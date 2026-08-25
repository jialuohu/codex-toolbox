"""Private-file checks for POSIX and native Windows."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import cast

from overleaf_tools.errors import ErrorCode, OverleafError

_SYSTEM_SID = "S-1-5-18"
_REPARSE_POINT = 0x400


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


def harden_path(path: Path, *, directory: bool) -> None:
    """Restrict a newly created path to the current account and SYSTEM."""

    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    sid = _windows_current_sid()
    inheritance = "(OI)(CI)F" if directory else "F"
    process = _run_private(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:{inheritance}",
            f"*{_SYSTEM_SID}:{inheritance}",
        ]
    )
    if process.returncode != 0:
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Unable to restrict private Overleaf storage on Windows.",
        )


def _windows_acl_sids(path: Path) -> set[str]:
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
    if isinstance(parsed, dict):
        entries = [cast(dict[str, object], parsed)]
    elif isinstance(parsed, list):
        items = cast(list[object], parsed)
        if not all(isinstance(item, dict) for item in items):
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "Unable to parse private Overleaf ACLs on Windows.",
            )
        entries = cast(list[dict[str, object]], items)
    else:
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Unable to parse private Overleaf ACLs on Windows.",
        )
    if any(entry.get("type") != "Allow" or entry.get("inherited") for entry in entries):
        raise OverleafError(
            ErrorCode.CONFIGURATION_INVALID,
            "Overleaf secret ACLs must contain explicit allow entries only.",
        )
    return {str(entry.get("sid")) for entry in entries}


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
            raise OverleafError(
                ErrorCode.CONFIGURATION_INVALID,
                "Overleaf secret ACLs must allow only the current account and SYSTEM.",
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
