"""Billing-free request recording and compatibility with historical ledger rows."""

import json
import sqlite3
from datetime import timedelta

import httpx
import pytest
from test_runtime import ANSWER, BOUND, NOW, QUESTIONS, FakeConfig, run

from typesafe_tools.billing import MONTHLY_CAP
from typesafe_tools.config import ConfigStore
from typesafe_tools.errors import EvaluationError
from typesafe_tools.ledger import Ledger
from typesafe_tools.service import Service

META = {"classification": "synthetic", "invocation": "explicit",
        "question_count": 1, "payload_bytes": 200}


def item(tmp_path, handler):
    return Service(FakeConfig(), Ledger(tmp_path / "state"), transport=httpx.MockTransport(handler),
                   clock=lambda: NOW)


def test_status_is_offline_and_contains_no_billing_fields(tmp_path):
    service = item(tmp_path, lambda request: pytest.fail("status sent a request"))
    status = service.status()
    assert status["status"] == "ready"
    assert status["automatic_routing_enabled"]
    assert "billing_status" not in status and "monthly_budget_usd" not in status
    assert "charged_nanousd" not in status["accounting"]
    assert not service.ledger.root.exists()


def test_dispatch_ignores_historical_cap_and_preserves_old_records(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert service.ledger.unlimited_status(NOW)["unresolved_requests"] == 1
        return httpx.Response(200, json=ANSWER)

    service = item(tmp_path, handler)
    for _ in range(5):
        service.ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    before = service.ledger.status(NOW)["used_nanousd"]
    for _ in range(6):
        result = run(service.evaluate("synthetic", QUESTIONS, "synthetic"))
        assert result["ok"] and "billing_mode" not in result
        assert "charged_nanousd" not in result and "reservation_id" not in result
    assert len(calls) == 6
    status = service.ledger.unlimited_status(NOW)
    assert status["input_tokens"] == 120 and status["requests_this_month"] == 6
    assert service.ledger.status(NOW)["used_nanousd"] == before
    assert b"synthetic-key" not in service.ledger.path.read_bytes()


def test_invalid_answer_still_records_usage(tmp_path):
    service = item(tmp_path, lambda request: httpx.Response(200, json={**ANSWER, "answers": {}}))
    result = run(service.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "invalid_response"
    assert service.ledger.unlimited_status(NOW)["input_tokens"] == 20
    assert service.ledger.unlimited_status(NOW)["unresolved_requests"] == 0


def test_timeout_keeps_unknown_usage_across_months(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout after dispatch", request=request)

    service = item(tmp_path, handler)
    result = run(service.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "deadline_exceeded" and len(calls) == 1
    status = service.ledger.unlimited_status(NOW + timedelta(days=2))
    assert status["requests_this_month"] == 0 and status["unresolved_requests"] == 1


def test_automatic_research_privacy_and_credential_controls_remain(tmp_path):
    service = item(tmp_path, lambda request: pytest.fail("unexpected request"))
    result = run(service.evaluate("synthetic", QUESTIONS, "synthetic", "automatic"))
    assert result["error"]["code"] == "automatic_use_unverified"
    result = run(service.evaluate("synthetic-key", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "data_ineligible"
    service.config = ConfigStore(tmp_path / "absent")
    result = run(service.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "credential_missing"


def test_duplicate_usage_halts_recording(tmp_path):
    ledger = Ledger(tmp_path / "state")
    identifier = ledger.start_unlimited(NOW, META)
    ledger.finish_unlimited(identifier, 1, 2)
    with pytest.raises(EvaluationError):
        ledger.finish_unlimited(identifier, 1, 2)
    with pytest.raises(EvaluationError):
        ledger.start_unlimited(NOW, META)


def test_status_does_not_migrate_legacy_database(tmp_path):
    ledger = Ledger(tmp_path / "state")
    ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    before = ledger.path.read_bytes()
    assert ledger.unlimited_status(NOW)["requests_this_month"] == 0
    assert ledger.path.read_bytes() == before
    with sqlite3.connect(ledger.path) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE name='uncapped_requests'")
        assert not table.fetchone()


@pytest.mark.parametrize("value", [None, 0, "5", 5])
def test_removed_budget_setting_is_rejected(tmp_path, value):
    store = ConfigStore(tmp_path)
    store.root.mkdir(mode=0o700)
    path = store.root / "config.json"
    path.touch(mode=0o600)
    path.write_text(json.dumps({"monthly_budget_usd": value}))
    with pytest.raises(EvaluationError) as error:
        store.settings()
    assert error.value.code == "configuration_invalid"
