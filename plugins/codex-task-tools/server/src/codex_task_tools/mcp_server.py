"""Narrow MCP surface. All mutations and execution live in the broker process."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .ipc import BrokerUnavailable, broker_request

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
CREATE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
RESPOND = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)

ProjectRef = Annotated[str, Field(min_length=10, max_length=256)]
Title = Annotated[str, Field(min_length=1, max_length=200)]
Prompt = Annotated[str, Field(min_length=1, max_length=200_000)]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=128)]


async def _call(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await broker_request(operation, params)
    except BrokerUnavailable as exc:
        return {"ok": False, "error": {"code": "broker_unavailable", "message": str(exc)}}


def create_server() -> FastMCP:
    server = FastMCP(
        "codex-task-tools",
        instructions=(
            "Use task creation only for an explicit user request for a new durable task. "
            "Find the exact existing backend project first. A matching directory alone does "
            "not establish project membership. Reuse the same idempotency key on retries. "
            "Treat unknown outcomes as needing recovery; never create another task or resend "
            "an accepted prompt. Show pending approvals to the user and respond only to their "
            "explicit answer. Desktop project membership is unverified unless separately observed."
        ),
    )

    @server.tool(name="codex_projects_find", annotations=READ)
    async def codex_projects_find(query: str | None = None) -> dict[str, Any]:
        """Find existing local backend projects and return canonical project references."""
        return await _call("projects_find", {"query": query})

    @server.tool(name="codex_task_create", annotations=CREATE)
    async def codex_task_create(
        projectRef: ProjectRef, title: Title, prompt: Prompt,
        idempotencyKey: IdempotencyKey, cwd: str | None = None,
    ) -> dict[str, Any]:
        """Create one durable project task, title it, and submit one initial prompt."""
        return await _call("task_create", {
            "project_ref": projectRef, "title": title, "prompt": prompt,
            "idempotency_key": idempotencyKey, "cwd": cwd,
        })

    @server.tool(name="codex_task_status", annotations=READ)
    async def codex_task_status(
        taskId: str | None = None, idempotencyKey: str | None = None,
    ) -> dict[str, Any]:
        """Read a tracked task's creation, submission, execution, and project evidence."""
        return await _call("task_status", {
            "task_id": taskId, "idempotency_key": idempotencyKey,
        })

    @server.tool(name="codex_task_respond", annotations=RESPOND)
    async def codex_task_respond(
        taskId: str, requestId: str, response: dict[str, Any],
    ) -> dict[str, Any]:
        """Answer one current pending server request after the user supplies the answer."""
        return await _call("task_respond", {
            "task_id": taskId, "request_id": requestId, "response": response,
        })

    return server


def main() -> None:
    create_server().run(transport="stdio")
