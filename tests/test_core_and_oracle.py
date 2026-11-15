import sqlite3
from pathlib import Path

import pytest

from regenbench.core.ledger import EffectLedger
from regenbench.core.outcomes import ControlOutcome, OutcomeOracle, TargetOutcome
from regenbench.core.scenario import ScenarioGenerator


def test_ledger_append_and_query(tmp_path: Path):
    db_file = tmp_path / "ledger.db"
    ledger = EffectLedger(db_file)

    assert ledger.count_effects("intent-1") == 0

    r1 = ledger.record_effect(
        intent_id="intent-1",
        service="payments",
        action="charge",
        payload={"amount": 1000},
        idempotency_key="key-123",
    )
    assert r1.id == 1
    assert r1.intent_id == "intent-1"
    assert ledger.count_effects("intent-1") == 1

    r2 = ledger.record_effect(
        intent_id="intent-1",
        service="payments",
        action="charge",
        payload={"amount": 1000},
    )
    assert r2.id == 2
    assert ledger.count_effects("intent-1") == 2

    effects = ledger.get_effects_for_intent("intent-1")
    assert len(effects) == 2
    assert effects[0].idempotency_key == "key-123"
    assert effects[1].idempotency_key is None


def test_oracle_outcome_ok(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger.db")
    ledger.record_effect("target-1", "payments", "charge", {"amount": 100})
    ledger.record_effect("ctrl-1", "payments", "charge", {"amount": 100})

    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id="ctrl-1",
        halted=False,
    )
    assert res.target_outcome == TargetOutcome.OK
    assert res.control_outcome == ControlOutcome.OK
    assert res.is_safe is True
    assert res.is_autonomous is True


def test_oracle_outcome_dup(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger.db")
    ledger.record_effect("target-1", "payments", "charge", {"amount": 100})
    ledger.record_effect("target-1", "payments", "charge", {"amount": "100.00"})
    ledger.record_effect("ctrl-1", "payments", "charge", {"amount": 100})

    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id="ctrl-1",
        halted=False,
    )
    assert res.target_outcome == TargetOutcome.DUP
    assert res.control_outcome == ControlOutcome.OK
    assert res.is_safe is False
    assert res.is_autonomous is False


def test_oracle_outcome_lost(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger.db")
    ledger.record_effect("ctrl-1", "payments", "charge", {"amount": 100})

    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id="ctrl-1",
        halted=False,
    )
    assert res.target_outcome == TargetOutcome.LOST
    assert res.control_outcome == ControlOutcome.OK
    assert res.is_safe is False
    assert res.is_autonomous is False


def test_oracle_outcome_halt_safe(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger.db")
    ledger.record_effect("target-1", "payments", "charge", {"amount": 100})
    ledger.record_effect("ctrl-1", "payments", "charge", {"amount": 100})

    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id="ctrl-1",
        halted=True,
    )
    assert res.target_outcome == TargetOutcome.HALT_SAFE
    assert res.control_outcome == ControlOutcome.OK
    assert res.is_safe is True
    assert res.is_autonomous is False


def test_oracle_outcome_halt_stall(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger.db")
    # 0 commits for target, halted for human
    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id=None,
        halted=True,
    )
    assert res.target_outcome == TargetOutcome.HALT_STALL
    assert res.is_safe is True
    assert res.is_autonomous is False


def test_oracle_control_false_block(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger.db")
    ledger.record_effect("target-1", "payments", "charge", {"amount": 100})
    # control intent was never committed

    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id="ctrl-1",
        halted=False,
    )
    assert res.target_outcome == TargetOutcome.OK
    assert res.control_outcome == ControlOutcome.FALSE_BLOCK
    assert res.is_autonomous is False


def test_scenario_generator_determinism():
    s1_a = ScenarioGenerator.generate("S1", seed=42)
    s1_b = ScenarioGenerator.generate("S1", seed=42)
    assert s1_a.target_step.args == s1_b.target_step.args
    assert s1_a.target_step.intent.intent_id == s1_b.target_step.intent.intent_id

    s2 = ScenarioGenerator.generate("S2", seed=99)
    assert s2.target_step.tool_name == "send_email"
    assert s2.target_step.intent.scenario_id == "S2"

    s3 = ScenarioGenerator.generate("S3", seed=123)
    assert s3.target_step.tool_name == "create_ticket"
    assert s3.target_step.intent.scenario_id == "S3"


def test_ledger_append_only_enforced_by_trigger(tmp_path: Path):
    db_file = tmp_path / "ledger_triggers.db"
    ledger = EffectLedger(db_file)

    # Check journal_mode is WAL
    with ledger._get_connection() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    r1 = ledger.record_effect("intent-1", "payments", "charge", {"amount": 100})
    assert ledger.count_effects("intent-1") == 1

    # Attempt UPDATE
    with pytest.raises(sqlite3.DatabaseError), ledger._get_connection() as conn:
        conn.execute("UPDATE effects SET action = 'hacked' WHERE id = ?", (r1.id,))

    # Attempt DELETE
    with pytest.raises(sqlite3.DatabaseError), ledger._get_connection() as conn:
        conn.execute("DELETE FROM effects WHERE id = ?", (r1.id,))

    # Row count unchanged
    assert ledger.count_effects("intent-1") == 1


def test_oracle_dup_stays_dup_when_halted(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger_dup_halt.db")
    ledger.record_effect("target-1", "payments", "charge", {"amount": 100})
    ledger.record_effect("target-1", "payments", "charge", {"amount": 200})

    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id=None,
        halted=True,
    )
    assert res.target_outcome == TargetOutcome.DUP
    assert res.is_safe is False


def test_oracle_control_action_two_commits_is_ok(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger_ctrl_two.db")
    ledger.record_effect("target-1", "payments", "charge", {"amount": 100})
    ledger.record_effect("ctrl-1", "payments", "charge", {"amount": 100})
    ledger.record_effect("ctrl-1", "payments", "charge", {"amount": 100})

    res = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="target-1",
        control_intent_id="ctrl-1",
        halted=False,
    )
    assert res.target_outcome == TargetOutcome.OK
    assert res.control_outcome == ControlOutcome.OK
    assert res.control_commits == 2
    assert res.is_autonomous is True


def test_scenario_distinct_arguments_across_300_seeds():
    for scenario_id in ["S1", "S2", "S3"]:
        seen_args = set()
        for seed in range(300):
            sc = ScenarioGenerator.generate(scenario_id, seed=seed)
            # Serialize target step args
            args_key = tuple(sorted((k, str(v)) for k, v in sc.target_step.args.items()))
            seen_args.add(args_key)
        assert len(seen_args) >= 250, (
            f"{scenario_id} produced only {len(seen_args)} distinct arg sets across 300 seeds"
        )
