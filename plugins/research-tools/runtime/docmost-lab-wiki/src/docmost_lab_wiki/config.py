"""Strict per-device configuration for the private Lab Wiki."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from docmost_lab_wiki.constants import MODEL_FILE, MODEL_FILE_SHA256, MODEL_FILE_SIZE

_ENV_LINE = re.compile(r"([A-Z][A-Z0-9_]*)=(.*)\Z")
_ALLOWED_KEYS = {
    "DOCMOST_LAB_WIKI_VAULT",
    "DOCMOST_LAB_WIKI_ROOT",
    "DOCMOST_LAB_WIKI_INDEX",
    "DOCMOST_LAB_WIKI_MODEL_PATH",
}


class ConfigurationError(RuntimeError):
    """A sanitized local configuration failure."""


@dataclass(frozen=True)
class WikiConfig:
    secrets_dir: Path
    config_file: Path
    vault: Path
    wiki_root_relative: PurePosixPath
    wiki_root: Path
    index_path: Path
    model_path: Path

    def validate_model(self) -> None:
        """Verify the exact pinned ONNX asset before any embedding operation."""

        import hashlib

        model_file = self.model_path / MODEL_FILE
        if not model_file.is_file() or model_file.is_symlink():
            raise ConfigurationError("Pinned Lab Wiki embedding model is missing or unsafe")
        if model_file.stat().st_size != MODEL_FILE_SIZE:
            raise ConfigurationError("Pinned Lab Wiki embedding model checksum is invalid")
        digest = hashlib.sha256()
        with model_file.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != MODEL_FILE_SHA256:
            raise ConfigurationError("Pinned Lab Wiki embedding model checksum is invalid")
        if not (self.model_path / "tokenizer.json").is_file():
            raise ConfigurationError("Pinned Lab Wiki tokenizer is missing")


def load_config(*, require_vault: bool = True) -> WikiConfig:
    """Load one mode-0600 env file without shell evaluation."""

    secrets_dir = _secrets_directory()
    config_file = secrets_dir / "docmost-lab-wiki.env"
    if not config_file.is_file() or config_file.is_symlink():
        raise ConfigurationError("Lab Wiki configuration is missing or unsafe")
    if stat.S_IMODE(config_file.stat().st_mode) != 0o600:
        raise ConfigurationError("Lab Wiki configuration must have mode 600")
    values: dict[str, str] = {}
    try:
        for raw_line in config_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = _ENV_LINE.fullmatch(line)
            if match is None or match.group(1) not in _ALLOWED_KEYS:
                raise ConfigurationError("Lab Wiki configuration contains an unsupported entry")
            value = match.group(2)
            if not value or "\x00" in value or "\n" in value or "\r" in value:
                raise ConfigurationError("Lab Wiki configuration contains an invalid value")
            values[match.group(1)] = value
    except UnicodeError as error:
        raise ConfigurationError("Lab Wiki configuration is not valid UTF-8") from error

    required = _ALLOWED_KEYS - values.keys()
    if required:
        raise ConfigurationError("Lab Wiki configuration is incomplete")
    vault = Path(values["DOCMOST_LAB_WIKI_VAULT"])
    index_path = Path(values["DOCMOST_LAB_WIKI_INDEX"])
    model_path = Path(values["DOCMOST_LAB_WIKI_MODEL_PATH"])
    if not all(path.is_absolute() for path in (vault, index_path, model_path)):
        raise ConfigurationError("Lab Wiki paths must be absolute")
    if require_vault and (not vault.is_dir() or vault.is_symlink()):
        raise ConfigurationError("Pinned Obsidian vault is missing or unsafe")
    relative = PurePosixPath(values["DOCMOST_LAB_WIKI_ROOT"])
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ConfigurationError("Lab Wiki root must be a safe vault-relative path")
    wiki_root = vault.joinpath(*relative.parts)
    try:
        wiki_root.relative_to(vault)
    except ValueError as error:
        raise ConfigurationError("Lab Wiki root escapes the pinned vault") from error
    if index_path == vault or vault in index_path.parents:
        raise ConfigurationError("Private Lab Wiki index must remain outside the vault")
    if model_path == vault or vault in model_path.parents:
        raise ConfigurationError("Lab Wiki model must remain outside the vault")
    if index_path == secrets_dir or secrets_dir not in index_path.parents:
        raise ConfigurationError("Private Lab Wiki index must remain beneath CODEX_SECRETS_DIR")
    return WikiConfig(
        secrets_dir=secrets_dir,
        config_file=config_file,
        vault=vault,
        wiki_root_relative=relative,
        wiki_root=wiki_root,
        index_path=index_path,
        model_path=model_path,
    )


def _secrets_directory() -> Path:
    raw = os.environ.get("CODEX_SECRETS_DIR")
    if raw:
        path = Path(raw)
    else:
        codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        path = codex_root / "secrets"
    if not path.is_absolute() or path.is_symlink():
        raise ConfigurationError("CODEX_SECRETS_DIR is missing or unsafe")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise ConfigurationError("CODEX_SECRETS_DIR is unavailable") from error
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ConfigurationError("CODEX_SECRETS_DIR must be private")
    return path
