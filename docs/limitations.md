# Known Limitations & Design Boundaries

`orchestration-engine` prioritizes simplicity, correctness, and zero runtime dependencies over multi-node distributed complexity. 

The following known limitations and non-goals are deliberate design trade-offs:

---

## 1. Thread Timeouts Cannot Forcefully Terminate Threads

In the Thread backend (`executor="thread"`):
- When a task reaches its `timeout_seconds`, the coordinator marks the task attempt as timed out, schedules a retry or failure, and moves forward.
- However, standard Python threads cannot be forcefully killed from the outside without unsafe native CPython hacks.
- If a thread is stuck inside a blocking C call (e.g., an uncooperative network socket without a socket-level timeout), the underlying thread will remain alive until it returns or the process exits.

> **Mitigation**: Use `executor="process"` if hard termination via `SIGTERM` / `SIGKILL` is strictly required.

---

## 2. Single-Node Execution (No Distributed Coordination)

- `orchestration-engine` coordinates tasks on a single machine using SQLite and local processes or threads.
- It does **not** support multi-machine scheduling (e.g., Celery, Airflow, Temporal, Ray).
- It does not integrate with message brokers (RabbitMQ, Kafka, Redis).

---

## 3. SQLite Single-Writer Bottleneck

- While WAL mode enables high write throughput, all transitions route through the single coordinator loop.
- The engine is optimized for multi-step AI and data pipelines where task duration ranges from hundreds of milliseconds to minutes, rather than millions of micro-tasks per second.

---

## 4. No Built-In Cron Scheduler or Web UI

- The engine provides on-demand execution and resume via Python APIs and the CLI.
- Recurring cron schedules, backfilling, and web dashboards are out of scope and should be handled by external schedulers (e.g., systemd timers, cron, GitHub Actions).
