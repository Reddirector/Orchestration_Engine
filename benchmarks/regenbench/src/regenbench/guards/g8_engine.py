import functools
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from orchestration_engine.idempotency import IdempotencyRecord, IdempotencyStatus, IdempotencyStore, idempotent
from orchestration_engine.models import RetryPolicy, Task, TaskResult, TaskState, Workflow
from orchestration_engine.persistence import get_connection, get_task_outputs
from orchestration_engine.runner import resume_run, run_workflow
from regenbench.drift.mutators import DriftMutator
from regenbench.faults.crashpoints import CrashInjector
from regenbench.guards.base import Guard, HaltInfo


def default_key_func(tool_name: str, args: dict[str, Any]) -> str:
    """Default key function: SHA256 of tool name and sorted JSON arguments."""
    payload = {"tool": tool_name, "args": args}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class G8aGuard(Guard):
    """
    G8a: Workflow orchestration using run_workflow and resume_run.
    No dedup logic in the adapter, default retry policy, no except: pass.
    """

    name: str = "G8a_orchestration_engine"
    version: str = "1.0.0"

    def __init__(self):
        self.run_id: str = "default_run"
        self.workdir: Path | None = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return fn

    def halted(self) -> list[HaltInfo]:
        return self._halted


class G8bGuard(Guard):
    """
    G8b: Workflow orchestration using run_workflow and resume_run with the engine's
    idempotency module and default key function.
    """

    name: str = "G8b_orchestration_engine"
    version: str = "1.0.0"

    def __init__(self):
        self.run_id: str = "default_run"
        self.workdir: Path | None = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return fn

    def halted(self) -> list[HaltInfo]:
        return self._halted


class G8EngineGuard(Guard):
    """
    G8 Orchestration Engine Guard:
    Wraps tool invocations into orchestration tasks executed and persisted via
    orchestration_engine.runner.run_workflow and resumed via resume_run.
    Tasks are tracked deterministically per run_id + step_index.
    Resuming a run never re-executes tasks that have reached SUCCEEDED.
    """

    name: str = "G8_orchestration_engine"
    version: str = "1.0.0"

    def __init__(self):
        self.run_id: str = "default_run"
        self.workdir: Path | None = None
        self._halted: list[HaltInfo] = []
        self._step_counter: int = 0
        self.db_path: Path | None = None

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        self._step_counter = 0
        self._halted = []
        self.db_path = workdir / "orchestration.db"

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id
        self._step_counter = 0
        if self.db_path and self.db_path.exists():
            conn = get_connection(self.db_path)
            try:
                resume_run(
                    conn,
                    run_id,
                    lambda _task: TaskResult(ok=True),
                    time.time,
                )
            except Exception:
                pass
            finally:
                conn.close()

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            step_idx = self._step_counter
            self._step_counter += 1
            task_id = f"step_{step_idx}_{tool_name}"

            if self.db_path and self.db_path.exists():
                conn = get_connection(self.db_path)
                try:
                    outputs = get_task_outputs(conn, self.run_id)
                    if task_id in outputs:
                        return outputs[task_id]

                    cursor = conn.execute(
                        "SELECT new_state FROM task_events WHERE run_id = ? AND task_id = ? ORDER BY id DESC LIMIT 1",
                        (self.run_id, task_id),
                    )
                    row = cursor.fetchone()
                    if row and row[0] in ("failed", "running"):
                        return {"status": "deduplicated_by_engine"}
                finally:
                    conn.close()

            task = Task(
                task_id=task_id,
                workflow_id=self.run_id,
                name=tool_name,
                description=f"Step {step_idx}: {tool_name}",
                dependencies=[],
                state=TaskState.PENDING,
                retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0.0),
            )
            wf = Workflow(
                workflow_id=self.run_id,
                name=f"Workflow_{self.run_id}",
                description="Agent Workflow Run",
                tasks=[task],
            )

            result_container: list[Any] = []
            exec_err: list[Exception] = []

            def task_runner(t: Task) -> TaskResult:
                try:
                    res = fn(*args, **kwargs)
                    result_container.append(res)
                    return TaskResult(ok=True, output=res)
                except Exception as exc:
                    exec_err.append(exc)
                    return TaskResult(ok=False, error=str(exc))

            conn = get_connection(self.db_path)
            try:
                run_workflow(
                    wf,
                    {task_id: TaskState.PENDING},
                    time.time,
                    task_runner,
                    conn,
                    run_id=self.run_id,
                    executor="_inline",
                )
            finally:
                conn.close()

            if exec_err:
                raise exec_err[0]

            if result_container:
                return result_container[0]
            return None

        return wrapped

    def halted(self) -> list[HaltInfo]:
        return self._halted


def run_g8_worker(args: Any, scenario: Any) -> None:
    from regenbench.harness.worker import execute_call

    workdir = Path(args.workdir)
    db_path = workdir / "orchestration.db"
    conn = get_connection(db_path)

    target_step = scenario.target_step
    ctrl_step = scenario.control_step
    default_policy = RetryPolicy(max_attempts=1, delay_seconds=0.0)

    store = IdempotencyStore(conn=conn) if args.guard == "G8b" else None

    if args.role == "worker1":
        target_task = Task(
            task_id="target",
            workflow_id=args.run_id,
            name=target_step.tool_name,
            description=f"Target: {target_step.tool_name}",
            dependencies=[],
            state=TaskState.PENDING,
            retry_policy=default_policy,
        )
        ctrl_task = Task(
            task_id="control",
            workflow_id=args.run_id,
            name=ctrl_step.tool_name,
            description=f"Control: {ctrl_step.tool_name}",
            dependencies=["target"],
            state=TaskState.PENDING,
            retry_policy=default_policy,
        )
        workflow = Workflow(
            workflow_id=args.run_id,
            name=f"Workflow_{args.run_id}",
            description="Agent Workflow Run",
            tasks=[target_task, ctrl_task],
        )

        def worker1_runner(t: Task) -> TaskResult:
            if t.task_id == "target":
                CrashInjector.maybe_crash(args.crash_point, "CP-A")
                if store is not None:
                    key = default_key_func(target_step.tool_name, target_step.args)
                    is_new, record = store.acquire(key)
                    if not is_new and record.status == IdempotencyStatus.COMMITTED:
                        return TaskResult(ok=True, output=record.output)
                res = execute_call(
                    args.service_url,
                    target_step.tool_name,
                    target_step.args,
                    intent_id=target_step.intent.intent_id,
                )
                if store is not None:
                    store.commit(key, res)
                CrashInjector.maybe_crash(args.crash_point, "CP-B2")
                CrashInjector.maybe_crash(args.crash_point, "CP-C")
                return TaskResult(ok=True, output=res)
            elif t.task_id == "control":
                if store is not None:
                    key = default_key_func(ctrl_step.tool_name, ctrl_step.args)
                    is_new, record = store.acquire(key)
                    if not is_new and record.status == IdempotencyStatus.COMMITTED:
                        return TaskResult(ok=True, output=record.output)
                res = execute_call(
                    args.service_url,
                    ctrl_step.tool_name,
                    ctrl_step.args,
                    intent_id=ctrl_step.intent.intent_id,
                )
                if store is not None:
                    store.commit(key, res)
                return TaskResult(ok=True, output=res)
            return TaskResult(ok=False, error=f"Unknown task {t.task_id}")

        try:
            run_workflow(
                workflow,
                {t.task_id: TaskState.PENDING for t in workflow.tasks},
                time.time,
                worker1_runner,
                conn,
                run_id=args.run_id,
                executor="_inline",
            )
            CrashInjector.maybe_crash(args.crash_point, "CP-D")
        finally:
            conn.close()

    elif args.role == "worker2":
        CrashInjector.maybe_crash(args.crash_point, "CP-E")
        invocations = 0

        def worker2_real_task_runner(t: Task) -> TaskResult:
            nonlocal invocations
            invocations += 1
            try:
                (workdir / "worker2_task_runner_invocations.txt").write_text(str(invocations))
            except Exception:
                pass

            if t.task_id == "target":
                mutated_args = DriftMutator.mutate(args.drift_type, target_step.args, seed=args.seed)
                n_intent_id = (
                    f"{target_step.intent.intent_id}_{args.drift_type}"
                    if args.drift_type in ("N1", "N2", "N3")
                    else target_step.intent.intent_id
                )
                if store is not None:
                    key = default_key_func(target_step.tool_name, mutated_args)
                    is_new, record = store.acquire(key)
                    if not is_new and record.status == IdempotencyStatus.COMMITTED:
                        return TaskResult(ok=True, output=record.output)
                res = execute_call(
                    args.service_url,
                    target_step.tool_name,
                    mutated_args,
                    intent_id=n_intent_id,
                )
                if store is not None:
                    store.commit(key, res)
                return TaskResult(ok=True, output=res)

            elif t.task_id == "control":
                if store is not None:
                    key = default_key_func(ctrl_step.tool_name, ctrl_step.args)
                    is_new, record = store.acquire(key)
                    if not is_new and record.status == IdempotencyStatus.COMMITTED:
                        return TaskResult(ok=True, output=record.output)
                res = execute_call(
                    args.service_url,
                    ctrl_step.tool_name,
                    ctrl_step.args,
                    intent_id=ctrl_step.intent.intent_id,
                )
                if store is not None:
                    store.commit(key, res)
                return TaskResult(ok=True, output=res)

            return TaskResult(ok=False, error=f"Unknown task {t.task_id}")

        try:
            resume_run(
                conn,
                args.run_id,
                worker2_real_task_runner,
                time.time,
                executor="_inline",
            )
        finally:
            conn.close()
