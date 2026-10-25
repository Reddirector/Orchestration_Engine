"""
Automated Incident Triage & Remediation Pipeline.

Demonstrates an autonomous SRE / DevSecOps incident response workflow:
1. 'ingest-alert': Receives and parses high-severity production alert.
2. Parallel Diagnostics (fan-out with max_concurrency=3):
   - 'check-logs': Analyzes error logs and stack traces.
   - 'check-db-pool': Checks connection pool saturation and query latency.
   - 'check-dependencies': Verifies upstream and downstream service health.
3. 'synthesize-rca': Fan-in synthesis combining diagnostic inputs to determine root cause.
4. 'execute-remediation': Executes targeted remediation action with automatic retry.
5. 'verify-resolution': Post-remediation verification confirming service health recovered.

Features highlighted:
- Fan-out concurrent diagnostics
- Fan-in multi-source root cause synthesis via task.inputs
- Automated remediation execution and verification
- Lifecycle hooks for Slack / PagerDuty / SRE notifications
- Zero runtime dependencies
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

# Simulated state for remediation attempt
_REMEDIATION_ATTEMPTS: dict[str, int] = {}


def incident_triage_runner(task: Task) -> TaskResult:
    """Task runner for autonomous incident triage and remediation."""
    step_name = task.name or task.task_id
    print(f"-> [Worker] Starting step: {step_name} (attempt {task.attempt_count})")

    if task.task_id == "ingest-alert":
        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Monitoring / Alert Webhook]
        # In a real environment, receives payload from Datadog, Prometheus, etc.
        # ---------------------------------------------------------------------
        alert_payload = {
            "incident_id": "INC-84920",
            "service": "checkout-api",
            "severity": "CRITICAL",
            "trigger": "HTTP 500 error rate spiked to 19.4% (threshold > 2.0%)",
            "timestamp": time.time(),
        }
        print(f"   [Alert Ingestion] {alert_payload['incident_id']} - {alert_payload['trigger']}")
        return TaskResult(ok=True, output=alert_payload)

    elif task.task_id == "check-logs":
        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Log Aggregator / CloudWatch / OpenSearch]
        # ---------------------------------------------------------------------
        time.sleep(0.02)
        log_findings = {
            "top_exception": "psycopg2.OperationalError: pool exhausted (max 50 conn)",
            "error_count_last_5m": 1420,
            "stray_transactions": 38,
        }
        print("   [Log Analysis] Found 1,420 connection pool exhaustion exceptions")
        return TaskResult(ok=True, output=log_findings)

    elif task.task_id == "check-db-pool":
        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Database Pool Metrics / pg_stat_activity]
        # ---------------------------------------------------------------------
        time.sleep(0.02)
        pool_metrics = {
            "total_capacity": 50,
            "active_connections": 50,
            "utilization_pct": 100.0,
            "longest_idle_in_tx_sec": 385.2,
        }
        print("   [Metrics Analysis] Connection pool utilization at 100.0% (saturation confirmed)")
        return TaskResult(ok=True, output=pool_metrics)

    elif task.task_id == "check-dependencies":
        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Dependency Health Checks / Ping]
        # ---------------------------------------------------------------------
        time.sleep(0.02)
        deps_health = {
            "payment_gateway": "HEALTHY (p95: 42ms)",
            "auth_service": "HEALTHY (p95: 15ms)",
            "database_primary": "REACHABLE (ping: 1.2ms)",
        }
        print("   [Dependencies] External dependencies healthy; database node reachable")
        return TaskResult(ok=True, output=deps_health)

    elif task.task_id == "synthesize-rca":
        # Fan-in: Combine findings from check-logs, check-db-pool, and check-dependencies
        logs = task.inputs.get("check-logs", {})
        metrics = task.inputs.get("check-db-pool", {})
        deps = task.inputs.get("check-dependencies", {})

        utilization = float(metrics.get("utilization_pct", 0))
        is_pool_exhausted = (
            "pool exhausted" in logs.get("top_exception", "")
            and utilization >= 95.0
        )
        cause = (
            "DATABASE_CONNECTION_POOL_EXHAUSTION"
            if is_pool_exhausted
            else "UNKNOWN"
        )

        rca_report = {
            "primary_cause": cause,
            "evidence": {
                "top_log_error": logs.get("top_exception"),
                "pool_saturation": f"{metrics.get('utilization_pct')}%",
                "idle_in_tx_seconds": metrics.get("longest_idle_in_tx_sec"),
            },
            "dependencies_status": deps,
            "recommended_action": "TERMINATE_IDLE_TX_AND_RESIZE_POOL",
        }
        print(f"   [RCA Engine] Root Cause Identified: {rca_report['primary_cause']}")
        return TaskResult(ok=True, output=rca_report)

    elif task.task_id == "execute-remediation":
        rca = task.inputs.get("synthesize-rca", {})

        # Simulate transient network hiccup during remediation dispatch on attempt 1
        run_key = f"{getattr(task, '_run_id', 'local')}:{task.task_id}"
        attempts = _REMEDIATION_ATTEMPTS.get(run_key, 0) + 1
        _REMEDIATION_ATTEMPTS[run_key] = attempts

        if attempts == 1:
            print("   [Remediation Tool] Connection reset (simulating transient network drop)")
            return TaskResult(ok=False, error="Transient network reset connecting to admin port")

        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Automated Ops / Kubernetes API / PgBouncer Admin]
        # ---------------------------------------------------------------------
        time.sleep(0.03)
        remediation_result = {
            "action_executed": rca.get("recommended_action"),
            "idle_connections_terminated": 38,
            "new_pool_capacity": 100,
            "status": "APPLIED",
        }
        print("   [Remediation Tool] Terminated 38 stale connections, scaled pool capacity to 100")
        return TaskResult(ok=True, output=remediation_result)

    elif task.task_id == "verify-resolution":
        # ---------------------------------------------------------------------
        # [INTEGRATION POINT: Post-Mitigation Verification]
        # ---------------------------------------------------------------------
        time.sleep(0.02)
        verification_metrics: dict[str, Any] = {
            "error_rate_pct": 0.08,
            "pool_utilization_pct": 24.0,
            "p95_latency_ms": 38.4,
            "incident_status": "RESOLVED",
        }
        err_pct = float(verification_metrics["error_rate_pct"])
        is_healthy = err_pct < 1.0
        print(f"   [Verification] Error rate dropped to {err_pct}% (Target < 1.0%)")
        print(f"   [Verification] Incident Status: {verification_metrics['incident_status']}")
        return TaskResult(ok=is_healthy, output=verification_metrics)

    return TaskResult(ok=False, error=f"Unknown task: {task.task_id}")


def build_incident_triage_workflow() -> Workflow:
    """Constructs the incident response and automated triage DAG."""
    builder = WorkflowBuilder(
        "incident-triage-pipeline",
        name="Incident Triage & Remediation",
        description="Autonomous incident ingestion, parallel diagnostics, RCA, and mitigation.",
        default_timeout_seconds=30.0,
    )

    builder.task(
        "ingest-alert",
        name="Ingest Incident Alert",
        description="Parses incoming alert notification",
        timeout_seconds=5.0,
    )
    builder.task(
        "check-logs",
        name="Scan Application Logs",
        description="Extracts exception frequencies from log streams",
        dependencies=["ingest-alert"],
        timeout_seconds=10.0,
    )
    builder.task(
        "check-db-pool",
        name="Inspect Connection Pool",
        description="Checks database saturation and active transactions",
        dependencies=["ingest-alert"],
        timeout_seconds=10.0,
    )
    builder.task(
        "check-dependencies",
        name="Ping Dependencies",
        description="Checks health of external upstream/downstream services",
        dependencies=["ingest-alert"],
        timeout_seconds=10.0,
    )
    builder.task(
        "synthesize-rca",
        name="Synthesize Root Cause (RCA)",
        description="Fan-in correlation of all diagnostic streams",
        dependencies=["check-logs", "check-db-pool", "check-dependencies"],
        timeout_seconds=10.0,
    )
    builder.task(
        "execute-remediation",
        name="Execute Remediation Action",
        description="Applies automated mitigation with retries",
        dependencies=["synthesize-rca"],
        retry_policy=RetryPolicy(max_attempts=3, delay_seconds=0.1),
        timeout_seconds=15.0,
    )
    builder.task(
        "verify-resolution",
        name="Verify Incident Resolution",
        description="Confirms error rates and system metrics recovered",
        dependencies=["execute-remediation"],
        timeout_seconds=10.0,
    )

    return builder.build()


def main() -> None:
    print("=== Automated Incident Triage & Remediation Pipeline ===\n")
    workflow = build_incident_triage_workflow()
    conn = get_connection(":memory:")

    # SRE Notification Hooks
    hooks = Hooks(
        on_task_start=lambda t: print(f"  [Notification] Step '{t.name}' started"),
        on_task_retry=lambda t: print(
            f"  [Notification] Step '{t.name}' retrying after transient error"
        ),
        on_task_succeeded=lambda t: print(f"  [Notification] Step '{t.name}' completed"),
        on_workflow_done=lambda wf, st: print(
            f"  [Notification] Incident workflow concluded: {st.value.upper()}"
        ),
    )

    print("--- Executing Incident Triage Workflow (Concurrency: 3) ---")
    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=incident_triage_runner,
        conn=conn,
        hooks=hooks,
        max_concurrency=3,
    )

    final_status = get_run_status(conn, run_id)
    print(f"\nFinal Workflow Status: {final_status.value}")
    assert final_status.value == "succeeded", f"Expected succeeded, got {final_status.value}"
    print("Incident triage and remediation executed successfully!\n")


if __name__ == "__main__":
    main()
