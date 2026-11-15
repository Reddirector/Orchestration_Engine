from collections.abc import Callable
from pathlib import Path
from typing import Any

from regenbench.guards.base import Guard, HaltInfo


class NoGuard(Guard):
    name: str = "G0_none"
    version: str = "0.0.0"

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return fn

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return []
