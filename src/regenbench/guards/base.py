from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol


@dataclass
class HaltInfo:
    tool_name: str
    args: dict[str, Any]
    reason: str


class Guard(Protocol):
    name: str
    version: str

    def setup(self, run_id: str, workdir: Path) -> None:
        ...

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: Optional[dict[str, Any]] = None,
    ) -> Callable[..., Any]:
        ...

    def on_resume(self, run_id: str) -> None:
        ...

    def halted(self) -> list[HaltInfo]:
        ...
