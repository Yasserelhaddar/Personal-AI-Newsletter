"""Unified error handling utilities for the Personal AI Newsletter system."""

import functools
import logging
from typing import Any, Callable, Optional, Dict, TypeVar, cast

from src.models.state import NewsletterGenerationState, ProcessingStage, ErrorSeverity, add_error

F = TypeVar('F', bound=Callable[..., Any])
logger = logging.getLogger(__name__)


def handle_agent_errors(
    stage: ProcessingStage,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    error_code: Optional[str] = None,
    fallback_return: Any = None,
    log_level: str = "error"
) -> Callable[[F], F]:
    """
    Decorator for unified error handling in agent functions.
    
    Args:
        stage: The processing stage where the error occurred
        severity: Error severity level
        error_code: Optional error code for categorization
        fallback_return: Value to return if an error occurs
        log_level: Logging level ('error', 'warning', 'info')
        
    Usage:
        @handle_agent_errors(ProcessingStage.COLLECTION, ErrorSeverity.HIGH, "COLLECTION_FAILED")
        async def collect_content(state: NewsletterGenerationState) -> NewsletterGenerationState:
            # Agent logic here
            return state
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract state from arguments (assumes first arg is state)
            state = None
            if args and isinstance(args[0], dict):
                state = args[0]
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_message = f"Error in {func.__name__}: {str(e)}"
                
                # Log the error
                log_func = getattr(logger, log_level, logger.error)
                log_func(error_message, exc_info=True)
                
                # Add error to state if available
                if state is not None:
                    add_error(
                        state,
                        stage,
                        error_message,
                        severity,
                        error_code,
                        {"function": func.__name__, "exception_type": type(e).__name__}
                    )
                
                # Return fallback value or re-raise
                if fallback_return is not None:
                    return fallback_return
                else:
                    return state if state is not None else None
                    
        return cast(F, wrapper)
    return decorator


def handle_service_errors(
    service_name: str,
    log_level: str = "error",
    reraise: bool = True
) -> Callable[[F], F]:
    """
    Decorator for service-level error handling without state dependency.
    
    Args:
        service_name: Name of the service for logging context
        log_level: Logging level ('error', 'warning', 'info')
        reraise: Whether to re-raise the exception after logging
        
    Usage:
        @handle_service_errors("OpenAI Service")
        async def analyze_content(self, content: str) -> dict:
            # Service logic here
            return result
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_message = f"Error in {service_name}.{func.__name__}: {str(e)}"
                
                # Log the error
                log_func = getattr(logger, log_level, logger.error)
                log_func(error_message, exc_info=True)
                
                if reraise:
                    raise
                return None
                    
        return cast(F, wrapper)
    return decorator


class ErrorContext:
    """Context manager for error handling with automatic state updates."""
    
    def __init__(
        self,
        state: NewsletterGenerationState,
        stage: ProcessingStage,
        operation: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        error_code: Optional[str] = None
    ):
        self.state = state
        self.stage = stage
        self.operation = operation
        self.severity = severity
        self.error_code = error_code
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            error_message = f"Error during {self.operation}: {str(exc_val)}"
            logger.error(error_message, exc_info=True)
            
            add_error(
                self.state,
                self.stage,
                error_message,
                self.severity,
                self.error_code,
                {
                    "operation": self.operation,
                    "exception_type": exc_type.__name__ if exc_type else None
                }
            )
            
        # Don't suppress the exception
        return False