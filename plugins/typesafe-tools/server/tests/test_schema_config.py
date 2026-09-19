"""Pure schema and protected configuration checks; no credentials or provider calls."""

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from typesafe_tools.billing import (
    MODEL,
    MONTHLY_CAP,
    NANOUSD,
    VERIFIED_BOUNDS,
    VERIFIED_PILOTS,
)
from typesafe_tools.config import ConfigStore, Settings, codex_home, protected_read
from typesafe_tools.errors import EvaluationError
from typesafe_tools.schema import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    json_bytes,
    question_body,
    response_body,
)


@pytest.fixture
def questions() -> dict:
    return {
        "choice": {
            "type": "choice",
            "instructions": "Select the passage that supports the claim.",
            "criteria": {"a": "direct evidence", "b": "unrelated evidence"},
        },
        "score": {
            "type": "score",
            "instructions": "Rate the supplied evidence.",
            "criteria": ["unsupported", "partial", "supported"],
        },
        "noul": {"type": "noul", "instructions": "The passage supports the claim."},
    }


@pytest.fixture
def response() -> dict:
    return {
        "model": MODEL,
        "answers": {
            "choice": {
                "type": "choice",
                "choice": "a",
                "probabilities": {"a": 0.75, "b": 0.25},
                "confidence": 0.6,
            },
            "score": {
                "type": "score",
                "score": 1.2,
                "legend": {"0": "unsupported", "1": "partial", "2": "supported"},
                "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
                "confidence": 0.7,
            },
            "noul": {"type": "noul", "noul": 0.8},
        },
        "usage": {"input_tokens": 110, "output_tokens": 0},
    }


def test_all_primitives_validate(questions: dict, response: dict) -> None:
    body = json.loads(question_body({"passages": ["Public fact"]}, questions))
    assert body == {"model": MODEL, "state": {"passages": ["Public fact"]},
                    "questions": questions}
    assert response_body(json_bytes(response), questions) == response


def test_question_count_bound(questions: dict) -> None:
    sixteen = {f"q_{i}": questions["noul"] for i in range(16)}
    assert len(json.loads(question_body("synthetic", sixteen))["questions"]) == 16
    sixteen["q_16"] = questions["noul"]
    with pytest.raises(EvaluationError, match="payload limits"):
        question_body("synthetic", sixteen)
    with pytest.raises(EvaluationError):
        question_body("synthetic", {})


def test_exact_total_utf8_payload_boundary(questions: dict) -> None:
    # UTF-8 bytes include model, question instructions/options and state overhead.
    base = len(question_body("x", questions)) - 1
    available = MAX_REQUEST_BYTES - base
    state = "界" * (available // 3) + "x" * (available % 3)
    assert len(state) < available
    assert len(question_body(state, questions)) == MAX_REQUEST_BYTES
    with pytest.raises(EvaluationError):
        question_body(state + "x", questions)
    expanded = deepcopy(questions)
    expanded["choice"]["criteria"]["b"] += "界"
    with pytest.raises(EvaluationError):
        question_body(state, expanded)


@pytest.mark.parametrize("state", [None, False, 17, "", {}, [], {"n": float("nan")}])
def test_invalid_state(state: object, questions: dict) -> None:
    with pytest.raises(EvaluationError):
        question_body(state, questions)


@pytest.mark.parametrize("bad", [
    {"type": "choice", "instructions": "x", "criteria": {}},
    {"type": "choice", "instructions": "x", "criteria": {"a": 1}},
    {"type": "choice", "instructions": "x", "criteria": {"": "bad"}},
    {"type": "choice", "instructions": "x", "criteria": {"a" * 129: "bad"}},
    {"type": "score", "instructions": "x", "criteria": ["only one"]},
    {"type": "score", "instructions": "x", "criteria": ["ok", ""]},
    {"type": "noul", "instructions": "x", "criteria": {"true": "x"}},
    {"type": "noul", "instructions": "x", "criteria": {"true": 1, "false": "x"}},
    {"type": "unknown", "instructions": "x"},
    {"type": "noul", "instructions": ""},
    {"type": "noul", "instructions": "x", "model": "other"},
])
def test_invalid_question_shapes(bad: dict) -> None:
    with pytest.raises(EvaluationError):
        question_body("public", {"q": bad})


@pytest.mark.parametrize("qid", ["", "9first", "has space", "x" * 65, "q\n", 1])
def test_question_ids_are_bounded(qid: object, questions: dict) -> None:
    with pytest.raises(EvaluationError):
        question_body("public", {qid: questions["noul"]})


def test_noul_explicit_criteria_and_null_choice_description(questions: dict) -> None:
    questions["noul"]["criteria"] = {"true": "supported", "false": "unsupported"}
    questions["choice"]["criteria"]["a"] = None
    assert question_body("public", questions)


@pytest.mark.parametrize("field,value", [
    ("confidence", float("nan")), ("confidence", float("inf")),
    ("confidence", True), ("confidence", -0.1), ("confidence", 1.1),
    ("choice", "missing"), ("choice", "b"),
    ("probabilities", {"a": 0.4, "b": 0.4}),
    ("probabilities", {"a": 0.75, "b": 0.25, "c": 0}),
    ("probabilities", {"a": 1, "b": float("nan")}),
    ("probabilities", {"a": True, "b": False}),
    ("probabilities", {"a": 1.1, "b": -0.1}),
])
def test_invalid_choice_responses(
    field: str, value: object, questions: dict, response: dict,
) -> None:
    response["answers"]["choice"][field] = value
    with pytest.raises(EvaluationError) as error:
        response_body(json.dumps(response).encode(), questions)
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("field,value", [
    ("score", 1.3), ("score", -1), ("score", 3), ("score", True),
    ("score", float("inf")), ("score", float("nan")),
    ("legend", {"0": "wrong", "1": "partial", "2": "supported"}),
    ("probabilities", {"0": 0.1, "1": 0.9}),
])
def test_invalid_score_responses(
    field: str, value: object, questions: dict, response: dict,
) -> None:
    response["answers"]["score"][field] = value
    with pytest.raises(EvaluationError):
        response_body(json.dumps(response).encode(), questions)


@pytest.mark.parametrize("value", [True, None, "0.8", -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_noul_responses(value: object, questions: dict, response: dict) -> None:
    response["answers"]["noul"]["noul"] = value
    with pytest.raises(EvaluationError):
        response_body(json.dumps(response).encode(), questions)


@pytest.mark.parametrize("value", [True, -1, 1.1, "100", float("nan"), None])
def test_usage_requires_nonnegative_integers(
    value: object, questions: dict, response: dict,
) -> None:
    response["usage"]["input_tokens"] = value
    with pytest.raises(EvaluationError):
        response_body(json.dumps(response).encode(), questions)


def test_model_answer_fields_and_count_are_closed(questions: dict, response: dict) -> None:
    for change in ["model", "missing", "extra", "extra_field", "wrong_type", "usage"]:
        modified = deepcopy(response)
        if change == "model":
            modified["model"] = "other-model"
        elif change == "missing":
            del modified["answers"]["choice"]
        elif change == "extra":
            modified["answers"]["injected"] = modified["answers"]["noul"]
        elif change == "extra_field":
            modified["answers"]["noul"]["instructions"] = "untrusted"
        elif change == "wrong_type":
            modified["answers"]["noul"]["type"] = "choice"
        else:
            modified["usage"]["total_tokens"] = 110
        with pytest.raises(EvaluationError):
            response_body(json_bytes(modified), questions)


def test_duplicate_json_fields_are_rejected(questions: dict, response: dict) -> None:
    body = json_bytes(response)
    for bad in [
        body.replace(b'"model":', b'"model":"other","model":', 1),
        body.replace(b'"noul":0.8', b'"noul":0.8,"noul":0.9'),
        body.replace(b'"a":0.75', b'"a":0.75,"a":0.75'),
    ]:
        with pytest.raises(EvaluationError):
            response_body(bad, questions)


@pytest.mark.parametrize("data", [b"not json", b"[]", b"null", b"\xff", b"{}"])
def test_malformed_response(data: bytes, questions: dict) -> None:
    with pytest.raises(EvaluationError):
        response_body(data, questions)


def test_response_size_is_bounded(questions: dict, response: dict) -> None:
    body = json_bytes(response)
    assert response_body(body + b" " * (MAX_RESPONSE_BYTES - len(body)), questions)
    with pytest.raises(EvaluationError):
        response_body(body + b" " * (MAX_RESPONSE_BYTES - len(body) + 1), questions)


@pytest.fixture
def config(tmp_path: Path) -> ConfigStore:
    root = tmp_path / "secrets/typesafe"
    root.mkdir(parents=True, mode=0o700)
    return ConfigStore(tmp_path / "secrets")


def write_private(path: Path, data: str) -> None:
    path.write_text(data)
    path.chmod(0o600)


def test_missing_config_defaults_without_writes(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "absent")
    assert store.settings() == Settings()
    assert not (tmp_path / "absent").exists()
    with pytest.raises(EvaluationError) as error:
        store.api_key()
    assert error.value.code == "credential_missing"


def test_private_key_and_budget_config(config: ConfigStore) -> None:
    write_private(config.root / "api-key", "synthetic-key-for-test-only\n")
    assert config.api_key() == "synthetic-key-for-test-only"
    write_private(config.root / "config.json", '{"monthly_budget_usd":"2.50"}')
    assert config.settings().monthly_limit == 5 * NANOUSD // 2
    assert config.settings().model == MODEL


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o666, 0o604])
def test_key_mode_rejected(config: ConfigStore, mode: int) -> None:
    path = config.root / "api-key"
    write_private(path, "synthetic-key-for-test-only")
    path.chmod(mode)
    with pytest.raises(EvaluationError):
        config.api_key()


def test_public_parent_mode_rejected(config: ConfigStore) -> None:
    write_private(config.root / "api-key", "synthetic-key-for-test-only")
    config.root.chmod(0o755)
    with pytest.raises(EvaluationError):
        config.api_key()


def test_key_symlink_rejected(config: ConfigStore) -> None:
    target = config.root / "source"
    write_private(target, "synthetic-key-for-test-only")
    (config.root / "api-key").symlink_to(target)
    with pytest.raises(EvaluationError):
        config.api_key()


def test_parent_symlink_rejected(config: ConfigStore, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    write_private(target / "api-key", "synthetic-key-for-test-only")
    config.root.rmdir()
    config.root.symlink_to(target, target_is_directory=True)
    with pytest.raises(EvaluationError):
        config.api_key()


@pytest.mark.skipif(os.name != "posix", reason="POSIX protection contract")
def test_fifo_is_rejected_without_blocking(config: ConfigStore) -> None:
    os.mkfifo(config.root / "api-key", mode=0o600)
    with pytest.raises(EvaluationError):
        config.api_key()


@pytest.mark.skipif(os.name != "posix", reason="POSIX protection contract")
def test_hardlinked_key_rejected(config: ConfigStore) -> None:
    path = config.root / "api-key"
    write_private(path, "synthetic-key-for-test-only")
    os.link(path, config.root / "alias")
    with pytest.raises(EvaluationError):
        config.api_key()


@pytest.mark.parametrize("value", ["", " ", "not valid key", "contains\x00nul", "界", "x" * 4097])
def test_invalid_key_contents(config: ConfigStore, value: str) -> None:
    write_private(config.root / "api-key", value)
    with pytest.raises(EvaluationError):
        config.api_key()


def test_protected_size_limit(config: ConfigStore) -> None:
    path = config.root / "file"
    write_private(path, "1234")
    assert protected_read(path, 4) == b"1234"
    with pytest.raises(EvaluationError):
        protected_read(path, 3)


@pytest.mark.parametrize("value", [
    '{"monthly_budget_usd":"5.01"}', '{"monthly_budget_usd":0}',
    '{"monthly_budget_usd":-1}', '{"monthly_budget_usd":"NaN"}',
    '{"monthly_budget_usd":"Infinity"}', '{"monthly_budget_usd":"0.0000000001"}',
    '{"monthly_budget_usd":true}', '{"model":"other"}',
    '{"billing_evidence_id":true}', '{"pilot_evidence_id":3}',
    '{"automatic_research":"true"}', '{"verified":true}',
    '{"hard_cap_verified":true}', '{"endpoint":"https://example.invalid"}',
    '[]', 'null', 'not json',
])
def test_invalid_or_self_attesting_configuration(config: ConfigStore, value: str) -> None:
    write_private(config.root / "config.json", value)
    with pytest.raises(EvaluationError):
        config.settings()


def test_caller_evidence_ids_do_not_verify_billing_or_pilot(config: ConfigStore) -> None:
    write_private(config.root / "config.json", json.dumps({
        "billing_evidence_id": "caller-assertion", "pilot_evidence_id": "caller-assertion",
        "automatic_research": True,
    }))
    settings = config.settings()
    assert settings.monthly_limit == MONTHLY_CAP
    assert settings.billing_evidence_id not in VERIFIED_BOUNDS
    assert settings.pilot_evidence_id not in VERIFIED_PILOTS
    assert not VERIFIED_BOUNDS
    assert not VERIFIED_PILOTS


def test_config_is_protected_as_key(config: ConfigStore) -> None:
    path = config.root / "config.json"
    write_private(path, "{}")
    path.chmod(0o644)
    with pytest.raises(EvaluationError):
        config.settings()


def test_relative_roots_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_HOME", "relative")
    with pytest.raises(EvaluationError):
        codex_home()
    with pytest.raises(EvaluationError):
        ConfigStore(Path("relative"))
