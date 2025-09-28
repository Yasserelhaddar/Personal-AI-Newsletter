"""Content collection agent for the newsletter workflow."""

from src.infrastructure.config import load_mcp_config
from src.infrastructure.logging import get_logger
from src.infrastructure.error_handling import handle_agent_errors, ErrorContext
from src.infrastructure.api_clients import FirecrawlAPIClient
from src.infrastructure.mcp_clients import GitHubClient
from src.models.state import (
    NewsletterGenerationState,
    ProcessingStage,
    ErrorSeverity,
    add_error,
)
from src.services.content_collection import ContentCollectionService

logger = get_logger(__name__)


@handle_agent_errors(ProcessingStage.COLLECTION, ErrorSeverity.CRITICAL, "COLLECTION_AGENT_ERROR")
async def collect_content_parallel(state: NewsletterGenerationState) -> NewsletterGenerationState:
    """Collect content from multiple sources in parallel.

    Args:
        state: Current workflow state

    Returns:
        Updated workflow state with collected content
    """
    logger.info(
        "Starting content collection",
        user_id=state["user_profile"].user_id,
        interests=state["user_profile"].interests,
    )

    # Mark collection stage start
    state["generation_metadata"].mark_stage_start(ProcessingStage.COLLECTION)

    # Initialize API clients
        mcp_config = load_mcp_config()

        # Initialize Firecrawl API client (no MCP needed)
        firecrawl_client = None
        async with ErrorContext(state, ProcessingStage.COLLECTION, "Firecrawl API client initialization", ErrorSeverity.MEDIUM, "FIRECRAWL_INIT_FAILED"):
            firecrawl_client = FirecrawlAPIClient()
            logger.info("Firecrawl API client initialized successfully")

        # Initialize GitHub MCP client
        github_client = GitHubClient(mcp_config["github"])
        connected_github = None

        async with ErrorContext(state, ProcessingStage.COLLECTION, "GitHub MCP client connection", ErrorSeverity.MEDIUM, "GITHUB_CONNECTION_FAILED"):
            await github_client.connect()
            connected_github = github_client
            logger.info("Successfully connected to GitHub MCP server")

        # Create content collection service with initialized clients
        content_service = ContentCollectionService(
            firecrawl_client=firecrawl_client,
            github_client=connected_github,
        )

        # Collect content for user
        max_items_per_source = min(
            state["user_profile"].max_articles * 2,  # Collect extra for curation
            20  # Reasonable limit per source
        )

        try:
            collected_content = await content_service.collect_content_for_user(
                state["user_profile"],
                max_items_per_source=max_items_per_source,
            )

            state["raw_content"] = collected_content
            state["generation_metadata"].total_content_collected = len(collected_content)

            # Collect user's GitHub activity if enabled and GitHub client is connected
            if (
                state["user_profile"].include_github_activity
                and state["user_profile"].github_username
                and connected_github is not None
            ):
                try:
                    github_activity = await connected_github.get_user_activity_summary(
                        state["user_profile"].github_username
                    )
                    state["workflow_context"]["github_activity"] = github_activity

                    logger.info(
                        "Collected GitHub activity",
                        user_id=state["user_profile"].user_id,
                        username=state["user_profile"].github_username,
                        repos_count=len(github_activity.get("recent_repositories", [])),
                    )

                except Exception as e:
                    state["warnings"].append(f"Failed to collect GitHub activity: {str(e)}")
                    logger.warning(
                        "GitHub activity collection failed",
                        user_id=state["user_profile"].user_id,
                        error=str(e),
                    )

        except Exception as e:
            add_error(
                state,
                ProcessingStage.COLLECTION,
                f"Content collection failed: {str(e)}",
                ErrorSeverity.HIGH,
                "CONTENT_COLLECTION_FAILED",
            )

        finally:
            # Clean up connections
            try:
                # Firecrawl API client doesn't need disconnect (no persistent connection)
                if connected_github:
                    await connected_github.disconnect()
            except Exception as e:
                logger.warning("Error during cleanup", error=str(e))

        # Validate collection results
        if not state["raw_content"]:
            add_error(
                state,
                ProcessingStage.COLLECTION,
                "No content was collected from any source",
                ErrorSeverity.HIGH,
                "NO_CONTENT_COLLECTED",
            )
        elif len(state["raw_content"]) < 3:
            state["warnings"].append(
                f"Only {len(state['raw_content'])} content items collected"
            )

        # Mark collection stage complete
        state["generation_metadata"].mark_stage_end(ProcessingStage.COLLECTION)

        logger.info(
            "Content collection completed",
            user_id=state["user_profile"].user_id,
            content_count=len(state["raw_content"]),
            sources=list(set(item.source for item in state["raw_content"])),
        )

        return state