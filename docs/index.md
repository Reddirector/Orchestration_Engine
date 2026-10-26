# Orchestration Engine

[![PyPI version](https://img.shields.io/pypi/v/orchestration-engine.svg)](https://pypi.org/project/orchestration-engine/)
[![Python versions](https://img.shields.io/pypi/pyversions/orchestration-engine.svg)](https://pypi.org/project/orchestration-engine/)
[![License](https://img.shields.io/badge/license-MIT%20%7C%20Apache--2.0-blue.svg)](https://github.com/Reddirector/Orchestration_Engine/blob/main/LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/Reddirector/Orchestration_Engine.svg)](https://github.com/Reddirector/Orchestration_Engine/releases)

A fault-tolerant, dependency-aware workflow orchestration engine for Python. Define tasks, dependencies, retries, and timeouts declaratively; supply the logic for each task; the engine schedules, executes, retries, times out, cancels dependents of failures, and records every state transition.

## Quick Installation

```bash
pip install orchestration-engine
```

For optional YAML workflow loading support:
```bash
pip install "orchestration-engine[yaml]"
```

> [!TIP]
> **Modern Linux (PEP 668):** If installing on Ubuntu 23.04+, Debian 12+, or Fedora without a global pip environment, activate a virtual environment first:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install orchestration-engine
> ```

## Mission

Multi-step automation pipelines—such as AI agent workflows, ETL transformations, and distributed tool executions—frequently encounter transient network drops, rate limits, and unhandled worker crashes. 

**Orchestration Engine** is designed to provide robust, deterministic workflow management with:
- **Zero runtime dependencies**: Pure Python standard library implementation.
- **Durable persistence**: Append-only SQLite audit trail recording all state transitions.
- **Crash resumption**: Seamless resumption of interrupted runs without re-executing already-succeeded tasks.
- **Transparent concurrency**: Deterministic execution scaling via threads or spawned isolated processes.
- **Fail-safe isolation**: Faults in user task runners and lifecycle hooks never corrupt internal engine state.

## Core Features

- **Dependency-Aware Scheduling**: Tasks are scheduled as a Directed Acyclic Graph (DAG) and advance as soon as all upstream dependencies succeed.
- **Automatic Retries & Exponential Backoff**: Transient errors are retried according to a configurable `RetryPolicy` using exponential backoff: `delay_seconds * 2**(attempt_count - 1)`.
- **Per-Task Timeouts**: Asynchronously enforced deadlines abandon stalled threads or terminate spawned child worker processes.
- **Transitive Cancellation**: When a task fails permanently, all downstream dependents (direct and indirect) are cancelled to a fixpoint, while independent branches continue executing to completion.
- **Data Flow**: Tasks receive outputs from completed upstream dependencies via `task.inputs`, with automatic JSON serialization and persistence in SQLite Schema v2.
- **Lifecycle Hooks**: Non-blocking callbacks (`on_task_start`, `on_task_succeeded`, `on_task_failed`, `on_task_retry`, `on_workflow_done`) for monitoring and logging.
- **Developer Ergonomics**: Fluent `WorkflowBuilder` API, JSON and YAML workflow definitions, and a CLI tool (`orchestration-engine`).

## Production Use Cases

See the full [Use Cases Guide](use-cases.md) for architectural blueprints and complete implementations:
- **[Multi-Step AI Agent Pipelines](use-cases.md#1-multi-step-ai-agent-pipelines)**: LLM tool calling, retrieval, rate limit handling, and fan-in synthesis.
- **[RAG Ingestion & Vector Indexing](use-cases.md#2-rag-document-ingestion-vector-indexing)**: Document chunking, concurrent embedding generation, and quality verification gates.
- **[Automated Incident Triage & Remediation](use-cases.md#3-automated-incident-triage-remediation-devops-sre)**: Fan-out telemetry diagnostics, root-cause correlation, automated mitigation, and verification.
- **[Resilient ETL Pipelines](use-cases.md#4-resilient-etl-data-processing-pipelines)**: Fluent DAG construction, type-safe data passing, and transactional SQLite persistence.

## Design Philosophy

1. **Zero runtime dependencies**: Everything is implemented using the Python standard library (`sqlite3`, `multiprocessing`, `concurrent.futures`, `json`, `argparse`).
2. **Correctness over raw throughput**: Every state transition is written to SQLite before in-memory mutation occurs (write-ahead log).
3. **Small, cohesive internals**: Each internal module has one job (`scheduler`, `readiness`, `executor`, `transitions`, `runner`, `persistence`, `recovery`, `loader`, `builder`).
4. **Minimal, frozen public API**: Only explicitly approved symbols are exported in `__all__`.
