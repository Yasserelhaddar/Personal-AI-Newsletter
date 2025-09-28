"""GitHub MCP client for repository and user activity tracking."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .base import JSONRPCMCPClient, MCPClientError
from src.models.content import ContentItem, ContentSource, ContentType, create_content_item


class GitHubClient(JSONRPCMCPClient):
    """MCP client for GitHub integration."""

    async def get_user_activity(
        self,
        username: str,
        per_page: int = 10,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        """Get recent activity for a GitHub user.

        Args:
            username: GitHub username
            per_page: Number of events per page
            page: Page number

        Returns:
            List of user activity events

        Raises:
            MCPClientError: If API call fails
        """
        params = {
            "username": username,
            "per_page": per_page,
            "page": page,
        }

        try:
            result = await self._execute_operation("user_events", params)
            return result.get("events", [])

        except Exception as e:
            raise MCPClientError(f"Failed to get user activity for {username}: {str(e)}")

    async def get_user_repositories(
        self,
        username: str,
        sort: str = "updated",
        direction: str = "desc",
        per_page: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get repositories for a GitHub user.

        Args:
            username: GitHub username
            sort: Sort order (created, updated, pushed, full_name)
            direction: Sort direction (asc, desc)
            per_page: Number of repositories per page

        Returns:
            List of user repositories
        """
        params = {
            "username": username,
            "sort": sort,
            "direction": direction,
            "per_page": per_page,
        }

        try:
            result = await self._execute_operation("user_repos", params)
            return result.get("repositories", [])

        except Exception as e:
            raise MCPClientError(f"Failed to get repositories for {username}: {str(e)}")

    async def get_trending_repositories(
        self,
        language: Optional[str] = None,
        since: str = "daily",
        per_page: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get trending repositories.

        Args:
            language: Programming language filter
            since: Time period (daily, weekly, monthly)
            per_page: Number of repositories

        Returns:
            List of trending repositories
        """
        params = {
            "since": since,
            "per_page": per_page,
        }

        if language:
            params["language"] = language

        try:
            result = await self._execute_operation("trending_repos", params)
            return result.get("repositories", [])

        except Exception as e:
            raise MCPClientError(f"Failed to get trending repositories: {str(e)}")

    async def search_repositories(
        self,
        query: str,
        sort: str = "stars",
        order: str = "desc",
        per_page: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search GitHub repositories.

        Args:
            query: Search query
            sort: Sort field (stars, forks, help-wanted-issues, updated)
            order: Sort order (asc, desc)
            per_page: Number of results

        Returns:
            List of matching repositories
        """
        params = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": per_page,
        }

        try:
            result = await self._execute_operation("search_repos", params)
            return result.get("items", [])

        except Exception as e:
            raise MCPClientError(f"Failed to search repositories: {str(e)}")

    async def get_repository_releases(
        self,
        owner: str,
        repo: str,
        per_page: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get recent releases for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            per_page: Number of releases

        Returns:
            List of repository releases
        """
        params = {
            "owner": owner,
            "repo": repo,
            "per_page": per_page,
        }

        try:
            result = await self._execute_operation("repo_releases", params)
            return result.get("releases", [])

        except Exception as e:
            raise MCPClientError(f"Failed to get releases for {owner}/{repo}: {str(e)}")

    async def get_user_activity_summary(self, username: str) -> Dict[str, Any]:
        """Get a summarized view of user's recent GitHub activity.

        Args:
            username: GitHub username

        Returns:
            Activity summary with stats and recent items
        """
        try:
            # Get recent events
            events = await self.get_user_activity(username, per_page=30)

            # Get user repositories
            repos = await self.get_user_repositories(username, per_page=5)

            # Process events into summary
            activity_summary = {
                "username": username,
                "total_events": len(events),
                "recent_repositories": [],
                "recent_activity": [],
                "languages": set(),
                "activity_types": {},
            }

            # Process repositories
            for repo in repos[:3]:  # Top 3 repositories
                activity_summary["recent_repositories"].append({
                    "name": repo.get("name", ""),
                    "full_name": repo.get("full_name", ""),
                    "description": repo.get("description", ""),
                    "language": repo.get("language", ""),
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "updated_at": repo.get("updated_at", ""),
                })

                if repo.get("language"):
                    activity_summary["languages"].add(repo.get("language"))

            # Process events
            for event in events[:10]:  # Recent 10 events
                event_type = event.get("type", "")
                activity_summary["activity_types"][event_type] = (
                    activity_summary["activity_types"].get(event_type, 0) + 1
                )

                activity_summary["recent_activity"].append({
                    "type": event_type,
                    "repo": event.get("repo", {}).get("name", ""),
                    "created_at": event.get("created_at", ""),
                    "public": event.get("public", True),
                })

            activity_summary["languages"] = list(activity_summary["languages"])

            return activity_summary

        except Exception as e:
            self.logger.warning("Failed to get user activity summary", username=username, error=str(e))
            return {
                "username": username,
                "error": str(e),
                "total_events": 0,
                "recent_repositories": [],
                "recent_activity": [],
                "languages": [],
                "activity_types": {},
            }

    async def collect_content_for_interest(self, interest: str, max_items: int = 10) -> List[ContentItem]:
        """Collect GitHub content related to a specific interest.

        Args:
            interest: Interest/topic to search for
            max_items: Maximum number of content items

        Returns:
            List of content items from GitHub
        """
        content_items = []

        try:
            self.logger.info("Starting GitHub content collection", interest=interest, max_items=max_items)

            # Search for repositories related to the interest
            # Quote multi-word interests for proper GitHub search syntax
            quoted_interest = f'"{interest}"' if " " in interest else interest
            search_query = f"{quoted_interest} language:python OR language:javascript OR language:typescript"

            try:
                repos = await self.search_repositories(search_query, per_page=max_items)
                self.logger.info("GitHub MCP search successful", repos_count=len(repos), interest=interest)

                # If no results with language filters, try simpler search
                if not repos:
                    self.logger.info("No results with language filters, trying simpler search", interest=interest)
                    simple_query = quoted_interest
                    repos = await self.search_repositories(simple_query, per_page=max_items)
                    self.logger.info("GitHub simple search result", repos_count=len(repos), interest=interest)

            except Exception as mcp_error:
                self.logger.warning("GitHub MCP search failed, trying fallback", error=str(mcp_error), interest=interest)
                repos = await self._search_repositories_fallback(search_query, max_items)

                # If fallback also returns empty, try simple fallback
                if not repos:
                    self.logger.info("Fallback search empty, trying simple fallback", interest=interest)
                    simple_query = quoted_interest
                    repos = await self._search_repositories_fallback(simple_query, max_items)

            for repo in repos:
                # Skip if repository is too old (> 1 year since last update)
                updated_at = repo.get("updated_at", "")
                if updated_at:
                    try:
                        update_date = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        # Use timezone-aware datetime for comparison
                        from datetime import timezone
                        now = datetime.now(timezone.utc)
                        if (now - update_date) > timedelta(days=365):
                            continue
                    except (ValueError, TypeError):
                        pass

                content_item = create_content_item(
                    title=repo.get("name", ""),
                    url=repo.get("html_url", ""),
                    source=ContentSource.GITHUB,
                    content_type=ContentType.REPOSITORY,
                    author=repo.get("owner", {}).get("login", ""),
                    summary=repo.get("description", ""),
                    metadata={
                        "stars": repo.get("stargazers_count", 0),
                        "forks": repo.get("forks_count", 0),
                        "language": repo.get("language", ""),
                        "topics": repo.get("topics", []),
                        "open_issues": repo.get("open_issues_count", 0),
                        "size": repo.get("size", 0),
                        "created_at": repo.get("created_at", ""),
                        "updated_at": repo.get("updated_at", ""),
                    }
                )
                content_items.append(content_item)

            self.logger.info("GitHub content collection completed", count=len(content_items), interest=interest)

        except Exception as e:
            self.logger.error("Failed to collect GitHub content", interest=interest, error=str(e), exc_info=True)

        return content_items

    async def _search_repositories_fallback(self, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        """Fallback GitHub search using direct API calls."""
        try:
            import aiohttp
            import urllib.parse
            import os

            # Get GitHub token from environment
            github_token = os.getenv("NEWSLETTER_GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
            if not github_token:
                self.logger.warning("No GitHub token available for fallback search")
                return []

            encoded_query = urllib.parse.quote(query)
            search_url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page={max_items}"

            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Personal-AI-Newsletter/1.0"
            }

            self.logger.info("Using GitHub fallback API", url=search_url)

            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, headers=headers) as response:
                    if response.status != 200:
                        self.logger.warning(f"GitHub API returned status {response.status}")
                        return []

                    data = await response.json()
                    items = data.get("items", [])

                    self.logger.info("GitHub fallback API successful", items_count=len(items))
                    return items

        except Exception as e:
            self.logger.error("GitHub fallback search failed", error=str(e), exc_info=True)
            return []

    async def get_trending_in_language(self, language: str, max_items: int = 5) -> List[ContentItem]:
        """Get trending repositories in a specific programming language.

        Args:
            language: Programming language
            max_items: Maximum number of repositories

        Returns:
            List of trending repository content items
        """
        try:
            repos = await self.get_trending_repositories(language=language, per_page=max_items)
            content_items = []

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
                        "language": language,
                        "trending_period": "daily",
                        "topics": repo.get("topics", []),
                    }
                )
                content_items.append(content_item)

            return content_items

        except Exception as e:
            self.logger.warning("Failed to get trending repositories", language=language, error=str(e))
            return []

    async def _execute_operation(self, operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a GitHub operation via MCP or direct API."""
        # The official GitHub MCP server doesn't have repository operations
        # So we'll use direct GitHub API calls for most functionality
        # and only use MCP tools where appropriate (user context, etc.)

        if operation == "get_me":
            # Use MCP tool for user context
            request = self._create_tool_call_request("get_me", data)
            return await self._send_request(request)
        else:
            # For repository operations, use GitHub REST API directly
            return await self._call_github_api(operation, data)

    async def _call_github_api(self, operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Call GitHub REST API directly for repository operations."""
        import aiohttp
        import os

        # Get GitHub token from environment or config
        token = os.environ.get("NEWSLETTER_GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or self.config.env.get("GITHUB_PERSONAL_ACCESS_TOKEN")

        if not token:
            raise MCPClientError("GitHub token not available")

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Personal-AI-Newsletter/1.0"
        }

        # Map operations to GitHub API endpoints
        if operation == "user_events":
            url = f"https://api.github.com/users/{data['username']}/events"
            params = {"per_page": data.get("per_page", 10), "page": data.get("page", 1)}
        elif operation == "user_repos":
            url = f"https://api.github.com/users/{data['username']}/repos"
            params = {
                "sort": data.get("sort", "updated"),
                "direction": data.get("direction", "desc"),
                "per_page": data.get("per_page", 10)
            }
        elif operation == "trending_repos":
            # Use search API for trending repositories (past week)
            since_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            query = f"stars:>10 created:>{since_date}"
            if data.get("language"):
                query += f" language:{data['language']}"
            url = "https://api.github.com/search/repositories"
            params = {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": data.get("per_page", 10)
            }
        elif operation == "search_repos":
            url = "https://api.github.com/search/repositories"
            params = {
                "q": data["q"],
                "sort": data.get("sort", "stars"),
                "order": data.get("order", "desc"),
                "per_page": data.get("per_page", 10)
            }
        elif operation == "repo_releases":
            url = f"https://api.github.com/repos/{data['owner']}/{data['repo']}/releases"
            params = {"per_page": data.get("per_page", 5)}
        else:
            raise MCPClientError(f"Unknown GitHub API operation: {operation}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    result = await response.json()

                    # Normalize response format to match expected structure
                    if operation == "user_events":
                        return {"events": result}
                    elif operation == "user_repos":
                        return {"repositories": result}
                    elif operation in ["trending_repos", "search_repos"]:
                        return result  # Return the full result with 'items' key
                    elif operation == "repo_releases":
                        return {"releases": result}
                    else:
                        return result
                else:
                    error_text = await response.text()
                    raise MCPClientError(f"GitHub API error {response.status}: {error_text}")

    async def _health_check_operation(self) -> None:
        """Health check by getting trending repositories."""
        await self.get_trending_repositories(per_page=1)