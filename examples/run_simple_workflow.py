"""
Minimal runnable example for orchestration_engine.

Run from the repo root with:
    uv run python examples/run_simple_workflow.py
"""
import time

from orchestration_engine import get_connection, run_workflow_from_file


def task_runner(task) -> bool:
    print(f"Running task: {task.name} ({task.task_id})")
    # Replace this with real logic — an LLM call, an API request, a tool invocation.
    return True


def main() -> None:
    conn = get_connection(":memory:")
    status = run_workflow_from_file(
        "examples/simple_workflow.json",
        task_runner,
        time.time,
        conn,
    )
    print(f"Workflow finished with status: {status}")


if __name__ == "__main__":
    main()
