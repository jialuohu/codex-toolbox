"""Capability routing stays advisory and cannot inherit research automation."""

import asyncio
import hashlib
import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from typesafe_tools.billing import MODEL
from typesafe_tools.config import ConfigStore, Settings
from typesafe_tools.ledger import Ledger
from typesafe_tools.routing import prepare
from typesafe_tools.server import create_server
from typesafe_tools.service import Service

DIGEST = hashlib.sha256(b"synthetic-catalog").hexdigest()
CANDIDATES = [
    {"id": "reading", "name": "Article reader", "description": "Read one public article.",
     "owner": "research-tools", "availability": "available", "implicit": True,
     "required": False},
    {"id": "code", "name": "Code review", "description": "Inspect source code.",
     "owner": "codex", "availability": "available", "implicit": True,
     "required": False},
]


class PilotConfig:
    def settings(self):
        return Settings(routing_pilot=True)

    def api_key(self):
        return "synthetic-key"


def reply():
    return {"model": MODEL, "answers": {
        "q0": {"type": "score", "score": 2.5,
                    "legend": {"0": "No relevant use for this task.",
                               "1": "Optional supporting capability.",
                               "2": "Useful for a material part of this task.",
                               "3": "Necessary to carry out this task."},
                    "probabilities": {"0": 0, "1": 0, "2": 0.5, "3": 0.5},
                    "confidence": 0.8},
        "q1": {"type": "score", "score": 0.2,
                 "legend": {"0": "No relevant use for this task.",
                            "1": "Optional supporting capability.",
                            "2": "Useful for a material part of this task.",
                            "3": "Necessary to carry out this task."},
                 "probabilities": {"0": 0.8, "1": 0.2, "2": 0, "3": 0},
                 "confidence": 0.7}},
            "usage": {"input_tokens": 80, "output_tokens": 10}}


def run(coro):
    return asyncio.run(coro)


def route(item, *, invocation="automatic", candidates=None):
    return run(item.route("Read a public article", candidates or CANDIDATES,
                          DIGEST, "synthetic", "session_1", "turn_1", invocation))


def test_default_routing_and_research_gates_are_separate(tmp_path):
    item = Service(ConfigStore(tmp_path / "secrets"), Ledger(tmp_path / "state"),
                   transport=httpx.MockTransport(lambda request: pytest.fail("dispatched")))
    assert route(item)["error"]["code"] == "credential_missing"
    assert route(item, invocation="pilot")["error"]["code"] == "routing_disabled"
    assert not (tmp_path / "state").exists()
    item.config = PilotConfig()
    result = run(item.evaluate("synthetic", {"q": {"type": "noul", "instructions": "x"}},
                               "synthetic", "automatic"))
    assert result["error"]["code"] == "automatic_use_unverified"


def test_automatic_routing_can_be_explicitly_disabled(tmp_path):
    class DisabledConfig(PilotConfig):
        def settings(self):
            return Settings(automatic_routing=False, routing_pilot=True)

    item = Service(DisabledConfig(), Ledger(tmp_path / "state"),
                   transport=httpx.MockTransport(lambda request: pytest.fail("dispatched")))
    assert route(item)["error"]["code"] == "routing_disabled"
    assert not (tmp_path / "state").exists()


def test_one_pilot_request_ranks_every_candidate_without_tool_authority(tmp_path):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert set(body["questions"]) == {"q0", "q1"}
        assert "session_1" not in str(body) and "turn_1" not in str(body)
        return httpx.Response(200, json=reply())

    item = Service(PilotConfig(), Ledger(tmp_path / "state"),
                   httpx.MockTransport(handler))
    result = route(item, invocation="pilot")
    assert result["status"] == "evaluated" and result["advisory_only"]
    assert result["ranked_ids"] == ["reading", "code"] and not result["abstain"]
    assert [row["id"] for row in result["candidates"]] == ["reading", "code"]
    assert result["catalog_digest"] == DIGEST and result["turn_id"] == "turn_1"
    assert len(calls) == 1
    assert b"Read a public article" not in item.ledger.path.read_bytes()


def test_invalid_and_ineligible_requests_never_dispatch(tmp_path):
    item = Service(PilotConfig(), Ledger(tmp_path / "state"),
                   httpx.MockTransport(lambda request: pytest.fail("dispatched")))
    invalid = [dict(CANDIDATES[0], availability="installed"),
               dict(CANDIDATES[0], implicit=False),
               dict(CANDIDATES[0], description="x" * 301)]
    for candidate in invalid:
        assert route(item, candidates=[candidate])["error"]["code"] == "invalid_request"
    assert route(item, candidates=CANDIDATES * 9)["error"]["code"] == "invalid_request"
    assert run(item.route("Private task", CANDIDATES, DIGEST, "private",  # pyright: ignore[reportArgumentType]
                          "session_1",
                          "turn_1"))["error"]["code"] == "data_ineligible"
    assert not item.ledger.root.exists()


def test_routing_timeout_does_not_retry_and_keeps_unknown_usage(tmp_path, monkeypatch):
    calls = []
    deadlines = []
    real_timeout = asyncio.timeout

    def record_timeout(delay):
        deadline = real_timeout(delay)
        deadlines.append(deadline)
        return deadline

    monkeypatch.setattr("typesafe_tools.service.asyncio.timeout", record_timeout)

    async def handler(request):
        calls.append(request)
        # Expire the real deadline after dispatch, independently of runner load.
        deadlines[0].reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()
        pytest.fail("the routing deadline did not cancel the request")

    item = Service(PilotConfig(), Ledger(tmp_path / "state"),
                   httpx.MockTransport(handler))
    assert route(item)["error"]["code"] == "deadline_exceeded"
    assert len(deadlines) == 1 and deadlines[0].expired()
    assert len(calls) == 1
    assert item.ledger.unlimited_status(item.clock())["unresolved_requests"] == 1


def test_bad_provider_results_are_never_ranked(tmp_path):
    broken = reply()
    broken["answers"].pop("q1")
    item = Service(PilotConfig(), Ledger(tmp_path / "state"),
                   httpx.MockTransport(lambda request: httpx.Response(200, json=broken)))
    assert route(item)["error"]["code"] == "invalid_response"


def test_abstention_preserves_candidates_and_required_choices(tmp_path):
    low = reply()
    low["answers"]["q0"]["score"] = 0.2
    low["answers"]["q0"]["probabilities"] = {"0": 0.8, "1": 0.2, "2": 0, "3": 0}
    item = Service(PilotConfig(), Ledger(tmp_path / "state"),
                   httpx.MockTransport(lambda request: httpx.Response(200, json=low)))
    result = route(item)
    assert result["ok"] and result["abstain"]
    assert [row["id"] for row in result["candidates"]] == ["reading", "code"]
    required = [dict(CANDIDATES[0], required=True), CANDIDATES[1]]
    result = route(item, candidates=required)
    assert not result["abstain"] and result["ranked_ids"][0] == "reading"


def test_session_stops_routing_after_three_provider_failures(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    item = Service(PilotConfig(), Ledger(tmp_path / "state"),
                   httpx.MockTransport(handler))
    for _ in range(3):
        assert route(item)["error"]["code"] == "provider_unavailable"
    assert route(item)["error"]["code"] == "routing_suspended"
    assert len(calls) == 3


def test_missing_ids_use_stable_local_session_and_fresh_turns(tmp_path):
    payloads = []

    def handler(request):
        payloads.append(request.content)
        return httpx.Response(200, json=reply())

    item = Service(PilotConfig(), Ledger(tmp_path / "state"), httpx.MockTransport(handler))
    first = run(item.route("Read a public article", CANDIDATES, DIGEST, "synthetic"))
    second = run(item.route("Read a public article", CANDIDATES, DIGEST, "synthetic"))
    partial = run(item.route("Read a public article", CANDIDATES, DIGEST,
                             "synthetic", session_id="caller_session"))
    assert first["ok"] and second["ok"] and partial["ok"]
    assert first["session_id"] == second["session_id"]
    assert first["turn_id"] != second["turn_id"]
    assert partial["session_id"] == "caller_session"
    assert partial["turn_id"] not in {first["turn_id"], second["turn_id"]}
    for identifier in (first["session_id"], first["turn_id"], second["turn_id"],
                       partial["session_id"], partial["turn_id"]):
        assert identifier.encode() not in b"".join(payloads)


def test_rotating_caller_ids_cannot_bypass_provider_failure_suspension(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    item = Service(PilotConfig(), Ledger(tmp_path / "state"), httpx.MockTransport(handler))
    for index in range(3):
        result = run(item.route("Read a public article", CANDIDATES, DIGEST,
                                "synthetic", f"session_{index}", f"turn_{index}"))
        assert result["error"]["code"] == "provider_unavailable"
    blocked = run(item.route("Read a public article", CANDIDATES, DIGEST,
                             "synthetic", "new_session", "new_turn"))
    assert blocked["error"]["code"] == "routing_suspended"
    assert len(calls) == 3


def test_mcp_reuses_service_for_session_failure_suspension(tmp_path, monkeypatch):
    calls = []
    instances = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    def factory():
        item = Service(PilotConfig(), Ledger(tmp_path / "state"),
                       httpx.MockTransport(handler))
        instances.append(item)
        return item

    monkeypatch.setattr("typesafe_tools.server.Service", factory)

    async def scenario():
        server = create_server()
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            for index in range(4):
                response = await client.call_tool("typesafe_route", {
                    "task": "Read a public article", "candidates": CANDIDATES,
                    "catalog_digest": DIGEST, "session_id": "session_1",
                    "turn_id": f"turn_{index}", "classification": "synthetic",
                })
                assert response.structuredContent is not None
                expected = "provider_unavailable" if index < 3 else "routing_suspended"
                assert response.structuredContent["error"]["code"] == expected

    run(scenario())
    assert len(instances) == 1 and len(calls) == 3


def test_catalog_id_and_payload_limits_are_closed():
    namespaced = [dict(CANDIDATES[0], id="skill:research-tools@jialuo-codex-toolbox/reader")]
    state, questions = prepare("Public task", namespaced, DIGEST, "session_1", "turn_1")
    assert state["candidates"][0]["question_id"] == "q0"
    assert state["candidates"][0]["id"] == namespaced[0]["id"]
    state, questions = prepare("Public task", CANDIDATES, DIGEST, "session_1", "turn_1")
    assert len(questions) == len(state["candidates"]) == 2
    with pytest.raises(Exception):
        prepare("Public task", CANDIDATES, "not-a-digest", "session_1", "turn_1")
