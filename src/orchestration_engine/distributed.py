"""Zero-Dependency Distributed Worker Cluster.

Coordinates tasks across multiple machines or container instances over standard HTTP
without requiring Celery, Redis, RabbitMQ, or ZooKeeper.
Features a built-in CoordinatorServer and auto-reconnecting WorkerAgent.
"""

from __future__ import annotations

import collections.abc
import http.server
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, cast

from orchestration_engine.persistence import get_connection

logger = logging.getLogger(__name__)


class _CoordinatorHandler(http.server.BaseHTTPRequestHandler):
    server: CoordinatorServer

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {}

        path = self.path.split("?")[0]

        if path == "/api/worker/register":
            worker_id = data.get("worker_id") or uuid.uuid4().hex
            self.server.register_worker(worker_id)
            self._send_json({"ok": True, "worker_id": worker_id})
        elif path == "/api/worker/heartbeat":
            worker_id = data.get("worker_id")
            if worker_id:
                self.server.heartbeat_worker(worker_id)
            self._send_json({"ok": True})
        elif path == "/api/tasks/complete":
            task_id = data.get("task_id")
            result = data.get("result", {})
            self.server.report_completion(task_id, result)
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "Not Found"}, status=404)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/tasks/poll":
            worker_id = query.get("worker_id", [""])[0]
            task = self.server.poll_task(worker_id)
            if task:
                self._send_json({"ok": True, "task": task})
            else:
                self._send_json({"ok": True, "task": None})
        elif path == "/api/cluster/status":
            status = self.server.get_cluster_status()
            self._send_json({"ok": True, "status": status})
        else:
            self._send_json({"error": "Not Found"}, status=404)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        out = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class CoordinatorServer(http.server.ThreadingHTTPServer):
    """Central HTTP coordinator assigning tasks to remote workers."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9100,
        db_path: str = "orchestration.db",
    ) -> None:
        super().__init__((host, port), _CoordinatorHandler)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._task_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._workers: dict[str, float] = {}  # worker_id -> last_heartbeat
        self._completed_results: dict[str, dict[str, Any]] = {}
        self._init_db()

    def _init_db(self) -> None:
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cluster_workers (
                    worker_id TEXT PRIMARY KEY,
                    registered_at REAL NOT NULL,
                    last_heartbeat REAL NOT NULL
                )
                """
            )

    def register_worker(self, worker_id: str) -> None:
        now = time.time()
        with self._lock:
            self._workers[worker_id] = now
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO cluster_workers (worker_id, registered_at, last_heartbeat)
                VALUES (?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET last_heartbeat = excluded.last_heartbeat
                """,
                (worker_id, now, now),
            )

    def heartbeat_worker(self, worker_id: str) -> None:
        now = time.time()
        with self._lock:
            self._workers[worker_id] = now

    def submit_task(self, task_id: str, workflow_id: str, payload: dict[str, Any]) -> None:
        """Enqueue a task to be pulled and executed by a remote worker."""
        self._task_queue.put(
            {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "payload": payload,
            }
        )

    def poll_task(self, worker_id: str) -> dict[str, Any] | None:
        try:
            return self._task_queue.get_nowait()
        except queue.Empty:
            return None

    def report_completion(self, task_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._completed_results[task_id] = result

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._completed_results.get(task_id)

    def get_cluster_status(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            active = [w for w, hb in self._workers.items() if now - hb < 30.0]
            return {
                "active_workers_count": len(active),
                "queued_tasks_count": self._task_queue.qsize(),
                "completed_tasks_count": len(self._completed_results),
            }


class WorkerAgent:
    """Remote compute node connecting to the Coordinator over HTTP."""

    def __init__(
        self,
        coordinator_url: str,
        *,
        worker_id: str | None = None,
        task_runner: collections.abc.Callable[[dict[str, Any]], Any] | None = None,
        poll_interval: float = 0.5,
    ) -> None:
        self.coordinator_url = coordinator_url.rstrip("/")
        self.worker_id = worker_id or uuid.uuid4().hex
        self.task_runner = task_runner or (lambda t: {"status": "ok"})
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None

    def register(self) -> bool:
        url = f"{self.coordinator_url}/api/worker/register"
        data = json.dumps({"worker_id": self.worker_id}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return bool(res.get("ok"))
        except Exception as exc:
            logger.error("Failed to register with coordinator: %s", exc)
            return False

    def send_heartbeat(self) -> None:
        url = f"{self.coordinator_url}/api/worker/heartbeat"
        data = json.dumps({"worker_id": self.worker_id}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                resp.read()
        except Exception:
            pass

    def start(self) -> None:
        """Start worker loop and heartbeat background threads."""
        self.register()
        self._stop_event.clear()

        def _heartbeat_loop() -> None:
            while not self._stop_event.wait(5.0):
                self.send_heartbeat()

        def _work_loop() -> None:
            while not self._stop_event.is_set():
                task_data = self._poll()
                if task_data:
                    self._execute_and_report(task_data)
                else:
                    time.sleep(self.poll_interval)

        self._heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

        self._worker_thread = threading.Thread(target=_work_loop, daemon=True)
        self._worker_thread.start()

    def _poll(self) -> dict[str, Any] | None:
        url = f"{self.coordinator_url}/api/tasks/poll?worker_id={self.worker_id}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return cast(dict[str, Any] | None, data.get("task"))
        except Exception:
            return None

    def _execute_and_report(self, task_data: dict[str, Any]) -> None:
        task_id = task_data.get("task_id", "")
        payload = task_data.get("payload", {})
        try:
            output = self.task_runner(payload)
            result = {"ok": True, "output": output}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}

        url = f"{self.coordinator_url}/api/tasks/complete"
        data = json.dumps({"task_id": task_id, "result": result}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                resp.read()
        except Exception as exc:
            logger.error("Failed to report task completion: %s", exc)

    def stop(self) -> None:
        """Stop worker execution cleanly."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=1.0)
