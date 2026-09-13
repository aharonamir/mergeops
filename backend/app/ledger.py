"""Small SQLite ledger for durable agent execution state.

The JSON file remains the dashboard snapshot.  This module owns only queue,
lease, process identity, cancellation, and ordered event state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4


class ExecutionLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    lease_owner TEXT,
                    lease_expires REAL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    process_pid INTEGER,
                    process_group INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_claimable ON jobs(state, lease_expires, created_at);
                CREATE TABLE IF NOT EXISTS execution_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def enqueue(self, run_id: str, payload: dict[str, object], created_at: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs(id, payload, state, created_at, updated_at)
                   VALUES (?, ?, 'queued', ?, ?)
                   ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, state='queued', lease_owner=NULL,
                   lease_expires=NULL, cancel_requested=0, updated_at=excluded.updated_at
                   WHERE jobs.state != 'running'""",
                (run_id, json.dumps(payload), created_at, created_at),
            )

    def ensure_queued(self, run_id: str, payload: dict[str, object], created_at: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO jobs(id, payload, state, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?)",
                (run_id, json.dumps(payload), created_at, created_at),
            )

    def claim(self, owner: str, lease_seconds: int = 30) -> dict[str, object] | None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM jobs
                   WHERE (state = 'queued' OR (state = 'running' AND lease_expires < ?))
                     AND cancel_requested = 0
                   ORDER BY created_at ASC LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            attempt = int(row["attempt"]) + 1
            connection.execute(
                """UPDATE jobs SET state='running', lease_owner=?, lease_expires=?, attempt=?, updated_at=? WHERE id=?""",
                (owner, now + lease_seconds, attempt, str(now), row["id"]),
            )
            connection.commit()
            payload = json.loads(row["payload"])
            return {"id": row["id"], "payload": payload, "attempt": attempt}

    def heartbeat(self, run_id: str, owner: str, lease_seconds: int = 30, process_pid: int | None = None, process_group: int | None = None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE jobs SET lease_expires=?, updated_at=?, process_pid=COALESCE(?, process_pid),
                   process_group=COALESCE(?, process_group) WHERE id=? AND lease_owner=?""",
                (time.time() + lease_seconds, str(time.time()), process_pid, process_group, run_id, owner),
            )

    def finish(self, run_id: str, state: str = "finished") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET state=?, lease_owner=NULL, lease_expires=NULL, process_pid=NULL, process_group=NULL, updated_at=? WHERE id=?",
                (state, str(time.time()), run_id),
            )

    def request_cancel(self, run_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?",
                (str(time.time()), run_id),
            )

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE id=?", (run_id,)).fetchone()
            return bool(row and row[0])

    def event(self, run_id: str, event_type: str, message: str, created_at: str, payload: dict[str, object] | None = None) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO execution_events(run_id,event_type,message,created_at,payload) VALUES (?,?,?,?,?)",
                (run_id, event_type, message, created_at, json.dumps(payload) if payload else None),
            )
            return int(cursor.lastrowid)

    def events_after(self, sequence: int = 0, limit: int = 100) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence,run_id,event_type,message,created_at,payload FROM execution_events WHERE sequence>? ORDER BY sequence LIMIT ?",
                (sequence, limit),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "runId": row["run_id"],
                "type": row["event_type"],
                "message": row["message"],
                "createdAt": row["created_at"],
                "payload": json.loads(row["payload"]) if row["payload"] else None,
            }
            for row in rows
        ]

    def active_jobs(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs WHERE state='running'").fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def owner() -> str:
        return f"mergeops-worker-{os.getpid()}-{uuid4().hex[:8]}"
