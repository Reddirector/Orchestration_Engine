"""Runtime Data Contracts and Schema Validation.

Provides zero-dependency, type-safe schema and contract enforcement for task inputs
and outputs. Ensures downstream tasks never crash unexpectedly due to missing fields,
invalid types, or malformed data shapes.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from orchestration_engine.errors import OrchestrationError

F = TypeVar("F", bound=Callable[..., Any])


class ContractValidationError(OrchestrationError):
    """Raised when a data payload violates a declared DataContract."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


@dataclass(frozen=True)
class Field:
    """Specification for a single field in a DataContract."""

    type: type | tuple[type, ...] | None = None
    required: bool = True
    default: Any = None
    min_val: float | None = None
    max_val: float | None = None
    min_len: int | None = None
    max_len: int | None = None
    regex: str | None = None
    choices: set[Any] | None = None
    description: str | None = None

    def validate_value(self, field_name: str, value: Any) -> list[str]:
        """Validate a single value against this field's constraints."""
        errors: list[str] = []

        if value is None:
            if self.required:
                errors.append(f"Field '{field_name}' is required but was None or missing.")
            return errors

        # Type checking
        if self.type is not None:
            if not isinstance(value, self.type):
                expected = (
                    tuple(t.__name__ for t in self.type)
                    if isinstance(self.type, tuple)
                    else self.type.__name__
                )
                actual = type(value).__name__
                errors.append(
                    f"Field '{field_name}' expected type {expected}, got {actual}."
                )
                return errors

        # Value bounds (int/float)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.min_val is not None and value < self.min_val:
                errors.append(
                    f"Field '{field_name}' value {value} is below minimum {self.min_val}."
                )
            if self.max_val is not None and value > self.max_val:
                errors.append(
                    f"Field '{field_name}' value {value} exceeds maximum {self.max_val}."
                )

        # Length bounds (str, list, dict, set, tuple)
        if hasattr(value, "__len__"):
            v_len = len(value)
            if self.min_len is not None and v_len < self.min_len:
                errors.append(
                    f"Field '{field_name}' length {v_len} is shorter than minimum {self.min_len}."
                )
            if self.max_len is not None and v_len > self.max_len:
                errors.append(
                    f"Field '{field_name}' length {v_len} exceeds maximum {self.max_len}."
                )

        # Regex format (str)
        if isinstance(value, str) and self.regex is not None:
            if not re.search(self.regex, value):
                errors.append(
                    f"Field '{field_name}' value '{value}' does not match pattern '{self.regex}'."
                )

        # Allowed choices
        if self.choices is not None and value not in self.choices:
            errors.append(
                f"Field '{field_name}' value {value!r} is not in allowed choices: {self.choices}."
            )

        return errors


class DataContract:
    """Schema contract defining and validating structured dictionary payloads."""

    def __init__(
        self,
        schema: dict[str, Field],
        *,
        allow_extra: bool = True,
        name: str = "Contract",
    ) -> None:
        self.schema = schema
        self.allow_extra = allow_extra
        self.name = name

    def validate(self, data: Any) -> tuple[bool, list[str]]:
        """Validate input data against contract. Returns (is_valid, list_of_errors)."""
        if not isinstance(data, dict):
            return False, [
                f"Payload for contract '{self.name}' must be a dict, got {type(data).__name__}"
            ]

        errors: list[str] = []
        # Check required & present fields
        for field_name, field_spec in self.schema.items():
            if field_name not in data:
                if field_spec.required:
                    errors.append(
                        f"Missing required field '{field_name}' in contract '{self.name}'."
                    )
            else:
                errors.extend(field_spec.validate_value(field_name, data[field_name]))

        # Check unexpected extra fields if allow_extra is False
        if not self.allow_extra:
            for key in data:
                if key not in self.schema:
                    errors.append(
                        f"Unexpected extra field '{key}' not allowed in contract '{self.name}'."
                    )

        return (len(errors) == 0, errors)

    def enforce(self, data: Any) -> dict[str, Any]:
        """Validate data and raise ContractValidationError if constraints are violated."""
        is_valid, errors = self.validate(data)
        if not is_valid:
            joined = "; ".join(errors)
            err_msg = (
                f"Contract '{self.name}' validation failed with "
                f"{len(errors)} error(s): {joined}"
            )
            raise ContractValidationError(err_msg, errors=errors)
        return dict(data)


def enforce_contract(
    input_contract: DataContract | None = None,
    output_contract: DataContract | None = None,
) -> Callable[[F], F]:
    """Decorator to enforce input/output DataContracts on a callable."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Validate input payload
            if input_contract is not None:
                # If first arg is a dict, validate it; otherwise validate kwargs
                payload = args[0] if (args and isinstance(args[0], dict)) else kwargs
                input_contract.enforce(payload)

            result = func(*args, **kwargs)

            # Validate output payload
            if output_contract is not None:
                output_contract.enforce(result)

            return result

        return wrapper  # type: ignore[return-value]

    return decorator
