"""Private, bounded staging for authenticated Docmost attachments."""

from __future__ import annotations

import codecs
import hashlib
import os
import secrets
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from threading import Lock
from typing import Literal

from docmost_tools.models import AttachmentDownload

StageErrorKind = Literal["too_large", "invalid_content", "size_mismatch", "closed"]


class AttachmentStageError(RuntimeError):
    """A stable internal failure that never embeds attachment content or paths."""

    def __init__(self, kind: StageErrorKind) -> None:
        super().__init__(kind)
        self.kind = kind


class AttachmentDownloadStore:
    """Stage downloads in private temporary directories and release them by token."""

    def __init__(self, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._root: Path | None = None
        self._paths: dict[str, Path] = {}
        self._closed = False
        self._lock = Lock()

    def stage(
        self,
        *,
        filename: str,
        media_type: Literal["application/pdf", "text/plain"],
        chunks: Iterable[object],
        expected_size: int,
    ) -> AttachmentDownload:
        """Write and validate one bounded immutable snapshot."""

        token, token_directory, destination = self._allocate(filename)
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        decoder = (
            codecs.getincrementaldecoder("utf-8")(errors="strict")
            if media_type == "text/plain"
            else None
        )
        try:
            with destination.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise AttachmentStageError("invalid_content")
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise AttachmentStageError("too_large")
                    if len(prefix) < 5:
                        prefix.extend(chunk[: 5 - len(prefix)])
                    if decoder is not None:
                        try:
                            decoder.decode(chunk, final=False)
                        except UnicodeDecodeError as error:
                            raise AttachmentStageError("invalid_content") from error
                    digest.update(chunk)
                    output.write(chunk)
                if decoder is not None:
                    try:
                        decoder.decode(b"", final=True)
                    except UnicodeDecodeError as error:
                        raise AttachmentStageError("invalid_content") from error

            if size != expected_size:
                raise AttachmentStageError("size_mismatch")
            if media_type == "application/pdf" and bytes(prefix) != b"%PDF-":
                raise AttachmentStageError("invalid_content")

            with self._lock:
                if self._closed:
                    raise AttachmentStageError("closed")
                self._paths[token] = destination
            return AttachmentDownload(
                download_token=token,
                local_path=str(destination.resolve()),
                filename=filename,
                media_type=media_type,
                size_bytes=size,
                sha256=digest.hexdigest(),
            )
        except Exception:
            shutil.rmtree(token_directory, ignore_errors=True)
            raise

    def release(self, token: str) -> bool:
        """Delete one managed staging directory; repeated release is harmless."""

        with self._lock:
            destination = self._paths.pop(token, None)
        if destination is None:
            return False
        shutil.rmtree(destination.parent, ignore_errors=True)
        return True

    def close(self) -> None:
        """Delete every outstanding download and permanently close the store."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            root = self._root
            self._root = None
            self._paths.clear()
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def _allocate(self, filename: str) -> tuple[str, Path, Path]:
        with self._lock:
            if self._closed:
                raise AttachmentStageError("closed")
            if self._root is None:
                self._root = Path(tempfile.mkdtemp(prefix="docmost-attachment-"))
                self._root.chmod(0o700)
            root = self._root
            token = secrets.token_urlsafe(32)
            while token in self._paths or (root / token).exists():
                token = secrets.token_urlsafe(32)
            token_directory = root / token
            token_directory.mkdir(mode=0o700)
        return token, token_directory, token_directory / filename
