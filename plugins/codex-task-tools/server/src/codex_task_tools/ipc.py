"""Private Unix socket request client for the independently managed broker."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

from .app_server import strict_json
from .broker import state_directory


class BrokerUnavailable(RuntimeError):
    pass


async def broker_request(
    operation: str, params: dict[str, Any] | None = None, *,
    state_dir: Path | None = None, timeout: float = 120,
) -> dict[str, Any]:
    directory = state_dir or state_directory()
    socket_path = directory / "broker.sock"
    try:
        parent, entry = directory.stat(), socket_path.lstat()
        if (
            not directory.is_dir() or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) & 0o077
            or not stat.S_ISSOCK(entry.st_mode) or entry.st_uid != os.getuid()
            or stat.S_IMODE(entry.st_mode) & 0o077
        ):
            raise BrokerUnavailable("Task broker socket is not private")
    except FileNotFoundError as exc:
        raise BrokerUnavailable("Task broker is not running") from exc
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(socket_path)), 5)
        payload = json.dumps(
            {"operation": operation, "params": params or {}}, separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        if len(payload) > 1024 * 1024:
            raise BrokerUnavailable("Task broker request is too large")
        writer.write(payload + b"\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout)
        if len(raw) > 1024 * 1024:
            raise BrokerUnavailable("Task broker response is too large")
        value = strict_json(raw)
        if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
            raise BrokerUnavailable("Task broker response is invalid")
        return value
    except (OSError, TimeoutError, ValueError) as exc:
        raise BrokerUnavailable("Task broker did not return a verified response") from exc
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
