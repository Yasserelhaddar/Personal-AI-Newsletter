"""Analytics update agent for the newsletter workflow."""

from src.infrastructure.logging import get_logger
from src.models.state import (
    NewsletterGenerationState,
    ProcessingStage,
    ErrorSeverity,
    add_error,
)

logger = get_logger(__name__)


async def update_user_analytics(state: NewsletterGenerationState) -> NewsletterGenerationState:
    """Update user analytics and learning data.

    Args:
        state: Current workflow state

    Returns:
        Updated workflow state with analytics
    """
    logger.info(
        "Updating user analytics",
        user_id=state["user_profile"].user_id,
        delivery_success=state["delivery_result"].success if state["delivery_result"] else False,
    )

    # Mark analytics stage start
    state["generation_metadata"].mark_stage_start(ProcessingStage.ANALYTICS)

    try:
        # Update user's newsletter history
        user_profile = state["user_profile"]
        user_profile.total_newsletters_sent += 1
        user_profile.last_newsletter_sent = state["generation_metadata"].start_time

        # Update analytics metadata
        analytics_data = {
            "generation_completed": True,
            "processing_time": state["generation_metadata"].total_processing_time,
            "content_collected": state["generation_metadata"].total_content_collected,
            "content_curated": state["generation_metadata"].content_after_curation,
            "ai_analysis_used": state["generation_metadata"].ai_analysis_steps > 0,
            "delivery_success": state["delivery_result"].success if state["delivery_result"] else False,
            "errors_count": len(state["errors"]),
            "warnings_count": len(state["warnings"]),
        }

        # Store analytics in workflow context
        state["workflow_context"]["analytics"] = analytics_data

        # Log performance metrics
        logger.info(
            "Analytics updated",
            user_id=user_profile.user_id,
            total_newsletters=user_profile.total_newsletters_sent,
            processing_time=analytics_data["processing_time"],
            delivery_success=analytics_data["delivery_success"],
        )

        # Mark analytics stage complete
        state["generation_metadata"].mark_stage_end(ProcessingStage.ANALYTICS)

        return state

    except Exception as e:
        add_error(
            state,
            ProcessingStage.ANALYTICS,
            f"Analytics update failed: {str(e)}",
            ErrorSeverity.MEDIUM,
            "ANALYTICS_UPDATE_FAILED",
        )

        logger.warning(
            "Analytics update failed",
            user_id=state["user_profile"].user_id,
            error=str(e),
        )

        return state