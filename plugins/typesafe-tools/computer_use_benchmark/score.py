"""Score imported computer-use runs. This module never starts Codex or Jev."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONDITIONS = ("A", "B", "C")
SURFACES = ("browser", "native")
REPETITIONS = 3
TUNING_PER_SURFACE = 10
HELDOUT_PER_SURFACE = 30
MIN_ELIGIBLE_JEV_COVERAGE = 0.90
BOOTSTRAP_SAMPLES = 4096
FAMILYWISE_ALPHA = 0.05
COMPARISONS_PER_SURFACE = 4  # latency and tokens, C against A and B
EVENT_HASH = re.compile(r"[0-9a-f]{64}\Z")
RECORD_FIELDS = {
    "case_id", "repetition", "condition", "order", "elapsed_ms", "success",
    "wrong_actions", "unsafe_actions", "tool_calls", "reset_verified",
    "observation_complete", "marker_seen", "usage_isolated", "timing_complete",
    "codex_usage", "jev_usage", "jev_decision",
}
TOKEN_FIELDS = {"input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                "output_tokens", "reasoning_output_tokens", "total_tokens"}
EVENT_FIELDS = {"event_sha256", *TOKEN_FIELDS}
SNAPSHOT_FIELDS = {"event_index", "event_sha256", "total_token_usage"}
JEV_FIELDS = {"calls", "input_tokens", "output_tokens", "elapsed_ms"}
JEV_DECISION_FIELDS = {"status", "skip_reason"}
JEV_SKIP_REASONS = {"no_meaningful_choice", "insufficient_observation", "service_unavailable"}


class IncompleteData(Exception):
    """Expected evidence is unavailable; the surface stays ineligible."""


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(path.read_text(encoding="utf-8"),
                      object_pairs_hook=_no_duplicates, parse_constant=reject_constant)


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _positive_number(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return float(value)


def _token_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise IncompleteData("missing Codex runtime token counters")
    if set(value) - TOKEN_FIELDS:
        raise ValueError("unexpected Codex runtime token counter")
    if set(value) != TOKEN_FIELDS:
        raise IncompleteData("missing Codex runtime token counters")
    usage = {field: _nonnegative_int(value[field], field) for field in TOKEN_FIELDS}
    if (usage["cached_input_tokens"] > usage["input_tokens"]
            or usage["reasoning_output_tokens"] > usage["output_tokens"]
            or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]):
        raise ValueError("inconsistent Codex runtime token counters")
    return usage


def load_fixtures(root: Path = ROOT) -> tuple[dict, str, list[dict]]:
    """Expand the frozen, original synthetic fixtures into 80 cases."""
    frozen = _read_json(root / "freeze.json")
    raw = (root / "fixtures.json").read_bytes()
    fixture_hash = hashlib.sha256(raw).hexdigest()
    if frozen != {"fixtures.json": fixture_hash}:
        raise ValueError("frozen fixture digest mismatch")
    manifest = _read_json(root / "fixtures.json")
    if (set(manifest) != {"schema_version", "license", "origin", "repetitions",
                          "conditions", "variants", "families"} or manifest["schema_version"] != 1
            or manifest["license"] != "CC0-1.0" or manifest["repetitions"] != REPETITIONS
            or set(manifest["conditions"]) != set(CONDITIONS)):
        raise ValueError("invalid fixture protocol")
    if (not isinstance(manifest["origin"], str) or not manifest["origin"].strip()
            or not all(isinstance(value, str) and value.strip()
                       for value in manifest["conditions"].values())):
        raise ValueError("missing fixture origin or condition definitions")
    families = manifest["families"]
    if not isinstance(families, list) or len(families) != 20:
        raise ValueError("expected ten scenario families per surface")
    variants = manifest["variants"]
    variant_fields = {"target", "section", "status", "tab", "group", "decoy"}
    if (not isinstance(variants, list) or len(variants) != 4
            or any(not isinstance(variant, dict) or set(variant) != variant_fields
                   or any(not isinstance(value, str) or not value.strip()
                          for value in variant.values())
                   or variant["target"] == variant["decoy"] for variant in variants)):
        raise ValueError("expected four complete synthetic UI variants")
    cases = []
    seen_family = set()
    seen_objective = set()
    for family in families:
        if set(family) != {"surface", "category", "objective", "observation",
                           "actions", "expected_action_id", "expected_result",
                           "jev_eligible", "decision_stage"}:
            raise ValueError("invalid scenario family fields")
        surface, category = family["surface"], family["category"]
        if (surface not in SURFACES or not isinstance(category, str) or not category
                or (surface, category) in seen_family):
            raise ValueError("duplicate or invalid surface/category")
        seen_family.add((surface, category))
        if type(family["jev_eligible"]) is not bool:
            raise ValueError("Jev eligibility must be predeclared")
        stage = family["decision_stage"]
        if (stage not in {"none", "initial", "status_options_open", "picker_open"}
                or (stage == "none") == family["jev_eligible"]):
            raise ValueError("invalid predeclared Jev decision stage")
        actions = family["actions"]
        if (not isinstance(actions, list)
                or (stage == "none" and (actions or family["expected_action_id"] is not None))
                or (stage != "none" and (len(actions) < 2
                                         or not isinstance(family["expected_action_id"], str)))
                or any(not isinstance(action, dict)
                       or set(action) != {"id", "description"}
                       or not isinstance(action["id"], str)
                       or not isinstance(action["description"], str)
                       for action in actions)):
            raise ValueError("invalid candidate actions")
        action_ids = [action["id"] for action in actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("duplicate candidate ID")
        for template_key in ("objective", "observation", "expected_result"):
            template = family[template_key]
            if not isinstance(template, str) or not template.strip():
                raise ValueError("scenario templates must be nonempty")
        for index, variant in enumerate(variants):
            case_id = f"{surface}-{category}-{index}"
            values = {**variant, "case_id": case_id}
            try:
                objective = family["objective"].format_map(values)
                observation = family["observation"].format_map(values)
                expanded_actions = [{"id": action["id"], "description": action["description"].format_map(values)}
                                    for action in actions]
                expected_action_id = (family["expected_action_id"].format_map(values)
                                      if stage != "none" else None)
                expected_result = family["expected_result"].format_map(values)
            except (KeyError, ValueError) as error:
                raise ValueError("invalid scenario template") from error
            if objective in seen_objective:
                raise ValueError("duplicate scenario objective")
            if stage != "none" and expected_action_id not in action_ids:
                raise ValueError("expected action absent from candidates")
            seen_objective.add(objective)
            cases.append({
                "case_id": case_id,
                "surface": surface,
                "split": "tuning" if index == 0 else "heldout",
                "category": category,
                "objective": objective,
                "observation": observation,
                "actions": expanded_actions,
                "expected_action_id": expected_action_id,
                "expected_result": expected_result,
                "jev_eligible": family["jev_eligible"],
                "decision_stage": stage,
            })
    for surface in SURFACES:
        if (len([case for case in cases if case["surface"] == surface
                 and case["split"] == "tuning"]) != TUNING_PER_SURFACE
                or len([case for case in cases if case["surface"] == surface
                        and case["split"] == "heldout"]) != HELDOUT_PER_SURFACE):
            raise ValueError("expected 10 tuning and 30 held-out cases per surface")
    return manifest, fixture_hash, cases


def _codex_measurement(codex: object, event_hashes: set[str], intervals: dict[str, list[tuple[int, int]]]) -> tuple[dict | None, str | None]:
    """Read actual token_count cumulative snapshots or disjoint event deltas."""
    if not isinstance(codex, dict):
        return None, "missing Codex usage"
    source = codex.get("source")
    if source == "codex_rollout_token_count":
        if set(codex) - {"source", "session_sha256", "start", "end"}:
            raise ValueError("unexpected Codex usage field; raw payloads are forbidden")
        if set(codex) != {"source", "session_sha256", "start", "end"}:
            return None, "incomplete Codex token_count snapshots"
        session = codex["session_sha256"]
        if not isinstance(session, str) or not EVENT_HASH.fullmatch(session):
            raise ValueError("Codex session reference must be an opaque SHA-256 identifier")
        snapshots = []
        for name in ("start", "end"):
            snapshot = codex[name]
            if not isinstance(snapshot, dict) or set(snapshot) - SNAPSHOT_FIELDS:
                raise ValueError("unexpected Codex snapshot field; raw payloads are forbidden")
            if set(snapshot) != SNAPSHOT_FIELDS:
                return None, "incomplete Codex token_count snapshot"
            if (type(snapshot["event_index"]) is not int or snapshot["event_index"] < 0
                    or not isinstance(snapshot["event_sha256"], str)
                    or not EVENT_HASH.fullmatch(snapshot["event_sha256"])):
                raise ValueError("invalid Codex token_count snapshot provenance")
            usage = _token_usage(snapshot["total_token_usage"])
            snapshots.append((snapshot["event_index"], snapshot["event_sha256"], usage))
        (start_index, start_hash, start), (end_index, end_hash, end) = snapshots
        if end_index <= start_index or end_hash == start_hash:
            raise ValueError("Codex token_count snapshots are not ordered")
        for prior_start, prior_end in intervals.get(session, []):
            if start_index < prior_end and end_index > prior_start:
                raise ValueError("Codex token_count intervals overlap across runs")
        delta = {field: end[field] - start[field] for field in TOKEN_FIELDS}
        if any(value < 0 for value in delta.values()):
            raise ValueError("Codex cumulative token counters decreased")
        _token_usage(delta)
        intervals.setdefault(session, []).append((start_index, end_index))
        return delta, None
    if source == "codex_runtime_usage_event_delta":
        if set(codex) - {"source", "events"}:
            raise ValueError("unexpected Codex usage field; raw payloads are forbidden")
        if set(codex) != {"source", "events"} or not isinstance(codex["events"], list) or not codex["events"]:
            return None, "missing Codex usage events"
        total = {field: 0 for field in TOKEN_FIELDS}
        local_hashes = set()
        for event in codex["events"]:
            if not isinstance(event, dict) or set(event) - EVENT_FIELDS:
                raise ValueError("unexpected Codex event field; raw payloads are forbidden")
            if set(event) != EVENT_FIELDS:
                return None, "incomplete Codex usage event"
            event_hash = event["event_sha256"]
            if not isinstance(event_hash, str) or not EVENT_HASH.fullmatch(event_hash):
                raise ValueError("Codex usage event must have an opaque SHA-256 identifier")
            if event_hash in event_hashes or event_hash in local_hashes:
                raise ValueError("Codex usage event reused across runs")
            local_hashes.add(event_hash)
            measured = _token_usage({field: event[field] for field in TOKEN_FIELDS})
            for field in TOKEN_FIELDS:
                total[field] += measured[field]
        event_hashes.update(local_hashes)
        return total, None
    if set(codex) - {"source", "events", "session_sha256", "start", "end"}:
        raise ValueError("unexpected Codex usage field; raw payloads are forbidden")
    return None, "missing attributable Codex runtime usage source"


def _validate_record(row: dict, event_hashes: set[str], intervals: dict[str, list[tuple[int, int]]]) -> tuple[dict | None, str | None]:
    """Return normalized measurements or an incomplete-data reason."""
    if not isinstance(row, dict) or set(row) - RECORD_FIELDS:
        raise ValueError("unexpected run field; UI payloads are forbidden")
    missing = RECORD_FIELDS - set(row)
    if missing:
        return None, "missing fields: " + ",".join(sorted(missing))
    if row["repetition"] not in (1, 2, 3) or row["condition"] not in CONDITIONS:
        raise ValueError("invalid run repetition or condition")
    if row["order"] not in (1, 2, 3):
        raise ValueError("invalid randomized execution order")
    elapsed = _positive_number(row["elapsed_ms"], "elapsed_ms")
    if type(row["success"]) is not bool:
        raise ValueError("success must be boolean")
    for field in ("wrong_actions", "unsafe_actions", "tool_calls"):
        _nonnegative_int(row[field], field)
    if type(row["marker_seen"]) is not bool or row["marker_seen"] != row["success"]:
        raise ValueError("success must match the visible PASS marker")
    if (row["reset_verified"] is not True or row["observation_complete"] is not True
            or row["usage_isolated"] is not True or row["timing_complete"] is not True):
        return None, "fixture reset, observation, usage isolation, or timing incomplete"
    measured, reason = _codex_measurement(row["codex_usage"], event_hashes, intervals)
    if reason:
        return None, reason
    if measured["total_tokens"] == 0:
        return None, "zero measured Codex tokens"
    jev = row["jev_usage"]
    if not isinstance(jev, dict) or set(jev) - JEV_FIELDS:
        raise ValueError("unexpected Jev usage field; raw payloads are forbidden")
    if set(jev) != JEV_FIELDS:
        return None, "incomplete Jev usage"
    for field in JEV_FIELDS:
        _nonnegative_int(jev[field], "jev_" + field)
    if jev["elapsed_ms"] > elapsed:
        raise ValueError("Jev elapsed time exceeds end-to-end elapsed time")
    if row["condition"] in ("A", "B") and any(jev.values()):
        raise ValueError("A and B must contain zero Jev usage")
    if jev["calls"] == 0 and any(jev[key] for key in ("input_tokens", "output_tokens", "elapsed_ms")):
        raise ValueError("Jev usage recorded without calls")
    if jev["calls"] and (jev["input_tokens"] + jev["output_tokens"] == 0
                         or jev["elapsed_ms"] == 0):
        return None, "Jev call lacks provider usage or elapsed time"
    decision = row["jev_decision"]
    if not isinstance(decision, dict) or set(decision) - JEV_DECISION_FIELDS:
        raise ValueError("unexpected Jev decision field; payloads are forbidden")
    if set(decision) != JEV_DECISION_FIELDS:
        return None, "incomplete Jev decision accounting"
    status, skip_reason = decision["status"], decision["skip_reason"]
    if not isinstance(skip_reason, str):
        raise TypeError("Jev skip reason must be a fixed label")
    if row["condition"] in ("A", "B"):
        if status != "not_applicable" or skip_reason:
            raise ValueError("A and B cannot report Jev decisions")
    elif status in ("evaluated", "abstained"):
        if jev["calls"] == 0 or skip_reason:
            raise ValueError("evaluated Jev decision requires measured calls")
    elif status == "skipped":
        if jev["calls"] != 0 or skip_reason not in JEV_SKIP_REASONS | {"ineligible_fixture"}:
            raise ValueError("skipped Jev decision needs a valid reason and zero calls")
    else:
        raise ValueError("unknown Jev decision status")
    return {**row, "elapsed_ms": elapsed,
            "codex_input_tokens": measured["input_tokens"],
            "codex_output_tokens": measured["output_tokens"],
            "codex_cached_input_tokens": measured["cached_input_tokens"],
            "codex_cache_write_input_tokens": measured["cache_write_input_tokens"],
            "codex_reasoning_output_tokens": measured["reasoning_output_tokens"],
            "codex_tokens": measured["total_tokens"]}, None


def _percentile(sorted_values: list[float], fraction: float) -> float:
    position = fraction * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _paired_interval(family_differences: list[float], seed: int) -> list[float]:
    """Two-sided Bonferroni-adjusted CI, resampling scenario families."""
    rng = random.Random(seed)
    count = len(family_differences)
    estimates = sorted(sum(family_differences[rng.randrange(count)] for _ in range(count)) / count
                       for _ in range(BOOTSTRAP_SAMPLES))
    tail = FAMILYWISE_ALPHA / (2 * COMPARISONS_PER_SURFACE)
    return [round(_percentile(estimates, tail), 6),
            round(_percentile(estimates, 1 - tail), 6)]


def _condition_metrics(rows: list[dict]) -> dict:
    return {
        "runs": len(rows),
        "mean_elapsed_ms": statistics.mean(row["elapsed_ms"] for row in rows),
        "mean_codex_tokens": statistics.mean(row["codex_tokens"] for row in rows),
        "total_codex_input_tokens": sum(row["codex_input_tokens"] for row in rows),
        "total_codex_output_tokens": sum(row["codex_output_tokens"] for row in rows),
        "total_cached_input_tokens": sum(row["codex_cached_input_tokens"] for row in rows),
        "total_cache_write_input_tokens": sum(row["codex_cache_write_input_tokens"] for row in rows),
        "total_reasoning_output_tokens": sum(row["codex_reasoning_output_tokens"] for row in rows),
        "successes": sum(row["success"] for row in rows),
        "wrong_actions": sum(row["wrong_actions"] for row in rows),
        "unsafe_actions": sum(row["unsafe_actions"] for row in rows),
        "tool_calls": sum(row["tool_calls"] for row in rows),
        "jev_calls": sum(row["jev_usage"]["calls"] for row in rows),
        "jev_input_tokens": sum(row["jev_usage"]["input_tokens"] for row in rows),
        "jev_output_tokens": sum(row["jev_usage"]["output_tokens"] for row in rows),
        "jev_elapsed_ms": sum(row["jev_usage"]["elapsed_ms"] for row in rows),
    }


def condition_order(fixture_hash: str, case_id: str, repetition: int) -> dict[str, int]:
    """Stable randomized order for a paired case repetition."""
    ordered = sorted(CONDITIONS, key=lambda condition: hashlib.sha256(
        f"{fixture_hash}:{case_id}:{repetition}:{condition}".encode()).digest())
    return {condition: index + 1 for index, condition in enumerate(ordered)}


def prepare_schedule(root: Path = ROOT) -> dict:
    """Return only synthetic objectives and the frozen execution order."""
    _, fixture_hash, cases = load_fixtures(root)
    runs = []
    for case in cases:
        if case["split"] != "heldout":
            continue
        for repetition in range(1, REPETITIONS + 1):
            order = condition_order(fixture_hash, case["case_id"], repetition)
            for condition in CONDITIONS:
                runs.append({"case_id": case["case_id"], "surface": case["surface"],
                             "objective": case["objective"], "repetition": repetition,
                             "condition": condition, "order": order[condition]})
    return {"schema_version": 1, "fixture_sha256": fixture_hash,
            "runs": sorted(runs, key=lambda row: (row["surface"], row["case_id"],
                                                  row["repetition"], row["order"]))}


def _score_surface(surface: str, fixture_hash: str, cases: list[dict], records: dict, incomplete: dict) -> dict:
    expected_keys = {(case["case_id"], repetition, condition)
                     for case in cases if case["surface"] == surface and case["split"] == "heldout"
                     for repetition in range(1, REPETITIONS + 1) for condition in CONDITIONS}
    found = expected_keys & (records.keys() | incomplete.keys())
    missing = expected_keys - found
    problems = [f"{len(missing)} missing run records"] if missing else []
    surface_incomplete = {key: reason for key, reason in incomplete.items() if key in expected_keys}
    if surface_incomplete:
        problems.append(f"{len(surface_incomplete)} incomplete run records")
    order_problems = 0
    eligibility_problems = 0
    for case in cases:
        if case["surface"] != surface or case["split"] != "heldout":
            continue
        for repetition in range(1, REPETITIONS + 1):
            triplet = [records.get((case["case_id"], repetition, condition)) for condition in CONDITIONS]
            if all(triplet):
                prescribed = condition_order(fixture_hash, case["case_id"], repetition)
                if any(records[(case["case_id"], repetition, condition)]["order"]
                       != prescribed[condition] for condition in CONDITIONS):
                    order_problems += 1
            assisted = records.get((case["case_id"], repetition, "C"))
            if assisted:
                decision = assisted["jev_decision"]
                if ((not case["jev_eligible"] and
                     (decision != {"status": "skipped", "skip_reason": "ineligible_fixture"}
                      or assisted["jev_usage"]["calls"] != 0))
                    or (case["jev_eligible"] and decision["status"] == "skipped"
                        and decision["skip_reason"] == "ineligible_fixture")):
                    eligibility_problems += 1
    if order_problems:
        problems.append(f"{order_problems} triplets depart from frozen execution order")
    if eligibility_problems:
        problems.append(f"{eligibility_problems} Jev decisions violate predeclared eligibility")
    result = {"activation_ready": False, "complete": not problems,
              "expected_runs": len(expected_keys), "missing_runs": len(missing),
              "incomplete_runs": len(surface_incomplete), "reasons": problems,
              "conditions": None, "comparisons": None}
    if problems:
        return result
    grouped = {condition: [records[key] for key in sorted(expected_keys)
                           if key[2] == condition] for condition in CONDITIONS}
    metrics = {condition: _condition_metrics(grouped[condition]) for condition in CONDITIONS}
    comparisons = {}
    for reference_index, reference in enumerate(("A", "B")):
        comparison = {}
        for metric_index, (name, field) in enumerate((("latency", "elapsed_ms"),
                                                      ("codex_tokens", "codex_tokens"))):
            family_differences = []
            for category in sorted({case["category"] for case in cases
                                    if case["surface"] == surface and case["split"] == "heldout"}):
                differences = [records[(case["case_id"], repetition, reference)][field]
                               - records[(case["case_id"], repetition, "C")][field]
                               for case in cases if case["surface"] == surface
                               and case["split"] == "heldout" and case["category"] == category
                               for repetition in range(1, REPETITIONS + 1)]
                family_differences.append(statistics.mean(differences))
            reference_mean = metrics[reference]["mean_elapsed_ms" if name == "latency" else "mean_codex_tokens"]
            assisted_mean = metrics["C"]["mean_elapsed_ms" if name == "latency" else "mean_codex_tokens"]
            reduction = (reference_mean - assisted_mean) / reference_mean
            interval = _paired_interval(family_differences,
                                        seed=20260923 + SURFACES.index(surface) * 10
                                        + reference_index * 2 + metric_index)
            comparison[name] = {
                "mean_reduction_fraction": round(reduction, 6),
                "paired_difference_ci": interval,
                "passes": reduction >= 0.10 and interval[0] > 0,
            }
        comparisons[f"C_vs_{reference}"] = comparison
    quality_pass = (metrics["C"]["successes"] >= max(metrics["A"]["successes"], metrics["B"]["successes"])
                    and metrics["C"]["wrong_actions"] <= min(metrics["A"]["wrong_actions"],
                                                                metrics["B"]["wrong_actions"])
                    and all(metric["unsafe_actions"] == 0 for metric in metrics.values()))
    eligible_cases = {case["case_id"] for case in cases
                      if case["surface"] == surface and case["split"] == "heldout"
                      and case["jev_eligible"]}
    eligible_runs = [row for row in grouped["C"] if row["case_id"] in eligible_cases]
    evaluated_runs = sum(row["jev_decision"]["status"] in ("evaluated", "abstained")
                         for row in eligible_runs)
    jev_coverage = evaluated_runs / len(eligible_runs) if eligible_runs else 0
    coverage_pass = jev_coverage >= MIN_ELIGIBLE_JEV_COVERAGE
    result.update(conditions=metrics, comparisons=comparisons,
                  quality_pass=quality_pass,
                  jev_coverage={"eligible_runs": len(eligible_runs),
                                "evaluated_or_abstained_runs": evaluated_runs,
                                "fraction": round(jev_coverage, 6),
                                "required_fraction": MIN_ELIGIBLE_JEV_COVERAGE,
                                "passes": coverage_pass},
                  activation_ready=(quality_pass and coverage_pass
                                    and all(measure["passes"] for comparison in comparisons.values()
                                            for measure in comparison.values())))
    if not quality_pass:
        result["reasons"].append("success, wrong-action, or unsafe-action gate failed")
    if not coverage_pass:
        result["reasons"].append("predeclared Jev coverage gate failed")
    if any(not measure["passes"] for comparison in comparisons.values() for measure in comparison.values()):
        result["reasons"].append("latency or Codex token benefit gate failed")
    return result


def score_results(document: dict, root: Path = ROOT) -> dict:
    """Validate metadata-only records and report per-surface eligibility.

    Eligibility is advisory evidence. This function never changes activation
    switches, installs plugins, or makes network calls.
    """
    _, fixture_hash, cases = load_fixtures(root)
    if not isinstance(document, dict) or set(document) != {"schema_version", "fixture_sha256", "records"}:
        raise ValueError("unexpected result document fields")
    if document["schema_version"] != 1 or document["fixture_sha256"] != fixture_hash:
        raise ValueError("result provenance does not match frozen fixtures")
    if not isinstance(document["records"], list):
        raise TypeError("records must be a list")
    heldout = {case["case_id"]: case for case in cases if case["split"] == "heldout"}
    records, incomplete, event_hashes, intervals = {}, {}, set(), {}
    for row in document["records"]:
        if not isinstance(row, dict) or set(row) - RECORD_FIELDS:
            raise ValueError("unexpected run field; UI payloads are forbidden")
        if not {"case_id", "repetition", "condition"} <= set(row):
            raise ValueError("run identity is missing")
        case_id, repetition, condition = row["case_id"], row["repetition"], row["condition"]
        if case_id not in heldout or repetition not in (1, 2, 3) or condition not in CONDITIONS:
            raise ValueError("unknown or tuning case, repetition, or condition")
        key = (case_id, repetition, condition)
        if key in records or key in incomplete:
            raise ValueError("duplicate run record")
        try:
            normalized, reason = _validate_record(row, event_hashes, intervals)
        except IncompleteData as error:
            normalized, reason = None, str(error)
        if reason:
            incomplete[key] = reason
        else:
            records[key] = normalized
    return {
        "schema_version": 1,
        "scorer_version": "1.0",
        "fixture_sha256": fixture_hash,
        "automatic_use_enabled": False,
        "interval": "98.75% two-sided percentile bootstrap, paired by case and clustered by 10 scenario families; four-comparison Bonferroni correction per surface",
        "surfaces": {surface: _score_surface(surface, fixture_hash, cases, records, incomplete)
                     for surface in SURFACES},
        "limitation": "Imported usage-event identifiers and outcome labels are not authenticated runtime attestations.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="?", type=Path,
                        help="metadata-only imported results JSON")
    parser.add_argument("--schedule", action="store_true",
                        help="print the frozen held-out A/B/C run order")
    args = parser.parse_args()
    if args.schedule and args.results is not None or not args.schedule and args.results is None:
        parser.error("provide either a results path or --schedule")
    try:
        report = prepare_schedule() if args.schedule else score_results(_read_json(args.results))
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"Invalid benchmark input: {error}\n")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
