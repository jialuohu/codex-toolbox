"""Public protocol fixtures contain schemas, never live tasks or ledger records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator, ValidationError
from protocol_contract import CONTRACT, validate_client_request, validate_server_response

from codex_task_tools.compatibility import SUPPORTED_APP_VERSIONS


def test_public_contract_schema_and_qualified_versions() -> None:
    Draft7Validator.check_schema(CONTRACT)
    qualification = json.loads(
        (Path(__file__).parent / "fixtures/app-server-compatibility.json").read_text()
    )
    assert set(qualification["versions"]) == SUPPORTED_APP_VERSIONS
    assert CONTRACT["x-source"]["version"] == "0.159.0"
    assert set(CONTRACT["x-source"]["original_schema_sha256"]) <= set(qualification["schemas"])
    for name, digest in CONTRACT["x-source"]["original_schema_sha256"].items():
        assert digest == qualification["schemas"][name]["schema_sha256"]["0.159.0"]


@pytest.mark.parametrize(("method", "params"), [
    ("thread/read", {"threadId": "synthetic-thread", "includeTurns": True}),
    ("thread/loaded/list", {"cursor": None, "limit": 100}),
])
def test_read_only_probe_payload_contract(method: str, params: dict[str, Any]) -> None:
    validate_client_request(method, params)


@pytest.mark.parametrize(("method", "params"), [
    ("thread/read", {"includeTurns": True}),
    ("thread/read", {"threadId": 17}),
    ("turn/start", {"threadId": "synthetic-thread", "input": [{"type": "text", "text": 17}]}),
    ("thread/loaded/list", {"limit": -1}),
])
def test_malformed_broker_request_payloads_fail_schema_validation(
    method: str, params: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        validate_client_request(method, params)


@pytest.mark.parametrize(("method", "result"), [
    ("item/commandExecution/requestApproval", {"decision": "decline"}),
    ("item/fileChange/requestApproval", {"decision": "accept"}),
    ("item/tool/requestUserInput", {"answers": {"synthetic-question": {"answers": ["choice"]}}}),
])
def test_supported_approval_response_payloads_match_generated_schema(
    method: str, result: dict[str, Any],
) -> None:
    validate_server_response(method, result)


@pytest.mark.parametrize(("method", "result"), [
    ("item/commandExecution/requestApproval", {"decision": "continueAnyway"}),
    ("item/fileChange/requestApproval", {"decision": True}),
    ("item/tool/requestUserInput", {"answers": {"synthetic-question": {"answers": 17}}}),
])
def test_invalid_approval_response_payloads_fail_schema_validation(
    method: str, result: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        validate_server_response(method, result)
