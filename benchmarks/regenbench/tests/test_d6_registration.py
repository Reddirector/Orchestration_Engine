import pytest
from regenbench.drift.mutators import DriftMutator


def test_d6_registered_in_drift_mutator():
    orig_args = {"order_id": "ord_123", "amount": 1000, "currency": "USD"}
    mutated = DriftMutator.mutate("D6", orig_args, seed=42)
    assert "batch" in mutated
    assert mutated["operation"] == "bulk_commit"
    assert DriftMutator.is_mutated(orig_args, mutated) is True
