"""Managed private leases for incoming Mail attachments."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import time
from pathlib import Path
from typing import Any

from .models import AppleMailError, ErrorCode

LEASE_TTL_SECONDS = 24 * 60 * 60


class LeaseStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cleanup_expired()

    def create_target(self, filename: str) -> tuple[str, Path, float]:
        token = secrets.token_urlsafe(32)
        lease_dir = self.root / token
        lease_dir.mkdir(mode=0o700)
        lease_dir.chmod(0o700)
        safe_name = _safe_filename(filename)
        return token, lease_dir / safe_name, time.time() + LEASE_TTL_SECONDS

    def finalize(
        self,
        token: str,
        file_path: Path,
        expires_at: float,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        lease_dir = self._lease_dir(token)
        try:
            file_metadata = file_path.lstat()
        except OSError as error:
            self._remove_lease_dir(lease_dir)
            raise AppleMailError(
                ErrorCode.BRIDGE_ERROR, "Mail did not save the attachment"
            ) from error
        if stat.S_ISLNK(file_metadata.st_mode) or not stat.S_ISREG(file_metadata.st_mode):
            self._remove_lease_dir(lease_dir)
            raise AppleMailError(ErrorCode.BRIDGE_ERROR, "Saved attachment is unsafe")
        file_path.chmod(0o600)
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        receipt = {
            "version": 1,
            "token": token,
            "path": str(file_path),
            "size": file_metadata.st_size,
            "sha256": digest.hexdigest(),
            "expires_at": expires_at,
            "metadata": metadata,
        }
        receipt_path = lease_dir / "lease.json"
        descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, (json.dumps(receipt, separators=(",", ":")) + "\n").encode())
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        return receipt

    def release(self, token: str) -> bool:
        lease_dir = self._lease_dir(token)
        if not lease_dir.exists() and not lease_dir.is_symlink():
            return False
        self._remove_lease_dir(lease_dir)
        return True

    def cleanup_expired(self) -> int:
        removed = 0
        now = time.time()
        for entry in self.root.iterdir():
            if entry.is_symlink():
                entry.unlink()
                removed += 1
                continue
            if not entry.is_dir() or not _valid_token(entry.name):
                continue
            receipt = entry / "lease.json"
            expires_at = 0.0
            try:
                raw = json.loads(receipt.read_text())
                expires_at = float(raw.get("expires_at", 0)) if isinstance(raw, dict) else 0.0
            except (OSError, ValueError, json.JSONDecodeError):
                expires_at = 0.0
            if expires_at <= now:
                self._remove_lease_dir(entry)
                removed += 1
        return removed

    def _lease_dir(self, token: str) -> Path:
        if not _valid_token(token):
            raise AppleMailError(ErrorCode.VALIDATION_ERROR, "Lease token is invalid")
        return self.root / token

    def _remove_lease_dir(self, path: Path) -> None:
        if path.parent != self.root:
            raise AppleMailError(ErrorCode.INTERNAL_ERROR, "Lease path is invalid")
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip().replace("\x00", "")
    if not name or name in {".", ".."}:
        name = "attachment"
    encoded = name.encode("utf-8")[:180]
    return encoded.decode("utf-8", errors="ignore") or "attachment"


def _valid_token(token: str) -> bool:
    return 32 <= len(token) <= 128 and all(
        character.isalnum() or character in "-_" for character in token
    )
