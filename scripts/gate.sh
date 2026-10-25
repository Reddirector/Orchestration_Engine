#!/usr/bin/env bash
set -euo pipefail

echo "=== 1. Checking Ruff ==="
uv run ruff check

echo "=== 2. Checking Mypy ==="
uv run mypy

echo "=== 3. Running Pytest with Coverage ==="
uv run pytest --cov=orchestration_engine --cov-fail-under=90 -q

echo "=== 4. Building Wheel ==="
uv build

echo "=== 5. Testing Fresh Venv Wheel Installation & Exports ==="
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT
SMOKE_VENV="$TEMP_DIR/venv"
uv venv "$SMOKE_VENV" -q
WHEEL=$(ls -t dist/*.whl | head -n 1)
uv pip install --python "$SMOKE_VENV/bin/python" "$WHEEL" -q

"$SMOKE_VENV/bin/python" -c "
import orchestration_engine as oe
for name in oe.__all__:
    assert hasattr(oe, name), f'Missing {name}'
print(f'All {len(oe.__all__)} exports successfully imported from wheel')
"

echo "=== 6. Running Examples Against Installed Wheel ==="
for example in examples/*.py; do
    echo "Running $example..."
    "$SMOKE_VENV/bin/python" "$example"
done

echo "=== 7. Checking Clean Working Tree ==="
STRAY=$(git status --porcelain | grep -E "orchestration\.db" || true)
if [ -n "$STRAY" ]; then
    echo "Error: stray database file detected:"
    echo "$STRAY"
    exit 1
fi

echo "=== Quality Gate Passed Successfully! ==="
