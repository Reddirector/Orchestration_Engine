import pytest
from regenbench.drift.classifier import DeterministicDriftClassifier


def test_classifier_d0():
    orig = {"order_id": "ord_1", "amount": 1000, "currency": "USD", "reference": "ref-1"}
    regen = {"order_id": "ord_1", "amount": 1000, "currency": "USD", "reference": "ref-1"}
    assert DeterministicDriftClassifier.classify(orig, regen) == "D0"


def test_classifier_d1():
    orig = {"order_id": "ord_1", "amount": 1000, "currency": "USD", "reference": "ref-1"}
    regen = {"order_id": "ord_1", "amount": 1000.0, "currency": "USD", "reference": "ref-1"}
    assert DeterministicDriftClassifier.classify(orig, regen) == "D1"


def test_classifier_d4():
    orig = {"order_id": "ord_1", "amount": 1000, "currency": "USD", "reference": "ref-1"}
    regen = {"order_id": "ord_1", "amount": 1000, "currency": "USD", "reference": "ref-2"}
    assert DeterministicDriftClassifier.classify(orig, regen) == "D4"


def test_classifier_different_intent():
    orig = {"order_id": "ord_1", "amount": 1000, "currency": "USD", "reference": "ref-1"}
    regen = {"order_id": "ord_1", "amount": 2000, "currency": "USD", "reference": "ref-1"}
    assert DeterministicDriftClassifier.classify(orig, regen) == "DIFFERENT_INTENT"
