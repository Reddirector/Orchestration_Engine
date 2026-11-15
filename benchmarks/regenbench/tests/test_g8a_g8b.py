import pytest
from pathlib import Path
from regenbench.guards.g8_engine import G8aGuard, G8bGuard, default_key_func


def test_default_key_func_deterministic():
    args1 = {"order_id": "ord_1", "amount": 100}
    args2 = {"amount": 100, "order_id": "ord_1"}
    args3 = {"order_id": "ord_1", "amount": 100.0}

    k1 = default_key_func("charge_card", args1)
    k2 = default_key_func("charge_card", args2)
    k3 = default_key_func("charge_card", args3)

    assert k1 == k2
    assert k1 != k3


def test_g8a_guard_definition():
    g = G8aGuard()
    assert g.name == "G8a_orchestration_engine"


def test_g8b_guard_definition():
    g = G8bGuard()
    assert g.name == "G8b_orchestration_engine"
