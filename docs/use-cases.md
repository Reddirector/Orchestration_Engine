# Real-World Use Cases

The **Orchestration Engine** is designed to provide zero-dependency, fault-tolerant execution for workflows where steps depend on each other, fail transiently, and require an auditable history.

Below are core production architectures implemented using the engine.

---

## 1. Multi-Step AI Agent Pipelines

**Example Implementation:** [`examples/agent_pipeline.py`](https://github.com/Reddirector/Orchestration_Engine/blob/main/examples/agent_pipeline.py)

Modern AI agent workflows often comprise multiple stages: knowledge retrieval, model inference, tool execution, critique/verification, and final synthesis.

```mermaid
flowchart TD
    retrieve["1. Retrieve Context<br/>(Vector DB / Tool)"] --> summarize["2A. Summarize<br/>(LLM Call with 429 Retry)"]
    retrieve --> extract["2B. Extract Entities<br/>(Structured Output)"]
    summarize --> report["3. Fan-in Executive Report<br/>(Synthesis Gate)"]
    extract --> report
```

### Key Engineering Patterns
- **Transient Provider Retries:** LLM APIs commonly return `HTTP 429 (Too Many Requests)` or `503 (Overloaded)`. Configured `RetryPolicy(max_attempts=3, delay_seconds=1.0)` retries with exponential backoff.
- **Concurrent Fan-Out:** Independent steps (e.g., entity extraction and narrative summarization) run concurrently via `max_concurrency=2`.
- **Data Flow:** Step outputs (`TaskResult(ok=True, output=...)`) are stored in SQLite and automatically injected into downstream tasks via `task.inputs`.
- **Crash Recovery:** If the agent host terminates abruptly mid-run, `resume_run(conn, run_id, ...)` resumes execution without re-executing completed tasks.

---

## 2. RAG Document Ingestion & Vector Indexing

**Example Implementation:** [`examples/rag_document_indexer.py`](https://github.com/Reddirector/Orchestration_Engine/blob/main/examples/rag_document_indexer.py)

Building retrieval-augmented generation (RAG) indexes requires ingesting source documents, chunking text, computing vector embeddings, and indexing them into a vector database with strict quality verification.

```mermaid
flowchart LR
    fetch["fetch-docs<br/>(Load Documents)"] --> chunk["chunk-docs<br/>(Semantic Chunker)"]
    chunk --> embed["embed-chunks<br/>(Embedding API + Retry)"]
    embed --> index["index-vectors<br/>(Vector DB Upsert)"]
    chunk --> eval["evaluate-coverage<br/>(Fan-in Quality Gate)"]
    index --> eval
```

### Key Engineering Patterns
- **Structured Data Propagation:** The chunker splits documents and passes structured chunks downstream via `task.inputs["fetch-docs"]`.
- **API Backpressure Mitigation:** Embedding models frequently impose tight token rate limits. Automatic retry policies ensure zero lost data during network or provider hiccups.
- **Fan-in Evaluation Gate:** `evaluate-coverage` compares the count of chunks produced by `chunk-docs` against the count of embeddings stored by `index-vectors`, validating indexing health before marking the workflow succeeded.

---

## 3. Automated Incident Triage & Remediation (DevOps / SRE)

**Example Implementation:** [`examples/incident_triage.py`](https://github.com/Reddirector/Orchestration_Engine/blob/main/examples/incident_triage.py)

Autonomous incident response systems must ingest alerts, run parallel diagnostics across different telemetry backends, synthesize a root-cause analysis (RCA), execute automated remediation, and verify recovery.

```mermaid
flowchart TD
    alert["1. Ingest Alert<br/>(Webhook / PagerDuty)"] --> logs["2A. Scan Logs<br/>(Search Stack Traces)"]
    alert --> metrics["2B. Inspect DB Pool<br/>(Check Saturation)"]
    alert --> deps["2C. Ping Dependencies<br/>(Health Checks)"]
    logs --> rca["3. Synthesize RCA<br/>(Multi-source Correlation)"]
    metrics --> rca
    deps --> rca
    rca --> remediate["4. Apply Mitigation<br/>(Resize Pool / Reset Conns)"]
    remediate --> verify["5. Verify Health<br/>(Confirm Nominal Error Rate)"]
```

### Key Engineering Patterns
- **High Concurrency Diagnostics:** Runs parallel checks against logs, metrics, and microservices simultaneously (`max_concurrency=3`).
- **Multi-Source Correlation:** `synthesize-rca` aggregates diagnostic data from all 3 independent branches to isolate the true root cause.
- **Fail-Safe Transitive Cancellation:** If automated mitigation fails, dependent verification steps are automatically `CANCELLED`, preventing premature incident closure.
- **Real-Time SRE Notifications:** User-supplied `Hooks` notify operations channels (e.g. Slack, PagerDuty) upon step transition or retry without blocking the coordinator.

---

## 4. Resilient ETL & Data Processing Pipelines

**Example Implementation:** [`examples/builder.py`](https://github.com/Reddirector/Orchestration_Engine/blob/main/examples/builder.py) and [`examples/data_flow.py`](https://github.com/Reddirector/Orchestration_Engine/blob/main/examples/data_flow.py)

Data pipelines requiring strict transactional guarantees, schema migration, and zero data loss.

### Key Engineering Patterns
- **Fluent Declarative Construction:** Construct complex DAGs cleanly with `WorkflowBuilder`:
```python
workflow = (
    WorkflowBuilder("etl-pipeline", default_timeout_seconds=30.0)
    .task("extract", timeout_seconds=10.0)
    .task("transform", dependencies=["extract"], max_attempts=3)
    .task("load", dependencies=["transform"])
    .build()
)
```
- **Portable Serialization:** Round-trip workflows to JSON/YAML dictionaries via `workflow_to_dict()` and `load_workflow_from_json()`.
- **Transactional State Persistence:** SQLite write-ahead logging (WAL) logs all task events (`task_events`) and payloads (`task_outputs`) atomically.
