from orchestration_engine.loader import load_workflow_from_json
from orchestration_engine.models import TaskState


def test_load_workflow_from_json() -> None:
    json_data = {
        "workflow_id": "wf-1",
        "name": "Demo",
        "description": "test run",
        "tasks": [
            {
                "task_id": "t1",
                "name": "First",
                "description": "step one",
                "dependencies": [],
                "retry_policy": {"max_attempts": 3, "delay_seconds": 5},
            }
        ],
    }

    workflow = load_workflow_from_json(json_data)

    assert workflow.workflow_id == "wf-1"
    assert len(workflow.tasks) == 1
    assert workflow.tasks[0].task_id == "t1"
    assert workflow.tasks[0].workflow_id == "wf-1"
    assert workflow.tasks[0].state == TaskState.PENDING
