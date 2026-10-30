"""Tests for Zero-Dependency Distributed Worker Cluster."""

from __future__ import annotations

import threading
import time
from typing import Any

from orchestration_engine.distributed import CoordinatorServer, WorkerAgent


def test_distributed_cluster_end_to_end(tmp_path: Any) -> None:
    db = str(tmp_path / "cluster.db")
    # Bind to ephemeral port by choosing port=0
    coordinator = CoordinatorServer(host="127.0.0.1", port=0, db_path=db)
    actual_port = coordinator.server_address[1]
    coord_url = f"http://127.0.0.1:{actual_port}"

    coord_thread = threading.Thread(target=coordinator.serve_forever, daemon=True)
    coord_thread.start()

    def sample_runner(payload: dict[str, Any]) -> dict[str, Any]:
        return {"doubled": payload.get("x", 0) * 2}

    worker = WorkerAgent(coord_url, task_runner=sample_runner, poll_interval=0.1)

    try:
        assert worker.register() is True
        worker.send_heartbeat()

        status = coordinator.get_cluster_status()
        assert status["active_workers_count"] >= 1

        # Submit task
        coordinator.submit_task("t-101", "wf-dist", {"x": 21})

        worker.start()

        # Wait for task completion
        deadline = time.time() + 5.0
        result = None
        while time.time() < deadline:
            result = coordinator.get_result("t-101")
            if result is not None:
                break
            time.sleep(0.1)

        assert result is not None
        assert result.get("ok") is True
        assert result.get("output") == {"doubled": 42}

    finally:
        worker.stop()
        coordinator.shutdown()
        coordinator.server_close()
        coord_thread.join(timeout=2.0)
