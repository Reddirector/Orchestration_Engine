import pytest
from regenbench.harness.runner import TrialRunner


def test_cp_a_d0_must_report_halted_for_in_doubt_guards():
    runner = TrialRunner()
    for guard in ["G1", "G2", "G3a"]:
        res = runner.run_trial("S1", guard, "CP-A", "D0", seed=42)
        assert res.halted_for_human is True, f"{guard} at CP-A D0 did not report halted_for_human=True"
