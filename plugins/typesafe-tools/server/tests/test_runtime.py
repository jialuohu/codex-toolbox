import asyncio
import json
import multiprocessing
import sqlite3
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from typesafe_tools.billing import MODEL, MONTHLY_CAP, BillingBound
from typesafe_tools.config import ConfigStore, Settings
from typesafe_tools.errors import EvaluationError
from typesafe_tools.ledger import Ledger
from typesafe_tools.schema import MAX_RESPONSE_BYTES
from typesafe_tools.server import create_server
from typesafe_tools.service import ENDPOINT, Service

NOW = datetime(2026, 9, 30, 23, 59, tzinfo=UTC)
BOUND = BillingBound("fictional-test-only", MODEL, 100, 10_000_000,
                     datetime(2030, 1, 1, tzinfo=UTC), "https://example.org/test-only")
QUESTIONS = {"valid": {"type": "noul", "instructions": "Is the synthetic value true?"}}
ANSWER = {"model": MODEL, "answers": {"valid": {"type": "noul", "noul": 0.75}},
          "usage": {"input_tokens": 20, "output_tokens": 0}}


class FakeConfig:
    def settings(self):
        return Settings()

    def api_key(self):
        return "synthetic-key"


def service(tmp_path, handler, **kwargs):
    return Service(FakeConfig(), Ledger(tmp_path / "state"),
                   httpx.MockTransport(handler), lambda: NOW, **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_no_billing_setting_is_required_for_dispatch(tmp_path):
    item = service(tmp_path, lambda request: httpx.Response(200, json=ANSWER))
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["ok"] and result["usage"] == ANSWER["usage"]
    assert "billing_mode" not in result and "charged_nanousd" not in result


def test_offline_status_no_initialization(tmp_path):
    item = Service(ConfigStore(tmp_path / "secrets"), Ledger(tmp_path / "state"))
    status = item.status()
    assert status["status"] == "blocked"
    assert "credential_missing" in status["block_reasons"]
    assert "monthly_budget_usd" not in status and "billing_status" not in status
    assert not list(tmp_path.iterdir())


def test_success_fixed_endpoint_and_reconciliation(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == ENDPOINT
        assert request.method == "POST"
        assert json.loads(request.content)["model"] == MODEL
        assert request.headers["authorization"] == "Bearer synthetic-key"
        assert "classification" not in json.loads(request.content)
        return httpx.Response(200, json=ANSWER)
    item = service(tmp_path, handler)
    result = run(item.evaluate("synthetic payload", QUESTIONS, "synthetic"))
    assert result["ok"] and len(calls) == 1
    assert result["usage"] == ANSWER["usage"]
    assert item.ledger.unlimited_status(NOW)["input_tokens"] == 20
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 0
    assert b"synthetic payload" not in item.ledger.path.read_bytes()
    assert b"synthetic-key" not in item.ledger.path.read_bytes()
    with sqlite3.connect(item.ledger.path) as db:
        audit = db.execute(
            "SELECT classification,invocation,question_count FROM uncapped_requests").fetchone()
        assert audit == ("synthetic", "explicit", 1)


@pytest.mark.parametrize("code", [301, 302, 307, 400, 401, 429, 500, 503])
def test_failure_single_dispatch_retains_unresolved_request(tmp_path, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(code, headers={"Location": "https://example.org/secret"})
    item = service(tmp_path, handler)
    result = run(item.evaluate("synthetic", QUESTIONS, "public"))
    assert result["error"]["code"] == "provider_unavailable"
    assert "example.org" not in str(result)
    assert len(calls) == 1
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 1


def test_total_timeout_single_dispatch(tmp_path, monkeypatch):
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
        # Expire the real enclosing deadline after dispatch. Configuration and
        # SQLite work may legitimately take more than 50 ms on a busy runner.
        deadlines[0].reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()
        pytest.fail("the total deadline did not cancel the request")
    item = service(tmp_path, handler)
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "deadline_exceeded"
    assert len(deadlines) == 1 and deadlines[0].expired()
    assert len(calls) == 1
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 1


def test_cancellation_retains_unresolved_request(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        async def handler(request):
            entered.set()
            await asyncio.sleep(10)
        item = service(tmp_path, handler)
        task = asyncio.create_task(item.evaluate("synthetic", QUESTIONS, "synthetic"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 1
    run(scenario())


def test_deadline_includes_accounting_and_never_dispatches_late(tmp_path, monkeypatch):
    item = service(tmp_path, lambda request: pytest.fail("late network dispatch"))
    record = item.ledger.start_unlimited
    def slow_record(*args):
        time.sleep(0.1)
        return record(*args)
    monkeypatch.setattr(item.ledger, "start_unlimited", slow_record)
    monkeypatch.setattr("typesafe_tools.service.DEADLINE_SECONDS", 0.03)
    async def scenario():
        before = time.monotonic()
        result = await item.evaluate("synthetic", QUESTIONS, "synthetic")
        assert time.monotonic() - before < 0.09
        assert result["error"]["code"] == "deadline_exceeded"
    run(scenario())
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 1


def test_status_does_not_consider_historical_reservations(tmp_path):
    item = service(tmp_path, lambda request: pytest.fail("network attempted"))
    for _ in range(5):
        item.ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    assert item.status()["status"] == "ready"


def test_month_change_before_dispatch_keeps_request_without_sending(tmp_path):
    item = service(tmp_path, lambda request: pytest.fail("late-month dispatch"))
    times = iter([NOW, NOW + timedelta(minutes=2)])
    item.clock = lambda: next(times)
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "submission_window_changed"
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 1


@pytest.mark.parametrize("body", [b"{}", b"X" * (MAX_RESPONSE_BYTES + 1),
                                   b'{"secret":"https://private.example/hidden"}'])
def test_bad_response_retains_unresolved_request(tmp_path, body):
    item = service(tmp_path, lambda request: httpx.Response(200, content=body))
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "invalid_response"
    assert "private.example" not in str(result)
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 1


def test_invalid_answer_reconciles_independently_valid_usage(tmp_path):
    malformed = {**ANSWER, "answers": {"valid": {"type": "noul", "noul": 2}}}
    item = service(tmp_path, lambda request: httpx.Response(200, json=malformed))
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "invalid_response"
    assert result["usage"] == ANSWER["usage"]
    assert "charged_nanousd" not in result
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 0


def test_credential_cannot_be_embedded_in_payload(tmp_path):
    item = service(tmp_path, lambda request: pytest.fail("credential dispatched"))
    result = run(item.evaluate("synthetic-key", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "data_ineligible"
    assert not item.ledger.root.exists()


def test_default_transport_ignores_environment_trust(tmp_path, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "absent-certificate"))
    original = httpx.AsyncHTTPTransport
    transports = []
    def factory(**kwargs):
        # Exercise the real SSL constructor with the service's actual arguments.
        transports.append(original(**kwargs))
        return httpx.MockTransport(lambda request: httpx.Response(200, json=ANSWER))
    monkeypatch.setattr("typesafe_tools.service.httpx.AsyncHTTPTransport", factory)
    item = service(tmp_path, lambda request: pytest.fail("injected transport used"))
    item.transport = None
    async def scenario():
        result = await item.evaluate("synthetic", QUESTIONS, "synthetic")
        assert result["ok"] and len(transports) == 1
        await transports[0].aclose()
    run(scenario())


def test_private_and_automatic_are_blocked(tmp_path):
    item = service(tmp_path, lambda _: pytest.fail("network attempted"))
    result = run(item.evaluate("private", QUESTIONS, cast(Any, "private")))
    assert result["error"]["code"] == "data_ineligible"
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic", "automatic"))
    assert result["error"]["code"] == "automatic_use_unverified"
    assert not (tmp_path / "state").exists()


def reserve_worker(root):
    try:
        Ledger(Path(root)).reserve(BOUND, MONTHLY_CAP, NOW)
        return True
    except EvaluationError as exc:
        assert exc.code == "budget_exhausted"
        return False


def crash_worker(root):
    import os
    Ledger(Path(root)).reserve(BOUND, MONTHLY_CAP, NOW)
    os._exit(17)


def test_concurrent_processes_cannot_exceed_cap(tmp_path):
    root = tmp_path / "ledger"
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        outcomes = pool.map(reserve_worker, [str(root)] * 12)
    assert sum(outcomes) == 5
    assert Ledger(root).status(NOW)["used_nanousd"] == MONTHLY_CAP


def test_crash_and_month_rollover_keep_old_reservations(tmp_path):
    root = tmp_path / "ledger"
    child = multiprocessing.get_context("spawn").Process(target=crash_worker, args=(str(root),))
    child.start()
    child.join(10)
    assert child.exitcode == 17
    ledger = Ledger(root)
    later = NOW + timedelta(minutes=2)
    assert ledger.status(later)["used_nanousd"] == 0
    assert ledger.status(later)["unsettled_reservations"] == 1
    identifier = ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    ledger.settle(identifier, 20, 0)
    assert ledger.status(later)["used_nanousd"] == 0
    assert ledger.status(NOW)["used_nanousd"] == 1_200_000_000


def test_corruption_and_missing_db_fail_closed(tmp_path):
    ledger = Ledger(tmp_path / "ledger")
    ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    ledger.path.write_bytes(b"corrupt")
    with pytest.raises(EvaluationError, match="accounting"):
        ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    ledger.path.unlink()
    with pytest.raises(EvaluationError, match="accounting"):
        ledger.reserve(BOUND, MONTHLY_CAP, NOW)


@pytest.mark.parametrize("tokens", [101, 10**30])
def test_over_bound_usage_durably_halts(tmp_path, tokens):
    ledger = Ledger(tmp_path / "ledger")
    identifier = ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    with pytest.raises(EvaluationError, match="exceeded"):
        ledger.settle(identifier, tokens, 0)
    with pytest.raises(EvaluationError, match="accounting"):
        Ledger(ledger.root).reserve(BOUND, MONTHLY_CAP, NOW + timedelta(days=2))
    with sqlite3.connect(ledger.path) as db:
        assert db.execute("SELECT halted FROM meta").fetchone() == (1,)


def test_repeat_settlement_halts(tmp_path):
    ledger = Ledger(tmp_path / "ledger")
    identifier = ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    ledger.settle(identifier, 1, 0)
    with pytest.raises(EvaluationError):
        ledger.settle(identifier, 1, 0)
    with pytest.raises(EvaluationError):
        ledger.reserve(BOUND, MONTHLY_CAP, NOW)


def test_status_does_not_acquire_writer_lock(tmp_path):
    ledger = Ledger(tmp_path / "ledger")
    ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    with sqlite3.connect(ledger.path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        assert ledger.status(NOW)["unsettled_reservations"] == 1


def test_initialization_crash_fails_closed(tmp_path):
    ledger = Ledger(tmp_path / "ledger")
    ledger.root.mkdir(mode=0o700)
    ledger.path.touch(mode=0o600)
    with pytest.raises(EvaluationError):
        ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    assert ledger.path.read_bytes() == b""
    assert not ledger.marker.exists()


def test_inconsistent_usage_fails_closed(tmp_path):
    ledger = Ledger(tmp_path / "ledger")
    identifier = ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    ledger.settle(identifier, 20, 0)
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE reservations SET input_tokens=0")
    with pytest.raises(EvaluationError):
        ledger.status(NOW)
    with pytest.raises(EvaluationError):
        ledger.reserve(BOUND, MONTHLY_CAP, NOW)


def test_output_priced_models_are_not_supported(tmp_path):
    ledger = Ledger(tmp_path / "ledger")
    with pytest.raises(EvaluationError):
        ledger.reserve(replace(BOUND, nanousd_per_output_token=1), MONTHLY_CAP, NOW)
    assert not ledger.root.exists()


def test_expired_bound_never_reserves(tmp_path):
    ledger = Ledger(tmp_path / "ledger")
    with pytest.raises(EvaluationError):
        ledger.reserve(replace(BOUND, valid_until=NOW), MONTHLY_CAP, NOW)
    assert not ledger.root.exists()


def test_mcp_discovery_and_offline_call(tmp_path):
    async def scenario():
        item = Service(ConfigStore(tmp_path / "secrets"), Ledger(tmp_path / "state"))
        server = create_server(item)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            assert set(tools) == {
                "typesafe_status", "typesafe_evaluate", "typesafe_route", "typesafe_choose_action",
            }
            status_annotations = tools["typesafe_status"].annotations
            evaluation_annotations = tools["typesafe_evaluate"].annotations
            routing_annotations = tools["typesafe_route"].annotations
            computer_use_annotations = tools["typesafe_choose_action"].annotations
            assert status_annotations is not None and status_annotations.readOnlyHint
            assert evaluation_annotations is not None and not evaluation_annotations.idempotentHint
            assert routing_annotations is not None and not routing_annotations.idempotentHint
            assert (computer_use_annotations is not None
                    and not computer_use_annotations.idempotentHint)
            status = await client.call_tool("typesafe_status", {})
            assert status.structuredContent is not None
            assert status.structuredContent["block_reasons"] == ["credential_missing"]
            response = await client.call_tool("typesafe_evaluate", {
                "state": "synthetic", "questions": QUESTIONS, "classification": "synthetic",
            })
            assert response.structuredContent is not None
            assert response.structuredContent["error"]["code"] == "credential_missing"
    run(scenario())
