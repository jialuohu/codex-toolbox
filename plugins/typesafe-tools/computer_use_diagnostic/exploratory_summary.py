"""Describe measured trial pairs without changing the diagnostic screening gate.

Only allowlisted metadata from ``report.score_results`` input is read. The
summary does not infer missing token counters, CUA sessions, operation counts,
or unsafe-action counts, and it never launches a GUI trial.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from . import report

COMPARISONS = (
    ("ordinary", "B_old", "B_new"),
    ("jev_assisted", "C_old", "C_new"),
)


def _median(values: list[int | float]) -> int | float | None:
    return statistics.median(values) if values else None


def _terminal_turn_usage(value: object) -> tuple[str, dict[str, int], set[tuple[str, str]], bool]:
    """Validate terminal usage even when a failed turn has no verified PASS marker.

    A normal failed exit still has a terminal usage record followed by its
    task_complete event. Its ``after_verification`` flag remains false because
    completion was not verified; that flag remains mandatory for screening.
    """
    obj = report._complete_fields(value, report.TURN_USAGE_FIELDS, "Codex turn usage")
    session = report._digest(obj["session_sha256"], "Codex session")
    turn = report._digest(obj["turn_sha256"], "Codex turn")
    usage_index = report._integer(obj["event_index"], "Codex usage event index")
    usage_hash = report._digest(obj["event_sha256"], "Codex usage event")
    completion = report._complete_fields(
        obj["task_complete"], report.TASK_COMPLETE_FIELDS, "task_complete boundary",
    )
    complete_index = report._integer(completion["event_index"], "task_complete event index")
    complete_hash = report._digest(completion["event_sha256"], "task_complete event")
    complete_turn = report._digest(completion["turn_sha256"], "task_complete turn")
    if (completion["kind"] != "task_complete" or complete_turn != turn
            or complete_index <= usage_index or complete_hash == usage_hash):
        raise ValueError("task_complete must follow the usage record in the same turn")
    if type(completion["after_verification"]) is not bool:
        raise ValueError("task_complete verification must be boolean")
    if obj["terminal_usage_verified"] is not True:
        raise report.Incomplete("terminal turn usage is unverified")
    measured = report._token_usage(obj["turn_token_usage"])
    if measured["total_tokens"] == 0:
        raise report.Incomplete("zero attributable Codex tokens")
    return (session, measured,
            {("turn", turn), ("event", usage_hash), ("event", complete_hash)},
            completion["after_verification"])


def _trial(row: dict[str, Any]) -> dict[str, Any]:
    """Revalidate the measured fields that incomplete screening skips."""
    elapsed: float | None = None
    if "span" in row:
        span = report._complete_fields(row["span"], {"start_ms", "end_ms"}, "run span")
        start = report._number(span["start_ms"], "run start_ms")
        end = report._number(span["end_ms"], "run end_ms")
        if end <= start:
            raise ValueError("run span must have positive duration")
        elapsed = end - start

    outcome = None
    if elapsed is not None and "outcome" in row:
        try:
            outcome = report._outcome(row["outcome"], row["case_id"], elapsed)
        except report.Incomplete:
            pass

    token_count = None
    usage = None
    if "codex_usage" in row:
        try:
            supplied = row["codex_usage"]
            if isinstance(supplied, dict) and supplied.get("source") == "codex_turn_token_usage_record":
                session, usage, references, after_verification = _terminal_turn_usage(supplied)
                if not after_verification and (outcome is None or outcome["status"] != "failure"):
                    usage = None
            else:
                session, usage, references = report._codex_usage(supplied)
        except report.Incomplete:
            session, references = None, set()
    else:
        session, references = None, set()

    provenance = row.get("provenance")
    if (usage is not None and outcome is not None and outcome["status"] != "timeout"
            and isinstance(provenance, dict)
            and provenance.get("context_isolated") is True
            and provenance.get("usage_isolated") is True):
        token_count = usage["total_tokens"]

    return {
        "elapsed_ms": elapsed,
        "codex_total_tokens": token_count,
        "status": outcome["status"] if outcome is not None else None,
        "wrong_actions": (outcome["wrong_actions"] if outcome is not None
                          and outcome["counter_observed"] else None),
        "_session": session,
        "_usage_refs": references,
    }


def _quality(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "supplied_runs": len(rows),
        "successes": sum(row["status"] == "success" for row in rows),
        "failures": sum(row["status"] == "failure" for row in rows),
        "timeouts": sum(row["status"] == "timeout" for row in rows),
        "outcomes_unmeasured": sum(row["status"] is None for row in rows),
        "wrong_actions_observed": sum(row["wrong_actions"] for row in rows
                                      if row["wrong_actions"] is not None),
        "wrong_action_counters_missing": sum(row["wrong_actions"] is None for row in rows),
    }


def _comparison(
    case_ids: tuple[str, ...], label: str, old_name: str, new_name: str,
    trials: dict[tuple[str, int, str], dict[str, Any]],
) -> dict[str, Any]:
    current = [trials[(case_id, repetition, old_name)]
               for case_id in case_ids for repetition in report.REPETITIONS
               if (case_id, repetition, old_name) in trials]
    optimized = [trials[(case_id, repetition, new_name)]
                 for case_id in case_ids for repetition in report.REPETITIONS
                 if (case_id, repetition, new_name) in trials]
    pairs = []
    elapsed_pairs = []
    token_pairs = []
    for case_id in case_ids:
        for repetition in report.REPETITIONS:
            old = trials.get((case_id, repetition, old_name))
            new = trials.get((case_id, repetition, new_name))
            if old is None or new is None:
                continue
            pair = {
                "case_id": case_id,
                "repetition": repetition,
                "current": {key: old[key] for key in
                            ("elapsed_ms", "codex_total_tokens", "status", "wrong_actions")},
                "optimized": {key: new[key] for key in
                              ("elapsed_ms", "codex_total_tokens", "status", "wrong_actions")},
            }
            if old["elapsed_ms"] is not None and new["elapsed_ms"] is not None:
                elapsed_pairs.append((old["elapsed_ms"], new["elapsed_ms"]))
                pair["elapsed_delta_ms"] = new["elapsed_ms"] - old["elapsed_ms"]
            else:
                pair["elapsed_delta_ms"] = None
            if old["codex_total_tokens"] is not None and new["codex_total_tokens"] is not None:
                token_pairs.append((old["codex_total_tokens"], new["codex_total_tokens"]))
                pair["codex_token_delta"] = (new["codex_total_tokens"]
                                             - old["codex_total_tokens"])
            else:
                pair["codex_token_delta"] = None
            pairs.append(pair)
    return {
        "label": label,
        "expected_pairs": len(case_ids) * len(report.REPETITIONS),
        "supplied_pairs": len(pairs),
        "elapsed_pairs": len(elapsed_pairs),
        "token_pairs": len(token_pairs),
        "median_current_elapsed_ms": _median([old for old, _ in elapsed_pairs]),
        "median_optimized_elapsed_ms": _median([new for _, new in elapsed_pairs]),
        "median_paired_elapsed_delta_ms": _median([new - old for old, new in elapsed_pairs]),
        "median_current_codex_total_tokens": _median([old for old, _ in token_pairs]),
        "median_optimized_codex_total_tokens": _median([new for _, new in token_pairs]),
        "median_paired_codex_token_delta": _median([new - old for old, new in token_pairs]),
        "current_quality": _quality(current),
        "optimized_quality": _quality(optimized),
        "paired_repetitions": pairs,
    }


def summarize_results(document: object) -> dict[str, Any]:
    """Validate first, then report only observed elapsed, usage, and quality."""
    scored = report.score_results(document)
    assert isinstance(document, dict)  # score_results already verified this.
    trials: dict[tuple[str, int, str], dict[str, Any]] = {}
    sessions: set[str] = set()
    usage_refs: set[tuple[str, str]] = set()
    missing_tokens = 0
    missing_sessions = 0
    missing_counts = 0
    missing_unsafe = 0
    for row in document["records"]:
        trial = _trial(row)
        session = trial.pop("_session")
        references = trial.pop("_usage_refs")
        if session is not None:
            if session in sessions or references & usage_refs:
                raise ValueError("Codex context, turn, or usage event reused across trials")
            sessions.add(session)
            usage_refs.update(references)
        missing_tokens += trial["codex_total_tokens"] is None
        missing_sessions += row.get("cua_session_sha256") is None
        counts = row.get("counts")
        missing_counts += not isinstance(counts, dict) or any(
            counts.get(field) is None for field in report.COUNT_FIELDS
        )
        outcome = row.get("outcome")
        missing_unsafe += not isinstance(outcome, dict) or outcome.get("unsafe_actions") is None
        trials[(row["case_id"], row["repetition"], row["condition"])] = trial

    cases = {
        case_id: {
            "surface": surface,
            "comparisons": {
                label: _comparison((case_id,), label, old_name, new_name, trials)
                for label, old_name, new_name in COMPARISONS
            },
        }
        for case_id, surface in report.CASES
    }
    surfaces = {
        surface: {
            "comparisons": {
                label: _comparison(
                    tuple(case_id for case_id, case_surface in report.CASES
                          if case_surface == surface),
                    label, old_name, new_name, trials,
                )
                for label, old_name, new_name in COMPARISONS
            },
        }
        for surface in ("browser", "native")
    }
    return {
        "schema_version": report.SCHEMA_VERSION,
        "diagnostic": "preparation_overhead_exploratory",
        "screening": scored["screening"],
        "screening_status_source": "computer_use_diagnostic.report.score_results",
        "expected_runs": scored["expected_runs"],
        "supplied_runs": scored["supplied_runs"],
        "complete_screening_runs": scored["complete_runs"],
        "missing_runs": len(scored["missing"]),
        "incomplete_screening_runs": len(scored["incomplete"]),
        "measurements_missing": {
            "codex_total_tokens": missing_tokens,
            "cua_session_identity": missing_sessions,
            "exact_operation_counts": missing_counts,
            "unsafe_action_count": missing_unsafe,
        },
        "cases": cases,
        "surfaces": surfaces,
        "limitation": (
            "Descriptive pairs only. Missing measurements remain null; incomplete screening "
            "does not establish a speedup or a Jev benefit."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="metadata-only diagnostic results JSON")
    args = parser.parse_args()
    try:
        summary = summarize_results(report.read_json(args.results))
    except (OSError, TypeError, ValueError) as error:
        parser.exit(2, f"Invalid diagnostic input: {error}\n")
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
