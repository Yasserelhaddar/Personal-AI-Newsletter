"""Content collection service with multi-source aggregation."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from src.infrastructure.logging import LoggerMixin
from src.infrastructure.api_clients import FirecrawlAPIClient
from src.infrastructure.mcp_clients import GitHubClient
from src.models.content import ContentItem, ContentSource, ContentType, create_content_item
from src.models.user import UserProfile


class ContentCollectionService(LoggerMixin):
    """Service for collecting content from multiple sources."""

    def __init__(
        self,
        firecrawl_client: Optional[FirecrawlAPIClient] = None,
        github_client: Optional[GitHubClient] = None,
        max_concurrent: int = 5,
    ):
        self.firecrawl_client = firecrawl_client
        self.github_client = github_client
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self.use_fallback = firecrawl_client is None or github_client is None

    async def collect_content_for_user(
        self,
        user_profile: UserProfile,
        max_items_per_source: int = None,
    ) -> List[ContentItem]:
        """Collect content for a specific user based on their interests.

        Args:
            user_profile: User profile with interests and preferences
            max_items_per_source: Maximum items to collect per source

        Returns:
            List of collected content items
        """
        from src.infrastructure.config import ApplicationConfig
        config = ApplicationConfig()

        if max_items_per_source is None:
            max_items_per_source = config.max_items_per_source

        self.logger.info(
            "Starting content collection",
            user_id=user_profile.user_id,
            interests=user_profile.interests,
            max_items_per_source=max_items_per_source,
        )

        all_content = []
        collection_tasks = []

        # Create collection tasks for each interest and source combination
        for interest in user_profile.interests:
            if "github" in user_profile.content_types or user_profile.include_github_activity:
                collection_tasks.append(
                    self._collect_github_content(interest, max_items_per_source)
                )

            if "articles" in user_profile.content_types:
                collection_tasks.append(
                    self._collect_hacker_news_content(interest, max_items_per_source)
                )
                collection_tasks.append(
                    self._collect_reddit_content(interest, max_items_per_source)
                )

        # Add user-specific GitHub activity if enabled
        if user_profile.include_github_activity and user_profile.github_username:
            collection_tasks.append(
                self._collect_user_github_activity(user_profile.github_username)
            )

        # Execute all collection tasks concurrently
        self.logger.info("Executing collection tasks", task_count=len(collection_tasks))

        try:
            results = await asyncio.gather(*collection_tasks, return_exceptions=True)

            # Process results and handle exceptions
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self.logger.error(
                        "Collection task failed",
                        task_index=i,
                        error=str(result),
                        exc_info=True,
                    )
                elif isinstance(result, list):
                    if len(result) == 0:
                        self.logger.warning(
                            "Collection task returned no content",
                            task_index=i,
                        )
                    else:
                        self.logger.info(
                            "Collection task successful",
                            task_index=i,
                            items_collected=len(result),
                        )
                    all_content.extend(result)
                else:
                    self.logger.warning(
                        "Collection task returned unexpected result type",
                        task_index=i,
                        result_type=type(result).__name__,
                    )

            # Remove duplicates and filter content
            unique_content = self._deduplicate_content(all_content)
            filtered_content = self._filter_content(unique_content, user_profile)

            self.logger.info(
                "Content collection completed",
                user_id=user_profile.user_id,
                total_collected=len(all_content),
                unique_items=len(unique_content),
                filtered_items=len(filtered_content),
            )

            return filtered_content

        except Exception as e:
            self.logger.error(
                "Content collection failed",
                user_id=user_profile.user_id,
                error=str(e),
                exc_info=True,
            )
            return []

    async def _collect_github_content(
        self, interest: str, max_items: int
    ) -> List[ContentItem]:
        """Collect GitHub repositories related to an interest."""
        async with self._semaphore:
            try:
                self.logger.debug("Collecting GitHub content", interest=interest)
                if self.github_client is None:
                    return self._get_fallback_github_content(interest, max_items)
                return await self.github_client.collect_content_for_interest(
                    interest, max_items
                )
            except Exception as e:
                self.logger.warning(
                    "Failed to collect GitHub content",
                    interest=interest,
                    error=str(e),
                )
                return self._get_fallback_github_content(interest, max_items)

    async def _collect_hacker_news_content(
        self, interest: str, max_items: int
    ) -> List[ContentItem]:
        """Collect Hacker News articles related to an interest."""
        async with self._semaphore:
            try:
                self.logger.debug("Collecting Hacker News content", interest=interest)
                if self.firecrawl_client is None:
                    return self._get_fallback_hacker_news_content(interest, max_items)
                return await self.firecrawl_client.scrape_hacker_news(
                    interest, max_items
                )
            except Exception as e:
                self.logger.warning(
                    "Failed to collect Hacker News content",
                    interest=interest,
                    error=str(e),
                )
                return self._get_fallback_hacker_news_content(interest, max_items)

    async def _collect_reddit_content(
        self, interest: str, max_items: int
    ) -> List[ContentItem]:
        """Collect Reddit posts related to an interest."""
        async with self._semaphore:
            try:
                self.logger.debug("Collecting Reddit content", interest=interest)

                # Map interests to subreddit names
                subreddit_map = {
                    "artificial intelligence": ["MachineLearning", "artificial", "ArtificialIntelligence"],
                    "ai": ["MachineLearning", "artificial", "ArtificialIntelligence"],
                    "machine learning": ["MachineLearning", "learnmachinelearning"],
                    "python": ["Python", "learnpython"],
                    "programming": ["programming", "compsci"],
                    "startup": ["startups", "entrepreneur"],
                    "climate": ["climatechange", "environment"],
                    "technology": ["technology", "tech"],
                    "web development": ["webdev", "javascript"],
                    "data science": ["datascience", "statistics"],
                }

                # Find relevant subreddits
                relevant_subreddits = []
                interest_lower = interest.lower()

                # Direct mapping
                if interest_lower in subreddit_map:
                    relevant_subreddits.extend(subreddit_map[interest_lower])
                else:
                    # Partial matching
                    for key, subreddits in subreddit_map.items():
                        if any(word in interest_lower for word in key.split()):
                            relevant_subreddits.extend(subreddits)

                # Default to programming subreddit if no match
                if not relevant_subreddits:
                    relevant_subreddits = ["programming"]

                # Check if we have a specific configured URL for this interest
                from src.infrastructure.config import ApplicationConfig
                config = ApplicationConfig()

                if self.firecrawl_client is None:
                    return self._get_fallback_reddit_content(interest, max_items)

                # Use specific configured URLs for AI and Computer Vision
                if "ai" in interest_lower or "artificial" in interest_lower or "machine learning" in interest_lower:
                    return await self.firecrawl_client.scrape_reddit_from_url(
                        config.reddit_ai_subreddits_url, max_items
                    )
                elif "computer vision" in interest_lower or "vision" in interest_lower:
                    return await self.firecrawl_client.scrape_reddit_from_url(
                        config.reddit_computer_vision_url, max_items
                    )

                # Fall back to single subreddit approach for other interests
                subreddit = relevant_subreddits[0]
                return await self.firecrawl_client.scrape_reddit(subreddit, max_items)

            except Exception as e:
                self.logger.warning(
                    "Failed to collect Reddit content",
                    interest=interest,
                    error=str(e),
                )
                return self._get_fallback_reddit_content(interest, max_items)

    async def _collect_user_github_activity(self, username: str) -> List[ContentItem]:
        """Collect user's GitHub activity as content items."""
        async with self._semaphore:
            try:
                self.logger.debug("Collecting user GitHub activity", username=username)

                if self.github_client is None:
                    return self._get_fallback_user_github_content(username)

                activity_summary = await self.github_client.get_user_activity_summary(
                    username
                )

                content_items = []

                # Convert recent repositories to content items
                for repo in activity_summary.get("recent_repositories", []):
                    content_item = create_content_item(
                        title=f"Your Repository: {repo['name']}",
                        url=f"https://github.com/{repo['full_name']}",
                        source=ContentSource.GITHUB,
                        content_type=ContentType.REPOSITORY,
                        author=username,
                        summary=repo.get("description", ""),
                        metadata={
                            **repo,
                            "user_owned": True,
                            "activity_type": "user_repository",
                        }
                    )
                    content_items.append(content_item)

                return content_items

            except Exception as e:
                self.logger.warning(
                    "Failed to collect user GitHub activity",
                    username=username,
                    error=str(e),
                )
                return self._get_fallback_user_github_content(username)

    def _get_fallback_github_content(self, interest: str, max_items: int) -> List[ContentItem]:
        """Generate fallback GitHub content when client is unavailable."""
        self.logger.info("Using fallback GitHub content", interest=interest)

        # Sample GitHub repositories based on interest
        sample_repos = {
            "artificial intelligence": [
                {"name": "transformers", "full_name": "huggingface/transformers", "description": "State-of-the-art Machine Learning for PyTorch, TensorFlow, and JAX.", "stars": 132000},
                {"name": "pytorch", "full_name": "pytorch/pytorch", "description": "Tensors and Dynamic neural networks in Python with strong GPU acceleration", "stars": 82000},
                {"name": "tensorflow", "full_name": "tensorflow/tensorflow", "description": "An Open Source Machine Learning Framework for Everyone", "stars": 185000},
            ],
            "machine learning": [
                {"name": "scikit-learn", "full_name": "scikit-learn/scikit-learn", "description": "Machine learning library for Python", "stars": 59000},
                {"name": "pandas", "full_name": "pandas-dev/pandas", "description": "Flexible and powerful data analysis / manipulation library for Python", "stars": 43000},
                {"name": "numpy", "full_name": "numpy/numpy", "description": "The fundamental package for scientific computing with Python", "stars": 27000},
            ],
            "python": [
                {"name": "cpython", "full_name": "python/cpython", "description": "The Python programming language", "stars": 62000},
                {"name": "requests", "full_name": "psf/requests", "description": "A simple, yet elegant, HTTP library.", "stars": 52000},
                {"name": "flask", "full_name": "pallets/flask", "description": "The Python micro framework for building web applications.", "stars": 67000},
            ],
            "programming": [
                {"name": "vscode", "full_name": "microsoft/vscode", "description": "Visual Studio Code", "stars": 163000},
                {"name": "react", "full_name": "facebook/react", "description": "The library for web and native user interfaces.", "stars": 228000},
                {"name": "vue", "full_name": "vuejs/vue", "description": "Vue.js is a progressive, incrementally-adoptable JavaScript framework", "stars": 207000},
            ],
        }

        # Get relevant repos for the interest
        interest_lower = interest.lower()
        repos = []

        # Direct match
        if interest_lower in sample_repos:
            repos = sample_repos[interest_lower]
        else:
            # Partial matching
            for key, sample_list in sample_repos.items():
                if any(word in interest_lower for word in key.split()):
                    repos = sample_list
                    break

        # Default to programming if no match
        if not repos:
            repos = sample_repos["programming"]

        # Convert to ContentItem objects
        content_items = []
        for i, repo in enumerate(repos[:max_items]):
            content_item = create_content_item(
                title=f"Trending: {repo['name']}",
                url=f"https://github.com/{repo['full_name']}",
                source=ContentSource.GITHUB,
                content_type=ContentType.REPOSITORY,
                author=repo['full_name'].split('/')[0],
                summary=repo['description'],
                metadata={
                    "stars": repo['stars'],
                    "fallback_content": True,
                    "interest": interest,
                }
            )
            content_items.append(content_item)

        return content_items

    def _get_fallback_hacker_news_content(self, interest: str, max_items: int) -> List[ContentItem]:
        """Generate fallback Hacker News content when client is unavailable."""
        self.logger.info("Using fallback Hacker News content", interest=interest)

        # Sample articles based on interest
        sample_articles = {
            "artificial intelligence": [
                {"title": "GPT-4 and the Future of AI Development", "url": "https://example.com/gpt4-future", "author": "techwriter"},
                {"title": "Understanding Large Language Models", "url": "https://example.com/llm-guide", "author": "airesearcher"},
                {"title": "AI Ethics in Production Systems", "url": "https://example.com/ai-ethics", "author": "ethicsexpert"},
            ],
            "machine learning": [
                {"title": "MLOps Best Practices for 2024", "url": "https://example.com/mlops-2024", "author": "mlenginer"},
                {"title": "Building Robust ML Pipelines", "url": "https://example.com/ml-pipelines", "author": "dataenginer"},
                {"title": "Feature Engineering at Scale", "url": "https://example.com/feature-eng", "author": "datascientsit"},
            ],
            "python": [
                {"title": "Python 3.12 Performance Improvements", "url": "https://example.com/python312", "author": "pythondev"},
                {"title": "Async Python Best Practices", "url": "https://example.com/async-python", "author": "pythonista"},
                {"title": "Building Microservices with FastAPI", "url": "https://example.com/fastapi", "author": "webdev"},
            ],
            "programming": [
                {"title": "The Evolution of Software Architecture", "url": "https://example.com/software-arch", "author": "architect"},
                {"title": "Clean Code Principles for 2024", "url": "https://example.com/clean-code", "author": "coder"},
                {"title": "Developer Productivity Tools", "url": "https://example.com/dev-tools", "author": "productivity"},
            ],
        }

        # Get relevant articles for the interest
        interest_lower = interest.lower()
        articles = []

        # Direct match
        if interest_lower in sample_articles:
            articles = sample_articles[interest_lower]
        else:
            # Partial matching
            for key, sample_list in sample_articles.items():
                if any(word in interest_lower for word in key.split()):
                    articles = sample_list
                    break

        # Default to programming if no match
        if not articles:
            articles = sample_articles["programming"]

        # Convert to ContentItem objects
        content_items = []
        for i, article in enumerate(articles[:max_items]):
            content_item = create_content_item(
                title=article['title'],
                url=article['url'],
                source=ContentSource.HACKER_NEWS,
                content_type=ContentType.ARTICLE,
                author=article['author'],
                summary=f"Interesting article about {interest} from Hacker News community.",
                metadata={
                    "fallback_content": True,
                    "interest": interest,
                    "score": 100 - i * 10,  # Decreasing score
                }
            )
            content_items.append(content_item)

        return content_items

    def _get_fallback_reddit_content(self, interest: str, max_items: int) -> List[ContentItem]:
        """Generate fallback Reddit content when client is unavailable."""
        self.logger.info("Using fallback Reddit content", interest=interest)

        # Sample Reddit posts based on interest
        sample_posts = {
            "artificial intelligence": [
                {"title": "What's the best way to get started with AI in 2024?", "author": "ai_beginner", "subreddit": "MachineLearning"},
                {"title": "Discussion: Current state of AGI research", "author": "researcher123", "subreddit": "artificial"},
                {"title": "Show HN: Built an AI chatbot for customer service", "author": "startup_founder", "subreddit": "ArtificialIntelligence"},
            ],
            "machine learning": [
                {"title": "Best ML courses for beginners?", "author": "student_ml", "subreddit": "MachineLearning"},
                {"title": "How to handle overfitting in deep learning", "author": "ml_practitioner", "subreddit": "learnmachinelearning"},
                {"title": "MLOps tools comparison 2024", "author": "data_engineer", "subreddit": "MachineLearning"},
            ],
            "python": [
                {"title": "Python project structure best practices", "author": "python_dev", "subreddit": "Python"},
                {"title": "Learning Python: What comes after the basics?", "author": "newbie_coder", "subreddit": "learnpython"},
                {"title": "FastAPI vs Django: Which to choose?", "author": "web_developer", "subreddit": "Python"},
            ],
            "programming": [
                {"title": "What programming language should I learn first?", "author": "coding_newbie", "subreddit": "programming"},
                {"title": "Clean architecture principles explained", "author": "senior_dev", "subreddit": "compsci"},
                {"title": "Remote work tips for developers", "author": "remote_worker", "subreddit": "programming"},
            ],
        }

        # Get relevant posts for the interest
        interest_lower = interest.lower()
        posts = []

        # Direct match
        if interest_lower in sample_posts:
            posts = sample_posts[interest_lower]
        else:
            # Partial matching
            for key, sample_list in sample_posts.items():
                if any(word in interest_lower for word in key.split()):
                    posts = sample_list
                    break

        # Default to programming if no match
        if not posts:
            posts = sample_posts["programming"]

        # Convert to ContentItem objects
        content_items = []
        for i, post in enumerate(posts[:max_items]):
            content_item = create_content_item(
                title=post['title'],
                url=f"https://reddit.com/r/{post['subreddit']}/comments/example{i}",
                source=ContentSource.REDDIT,
                content_type=ContentType.DISCUSSION,
                author=post['author'],
                summary=f"Community discussion about {interest} from r/{post['subreddit']}.",
                metadata={
                    "fallback_content": True,
                    "interest": interest,
                    "subreddit": post['subreddit'],
                    "upvotes": 150 - i * 20,  # Decreasing upvotes
                }
            )
            content_items.append(content_item)

        return content_items

    def _get_fallback_user_github_content(self, username: str) -> List[ContentItem]:
        """Generate fallback user GitHub content when client is unavailable."""
        self.logger.info("Using fallback user GitHub content", username=username)

        # Sample user repositories
        sample_repos = [
            {"name": "my-awesome-project", "description": "A cool project I'm working on"},
            {"name": "learning-python", "description": "My Python learning journey"},
            {"name": "portfolio-website", "description": "Personal portfolio and blog"},
        ]

        content_items = []
        for i, repo in enumerate(sample_repos):
            content_item = create_content_item(
                title=f"Your Repository: {repo['name']}",
                url=f"https://github.com/{username}/{repo['name']}",
                source=ContentSource.GITHUB,
                content_type=ContentType.REPOSITORY,
                author=username,
                summary=repo['description'],
                metadata={
                    "user_owned": True,
                    "activity_type": "user_repository",
                    "fallback_content": True,
                    "stars": i + 1,  # Small number of stars for personal repos
                }
            )
            content_items.append(content_item)

        return content_items

    def _deduplicate_content(self, content_items: List[ContentItem]) -> List[ContentItem]:
        """Remove duplicate content items based on URL and content hash."""
        seen_urls: Set[str] = set()
        seen_hashes: Set[str] = set()
        unique_content = []

        for item in content_items:
            # Check for URL duplicates
            if item.url in seen_urls:
                continue

            # Check for content hash duplicates
            if item.content_hash in seen_hashes:
                continue

            seen_urls.add(item.url)
            seen_hashes.add(item.content_hash)
            unique_content.append(item)

        self.logger.debug(
            "Content deduplication",
            original_count=len(content_items),
            unique_count=len(unique_content),
            duplicates_removed=len(content_items) - len(unique_content),
        )

        return unique_content

    def _filter_content(
        self, content_items: List[ContentItem], user_profile: UserProfile
    ) -> List[ContentItem]:
        """Filter content based on user preferences and quality criteria."""
        filtered_content = []

        for item in content_items:
            # Filter by content type preferences
            if not self._matches_content_type_preference(item, user_profile):
                continue

            # Filter by quality criteria
            if not self._meets_quality_criteria(item):
                continue

            # Filter by age (content should be relatively recent)
            if item.age_hours > 168:  # Older than 1 week
                continue

            filtered_content.append(item)

        # Sort by relevance and recency
        filtered_content.sort(
            key=lambda x: (
                self._calculate_relevance_score(x, user_profile),
                -x.age_hours,  # Negative for recent-first sorting
            ),
            reverse=True,
        )

        # Limit to reasonable number per user
        max_total_items = user_profile.max_articles * 3  # Allow for curation filtering
        filtered_content = filtered_content[:max_total_items]

        self.logger.debug(
            "Content filtering",
            original_count=len(content_items),
            filtered_count=len(filtered_content),
            max_allowed=max_total_items,
        )

        return filtered_content

    def _matches_content_type_preference(
        self, item: ContentItem, user_profile: UserProfile
    ) -> bool:
        """Check if content type matches user preferences."""
        content_type_map = {
            ContentType.ARTICLE: "articles",
            ContentType.VIDEO: "videos",
            ContentType.PAPER: "papers",
            ContentType.DISCUSSION: "discussions",
            ContentType.REPOSITORY: "github",
            ContentType.NEWS: "articles",
            ContentType.BLOG_POST: "articles",
        }

        preferred_type = content_type_map.get(item.content_type)
        return preferred_type in user_profile.content_types

    def _meets_quality_criteria(self, item: ContentItem) -> bool:
        """Check if content meets basic quality criteria."""
        # Title should be meaningful
        if len(item.title) < 10:
            return False

        # Should have a valid URL
        if not item.url or not item.url.startswith(("http://", "https://")):
            return False

        # GitHub repositories should have some activity
        if item.content_type == ContentType.REPOSITORY:
            stars = item.metadata.get("stars", 0)
            if stars < 5:  # Minimum star threshold
                return False

        return True

    def _calculate_relevance_score(
        self, item: ContentItem, user_profile: UserProfile
    ) -> float:
        """Calculate relevance score for content item."""
        score = 0.0

        # Interest matching (basic keyword matching)
        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()

        for interest in user_profile.interests:
            interest_lower = interest.lower()
            if interest_lower in title_lower:
                score += 2.0
            elif interest_lower in summary_lower:
                score += 1.0

        # Boost for user's own content
        if item.metadata.get("user_owned"):
            score += 3.0

        # Quality indicators
        if item.content_type == ContentType.REPOSITORY:
            stars = item.metadata.get("stars", 0)
            score += min(2.0, stars / 100)  # Max 2 points for stars

        # Recency boost
        if item.age_hours < 24:
            score += 1.0
        elif item.age_hours < 72:
            score += 0.5

        return score

    async def get_trending_content(
        self, languages: Optional[List[str]] = None, max_items: int = 10
    ) -> List[ContentItem]:
        """Get currently trending content across sources.

        Args:
            languages: Programming languages to focus on
            max_items: Maximum items to return

        Returns:
            List of trending content items
        """
        try:
            trending_content = []

            # Get trending GitHub repositories
            if languages:
                for language in languages:
                    repos = await self.github_client.get_trending_in_language(
                        language, max_items // len(languages)
                    )
                    trending_content.extend(repos)
            else:
                repos = await self.github_client.get_trending_repositories(
                    per_page=max_items
                )
                for repo in repos:
                    content_item = create_content_item(
                        title=f"Trending: {repo.get('name', '')}",
                        url=repo.get("html_url", ""),
                        source=ContentSource.GITHUB,
                        content_type=ContentType.REPOSITORY,
                        author=repo.get("owner", {}).get("login", ""),
                        summary=repo.get("description", ""),
                        metadata={
                            "stars": repo.get("stargazers_count", 0),
                            "trending_period": "daily",
                        }
                    )
                    trending_content.append(content_item)

            return trending_content[:max_items]

        except Exception as e:
            self.logger.error("Failed to get trending content", error=str(e))
            return []