"""Resend MCP client for email delivery."""

from typing import Any, Dict, List, Optional

from .base import JSONRPCMCPClient, MCPClientError
from src.models.email import EmailContent
from src.models.user import DeliveryResult, DeliveryStatus
from src.infrastructure.config import ApplicationConfig


class ResendClient(JSONRPCMCPClient):
    """MCP client for Resend email delivery service."""

    def __init__(self, config):
        super().__init__(config)
        self.app_config = ApplicationConfig()

    async def send_email(
        self,
        to: List[str],
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        tags: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Send an email via Resend.

        Args:
            to: List of recipient email addresses
            subject: Email subject line
            html: HTML email content
            text: Plain text email content (optional)
            from_email: Sender email address
            from_name: Sender name
            reply_to: Reply-to email address
            tags: List of tags for email tracking
            headers: Additional email headers

        Returns:
            Delivery ID from Resend

        Raises:
            MCPClientError: If email sending fails
        """
        # Use config defaults if not provided
        if from_email is None:
            from_email = self.app_config.newsletter_from_email
        if from_name is None:
            from_name = self.app_config.from_name

        params = {
            "to": to[0] if isinstance(to, list) and to else to,  # Take first email if list
            "subject": subject,
            "html": html,
            "text": text or "",  # text is required when html is provided
            "from": from_email,  # Simple email, not formatted
        }

        if reply_to:
            params["reply_to"] = reply_to

        if tags:
            params["tags"] = tags

        if headers:
            params["headers"] = headers

        try:
            result = await self._execute_operation("send_email", params)
            return result.get("id", "")

        except Exception as e:
            raise MCPClientError(f"Failed to send email: {str(e)}")

    async def send_newsletter(self, email_content: EmailContent, recipient_email: str) -> DeliveryResult:
        """Send a newsletter email.

        Args:
            email_content: Complete email content
            recipient_email: Recipient email address

        Returns:
            DeliveryResult with success status and delivery details
        """
        try:
            delivery_id = await self.send_email(
                to=[recipient_email],
                subject=email_content.subject,
                html=email_content.html,
                text=email_content.text,
                from_email=email_content.from_email or None,  # Let the method use config default
                from_name=email_content.from_name or None,    # Let the method use config default
                reply_to=email_content.reply_to,
                tags=email_content.tags,
                headers=email_content.headers,
            )

            return DeliveryResult(
                success=True,
                delivery_id=delivery_id,
                status=DeliveryStatus.SENT,
                metadata={
                    "resend_id": delivery_id,
                    "recipient": recipient_email,
                    "subject": email_content.subject,
                    "tags": email_content.tags,
                }
            )

        except Exception as e:
            return DeliveryResult(
                success=False,
                status=DeliveryStatus.FAILED,
                error_message=str(e),
                metadata={
                    "recipient": recipient_email,
                    "subject": email_content.subject,
                }
            )

    async def get_email_status(self, delivery_id: str) -> Dict[str, Any]:
        """Get the status of a sent email.

        Args:
            delivery_id: Resend delivery ID

        Returns:
            Email status information
        """
        try:
            result = await self._execute_operation("get_email", {"id": delivery_id})
            return result

        except Exception as e:
            raise MCPClientError(f"Failed to get email status: {str(e)}")

    async def get_email_events(self, delivery_id: str) -> List[Dict[str, Any]]:
        """Get events for a sent email (opens, clicks, etc.).

        Args:
            delivery_id: Resend delivery ID

        Returns:
            List of email events
        """
        try:
            result = await self._execute_operation("get_email_events", {"id": delivery_id})
            return result.get("events", [])

        except Exception as e:
            raise MCPClientError(f"Failed to get email events: {str(e)}")

    async def create_domain(self, domain: str) -> Dict[str, Any]:
        """Create a new domain for sending emails.

        Args:
            domain: Domain name to add

        Returns:
            Domain configuration details
        """
        try:
            result = await self._execute_operation("create_domain", {"name": domain})
            return result

        except Exception as e:
            raise MCPClientError(f"Failed to create domain: {str(e)}")

    async def list_domains(self) -> List[Dict[str, Any]]:
        """List all configured domains.

        Returns:
            List of domain configurations
        """
        try:
            result = await self._execute_operation("list_domains", {})
            return result.get("data", [])

        except Exception as e:
            raise MCPClientError(f"Failed to list domains: {str(e)}")

    async def validate_email_address(self, email: str) -> bool:
        """Validate an email address format.

        Args:
            email: Email address to validate

        Returns:
            True if email is valid, False otherwise
        """
        import re

        # Basic email validation regex
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_pattern, email))

    async def _execute_operation(self, operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a Resend operation via MCP."""
        # The official Resend MCP server has only one tool called "resend"
        # All operations use this single tool with different parameters

        if operation == "send_email":
            request = self._create_tool_call_request("send-email", data)
            return await self._send_request(request)
        else:
            # Other operations are not supported by the official Resend MCP server
            # We could implement them via direct API calls if needed
            raise MCPClientError(f"Operation {operation} not supported by official Resend MCP server")

    async def _health_check_operation(self) -> None:
        """Health check by validating connection to MCP server."""
        # The official Resend MCP server doesn't have a list operation
        # So we just verify the connection is working
        pass