import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from orchestration_engine.cli import main
from orchestration_engine.persistence import get_connection


@pytest.fixture
def sample_workflow_json(tmp_path: Path) -> Path:
    wf_path = tmp_path / "workflow.json"
    wf_path.write_text(
        json.dumps(
            {
                "workflow_id": "test-wf-cli",
                "name": "CLI Test Workflow",
                "description": "A workflow for CLI unit tests",
                "tasks": [
                    {
                        "task_id": "t1",
                        "name": "Task 1",
                        "description": "First test task",
                        "dependencies": [],
                        "retry_policy": {"max_attempts": 1, "delay_seconds": 0.0},
                    },
                    {
                        "task_id": "t2",
                        "name": "Task 2",
                        "description": "Second test task",
                        "dependencies": ["t1"],
                        "retry_policy": {"max_attempts": 1, "delay_seconds": 0.0},
                    },
                ],
            }
        )
    )
    return wf_path


@pytest.fixture
def sample_workflow_yaml(tmp_path: Path) -> Path:
    wf_path = tmp_path / "workflow.yaml"
    wf_path.write_text(
        """
workflow_id: test-yaml-cli
name: YAML CLI Test
description: YAML workflow for CLI unit tests
tasks:
  - task_id: y1
    name: Yaml Task 1
    description: YAML test task
    dependencies: []
    retry_policy:
      max_attempts: 1
      delay_seconds: 0.0
"""
    )
    return wf_path


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--help"])
    assert code == 0
    captured = capsys.readouterr()
    assert "orchestration-engine" in captured.out
    assert "Available subcommands" in captured.out


def test_cli_no_args_shows_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    assert code == 2
    captured = capsys.readouterr()
    assert "Available subcommands" in captured.err


def test_cli_validate_success(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["validate", str(sample_workflow_json)])
    assert code == 0
    captured = capsys.readouterr()
    assert "Workflow 'test-wf-cli' is valid (2 tasks)." in captured.out


def test_cli_validate_json_output(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["validate", str(sample_workflow_json), "--json"])
    assert code == 0
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]
    data = json.loads(lines[-1])
    assert data == {"workflow_id": "test-wf-cli", "tasks_count": 2, "valid": True}


def test_cli_validate_yaml_success(
    sample_workflow_yaml: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["validate", str(sample_workflow_yaml)])
    assert code == 0
    captured = capsys.readouterr()
    assert "Workflow 'test-yaml-cli' is valid" in captured.out


def test_cli_validate_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["validate", "nonexistent.json"])
    assert code == 2
    captured = capsys.readouterr()
    assert "Workflow file not found" in captured.err


def test_cli_validate_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{invalid-json")
    code = main(["validate", str(bad_file)])
    assert code == 2
    captured = capsys.readouterr()
    assert "Validation error" in captured.err


def test_cli_validate_invalid_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_file = tmp_path / "bad_schema.json"
    bad_file.write_text(json.dumps({"tasks": []}))
    code = main(["validate", str(bad_file)])
    assert code == 2
    captured = capsys.readouterr()
    assert "Validation error" in captured.err


def test_cli_run_success_in_memory(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:run",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "completed with status: succeeded" in captured.out


def test_cli_run_success_with_db_and_json(
    sample_workflow_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "cli_test.db")
    code = main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:run",
            "--db",
            db_path,
            "--run-id",
            "run-cli-001",
            "--max-concurrency",
            "2",
            "--executor",
            "thread",
            "--json",
        ]
    )
    assert code == 0
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]
    data = json.loads(lines[-1])
    assert data["run_id"] == "run-cli-001"
    assert data["workflow_id"] == "test-wf-cli"
    assert data["status"] == "succeeded"


def test_cli_run_failure(
    sample_workflow_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "failing.db")
    code = main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:failing_runner",
            "--db",
            db_path,
            "--json",
        ]
    )
    assert code == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "failed"


def test_cli_run_invalid_runner_syntax(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", str(sample_workflow_json), "--runner", "no_colon_here"])
    assert code == 2
    assert "Invalid runner specification" in capsys.readouterr().err


def test_cli_run_invalid_runner_module(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["run", str(sample_workflow_json), "--runner", "nonexistent_module:fn"]
    )
    assert code == 2
    assert "Could not import module" in capsys.readouterr().err


def test_cli_run_invalid_runner_attribute(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["run", str(sample_workflow_json), "--runner", "examples.runners:nonexistent_fn"]
    )
    assert code == 2
    assert "has no attribute" in capsys.readouterr().err


def test_cli_run_invalid_concurrency(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:run",
            "--max-concurrency",
            "0",
        ]
    )
    assert code == 2
    assert "max_concurrency must be >= 1" in capsys.readouterr().err


def test_cli_status_and_history_and_runs(
    sample_workflow_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "lifecycle.db")
    # Run
    main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:run",
            "--db",
            db_path,
            "--run-id",
            "run-lifecycle-1",
        ]
    )
    capsys.readouterr()

    # Status text
    code = main(["status", "run-lifecycle-1", "--db", db_path])
    assert code == 0
    assert "Run run-lifecycle-1: succeeded" in capsys.readouterr().out

    # Status json
    code = main(["status", "run-lifecycle-1", "--db", db_path, "--json"])
    assert code == 0
    st_data = json.loads(capsys.readouterr().out)
    assert st_data == {"run_id": "run-lifecycle-1", "status": "succeeded"}

    # History text
    code = main(["history", "run-lifecycle-1", "--db", db_path])
    assert code == 0
    hist_out = capsys.readouterr().out
    assert "Task 't1':" in hist_out
    assert "Task 't2':" in hist_out

    # History json
    code = main(["history", "run-lifecycle-1", "--db", db_path, "--json"])
    assert code == 0
    hist_data = json.loads(capsys.readouterr().out)
    assert isinstance(hist_data, list)
    assert len(hist_data) >= 4
    assert hist_data[0]["workflow_id"] == "test-wf-cli"

    # Runs list text
    code = main(["runs", "--db", db_path])
    assert code == 0
    assert "run-lifecycle-1" in capsys.readouterr().out

    # Runs list json
    code = main(["runs", "--db", db_path, "--json"])
    assert code == 0
    runs_data = json.loads(capsys.readouterr().out)
    assert len(runs_data) == 1
    assert runs_data[0]["run_id"] == "run-lifecycle-1"

    # Filter runs by workflow
    code = main(["runs", "--db", db_path, "--workflow", "test-wf-cli", "--json"])
    assert code == 0
    assert len(json.loads(capsys.readouterr().out)) == 1

    code = main(["runs", "--db", db_path, "--workflow", "other-wf", "--json"])
    assert code == 0
    assert len(json.loads(capsys.readouterr().out)) == 0


def test_cli_status_nonexistent_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "empty.db")
    # Initialize DB
    get_connection(db_path)
    code = main(["status", "no-such-run", "--db", db_path])
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_cli_history_nonexistent_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "empty.db")
    get_connection(db_path)
    code = main(["history", "no-such-run", "--db", db_path])
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_cli_resume(
    sample_workflow_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "resume.db")
    main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:run",
            "--db",
            db_path,
            "--run-id",
            "run-to-resume",
        ]
    )
    capsys.readouterr()

    # Resume succeeded run returns 0 and reports status
    code = main(
        [
            "resume",
            "run-to-resume",
            "--runner",
            "examples.runners:run",
            "--db",
            db_path,
            "--json",
        ]
    )
    assert code == 0
    res = json.loads(capsys.readouterr().out)
    assert res == {"run_id": "run-to-resume", "status": "succeeded"}


def test_cli_persistence_error_returns_exit_code_3(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A path to a file that cannot be opened as a SQLite database directory
    invalid_db = "/proc/invalid/path/db.sqlite"
    code = main(["status", "any-id", "--db", invalid_db])
    assert code == 3
    assert "Database error" in capsys.readouterr().err


def test_structured_logging_records_extra_fields(
    sample_workflow_json: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="orchestration_engine")
    code = main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:run",
            "--log-level",
            "INFO",
        ]
    )
    assert code == 0
    records = [
        r for r in caplog.records if r.name == "orchestration_engine" and hasattr(r, "old_state")
    ]
    assert len(records) > 0
    first = records[0]
    assert hasattr(first, "workflow_id")
    assert hasattr(first, "run_id")
    assert hasattr(first, "task_id")
    assert hasattr(first, "old_state")
    assert hasattr(first, "new_state")
    assert hasattr(first, "attempt")


def test_subprocess_smoke_test(sample_workflow_json: Path, tmp_path: Path) -> None:
    db_path = str(tmp_path / "subprocess.db")
    cmd = [
        sys.executable,
        "-m",
        "orchestration_engine",
        "run",
        str(sample_workflow_json),
        "--runner",
        "examples.runners:run",
        "--db",
        db_path,
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    data = json.loads(lines[-1])
    assert data["status"] == "succeeded"


def test_cli_runner_empty_parts(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", str(sample_workflow_json), "--runner", ":run"])
    assert code == 2
    assert "Invalid runner specification" in capsys.readouterr().err


def test_cli_runner_not_callable(
    sample_workflow_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["run", str(sample_workflow_json), "--runner", "examples.runners:NOT_A_CALLABLE"]
    )
    assert code == 2
    assert "is not callable" in capsys.readouterr().err


def test_cli_validate_array_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    array_file = tmp_path / "array.json"
    array_file.write_text("[1, 2, 3]")
    code = main(["validate", str(array_file)])
    assert code == 2
    assert "must be an object" in capsys.readouterr().err


def test_cli_resume_text_output(
    sample_workflow_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "resume_text.db")
    main(
        [
            "run",
            str(sample_workflow_json),
            "--runner",
            "examples.runners:run",
            "--db",
            db_path,
            "--run-id",
            "run-resume-text",
        ]
    )
    capsys.readouterr()

    code = main(
        [
            "resume",
            "run-resume-text",
            "--runner",
            "examples.runners:run",
            "--db",
            db_path,
        ]
    )
    assert code == 0
    assert (
        "Resumed run 'run-resume-text' completed with status: succeeded"
        in capsys.readouterr().out
    )


def test_cli_resume_invalid_concurrency(
    sample_workflow_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = str(tmp_path / "resume_bad_conc.db")
    code = main(
        [
            "resume",
            "any-run",
            "--runner",
            "examples.runners:run",
            "--db",
            db_path,
            "--max-concurrency",
            "0",
        ]
    )
    assert code == 2
    assert "max_concurrency must be >= 1" in capsys.readouterr().err


def test_cli_resume_persistence_error(capsys: pytest.CaptureFixture[str]) -> None:
    invalid_db = "/proc/invalid/path/db.sqlite"
    code = main(
        [
            "resume",
            "any-run",
            "--runner",
            "examples.runners:run",
            "--db",
            invalid_db,
        ]
    )
    assert code == 3
    assert "Database error" in capsys.readouterr().err


def test_cli_empty_runs_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = str(tmp_path / "empty_runs.db")
    get_connection(db_path)
    code = main(["runs", "--db", db_path])
    assert code == 0
    assert "No runs found." in capsys.readouterr().out


def test_cli_history_empty_events(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = str(tmp_path / "empty_history.db")
    conn = get_connection(db_path)
    # Insert a run directly without task events
    conn.execute(
        "INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json) "
        "VALUES ('direct-run', 'wf', 100.0, 101.0, 'succeeded', '{}')"
    )
    conn.commit()

    code = main(["history", "direct-run", "--db", db_path])
    assert code == 0
    assert "No history events recorded for run 'direct-run'." in capsys.readouterr().out


def test_cli_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    sample_workflow_json: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = str(tmp_path / "internal.db")
    conn = get_connection(db_path)

    def raise_boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("boom")

    # Validate unexpected error
    with monkeypatch.context() as m:
        m.setattr("orchestration_engine.cli._load_workflow_file", raise_boom)
        assert main(["validate", str(sample_workflow_json)]) == 3
        assert "Internal error: boom" in capsys.readouterr().err

    # Run unexpected error
    with monkeypatch.context() as m:
        m.setattr("orchestration_engine.cli.run_workflow", raise_boom)
        assert (
            main(
                [
                    "run",
                    str(sample_workflow_json),
                    "--runner",
                    "examples.runners:run",
                    "--db",
                    db_path,
                ]
            )
            == 3
        )
        assert "Internal error during run: boom" in capsys.readouterr().err

    # Resume unexpected error
    with monkeypatch.context() as m:
        m.setattr("orchestration_engine.cli.resume_run", raise_boom)
        assert (
            main(["resume", "any-id", "--runner", "examples.runners:run", "--db", db_path])
            == 3
        )
        assert "Internal error during resume: boom" in capsys.readouterr().err

    # Status unexpected error
    with monkeypatch.context() as m:
        m.setattr("orchestration_engine.cli.get_run_status", raise_boom)
        assert main(["status", "any-id", "--db", db_path]) == 3
        assert "Internal error: boom" in capsys.readouterr().err

    # History unexpected error
    conn.execute(
        "INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json) "
        "VALUES ('internal-run', 'wf', 100.0, 101.0, 'succeeded', '{}')"
    )
    conn.commit()
    with monkeypatch.context() as m:
        m.setattr("orchestration_engine.cli.get_run_history", raise_boom)
        assert main(["history", "internal-run", "--db", db_path]) == 3
        assert "Internal error: boom" in capsys.readouterr().err

    # Runs unexpected error
    with monkeypatch.context() as m:
        m.setattr("orchestration_engine.cli.list_runs", raise_boom)
        assert main(["runs", "--db", db_path]) == 3
        assert "Internal error: boom" in capsys.readouterr().err


def test_main_module_execution() -> None:
    import runpy

    # Running python -m orchestration_engine with --help raises SystemExit(0)
    with pytest.raises(SystemExit) as exc:
        sys.argv = ["orchestration-engine", "--help"]
        runpy.run_module("orchestration_engine", run_name="__main__")
    assert exc.value.code == 0


def test_cli_trace_and_signal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = str(tmp_path / "cli_extra.db")
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json) "
        "VALUES ('run-trace-1', 'wf-trace', 100.0, 102.0, 'succeeded', '{}')"
    )
    conn.commit()

    # trace stdout
    exit_code = main(["trace", "run-trace-1", "--db", db_path])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "traceEvents" in out

    # trace file output
    out_file = str(tmp_path / "trace.json")
    exit_code = main(["trace", "run-trace-1", "--db", db_path, "-o", out_file])
    assert exit_code == 0
    assert Path(out_file).exists()

    # signal command
    exit_code = main(
        ["signal", "run-trace-1", "approve", "--payload", '{"ok": true}', "--db", db_path]
    )
    assert exit_code == 0
    assert "delivered" in capsys.readouterr().out

    # signal with invalid JSON
    exit_code = main(
        ["signal", "run-trace-1", "approve", "--payload", "bad-json", "--db", db_path]
    )
    assert exit_code == 2


def test_cli_plan_and_dlq(
    sample_workflow_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1. Plan command (human readable)
    code = main(["plan", str(sample_workflow_json)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Workflow:" in out
    assert "Critical Path:" in out
    assert "Execution Stages:" in out

    # 2. Plan command (--json)
    code = main(["plan", str(sample_workflow_json), "--json"])
    assert code == 0
    plan_data = json.loads(capsys.readouterr().out)
    assert "workflow_id" in plan_data
    assert "stages" in plan_data

    # 3. Plan invalid file
    code = main(["plan", "nonexistent-file.json"])
    assert code == 1
    assert "Error loading workflow" in capsys.readouterr().err

    # 4. DLQ command: list empty
    db_path = str(tmp_path / "dlq_cli.db")
    code = main(["dlq", "list", "--db", db_path])
    assert code == 0
    assert "Dead Letter Queue is empty" in capsys.readouterr().out

    # 5. DLQ enqueue & list
    from orchestration_engine.dead_letter import DeadLetterQueue
    dlq = DeadLetterQueue(db_path)
    dlq.enqueue(workflow_id="wf-test", run_id="r1", task_id="t1", error="boom")

    code = main(["dlq", "list", "--db", db_path, "--json"])
    assert code == 0
    dlq_data = json.loads(capsys.readouterr().out)
    assert len(dlq_data) == 1
    assert dlq_data[0]["task_id"] == "t1"

    # Human readable list
    code = main(["dlq", "list", "--db", db_path])
    assert code == 0
    assert "task=t1" in capsys.readouterr().out

    # 6. DLQ purge
    code = main(["dlq", "purge", "--db", db_path])
    assert code == 0
    assert "Purged 1 message(s)" in capsys.readouterr().out


def test_cli_coordinator_and_worker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1. Coordinator help
    code = main(["coordinator", "--help"])
    assert code == 0
    assert "--host HOST" in capsys.readouterr().out

    # 2. Worker help
    code = main(["worker", "--help"])
    assert code == 0
    assert "--coordinator" in capsys.readouterr().out

    # 3. Worker with unreachable coordinator should exit with code 1
    code = main(["worker", "--coordinator", "http://127.0.0.1:59999"])
    assert code == 1
    assert "Could not connect to coordinator" in capsys.readouterr().err




