"""Configuration management for the Personal AI Newsletter Generator."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class ApplicationConfig(BaseSettings):
    """Application configuration with environment variable support."""

    # Database
    database_url: str = Field(
        default="sqlite:///newsletter.db",
        description="Database connection URL"
    )

    # MCP Server Configuration
    resend_api_key: str = Field(
        default="",
        description="Resend API key for email delivery"
    )
    firecrawl_api_key: str = Field(
        default="",
        description="Firecrawl API key for web scraping"
    )
    github_token: str = Field(
        default="",
        description="GitHub personal access token"
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for LLM services"
    )

    # Application Settings
    max_concurrent_collections: int = Field(
        default=5,
        description="Maximum concurrent content collection operations"
    )
    content_cache_ttl: int = Field(
        default=3600,
        description="Content cache TTL in seconds"
    )
    default_articles_per_newsletter: int = Field(
        default=10,
        description="Default number of articles per newsletter"
    )

    # Domain Settings
    domain: str = Field(
        default="",
        description="Domain name for email addresses (leave empty to use Resend test email)"
    )

    # Email Settings
    from_email: str = Field(
        default="",
        description="From email address for newsletters (auto-configured based on domain)"
    )
    from_name: str = Field(
        default="AI Newsletter",
        description="From name for newsletters"
    )

    # Scheduling
    default_send_time: str = Field(
        default="07:00",
        description="Default newsletter send time (HH:MM format)"
    )
    timezone: str = Field(
        default="UTC",
        description="Default timezone for scheduling"
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    log_format: str = Field(
        default="structured",
        description="Log format: structured or text"
    )

    # Performance
    request_timeout: int = Field(
        default=30,
        description="HTTP request timeout in seconds"
    )
    retry_attempts: int = Field(
        default=3,
        description="Number of retry attempts for failed requests"
    )

    # Content Quality Thresholds
    content_composite_score_threshold: float = Field(
        default=0.2,
        description="Minimum composite score for content to be included"
    )
    content_quality_score_threshold: float = Field(
        default=0.2,
        description="Minimum quality score for content to be included"
    )
    content_fallback_score_threshold: float = Field(
        default=0.1,
        description="Fallback threshold when not enough content meets quality threshold"
    )
    content_quality_score_default: float = Field(
        default=0.5,
        description="Default quality score when score is null"
    )

    # OpenAI Configuration
    openai_model: str = Field(
        default="gpt-4",
        description="OpenAI model to use for content analysis"
    )
    openai_max_tokens: int = Field(
        default=4000,
        description="Maximum tokens for OpenAI API calls"
    )
    openai_temperature: float = Field(
        default=0.1,
        description="Temperature setting for OpenAI API calls"
    )

    # Content Collection Settings
    max_items_per_source: int = Field(
        default=20,
        description="Maximum items to collect from each content source"
    )
    content_reading_words_per_minute: int = Field(
        default=200,
        description="Words per minute for reading time calculation"
    )
    content_max_reading_time: int = Field(
        default=15,
        description="Maximum reading time in minutes"
    )

    # Content Sources
    content_sources: Dict[str, Dict[str, str]] = Field(
        default_factory=lambda: {
            "hacker_news": {
                "base_url": "https://hacker-news.firebaseio.com/v0",
                "type": "api"
            },
            "reddit": {
                "base_url": "https://www.reddit.com",
                "type": "web"
            },
            "github_trending": {
                "base_url": "https://api.github.com",
                "type": "api"
            }
        },
        description="Configuration for content sources"
    )

    # Reddit Content URLs
    reddit_ai_subreddits_url: str = Field(
        default="https://www.reddit.com/r/MachineLearning+artificial+ArtificialIntelligence/.json",
        description="Reddit URL for AI-related subreddits"
    )
    reddit_computer_vision_url: str = Field(
        default="https://www.reddit.com/r/computervision/.json",
        description="Reddit URL for Computer Vision subreddit"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()

    @field_validator("default_send_time")
    @classmethod
    def validate_send_time(cls, v):
        """Validate send time format."""
        try:
            hours, minutes = v.split(":")
            if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("default_send_time must be in HH:MM format")
        return v

    @property
    def newsletter_from_email(self) -> str:
        """Generate from email using the configured domain or fallback to Resend test email."""
        if self.from_email:
            # Use explicitly configured from_email
            return self.from_email
        elif self.domain and self.domain != "" and self.domain != "yourdomain.com":
            # Use domain-based email if custom domain is configured
            return f"newsletter@{self.domain}"
        else:
            # Fallback to Resend's test email for development
            return "onboarding@resend.dev"
    
    @property
    def is_using_test_email(self) -> bool:
        """Check if using test email address."""
        return self.newsletter_from_email == "onboarding@resend.dev"

    class Config:
        env_prefix = "NEWSLETTER_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@dataclass
class MCPServerConfig:
    """Configuration for MCP servers."""

    name: str
    command: str
    args: List[str]
    env: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    retry_attempts: int = 3


@dataclass
class UserConfig:
    """User-specific configuration."""

    user_id: str
    email: str
    name: str
    timezone: str = "UTC"
    github_username: Optional[str] = None
    interests: List[str] = field(default_factory=list)
    schedule_time: str = "07:00"
    schedule_days: List[str] = field(default_factory=lambda: [
        "monday", "tuesday", "wednesday", "thursday", "friday"
    ])
    max_articles: int = 10
    include_github_activity: bool = True
    include_trending_repos: bool = True
    content_types: List[str] = field(default_factory=lambda: [
        "articles", "videos", "papers", "discussions"
    ])


def load_config() -> ApplicationConfig:
    """Load application configuration from environment and files."""
    return ApplicationConfig()


def load_mcp_config() -> Dict[str, MCPServerConfig]:
    """Load MCP server configuration."""
    import shutil

    config = ApplicationConfig()

    # Find commands in PATH instead of hardcoded paths
    npx_path = shutil.which("npx")
    uvx_path = shutil.which("uvx")

    if not npx_path:
        raise RuntimeError("npx not found in PATH. Please install Node.js and npm.")
    if not uvx_path:
        raise RuntimeError("uvx not found in PATH. Please install uvx.")

    return {
        "resend": MCPServerConfig(
            name="resend",
            command="node",
            args=[str(get_project_root() / "mcp-servers" / "resend" / "build" / "index.js"), "--key", config.resend_api_key] if config.resend_api_key else [str(get_project_root() / "mcp-servers" / "resend" / "build" / "index.js")],
            env={"RESEND_API_KEY": config.resend_api_key},
        ),
        # "firecrawl": MCPServerConfig(
        #     name="firecrawl",
        #     command=npx_path,
        #     args=["-y", "firecrawl-mcp"],  # Package doesn't exist, use direct API instead
        #     env={"FIRECRAWL_API_KEY": config.firecrawl_api_key},
        # ),
        "github": MCPServerConfig(
            name="github",
            command="docker",
            args=[
                "run", "-i", "--rm",
                "-e", f"GITHUB_PERSONAL_ACCESS_TOKEN={config.github_token}",
                "ghcr.io/github/github-mcp-server"
            ],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": config.github_token},
        ),
    }


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def get_config_dir() -> Path:
    """Get the configuration directory."""
    return get_project_root() / "config"


def get_templates_dir() -> Path:
    """Get the templates directory."""
    return get_project_root() / "templates"


def get_logs_dir() -> Path:
    """Get the logs directory."""
    logs_dir = get_project_root() / "logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir





def save_config(configs: Dict[str, MCPServerConfig]) -> None:
    """Save MCP server configuration to file."""
    import json
    config_file = get_config_dir() / "mcp_servers.json"
    config_file.parent.mkdir(exist_ok=True)

    data = {}
    for name, config in configs.items():
        data[name] = {
            "command": [config.command] + config.args,
            "env": config.env,
            "timeout": config.timeout,
            "retry_attempts": config.retry_attempts
        }

    with open(config_file, "w") as f:
        json.dump(data, f, indent=2)