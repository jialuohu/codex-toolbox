"""Optional local UserPromptSubmit observation hook for routing experiments.

The hook is inert unless TYPESAFE_ROUTING_HOOK_ENABLED=1. It never forwards,
prints, hashes, or stores the prompt, transcript, working directory, or URL.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_OUTCOMES = frozenset(("evaluated", "abstained", "skipped", "failed", "missed"))
_REASONS = frozenset((
    "private", "uncertain", "disabled", "not_needed", "oversized",
    "inventory_unavailable", "provider_unavailable", "invalid_response",
    "timeout", "stale", "duplicate", "other",
))
_REMINDER = (
    "Review capability routing for this turn. Send Jev only public or synthetic "
    "task and candidate fields after checking eligibility and current tool "
    "availability. Respect explicit skill and permission rules. If routing is "
    "disabled, unsuitable, or unavailable, use ordinary Codex selection and "
    "record a local outcome."
)
_INPUT_LIMIT = 1024 * 1024


def _state_dir(override: Path | None = None) -> Path:
    if override is not None:
        return override
    configured = os.environ.get("TYPESAFE_ROUTING_STATE_DIR")
    if configured:
        return Path(configured)
    plugin_data = os.environ.get("PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data) / "routing"
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_home / "state" / "typesafe-routing"


def _protected_dir(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("state directory must be absolute")
    # Create only our leaf; the selected parent must already exist.
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("state parent is unavailable")
    if not path.exists():
        path.mkdir(mode=0o700)
    mode = path.lstat().st_mode
    if not stat.S_ISDIR(mode) or mode & 0o077:
        raise ValueError("state directory is not private")
    return path


def _write_event(session_id: str, turn_id: str, event: str,
                 outcome: str | None = None, reason_code: str | None = None,
                 state_dir: Path | None = None) -> None:
    if not (_ID.fullmatch(session_id) and _ID.fullmatch(turn_id)):
        raise ValueError("invalid session or turn id")
    if event not in ("observed", "outcome"):
        raise ValueError("invalid event")
    if event == "outcome" and outcome not in _OUTCOMES:
        raise ValueError("invalid routing outcome")
    if reason_code is not None and reason_code not in _REASONS:
        raise ValueError("invalid reason code")
    directory = _protected_dir(_state_dir(state_dir))
    path = directory / "events.jsonl"
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
            raise ValueError("routing event file is not private")
        fcntl.flock(fd, fcntl.LOCK_EX)
        if event == "outcome":
            with os.fdopen(os.dup(fd), "r", encoding="utf-8") as stream:
                stream.seek(0)
                for line in stream:
                    try:
                        prior = json.loads(line)
                    except json.JSONDecodeError:
                        raise ValueError("invalid local routing ledger") from None
                    if (prior.get("event") == "outcome" and prior.get("session_id") == session_id
                            and prior.get("turn_id") == turn_id):
                        raise ValueError("duplicate routing outcome")
        row: dict[str, Any] = {
            "event": event, "session_id": session_id, "turn_id": turn_id,
            "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if outcome is not None:
            row["outcome"] = outcome
        if reason_code is not None:
            row["reason_code"] = reason_code
        os.write(fd, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def record_outcome(session_id: str, turn_id: str, outcome: str,
                   reason_code: str | None = None, *, state_dir: Path | None = None) -> None:
    """Record one terminal outcome without task content; reject duplicate turns."""
    _write_event(session_id, turn_id, "outcome", outcome, reason_code, state_dir)


def summarize_observed(state_dir: Path | None = None) -> dict[str, int]:
    """Count only turns seen by this hook; it cannot detect hooks that never ran."""
    path = _state_dir(state_dir) / "events.jsonl"
    observed: set[tuple[str, str]] = set()
    terminal: dict[tuple[str, str], str] = {}
    if not path.is_file():
        return {"observed": 0, "terminal": 0, "without_terminal": 0}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["session_id"], row["turn_id"])
        if row["event"] == "observed":
            observed.add(key)
        elif row["event"] == "outcome":
            terminal[key] = row["outcome"]
    return {"observed": len(observed), "terminal": len(observed & terminal.keys()),
            "without_terminal": len(observed - terminal.keys())}


def hook_main() -> int:
    if os.environ.get("TYPESAFE_ROUTING_HOOK_ENABLED") != "1":
        return 0
    try:
        raw = sys.stdin.buffer.read(_INPUT_LIMIT + 1)
        if len(raw) > _INPUT_LIMIT:
            return 0
        input_data = json.loads(raw)
        if not isinstance(input_data, dict) or input_data.get("hook_event_name") != "UserPromptSubmit":
            return 0
        session_id, turn_id = input_data.get("session_id"), input_data.get("turn_id")
        if not isinstance(session_id, str) or not isinstance(turn_id, str):
            return 0
        _write_event(session_id, turn_id, "observed")
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return 0  # A broken optional hook cannot block the user turn.
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": _REMINDER,
    }}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    outcome = commands.add_parser("outcome", help="record one terminal result locally")
    outcome.add_argument("--session-id", required=True)
    outcome.add_argument("--turn-id", required=True)
    outcome.add_argument("--outcome", required=True, choices=sorted(_OUTCOMES))
    outcome.add_argument("--reason-code", choices=sorted(_REASONS))
    commands.add_parser("coverage", help="summarize hook-observed turns only")
    args = parser.parse_args()
    if args.command == "outcome":
        record_outcome(args.session_id, args.turn_id, args.outcome, args.reason_code)
        return 0
    if args.command == "coverage":
        print(json.dumps(summarize_observed(), sort_keys=True))
        return 0
    return hook_main()


if __name__ == "__main__":
    raise SystemExit(main())
