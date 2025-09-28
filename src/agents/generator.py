"""Email generation agent for the newsletter workflow."""

from src.infrastructure.logging import get_logger
from src.models.state import (
    NewsletterGenerationState,
    ProcessingStage,
    ErrorSeverity,
    add_error,
)
from src.services.email_generation import EmailGenerationService

logger = get_logger(__name__)


async def generate_responsive_email(state: NewsletterGenerationState) -> NewsletterGenerationState:
    """Generate responsive HTML email from curated newsletter.

    Args:
        state: Current workflow state

    Returns:
        Updated workflow state with generated email content
    """
    logger.info(
        "Starting email generation",
        user_id=state["user_profile"].user_id,
        newsletter_articles=state["curated_newsletter"].total_articles if state["curated_newsletter"] else 0,
    )

    # Mark generation stage start
    state["generation_metadata"].mark_stage_start(ProcessingStage.GENERATION)

    try:
        # Create email generation service
        email_service = EmailGenerationService()

        # Generate email content
        try:
            email_content = await email_service.generate_newsletter_email(
                newsletter=state["curated_newsletter"],
                user_profile=state["user_profile"],
                tracking_data={
                    "generation_id": state["generation_metadata"].generation_id,
                    "user_id": state["user_profile"].user_id,
                },
            )

            state["email_content"] = email_content

            # Validate email content
            if email_service.validate_email_content(email_content):
                logger.info(
                    "Email generation completed successfully",
                    user_id=state["user_profile"].user_id,
                    email_size_kb=email_content.estimated_size_kb,
                    subject=email_content.subject,
                )
            else:
                state["warnings"].append("Email content validation warnings detected")

        except Exception as e:
            add_error(
                state,
                ProcessingStage.GENERATION,
                f"Email generation failed: {str(e)}",
                ErrorSeverity.HIGH,
                "EMAIL_GENERATION_FAILED",
            )

            # Try generating a test email as fallback
            try:
                logger.warning(
                    "Attempting fallback email generation",
                    user_id=state["user_profile"].user_id,
                )

                fallback_email = await email_service.generate_test_email(
                    state["user_profile"]
                )

                state["email_content"] = fallback_email
                state["warnings"].append("Used fallback email generation")

                logger.info(
                    "Fallback email generation completed",
                    user_id=state["user_profile"].user_id,
                )

            except Exception as fallback_error:
                add_error(
                    state,
                    ProcessingStage.GENERATION,
                    f"Fallback email generation also failed: {str(fallback_error)}",
                    ErrorSeverity.CRITICAL,
                    "FALLBACK_EMAIL_FAILED",
                )

        # Validate generation results
        if not state["email_content"]:
            add_error(
                state,
                ProcessingStage.GENERATION,
                "No email content was generated",
                ErrorSeverity.CRITICAL,
                "NO_EMAIL_CONTENT",
            )

        # Mark generation stage complete
        state["generation_metadata"].mark_stage_end(ProcessingStage.GENERATION)

        return state

    except Exception as e:
        add_error(
            state,
            ProcessingStage.GENERATION,
            f"Email generation agent failed: {str(e)}",
            ErrorSeverity.CRITICAL,
            "GENERATION_AGENT_ERROR",
        )

        logger.error(
            "Email generation agent failed",
            user_id=state["user_profile"].user_id,
            error=str(e),
            exc_info=True,
        )

        return state