import functools
import json
from pathlib import Path
from typing import Any, Callable, Optional
from regenbench.guards.base import Guard, HaltInfo


class SemanticAnalyzerGuard(Guard):
    """
    G7 ACRFence-style baseline: logs calls before execution and compares
    restored tool calls with logged prior calls using semantic equivalence.
    """
    name: str = "G7_analyzer"
    version: str = "1.0.0"

    def __init__(self):
        self.run_id: str = "default_run"
        self.workdir: Optional[Path] = None
        self.prior_calls: list[dict[str, Any]] = []
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        self.prior_calls_file = workdir / "g7_prior_calls.json"
        if self.prior_calls_file.exists():
            try:
                self.prior_calls = json.loads(self.prior_calls_file.read_text())
            except Exception:
                self.prior_calls = []

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: Optional[dict[str, Any]] = None,
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            call_dict = kwargs if kwargs else (args[0] if args and isinstance(args[0], dict) else {"args": args})

            # Check if current call is semantically identical to a logged call
            for prior in self.prior_calls:
                if prior.get("tool_name") == tool_name:
                    p_args = prior.get("args", {})
                    is_replay = False
                    if "order_id" in call_dict and call_dict.get("order_id") == p_args.get("order_id"):
                        is_replay = True
                    elif "to" in call_dict and str(call_dict.get("to", "")).lower() == str(p_args.get("to", "")).lower():
                        is_replay = True
                    elif "customer_id" in call_dict and call_dict.get("customer_id") == p_args.get("customer_id"):
                        is_replay = True

                    if is_replay:
                        return prior.get("result", {"status": "deduplicated_by_analyzer"})

            # Log call entry before execution
            self.prior_calls.append({
                "tool_name": tool_name,
                "args": call_dict,
                "result": {"status": "success", "semantic_replay": True},
            })
            if self.workdir:
                self.prior_calls_file.write_text(json.dumps(self.prior_calls))

            res = fn(*args, **kwargs)
            return res

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id
        if self.workdir and self.prior_calls_file.exists():
            try:
                self.prior_calls = json.loads(self.prior_calls_file.read_text())
            except Exception:
                pass

    def halted(self) -> list[HaltInfo]:
        return self._halted
