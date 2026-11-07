"""Chaos Engineering, Schema Contracts, and Time-Travel Replay Showcase.

Demonstrates production resilience patterns with zero third-party dependencies:
1. Strict DataContract schemas validating input and output shapes.
2. Controlled ChaosPolicy fault injection to simulate transient microservice failures.
3. Time-travel inspection to examine historical run state at each step.
4. Forking execution from a failed task checkpoint without re-running earlier steps.
5. Semantic workflow versioning hash to verify code stability.
"""

from __future__ import annotations

import tempfile
import time
from typing import Any

from orchestration_engine import (
    ChaosPolicy,
    DataContract,
    Field,
    TaskResult,
    WorkflowBuilder,
    compute_workflow_hash,
    enforce_contract,
    fork_run_from_task,
    get_connection,
    resume_run,
    run_workflow,
    time_travel_inspect,
    with_chaos,
)


def run_showcase() -> None:
    print("=" * 70)
    print("🛡️ Schema Contracts, Chaos Injection, and Time-Travel Replay Showcase")
    print("=" * 70)

    # 1. Define Data Contracts for tasks
    invoice_contract = DataContract(
        {
            "invoice_id": Field(type=str, regex=r"^INV-[0-9]{4}$"),
            "amount": Field(type=(int, float), min_val=1.0),
            "currency": Field(type=str, choices={"USD", "EUR", "GBP"}),
        },
        name="InvoiceSchema",
    )

    payment_receipt_contract = DataContract(
        {
            "tx_id": Field(type=str, regex=r"^tx_[a-z0-9]+$"),
            "status": Field(choices={"paid", "settled"}),
        },
        name="ReceiptSchema",
    )

    # 2. Build Workflow
    wf = (
        WorkflowBuilder("fintech-billing")
        .task("create_invoice")
        .task("charge_customer", dependencies=["create_invoice"])
        .task("send_receipt", dependencies=["charge_customer"])
        .build()
    )

    wf_hash = compute_workflow_hash(wf)
    print(f"\n[Versioning] Workflow '{wf.workflow_id}' semantic hash: {wf_hash}")

    # 3. Task Implementations with Contract Enforcement
    @enforce_contract(output_contract=invoice_contract)
    def create_invoice() -> dict[str, Any]:
        print("  [Step 1] Generated Invoice: INV-8821 ($250.00 USD)")
        return {"invoice_id": "INV-8821", "amount": 250.00, "currency": "USD"}

    # Simulate chaos fault injection on payment gateway
    chaos_policy = ChaosPolicy(
        failure_rate=1.0,
        task_targets={"charge_customer"},
    )

    @with_chaos(chaos_policy)
    def charge_with_chaos(create_invoice: dict[str, Any]) -> dict[str, Any]:
        print(f"  [Step 2] Charging {create_invoice['currency']} {create_invoice['amount']}...")
        return {"tx_id": "tx_9941a", "status": "paid"}

    def safe_charge(create_invoice: dict[str, Any]) -> dict[str, Any]:
        curr = create_invoice["currency"]
        amt = create_invoice["amount"]
        print(f"  [Step 2 - Fixed] Charging {curr} {amt}...")
        return {"tx_id": "tx_9941a", "status": "paid"}

    @enforce_contract(output_contract=payment_receipt_contract)
    def send_receipt(charge_customer: dict[str, Any]) -> dict[str, Any]:
        print(f"  [Step 3] Delivery Receipt for transaction {charge_customer['tx_id']}")
        return {"tx_id": charge_customer["tx_id"], "status": "settled"}

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = tmp.name
        conn = get_connection(db_path)

        def runner_fail(task: Any) -> Any:
            try:
                if task.task_id == "create_invoice":
                    return TaskResult(ok=True, output=create_invoice())
                elif task.task_id == "charge_customer":
                    inp = task.inputs.get("create_invoice", {})
                    return TaskResult(ok=True, output=charge_with_chaos(inp))
                elif task.task_id == "send_receipt":
                    inp = task.inputs.get("charge_customer", {})
                    return TaskResult(ok=True, output=send_receipt(inp))
                return TaskResult(ok=True)
            except Exception as exc:
                return TaskResult(ok=False, error=str(exc))

        print("\n🚀 1. Running initial workflow with Chaos Fault Injection...")
        run_id = run_workflow(wf, {}, time.time, runner_fail, conn)
        print(f"  Run '{run_id}' concluded with failure as expected under chaos.")

        # 4. Time-Travel Inspection
        print("\n⏪ 2. Time-Travel Inspection of Run Event Log:")
        snapshot = time_travel_inspect(conn, run_id)
        for t_id, state in snapshot.task_states.items():
            out_info = ""
            if t_id in snapshot.task_outputs:
                out_info = f" -> Output: {snapshot.task_outputs[t_id]}"
            err_info = ""
            if snapshot.task_errors.get(t_id):
                err_info = f" -> Error: {snapshot.task_errors[t_id]}"
            print(f"  Task '{t_id}': state={state}{out_info}{err_info}")

        # 5. Fork Run from Task 'charge_customer'
        print("\n🔀 3. Forking execution from failed step 'charge_customer'...")
        forked_run_id = fork_run_from_task(conn, run_id, restart_from_task_id="charge_customer")
        print(f"  New Forked Run ID: {forked_run_id}")
        forked_snap = time_travel_inspect(conn, forked_run_id)
        inherited = list(forked_snap.task_outputs.keys())
        print(f"  Inherited outputs without re-computation: {inherited}")

        # 6. Resume Forked Run to Completion with Fixed Runner
        def runner_fixed(task: Any) -> Any:
            if task.task_id == "create_invoice":
                raise RuntimeError("Should never be called! Output was inherited.")
            elif task.task_id == "charge_customer":
                return TaskResult(ok=True, output=safe_charge(task.inputs["create_invoice"]))
            elif task.task_id == "send_receipt":
                return TaskResult(ok=True, output=send_receipt(task.inputs["charge_customer"]))
            return TaskResult(ok=True)

        print("\n🏁 4. Resuming forked run with corrected runner...")
        resumed_status = resume_run(conn, forked_run_id, runner_fixed, time.time)
        print(f"  Resumed Run Status: {resumed_status.value}")
        assert resumed_status.value == "succeeded"
        print("  ✓ Forked run completed with 100% success without repeating Step 1!")

        conn.close()


if __name__ == "__main__":
    run_showcase()
