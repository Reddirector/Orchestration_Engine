import pytest
from pathlib import Path
from regenbench.guards.g8_engine import G8EngineGuard


def test_g8_engine_executes_and_deduplicates(tmp_path: Path):
    guard1 = G8EngineGuard()
    guard1.setup(run_id="run_test_1", workdir=tmp_path)

    calls = []

    def sample_tool(val: int):
        calls.append(val)
        return {"result": val * 2}

    wrapped1 = guard1.wrap("sample_tool", sample_tool)
    out1 = wrapped1(val=10)
    assert out1 == {"result": 20}
    assert calls == [10]

    # Worker 2 resumes the run
    guard2 = G8EngineGuard()
    guard2.setup(run_id="run_test_1", workdir=tmp_path)
    guard2.on_resume(run_id="run_test_1")

    # Drifted args to the same step
    wrapped2 = guard2.wrap("sample_tool", sample_tool)
    out2 = wrapped2(val=15)
    # Must return deduplicated result without calling sample_tool again
    assert out2 == {"result": 20}
    assert calls == [10]

    # Control action (second step) executes successfully
    ctrl_tool = guard2.wrap("ctrl_tool", lambda msg: f"ok:{msg}")
    ctrl_out = ctrl_tool(msg="hello")
    assert ctrl_out == "ok:hello"
