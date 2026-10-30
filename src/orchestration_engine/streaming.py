"""Zero-Memory Streaming Tasks and Ring-Buffer Backpressure.

Enables tasks to stream records, token generators, or large datasets item-by-item
without buffering gigabytes into memory. Features an in-memory queue that automatically
spills to SQLite when the consumer is slower than the producer (backpressure mitigation).
"""

from __future__ import annotations

import collections.abc
import json
import queue
import threading
import uuid
from collections.abc import Iterator
from types import TracebackType
from typing import Any

from orchestration_engine.persistence import get_connection


class StreamPipe:
    """Thread-safe streaming pipe with optional disk-spooling backpressure.

    Attributes:
        max_buffer_size: Number of elements kept in RAM before spilling to SQLite.
        db_path: Path to SQLite database for spooling overflow items.
    """

    def __init__(
        self,
        max_buffer_size: int = 1000,
        spill_db_path: str | None = None,
    ) -> None:
        self.max_buffer_size = max_buffer_size
        self.spill_db_path = spill_db_path
        self._stream_id = uuid.uuid4().hex
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_buffer_size)
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._spill_count = 0
        self._read_spill_cursor = 0

        if self.spill_db_path:
            self._init_spill_table()

    def _init_spill_table(self) -> None:
        assert self.spill_db_path is not None
        conn = get_connection(self.spill_db_path)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stream_spool (
                    stream_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    item_json TEXT NOT NULL,
                    PRIMARY KEY (stream_id, sequence_no)
                )
                """
            )

    def push(self, item: Any) -> None:
        """Push an item into the stream. Spills to SQLite if buffer is saturated."""
        if self._closed.is_set():
            raise RuntimeError("Cannot push into a closed StreamPipe")

        try:
            self._queue.put_nowait(item)
        except queue.Full:
            if self.spill_db_path:
                with self._lock:
                    self._spill_count += 1
                    seq = self._spill_count
                conn = get_connection(self.spill_db_path)
                with conn:
                    conn.execute(
                        """
                        INSERT INTO stream_spool (stream_id, sequence_no, item_json)
                        VALUES (?, ?, ?)
                        """,
                        (self._stream_id, seq, json.dumps(item)),
                    )
            else:
                # Blocks producer until space is freed (natural backpressure)
                self._queue.put(item)

    def close(self) -> None:
        """Signal end of stream (EOF)."""
        self._closed.set()

    def pull(self, timeout: float | None = 10.0) -> Any:
        """Pull the next item. Raises StopIteration when stream is closed and empty."""
        try:
            return self._queue.get(timeout=timeout if not self._closed.is_set() else 0.05)
        except queue.Empty as exc:
            # Check if any items were spooled to SQLite
            if self.spill_db_path and self._read_spill_cursor < self._spill_count:
                with self._lock:
                    self._read_spill_cursor += 1
                    seq = self._read_spill_cursor
                conn = get_connection(self.spill_db_path)
                with conn:
                    cursor = conn.execute(
                        "SELECT item_json FROM stream_spool "
                        "WHERE stream_id = ? AND sequence_no = ?",
                        (self._stream_id, seq),
                    )
                    row = cursor.fetchone()
                    if row:
                        conn.execute(
                            "DELETE FROM stream_spool WHERE stream_id = ? AND sequence_no = ?",
                            (self._stream_id, seq),
                        )
                        return json.loads(row[0])

            if self._closed.is_set():
                raise StopIteration from None
            raise TimeoutError("Timed out waiting for item in StreamPipe") from exc

    def __iter__(self) -> Iterator[Any]:
        while True:
            try:
                yield self.pull()
            except StopIteration:
                break

    def __enter__(self) -> StreamPipe:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
        # Clean up any leftover spooled items
        if self.spill_db_path:
            conn = get_connection(self.spill_db_path)
            with conn:
                conn.execute(
                    "DELETE FROM stream_spool WHERE stream_id = ?",
                    (self._stream_id,),
                )


def run_streaming_pipeline(
    producer: collections.abc.Callable[[StreamPipe], None],
    consumer: collections.abc.Callable[[StreamPipe], Any],
    *,
    max_buffer_size: int = 1000,
    spill_db_path: str | None = None,
) -> Any:
    """Execute a producer-consumer streaming pipeline with zero memory accumulation."""
    pipe = StreamPipe(max_buffer_size=max_buffer_size, spill_db_path=spill_db_path)
    producer_error: list[Exception] = []

    def _producer_wrapper() -> None:
        try:
            producer(pipe)
        except Exception as exc:
            producer_error.append(exc)
        finally:
            pipe.close()

    producer_thread = threading.Thread(target=_producer_wrapper, daemon=True)
    producer_thread.start()

    try:
        result = consumer(pipe)
    finally:
        producer_thread.join(timeout=5.0)

    if producer_error:
        raise producer_error[0]

    return result
