"""Event-Driven Processing, Distributed Idempotency, and SLA Monitoring Showcase.

Demonstrates production enterprise patterns with zero external dependencies:
1. EventBus routing incoming cloud events/webhooks to workflow executions.
2. Distributed IdempotencyStore preventing duplicate side-effects during retries.
3. WorkflowBlackboard providing atomic shared memory across tasks.
4. SLAMonitor detecting SLA business deadline breaches.
5. Log compaction pruning microsecond events for completed runs.
"""

from __future__ import annotations

import tempfile
import time
from typing import Any

from orchestration_engine import (
    EventBus,
    IdempotencyStore,
    SLAMonitor,
    SLAPolicy,
    TaskResult,
    WorkflowBlackboard,
    WorkflowBuilder,
    compact_event_log,
    get_connection,
    idempotent,
    run_workflow,
)


def run_showcase() -> None:
    print("=" * 70)
    print("⚡ Event-Driven Idempotency, Shared Blackboard & SLA Showcase")
    print("=" * 70)

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = tmp.name
        conn = get_connection(db_path)

        # 1. Initialize Event Bus and Stores
        bus = EventBus()
        idempotency_store = IdempotencyStore(db_path)
        sla_monitor = SLAMonitor()

        def _on_warn(tid: str, el: float, dl: float) -> None:
            print(f"  [SLA Alert] Task '{tid}' at {el:.2f}s (threshold {dl*0.5:.2f}s)")

        def _on_breach(tid: str, el: float, dl: float) -> None:
            print(f"  [SLA BREACH 🚨] Task '{tid}' breached {dl:.1f}s deadline ({el:.2f}s)")

        # Track SLA policy: task must finish within 1.0s
        sla_monitor.register_sla(
            "fulfill_order",
            SLAPolicy(
                deadline_seconds=1.0,
                warning_ratio=0.5,
                on_warning=_on_warn,
                on_breach=_on_breach,
            ),
        )

        charge_execution_count = 0

        # Idempotent payment processor
        @idempotent(idempotency_store, key_func=lambda order_id, amt: f"payment:{order_id}")
        def charge_payment(order_id: str, amt: float) -> dict[str, Any]:
            nonlocal charge_execution_count
            charge_execution_count += 1
            print(f"  [Payment Gateway] Processing real card charge for {order_id}: ${amt:.2f}")
            return {"tx_id": f"tx_{order_id}", "status": "approved", "amount": amt}

        # 2. Build Event-Triggered Workflow
        wf = (
            WorkflowBuilder("ecommerce-order")
            .task("validate_order")
            .task("process_payment", dependencies=["validate_order"])
            .task("fulfill_order", dependencies=["process_payment"])
            .build()
        )

        # 3. Subscribe Workflow to 'orders.checkout' Event Topic
        def on_order_event(event: Any) -> None:
            order_data = event.payload
            order_id = order_data["order_id"]
            amount = order_data["amount"]
            print(f"\n[Event Bus] Received '{event.topic}': Order {order_id} (${amount:.2f})")

            # Setup Blackboard for this run
            run_id = f"run-{order_id}"
            blackboard = WorkflowBlackboard(run_id, db_path)
            blackboard.set("customer_tier", order_data.get("tier", "standard"))

            def runner(task: Any) -> Any:
                if task.task_id == "validate_order":
                    blackboard.increment("steps_completed")
                    return TaskResult(ok=True, output={"valid": True})

                elif task.task_id == "process_payment":
                    # Charge card idempotently
                    receipt = charge_payment(order_id, amount)
                    blackboard.increment("steps_completed")
                    return TaskResult(ok=True, output=receipt)

                elif task.task_id == "fulfill_order":
                    sla_monitor.record_start("fulfill_order")
                    # Simulate processing time
                    time.sleep(0.05)
                    sla_monitor.record_completion("fulfill_order")
                    blackboard.increment("steps_completed")
                    tier = blackboard.get("customer_tier")
                    shipping = "expedited" if tier == "vip" else "standard"
                    return TaskResult(ok=True, output={"shipping": shipping})

                return TaskResult(ok=True)

            res = run_workflow(wf, {}, time.time, runner, conn, run_id=run_id)
            print(f"  Run '{res}' completed. Blackboard dump: {blackboard.dump_state()}")

        bus.subscribe("orders.*", on_order_event)

        # 4. Trigger Event 1: Normal Order
        bus.publish("orders.checkout", {"order_id": "ORD-101", "amount": 89.99, "tier": "vip"})

        # 5. Simulate duplicate webhook retry with identical order_id
        print("\n[Simulation] Duplicate webhook delivery arriving (simulating network retry)...")
        bus.publish("orders.checkout", {"order_id": "ORD-101", "amount": 89.99, "tier": "vip"})

        # 6. Verify Exactly-Once Execution
        print(f"\n[Verification] Total physical payment charges executed: {charge_execution_count}")
        assert charge_execution_count == 1, "Duplicate payment was prevented by IdempotencyStore!"
        print("  ✓ Exactly-Once Semantics verified: duplicate charge was intercepted.")

        # 7. Test Log Compaction
        pruned_events = compact_event_log(conn, older_than_seconds=0.0, keep_failed=True)
        print(f"\n[Log Compaction] Pruned {pruned_events} historical event records from SQLite.")

        conn.close()


if __name__ == "__main__":
    run_showcase()
