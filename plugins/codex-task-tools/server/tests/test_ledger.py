"""Journal invariants for retries and private coordination state."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from codex_task_tools.ledger import KeyConflict, Ledger, LedgerError


def request_values(payload_hash: str = "payload-a") -> dict[str, str]:
    return {
        "backend_identity": "a" * 64,
        "idempotency_key": "one-request",
        "payload_hash": payload_hash,
        "project_ref": "local:aaaaaaaaaaaaaaaaaaaa:project-1",
        "project_id": "project-1",
        "cwd": "/fixture/codex-toolbox",
        "requested_title": "Fixture title",
        "prompt_hash": "b" * 64,
        "prompt_body": "Harmless fixture prompt",
    }


def test_transactional_reservation_survives_restart_and_rejects_key_reuse(tmp_path: Path) -> None:
    root = tmp_path / "state"
    first = Ledger(root)
    row, created = first.reserve(request_values())
    assert created is True
    assert row["stage"] == "reserved"
    first.update("a" * 64, "one-request", stage="create_sending")
    first.close()

    restarted = Ledger(root)
    restarted.mark_inflight_unknown("a" * 64)
    same, created = restarted.reserve(request_values())
    assert created is False
    assert same["stage"] == "needs_recovery"
    assert same["creation"] == "unknown"
    with pytest.raises(KeyConflict):
        restarted.reserve(request_values("different-payload"))
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(restarted.path.stat().st_mode) == 0o600
    restarted.close()


def test_unsafe_state_directory_and_symlink_are_refused(tmp_path: Path) -> None:
    exposed = tmp_path / "exposed"
    exposed.mkdir(mode=0o755)
    exposed.chmod(0o755)
    with pytest.raises(LedgerError, match="accessible"):
        Ledger(exposed)

    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(safe, target_is_directory=True)
    with pytest.raises(LedgerError, match="symlink"):
        Ledger(alias)


def test_corrupt_ledger_is_not_replaced(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    path = root / "ledger.sqlite3"
    original = b"invalid sqlite state with no recoverable task receipt"
    path.write_bytes(original)
    path.chmod(0o600)
    with pytest.raises(Exception):
        Ledger(root)
    assert path.read_bytes() == original
