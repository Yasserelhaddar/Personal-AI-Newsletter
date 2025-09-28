"""Email models for the Personal AI Newsletter Generator."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class EmailFormat(str, Enum):
    """Email content formats."""

    HTML = "html"
    TEXT = "text"
    BOTH = "both"


class EmailPriority(str, Enum):
    """Email priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class EmailContent:
    """Complete email content ready for delivery."""

    html: str
    text: str
    subject: str
    preview_text: Optional[str] = None
    from_email: str = "newsletter@yourdomain.com"
    from_name: str = "Your AI Newsletter"
    reply_to: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: EmailPriority = EmailPriority.NORMAL
    track_opens: bool = True
    track_clicks: bool = True
    generated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def estimated_size_kb(self) -> float:
        """Estimate email size in KB."""
        html_size = len(self.html.encode('utf-8'))
        text_size = len(self.text.encode('utf-8'))
        return (html_size + text_size) / 1024

    @property
    def is_valid(self) -> bool:
        """Check if email content is valid for sending."""
        return bool(
            self.html and
            self.text and
            self.subject and
            len(self.subject) <= 998 and  # RFC 5322 limit
            self.estimated_size_kb < 10000  # 10MB limit
        )


@dataclass
class TemplateData:
    """Data structure for email template rendering."""

    # Newsletter metadata
    date: str
    user_name: str
    greeting: str
    subject_line: str

    # Content sections
    sections: List[Dict[str, Any]] = field(default_factory=list)
    personalized_insights: List[Dict[str, Any]] = field(default_factory=list)
    quick_reads: List[Dict[str, Any]] = field(default_factory=list)

    # User activity
    github_activity: Optional[Dict[str, Any]] = None
    trending_repos: List[Dict[str, Any]] = field(default_factory=list)

    # Footer and metadata
    footer_content: str = ""
    unsubscribe_url: str = ""
    preferences_url: str = ""
    web_version_url: str = ""

    # Analytics
    tracking_data: Dict[str, str] = field(default_factory=dict)
    generation_metadata: Dict[str, Any] = field(default_factory=dict)

    # Styling
    brand_colors: Dict[str, str] = field(default_factory=lambda: {
        "primary": "#2563eb",
        "secondary": "#64748b",
        "accent": "#f59e0b",
        "background": "#ffffff",
        "text": "#1f2937",
        "muted": "#6b7280"
    })

    @property
    def total_articles(self) -> int:
        """Calculate total number of articles."""
        section_articles = sum(len(section.get('articles', [])) for section in self.sections)
        return section_articles + len(self.quick_reads)

    @property
    def estimated_reading_time(self) -> int:
        """Calculate estimated total reading time."""
        section_time = sum(
            sum(article.get('reading_time', 3) for article in section.get('articles', []))
            for section in self.sections
        )
        quick_reads_time = sum(article.get('reading_time', 2) for article in self.quick_reads)
        return section_time + quick_reads_time + 3  # +3 for insights and metadata


@dataclass
class EmailTemplate:
    """Email template configuration."""

    name: str
    html_template: str
    text_template: str
    css_styles: Optional[str] = None
    inline_css: bool = True
    responsive: bool = True
    template_variables: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def required_variables(self) -> List[str]:
        """Get list of required template variables."""
        # This would ideally parse the template to find variables
        return self.template_variables


@dataclass
class EmailAnalytics:
    """Email analytics and tracking data."""

    delivery_id: str
    user_id: str
    sent_at: datetime
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    first_click_at: Optional[datetime] = None
    total_clicks: int = 0
    unique_clicks: int = 0
    click_details: List[Dict[str, Any]] = field(default_factory=list)
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    location_data: Optional[Dict[str, str]] = None
    device_type: Optional[str] = None

    @property
    def time_to_open_seconds(self) -> Optional[float]:
        """Calculate time from delivery to first open."""
        if self.delivered_at and self.opened_at:
            return (self.opened_at - self.delivered_at).total_seconds()
        return None

    @property
    def engagement_score(self) -> float:
        """Calculate engagement score (0-100)."""
        score = 0.0

        # Opening the email
        if self.opened_at:
            score += 30.0

        # Click engagement
        if self.total_clicks > 0:
            score += min(40.0, self.total_clicks * 10)

        # Speed of engagement
        if self.time_to_open_seconds and self.time_to_open_seconds < 3600:  # Within 1 hour
            score += 20.0
        elif self.time_to_open_seconds and self.time_to_open_seconds < 86400:  # Within 1 day
            score += 10.0

        return min(100.0, score)


# Pydantic models for API serialization
class EmailContentModel(BaseModel):
    """Pydantic model for EmailContent."""

    html: str
    text: str
    subject: str = Field(..., max_length=998)
    preview_text: Optional[str] = Field(None, max_length=200)
    from_email: EmailStr = "newsletter@yourdomain.com"
    from_name: str = "Your AI Newsletter"
    reply_to: Optional[EmailStr] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    priority: EmailPriority = EmailPriority.NORMAL
    track_opens: bool = True
    track_clicks: bool = True
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class TemplateDataModel(BaseModel):
    """Pydantic model for TemplateData."""

    date: str
    user_name: str
    greeting: str
    subject_line: str
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    personalized_insights: List[Dict[str, Any]] = Field(default_factory=list)
    quick_reads: List[Dict[str, Any]] = Field(default_factory=list)
    github_activity: Optional[Dict[str, Any]] = None
    trending_repos: List[Dict[str, Any]] = Field(default_factory=list)
    footer_content: str = ""
    unsubscribe_url: str = ""
    preferences_url: str = ""
    web_version_url: str = ""
    tracking_data: Dict[str, str] = Field(default_factory=dict)
    generation_metadata: Dict[str, Any] = Field(default_factory=dict)
    brand_colors: Dict[str, str] = Field(default_factory=lambda: {
        "primary": "#2563eb",
        "secondary": "#64748b",
        "accent": "#f59e0b",
        "background": "#ffffff",
        "text": "#1f2937",
        "muted": "#6b7280"
    })


class EmailAnalyticsModel(BaseModel):
    """Pydantic model for EmailAnalytics."""

    delivery_id: str
    user_id: str
    sent_at: datetime
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    first_click_at: Optional[datetime] = None
    total_clicks: int = Field(default=0, ge=0)
    unique_clicks: int = Field(default=0, ge=0)
    click_details: List[Dict[str, Any]] = Field(default_factory=list)
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    location_data: Optional[Dict[str, str]] = None
    device_type: Optional[str] = None


# Utility functions
def create_email_content(
    html: str,
    text: str,
    subject: str,
    **kwargs
) -> EmailContent:
    """Create EmailContent with proper defaults."""
    return EmailContent(
        html=html,
        text=text,
        subject=subject,
        **kwargs
    )


def generate_email_headers(
    newsletter_type: str = "daily-digest",
    generation_id: str = "",
    user_id: str = "",
) -> Dict[str, str]:
    """Generate standard email headers."""
    headers = {
        "X-Newsletter-Type": newsletter_type,
        "X-Mailer": "Personal-AI-Newsletter-Generator",
        "X-Priority": "3",
        "X-MSMail-Priority": "Normal",
    }

    if generation_id:
        headers["X-Generation-ID"] = generation_id

    if user_id:
        headers["X-User-ID"] = user_id

    return headers


def generate_tracking_pixel_url(
    delivery_id: str,
    user_id: str,
    base_url: str = "https://yourdomain.com/track"
) -> str:
    """Generate tracking pixel URL for open tracking."""
    return f"{base_url}/open/{delivery_id}?user={user_id}"


def generate_click_tracking_url(
    original_url: str,
    delivery_id: str,
    user_id: str,
    link_id: str,
    base_url: str = "https://yourdomain.com/track"
) -> str:
    """Generate click tracking URL."""
    import urllib.parse
    encoded_url = urllib.parse.quote(original_url, safe='')
    return f"{base_url}/click/{delivery_id}?user={user_id}&link={link_id}&url={encoded_url}"


def extract_text_from_html(html: str) -> str:
    """Extract plain text from HTML for text version."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        # Get text and clean it up
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)

        return text
    except ImportError:
        # Fallback if beautifulsoup4 is not available
        import re
        # Remove HTML tags
        text = re.sub('<[^<]+?>', '', html)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text


def validate_email_content(content: EmailContent) -> List[str]:
    """Validate email content and return list of issues."""
    issues = []

    if not content.html:
        issues.append("HTML content is empty")

    if not content.text:
        issues.append("Text content is empty")

    if not content.subject:
        issues.append("Subject line is empty")

    if len(content.subject) > 998:
        issues.append("Subject line too long (max 998 characters)")

    if content.estimated_size_kb > 10000:
        issues.append("Email size too large (max 10MB)")

    # Check for common spam triggers
    spam_words = ['FREE', 'URGENT', 'WINNER', 'CLICK NOW', 'LIMITED TIME']
    subject_upper = content.subject.upper()
    if any(word in subject_upper for word in spam_words):
        issues.append("Subject contains potential spam trigger words")

    return issues