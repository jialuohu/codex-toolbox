"""Read-only replay of the frozen 72-trial diagnostic with corrected UI scoring.

Only metadata and hashes are written. The original v1 result and sidecars are
never changed, and the current skill source is intentionally not consulted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from . import report
from .runner import TrialObserver

HISTORICAL_SHA256 = {
    "results": "964922185da9570e74017931f6e2faea8fe534365e65bfcc5cfe2f67c2af09cd",
    "pins": "098ffcb78d37f8cbb20507a8a9bfab412a57e04664b2df2e96c1583e0bba1c0c",
    "metrics": "eb20d271b277abbda2de8bfe9da9640c9d4e974bf3db1ad91fe291b9a173e1b1",
}
ROLLOUT_ID = re.compile(r"([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})\.jsonl$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sessions_by_hash(sessions_day: Path, required: set[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sessions_day.glob("rollout-*.jsonl"):
        match = ROLLOUT_ID.search(path.name)
        if match is None:
            continue
        identity_hash = hashlib.sha256(match.group(1).encode()).hexdigest()
        if identity_hash in required:
            if identity_hash in found or path.is_symlink():
                raise ValueError("historical rollout identity is ambiguous")
            found[identity_hash] = path
    if set(found) != required:
        raise ValueError("historical rollout identity is missing")
    return found


def _audit_trial(metric: dict[str, Any], rollout: Path) -> dict[str, Any]:
    """Replay CUA receipts using original attributed monotonic call boundaries."""
    observer = TrialObserver(metric["case_id"])
    cua_calls = [call for call in metric["tool_calls"] if call["kind"] == "cua"]
    cua_ordinal = 0
    session_id = ROLLOUT_ID.search(rollout.name)
    if session_id is None:
        raise ValueError("historical rollout name is invalid")
    expected_thread = hashlib.sha256(session_id.group(1).encode()).hexdigest()
    if expected_thread != metric["thread_id_sha256"]:
        raise ValueError("historical rollout does not match trial identity")
    seen_session = False
    task_complete_indices: list[int] = []
    task_complete_turn_hashes: list[str | None] = []
    pass_event_index = None
    verified_event_index = None
    wrong_at_verification = None
    with rollout.open("rb") as source:
        for event_index, raw in enumerate(source):
            entry = json.loads(raw)
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            if entry.get("type") == "session_meta":
                if seen_session or payload.get("id") != session_id.group(1):
                    raise ValueError("historical rollout session metadata is invalid")
                seen_session = True
            if entry.get("type") != "event_msg":
                continue
            if payload.get("type") == "task_complete":
                task_complete_indices.append(event_index)
                turn_id = payload.get("turn_id")
                task_complete_turn_hashes.append(
                    hashlib.sha256(turn_id.encode()).hexdigest()
                    if isinstance(turn_id, str) else None)
                continue
            if payload.get("type") != "item_completed":
                continue
            item = payload.get("item")
            if (not isinstance(item, dict) or item.get("type") != "McpToolCall"
                    or item.get("server") != "cua_repl" or item.get("tool") != "js"):
                continue
            if cua_ordinal >= len(cua_calls):
                raise ValueError("rollout has an unattributed CUA completion")
            call = cua_calls[cua_ordinal]
            cua_ordinal += 1
            receipt_ms = call["end_ms"]
            observer.on_event({"type": "item.completed", "item": {
                **item, "type": "mcp_tool_call",
            }}, receipt_ms)
            if observer.pass_observed_ms == receipt_ms:
                pass_event_index = event_index
            if observer.marker_verified and observer.verified_ms == receipt_ms:
                verified_event_index = event_index
                wrong_at_verification = observer.wrong_actions
    if not seen_session or cua_ordinal != len(cua_calls) or len(task_complete_indices) > 1:
        raise ValueError("historical rollout evidence is incomplete or duplicated")
    supplied_completion = (metric.get("codex_usage") or {}).get("task_complete")
    if supplied_completion is not None and (
            len(task_complete_indices) != 1
            or supplied_completion.get("event_index") != task_complete_indices[0]
            or supplied_completion.get("turn_sha256") != task_complete_turn_hashes[0]):
        raise ValueError("historical agent completion is not attributable")
    if observer.reset_verified != metric["reset_verified"]:
        raise ValueError("historical reset disagrees with original metadata")
    if (observer.pass_observed_ms is not None
            and not metric["start_ms"] < observer.pass_observed_ms <= metric["end_ms"]):
        raise ValueError("historical PASS receipt is outside the recorded trial span")
    if (observer.verified_ms is not None
            and not metric["start_ms"] < observer.verified_ms <= metric["end_ms"]):
        raise ValueError("historical verification is outside the recorded trial span")
    finalized_after_ui = bool(task_complete_indices and verified_event_index is not None
                              and task_complete_indices[0] > verified_event_index)
    original_status = metric["status"]
    if original_status == "success" and (not observer.marker_verified or not finalized_after_ui):
        raise ValueError("previously successful trial lacks matching UI or terminal evidence")
    corrected_status = original_status
    if (original_status == "failure" and observer.marker_verified
            and finalized_after_ui and metric["returncode"] == 0):
        corrected_status = "success"
    return {
        "sequence": metric["sequence"], "case_id": metric["case_id"],
        "surface": metric["surface"], "condition": metric["condition"],
        "repetition": metric["repetition"],
        "session_sha256": metric["thread_id_sha256"],
        "rollout_sha256": _sha256(rollout),
        "original_status": original_status, "corrected_status": corrected_status,
        "reset_verified": observer.reset_verified,
        "ui_pass_observed": observer.pass_observed_ms is not None,
        "ui_pass_event_index": pass_event_index,
        "ui_pass_elapsed_ms": (observer.pass_observed_ms - metric["start_ms"]
                               if observer.pass_observed_ms is not None else None),
        "ui_verified": observer.marker_verified,
        "ui_verified_event_index": verified_event_index,
        "ui_verified_elapsed_ms": (observer.verified_ms - metric["start_ms"]
                                   if observer.verified_ms is not None else None),
        "wrong_actions_at_verification": wrong_at_verification,
        "controller_returncode": metric["returncode"],
        "controller_timed_out": original_status == "timeout",
        "controller_end_elapsed_ms": metric["end_ms"] - metric["start_ms"],
        "agent_finalized": len(task_complete_indices) == 1,
        "agent_finalized_after_ui": finalized_after_ui,
    }


def build_correction(results_path: Path, sessions_day: Path,
                     *, expected_hashes: dict[str, str] = HISTORICAL_SHA256,
                     expected_runs: int = 72) -> dict[str, Any]:
    """Validate immutable v1 inputs and return a metadata-only correction."""
    paths = {
        "results": results_path,
        "pins": results_path.with_name(results_path.name + ".pins.json"),
        "metrics": results_path.with_name(results_path.name + ".metrics.json"),
    }
    hashes = {name: _sha256(path) for name, path in paths.items()}
    if hashes != expected_hashes:
        raise ValueError("historical input hashes changed")
    results = report.read_json(paths["results"])
    pins = report.read_json(paths["pins"])
    metrics = report.read_json(paths["metrics"])
    rows = metrics.get("records")
    recorded = results.get("records")
    if (not isinstance(rows, list) or not isinstance(recorded, list)
            or len(rows) != expected_runs or len(recorded) != expected_runs
            or results.get("schema_version") != 1 or metrics.get("schema_version") != 1
            or pins.get("schedule_sha256") != results.get("schedule_sha256")
            or metrics.get("schedule_sha256") != results.get("schedule_sha256")):
        raise ValueError("historical input protocol is invalid")
    report.score_results(results)
    required = {row["thread_id_sha256"] for row in rows}
    if len(required) != expected_runs or None in required:
        raise ValueError("historical trial identities are missing or repeated")
    rollouts = _sessions_by_hash(sessions_day, required)
    audited = []
    for index, (record, metric) in enumerate(zip(recorded, rows), 1):
        if (metric["sequence"] != index or record["sequence"] != index
                or any(record[key] != metric[key] for key in
                       ("case_id", "condition", "repetition"))
                or record["outcome"]["status"] != metric["status"]):
            raise ValueError("historical result and timing sidecar disagree")
        audited.append(_audit_trial(metric, rollouts[metric["thread_id_sha256"]]))
    original = Counter(row["original_status"] for row in audited)
    corrected = Counter(row["corrected_status"] for row in audited)
    changed = [row["sequence"] for row in audited
               if row["corrected_status"] != row["original_status"]]
    pass_timeouts = [row["sequence"] for row in audited
                     if row["original_status"] == "timeout" and row["ui_pass_observed"]]
    return {
        "schema_version": 2,
        "kind": "historical_computer_use_scoring_correction",
        "input_sha256": hashes,
        "source_schedule_sha256": results["schedule_sha256"],
        "summary": {
            "runs": expected_runs,
            "original_statuses": dict(sorted(original.items())),
            "corrected_statuses": dict(sorted(corrected.items())),
            "corrected_false_failure_sequences": changed,
            "timeouts_with_observed_pass_sequences": pass_timeouts,
            "timeouts_with_verified_ui": sum(row["original_status"] == "timeout"
                                             and row["ui_verified"] for row in audited),
            "timeouts_with_marker_only": sum(row["original_status"] == "timeout"
                                             and row["ui_pass_observed"]
                                             and not row["ui_verified"] for row in audited),
            "screening": "incomplete",
        },
        "records": audited,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--sessions-day", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output in {args.results, args.results.with_name(args.results.name + ".pins.json"),
                       args.results.with_name(args.results.name + ".metrics.json")}:
        raise ValueError("correction output must not replace historical inputs")
    result = build_correction(args.results, args.sessions_day)
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())
    print(json.dumps({"output_sha256": _sha256(args.output), **result["summary"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
