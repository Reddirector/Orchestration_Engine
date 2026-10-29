"""Tests for TaskCache and TokenBucketRateLimiter."""

import asyncio
import time
from pathlib import Path

import pytest

from orchestration_engine import (
    Task,
    TaskCache,
    TaskResult,
    TokenBucketRateLimiter,
    get_connection,
)


def test_cache_miss_and_hit(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path / "cache.db"))
    cache = TaskCache(conn)

    inputs = {"query": "weather", "city": "tokyo"}
    hit, val = cache.get("fetch_weather", inputs)
    assert not hit
    assert val is None

    # Set cache entry
    cache.set("fetch_weather", inputs, {"temp": 22})

    # Cache hit
    hit, val = cache.get("fetch_weather", inputs)
    assert hit
    assert val == {"temp": 22}

    # Order of dict keys shouldn't affect cache key
    shuffled_inputs = {"city": "tokyo", "query": "weather"}
    hit, val = cache.get("fetch_weather", shuffled_inputs)
    assert hit
    assert val == {"temp": 22}

    # Different input is a miss
    hit, val = cache.get("fetch_weather", {"query": "weather", "city": "kyoto"})
    assert not hit
    conn.close()


def test_cache_ttl_expiration(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path / "cache_ttl.db"))
    cache = TaskCache(conn)

    cache.set("t1", {"x": 1}, "output1", ttl_seconds=0.05)
    hit, val = cache.get("t1", {"x": 1})
    assert hit
    assert val == "output1"

    time.sleep(0.08)
    hit, val = cache.get("t1", {"x": 1})
    assert not hit
    assert val is None
    conn.close()


def test_cache_wrap_runner(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path / "cache_wrap.db"))
    cache = TaskCache(conn)

    execution_count = 0

    def expensive_runner(task: Task) -> TaskResult:
        nonlocal execution_count
        execution_count += 1
        return TaskResult(ok=True, output=f"result-{task.task_id}")

    cached_runner = cache.wrap_runner(expensive_runner)

    t = Task(
        task_id="fetch",
        workflow_id="wf1",
        name="Fetch",
        description="",
        dependencies=[],
        state="pending",  # type: ignore[arg-type]
        retry_policy=None,  # type: ignore[arg-type]
    )
    t.inputs = {"id": 100}

    # First call: executes runner
    res1 = cached_runner(t)
    assert res1.ok
    assert res1.output == "result-fetch"
    assert execution_count == 1

    # Second call with same inputs: served from cache!
    res2 = cached_runner(t)
    assert res2.ok
    assert res2.output == "result-fetch"
    assert execution_count == 1  # count did not increase!

    conn.close()


def test_rate_limiter_sync() -> None:
    # 20 tokens/sec
    limiter = TokenBucketRateLimiter(rate=20.0, capacity=2)

    start = time.perf_counter()
    # Acquire burst of 2 immediately
    limiter.acquire(1.0)
    limiter.acquire(1.0)
    # 3rd acquire needs 1/20 sec wait (~0.05s)
    limiter.acquire(1.0)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.04

    # Context manager test
    with limiter:
        pass


def test_rate_limiter_async() -> None:
    async def _test() -> None:
        limiter = TokenBucketRateLimiter(rate=20.0, capacity=1)
        start = time.perf_counter()
        await limiter.acquire_async(1.0)
        await limiter.acquire_async(1.0)
        elapsed = time.perf_counter() - start
        assert elapsed >= 0.04

        async with limiter:
            pass

    asyncio.run(_test())


def test_rate_limiter_decorators() -> None:
    async def _test() -> None:
        limiter = TokenBucketRateLimiter(rate=50.0, capacity=5)

        @limiter.limit
        def sync_api() -> str:
            return "sync_ok"

        @limiter.limit_async
        async def async_api() -> str:
            return "async_ok"

        assert sync_api() == "sync_ok"
        assert await async_api() == "async_ok"

    asyncio.run(_test())


def test_rate_limiter_invalid_args() -> None:
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate=0.0)

    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate=10.0, capacity=0)
