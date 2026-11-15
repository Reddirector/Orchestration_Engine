import functools
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from regenbench.guards.base import Guard, HaltInfo


class ServerIdempotencyKeyGuard(Guard):
    """
    G6: Injects client-side Idempotency-Key based on argument hash.
    The mock server stores results under the idempotency key with TTL.
    """

    name: str = "G6_server_key"
    version: str = "1.0.0"

    def __init__(self):
        self.run_id: str = "default_run"
        self.workdir: Path | None = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            call_dict = (
                kwargs
                if kwargs
                else (args[0] if args and isinstance(args[0], dict) else {"args": args})
            )
            raw_hash = hashlib.sha256(
                json.dumps(call_dict, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
            # Client injects Idempotency-Key header to the service call
            idem_key = f"ik-{self.run_id}-{tool_name}-{raw_hash}"

            if kwargs and "idempotency_key" in kwargs:
                kwargs["idempotency_key"] = idem_key
            elif args and isinstance(args[0], dict):
                args[0]["idempotency_key"] = idem_key

            return fn(*args, **kwargs)

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return self._halted
