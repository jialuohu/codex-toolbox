"""Private resumable SQLite FTS5 index for Mail history."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import time
import uuid
from pathlib import Path
from typing import Any, cast

from .models import AppleMailError, ErrorCode

_WORD = re.compile(r"\w+", re.UNICODE)


class MailIndex:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file() and not self.path.is_symlink()

    def _connect(self, *, create: bool = True) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Mail index is unsafe")
        if not create and not self.path.exists():
            raise AppleMailError(
                ErrorCode.INDEX_INCOMPLETE, "Mail history index has not been created"
            )
        existed = self.path.exists()
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        if not existed:
            self.path.chmod(0o600)
        metadata = self.path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            connection.close()
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Mail index is unsafe")
        _secure_sqlite_sidecars(self.path)
        self._schema(connection)
        return connection

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                sync_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                account_id TEXT NOT NULL,
                mailbox_path TEXT NOT NULL,
                next_offset INTEGER NOT NULL DEFAULT 0,
                complete INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY(sync_id, account_id, mailbox_path)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts USING fts5(
                location_key UNINDEXED,
                generation UNINDEXED,
                account_id UNINDEXED,
                mailbox_path UNINDEXED,
                native_id UNINDEXED,
                rfc_message_id UNINDEXED,
                fingerprint UNINDEXED,
                subject,
                sender,
                recipients,
                body,
                date_received UNINDEXED,
                date_sent UNINDEXED,
                read_status UNINDEXED,
                flagged_status UNINDEXED,
                message_size UNINDEXED,
                indexed_at UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )

    def active_sync(self, mode: str) -> dict[str, Any] | None:
        if not self.exists():
            return None
        with self._connect(create=False) as connection:
            sync_id = self._metadata(connection, f"active_{mode}_sync")
            scopes = self._metadata(connection, f"active_{mode}_scopes")
        if not sync_id or not scopes:
            return None
        value = json.loads(scopes)
        return {"sync_id": sync_id, "scopes": value}

    def choose_sync(
        self, mode: str, scopes: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        active = self.active_sync(mode)
        if active is not None:
            active_scopes = active["scopes"]
            if active_scopes != scopes:
                raise AppleMailError(
                    ErrorCode.INDEX_INCOMPLETE,
                    "An existing index sync must finish before its scope can change",
                )
            return str(active["sync_id"]), active_scopes
        return uuid.uuid4().hex, scopes

    def activate_sync(self, sync_id: str, mode: str, scopes: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            current = self._metadata(connection, f"active_{mode}_sync")
            if current not in (None, sync_id):
                raise AppleMailError(
                    ErrorCode.INDEX_INCOMPLETE, "Another index sync is already active"
                )
            self._set_metadata(connection, f"active_{mode}_sync", sync_id)
            self._set_metadata(
                connection,
                f"active_{mode}_scopes",
                json.dumps(scopes, sort_keys=True, separators=(",", ":")),
            )
            for scope in scopes:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO checkpoints
                    (sync_id, mode, account_id, mailbox_path, next_offset, complete, updated_at)
                    VALUES (?, ?, ?, ?, 0, 0, ?)
                    """,
                    (
                        sync_id,
                        mode,
                        scope["account_id"],
                        _path_text(scope["mailbox_path"]),
                        time.time(),
                    ),
                )
            connection.commit()

    def checkpoint(
        self, sync_id: str, account_id: str, mailbox_path: list[str]
    ) -> tuple[int, bool]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT next_offset, complete FROM checkpoints "
                "WHERE sync_id=? AND account_id=? AND mailbox_path=?",
                (sync_id, account_id, _path_text(mailbox_path)),
            ).fetchone()
        if row is None:
            return 0, False
        return int(row["next_offset"]), bool(row["complete"])

    def index_page(
        self,
        *,
        sync_id: str,
        mode: str,
        account_id: str,
        mailbox_path: list[str],
        messages: list[dict[str, Any]],
        next_offset: int,
        complete: bool,
    ) -> None:
        now = time.time()
        path_text = _path_text(mailbox_path)
        with self._connect() as connection:
            for message in messages:
                location_key = _location_key(account_id, path_text, int(message["native_id"]))
                connection.execute("DELETE FROM mail_fts WHERE location_key = ?", (location_key,))
                recipients = " ".join(
                    str(value) for key in ("to", "cc", "bcc") for value in message.get(key, [])
                )
                connection.execute(
                    """
                    INSERT INTO mail_fts VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        location_key,
                        sync_id,
                        account_id,
                        path_text,
                        int(message["native_id"]),
                        message.get("rfc_message_id") or "",
                        message["fingerprint"],
                        message.get("subject") or "",
                        message.get("sender") or "",
                        recipients,
                        message.get("body") or "",
                        message.get("date_received") or "",
                        message.get("date_sent") or "",
                        1 if message.get("read_status") else 0,
                        1 if message.get("flagged_status") else 0,
                        int(message.get("message_size") or 0),
                        now,
                    ),
                )
            connection.execute(
                """
                UPDATE checkpoints SET next_offset=?, complete=?, updated_at=?
                WHERE sync_id=? AND account_id=? AND mailbox_path=?
                """,
                (next_offset, 1 if complete else 0, now, sync_id, account_id, path_text),
            )
            if complete and mode == "full":
                connection.execute(
                    "DELETE FROM mail_fts WHERE account_id=? AND mailbox_path=? AND generation<>?",
                    (account_id, path_text, sync_id),
                )
            connection.commit()

    def finish_if_complete(self, sync_id: str, mode: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS pending FROM checkpoints WHERE sync_id=? AND complete=0",
                (sync_id,),
            ).fetchone()
            complete = row is not None and int(row["pending"]) == 0
            if complete:
                self._set_metadata(connection, f"last_{mode}_sync", sync_id)
                self._set_metadata(connection, f"last_{mode}_completed_at", str(time.time()))
                connection.execute(
                    "DELETE FROM metadata WHERE key IN (?, ?)",
                    (f"active_{mode}_sync", f"active_{mode}_scopes"),
                )
                connection.commit()
        return complete

    def status(self) -> dict[str, Any]:
        if not self.exists():
            return {
                "present": False,
                "message_locations": 0,
                "complete_full_history": False,
                "active_syncs": [],
            }
        with self._connect(create=False) as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM mail_fts").fetchone()[0])
            metadata = {
                row["key"]: row["value"] for row in connection.execute("SELECT * FROM metadata")
            }
            active_rows = connection.execute(
                """
                SELECT sync_id, mode, COUNT(*) AS mailbox_count,
                       SUM(CASE WHEN complete=1 THEN 1 ELSE 0 END) AS complete_count,
                       SUM(next_offset) AS indexed_count, MAX(updated_at) AS updated_at
                FROM checkpoints
                WHERE sync_id IN (
                    SELECT value FROM metadata
                    WHERE key IN ('active_full_sync','active_incremental_sync')
                )
                GROUP BY sync_id, mode
                """
            ).fetchall()
            indexed_rows = connection.execute(
                """
                SELECT account_id, mailbox_path, COUNT(*) AS message_locations,
                       MAX(CAST(indexed_at AS REAL)) AS newest_indexed_at
                FROM mail_fts
                GROUP BY account_id, mailbox_path
                ORDER BY account_id, mailbox_path
                """
            ).fetchall()
            newest = connection.execute(
                "SELECT MAX(CAST(indexed_at AS REAL)) FROM mail_fts"
            ).fetchone()[0]
        active = [dict(row) for row in active_rows]
        return {
            "present": True,
            "message_locations": count,
            "complete_full_history": "last_full_sync" in metadata,
            "last_full_completed_at": _float_or_none(metadata.get("last_full_completed_at")),
            "last_incremental_completed_at": _float_or_none(
                metadata.get("last_incremental_completed_at")
            ),
            "last_full_generation": metadata.get("last_full_sync"),
            "last_incremental_generation": metadata.get("last_incremental_sync"),
            "newest_indexed_at": _float_or_none(newest),
            "active_syncs": active,
            "indexed_scopes": [dict(row) for row in indexed_rows],
        }

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        match = literal_fts_query(query)
        with self._connect(create=False) as connection:
            rows = connection.execute(
                """
                SELECT *, bm25(mail_fts) AS relevance
                FROM mail_fts WHERE mail_fts MATCH ?
                ORDER BY relevance, date_received DESC LIMIT ?
                """,
                (match, min(limit * 5, 500)),
            ).fetchall()
        return [dict(row) for row in rows]

    def erase(self) -> list[str]:
        removed: list[str] = []
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self.path}{suffix}")
            if path.is_symlink():
                raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Mail index is unsafe")
            if path.is_file():
                path.unlink()
                removed.append(path.name)
            elif path.exists():
                raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Mail index is unsafe")
        return removed

    @staticmethod
    def _metadata(connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO metadata(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def literal_fts_query(query: str) -> str:
    words = _WORD.findall(query)
    if not words:
        raise AppleMailError(
            ErrorCode.VALIDATION_ERROR, "History query must contain searchable text"
        )
    return " AND ".join(f'"{word.replace(chr(34), chr(34) * 2)}"' for word in words[:50])


def _path_text(path: list[str]) -> str:
    return json.dumps(path, ensure_ascii=False, separators=(",", ":"))


def decode_path(value: str) -> list[str]:
    raw_result: Any = json.loads(value)
    if not isinstance(raw_result, list):
        raise AppleMailError(ErrorCode.INTERNAL_ERROR, "Indexed mailbox path is invalid")
    result = cast(list[Any], raw_result)
    if not all(isinstance(item, str) for item in result):
        raise AppleMailError(ErrorCode.INTERNAL_ERROR, "Indexed mailbox path is invalid")
    return [cast(str, item) for item in result]


def _location_key(account_id: str, path_text: str, native_id: int) -> str:
    import hashlib

    return hashlib.sha256(f"{account_id}\0{path_text}\0{native_id}".encode()).hexdigest()


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _secure_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.is_symlink():
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Mail index is unsafe")
        if sidecar.is_file():
            sidecar.chmod(0o600)
