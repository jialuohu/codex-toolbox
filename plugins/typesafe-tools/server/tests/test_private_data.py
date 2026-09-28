"""Private-data opt-in uses fabricated content and mocked HTTP only."""

import json
import sqlite3

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from test_computer_use import CANDIDATES as ACTIONS
from test_computer_use import answer
from test_routing import CANDIDATES as CAPABILITIES
from test_routing import DIGEST, reply
from test_runtime import ANSWER, NOW, QUESTIONS, run

from typesafe_tools.config import ConfigStore
from typesafe_tools.ledger import Ledger
from typesafe_tools.server import create_server
from typesafe_tools.service import Service

MARKER = "fabricated-private-record-3817"
KEY = "fabricated-private-api-key"
KINDS = ("research", "routing", "browser", "native")


def configure(tmp_path, values):
    config = ConfigStore(tmp_path / "secrets")
    config.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, value in (("api-key", KEY), ("config.json", json.dumps(values))):
        path = config.root / name
        path.touch(mode=0o600)
        path.write_text(value)
    return config


def request_for(kind, text=MARKER):
    if kind == "research":
        return "typesafe_evaluate", {
            "state": text, "questions": QUESTIONS, "classification": "private",
            "invocation": "explicit",
        }, ANSWER
    if kind == "routing":
        return "typesafe_route", {
            "task": text, "candidates": CAPABILITIES, "catalog_digest": DIGEST,
            "classification": "private", "invocation": "automatic",
        }, reply()
    return "typesafe_choose_action", {
        "surface": kind, "objective": "Inspect the relevant record",
        "observation": text, "snapshot_id": "snap_1", "task_scope_id": "task_1",
        "candidates": ACTIONS, "classification": "private", "invocation": "explicit",
    }, answer()


async def dispatch(service, kind, arguments):
    if kind == "research":
        return await service.evaluate(**arguments)
    if kind == "routing":
        return await service.route(**arguments)
    return await service.choose_action(**arguments)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enabled", [False, True])
def test_mcp_private_schema_and_opt_in_dispatch(tmp_path, kind, enabled):
    tool_name, arguments, response = request_for(kind)
    requests = []

    def handler(request):
        requests.append(request)
        assert MARKER.encode() in request.content
        assert "classification" not in json.loads(request.content)
        return httpx.Response(200, json=response)

    service = Service(configure(tmp_path, {"allow_private_data": enabled}),
                      Ledger(tmp_path / "ledger"), httpx.MockTransport(handler), lambda: NOW)

    async def scenario():
        server = create_server(service)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            for name in ("typesafe_evaluate", "typesafe_route", "typesafe_choose_action"):
                assert tools[name].inputSchema["properties"]["classification"]["enum"] == [
                    "public", "synthetic", "private"]
                assert "allow_private_data" not in tools[name].inputSchema["properties"]
            status = await client.call_tool("typesafe_status", {})
            assert status.structuredContent is not None
            assert status.structuredContent["private_data_enabled"] is enabled
            assert not requests and not service.ledger.root.exists()
            result = await client.call_tool(tool_name, arguments)
            assert result.structuredContent is not None
            return result.structuredContent

    result = run(scenario())
    if not enabled:
        assert result["error"]["code"] == "data_ineligible"
        assert not requests and not service.ledger.root.exists()
        return
    assert result["ok"] and result["advisory_only"] and len(requests) == 1
    assert MARKER.encode() not in service.ledger.path.read_bytes()
    assert KEY.encode() not in service.ledger.path.read_bytes()
    assert MARKER not in json.dumps(service.status())
    with sqlite3.connect(service.ledger.path) as db:
        assert db.execute("SELECT classification FROM uncapped_requests").fetchall() == [
            ("private",)]


@pytest.mark.parametrize(("kind", "settings", "code"), [
    ("research", {}, "automatic_use_unverified"),
    ("research", {"automatic_research": True}, "automatic_use_unverified"),
    ("routing", {"automatic_routing": False}, "routing_disabled"),
    ("browser", {}, "computer_use_disabled"),
    ("native", {}, "computer_use_disabled"),
    ("browser", {"automatic_browser_use": True}, "computer_use_unverified"),
    ("native", {"automatic_native_use": True}, "computer_use_unverified"),
])
def test_private_opt_in_does_not_bypass_automatic_gates(tmp_path, kind, settings, code):
    service = Service(configure(tmp_path, {**settings, "allow_private_data": True}),
                      Ledger(tmp_path / "ledger"),
                      httpx.MockTransport(lambda _: pytest.fail("unexpected dispatch")))
    _, arguments, _ = request_for(kind)
    arguments["invocation"] = "automatic"
    assert run(dispatch(service, kind, arguments))["error"]["code"] == code
    assert not service.ledger.root.exists()


@pytest.mark.parametrize("kind", ["browser", "native"])
def test_private_automatic_advice_requires_both_opt_ins(tmp_path, kind):
    _, arguments, response = request_for(kind)
    arguments["invocation"] = "automatic"
    settings = {f"automatic_{kind}_use": True, f"{kind}_user_opt_in": True}
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    service = Service(configure(tmp_path, settings), Ledger(tmp_path / "ledger"),
                      httpx.MockTransport(handler))
    assert run(dispatch(service, kind, arguments))["error"]["code"] == "data_ineligible"
    assert not requests and not service.ledger.root.exists()
    configure(tmp_path, {**settings, "allow_private_data": True})
    assert run(dispatch(service, kind, arguments))["ok"]
    assert len(requests) == 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("settings", [{}, {"allow_private_data": False}])
def test_revocation_blocks_next_request_without_ledger_change(tmp_path, kind, settings):
    _, arguments, response = request_for(kind)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    service = Service(configure(tmp_path, {"allow_private_data": True}),
                      Ledger(tmp_path / "ledger"), httpx.MockTransport(handler))
    assert run(dispatch(service, kind, arguments))["ok"]
    before = service.ledger.path.read_bytes()
    configure(tmp_path, settings)
    assert not service.status()["private_data_enabled"]
    assert run(dispatch(service, kind, arguments))["error"]["code"] == "data_ineligible"
    assert len(requests) == 1 and service.ledger.path.read_bytes() == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("protected", ["credential", "secrets_directory"])
def test_private_opt_in_preserves_known_secret_blocks(tmp_path, kind, protected):
    config = configure(tmp_path, {"allow_private_data": True})
    text = KEY if protected == "credential" else str(config.secrets)
    _, arguments, _ = request_for(kind, text=text)
    service = Service(config, Ledger(tmp_path / "ledger"),
                      httpx.MockTransport(lambda _: pytest.fail("protected data sent")))
    result = run(dispatch(service, kind, arguments))
    assert result["error"]["code"] == "data_ineligible"
    assert text not in json.dumps(result) and not service.ledger.root.exists()


@pytest.mark.parametrize("classification", ["unknown", "confidential", "", None, {}, []])
def test_opt_in_does_not_allow_unknown_classifications(tmp_path, classification):
    service = Service(configure(tmp_path, {"allow_private_data": True}),
                      Ledger(tmp_path / "ledger"),
                      httpx.MockTransport(lambda _: pytest.fail("unknown classification sent")))
    _, arguments, _ = request_for("research")
    arguments["classification"] = classification
    assert run(dispatch(service, "research", arguments))["error"]["code"] == "data_ineligible"
    assert not service.ledger.root.exists()


def test_private_errors_do_not_echo_content_or_retry(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(500, text=MARKER)

    service = Service(configure(tmp_path, {"allow_private_data": True}),
                      Ledger(tmp_path / "ledger"), httpx.MockTransport(handler))
    result = run(service.evaluate(MARKER, QUESTIONS, "private"))
    assert result["error"]["code"] == "provider_unavailable" and len(requests) == 1
    assert MARKER not in json.dumps(result)
    assert MARKER not in json.dumps(service.status())
    assert MARKER.encode() not in service.ledger.path.read_bytes()
    assert service.status()["accounting"]["unresolved_requests"] == 1


@pytest.mark.parametrize("classification", ["public", "synthetic"])
@pytest.mark.parametrize("enabled", [False, True])
def test_public_and_synthetic_dispatch_are_independent_of_private_opt_in(
        tmp_path, classification, enabled):
    service = Service(configure(tmp_path, {"allow_private_data": enabled}),
                      Ledger(tmp_path / "ledger"),
                      httpx.MockTransport(lambda _: httpx.Response(200, json=ANSWER)))
    _, arguments, _ = request_for("research", text="Fabricated public example")
    arguments["classification"] = classification
    assert run(dispatch(service, "research", arguments))["ok"]


def test_status_does_not_advertise_private_data_when_configuration_is_unprotected(tmp_path):
    config = configure(tmp_path, {"allow_private_data": True})
    (config.root / "config.json").chmod(0o644)
    service = Service(config, Ledger(tmp_path / "ledger"),
                      httpx.MockTransport(lambda _: pytest.fail("unexpected dispatch")))
    assert service.status()["block_reasons"] == ["configuration_invalid"]
    assert not service.status()["private_data_enabled"]
    assert run(service.evaluate(MARKER, QUESTIONS, "private"))["error"]["code"] == (
        "configuration_invalid")
    assert not service.ledger.root.exists()
