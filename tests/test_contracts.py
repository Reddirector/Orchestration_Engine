"""Tests for Data Contracts and Output Validation."""

from __future__ import annotations

import pytest

from orchestration_engine.contracts import (
    ContractValidationError,
    DataContract,
    Field,
    enforce_contract,
)


def test_contract_valid_payload() -> None:
    contract = DataContract(
        {
            "user_id": Field(type=str, min_len=3, regex=r"^usr_"),
            "score": Field(type=(int, float), min_val=0.0, max_val=100.0),
            "tier": Field(type=str, choices={"free", "pro", "enterprise"}),
            "tags": Field(type=list, required=False),
        },
        name="UserSchema",
    )

    valid_data = {
        "user_id": "usr_99",
        "score": 95.5,
        "tier": "pro",
        "tags": ["vip", "beta"],
    }
    is_valid, errors = contract.validate(valid_data)
    assert is_valid is True
    assert errors == []

    # enforce should return data cleanly
    enforced = contract.enforce(valid_data)
    assert enforced["user_id"] == "usr_99"


def test_contract_missing_required_and_type_mismatch() -> None:
    contract = DataContract(
        {
            "id": Field(type=int, required=True),
            "email": Field(type=str, required=True),
        },
        name="Account",
    )

    # Missing email, wrong id type
    data = {"id": "not_an_int"}
    is_valid, errors = contract.validate(data)
    assert is_valid is False
    assert len(errors) == 2
    assert any("expected type int" in err for err in errors)
    assert any("Missing required field 'email'" in err for err in errors)

    with pytest.raises(ContractValidationError) as exc_info:
        contract.enforce(data)
    assert "validation failed" in str(exc_info.value)
    assert len(exc_info.value.errors) == 2


def test_contract_bounds_and_regex() -> None:
    contract = DataContract(
        {
            "age": Field(type=int, min_val=18, max_val=120),
            "sku": Field(type=str, regex=r"^SKU-[0-9]{4}$"),
            "status": Field(choices={"active", "paused"}),
        }
    )

    bad_data = {
        "age": 15,
        "sku": "BAD-SKU",
        "status": "deleted",
    }
    is_valid, errors = contract.validate(bad_data)
    assert is_valid is False
    assert len(errors) == 3
    assert any("below minimum 18" in err for err in errors)
    assert any("does not match pattern" in err for err in errors)
    assert any("not in allowed choices" in err for err in errors)


def test_contract_disallow_extra_fields() -> None:
    contract = DataContract(
        {"a": Field(type=int)},
        allow_extra=False,
    )
    is_valid, errors = contract.validate({"a": 1, "b": 2})
    assert is_valid is False
    assert any("Unexpected extra field 'b'" in err for err in errors)


def test_enforce_contract_decorator() -> None:
    in_contract = DataContract({"x": Field(type=int), "y": Field(type=int)})
    out_contract = DataContract({"sum": Field(type=int, min_val=0)})

    @enforce_contract(input_contract=in_contract, output_contract=out_contract)
    def compute_sum(payload: dict[str, int]) -> dict[str, int]:
        return {"sum": payload["x"] + payload["y"]}

    # Valid invocation
    res = compute_sum({"x": 10, "y": 20})
    assert res == {"sum": 30}

    # Invalid input
    with pytest.raises(ContractValidationError):
        compute_sum({"x": "invalid", "y": 20})  # type: ignore[dict-item]

    # Invalid output simulation
    @enforce_contract(output_contract=out_contract)
    def broken_output() -> dict[str, int]:
        return {"sum": -5}

    with pytest.raises(ContractValidationError) as exc_info:
        broken_output()
    assert "below minimum 0" in str(exc_info.value)
