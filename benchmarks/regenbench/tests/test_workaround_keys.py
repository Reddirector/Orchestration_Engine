from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.guards.call4agents_adapter import Call4AgentsAdapter
from regenbench.guards.idempotent_tools_adapter import IdempotentToolsAdapter


def test_workaround_keys_business_id_only(tmp_path):
    s1 = ScenarioGenerator.generate("S1", seed=0)
    orig = s1.target_step.args
    d1_mut = DriftMutator.mutate("D1", orig, seed=0)
    d4_mut = DriftMutator.mutate("D4", orig, seed=0)
    ctrl = s1.control_step.args

    # Check G1 workaround key logic
    g1 = Call4AgentsAdapter(use_workaround_key=True)
    g1.setup("run_test", tmp_path / "g1")
    k1_orig = g1.compute_key(s1.target_step.tool_name, (orig,), {})
    k1_d1 = g1.compute_key(s1.target_step.tool_name, (d1_mut,), {})
    k1_d4 = g1.compute_key(s1.target_step.tool_name, (d4_mut,), {})
    k1_ctrl = g1.compute_key(s1.control_step.tool_name, (ctrl,), {})

    assert k1_orig == orig["order_id"]
    assert k1_d1 == k1_orig
    assert k1_d4 == k1_orig
    assert k1_ctrl == ctrl["order_id"]
    assert k1_ctrl != k1_orig

    # Check G3b workaround key logic
    g3b = IdempotentToolsAdapter(mode="context")
    g3b.setup("run_test", tmp_path / "g3b")
    k3_orig = g3b.compute_key(s1.target_step.tool_name, (orig,), {})
    k3_d1 = g3b.compute_key(s1.target_step.tool_name, (d1_mut,), {})
    k3_d4 = g3b.compute_key(s1.target_step.tool_name, (d4_mut,), {})
    k3_ctrl = g3b.compute_key(s1.control_step.tool_name, (ctrl,), {})

    assert k3_orig == orig["order_id"]
    assert k3_d1 == k3_orig
    assert k3_d4 == k3_orig
    assert k3_ctrl == ctrl["order_id"]
    assert k3_ctrl != k3_orig
