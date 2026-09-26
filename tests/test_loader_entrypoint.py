import json

from orchestration_engine.loader import run_workflow_from_file
from orchestration_engine.models import WorkflowStatus


def test_run_workflow_from_file_succeeds(tmp_path, conn) -> None:
    workflow_data = {
        "workflow_id": "wf-file-1",
        "name": "File Test",
        "description": "test",
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

    file_path = tmp_path / "workflow.json"
    file_path.write_text(json.dumps(workflow_data))

    status = run_workflow_from_file(
        path=str(file_path),
        task_runner=lambda task: True,
        time_source=lambda: 0.0,
        conn=conn,
    )

    assert status == WorkflowStatus.SUCCEEDED
