import functools
import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from regenbench.guards.base import Guard, HaltInfo


class AgentRaaSAdapter(Guard):
    """
    Adapter for agentraas-style exactly-once deduplication slot claiming.
    Slot is claimed before executing target function. If already claimed/completed,
    returns cached result.
    """

    name: str = "G2_agentraas"
    version: str = "0.16.0"

    def __init__(self, use_workaround_key: bool = False):
        self.use_workaround_key = use_workaround_key
        self.run_id: str = "default_run"
        self.workdir: Path | None = None
        self._halted: list[HaltInfo] = []

    def setup(self, run_id: str, workdir: Path) -> None:
        self.run_id = run_id
        self.workdir = workdir
        self.db_path = workdir / "agentraas_slots.sqlite"
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dedup_slots (
                    slot_key TEXT PRIMARY KEY,
                    status TEXT,
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
        intent_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            call_dict = (
                kwargs
                if kwargs
                else (args[0] if args and isinstance(args[0], dict) else {"args": args})
            )

            if self.use_workaround_key and intent_schema and "fields" in intent_schema:
                subset = {k: call_dict[k] for k in intent_schema["fields"] if k in call_dict}
                payload_str = json.dumps(subset, sort_keys=True)
            else:
                payload_str = json.dumps(call_dict, sort_keys=True)

            slot_key = hashlib.sha256(
                f"{self.run_id}:{tool_name}:{payload_str}".encode()
            ).hexdigest()

            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status, result FROM dedup_slots WHERE slot_key = ?", (slot_key,)
                )
                row = cursor.fetchone()
                if row and row[0] == "claimed":
                    self._halted.append(
                        HaltInfo(
                            tool_name=tool_name,
                            args=call_dict,
                            reason="Slot in claimed state without result",
                        )
                    )
                    if row[1]:
                        return json.loads(row[1])
                    return {"status": "deduplicated_in_flight"}
                elif row and row[0] == "completed":
                    if row[1]:
                        return json.loads(row[1])
                    return {"status": "deduplicated_completed"}

                # Claim slot prior to executing
                conn.execute(
                    "INSERT OR REPLACE INTO dedup_slots (slot_key, status, result) VALUES (?, ?, ?)",
                    (slot_key, "claimed", None),
                )
                conn.commit()

            # Execute
            res = fn(*args, **kwargs)

            # Mark completed with result
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "UPDATE dedup_slots SET status = 'completed', result = ? WHERE slot_key = ?",
                    (json.dumps(res, sort_keys=True), slot_key),
                )
                conn.commit()

            return res

        return wrapped

    def on_resume(self, run_id: str) -> None:
        self.run_id = run_id

    def halted(self) -> list[HaltInfo]:
        return self._halted
