"""Tests for Distributed Sagas and Compensating Transactions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.persistence import get_connection
from orchestration_engine.sagas import SagaStatus, run_saga


def test_saga_successful_flow(tmp_path: Any) -> None:
    db = str(tmp_path / "saga.db")
    wf = (
        WorkflowBuilder("saga-ok")
        .task("charge")
        .task("provision", dependencies=["charge"])
        .build()
    )

    runners: dict[str, Callable[..., Any]] = {
        "charge": lambda: {"charged": 100},
        "provision": lambda charge: {"instance": "i-123", "paid": charge["charged"]},
    }
    compensators = {
        "charge": lambda **kw: None,
        "provision": lambda **kw: None,
    }

    result = run_saga(wf, runners, compensators, db_path=db)
    assert result.status == SagaStatus.COMPLETED
    assert result.compensated_tasks == []
    assert result.compensation_errors == {}


def test_saga_failure_and_reverse_compensation(tmp_path: Any) -> None:
    db = str(tmp_path / "saga_fail.db")
    wf = (
        WorkflowBuilder("saga-fail")
        .task("reserve_stock")
        .task("charge_card", dependencies=["reserve_stock"])
        .task("ship_item", dependencies=["charge_card"])
        .build()
    )

    compensated_order: list[str] = []

    def compensate_stock(**kw: Any) -> None:
        compensated_order.append("reserve_stock")

    def compensate_card(**kw: Any) -> None:
        compensated_order.append("charge_card")

    def fail_shipping(charge_card: Any) -> Any:
        raise RuntimeError("Shipping carrier offline")

    runners: dict[str, Callable[..., Any]] = {
        "reserve_stock": lambda: {"reserved": True},
        "charge_card": lambda reserve_stock: {"charged": 50},
        "ship_item": fail_shipping,
    }
    compensators = {
        "reserve_stock": compensate_stock,
        "charge_card": compensate_card,
    }

    result = run_saga(wf, runners, compensators, db_path=db)
    assert result.status == SagaStatus.COMPENSATED
    # Compensations must be in reverse order of completion: charge_card before reserve_stock
    assert compensated_order == ["charge_card", "reserve_stock"]
    assert result.compensated_tasks == ["charge_card", "reserve_stock"]
    assert result.compensation_errors == {}

    # Verify audit entries in SQLite
    conn = get_connection(db)
    with conn:
        cursor = conn.execute(
            "SELECT task_id, status FROM saga_compensations WHERE run_id = ? ORDER BY id ASC",
            (result.workflow_run_id,),
        )
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert rows[0] == ("charge_card", "succeeded")
        assert rows[1] == ("reserve_stock", "succeeded")


def test_saga_compensation_failure(tmp_path: Any) -> None:
    db = str(tmp_path / "saga_comp_err.db")
    wf = (
        WorkflowBuilder("saga-comp-err")
        .task("step1")
        .task("step2", dependencies=["step1"])
        .build()
    )

    def comp_fail(**kw: Any) -> None:
        raise ValueError("Bank refund endpoint error")

    runners: dict[str, Callable[..., Any]] = {
        "step1": lambda: "ok",
        "step2": lambda step1: (_ for _ in ()).throw(RuntimeError("step2 crash")),
    }
    compensators = {
        "step1": comp_fail,
    }

    result = run_saga(wf, runners, compensators, db_path=db)
    assert result.status == SagaStatus.COMPENSATION_FAILED
    assert "step1" in result.compensation_errors
    assert "Bank refund endpoint error" in result.compensation_errors["step1"]


def test_saga_callable_runner_and_missing_compensator(tmp_path: Any) -> None:
    db = str(tmp_path / "saga_callable.db")
    wf = (
        WorkflowBuilder("saga-call")
        .task("t1")
        .task("t2", dependencies=["t1"])
        .build()
    )

    def single_runner(task: Any) -> Any:
        if task.task_id == "t2":
            raise RuntimeError("t2 fail")
        return {"t1": "done"}

    compensated: list[str] = []

    def zero_arg_compensator() -> None:
        compensated.append("t1")

    # Only t1 has a compensator, t2 does not
    compensators = {"t1": zero_arg_compensator}

    result = run_saga(wf, single_runner, compensators, db_path=db)
    assert result.status == SagaStatus.COMPENSATED
    assert compensated == ["t1"]
    assert result.compensated_tasks == ["t1"]

