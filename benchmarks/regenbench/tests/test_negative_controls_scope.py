import pytest
from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator


@pytest.mark.parametrize("sc", ["S1", "S2", "S3"])
def test_n1_changes_business_fields(sc: str):
    orig = ScenarioGenerator.generate(sc, seed=42).target_step.args
    n1 = DriftMutator.mutate("N1", orig, seed=42)

    assert DriftMutator.is_mutated(orig, n1)
    if sc == "S1":
        assert n1["amount"] != orig["amount"]
    elif sc == "S2":
        assert n1["to"] != orig["to"]
    elif sc == "S3":
        assert n1["customer_id"] != orig["customer_id"]


@pytest.mark.parametrize("sc", ["S1", "S2", "S3"])
def test_n2_changes_business_fields(sc: str):
    orig = ScenarioGenerator.generate(sc, seed=42).target_step.args
    n2 = DriftMutator.mutate("N2", orig, seed=42)

    assert DriftMutator.is_mutated(orig, n2)
    if sc == "S1":
        assert n2.get("order_id") != orig.get("order_id") or n2.get("amount") != orig.get("amount")
    elif sc == "S2":
        assert n2["to"] != orig["to"]
    elif sc == "S3":
        assert n2["customer_id"] != orig["customer_id"]


@pytest.mark.parametrize("sc", ["S1", "S2", "S3"])
def test_n3_is_identical_args(sc: str):
    orig = ScenarioGenerator.generate(sc, seed=42).target_step.args
    n3 = DriftMutator.mutate("N3", orig, seed=42)
    assert orig == n3
