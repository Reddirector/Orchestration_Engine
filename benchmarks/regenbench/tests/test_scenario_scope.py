from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator

def test_scenario_drift_scope_active_and_na_cells():
    """Formally defines which (scenario, drift) cells are active vs n/a."""
    scope = {
        "D1": {"active": ["S1"], "na": ["S2", "S3"]},
        "D2": {"active": ["S1", "S2", "S3"], "na": []},
        "D3": {"active": ["S2", "S3"], "na": ["S1"]},
        "D4": {"active": ["S1", "S3"], "na": ["S2"]},
        "D5": {"active": ["S2"], "na": ["S1", "S3"]},
    }
    for drift, spec in scope.items():
        for sc_id in spec["active"]:
            sc = ScenarioGenerator.generate(sc_id, seed=0)
            mut = DriftMutator.mutate(drift, sc.target_step.args, seed=0)
            assert DriftMutator.is_mutated(sc.target_step.args, mut) is True, f"{sc_id} {drift} should mutate"
        for sc_id in spec["na"]:
            sc = ScenarioGenerator.generate(sc_id, seed=0)
            mut = DriftMutator.mutate(drift, sc.target_step.args, seed=0)
            assert DriftMutator.is_mutated(sc.target_step.args, mut) is False, f"{sc_id} {drift} should be n/a (no-op)"
