from orchestration_engine.models import Task


def test_task_creation() -> None:
    task = Task(task_id="task-1", name="Example Task")

    assert task.task_id == "task-1"
    assert task.name == "Example Task"