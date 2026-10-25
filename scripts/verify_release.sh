#!/usr/bin/env bash
set -euo pipefail

echo "=== Release Verification Script ==="

# 1. Clean build directory and build wheel & sdist
echo "-> Building distributions with uv..."
rm -rf dist/
uv build --clear

WHEEL=$(ls dist/*.whl | head -n 1)
echo "-> Found built wheel: $WHEEL"

# 2. Create clean temporary virtual environment
TMP_DIR=$(mktemp -d -t oe-release-verify-XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "-> Creating fresh isolated virtual environment in $TMP_DIR..."
python3 -m venv "$TMP_DIR/venv"
PIP="$TMP_DIR/venv/bin/pip"
PYTHON="$TMP_DIR/venv/bin/python"
CLI="$TMP_DIR/venv/bin/orchestration-engine"

# 3. Install wheel and optional yaml dependency
echo "-> Installing wheel into isolated virtual environment..."
"$PIP" install --quiet "$WHEEL" pyyaml

# 4. Import all 25 public exports
echo "-> Verifying all public exports can be imported from installed wheel..."
"$PYTHON" -c "
import orchestration_engine as oe

expected = {
    'Task', 'Workflow', 'RetryPolicy', 'TaskState', 'WorkflowStatus',
    'run_workflow', 'run_workflow_from_file', 'load_workflow_from_json',
    'get_workflow_status', 'get_workflow_history', 'get_connection',
    'OrchestrationError', 'WorkflowDefinitionError', 'WorkflowValidationError',
    'PersistenceError', '__version__',
    'resume_run', 'get_run_status', 'get_run_history', 'list_runs',
    'TaskResult', 'Hooks', 'WorkflowBuilder', 'workflow_to_dict',
    'load_workflow_from_yaml',
}

actual = set(oe.__all__)
assert actual == expected, f'Export mismatch: {actual ^ expected}'
for name in oe.__all__:
    getattr(oe, name)
print(f'Successfully imported all {len(oe.__all__)} symbols from version {oe.__version__}')
"

# 5. Run every example script against the installed wheel
echo "-> Running all examples against installed wheel..."
for example in examples/*.py; do
    echo "   Running $example..."
    "$PYTHON" "$example" > /dev/null
done

# 6. Verify CLI subcommands
echo "-> Verifying CLI subcommands with installed wheel..."
DB_PATH="$TMP_DIR/test_run.db"

"$CLI" --help > /dev/null
"$CLI" validate examples/simple_workflow.json > /dev/null
"$CLI" run examples/simple_workflow.json --runner examples.runners:run --db "$DB_PATH" --run-id "verify-run-1" > /dev/null
"$CLI" status verify-run-1 --db "$DB_PATH" > /dev/null
"$CLI" history verify-run-1 --db "$DB_PATH" > /dev/null
"$CLI" runs --db "$DB_PATH" > /dev/null

echo "=== Release Verification Passed Successfully! ==="
