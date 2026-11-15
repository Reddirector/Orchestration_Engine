import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EffectRecord:
    id: int
    intent_id: str
    service: str
    action: str
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: str


class EffectLedger:
    """Append-only SQLite ledger in WAL mode to track real side effects.

    UPDATE and DELETE are rejected via SQLite triggers.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS effects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_id TEXT NOT NULL,
                    service TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    idempotency_key TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_intent ON service_requests(intent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_effects_intent ON effects(intent_id)")
            # Triggers to enforce append-only guarantees
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS abort_update_effects
                BEFORE UPDATE ON effects
                BEGIN
                    SELECT RAISE(ABORT, 'Effects table is append-only: UPDATE not allowed');
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS abort_delete_effects
                BEFORE DELETE ON effects
                BEGIN
                    SELECT RAISE(ABORT, 'Effects table is append-only: DELETE not allowed');
                END;
                """
            )
            conn.commit()

    def record_request(self, intent_id: str, phase: str = "w1") -> None:
        now = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO service_requests (intent_id, phase, created_at) VALUES (?, ?, ?)",
                (intent_id, phase, now),
            )
            conn.commit()

    def count_requests(self, intent_id: str, phase: str | None = None) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if phase is not None:
                cursor.execute(
                    "SELECT COUNT(*) FROM service_requests WHERE intent_id = ? AND phase = ?",
                    (intent_id, phase),
                )
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM service_requests WHERE intent_id = ?",
                    (intent_id,),
                )
            return cursor.fetchone()[0]

    def record_effect(
        self,
        intent_id: str,
        service: str,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> EffectRecord:
        now = datetime.now(UTC).isoformat()
        payload_str = json.dumps(payload, sort_keys=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO effects (intent_id, service, action, payload, idempotency_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (intent_id, service, action, payload_str, idempotency_key, now),
            )
            conn.commit()
            record_id = cursor.lastrowid
            return EffectRecord(
                id=record_id,
                intent_id=intent_id,
                service=service,
                action=action,
                payload=payload,
                idempotency_key=idempotency_key,
                created_at=now,
            )

    def get_effects_for_intent(self, intent_id: str) -> list[EffectRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, intent_id, service, action, payload, idempotency_key, created_at
                FROM effects
                WHERE intent_id = ?
                ORDER BY id ASC
                """,
                (intent_id,),
            )
            rows = cursor.fetchall()
            return [
                EffectRecord(
                    id=row[0],
                    intent_id=row[1],
                    service=row[2],
                    action=row[3],
                    payload=json.loads(row[4]),
                    idempotency_key=row[5],
                    created_at=row[6],
                )
                for row in rows
            ]

    def count_effects(self, intent_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM effects WHERE intent_id = ?",
                (intent_id,),
            )
            return cursor.fetchone()[0]

    def all_effects(self) -> list[EffectRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, intent_id, service, action, payload, idempotency_key, created_at
                FROM effects
                ORDER BY id ASC
                """
            )
            rows = cursor.fetchall()
            return [
                EffectRecord(
                    id=row[0],
                    intent_id=row[1],
                    service=row[2],
                    action=row[3],
                    payload=json.loads(row[4]),
                    idempotency_key=row[5],
                    created_at=row[6],
                )
                for row in rows
            ]
