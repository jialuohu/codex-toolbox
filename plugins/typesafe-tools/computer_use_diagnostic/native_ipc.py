"""Attest an isolated native Computer Use *client* during a live CLI task.

This observes OS process ancestry and a Unix socket connected to the installed
Sky service. It does not expose or infer a server-issued CUA session ID.
Only hashes, a monotonic observation time, and stable failure codes leave this
module; process commands and socket endpoints remain in memory.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from collections.abc import Callable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path

_APP_RESOURCES = Path("/Applications/ChatGPT.app/Contents/Resources/cua_node")
_MCP_COMMAND = (
    f"{_APP_RESOURCES}/bin/node "
    f"{_APP_RESOURCES}/lib/node_modules/@oai/cua-repl/bin/cua-repl.mjs"
)
_REPL_COMMAND = str(_APP_RESOURCES / "bin/node_repl")
_SERVICE_COMMAND = str(
    Path.home() / ".codex/computer-use/Codex Computer Use.app/Contents/MacOS/"
    "SkyComputerUseService"
)
_SOCKET_PATH = str(
    Path.home() / "Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/"
    "IPC/computeruse.sock"
)
_PROCESS_RE = re.compile(
    r"^\s*(?P<pid>\d+)\s+(?P<ppid>\d+)\s+"
    r"(?P<birth>\w+\s+\w+\s+\d+\s+\d\d:\d\d:\d\d\s+\d{4})\s+"
    r"(?P<command>.+?)\s*$"
)
_SOCKET_ID_RE = re.compile(r"0x[0-9a-fA-F]+\Z")


class _Unverified(ValueError):
    """A stable reason for evidence that is missing or ambiguous."""


@dataclass(frozen=True)
class _Process:
    pid: int
    ppid: int
    birth: str
    command: str


@dataclass(frozen=True)
class NativeClientAttestation:
    verified: bool
    client_context_sha256: str | None
    client_process_sha256: str | None
    ipc_connection_sha256: str | None
    observed_at_monotonic_ms: float
    reason: str | None
    basis: str = "native_client_process_ipc"
    backend_session_id_observed: bool = False


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _default_probe(argv: tuple[str, ...]) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, check=False,
                               timeout=3)
    if completed.returncode != 0:
        raise _Unverified("os_probe_failed")
    return completed.stdout


def _parse_process(line: str) -> _Process:
    match = _PROCESS_RE.fullmatch(line)
    if match is None:
        raise _Unverified("process_identity_unavailable")
    birth = match["birth"]
    try:
        time.strptime(birth, "%a %b %d %H:%M:%S %Y")
    except ValueError as error:
        raise _Unverified("process_birth_unavailable") from error
    return _Process(int(match["pid"]), int(match["ppid"]), birth,
                    match["command"])


def _process(pid: int, probe: Callable[[tuple[str, ...]], str]) -> _Process:
    output = probe(("ps", "-ww", "-p", str(pid), "-o", "pid=", "-o", "ppid=",
                    "-o", "lstart=", "-o", "command="))
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise _Unverified("process_identity_unavailable")
    process = _parse_process(lines[0])
    if process.pid != pid:
        raise _Unverified("process_identity_unavailable")
    return process


def _children(pid: int, probe: Callable[[tuple[str, ...]], str]) -> list[int]:
    output = probe(("pgrep", "-P", str(pid)))
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines or any(not line.isdecimal() for line in lines):
        raise _Unverified("process_child_unavailable")
    values = [int(line) for line in lines]
    if len(values) != len(set(values)):
        raise _Unverified("process_child_ambiguous")
    return values


def _unique_child(parent: _Process, command: str,
                  probe: Callable[[tuple[str, ...]], str]) -> _Process:
    matches = [_process(pid, probe) for pid in _children(parent.pid, probe)]
    selected = [item for item in matches if item.command == command
                and item.ppid == parent.pid]
    if len(selected) != 1:
        raise _Unverified("process_child_ambiguous")
    child = selected[0]
    if time.strptime(child.birth, "%a %b %d %H:%M:%S %Y") < time.strptime(
        parent.birth, "%a %b %d %H:%M:%S %Y"
    ):
        raise _Unverified("process_birth_order_invalid")
    return child


def _service(probe: Callable[[tuple[str, ...]], str]) -> _Process:
    # pgrep returns only PIDs; avoid retaining a machine-wide process-command
    # inventory just to identify the one installed service.
    output = probe(("pgrep", "-f", "SkyComputerUseService"))
    matches = []
    for line in output.splitlines():
        if not line.strip().isdecimal():
            raise _Unverified("native_service_ambiguous")
        item = _process(int(line.strip()), probe)
        if item.command == _SERVICE_COMMAND:
            matches.append(item)
    if len(matches) != 1:
        raise _Unverified("native_service_ambiguous")
    return matches[0]


def _unix_rows(pid: int, probe: Callable[[tuple[str, ...]], str]) -> list[tuple[str, str]]:
    output = probe(("lsof", "-a", "-nP", "-U", "-p", str(pid)))
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 8 or parts[1] != str(pid) or "unix" not in parts:
            continue
        at = parts.index("unix")
        if at + 1 >= len(parts) or _SOCKET_ID_RE.fullmatch(parts[at + 1]) is None:
            continue
        rows.append((parts[at + 1].lower(), " ".join(parts[at + 2:])))
    return rows


def _connection(repl: _Process, service: _Process,
                probe: Callable[[tuple[str, ...]], str]) -> tuple[str, str]:
    server_endpoints = {
        endpoint for endpoint, suffix in _unix_rows(service.pid, probe)
        if suffix.endswith(_SOCKET_PATH)
    }
    if not server_endpoints:
        raise _Unverified("native_service_socket_unavailable")
    matches: list[tuple[str, str]] = []
    for endpoint, suffix in _unix_rows(repl.pid, probe):
        for peer in re.findall(r"->(0x[0-9a-fA-F]+)(?:\s|$)", suffix):
            if peer.lower() in server_endpoints:
                matches.append((endpoint, peer.lower()))
    if len(matches) != 1:
        raise _Unverified("native_client_socket_ambiguous")
    return matches[0]


def attest_native_client(
    codex_pid: int, *,
    seen_contexts: AbstractSet[str] = frozenset(),
    probe: Callable[[tuple[str, ...]], str] | None = None,
) -> NativeClientAttestation:
    """Attest one live CLI -> CUA REPL -> Sky IPC client chain.

    Call after the first native CUA request and before the CLI exits. A failed
    probe is an incomplete measurement, never evidence of isolation.
    """
    observed = time.monotonic_ns() / 1_000_000
    try:
        if type(codex_pid) is not int or codex_pid <= 0:
            raise _Unverified("codex_pid_invalid")
        inspect = probe or _default_probe
        codex = _process(codex_pid, inspect)
        if re.match(r"^(?:\S*/)?codex exec(?:\s|$)", codex.command) is None:
            raise _Unverified("codex_process_unexpected")
        mcp = _unique_child(codex, _MCP_COMMAND, inspect)
        repl = _unique_child(mcp, _REPL_COMMAND, inspect)
        service = _service(inspect)
        endpoint, peer = _connection(repl, service, inspect)
        # A task or its child could have exited while the socket was inspected.
        if any(_process(item.pid, inspect) != item for item in (codex, mcp, repl, service)):
            raise _Unverified("process_changed_during_probe")
        client_process = _digest(f"{repl.pid}\0{repl.birth}\0{repl.command}")
        connection = _digest(f"{endpoint}\0{peer}\0{service.pid}\0{service.birth}")
        context = _digest(
            f"{codex.pid}\0{codex.birth}\0{mcp.pid}\0{mcp.birth}\0"
            f"{client_process}\0{connection}"
        )
        if context in seen_contexts:
            raise _Unverified("native_client_context_reused")
        return NativeClientAttestation(
            True, context, client_process, connection,
            time.monotonic_ns() / 1_000_000, None,
        )
    except (_Unverified, OSError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, _Unverified) else "os_probe_failed"
        return NativeClientAttestation(False, None, None, None, observed, reason)
