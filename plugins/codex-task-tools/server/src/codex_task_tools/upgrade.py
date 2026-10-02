"""One bounded stop path for the known 0.1.0 broker stranded by Desktop 0.159.0.

This never writes the ledger or issues thread mutation RPCs. The installer runs
the qualified candidate in isolation; only after a guarded stop and final proof
does it replace the stable environment while retaining exclusive broker ownership.
Readback is not atomic with external thread loads. Normal service stop remains strict.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import fcntl
import hashlib
import importlib.metadata
import io
import json
import os
import re
import socket
import sqlite3
import stat
import subprocess
import time
import tomllib
import uuid
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Any

from . import service
from .app_server import AppServerClient, AppServerError, strict_json
from .broker import state_directory

# Source bytes at toolbox commit 3a8a678. No installed code is imported or run.
LEGACY_HASHES = {
    "__init__.py": "c5b463535925ec8e494d360922efbeb7ff44a26c62cfed562b29d2730efa01dc",
    "app_server.py": "07a99096bce5e6e2196b8cffda24137f080f80699ae920654fde0d39ec8df936",
    "broker.py": "cc67645d239643875d741715ddc093514a956dea96eedf643c8ce6ca6fa420ed",
    "ipc.py": "725d0be60cc9ef0449569a2b3e177222c0f10f2f871b165c589746dbff3d7788",
    "ledger.py": "2f97108ed11d4641eb7792c3da0405f4b56ded9624eeb2c9d62445857e20d895",
    "service.py": "7c2a7e3afae4af4a7d7c2bfc5b8c74109df7816614f873be7c92aecde2a7f022",
    "mcp_server.py": "629b2102cbce0b98e556cd861962b9d9714d4dc2fb331a453b453e107a78d69e",
    "recover.py": "6768fde445c849c9b2a16307de2c77bcfa15cc2c3889966016f30cf780086387",
}
LEGACY_SCHEMA_HASH = "46df5ad47d554b45467235d3b64eb837e75adff27452f0166337e59603aa43ef"
TERMINAL = {"completed", "failed", "interrupted"}
APP_VERSION = "0.159.0"
INSTALL_MARKER = "upgrade-install.json"


class UpgradeError(service.ServiceError):
    """Only fixed, content-free diagnostics are emitted to the installer."""


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_path(path: Path, kind: str, *, private: bool = True) -> os.stat_result:
    if not path.is_absolute() or ".." in path.parts:
        raise UpgradeError("Upgrade path must be absolute and canonical")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        entry = current.lstat()
        if stat.S_ISLNK(entry.st_mode):
            raise UpgradeError("Upgrade paths may not traverse symlinks")
    entry = path.lstat()
    kinds = {"file": stat.S_ISREG, "dir": stat.S_ISDIR, "socket": stat.S_ISSOCK}
    if (not kinds[kind](entry.st_mode) or entry.st_uid != os.getuid()
            or stat.S_IMODE(entry.st_mode) & (0o077 if private else 0o022)):
        raise UpgradeError("Upgrade path ownership, type, or permissions are unsafe")
    return entry


@dataclass(frozen=True)
class Layout:
    venv: Path
    broker: Path
    plist: Path
    state: Path

    @classmethod
    def current(cls, state: Path) -> Layout:
        venv, broker, plist = service._paths()
        if state != state_directory().expanduser().absolute():
            raise UpgradeError("Upgrade state directory does not match the configured broker")
        return cls(venv, broker, plist, state)


@dataclass(frozen=True)
class Installation:
    project: Path
    uv: Path


@dataclass(frozen=True)
class InstallMarker:
    path: Path
    device: int
    inode: int
    contents: bytes


def _no_install_marker(layout: Layout) -> None:
    if os.path.lexists(layout.state / INSTALL_MARKER):
        raise UpgradeError("Interrupted installation requires reviewed recovery; broker must remain unloaded")


def _sync_state_directory(layout: Layout) -> None:
    descriptor = os.open(layout.state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _begin_install_marker(layout: Layout, candidate: str) -> InstallMarker:
    """Leave durable evidence before any stable-environment replacement can begin."""
    _safe_path(layout.state, "dir")
    path = layout.state / INSTALL_MARKER
    contents = (json.dumps({"schemaVersion": 1, "fromVersion": "0.1.0", "toVersion": "0.1.1",
                           "candidateSha256": candidate, "invocation": uuid.uuid4().hex},
                          sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        opened = os.fstat(descriptor)
        current = _safe_path(path, "file")
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise UpgradeError("Installation marker ownership changed before replacement")
        _sync_state_directory(layout)
        return InstallMarker(path, opened.st_dev, opened.st_ino, contents)
    finally:
        os.close(descriptor)


def _finish_install_marker(layout: Layout, marker: InstallMarker) -> None:
    """Remove only the exact marker created and verified by this invocation."""
    if marker.path != layout.state / INSTALL_MARKER:
        raise UpgradeError("Installation marker is outside the owned state directory")
    entry = _safe_path(marker.path, "file")
    if ((entry.st_dev, entry.st_ino) != (marker.device, marker.inode)
            or entry.st_nlink != 1 or stat.S_IMODE(entry.st_mode) != 0o600
            or entry.st_size != len(marker.contents)):
        raise UpgradeError("Installation marker ownership changed; reviewed recovery is required")
    descriptor = os.open(marker.path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if ((opened.st_dev, opened.st_ino) != (marker.device, marker.inode)
                or os.read(descriptor, len(marker.contents) + 1) != marker.contents):
            raise UpgradeError("Installation marker contents changed; reviewed recovery is required")
        current = marker.path.lstat()
        if (current.st_dev, current.st_ino) != (marker.device, marker.inode):
            raise UpgradeError("Installation marker changed before completion")
        marker.path.unlink()
        _sync_state_directory(layout)
    finally:
        os.close(descriptor)


def _candidate(install: Installation) -> str:
    """Bind installation to the non-editable candidate that is executing this helper."""
    _safe_path(install.project, "dir", private=False)
    _safe_path(install.uv, "file", private=False)
    if not os.access(install.uv, os.X_OK):
        raise UpgradeError("Qualified uv executable is unavailable")
    project_file, lock_file = install.project / "pyproject.toml", install.project / "uv.lock"
    for path in (project_file, lock_file):
        _safe_path(path, "file", private=False)
    project = tomllib.loads(project_file.read_text()).get("project")
    if not isinstance(project, dict) or (project.get("name"), project.get("version")) != (
            "codex-task-tools", "0.1.1"):
        raise UpgradeError("Candidate project is not the qualified 0.1.1 package")
    distribution = importlib.metadata.distribution("codex-task-tools")
    origin = strict_json(distribution.read_text("direct_url.json") or "{}")
    directory_info = origin.get("dir_info") if isinstance(origin, dict) else None
    noneditable = isinstance(directory_info, dict) and (
        not directory_info or (set(directory_info) == {"editable"} and directory_info["editable"] is False)
    )
    if (distribution.version != "0.1.1" or not isinstance(origin, dict)
            or origin.get("url") != install.project.as_uri() or not noneditable):
        raise UpgradeError("Installation project differs from the executing isolated candidate")
    source = install.project / "src/codex_task_tools"
    running = Path(__file__).absolute().parent
    _safe_path(source, "dir", private=False)
    names = {path.name for path in source.iterdir() if path.name != "__pycache__"}
    if (not names or names != {path.name for path in running.iterdir() if path.name != "__pycache__"}
            or any(not name.endswith(".py") for name in names)):
        raise UpgradeError("Candidate package file inventory differs from the executing helper")
    digest_parts = [project_file.read_bytes(), lock_file.read_bytes(), install.uv.read_bytes()]
    for name in sorted(names):
        _safe_path(source / name, "file", private=False)
        raw = (source / name).read_bytes()
        if raw != (running / name).read_bytes():
            raise UpgradeError("Candidate package source differs from the executing helper")
        digest_parts.append(raw)
    return _hash(b"\0".join(digest_parts))


def _sync_candidate(layout: Layout, install: Installation, candidate: str) -> None:
    """Called only while both upgrade serialization and broker ownership locks are held."""
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    environment["UV_PROJECT_ENVIRONMENT"] = str(layout.venv)
    result = subprocess.run(
        [str(install.uv), "sync", "--frozen", "--no-dev", "--no-editable",
         "--refresh-package", "codex-task-tools", "--project", str(install.project)],
        env=environment, capture_output=True, text=True, check=False, timeout=300,
    )
    if result.returncode:
        raise UpgradeError("Stable runtime installation failed; do not restart a possibly partial environment")
    if _candidate(install) != candidate:
        raise UpgradeError("Candidate changed during installation; stable runtime requires review")
    site = layout.venv / "lib/python3.12/site-packages"
    package = site / "codex_task_tools"
    source = install.project / "src/codex_task_tools"
    _safe_path(package, "dir", private=False)
    names = {path.name for path in source.iterdir() if path.name != "__pycache__"}
    if {path.name for path in package.iterdir() if path.name != "__pycache__"} != names:
        raise UpgradeError("Installed candidate package inventory does not match")
    for name in names:
        _safe_path(package / name, "file", private=False)
        if (package / name).read_bytes() != (source / name).read_bytes():
            raise UpgradeError("Installed candidate source does not match")
    infos = list(site.glob("codex_task_tools-*.dist-info"))
    if len(infos) != 1 or infos[0].name != "codex_task_tools-0.1.1.dist-info":
        raise UpgradeError("Installed distribution version is not exactly 0.1.1")
    _safe_path(infos[0] / "METADATA", "file", private=False)
    metadata = Parser().parsestr((infos[0] / "METADATA").read_text())
    if metadata.get_all("Name") != ["codex-task-tools"] or metadata.get_all("Version") != ["0.1.1"]:
        raise UpgradeError("Installed candidate distribution metadata does not match")


def _provenance(layout: Layout) -> str:
    """Bind the complete old Python package, entry point, and exact owned plist."""
    _safe_path(layout.state, "dir")
    _safe_path(layout.venv, "dir", private=False)
    _safe_path(layout.broker, "file", private=False)
    _safe_path(layout.plist, "file")
    expected_plist = {
        "Label": service.LABEL,
        "ProgramArguments": [str(layout.broker), "--state-dir", str(layout.state)],
        "RunAtLoad": True, "KeepAlive": True, "Umask": 0o077, "ProcessType": "Background",
        "StandardOutPath": str(layout.state / "broker.out.log"),
        "StandardErrorPath": str(layout.state / "broker.err.log"),
        "EnvironmentVariables": {"CODEX_HOME": str(layout.state.parent.parent)},
    }
    raw_plist = layout.plist.read_bytes()
    if service.plistlib.loads(raw_plist) != expected_plist:
        raise UpgradeError("LaunchAgent does not match the known toolbox broker")
    sites = list((layout.venv / "lib").glob("python3.12/site-packages"))
    if len(sites) != 1:
        raise UpgradeError("Legacy Python package location is unsupported")
    site = sites[0]
    package = site / "codex_task_tools"
    _safe_path(package, "dir", private=False)
    if {p.name for p in package.iterdir() if p.name != "__pycache__"} != set(LEGACY_HASHES):
        raise UpgradeError("Legacy package contains unexpected files")
    digest_parts = [raw_plist]
    for name, digest in LEGACY_HASHES.items():
        source = package / name
        _safe_path(source, "file", private=False)
        raw = source.read_bytes()
        if _hash(raw) != digest:
            raise UpgradeError("Legacy broker source does not match the qualified 0.1.0 release")
        digest_parts.append(raw)
    infos = list(site.glob("codex_task_tools-*.dist-info"))
    if len(infos) != 1 or infos[0].name != "codex_task_tools-0.1.0.dist-info":
        raise UpgradeError("Legacy distribution version is not exactly 0.1.0")
    info = infos[0]
    for name in ("METADATA", "RECORD", "entry_points.txt"):
        _safe_path(info / name, "file", private=False)
    metadata = Parser().parsestr((info / "METADATA").read_text())
    if metadata.get_all("Name") != ["codex-task-tools"] or metadata.get_all("Version") != ["0.1.0"]:
        raise UpgradeError("Legacy distribution metadata does not match")
    entry_points = (info / "entry_points.txt").read_text()
    if "codex-task-tools-broker = codex_task_tools.broker:main" not in entry_points:
        raise UpgradeError("Legacy broker entry point does not match")
    raw_entry = layout.broker.read_bytes()
    expected_entry = (
        f"#!{layout.venv}/bin/python3\n# -*- coding: utf-8 -*-\nimport sys\n"
        "from codex_task_tools.broker import main\nif __name__ == \"__main__\":\n"
        "    if sys.argv[0].endswith(\"-script.pyw\"):\n        sys.argv[0] = sys.argv[0][:-11]\n"
        "    elif sys.argv[0].endswith(\".exe\"):\n        sys.argv[0] = sys.argv[0][:-4]\n"
        "    sys.exit(main())\n"
    ).encode()
    if raw_entry != expected_entry:
        raise UpgradeError("Legacy executable wrapper does not match")
    record_rows = list(csv.reader(io.StringIO((info / "RECORD").read_text())))
    if any(len(row) != 3 for row in record_rows) or len({r[0] for r in record_rows}) != len(record_rows):
        raise UpgradeError("Legacy distribution RECORD is invalid")
    records = {row[0]: row for row in record_rows}
    for name, digest in LEGACY_HASHES.items():
        row = records.get(f"codex_task_tools/{name}")
        encoded = base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip("=")
        if row is None or row[1] != f"sha256={encoded}" or row[2] != str((package / name).stat().st_size):
            raise UpgradeError("Legacy distribution RECORD does not bind the source")
    digest_parts.extend([raw_entry, (info / "METADATA").read_bytes(),
                         (info / "RECORD").read_bytes(), entry_points.encode()])
    return _hash(b"\0".join(digest_parts))


@dataclass(frozen=True)
class Identity:
    pid: int
    process: str
    socket_identity: tuple[int, int]


def _launch_state() -> subprocess.CompletedProcess[str] | None:
    printed = service._launchctl("print", f"{service._domain()}/{service.LABEL}")
    if printed.returncode == 0:
        return printed
    # Observed launchctl 113 is specific to an absent service in this owned GUI
    # domain. Permission errors, missing domains, or transport failures are unknown.
    absent = (f'Bad request.\nCould not find service "{service.LABEL}" '
              f"in domain for user gui: {os.getuid()}\n")
    if printed.returncode == 113 and printed.stdout == "" and printed.stderr == absent:
        return None
    raise UpgradeError("LaunchAgent state is unknown; absence is not proven")


def _loaded() -> bool:
    return _launch_state() is not None


def _identity(layout: Layout) -> Identity:
    printed = _launch_state()
    if printed is None:
        raise UpgradeError("Owned LaunchAgent is absent")
    pids = re.findall(r"^\s*pid = ([1-9][0-9]*)\s*$", printed.stdout, re.MULTILINE)
    if printed.returncode or len(pids) != 1:
        raise UpgradeError("Owned LaunchAgent has no unique live broker process")
    pid = int(pids[0])
    proc = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "uid=,lstart=,command="],
                          capture_output=True, text=True, check=False, timeout=10)
    lines = proc.stdout.strip().splitlines()
    if proc.returncode or len(lines) != 1:
        raise UpgradeError("Legacy broker process identity is unavailable")
    fields = lines[0].split(maxsplit=6)
    expected = f"{layout.venv}/bin/python3 {layout.broker} --state-dir {layout.state}"
    if len(fields) != 7 or fields[0] != str(os.getuid()) or fields[6] != expected:
        raise UpgradeError("LaunchAgent process does not execute the known stable broker")
    entry = _safe_path(layout.state / "broker.sock", "socket")
    return Identity(pid, lines[0], (entry.st_dev, entry.st_ino))


def _rpc(layout: Layout, identity: Identity, operation: str, enabled: bool | None = None) -> dict[str, Any]:
    if _identity(layout) != identity:
        raise UpgradeError("Broker identity changed during upgrade coordination")
    if operation not in {"service_status", "service_quiesce"}:
        raise UpgradeError("Unsupported upgrade coordination request")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(120 if operation == "service_quiesce" else 10)
        client.connect(str(layout.state / "broker.sock"))
        # Darwin sys/un.h: SOL_LOCAL=0, LOCAL_PEERPID=2.
        if client.getsockopt(0, 2) != identity.pid:
            raise UpgradeError("Broker socket peer does not match the LaunchAgent PID")
        params = {} if enabled is None else {"enabled": enabled}
        client.sendall(json.dumps({"operation": operation, "params": params}).encode() + b"\n")
        chunks = bytearray()
        while b"\n" not in chunks:
            block = client.recv(4096)
            if not block or len(chunks) + len(block) > 65536:
                raise UpgradeError("Broker coordination response is incomplete")
            chunks.extend(block)
        answer = strict_json(bytes(chunks))
    if _identity(layout) != identity:
        raise UpgradeError("Broker identity changed during upgrade coordination")
    if not isinstance(answer, dict) or answer.get("ok") is not True or not isinstance(answer.get("result"), dict):
        raise UpgradeError("Broker did not confirm upgrade coordination")
    return answer["result"]


def _disconnected(status: dict[str, Any], *, quiesced: bool) -> None:
    expected = {"running": True, "backendConnected": False, "appServerVersion": None,
                "backendIdentity": None, "activeTaskCount": None, "pendingApprovalCount": None,
                "quiesced": quiesced, "eventProcessingError": False}
    if status != expected:
        raise UpgradeError("Legacy broker is not in the qualified disconnected state")


def _no_journals(state: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        if os.path.lexists(state / f"ledger.sqlite3{suffix}"):
            raise UpgradeError("Legacy ledger has a journal or concurrent database state")


def _ledger_rows(state: Path, backend: str) -> list[dict[str, Any]]:
    """Read every backend and pending row without creating or repairing a database."""
    _safe_path(state, "dir")
    path = state / "ledger.sqlite3"
    original = _safe_path(path, "file")
    _no_journals(state)
    original_hash = _hash(path.read_bytes())
    db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1, isolation_level=None)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name").fetchall()
        normalized = [list(row[:3]) + [" ".join(row[3].split()) if row[3] else None] for row in schema]
        if _hash(json.dumps(normalized, separators=(",", ":")).encode()) != LEGACY_SCHEMA_HASH:
            raise UpgradeError("Legacy ledger schema is not the qualified 0.1.0 schema")
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise UpgradeError("Legacy ledger integrity is unverified")
        if db.execute("SELECT COUNT(*) FROM pending").fetchone()[0] != 0:
            raise UpgradeError("Legacy ledger contains pending or historical approval state")
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(
            "SELECT backend_identity,task_id,turn_id,project_id,project_ref,stage,creation,title_status,"
            "submission,prompt_delivery,execution,persistence,backend_membership,"
            "prompt_body IS NULL AS prompt_cleared,reason IS NULL AS reason_cleared FROM tasks"
        )]
        for row in rows:
            exact = {"backend_identity": backend, "stage": "submitted", "title_status": "verified",
                     "submission": "accepted", "prompt_delivery": "verified_once", "persistence": "verified",
                     "backend_membership": "verified", "prompt_cleared": 1, "reason_cleared": 1}
            if (any(row[key] != value for key, value in exact.items())
                    or row["creation"] not in {"created", "adopted"} or row["execution"] not in TERMINAL
                    or any(not isinstance(row[key], str) or not row[key]
                           for key in ("task_id", "turn_id", "project_id"))
                    or row["project_ref"] != f"local:{backend[:20]}:{row['project_id']}"):
                raise UpgradeError("Legacy ledger contains foreign, active, incomplete, or uncertain task state")
        db.execute("COMMIT")
    finally:
        db.close()
    current = _safe_path(path, "file")
    if (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns) != (
            current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns
    ) or _hash(path.read_bytes()) != original_hash:
        raise UpgradeError("Legacy ledger changed during the read-only proof")
    _no_journals(state)
    return rows


def _thread(result: dict[str, Any], row: dict[str, Any], *, history: bool) -> None:
    thread = result.get("thread")
    if (not isinstance(thread, dict) or thread.get("id") != row["task_id"]
            or thread.get("projectId") != row["project_id"] or thread.get("ephemeral") is not False
            or thread.get("status") != {"type": "notLoaded"}):
        raise UpgradeError("Tracked thread identity or unloaded status is not verified")
    # Qualified ThreadReadResponse has no pagination fields. Never accept partial history.
    for value in (result, thread):
        if any(key in value for key in ("nextCursor", "cursor", "hasMore", "truncated")):
            raise UpgradeError("Tracked thread history completeness is unverified")
    if history:
        turns = thread.get("turns")
        if not isinstance(turns, list) or not turns:
            raise UpgradeError("Tracked thread has no complete turn history")
        ids: list[str] = []
        for turn in turns:
            if (not isinstance(turn, dict) or not isinstance(turn.get("id"), str) or not turn["id"]
                    or not isinstance(turn.get("status"), str) or turn["status"] not in TERMINAL
                    or turn.get("itemsView") != "full"):
                raise UpgradeError("Tracked thread contains active or unknown turns")
            ids.append(turn["id"])
        if len(set(ids)) != len(ids) or row["turn_id"] not in ids:
            raise UpgradeError("Recorded turn is missing or duplicated in live history")
        recorded = turns[ids.index(row["turn_id"])]
        if recorded["status"] != row["execution"]:
            raise UpgradeError("Recorded turn terminal status differs from the ledger")


async def _proof(layout: Layout, allowed_versions: set[str]) -> tuple[str, int]:
    app = AppServerClient(layout.state.parent.parent, timeout=30)
    try:
        await app.connect()
        version = app.version
        if version not in allowed_versions or not re.fullmatch(r"[a-f0-9]{64}", app.backend_identity):
            raise UpgradeError("Upgrade requires an exact qualified Desktop backend")
        rows = _ledger_rows(layout.state, app.backend_identity)
        for row in rows:
            # Loaded paginated threads may persist during includeTurns reads in 0.159.0.
            # Establish notLoaded first, and reject any change on the full-history read.
            metadata = await app.request("thread/read", {"threadId": row["task_id"], "includeTurns": False})
            _thread(metadata, row, history=False)
            result = await app.request("thread/read", {"threadId": row["task_id"], "includeTurns": True})
            _thread(result, row, history=True)
        if app.version != version or app.reader_failed:
            raise UpgradeError("Qualified App Server connection changed during the proof")
        if _ledger_rows(layout.state, app.backend_identity) != rows:
            raise UpgradeError("Legacy ledger changed during live readback")
        return version, len(rows)
    finally:
        await app.close()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _fully_stopped(layout: Layout, old: Identity | None) -> bool:
    return (not _loaded() and not os.path.lexists(layout.state / "broker.sock")
            and (old is None or not _pid_alive(old.pid)))


def _claim_lock(layout: Layout) -> int:
    path = layout.state / "broker.lock"
    before = _safe_path(path, "file")
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)  # Existing file only; never create or unlink it.
    try:
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise UpgradeError("Broker lock changed while acquiring it")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _restore(layout: Layout, old: Identity | None, provenance: str) -> None:
    """Restore unchanged launchd registration only after the old owner is gone.

    The caller releases its lock immediately before bootstrap: the original broker
    must acquire that lock itself. launchctl bootstrap atomically refuses duplicate
    registration, and the broker lock prevents a second journal owner.
    """
    if _provenance(layout) != provenance or not _fully_stopped(layout, old):
        raise UpgradeError("Upgrade stopped safely; automatic service restoration is not proven safe")
    result = service._launchctl("bootstrap", service._domain(), str(layout.plist))
    if result.returncode:
        raise UpgradeError("Upgrade stopped safely; original service restoration failed")


def _claim_upgrade_lock(layout: Layout) -> int:
    """Serialize helpers before any shared Boolean quiesce barrier is observed."""
    _safe_path(layout.state, "dir")
    path = layout.state / "upgrade.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        opened = os.fstat(fd)
        current = _safe_path(path, "file")
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise UpgradeError("Upgrade lock changed while acquiring it")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


def run_upgrade(
    layout: Layout, from_version: str, to_version: str, install: Installation | None = None,
) -> dict[str, Any]:
    if (from_version, to_version) != ("0.1.0", "0.1.1"):
        raise UpgradeError("Only the reviewed 0.1.0 to 0.1.1 upgrade is supported")
    _no_install_marker(layout)
    serialization_fd = _claim_upgrade_lock(layout)
    try:
        return _run_locked(layout, from_version, to_version, install)
    finally:
        os.close(serialization_fd)


def _run_locked(
    layout: Layout, from_version: str, to_version: str, install: Installation | None,
) -> dict[str, Any]:
    _no_install_marker(layout)
    candidate = _candidate(install) if install is not None else None
    provenance = _provenance(layout)
    old: Identity | None = None
    own_barrier = False
    stopped = False
    lock_fd: int | None = None
    success = False
    installation_started = False
    # A broker absent from the outset cannot reconnect or dispatch. Its existing
    # 0.156.1 support remains valid; a live disconnected 0.1.0 owner requires 0.159.0.
    allowed_versions = {"0.156.1", APP_VERSION}
    try:
        if _loaded():
            old = _identity(layout)
            _disconnected(_rpc(layout, old, "service_status"), quiesced=False)
            # Once sent, the barrier belongs to this invocation even if its reply is lost.
            own_barrier = True
            _disconnected(_rpc(layout, old, "service_quiesce", True), quiesced=True)
            version, _count = asyncio.run(_proof(layout, {APP_VERSION}))
            allowed_versions = {version}
            if _provenance(layout) != provenance or _identity(layout) != old:
                raise UpgradeError("Legacy ownership or source changed before stop")
            _disconnected(_rpc(layout, old, "service_status"), quiesced=True)
            if service._launchctl("bootout", f"{service._domain()}/{service.LABEL}").returncode:
                raise UpgradeError("Could not stop the qualified legacy LaunchAgent")
            deadline = time.monotonic() + 30
            while not _fully_stopped(layout, old):
                if time.monotonic() >= deadline:
                    raise UpgradeError("Legacy broker did not fully stop; stable runtime must remain unchanged")
                time.sleep(0.25)
            stopped = True
        else:
            # Crash recovery still requires the same full proof under the existing lock.
            if not _fully_stopped(layout, None):
                raise UpgradeError("Unloaded legacy broker has unresolved process or socket state")
            stopped = True
        lock_fd = _claim_lock(layout)
        if not _fully_stopped(layout, old) or _provenance(layout) != provenance:
            raise UpgradeError("Legacy ownership or source changed after lock acquisition")
        version, task_count = asyncio.run(_proof(layout, allowed_versions))
        if not _fully_stopped(layout, old) or _provenance(layout) != provenance:
            raise UpgradeError("Legacy ownership or source changed during final proof")
        if install is not None:
            if _candidate(install) != candidate:
                raise UpgradeError("Installation candidate changed before stable replacement")
            # No rollback claim or automatic old-service restart is safe from here onward.
            installation_started = True
            assert candidate is not None
            marker = _begin_install_marker(layout, candidate)
            _sync_candidate(layout, install, candidate)
            if not _fully_stopped(layout, old):
                raise UpgradeError("LaunchAgent changed during installation; verify the new runtime before startup")
            _finish_install_marker(layout, marker)
        success = True
        return {"ok": True, "fromVersion": from_version, "toVersion": to_version,
                "appServerVersion": version, "stopped": True, "runtimeInstalled": install is not None,
                "verifiedTerminalTaskCount": task_count}
    finally:
        restore = False
        try:
            if not success and not installation_started and stopped and lock_fd is not None and old is not None:
                # Establish restoration eligibility while still excluding any new owner.
                restore = _fully_stopped(layout, old) and _provenance(layout) == provenance
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
        if restore:
            _restore(layout, old, provenance)
        elif not success and not installation_started and own_barrier and old is not None:
            # Never release a pre-existing barrier or one belonging to a replacement PID.
            try:
                if _provenance(layout) == provenance and _identity(layout) == old:
                    _disconnected(_rpc(layout, old, "service_status"), quiesced=True)
                    _disconnected(_rpc(layout, old, "service_quiesce", False), quiesced=False)
            except (UpgradeError, OSError, AppServerError):
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--to-version", required=True)
    parser.add_argument("--state-dir", type=Path, default=state_directory())
    parser.add_argument("--install-project", type=Path, required=True)
    parser.add_argument("--uv-executable", type=Path, required=True)
    args = parser.parse_args()
    try:
        installation = Installation(args.install_project.expanduser().absolute(),
                                    args.uv_executable.resolve(strict=True))
        result = run_upgrade(Layout.current(args.state_dir.expanduser().absolute()),
                             args.from_version, args.to_version, installation)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except service.ServiceError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    except (AppServerError, OSError, ValueError, TypeError, sqlite3.Error, importlib.metadata.PackageNotFoundError,
            subprocess.SubprocessError):
        # The underlying exceptions may contain private paths, SQL, or server text.
        print(json.dumps({"ok": False, "error": "Legacy upgrade failed; verify runtime state before restarting"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
