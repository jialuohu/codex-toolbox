"""Command-line entry point for isolated Docmost browser authentication."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from docmost_tools.auth import AuthService
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode, OperationError, OperationResult
from docmost_tools.profile import ProfilePathError, profile_paths
from docmost_tools.runtime import CONFIGURATION_INVALID_MESSAGE
from docmost_tools.runtime_lock import (
    LOCK_FD_ENV,
    LOCK_MODE_ENV,
    LockMode,
    validate_inherited_lock,
)

AUTH_LOCK_INVALID_MESSAGE = "Docmost authentication runtime lock is invalid"


def _has_required_runtime_lock(command: str) -> bool:
    mode: LockMode = "shared" if command == "status" else "exclusive"
    if os.environ.get(LOCK_MODE_ENV) != mode:
        return False
    raw_descriptor = os.environ.get(LOCK_FD_ENV)
    if raw_descriptor is None or not raw_descriptor.isdecimal():
        return False
    descriptor = int(raw_descriptor)
    if descriptor <= 2:
        return False
    raw_codex_home = os.environ.get("CODEX_HOME")
    codex_home = Path(raw_codex_home).expanduser() if raw_codex_home else Path.home() / ".codex"
    return validate_inherited_lock(codex_home / "runtime", mode, descriptor)


def main(argv: Sequence[str] | None = None, *, output: TextIO | None = None) -> int:
    """Run one browser-profile operation and emit its stable JSON envelope."""

    parser = argparse.ArgumentParser(prog="docmost-auth")
    parser.add_argument("command", choices=("login", "status", "logout"))
    args = parser.parse_args(argv)
    destination = output
    if destination is None:
        import sys

        destination = sys.stdout
    if not _has_required_runtime_lock(args.command):
        result: OperationResult[dict[str, object]] = OperationResult[dict[str, object]](
            ok=False,
            error=OperationError(
                code=ErrorCode.CONFIGURATION_INVALID,
                message=AUTH_LOCK_INVALID_MESSAGE,
            ),
        )
    else:
        try:
            paths = profile_paths()
        except ProfilePathError:
            result = OperationResult[dict[str, object]](
                ok=False,
                error=OperationError(
                    code=ErrorCode.CONFIGURATION_INVALID,
                    message=CONFIGURATION_INVALID_MESSAGE,
                ),
            )
        else:
            if args.command == "logout":
                result = AuthService.logout_paths(paths)
            else:
                try:
                    service = AuthService(DocmostSettings.model_validate({}), paths)
                except ValidationError:
                    result = OperationResult[dict[str, object]](
                        ok=False,
                        error=OperationError(
                            code=ErrorCode.CONFIGURATION_INVALID,
                            message=CONFIGURATION_INVALID_MESSAGE,
                        ),
                    )
                else:
                    result = service.login() if args.command == "login" else service.status()
    json.dump(result.model_dump(mode="json"), destination)
    destination.write("\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
