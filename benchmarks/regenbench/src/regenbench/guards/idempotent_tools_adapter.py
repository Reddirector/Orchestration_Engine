import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from idempotent_tools import SQLiteBackend, idempotent

from regenbench.guards.base import Guard, HaltInfo


def extract_business_id(args: tuple, kwargs: dict) -> str:
    d = kwargs if kwargs else (args[0] if args and isinstance(args[0], dict) else {})
    for k in ("order_id", "to", "customer_id"):
        if k in d:
            return str(d[k])
    return str(d)


class IdempotentToolsAdapter(Guard):
    name: str = "G3_idempotent_tools"
    version: str = "0.1.1"

    def __init__(self, mode: str = "default"):
        """
        mode:
          - "default" (G3a): default keying (SHA-256 of func name + exact args/kwargs)
          - "context" (G3b): step-derived workaround keying
        """
        self.mode = mode
        self.run_id: str = "default_run"
        self.workdir: Path | None = None
        self.backend: SQLiteBackend | None = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        db_path = str(workdir / "idempotent_tools.sqlite")
        self.backend = SQLiteBackend(db_path=db_path)

    def compute_key(self, tool_name: str, args: tuple, kwargs: dict) -> str:
        if self.mode == "context":
            return extract_business_id(args, kwargs)
        return f"{self.run_id}:{tool_name}"

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        if self.mode == "context":
            # Workaround G3b: keying uses business identifier
            def key_fn(f, a, kw, ctx):
                return self.compute_key(tool_name, a, kw)

            decorated = idempotent(
                fn,
                backend=self.backend,
                context=tool_name,
                key_fn=key_fn,
            )
        else:
            # Default G3a: exact argument hash
            decorated = idempotent(
                fn,
                backend=self.backend,
            )

        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            call_dict = kwargs if kwargs else (args[0] if args and isinstance(args[0], dict) else {"args": args})
            try:
                return decorated(*args, **kwargs)
            except Exception as exc:
                if "DuplicateInFlightError" in type(exc).__name__:
                    self._halted.append(
                        HaltInfo(tool_name=tool_name, args=call_dict, reason=f"DuplicateInFlightError: {exc}")
                    )
                raise

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return self._halted
