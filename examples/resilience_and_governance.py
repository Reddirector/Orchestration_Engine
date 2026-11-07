#!/usr/bin/env python3
"""
Enterprise Resilience, Fair-Share Multi-Tenancy & Governance Showcase.

Demonstrates 5 advanced architectural systems in Orchestration Engine:
  1. Distributed Work Stealing & Dead Worker Reclamation (WorkStealingRegistry)
  2. Historical Backfill & Deterministic Catchup Engine (BackfillExecutor)
  3. Multi-Tenant Concurrency & Rate Quota Engine (TenantQuotaManager)
  4. Task Interceptors & Middleware Pipeline (secret masking, timing, audit logs)
  5. Self-Healing Workflow Watchdog & Auto-Supervisor (WorkflowSupervisor)

Zero third-party runtime dependencies. Uses strictly standard library Python 3.10+.
"""

import tempfile
from typing import Any

from orchestration_engine import (
    AutoRemedy,
    BackfillExecutor,
    CatchupPolicy,
    MiddlewarePipeline,
    SupervisorPolicy,
    Task,
    TaskResult,
    TenantQuota,
    TenantQuotaManager,
    WorkflowBuilder,
    WorkflowSupervisor,
    WorkStealingRegistry,
    audit_logging_middleware,
    execution_timer_middleware,
    generate_backfill_plan,
    get_connection,
    secret_masking_middleware,
)


def main() -> None:
    print("=" * 70)
    print("🛡️ Enterprise Resilience, Fair-Share Multi-Tenancy & Governance Showcase")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = f"{tmp_dir}/cluster.db"
        conn = get_connection(db_path)

        # ----------------------------------------------------------------------
        # 1. Distributed Work Stealing & Dead Worker Reclamation
        # ----------------------------------------------------------------------
        print("\n[1/5] Demonstrating Distributed Work Stealing & Dead Worker Reclamation...")
        registry = WorkStealingRegistry(conn)

        # Register workers
        registry.register_worker("worker_alpha", capacity=4)
        registry.register_worker("worker_beta", capacity=4)

        # Enqueue 4 tasks on worker_alpha (heavy load)
        for i in range(4):
            registry.enqueue_task(f"job_{i}", assigned_worker_id="worker_alpha", state="READY")

        print(f"  -> Initial queue for worker_alpha: {registry.get_assigned_tasks('worker_alpha')}")
        print(f"  -> Initial queue for worker_beta:  {registry.get_assigned_tasks('worker_beta')}")

        # Worker beta steals tasks
        stolen = registry.steal_work("worker_beta", max_tasks=2)
        print(f"  ✓ worker_beta stole {len(stolen)} tasks from overloaded worker_alpha: {stolen}")
        print(f"  -> Rebalanced worker_alpha: {registry.get_assigned_tasks('worker_alpha')}")
        print(f"  -> Rebalanced worker_beta:  {registry.get_assigned_tasks('worker_beta')}")

        # Simulate dead worker reclamation
        registry.register_worker("worker_crashed", capacity=2, time_source=100.0)
        registry.enqueue_task(
            "orphaned_payment",
            assigned_worker_id="worker_crashed",
            state="RUNNING",
        )
        reclaimed = registry.reclaim_dead_workers(timeout_seconds=30.0, time_source=200.0)
        print(f"  ✓ Watchdog detected crashed node and reclaimed orphaned tasks: {reclaimed}")

        # ----------------------------------------------------------------------
        # 2. Historical Backfill & Deterministic Catchup Engine
        # ----------------------------------------------------------------------
        print("\n[2/5] Compiling & Executing Historical Backfill Plan...")
        backfill_wf = (
            WorkflowBuilder("daily-reconciliation")
            .task("reconcile_window", name="Reconcile Historical Ledger")
            .build()
        )

        def backfill_runner(t: Task) -> TaskResult:
            w_start = t.inputs.get("window_start")
            w_end = t.inputs.get("window_end")
            return TaskResult(ok=True, output={"reconciled_range": f"{w_start}->{w_end}"})

        plan = generate_backfill_plan(
            workflow_id="daily-reconciliation",
            start_time=1700000000.0,
            end_time=1700000300.0,
            interval_seconds=100.0,
            catchup_policy=CatchupPolicy.ALL,
            jitter_max_seconds=5.0,
        )

        executor = BackfillExecutor(conn)
        executed_windows = executor.run_plan(plan, backfill_wf, backfill_runner)
        print(f"  ✓ Executed {len(executed_windows)} backfill windows sequentially:")
        for w in executed_windows:
            print(f"    - Window {w.window_id}: status={w.status}, jitter={w.jitter_seconds}s")

        # ----------------------------------------------------------------------
        # 3. Multi-Tenant Fair-Share Concurrency & Rate Quotas
        # ----------------------------------------------------------------------
        print("\n[3/5] Enforcing Multi-Tenant Fair-Share Rate & Concurrency Limits...")
        quota_mgr = TenantQuotaManager()
        quota_mgr.set_quota(
            TenantQuota(
                tenant_id="tenant_fintech",
                max_concurrent=2,
                rate_limit_per_second=10.0,
                burst_capacity=3.0,
            )
        )

        # Acquire quota slots
        acq1 = quota_mgr.acquire("tenant_fintech")
        acq2 = quota_mgr.acquire("tenant_fintech")
        acq3 = quota_mgr.acquire("tenant_fintech")
        print(f"  -> Slot 1 acquired: {acq1}")
        print(f"  -> Slot 2 acquired: {acq2}")
        print(f"  -> Slot 3 acquired: {acq3} (blocked by max_concurrent=2)")
        quota_mgr.release("tenant_fintech")
        print("  ✓ Released slot 1; quota usage normalized.")

        # ----------------------------------------------------------------------
        # 4. Task Interceptors & Middleware Pipeline
        # ----------------------------------------------------------------------
        print("\n[4/5] Executing Tasks via Composable Onion Middleware Pipeline...")
        audit_records: list[dict[str, Any]] = []
        metrics: dict[str, float] = {}

        pipeline = (
            MiddlewarePipeline()
            .use(audit_logging_middleware(audit_records))
            .use(execution_timer_middleware(lambda tid, ms: metrics.update({tid: ms})))
            .use(secret_masking_middleware())
        )

        task_wf = (
            WorkflowBuilder("payment-processor")
            .task("process_payment", name="Process Customer Charge")
            .build()
        )
        charge_task = task_wf.tasks[0]
        charge_task.inputs = {
            "order_id": "ord_88291",
            "api_key": "sk_live_secret_key_9999",
            "card_token": "tok_visa_4242",
        }

        def charge_runner(t: Task) -> TaskResult:
            # Inputs were masked before entering business logic
            return TaskResult(
                ok=True,
                output={
                    "status": "CHARGED",
                    "auth_token": "secret_auth_token_xyz",
                    "amount": 49.99,
                },
            )

        wrapped_runner = pipeline.wrap_runner(charge_runner, run_id="run_pay_1")
        result = wrapped_runner(charge_task)

        print(f"  ✓ Masked Inputs:  {charge_task.inputs}")
        print(f"  ✓ Masked Outputs: {result.output}")
        print(f"  ✓ Task Execution Duration: {metrics.get('process_payment')} ms")
        print(f"  ✓ Audit Trail Generated: {len(audit_records)} records")

        # ----------------------------------------------------------------------
        # 5. Self-Healing Workflow Watchdog & Auto-Supervisor
        # ----------------------------------------------------------------------
        print("\n[5/5] Demonstrating Self-Healing Workflow Watchdog...")
        supervisor = WorkflowSupervisor(
            conn,
            SupervisorPolicy(stuck_timeout_seconds=30.0, default_remedy=AutoRemedy.RETRY),
        )

        # Inject simulated zombie run (e.g. killed worker host)
        with conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, workflow_id, started_at, status, definition_json)
                VALUES ('run_zombie_demo', 'zombie-wf', 100.0, 'running', '{}')
                """
            )
            conn.execute(
                """
                INSERT INTO task_events (
                    run_id, workflow_id, task_id,
                    old_state, new_state, timestamp, attempt_count, error
                ) VALUES (
                    'run_zombie_demo', 'zombie-wf', 't_hang',
                    'ready', 'running', 100.0, 1, NULL
                )
                """
            )

        # Watchdog scans at t=150.0 (50s elapsed > 30s threshold)
        incidents = supervisor.scan_and_heal(time_source=150.0)
        print(f"  ✓ Watchdog identified {len(incidents)} zombie incident(s):")
        for inc in incidents:
            print(f"    - Task '{inc.task_id}': {inc.reason} -> Remedy: {inc.remedy_applied}")

        print("\n" + "=" * 70)
        print("🎉 All 5 Resilience, Fair-Share & Governance Systems Demonstrated!")
        print("=" * 70)


if __name__ == "__main__":
    main()
