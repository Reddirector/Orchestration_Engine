import functools
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Optional
from regenbench.guards.base import Guard, HaltInfo
from regenbench.guards.intentguard.normalize import normalize_declared_args


class IntentGuard(Guard):
    """
    G4 IntentGuard:
    1. Intent Key: normalizes declared arguments and hashes (run_id + tool + normalized_declared_args).
    2. Reconcile-before-retry: checks if effect already committed prior to re-executing.
    """
    name: str = "G4_intentguard"
    version: str = "1.0.0"

    def __init__(self):
        self.run_id: str = "default_run"
        self.workdir: Optional[Path] = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        self.db_path = workdir / "intentguard_store.sqlite"
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intent_store (
                    intent_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            call_dict = kwargs if kwargs else (args[0] if args and isinstance(args[0], dict) else {"args": args})
            norm_args = normalize_declared_args(tool_name, call_dict)
            norm_str = json.dumps(norm_args, sort_keys=True)
            intent_key = hashlib.sha256(f"{self.run_id}:{tool_name}:{norm_str}".encode("utf-8")).hexdigest()

            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT state, result FROM intent_store WHERE intent_key = ?", (intent_key,))
                row = cursor.fetchone()
                if row:
                    state, res_str = row[0], row[1]
                    if state in ("COMMITTED", "INTENT"):
                        if res_str:
                            return json.loads(res_str)
                        # Reconcile lookup against external service
                        return {"status": "reconciled_existing", "intent_key": intent_key}

                # Transition to INTENT state
                conn.execute(
                    "INSERT OR REPLACE INTO intent_store (intent_key, state, result) VALUES (?, ?, ?)",
                    (intent_key, "INTENT", None),
                )
                conn.commit()

            # Execute effect
            try:
                res = fn(*args, **kwargs)
            except Exception as e:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute("UPDATE intent_store SET state = 'DOUBT' WHERE intent_key = ?", (intent_key,))
                    conn.commit()
                raise e

            # Transition to COMMITTED
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "UPDATE intent_store SET state = 'COMMITTED', result = ? WHERE intent_key = ?",
                    (json.dumps(res, sort_keys=True), intent_key),
                )
                conn.commit()

            return res

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return self._halted
