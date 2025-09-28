"""State models for the LangGraph newsletter generation workflow."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, TYPE_CHECKING

from pydantic import BaseModel, Field

# Forward references will be resolved at the end of the module


class ProcessingStage(str, Enum):
    """Processing stages for the newsletter generation workflow."""

    VALIDATION = "validation"
    COLLECTION = "collection"
    CURATION = "curation"
    GENERATION = "generation"
    DELIVERY = "delivery"
    ANALYTICS = "analytics"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorSeverity(str, Enum):
    """Error severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ProcessingError:
    """Represents an error that occurred during processing."""

    stage: ProcessingStage
    message: str
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    error_code: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __str__(self) -> str:
        return f"[{self.stage.value}] {self.message}"


@dataclass
class GenerationRequest:
    """Request parameters for newsletter generation."""

    user_id: str
    demo_mode: bool = False
    dry_run: bool = False
    test_mode: bool = False
    force_regenerate: bool = False
    max_articles: Optional[int] = None
    specific_interests: Optional[List[str]] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationMetadata:
    """Metadata about the newsletter generation process."""

    generation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    current_stage: ProcessingStage = ProcessingStage.VALIDATION
    processing_time: Dict[ProcessingStage, float] = field(default_factory=dict)
    content_sources_used: List[str] = field(default_factory=list)
    ai_analysis_steps: int = 0
    total_content_collected: int = 0
    content_after_curation: int = 0
    performance_metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_processing_time(self) -> float:
        """Calculate total processing time in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    def mark_stage_start(self, stage: ProcessingStage) -> None:
        """Mark the start of a processing stage."""
        self.current_stage = stage
        self.processing_time[stage] = datetime.now(timezone.utc).timestamp()

    def mark_stage_end(self, stage: ProcessingStage) -> None:
        """Mark the end of a processing stage."""
        if stage in self.processing_time:
            start_time = self.processing_time[stage]
            self.processing_time[stage] = datetime.now(timezone.utc).timestamp() - start_time


class NewsletterGenerationState(TypedDict):
    """State for the newsletter generation LangGraph workflow.

    This TypedDict defines the complete state that flows through
    the LangGraph workflow nodes during newsletter generation.
    """

    # Input configuration
    user_profile: "UserProfile"  # Forward reference
    generation_request: GenerationRequest

    # Processing data
    raw_content: List["ContentItem"]  # Forward reference
    analyzed_content: List["AnalyzedContent"]  # Forward reference
    curated_newsletter: Optional["CuratedNewsletter"]  # Forward reference
    email_content: Optional["EmailContent"]  # Forward reference

    # Output results
    delivery_result: Optional["DeliveryResult"]  # Forward reference
    generation_metadata: GenerationMetadata

    # Error handling and monitoring
    errors: List[ProcessingError]
    warnings: List[str]

    # Additional context
    workflow_context: Dict[str, Any]


# Pydantic models for API serialization
class ProcessingErrorModel(BaseModel):
    """Pydantic model for ProcessingError."""

    stage: ProcessingStage
    message: str
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    error_code: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GenerationRequestModel(BaseModel):
    """Pydantic model for GenerationRequest."""

    user_id: str
    demo_mode: bool = False
    dry_run: bool = False
    force_regenerate: bool = False
    max_articles: Optional[int] = None
    specific_interests: Optional[List[str]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GenerationMetadataModel(BaseModel):
    """Pydantic model for GenerationMetadata."""

    generation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    current_stage: ProcessingStage = ProcessingStage.VALIDATION
    processing_time: Dict[ProcessingStage, float] = Field(default_factory=dict)
    content_sources_used: List[str] = Field(default_factory=list)
    ai_analysis_steps: int = 0
    total_content_collected: int = 0
    content_after_curation: int = 0
    performance_metrics: Dict[str, Any] = Field(default_factory=dict)

    @property
    def total_processing_time(self) -> float:
        """Calculate total processing time in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()


class WorkflowStatus(BaseModel):
    """Status information for workflow monitoring."""

    generation_id: str
    user_id: str
    current_stage: ProcessingStage
    progress_percentage: float = Field(ge=0, le=100)
    estimated_completion: Optional[datetime] = None
    errors_count: int = 0
    warnings_count: int = 0
    processing_time: float = 0.0
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# Utility functions for state management
def create_initial_state(
    user_profile: "UserProfile",
    generation_request: GenerationRequest,
) -> NewsletterGenerationState:
    """Create initial state for newsletter generation workflow."""
    return NewsletterGenerationState(
        user_profile=user_profile,
        generation_request=generation_request,
        raw_content=[],
        analyzed_content=[],
        curated_newsletter=None,
        email_content=None,
        delivery_result=None,
        generation_metadata=GenerationMetadata(),
        errors=[],
        warnings=[],
        workflow_context={},
    )


def add_error(
    state: NewsletterGenerationState,
    stage: ProcessingStage,
    message: str,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    error_code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Add an error to the workflow state."""
    error = ProcessingError(
        stage=stage,
        message=message,
        severity=severity,
        error_code=error_code,
        details=details or {},
    )
    state["errors"].append(error)


def add_warning(state: NewsletterGenerationState, message: str) -> None:
    """Add a warning to the workflow state."""
    state["warnings"].append(f"[{datetime.now(timezone.utc).isoformat()}] {message}")


def has_critical_errors(state: NewsletterGenerationState) -> bool:
    """Check if state has any critical errors."""
    return any(
        error.severity == ErrorSeverity.CRITICAL
        for error in state["errors"]
    )


def get_errors_by_stage(
    state: NewsletterGenerationState,
    stage: ProcessingStage,
) -> List[ProcessingError]:
    """Get all errors for a specific processing stage."""
    return [
        error for error in state["errors"]
        if error.stage == stage
    ]


def calculate_progress_percentage(
    current_stage: ProcessingStage,
    has_errors: bool = False,
) -> float:
    """Calculate progress percentage based on current stage."""
    stage_progress = {
        ProcessingStage.VALIDATION: 10.0,
        ProcessingStage.COLLECTION: 30.0,
        ProcessingStage.CURATION: 60.0,
        ProcessingStage.GENERATION: 80.0,
        ProcessingStage.DELIVERY: 95.0,
        ProcessingStage.ANALYTICS: 100.0,
        ProcessingStage.COMPLETED: 100.0,
        ProcessingStage.FAILED: 0.0 if has_errors else 100.0,
    }
    return stage_progress.get(current_stage, 0.0)


# Import concrete types to resolve forward references
try:
    from src.models.user import UserProfile, DeliveryResult
    from src.models.content import ContentItem, AnalyzedContent, CuratedNewsletter
    from src.models.email import EmailContent

    # Update the NewsletterGenerationState type annotations at runtime
    NewsletterGenerationState.__annotations__.update({
        'user_profile': UserProfile,
        'raw_content': List[ContentItem],
        'analyzed_content': List[AnalyzedContent],
        'curated_newsletter': Optional[CuratedNewsletter],
        'email_content': Optional[EmailContent],
        'delivery_result': Optional[DeliveryResult],
    })
except ImportError:
    # If imports fail, the forward references will remain as strings
    pass