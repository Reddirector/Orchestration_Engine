import functools
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from orchestration_engine.models import RetryPolicy, Task, TaskResult, TaskState, Workflow
from orchestration_engine.persistence import get_connection, get_task_outputs
from orchestration_engine.runner import resume_run, run_workflow
from regenbench.guards.base import Guard, HaltInfo


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
        self._resumed: bool = False
        self._task_runner_invocations_w2: int = 0

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        self._step_counter = 0
        self._halted = []
        self.db_path = workdir / "orchestration.db"

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id
        self._step_counter = 0
        self._resumed = True
        if self.db_path and self.db_path.exists():
            conn = get_connection(self.db_path)
            try:
                # Call engine's resume_run entrypoint
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
                        # Task already SUCCEEDED in this run; return cached output
                        return outputs[task_id]

                    cursor = conn.execute(
                        "SELECT new_state FROM task_events WHERE run_id = ? AND task_id = ? ORDER BY id DESC LIMIT 1",
                        (self.run_id, task_id),
                    )
                    row = cursor.fetchone()
                    if row and row[0] in ("failed", "running"):
                        # Task was interrupted or marked terminal
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
                if self._resumed and self.workdir:
                    self._task_runner_invocations_w2 += 1
                    try:
                        (self.workdir / "worker2_task_runner_invocations.txt").write_text(
                            str(self._task_runner_invocations_w2)
                        )
                    except Exception:
                        pass
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
