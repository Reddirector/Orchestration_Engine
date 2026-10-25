"""
Example demonstrating data flow between tasks using TaskResult and task.inputs.
"""
import time

from orchestration_engine import (
    RetryPolicy,
    Task,
    TaskResult,
    TaskState,
    Workflow,
    get_connection,
    run_workflow,
)


def main() -> None:
    # Build pipeline: Task A and Task B feed Task C
    task_a = Task(
        task_id="fetch_user",
        workflow_id="data-flow-wf",
        name="Fetch User",
        description="Retrieves user profile data",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(max_attempts=2, delay_seconds=1.0),
    )

    task_b = Task(
        task_id="fetch_orders",
        workflow_id="data-flow-wf",
        name="Fetch Orders",
        description="Retrieves customer orders",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(max_attempts=2, delay_seconds=1.0),
    )

    task_c = Task(
        task_id="summarize",
        workflow_id="data-flow-wf",
        name="Summarize Account",
        description="Merges user profile with order total",
        dependencies=["fetch_user", "fetch_orders"],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(max_attempts=1, delay_seconds=1.0),
    )

    workflow = Workflow(
        workflow_id="data-flow-wf",
        name="Customer Summary Workflow",
        description="Demonstrates passing data between upstream and downstream tasks",
        tasks=[task_a, task_b, task_c],
    )

    def task_runner(task: Task) -> TaskResult:
        if task.task_id == "fetch_user":
            print("Fetching user data...")
            return TaskResult(ok=True, output={"user_id": 42, "name": "Alice"})
        elif task.task_id == "fetch_orders":
            print("Fetching order history...")
            orders = [
                {"item": "Widget", "amount": 25.50},
                {"item": "Book", "amount": 14.50},
            ]
            return TaskResult(ok=True, output=orders)
        elif task.task_id == "summarize":
            user = task.inputs["fetch_user"]
            orders = task.inputs["fetch_orders"]
            total_spent = sum(order["amount"] for order in orders)
            summary = {
                "customer": user["name"],
                "order_count": len(orders),
                "total_spent": total_spent,
            }
            print(f"Summary computed: {summary}")
            return TaskResult(ok=True, output=summary)
        return TaskResult(ok=True)

    conn = get_connection(":memory:")
    run_id = run_workflow(workflow, {}, time.time, task_runner, conn)
    print(f"Workflow completed successfully! run_id: {run_id}")


if __name__ == "__main__":
    main()
