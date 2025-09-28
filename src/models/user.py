"""User models for the Personal AI Newsletter Generator."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class InteractionType(str, Enum):
    """Types of user interactions with content."""

    CLICK = "click"
    READ = "read"
    SKIP = "skip"
    LIKE = "like"
    SHARE = "share"
    SAVE = "save"
    REPLY = "reply"
    OPEN_EMAIL = "open_email"


class DeliveryStatus(str, Enum):
    """Email delivery status."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"
    COMPLAINED = "complained"
    UNSUBSCRIBED = "unsubscribed"


class ScheduleDay(str, Enum):
    """Days of the week for scheduling."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


@dataclass
class UserProfile:
    """Complete user profile with preferences and history."""

    user_id: str
    email: str
    name: str
    timezone: str = "UTC"
    github_username: Optional[str] = None
    interests: List[str] = field(default_factory=list)
    interest_weights: Dict[str, float] = field(default_factory=dict)

    # Scheduling preferences
    schedule_time: str = "07:00"  # HH:MM format
    schedule_days: List[ScheduleDay] = field(default_factory=lambda: [
        ScheduleDay.MONDAY, ScheduleDay.TUESDAY, ScheduleDay.WEDNESDAY,
        ScheduleDay.THURSDAY, ScheduleDay.FRIDAY
    ])

    # Content preferences
    max_articles: int = 10
    include_github_activity: bool = True
    include_trending_repos: bool = True
    content_types: List[str] = field(default_factory=lambda: [
        "articles", "videos", "papers", "discussions"
    ])

    # Personalization data
    interaction_history: List["UserInteraction"] = field(default_factory=list)
    computed_preferences: Dict[str, Any] = field(default_factory=dict)
    last_newsletter_sent: Optional[datetime] = None
    total_newsletters_sent: int = 0

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def full_interests(self) -> List[Dict[str, Any]]:
        """Get interests with their weights."""
        return [
            {
                "interest": interest,
                "weight": self.interest_weights.get(interest, 1.0)
            }
            for interest in self.interests
        ]

    def update_interest_weight(self, interest: str, weight_delta: float) -> None:
        """Update interest weight based on user interaction."""
        current_weight = self.interest_weights.get(interest, 1.0)
        new_weight = max(0.1, min(2.0, current_weight + weight_delta))
        self.interest_weights[interest] = new_weight


@dataclass
class UserInteraction:
    """Represents a user interaction with content."""

    user_id: str
    content_id: str
    interaction_type: InteractionType
    interaction_value: Optional[float] = None  # reading time, engagement score
    content_title: Optional[str] = None
    content_url: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def engagement_score(self) -> float:
        """Calculate engagement score for this interaction."""
        base_scores = {
            InteractionType.SKIP: -0.2,
            InteractionType.CLICK: 0.5,
            InteractionType.READ: 1.0,
            InteractionType.LIKE: 1.5,
            InteractionType.SHARE: 2.0,
            InteractionType.SAVE: 1.8,
            InteractionType.REPLY: 2.5,
            InteractionType.OPEN_EMAIL: 0.3,
        }

        base_score = base_scores.get(self.interaction_type, 0.0)

        # Adjust for interaction value (e.g., reading time)
        if self.interaction_value and self.interaction_type == InteractionType.READ:
            # Normalize reading time to 0-2 multiplier
            time_multiplier = min(2.0, self.interaction_value / 300)  # 5 minutes = 1.0
            base_score *= time_multiplier

        return base_score


@dataclass
class DeliveryResult:
    """Result of email delivery attempt."""

    success: bool
    delivery_id: Optional[str] = None
    status: DeliveryStatus = DeliveryStatus.PENDING
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    click_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def delivery_time_seconds(self) -> Optional[float]:
        """Calculate delivery time in seconds."""
        if self.sent_at and self.delivered_at:
            return (self.delivered_at - self.sent_at).total_seconds()
        return None


# Pydantic models for API serialization
class UserProfileModel(BaseModel):
    """Pydantic model for UserProfile."""

    user_id: str
    email: EmailStr
    name: str
    timezone: str = "UTC"
    github_username: Optional[str] = None
    interests: List[str] = Field(default_factory=list)
    interest_weights: Dict[str, float] = Field(default_factory=dict)

    schedule_time: str = "07:00"
    schedule_days: List[ScheduleDay] = Field(default_factory=lambda: [
        ScheduleDay.MONDAY, ScheduleDay.TUESDAY, ScheduleDay.WEDNESDAY,
        ScheduleDay.THURSDAY, ScheduleDay.FRIDAY
    ])

    max_articles: int = Field(default=10, ge=1, le=50)
    include_github_activity: bool = True
    include_trending_repos: bool = True
    content_types: List[str] = Field(default_factory=lambda: [
        "articles", "videos", "papers", "discussions"
    ])

    computed_preferences: Dict[str, Any] = Field(default_factory=dict)
    last_newsletter_sent: Optional[datetime] = None
    total_newsletters_sent: int = Field(default=0, ge=0)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator('schedule_time')
    @classmethod
    def validate_schedule_time(cls, v):
        """Validate schedule time format."""
        try:
            hours, minutes = v.split(':')
            if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError('schedule_time must be in HH:MM format')
        return v

    @field_validator('interests')
    @classmethod
    def validate_interests(cls, v):
        """Validate interests list."""
        if len(v) > 20:
            raise ValueError('Maximum 20 interests allowed')
        return [interest.strip().lower() for interest in v if interest.strip()]

    class Config:
        use_enum_values = True


class UserInteractionModel(BaseModel):
    """Pydantic model for UserInteraction."""

    user_id: str
    content_id: str
    interaction_type: InteractionType
    interaction_value: Optional[float] = None
    content_title: Optional[str] = None
    content_url: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class DeliveryResultModel(BaseModel):
    """Pydantic model for DeliveryResult."""

    success: bool
    delivery_id: Optional[str] = None
    status: DeliveryStatus = DeliveryStatus.PENDING
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    click_count: int = Field(default=0, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True


class UserPreferencesUpdateModel(BaseModel):
    """Model for updating user preferences."""

    interests: Optional[List[str]] = None
    schedule_time: Optional[str] = None
    schedule_days: Optional[List[ScheduleDay]] = None
    max_articles: Optional[int] = Field(None, ge=1, le=50)
    include_github_activity: Optional[bool] = None
    include_trending_repos: Optional[bool] = None
    content_types: Optional[List[str]] = None

    @field_validator('schedule_time')
    @classmethod
    def validate_schedule_time(cls, v):
        """Validate schedule time format."""
        if v is not None:
            try:
                hours, minutes = v.split(':')
                if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                raise ValueError('schedule_time must be in HH:MM format')
        return v

    class Config:
        use_enum_values = True


# Utility functions
def create_user_profile(
    email: str,
    name: str,
    interests: List[str],
    **kwargs
) -> UserProfile:
    """Create a new user profile with proper defaults."""
    user_id = str(uuid.uuid4())

    return UserProfile(
        user_id=user_id,
        email=email,
        name=name,
        interests=interests,
        **kwargs
    )


def calculate_user_engagement_score(interactions: List[UserInteraction]) -> float:
    """Calculate overall user engagement score."""
    if not interactions:
        return 0.0

    total_score = sum(interaction.engagement_score for interaction in interactions)
    return min(10.0, total_score / len(interactions) * 5)  # Scale to 0-10


def get_user_interest_trends(
    interactions: List[UserInteraction],
    days: int = 30
) -> Dict[str, float]:
    """Analyze user interest trends from recent interactions."""
    cutoff_date = datetime.now(timezone.utc) - datetime.timedelta(days=days)
    recent_interactions = [
        interaction for interaction in interactions
        if interaction.timestamp >= cutoff_date
    ]

    if not recent_interactions:
        return {}

    # Group interactions by source/content type
    source_scores = {}
    for interaction in recent_interactions:
        source = interaction.source or "unknown"
        if source not in source_scores:
            source_scores[source] = []
        source_scores[source].append(interaction.engagement_score)

    # Calculate average engagement per source
    source_trends = {}
    for source, scores in source_scores.items():
        source_trends[source] = sum(scores) / len(scores)

    return source_trends


def should_send_newsletter(
    user_profile: UserProfile,
    current_time: datetime
) -> bool:
    """Determine if newsletter should be sent to user now."""
    # Check if it's the right day
    current_day = ScheduleDay(current_time.strftime('%A').lower())
    if current_day not in user_profile.schedule_days:
        return False

    # Check if it's the right time (within 30 minutes)
    schedule_time = datetime.strptime(user_profile.schedule_time, '%H:%M').time()
    current_time_only = current_time.time()

    # Convert to minutes for easier comparison
    schedule_minutes = schedule_time.hour * 60 + schedule_time.minute
    current_minutes = current_time_only.hour * 60 + current_time_only.minute

    # Allow 30-minute window
    time_diff = abs(current_minutes - schedule_minutes)
    if time_diff > 30 and time_diff < (24 * 60 - 30):  # Handle day boundary
        return False

    # Check if newsletter was already sent today
    if user_profile.last_newsletter_sent:
        last_sent_date = user_profile.last_newsletter_sent.date()
        current_date = current_time.date()
        if last_sent_date == current_date:
            return False

    return True