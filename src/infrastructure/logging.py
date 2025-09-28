"""Logging configuration for the Personal AI Newsletter Generator."""

import logging
import logging.config
import sys
from pathlib import Path
from typing import Dict, Any

import structlog
from rich.logging import RichHandler

from src.infrastructure.config import get_logs_dir


def setup_logging(
    level: str = "INFO",
    format_type: str = "structured",
    log_file: bool = True,
) -> structlog.stdlib.BoundLogger:
    """Set up structured logging with rich console output.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: Log format type ("structured" or "text")
        log_file: Whether to log to file

    Returns:
        Configured structlog logger
    """
    log_level = getattr(logging, level.upper())

    # Configure timestamper
    timestamper = structlog.processors.TimeStamper(fmt="ISO")

    # Shared processors
    shared_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if format_type == "structured":
        # Structured JSON logging
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        # Human-readable text logging
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(colors=True)
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    # Configure standard library logging
    handlers = []

    # Rich console handler for beautiful terminal output
    if format_type == "text":
        rich_handler = RichHandler(
            rich_tracebacks=True,
            show_path=False,
            show_time=False,  # We add timestamp in processors
        )
        rich_handler.setLevel(log_level)
        handlers.append(rich_handler)
    else:
        # Simple console handler for structured logs
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        handlers.append(console_handler)

    # File handler for persistent logging
    if log_file:
        logs_dir = get_logs_dir()
        log_file_path = logs_dir / "newsletter.log"

        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file

        # Use JSON format for file logs
        if format_type == "structured":
            file_formatter = logging.Formatter('%(message)s')
        else:
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(message)s",
    )

    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Return structlog logger
    logger = structlog.get_logger("newsletter")
    logger.info("Logging configured", level=level, format=format_type)

    return logger


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


class LoggerMixin:
    """Mixin class to add logger to any class."""

    @property
    def logger(self) -> structlog.stdlib.BoundLogger:
        """Get logger instance for this class."""
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__name__)
        return self._logger