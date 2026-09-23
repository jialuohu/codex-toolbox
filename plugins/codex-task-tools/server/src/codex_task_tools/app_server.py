"""Bounded, multiplexed App Server client for the running local Unix listener."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import uuid
from pathlib import Path
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, unix_connect
from websockets.exceptions import ConnectionClosed


class AppServerError(RuntimeError):
    """A safe, client-authored error without server text or prompt content."""


class NotSent(AppServerError):
    """The request could not have reached App Server."""


class OutcomeUnknown(AppServerError):
    """The request may have reached App Server; a retry is unsafe."""


class RPCRejected(AppServerError):
    """App Server returned a JSON-RPC error response for this request."""

    def __init__(self, method: str, code: int | None = None) -> None:
        super().__init__(f"App Server rejected {method}")
        self.method = method
        self.code = code


class AppClient(Protocol):
    backend_identity: str
    version: str
    generation: str

    async def connect(self) -> None: ...

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]: ...

    async def next_event(self) -> dict[str, Any]: ...

    async def send_response(self, request_id: str | int, result: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


def strict_json(raw: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise AppServerError("Duplicate JSON key from App Server")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=pairs)


def _machine_binding() -> str:
    if platform.system() != "Darwin":
        raise AppServerError("Codex task creation is currently supported on macOS only")
    try:
        raw = subprocess.check_output(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], timeout=10
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AppServerError("Physical Mac identity unavailable") from exc
    matches = [line for line in raw.splitlines() if b'"IOPlatformUUID"' in line]
    if len(matches) != 1:
        raise AppServerError("Physical Mac identity unavailable")
    return hashlib.sha256(matches[0].strip()).hexdigest()


class AppServerClient:
    """One connection; a reader dispatches interleaved responses, events, and server requests."""

    def __init__(self, codex_home: Path | None = None, *, timeout: float = 90) -> None:
        self.codex_home = (codex_home or Path(os.getenv("CODEX_HOME", Path.home() / ".codex"))).resolve()
        self.socket_path = self.codex_home / "app-server-control" / "app-server-control.sock"
        self.timeout = timeout
        self.connection: ClientConnection | None = None
        self.reader: asyncio.Task[None] | None = None
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self.overflow_event: dict[str, Any] | None = None
        self.connection_lost_pending = False
        self.reader_failed = False
        self.write_lock = asyncio.Lock()
        self.next_id = 0
        self.generation = ""
        self.backend_identity = ""
        self.version = ""

    async def connect(self) -> None:
        if self.connection is not None:
            return
        if platform.system() != "Darwin":
            raise AppServerError("Codex task creation is currently supported on macOS only")
        self._check_control_socket()
        try:
            self.connection = await unix_connect(
                str(self.socket_path), uri="ws://localhost/", max_size=16 * 1024 * 1024,
                max_queue=32, open_timeout=10,
            )
        except (OSError, TimeoutError) as exc:
            raise AppServerError("Cannot connect to the existing Codex App Server") from exc
        self.generation = uuid.uuid4().hex
        self.reader_failed = False
        self.reader = asyncio.create_task(self._read_loop(), name="app-server-reader")
        try:
            init = await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_task_tools",
                        "title": "Codex Task Tools",
                        "version": "0.1.0",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "optOutNotificationMethods": [
                            "item/agentMessage/delta",
                            "item/reasoning/summaryTextDelta",
                            "item/reasoning/textDelta",
                            "item/commandExecution/outputDelta",
                            "turn/diff/updated",
                            "turn/plan/updated",
                            "thread/tokenUsage/updated",
                        ],
                    },
                },
            )
            codex_home = init.get("codexHome")
            if (
                not isinstance(codex_home, str)
                or Path(codex_home).resolve() != self.codex_home
                or init.get("platformOs") != "macos"
            ):
                raise AppServerError("App Server identity does not match this local Codex home")
            agent = init.get("userAgent", "")
            match = re.search(r"(?<!\d)(0\.156\.1)(?!\d)", agent)
            self.version = match.group(1) if match else "unsupported"
            self.backend_identity = hashlib.sha256(
                f"{_machine_binding()}\0{self.codex_home}\0{os.getuid()}".encode()
            ).hexdigest()
            await self.notify("initialized", {})
        except Exception:
            await self.close()
            raise

    def _check_control_socket(self) -> None:
        """Accept only the owned daemon's private socket or its owned default symlink."""
        try:
            home = self.codex_home.lstat()
            parent = self.socket_path.parent.lstat()
            entry = self.socket_path.lstat()
        except (OSError, ValueError) as exc:
            raise AppServerError("The existing Codex App Server control socket is unavailable") from exc
        if (
            home.st_uid != os.getuid() or not stat.S_ISDIR(home.st_mode)
            or parent.st_uid != os.getuid() or not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) & 0o077
        ):
            raise AppServerError("App Server control socket path is unsafe")
        if entry.st_uid != os.getuid():
            raise AppServerError("App Server control socket path is unsafe")
        if stat.S_ISLNK(entry.st_mode):
            target = Path(os.readlink(self.socket_path))
            private_root = Path(f"/private/tmp/codex-daemon-{os.getuid()}")
            if (
                not target.is_absolute() or target.parent != private_root
                or not re.fullmatch(r"[0-9a-f]{64}", target.name)
            ):
                raise AppServerError("App Server control socket symlink target is unsupported")
            try:
                root_stat, target_stat = private_root.lstat(), target.lstat()
            except (OSError, ValueError) as exc:
                raise AppServerError("App Server control socket target is unavailable") from exc
            if (
                root_stat.st_uid != os.getuid()
                or not stat.S_ISDIR(root_stat.st_mode)
                or stat.S_IMODE(root_stat.st_mode) != 0o700
                or target_stat.st_uid != os.getuid()
                or not stat.S_ISSOCK(target_stat.st_mode)
                or stat.S_IMODE(target_stat.st_mode) & 0o077
            ):
                raise AppServerError("App Server control socket symlink target is unsafe")
        elif not stat.S_ISSOCK(entry.st_mode) or stat.S_IMODE(entry.st_mode) & 0o077:
            raise AppServerError("App Server control socket path is unsafe")

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.connection is None or self.reader_failed:
            raise NotSent("App Server is disconnected")
        self.next_id += 1
        rpc_id = self.next_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[rpc_id] = future
        try:
            await self._send({"id": rpc_id, "method": method, "params": params})
            message = await asyncio.wait_for(future, timeout=self.timeout)
        except (TimeoutError, ConnectionClosed, OSError) as exc:
            raise OutcomeUnknown(f"App Server response unavailable for {method}") from exc
        finally:
            self.pending.pop(rpc_id, None)
        if "error" in message:
            error = message["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise RPCRejected(method, code if isinstance(code, int) else None)
        result = message.get("result")
        if not isinstance(result, dict):
            raise OutcomeUnknown(f"App Server returned an invalid response for {method}")
        return result

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def send_response(self, request_id: str | int, result: dict[str, Any]) -> None:
        await self._send({"id": request_id, "result": result})

    async def _send(self, value: dict[str, Any]) -> None:
        connection = self.connection
        if connection is None or self.reader_failed:
            raise NotSent("App Server is disconnected")
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if len(payload.encode()) > 4 * 1024 * 1024:
            raise NotSent("App Server request exceeds the supported size")
        async with self.write_lock:
            try:
                await connection.send(payload)
            except (ConnectionClosed, OSError) as exc:
                raise OutcomeUnknown("App Server connection failed while sending") from exc

    async def _read_loop(self) -> None:
        connection = self.connection
        assert connection is not None
        try:
            async for raw in connection:
                value = strict_json(raw)
                if not isinstance(value, dict):
                    raise AppServerError("Invalid App Server message")
                if "id" in value and "method" not in value:
                    future = self.pending.get(value["id"])
                    if future is not None and not future.done():
                        future.set_result(value)
                elif "method" in value:
                    method = value["method"]
                    if "id" in value or method in {
                        "turn/started", "turn/completed", "serverRequest/resolved",
                        "thread/status/changed",
                    }:
                        try:
                            self.events.put_nowait(value)
                        except asyncio.QueueFull:
                            # Stop this connection without discarding the received request.
                            # Awaiting queue space here would also block RPC responses.
                            self.overflow_event = value
                            break
                else:
                    raise AppServerError("Invalid App Server message")
        except (ConnectionClosed, AppServerError, asyncio.QueueFull, ValueError, TypeError):
            pass
        finally:
            self.reader_failed = True
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(OutcomeUnknown("App Server connection ended"))
            if self.events.full() or self.overflow_event is not None:
                self.connection_lost_pending = True
            else:
                self.events.put_nowait({"method": "_connection_lost", "params": {}})

    async def next_event(self) -> dict[str, Any]:
        if self.events.empty():
            if self.overflow_event is not None:
                event, self.overflow_event = self.overflow_event, None
                return event
            if self.connection_lost_pending:
                self.connection_lost_pending = False
                return {"method": "_connection_lost", "params": {}}
        return await self.events.get()

    async def close(self) -> None:
        connection, reader = self.connection, self.reader
        self.connection = None
        self.reader = None
        if connection is not None:
            await connection.close()
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
