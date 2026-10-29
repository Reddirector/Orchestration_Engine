"""
Scheduling components for Orchestration Engine.

Provides:
- `schedule_once`: Step-level DAG scheduler evaluating ready tasks and cancellations.
- `IntervalSchedule`: Fixed interval recurrence (e.g. every 60 seconds).
- `CronSchedule`: 5-field cron recurrence (e.g. '*/15 * * * *', '0 9 * * 1-5').
- `WorkflowScheduler`: Background scheduler daemon to run workflows on recurring schedules.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orchestration_engine.executor import retry_task
from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.readiness import cancel_blocked_tasks, mark_ready_tasks

logger = logging.getLogger("orchestration_engine.scheduler")


def schedule_once(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    current_time: float,
    conn: sqlite3.Connection,
) -> list[Task]:
    """
    Evaluate ready and retrying tasks for a single workflow scheduling iteration.
    Cancels blocked tasks to a fixpoint.
    """
    retried_tasks: list[Task] = []

    for task in workflow.tasks:
        if task.state == TaskState.RETRY_WAIT:
            if retry_task(task, current_time, conn, task_states):
                retried_tasks.append(task)

    cancel_blocked_tasks(workflow, task_states, conn, current_time)
    ready_tasks = mark_ready_tasks(workflow, task_states, conn, current_time)

    return ready_tasks + retried_tasks


# ---------------------------------------------------------------------------
# Recurring Schedule Components
# ---------------------------------------------------------------------------


class IntervalSchedule:
    """
    Fixed-interval recurring schedule.

    Args:
        seconds: Number of seconds between executions.
    """

    def __init__(self, seconds: float) -> None:
        if seconds <= 0:
            raise ValueError("Interval seconds must be greater than 0.")
        self.interval_seconds = float(seconds)

    def next_run_after(self, reference_time: float) -> float:
        """Compute the next execution timestamp strictly after reference_time."""
        return reference_time + self.interval_seconds

    def __repr__(self) -> str:
        return f"IntervalSchedule({self.interval_seconds}s)"


class CronSchedule:
    """
    Zero-dependency 5-field standard cron schedule.

    Format: `minute hour day_of_month month day_of_week`
    Supports: `*`, `*/n`, `a-b`, `a,b,c`
    Days of week: 0-6 (0=Sunday ... 6=Saturday, or 7=Sunday).
    """

    def __init__(self, expression: str) -> None:
        self.expression = expression.strip()
        parts = self.expression.split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression '{expression}': expected 5 fields "
                "(minute hour day month day_of_week)."
            )
        self.minute_spec = self._parse_field(parts[0], 0, 59)
        self.hour_spec = self._parse_field(parts[1], 0, 23)
        self.day_spec = self._parse_field(parts[2], 1, 31)
        self.month_spec = self._parse_field(parts[3], 1, 12)
        self.dow_spec = self._parse_dow_field(parts[4])

    @staticmethod
    def _parse_field(field_str: str, min_val: int, max_val: int) -> set[int]:
        allowed: set[int] = set()
        for item in field_str.split(","):
            item = item.strip()
            if not item:
                continue
            if item == "*":
                allowed.update(range(min_val, max_val + 1))
            elif item.startswith("*/"):
                step = int(item[2:])
                if step <= 0:
                    raise ValueError(f"Invalid cron step '{item}'")
                allowed.update(range(min_val, max_val + 1, step))
            elif "-" in item:
                start_s, end_s = item.split("-", 1)
                start, end = int(start_s), int(end_s)
                if start > end or start < min_val or end > max_val:
                    raise ValueError(f"Invalid cron range '{item}' ({min_val}-{max_val})")
                allowed.update(range(start, end + 1))
            else:
                val = int(item)
                if val < min_val or val > max_val:
                    raise ValueError(f"Value '{val}' out of bounds ({min_val}-{max_val})")
                allowed.add(val)
        return allowed

    @classmethod
    def _parse_dow_field(cls, field_str: str) -> set[int]:
        raw = cls._parse_field(field_str, 0, 7)
        # Standard cron: 0 or 7 is Sunday. Normalize 7 -> 0
        normalized = set()
        for v in raw:
            normalized.add(0 if v == 7 else v)
        return normalized

    def matches(self, dt: datetime.datetime) -> bool:
        """Check if datetime matches cron specification."""
        # Python weekday: Mon=0 ... Sun=6
        # Cron weekday: Sun=0, Mon=1 ... Sat=6
        cron_dow = (dt.weekday() + 1) % 7
        return (
            dt.minute in self.minute_spec
            and dt.hour in self.hour_spec
            and dt.day in self.day_spec
            and dt.month in self.month_spec
            and cron_dow in self.dow_spec
        )

    def next_run_after(self, reference_time: float) -> float:
        """
        Compute the next UNIX timestamp matching the cron expression.
        Advances in 1-minute increments starting from reference_time rounded to minute.
        """
        dt = datetime.datetime.fromtimestamp(reference_time).replace(second=0, microsecond=0)
        dt += datetime.timedelta(minutes=1)

        # Search up to 366 days ahead
        max_minutes = 366 * 24 * 60
        for _ in range(max_minutes):
            if self.matches(dt):
                return dt.timestamp()
            dt += datetime.timedelta(minutes=1)

        raise OverflowError(f"No match found for cron '{self.expression}' within 1 year.")

    def __repr__(self) -> str:
        return f"CronSchedule('{self.expression}')"


@dataclass
class ScheduledJob:
    """A registered scheduled workflow job."""

    job_id: str
    workflow_factory: Callable[[], Workflow]
    schedule: IntervalSchedule | CronSchedule
    task_runner: Callable[[Task], Any]
    max_concurrency: int = 1
    db_path: str = "orchestration.db"
    last_run_at: float | None = None
    next_run_at: float = 0.0
    runs_count: int = 0
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkflowScheduler:
    """
    Recurring workflow scheduler daemon.

    Manages registered workflow jobs, periodically checks due schedules,
    and launches workflow executions in background worker threads.
    """

    def __init__(self, check_interval: float = 1.0, time_source: Callable[[], float] = time.time):
        self.check_interval = check_interval
        self.time_source = time_source
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def add_job(
        self,
        job_id: str,
        workflow_factory: Callable[[], Workflow],
        schedule: IntervalSchedule | CronSchedule,
        task_runner: Callable[[Task], Any],
        max_concurrency: int = 1,
        db_path: str = "orchestration.db",
        metadata: dict[str, Any] | None = None,
    ) -> ScheduledJob:
        """Register a new scheduled workflow job."""
        now = self.time_source()
        next_run = schedule.next_run_after(now)
        job = ScheduledJob(
            job_id=job_id,
            workflow_factory=workflow_factory,
            schedule=schedule,
            task_runner=task_runner,
            max_concurrency=max_concurrency,
            db_path=db_path,
            next_run_at=next_run,
            metadata=metadata or {},
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by ID."""
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def list_jobs(self) -> list[dict[str, Any]]:
        """List all scheduled jobs with their status and timing."""
        with self._lock:
            result = []
            for job in self._jobs.values():
                result.append(
                    {
                        "job_id": job.job_id,
                        "schedule": str(job.schedule),
                        "is_active": job.is_active,
                        "last_run_at": job.last_run_at,
                        "next_run_at": job.next_run_at,
                        "runs_count": job.runs_count,
                        "max_concurrency": job.max_concurrency,
                        "metadata": job.metadata,
                    }
                )
            return result

    def tick(self, now: float | None = None) -> list[str]:
        """
        Evaluate all jobs against the current timestamp.
        Triggers any due jobs and returns their job IDs.
        """
        from orchestration_engine.persistence import get_connection
        from orchestration_engine.runner import run_workflow

        current = self.time_source() if now is None else now
        triggered: list[str] = []

        with self._lock:
            due_jobs = [
                j for j in self._jobs.values() if j.is_active and current >= j.next_run_at
            ]

        for job in due_jobs:
            job.last_run_at = current
            job.runs_count += 1
            job.next_run_at = job.schedule.next_run_after(current)
            triggered.append(job.job_id)

            def _execute(target_job: ScheduledJob) -> None:
                try:
                    wf = target_job.workflow_factory()
                    conn = get_connection(target_job.db_path)
                    try:
                        run_workflow(
                            workflow=wf,
                            task_states={},
                            time_source=self.time_source,
                            task_runner=target_job.task_runner,
                            conn=conn,
                            max_concurrency=target_job.max_concurrency,
                        )
                    finally:
                        conn.close()
                except Exception as exc:
                    logger.error("Error executing scheduled job '%s': %s", target_job.job_id, exc)

            worker = threading.Thread(
                target=_execute, args=(job,), name=f"scheduler-job-{job.job_id}", daemon=True
            )
            worker.start()

        return triggered

    def start(self, daemon: bool = True) -> None:
        """Start the background scheduler daemon loop."""
        with self._lock:
            if self._running:
                return
            self._running = True

        def _loop() -> None:
            while self._running:
                self.tick()
                time.sleep(self.check_interval)

        self._thread = threading.Thread(target=_loop, name="workflow-scheduler", daemon=daemon)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler daemon loop."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
