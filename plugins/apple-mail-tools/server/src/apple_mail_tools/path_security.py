"""Outgoing attachment validation with a non-overridable denylist."""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .models import AppleMailError, ErrorCode

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_DRAFT_BYTES = 50 * 1024 * 1024
MAX_DRAFT_ATTACHMENTS = 10
_CREDENTIAL_NAME = re.compile(
    r"(?:^|[._-])(password|passwd|secret|secrets|credential|credentials|token|apikey|api-key|auth|oauth|keychain)(?:$|[._-])",
    re.IGNORECASE,
)
def _pem_begin(label: bytes) -> bytes:
    return b"-----BEGIN " + label + b"-----"


_PRIVATE_KEY_MARKERS = tuple(
    _pem_begin(label)
    for label in (
        b"PRIVATE KEY",
        b"RSA PRIVATE KEY",
        b"OPENSSH PRIVATE KEY",
        b"EC PRIVATE KEY",
        b"PGP PRIVATE KEY BLOCK",
    )
)
_BLOCKED_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".kdb", ".keychain", ".keychain-db"}
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


@dataclass(frozen=True)
class ValidatedAttachment:
    path: Path
    size: int
    sha256: str


def validate_outgoing_attachments(
    raw_paths: list[str], *, secrets_root: Path
) -> list[ValidatedAttachment]:
    if len(raw_paths) > MAX_DRAFT_ATTACHMENTS:
        raise AppleMailError(
            ErrorCode.VALIDATION_ERROR,
            f"A draft may include at most {MAX_DRAFT_ATTACHMENTS} attachments",
        )
    home = Path.home().resolve(strict=True)
    resolved_secrets = secrets_root.resolve(strict=False)
    results: list[ValidatedAttachment] = []
    total = 0
    for raw_path in raw_paths:
        if not raw_path or "\x00" in raw_path:
            raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "Attachment path is invalid")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "Attachment path must be absolute")
        _reject_symlink_components(candidate)
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.lstat()
            relative = resolved.relative_to(home)
        except (OSError, ValueError) as error:
            raise AppleMailError(
                ErrorCode.FORBIDDEN_PATH, "Attachment must be a regular file under the home folder"
            ) from error
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise AppleMailError(
                ErrorCode.FORBIDDEN_PATH, "Attachment must be a non-linked regular file"
            )
        if any(part.startswith(".") for part in relative.parts):
            raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "Hidden paths cannot be attached")
        if relative.parts and relative.parts[0].casefold() == "library":
            raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "The Library folder cannot be attached")
        if _is_within(resolved, resolved_secrets):
            raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "Private Codex state cannot be attached")
        lowered_parts = {part.casefold() for part in relative.parts}
        if lowered_parts.intersection({".ssh", ".gnupg", "keychains"}):
            raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "Key material cannot be attached")
        lowered_name = resolved.name.casefold()
        if (
            lowered_name in _BLOCKED_NAMES
            or resolved.suffix.casefold() in _BLOCKED_SUFFIXES
            or _CREDENTIAL_NAME.search(lowered_name)
        ):
            raise AppleMailError(
                ErrorCode.FORBIDDEN_PATH, "Credential-like files cannot be attached"
            )
        size = metadata.st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise AppleMailError(
                ErrorCode.ATTACHMENT_TOO_LARGE,
                f"Each attachment must be at most {MAX_ATTACHMENT_BYTES} bytes",
            )
        total += size
        if total > MAX_DRAFT_BYTES:
            raise AppleMailError(
                ErrorCode.ATTACHMENT_TOO_LARGE,
                f"Draft attachments must total at most {MAX_DRAFT_BYTES} bytes",
            )
        digest = hashlib.sha256()
        first_chunk = b""
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if not first_chunk:
                    first_chunk = chunk[:65_536]
                digest.update(chunk)
        if any(marker in first_chunk for marker in _PRIVATE_KEY_MARKERS):
            raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "Private keys cannot be attached")
        results.append(ValidatedAttachment(resolved, size, digest.hexdigest()))
    return results


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise AppleMailError(ErrorCode.FORBIDDEN_PATH, "Symlinks cannot be attached")
        except FileNotFoundError:
            break


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
