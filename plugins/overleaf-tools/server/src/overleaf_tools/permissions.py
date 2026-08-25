"""Private-file checks for POSIX and native Windows."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from overleaf_tools.errors import ErrorCode, OverleafError

_SYSTEM_SID = "S-1-5-18"
_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class _WindowsAclEntry:
    sid: str
    access_type: str
    inherited: bool


class _WindowsAcl(Protocol):
    def AddAccessAllowedAceEx(
        self, revision: int, flags: int, access_mask: int, sid: object
    ) -> None: ...


class _WindowsSecurity(Protocol):
    ACL_REVISION_DS: int
    DACL_SECURITY_INFORMATION: int
    PROTECTED_DACL_SECURITY_INFORMATION: int
    SE_FILE_OBJECT: int

    def ACL(self) -> _WindowsAcl: ...

    def GetBinarySid(self, sid: str) -> object: ...

    def SetNamedSecurityInfo(
        self,
        object_name: str,
        object_type: int,
        security_info: int,
        owner: object | None,
        group: object | None,
        dacl: _WindowsAcl,
        sacl: object | None,
    ) -> None: ...


class _WindowsSecurityConstants(Protocol):
    CONTAINER_INHERIT_ACE: int
    FILE_ALL_ACCESS: int
    OBJECT_INHERIT_ACE: int


def _load_windows_security_modules() -> tuple[
    _WindowsSecurity, _WindowsSecurityConstants
]:
    security = cast(
        _WindowsSecurity, cast(object, import_module("win32security"))
    )
    constants = cast(
        _WindowsSecurityConstants, cast(object, import_module("ntsecuritycon"))
    )
    return security, constants


def is_link_like(path: Path) -> bool:
    """Return whether a path is a symlink, junction, or other reparse point."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt" and getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def reject_link_components(path: Path, *, stop_at: Path | None = None) -> None:
    """Reject an existing link-like component between path and stop_at."""

    absolute = path.absolute()
    stop = stop_at.absolute() if stop_at is not None else None
    current = absolute
    while True:
        if current.exists() and is_link_like(current):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "Private Overleaf paths must not contain symlinks, junctions, or reparse points.",
            )
        if current == current.parent or current == stop:
            break
        current = current.parent


def _run_private(
    command: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        input=input_text,
        text=True,
        timeout=30,
    )


def _windows_current_sid() -> str:
    process = _run_private(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
        ]
    )
    sid = process.stdout.strip()
    if process.returncode != 0 or not sid.startswith("S-"):
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Unable to resolve the current Windows account for private Overleaf storage.",
        )
    return sid


def _harden_windows_path(path: Path, *, directory: bool) -> None:
    sid = _windows_current_sid()
    try:
        security, constants = _load_windows_security_modules()
        acl = security.ACL()
        flags = (
            constants.CONTAINER_INHERIT_ACE | constants.OBJECT_INHERIT_ACE
            if directory
            else 0
        )
        for allowed_sid in (sid, _SYSTEM_SID):
            acl.AddAccessAllowedAceEx(
                security.ACL_REVISION_DS,
                flags,
                constants.FILE_ALL_ACCESS,
                security.GetBinarySid(allowed_sid),
            )
        security.SetNamedSecurityInfo(
            str(path),
            security.SE_FILE_OBJECT,
            security.DACL_SECURITY_INFORMATION
            | security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            acl,
            None,
        )
    except Exception as error:
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Unable to restrict private Overleaf storage on Windows.",
        ) from error


def harden_path(path: Path, *, directory: bool) -> None:
    """Restrict a newly created path to the current account and SYSTEM."""

    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    _harden_windows_path(path, directory=directory)


def _windows_acl_entries(path: Path) -> tuple[_WindowsAclEntry, ...]:
    script = (
        "$p=[Console]::In.ReadToEnd();"
        "$a=(Get-Acl -LiteralPath $p).Access | ForEach-Object {"
        "[pscustomobject]@{sid=$_.IdentityReference.Translate("
        "[System.Security.Principal.SecurityIdentifier]).Value;"
        "type=$_.AccessControlType.ToString();inherited=$_.IsInherited}};"
        "$a | ConvertTo-Json -Compress"
    )
    process = _run_private(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        input_text=str(path),
    )
    if process.returncode != 0:
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Unable to validate private Overleaf storage on Windows.",
        )
    raw = process.stdout.strip()
    parsed: object = [] if not raw else json.loads(raw)
    raw_entries: list[object]
    if isinstance(parsed, dict):
        raw_entries = [parsed]
    elif isinstance(parsed, list):
        raw_entries = cast(list[object], parsed)
    else:
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Unable to parse private Overleaf ACLs on Windows.",
        )
    entries: list[_WindowsAclEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "Unable to parse private Overleaf ACLs on Windows.",
            )
        entry = cast(dict[str, object], raw_entry)
        raw_sid = entry.get("sid")
        raw_type = entry.get("type")
        raw_inherited = entry.get("inherited")
        if (
            not isinstance(raw_sid, str)
            or not raw_sid.startswith("S-")
            or not isinstance(raw_type, str)
            or raw_type not in {"Allow", "Deny"}
            or not isinstance(raw_inherited, bool)
        ):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "Unable to parse private Overleaf ACLs on Windows.",
            )
        entries.append(
            _WindowsAclEntry(
                sid=raw_sid,
                access_type=raw_type,
                inherited=raw_inherited,
            )
        )
    return tuple(entries)


def _windows_acl_sids(path: Path) -> set[str]:
    entries = _windows_acl_entries(path)
    if any(entry.access_type != "Allow" or entry.inherited for entry in entries):
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Overleaf secret ACLs must contain explicit allow entries only.",
        )
    return {entry.sid for entry in entries}


def assert_private(path: Path, *, directory: bool) -> None:
    """Validate a private path without changing its permissions."""

    if not path.exists() or is_link_like(path):
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Required private Overleaf storage is missing or link-backed.",
        )
    info = path.stat()
    if directory and not stat.S_ISDIR(info.st_mode):
        raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "Expected a private directory.")
    if not directory and not stat.S_ISREG(info.st_mode):
        raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "Expected a private regular file.")
    if os.name == "nt":
        allowed = {_windows_current_sid(), _SYSTEM_SID}
        actual = _windows_acl_sids(path)
        if actual != allowed:
            missing_count = len(allowed - actual)
            unexpected_count = len(actual - allowed)
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "Overleaf secret ACLs must allow only the current account and SYSTEM. "
                f"Missing allowed identities: {missing_count}; unexpected identities: "
                f"{unexpected_count}.",
            )
        return
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Overleaf secret paths must be owned by the current user and not "
            "group/world accessible.",
        )


def ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_link_components(path)
    harden_path(path, directory=True)
    assert_private(path, directory=True)
