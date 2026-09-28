"""Metadata-only, descriptive summary for controller canaries and comparisons."""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import fields
from pathlib import Path
from typing import Any

from . import campaign_v2, report, runner


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _counters(attempt: runner.TrialAttempt) -> dict[str, int] | None:
    usage = attempt.codex_usage
    if not isinstance(usage, dict) or usage.get("source") != "codex_turn_token_usage_record":
        return None
    try:
        counters = report._token_usage(usage.get("turn_token_usage"))
    except (ValueError, report.Incomplete):
        return None
    return counters if attempt.usage_isolated else None


def _elapsed(attempt: runner.TrialAttempt) -> float:
    if attempt.status == "success" and attempt.ui_verified_ms is not None:
        return min(float(report.TIMEOUT_MS), attempt.ui_verified_ms - attempt.start_ms)
    return float(report.TIMEOUT_MS)


def summarize(document: object) -> dict[str, Any]:
    if (not isinstance(document, dict) or set(document) != {"schema_version", "protocol", "slots"}
            or document["schema_version"] != campaign_v2.SCHEMA_VERSION
            or not isinstance(document["protocol"], dict)
            or document["protocol"].get("mode") not in {"canary", "comparison"}
            or not isinstance(document["slots"], list)):
        raise ValueError("invalid v2 result document")
    mode = document["protocol"]["mode"]
    scheduled = campaign_v2.schedule(mode)
    if (document["protocol"].get("schedule_sha256") != campaign_v2._hash(
            json.dumps(scheduled, sort_keys=True, separators=(",", ":")).encode())
            or len(document["slots"]) > len(scheduled)):
        raise ValueError("v2 schedule changed or exceeded its length")
    rows: list[dict[str, Any]] = []
    metadata_fields = {item.name for item in fields(runner.TrialAttempt)}
    for index, row in enumerate(document["slots"]):
        if (not isinstance(row, dict) or set(row) != {
                "slot", "attempt", "cleanup", "quiescent", "verification"}
                or row["slot"] != scheduled[index]
                or not isinstance(row["attempt"], dict)
                or set(row["attempt"]) != metadata_fields
                or not isinstance(row["cleanup"], dict)
                or not isinstance(row["verification"], dict)
                or set(row["verification"]) != {"fresh_full_ax_receipt_ms"}
                or type(row["quiescent"]) is not bool):
            raise ValueError("invalid or nonsequential v2 trial")
        attempt = runner.TrialAttempt(**row["attempt"])
        slot = row["slot"]
        if (attempt.sequence != slot["sequence"] or attempt.case_id != slot["case_id"]
                or attempt.condition != slot["condition"] or attempt.surface != slot["surface"]
                or attempt.repetition != slot["repetition"] or attempt.order != slot["order"]
                or attempt.status not in {"success", "failure", "timeout"}
                or attempt.end_ms <= attempt.start_ms):
            raise ValueError("v2 trial metadata disagrees with its slot")
        counters = _counters(attempt)
        token_total = counters["total_tokens"] if counters is not None else None
        jev_calls = sum(call["kind"] == "jev" for call in attempt.tool_calls)
        tool_ms = sum(call["end_ms"] - call["start_ms"] for call in attempt.tool_calls)
        rows.append({"case_id": attempt.case_id, "surface": attempt.surface,
                     "repetition": attempt.repetition, "condition": attempt.condition,
                     "status": attempt.status,
                     "wrong_actions": attempt.wrong_actions,
                     "cap_penalized_ms": _elapsed(attempt),
                     "ui_completion_ms": (attempt.ui_verified_ms - attempt.start_ms
                                          if attempt.ui_verified_ms is not None else None),
                     "independent_full_ax_verified": (
                         row["verification"]["fresh_full_ax_receipt_ms"] == attempt.ui_verified_ms
                         and attempt.ui_verified_ms is not None),
                     "controller_termination_ms": (attempt.controller_terminated_ms - attempt.start_ms
                                                   if attempt.controller_terminated_ms is not None else None),
                     "agent_finalization_ms": (attempt.agent_finalized_ms - attempt.start_ms
                                               if attempt.agent_finalized_ms is not None else None),
                     "tool_duration_ms": tool_ms, "tool_calls": len(attempt.tool_calls),
                     "code_bytes": sum(call["code_bytes"] for call in attempt.tool_calls),
                     "output_bytes": sum(call["output_bytes"] for call in attempt.tool_calls),
                     "observed_evidence_lower_bounds": attempt.observed_evidence,
                     "observed_action_errors": attempt.observed_action_errors,
                     "observed_verification_failures": attempt.observed_verification_failures,
                     "codex_counters": counters,
                     "codex_total_tokens": token_total,
                     "jev_status": attempt.jev_result_status, "jev_calls": jev_calls,
                     "jev_input_tokens": attempt.jev_input_tokens,
                     "jev_output_tokens": attempt.jev_output_tokens,
                     "cleanup_phase": row["cleanup"].get("close_phase"),
                     "post_trial_cleanup_ms": row["cleanup"].get("recovery_elapsed_ms"),
                     "post_trial_cleanup_verified": row["cleanup"].get("recovery_verified"),
                     "cleanup_verified": (row["cleanup"].get("close_verified") is True
                                          if attempt.surface == "browser" else True),
                     "quiescent": row["quiescent"]})
    by_surface_condition = []
    for surface in ("browser", "native"):
        for condition in report.CONDITIONS:
            group = [row for row in rows if row["surface"] == surface
                     and row["condition"] == condition]
            token_values = [float(row["codex_total_tokens"]) for row in group
                            if row["codex_total_tokens"] is not None]
            by_surface_condition.append({
                "surface": surface, "condition": condition, "trials": len(group),
                "successes": sum(row["status"] == "success" for row in group),
                "failures": sum(row["status"] == "failure" for row in group),
                "timeouts": sum(row["status"] == "timeout" for row in group),
                "cap_penalized_median_ms": _median([row["cap_penalized_ms"] for row in group]),
                "codex_total_tokens_median": (_median(token_values)
                                              if len(token_values) == len(group) else None),
                "missing_codex_counters": len(group) - len(token_values),
                "jev_evaluated": sum(row["jev_status"] == "evaluated" for row in group),
            })
    lookup = {(row["case_id"], row["repetition"], row["condition"]): row for row in rows}
    pairs = []
    for case_id in report.CASE_SURFACE:
        for repetition in report.REPETITIONS:
            for old, new in (("B_old", "B_new"), ("C_old", "C_new")):
                before = lookup.get((case_id, repetition, old))
                after = lookup.get((case_id, repetition, new))
                if before is None or after is None:
                    continue
                old_tokens, new_tokens = before["codex_total_tokens"], after["codex_total_tokens"]
                pairs.append({"case_id": case_id, "surface": report.CASE_SURFACE[case_id],
                              "repetition": repetition, "old": old, "new": new,
                              "old_status": before["status"], "new_status": after["status"],
                              "cap_penalized_delta_ms": (after["cap_penalized_ms"]
                                                        - before["cap_penalized_ms"]),
                              "codex_total_tokens_delta": (new_tokens - old_tokens
                                                           if old_tokens is not None
                                                           and new_tokens is not None else None)})
    missing = []
    if mode != "comparison" or len(rows) != 72:
        missing.append("fewer_than_72_comparison_trials")
    if any(row["surface"] == "native" for row in rows):
        missing.append("native_backend_session_id_unavailable")
    missing.append("exact_operation_and_unsafe_action_counts_unavailable")
    if any(row["codex_total_tokens"] is None for row in rows):
        missing.append("six_codex_token_counters_missing")
    if any(not row["cleanup_verified"] or not row["quiescent"] for row in rows):
        missing.append("quiescence_or_cleanup_unverified")
    return {"schema_version": 2, "mode": mode, "trials": len(rows),
            "screening": "incomplete", "incomplete_reasons": sorted(set(missing)),
            "by_surface_condition": by_surface_condition, "pairs": pairs, "trials_metadata": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(report.read_json(args.results)), sort_keys=True,
                     separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
