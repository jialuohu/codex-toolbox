"""Private, synchronous SQLite journal for at-most-once App Server mutations."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any


class LedgerError(RuntimeError):
    pass


class KeyConflict(LedgerError):
    pass


FIELDS = {
    "task_id", "turn_id", "stage", "creation", "title_status", "submission", "execution",
    "persistence", "backend_membership", "desktop_verification", "prompt_delivery",
    "prompt_body",
    "effective_settings", "instruction_sources", "reason", "observed_at",
}


def private_dir(path: Path) -> Path:
    path = path.expanduser().absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise LedgerError("Private task state may not pass through a symlink")
        if not current.exists():
            current.mkdir(mode=0o700)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise LedgerError("Private task state has the wrong owner or type")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise LedgerError("Private task state is accessible to another user")
    return path


class Ledger:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = private_dir(state_dir)
        self.path = self.state_dir / "ledger.sqlite3"
        if self.path.is_symlink():
            raise LedgerError("Private ledger may not be a symlink")
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
        if (
            not self.path.is_file()
            or self.path.stat().st_uid != os.getuid()
            or stat.S_IMODE(self.path.stat().st_mode) & 0o077
        ):
            raise LedgerError("Private ledger has unsafe permissions")
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                backend_identity TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                project_ref TEXT NOT NULL,
                project_id TEXT NOT NULL,
                cwd TEXT NOT NULL,
                requested_title TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                prompt_body TEXT,
                task_id TEXT,
                turn_id TEXT,
                stage TEXT NOT NULL,
                creation TEXT NOT NULL,
                title_status TEXT NOT NULL,
                submission TEXT NOT NULL,
                prompt_delivery TEXT NOT NULL,
                execution TEXT NOT NULL,
                persistence TEXT NOT NULL,
                backend_membership TEXT NOT NULL,
                desktop_verification TEXT NOT NULL,
                effective_settings TEXT,
                instruction_sources TEXT,
                reason TEXT,
                observed_at INTEGER NOT NULL,
                PRIMARY KEY (backend_identity, idempotency_key)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS tasks_by_id ON tasks (backend_identity, task_id)
                WHERE task_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS pending (
                backend_identity TEXT NOT NULL,
                task_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                generation TEXT NOT NULL,
                method TEXT NOT NULL,
                params TEXT NOT NULL,
                state TEXT NOT NULL,
                observed_at INTEGER NOT NULL,
                PRIMARY KEY (backend_identity, task_id, request_id, generation)
            );
            """
        )

    def close(self) -> None:
        self.db.close()

    def reserve(self, values: dict[str, str]) -> tuple[dict[str, Any], bool]:
        """Atomic key reservation; an existing key must bind to exactly the same payload."""
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM tasks WHERE backend_identity=? AND idempotency_key=?",
                (values["backend_identity"], values["idempotency_key"]),
            ).fetchone()
            if row is not None:
                if row["payload_hash"] != values["payload_hash"]:
                    raise KeyConflict("Idempotency key is already bound to a different request")
                self.db.execute("COMMIT")
                return dict(row), False
            self.db.execute(
                """INSERT INTO tasks (
                    backend_identity, idempotency_key, payload_hash, project_ref, project_id,
                    cwd, requested_title, prompt_hash, prompt_body, stage, creation,
                    title_status, submission, prompt_delivery, execution, persistence, backend_membership,
                    desktop_verification, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', 'reserved', 'pending',
                          'pending', 'unverified', 'not_started', 'unverified', 'unverified',
                          'unverified', ?)""",
                (
                    values["backend_identity"], values["idempotency_key"],
                    values["payload_hash"], values["project_ref"], values["project_id"],
                    values["cwd"], values["requested_title"], values["prompt_hash"],
                    values["prompt_body"], now,
                ),
            )
            row = self.db.execute(
                "SELECT * FROM tasks WHERE backend_identity=? AND idempotency_key=?",
                (values["backend_identity"], values["idempotency_key"]),
            ).fetchone()
            self.db.execute("COMMIT")
            assert row is not None
            return dict(row), True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def update(self, backend: str, key: str, **fields: Any) -> dict[str, Any]:
        if not fields or set(fields) - FIELDS:
            raise LedgerError("Unsupported ledger transition")
        fields["observed_at"] = int(time.time())
        columns = ", ".join(f"{field}=?" for field in fields)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.db.execute(
                f"UPDATE tasks SET {columns} WHERE backend_identity=? AND idempotency_key=?",
                (*fields.values(), backend, key),
            )
            if cursor.rowcount != 1:
                raise LedgerError("Task receipt is unavailable")
            row = self.by_key(backend, key)
            self.db.execute("COMMIT")
            assert row is not None
            return row
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def by_key(self, backend: str, key: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM tasks WHERE backend_identity=? AND idempotency_key=?",
            (backend, key),
        ).fetchone()
        return dict(row) if row is not None else None

    def by_task(self, backend: str, task_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM tasks WHERE backend_identity=? AND task_id=?", (backend, task_id)
        ).fetchone()
        return dict(row) if row is not None else None

    def tracked(self, backend: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM tasks WHERE backend_identity=? AND task_id IS NOT NULL", (backend,)
        )]

    def mark_inflight_unknown(self, backend: str) -> None:
        """A restarted broker cannot know whether an in-flight mutation committed."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for stage, creation, title, submission in (
                ("create_sending", "unknown", None, None),
                ("assign_sending", None, None, None),
                ("title_sending", None, "unknown", None),
                ("turn_sending", None, None, "unknown"),
            ):
                reason = (
                    "broker_restart_during_assignment" if stage == "assign_sending"
                    else "broker_restart_during_mutation"
                )
                assignments = ["stage='needs_recovery'", f"reason='{reason}'"]
                if stage == "assign_sending":
                    assignments.append("backend_membership='unknown'")
                if creation:
                    assignments.append("creation='unknown'")
                if title:
                    assignments.append("title_status='unknown'")
                if submission:
                    assignments.append("submission='unknown'")
                self.db.execute(
                    f"UPDATE tasks SET {', '.join(assignments)} WHERE backend_identity=? AND stage=?",
                    (backend, stage),
                )
            self.db.execute(
                "UPDATE pending SET state='stale' WHERE backend_identity=? "
                "AND state IN ('pending', 'responding', 'sent_unconfirmed')", (backend,)
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def add_pending(
        self, backend: str, task_id: str, request_id: str, generation: str,
        method: str, params: dict[str, Any], state: str,
    ) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO pending
               (backend_identity, task_id, request_id, generation, method, params, state, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (backend, task_id, request_id, generation, method,
             json.dumps(params, separators=(",", ":")), state, int(time.time())),
        )

    def pending_for(self, backend: str, task_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT request_id, generation, method, params, state, observed_at FROM pending
               WHERE backend_identity=? AND task_id=?
               AND state IN ('pending', 'stale', 'needs_attention', 'responding', 'sent_unconfirmed')
               ORDER BY observed_at""", (backend, task_id)
        )
        return [dict(row) for row in rows]

    def pending_exact(self, backend: str, task_id: str, request_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            """SELECT * FROM pending WHERE backend_identity=? AND task_id=? AND request_id=?
               AND state='pending' ORDER BY observed_at DESC LIMIT 1""",
            (backend, task_id, request_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def pending_state(
        self, backend: str, task_id: str, request_id: str, generation: str, state: str,
        *, expected_state: str | None = None,
    ) -> None:
        expected_clause = " AND state=?" if expected_state is not None else ""
        values = (state, int(time.time()), backend, task_id, request_id, generation)
        if expected_state is not None:
            values += (expected_state,)
        self.db.execute(
            """UPDATE pending SET state=?, observed_at=? WHERE backend_identity=? AND task_id=?
               AND request_id=? AND generation=?""" + expected_clause,
            values,
        )

    def resolve_for_task(self, backend: str, task_id: str) -> None:
        self.db.execute(
            """UPDATE pending SET state='resolved', observed_at=?
               WHERE backend_identity=? AND task_id=?
               AND state IN ('pending', 'stale', 'needs_attention', 'responding',
                             'sent_unconfirmed')""",
            (int(time.time()), backend, task_id),
        )
