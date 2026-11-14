from pathlib import Path
import pytest
from regenbench.core.outcomes import TargetOutcome, ControlOutcome
from regenbench.harness.runner import TrialRunner


def test_runner_g0_reproduces_dup_on_crashes(tmp_path: Path):
    results_file = tmp_path / "results.jsonl"
    runner = TrialRunner(results_path=results_file)

    # CP-A: Killed before service call committed -> 0 commits before kill, 1 commit on resume -> OK (target committed exactly 1 time)
    res_a = runner.run_trial("S1", "G0", "CP-A", "D0", seed=42, workdir=tmp_path / "trial_a")
    assert res_a.target_outcome == TargetOutcome.OK
    assert res_a.target_commits == 1

    # CP-B1: Service committed effect, socket closed -> 1 commit in worker 1, 1 commit on resume in worker 2 -> DUP
    res_b1 = runner.run_trial("S1", "G0", "CP-B1", "D0", seed=42, workdir=tmp_path / "trial_b1")
    assert res_b1.target_outcome == TargetOutcome.DUP
    assert res_b1.target_commits == 2

    # CP-B2: Hard process kill after commit -> 1 commit in worker 1, 1 commit on resume in worker 2 -> DUP
    res_b2 = runner.run_trial("S1", "G0", "CP-B2", "D0", seed=42, workdir=tmp_path / "trial_b2")
    assert res_b2.target_outcome == TargetOutcome.DUP
    assert res_b2.target_commits == 2

    # CP-C: Response received, killed before guard saves -> DUP
    res_c = runner.run_trial("S1", "G0", "CP-C", "D0", seed=42, workdir=tmp_path / "trial_c")
    assert res_c.target_outcome == TargetOutcome.DUP
    assert res_c.target_commits == 2

    # CP-D: Guard saved, killed before checkpoint -> DUP for G0
    res_d = runner.run_trial("S1", "G0", "CP-D", "D0", seed=42, workdir=tmp_path / "trial_d")
    assert res_d.target_outcome == TargetOutcome.DUP
    assert res_d.target_commits == 2


def test_runner_call4agents_prevents_dup_on_d0(tmp_path: Path):
    runner = TrialRunner(results_path=tmp_path / "results.jsonl")

    # With call4agents (G1) on D0 (identical arguments), CP-B2 resume should be deduplicated (OK)
    res_g1_d0 = runner.run_trial("S1", "G1", "CP-B2", "D0", seed=10, workdir=tmp_path / "trial_g1_d0")
    assert res_g1_d0.target_outcome == TargetOutcome.OK
    assert res_g1_d0.target_commits == 1


def test_runner_call4agents_leaks_on_d1_numeric_drift(tmp_path: Path):
    runner = TrialRunner(results_path=tmp_path / "results.jsonl")

    # With call4agents (G1) on D1 (numeric drift 10 -> 10.0), keying on exact args leaks a duplicate!
    res_g1_d1 = runner.run_trial("S1", "G1", "CP-B2", "D1", seed=10, workdir=tmp_path / "trial_g1_d1")
    assert res_g1_d1.target_outcome == TargetOutcome.DUP
    assert res_g1_d1.target_commits == 2

def test_runner_all_phase3_guards_d0_and_d1(tmp_path: Path):
    runner = TrialRunner(results_path=tmp_path / "results_phase3.jsonl")

    # G2 (agentraas default) on D0 deduplicates -> OK
    r_g2_d0 = runner.run_trial("S1", "G2", "CP-B2", "D0", seed=20, workdir=tmp_path / "t_g2_d0")
    assert r_g2_d0.target_outcome == TargetOutcome.OK
    assert r_g2_d0.target_commits == 1

    # G2 on D1 leaks duplicate -> DUP
    r_g2_d1 = runner.run_trial("S1", "G2", "CP-B2", "D1", seed=20, workdir=tmp_path / "t_g2_d1")
    assert r_g2_d1.target_outcome == TargetOutcome.DUP
    assert r_g2_d1.target_commits == 2

    # G3a (idempotent-tools default) on D0 deduplicates -> OK
    r_g3a_d0 = runner.run_trial("S1", "G3a", "CP-B2", "D0", seed=30, workdir=tmp_path / "t_g3a_d0")
    assert r_g3a_d0.target_outcome == TargetOutcome.OK

    # G3a on D1 leaks duplicate -> DUP
    r_g3a_d1 = runner.run_trial("S1", "G3a", "CP-B2", "D1", seed=30, workdir=tmp_path / "t_g3a_d1")
    assert r_g3a_d1.target_outcome == TargetOutcome.DUP

    # G5 (StepKey) on D1 survives numeric drift -> OK
    r_g5_d1 = runner.run_trial("S1", "G5", "CP-B2", "D1", seed=40, workdir=tmp_path / "t_g5_d1")
    assert r_g5_d1.target_outcome == TargetOutcome.OK
    assert r_g5_d1.target_commits == 1
