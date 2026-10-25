# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability within `orchestration-engine`, please do **not** open a public issue. Instead, report it privately to the repository owner via GitHub Security Advisories or by contacting `aditya@reddirector.com`.

All reports will be acknowledged within 48 hours, and a security fix or advisory will be issued promptly.

---

## Threat Model and Trust Boundaries

### 1. Runner Trust Model (`--runner module:function`)
- When using the CLI `--runner` flag or passing callables to `run_workflow`, the engine dynamically imports and executes Python code in the host process environment.
- The current working directory (`os.getcwd()`) is prepended to `sys.path` to permit resolving user workflow runner scripts.
- **Trust Boundary**: Executing a workflow with `--runner` has the **same trust level as running an arbitrary Python script**. Operators must only invoke workflows and runners from trusted sources.

### 2. Workflow Definitions (JSON & YAML)
- Workflow definitions are parsed strictly:
  - JSON definitions are parsed with standard `json.loads` and validated against the formal schema `workflow.schema.json`.
  - YAML definitions require the optional extra (`orchestration-engine[yaml]`) and are loaded exclusively with `yaml.safe_load`. Arbitrary Python object instantiation via YAML tags is strictly prohibited.
- **Resource Exhaustion Limits**:
  - Maximum workflow definition file size: **10 MB** (`MAX_WORKFLOW_FILE_SIZE`).
  - Maximum tasks per workflow: **5,000** (`MAX_TASKS_PER_WORKFLOW`).
  - Maximum dependencies per task: **500** (`MAX_DEPENDENCIES_PER_TASK`).

### 3. Database & SQL Injection Defenses
- All queries across all engine subsystems use parameterized statements (`?` placeholders).
- Zero SQL statements utilize string concatenation, string interpolation, or f-strings.
- Foreign keys are enforced (`PRAGMA foreign_keys = ON`), and write-ahead locking (`PRAGMA journal_mode = WAL`) guarantees concurrency safety under a single-writer architecture.

### 4. Serialization & Inter-Process Communication (IPC)
- **Database Persistence**: State transitions, task outputs, and workflow metadata stored in SQLite are serialized strictly as standard JSON (`json.dumps`/`json.loads`).
- **Process Backend**: The standard library `multiprocessing` module is used with the `spawn` context. `pickle` is used solely for inter-process communication over unidirectional OS pipes between the parent coordinator and spawned worker processes.

### 5. Supply Chain & Dependencies
- Core runtime dependencies: **0** (pure Python standard library).
- Optional extras (`pyyaml`, `mkdocs`) are strictly optional and isolated from the core scheduling engine.
