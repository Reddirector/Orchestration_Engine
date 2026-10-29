"""
Zero-dependency thread-safe and async-safe token-bucket rate limiter.

Protects external API endpoints (LLMs, webhooks, databases) from exceeding
rate limits (HTTP 429) during parallel task execution.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from collections.abc import Callable, Coroutine
from typing import Any


class TokenBucketRateLimiter:
    """
    Token-bucket rate limiter supporting both synchronous and asynchronous callers.

    Attributes:
        rate: Number of tokens added per second.
        capacity: Maximum burst capacity of the token bucket.
    """

    def __init__(self, rate: float, capacity: int = 1) -> None:
        if rate <= 0:
            raise ValueError("Rate must be strictly positive.")
        if capacity < 1:
            raise ValueError("Capacity must be an integer >= 1.")

        self.rate = float(rate)
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._last_time = time.monotonic()
        self._lock = threading.Lock()
        self._async_lock: asyncio.Lock | None = None

    def _replenish(self, now: float) -> None:
        elapsed = now - self._last_time
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_time = now

    def acquire(self, tokens: float = 1.0) -> None:
        """Synchronously block until requested tokens are available."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._replenish(now)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate sleep time needed
                needed = tokens - self._tokens
                wait_sec = needed / self.rate

            time.sleep(wait_sec)

    async def acquire_async(self, tokens: float = 1.0) -> None:
        """Asynchronously wait until requested tokens are available."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()

        while True:
            async with self._async_lock:
                now = time.monotonic()
                self._replenish(now)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                needed = tokens - self._tokens
                wait_sec = needed / self.rate

            await asyncio.sleep(wait_sec)

    def __enter__(self) -> TokenBucketRateLimiter:
        self.acquire(1.0)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    async def __aenter__(self) -> TokenBucketRateLimiter:
        await self.acquire_async(1.0)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def limit(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator that rate-limits a synchronous function call."""
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.acquire(1.0)
            return func(*args, **kwargs)
        return wrapper

    def limit_async(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        """Decorator that rate-limits an asynchronous coroutine call."""
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            await self.acquire_async(1.0)
            return await func(*args, **kwargs)
        return wrapper
