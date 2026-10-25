"""
Example demonstrating lifecycle Hooks for workflow observability.
"""
import time

from orchestration_engine import (
    Hooks,
    RetryPolicy,
    Task,
    TaskState,
    Workflow,
    get_connection,
    run_workflow,
)


def main() -> None:
    task1 = Task(
        task_id="step1",
        workflow_id="hooks-wf",
        name="Step One",
        description="First step",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(max_attempts=2, delay_seconds=0.5),
    )

    task2 = Task(
        task_id="step2",
        workflow_id="hooks-wf",
        name="Step Two",
        description="Second step",
        dependencies=["step1"],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0.5),
    )

    workflow = Workflow(
        workflow_id="hooks-wf",
        name="Hooks Demo Workflow",
        description="Demonstrates lifecycle callbacks",
        tasks=[task1, task2],
    )

    hooks = Hooks(
        on_task_start=lambda t: print(f"[HOOK] Task started: {t.name} (attempt {t.attempt_count})"),
        on_task_succeeded=lambda t: print(f"[HOOK] Task succeeded: {t.name}"),
        on_task_retry=lambda t: print(f"[HOOK] Task scheduled for retry: {t.name}"),
        on_task_failed=lambda t: print(f"[HOOK] Task failed: {t.name} (error: {t.last_error})"),
        on_workflow_done=lambda wf, st: print(
            f"[HOOK] Workflow {wf.workflow_id} finished with status {st.value}"
        ),
    )

    def task_runner(task: Task) -> bool:
        print(f"Executing business logic for: {task.name}")
        return True

    conn = get_connection(":memory:")
    run_id = run_workflow(workflow, {}, time.time, task_runner, conn, hooks=hooks)
    print(f"Run {run_id} complete.")


if __name__ == "__main__":
    main()
