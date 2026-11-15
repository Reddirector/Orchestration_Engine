import pytest
from regenbench.guards.intentguard.normalize import normalize_declared_args
from regenbench.guards.analyzer import SemanticAnalyzerGuard
from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from pathlib import Path


def test_g4_normalizes_d6_compound_envelope():
    scenario = ScenarioGenerator.generate("S1", seed=0)
    orig_args = scenario.target_step.args
    d6_args = DriftMutator.mutate("D6", orig_args, seed=0)
    
    norm_orig = normalize_declared_args("charge_card", orig_args)
    norm_d6 = normalize_declared_args("charge_card", d6_args)
    
    # D6 preserves business intent fields; normalization must unwrap compound envelope
    assert norm_d6 == norm_orig


def test_g7_matches_d6_compound_envelope(tmp_path: Path):
    scenario = ScenarioGenerator.generate("S1", seed=0)
    orig_args = scenario.target_step.args
    d6_args = DriftMutator.mutate("D6", orig_args, seed=0)
    
    guard = SemanticAnalyzerGuard()
    guard.setup(run_id="test_run", workdir=tmp_path)
    
    calls = []
    def dummy_tool(**kwargs):
        calls.append(kwargs)
        return {"status": "success"}
    
    wrapped = guard.wrap("charge_card", dummy_tool)
    res1 = wrapped(**orig_args)
    assert calls == [orig_args]
    
    # Resume on same run
    guard.on_resume("test_run")
    wrapped2 = guard.wrap("charge_card", dummy_tool)
    res2 = wrapped2(**d6_args)
    
    # Must deduplicate without second call
    assert len(calls) == 1
    assert res2.get("status") in ("success", "deduplicated_by_analyzer")
