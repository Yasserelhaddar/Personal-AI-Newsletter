"""Notification service with Resend MCP integration."""

from datetime import datetime, timezone
from typing import Optional

from src.infrastructure.logging import LoggerMixin
from src.infrastructure.mcp_clients import ResendClient
from src.models.email import EmailContent
from src.models.user import UserProfile, DeliveryResult, DeliveryStatus


class NotificationService(LoggerMixin):
    """Service for email delivery with tracking and analytics."""

    def __init__(self, resend_client: ResendClient):
        self.resend_client = resend_client

    async def send_newsletter(
        self,
        email_content: EmailContent,
        user_profile: UserProfile,
        generation_id: Optional[str] = None,
    ) -> DeliveryResult:
        """Send newsletter email to user.

        Args:
            email_content: Complete email content
            user_profile: Recipient user profile
            generation_id: Optional generation ID for tracking

        Returns:
            Delivery result with success status and tracking info
        """
        self.logger.info(
            "Sending newsletter",
            user_id=user_profile.user_id,
            email=user_profile.email,
            subject=email_content.subject,
            generation_id=generation_id,
        )

        try:
            # Validate email content
            if not self._validate_email_content(email_content):
                return DeliveryResult(
                    success=False,
                    status=DeliveryStatus.FAILED,
                    error_message="Email content validation failed",
                )

            # Send email via Resend
            delivery_result = await self.resend_client.send_newsletter(
                email_content, user_profile.email
            )

            # Log delivery result
            if delivery_result.success:
                self.logger.info(
                    "Newsletter sent successfully",
                    user_id=user_profile.user_id,
                    delivery_id=delivery_result.delivery_id,
                )
            else:
                self.logger.error(
                    "Newsletter delivery failed",
                    user_id=user_profile.user_id,
                    error=delivery_result.error_message,
                )

            return delivery_result

        except Exception as e:
            self.logger.error(
                "Newsletter sending failed",
                user_id=user_profile.user_id,
                error=str(e),
                exc_info=True,
            )

            return DeliveryResult(
                success=False,
                status=DeliveryStatus.FAILED,
                error_message=str(e),
            )

    def _validate_email_content(self, email_content: EmailContent) -> bool:
        """Validate email content before sending."""
        if not email_content.html:
            self.logger.warning("Email content missing HTML")
            return False

        if not email_content.text:
            self.logger.warning("Email content missing text version")
            return False

        if not email_content.subject:
            self.logger.warning("Email content missing subject")
            return False

        if len(email_content.subject) > 998:
            self.logger.warning("Email subject too long")
            return False

        if email_content.estimated_size_kb > 10000:
            self.logger.warning("Email too large")
            return False

        return True

    async def get_delivery_status(self, delivery_id: str) -> Optional[dict]:
        """Get delivery status from Resend."""
        try:
            return await self.resend_client.get_email_status(delivery_id)
        except Exception as e:
            self.logger.error("Failed to get delivery status", delivery_id=delivery_id, error=str(e))
            return None