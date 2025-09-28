"""OpenAI service for intelligent content analysis and generation."""

import json
from typing import Dict, List, Optional, Any

from openai import AsyncOpenAI

from src.infrastructure.config import ApplicationConfig
from src.infrastructure.logging import get_logger
from src.models.content import ContentItem, AnalyzedContent
from src.models.user import UserProfile

logger = get_logger(__name__)


class OpenAIService:
    """Service for OpenAI LLM interactions."""

    def __init__(self, api_key: Optional[str] = None):
        config = ApplicationConfig()
        self.api_key = api_key or config.openai_api_key
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None
        self.available = bool(self.client and self.api_key)

    async def analyze_content_relevance(
        self,
        content_items: List[ContentItem],
        user_profile: UserProfile,
    ) -> List[AnalyzedContent]:
        """Analyze content relevance for user interests using OpenAI."""
        if not self.available:
            logger.warning("OpenAI not available, using fallback analysis")
            return self._fallback_content_analysis(content_items, user_profile)

        try:
            analyzed_content = []

            # Process in batches to avoid token limits
            batch_size = 5
            for i in range(0, len(content_items), batch_size):
                batch = content_items[i:i + batch_size]
                batch_results = await self._analyze_content_batch(batch, user_profile)
                analyzed_content.extend(batch_results)

            logger.info(
                "Content analysis completed",
                analyzed_count=len(analyzed_content),
                avg_relevance=sum(c.relevance_score for c in analyzed_content) / len(analyzed_content) if analyzed_content else 0
            )

            return analyzed_content

        except Exception as e:
            logger.error("OpenAI content analysis failed", error=str(e))
            return self._fallback_content_analysis(content_items, user_profile)

    async def _analyze_content_batch(
        self,
        content_items: List[ContentItem],
        user_profile: UserProfile,
    ) -> List[AnalyzedContent]:
        """Analyze a batch of content items."""

        # Build analysis prompt
        content_summaries = []
        for i, item in enumerate(content_items):
            content_summaries.append(f"""
Article {i+1}:
Title: {item.title}
Summary: {item.summary or 'No summary available'}
Source: {item.source}
Tags: {', '.join(item.tags) if item.tags else 'None'}
""")

        prompt = f"""
Analyze these {len(content_items)} articles for relevance to a user with these interests:

User Interests: {', '.join(user_profile.interests)}
User Interest Weights: {user_profile.interest_weights}

Articles to analyze:
{''.join(content_summaries)}

For each article, provide:
1. Relevance score (0.0-1.0) based on user interests
2. Brief explanation (1-2 sentences) of why it's relevant
3. Key topics that match user interests
4. Suggested priority (high/medium/low)

Return as JSON array with this structure:
[{{
  "article_index": 0,
  "relevance_score": 0.85,
  "explanation": "This article about AI advances directly relates to the user's AI interest...",
  "matching_topics": ["artificial intelligence", "machine learning"],
  "priority": "high"
}}]

Focus on accuracy and be conservative with scores. Only high-quality, genuinely relevant content should score above 0.7.
"""

        try:
            config = ApplicationConfig()
            response = await self.client.chat.completions.create(
                model=config.openai_model,
                messages=[
                    {"role": "system", "content": "You are an expert content analyst who evaluates article relevance for personalized newsletters."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=config.openai_max_tokens // 2,  # Use half for batch analysis
                temperature=config.openai_temperature,
            )

            # Parse AI response
            analysis_text = response.choices[0].message.content

            # Try to extract JSON from response
            try:
                if "```json" in analysis_text:
                    json_start = analysis_text.find("```json") + 7
                    json_end = analysis_text.find("```", json_start)
                    analysis_text = analysis_text[json_start:json_end].strip()

                analysis_results = json.loads(analysis_text)
            except json.JSONDecodeError:
                logger.warning("Failed to parse AI analysis as JSON, using fallback")
                return self._fallback_content_analysis(content_items, user_profile)

            # Convert to AnalyzedContent objects
            analyzed_content = []
            for result in analysis_results:
                if result["article_index"] < len(content_items):
                    item = content_items[result["article_index"]]
                    analyzed_content.append(AnalyzedContent(
                        content_item=item,
                        relevance_score=max(0.0, min(1.0, result["relevance_score"])),
                        ai_summary=result["explanation"],
                        interest_matches=result.get("matching_topics", []),
                        analysis_metadata={
                            "model": "gpt-4o-mini",
                            "analyzed_at": "2024-01-01T00:00:00Z",  # Would be actual timestamp
                            "tokens_used": response.usage.total_tokens if response.usage else 0,
                            "priority": result.get("priority", "medium"),
                        }
                    ))

            return analyzed_content

        except Exception as e:
            logger.error("OpenAI API call failed", error=str(e))
            return self._fallback_content_analysis(content_items, user_profile)

    async def generate_personalized_insights(
        self,
        analyzed_content: List[AnalyzedContent],
        user_profile: UserProfile,
    ) -> List[Dict[str, str]]:
        """Generate personalized insights about the curated content."""
        if not self.available:
            logger.info("OpenAI not available, skipping insights generation")
            return []

        try:
            # Select top content for insights
            top_content = sorted(analyzed_content, key=lambda x: x.relevance_score, reverse=True)[:5]

            if not top_content:
                return []

            content_summaries = []
            for item in top_content:
                content_summaries.append(f"""
- {item.content_item.title}
  Relevance: {item.relevance_score:.2f}
  Topics: {', '.join(item.interest_matches)}
  Explanation: {item.ai_summary or 'No summary available'}
""")

            prompt = f"""
Based on this curated content for a user interested in {', '.join(user_profile.interests)}, generate 2-3 personalized insights:

Content Summary:
{''.join(content_summaries)}

Generate insights that:
1. Connect themes across multiple articles
2. Highlight emerging trends relevant to the user
3. Provide actionable takeaways
4. Are concise (2-3 sentences each)

Return as JSON array:
[{{
  "title": "Emerging AI Trends",
  "content": "Your curated articles reveal three key AI developments this week..."
}}]

Make insights feel personal and valuable to someone with these specific interests.
"""

            config = ApplicationConfig()
            response = await self.client.chat.completions.create(
                model=config.openai_model,
                messages=[
                    {"role": "system", "content": "You are an expert analyst who creates personalized insights from curated content."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=config.openai_max_tokens // 5,  # Use 1/5 for insights
                temperature=config.openai_temperature + 0.1,  # Slightly more creative for insights
            )

            # Parse response
            insights_text = response.choices[0].message.content

            try:
                if "```json" in insights_text:
                    json_start = insights_text.find("```json") + 7
                    json_end = insights_text.find("```", json_start)
                    insights_text = insights_text[json_start:json_end].strip()

                insights = json.loads(insights_text)

                logger.info("Generated personalized insights", count=len(insights))
                return insights

            except json.JSONDecodeError:
                logger.warning("Failed to parse insights JSON")
                return []

        except Exception as e:
            logger.error("Insights generation failed", error=str(e))
            return []

    async def generate_subject_line(
        self,
        newsletter_content: Any,  # CuratedNewsletter object
        user_profile: UserProfile,
    ) -> str:
        """Generate an engaging subject line for the newsletter."""
        if not self.available:
            return f"Your Daily Intelligence Digest - {newsletter_content.generated_at.strftime('%B %d')}"

        try:
            # Extract key themes from the newsletter
            article_titles = []
            for section in newsletter_content.sections:
                for article in section.articles:
                    article_titles.append(article.content_item.title)

            prompt = f"""
Create an engaging email subject line for a personalized newsletter with these characteristics:

User Interests: {', '.join(user_profile.interests)}
Article Count: {newsletter_content.total_articles}
Key Article Titles:
{chr(10).join(f"- {title}" for title in article_titles[:5])}

Requirements:
- 6-8 words maximum
- Personal and engaging
- Reflects the main themes
- Creates curiosity without being clickbait
- Professional tone

Examples of good subject lines:
- "Your AI Weekly: 3 Breakthrough Discoveries"
- "Tech Insights: What's Changing This Week"
- "Your Programming Digest: 4 Game-Changers"

Return only the subject line, no quotes or explanation.
"""

            config = ApplicationConfig()
            response = await self.client.chat.completions.create(
                model=config.openai_model,
                messages=[
                    {"role": "system", "content": "You are an expert email marketer who creates compelling subject lines."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50,  # Short subject lines don't need much
                temperature=config.openai_temperature + 0.2,  # More creative for subject lines
            )

            subject_line = response.choices[0].message.content.strip().strip('"').strip("'")

            logger.info("Generated AI subject line", subject=subject_line)
            return subject_line

        except Exception as e:
            logger.error("Subject line generation failed", error=str(e))
            return f"Your Daily Intelligence Digest - {newsletter_content.generated_at.strftime('%B %d')}"

    def _fallback_content_analysis(
        self,
        content_items: List[ContentItem],
        user_profile: UserProfile,
    ) -> List[AnalyzedContent]:
        """Fallback content analysis when OpenAI is not available."""
        analyzed_content = []

        for item in content_items:
            # Simple keyword matching for relevance
            relevance_score = 0.0
            matching_topics = []

            # Check title and summary for user interests
            text_to_check = f"{item.title} {item.summary or ''}".lower()

            for interest in user_profile.interests:
                if interest.lower() in text_to_check:
                    weight = user_profile.interest_weights.get(interest, 1.0)
                    relevance_score += 0.3 * weight
                    matching_topics.append(interest)

            # Check tags
            for tag in item.tags or []:
                for interest in user_profile.interests:
                    if interest.lower() in tag.lower():
                        relevance_score += 0.2
                        if interest not in matching_topics:
                            matching_topics.append(interest)

            # Normalize score
            relevance_score = min(relevance_score, 1.0)

            # Determine priority
            if relevance_score >= 0.7:
                priority = "high"
            elif relevance_score >= 0.4:
                priority = "medium"
            else:
                priority = "low"

            analyzed_content.append(AnalyzedContent(
                content_item=item,
                relevance_score=relevance_score,
                ai_summary=f"Matches {len(matching_topics)} of your interests: {', '.join(matching_topics[:3])}",
                interest_matches=matching_topics,
                analysis_metadata={
                    "method": "fallback_keyword_matching",
                    "priority": priority
                }
            ))

        logger.info("Fallback content analysis completed", analyzed_count=len(analyzed_content))
        return analyzed_content