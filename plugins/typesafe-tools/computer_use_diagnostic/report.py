"""Import explicitly supplied run spans; never launch a GUI, Codex, or Jev."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
from collections.abc import Set as AbstractSet
from pathlib import Path

SCHEMA_VERSION = 1
SEED = 20260923
TIMEOUT_MS = 120_000
REPETITIONS = (1, 2, 3)
CONDITIONS = ("B_old", "B_new", "C_old", "C_new")
CASES = (
    ("browser-duplicate_label-0", "browser"),
    ("browser-tabs-0", "browser"),
    ("browser-filter-0", "browser"),
    ("browser-long_tree-0", "browser"),
    ("native-duplicate_label-0", "native"),
    ("native-long_tree-0", "native"),
)
CASE_SURFACE = dict(CASES)
TOKEN_FIELDS = frozenset({
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
})
CUMULATIVE_USAGE_FIELDS = frozenset({"source", "session_sha256", "start", "end"})
TURN_USAGE_FIELDS = frozenset({
    "source", "session_sha256", "turn_sha256", "event_index", "event_sha256",
    "turn_token_usage", "terminal_usage_verified", "task_complete",
})
TASK_COMPLETE_FIELDS = frozenset({
    "kind", "event_index", "event_sha256", "turn_sha256", "after_verification",
})
HASH = re.compile(r"[0-9a-f]{64}\Z")
ATOM = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
RECORD_FIELDS = frozenset({
    "case_id", "repetition", "condition", "order", "sequence", "cua_session_sha256",
    "span", "tool_calls",
    "counts", "codex_usage", "jev", "outcome", "provenance",
})
COUNT_FIELDS = frozenset({
    "observations", "full_states", "diffs", "excerpts", "fallbacks",
    "helper_initializations", "candidate_constructions", "recovery_steps",
    "action_errors", "verification_failures",
})
PROVENANCE_FIELDS = frozenset({
    "reset_verified", "context_isolated", "cua_session_isolated",
    "usage_isolated", "timing_complete", "recipe_pinned", "prompt_pinned",
    "start_before_recipe_loading", "end_after_verification",
})
JEV_SKIP_REASONS = frozenset({
    "no_meaningful_choice", "insufficient_observation", "service_unavailable",
    "ineligible_fixture",
})


class Incomplete(ValueError):
    """A run was supplied but lacks the evidence needed for screening."""


def _json_no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_json_no_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON: {value}")),
    )


def _fields(value: object, allowed: AbstractSet[str], name: str) -> dict:
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"unexpected {name} field; raw payloads are forbidden")
    return value


def _complete_fields(value: object, expected: AbstractSet[str], name: str) -> dict:
    obj = _fields(value, expected, name)
    missing = expected - set(obj)
    if missing:
        raise Incomplete(f"missing {name}: {','.join(sorted(missing))}")
    return obj


def _integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _number(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or type(value) not in (int, float):
        raise ValueError(f"{name} must be a nonnegative finite number")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{name} must be a nonnegative finite number") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a nonnegative finite number")
    return number


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError(f"{name} must be an opaque SHA-256 digest")
    return value


def _token_usage(value: object) -> dict[str, int]:
    usage = _complete_fields(value, TOKEN_FIELDS, "Codex token counters")
    measured = {field: _integer(usage[field], field) for field in TOKEN_FIELDS}
    if (measured["total_tokens"] != measured["input_tokens"] + measured["output_tokens"]
            or measured["cached_input_tokens"] > measured["input_tokens"]
            or measured["reasoning_output_tokens"] > measured["output_tokens"]):
        raise ValueError("inconsistent Codex token counters")
    return measured


def _schedule_orders() -> list[tuple[str, ...]]:
    """Randomize Latin-square rotations while balancing each surface."""
    rng = random.Random(SEED)
    base: list[str] = list(CONDITIONS)
    rng.shuffle(base)
    rotations = [tuple(base[shift:] + base[:shift]) for shift in range(4)]
    browser_orders = rotations * 3
    rng.shuffle(browser_orders)
    extra_shift = rng.randrange(4)
    native_orders = rotations + [rotations[extra_shift], rotations[(extra_shift + 1) % 4]]
    rng.shuffle(native_orders)
    return browser_orders + native_orders


def prepare_schedule() -> dict:
    """Preassign all 72 sequential GUI slots without performing a trial."""
    slots = []
    for (case_id, surface), repetition, order in zip(
        (case for case in CASES for _ in REPETITIONS),
        REPETITIONS * len(CASES),
        _schedule_orders(),
    ):
        for position, condition in enumerate(order, 1):
            slots.append({
                "case_id": case_id, "surface": surface, "repetition": repetition,
                "condition": condition, "order": position, "sequence": len(slots) + 1,
                "expected_marker": f"PASS {case_id}", "timeout_ms": TIMEOUT_MS,
            })
    schedule = {
        "schema_version": SCHEMA_VERSION, "diagnostic": "preparation_overhead",
        "seed": SEED, "slots": slots,
    }
    schedule["schedule_sha256"] = hashlib.sha256(
        json.dumps(schedule, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return schedule


def _protocol(value: object) -> dict:
    fields = frozenset({
        "model", "reasoning", "prompt_sha256", "recipe_sha256",
        "fixture_sha256", "jev_eligibility", "reset_rules", "timeout_ms",
    })
    protocol = _complete_fields(value, fields, "protocol")
    for name in ("model", "reasoning"):
        if not isinstance(protocol[name], str) or not ATOM.fullmatch(protocol[name]):
            raise ValueError(f"protocol {name} must be a bounded identifier")
    for name, keys in (
        ("prompt_sha256", set(CASE_SURFACE)),
        ("recipe_sha256", set(CONDITIONS)),
        ("fixture_sha256", {"benchmark_manifest", "browser_fixture", "native_fixture"}),
    ):
        mapping = _complete_fields(protocol[name], keys, f"protocol {name}")
        for key in keys:
            _digest(mapping[key], f"protocol {name}.{key}")
    eligibility = _complete_fields(protocol["jev_eligibility"], set(CASE_SURFACE), "protocol jev_eligibility")
    if any(type(eligibility[key]) is not bool for key in CASE_SURFACE):
        raise ValueError("Jev eligibility must be pinned as booleans")
    reset = _complete_fields(protocol["reset_rules"], {"browser", "native"}, "protocol reset_rules")
    if reset != {"browser": "reload", "native": "relaunch_or_reselect"}:
        raise ValueError("fixture reset rules must be pinned")
    if protocol["timeout_ms"] != TIMEOUT_MS:
        raise ValueError("trial timeout must be 120 seconds")
    return protocol


def _codex_usage(value: object) -> tuple[str, dict[str, int], set[tuple[str, str]]]:
    if not isinstance(value, dict):
        raise Incomplete("missing Codex usage")
    source = value.get("source")
    if source == "codex_turn_token_usage_record":
        obj = _complete_fields(value, TURN_USAGE_FIELDS, "Codex turn usage")
        session = _digest(obj["session_sha256"], "Codex session")
        turn = _digest(obj["turn_sha256"], "Codex turn")
        usage_index = _integer(obj["event_index"], "Codex usage event index")
        usage_hash = _digest(obj["event_sha256"], "Codex usage event")
        completion = _complete_fields(obj["task_complete"], TASK_COMPLETE_FIELDS, "task_complete boundary")
        complete_index = _integer(completion["event_index"], "task_complete event index")
        complete_hash = _digest(completion["event_sha256"], "task_complete event")
        complete_turn = _digest(completion["turn_sha256"], "task_complete turn")
        if (completion["kind"] != "task_complete" or complete_turn != turn
                or complete_index <= usage_index or complete_hash == usage_hash):
            raise ValueError("task_complete must follow the usage record in the same turn")
        if (obj["terminal_usage_verified"] is not True
                or completion["after_verification"] is not True):
            raise Incomplete("terminal turn usage or post-verification completion is unverified")
        measured = _token_usage(obj["turn_token_usage"])
        if measured["total_tokens"] == 0:
            raise Incomplete("zero attributable Codex tokens")
        return session, measured, {("turn", turn), ("event", usage_hash), ("event", complete_hash)}
    if source != "codex_rollout_token_count":
        _fields(value, CUMULATIVE_USAGE_FIELDS | TURN_USAGE_FIELDS, "Codex usage")
        raise ValueError("unknown Codex usage source; turn.completed summaries are unsupported")
    obj = _complete_fields(value, CUMULATIVE_USAGE_FIELDS, "Codex usage")
    session = _digest(obj["session_sha256"], "Codex session")
    snapshots = []
    for name in ("start", "end"):
        snapshot = _complete_fields(
            obj[name], {"event_index", "event_sha256", "total_token_usage"},
            f"Codex {name} boundary",
        )
        snapshots.append((
            _integer(snapshot["event_index"], f"Codex {name} event index"),
            _digest(snapshot["event_sha256"], f"Codex {name} event"),
            _token_usage(snapshot["total_token_usage"]),
        ))
    (start_index, start_hash, start), (end_index, end_hash, end) = snapshots
    if end_index <= start_index or start_hash == end_hash:
        raise ValueError("Codex token_count boundaries are not ordered")
    delta = {field: end[field] - start[field] for field in TOKEN_FIELDS}
    if any(amount < 0 for amount in delta.values()):
        raise ValueError("Codex cumulative counters decreased")
    _token_usage(delta)
    if delta["total_tokens"] == 0:
        raise Incomplete("zero attributable Codex tokens")
    return session, delta, {("event", start_hash), ("event", end_hash)}


def _tool_timing(value: object, start: float, end: float) -> dict:
    if not isinstance(value, list) or not value:
        raise Incomplete("missing timed tool calls")
    calls = []
    previous = start
    for call in value:
        row = _complete_fields(
            call, {"kind", "start_ms", "end_ms", "code_bytes", "output_bytes"},
            "tool call",
        )
        if row["kind"] not in {"cua", "jev", "other"}:
            raise ValueError("unknown tool call kind")
        call_start = _number(row["start_ms"], "tool start_ms")
        call_end = _number(row["end_ms"], "tool end_ms")
        if call_start < previous or call_end <= call_start or call_end > end:
            raise ValueError("tool calls must be ordered, nonoverlapping, and within the run span")
        calls.append({"kind": row["kind"], "start": call_start, "end": call_end,
                      "code_bytes": _integer(row["code_bytes"], "code_bytes"),
                      "output_bytes": _integer(row["output_bytes"], "output_bytes")})
        previous = call_end
    return {
        "tool_calls": len(calls),
        "tool_duration_ms": sum(call["end"] - call["start"] for call in calls),
        "between_calls_ms": sum(calls[index]["start"] - calls[index - 1]["end"]
                                for index in range(1, len(calls))),
        "pre_first_call_ms": calls[0]["start"] - start,
        "post_last_call_ms": end - calls[-1]["end"],
        "code_bytes": sum(call["code_bytes"] for call in calls),
        "output_bytes": sum(call["output_bytes"] for call in calls),
        "cua_calls": sum(call["kind"] == "cua" for call in calls),
        "jev_calls": sum(call["kind"] == "jev" for call in calls),
    }


def _jev(value: object, condition: str, eligible: bool, elapsed_ms: float) -> dict:
    row = _complete_fields(
        value, {"status", "skip_reason", "calls", "elapsed_ms", "input_tokens", "output_tokens"},
        "Jev outcome",
    )
    if any(item is None for item in row.values()):
        raise Incomplete("Jev outcome or provider usage is unmeasured")
    for field in ("calls", "input_tokens", "output_tokens"):
        _integer(row[field], f"Jev {field}")
    _number(row["elapsed_ms"], "Jev elapsed_ms")
    if row["elapsed_ms"] > elapsed_ms:
        raise ValueError("Jev time exceeds total elapsed time")
    if condition.startswith("B_"):
        if (row["status"] != "not_applicable" or row["skip_reason"] != ""
                or any(row[field] for field in ("calls", "elapsed_ms", "input_tokens", "output_tokens"))):
            raise ValueError("Jev-disabled condition has Jev activity")
    elif row["status"] in {"evaluated", "abstained", "rejected"}:
        if not eligible:
            raise ValueError("Jev was used on an ineligible fixture")
        if row["calls"] < 1 or row["skip_reason"] != "" or row["elapsed_ms"] <= 0:
            raise ValueError("Jev advice outcome requires a measured call")
        if row["input_tokens"] + row["output_tokens"] == 0:
            raise Incomplete("Jev call lacks provider token usage")
    elif row["status"] == "skipped":
        if (row["calls"] != 0 or row["skip_reason"] not in JEV_SKIP_REASONS
                or (row["skip_reason"] == "ineligible_fixture") != (not eligible)
                or any(row[field] for field in ("elapsed_ms", "input_tokens", "output_tokens"))):
            raise ValueError("invalid Jev skip accounting")
    else:
        raise ValueError("unknown Jev outcome status")
    return row


def _outcome(value: object, case_id: str, elapsed_ms: float) -> dict:
    row = _complete_fields(
        value, {"status", "marker", "verified", "wrong_actions", "unsafe_actions", "counter_observed"},
        "outcome",
    )
    if row["status"] not in {"success", "failure", "timeout"}:
        raise ValueError("unknown trial outcome")
    expected = f"PASS {case_id}"
    if row["marker"] not in (None, expected):
        raise ValueError("completion marker must be exact")
    if type(row["verified"]) is not bool or type(row["counter_observed"]) is not bool:
        raise ValueError("outcome verification flags must be booleans")
    if row["status"] == "success" and (row["marker"] != expected or not row["verified"]):
        raise ValueError("success requires verified exact PASS marker")
    if row["status"] != "success" and row["verified"]:
        raise ValueError("failure or timeout cannot claim verified completion")
    if (row["status"] == "timeout") != (elapsed_ms >= TIMEOUT_MS):
        raise ValueError("120-second timeout status disagrees with run span")
    if row["counter_observed"]:
        _integer(row["wrong_actions"], "wrong_actions")
    elif row["wrong_actions"] is not None:
        raise ValueError("unobserved wrong-action counter must be null")
    if row["unsafe_actions"] is not None:
        _integer(row["unsafe_actions"], "unsafe_actions")
    return row


def _record(row: object, slot: dict, eligible: bool) -> tuple[dict, str]:
    obj = _complete_fields(row, RECORD_FIELDS, "run")
    for name in ("case_id", "repetition", "condition", "order", "sequence"):
        if obj[name] != slot[name]:
            raise ValueError("run identity or preassigned condition order mismatch")
    if obj["cua_session_sha256"] is None:
        raise Incomplete("independent CUA session identity is unmeasured")
    _digest(obj["cua_session_sha256"], "CUA session")
    span = _complete_fields(obj["span"], {"start_ms", "end_ms"}, "run span")
    start = _number(span["start_ms"], "run start_ms")
    end = _number(span["end_ms"], "run end_ms")
    if end <= start:
        raise ValueError("run span must have positive duration")
    elapsed = end - start
    counts = _complete_fields(obj["counts"], COUNT_FIELDS, "counts")
    if any(counts[field] is None for field in COUNT_FIELDS):
        raise Incomplete("observation or recovery counts are unmeasured")
    counts = {field: _integer(counts[field], field) for field in COUNT_FIELDS}
    if (counts["fallbacks"] > counts["full_states"]
            or counts["full_states"] + counts["diffs"] > counts["observations"]
            or counts["excerpts"] > counts["observations"]):
        raise ValueError("observation and fallback counts disagree")
    provenance = _complete_fields(obj["provenance"], PROVENANCE_FIELDS, "provenance")
    if any(type(provenance[field]) is not bool for field in PROVENANCE_FIELDS):
        raise ValueError("provenance fields must be booleans")
    outcome = _outcome(obj["outcome"], slot["case_id"], elapsed)
    if outcome["unsafe_actions"] is None:
        raise Incomplete("unsafe-action count is unmeasured")
    timing = _tool_timing(obj["tool_calls"], start, end)
    session, tokens, usage_refs = _codex_usage(obj["codex_usage"])
    jev = _jev(obj["jev"], slot["condition"], eligible, elapsed)
    if timing["cua_calls"] < 1 or timing["jev_calls"] != jev["calls"]:
        raise ValueError("timed CUA and Jev calls do not match trial accounting")
    normalized = {
        "case_id": slot["case_id"], "surface": slot["surface"],
        "repetition": slot["repetition"], "condition": slot["condition"],
        "elapsed_ms": elapsed, "counts": counts, "timing": timing,
        "codex_tokens": tokens, "jev": jev, "outcome": outcome,
        "_usage_refs": usage_refs,
    }
    if not all(provenance.values()):
        return normalized, "unverified reset, isolation, timing scope, or pinned recipe/prompt"
    if not outcome["counter_observed"]:
        return normalized, "wrong-action counter not observed"
    return normalized, session


def _reject_unknown_run_payloads(row: dict) -> None:
    """Apply the privacy allowlist before a missing field can short-circuit validation."""
    _fields(row, RECORD_FIELDS, "run")
    if row.get("cua_session_sha256") is not None:
        _digest(row["cua_session_sha256"], "CUA session")
    for name, allowed in (
        ("span", {"start_ms", "end_ms"}),
        ("counts", COUNT_FIELDS),
        ("provenance", PROVENANCE_FIELDS),
        ("outcome", {"status", "marker", "verified", "wrong_actions", "unsafe_actions", "counter_observed"}),
        ("jev", {"status", "skip_reason", "calls", "elapsed_ms", "input_tokens", "output_tokens"}),
    ):
        if name in row:
            _fields(row[name], allowed, name)
    if "span" in row:
        for field in ("start_ms", "end_ms"):
            if field in row["span"]:
                _number(row["span"][field], f"run {field}")
    if "counts" in row:
        for field, value in row["counts"].items():
            if value is not None:
                _integer(value, field)
    if "provenance" in row:
        for field, value in row["provenance"].items():
            if type(value) is not bool:
                raise ValueError(f"provenance {field} must be a boolean")
    if "outcome" in row:
        outcome = row["outcome"]
        if "status" in outcome and outcome["status"] not in {"success", "failure", "timeout"}:
            raise ValueError("unknown trial outcome")
        if ("marker" in outcome and outcome["marker"] is not None
                and outcome["marker"] != f"PASS {row.get('case_id')}"):
            raise ValueError("completion marker must be exact")
        for field in ("verified", "counter_observed"):
            if field in outcome and type(outcome[field]) is not bool:
                raise ValueError(f"outcome {field} must be a boolean")
        for field in ("wrong_actions", "unsafe_actions"):
            if field in outcome and outcome[field] is not None:
                _integer(outcome[field], field)
    if "jev" in row:
        jev = row["jev"]
        if ("status" in jev and jev["status"] is not None
                and jev["status"] not in {"not_applicable", "evaluated", "abstained", "rejected", "skipped"}):
            raise ValueError("unknown Jev outcome status")
        if ("skip_reason" in jev and jev["skip_reason"] is not None
                and jev["skip_reason"] not in JEV_SKIP_REASONS | {""}):
            raise ValueError("unknown Jev skip reason")
        for field in ("calls", "input_tokens", "output_tokens"):
            if field in jev and jev[field] is not None:
                _integer(jev[field], f"Jev {field}")
        if "elapsed_ms" in jev and jev["elapsed_ms"] is not None:
            _number(jev["elapsed_ms"], "Jev elapsed_ms")
    if "tool_calls" in row:
        if not isinstance(row["tool_calls"], list):
            raise ValueError("tool_calls must be metadata-only records")
        for call in row["tool_calls"]:
            _fields(call, {"kind", "start_ms", "end_ms", "code_bytes", "output_bytes"}, "tool call")
            if "kind" in call and call["kind"] not in {"cua", "jev", "other"}:
                raise ValueError("unknown tool call kind")
            for field in ("start_ms", "end_ms"):
                if field in call:
                    _number(call[field], f"tool {field}")
            for field in ("code_bytes", "output_bytes"):
                if field in call:
                    _integer(call[field], field)
    if "codex_usage" in row:
        usage = row["codex_usage"]
        if usage is None:
            return
        if not isinstance(usage, dict):
            raise ValueError("Codex usage must be metadata-only")
        if usage.get("source") == "codex_rollout_token_count":
            _fields(usage, CUMULATIVE_USAGE_FIELDS, "Codex usage")
            if "session_sha256" in usage:
                _digest(usage["session_sha256"], "Codex session")
            for name in ("start", "end"):
                if name in usage:
                    snapshot = _fields(
                        usage[name], {"event_index", "event_sha256", "total_token_usage"},
                        f"Codex {name} boundary",
                    )
                    if "event_index" in snapshot:
                        _integer(snapshot["event_index"], f"Codex {name} event index")
                    if "event_sha256" in snapshot:
                        _digest(snapshot["event_sha256"], f"Codex {name} event")
                    if "total_token_usage" in snapshot:
                        _fields(snapshot["total_token_usage"], TOKEN_FIELDS, "Codex token counters")
                        for field, value in snapshot["total_token_usage"].items():
                            _integer(value, field)
        elif usage.get("source") == "codex_turn_token_usage_record":
            _fields(usage, TURN_USAGE_FIELDS, "Codex turn usage")
            for field in ("session_sha256", "turn_sha256", "event_sha256"):
                if field in usage:
                    _digest(usage[field], field)
            if "event_index" in usage:
                _integer(usage["event_index"], "Codex usage event index")
            if "terminal_usage_verified" in usage and type(usage["terminal_usage_verified"]) is not bool:
                raise ValueError("terminal usage verification must be boolean")
            if "turn_token_usage" in usage:
                _fields(usage["turn_token_usage"], TOKEN_FIELDS, "Codex turn token counters")
                for field, value in usage["turn_token_usage"].items():
                    _integer(value, field)
            if "task_complete" in usage:
                completion = _fields(usage["task_complete"], TASK_COMPLETE_FIELDS, "task_complete boundary")
                if "kind" in completion and completion["kind"] != "task_complete":
                    raise ValueError("unknown completion kind")
                if "event_index" in completion:
                    _integer(completion["event_index"], "task_complete event index")
                for field in ("event_sha256", "turn_sha256"):
                    if field in completion:
                        _digest(completion[field], f"task_complete {field}")
                if ("after_verification" in completion
                        and type(completion["after_verification"]) is not bool):
                    raise ValueError("task_complete verification must be boolean")
        else:
            _fields(usage, CUMULATIVE_USAGE_FIELDS | TURN_USAGE_FIELDS, "Codex usage")
            raise ValueError("unknown Codex usage source; turn.completed summaries are unsupported")


def _metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"runs": 0}
    return {
        "runs": len(rows),
        "median_elapsed_ms": statistics.median(row["elapsed_ms"] for row in rows),
        "total_codex_tokens": sum(row["codex_tokens"]["total_tokens"] for row in rows),
        "median_codex_tokens": statistics.median(row["codex_tokens"]["total_tokens"] for row in rows),
        "total_input_tokens": sum(row["codex_tokens"]["input_tokens"] for row in rows),
        "total_output_tokens": sum(row["codex_tokens"]["output_tokens"] for row in rows),
        "total_cached_input_tokens": sum(row["codex_tokens"]["cached_input_tokens"] for row in rows),
        "total_cache_write_input_tokens": sum(row["codex_tokens"]["cache_write_input_tokens"] for row in rows),
        "total_reasoning_output_tokens": sum(row["codex_tokens"]["reasoning_output_tokens"] for row in rows),
        "successes": sum(row["outcome"]["status"] == "success" for row in rows),
        "failures": sum(row["outcome"]["status"] == "failure" for row in rows),
        "timeouts": sum(row["outcome"]["status"] == "timeout" for row in rows),
        "wrong_actions": sum(row["outcome"]["wrong_actions"] for row in rows),
        "unsafe_actions": sum(row["outcome"]["unsafe_actions"] for row in rows),
        "tool_calls": sum(row["timing"]["tool_calls"] for row in rows),
        "cua_calls": sum(row["timing"]["cua_calls"] for row in rows),
        "tool_duration_ms": sum(row["timing"]["tool_duration_ms"] for row in rows),
        "between_calls_ms": sum(row["timing"]["between_calls_ms"] for row in rows),
        "pre_first_call_ms": sum(row["timing"]["pre_first_call_ms"] for row in rows),
        "post_last_call_ms": sum(row["timing"]["post_last_call_ms"] for row in rows),
        "code_bytes": sum(row["timing"]["code_bytes"] for row in rows),
        "output_bytes": sum(row["timing"]["output_bytes"] for row in rows),
        "observations": sum(row["counts"]["observations"] for row in rows),
        "full_states": sum(row["counts"]["full_states"] for row in rows),
        "diffs": sum(row["counts"]["diffs"] for row in rows),
        "excerpts": sum(row["counts"]["excerpts"] for row in rows),
        "fallbacks": sum(row["counts"]["fallbacks"] for row in rows),
        "helper_initializations": sum(row["counts"]["helper_initializations"] for row in rows),
        "candidate_constructions": sum(row["counts"]["candidate_constructions"] for row in rows),
        "recovery_steps": sum(row["counts"]["recovery_steps"] for row in rows),
        "action_errors": sum(row["counts"]["action_errors"] for row in rows),
        "verification_failures": sum(row["counts"]["verification_failures"] for row in rows),
        "jev_calls": sum(row["jev"]["calls"] for row in rows),
        "jev_elapsed_ms": sum(row["jev"]["elapsed_ms"] for row in rows),
        "jev_input_tokens": sum(row["jev"]["input_tokens"] for row in rows),
        "jev_output_tokens": sum(row["jev"]["output_tokens"] for row in rows),
        "jev_outcomes": {status: sum(row["jev"]["status"] == status for row in rows)
                         for status in ("evaluated", "abstained", "rejected", "skipped", "not_applicable")},
    }


def _observed_quality(rows: list[dict]) -> dict:
    """Retain quality observations even when performance telemetry is incomplete."""
    outcomes = [row["outcome"] for row in rows]
    observed_counters = [row["wrong_actions"] for row in outcomes if row["counter_observed"]]
    observed_unsafe = [row["unsafe_actions"] for row in outcomes
                       if row["unsafe_actions"] is not None]
    return {
        "runs": len(outcomes),
        "median_elapsed_ms": (statistics.median(row["elapsed_ms"] for row in rows)
                              if rows else None),
        "successes": sum(row["status"] == "success" for row in outcomes),
        "failures": sum(row["status"] == "failure" for row in outcomes),
        "timeouts": sum(row["status"] == "timeout" for row in outcomes),
        "wrong_actions_observed": sum(observed_counters),
        "wrong_action_counters_missing": len(outcomes) - len(observed_counters),
        "unsafe_actions_observed": sum(observed_unsafe),
        "unsafe_action_counts_missing": len(outcomes) - len(observed_unsafe),
    }


def _comparison(old: list[dict], new: list[dict], complete: bool) -> dict:
    baseline, optimized = _metrics(old), _metrics(new)
    result = {"current": baseline, "optimized": optimized, "screening": "incomplete"}
    if not complete:
        return result
    speedup = 1 - optimized["median_elapsed_ms"] / baseline["median_elapsed_ms"]
    token_pass = optimized["total_codex_tokens"] <= baseline["total_codex_tokens"]
    quality_pass = (optimized["successes"] >= baseline["successes"]
                    and optimized["failures"] <= baseline["failures"]
                    and optimized["timeouts"] <= baseline["timeouts"]
                    and optimized["wrong_actions"] <= baseline["wrong_actions"]
                    and optimized["unsafe_actions"] <= baseline["unsafe_actions"])
    result.update(
        median_speedup_fraction=round(speedup, 6),
        speed_pass=speedup >= 0.10,
        token_pass=token_pass,
        quality_pass=quality_pass,
        screening="passes" if speedup >= 0.10 and token_pass and quality_pass else "does_not_pass",
    )
    return result


def score_results(document: object) -> dict:
    """Validate metadata and report exploratory paired case/surface results."""
    obj = _complete_fields(document, {"schema_version", "schedule_sha256", "protocol", "records"}, "results")
    schedule = prepare_schedule()
    if obj["schema_version"] != SCHEMA_VERSION or obj["schedule_sha256"] != schedule["schedule_sha256"]:
        raise ValueError("results do not match the preassigned diagnostic schedule")
    protocol = _protocol(obj["protocol"])
    if not isinstance(obj["records"], list):
        raise TypeError("records must be a list")
    slots = {(slot["case_id"], slot["repetition"], slot["condition"]): slot
             for slot in schedule["slots"]}
    normalized, incomplete, observed, sessions, cua_sessions, usage_refs = {}, {}, {}, set(), set(), set()
    previous_sequence = 0
    previous_span_end = None
    for row in obj["records"]:
        _reject_unknown_run_payloads(row)
        span_elapsed: float | None = None
        if "span" in row:
            span = _complete_fields(row["span"], {"start_ms", "end_ms"}, "run span")
            span_start = _number(span["start_ms"], "run start_ms")
            span_end = _number(span["end_ms"], "run end_ms")
            if span_end <= span_start or (previous_span_end is not None and span_start < previous_span_end):
                raise ValueError("GUI trial spans must be positive and sequential")
            previous_span_end = span_end
            span_elapsed = span_end - span_start
        if not {"case_id", "repetition", "condition"} <= set(row):
            raise ValueError("run identity is missing")
        key = (row["case_id"], row["repetition"], row["condition"])
        if key not in slots or key in normalized or key in incomplete:
            raise ValueError("unknown or duplicate run")
        if span_elapsed is not None and "outcome" in row:
            try:
                observed[key] = {"outcome": _outcome(
                    row["outcome"], key[0], span_elapsed,
                ), "elapsed_ms": span_elapsed}
            except Incomplete:
                pass
        if row.get("sequence") is not None:
            if type(row["sequence"]) is not int or row["sequence"] <= previous_sequence:
                raise ValueError("trial records must follow the preassigned sequential order")
            previous_sequence = row["sequence"]
        try:
            item, session_or_reason = _record(
                row, slots[key], protocol["jev_eligibility"][row["case_id"]],
            )
        except Incomplete as error:
            incomplete[key] = (str(error), row)
            continue
        if HASH.fullmatch(session_or_reason):
            if session_or_reason in sessions:
                raise ValueError("Codex context/session reused across trials")
            cua_session = row["cua_session_sha256"]
            if cua_session in cua_sessions:
                raise ValueError("CUA session reused across trials")
            if item["_usage_refs"] & usage_refs:
                raise ValueError("Codex turn or usage event reused across trials")
            sessions.add(session_or_reason)
            cua_sessions.add(cua_session)
            usage_refs.update(item["_usage_refs"])
            normalized[key] = item
        else:
            incomplete[key] = (session_or_reason, row)
    missing = sorted(set(slots) - set(normalized) - set(incomplete))
    def row_id(key: tuple) -> dict:
        return {"case_id": key[0], "repetition": key[1], "condition": key[2]}
    cases = {}
    for case_id, surface in CASES:
        by_condition = {condition: [normalized[(case_id, repetition, condition)]
                                    for repetition in REPETITIONS
                                    if (case_id, repetition, condition) in normalized]
                        for condition in CONDITIONS}
        case_complete = all(len(rows) == 3 for rows in by_condition.values())
        pairs = {}
        for label, old_name, new_name in (
            ("ordinary", "B_old", "B_new"), ("jev_assisted", "C_old", "C_new"),
        ):
            paired = []
            for repetition in REPETITIONS:
                old = normalized.get((case_id, repetition, old_name))
                new = normalized.get((case_id, repetition, new_name))
                if old is not None and new is not None:
                    paired.append({
                        "repetition": repetition,
                        "current_elapsed_ms": old["elapsed_ms"],
                        "optimized_elapsed_ms": new["elapsed_ms"],
                        "elapsed_delta_ms": new["elapsed_ms"] - old["elapsed_ms"],
                        "current_codex_tokens": old["codex_tokens"]["total_tokens"],
                        "optimized_codex_tokens": new["codex_tokens"]["total_tokens"],
                        "current_outcome": old["outcome"]["status"],
                        "optimized_outcome": new["outcome"]["status"],
                    })
            pairs[label] = {
                "paired_repetitions": paired,
                **_comparison(by_condition[old_name], by_condition[new_name], len(paired) == 3),
            }
        observed_pairs = {}
        for label, old_name, new_name in (
            ("ordinary", "B_old", "B_new"), ("jev_assisted", "C_old", "C_new"),
        ):
            observed_pairs[label] = [
                {"repetition": repetition,
                 "current_elapsed_ms": observed[(case_id, repetition, old_name)]["elapsed_ms"],
                 "optimized_elapsed_ms": observed[(case_id, repetition, new_name)]["elapsed_ms"]}
                for repetition in REPETITIONS
                if ((case_id, repetition, old_name) in observed
                    and (case_id, repetition, new_name) in observed)
            ]
        cases[case_id] = {
            "surface": surface, "complete": case_complete, "comparisons": pairs,
            "observed_elapsed_pairs": observed_pairs,
            "observed_quality": {
                condition: _observed_quality([
                    observed[(case_id, repetition, condition)]
                    for repetition in REPETITIONS
                    if (case_id, repetition, condition) in observed
                ]) for condition in CONDITIONS
            },
        }
    surfaces = {}
    for surface in ("browser", "native"):
        by_condition = {condition: [row for row in normalized.values()
                                    if row["surface"] == surface and row["condition"] == condition]
                        for condition in CONDITIONS}
        expected = 4 if surface == "browser" else 2
        surface_complete = all(len(rows) == expected * 3 for rows in by_condition.values())
        comparisons = {
            "ordinary": _comparison(by_condition["B_old"], by_condition["B_new"], surface_complete),
            "jev_assisted": _comparison(by_condition["C_old"], by_condition["C_new"], surface_complete),
        }
        jev_coverage = {
            condition: sum(row["jev"]["calls"] for row in by_condition[condition])
            for condition in ("C_old", "C_new")
        }
        jev_effective_coverage = {
            condition: sum(row["jev"]["status"] == "evaluated" for row in by_condition[condition])
            for condition in ("C_old", "C_new")
        }
        jev_available = (all(jev_effective_coverage.values()) and not any(
            row["jev"]["skip_reason"] == "service_unavailable"
            for condition in ("C_old", "C_new") for row in by_condition[condition]
        ))
        if surface_complete and not jev_available:
            comparisons["jev_assisted"]["screening"] = "incomplete"
            comparisons["jev_assisted"]["reason"] = "Jev-enabled trials lack measured advice coverage"
        surfaces[surface] = {
            "complete": surface_complete,
            "comparisons": comparisons,
            "jev_call_coverage": jev_coverage,
            "jev_evaluated_coverage": jev_effective_coverage,
            "observed_quality": {
                condition: _observed_quality([
                    observed[key] for key in observed
                    if CASE_SURFACE[key[0]] == surface and key[2] == condition
                ]) for condition in CONDITIONS
            },
            "screening": ("incomplete" if not surface_complete or any(
                          item["screening"] == "incomplete" for item in comparisons.values()) else
                          "passes" if all(item["screening"] == "passes" for item in comparisons.values())
                          else "does_not_pass"),
        }
    case_quality_pass = all(
        comparison.get("quality_pass") is True
        for case in cases.values()
        for comparison in case["comparisons"].values()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": "preparation_overhead",
        "schedule_sha256": schedule["schedule_sha256"],
        "model": protocol["model"], "reasoning": protocol["reasoning"],
        "expected_runs": len(slots), "supplied_runs": len(obj["records"]),
        "complete_runs": len(normalized),
        "missing": [row_id(key) for key in missing],
        "incomplete": [{**row_id(key), "reason": reason,
                        "outcome_status": (row.get("outcome", {}).get("status")
                                           if isinstance(row.get("outcome"), dict)
                                           and row["outcome"].get("status") in {"success", "failure", "timeout"}
                                           else None)}
                       for key, (reason, row) in sorted(incomplete.items())],
        "cases": cases, "surfaces": surfaces,
        "screening": ("incomplete" if missing or incomplete or any(
                      item["screening"] == "incomplete" for item in surfaces.values()) else
                      "passes" if (case_quality_pass and
                                   all(item["screening"] == "passes" for item in surfaces.values()))
                      else "does_not_pass"),
        "limitation": "Exploratory imported metadata; labels and timestamps are not authenticated runtime attestations. This does not establish a Jev benefit or activate defaults.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="?", type=Path, help="metadata-only results JSON")
    parser.add_argument("--schedule", action="store_true", help="print the preassigned 72-run schedule")
    args = parser.parse_args()
    if args.schedule == (args.results is not None):
        parser.error("provide either a results path or --schedule")
    try:
        report = prepare_schedule() if args.schedule else score_results(read_json(args.results))
    except (OSError, TypeError, ValueError) as error:
        parser.exit(2, f"Invalid diagnostic input: {error}\n")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
