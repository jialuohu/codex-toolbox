"""Minimal Git askpass helper that never places the token in argv or a URL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from overleaf_tools.errors import OverleafError
from overleaf_tools.permissions import assert_private


def main() -> int:
    prompt = sys.argv[1].lower() if len(sys.argv) > 1 else "password"
    if "username" in prompt:
        print("git")
        return 0
    raw_path = os.environ.get("OVERLEAF_TOKEN_FILE")
    if not raw_path:
        return 1
    path = Path(raw_path)
    try:
        assert_private(path, directory=False)
        token = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, OverleafError):
        return 1
    if not token or any(char in token for char in "\x00\r\n"):
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
