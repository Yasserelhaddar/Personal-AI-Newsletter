"""AI curation agent for the newsletter workflow."""

from src.infrastructure.logging import get_logger
from src.services.openai_service import OpenAIService
from src.models.state import (
    NewsletterGenerationState,
    ProcessingStage,
    ErrorSeverity,
    add_error,
)
from src.services.curation import CurationEngine

logger = get_logger(__name__)


async def curate_with_ai(state: NewsletterGenerationState) -> NewsletterGenerationState:
    """Curate newsletter content using AI analysis.

    Args:
        state: Current workflow state

    Returns:
        Updated workflow state with curated newsletter
    """
    logger.info(
        "Starting AI content curation",
        user_id=state["user_profile"].user_id,
        content_count=len(state["raw_content"]),
    )

    # Mark curation stage start
    state["generation_metadata"].mark_stage_start(ProcessingStage.CURATION)

    try:
        # Initialize OpenAI service
        openai_service = OpenAIService()

        if openai_service.available:
            logger.info("OpenAI service available for intelligent curation")
        else:
            logger.warning("OpenAI service not available, using fallback curation")
            add_error(
                state,
                ProcessingStage.CURATION,
                "OpenAI API key not configured, using fallback curation",
                ErrorSeverity.MEDIUM,
                "AI_SERVICE_UNAVAILABLE",
            )

        # Create curation engine with OpenAI service
        curation_engine = CurationEngine(openai_service)

        # Perform AI curation
        try:
            curated_newsletter = await curation_engine.curate_newsletter(
                raw_content=state["raw_content"],
                user_profile=state["user_profile"],
                github_activity=state["workflow_context"].get("github_activity"),
            )

            state["curated_newsletter"] = curated_newsletter
            state["generation_metadata"].content_after_curation = curated_newsletter.total_articles
            state["generation_metadata"].ai_analysis_steps += 1

            # Update workflow context with curation metadata
            state["workflow_context"]["curation_metadata"] = curated_newsletter.generation_metadata

            logger.info(
                "AI curation completed",
                user_id=state["user_profile"].user_id,
                articles_selected=curated_newsletter.total_articles,
                sections_count=len(curated_newsletter.sections),
                insights_count=len(curated_newsletter.personalized_insights),
                fallback_mode=curated_newsletter.generation_metadata.get("fallback_mode", False),
            )

        except Exception as e:
            add_error(
                state,
                ProcessingStage.CURATION,
                f"AI curation failed: {str(e)}",
                ErrorSeverity.HIGH,
                "AI_CURATION_FAILED",
            )

            # Try fallback curation
            try:
                logger.warning(
                    "Attempting fallback curation",
                    user_id=state["user_profile"].user_id,
                )

                fallback_newsletter = await curation_engine._create_fallback_newsletter(
                    state["raw_content"],
                    state["user_profile"],
                )

                state["curated_newsletter"] = fallback_newsletter
                state["generation_metadata"].content_after_curation = fallback_newsletter.total_articles
                state["warnings"].append("Used fallback curation due to AI failure")

                logger.info(
                    "Fallback curation completed",
                    user_id=state["user_profile"].user_id,
                    articles_selected=fallback_newsletter.total_articles,
                )

            except Exception as fallback_error:
                add_error(
                    state,
                    ProcessingStage.CURATION,
                    f"Fallback curation also failed: {str(fallback_error)}",
                    ErrorSeverity.CRITICAL,
                    "FALLBACK_CURATION_FAILED",
                )

        finally:
            # No cleanup needed for OpenAI service (stateless HTTP API)
            pass

        # Validate curation results
        if not state["curated_newsletter"]:
            add_error(
                state,
                ProcessingStage.CURATION,
                "No curated newsletter was produced",
                ErrorSeverity.CRITICAL,
                "NO_CURATED_CONTENT",
            )
        elif state["curated_newsletter"].total_articles == 0:
            add_error(
                state,
                ProcessingStage.CURATION,
                "Curated newsletter contains no articles",
                ErrorSeverity.HIGH,
                "EMPTY_NEWSLETTER",
            )

        # Mark curation stage complete
        state["generation_metadata"].mark_stage_end(ProcessingStage.CURATION)

        return state

    except Exception as e:
        add_error(
            state,
            ProcessingStage.CURATION,
            f"Curation agent failed: {str(e)}",
            ErrorSeverity.CRITICAL,
            "CURATION_AGENT_ERROR",
        )

        logger.error(
            "AI curation agent failed",
            user_id=state["user_profile"].user_id,
            error=str(e),
            exc_info=True,
        )

        return state