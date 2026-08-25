from __future__ import annotations

from typing import Any, cast

import anyio
from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session

from overleaf_tools.server import OperationSurface, create_server

TOOLS = [
    "overleaf_configuration_status",
    "overleaf_list_projects",
    "overleaf_get_project_status",
    "overleaf_list_files",
    "overleaf_read_text_file",
    "overleaf_get_outline",
    "overleaf_reconcile_commit",
    "overleaf_edit_text_file",
    "overleaf_write_text_file",
    "overleaf_import_file",
    "overleaf_move_file",
    "overleaf_delete_file",
]


class FakeOperations:
    def __getattr__(self, name: str) -> Any:
        def operation(*_args: object, **_kwargs: object) -> dict[str, Any]:
            return {
                "ok": True,
                "outcome": "read",
                "data": {"operation": name},
                "error": None,
            }

        return operation


def test_protocol_lists_exact_tools_schemas_and_annotations() -> None:
    async def exercise() -> None:
        operations = cast(OperationSurface, FakeOperations())
        async with create_connected_server_and_client_session(
            create_server(operations=operations)
        ) as session:
            response = await session.list_tools()
        assert [tool.name for tool in response.tools] == TOOLS
        by_name = {tool.name: tool for tool in response.tools}
        for tool in response.tools:
            Draft202012Validator.check_schema(tool.inputSchema)
            assert tool.annotations is not None
            assert tool.annotations.openWorldHint is True
        for name in TOOLS[:7]:
            annotations = by_name[name].annotations
            assert annotations is not None
            assert annotations.readOnlyHint is True
        for name in TOOLS[7:]:
            annotations = by_name[name].annotations
            assert annotations is not None
            assert annotations.readOnlyHint is False
            assert annotations.destructiveHint is True
        assert by_name["overleaf_list_files"].inputSchema["properties"]["limit"]["maximum"] == 500
        expected_blob = by_name["overleaf_write_text_file"].inputSchema["properties"][
            "expected_blob_sha"
        ]
        assert "absent" in expected_blob["pattern"]

    anyio.run(exercise)


def test_protocol_returns_structured_result() -> None:
    async def exercise() -> None:
        operations = cast(OperationSurface, FakeOperations())
        async with create_connected_server_and_client_session(
            create_server(operations=operations)
        ) as session:
            response = await session.call_tool("overleaf_configuration_status", {})
        assert response.isError is False
        assert response.structuredContent == {
            "ok": True,
            "outcome": "read",
            "data": {"operation": "configuration_status"},
            "error": None,
        }

    anyio.run(exercise)
