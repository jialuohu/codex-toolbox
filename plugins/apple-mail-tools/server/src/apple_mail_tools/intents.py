"""Private, expiring, single-use operation intents."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any

from .models import AppleMailError, ErrorCode


class IntentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Intent store is unsafe")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        self.path.chmod(0o600)
        _secure_sqlite_sidecars(self.path)
        return connection

    def _initialize(self) -> None:
        if self.path.is_symlink():
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Intent store is unsafe")
        existed = self.path.exists()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS intents (
                    token_hash TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    used_at REAL
                )
                """
            )
            connection.execute("DELETE FROM intents WHERE expires_at < ?", (time.time() - 86_400,))
        if not existed:
            self.path.chmod(0o600)
        metadata = self.path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Intent store is unsafe")
        _secure_sqlite_sidecars(self.path)

    def create(self, kind: str, payload: dict[str, Any], *, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO intents VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    _token_hash(token),
                    kind,
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                    now,
                    now + ttl_seconds,
                ),
            )
        return token

    def consume(self, token: str, kind: str) -> dict[str, Any]:
        if not _valid_token(token):
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Intent token is invalid")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM intents WHERE token_hash = ? AND kind = ?",
                (_token_hash(token), kind),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise AppleMailError(ErrorCode.NOT_FOUND, "Intent token is unavailable")
            if row["used_at"] is not None:
                connection.execute("ROLLBACK")
                raise AppleMailError(ErrorCode.INTENT_USED, "Intent token was already used")
            if float(row["expires_at"]) < now:
                connection.execute("ROLLBACK")
                raise AppleMailError(ErrorCode.INTENT_EXPIRED, "Intent token expired")
            changed = connection.execute(
                "UPDATE intents SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (now, _token_hash(token)),
            ).rowcount
            if changed != 1:
                connection.execute("ROLLBACK")
                raise AppleMailError(ErrorCode.INTENT_USED, "Intent token was already used")
            connection.execute("COMMIT")
        payload = json.loads(row["payload"])
        if not isinstance(payload, dict):
            raise AppleMailError(ErrorCode.INTERNAL_ERROR, "Stored intent is invalid")
        return payload

    def cancel(self, token: str, kind: str) -> bool:
        if not _valid_token(token):
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Intent token is invalid")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE intents SET used_at = ? "
                "WHERE token_hash = ? AND kind = ? AND used_at IS NULL",
                (time.time(), _token_hash(token), kind),
            ).rowcount
        return changed == 1


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _valid_token(token: str) -> bool:
    return 32 <= len(token) <= 128 and all(
        character.isalnum() or character in "-_" for character in token
    )


def _secure_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.is_symlink():
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Intent store is unsafe")
        if sidecar.is_file():
            sidecar.chmod(0o600)
