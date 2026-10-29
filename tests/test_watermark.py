"""Tests for Stateful Watermark and Incremental ETL Store."""

from __future__ import annotations

from typing import Any

from orchestration_engine.watermark import WatermarkStore


def test_watermark_set_get_advance(tmp_path: Any) -> None:
    db = str(tmp_path / "watermarks.db")
    store = WatermarkStore(db)

    # Initial get returns default
    assert store.get_watermark("pipeline-sales", "last_timestamp", default=0.0) == 0.0

    # Set watermark
    store.set_watermark("pipeline-sales", "last_timestamp", 1700000000.0, run_id="run-001")
    val = store.get_watermark("pipeline-sales", "last_timestamp")
    assert val == 1700000000.0

    # Advance watermark
    store.advance_watermark("pipeline-sales", "last_timestamp", 1700003600.0, run_id="run-002")
    assert store.get_watermark("pipeline-sales", "last_timestamp") == 1700003600.0

    # Complex JSON dictionary watermark
    kafka_offsets = {"partition-0": 1054, "partition-1": 2980}
    store.set_watermark("pipeline-events", "kafka_offsets", kafka_offsets)
    assert store.get_watermark("pipeline-events", "kafka_offsets") == kafka_offsets

    # List
    all_wm = store.list_watermarks()
    assert len(all_wm) == 2

    sales_wm = store.list_watermarks(pipeline_id="pipeline-sales")
    assert len(sales_wm) == 1
    assert sales_wm[0].key == "last_timestamp"
    assert sales_wm[0].run_id == "run-002"
