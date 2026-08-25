"""Secrets-only Overleaf configuration loading and atomic writes."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from overleaf_tools.errors import ErrorCode, OverleafError
from overleaf_tools.permissions import (
    assert_private,
    ensure_private_directory,
    harden_path,
    is_link_like,
    reject_link_components,
)

_ALIAS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_PROJECT_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,128}")
_TOKEN_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True)
class ProjectConfig:
    alias: str
    project_id: str
    token_path: Path
    display_name: str | None = None


@dataclass(frozen=True)
class ToolboxConfig:
    projects: dict[str, ProjectConfig]
    allowed_import_roots: tuple[Path, ...]


def validate_alias(value: str) -> str:
    if _ALIAS_RE.fullmatch(value) is None:
        raise OverleafError(
            ErrorCode.INVALID_ARGUMENT,
            "Project aliases must use 1-64 ASCII letters, digits, dots, dashes, or underscores.",
        )
    return value


def validate_project_id(value: str) -> str:
    if _PROJECT_ID_RE.fullmatch(value) is None:
        raise OverleafError(ErrorCode.INVALID_ARGUMENT, "The Overleaf project ID is invalid.")
    return value


def validate_token_name(value: str) -> str:
    if _TOKEN_NAME_RE.fullmatch(value) is None:
        raise OverleafError(ErrorCode.INVALID_ARGUMENT, "The token name is invalid.")
    return value


class ConfigStore:
    """Read and update configuration under the private Codex secrets root."""

    def __init__(self, secrets_dir: Path | None = None) -> None:
        if secrets_dir is None:
            raw = os.environ.get("CODEX_SECRETS_DIR")
            if not raw:
                codex_home = os.environ.get("CODEX_HOME")
                home = Path(codex_home) if codex_home else Path.home() / ".codex"
                raw = str(home / "secrets")
            secrets_dir = Path(raw)
        if not secrets_dir.is_absolute():
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "The Overleaf secrets directory must be an absolute path.",
            )
        self.secrets_dir = secrets_dir.absolute()
        self.root = self.secrets_dir / "overleaf-tools"
        self.config_path = self.root / "config.json"

    def initialize(self) -> bool:
        ensure_private_directory(self.root)
        ensure_private_directory(self.root / "tokens")
        ensure_private_directory(self.root / "repos")
        ensure_private_directory(self.root / "locks")
        ensure_private_directory(self.root / "worktrees")
        if self.config_path.exists():
            assert_private(self.config_path, directory=False)
            return False
        self.write_raw({"version": 1, "projects": {}, "allowedImportRoots": []})
        return True

    def _token_path(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or len(pure.parts) != 2
            or pure.parts[0] != "tokens"
            or pure.parts[1] in {"", ".", ".."}
        ):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "tokenFile must name one file under the private tokens directory.",
            )
        validate_token_name(pure.parts[1].removesuffix(".token"))
        if not pure.parts[1].endswith(".token"):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "tokenFile must end in .token.",
            )
        return self.root.joinpath(*pure.parts)

    def read_raw(self) -> dict[str, object]:
        if not self.config_path.exists():
            raise OverleafError(
                ErrorCode.CONFIGURATION_MISSING,
                "Overleaf Tools is not configured. Run overleaf-config init.",
            )
        reject_link_components(self.config_path, stop_at=self.root)
        assert_private(self.root, directory=True)
        assert_private(self.config_path, directory=False)
        try:
            parsed: object = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "The private Overleaf configuration is not valid UTF-8 JSON.",
            ) from exc
        if not isinstance(parsed, dict):
            raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "Configuration must be an object.")
        return cast(dict[str, object], parsed)

    def load(self) -> ToolboxConfig:
        raw = self.read_raw()
        if set(raw) != {"version", "projects", "allowedImportRoots"}:
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "Configuration contains unknown or missing top-level fields.",
            )
        if raw.get("version") != 1:
            raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "Unsupported config version.")
        projects_value = raw.get("projects")
        roots_value = raw.get("allowedImportRoots")
        if not isinstance(projects_value, dict) or not isinstance(roots_value, list):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID, "Configuration fields are invalid."
            )
        raw_projects = cast(dict[object, object], projects_value)
        raw_roots = cast(list[object], roots_value)
        projects: dict[str, ProjectConfig] = {}
        for alias, value_object in raw_projects.items():
            if not isinstance(alias, str) or not isinstance(value_object, dict):
                raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "Project entries are invalid.")
            value = cast(dict[object, object], value_object)
            if not {"projectId", "tokenFile"}.issubset(value) or not set(value).issubset(
                {"projectId", "tokenFile", "displayName"}
            ):
                raise OverleafError(
                    ErrorCode.CONFIGURATION_INVALID,
                    "Project entries contain unknown or missing fields.",
                )
            validate_alias(alias)
            project_id = value.get("projectId")
            token_file = value.get("tokenFile")
            display_name = value.get("displayName")
            if not isinstance(project_id, str) or not isinstance(token_file, str):
                raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "Project fields are invalid.")
            validate_project_id(project_id)
            if display_name is not None and (
                not isinstance(display_name, str)
                or not display_name.strip()
                or len(display_name) > 200
                or any(ord(char) < 32 for char in display_name)
            ):
                raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "displayName is invalid.")
            projects[alias] = ProjectConfig(
                alias=alias,
                project_id=project_id,
                token_path=self._token_path(token_file),
                display_name=display_name,
            )
        roots: list[Path] = []
        for value in raw_roots:
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise OverleafError(
                    ErrorCode.CONFIGURATION_INVALID,
                    "Every allowedImportRoots entry must be an absolute path.",
                )
            path = Path(value)
            if not path.is_dir() or is_link_like(path):
                raise OverleafError(
                    ErrorCode.CONFIGURATION_INVALID,
                    "Every allowed import root must be an existing non-link directory.",
                )
            reject_link_components(path)
            roots.append(path.resolve(strict=True))
        return ToolboxConfig(projects=projects, allowed_import_roots=tuple(roots))

    def project(self, alias: str) -> tuple[ToolboxConfig, ProjectConfig]:
        validate_alias(alias)
        config = self.load()
        project = config.projects.get(alias)
        if project is None:
            raise OverleafError(ErrorCode.PROJECT_NOT_FOUND, "The project alias is not configured.")
        if not project.token_path.exists():
            raise OverleafError(
                ErrorCode.TOKEN_UNAVAILABLE,
                "The configured Overleaf Git token file is missing.",
            )
        assert_private(project.token_path, directory=False)
        return config, project

    def remove_project(self, alias: str) -> None:
        """Atomically remove one configured alias without deleting shared private state."""

        validate_alias(alias)
        raw = self.read_raw()
        projects_value = raw.get("projects")
        if not isinstance(projects_value, dict):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "The projects configuration is invalid.",
            )
        projects = cast(dict[str, object], projects_value)
        if alias not in projects:
            raise OverleafError(
                ErrorCode.PROJECT_NOT_FOUND,
                "The project alias is not configured.",
            )
        del projects[alias]
        self.write_raw(raw)
        self.load()

    def write_raw(self, raw: dict[str, object]) -> None:
        ensure_private_directory(self.root)
        serialized = json.dumps(raw, indent=2, sort_keys=True) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=self.root)
        temporary_path = Path(temporary)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            harden_path(temporary_path, directory=False)
            os.replace(temporary_path, self.config_path)
            harden_path(self.config_path, directory=False)
        finally:
            temporary_path.unlink(missing_ok=True)

    def set_token(self, name: str, token: str) -> Path:
        validate_token_name(name)
        if not token or len(token) > 4096 or any(char in token for char in "\x00\r\n"):
            raise OverleafError(ErrorCode.INVALID_ARGUMENT, "The token value is invalid.")
        self.initialize()
        path = self.root / "tokens" / f"{name}.token"
        descriptor, temporary = tempfile.mkstemp(prefix=f".{name}-", dir=path.parent)
        temporary_path = Path(temporary)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            harden_path(temporary_path, directory=False)
            os.replace(temporary_path, path)
            harden_path(path, directory=False)
        finally:
            temporary_path.unlink(missing_ok=True)
        return path
