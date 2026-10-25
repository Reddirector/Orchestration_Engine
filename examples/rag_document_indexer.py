"""
RAG Document Ingestion & Vector Indexing Pipeline.

Demonstrates an automated knowledge retrieval and vector indexing workflow:
1. 'fetch-docs': Retrieves raw document records from storage.
2. 'chunk-docs': Splits documents into semantic chunks (data flow via task.inputs).
3. 'embed-chunks': Generates embedding representations with transient error handling
   and exponential backoff retry.
4. 'index-vectors': Persists embeddings into the vector store.
5. 'evaluate-coverage': Validates indexing integrity (fan-in evaluation gate).

Features highlighted:
- Multi-step ETL and RAG vector indexing graph
- Automatic retry on transient API/service errors
- Strict data flow passing structured chunks and embeddings
- Fan-in verification step ensuring all chunks were indexed
- Zero runtime dependencies with clear provider integration stubs
"""

from __future__ import annotations

import time
from typing import Any

from orchestration_engine import (
    Hooks,
    RetryPolicy,
    Task,
    TaskResult,
    Workflow,
    WorkflowBuilder,
    get_connection,
    get_run_status,
    run_workflow,
)

# Simulated transient failure state for embedding service
_EMBED_ATTEMPTS: dict[str, int] = {}


def rag_indexer_runner(task: Task) -> TaskResult:
    """Task runner for document indexing and embedding generation."""
    step_name = task.name or task.task_id
    print(f"-> [Worker] Starting step: {step_name} (attempt {task.attempt_count})")

    if task.task_id == "fetch-docs":
        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Document Storage / Blob Store / S3 / GCS]
        # e.g.: docs = s3_client.get_objects(prefix="kb/policies/")
        # ---------------------------------------------------------------------
        raw_documents = [
            {
                "doc_id": "doc-101",
                "title": "Authentication Policy",
                "content": (
                    "All services must use mTLS for internal communication. "
                    "External requests require OAuth2 bearer tokens with 15-minute TTL."
                ),
            },
            {
                "doc_id": "doc-102",
                "title": "Rate Limiting Guidelines",
                "content": (
                    "Public endpoints are restricted to 100 requests per minute per IP. "
                    "Authenticated tiers allow 1000 requests per minute with burst allowance."
                ),
            },
        ]
        return TaskResult(ok=True, output={"documents": raw_documents})

    elif task.task_id == "chunk-docs":
        # Receive documents from upstream 'fetch-docs'
        fetch_output = task.inputs.get("fetch-docs", {})
        documents = fetch_output.get("documents", [])

        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Text Splitter / Chunking Strategy]
        # e.g.: chunks = recursive_character_splitter.split(doc.content)
        # ---------------------------------------------------------------------
        chunks: list[dict[str, Any]] = []
        for doc in documents:
            sentences = [s.strip() for s in doc["content"].split(". ") if s.strip()]
            for idx, sentence in enumerate(sentences):
                chunks.append(
                    {
                        "chunk_id": f"{doc['doc_id']}-c{idx + 1}",
                        "doc_id": doc["doc_id"],
                        "text": sentence if sentence.endswith(".") else f"{sentence}.",
                    }
                )

        print(f"   [Chunker] Split {len(documents)} documents into {len(chunks)} chunks")
        return TaskResult(ok=True, output={"chunks": chunks})

    elif task.task_id == "embed-chunks":
        # Simulate transient embedding service rate limit or timeout on attempt 1
        run_key = f"{getattr(task, '_run_id', 'local')}:{task.task_id}"
        attempts = _EMBED_ATTEMPTS.get(run_key, 0) + 1
        _EMBED_ATTEMPTS[run_key] = attempts

        if attempts == 1:
            print("   [Embedding API] 503 Service Unavailable (simulating transient backpressure)")
            return TaskResult(
                ok=False,
                error="Embedding service unavailable: 503 backpressure",
            )

        # Receive chunks from 'chunk-docs'
        chunk_output = task.inputs.get("chunk-docs", {})
        chunks = chunk_output.get("chunks", [])

        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Embedding Model API]
        # e.g.: embeddings = client.models.embed_content(model="text-embedding-004", ...)
        # ---------------------------------------------------------------------
        embedded_items: list[dict[str, Any]] = []
        for chunk in chunks:
            # Deterministic mock 8-dimensional vector representation based on text length
            dim_val = round(len(chunk["text"]) / 100.0, 3)
            embedded_items.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "vector": [dim_val] * 8,
                    "metadata": {"doc_id": chunk["doc_id"], "text": chunk["text"]},
                }
            )

        print(f"   [Embedding API] Generated {len(embedded_items)} vector embeddings successfully")
        return TaskResult(ok=True, output={"embedded_items": embedded_items})

    elif task.task_id == "index-vectors":
        embed_output = task.inputs.get("embed-chunks", {})
        embedded_items = embed_output.get("embedded_items", [])

        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Vector Database]
        # e.g.: vector_db.upsert(vectors=embedded_items, namespace="kb-prod")
        # ---------------------------------------------------------------------
        time.sleep(0.02)
        indexed_count = len(embedded_items)
        print(f"   [Vector Store] Indexed {indexed_count} vectors into collection 'kb-policies'")
        return TaskResult(
            ok=True,
            output={"indexed_count": indexed_count, "collection": "kb-policies"},
        )

    elif task.task_id == "evaluate-coverage":
        # Fan-in verification: verify chunk count matches indexed count
        chunk_output = task.inputs.get("chunk-docs", {})
        index_output = task.inputs.get("index-vectors", {})

        total_chunks = len(chunk_output.get("chunks", []))
        indexed_count = index_output.get("indexed_count", 0)

        coverage_ratio = (indexed_count / total_chunks) if total_chunks > 0 else 0.0
        is_complete = indexed_count == total_chunks

        report = {
            "total_chunks_produced": total_chunks,
            "total_vectors_indexed": indexed_count,
            "coverage_ratio": coverage_ratio,
            "status": "HEALTHY" if is_complete else "DEGRADED",
        }
        pct = coverage_ratio * 100.0
        print(f"   [Quality Gate] Coverage: {pct:.1f}%, Status: {report['status']}")
        return TaskResult(ok=is_complete, output=report)

    return TaskResult(ok=False, error=f"Unknown task: {task.task_id}")


def build_rag_indexing_workflow() -> Workflow:
    """Constructs the RAG document indexing DAG."""
    builder = WorkflowBuilder(
        "rag-indexer-pipeline",
        name="RAG Ingestion & Vector Indexing",
        description="Ingest documents, chunk, compute embeddings with retry, index, and verify.",
        default_timeout_seconds=20.0,
    )

    builder.task(
        "fetch-docs",
        name="Fetch Raw Documents",
        description="Ingests documents from source repository",
        timeout_seconds=5.0,
    )
    builder.task(
        "chunk-docs",
        name="Chunk Documents",
        description="Splits documents into semantic passages",
        dependencies=["fetch-docs"],
        timeout_seconds=5.0,
    )
    builder.task(
        "embed-chunks",
        name="Generate Vector Embeddings",
        description="Embeds passages with rate-limit retries",
        dependencies=["chunk-docs"],
        retry_policy=RetryPolicy(max_attempts=3, delay_seconds=0.1),
        timeout_seconds=10.0,
    )
    builder.task(
        "index-vectors",
        name="Store in Vector Database",
        description="Persists vectors and metadata into index",
        dependencies=["embed-chunks"],
        timeout_seconds=5.0,
    )
    builder.task(
        "evaluate-coverage",
        name="Evaluate Indexing Quality",
        description="Fan-in quality gate comparing chunks generated to vectors stored",
        dependencies=["chunk-docs", "index-vectors"],
        timeout_seconds=5.0,
    )

    return builder.build()


def main() -> None:
    print("=== RAG Document Ingestion & Vector Indexing Pipeline ===\n")
    workflow = build_rag_indexing_workflow()
    conn = get_connection(":memory:")

    hooks = Hooks(
        on_task_start=lambda t: print(f"  [Event] Task '{t.task_id}' started"),
        on_task_retry=lambda t: print(f"  [Event] Task '{t.task_id}' retrying"),
        on_task_succeeded=lambda t: print(f"  [Event] Task '{t.task_id}' completed successfully"),
        on_workflow_done=lambda wf, st: print(
            f"  [Event] Workflow finished with status: {st.value}"
        ),
    )

    print("--- Executing Indexing Pipeline ---")
    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=rag_indexer_runner,
        conn=conn,
        hooks=hooks,
        max_concurrency=2,
    )

    final_status = get_run_status(conn, run_id)
    print(f"\nFinal Workflow Status: {final_status.value}")
    assert final_status.value == "succeeded", f"Expected succeeded, got {final_status.value}"
    print("Pipeline execution verified successfully!\n")


if __name__ == "__main__":
    main()
