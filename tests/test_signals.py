"""Unit tests for SignalBroker and Human-in-the-Loop workflows."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time

import pytest

from orchestration_engine.signals import SignalBroker, SignalTimeoutError


def test_signal_broker_send_and_wait(tmp_path: pytest.TempPathFactory) -> None:
    db = str(tmp_path) + "/signals.db"
    broker = SignalBroker(db_path=db)

    # Deliver before wait (buffered signal)
    broker.send_signal(run_id="run-1", signal_name="approval", payload={"approved": True})
    result = broker.wait_for_signal(run_id="run-1", signal_name="approval", timeout=2.0)
    assert result == {"approved": True}

    # Signal in background thread while waiting
    def _delayed_send() -> None:
        time.sleep(0.05)
        broker.send_signal(run_id="run-2", signal_name="proceed", payload={"token": "abc-123"})

    t = threading.Thread(target=_delayed_send)
    t.start()

    res2 = broker.wait_for_signal(run_id="run-2", signal_name="proceed", timeout=2.0)
    t.join()
    assert res2 == {"token": "abc-123"}


def test_signal_timeout() -> None:
    broker = SignalBroker(db_path=":memory:")
    with pytest.raises(SignalTimeoutError):
        broker.wait_for_signal(run_id="run-timeout", signal_name="never_arrives", timeout=0.05)


def test_signal_broker_async() -> None:
    broker = SignalBroker(db_path=":memory:")

    async def _test() -> None:
        async def _sender() -> None:
            await asyncio.sleep(0.02)
            broker.send_signal(run_id="async-run", signal_name="resume", payload={"step": 2})

        asyncio.create_task(_sender())
        res = await broker.wait_for_signal_async(
            run_id="async-run", signal_name="resume", timeout=1.0
        )
        assert res == {"step": 2}

    asyncio.run(_test())


def test_list_signals(conn: sqlite3.Connection) -> None:
    broker = SignalBroker(db_path=":memory:")
    broker.send_signal("run-audit", "sig_a", {"val": 1}, conn=conn)
    broker.send_signal("run-audit", "sig_b", {"val": 2}, conn=conn)

    history = broker.list_signals("run-audit", conn=conn)
    assert len(history) == 2
    assert history[0]["signal_name"] == "sig_a"
    assert history[0]["payload"] == {"val": 1}
    assert history[1]["signal_name"] == "sig_b"
