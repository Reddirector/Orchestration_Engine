"""Tests for Zero-Memory Streaming Tasks and Ring-Buffer Backpressure."""

from __future__ import annotations

from typing import Any

import pytest

from orchestration_engine.streaming import StreamPipe, run_streaming_pipeline


def test_stream_pipe_push_pull_and_iteration() -> None:
    pipe = StreamPipe(max_buffer_size=10)

    for i in range(5):
        pipe.push(f"item-{i}")
    pipe.close()

    collected = list(pipe)
    assert collected == ["item-0", "item-1", "item-2", "item-3", "item-4"]

    with pytest.raises(RuntimeError):
        pipe.push("too-late")


def test_stream_pipe_spill_to_disk(tmp_path: Any) -> None:
    db = str(tmp_path / "spool.db")
    # Tiny buffer of 2 items, remaining 5 items must spill to SQLite
    pipe = StreamPipe(max_buffer_size=2, spill_db_path=db)

    for i in range(7):
        pipe.push({"record_id": i})
    pipe.close()

    results = []
    with pipe:
        for item in pipe:
            results.append(item["record_id"])

    assert results == [0, 1, 2, 3, 4, 5, 6]


def test_run_streaming_pipeline() -> None:
    def producer(stream: StreamPipe) -> None:
        for word in ["orchestration", "engine", "streaming"]:
            stream.push(word)

    def consumer(stream: StreamPipe) -> str:
        words = list(stream)
        return " ".join(words)

    result = run_streaming_pipeline(producer, consumer, max_buffer_size=5)
    assert result == "orchestration engine streaming"
