"""Rate limiting utilities for API clients."""

import asyncio
import time
import random
from typing import List, Optional, Callable, Any, Dict
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    max_concurrent: int = 3
    max_retries: int = 3
    base_backoff: float = 1.0
    jitter: bool = True


class RateLimiter:
    """Rate limiter with sliding window and exponential backoff."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.request_times: List[float] = []
        self.semaphore = asyncio.Semaphore(config.max_concurrent)
        self.min_delay = 60.0 / config.requests_per_minute

    async def acquire(self) -> None:
        """Acquire permission to make a request."""
        await self.semaphore.acquire()
        await self._enforce_rate_limit()

    def release(self) -> None:
        """Release the semaphore."""
        self.semaphore.release()

    async def _enforce_rate_limit(self) -> None:
        """Enforce rate limiting using sliding window."""
        now = time.time()

        # Remove requests older than 1 minute
        self.request_times = [t for t in self.request_times if now - t < 60]

        # If at limit, wait for oldest request to age out
        if len(self.request_times) >= self.config.requests_per_minute:
            sleep_time = 60 - (now - self.request_times[0]) + 0.1
            if sleep_time > 0:
                logger.debug(f"Rate limit hit, sleeping {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
                return await self._enforce_rate_limit()

        # Record this request
        self.request_times.append(now)

        # Add base delay between requests
        if len(self.request_times) > 1:
            await asyncio.sleep(self.min_delay)

    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Optional[Any]:
        """Execute function with rate limiting and retry logic."""

        for attempt in range(self.config.max_retries + 1):
            try:
                await self.acquire()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    self.release()

            except Exception as e:
                # Check if it's a rate limit error
                is_rate_limit = (
                    hasattr(e, 'status_code') and e.status_code == 429
                    or '429' in str(e)
                    or 'rate limit' in str(e).lower()
                )

                if is_rate_limit and attempt < self.config.max_retries:
                    # Extract retry-after from error message if available
                    wait_time = self._extract_retry_after(str(e))
                    if wait_time is None:
                        # Exponential backoff with jitter
                        wait_time = self.config.base_backoff * (2 ** attempt)
                        if self.config.jitter:
                            wait_time += random.uniform(0, wait_time * 0.1)

                    logger.warning(
                        f"Rate limited, retrying in {wait_time:.1f}s "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Non-rate-limit error or max retries exceeded
                    if attempt == self.config.max_retries:
                        logger.error(f"Max retries exceeded: {e}")
                    raise e

        return None

    def _extract_retry_after(self, error_message: str) -> Optional[float]:
        """Extract retry-after time from error message."""
        try:
            # Look for "retry after Xs" pattern
            import re
            match = re.search(r'retry after (\d+)s', error_message)
            if match:
                return float(match.group(1))

            # Look for reset time pattern
            match = re.search(r'resets at .+ (\d+)s', error_message)
            if match:
                return float(match.group(1))

        except Exception:
            pass

        return None


class WorkerPool:
    """Worker pool for processing tasks with rate limiting."""

    def __init__(self, rate_limiter: RateLimiter, worker_count: int = 3):
        self.rate_limiter = rate_limiter
        self.worker_count = worker_count
        self.queue: asyncio.Queue = asyncio.Queue()
        self.results: List[Any] = []
        self.workers: List[asyncio.Task] = []

    async def add_task(self, func: Callable, *args, **kwargs) -> None:
        """Add a task to the queue."""
        await self.queue.put((func, args, kwargs))

    async def _worker(self, worker_id: int) -> None:
        """Worker that processes tasks from the queue."""
        logger.debug(f"Worker {worker_id} started")

        while True:
            try:
                # Get task from queue with timeout
                func, args, kwargs = await asyncio.wait_for(
                    self.queue.get(), timeout=1.0
                )

                try:
                    result = await self.rate_limiter.execute_with_retry(
                        func, *args, **kwargs
                    )
                    if result is not None:
                        self.results.append(result)
                except Exception as e:
                    logger.warning(f"Worker {worker_id} task failed: {e}")
                finally:
                    self.queue.task_done()

            except asyncio.TimeoutError:
                # No tasks available, check if we should continue
                if self.queue.empty():
                    break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                break

        logger.debug(f"Worker {worker_id} finished")

    async def process_all(self) -> List[Any]:
        """Process all queued tasks and return results."""
        if self.queue.empty():
            return []

        # Start workers
        self.workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.worker_count)
        ]

        # Wait for all tasks to complete
        await self.queue.join()

        # Cancel workers
        for worker in self.workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)

        results = self.results.copy()
        self.results.clear()
        return results