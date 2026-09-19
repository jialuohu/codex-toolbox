#!/usr/bin/env python3
"""Offline fixture validation and paired scoring. Never calls a model or API."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
FROZEN = ("cases.json", "tuning.json", "protocol.json")
LABELS = {"supported", "contradicted", "insufficient"}
COST_FIELDS = {"cost_usd", "jev_cost_usd"}


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path):
    def invalid_constant(_):
        raise ValueError("non-finite JSON number")
    return json.loads(Path(path).read_text(), object_pairs_hook=reject_duplicates,
                      parse_constant=invalid_constant)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(root=ROOT):
    frozen = read_json(root / "freeze.json")
    if set(frozen) != set(FROZEN):
        raise ValueError("unexpected frozen file set")
    for name in FROZEN:
        if digest(root / name) != frozen[name]:
            raise ValueError("frozen fixture or protocol changed")
    cases = read_json(root / "cases.json")
    tuning = read_json(root / "tuning.json")
    if cases.get("split") != "held_out" or tuning.get("split") != "tuning":
        raise ValueError("invalid split")
    seen = set()
    for case in cases["cases"] + tuning["cases"]:
        if case["id"] in seen:
            raise ValueError("duplicate case across splits")
        seen.add(case["id"])
        ids = [p["id"] for p in case["passages"]]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("invalid passage IDs")
        if not isinstance(case["question"], str) or not case["question"].strip():
            raise ValueError("missing question")
        for passage in case["passages"]:
            if not passage["text"] or passage["provenance"] != {
                "kind": "synthetic", "author": "codex-toolbox", "license": "CC0-1.0"
            }:
                raise ValueError("invalid synthetic provenance")
        if case["task"] == "ranking":
            if sorted(case["gold"]) != sorted(ids):
                raise ValueError("gold ranking must preserve all candidates")
        elif case["task"] == "claim":
            if case["gold"] not in LABELS:
                raise ValueError("invalid claim label")
        else:
            raise ValueError("unknown task")
    for task in ("ranking", "claim"):
        selected = [c for c in cases["cases"] if c["task"] == task]
        if len(selected) != 30 or {c["category"] for c in selected} != {
            "direct", "insufficient", "contradictory", "injected", "numeric", "date"
        }:
            raise ValueError("expected 30 cases per task covering six categories")
    return cases["cases"], frozen


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid " + name)
    if value < 0 or (positive and value == 0):
        raise ValueError("invalid " + name)
    return value


def total(values):
    """Unknown monetary components make the total unknown, never zero."""
    values = list(values)
    return None if any(value is None for value in values) else sum(values)


def cost_metrics(rows):
    return {
        "cost_usd": total(row["usage"]["cost_usd"] for row in rows),
        "jev_cost_usd": total(row["usage"]["jev_cost_usd"] for row in rows),
        "unknown_cost_records": sum(row["usage"]["cost_usd"] is None for row in rows),
        "unknown_jev_cost_records": sum(row["usage"]["jev_cost_usd"] is None for row in rows),
    }


def score(result_path, root=ROOT):
    cases, frozen = validate(root)
    document = read_json(result_path)
    if set(document) != {"version", "frozen_sha256", "run_notes", "records"}:
        raise ValueError("unexpected result document fields")
    if document["version"] != 1 or document["frozen_sha256"] != frozen:
        raise ValueError("results do not match frozen evaluation")
    if not isinstance(document["run_notes"], str) or not document["run_notes"].strip():
        raise ValueError("document condition order, model versions and interruptions")
    indexed = {case["id"]: case for case in cases}
    seen, scored = set(), []
    for row in document["records"]:
        if set(row) != {"case_id", "condition", "model", "prediction", "final_answer",
                        "elapsed_seconds", "jev_elapsed_seconds", "usage", "adjudication"}:
            raise ValueError("unexpected result fields")
        key = (row["case_id"], row["condition"])
        if row["case_id"] not in indexed or row["condition"] not in {"baseline", "jev"} or key in seen:
            raise ValueError("invalid or duplicate case/condition")
        seen.add(key)
        case = indexed[row["case_id"]]
        prediction = row["prediction"]
        if case["task"] == "ranking":
            if (not isinstance(prediction, list) or
                    any(not isinstance(p, str) for p in prediction) or
                    sorted(prediction) != sorted(case["gold"])):
                raise ValueError("ranking must preserve every candidate exactly once")
        elif not isinstance(prediction, str) or prediction not in LABELS:
            raise ValueError("invalid claim prediction")
        for name in ("model", "final_answer"):
            if not isinstance(row[name], str) or not row[name].strip():
                raise ValueError("missing " + name)
        number(row["elapsed_seconds"], "elapsed_seconds", positive=True)
        number(row["jev_elapsed_seconds"], "jev_elapsed_seconds")
        if row["jev_elapsed_seconds"] > row["elapsed_seconds"]:
            raise ValueError("Jev latency exceeds end-to-end elapsed time")
        if row["condition"] == "baseline" and row["jev_elapsed_seconds"] != 0:
            raise ValueError("baseline includes Jev latency")
        if row["condition"] == "jev" and row["jev_elapsed_seconds"] == 0:
            raise ValueError("Jev condition requires measured latency")
        usage = row["usage"]
        if set(usage) != {"input_tokens", "output_tokens", "cost_usd", "jev_calls", "jev_cost_usd"}:
            raise ValueError("unexpected usage fields")
        for name in usage:
            if name in COST_FIELDS and usage[name] is None:
                continue
            number(usage[name], name)
            if name in {"input_tokens", "output_tokens", "jev_calls"} and type(usage[name]) is not int:
                raise ValueError("token and call counts must be integers")
        if (usage["jev_cost_usd"] is not None and usage["cost_usd"] is not None
                and usage["jev_cost_usd"] > usage["cost_usd"]):
            raise ValueError("Jev cost exceeds total cost")
        if row["condition"] == "baseline" and (usage["jev_calls"] or usage["jev_cost_usd"]):
            raise ValueError("baseline includes Jev usage")
        if row["condition"] == "jev" and not usage["jev_calls"]:
            raise ValueError("Jev condition requires actual measured Jev calls")
        review = row["adjudication"]
        if set(review) != {"reviewer", "blinded", "final_correct", "unsupported_conclusions", "notes"}:
            raise ValueError("unexpected adjudication fields")
        if not isinstance(review["reviewer"], str) or not review["reviewer"].strip() or review["blinded"] is not True:
            raise ValueError("independent blinded reviewer required")
        if type(review["final_correct"]) is not bool or type(review["unsupported_conclusions"]) is not int or review["unsupported_conclusions"] < 0:
            raise ValueError("invalid adjudication")
        if not isinstance(review["notes"], str) or not review["notes"].strip():
            raise ValueError("adjudication rationale required")
        if review["final_correct"] and review["unsupported_conclusions"]:
            raise ValueError("correct final answer contains unsupported conclusions")
        scored.append({**row, "task": case["task"], "category": case["category"],
                       "prediction_correct": prediction == case["gold"],
                       "top1_correct": prediction[0] == case["gold"][0] if case["task"] == "ranking" else None})
    if seen != {(case["id"], arm) for case in cases for arm in ("baseline", "jev")}:
        raise ValueError("require all 60 held-out cases in both conditions")
    report = {"exploratory": True, "automatic_use_enabled": False,
              "warning": "Synthetic pilot only. Reviewer declarations are not independently verified. Review results before any activation.",
              "conditions": {}, "paired": {}}
    for arm in ("baseline", "jev"):
        rows = [r for r in scored if r["condition"] == arm]
        def metrics(group):
            return {"n": len(group), "prediction_accuracy": statistics.mean(r["prediction_correct"] for r in group),
                    "final_answer_accuracy": statistics.mean(r["adjudication"]["final_correct"] for r in group),
                    "unsupported_conclusions": sum(r["adjudication"]["unsupported_conclusions"] for r in group),
                    "mean_elapsed_seconds": statistics.mean(r["elapsed_seconds"] for r in group),
                    "mean_jev_elapsed_seconds": statistics.mean(r["jev_elapsed_seconds"] for r in group),
                    **cost_metrics(group)}
        report["conditions"][arm] = {**metrics(rows),
            "ranking_top1_accuracy": statistics.mean(r["top1_correct"] for r in rows if r["task"] == "ranking"),
            "by_task": {task: metrics([r for r in rows if r["task"] == task]) for task in ("ranking", "claim")},
            "by_category": {cat: metrics([r for r in rows if r["category"] == cat]) for cat in sorted({r["category"] for r in rows})},
            "usage": {key: total(r["usage"][key] for r in rows) for key in rows[0]["usage"]}}
    pairs = {arm: {r["case_id"]: r for r in scored if r["condition"] == arm} for arm in ("baseline", "jev")}
    for case in cases:
        base, jev = (pairs[arm][case["id"]] for arm in ("baseline", "jev"))
        report["paired"][case["id"]] = {
            "final_correct_change": int(jev["adjudication"]["final_correct"]) - int(base["adjudication"]["final_correct"]),
            "unsupported_change": jev["adjudication"]["unsupported_conclusions"] - base["adjudication"]["unsupported_conclusions"],
            "elapsed_change_seconds": jev["elapsed_seconds"] - base["elapsed_seconds"]}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    scoring = sub.add_parser("score")
    scoring.add_argument("results", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            cases, frozen = validate()
            result = {"valid": True, "held_out_cases": len(cases), "frozen_sha256": frozen}
        else:
            result = score(args.results)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError, AttributeError, IndexError):
        parser.exit(2, "Invalid fixture, protocol, or result input; no evaluation or activation performed.\n")


if __name__ == "__main__":
    main()
