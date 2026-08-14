from __future__ import annotations

import anyio
from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session

from apple_mail_tools.server import create_server
from apple_mail_tools.service import ServiceOutput

TOOLS = [
    "apple_mail_health_check",
    "apple_mail_list_accounts",
    "apple_mail_list_mailboxes",
    "apple_mail_list_messages",
    "apple_mail_search_recent",
    "apple_mail_search_history",
    "apple_mail_get_message",
    "apple_mail_list_attachments",
    "apple_mail_index_status",
    "apple_mail_prepare_index_sync",
    "apple_mail_commit_index_sync",
    "apple_mail_erase_index",
    "apple_mail_fetch_attachment",
    "apple_mail_release_attachment",
    "apple_mail_create_draft",
    "apple_mail_prepare_mutation",
    "apple_mail_commit_mutation",
    "apple_mail_cancel_mutation",
]


class FakeService:
    def __getattr__(self, name: str):
        def operation(*args: object, **kwargs: object) -> ServiceOutput:
            return ServiceOutput({"operation": name})

        return operation


def test_protocol_lists_exact_tools_valid_schemas_and_annotations() -> None:
    async def exercise() -> None:
        async with create_connected_server_and_client_session(
            create_server(service=FakeService())
        ) as session:
            response = await session.list_tools()
        assert [tool.name for tool in response.tools] == TOOLS
        by_name = {tool.name: tool for tool in response.tools}
        for tool in response.tools:
            Draft202012Validator.check_schema(tool.inputSchema)
            assert tool.annotations is not None
            assert tool.annotations.openWorldHint is False
        for name in (
            "apple_mail_commit_index_sync",
            "apple_mail_erase_index",
            "apple_mail_fetch_attachment",
            "apple_mail_create_draft",
            "apple_mail_commit_mutation",
        ):
            annotations = by_name[name].annotations
            assert annotations is not None
            assert annotations.readOnlyHint is False
        assert (
            by_name["apple_mail_list_messages"].inputSchema["properties"]["limit"]["maximum"] == 100
        )
        assert (
            by_name["apple_mail_get_message"].inputSchema["properties"]["max_chars"]["maximum"]
            == 100_000
        )
        handles = by_name["apple_mail_prepare_mutation"].inputSchema["properties"][
            "message_handles"
        ]
        assert handles["maxItems"] == 20

    anyio.run(exercise)


def test_protocol_returns_common_envelope() -> None:
    async def exercise() -> None:
        async with create_connected_server_and_client_session(
            create_server(service=FakeService())
        ) as session:
            response = await session.call_tool("apple_mail_health_check", {})
        assert response.isError is False
        assert response.structuredContent == {
            "ok": True,
            "data": {"operation": "health_check"},
            "error": None,
            "coverage": None,
        }

    anyio.run(exercise)
