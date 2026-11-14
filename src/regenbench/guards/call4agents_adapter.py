import functools
from pathlib import Path
from typing import Any, Callable, Optional
import call4agents
from regenbench.guards.base import Guard, HaltInfo


class Call4AgentsAdapter(Guard):
    name: str = "G1_call4agents"
    version: str = "0.7.2"

    def __init__(self, use_workaround_key: bool = False):
        self.use_workaround_key = use_workaround_key
        self.run_id: str = "default_run"
        self.workdir: Optional[Path] = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        db_path = str(workdir / "c4a_ledger.sqlite")
        call4agents.init(path=db_path)

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: Optional[dict[str, Any]] = None,
    ) -> Callable[..., Any]:
        key_fn = None
        if self.use_workaround_key and intent_schema and "key_fn" in intent_schema:
            key_fn = intent_schema["key_fn"]

        c4a_decorated = call4agents.effect(fn, name=tool_name, key=key_fn)

        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with call4agents.run(self.run_id):
                return c4a_decorated(*args, **kwargs)

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return self._halted
