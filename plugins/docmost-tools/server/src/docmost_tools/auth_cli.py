"""Command-line entry point for isolated Docmost browser authentication."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import TextIO

from pydantic import ValidationError

from docmost_tools.auth import AuthService
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode, OperationError, OperationResult
from docmost_tools.profile import ProfilePathError, profile_paths
from docmost_tools.runtime import CONFIGURATION_INVALID_MESSAGE


def main(argv: Sequence[str] | None = None, *, output: TextIO | None = None) -> int:
    """Run one browser-profile operation and emit its stable JSON envelope."""

    parser = argparse.ArgumentParser(prog="docmost-auth")
    parser.add_argument("command", choices=("login", "status", "logout"))
    args = parser.parse_args(argv)
    destination = output
    if destination is None:
        import sys

        destination = sys.stdout
    try:
        paths = profile_paths()
    except ProfilePathError:
        result: OperationResult[dict[str, object]] = OperationResult[dict[str, object]](
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
