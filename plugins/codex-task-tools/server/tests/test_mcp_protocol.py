"""The public MCP exposes only the four planned task operations."""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from codex_task_tools import mcp_server

NAMES = [
    "codex_projects_find",
    "codex_task_create",
    "codex_task_status",
    "codex_task_respond",
]


def test_four_tool_surface_schemas_and_side_effect_hints() -> None:
    async def exercise() -> None:
        async with create_connected_server_and_client_session(
            mcp_server.create_server()
        ) as session:
            listed = await session.list_tools()

        assert [tool.name for tool in listed.tools] == NAMES
        tools = {tool.name: tool for tool in listed.tools}
        for name in ("codex_projects_find", "codex_task_status"):
            annotations = tools[name].annotations
            assert annotations is not None
            assert annotations.readOnlyHint is True
        for name in ("codex_task_create", "codex_task_respond"):
            annotations = tools[name].annotations
            assert annotations is not None
            assert annotations.readOnlyHint is False
        create = tools["codex_task_create"].inputSchema
        assert set(create["required"]) == {"projectRef", "title", "prompt", "idempotencyKey"}
        assert "cwd" in create["properties"]
        assert create["properties"]["title"]["maxLength"] == 200
        assert create["properties"]["prompt"]["maxLength"] == 200_000

    anyio.run(exercise)


def test_create_tool_passes_exact_user_payload_to_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_call(operation: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((operation, params))
        return {"ok": True, "result": {"taskId": "task-1", "submission": "accepted"}}

    monkeypatch.setattr(mcp_server, "_call", fake_call)

    async def exercise() -> None:
        async with create_connected_server_and_client_session(
            mcp_server.create_server()
        ) as session:
            result = await session.call_tool(
                "codex_task_create",
                {
                    "projectRef": "local:aaaaaaaaaaaaaaaaaaaa:project-1",
                    "title": "Fixture task",
                    "prompt": "Reply with hello.",
                    "idempotencyKey": "fixture-once",
                    "cwd": "/fixture/project",
                },
            )
        assert result.isError is False
        assert result.structuredContent == {
            "ok": True,
            "result": {"taskId": "task-1", "submission": "accepted"},
        }

    anyio.run(exercise)
    assert calls == [
        (
            "task_create",
            {
                "project_ref": "local:aaaaaaaaaaaaaaaaaaaa:project-1",
                "title": "Fixture task",
                "prompt": "Reply with hello.",
                "idempotency_key": "fixture-once",
                "cwd": "/fixture/project",
            },
        )
    ]
