"""Base MCP client implementation with common patterns."""

import asyncio
import json
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import structlog

from src.infrastructure.config import MCPServerConfig

logger = structlog.get_logger(__name__)


class MCPClientError(Exception):
    """Base exception for MCP client errors."""

    def __init__(self, message: str, error_code: Optional[str] = None, details: Optional[Dict] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}


class CircuitBreakerError(MCPClientError):
    """Raised when circuit breaker is open."""
    pass


@dataclass
class CircuitBreaker:
    """Simple circuit breaker implementation for MCP client reliability."""

    failure_threshold: int = 5
    timeout: float = 60.0
    half_open_max_calls: int = 3

    def __post_init__(self):
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "closed"  # closed, open, half_open
        self.half_open_calls = 0

    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        if self.state == "closed":
            return True

        if self.state == "open":
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = "half_open"
                self.half_open_calls = 0
                return True
            return False

        if self.state == "half_open":
            return self.half_open_calls < self.half_open_max_calls

        return False

    def record_success(self) -> None:
        """Record successful execution."""
        if self.state == "half_open":
            self.state = "closed"
        self.failure_count = 0
        self.half_open_calls = 0

    def record_failure(self) -> None:
        """Record failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == "closed" and self.failure_count >= self.failure_threshold:
            self.state = "open"
        elif self.state == "half_open":
            self.state = "open"

        if self.state == "half_open":
            self.half_open_calls += 1


class BaseMCPClient(ABC):
    """Base class for all MCP clients with common functionality."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.circuit_breaker = CircuitBreaker()
        self.process: Optional[subprocess.Popen] = None
        self.is_connected = False
        self.logger = logger.bind(mcp_server=config.name)

    async def connect(self) -> None:
        """Connect to the MCP server."""
        if not self.circuit_breaker.can_execute():
            raise CircuitBreakerError(f"Circuit breaker open for {self.config.name}")

        try:
            self.logger.info("Connecting to MCP server", command=self.config.command)

            # Start the MCP server process
            import os
            env = os.environ.copy()  # Inherit system environment including PATH
            if self.config.env:
                env.update(self.config.env)  # Add MCP-specific environment variables

            self.process = subprocess.Popen(
                [self.config.command] + self.config.args,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait a moment for the process to start
            await asyncio.sleep(1)

            # Check if process is still running
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise MCPClientError(
                    f"MCP server {self.config.name} failed to start: {stderr}",
                    error_code="START_FAILED"
                )

            await self._initialize_connection()
            self.is_connected = True
            self.circuit_breaker.record_success()

            self.logger.info("Successfully connected to MCP server")

        except Exception as e:
            self.circuit_breaker.record_failure()
            self.logger.error("Failed to connect to MCP server", error=str(e))
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self.process:
            try:
                self.process.terminate()
                # Give it a moment to terminate gracefully
                await asyncio.sleep(1)
                if self.process.poll() is None:
                    self.process.kill()
            except Exception as e:
                self.logger.warning("Error during process cleanup", error=str(e))
            finally:
                self.process = None

        self.is_connected = False
        self.logger.info("Disconnected from MCP server")

    async def execute_with_retry(
        self,
        operation: str,
        data: Dict[str, Any],
        max_retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute an operation with retry logic and circuit breaker."""
        if not self.circuit_breaker.can_execute():
            raise CircuitBreakerError(f"Circuit breaker open for {self.config.name}")

        max_retries = max_retries or self.config.retry_attempts
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if not self.is_connected:
                    await self.connect()

                result = await self._execute_operation(operation, data)
                self.circuit_breaker.record_success()
                return result

            except Exception as e:
                last_error = e
                self.logger.warning(
                    "Operation failed",
                    operation=operation,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                )

                if attempt < max_retries:
                    # Exponential backoff
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                    # Reconnect on next attempt
                    await self.disconnect()

        # All retries exhausted
        self.circuit_breaker.record_failure()
        raise MCPClientError(
            f"Operation {operation} failed after {max_retries + 1} attempts: {str(last_error)}",
            error_code="MAX_RETRIES_EXCEEDED",
            details={"operation": operation, "last_error": str(last_error)}
        )

    @abstractmethod
    async def _initialize_connection(self) -> None:
        """Initialize the connection to the MCP server."""
        pass

    @abstractmethod
    async def _execute_operation(self, operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific operation on the MCP server."""
        pass

    async def health_check(self) -> bool:
        """Check if the MCP server is healthy."""
        try:
            if not self.is_connected:
                return False

            # Try a simple operation to verify health
            await self._health_check_operation()
            return True

        except Exception as e:
            self.logger.warning("Health check failed", error=str(e))
            return False

    @abstractmethod
    async def _health_check_operation(self) -> None:
        """Perform a health check specific to this MCP server."""
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


class JSONRPCMCPClient(BaseMCPClient):
    """Base class for MCP clients using JSON-RPC communication."""

    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self.request_id = 0

    def _create_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a JSON-RPC request."""
        self.request_id += 1
        return {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params,
        }

    def _create_tool_call_request(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a tool call request using MCP tools/call method."""
        self.request_id += 1
        return {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

    async def _send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request and get response."""
        if not self.process or not self.process.stdin:
            raise MCPClientError("No active connection to MCP server")

        try:
            # Send request
            request_json = json.dumps(request) + "\n"
            self.process.stdin.write(request_json)
            self.process.stdin.flush()

            # Read response
            response_line = await self._read_response_line()
            response = json.loads(response_line)

            # Check for JSON-RPC errors
            if "error" in response:
                error = response["error"]
                raise MCPClientError(
                    error.get("message", "Unknown error"),
                    error_code=str(error.get("code", "UNKNOWN")),
                    details=error.get("data", {})
                )

            return response.get("result", {})

        except json.JSONDecodeError as e:
            raise MCPClientError(f"Invalid JSON response: {e}")
        except Exception as e:
            raise MCPClientError(f"Communication error: {e}")

    async def _read_response_line(self) -> str:
        """Read a response line from the MCP server."""
        if not self.process or not self.process.stdout:
            raise MCPClientError("No active connection to MCP server")

        # In a real implementation, this would be async
        # For now, using a simple synchronous read
        try:
            line = self.process.stdout.readline()
            if not line:
                raise MCPClientError("Connection closed by server")
            return line.strip()
        except Exception as e:
            raise MCPClientError(f"Failed to read response: {e}")

    async def _initialize_connection(self) -> None:
        """Initialize JSON-RPC connection."""
        # Send initialization request
        init_request = self._create_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "personal-ai-newsletter",
                "version": "0.1.0",
            },
        })

        response = await self._send_request(init_request)
        self.logger.info("MCP server initialized", capabilities=response.get("capabilities", {}))

    async def _health_check_operation(self) -> None:
        """Basic health check using list_resources."""
        request = self._create_request("resources/list", {})
        await self._send_request(request)