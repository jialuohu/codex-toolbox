"""Private paths and local Apple Mail configuration."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .models import AppleMailError, ErrorCode

DEFAULT_EXCLUSIONS = (
    "Junk",
    "Junk Email",
    "Spam",
    "Trash",
    "Deleted Items",
    "Deleted Messages",
)
DEFAULT_TRASH_NAMES = ("Trash", "Deleted Items", "Deleted Messages")


@dataclass(frozen=True)
class Settings:
    allow_unencrypted_index: bool
    excluded_mailbox_names: tuple[str, ...]
    trash_mailbox_names: tuple[str, ...]


@dataclass(frozen=True)
class RuntimePaths:
    codex_home: Path
    secrets_root: Path
    state_root: Path
    config_file: Path
    signing_key: Path
    index_file: Path
    intent_file: Path
    leases_root: Path
    requests_root: Path

    @classmethod
    def from_environment(cls) -> RuntimePaths:
        codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().absolute()
        secrets_root = (
            Path(os.environ.get("CODEX_SECRETS_DIR", str(codex_home / "secrets")))
            .expanduser()
            .absolute()
        )
        state_root = secrets_root / "apple-mail-tools"
        return cls(
            codex_home=codex_home,
            secrets_root=secrets_root,
            state_root=state_root,
            config_file=state_root / "config.json",
            signing_key=state_root / "handle.key",
            index_file=state_root / "mail-index.sqlite3",
            intent_file=state_root / "intents.sqlite3",
            leases_root=state_root / "leases",
            requests_root=state_root / "requests",
        )

    def ensure(self) -> None:
        _ensure_private_directory(self.secrets_root)
        _ensure_private_directory(self.state_root)
        _ensure_private_directory(self.leases_root)
        _ensure_private_directory(self.requests_root)
        if not self.config_file.exists():
            _write_private_json(
                self.config_file,
                {
                    "version": 1,
                    "allow_unencrypted_index": False,
                    "excluded_mailbox_names": list(DEFAULT_EXCLUSIONS),
                    "trash_mailbox_names": list(DEFAULT_TRASH_NAMES),
                },
            )
        _validate_private_regular(self.config_file)
        if not self.signing_key.exists():
            _write_private_bytes(self.signing_key, os.urandom(32))
        _validate_private_regular(self.signing_key)
        if len(self.signing_key.read_bytes()) != 32:
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Signing key is invalid")

    def load_settings(self) -> Settings:
        _validate_private_regular(self.config_file)
        try:
            raw: Any = json.loads(self.config_file.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise AppleMailError(
                ErrorCode.CONFIGURATION_INVALID, "Apple Mail configuration is invalid"
            ) from error
        if not isinstance(raw, dict):
            raise AppleMailError(
                ErrorCode.CONFIGURATION_INVALID, "Apple Mail configuration version is invalid"
            )
        config = cast(dict[str, Any], raw)
        if config.get("version") != 1:
            raise AppleMailError(
                ErrorCode.CONFIGURATION_INVALID, "Apple Mail configuration version is invalid"
            )
        allow = config.get("allow_unencrypted_index", False)
        excluded = config.get("excluded_mailbox_names", list(DEFAULT_EXCLUSIONS))
        trash = config.get("trash_mailbox_names", list(DEFAULT_TRASH_NAMES))
        if not isinstance(allow, bool):
            raise AppleMailError(
                ErrorCode.CONFIGURATION_INVALID, "allow_unencrypted_index must be boolean"
            )
        return Settings(
            allow_unencrypted_index=allow,
            excluded_mailbox_names=_validated_names(excluded, "excluded_mailbox_names"),
            trash_mailbox_names=_validated_names(trash, "trash_mailbox_names"),
        )


def _validated_names(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, f"{field} is invalid")
    items = cast(list[Any], value)
    if len(items) > 100:
        raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, f"{field} is invalid")
    names: list[str] = []
    for item in items:
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 200
            or any(ord(character) < 32 for character in item)
        ):
            raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, f"{field} is invalid")
        names.append(item.strip())
    return tuple(dict.fromkeys(names))


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Private directory is unsafe")
    if path.exists() and not path.is_dir():
        raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Private directory is unsafe")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    metadata = path.stat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Private directory is unsafe")


def _validate_private_regular(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Private file is missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise AppleMailError(ErrorCode.CONFIGURATION_INVALID, "Private file is unsafe")


def _write_private_bytes(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, value)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    _write_private_bytes(path, (json.dumps(value, indent=2) + "\n").encode())
