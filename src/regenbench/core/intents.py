from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Intent:
    """Out-of-band intent definition.

    Guards NEVER see intent_id. It is passed via out-of-band transport
    (e.g., hidden HTTP header) directly from scenario/wrapper to mock service.
    """

    intent_id: str
    scenario_id: str
    tool_name: str
    canonical_payload: dict[str, Any]
    is_control: bool = False
    description: str | None = None
