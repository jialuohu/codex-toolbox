"""Closed question/answer validation for the inspected TypeSafe v1 HTTP contract."""

import json
import math
import re
from decimal import Decimal, localcontext

from .billing import MODEL
from .errors import EvaluationError

MAX_REQUEST_BYTES = 24 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
ID = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")
TOLERANCE = 1e-5


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def question_body(state: object, questions: dict) -> bytes:
    try:
        if not isinstance(state, (str, dict, list)) or not state:
            raise ValueError
        if not isinstance(questions, dict) or not 1 <= len(questions) <= 16:
            raise ValueError
        for qid, question in questions.items():
            if not isinstance(qid, str) or not ID.fullmatch(qid):
                raise ValueError
            if not isinstance(question, dict) or not set(question) <= {
                "type", "instructions", "criteria",
            } or not {"type", "instructions"} <= set(question):
                raise ValueError
            instructions = question["instructions"]
            if not isinstance(instructions, (str, dict, list)) or not instructions:
                raise ValueError
            criteria = question.get("criteria")
            match question["type"]:
                case "choice":
                    if not isinstance(criteria, dict) or not 1 <= len(criteria) <= 64:
                        raise ValueError
                    if any(not isinstance(k, str) or not k or len(k) > 128
                           or (v is not None and not isinstance(v, str))
                           for k, v in criteria.items()):
                        raise ValueError
                case "score":
                    if not isinstance(criteria, list) or not 2 <= len(criteria) <= 64:
                        raise ValueError
                    if any(not isinstance(v, str) or not v for v in criteria):
                        raise ValueError
                case "noul":
                    if criteria is not None and (
                        not isinstance(criteria, dict) or set(criteria) != {"true", "false"}
                        or any(not isinstance(v, str) for v in criteria.values())
                    ):
                        raise ValueError
                case _:
                    raise ValueError
        body = json_bytes({"model": MODEL, "state": state, "questions": questions})
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError
        return body
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise EvaluationError("invalid_request") from exc


def _unique(pairs: list) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError
        out[key] = value
    return out


def number(value: object, lower: float, upper: float) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and lower <= value <= upper)


def _rounding_interval(value: int | float, upper: int = 1) -> tuple[Decimal, Decimal]:
    """Allow independent rounding to two decimals, retaining finer supplied precision."""
    decimal = Decimal(str(value))
    exponent = decimal.as_tuple().exponent
    assert isinstance(exponent, int)  # Caller has already rejected nonfinite values.
    half_quantum = Decimal(1).scaleb(min(-2, exponent)) / 2
    return max(Decimal(0), decimal - half_quantum), min(Decimal(upper), decimal + half_quantum)


def _expectation_interval(intervals: list[tuple[Decimal, Decimal]]) -> tuple[Decimal, Decimal]:
    """Extrema under interval bounds and the constraint that probabilities sum to one."""
    lower_mass = sum((low for low, _ in intervals), Decimal(0))
    lower_expectation = sum((i * low for i, (low, _) in enumerate(intervals)), Decimal(0))

    def extremum(indices: range) -> Decimal:
        remaining = Decimal(1) - lower_mass
        expectation = lower_expectation
        for i in indices:
            low, high = intervals[i]
            allocated = min(high - low, remaining)
            expectation += i * allocated
            remaining -= allocated
        return expectation

    return extremum(range(len(intervals))), extremum(range(len(intervals) - 1, -1, -1))


def response_envelope(data: bytes) -> dict:
    """Validate reported token usage independently of answer contents."""
    try:
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError
        raw = json.loads(data, object_pairs_hook=_unique)
        if not isinstance(raw, dict) or set(raw) != {"model", "answers", "usage"}:
            raise ValueError
        if raw["model"] != MODEL or not isinstance(raw["answers"], dict):
            raise ValueError
        usage = raw["usage"]
        if (not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}
                or any(type(x) is not int or x < 0 for x in usage.values())):
            raise ValueError
        return raw
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise EvaluationError("invalid_response") from exc


def response_body(data: bytes, questions: dict) -> dict:
    try:
        raw = response_envelope(data)
        if set(raw["answers"]) != set(questions):
            raise ValueError
        for qid, question in questions.items():
            answer = raw["answers"][qid]
            kind = question["type"]
            if not isinstance(answer, dict) or answer.get("type") != kind:
                raise ValueError
            if kind == "noul":
                if set(answer) != {"type", "noul"} or not number(answer["noul"], 0, 1):
                    raise ValueError
                continue
            expected = ({"type", "choice", "probabilities", "confidence"} if kind == "choice"
                        else {"type", "score", "legend", "probabilities", "confidence"})
            if set(answer) != expected or not number(answer["confidence"], 0, 1):
                raise ValueError
            criteria = question["criteria"]
            keys = set(criteria) if kind == "choice" else {str(i) for i in range(len(criteria))}
            probs = answer["probabilities"]
            if not isinstance(probs, dict) or set(probs) != keys:
                raise ValueError
            if any(not number(p, 0, 1) for p in probs.values()):
                raise ValueError
            # 400 digits cover even subnormal JSON float precision without losing
            # the interval widths when summing probability mass near one.
            with localcontext() as context:
                context.prec = 400
                intervals = {key: _rounding_interval(p) for key, p in probs.items()}
                lower_mass = sum((low for low, _ in intervals.values()), Decimal(0))
                upper_mass = sum((high for _, high in intervals.values()), Decimal(0))
                if not lower_mass <= 1 <= upper_mass:
                    raise ValueError
                if kind == "choice":
                    choice = answer["choice"]
                    if not isinstance(choice, str) or choice not in keys:
                        raise ValueError
                    if probs[choice] + TOLERANCE < max(probs.values()):
                        raise ValueError
                else:
                    if answer["legend"] != {str(i): v for i, v in enumerate(criteria)}:
                        raise ValueError
                    score = answer["score"]
                    if not number(score, 0, len(criteria) - 1):
                        raise ValueError
                    low, high = _expectation_interval(
                        [intervals[str(i)] for i in range(len(criteria))])
                    score_low, score_high = _rounding_interval(score, len(criteria) - 1)
                    if score_high < low or score_low > high:
                        raise ValueError
        return raw
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise EvaluationError("invalid_response") from exc
