"""Guarded access to one outgoing local PDF for Docmost upload."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

MAX_PDF_BYTES = 50 * 1024 * 1024

PdfValidationKind = Literal[
    "forbidden_path",
    "unsupported_attachment",
    "attachment_too_large",
    "conflict",
]

_CREDENTIAL_NAME = re.compile(
    r"(?:^|[._-])"
    r"(password|passwd|secret|secrets|credential|credentials|token|apikey|api-key|auth|oauth|keychain)"
    r"(?:$|[._-])",
    re.IGNORECASE,
)
_BLOCKED_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".kdb",
    ".keychain",
    ".keychain-db",
}
_BLOCKED_NAMES = {
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "known_hosts",
    "authorized_keys",
    "credentials",
    "credentials.json",
}
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class PdfValidationError(RuntimeError):
    """Stable validation failure that never includes local paths or file content."""

    def __init__(self, kind: PdfValidationKind) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class ValidatedPdf:
    """An open, validated PDF descriptor held stable for one upload call."""

    path: Path
    filename: str
    size_bytes: int
    sha256: str
    stream: BinaryIO
    metadata_identity: tuple[int, int, int, int, int, int]

    def assert_stable(self) -> None:
        """Reject any metadata change while the caller retains this descriptor."""

        try:
            current = os.fstat(self.stream.fileno())
        except OSError as error:
            raise PdfValidationError("conflict") from error
        identity = (
            current.st_dev,
            current.st_ino,
            current.st_mode,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
        )
        if identity != self.metadata_identity:
            raise PdfValidationError("conflict")


class PdfUploadValidator:
    """Open one safe home-rooted PDF without following links or rereading its path."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        secrets_root: Path | None = None,
        max_bytes: int = MAX_PDF_BYTES,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        try:
            self._home = (Path.home() if home is None else home).resolve(strict=True)
        except OSError as error:
            raise ValueError("home must resolve to an existing directory") from error
        if not self._home.is_dir():
            raise ValueError("home must resolve to an existing directory")
        self._secrets_root = (
            self._default_secrets_root(self._home)
            if secrets_root is None
            else secrets_root.resolve(strict=False)
        )
        self._max_bytes = max_bytes

    @contextmanager
    def open(self, raw_path: str, expected_sha256: str) -> Iterator[ValidatedPdf]:
        """Validate, hash, and retain one immutable file descriptor until upload completes."""

        if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
            raise PdfValidationError("conflict")
        path, relative = self._resolve_path(raw_path)
        try:
            descriptor = self._open_beneath_home(relative)
        except OSError as error:
            raise PdfValidationError("forbidden_path") from error

        stream = os.fdopen(descriptor, "rb", closefd=True)
        try:
            try:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise PdfValidationError("forbidden_path")
                if before.st_size < 1:
                    raise PdfValidationError("unsupported_attachment")
                if before.st_size > self._max_bytes:
                    raise PdfValidationError("attachment_too_large")

                digest = hashlib.sha256()
                prefix = b""
                while chunk := stream.read(1024 * 1024):
                    if not prefix:
                        prefix = chunk[:5]
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
                stream.seek(0)
            except OSError as error:
                raise PdfValidationError("conflict") from error
            if self._identity(before) != self._identity(after):
                raise PdfValidationError("conflict")
            if prefix != b"%PDF-":
                raise PdfValidationError("unsupported_attachment")
            actual_sha256 = digest.hexdigest()
            if actual_sha256 != expected_sha256:
                raise PdfValidationError("conflict")
            identity = self._identity(after)
            yield ValidatedPdf(
                path=path,
                filename=path.name,
                size_bytes=before.st_size,
                sha256=actual_sha256,
                stream=stream,
                metadata_identity=identity,
            )
        finally:
            stream.close()

    def _resolve_path(self, raw_path: str) -> tuple[Path, Path]:
        if not raw_path or _CONTROL_PATTERN.search(raw_path):
            raise PdfValidationError("forbidden_path")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            raise PdfValidationError("forbidden_path")
        self._reject_symlink_components(candidate)
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(self._home)
        except (OSError, ValueError) as error:
            raise PdfValidationError("forbidden_path") from error
        if not relative.parts or any(part.startswith(".") for part in relative.parts):
            raise PdfValidationError("forbidden_path")
        lowered_parts = {part.casefold() for part in relative.parts}
        if relative.parts[0].casefold() == "library" or lowered_parts.intersection(
            {".ssh", ".gnupg", "keychains", "keys", "private-keys", "private_keys"}
        ):
            raise PdfValidationError("forbidden_path")
        if self._is_within(resolved, self._secrets_root):
            raise PdfValidationError("forbidden_path")
        lowered_name = resolved.name.casefold()
        if (
            len(resolved.name) > 512
            or lowered_name in _BLOCKED_NAMES
            or resolved.stem.casefold() in _BLOCKED_NAMES
            or any(suffix.casefold() in _BLOCKED_SUFFIXES for suffix in resolved.suffixes)
            or _CREDENTIAL_NAME.search(lowered_name)
            or any(_CREDENTIAL_NAME.search(part.casefold()) for part in relative.parts)
        ):
            raise PdfValidationError("forbidden_path")
        if resolved.suffix.casefold() != ".pdf":
            raise PdfValidationError("unsupported_attachment")
        return resolved, relative

    def _open_beneath_home(self, relative: Path) -> int:
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_fd = os.open(self._home, directory_flags)
        try:
            for part in relative.parts[:-1]:
                child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child_fd
            return os.open(relative.name, file_flags, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _reject_symlink_components(path: Path) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise PdfValidationError("forbidden_path")
            except FileNotFoundError:
                break
            except OSError as error:
                raise PdfValidationError("forbidden_path") from error

    @staticmethod
    def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _default_secrets_root(home: Path) -> Path:
        configured = os.environ.get("CODEX_SECRETS_DIR")
        if configured:
            return Path(configured).resolve(strict=False)
        codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
        return (codex_home / "secrets").resolve(strict=False)
