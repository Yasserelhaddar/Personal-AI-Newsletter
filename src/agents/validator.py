"""Input validation agent for the newsletter workflow."""

from src.infrastructure.logging import get_logger
from src.models.state import (
    NewsletterGenerationState,
    ProcessingStage,
    ErrorSeverity,
    add_error,
)

logger = get_logger(__name__)


async def validate_user_input(state: NewsletterGenerationState) -> NewsletterGenerationState:
    """Validate user input and configuration before processing.

    Args:
        state: Current workflow state

    Returns:
        Updated workflow state with validation results
    """
    logger.info(
        "Validating user input",
        user_id=state["user_profile"].user_id,
        generation_id=state["generation_metadata"].generation_id,
    )

    # Mark validation stage start
    state["generation_metadata"].mark_stage_start(ProcessingStage.VALIDATION)

    try:
        # Validate user profile
        user_profile = state["user_profile"]

        if not user_profile.email:
            add_error(
                state,
                ProcessingStage.VALIDATION,
                "User email is required",
                ErrorSeverity.CRITICAL,
                "MISSING_EMAIL",
            )

        if not user_profile.interests:
            add_error(
                state,
                ProcessingStage.VALIDATION,
                "User must have at least one interest",
                ErrorSeverity.HIGH,
                "NO_INTERESTS",
            )

        if len(user_profile.interests) > 20:
            add_error(
                state,
                ProcessingStage.VALIDATION,
                "Too many interests (max 20)",
                ErrorSeverity.MEDIUM,
                "TOO_MANY_INTERESTS",
            )
            # Trim to first 20 interests
            user_profile.interests = user_profile.interests[:20]
            state["warnings"].append("Trimmed interests to 20 items")

        # Validate generation request
        generation_request = state["generation_request"]

        if generation_request.max_articles and generation_request.max_articles < 1:
            add_error(
                state,
                ProcessingStage.VALIDATION,
                "max_articles must be at least 1",
                ErrorSeverity.MEDIUM,
                "INVALID_MAX_ARTICLES",
            )

        if generation_request.max_articles and generation_request.max_articles > 50:
            state["warnings"].append("max_articles capped at 50")
            generation_request.max_articles = 50

        # Validate configuration consistency
        if (
            user_profile.include_github_activity
            and not user_profile.github_username
            and not generation_request.demo_mode
        ):
            state["warnings"].append(
                "GitHub activity requested but no username provided"
            )

        # Set processing metadata
        state["generation_metadata"].content_sources_used = []
        if "articles" in user_profile.content_types:
            state["generation_metadata"].content_sources_used.extend(
                ["hacker_news", "reddit"]
            )
        if "github" in user_profile.content_types or user_profile.include_github_activity:
            state["generation_metadata"].content_sources_used.append("github")

        # Mark validation stage complete
        state["generation_metadata"].mark_stage_end(ProcessingStage.VALIDATION)

        logger.info(
            "User input validation completed",
            user_id=user_profile.user_id,
            interests_count=len(user_profile.interests),
            content_sources=state["generation_metadata"].content_sources_used,
            warnings_count=len(state["warnings"]),
        )

        return state

    except Exception as e:
        add_error(
            state,
            ProcessingStage.VALIDATION,
            f"Validation failed: {str(e)}",
            ErrorSeverity.CRITICAL,
            "VALIDATION_ERROR",
        )

        logger.error(
            "Validation failed",
            user_id=state["user_profile"].user_id,
            error=str(e),
            exc_info=True,
        )

        return state