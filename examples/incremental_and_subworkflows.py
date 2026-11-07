"""Example: Advanced Architectural Systems.

Demonstrates:
1. Hierarchical Sub-Workflows: Nesting an entire child DAG inside a parent task step.
2. Content-Addressable Incremental Evaluation: Skipping execution of unchanged tasks.
3. Compressed Blob Offloading: Storing large payloads (>64KB) outside SQLite WAL.
4. Adaptive Concurrency: Real-time AIMD latency and failure backpressure auto-tuning.
5. CDC Multi-Node Replication: Synchronizing state and outputs between primary & replica.
"""

from __future__ import annotations

import tempfile

from orchestration_engine import (
    AdaptiveConcurrencyController,
    AdaptiveConcurrencyPolicy,
    BlobStore,
    CDCReplicationSource,
    CDCReplicationTarget,
    IncrementalStore,
    Task,
    TaskResult,
    WorkflowBuilder,
    get_connection,
    get_subworkflow_tree,
    make_subworkflow_runner,
    run_workflow,
    wrap_incremental,
)


def main() -> None:
    print("=" * 70)
    print("🚀 Advanced Architectural Systems Showcase")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        primary_db = f"{tmpdir}/primary.db"
        replica_db = f"{tmpdir}/replica.db"
        blob_dir = f"{tmpdir}/blobs"

        conn_prim = get_connection(primary_db)
        blob_store = BlobStore(storage_dir=blob_dir)
        inc_store = IncrementalStore(primary_db)

        # ---------------------------------------------------------------------
        # 1. Hierarchical Sub-Workflow Definition
        # ---------------------------------------------------------------------
        print("\n[1/5] Defining Nested Child Sub-Workflow...")
        child_wf = (
            WorkflowBuilder("child_data_cleanup")
            .task("sanitize_text", name="Sanitize Text")
            .task("tokenize", name="Tokenize Chunks", dependencies=["sanitize_text"])
            .build()
        )

        def child_runner(task: Task) -> TaskResult:
            print(f"  -> [Sub-Workflow Task] Executing '{task.task_id}'")
            if task.task_id == "sanitize_text":
                return TaskResult(ok=True, output={"clean_lines": 1200})
            return TaskResult(ok=True, output={"tokens_generated": 48000})

        child_task_runner = make_subworkflow_runner(
            subworkflow=child_wf,
            child_task_runner=child_runner,
            conn_factory=lambda: get_connection(primary_db),
        )

        # ---------------------------------------------------------------------
        # 2. Parent Workflow with Large Payload Blob Offloading
        # ---------------------------------------------------------------------
        print("\n[2/5] Constructing Parent Workflow with Compressed Blob Offloading...")
        parent_wf = (
            WorkflowBuilder("parent_ingest_pipeline")
            .task("extract_large_corpus", name="Extract Corpus")
            .task("run_cleanup", name="Nested Cleanup DAG", dependencies=["extract_large_corpus"])
            .task("finalize_summary", name="Final Report", dependencies=["run_cleanup"])
            .build()
        )

        # Adaptive backpressure controller
        adapt_policy = AdaptiveConcurrencyPolicy(
            min_concurrency=1,
            max_concurrency=8,
            initial_concurrency=2,
        )
        adaptive_ctrl = AdaptiveConcurrencyController(adapt_policy)
        adaptive_hooks = adaptive_ctrl.create_hooks()

        def parent_runner(task: Task) -> TaskResult:
            if task.task_id == "extract_large_corpus":
                # Generate large 100KB payload and offload to BlobStore
                large_matrix = {"embeddings": [float(i) for i in range(12000)]}
                pointer = blob_store.offload_if_large(large_matrix, threshold_bytes=1000)
                print(f"  [BlobStore] Offloaded payload: hash={pointer.get('blob_hash')[:12]}...")
                return TaskResult(ok=True, output=pointer)

            if task.task_id == "run_cleanup":
                return child_task_runner(task)

            # Finalize summary
            print(f"  -> [Parent Task] Executing '{task.task_id}'")
            return TaskResult(ok=True, output={"status": "completed"})

        # Wrap with incremental caching
        wrapped_runner, get_inc_summary = wrap_incremental(
            store=inc_store,
            runner=parent_runner,
            code_fingerprints={"extract_large_corpus": "v1.0", "finalize_summary": "v1.0"},
        )

        # ---------------------------------------------------------------------
        # 3. Execution Pass 1: Fresh Run
        # ---------------------------------------------------------------------
        print("\n[3/5] Executing Primary Workflow (Pass 1 - Fresh)...")
        run_id_1 = run_workflow(
            workflow=parent_wf,
            task_states={t.task_id: t.state for t in parent_wf.tasks},
            time_source=lambda: 1000.0,
            task_runner=wrapped_runner,
            conn=conn_prim,
            hooks=adaptive_hooks,
        )
        print(f"  ✓ Parent Run Finished: {run_id_1}")
        tree = get_subworkflow_tree(conn_prim, run_id_1)
        print(
            f"  ✓ Sub-Workflow Tree: Nested child run recorded ({len(tree['children'])} sub-runs)"
        )

        summary_1 = get_inc_summary()
        print(
            f"  ✓ Incremental Status: Executed={summary_1.executed_task_ids}, "
            f"Skipped={summary_1.skipped_task_ids}"
        )

        # ---------------------------------------------------------------------
        # 4. Execution Pass 2: Incremental Cached Run
        # ---------------------------------------------------------------------
        print("\n[4/5] Executing Pass 2 (Unchanged Inputs & Code - Incremental Evaluation)...")
        parent_wf_2 = (
            WorkflowBuilder("parent_ingest_pipeline")
            .task("extract_large_corpus", name="Extract Corpus")
            .task("run_cleanup", name="Nested Cleanup DAG", dependencies=["extract_large_corpus"])
            .task("finalize_summary", name="Final Report", dependencies=["run_cleanup"])
            .build()
        )

        wrapped_runner_2, get_inc_summary_2 = wrap_incremental(
            store=inc_store,
            runner=parent_runner,
            code_fingerprints={"extract_large_corpus": "v1.0", "finalize_summary": "v1.0"},
        )

        run_id_2 = run_workflow(
            workflow=parent_wf_2,
            task_states={t.task_id: t.state for t in parent_wf_2.tasks},
            time_source=lambda: 1010.0,
            task_runner=wrapped_runner_2,
            conn=conn_prim,
            hooks=adaptive_hooks,
        )
        summary_2 = get_inc_summary_2()
        print(f"  ✓ Parent Run Finished: {run_id_2}")
        print(
            f"  ✓ Incremental Status: Executed={summary_2.executed_task_ids}, "
            f"Skipped={summary_2.skipped_task_ids}"
        )

        # ---------------------------------------------------------------------
        # 5. CDC Multi-Node Replication Synchronization
        # ---------------------------------------------------------------------
        print("\n[5/5] Replicating Primary Events & Outputs to Edge Replica DB...")
        source = CDCReplicationSource(primary_db)
        target = CDCReplicationTarget(replica_db)

        cdc_batch = source.read_changes(since_event_id=0, limit=200)
        synced_count = target.apply_batch(cdc_batch)
        print(
            f"  ✓ Replicated {synced_count} transition events, {len(cdc_batch.runs)} runs, "
            f"and {len(cdc_batch.outputs)} task outputs to replica database!"
        )

        print("\n" + "=" * 70)
        print("🎉 All 5 Advanced Architectural Systems Successfully Demonstrated!")
        print("=" * 70)


if __name__ == "__main__":
    main()
