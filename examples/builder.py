"""
Example demonstrating WorkflowBuilder and workflow_to_dict serialization.
"""
import json
import time

from orchestration_engine import (
    WorkflowBuilder,
    get_connection,
    run_workflow,
    workflow_to_dict,
)


def main() -> None:
    # Build workflow fluently
    workflow = (
        WorkflowBuilder("builder-wf", "ETL Workflow")
        .description("Fluent definition of an extract-transform-load pipeline")
        .default_timeout(30.0)
        .task("extract", name="Extract Records", timeout_seconds=10.0)
        .task(
            "transform",
            name="Transform Records",
            dependencies=["extract"],
            max_attempts=3,
            delay_seconds=1.0,
        )
        .task("load", name="Load to Destination", dependencies=["transform"])
        .build()
    )

    # Serialize workflow to JSON dictionary
    wf_dict = workflow_to_dict(workflow)
    print("Serialized Workflow Definition:")
    print(json.dumps(wf_dict, indent=2))

    # Execute workflow
    conn = get_connection(":memory:")
    run_id = run_workflow(
        workflow,
        {},
        time.time,
        lambda t: True,
        conn,
    )
    print(f"Executed workflow successfully with run_id: {run_id}")


if __name__ == "__main__":
    main()
