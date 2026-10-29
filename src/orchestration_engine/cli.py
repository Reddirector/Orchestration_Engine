"""Command-line interface for the orchestration engine."""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any, cast

from orchestration_engine.errors import (
    OrchestrationError,
    PersistenceError,
    WorkflowDefinitionError,
    WorkflowValidationError,
)
from orchestration_engine.loader import load_workflow_from_json
from orchestration_engine.models import Workflow, WorkflowStatus
from orchestration_engine.persistence import (
    get_connection,
    get_run_history,
    list_runs,
)
from orchestration_engine.runner import resume_run, run_workflow
from orchestration_engine.status import get_run_status

logger = logging.getLogger("orchestration_engine")


def _load_runner(runner_spec: str) -> Callable[..., Any]:
    """
    Resolve a task runner callable from a 'module:function' string via importlib.

    Note: This dynamically imports user-specified code and prepends os.getcwd()
    to sys.path. It operates under the same trust model as executing a Python script.
    """
    if ":" not in runner_spec:
        raise ValueError(
            f"Invalid runner specification '{runner_spec}'. Expected format 'module:function'."
        )
    module_name, func_name = runner_spec.split(":", 1)
    if not module_name.strip() or not func_name.strip():
        raise ValueError(
            f"Invalid runner specification '{runner_spec}'. Expected format 'module:function'."
        )

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        raise ImportError(f"Could not import module '{module_name}': {exc}") from exc

    if not hasattr(mod, func_name):
        raise AttributeError(f"Module '{module_name}' has no attribute '{func_name}'")

    runner = getattr(mod, func_name)
    if not callable(runner):
        raise TypeError(f"Runner '{runner_spec}' is not callable.")

    return cast(Callable[..., Any], runner)


def _load_workflow_file(path: str) -> Workflow:
    """Load a workflow definition from a JSON or YAML file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Workflow file not found: '{path}'")

    if os.path.getsize(path) > 10 * 1024 * 1024:
        raise WorkflowDefinitionError(f"Workflow file '{path}' exceeds maximum size of 10 MB")

    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        try:
            from orchestration_engine.loader import load_workflow_from_yaml
        except ImportError as exc:
            raise WorkflowValidationError(
                "YAML support requires the 'yaml' extra. "
                "Install with: pip install 'orchestration-engine[yaml]'"
            ) from exc
        return load_workflow_from_yaml(path, collect_errors=True)

    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise WorkflowDefinitionError(f"Invalid JSON in '{path}': {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowDefinitionError(f"Root of workflow JSON in '{path}' must be an object")

    return load_workflow_from_json(data, collect_errors=True)


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        workflow = _load_workflow_file(args.workflow_file)
    except (WorkflowValidationError, WorkflowDefinitionError, FileNotFoundError, ValueError) as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(
            json.dumps(
                {
                    "workflow_id": workflow.workflow_id,
                    "tasks_count": len(workflow.tasks),
                    "valid": True,
                }
            )
        )
    else:
        print(f"Workflow '{workflow.workflow_id}' is valid ({len(workflow.tasks)} tasks).")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        workflow = _load_workflow_file(args.workflow_file)
        runner = _load_runner(args.runner)
        if args.max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {args.max_concurrency}")
    except (
        WorkflowValidationError,
        WorkflowDefinitionError,
        FileNotFoundError,
        ValueError,
        ImportError,
        AttributeError,
        TypeError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 3

    try:
        conn = get_connection(args.db) if args.db else get_connection(":memory:")
    except PersistenceError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 3

    try:
        actual_run_id = run_workflow(
            workflow,
            task_states={},
            time_source=time.time,
            task_runner=runner,
            conn=conn,
            run_id=args.run_id,
            max_concurrency=args.max_concurrency,
            executor=args.executor,
        )
        st = get_run_status(conn, actual_run_id)
    except (
        WorkflowValidationError,
        WorkflowDefinitionError,
        OrchestrationError,
        ValueError,
    ) as exc:
        print(f"Execution error: {exc}", file=sys.stderr)
        return 2
    except PersistenceError as exc:
        print(f"Database error during run: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Internal error during run: {exc}", file=sys.stderr)
        return 3

    status_str = st.value if st is not None else "unknown"
    if args.json:
        print(
            json.dumps(
                {
                    "run_id": actual_run_id,
                    "workflow_id": workflow.workflow_id,
                    "status": status_str,
                }
            )
        )
    else:
        print(f"Workflow run '{actual_run_id}' completed with status: {status_str}")

    return 0 if st == WorkflowStatus.SUCCEEDED else 1


def _cmd_resume(args: argparse.Namespace) -> int:
    try:
        runner = _load_runner(args.runner)
        if args.max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {args.max_concurrency}")
    except (ValueError, ImportError, AttributeError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 3

    try:
        conn = get_connection(args.db)
    except PersistenceError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 3

    try:
        st = resume_run(
            conn=conn,
            run_id=args.run_id,
            task_runner=runner,
            time_source=time.time,
            max_concurrency=args.max_concurrency,
            executor=args.executor,
        )
    except (
        WorkflowValidationError,
        WorkflowDefinitionError,
        OrchestrationError,
        ValueError,
    ) as exc:
        print(f"Resume error: {exc}", file=sys.stderr)
        return 2
    except PersistenceError as exc:
        print(f"Database error during resume: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Internal error during resume: {exc}", file=sys.stderr)
        return 3

    status_str = st.value
    if args.json:
        print(json.dumps({"run_id": args.run_id, "status": status_str}))
    else:
        print(f"Resumed run '{args.run_id}' completed with status: {status_str}")

    return 0 if st == WorkflowStatus.SUCCEEDED else 1


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        conn = get_connection(args.db)
        st = get_run_status(conn, args.run_id)
    except PersistenceError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 3
    except OrchestrationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({"run_id": args.run_id, "status": st.value}))
    else:
        print(f"Run {args.run_id}: {st.value}")
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    try:
        conn = get_connection(args.db)
        get_run_status(conn, args.run_id)
        events = get_run_history(conn, args.run_id)
    except PersistenceError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 3
    except OrchestrationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        output_events = [
            {
                "id": row[0],
                "workflow_id": row[1],
                "task_id": row[2],
                "old_state": row[3],
                "new_state": row[4],
                "timestamp": row[5],
                "attempt_count": row[6],
            }
            for row in events
        ]
        print(json.dumps(output_events, indent=2))
    else:
        if not events:
            print(f"No history events recorded for run '{args.run_id}'.")
        else:
            for row in events:
                print(f"[{row[5]:.2f}] Task '{row[2]}': {row[3]} -> {row[4]} (attempt {row[6]})")
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    try:
        conn = get_connection(args.db)
        runs_list = list_runs(conn, workflow_id=args.workflow)
    except PersistenceError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        runs_data = [
            {
                "run_id": row[0],
                "workflow_id": row[1],
                "started_at": row[2],
                "finished_at": row[3],
                "status": row[4],
            }
            for row in runs_list
        ]
        print(json.dumps(runs_data, indent=2))
    else:
        if not runs_list:
            print("No runs found.")
        else:
            for row in runs_list:
                print(
                    f"{row[0]}  workflow={row[1]}  status={row[4]}  "
                    f"started={row[2]}  finished={row[3]}"
                )
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    """Analyze workflow and output execution plan."""
    from orchestration_engine.loader import load_workflow_from_json, load_workflow_from_yaml
    from orchestration_engine.plan import generate_execution_plan

    source = args.file
    try:
        with open(source, encoding="utf-8") as f:
            raw = f.read()
        if source.endswith((".yaml", ".yml")):
            wf = load_workflow_from_yaml(raw)
        else:
            wf = load_workflow_from_json(json.loads(raw))
    except Exception as exc:
        print(f"Error loading workflow: {exc}", file=sys.stderr)
        return 1

    plan = generate_execution_plan(wf)
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
    else:
        print(f"Workflow: {plan.workflow_id}")
        print(f"Total Tasks: {plan.total_tasks}")
        print(f"Max Parallelism: {plan.max_parallelism} concurrent workers")
        print(f"Critical Path: {' -> '.join(plan.critical_path)}")
        print("\nExecution Stages:")
        for s in plan.stages:
            print(f"  Stage {s.stage_index}: {', '.join(s.task_ids)}")
    return 0


def _cmd_dlq(args: argparse.Namespace) -> int:
    """Manage the Dead Letter Queue."""
    from orchestration_engine.dead_letter import DeadLetterQueue

    dlq = DeadLetterQueue(args.db)
    action = args.dlq_action

    if action == "list":
        messages = dlq.list_messages(workflow_id=args.workflow, limit=args.limit)
        if args.json:
            print(json.dumps([dataclasses.asdict(m) for m in messages], indent=2))
        else:
            if not messages:
                print("Dead Letter Queue is empty.")
            else:
                for m in messages:
                    print(
                        f"[{m.message_id[:8]}] task={m.task_id} workflow={m.workflow_id} "
                        f"attempts={m.attempt_count} error={m.error_message}"
                    )
    elif action == "purge":
        count = dlq.purge(workflow_id=args.workflow, older_than_seconds=args.older_than)
        print(f"Purged {count} message(s) from Dead Letter Queue.")
    return 0


def _cmd_trace(args: argparse.Namespace) -> int:
    """Export Chrome Trace / Perfetto format for a run."""
    from orchestration_engine.tracing import TraceExporter

    conn = get_connection(args.db)
    try:
        data = TraceExporter.to_chrome_trace(conn, args.run_id)
        out_str = json.dumps(data, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out_str)
            print(f"Exported Chrome trace for run '{args.run_id}' to {args.output}")
        else:
            print(out_str)
        return 0
    finally:
        conn.close()


def _cmd_signal(args: argparse.Namespace) -> int:
    """Send a human-in-the-loop signal to a workflow run."""
    from orchestration_engine.signals import default_signal_broker

    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON payload: {exc}", file=sys.stderr)
        return 2

    conn = get_connection(args.db)
    try:
        default_signal_broker.send_signal(args.run_id, args.signal_name, payload, conn)
        print(f"Signal '{args.signal_name}' delivered to run '{args.run_id}'.")
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        type=str.upper,
        help="Configure log level for orchestration_engine.",
    )

    parser = argparse.ArgumentParser(
        prog="orchestration-engine",
        description="Fault-tolerant, dependency-aware workflow orchestration engine.",
        parents=[common],
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # validate
    val_p = subparsers.add_parser(
        "validate", parents=[common], help="Validate a workflow definition file."
    )
    val_p.add_argument("workflow_file", help="Path to workflow JSON or YAML file.")
    val_p.add_argument("--json", action="store_true", help="Output result as JSON.")
    val_p.set_defaults(func=_cmd_validate)

    # run
    run_p = subparsers.add_parser("run", parents=[common], help="Run a workflow to completion.")
    run_p.add_argument("workflow_file", help="Path to workflow JSON or YAML file.")
    run_p.add_argument(
        "--runner", required=True, help="Task runner callable in 'module:function' format."
    )
    run_p.add_argument(
        "--db", default=None, help="Path to SQLite database (defaults to in-memory)."
    )
    run_p.add_argument("--run-id", default=None, help="Custom identifier for this run.")
    run_p.add_argument(
        "--max-concurrency", type=int, default=1, help="Maximum concurrent tasks (default: 1)."
    )
    run_p.add_argument(
        "--executor",
        choices=["thread", "process"],
        default="thread",
        help="Coordinator executor backend.",
    )
    run_p.add_argument("--json", action="store_true", help="Output result as JSON.")
    run_p.set_defaults(func=_cmd_run)

    # resume
    res_p = subparsers.add_parser(
        "resume", parents=[common], help="Resume an interrupted run."
    )
    res_p.add_argument("run_id", help="Run identifier to resume.")
    res_p.add_argument(
        "--runner", required=True, help="Task runner callable in 'module:function' format."
    )
    res_p.add_argument("--db", required=True, help="Path to SQLite database.")
    res_p.add_argument(
        "--max-concurrency", type=int, default=1, help="Maximum concurrent tasks (default: 1)."
    )
    res_p.add_argument(
        "--executor",
        choices=["thread", "process"],
        default="thread",
        help="Coordinator executor backend.",
    )
    res_p.add_argument("--json", action="store_true", help="Output result as JSON.")
    res_p.set_defaults(func=_cmd_resume)

    # status
    stat_p = subparsers.add_parser("status", parents=[common], help="Check run status.")
    stat_p.add_argument("run_id", help="Run identifier.")
    stat_p.add_argument("--db", required=True, help="Path to SQLite database.")
    stat_p.add_argument("--json", action="store_true", help="Output result as JSON.")
    stat_p.set_defaults(func=_cmd_status)

    # history
    hist_p = subparsers.add_parser(
        "history", parents=[common], help="Show task transition history."
    )
    hist_p.add_argument("run_id", help="Run identifier.")
    hist_p.add_argument("--db", required=True, help="Path to SQLite database.")
    hist_p.add_argument("--json", action="store_true", help="Output result as JSON.")
    hist_p.set_defaults(func=_cmd_history)

    # runs
    runs_p = subparsers.add_parser("runs", parents=[common], help="List workflow runs.")
    runs_p.add_argument("--db", required=True, help="Path to SQLite database.")
    runs_p.add_argument("--workflow", default=None, help="Filter runs by workflow identifier.")
    runs_p.add_argument("--json", action="store_true", help="Output result as JSON.")
    runs_p.set_defaults(func=_cmd_runs)

    # plan
    plan_p = subparsers.add_parser(
        "plan", parents=[common], help="Generate dry-run execution plan and critical path."
    )
    plan_p.add_argument("file", help="Path to workflow JSON or YAML file.")
    plan_p.add_argument("--json", action="store_true", help="Output plan as JSON.")
    plan_p.set_defaults(func=_cmd_plan)

    # dlq
    dlq_p = subparsers.add_parser(
        "dlq", parents=[common], help="Manage Dead Letter Queue for failed tasks."
    )
    dlq_p.add_argument("dlq_action", choices=["list", "purge"], help="DLQ action.")
    dlq_p.add_argument("--db", default="orchestration.db", help="Path to SQLite database.")
    dlq_p.add_argument("--workflow", default=None, help="Filter by workflow identifier.")
    dlq_p.add_argument("--limit", type=int, default=50, help="Maximum messages to list.")
    dlq_p.add_argument(
        "--older-than", type=float, default=None, help="Purge messages older than N seconds."
    )
    dlq_p.add_argument("--json", action="store_true", help="Output as JSON.")
    dlq_p.set_defaults(func=_cmd_dlq)

    # trace
    tr_p = subparsers.add_parser(
        "trace", parents=[common], help="Export Chrome Trace / Perfetto format for a run."
    )
    tr_p.add_argument("run_id", help="Run identifier.")
    tr_p.add_argument("--db", required=True, help="Path to SQLite database.")
    tr_p.add_argument("-o", "--output", default=None, help="Output JSON file path.")
    tr_p.set_defaults(func=_cmd_trace)

    # signal
    sig_p = subparsers.add_parser(
        "signal", parents=[common], help="Send human-in-the-loop signal to a run."
    )
    sig_p.add_argument("run_id", help="Run identifier.")
    sig_p.add_argument("signal_name", help="Signal name (e.g. approval, webhook).")
    sig_p.add_argument(
        "--payload", default="{}", help="JSON payload to deliver (default: '{}')."
    )
    sig_p.add_argument(
        "--db", default="orchestration.db", help="Path to SQLite database."
    )
    sig_p.set_defaults(func=_cmd_signal)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the orchestration-engine CLI."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if args.log_level:
        logging.basicConfig(
            level=getattr(logging, args.log_level.upper()),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 2

    return int(args.func(args))
