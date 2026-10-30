"""Zero-Memory Streaming Pipeline with Disk-Spooling Backpressure.

Demonstrates high-throughput, constant-memory producer-consumer streaming:
1. Producer generates a high-volume stream of event records.
2. StreamPipe with a compact RAM ring-buffer (e.g. 50 items) automatically
   spills excess items to SQLite when the consumer processes at a slower rate.
3. Consumer streams and aggregates records in O(1) constant memory.
4. Automatic spool cleanup on pipeline completion.
"""

from __future__ import annotations

import tempfile
import time
from typing import Any

from orchestration_engine import StreamPipe, run_streaming_pipeline


def run_streaming_demo() -> None:
    print("=" * 70)
    print("🌊 Zero-Memory Streaming Pipeline with Disk-Spooling Backpressure")
    print("=" * 70)

    total_records = 200

    def event_producer(pipe: StreamPipe) -> None:
        print(f"\n[Producer] Streaming {total_records} events at high speed...")
        for i in range(1, total_records + 1):
            event = {
                "event_id": f"evt-{i:05d}",
                "metric_value": i * 1.5,
                "timestamp": time.time(),
            }
            pipe.push(event)
            # Producer produces rapidly
            if i % 50 == 0:
                print(
                    f"  [Producer] Pushed {i}/{total_records} events "
                    f"(RAM buffer limit: {pipe.max_buffer_size})"
                )
        print("  [Producer] Finished generating all events.")

    def event_consumer(pipe: StreamPipe) -> dict[str, Any]:
        print("\n[Consumer] Consuming events with continuous backpressure...")
        count = 0
        total_sum = 0.0

        for event in pipe:
            count += 1
            total_sum += float(event["metric_value"])
            # Simulate processing delay to trigger spill-to-disk spooling
            if count % 40 == 0:
                print(f"  [Consumer] Processed {count} events... (running sum: {total_sum:.2f})")
                time.sleep(0.01)

        print(f"  [Consumer] Stream finished! Total events processed: {count}")
        return {
            "processed_count": count,
            "metric_sum": total_sum,
            "average_metric": total_sum / count if count else 0.0,
        }

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        spill_db = tmp.name
        # Set max_buffer_size=20 so items 21..200 automatically spill to SQLite spool
        result = run_streaming_pipeline(
            producer=event_producer,
            consumer=event_consumer,
            max_buffer_size=20,
            spill_db_path=spill_db,
        )

        print("\n" + "=" * 70)
        print("📊 Pipeline Aggregation Result:")
        print(f"  Total Processed: {result['processed_count']} events")
        print(f"  Total Metric Sum: {result['metric_sum']:.2f}")
        print(f"  Average Metric: {result['average_metric']:.2f}")
        print("  Memory footprint: O(1) constant RAM despite high volume.")
        print("=" * 70)


if __name__ == "__main__":
    run_streaming_demo()
