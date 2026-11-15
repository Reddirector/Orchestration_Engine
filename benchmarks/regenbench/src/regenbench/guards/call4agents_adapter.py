import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import call4agents

from regenbench.guards.base import Guard, HaltInfo


def extract_business_id(args: tuple, kwargs: dict) -> str:
    d = kwargs if kwargs else (args[0] if args and isinstance(args[0], dict) else {})
    for k in ("order_id", "to", "customer_id"):
        if k in d:
            return str(d[k])
    return str(d)


class Call4AgentsAdapter(Guard):
    name: str = "G1_call4agents"
    version: str = "0.7.2"

    def __init__(self, use_workaround_key: bool = False):
        self.use_workaround_key = use_workaround_key
        self.run_id: str = "default_run"
        self.workdir: Path | None = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        db_path = str(workdir / "c4a_ledger.sqlite")
        call4agents.init(path=db_path)

    def compute_key(self, tool_name: str, args: tuple, kwargs: dict) -> str:
        return extract_business_id(args, kwargs)

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        c4a_decorated = call4agents.effect(fn, name=tool_name)

        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            call_kw = dict(kwargs)
            if self.use_workaround_key:
                call_kw["c4a_key"] = self.compute_key(tool_name, args, kwargs)
            with call4agents.run(self.run_id):
                return c4a_decorated(*args, **call_kw)

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return self._halted
