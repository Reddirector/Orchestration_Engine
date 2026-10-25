"""
Multi-step AI Agent Pipeline Example.

Demonstrates orchestrating a realistic multi-step AI agent workflow:
1. 'retrieve': Fetches source context documents (knowledge retrieval).
2. 'summarize' & 'extract': Parallel fan-out tasks processing retrieved text.
   - 'summarize' simulates a transient provider rate limit (429) that succeeds on retry.
3. 'report': Fan-in synthesis combining summary and structured entities.

Features highlighted:
- Fan-out / fan-in DAG dependencies
- Retries with exponential backoff on transient provider failures
- Per-step timeouts
- Data flow: passing structured outputs via TaskResult and task.inputs
- Crash resumption demonstration
- Zero external provider SDK dependencies (clean stub extension points)
"""

from __future__ import annotations

import time
from typing import Any

from orchestration_engine import (
    Hooks,
    RetryPolicy,
    Task,
    TaskResult,
    WorkflowBuilder,
    get_connection,
    get_run_status,
    resume_run,
    run_workflow,
)

# Simulated transient failure tracking
_SUMMARIZE_ATTEMPTS: dict[str, int] = {}


def agent_runner(task: Task) -> TaskResult:
    """
    Task runner executing agent pipeline steps.

    Each step contains clearly marked integration points for connecting
    real LLM providers (e.g. Gemini, Anthropic, OpenAI) without adding
    runtime dependencies to the engine.
    """
    print(f"-> [Worker] Starting step: {task.name} ({task.task_id}), attempt {task.attempt_count}")

    if task.task_id == "retrieve":
        # ---------------------------------------------------------------------
        # [PROVIDER INTEGRATION POINT: Retrieval / Search]
        # In a production agent pipeline, call your vector database or search tool:
        # e.g.: results = vector_store.similarity_search("quarterly earnings")
        # ---------------------------------------------------------------------
        time.sleep(0.05)  # simulate network fetch
        retrieved_docs = [
            {"id": "doc-1", "text": "Q3 revenue grew by 18% YoY to $4.2B."},
            {"id": "doc-2", "text": "Operating margin improved from 21% to 26%."},
            {"id": "doc-3", "text": "Risks include currency swings and supply constraints."},
        ]
        return TaskResult(ok=True, output={"documents": retrieved_docs})

    elif task.task_id == "summarize":
        # Simulate a transient 429 Rate Limit error on the first attempt
        run_key = f"{getattr(task, '_run_id', 'local')}:{task.task_id}"
        attempts = _SUMMARIZE_ATTEMPTS.get(run_key, 0) + 1
        _SUMMARIZE_ATTEMPTS[run_key] = attempts

        if attempts == 1:
            print("   [Provider] HTTP 429 Too Many Requests (simulating API rate limit)")
            return TaskResult(
                ok=False,
                error="RateLimitError: 429 Too Many Requests from LLM endpoint",
            )

        # ---------------------------------------------------------------------
        # [PROVIDER INTEGRATION POINT: LLM Summarization]
        # e.g.:
        # response = client.models.generate_content(
        #     model="gemini-2.5-flash",
        #     contents=f"Summarize these documents: {task.inputs['retrieve']}"
        # )
        # ---------------------------------------------------------------------
        time.sleep(0.05)
        docs = task.inputs["retrieve"]["documents"]
        summary = (
            f"Analyzed {len(docs)} documents: Company demonstrated strong Q3 revenue expansion."
        )
        return TaskResult(ok=True, output={"summary": summary})

    elif task.task_id == "extract":
        # ---------------------------------------------------------------------
        # [PROVIDER INTEGRATION POINT: Structured Extraction / Tool Calling]
        # e.g.:
        # response = client.models.generate_content(
        #     model="gemini-2.5-flash",
        #     contents=prompt,
        #     config=types.GenerateContentConfig(response_schema=FinancialMetrics)
        # )
        # ---------------------------------------------------------------------
        time.sleep(0.05)
        entities = {
            "revenue": "$4.2B",
            "growth": "18%",
            "operating_margin": "26%",
            "risk_factors": ["currency", "supply_chain"],
        }
        return TaskResult(ok=True, output={"metrics": entities})

    elif task.task_id == "report":
        # ---------------------------------------------------------------------
        # [PROVIDER INTEGRATION POINT: Final Synthesis]
        # Combine upstream parallel outputs from summarize and extract
        # ---------------------------------------------------------------------
        summary = task.inputs["summarize"]["summary"]
        metrics = task.inputs["extract"]["metrics"]

        final_report = (
            f"=== EXECUTIVE BRIEFING ===\n"
            f"Summary: {summary}\n"
            f"Revenue: {metrics['revenue']} (+{metrics['growth']}), "
            f"Margin: {metrics['operating_margin']}\n"
            f"Identified Risks: {', '.join(metrics['risk_factors'])}\n"
            f"=========================="
        )
        return TaskResult(ok=True, output={"report": final_report})

    return TaskResult(ok=False, error=f"Unknown task: {task.task_id}")


def build_agent_pipeline_workflow() -> Any:
    """Build the DAG for the agent research pipeline."""
    return (
        WorkflowBuilder("agent-pipeline-wf", "AI Research Agent Pipeline")
        .description("Retrieves data, runs parallel tasks, and synthesizes report")
        .default_timeout(10.0)
        .task(
            "retrieve",
            name="Retrieve Source Context",
            timeout_seconds=5.0,
        )
        .task(
            "summarize",
            name="Summarize Findings",
            dependencies=["retrieve"],
            retry_policy=RetryPolicy(max_attempts=3, delay_seconds=0.1),
            timeout_seconds=5.0,
        )
        .task(
            "extract",
            name="Extract Metrics & Entities",
            dependencies=["retrieve"],
            retry_policy=RetryPolicy(max_attempts=2, delay_seconds=0.1),
            timeout_seconds=5.0,
        )
        .task(
            "report",
            name="Generate Executive Report",
            dependencies=["summarize", "extract"],
            timeout_seconds=5.0,
        )
        .build()
    )


def main() -> None:
    print("=== Multi-Step AI Agent Pipeline ===")
    conn = get_connection("agent_runs.db")
    workflow = build_agent_pipeline_workflow()

    hooks = Hooks(
        on_task_start=lambda t: print(f"  [Hook] Task '{t.task_id}' started"),
        on_task_retry=lambda t: print(f"  [Hook] Task '{t.task_id}' entering retry wait"),
        on_task_succeeded=lambda t: print(f"  [Hook] Task '{t.task_id}' succeeded"),
        on_workflow_done=lambda wf, st: print(
            f"  [Hook] Workflow '{wf.workflow_id}' completed: {st.value}"
        ),
    )

    print("\n--- Executing Workflow with Concurrency (max_concurrency=2) ---")
    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=agent_runner,
        conn=conn,
        max_concurrency=2,
        executor="thread",
        hooks=hooks,
    )

    final_status = get_run_status(conn, run_id)
    print(f"\nWorkflow finished with status: {final_status.value}")

    # Inspect the final produced report from database
    cursor = conn.execute(
        "SELECT output_json FROM task_outputs WHERE run_id = ? AND task_id = 'report'",
        (run_id,),
    )
    row = cursor.fetchone()
    if row and row[0]:
        import json
        report_data = json.loads(row[0])
        print("\n" + report_data["report"])

    # Demonstration of resume capability on an existing run
    print("\n--- Testing Resume on Run ---")
    resumed_st = resume_run(
        conn=conn,
        run_id=run_id,
        task_runner=agent_runner,
        time_source=time.time,
    )
    print(f"Resume result: {resumed_st.value} (already completed tasks were safely preserved)")


if __name__ == "__main__":
    main()
