from hypothesis import given
from hypothesis import strategies as st

from regenbench.drift.mutators import DriftMutator


def test_is_mutated_detects_numeric_float_type_change():
    orig = {"order_id": "ord_1", "amount": 1000}
    mut = {"order_id": "ord_1", "amount": 1000.0}
    # Python equality considers 1000 == 1000.0, but json serialization detects drift
    assert orig == mut
    assert DriftMutator.is_mutated(orig, mut) is True


def test_d0_none():
    args = {"amount": 100, "user": "alice@example.com"}
    mutated = DriftMutator.mutate("D0", args, seed=42)
    assert mutated == args


def test_d1_numeric_format():
    args = {"order_id": "ord_1", "amount": 1000}
    m1 = DriftMutator.mutate("D1", args, seed=1)
    # Mutates integer to float or formatted string representation
    assert m1["order_id"] == "ord_1"
    assert m1["amount"] in (1000.0, "1000", "1000.00", "$1000")


def test_d2_structure_noise():
    args = {"b": 2, "a": 1, "c": 3}
    m2 = DriftMutator.mutate("D2", args, seed=2)
    # Extra optional field with default or shuffled keys
    assert m2["a"] == 1 and m2["b"] == 2 and m2["c"] == 3


def test_d2a_key_reorder_only():
    args = {"order_id": "ord_1", "amount": 1000, "currency": "USD"}
    m2a = DriftMutator.mutate("D2a", args, seed=1)
    # Keys reordered, but same key-value pairs
    assert list(m2a.keys()) != list(args.keys())
    assert m2a == args


def test_d2b_string_padding():
    args = {"order_id": "ord_1", "subject": "Invoice #100", "body": "Please pay"}
    m2b = DriftMutator.mutate("D2b", args, seed=1)
    # String padding introduced into text fields
    assert m2b["order_id"] == "ord_1"
    assert m2b["subject"] != args["subject"] or m2b["body"] != args["body"]
    assert m2b["subject"].strip() == args["subject"].strip()



def test_d3_free_text_paraphrase():
    args = {"to": "alice@example.com", "subject": "Invoice #123", "body": "Please find attached."}
    m3 = DriftMutator.mutate("D3", args, seed=3)
    assert m3["to"] == "alice@example.com"
    assert m3["subject"] != args["subject"] or m3["body"] != args["body"]


def test_d4_volatile_fields():
    args = {"order_id": "ord_1", "reference": "ref-pay-123"}
    m4 = DriftMutator.mutate("D4", args, seed=4)
    assert m4["order_id"] == "ord_1"
    assert m4["reference"] != args["reference"]


def test_d5_encoding_aliases():
    args = {"to": "Customer@Example.COM", "currency": "usd"}
    m5 = DriftMutator.mutate("D5", args, seed=5)
    assert m5["to"].lower() == "customer@example.com"


def test_n1_negative_control_different_amount():
    args = {"order_id": "ord_1", "amount": 1000}
    n1 = DriftMutator.mutate("N1", args, seed=1)
    assert n1["order_id"] == "ord_1"
    assert n1["amount"] != 1000


def test_n2_negative_control_different_recipient():
    args = {"to": "alice@example.com", "subject": "Hello"}
    n2 = DriftMutator.mutate("N2", args, seed=2)
    assert n2["to"] != "alice@example.com"


def test_n3_negative_control_explicit_second_request():
    args = {"order_id": "ord_1", "amount": 1000}
    n3 = DriftMutator.mutate("N3", args, seed=3)
    # N3 by design identical payload but distinct intent context
    assert n3 == args


# Hypothesis Property-based tests
@given(st.integers(min_value=1, max_value=100000), st.integers(min_value=0, max_value=10000))
def test_hypothesis_d1_d5_preserves_intent_identity(amount, seed):
    args = {
        "order_id": "ord_hypo_1",
        "amount": amount,
        "currency": "USD",
        "reference": "ref-1",
        "to": "user@example.com",
    }
    for d_type in ["D0", "D1", "D2", "D4", "D5"]:
        mutated = DriftMutator.mutate(d_type, args, seed=seed)
        # Core business identity order_id is preserved
        assert mutated["order_id"] == args["order_id"]


@given(st.integers(min_value=1, max_value=100000), st.integers(min_value=0, max_value=10000))
def test_hypothesis_negatives_change_business_identity(amount, seed):
    args = {
        "order_id": "ord_hypo_2",
        "amount": amount,
        "currency": "USD",
        "to": "user@example.com",
    }
    n1 = DriftMutator.mutate("N1", args, seed=seed)
    assert n1["amount"] != args["amount"]

    n2 = DriftMutator.mutate("N2", args, seed=seed)
    assert n2["to"] != args["to"]
