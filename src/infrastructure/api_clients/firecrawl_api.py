"""Firecrawl API client for web content scraping."""

import aiohttp
import asyncio
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import structlog

from src.models.content import ContentItem, ContentSource, ContentType, create_content_item
from .rate_limiter import RateLimiter, RateLimitConfig, WorkerPool


class FirecrawlAPIError(Exception):
    """Firecrawl API error."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class FirecrawlAPIClient:
    """Firecrawl API client for web scraping and content extraction."""

    def __init__(self, api_key: Optional[str] = None, rate_limit_config: Optional[RateLimitConfig] = None):
        """Initialize Firecrawl API client.

        Args:
            api_key: Firecrawl API key. If not provided, reads from NEWSLETTER_FIRECRAWL_API_KEY
            rate_limit_config: Rate limiting configuration
        """
        self.api_key = api_key or os.environ.get("NEWSLETTER_FIRECRAWL_API_KEY")
        if not self.api_key:
            raise FirecrawlAPIError("Firecrawl API key not provided")

        self.base_url = "https://api.firecrawl.dev/v1"
        self.logger = structlog.get_logger(__name__)

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Personal-AI-Newsletter/1.0"
        }

        # Initialize rate limiter
        self.rate_limit_config = rate_limit_config or RateLimitConfig(
            requests_per_minute=60,  # Conservative for free tier
            max_concurrent=3,        # Limit concurrent requests
            max_retries=3,
            base_backoff=1.0
        )
        self.rate_limiter = RateLimiter(self.rate_limit_config)

    async def _make_api_request(
        self,
        endpoint: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make rate-limited API request with retry logic."""

        async def _request():
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/{endpoint}",
                    headers=self.headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("data", {})
                    else:
                        error_text = await response.text()
                        raise FirecrawlAPIError(
                            f"Firecrawl API error {response.status}: {error_text}",
                            status_code=response.status
                        )

        return await self.rate_limiter.execute_with_retry(_request)

    async def scrape_articles_batch(self, articles: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Scrape multiple articles using worker pool for better rate limiting.

        Args:
            articles: List of dicts with 'url' and 'title' keys

        Returns:
            List of scraped content results
        """
        if not articles:
            return []

        # Create worker pool
        worker_pool = WorkerPool(self.rate_limiter, worker_count=self.rate_limit_config.max_concurrent)

        # Add all scraping tasks to the pool
        for article in articles:
            await worker_pool.add_task(
                self._scrape_article_content,
                article['url'],
                article['title']
            )

        # Process all tasks with rate limiting
        results = await worker_pool.process_all()
        return [r for r in results if r is not None]

    async def scrape_url(
        self,
        url: str,
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
        include_tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        wait_for: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Scrape a single URL.

        Args:
            url: URL to scrape
            formats: List of formats to extract (markdown, html, links, screenshot)
            only_main_content: Extract only main content, ignore navigation/ads
            include_tags: HTML tags to include
            exclude_tags: HTML tags to exclude
            wait_for: Time to wait before scraping (ms)
            timeout: Request timeout (ms)

        Returns:
            Scraped content in requested formats

        Raises:
            FirecrawlAPIError: If scraping fails
        """
        payload = {
            "url": url,
            "formats": formats or ["markdown"],
            "onlyMainContent": only_main_content,
        }

        if include_tags:
            payload["includeTags"] = include_tags

        if exclude_tags:
            payload["excludeTags"] = exclude_tags

        if wait_for:
            payload["waitFor"] = wait_for

        if timeout:
            payload["timeout"] = timeout

        try:
            return await self._make_api_request("scrape", payload)
        except Exception as e:
            raise FirecrawlAPIError(f"Failed to scrape URL {url}: {str(e)}")

    async def crawl_website(
        self,
        url: str,
        max_pages: int = 10,
        include_paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        formats: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Crawl a website starting from a URL.

        Args:
            url: Starting URL for crawling
            max_pages: Maximum number of pages to crawl
            include_paths: URL patterns to include
            exclude_paths: URL patterns to exclude
            formats: Content formats to extract
            limit: Maximum number of results

        Returns:
            List of crawled pages with content

        Raises:
            FirecrawlAPIError: If crawling fails
        """
        payload = {
            "url": url,
            "crawlerOptions": {
                "maxDepth": 2,
                "limit": max_pages,
            },
            "pageOptions": {
                "formats": formats or ["markdown"],
                "onlyMainContent": True,
            }
        }

        if include_paths:
            payload["crawlerOptions"]["includePaths"] = include_paths

        if exclude_paths:
            payload["crawlerOptions"]["excludePaths"] = exclude_paths

        if limit:
            payload["crawlerOptions"]["limit"] = limit

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/crawl",
                    headers=self.headers,
                    json=payload
                ) as response:

                    if response.status == 200:
                        result = await response.json()
                        return result.get("data", [])
                    else:
                        error_text = await response.text()
                        raise FirecrawlAPIError(
                            f"Firecrawl API error {response.status}: {error_text}",
                            status_code=response.status
                        )

        except aiohttp.ClientError as e:
            raise FirecrawlAPIError(f"HTTP client error: {str(e)}")
        except Exception as e:
            raise FirecrawlAPIError(f"Failed to crawl website {url}: {str(e)}")

    async def search_web(
        self,
        query: str,
        max_results: int = 10,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        formats: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search the web and scrape results.

        Args:
            query: Search query
            max_results: Maximum number of results
            include_domains: Domains to include in search
            exclude_domains: Domains to exclude from search
            formats: Content formats to extract

        Returns:
            List of search results with scraped content

        Raises:
            FirecrawlAPIError: If search fails
        """
        payload = {
            "query": query,
            "pageOptions": {
                "formats": formats or ["markdown"],
                "onlyMainContent": True,
            },
            "searchOptions": {
                "limit": max_results,
            }
        }

        if include_domains:
            payload["searchOptions"]["includeDomains"] = include_domains

        if exclude_domains:
            payload["searchOptions"]["excludeDomains"] = exclude_domains

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/search",
                    headers=self.headers,
                    json=payload
                ) as response:

                    if response.status == 200:
                        result = await response.json()
                        return result.get("data", [])
                    else:
                        error_text = await response.text()
                        raise FirecrawlAPIError(
                            f"Firecrawl API error {response.status}: {error_text}",
                            status_code=response.status
                        )

        except aiohttp.ClientError as e:
            raise FirecrawlAPIError(f"HTTP client error: {str(e)}")
        except Exception as e:
            raise FirecrawlAPIError(f"Failed to search web for '{query}': {str(e)}")

    async def scrape_hacker_news(self, interest: str, max_items: int = 10) -> List[ContentItem]:
        """Scrape Hacker News for content related to an interest using discovery + extraction pattern.

        Args:
            interest: Interest/topic to search for
            max_items: Maximum number of items to return

        Returns:
            List of content items from Hacker News with full content
        """
        try:
            # Step 1: Use HN API for discovery
            encoded_interest = quote_plus(interest)
            search_url = f"https://hn.algolia.com/api/v1/search?query={encoded_interest}&tags=story&hitsPerPage={max_items}"

            self.logger.info("Discovering HN articles", url=search_url, interest=interest)

            async with aiohttp.ClientSession() as session:
                headers = {"User-Agent": "Personal-AI-Newsletter/1.0"}
                async with session.get(search_url, headers=headers) as response:
                    if response.status != 200:
                        self.logger.warning(f"Hacker News API returned status {response.status}")
                        return []

                    data = await response.json()

            content_items = []
            hits = data.get("hits", [])

            self.logger.info("HN discovery complete", hits_count=len(hits), interest=interest)

            # Step 2: Use Firecrawl to scrape full content from discovered URLs
            for hit in hits:
                title = hit.get("title", "")
                url = hit.get("url", "")
                author = hit.get("author", "")
                created_at = hit.get("created_at", "")

                if not url:  # Skip text posts without URLs
                    continue

                # Extract full article content using Firecrawl
                scraped_content = await self._scrape_article_content(url, title)

                content_item = create_content_item(
                    title=title,
                    url=url,
                    source=ContentSource.HACKER_NEWS,
                    content_type=ContentType.ARTICLE,
                    author=author,
                    summary=scraped_content.get("summary", "")[:500] if scraped_content else "",
                    metadata={
                        "hacker_news_id": hit.get("objectID"),
                        "points": hit.get("points", 0),
                        "num_comments": hit.get("num_comments", 0),
                        "created_at": created_at,
                        "full_content": scraped_content.get("content", "") if scraped_content else "",
                        "reading_time_minutes": scraped_content.get("reading_time_minutes", 0) if scraped_content else 0,
                    }
                )
                content_items.append(content_item)

            self.logger.info("HN content collection complete", count=len(content_items), interest=interest)
            return content_items

        except Exception as e:
            self.logger.error("Failed to scrape Hacker News", interest=interest, error=str(e), exc_info=True)
            return []

    async def scrape_reddit(self, subreddit: str, max_items: int = 10) -> List[ContentItem]:
        """Scrape Reddit for content from a specific subreddit using discovery + extraction pattern.

        Args:
            subreddit: Subreddit name (without r/)
            max_items: Maximum number of items to return

        Returns:
            List of content items from Reddit with full content
        """
        try:
            # Step 1: Use Reddit API for discovery
            reddit_url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={max_items}"

            self.logger.info("Discovering Reddit articles", url=reddit_url, subreddit=subreddit)

            async with aiohttp.ClientSession() as session:
                headers = {"User-Agent": "Personal-AI-Newsletter/1.0"}
                async with session.get(reddit_url, headers=headers) as response:
                    if response.status != 200:
                        self.logger.warning(f"Reddit API returned status {response.status}")
                        return []

                    data = await response.json()

            content_items = []
            posts = data.get("data", {}).get("children", [])

            self.logger.info("Reddit discovery complete", posts_count=len(posts), subreddit=subreddit)

            # Step 2: Use Firecrawl to scrape full content from discovered URLs
            for post_data in posts:
                post = post_data.get("data", {})

                title = post.get("title", "")
                url = post.get("url", "")
                author = post.get("author", "")
                created_utc = post.get("created_utc", 0)

                # Skip self posts without external URLs
                if url.startswith(f"https://www.reddit.com/r/{subreddit}"):
                    continue

                # Extract full article content using Firecrawl
                scraped_content = await self._scrape_article_content(url, title)

                content_item = create_content_item(
                    title=title,
                    url=url,
                    source=ContentSource.REDDIT,
                    content_type=ContentType.DISCUSSION,
                    author=author,
                    summary=scraped_content.get("summary", "")[:500] if scraped_content else post.get("selftext", "")[:500],
                    metadata={
                        "subreddit": subreddit,
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "created_utc": created_utc,
                        "self_text": post.get("selftext", ""),
                        "full_content": scraped_content.get("content", "") if scraped_content else "",
                        "reading_time_minutes": scraped_content.get("reading_time_minutes", 0) if scraped_content else 0,
                    }
                )
                content_items.append(content_item)

            self.logger.info("Reddit content collection complete", count=len(content_items), subreddit=subreddit)
            return content_items

        except Exception as e:
            self.logger.warning("Failed to scrape Reddit", subreddit=subreddit, error=str(e))
            return []

    async def scrape_reddit_from_url(self, reddit_url: str, max_items: int = 10) -> List[ContentItem]:
        """Scrape Reddit content from a specific URL.

        Args:
            reddit_url: Full Reddit JSON URL (e.g., combined subreddits)
            max_items: Maximum number of items to return

        Returns:
            List of content items from Reddit
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"User-Agent": "Personal-AI-Newsletter/1.0"}
                async with session.get(reddit_url, headers=headers) as response:
                    if response.status != 200:
                        self.logger.warning(f"Reddit API returned status {response.status}")
                        return []

                    data = await response.json()

            content_items = []
            posts = data.get("data", {}).get("children", [])[:max_items]

            for post_data in posts:
                post = post_data.get("data", {})
                if not post.get("title"):
                    continue

                content_item = create_content_item(
                    title=post["title"],
                    url=f"https://reddit.com{post['permalink']}",
                    source=ContentSource.REDDIT,
                    content_type=ContentType.DISCUSSION,
                    summary=post.get("selftext", "")[:500] if post.get("selftext") else None,
                    author=post.get("author"),
                    metadata={
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "subreddit": post.get("subreddit"),
                        "created_utc": post.get("created_utc"),
                    },
                )
                content_items.append(content_item)

            self.logger.info(
                "Scraped Reddit from URL",
                url=reddit_url,
                collected=len(content_items)
            )
            return content_items

        except Exception as e:
            self.logger.warning("Failed to scrape Reddit from URL", url=reddit_url, error=str(e))
            return []

    async def _scrape_article_content(self, url: str, title: str) -> Optional[Dict[str, Any]]:
        """Helper method to scrape article content using Firecrawl API.

        Args:
            url: Article URL to scrape
            title: Article title for logging

        Returns:
            Scraped content with summary and metadata, or None if failed
        """
        try:
            self.logger.info("Scraping article with Firecrawl API", url=url, title=title[:50])

            result = await self.scrape_url(
                url,
                formats=["markdown"],
                only_main_content=True,
                exclude_tags=["nav", "footer", "aside", "script", "style", "header"]
            )

            if not result or not result.get("markdown"):
                self.logger.warning("Firecrawl API returned no content", url=url)
                return None

            markdown_content = result.get("markdown", "")

            # Extract reading time estimate
            word_count = len(markdown_content.split()) if markdown_content else 0
            reading_time = max(1, round(word_count / 200))  # Average reading speed

            # Create summary from first paragraph
            summary = ""
            if markdown_content:
                lines = markdown_content.split('\n')
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('*'):
                        summary = line[:300]
                        break

            self.logger.info("Firecrawl API scraping successful", url=url, word_count=word_count)

            return {
                "content": markdown_content,
                "summary": summary,
                "word_count": word_count,
                "reading_time_minutes": reading_time,
                "metadata": result.get("metadata", {}),
            }

        except FirecrawlAPIError as e:
            self.logger.warning("Firecrawl API error", url=url, error=str(e))
            return None
        except Exception as e:
            self.logger.warning("Failed to scrape article", url=url, error=str(e))
            return None