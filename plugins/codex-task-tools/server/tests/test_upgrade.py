"""Exceptional legacy upgrade tests use temporary ledgers and mocked App Server/launchd."""

from __future__ import annotations

import asyncio
import base64
import copy
import csv
import fcntl
import hashlib
import io
import os
import plistlib
import shutil
import socket
import sqlite3
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from codex_task_tools import upgrade
from codex_task_tools.ledger import Ledger

BACKEND = "a" * 64


def terminal_ledger(path: Path) -> None:
    ledger = Ledger(path)
    ledger.reserve({
        "backend_identity": BACKEND, "idempotency_key": "fixture", "payload_hash": "b" * 64,
        "project_ref": f"local:{BACKEND[:20]}:project", "project_id": "project", "cwd": "/fixture",
        "requested_title": "Fixture", "prompt_hash": "c" * 64, "prompt_body": "Private fixture content",
    })
    ledger.update(BACKEND, "fixture", task_id="task", turn_id="turn", stage="submitted", creation="created",
                  title_status="verified", submission="accepted", prompt_delivery="verified_once",
                  execution="completed", persistence="verified", backend_membership="verified",
                  prompt_body=None, reason=None)
    ledger.close()


def fixture_layout(tmp_path: Path) -> upgrade.Layout:
    state = tmp_path / "state"
    terminal_ledger(state)
    lock = state / "broker.lock"
    lock.touch(mode=0o600)
    return upgrade.Layout(tmp_path / "venv", tmp_path / "venv/bin/broker", tmp_path / "broker.plist", state)


def change(path: Path, sql: str, parameters: tuple[Any, ...] = ()) -> None:
    with sqlite3.connect(path / "ledger.sqlite3") as db:
        db.execute(sql, parameters)


def test_ledger_proof_is_read_only_and_scans_all_rows(tmp_path: Path) -> None:
    layout = fixture_layout(tmp_path)
    before = {p.name: p.read_bytes() for p in layout.state.iterdir()}
    rows = upgrade._ledger_rows(layout.state, BACKEND)
    assert rows[0]["task_id"] == "task"
    assert "prompt_body" not in rows[0]
    assert {p.name: p.read_bytes() for p in layout.state.iterdir()} == before
    change(layout.state, "UPDATE tasks SET backend_identity=?", ("d" * 64,))
    with pytest.raises(upgrade.UpgradeError, match="foreign"):
        upgrade._ledger_rows(layout.state, BACKEND)


@pytest.mark.parametrize(("column", "value"), [
    ("stage", "reserved"), ("stage", "create_sending"), ("stage", "needs_recovery"),
    ("submission", "unknown"), ("submission", "pending"), ("creation", "unknown"),
    ("title_status", "pending"), ("execution", "inProgress"), ("execution", "unknown"),
    ("execution", "not_started"), ("prompt_delivery", "unverified"), ("prompt_body", "private"),
    ("persistence", "unverified"), ("backend_membership", "unverified"),
    ("reason", "uncertain"), ("task_id", None), ("turn_id", None),
    ("project_ref", "local:foreign:project"),
])
def test_uncertain_or_active_row_blocks_upgrade(tmp_path: Path, column: str, value: Any) -> None:
    layout = fixture_layout(tmp_path)
    change(layout.state, f"UPDATE tasks SET {column}=?", (value,))
    with pytest.raises(upgrade.UpgradeError, match="foreign, active, incomplete, or uncertain"):
        upgrade._ledger_rows(layout.state, BACKEND)


@pytest.mark.parametrize("pending_state", ["pending", "resolved", "unknown"])
def test_any_pending_row_even_foreign_resolved_blocks(tmp_path: Path, pending_state: str) -> None:
    layout = fixture_layout(tmp_path)
    change(layout.state, "INSERT INTO pending VALUES (?,?,?,?,?,?,?,?)",
           ("foreign", "untracked", "request", "generation", "method", "{}", pending_state, 1))
    with pytest.raises(upgrade.UpgradeError, match="approval state"):
        upgrade._ledger_rows(layout.state, BACKEND)


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_journal_files_are_never_ignored_or_repaired(tmp_path: Path, suffix: str) -> None:
    layout = fixture_layout(tmp_path)
    (layout.state / f"ledger.sqlite3{suffix}").write_bytes(b"fixture")
    before = (layout.state / "ledger.sqlite3").read_bytes()
    with pytest.raises(upgrade.UpgradeError, match="journal"):
        upgrade._ledger_rows(layout.state, BACKEND)
    assert (layout.state / "ledger.sqlite3").read_bytes() == before


def test_schema_or_symlink_drift_is_rejected(tmp_path: Path) -> None:
    layout = fixture_layout(tmp_path)
    change(layout.state, "CREATE TABLE surprise (id TEXT)")
    with pytest.raises(upgrade.UpgradeError, match="schema"):
        upgrade._ledger_rows(layout.state, BACKEND)
    alias = tmp_path / "alias"
    alias.symlink_to(layout.state)
    with pytest.raises(upgrade.UpgradeError, match="symlinks"):
        upgrade._ledger_rows(alias, BACKEND)


def thread_result() -> dict[str, Any]:
    return {"thread": {"id": "task", "projectId": "project", "ephemeral": False,
                       "status": {"type": "notLoaded"},
                       "turns": [{"id": "turn", "status": "completed", "itemsView": "full"}]}}


class ReadOnlyApp:
    version = "0.159.0"
    backend_identity = BACKEND
    reader_failed = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.result = thread_result()
        self.closed = False

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert method == "thread/read"
        self.calls.append((method, params))
        return copy.deepcopy(self.result)


def test_proof_reads_only_recorded_thread_and_checks_metadata_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    app = ReadOnlyApp()
    monkeypatch.setattr(upgrade, "AppServerClient", lambda *_args, **_kwargs: app)
    assert asyncio.run(upgrade._proof(layout, {"0.159.0"})) == ("0.159.0", 1)
    assert app.calls == [("thread/read", {"threadId": "task", "includeTurns": False}),
                         ("thread/read", {"threadId": "task", "includeTurns": True})]
    assert app.closed


@pytest.mark.parametrize(("field", "value"), [
    ("id", "another"), ("projectId", "another"), ("ephemeral", True),
    ("status", {"type": "idle"}), ("status", {"type": "active"}),
    ("status", {"type": "notLoaded", "unknown": True}),
])
def test_wrong_identity_or_loaded_metadata_prevents_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: Any,
) -> None:
    layout = fixture_layout(tmp_path)
    app = ReadOnlyApp()
    app.result["thread"][field] = value
    monkeypatch.setattr(upgrade, "AppServerClient", lambda *_args, **_kwargs: app)
    with pytest.raises(upgrade.UpgradeError, match="identity or unloaded"):
        asyncio.run(upgrade._proof(layout, {"0.159.0"}))
    assert len(app.calls) == 1
    assert app.closed


@pytest.mark.parametrize("turns", [
    None, [], [{"id": "other", "status": "completed", "itemsView": "full"}],
    [{"id": "turn", "status": "inProgress", "itemsView": "full"}],
    [{"id": "turn", "status": "completed", "itemsView": "full"}] * 2,
    [{"id": "turn", "status": "failed", "itemsView": "full"}],
    [{"id": "turn", "status": "completed", "itemsView": "summary"}],
    [{"id": "turn", "status": "completed", "itemsView": "notLoaded"}],
    [{"id": "turn", "status": "completed"}],
    [{"id": "turn", "status": {}, "itemsView": "full"}],
    [{"id": "turn", "status": [], "itemsView": "full"}],
])
def test_incomplete_or_active_history_blocks(tmp_path: Path, turns: Any) -> None:
    row = upgrade._ledger_rows(fixture_layout(tmp_path).state, BACKEND)[0]
    result = thread_result()
    result["thread"]["turns"] = turns
    with pytest.raises(upgrade.UpgradeError):
        upgrade._thread(result, row, history=True)


@pytest.mark.parametrize("version", ["0.159.1", "0.160.0", "unsupported", "0.156.1"])
def test_live_exception_requires_exact_0159(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str,
) -> None:
    layout = fixture_layout(tmp_path)
    app = ReadOnlyApp()
    app.version = version
    monkeypatch.setattr(upgrade, "AppServerClient", lambda *_args, **_kwargs: app)
    with pytest.raises(upgrade.UpgradeError, match="exact qualified"):
        asyncio.run(upgrade._proof(layout, {"0.159.0"}))
    assert app.calls == []


def test_truncated_history_and_mid_read_version_change_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    app = ReadOnlyApp()
    app.result["nextCursor"] = "more"
    monkeypatch.setattr(upgrade, "AppServerClient", lambda *_args, **_kwargs: app)
    with pytest.raises(upgrade.UpgradeError, match="completeness"):
        asyncio.run(upgrade._proof(layout, {"0.159.0"}))
    app.result = thread_result()
    original = app.request

    async def change_version(method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await original(method, params)
        app.version = "0.156.1"
        return response

    app.request = change_version  # type: ignore[method-assign]
    with pytest.raises(upgrade.UpgradeError, match="connection changed"):
        asyncio.run(upgrade._proof(layout, {"0.159.0"}))


def disconnected(quiesced: bool = False) -> dict[str, Any]:
    return {"running": True, "backendConnected": False, "appServerVersion": None,
            "backendIdentity": None, "activeTaskCount": None, "pendingApprovalCount": None,
            "quiesced": quiesced, "eventProcessingError": False}


class Lifecycle:
    def __init__(self, layout: upgrade.Layout, monkeypatch: pytest.MonkeyPatch) -> None:
        self.layout = layout
        self.loaded = True
        self.barrier = False
        self.identity = upgrade.Identity(111, "fixture process", (1, 2))
        self.operations: list[str] = []
        self.proofs: list[set[str]] = []
        self.fail_proof = 0
        self.fail_bootout = False
        self.version = "0.159.0"
        monkeypatch.setattr(upgrade, "_provenance", lambda _layout: "pinned")
        monkeypatch.setattr(upgrade, "_identity", lambda _layout: self.identity)
        monkeypatch.setattr(upgrade, "_loaded", lambda: self.loaded)
        monkeypatch.setattr(upgrade, "_fully_stopped", lambda *_args: not self.loaded)
        monkeypatch.setattr(upgrade, "_rpc", self.rpc)
        monkeypatch.setattr(upgrade, "_proof", self.proof)
        monkeypatch.setattr(upgrade.service, "_launchctl", self.launchctl)

    def rpc(self, _layout: upgrade.Layout, _identity: upgrade.Identity, operation: str,
            enabled: bool | None = None) -> dict[str, Any]:
        self.operations.append(f"{operation}:{enabled}")
        if operation == "service_quiesce":
            self.barrier = bool(enabled)
        return disconnected(self.barrier)

    async def proof(self, _layout: upgrade.Layout, allowed: set[str]) -> tuple[str, int]:
        self.proofs.append(allowed)
        self.operations.append("proof")
        if not self.loaded:
            probe = os.open(self.layout.state / "broker.lock", os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(probe)
        if len(self.proofs) == self.fail_proof or self.version not in allowed:
            raise upgrade.UpgradeError("Fixture proof failure")
        return self.version, 1

    def launchctl(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.operations.append(args[0])
        if args[0] == "bootout":
            if self.fail_bootout:
                return subprocess.CompletedProcess(args, 1, "", "")
            self.loaded = False
        elif args[0] == "bootstrap":
            assert not self.loaded
            probe = os.open(self.layout.state / "broker.lock", os.O_RDWR)
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(probe)
            self.loaded = True
        return subprocess.CompletedProcess(args, 0, "", "")


def test_success_proves_again_under_lock_after_full_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    result = upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert result["stopped"] is True
    assert lifecycle.operations == ["service_status:None", "service_quiesce:True", "proof",
                                    "service_status:None", "bootout", "proof"]
    assert lifecycle.proofs == [{"0.159.0"}, {"0.159.0"}]
    assert not lifecycle.loaded


@pytest.mark.parametrize("version", ["0.156.1", "0.159.0"])
def test_already_stopped_legacy_still_requires_proof_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    lifecycle.loaded = False
    lifecycle.version = version
    result = upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert result["appServerVersion"] == version
    assert lifecycle.operations == ["proof"]
    assert lifecycle.proofs == [{"0.156.1", "0.159.0"}]


def test_preexisting_barrier_is_never_released(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    lifecycle.barrier = True
    with pytest.raises(upgrade.UpgradeError, match="disconnected"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert lifecycle.operations == ["service_status:None"]
    assert lifecycle.barrier


def test_pre_stop_failure_releases_only_own_barrier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    lifecycle.fail_proof = 1
    with pytest.raises(upgrade.UpgradeError, match="Fixture"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert lifecycle.operations[-2:] == ["service_status:None", "service_quiesce:False"]
    assert "bootout" not in lifecycle.operations


def test_failed_bootout_releases_own_barrier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    lifecycle.fail_bootout = True
    with pytest.raises(upgrade.UpgradeError, match="Could not stop"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert not lifecycle.barrier
    assert "bootstrap" not in lifecycle.operations


def test_final_failure_restores_only_original_service_after_releasing_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    lifecycle.fail_proof = 2
    with pytest.raises(upgrade.UpgradeError, match="Fixture"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert lifecycle.operations[-1] == "bootstrap"
    assert lifecycle.operations.count("bootstrap") == 1


def test_lock_owned_by_replacement_prevents_proof_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    lifecycle.loaded = False
    fd = upgrade._claim_lock(layout)
    try:
        with pytest.raises(BlockingIOError):
            upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    finally:
        os.close(fd)
    assert lifecycle.operations == []


def test_version_change_between_pre_and_post_stop_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    original = lifecycle.launchctl

    def change_version(*args: str) -> subprocess.CompletedProcess[str]:
        answer = original(*args)
        if args[0] == "bootout":
            lifecycle.version = "0.156.1"
        return answer

    monkeypatch.setattr(upgrade.service, "_launchctl", change_version)
    with pytest.raises(upgrade.UpgradeError, match="Fixture proof"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert lifecycle.operations[-1] == "bootstrap"


def test_lock_path_symlink_and_missing_file_are_not_created(tmp_path: Path) -> None:
    layout = fixture_layout(tmp_path)
    lock = layout.state / "broker.lock"
    lock.unlink()
    with pytest.raises(FileNotFoundError):
        upgrade._claim_lock(layout)
    assert not lock.exists()
    target = layout.state / "target"
    target.touch(mode=0o600)
    lock.symlink_to(target)
    with pytest.raises(upgrade.UpgradeError, match="symlinks"):
        upgrade._claim_lock(layout)


def test_unsupported_upgrade_has_no_runtime_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    with pytest.raises(upgrade.UpgradeError, match="Only the reviewed"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.2")
    assert lifecycle.operations == []


def provenance_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> upgrade.Layout:
    layout = fixture_layout(tmp_path)
    package = layout.venv / "lib/python3.12/site-packages/codex_task_tools"
    package.mkdir(parents=True)
    source = b"# fixture release module\n"
    (package / "broker.py").write_bytes(source)
    digest = hashlib.sha256(source).hexdigest()
    monkeypatch.setattr(upgrade, "LEGACY_HASHES", {"broker.py": digest})
    info = package.parent / "codex_task_tools-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: codex-task-tools\nVersion: 0.1.0\n")
    (info / "entry_points.txt").write_text(
        "[console_scripts]\ncodex-task-tools-broker = codex_task_tools.broker:main\n"
    )
    record = io.StringIO()
    encoded = base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip("=")
    csv.writer(record).writerow(["codex_task_tools/broker.py", f"sha256={encoded}", len(source)])
    (info / "RECORD").write_text(record.getvalue())
    layout.broker.parent.mkdir()
    layout.broker.write_text(
        f"#!{layout.venv}/bin/python3\n# -*- coding: utf-8 -*-\nimport sys\n"
        "from codex_task_tools.broker import main\nif __name__ == \"__main__\":\n"
        "    if sys.argv[0].endswith(\"-script.pyw\"):\n        sys.argv[0] = sys.argv[0][:-11]\n"
        "    elif sys.argv[0].endswith(\".exe\"):\n        sys.argv[0] = sys.argv[0][:-4]\n"
        "    sys.exit(main())\n"
    )
    layout.plist.write_bytes(plistlib.dumps({
        "Label": upgrade.service.LABEL,
        "ProgramArguments": [str(layout.broker), "--state-dir", str(layout.state)],
        "RunAtLoad": True, "KeepAlive": True, "Umask": 0o077, "ProcessType": "Background",
        "StandardOutPath": str(layout.state / "broker.out.log"),
        "StandardErrorPath": str(layout.state / "broker.err.log"),
        "EnvironmentVariables": {"CODEX_HOME": str(layout.state.parent.parent)},
    }))
    layout.plist.chmod(0o600)
    return layout


@pytest.mark.parametrize("mutation", ["module", "extra_module", "metadata", "record", "entry", "plist", "symlink"])
def test_old_release_provenance_rejects_unknown_or_drifted_installations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    layout = provenance_fixture(tmp_path, monkeypatch)
    package = layout.venv / "lib/python3.12/site-packages/codex_task_tools"
    info = package.parent / "codex_task_tools-0.1.0.dist-info"
    assert upgrade._provenance(layout)
    if mutation == "module":
        (package / "broker.py").write_text("# modified source\n")
    elif mutation == "extra_module":
        (package / "unreviewed.py").write_text("# unexpected code\n")
    elif mutation == "metadata":
        (info / "METADATA").write_text("Name: codex-task-tools\nVersion: 0.0.9\n")
    elif mutation == "record":
        (info / "RECORD").write_text("codex_task_tools/broker.py,sha256=wrong,0\n")
    elif mutation == "entry":
        layout.broker.write_text("#!/bin/sh\nexit 0\n")
    elif mutation == "plist":
        content = plistlib.loads(layout.plist.read_bytes())
        content["ProgramArguments"] = ["unrelated-broker"]
        layout.plist.write_bytes(plistlib.dumps(content))
    else:
        target = package / "broker.py"
        original = tmp_path / "original.py"
        target.rename(original)
        target.symlink_to(original)
    with pytest.raises(upgrade.UpgradeError):
        upgrade._provenance(layout)


@pytest.mark.parametrize(("code", "stderr"), [(1, "Permission denied"), (113, "Unknown error"),
                                               (125, "Domain does not support specified action")])
def test_unknown_launchctl_failure_is_not_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, stderr: str,
) -> None:
    layout = fixture_layout(tmp_path)
    monkeypatch.setattr(upgrade, "_provenance", lambda _layout: "pinned")
    calls: list[tuple[str, ...]] = []

    def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, code, "", stderr)

    monkeypatch.setattr(upgrade.service, "_launchctl", launchctl)
    with pytest.raises(upgrade.UpgradeError, match="absence is not proven"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert [args[0] for args in calls] == ["print"]


def test_exact_launchctl_absence_receipt_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    absent = (f'Bad request.\nCould not find service "{upgrade.service.LABEL}" '
              f"in domain for user gui: {os.getuid()}\n")
    monkeypatch.setattr(upgrade.service, "_launchctl",
                        lambda *args: subprocess.CompletedProcess(args, 113, "", absent))
    assert upgrade._loaded() is False


def test_socket_peer_pid_must_match_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    identity = upgrade.Identity(111, "fixture", (1, 2))
    monkeypatch.setattr(upgrade, "_identity", lambda _layout: identity)

    class WrongPeer:
        sent = False

        def __enter__(self) -> WrongPeer:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def settimeout(self, _timeout: int) -> None:
            pass

        def connect(self, _path: str) -> None:
            pass

        def getsockopt(self, level: int, option: int) -> int:
            assert (level, option) == (0, 2)
            return 222

        def sendall(self, _data: bytes) -> None:
            self.sent = True

    client = WrongPeer()
    monkeypatch.setattr(socket, "socket", lambda *_args: client)
    with pytest.raises(upgrade.UpgradeError, match="socket peer"):
        upgrade._rpc(layout, identity, "service_quiesce", True)
    assert not client.sent


def test_replacement_identity_prevents_cleanup_of_someone_elses_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    original = lifecycle.proof

    async def replace_process(candidate: upgrade.Layout, versions: set[str]) -> tuple[str, int]:
        answer = await original(candidate, versions)
        lifecycle.identity = upgrade.Identity(222, "replacement", (2, 3))
        return answer

    monkeypatch.setattr(upgrade, "_proof", replace_process)
    with pytest.raises(upgrade.UpgradeError, match="changed before stop"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert "service_quiesce:False" not in lifecycle.operations
    assert "bootout" not in lifecycle.operations


def test_stop_timeout_never_bootstraps_or_releases_replacement_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    monkeypatch.setattr(upgrade, "_fully_stopped", lambda *_args: False)
    ticks = iter([0.0, 31.0])
    monkeypatch.setattr(upgrade, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _delay: None))
    with pytest.raises(upgrade.UpgradeError, match="did not fully stop"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    # No restore runs while old process/socket disappearance remains unproven.
    assert "bootstrap" not in lifecycle.operations


def test_db_hash_detects_changes_that_preserve_size_and_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    path = layout.state / "ledger.sqlite3"
    original_read = Path.read_bytes
    reads = 0

    def changed_read(candidate: Path) -> bytes:
        nonlocal reads
        value = original_read(candidate)
        if candidate == path:
            reads += 1
            if reads == 2:
                return value[:-1] + bytes([value[-1] ^ 1])
        return value

    monkeypatch.setattr(Path, "read_bytes", changed_read)
    with pytest.raises(upgrade.UpgradeError, match="changed during the read-only"):
        upgrade._ledger_rows(layout.state, BACKEND)


def installation_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> upgrade.Installation:
    project = tmp_path / "candidate"
    package = project / "src/codex_task_tools"
    package.mkdir(parents=True)
    for path in Path(upgrade.__file__).parent.glob("*.py"):
        shutil.copyfile(path, package / path.name)
    (project / "pyproject.toml").write_text('[project]\nname = "codex-task-tools"\nversion = "0.1.1"\n')
    (project / "uv.lock").write_text("# fixture locked candidate\n")
    uv = tmp_path / "uv"
    uv.write_text("#!/bin/sh\nexit 1\n")
    uv.chmod(0o700)

    class Distribution:
        version = "0.1.1"

        def read_text(self, name: str) -> str:
            assert name == "direct_url.json"
            return upgrade.json.dumps({"url": project.as_uri(), "dir_info": {}})

    monkeypatch.setattr(upgrade.importlib.metadata, "distribution", lambda _name: Distribution())
    return upgrade.Installation(project, uv)


def test_candidate_origin_and_source_must_match_executing_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = installation_fixture(tmp_path, monkeypatch)
    assert upgrade._candidate(install)
    other = tmp_path / "different-project"
    shutil.copytree(install.project, other)
    with pytest.raises(upgrade.UpgradeError, match="differs from the executing"):
        upgrade._candidate(upgrade.Installation(other, install.uv))
    (install.project / "src/codex_task_tools/upgrade.py").write_text("# unqualified replacement\n")
    with pytest.raises(upgrade.UpgradeError, match="source differs"):
        upgrade._candidate(install)


def test_two_helpers_cannot_share_the_boolean_quiesce_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    fd = upgrade._claim_upgrade_lock(layout)
    try:
        with pytest.raises(BlockingIOError):
            upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    finally:
        os.close(fd)
    assert lifecycle.operations == []


def assert_lock_held(path: Path) -> None:
    probe = os.open(path, os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(probe)


def test_stable_sync_holds_both_locks_and_clears_inherited_virtual_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = fixture_layout(tmp_path)
    install = installation_fixture(tmp_path, monkeypatch)
    lifecycle = Lifecycle(layout, monkeypatch)
    monkeypatch.setenv("VIRTUAL_ENV", "/unrelated/venv")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/unrelated/project-venv")
    commands: list[list[str]] = []
    finish_marker = upgrade._finish_install_marker

    def finish_while_locked(candidate_layout: upgrade.Layout, marker: upgrade.InstallMarker) -> None:
        assert len(commands) == 1
        assert_lock_held(layout.state / "broker.lock")
        assert_lock_held(layout.state / "upgrade.lock")
        finish_marker(candidate_layout, marker)

    monkeypatch.setattr(upgrade, "_finish_install_marker", finish_while_locked)

    def sync(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert command == [str(install.uv), "sync", "--frozen", "--no-dev", "--no-editable",
                           "--refresh-package", "codex-task-tools", "--project", str(install.project)]
        assert "VIRTUAL_ENV" not in kwargs["env"]
        assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(layout.venv)
        assert_lock_held(layout.state / "broker.lock")
        assert_lock_held(layout.state / "upgrade.lock")
        marker_path = layout.state / upgrade.INSTALL_MARKER
        marker = upgrade.json.loads(marker_path.read_text())
        assert marker["fromVersion"] == "0.1.0"
        assert marker["toVersion"] == "0.1.1"
        assert marker["candidateSha256"] == upgrade._candidate(install)
        assert len(marker["invocation"]) == 32
        assert stat.S_IMODE(marker_path.stat().st_mode) == 0o600
        source = install.project / "src/codex_task_tools"
        site = layout.venv / "lib/python3.12/site-packages"
        shutil.copytree(source, site / "codex_task_tools")
        info = site / "codex_task_tools-0.1.1.dist-info"
        info.mkdir()
        (info / "METADATA").write_text("Name: codex-task-tools\nVersion: 0.1.1\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(upgrade.subprocess, "run", sync)
    result = upgrade.run_upgrade(layout, "0.1.0", "0.1.1", install)
    assert result["runtimeInstalled"] is True
    assert len(commands) == 1
    assert "bootstrap" not in lifecycle.operations
    assert not (layout.state / upgrade.INSTALL_MARKER).exists()


@pytest.mark.parametrize("returncode", [1, 0])
def test_failed_sync_or_missing_installed_candidate_never_restarts_old_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int,
) -> None:
    layout = fixture_layout(tmp_path)
    install = installation_fixture(tmp_path, monkeypatch)
    lifecycle = Lifecycle(layout, monkeypatch)

    def fail_sync(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert_lock_held(layout.state / "broker.lock")
        return subprocess.CompletedProcess(command, returncode, "", "private fixture output")

    monkeypatch.setattr(upgrade.subprocess, "run", fail_sync)
    with pytest.raises((upgrade.UpgradeError, FileNotFoundError)):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1", install)
    assert lifecycle.operations[-1] == "proof"
    assert "bootstrap" not in lifecycle.operations
    assert "service_quiesce:False" not in lifecycle.operations
    marker = layout.state / upgrade.INSTALL_MARKER
    before = marker.read_bytes()
    operations = lifecycle.operations.copy()
    with pytest.raises(upgrade.UpgradeError, match="Interrupted installation"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1", install)
    assert lifecycle.operations == operations
    assert marker.read_bytes() == before


def test_invalid_candidate_blocks_before_quiesce(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = fixture_layout(tmp_path)
    install = installation_fixture(tmp_path, monkeypatch)
    lifecycle = Lifecycle(layout, monkeypatch)
    (install.project / "pyproject.toml").write_text('[project]\nname="other"\nversion="0.1.1"\n')
    with pytest.raises(upgrade.UpgradeError, match="not the qualified"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1", install)
    assert lifecycle.operations == []


@pytest.mark.parametrize("directory_info", [{}, {"editable": False}, {"editable": True},
                                           {"editable": 0}, {"unknown": False}, []])
def test_only_canonical_noneditable_candidate_origins_are_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory_info: Any,
) -> None:
    install = installation_fixture(tmp_path, monkeypatch)

    class Distribution:
        version = "0.1.1"

        def read_text(self, _name: str) -> str:
            return upgrade.json.dumps({"url": install.project.as_uri(), "dir_info": directory_info})

    monkeypatch.setattr(upgrade.importlib.metadata, "distribution", lambda _name: Distribution())
    if directory_info == {} or (isinstance(directory_info, dict) and directory_info.get("editable") is False):
        assert upgrade._candidate(install)
    else:
        with pytest.raises(upgrade.UpgradeError, match="differs from the executing"):
            upgrade._candidate(install)


def test_malformed_project_metadata_is_a_fixed_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = installation_fixture(tmp_path, monkeypatch)
    (install.project / "pyproject.toml").write_text('project=["private fixture"]\n')
    with pytest.raises(upgrade.UpgradeError, match="not the qualified"):
        upgrade._candidate(install)


def test_missing_distribution_is_reported_without_private_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    layout = fixture_layout(tmp_path)
    monkeypatch.setattr(upgrade.Layout, "current", lambda _state: layout)
    monkeypatch.setattr(upgrade.service.sys, "argv", ["upgrade", "--from-version", "0.1.0", "--to-version", "0.1.1",
                                                    "--install-project", str(tmp_path),
                                                    "--uv-executable", str(tmp_path)])

    def missing(*_args: Any) -> dict[str, Any]:
        raise upgrade.importlib.metadata.PackageNotFoundError("private fixture detail")

    monkeypatch.setattr(upgrade, "run_upgrade", missing)
    assert upgrade.main() == 1
    result = capsys.readouterr().out
    assert upgrade.json.loads(result)["ok"] is False
    assert "private fixture detail" not in result


@pytest.mark.parametrize("entry_type", ["file", "directory", "broken_symlink"])
def test_preexisting_install_marker_blocks_before_any_broker_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_type: str,
) -> None:
    layout = fixture_layout(tmp_path)
    lifecycle = Lifecycle(layout, monkeypatch)
    marker = layout.state / upgrade.INSTALL_MARKER
    if entry_type == "file":
        marker.write_text('{"fromVersion":"0.1.0","toVersion":"0.1.1"}')
    elif entry_type == "directory":
        marker.mkdir()
    else:
        marker.symlink_to(tmp_path / "missing")
    with pytest.raises(upgrade.UpgradeError, match="Interrupted installation"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1")
    assert lifecycle.operations == []
    assert os.path.lexists(marker)
    assert not (layout.state / "upgrade.lock").exists()


@pytest.mark.parametrize("mutation", ["contents", "inode", "permissions", "symlink", "hardlink"])
def test_marker_cleanup_never_removes_changed_or_unowned_marker(tmp_path: Path, mutation: str) -> None:
    layout = fixture_layout(tmp_path)
    marker = upgrade._begin_install_marker(layout, "a" * 64)
    if mutation == "contents":
        marker.path.write_bytes(marker.contents.replace(b"0.1.1", b"0.1.2"))
    elif mutation == "inode":
        replacement = layout.state / "replacement.json"
        replacement.write_bytes(marker.contents)
        replacement.chmod(0o600)
        replacement.replace(marker.path)
    elif mutation == "permissions":
        marker.path.chmod(0o644)
    elif mutation == "symlink":
        target = layout.state / "other.json"
        target.write_bytes(marker.contents)
        target.chmod(0o600)
        marker.path.unlink()
        marker.path.symlink_to(target)
    else:
        os.link(marker.path, layout.state / "hardlink.json")
    with pytest.raises(upgrade.UpgradeError):
        upgrade._finish_install_marker(layout, marker)
    assert os.path.lexists(marker.path)


def test_same_invocation_marker_clears_after_verification_only(tmp_path: Path) -> None:
    layout = fixture_layout(tmp_path)
    marker = upgrade._begin_install_marker(layout, "b" * 64)
    with pytest.raises(FileExistsError):
        upgrade._begin_install_marker(layout, "c" * 64)
    assert marker.path.read_bytes() == marker.contents
    upgrade._finish_install_marker(layout, marker)
    assert not marker.path.exists()


@pytest.mark.parametrize("failure", ["timeout", "interrupted", "stopped_changed"])
def test_interrupted_or_unverified_installation_retains_marker_and_blocks_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    layout = fixture_layout(tmp_path)
    install = installation_fixture(tmp_path, monkeypatch)
    lifecycle = Lifecycle(layout, monkeypatch)

    def interrupted(_layout: upgrade.Layout, _install: upgrade.Installation, _candidate: str) -> None:
        assert_lock_held(layout.state / "broker.lock")
        assert (layout.state / upgrade.INSTALL_MARKER).is_file()
        if failure == "timeout":
            raise subprocess.TimeoutExpired("fixture uv", 300)
        if failure == "interrupted":
            raise KeyboardInterrupt
        lifecycle.loaded = True

    monkeypatch.setattr(upgrade, "_sync_candidate", interrupted)
    expected = {"timeout": subprocess.TimeoutExpired, "interrupted": KeyboardInterrupt,
                "stopped_changed": upgrade.UpgradeError}[failure]
    with pytest.raises(expected):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1", install)
    marker = layout.state / upgrade.INSTALL_MARKER
    assert marker.is_file()
    assert "bootstrap" not in lifecycle.operations
    assert "service_quiesce:False" not in lifecycle.operations
    operations = lifecycle.operations.copy()
    with pytest.raises(upgrade.UpgradeError, match="Interrupted installation"):
        upgrade.run_upgrade(layout, "0.1.0", "0.1.1", install)
    assert lifecycle.operations == operations
