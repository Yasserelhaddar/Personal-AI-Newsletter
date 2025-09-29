"""AI-powered content curation engine using OpenAI LLM."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from src.infrastructure.logging import LoggerMixin
from src.services.openai_service import OpenAIService
from src.models.content import (
    ContentItem,
    AnalyzedContent,
    CuratedNewsletter,
    ContentSection,
    PersonalizedInsight,
    generate_content_sections,
    categorize_content_by_interest,
    estimate_reading_time,
)
from src.models.user import UserProfile


class CurationEngine(LoggerMixin):
    """AI-powered content curation engine."""

    def __init__(self, openai_service: Optional[OpenAIService] = None):
        self.ai_service = openai_service or OpenAIService()
        self.use_fallback = not self.ai_service.available
        self.content_analyzer = ContentAnalyzer(self.ai_service)
        self.newsletter_composer = NewsletterComposer(self.ai_service)

    async def curate_newsletter(
        self,
        raw_content: List[ContentItem],
        user_profile: UserProfile,
        github_activity: Optional[Dict[str, Any]] = None,
    ) -> CuratedNewsletter:
        """Curate a complete newsletter from raw content.

        Args:
            raw_content: Raw content items collected from various sources
            user_profile: User profile with preferences and interests
            github_activity: User's GitHub activity summary

        Returns:
            Curated newsletter ready for email generation

        Raises:
            Exception: If curation fails critically
        """
        self.logger.info(
            "Starting newsletter curation",
            user_id=user_profile.user_id,
            content_count=len(raw_content),
            max_articles=user_profile.max_articles,
        )

        try:
            # Step 1: Analyze content relevance and quality
            self.logger.debug("Analyzing content relevance")
            analyzed_content = await self.content_analyzer.analyze_content_batch(
                raw_content, user_profile
            )

            if not analyzed_content:
                raise Exception("No content passed relevance analysis")

            # Step 2: Select and organize best content
            self.logger.debug("Selecting and organizing content")
            organized_content = await self._organize_content(
                analyzed_content, user_profile
            )

            # Step 3: Generate personalized insights
            self.logger.debug("Generating personalized insights")
            insights = await self._generate_insights(
                organized_content, user_profile, github_activity
            )

            # Step 4: Compose final newsletter
            self.logger.debug("Composing newsletter")
            newsletter = await self.newsletter_composer.compose_newsletter(
                organized_content, insights, user_profile, github_activity
            )

            self.logger.info(
                "Newsletter curation completed",
                user_id=user_profile.user_id,
                total_articles=newsletter.total_articles,
                sections_count=len(newsletter.sections),
                insights_count=len(newsletter.personalized_insights),
            )

            return newsletter

        except Exception as e:
            self.logger.error(
                "Newsletter curation failed",
                user_id=user_profile.user_id,
                error=str(e),
                exc_info=True,
            )
            # Return fallback newsletter
            return await self._create_fallback_newsletter(raw_content, user_profile)

    async def _organize_content(
        self,
        analyzed_content: List[AnalyzedContent],
        user_profile: UserProfile,
    ) -> Dict[str, List[AnalyzedContent]]:
        """Organize analyzed content by themes and interests."""
        # Debug: Check why content is being filtered out
        sample_items = analyzed_content[:3]
        for i, item in enumerate(sample_items):
            self.logger.info(
                f"Content {i+1} analysis",
                title=item.content_item.title[:50],
                relevance=item.relevance_score,
                composite=item.composite_score,
                quality=item.quality_score,
                interest_matches=item.interest_matches,
                is_high_quality=item.is_high_quality
            )

        # Import config for thresholds
        from src.infrastructure.config import ApplicationConfig
        config = ApplicationConfig()

        # Filter high-quality content
        high_quality_content = [
            item for item in analyzed_content
            if item.is_high_quality and item.composite_score >= config.content_composite_score_threshold
        ]

        # Categorize by user interests - allow generous per-category limits
        # The final total will be controlled in newsletter composition
        categorized = categorize_content_by_interest(
            high_quality_content,
            user_profile.interests,
            max_per_category=max(5, user_profile.max_articles // len(user_profile.interests) + 2)
        )

        # Ensure we have enough content
        if sum(len(items) for items in categorized.values()) < 3:
            # Fall back to lower quality threshold
            medium_quality_content = [
                item for item in analyzed_content
                if item.composite_score >= config.content_fallback_score_threshold
            ]
            categorized = categorize_content_by_interest(
                medium_quality_content,
                user_profile.interests,
                max_per_category=max(5, user_profile.max_articles // len(user_profile.interests) + 2)
            )

        return categorized

    async def _generate_insights(
        self,
        organized_content: Dict[str, List[AnalyzedContent]],
        user_profile: UserProfile,
        github_activity: Optional[Dict[str, Any]],
    ) -> List[PersonalizedInsight]:
        """Generate personalized insights from organized content."""
        try:
            # Return empty insights if OpenAI not available
            if self.use_fallback:
                self.logger.info("Skipping insights generation (no OpenAI)")
                return []

            # Collect analyzed content for insights generation
            all_analyzed_content = []
            for items in organized_content.values():
                all_analyzed_content.extend(items)

            # Generate insights using OpenAI
            insights_data = await self.content_analyzer.openai_service.generate_personalized_insights(
                all_analyzed_content, user_profile
            )

            insights = []
            for insight_data in insights_data:
                insight = PersonalizedInsight(
                    title=insight_data.get("title", ""),
                    content=insight_data.get("content", ""),
                    related_articles=insight_data.get("related_articles", []),
                    confidence_score=insight_data.get("confidence_score", 0.0),
                    insight_type=insight_data.get("insight_type", "general"),
                    metadata=insight_data.get("metadata", {}),
                )
                insights.append(insight)

            return insights

        except Exception as e:
            self.logger.warning("Failed to generate insights", error=str(e))
            return []

    async def _create_fallback_newsletter(
        self,
        raw_content: List[ContentItem],
        user_profile: UserProfile,
    ) -> CuratedNewsletter:
        """Create a basic fallback newsletter when AI curation fails."""
        self.logger.warning("Creating fallback newsletter")

        # Simple scoring based on age and basic relevance
        scored_content = []
        for item in raw_content:
            score = 0.5  # Base score

            # Age scoring
            if item.age_hours < 24:
                score += 0.3
            elif item.age_hours < 72:
                score += 0.1

            # Interest matching
            title_lower = item.title.lower()
            for interest in user_profile.interests:
                if interest.lower() in title_lower:
                    score += 0.4
                    break

            # Create basic analyzed content
            analyzed = AnalyzedContent(
                content_item=item,
                relevance_score=score,
                interest_matches=[
                    interest for interest in user_profile.interests
                    if interest.lower() in item.title.lower()
                ],
                quality_score=0.7,  # Default quality
                ai_summary=item.summary or f"Article about {item.title}",
            )
            scored_content.append(analyzed)

        # Sort by score and take top items
        scored_content.sort(key=lambda x: x.composite_score, reverse=True)
        top_content = scored_content[:user_profile.max_articles]

        # Create simple sections
        sections = []
        if top_content:
            sections.append(
                ContentSection(
                    title="Today's Highlights",
                    description="Curated content based on your interests",
                    emoji="⚡",
                    articles=top_content,
                )
            )

        return CuratedNewsletter(
            subject_line=f"Your Daily Digest - {datetime.now().strftime('%B %d')}",
            greeting=f"Good morning, {user_profile.name}!",
            sections=sections,
            personalized_insights=[],
            github_activity=None,
            quick_reads=[],
            trending_repos=[],
            footer_content="Generated by Personal AI Newsletter",
            generation_metadata={
                "fallback_mode": True,
                "curation_engine": "simple",
                "content_sources": list(set(item.content_item.source for item in top_content)),
            },
        )


class ContentAnalyzer(LoggerMixin):
    """Analyzes content relevance, quality, and themes."""

    def __init__(self, openai_service: Optional[OpenAIService] = None):
        self.openai_service = openai_service or OpenAIService()
        self.use_fallback = not self.openai_service.available

    async def analyze_content_batch(
        self,
        content_items: List[ContentItem],
        user_profile: UserProfile,
        batch_size: int = 20,
    ) -> List[AnalyzedContent]:
        """Analyze a batch of content items for relevance and quality."""
        analyzed_content = []

        # Process in batches to manage token usage
        for i in range(0, len(content_items), batch_size):
            batch = content_items[i:i + batch_size]

            # Use OpenAI for intelligent analysis, fallback if not available
            if self.use_fallback:
                self.logger.info("Using fallback content analysis (no OpenAI)")
                fallback_results = self._analyze_batch_simple(batch, user_profile)
                analyzed_content.extend(fallback_results)
                continue

            try:
                batch_results = await self.openai_service.analyze_content_relevance(batch, user_profile)
                analyzed_content.extend(batch_results)
            except Exception as e:
                self.logger.warning(
                    "Batch analysis failed, using fallback",
                    batch_index=i // batch_size,
                    error=str(e),
                )
                # Fallback to simple analysis
                fallback_results = self._analyze_batch_simple(batch, user_profile)
                analyzed_content.extend(fallback_results)

        return analyzed_content

    async def _analyze_batch_with_ai(
        self,
        content_items: List[ContentItem],
        user_profile: UserProfile,
    ) -> List[AnalyzedContent]:
        """Analyze content batch using AI."""
        # Prepare content data for AI analysis
        content_data = []
        for item in content_items:
            content_data.append({
                "title": item.title,
                "url": item.url,
                "source": item.source.value,
                "content_type": item.content_type.value,
                "summary": item.summary or "",
                "author": item.author or "",
                "age_hours": item.age_hours,
                "metadata": item.metadata,
            })

        # Get AI analysis
        analysis_results = await self.ai_client.analyze_content_relevance(
            content_items=content_data,
            user_interests=user_profile.interests,
        )

        # Convert AI results to AnalyzedContent objects
        analyzed_content = []
        for i, result in enumerate(analysis_results):
            if i >= len(content_items):
                break

            analyzed = AnalyzedContent(
                content_item=content_items[i],
                relevance_score=result.get("relevance_score", 0.5),
                interest_matches=result.get("interest_matches", []),
                quality_score=result.get("quality_score", 0.5),
                novelty_score=result.get("novelty_score", 0.5),
                ai_summary=result.get("summary", ""),
                ai_insights=result.get("insights", []),
                extracted_topics=result.get("topics", []),
                analysis_metadata=result.get("metadata", {}),
            )
            analyzed_content.append(analyzed)

        return analyzed_content

    def _analyze_batch_simple(
        self,
        content_items: List[ContentItem],
        user_profile: UserProfile,
    ) -> List[AnalyzedContent]:
        """Simple fallback analysis without AI."""
        analyzed_content = []

        for item in content_items:
            # Simple relevance scoring
            relevance_score = self._calculate_simple_relevance(item, user_profile)

            # Basic quality scoring
            quality_score = self._calculate_simple_quality(item)

            # Interest matching
            interest_matches = []
            title_lower = item.title.lower()
            summary_lower = (item.summary or "").lower()

            for interest in user_profile.interests:
                interest_lower = interest.lower()
                if interest_lower in title_lower or interest_lower in summary_lower:
                    interest_matches.append(interest)

            analyzed = AnalyzedContent(
                content_item=item,
                relevance_score=relevance_score,
                interest_matches=interest_matches,
                quality_score=quality_score,
                novelty_score=0.5,  # Default
                ai_summary=item.summary or f"Content about {item.title}",
                ai_insights=[],
                extracted_topics=interest_matches,
                analysis_metadata={"analysis_method": "simple"},
            )
            analyzed_content.append(analyzed)

        return analyzed_content

    def _calculate_simple_relevance(
        self, item: ContentItem, user_profile: UserProfile
    ) -> float:
        """Calculate simple relevance score."""
        score = 0.3  # Base score

        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()

        # Interest matching
        for interest in user_profile.interests:
            interest_lower = interest.lower()
            if interest_lower in title_lower:
                score += 0.4
            elif interest_lower in summary_lower:
                score += 0.2

        # Age factor
        if item.age_hours < 24:
            score += 0.2
        elif item.age_hours < 72:
            score += 0.1

        return min(1.0, score)

    def _calculate_simple_quality(self, item: ContentItem) -> float:
        """Calculate simple quality score."""
        score = 0.5  # Base score

        # Title length (meaningful titles)
        if 20 <= len(item.title) <= 100:
            score += 0.1

        # Has summary
        if item.summary and len(item.summary) > 50:
            score += 0.1

        # Repository specific quality
        if item.content_type.value == "repository":
            stars = item.metadata.get("stars", 0)
            if stars > 10:
                score += 0.2
            if stars > 100:
                score += 0.1

        # Has author
        if item.author:
            score += 0.1

        return min(1.0, score)


class NewsletterComposer(LoggerMixin):
    """Composes the final newsletter structure."""

    def __init__(self, openai_service: Optional[OpenAIService] = None):
        self.openai_service = openai_service or OpenAIService()
        self.use_fallback = not self.openai_service.available

    async def compose_newsletter(
        self,
        organized_content: Dict[str, List[AnalyzedContent]],
        insights: List[PersonalizedInsight],
        user_profile: UserProfile,
        github_activity: Optional[Dict[str, Any]],
    ) -> CuratedNewsletter:
        """Compose the final newsletter."""
        try:
            # Generate sections from organized content
            sections = generate_content_sections(organized_content)

            # Generate optimized subject line
            subject_line = await self._generate_subject_line(
                organized_content, user_profile
            )

            # Prepare quick reads (shorter articles)
            quick_reads = self._select_quick_reads(organized_content, max_items=3)

            # Generate greeting
            greeting = self._generate_greeting(user_profile)

            newsletter = CuratedNewsletter(
                subject_line=subject_line,
                greeting=greeting,
                sections=sections,
                personalized_insights=insights,
                github_activity=github_activity,
                quick_reads=quick_reads,
                trending_repos=[],
                footer_content=self._generate_footer(),
                generation_metadata={
                    "curation_engine": "ai_powered",
                    "ai_analysis": True,
                    "content_sources": list(set(
                        item.content_item.source
                        for items in organized_content.values()
                        for item in items
                    )),
                    "total_content_analyzed": sum(
                        len(items) for items in organized_content.values()
                    ),
                },
            )

            return newsletter

        except Exception as e:
            self.logger.error("Newsletter composition failed", error=str(e))
            raise

    async def _generate_subject_line(
        self,
        organized_content: Dict[str, List[AnalyzedContent]],
        user_profile: UserProfile,
    ) -> str:
        """Generate an engaging subject line."""
        try:
            # Use default subject line if OpenAI not available
            if self.use_fallback:
                self.logger.info("Using default subject line (no OpenAI)")
                return self._generate_default_subject_line()

            # Create a mock curated newsletter object for the OpenAI service
            from types import SimpleNamespace


            mock_newsletter = SimpleNamespace()
            mock_newsletter.total_articles = sum(len(items) for items in organized_content.values())
            mock_newsletter.sections = []
            mock_newsletter.generated_at = datetime.now()

            # Add sections with articles for context
            for interest, items in organized_content.items():
                section = SimpleNamespace()
                section.articles = []
                for item in items[:3]:  # Top 3 per interest
                    article = SimpleNamespace()
                    article.content_item = item.content_item
                    section.articles.append(article)
                mock_newsletter.sections.append(section)

            subject_line = await self.openai_service.generate_subject_line(
                mock_newsletter, user_profile
            )

            return subject_line if subject_line else self._generate_default_subject_line()

        except Exception as e:
            self.logger.warning("AI subject line generation failed", error=str(e))
            return self._generate_default_subject_line()

    def _generate_default_subject_line(self) -> str:
        """Generate default subject line."""
        current_date = datetime.now().strftime("%B %d")
        return f"Your Daily Intelligence Digest - {current_date}"

    def _select_quick_reads(
        self,
        organized_content: Dict[str, List[AnalyzedContent]],
        max_items: int = 3,
    ) -> List[AnalyzedContent]:
        """Select articles for quick reads section."""
        all_items = []
        for items in organized_content.values():
            all_items.extend(items)

        # Filter for shorter content
        quick_reads = [
            item for item in all_items
            if (item.content_item.reading_time_minutes or 5) <= 3
        ]

        # Sort by score and take top items
        quick_reads.sort(key=lambda x: x.composite_score, reverse=True)
        return quick_reads[:max_items]

    def _generate_greeting(self, user_profile: UserProfile) -> str:
        """Generate personalized greeting."""
        current_hour = datetime.now().hour

        if current_hour < 12:
            greeting = "Good morning"
        elif current_hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        return f"{greeting}, {user_profile.name}!"

    def _generate_footer(self) -> str:
        """Generate newsletter footer."""
        return "Thanks for reading your personalized AI newsletter!"