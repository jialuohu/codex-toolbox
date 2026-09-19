"""Probability and Score consistency under independently rounded provider values."""

from copy import deepcopy

import pytest

from typesafe_tools.billing import MODEL
from typesafe_tools.errors import EvaluationError
from typesafe_tools.schema import json_bytes, response_body


def score_fixture(probabilities: list[float], score: float) -> tuple[dict, dict]:
    criteria = [f"Level {i}" for i in range(len(probabilities))]
    questions = {"q": {"type": "score", "instructions": "Rate synthetic evidence.",
                       "criteria": criteria}}
    response = {
        "model": MODEL,
        "answers": {"q": {
            "type": "score", "score": score, "confidence": 0.31,
            "legend": {str(i): label for i, label in enumerate(criteria)},
            "probabilities": {str(i): p for i, p in enumerate(probabilities)},
        }},
        "usage": {"input_tokens": 386, "output_tokens": 33},
    }
    return questions, response


def test_observed_synthetic_score_rounding_preserves_raw_values() -> None:
    criteria = ["No relevant facts.", "Partial evidence.", "Direct complete evidence."]
    questions = {name: {"type": "score", "instructions": "Rate the supplied evidence.",
                        "criteria": criteria} for name in ("memory", "throughput")}
    response = {
        "model": MODEL,
        "answers": {
            "memory": {
                "type": "score", "score": 2.0, "confidence": 1.0,
                "legend": {str(i): label for i, label in enumerate(criteria)},
                "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0},
            },
            "throughput": {
                "type": "score", "score": 0.55, "confidence": 0.31,
                "legend": {str(i): label for i, label in enumerate(criteria)},
                "probabilities": {"0": 0.46, "1": 0.54, "2": 0.0},
            },
        },
        "usage": {"input_tokens": 386, "output_tokens": 33},
    }
    before = deepcopy(response)
    validated = response_body(json_bytes(response), questions)
    assert validated == before
    assert validated["answers"]["throughput"]["score"] == 0.55
    assert validated["answers"]["throughput"]["probabilities"]["1"] == 0.54
    assert response == before


@pytest.mark.parametrize("levels,probability,score", [
    (2, 0.5, 0.5), (16, 0.06, 7.5), (64, 0.02, 31.5),
])
def test_two_decimal_distributions_admit_mass_one(
    levels: int, probability: float, score: float,
) -> None:
    questions, response = score_fixture([probability] * levels, score)
    assert response_body(json_bytes(response), questions) == response


@pytest.mark.parametrize("levels,probability", [(2, 0.49), (16, 0.04), (64, 0.03)])
def test_impossible_probability_mass_rejected(levels: int, probability: float) -> None:
    questions, response = score_fixture([probability] * levels, (levels - 1) / 2)
    with pytest.raises(EvaluationError) as error:
        response_body(json_bytes(response), questions)
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("levels,probability,score", [
    (2, 0.5, 0.8), (16, 0.06, 10.0), (64, 0.02, 45.0),
])
def test_large_score_mismatch_rejected(levels: int, probability: float, score: float) -> None:
    questions, response = score_fixture([probability] * levels, score)
    with pytest.raises(EvaluationError):
        response_body(json_bytes(response), questions)


@pytest.mark.parametrize("probabilities,score", [
    ([0.333333, 0.666667], 0.666667),
    ([0.0625] * 16, 7.5),
    ([0.015625] * 64, 31.5),
])
def test_finer_probability_precision_preserved(probabilities: list[float], score: float) -> None:
    questions, response = score_fixture(probabilities, score)
    assert response_body(json_bytes(response), questions) == response


@pytest.mark.parametrize("probabilities,score", [
    ([0.333333, 0.666667], 0.6668),
    ([0.0625] * 16, 7.5033),
    ([0.015625] * 64, 31.5006),
])
def test_finer_precision_does_not_get_two_decimal_epsilon(
    probabilities: list[float], score: float,
) -> None:
    questions, response = score_fixture(probabilities, score)
    with pytest.raises(EvaluationError):
        response_body(json_bytes(response), questions)


def test_distribution_must_admit_one_at_supplied_finer_precision() -> None:
    questions, response = score_fixture([0.4999, 0.4999], 0.5)
    with pytest.raises(EvaluationError):
        response_body(json_bytes(response), questions)


def test_score_bin_must_intersect_mass_constrained_expectation() -> None:
    # Independent endpoint multiplication gives a lower bound of 0.995, but
    # allocating the missing 0.015 mass under sum-one requires expectation >= 1.
    questions, response = score_fixture([0.33, 0.33, 0.34], 0.997)
    with pytest.raises(EvaluationError):
        response_body(json_bytes(response), questions)


@pytest.mark.parametrize("score", [-0.001, 1.001])
def test_raw_score_range_is_checked_before_rounding(score: float) -> None:
    probabilities = [1.0, 0.0] if score < 0 else [0.0, 1.0]
    questions, response = score_fixture(probabilities, score)
    with pytest.raises(EvaluationError):
        response_body(json_bytes(response), questions)


def test_choice_rounded_probabilities_keep_maximum_choice_check() -> None:
    questions = {"q": {"type": "choice", "instructions": "Select synthetic evidence.",
                       "criteria": {"a": "A", "b": "B", "c": "C"}}}
    response = {
        "model": MODEL,
        "answers": {"q": {"type": "choice", "choice": "c", "confidence": 0.4,
                          "probabilities": {"a": 0.33, "b": 0.33, "c": 0.35}}},
        "usage": {"input_tokens": 1, "output_tokens": 0},
    }
    assert response_body(json_bytes(response), questions) == response
    response["answers"]["q"]["choice"] = "a"
    with pytest.raises(EvaluationError):
        response_body(json_bytes(response), questions)


def test_subnormal_probability_retains_finite_rounding_interval() -> None:
    questions, response = score_fixture([5e-324, 1.0], 1.0)
    assert response_body(json_bytes(response), questions) == response
