"""Email generation service with responsive templates."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from premailer import Premailer

from src.infrastructure.logging import LoggerMixin
from src.infrastructure.config import get_templates_dir, ApplicationConfig
from src.models.content import CuratedNewsletter
from src.models.email import EmailContent, TemplateData, create_email_content, extract_text_from_html
from src.models.user import UserProfile


class EmailGenerationService(LoggerMixin):
    """Service for generating beautiful HTML emails from newsletter content."""

    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or get_templates_dir()
        self.config = ApplicationConfig()
        self.jinja_env = self._setup_jinja_environment()
        self.css_inliner = Premailer(
            base_url=f"https://{self.config.domain}",
            remove_classes=False,
            keep_style_tags=True,
            strip_important=False,
        )

    def _setup_jinja_environment(self) -> Environment:
        """Set up Jinja2 environment with proper configuration."""
        return Environment(
            loader=FileSystemLoader(self.templates_dir),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    async def generate_newsletter_email(
        self,
        newsletter: CuratedNewsletter,
        user_profile: UserProfile,
        tracking_data: Optional[Dict[str, str]] = None,
    ) -> EmailContent:
        """Generate complete email content from curated newsletter.

        Args:
            newsletter: Curated newsletter content
            user_profile: User profile for personalization
            tracking_data: Optional tracking parameters

        Returns:
            Complete email content ready for sending
        """
        self.logger.info(
            "Generating newsletter email",
            user_id=user_profile.user_id,
            articles_count=newsletter.total_articles,
            sections_count=len(newsletter.sections),
        )

        try:
            # Prepare template data
            template_data = self._prepare_template_data(
                newsletter, user_profile, tracking_data
            )

            # Render HTML content
            html_content = await self._render_html_template(template_data)

            # Inline CSS for email clients
            inlined_html = self._inline_css(html_content)

            # Generate text version
            text_content = self._generate_text_version(newsletter, user_profile)

            # Generate preview text
            preview_text = self._generate_preview_text(newsletter)

            # Create email content
            email_content = create_email_content(
                html=inlined_html,
                text=text_content,
                subject=newsletter.subject_line,
                preview_text=preview_text,
                from_email=self.config.newsletter_from_email,
                from_name=self.config.from_name,
                tags=["newsletter", "daily-digest", "ai-curated"],
                metadata={
                    "user_id": user_profile.user_id,
                    "newsletter_id": template_data.generation_metadata.get("generation_id"),
                    "articles_count": newsletter.total_articles,
                    "sections": [section.title for section in newsletter.sections],
                },
            )

            self.logger.info(
                "Newsletter email generated successfully",
                user_id=user_profile.user_id,
                email_size_kb=email_content.estimated_size_kb,
                subject=newsletter.subject_line,
            )

            return email_content

        except Exception as e:
            self.logger.error(
                "Failed to generate newsletter email",
                user_id=user_profile.user_id,
                error=str(e),
                exc_info=True,
            )
            raise

    def _prepare_template_data(
        self,
        newsletter: CuratedNewsletter,
        user_profile: UserProfile,
        tracking_data: Optional[Dict[str, str]] = None,
    ) -> TemplateData:
        """Prepare data for email template rendering."""
        # Convert content sections to template format
        sections_data = []
        for section in newsletter.sections:
            articles_data = []
            for article in section.articles:
                articles_data.append({
                    "content_item": {
                        "title": article.content_item.title,
                        "url": self._add_tracking_to_url(
                            article.content_item.url, tracking_data
                        ),
                        "author": article.content_item.author,
                        "reading_time_minutes": article.content_item.reading_time_minutes,
                        "source": article.content_item.source.value,
                    },
                    "ai_summary": article.ai_summary,
                    "relevance_score": article.relevance_score,
                })

            sections_data.append({
                "title": section.title,
                "description": section.description,
                "emoji": section.emoji,
                "articles": articles_data,
                "insights": section.insights,
            })

        # Convert personalized insights
        insights_data = []
        for insight in newsletter.personalized_insights:
            insights_data.append({
                "title": insight.title,
                "content": insight.content,
                "confidence_score": insight.confidence_score,
                "insight_type": insight.insight_type,
            })

        # Convert quick reads
        quick_reads_data = []
        for article in newsletter.quick_reads:
            quick_reads_data.append({
                "content_item": {
                    "title": article.content_item.title,
                    "url": self._add_tracking_to_url(
                        article.content_item.url, tracking_data
                    ),
                    "reading_time_minutes": article.content_item.reading_time_minutes,
                },
                "ai_summary": article.ai_summary,
            })

        return TemplateData(
            date=datetime.now().strftime("%B %d, %Y"),
            user_name=user_profile.name,
            greeting=newsletter.greeting,
            subject_line=newsletter.subject_line,
            sections=sections_data,
            personalized_insights=insights_data,
            quick_reads=quick_reads_data,
            github_activity=newsletter.github_activity,
            trending_repos=newsletter.trending_repos,
            footer_content=newsletter.footer_content,
            unsubscribe_url=self._generate_unsubscribe_url(user_profile.user_id),
            preferences_url=self._generate_preferences_url(user_profile.user_id),
            web_version_url=self._generate_web_version_url(user_profile.user_id),
            tracking_data=tracking_data or {},
            generation_metadata=newsletter.generation_metadata,
        )

    async def _render_html_template(self, template_data: TemplateData) -> str:
        """Render HTML email template with data."""
        try:
            template = self.jinja_env.get_template("email/newsletter.html")
            html_content = template.render(**template_data.__dict__)
            return html_content

        except Exception as e:
            self.logger.error("Failed to render HTML template", error=str(e))
            raise

    def _inline_css(self, html_content: str) -> str:
        """Inline CSS styles for better email client compatibility."""
        try:
            inlined = self.css_inliner.transform(html_content)
            return inlined

        except Exception as e:
            self.logger.warning("Failed to inline CSS, using original HTML", error=str(e))
            return html_content

    def _generate_text_version(
        self, newsletter: CuratedNewsletter, user_profile: UserProfile
    ) -> str:
        """Generate plain text version of the newsletter."""
        lines = []

        # Header
        lines.append("🌅 Your Daily Intelligence Digest")
        lines.append(f"{datetime.now().strftime('%B %d, %Y')}")
        lines.append("")
        lines.append(newsletter.greeting)
        lines.append("")

        # Sections
        for section in newsletter.sections:
            lines.append(f"{section.emoji or '▶'} {section.title.upper()}")
            lines.append("-" * 40)

            for article in section.articles:
                lines.append(f"• {article.content_item.title}")
                if article.ai_summary:
                    lines.append(f"  {article.ai_summary}")
                lines.append(f"  Link: {article.content_item.url}")
                if article.content_item.reading_time_minutes:
                    lines.append(f"  Reading time: {article.content_item.reading_time_minutes} min")
                lines.append("")

            lines.append("")

        # Personalized insights
        if newsletter.personalized_insights:
            lines.append("💡 PERSONALIZED INSIGHTS")
            lines.append("-" * 40)
            for insight in newsletter.personalized_insights:
                lines.append(f"• {insight.title}")
                lines.append(f"  {insight.content}")
                lines.append("")

        # GitHub activity
        if newsletter.github_activity and newsletter.github_activity.get("recent_repositories"):
            lines.append("🐙 YOUR GITHUB ACTIVITY")
            lines.append("-" * 40)
            for repo in newsletter.github_activity.get("recent_repositories", []):
                lines.append(f"• {repo.get('name', '')}")
                if repo.get("description"):
                    lines.append(f"  {repo.get('description')}")
                if repo.get("stars"):
                    lines.append(f"  ⭐ {repo.get('stars')} stars")
                lines.append("")

        # Quick reads
        if newsletter.quick_reads:
            lines.append("📚 QUICK READS")
            lines.append("-" * 40)
            for article in newsletter.quick_reads:
                time_str = f" [{article.content_item.reading_time_minutes} min]" if article.content_item.reading_time_minutes else ""
                lines.append(f"• {article.content_item.title}{time_str}")
                lines.append(f"  {article.content_item.url}")
                lines.append("")

        # Footer
        lines.append("")
        lines.append(newsletter.footer_content)
        lines.append("")
        lines.append("Update preferences: " + self._generate_preferences_url(user_profile.user_id))
        lines.append("Unsubscribe: " + self._generate_unsubscribe_url(user_profile.user_id))

        return "\n".join(lines)

    def _generate_preview_text(self, newsletter: CuratedNewsletter) -> str:
        """Generate email preview text."""
        if newsletter.personalized_insights:
            first_insight = newsletter.personalized_insights[0]
            return f"{first_insight.title}: {first_insight.content[:100]}..."

        if newsletter.sections and newsletter.sections[0].articles:
            first_article = newsletter.sections[0].articles[0]
            return f"Today's highlights: {first_article.content_item.title}..."

        return f"Your personalized newsletter with {newsletter.total_articles} articles"

    def _add_tracking_to_url(
        self, url: str, tracking_data: Optional[Dict[str, str]]
    ) -> str:
        """Add tracking parameters to URLs."""
        if not tracking_data:
            return url

        # Simple implementation - in production, use proper URL tracking
        if "?" in url:
            return f"{url}&utm_source=newsletter&utm_campaign=daily_digest"
        else:
            return f"{url}?utm_source=newsletter&utm_campaign=daily_digest"

    def _generate_unsubscribe_url(self, user_id: str) -> str:
        """Generate unsubscribe URL."""
        return f"https://{self.config.domain}/unsubscribe?user={user_id}"

    def _generate_preferences_url(self, user_id: str) -> str:
        """Generate preferences URL."""
        return f"https://{self.config.domain}/preferences?user={user_id}"

    def _generate_web_version_url(self, user_id: str) -> str:
        """Generate web version URL."""
        return f"https://{self.config.domain}/newsletter/{user_id}/latest"

    async def generate_test_email(self, user_profile: UserProfile) -> EmailContent:
        """Generate a test email for debugging purposes."""
        from src.models.content import (
            ContentSection,
            PersonalizedInsight,
            AnalyzedContent,
            create_content_item,
            ContentSource,
            ContentType,
        )

        # Create test content
        test_article = AnalyzedContent(
            content_item=create_content_item(
                title="Test Article: AI Newsletter Generation",
                url="https://example.com/test-article",
                source=ContentSource.WEB_SCRAPE,
                content_type=ContentType.ARTICLE,
                author="Test Author",
                summary="This is a test article for the AI newsletter system.",
                reading_time_minutes=3,
            ),
            relevance_score=0.9,
            ai_summary="A comprehensive test of the newsletter generation system.",
            quality_score=0.8,
        )

        test_section = ContentSection(
            title="Test Section",
            description="Testing the newsletter system",
            emoji="🧪",
            articles=[test_article],
        )

        test_insight = PersonalizedInsight(
            title="Test Insight",
            content="This is a test personalized insight to verify email generation.",
            confidence_score=0.8,
        )

        test_newsletter = CuratedNewsletter(
            subject_line="Test Newsletter - AI Generation System",
            greeting=f"Hello, {user_profile.name}!",
            sections=[test_section],
            personalized_insights=[test_insight],
            quick_reads=[],
            footer_content="Test newsletter generated by AI system",
            generation_metadata={
                "test_mode": True,
                "generation_time": datetime.now().isoformat(),
            },
        )

        return await self.generate_newsletter_email(test_newsletter, user_profile)

    def validate_email_content(self, email_content: EmailContent) -> bool:
        """Validate email content for common issues."""
        issues = []

        # Check basic requirements
        if not email_content.html:
            issues.append("Missing HTML content")

        if not email_content.text:
            issues.append("Missing text content")

        if not email_content.subject:
            issues.append("Missing subject line")

        # Check size limits
        if email_content.estimated_size_kb > 10000:  # 10MB limit
            issues.append("Email too large")

        # Check for broken links (basic)
        html_links = re.findall(r'href="([^"]*)"', email_content.html)
        for link in html_links:
            if not link.startswith(("http://", "https://", "mailto:", "#")):
                issues.append(f"Potentially broken link: {link}")

        if issues:
            self.logger.warning("Email validation issues", issues=issues)
            return False

        return True