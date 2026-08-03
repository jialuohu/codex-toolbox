"""Bounded headless Docmost session smoke check for local setup."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from pydantic import ValidationError

from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode, OperationError, OperationResult
from docmost_tools.profile import ProfilePathError, profile_paths
from docmost_tools.runtime import CONFIGURATION_INVALID_MESSAGE, bootstrap_runtime


def _failure(code: ErrorCode, message: str, *, retryable: bool = False) -> OperationResult[Any]:
    return OperationResult[Any](
        ok=False,
        error=OperationError(code=code, message=message, retryable=retryable),
    )


def run_smoke() -> OperationResult[dict[str, object]]:
    """Verify the authenticated identity and a bounded space listing once."""
    try:
        settings = DocmostSettings.model_validate({})
        paths = profile_paths()
    except (ProfilePathError, ValidationError):
        return _failure(ErrorCode.CONFIGURATION_INVALID, CONFIGURATION_INVALID_MESSAGE)

    state = bootstrap_runtime(settings, paths)
    try:
        if state.startup_error is not None:
            return OperationResult[dict[str, object]](ok=False, error=state.startup_error)
        if state.client is None:
            return _failure(ErrorCode.INTERNAL_ERROR, "Docmost smoke bootstrap was unavailable")
        identity = state.client.current_user()
        if not identity.ok:
            assert identity.error is not None
            return OperationResult[dict[str, object]](ok=False, error=identity.error)
        spaces = state.client.list_spaces(limit=1)
        if not spaces.ok:
            assert spaces.error is not None
            return OperationResult[dict[str, object]](ok=False, error=spaces.error)
        return OperationResult[dict[str, object]](
            ok=True,
            data={
                "current_user": identity.data.model_dump(mode="json") if identity.data else {},
                "spaces": spaces.data.model_dump(mode="json") if spaces.data else {},
            },
        )
    finally:
        state.close()


def main(argv: Sequence[str] | None = None, *, output: TextIO | None = None) -> int:
    """Emit one stable, secret-free JSON operation envelope."""
    del argv
    result = run_smoke()
    destination = sys.stdout if output is None else output
    json.dump(result.model_dump(mode="json"), destination)
    destination.write("\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
