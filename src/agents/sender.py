"""Email sending agent for the newsletter workflow."""

from src.infrastructure.config import load_mcp_config
from src.infrastructure.logging import get_logger
from src.infrastructure.mcp_clients import ResendClient
from src.models.state import (
    NewsletterGenerationState,
    ProcessingStage,
    ErrorSeverity,
    add_error,
)
from src.services.notification import NotificationService

logger = get_logger(__name__)


async def send_with_tracking(state: NewsletterGenerationState) -> NewsletterGenerationState:
    """Send newsletter email with delivery tracking.

    Args:
        state: Current workflow state

    Returns:
        Updated workflow state with delivery results
    """
    user_id = state["user_profile"].user_id
    dry_run = state["generation_request"].dry_run

    logger.info(
        "Starting email delivery",
        user_id=user_id,
        dry_run=dry_run,
        subject=state["email_content"].subject if state["email_content"] else "Unknown",
    )

    # Mark delivery stage start
    state["generation_metadata"].mark_stage_start(ProcessingStage.DELIVERY)

    try:
        # Handle dry run mode
        if dry_run:
            from src.models.user import DeliveryResult, DeliveryStatus

            state["delivery_result"] = DeliveryResult(
                success=True,
                status=DeliveryStatus.SENT,
                delivery_id="dry-run-" + state["generation_metadata"].generation_id,
                metadata={
                    "dry_run": True,
                    "user_id": user_id,
                    "email_size_kb": state["email_content"].estimated_size_kb,
                },
            )

            logger.info(
                "Dry run email delivery completed",
                user_id=user_id,
                generation_id=state["generation_metadata"].generation_id,
            )

            # Mark delivery stage complete
            state["generation_metadata"].mark_stage_end(ProcessingStage.DELIVERY)
            return state

        # Initialize Resend MCP client for actual sending
        mcp_config = load_mcp_config()
        resend_client = ResendClient(mcp_config["resend"])

        # Create notification service
        notification_service = NotificationService(resend_client)

        # Connect to Resend MCP
        try:
            await resend_client.connect()
        except Exception as e:
            add_error(
                state,
                ProcessingStage.DELIVERY,
                f"Failed to connect to Resend MCP: {str(e)}",
                ErrorSeverity.HIGH,
                "RESEND_CONNECTION_FAILED",
            )

        # Send the newsletter
        try:
            delivery_result = await notification_service.send_newsletter(
                email_content=state["email_content"],
                user_profile=state["user_profile"],
                generation_id=state["generation_metadata"].generation_id,
            )

            state["delivery_result"] = delivery_result

            if delivery_result.success:
                logger.info(
                    "Newsletter delivered successfully",
                    user_id=user_id,
                    delivery_id=delivery_result.delivery_id,
                    recipient=state["user_profile"].email,
                )
            else:
                add_error(
                    state,
                    ProcessingStage.DELIVERY,
                    f"Email delivery failed: {delivery_result.error_message}",
                    ErrorSeverity.HIGH,
                    "DELIVERY_FAILED",
                )

        except Exception as e:
            add_error(
                state,
                ProcessingStage.DELIVERY,
                f"Email sending failed: {str(e)}",
                ErrorSeverity.HIGH,
                "SENDING_FAILED",
            )

            # Create failed delivery result
            from src.models.user import DeliveryResult, DeliveryStatus

            state["delivery_result"] = DeliveryResult(
                success=False,
                status=DeliveryStatus.FAILED,
                error_message=str(e),
                metadata={"user_id": user_id},
            )

        finally:
            # Clean up MCP connection
            try:
                await resend_client.disconnect()
            except Exception as e:
                logger.warning("Error during Resend MCP cleanup", error=str(e))

        # Validate delivery results
        if not state["delivery_result"]:
            add_error(
                state,
                ProcessingStage.DELIVERY,
                "No delivery result was recorded",
                ErrorSeverity.CRITICAL,
                "NO_DELIVERY_RESULT",
            )

        # Mark delivery stage complete
        state["generation_metadata"].mark_stage_end(ProcessingStage.DELIVERY)

        return state

    except Exception as e:
        add_error(
            state,
            ProcessingStage.DELIVERY,
            f"Email sending agent failed: {str(e)}",
            ErrorSeverity.CRITICAL,
            "SENDER_AGENT_ERROR",
        )

        logger.error(
            "Email sending agent failed",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )

        return state