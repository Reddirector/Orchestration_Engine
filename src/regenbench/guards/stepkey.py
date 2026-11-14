import functools
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Optional
from regenbench.guards.base import Guard, HaltInfo


class StepKeyGuard(Guard):
    """
    G5 StepKey: Keys solely by run_id + deterministic step index / tool name.
    Ignores argument differences entirely. Slot claimed before execution.
    """
    name: str = "G5_stepkey"
    version: str = "1.0.0"

    def __init__(self):
        self.run_id: str = "default_run"
        self.workdir: Optional[Path] = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        self.db_path = workdir / "stepkey_store.sqlite"
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS step_effects (
                    step_key TEXT PRIMARY KEY,
                    status TEXT,
                    result TEXT
                )
                """
            )
            conn.commit()

    def wrap(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        intent_schema: Optional[dict[str, Any]] = None,
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            step_key = f"{self.run_id}:{tool_name}"
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status, result FROM step_effects WHERE step_key = ?", (step_key,))
                row = cursor.fetchone()
                if row and row[0] in ("claimed", "completed"):
                    if row[1]:
                        return json.loads(row[1])
                    return {"status": "deduplicated_by_step"}

                conn.execute(
                    "INSERT OR REPLACE INTO step_effects (step_key, status, result) VALUES (?, ?, ?)",
                    (step_key, "claimed", None),
                )
                conn.commit()

            res = fn(*args, **kwargs)

            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "UPDATE step_effects SET status = 'completed', result = ? WHERE step_key = ?",
                    (json.dumps(res, sort_keys=True), step_key),
                )
                conn.commit()

            return res

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return self._halted
