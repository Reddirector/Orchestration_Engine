# Versioning, Public API & Deprecation Policy

## 1. Semantic Versioning

`orchestration-engine` strictly adheres to [Semantic Versioning 2.0.0](https://semver.org/):

$$\text{MAJOR}.\text{MINOR}.\text{PATCH}$$

- **PATCH (`1.0.x`)**: Backwards-compatible bug fixes, documentation enhancements, and internal performance optimizations. No API changes.
- **MINOR (`1.x.0`)**: Backwards-compatible feature additions, additive schema migrations, and formal deprecation announcements.
- **MAJOR (`x.0.0`)**: Breaking API changes, backward-incompatible schema shifts, or removal of previously deprecated interfaces.

---

## 2. Definition of Public API

Only symbols explicitly declared in `orchestration_engine.__all__` and the CLI interface documented in `docs/cli.md` constitute the public contract:

### Public Symbols (`orchestration_engine.__all__`)
- **Core Models**: `Task`, `Workflow`, `RetryPolicy`, `TaskResult`, `Hooks`, `TaskState`, `WorkflowStatus`
- **Execution & Persistence**: `run_workflow`, `run_workflow_from_file`, `resume_run`, `get_connection`, `get_run_status`, `get_run_history`, `get_workflow_status`, `get_workflow_history`, `list_runs`
- **Builder & Loaders**: `WorkflowBuilder`, `workflow_to_dict`, `load_workflow_from_json`, `load_workflow_from_yaml`
- **Exceptions**: `OrchestrationError`, `WorkflowDefinitionError`, `WorkflowValidationError`, `PersistenceError`
- **Metadata**: `__version__`

> [!IMPORTANT]
> All other internal modules (`orchestration_engine.readiness`, `orchestration_engine.scheduler`, `orchestration_engine.transitions`, etc.) are private implementation details and are subject to change without notice.

---

## 3. Deprecation Policy

When an existing public interface, parameter, or behavior is superseded:
1. **Notice Period**: The interface will be marked deprecated for at least one full minor release cycle prior to any removal.
2. **Runtime Warning**: The interface will emit a Python `DeprecationWarning` to alert callers.
3. **Changelog**: Deprecations are highlighted prominently in `CHANGELOG.md` under a dedicated `### Deprecated` header.
4. **Removal**: Deprecated interfaces may only be removed in a subsequent `MAJOR` version release.

---

## 4. `task_states` Deprecation Status

In early releases (`v0.1.0`), `run_workflow` required callers to provide a mutable dictionary to track task execution states:

```python
run_workflow(workflow, task_states, time_source, task_runner, conn)
```

### Current Status
- Starting in `v0.3.0`, the internal engine was refactored to treat `Task.state` on the `Task` dataclass objects as the **single source of truth**.
- The `task_states` dictionary is automatically synchronized as a mirror for full backwards compatibility with legacy callers.
- Callers may safely pass an empty dictionary `{}` to `run_workflow`.

### Roadmap
- `task_states` remains accepted throughout all `1.x` releases without breaking existing code.
- In `2.0.0`, `task_states` will be made optional or deprecated in favor of reading states directly from `workflow.tasks`.
