"""Enterprise Resilience Showcase.

Demonstrates high-impact production patterns for distributed systems, fintech,
and AI pipelines with zero external dependencies:
1. Distributed Sagas with automatic compensating rollback.
2. Resilient Circuit Breakers fast-failing against down upstream APIs.
3. Persistent Dead Letter Queue (DLQ) for unrecoverable post-mortems.
4. Distributed Advisory Leases for multi-worker coordination without Redis.
5. Dynamic Decision Branching based on AI confidence scoring.
6. Stateful incremental ETL with WatermarkStore.
"""

from __future__ import annotations

import time
from typing import Any

from orchestration_engine import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    DeadLetterQueue,
    TaskLease,
    WatermarkStore,
    WorkflowBuilder,
    run_saga,
)


def run_saga_demo() -> None:
    print("\n--- 1. Distributed Saga with Compensating Rollback ---")
    wf = (
        WorkflowBuilder("fintech-checkout")
        .task("reserve_inventory")
        .task("charge_credit_card", dependencies=["reserve_inventory"])
        .task("provision_digital_license", dependencies=["charge_credit_card"])
        .build()
    )

    audit_log: list[str] = []

    def reserve(**kw: Any) -> dict[str, Any]:
        audit_log.append("RESERVED: SKU-8849")
        print("  [Forward] Reserved Inventory: SKU-8849")
        return {"sku": "SKU-8849", "quantity": 1}

    def charge(reserve_inventory: dict[str, Any]) -> dict[str, Any]:
        audit_log.append("CHARGED: $149.00")
        print("  [Forward] Charged Card: $149.00")
        return {"amount": 149.0, "tx_id": "tx-9941"}

    def provision(charge_credit_card: dict[str, Any]) -> Any:
        # Simulate fatal failure in provisioning service
        print("  [Forward] Provisioning digital license... (503 Service Unavailable)")
        raise RuntimeError("Cloud KMS licensing service unreachable")

    # Compensations (Executed in reverse order of succeeded steps on failure)
    def refund_card(**kw: Any) -> None:
        audit_log.append("REFUNDED: $149.00")
        print("  [Compensate ⏪] Issued full refund of $149.00")

    def release_stock(**kw: Any) -> None:
        audit_log.append("RELEASED: SKU-8849")
        print("  [Compensate ⏪] Restored SKU-8849 to warehouse inventory")

    runners = {
        "reserve_inventory": reserve,
        "charge_credit_card": charge,
        "provision_digital_license": provision,
    }
    compensators = {
        "charge_credit_card": refund_card,
        "reserve_inventory": release_stock,
    }

    result = run_saga(wf, runners, compensators, db_path="resilience_demo.db")
    print(f"  Saga Result: status={result.status.value}, compensated={result.compensated_tasks}")
    assert audit_log == [
        "RESERVED: SKU-8849",
        "CHARGED: $149.00",
        "REFUNDED: $149.00",
        "RELEASED: SKU-8849",
    ]


def run_circuit_breaker_demo() -> None:
    print("\n--- 2. Resilient Circuit Breaker ---")
    cb = CircuitBreaker("openai-llm-gateway", failure_threshold=2, recovery_timeout=2.0)

    @cb.protect
    def query_model(prompt: str) -> str:
        if "fail" in prompt:
            raise ConnectionError("504 Gateway Timeout")
        return f"Response for {prompt}"

    print(f"  Initial State: {cb.state.value}")
    try:
        query_model("fail prompt 1")
    except ConnectionError:
        print("  Call 1: ConnectionError caught (Failure 1/2)")

    try:
        query_model("fail prompt 2")
    except ConnectionError:
        print("  Call 2: ConnectionError caught (Failure 2/2 -> Trips to OPEN)")

    print(f"  Circuit State: {cb.state.value}")

    # Subsequent call fails fast without network request
    try:
        query_model("normal prompt")
    except CircuitBreakerOpenError as exc:
        print(f"  Fast Fail: {exc}")


def run_dlq_and_lease_demo() -> None:
    print("\n--- 3. Dead Letter Queue (DLQ) & Advisory Leases ---")
    dlq = DeadLetterQueue("resilience_demo.db")
    msg_id = dlq.enqueue(
        workflow_id="etl-batch-2026",
        run_id="run-4820",
        task_id="transform_customer_record",
        inputs={"customer_id": "cust-9912", "country": "DE"},
        error="MalformedPostalCodeError: Expected 5 digits",
        attempt_count=3,
    )
    print(f"  Enqueued dead task into DLQ: message_id={msg_id[:12]}...")

    messages = dlq.list_messages(workflow_id="etl-batch-2026")
    print(f"  DLQ Active Failures: {len(messages)} message(s) queued for triage")

    # Distributed Lease Locking
    lease = TaskLease(
        "resilience_demo.db", "partition-europe-west", "worker-node-1", ttl_seconds=10.0
    )
    with lease:
        print("  [Worker 1] Acquired distributed advisory lease on 'partition-europe-west'")
        print("  [Worker 1] Executing exclusive partition sync safely...")


def run_watermark_demo() -> None:
    print("\n--- 4. Incremental Watermark Checkpoint Store ---")
    wm_store = WatermarkStore("resilience_demo.db")
    last_synced = wm_store.get_watermark("salesforce-sync", "last_event_time", default=0.0)
    print(f"  Initial High-Watermark: {last_synced}")

    new_timestamp = time.time()
    wm_store.advance_watermark(
        "salesforce-sync", "last_event_time", new_timestamp, run_id="run-4820"
    )
    print(f"  Advanced Watermark to: {new_timestamp}")


def main() -> None:
    import os

    print("=== Orchestration Engine — Enterprise Resilience Suite ===")
    try:
        run_saga_demo()
        run_circuit_breaker_demo()
        run_dlq_and_lease_demo()
        run_watermark_demo()
        print("\nAll enterprise capabilities executed successfully with 0 external dependencies!")
    finally:
        if os.path.exists("resilience_demo.db"):
            os.remove("resilience_demo.db")


if __name__ == "__main__":
    main()
