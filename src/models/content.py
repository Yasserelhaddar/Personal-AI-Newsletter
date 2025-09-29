"""Content models for the Personal AI Newsletter Generator."""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ContentType(str, Enum):
    """Types of content that can be collected."""

    ARTICLE = "article"
    VIDEO = "video"
    PAPER = "paper"
    DISCUSSION = "discussion"
    REPOSITORY = "repository"
    PODCAST = "podcast"
    TWEET = "tweet"
    BLOG_POST = "blog_post"
    NEWS = "news"


class ContentSource(str, Enum):
    """Sources of content collection."""

    HACKER_NEWS = "hacker_news"
    REDDIT = "reddit"
    GITHUB = "github"
    ARXIV = "arxiv"
    TWITTER = "twitter"
    RSS_FEED = "rss_feed"
    MANUAL = "manual"
    WEB_SCRAPE = "web_scrape"


class ContentStatus(str, Enum):
    """Status of content processing."""

    RAW = "raw"
    ANALYZED = "analyzed"
    CURATED = "curated"
    INCLUDED = "included"
    EXCLUDED = "excluded"
    FAILED = "failed"


@dataclass
class ContentItem:
    """Represents a piece of content collected from various sources."""

    title: str
    url: str
    source: ContentSource
    content_type: ContentType
    summary: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    content_hash: str = field(init=False)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    language: str = "en"
    word_count: Optional[int] = None
    reading_time_minutes: Optional[int] = None
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Generate content hash after initialization."""
        self.content_hash = self._generate_content_hash()

    def _generate_content_hash(self) -> str:
        """Generate a unique hash for this content item."""
        content_str = f"{self.title}{self.url}{self.author or ''}"
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    @property
    def age_hours(self) -> float:
        """Calculate age of content in hours."""
        if self.published_at:
            return (datetime.now(timezone.utc) - self.published_at).total_seconds() / 3600
        return (datetime.now(timezone.utc) - self.collected_at).total_seconds() / 3600


@dataclass
class AnalyzedContent:
    """Content item with AI analysis results."""

    content_item: ContentItem
    relevance_score: float = 0.0
    interest_matches: List[str] = field(default_factory=list)
    sentiment_score: Optional[float] = None
    complexity_score: Optional[float] = None
    novelty_score: Optional[float] = None
    quality_score: Optional[float] = None
    ai_summary: Optional[str] = None
    ai_insights: List[str] = field(default_factory=list)
    extracted_topics: List[str] = field(default_factory=list)
    status: ContentStatus = ContentStatus.ANALYZED
    analysis_metadata: Dict[str, Any] = field(default_factory=dict)
    analyzed_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def composite_score(self) -> float:
        """Calculate composite relevance score."""
        from src.infrastructure.config import ApplicationConfig
        config = ApplicationConfig()

        scores = [
            self.relevance_score,
            self.quality_score or config.content_quality_score_default,
            self.novelty_score or 0.5,
        ]
        # Weight relevance more heavily
        weights = [0.5, 0.3, 0.2]
        return sum(score * weight for score, weight in zip(scores, weights))

    @property
    def is_high_quality(self) -> bool:
        """Determine if content is high quality based on scores."""
        from src.infrastructure.config import ApplicationConfig
        config = ApplicationConfig()

        return (
            self.composite_score >= config.content_composite_score_threshold and
            (self.quality_score or config.content_quality_score_default) >= config.content_quality_score_threshold
        )


@dataclass
class ContentSection:
    """A themed section of curated content."""

    title: str
    description: str
    emoji: Optional[str] = None
    articles: List[AnalyzedContent] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    order: int = 0

    @property
    def total_reading_time(self) -> int:
        """Calculate total reading time for this section."""
        return sum(
            article.content_item.reading_time_minutes or 3
            for article in self.articles
        )


@dataclass
class PersonalizedInsight:
    """AI-generated personalized insight."""

    title: str
    content: str
    related_articles: List[str] = field(default_factory=list)  # Article URLs
    confidence_score: float = 0.0
    insight_type: str = "general"  # general, trend, recommendation, connection
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CuratedNewsletter:
    """Complete curated newsletter content."""

    subject_line: str
    greeting: str
    sections: List[ContentSection] = field(default_factory=list)
    personalized_insights: List[PersonalizedInsight] = field(default_factory=list)
    github_activity: Optional[Dict[str, Any]] = None
    quick_reads: List[AnalyzedContent] = field(default_factory=list)
    trending_repos: List[Dict[str, Any]] = field(default_factory=list)
    footer_content: str = ""
    generation_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_articles(self) -> int:
        """Total number of articles in the newsletter."""
        return sum(len(section.articles) for section in self.sections)

    @property
    def estimated_reading_time(self) -> int:
        """Estimated total reading time in minutes."""
        section_time = sum(section.total_reading_time for section in self.sections)
        quick_reads_time = sum(
            article.content_item.reading_time_minutes or 2
            for article in self.quick_reads
        )
        return section_time + quick_reads_time + 2  # +2 for insights and metadata


# Pydantic models for API serialization
class ContentItemModel(BaseModel):
    """Pydantic model for ContentItem."""

    title: str
    url: HttpUrl
    source: ContentSource
    content_type: ContentType
    summary: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    content_hash: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    language: str = "en"
    word_count: Optional[int] = None
    reading_time_minutes: Optional[int] = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator('reading_time_minutes')
    @classmethod
    def validate_reading_time(cls, v):
        """Validate reading time is reasonable."""
        if v is not None and (v < 1 or v > 120):
            raise ValueError('Reading time must be between 1 and 120 minutes')
        return v

    class Config:
        use_enum_values = True


class AnalyzedContentModel(BaseModel):
    """Pydantic model for AnalyzedContent."""

    content_item: ContentItemModel
    relevance_score: float = Field(ge=0.0, le=1.0)
    interest_matches: List[str] = Field(default_factory=list)
    sentiment_score: Optional[float] = Field(None, ge=-1.0, le=1.0)
    complexity_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    novelty_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    ai_summary: Optional[str] = None
    ai_insights: List[str] = Field(default_factory=list)
    extracted_topics: List[str] = Field(default_factory=list)
    status: ContentStatus = ContentStatus.ANALYZED
    analysis_metadata: Dict[str, Any] = Field(default_factory=dict)
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class ContentSectionModel(BaseModel):
    """Pydantic model for ContentSection."""

    title: str
    description: str
    emoji: Optional[str] = None
    articles: List[AnalyzedContentModel] = Field(default_factory=list)
    insights: List[str] = Field(default_factory=list)
    order: int = 0


class PersonalizedInsightModel(BaseModel):
    """Pydantic model for PersonalizedInsight."""

    title: str
    content: str
    related_articles: List[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    insight_type: str = "general"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CuratedNewsletterModel(BaseModel):
    """Pydantic model for CuratedNewsletter."""

    subject_line: str
    greeting: str
    sections: List[ContentSectionModel] = Field(default_factory=list)
    personalized_insights: List[PersonalizedInsightModel] = Field(default_factory=list)
    github_activity: Optional[Dict[str, Any]] = None
    quick_reads: List[AnalyzedContentModel] = Field(default_factory=list)
    trending_repos: List[Dict[str, Any]] = Field(default_factory=list)
    footer_content: str = ""
    generation_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Utility functions
def create_content_item(
    title: str,
    url: str,
    source: ContentSource,
    content_type: ContentType,
    **kwargs
) -> ContentItem:
    """Create a new ContentItem with proper defaults."""
    return ContentItem(
        title=title,
        url=url,
        source=source,
        content_type=content_type,
        **kwargs
    )


def estimate_reading_time(text: str, words_per_minute: int = None) -> int:
    """Estimate reading time in minutes based on word count."""
    from src.infrastructure.config import ApplicationConfig

    if words_per_minute is None:
        config = ApplicationConfig()
        words_per_minute = config.content_reading_words_per_minute

    if not text:
        return 1

    word_count = len(text.split())
    reading_time = max(1, round(word_count / words_per_minute))

    config = ApplicationConfig()
    return min(reading_time, config.content_max_reading_time)


def categorize_content_by_interest(
    content: List[AnalyzedContent],
    interests: List[str],
    max_per_category: int = 5
) -> Dict[str, List[AnalyzedContent]]:
    """Categorize content by user interests."""
    categories = {}

    for interest in interests:
        interest_content = [
            item for item in content
            if any(
                interest.lower() in match.lower() or match.lower() in interest.lower()
                for match in item.interest_matches
            )
        ]
        # Sort by composite score and take top items
        interest_content.sort(key=lambda x: x.composite_score, reverse=True)
        categories[interest] = interest_content[:max_per_category]

    return categories


def generate_content_sections(
    categorized_content: Dict[str, List[AnalyzedContent]],
    section_emojis: Optional[Dict[str, str]] = None
) -> List[ContentSection]:
    """Generate content sections from categorized content."""
    default_emojis = {
        "ai": "🤖",
        "artificial intelligence": "🤖",
        "python": "🐍",
        "programming": "💻",
        "startup": "🚀",
        "climate": "🌍",
        "technology": "⚡",
        "science": "🔬",
        "data": "📊",
        "machine learning": "🧠",
    }

    sections = []
    for order, (interest, articles) in enumerate(categorized_content.items()):
        if not articles:
            continue

        emoji = None
        if section_emojis:
            emoji = section_emojis.get(interest.lower())
        else:
            for key, emoji_val in default_emojis.items():
                if key in interest.lower():
                    emoji = emoji_val
                    break

        section = ContentSection(
            title=interest.title(),
            description=f"Latest developments in {interest}",
            emoji=emoji,
            articles=articles,
            order=order
        )
        sections.append(section)

    return sections