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
        service = AuthService(DocmostSettings.model_validate({}), profile_paths())
    except (ProfilePathError, ValidationError) as error:
        result: OperationResult[dict[str, object]] = OperationResult[dict[str, object]](
            ok=False,
            error=OperationError(code=ErrorCode.CONFIGURATION_INVALID, message=str(error)),
        )
    else:
        if args.command == "login":
            result = service.login()
        elif args.command == "status":
            result = service.status()
        else:
            result = service.logout()
    json.dump(result.model_dump(mode="json"), destination)
    destination.write("\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
