import json
import sqlite3
from datetime import timedelta

import httpx
import pytest
from test_runtime import ANSWER, BOUND, NOW, QUESTIONS, FakeConfig, run

from typesafe_tools.billing import MONTHLY_CAP
from typesafe_tools.config import ConfigStore, Settings
from typesafe_tools.errors import EvaluationError
from typesafe_tools.ledger import Ledger
from typesafe_tools.service import Service

META = {"classification": "synthetic", "invocation": "explicit",
        "question_count": 1, "payload_bytes": 200}


class UncappedConfig(FakeConfig):
    def settings(self):
        return Settings(monthly_limit=None)


def uncapped(tmp_path, handler):
    return Service(UncappedConfig(), Ledger(tmp_path / "state"), {},
                   httpx.MockTransport(handler), lambda: NOW)


def test_null_is_explicit_opt_out_and_status_is_offline(tmp_path):
    store = ConfigStore(tmp_path)
    store.root.mkdir(mode=0o700)
    file = store.root / "config.json"
    file.touch(mode=0o600)
    file.write_text('{"monthly_budget_usd":null}')
    assert store.settings().monthly_limit is None
    item = uncapped(tmp_path, lambda request: pytest.fail("status sent a request"))
    status = item.status()
    assert status["status"] == "ready"
    assert status["billing_status"] == "uncapped"
    assert status["monthly_budget_usd"] is None
    assert not status["automatic_research_enabled"]
    assert not item.ledger.root.exists()


def test_uncapped_dispatch_without_bound_preserves_old_reservations(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 1
        return httpx.Response(200, json=ANSWER)
    item = uncapped(tmp_path, handler)
    for _ in range(5):
        item.ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    for _ in range(6):
        result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
        assert result["ok"] and result["charged_nanousd"] is None
        assert result["billing_mode"] == "uncapped" and "reservation_id" not in result
    assert len(calls) == 6
    status = item.ledger.unlimited_status(NOW)
    assert status["input_tokens"] == 120
    assert status["requests_this_month"] == 6
    assert status["legacy_capped_accounting"]["used_nanousd"] == MONTHLY_CAP
    assert b"synthetic-key" not in item.ledger.path.read_bytes()


def test_invalid_answer_still_records_usage(tmp_path):
    item = uncapped(tmp_path, lambda request: httpx.Response(200, json={**ANSWER, "answers": {}}))
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "invalid_response"
    assert result["charged_nanousd"] is None
    assert item.ledger.unlimited_status(NOW)["input_tokens"] == 20
    assert item.ledger.unlimited_status(NOW)["unresolved_requests"] == 0


def test_timeout_keeps_unknown_usage_across_months(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout after dispatch", request=request)
    item = uncapped(tmp_path, handler)
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "deadline_exceeded" and len(calls) == 1
    status = item.ledger.unlimited_status(NOW + timedelta(days=2))
    assert status["requests_this_month"] == 0 and status["unresolved_requests"] == 1
    assert status["charged_nanousd"] is None


def test_automatic_private_and_credential_controls_remain(tmp_path):
    item = uncapped(tmp_path, lambda request: pytest.fail("unexpected request"))
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic", "automatic"))
    assert result["error"]["code"] == "automatic_use_unverified"
    result = run(item.evaluate("synthetic-key", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "data_ineligible"
    item.config = ConfigStore(tmp_path / "absent")
    item.config.settings = lambda: Settings(monthly_limit=None)
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "credential_missing"


def test_reenable_cap_cannot_ignore_uncapped_costs(tmp_path):
    item = uncapped(tmp_path, lambda request: httpx.Response(200, json=ANSWER))
    assert run(item.evaluate("synthetic", QUESTIONS, "synthetic"))["ok"]
    item.config = FakeConfig()
    item.bounds = {BOUND.evidence_id: BOUND}
    assert "accounting_unavailable" in item.status()["block_reasons"]
    result = run(item.evaluate("synthetic", QUESTIONS, "synthetic"))
    assert result["error"]["code"] == "accounting_unavailable"
    item.ledger.reserve(BOUND, MONTHLY_CAP, NOW + timedelta(days=2))


def test_duplicate_usage_halts_both_modes(tmp_path):
    ledger = Ledger(tmp_path / "state")
    identifier = ledger.start_unlimited(NOW, META)
    ledger.finish_unlimited(identifier, 1, 2)
    with pytest.raises(EvaluationError):
        ledger.finish_unlimited(identifier, 1, 2)
    with pytest.raises(EvaluationError):
        ledger.start_unlimited(NOW, META)
    with pytest.raises(EvaluationError):
        ledger.reserve(BOUND, MONTHLY_CAP, NOW)


def test_status_does_not_migrate_legacy_database(tmp_path):
    ledger = Ledger(tmp_path / "state")
    ledger.reserve(BOUND, MONTHLY_CAP, NOW)
    before = ledger.path.read_bytes()
    assert ledger.unlimited_status(NOW)["requests_this_month"] == 0
    assert ledger.path.read_bytes() == before
    with sqlite3.connect(ledger.path) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE name='uncapped_requests'")
        assert not table.fetchone()


@pytest.mark.parametrize("value", ["null", False, 0, -1, 6])
def test_only_json_null_opts_out(tmp_path, value):
    store = ConfigStore(tmp_path)
    store.root.mkdir(mode=0o700)
    path = store.root / "config.json"
    path.touch(mode=0o600)
    path.write_text(json.dumps({"monthly_budget_usd": value}))
    with pytest.raises(EvaluationError):
        store.settings()
