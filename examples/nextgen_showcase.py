"""
Next-Generation Capabilities Showcase for Orchestration Engine.

Demonstrates:
1. Ergonomic @task and @workflow decorators
2. Native asyncio runner (run_workflow_async)
3. Token-bucket rate limiter (TokenBucketRateLimiter)
4. Deterministic result caching in SQLite (TaskCache)
5. Zero external runtime dependencies
"""

import asyncio
import time
from typing import Any

from orchestration_engine import (
    Task,
    TaskCache,
    TaskResult,
    TokenBucketRateLimiter,
    get_connection,
    task,
    workflow,
)

# 1. Initialize Token-Bucket Rate Limiter (e.g. 5 requests/sec for LLM API)
limiter = TokenBucketRateLimiter(rate=5.0, capacity=2)


# 2. Define Tasks using @task Decorators
@task
@limiter.limit_async
async def retrieve_context() -> dict[str, Any]:  # type: ignore[name-defined]
    """Simulate non-blocking async document retrieval with rate limiting."""
    await asyncio.sleep(0.05)
    return {
        "documents": [
            {"id": "doc-101", "content": "Autonomous agents require deterministic state."},
            {"id": "doc-102", "content": "SQLite WAL provides crash-resilient durability."},
        ]
    }


@task(dependencies=[retrieve_context], max_attempts=2)
async def generate_embeddings(task: Task) -> TaskResult:
    """Simulate async vector embedding generation."""
    docs = task.inputs["retrieve_context"]["documents"]
    embeddings = [f"vec_{d['id']}" for d in docs]
    return TaskResult(ok=True, output={"embeddings": embeddings, "count": len(embeddings)})


@task(dependencies=[generate_embeddings])
def format_summary(task: Task) -> dict[str, str]:
    """Sync task seamlessly composed into async workflow."""
    embed_count = task.inputs["generate_embeddings"]["count"]
    return {"summary": f"Successfully indexed {embed_count} document vectors."}


# 3. Define Workflow with @workflow Decorator
@workflow(workflow_id="rag-indexing-pipeline", name="RAG Indexing Pipeline")
def rag_pipeline() -> list[Any]:  # type: ignore[name-defined]
    return [retrieve_context, generate_embeddings, format_summary]


async def main() -> None:
    print("=== Orchestration Engine Next-Gen Showcase ===")
    conn = get_connection(":memory:")

    # 4. Demonstrate SQLite-backed Result Cache
    cache = TaskCache(conn)
    cached_val = cache.get("rag-indexing-pipeline", {"mock": "input"})
    print(f"Cache check: {'HIT' if cached_val[0] else 'MISS'}")

    # 5. Run Workflow Asynchronously
    print("\n--- Running Workflow with Native Async Coordinator ---")
    start = time.perf_counter()
    status = await rag_pipeline.run_async(conn=conn, max_concurrency=10)
    elapsed = time.perf_counter() - start

    print(f"Workflow Finished Status: {status.value}")
    print(f"Elapsed Time: {elapsed:.3f}s")
    print("\nAll tasks completed with 0 external dependencies!")


if __name__ == "__main__":
    asyncio.run(main())
