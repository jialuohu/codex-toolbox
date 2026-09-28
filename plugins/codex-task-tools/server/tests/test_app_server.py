"""App Server transport tests use a fake WebSocket, never the real daemon."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from codex_task_tools import app_server


class FakeWebSocket:
    def __init__(self, codex_home: Path) -> None:
        self.codex_home = codex_home
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []

    async def send(self, raw: str) -> None:
        message = json.loads(raw)
        self.sent.append(message)
        method = message.get("method")
        if method == "initialize":
            await self.incoming.put(
                json.dumps(
                    {"method": "thread/status/changed", "params": {"threadId": "earlier"}}
                )
            )
            await self.incoming.put(
                json.dumps(
                    {
                        "id": message["id"],
                        "result": {
                            "codexHome": str(self.codex_home),
                            "platformOs": "macos",
                            "userAgent": "codex_cli/0.156.1",
                        },
                    }
                )
            )
        elif method == "thread/read":
            await self.incoming.put(
                json.dumps(
                    {
                        "id": "approval-17",
                        "method": "item/commandExecution/requestApproval",
                        "params": {"threadId": "task-1", "turnId": "turn-1"},
                    }
                )
            )
            await self.incoming.put(
                json.dumps({"method": "turn/started", "params": {"threadId": "task-1"}})
            )
            await self.incoming.put(
                json.dumps({"id": message["id"], "result": {"thread": {"id": "task-1"}}})
            )

    async def close(self) -> None:
        await self.incoming.put(None)

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        while True:
            value = await self.incoming.get()
            if value is None:
                return
            yield value


def test_interleaved_notifications_and_server_requests_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        socket_path = tmp_path / "app-server-control" / "app-server-control.sock"
        socket_path.parent.mkdir(mode=0o700)
        original_lstat = Path.lstat

        def fake_lstat(path: Path, *args: Any, **kwargs: Any) -> os.stat_result:
            if path == socket_path:
                return os.stat_result(
                    (stat.S_IFSOCK | 0o600, 0, 0, 1, os.getuid(), os.getgid(), 0, 0, 0, 0)
                )
            return original_lstat(path, *args, **kwargs)

        socket = FakeWebSocket(tmp_path)

        async def connect(*_args: Any, **_kwargs: Any) -> FakeWebSocket:
            return socket

        monkeypatch.setattr(app_server.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(app_server, "_machine_binding", lambda: "a" * 64)
        monkeypatch.setattr(Path, "lstat", fake_lstat)
        monkeypatch.setattr(app_server, "unix_connect", connect)
        client = app_server.AppServerClient(tmp_path, timeout=2)
        await client.connect()
        try:
            assert client.version == "0.156.1"
            result = await client.request("thread/read", {"threadId": "task-1"})
            assert result == {"thread": {"id": "task-1"}}
            first = await asyncio.wait_for(client.next_event(), timeout=1)
            second = await asyncio.wait_for(client.next_event(), timeout=1)
            third = await asyncio.wait_for(client.next_event(), timeout=1)
            assert first["method"] == "thread/status/changed"
            assert second["id"] == "approval-17"
            assert second["method"] == "item/commandExecution/requestApproval"
            assert third["method"] == "turn/started"
            await client.send_response("approval-17", {"decision": "decline"})
            assert socket.sent[-1] == {"id": "approval-17", "result": {"decision": "decline"}}
        finally:
            await client.close()

    asyncio.run(exercise())


def test_duplicate_json_keys_and_oversized_requests_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(app_server.AppServerError, match="Duplicate JSON key"):
        app_server.strict_json('{"id":1,"id":2}')

    async def exercise() -> None:
        client = app_server.AppServerClient(tmp_path)
        socket = FakeWebSocket(tmp_path)
        client.connection = socket  # type: ignore[assignment]
        with pytest.raises(app_server.NotSent, match="exceeds"):
            await client.request("thread/start", {"prompt": "x" * (4 * 1024 * 1024)})
        assert socket.sent == []
        await client.close()

    asyncio.run(exercise())


def test_event_queue_saturation_preserves_server_requests_and_disconnects(tmp_path: Path) -> None:
    async def exercise() -> None:
        socket = FakeWebSocket(tmp_path)
        client = app_server.AppServerClient(tmp_path)
        client.connection = socket  # type: ignore[assignment]
        loop = asyncio.get_running_loop()
        pending: asyncio.Future[dict[str, Any]] = loop.create_future()
        client.pending[1] = pending
        for index in range(1025):
            socket.incoming.put_nowait(json.dumps({
                "id": f"approval-{index}",
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": "task-1"},
            }))
        client.reader = asyncio.create_task(client._read_loop())  # noqa: SLF001
        await asyncio.wait_for(client.reader, 1)

        with pytest.raises(app_server.OutcomeUnknown, match="connection ended"):
            await pending
        with pytest.raises(app_server.NotSent, match="disconnected"):
            await client.request("thread/read", {"threadId": "task-1"})
        events = [await asyncio.wait_for(client.next_event(), 1) for _ in range(1026)]
        assert [event["id"] for event in events[:-1]] == [
            f"approval-{index}" for index in range(1025)
        ]
        assert events[-1]["method"] == "_connection_lost"
        await client.close()

    asyncio.run(exercise())
