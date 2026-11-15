from pathlib import Path
from regenbench.core.ledger import EffectLedger
from regenbench.core.outcomes import OutcomeOracle, TargetOutcome


def test_ledger_records_and_counts_requests(tmp_path: Path):
    db_path = tmp_path / "ledger.sqlite"
    ledger = EffectLedger(db_path)

    ledger.record_request("intent-1", phase="w1")
    ledger.record_request("intent-1", phase="w2")
    ledger.record_request("intent-2", phase="w1")

    assert ledger.count_requests("intent-1", phase="w1") == 1
    assert ledger.count_requests("intent-1", phase="w2") == 1
    assert ledger.count_requests("intent-2", phase="w1") == 1
    assert ledger.count_requests("intent-2", phase="w2") == 0


def test_oracle_classification_includes_request_counts(tmp_path: Path):
    db_path = tmp_path / "ledger.sqlite"
    ledger = EffectLedger(db_path)
    ledger.record_request("intent-1", phase="w1")

    classification = OutcomeOracle.classify(
        ledger=ledger,
        target_intent_id="intent-1",
        requests_w1=1,
        requests_w2=0,
        task_runner_invocations_w2=0,
    )
    assert classification.requests_w1 == 1
    assert classification.requests_w2 == 0
    assert classification.task_runner_invocations_w2 == 0
