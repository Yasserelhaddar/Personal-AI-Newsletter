"""Main newsletter generation workflow using LangGraph."""

from datetime import datetime, timezone
from typing import Dict, Any

from langgraph.graph import StateGraph, START, END

from src.models.state import (
    NewsletterGenerationState,
    ProcessingStage,
    ErrorSeverity,
    add_error,
    create_initial_state,
    has_critical_errors,
)
from src.models.user import UserProfile
from src.models.state import GenerationRequest
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


def create_newsletter_workflow() -> StateGraph:
    """Create the complete newsletter generation workflow.

    Returns:
        Configured LangGraph StateGraph for newsletter generation
    """
    workflow = StateGraph(NewsletterGenerationState)

    # Import workflow nodes (avoiding circular imports)
    from src.agents.validator import validate_user_input
    from src.agents.collector import collect_content_parallel
    from src.agents.curator import curate_with_ai
    from src.agents.generator import generate_responsive_email
    from src.agents.sender import send_with_tracking
    from src.agents.analytics import update_user_analytics

    # Error handling nodes
    from src.agents.error_handlers import (
        handle_collection_error,
        handle_curation_error,
        handle_delivery_error,
        handle_critical_failure,
    )

    # Add workflow nodes
    workflow.add_node("validate_input", validate_user_input)
    workflow.add_node("collect_content", collect_content_parallel)
    workflow.add_node("curate_content", curate_with_ai)
    workflow.add_node("generate_email", generate_responsive_email)
    workflow.add_node("send_newsletter", send_with_tracking)
    workflow.add_node("update_analytics", update_user_analytics)

    # Error handling nodes
    workflow.add_node("handle_collection_error", handle_collection_error)
    workflow.add_node("handle_curation_error", handle_curation_error)
    workflow.add_node("handle_delivery_error", handle_delivery_error)
    workflow.add_node("handle_critical_failure", handle_critical_failure)

    # Define workflow edges with conditional routing
    workflow.add_edge(START, "validate_input")

    # From validation - proceed or fail
    workflow.add_conditional_edges(
        "validate_input",
        _route_after_validation,
        {
            "collect": "collect_content",
            "fail": "handle_critical_failure",
        }
    )

    # From collection - proceed or handle error
    workflow.add_conditional_edges(
        "collect_content",
        _route_after_collection,
        {
            "curate": "curate_content",
            "error": "handle_collection_error",
            "fail": "handle_critical_failure",
        }
    )

    # From collection error handling
    workflow.add_conditional_edges(
        "handle_collection_error",
        _route_after_collection_error,
        {
            "retry": "collect_content",
            "curate": "curate_content",
            "fail": "handle_critical_failure",
        }
    )

    # From curation - proceed or handle error
    workflow.add_conditional_edges(
        "curate_content",
        _route_after_curation,
        {
            "generate": "generate_email",
            "error": "handle_curation_error",
            "fail": "handle_critical_failure",
        }
    )

    # From curation error handling
    workflow.add_conditional_edges(
        "handle_curation_error",
        _route_after_curation_error,
        {
            "retry": "curate_content",
            "generate": "generate_email",
            "fail": "handle_critical_failure",
        }
    )

    # From generation - proceed to send
    workflow.add_conditional_edges(
        "generate_email",
        _route_after_generation,
        {
            "send": "send_newsletter",
            "fail": "handle_critical_failure",
        }
    )

    # From sending - proceed or handle error
    workflow.add_conditional_edges(
        "send_newsletter",
        _route_after_sending,
        {
            "analytics": "update_analytics",
            "error": "handle_delivery_error",
            "complete": END,
        }
    )

    # From delivery error handling
    workflow.add_conditional_edges(
        "handle_delivery_error",
        _route_after_delivery_error,
        {
            "retry": "send_newsletter",
            "complete": END,
        }
    )

    # Analytics always goes to end
    workflow.add_edge("update_analytics", END)
    workflow.add_edge("handle_critical_failure", END)

    return workflow


# Routing functions for conditional edges
def _route_after_validation(state: NewsletterGenerationState) -> str:
    """Route after input validation."""
    if has_critical_errors(state):
        return "fail"
    return "collect"


def _route_after_collection(state: NewsletterGenerationState) -> str:
    """Route after content collection."""
    if has_critical_errors(state):
        return "fail"

    if not state["raw_content"]:
        # No content collected - this is an error but not critical
        add_error(
            state,
            ProcessingStage.COLLECTION,
            "No content was collected from any source",
            ErrorSeverity.HIGH,
        )
        return "error"

    if len(state["raw_content"]) < 3:
        # Very little content - warning but proceed
        state["warnings"].append("Only collected a small amount of content")

    return "curate"


def _route_after_collection_error(state: NewsletterGenerationState) -> str:
    """Route after collection error handling."""
    if has_critical_errors(state):
        return "fail"

    # Check if error handler provided fallback content
    if state["raw_content"]:
        return "curate"

    # If still no content after error handling, this is critical
    add_error(
        state,
        ProcessingStage.COLLECTION,
        "Failed to collect content even after error handling",
        ErrorSeverity.CRITICAL,
    )
    return "fail"


def _route_after_curation(state: NewsletterGenerationState) -> str:
    """Route after content curation."""
    if has_critical_errors(state):
        return "fail"

    if not state["curated_newsletter"]:
        add_error(
            state,
            ProcessingStage.CURATION,
            "AI curation failed to produce newsletter content",
            ErrorSeverity.HIGH,
        )
        return "error"

    return "generate"


def _route_after_curation_error(state: NewsletterGenerationState) -> str:
    """Route after curation error handling."""
    if has_critical_errors(state):
        return "fail"

    # Check if error handler provided fallback content
    if state["curated_newsletter"]:
        return "generate"

    # If still no curated content, this is critical
    add_error(
        state,
        ProcessingStage.CURATION,
        "Failed to curate content even after error handling",
        ErrorSeverity.CRITICAL,
    )
    return "fail"


def _route_after_generation(state: NewsletterGenerationState) -> str:
    """Route after email generation."""
    if has_critical_errors(state) or not state["email_content"]:
        return "fail"
    return "send"


def _route_after_sending(state: NewsletterGenerationState) -> str:
    """Route after email sending."""
    # Check if we're in dry run mode
    if state["generation_request"].dry_run:
        return "complete"

    # Check delivery result
    delivery_result = state["delivery_result"]
    if not delivery_result:
        add_error(
            state,
            ProcessingStage.DELIVERY,
            "No delivery result received",
            ErrorSeverity.HIGH,
        )
        return "error"

    if delivery_result.success:
        return "analytics"
    else:
        add_error(
            state,
            ProcessingStage.DELIVERY,
            f"Email delivery failed: {delivery_result.error_message}",
            ErrorSeverity.HIGH,
        )
        return "error"


def _route_after_delivery_error(state: NewsletterGenerationState) -> str:
    """Route after delivery error handling."""
    # For now, always complete after delivery error handling
    # In the future, could implement retry logic here
    return "complete"


async def run_newsletter_generation(
    user_profile: UserProfile,
    generation_request: GenerationRequest,
) -> NewsletterGenerationState:
    """Run the complete newsletter generation workflow.

    Args:
        user_profile: User profile with preferences and interests
        generation_request: Request parameters for generation

    Returns:
        Final workflow state with results and any errors
    """
    logger.info(
        "Starting newsletter generation",
        user_id=user_profile.user_id,
        generation_id=generation_request.metadata.get("generation_id"),
        demo_mode=generation_request.demo_mode,
    )

    # Create workflow
    workflow = create_newsletter_workflow()
    app = workflow.compile()

    # Create initial state
    initial_state = create_initial_state(user_profile, generation_request)
    initial_state["generation_metadata"].mark_stage_start(ProcessingStage.VALIDATION)

    try:
        # Execute workflow
        final_state = await app.ainvoke(initial_state)

        # Mark completion
        final_state["generation_metadata"].end_time = datetime.now(timezone.utc)
        final_state["generation_metadata"].current_stage = (
            ProcessingStage.COMPLETED if not has_critical_errors(final_state)
            else ProcessingStage.FAILED
        )

        # Log results
        if has_critical_errors(final_state):
            logger.error(
                "Newsletter generation failed",
                user_id=user_profile.user_id,
                errors=[str(error) for error in final_state["errors"]],
                processing_time=final_state["generation_metadata"].total_processing_time,
            )
        else:
            logger.info(
                "Newsletter generation completed",
                user_id=user_profile.user_id,
                total_articles=final_state["curated_newsletter"].total_articles if final_state["curated_newsletter"] else 0,
                processing_time=final_state["generation_metadata"].total_processing_time,
                delivered=final_state["delivery_result"].success if final_state["delivery_result"] else False,
            )

        return final_state

    except Exception as e:
        logger.error(
            "Newsletter generation workflow failed",
            user_id=user_profile.user_id,
            error=str(e),
            exc_info=True,
        )

        # Add critical error to state
        add_error(
            initial_state,
            ProcessingStage.FAILED,
            f"Workflow execution failed: {str(e)}",
            ErrorSeverity.CRITICAL,
        )

        initial_state["generation_metadata"].end_time = datetime.now(timezone.utc)
        initial_state["generation_metadata"].current_stage = ProcessingStage.FAILED

        return initial_state


def get_workflow_status(state: NewsletterGenerationState) -> Dict[str, Any]:
    """Get current workflow status for monitoring.

    Args:
        state: Current workflow state

    Returns:
        Status information including progress and errors
    """
    from src.models.state import calculate_progress_percentage

    metadata = state["generation_metadata"]
    has_errors = bool(state["errors"])

    return {
        "generation_id": metadata.generation_id,
        "user_id": state["user_profile"].user_id,
        "current_stage": metadata.current_stage.value,
        "progress_percentage": calculate_progress_percentage(
            metadata.current_stage, has_errors
        ),
        "processing_time": metadata.total_processing_time,
        "errors_count": len(state["errors"]),
        "warnings_count": len(state["warnings"]),
        "content_collected": len(state["raw_content"]),
        "content_curated": state["curated_newsletter"].total_articles if state["curated_newsletter"] else 0,
        "is_complete": metadata.current_stage in [ProcessingStage.COMPLETED, ProcessingStage.FAILED],
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }