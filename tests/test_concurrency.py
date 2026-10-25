import multiprocessing
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from orchestration_engine.errors import WorkflowValidationError
from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.runner import run_workflow


def test_invalid_concurrency_parameters(conn: sqlite3.Connection) -> None:
    wf = Workflow(
        "wf", "wf", "desc",
        [Task("t1", "wf", "t1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))]
    )
    with pytest.raises(WorkflowValidationError, match="max_concurrency"):
        run_workflow(wf, {}, time.time, lambda _t: True, conn, max_concurrency=0)

    with pytest.raises(WorkflowValidationError, match="max_concurrency"):
        run_workflow(wf, {}, time.time, lambda _t: True, conn, max_concurrency=-2)

    with pytest.raises(WorkflowValidationError, match="max_concurrency"):
        run_workflow(wf, {}, time.time, lambda _t: True, conn, max_concurrency=True)

    with pytest.raises(WorkflowValidationError, match="executor"):
        run_workflow(wf, {}, time.time, lambda _t: True, conn, executor="invalid_backend")  # type: ignore[arg-type]


def test_concurrency_two_speedup_and_peak(conn: sqlite3.Connection) -> None:
    # 2 independent tasks taking 0.3s each
    t1 = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    t2 = Task("t2", "wf", "T2", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [t1, t2])

    active = 0
    peak = 0
    lock = threading.Lock()

    def runner(_task: Task) -> bool:
        nonlocal active, peak
        with lock:
            active += 1
            if active > peak:
                peak = active
        time.sleep(0.3)
        with lock:
            active -= 1
        return True

    start = time.perf_counter()
    status_run_id = run_workflow(
        wf, {}, time.time, runner, conn, max_concurrency=2, executor="thread"
    )
    elapsed = time.perf_counter() - start

    assert isinstance(status_run_id, str)
    assert t1.state == TaskState.SUCCEEDED
    assert t2.state == TaskState.SUCCEEDED
    assert peak == 2
    # Two 0.3s tasks in parallel should finish in well under 0.6s
    assert elapsed < 0.55


def test_dependent_task_never_starts_early(conn: sqlite3.Connection) -> None:
    tA = Task("tA", "wf", "A", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    tB = Task("tB", "wf", "B", "d", ["tA"], TaskState.PENDING, RetryPolicy(1, 1.0))
    tC = Task("tC", "wf", "C", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [tA, tB, tC])

    a_finished = False
    b_started_after_a = False
    lock = threading.Lock()

    def runner(task: Task) -> bool:
        nonlocal a_finished, b_started_after_a
        if task.task_id == "tA":
            time.sleep(0.2)
            with lock:
                a_finished = True
            return True
        elif task.task_id == "tB":
            with lock:
                b_started_after_a = a_finished
            return True
        elif task.task_id == "tC":
            time.sleep(0.1)
            return True
        return True

    run_workflow(wf, {}, time.time, runner, conn, max_concurrency=2)
    assert tA.state == TaskState.SUCCEEDED
    assert tB.state == TaskState.SUCCEEDED
    assert tC.state == TaskState.SUCCEEDED
    assert b_started_after_a is True


def _top_level_hung_runner(_task: Task) -> bool:
    time.sleep(30.0)
    return True


def test_process_backend_kills_timed_out_task(tmp_path: Path) -> None:
    from orchestration_engine.persistence import get_connection

    db_path = tmp_path / "proc_timeout.db"
    conn = get_connection(db_path)
    try:
        task = Task(
            "t1", "wf", "Hung", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0), timeout_seconds=0.2
        )
        wf = Workflow("wf", "wf", "desc", [task])

        start = time.perf_counter()
        run_workflow(
            wf, {}, time.time, _top_level_hung_runner, conn, max_concurrency=1, executor="process"
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0
        assert task.state == TaskState.FAILED
        assert task.last_error is not None
        assert "timeout" in task.last_error
    finally:
        conn.close()


def test_process_backend_rejects_unpicklable_runner(conn: sqlite3.Connection) -> None:
    # A lambda or local closure inside a function cannot be pickled by default
    def make_unpicklable() -> Any:
        local_var = 123
        def inner(_task: Task) -> bool:
            return local_var == 123
        return inner

    unpicklable_runner = make_unpicklable()
    wf = Workflow(
        "wf", "wf", "desc",
        [Task("t1", "wf", "t1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))]
    )
    with pytest.raises(WorkflowValidationError, match="picklable"):
        run_workflow(wf, {}, time.time, unpicklable_runner, conn, executor="process")


def test_inline_executor_deterministic(conn: sqlite3.Connection) -> None:
    current_time = 100.0

    def adv_time() -> float:
        return current_time

    def fake_sleep(s: float) -> None:
        nonlocal current_time
        current_time += s

    t1 = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(2, 5.0))
    wf = Workflow("wf", "wf", "desc", [t1])

    attempts = 0

    def flaky_runner(_task: Task) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts >= 2

    run_workflow(
        wf,
        {},
        time_source=adv_time,
        task_runner=flaky_runner,
        conn=conn,
        sleep=fake_sleep,
        executor="_inline",
    )

    assert t1.state == TaskState.SUCCEEDED
    assert t1.attempt_count == 2
    assert current_time == 105.0  # 100 + 5s backoff


def _top_level_fast_runner(_task: Task) -> bool:
    return True


def test_process_executor_concurrent_success(tmp_path: Path) -> None:
    from orchestration_engine.persistence import get_connection

    db_path = tmp_path / "proc_concurrent.db"
    conn = get_connection(db_path)
    try:
        tasks = [
            Task(f"t{i}", "wf", f"T{i}", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
            for i in range(4)
        ]
        wf = Workflow("wf", "wf", "desc", tasks)

        run_id = run_workflow(
            wf,
            {},
            time.time,
            _top_level_fast_runner,
            conn,
            max_concurrency=2,
            executor="process",
        )
        assert isinstance(run_id, str)
        for t in tasks:
            assert t.state == TaskState.SUCCEEDED
    finally:
        conn.close()


def test_no_sqlite3_programming_error_under_concurrency(conn: sqlite3.Connection) -> None:
    tasks = [
        Task(f"task_{i}", "wf", f"Task {i}", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
        for i in range(10)
    ]
    wf = Workflow("wf", "wf", "desc", tasks)

    def fast_runner(_task: Task) -> bool:
        time.sleep(0.01)
        return True

    run_id = run_workflow(
        wf,
        {},
        time.time,
        fast_runner,
        conn,
        max_concurrency=4,
        executor="thread",
    )
    assert isinstance(run_id, str)
    for t in tasks:
        assert t.state == TaskState.SUCCEEDED


def test_task_event_order_valid_under_concurrency(conn: sqlite3.Connection) -> None:
    tA = Task("tA", "wf", "A", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    tB = Task("tB", "wf", "B", "d", ["tA"], TaskState.PENDING, RetryPolicy(1, 1.0))
    tC = Task("tC", "wf", "C", "d", ["tB"], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [tA, tB, tC])

    run_id = run_workflow(
        wf,
        {},
        time.time,
        lambda _t: True,
        conn,
        max_concurrency=3,
        executor="thread",
    )

    rows = conn.execute(
        "SELECT task_id, old_state, new_state FROM task_events WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()

    events_by_task: dict[str, list[tuple[str, str]]] = {"tA": [], "tB": [], "tC": []}
    for tid, old_st, new_st in rows:
        events_by_task[tid].append((old_st, new_st))

    for tid in ("tA", "tB", "tC"):
        seq = events_by_task[tid]
        assert len(seq) == 3
        assert seq[0] == ("pending", "ready")
        assert seq[1] == ("ready", "running")
        assert seq[2] == ("running", "succeeded")


def test_process_task_target_success_and_error() -> None:
    from orchestration_engine.runner import _process_task_target

    ctx = multiprocessing.get_context("spawn")
    task = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))

    p1, c1 = ctx.Pipe()
    _process_task_target(task, lambda _t: True, c1)
    ok, err = p1.recv()
    assert ok is True
    assert err is None
    p1.close()

    p2, c2 = ctx.Pipe()

    def crasher(_t: Task) -> bool:
        raise ValueError("boom")

    _process_task_target(task, crasher, c2)
    ok, err = p2.recv()
    assert ok is False
    assert "ValueError: boom" in (err or "")
    p2.close()


def test_resume_run_already_terminal(conn: sqlite3.Connection) -> None:
    from orchestration_engine.models import WorkflowStatus
    from orchestration_engine.runner import resume_run

    task = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [task])
    run_id = run_workflow(wf, {}, time.time, lambda _t: True, conn)
    st = resume_run(conn, run_id, lambda _t: True, time.time)
    assert st == WorkflowStatus.SUCCEEDED


def test_inline_executor_runner_exception(conn: sqlite3.Connection) -> None:
    task = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [task])

    def crasher(_t: Task) -> bool:
        raise RuntimeError("inline crash")

    run_workflow(wf, {}, time.time, crasher, conn, executor="_inline")
    assert task.state == TaskState.FAILED
    assert "RuntimeError: inline crash" in (task.last_error or "")


def _top_level_failing_runner(_task: Task) -> bool:
    return False


def test_process_executor_failure(tmp_path: Path) -> None:
    from orchestration_engine.persistence import get_connection

    db_path = tmp_path / "proc_fail.db"
    conn = get_connection(db_path)
    try:
        task = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
        wf = Workflow("wf", "wf", "desc", [task])
        run_workflow(
            wf, {}, time.time, _top_level_failing_runner, conn, executor="process"
        )
        assert task.state == TaskState.FAILED
    finally:
        conn.close()


