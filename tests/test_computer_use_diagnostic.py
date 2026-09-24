"""Offline tests for the exploratory, metadata-only computer-use diagnostic."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import report as diagnostic


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def tokens(total: int) -> dict:
    return {
        "input_tokens": total - 20, "cached_input_tokens": 10,
        "cache_write_input_tokens": 0, "output_tokens": 20,
        "reasoning_output_tokens": 5, "total_tokens": total,
    }


def protocol() -> dict:
    return {
        "model": "gpt-6", "reasoning": "medium", "timeout_ms": 120000,
        "prompt_sha256": {case_id: digest("prompt:" + case_id)
                          for case_id, _ in diagnostic.CASES},
        "recipe_sha256": {condition: digest("recipe:" + condition)
                          for condition in diagnostic.CONDITIONS},
        "fixture_sha256": {key: digest("fixture:" + key) for key in
                           ("benchmark_manifest", "browser_fixture", "native_fixture")},
        "jev_eligibility": {case_id: True for case_id, _ in diagnostic.CASES},
        "reset_rules": {"browser": "reload", "native": "relaunch_or_reselect"},
    }


def run(slot: dict, *, elapsed: int | None = None, total_tokens: int = 120) -> dict:
    condition = slot["condition"]
    key = f"{slot['case_id']}:{slot['repetition']}:{condition}"
    elapsed = elapsed or (5000 if condition.endswith("old") else 4400)
    jev = condition.startswith("C_")
    base = (slot["sequence"] - 1) * 130000
    call_start = base + 100
    call_end = base + 200
    return {
        "case_id": slot["case_id"], "repetition": slot["repetition"],
        "condition": condition, "order": slot["order"], "sequence": slot["sequence"],
        "cua_session_sha256": digest("cua:" + key),
        "span": {"start_ms": base, "end_ms": base + elapsed},
        "tool_calls": [
            {"kind": "jev" if jev else "other", "start_ms": call_start,
             "end_ms": call_end, "code_bytes": 40, "output_bytes": 20},
            {"kind": "cua", "start_ms": base + 400, "end_ms": base + 700,
             "code_bytes": 180, "output_bytes": 100},
        ],
        "counts": {"observations": 2, "full_states": 1, "diffs": 1, "excerpts": 0,
                   "fallbacks": 0, "helper_initializations": 1,
                   "candidate_constructions": 1 if jev else 0,
                   "recovery_steps": 0, "action_errors": 0,
                   "verification_failures": 0},
        "codex_usage": {
            "source": "codex_rollout_token_count", "session_sha256": digest("session:" + key),
            "start": {"event_index": 1, "event_sha256": digest("start:" + key),
                      "total_token_usage": tokens(100)},
            "end": {"event_index": 2, "event_sha256": digest("end:" + key),
                    "total_token_usage": tokens(100 + total_tokens)},
        },
        "jev": {"status": "evaluated" if jev else "not_applicable", "skip_reason": "",
                "calls": 1 if jev else 0, "elapsed_ms": 100 if jev else 0,
                "input_tokens": 12 if jev else 0, "output_tokens": 4 if jev else 0},
        "outcome": {"status": "success", "marker": slot["expected_marker"],
                    "verified": True, "wrong_actions": 0, "unsafe_actions": 0,
                    "counter_observed": True},
        "provenance": {field: True for field in diagnostic.PROVENANCE_FIELDS},
    }


def results() -> dict:
    schedule = diagnostic.prepare_schedule()
    return {
        "schema_version": 1, "schedule_sha256": schedule["schedule_sha256"],
        "protocol": protocol(), "records": [run(slot) for slot in schedule["slots"]],
    }


def turn_usage(row: dict) -> dict:
    key = f"{row['case_id']}:{row['repetition']}:{row['condition']}"
    turn = digest("turn:" + key)
    return {
        "source": "codex_turn_token_usage_record",
        "session_sha256": row["codex_usage"]["session_sha256"],
        "turn_sha256": turn,
        "event_index": 7,
        "event_sha256": digest("terminal-usage:" + key),
        "turn_token_usage": tokens(120),
        "terminal_usage_verified": True,
        "task_complete": {
            "kind": "task_complete", "event_index": 8,
            "event_sha256": digest("task-complete:" + key),
            "turn_sha256": turn, "after_verification": True,
        },
    }


class DiagnosticTests(unittest.TestCase):
    def test_preassigned_schedule_has_72_near_balanced_slots(self) -> None:
        schedule = diagnostic.prepare_schedule()
        self.assertEqual(len(schedule["slots"]), 72)
        self.assertEqual(schedule, diagnostic.prepare_schedule())
        positions = {(condition, position): 0 for condition in diagnostic.CONDITIONS
                     for position in range(1, 5)}
        for slot in schedule["slots"]:
            positions[(slot["condition"], slot["order"])] += 1
            self.assertEqual(slot["expected_marker"], "PASS " + slot["case_id"])
            self.assertEqual(slot["timeout_ms"], 120000)
        self.assertEqual([slot["sequence"] for slot in schedule["slots"]], list(range(1, 73)))
        self.assertEqual(set(positions.values()), {4, 5})
        for case_id, _ in diagnostic.CASES:
            for repetition in diagnostic.REPETITIONS:
                block = [slot for slot in schedule["slots"]
                         if slot["case_id"] == case_id and slot["repetition"] == repetition]
                self.assertEqual({slot["condition"] for slot in block}, set(diagnostic.CONDITIONS))
                self.assertEqual({slot["order"] for slot in block}, {1, 2, 3, 4})

    def test_full_import_reports_paired_cases_and_surface_screening(self) -> None:
        report = diagnostic.score_results(results())
        self.assertEqual(report["complete_runs"], 72)
        self.assertEqual(report["screening"], "passes")
        self.assertEqual(set(report["cases"]), set(diagnostic.CASE_SURFACE))
        self.assertEqual(len(report["cases"]["browser-tabs-0"]["comparisons"]["ordinary"]["paired_repetitions"]), 3)
        for surface in ("browser", "native"):
            self.assertEqual(report["surfaces"][surface]["screening"], "passes")
            comparison = report["surfaces"][surface]["comparisons"]["ordinary"]
            self.assertAlmostEqual(comparison["median_speedup_fraction"], 0.12)
            self.assertEqual(comparison["current"]["between_calls_ms"],
                             200 * (12 if surface == "browser" else 6))

    def test_missing_run_and_sixth_counter_remain_incomplete(self) -> None:
        data = results()
        data["records"].pop()
        del data["records"][0]["codex_usage"]["end"]["total_token_usage"]["cache_write_input_tokens"]
        report = diagnostic.score_results(data)
        self.assertEqual(report["complete_runs"], 70)
        self.assertEqual(len(report["missing"]), 1)
        self.assertEqual(len(report["incomplete"]), 1)
        self.assertEqual(report["screening"], "incomplete")

    def test_terminal_turn_usage_record_is_accepted_without_delta_subtraction(self) -> None:
        data = results()
        data["records"][0]["codex_usage"] = turn_usage(data["records"][0])
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "passes")
        self.assertEqual(report["surfaces"]["browser"]["comparisons"]["ordinary"]["current"]["total_codex_tokens"], 12 * 120)

    def test_early_or_unbounded_turn_usage_is_incomplete(self) -> None:
        data = results()
        row = data["records"][0]
        row["codex_usage"] = turn_usage(row)
        row["codex_usage"]["terminal_usage_verified"] = False
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "incomplete")
        self.assertIn("terminal turn usage", report["incomplete"][0]["reason"])
        row["codex_usage"]["terminal_usage_verified"] = True
        del row["codex_usage"]["task_complete"]
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "incomplete")
        row["codex_usage"] = turn_usage(row)
        del row["codex_usage"]["turn_token_usage"]["cache_write_input_tokens"]
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "incomplete")

    def test_turn_completed_summary_and_reused_turn_are_rejected(self) -> None:
        data = results()
        data["records"][0]["codex_usage"] = {"source": "turn.completed", "total_tokens": 120}
        with self.assertRaisesRegex(ValueError, "raw payloads|unsupported"):
            diagnostic.score_results(data)
        data = results()
        for row in data["records"][:2]:
            row["codex_usage"] = turn_usage(row)
        data["records"][1]["codex_usage"]["turn_sha256"] = data["records"][0]["codex_usage"]["turn_sha256"]
        data["records"][1]["codex_usage"]["task_complete"]["turn_sha256"] = data["records"][0]["codex_usage"]["turn_sha256"]
        with self.assertRaisesRegex(ValueError, "turn or usage event reused"):
            diagnostic.score_results(data)
        data = results()
        row = data["records"][0]
        row["codex_usage"] = turn_usage(row)
        row["codex_usage"]["task_complete"]["event_index"] = 6
        with self.assertRaisesRegex(ValueError, "must follow"):
            diagnostic.score_results(data)
        data = results()
        row = data["records"][0]
        row["codex_usage"] = turn_usage(row)
        row["codex_usage"]["prompt"] = "private page"
        with self.assertRaisesRegex(ValueError, "raw payloads"):
            diagnostic.score_results(data)

    def test_raw_ui_payload_is_rejected_at_every_boundary(self) -> None:
        for path, value in (
            (("records", 0), {"ui_text": "private page"}),
            (("records", 0, "tool_calls", 0), {"request": "private page"}),
            (("records", 0, "codex_usage", "start"), {"raw_event": "private page"}),
            (("protocol",), {"prompt": "private page"}),
        ):
            with self.subTest(path=path):
                data = results()
                target = data
                for key in path:
                    target = target[key]
                target.update(value)
                with self.assertRaisesRegex(ValueError, "raw payloads|unexpected"):
                    diagnostic.score_results(data)

    def test_exact_completion_marker_and_verification_required(self) -> None:
        for marker in ("PASS browser-tabs-0 extra", "prefix PASS browser-tabs-0"):
            data = results()
            data["records"][0]["outcome"]["marker"] = marker
            with self.assertRaisesRegex(ValueError, "exact"):
                diagnostic.score_results(data)
        data = results()
        data["records"][0]["outcome"]["verified"] = False
        with self.assertRaisesRegex(ValueError, "verified exact"):
            diagnostic.score_results(data)

    def test_wrong_action_counter_is_included_and_missing_counter_blocks_screen(self) -> None:
        data = results()
        optimized = next(row for row in data["records"] if row["condition"] == "B_new")
        optimized["outcome"]["wrong_actions"] = 1
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "does_not_pass")
        self.assertFalse(report["surfaces"]["browser"]["comparisons"]["ordinary"]["quality_pass"])
        optimized["outcome"].update(counter_observed=False, wrong_actions=None)
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "incomplete")

    def test_wrong_actions_cannot_shift_between_cases(self) -> None:
        data = results()
        current = next(row for row in data["records"] if
                       row["case_id"] == "browser-tabs-0" and row["condition"] == "B_old")
        optimized = next(row for row in data["records"] if
                         row["case_id"] == "browser-duplicate_label-0" and row["condition"] == "B_new")
        current["outcome"]["wrong_actions"] = 1
        optimized["outcome"]["wrong_actions"] = 1
        report = diagnostic.score_results(data)
        self.assertTrue(report["surfaces"]["browser"]["comparisons"]["ordinary"]["quality_pass"])
        self.assertFalse(report["cases"]["browser-duplicate_label-0"]["comparisons"]["ordinary"]["quality_pass"])
        self.assertEqual(report["screening"], "does_not_pass")

    def test_overlapping_trials_and_missing_timed_tools_are_rejected(self) -> None:
        data = results()
        data["records"][1]["span"]["start_ms"] = data["records"][0]["span"]["start_ms"]
        with self.assertRaisesRegex(ValueError, "sequential"):
            diagnostic.score_results(data)
        data = results()
        data["records"][0]["tool_calls"][1]["kind"] = "other"
        with self.assertRaisesRegex(ValueError, "timed CUA"):
            diagnostic.score_results(data)
        data = results()
        jev_row = next(row for row in data["records"] if row["condition"].startswith("C_"))
        jev_row["tool_calls"][0]["kind"] = "other"
        with self.assertRaisesRegex(ValueError, "timed CUA and Jev"):
            diagnostic.score_results(data)

    def test_action_error_with_successful_side_effect_is_still_success(self) -> None:
        data = results()
        data["records"][0]["counts"]["action_errors"] = 1
        self.assertEqual(diagnostic.score_results(data)["screening"], "passes")

    def test_excerpt_can_display_same_full_state_observation(self) -> None:
        data = results()
        data["records"][0]["counts"].update(
            observations=1, full_states=1, diffs=0, excerpts=1,
        )
        self.assertEqual(diagnostic.score_results(data)["screening"], "passes")

    def test_failed_verification_is_counted_as_failure(self) -> None:
        data = results()
        optimized = next(row for row in data["records"] if row["condition"] == "B_new")
        optimized["outcome"].update(status="failure", marker="PASS " + optimized["case_id"], verified=False)
        optimized["counts"]["verification_failures"] = 1
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "does_not_pass")
        self.assertEqual(report["surfaces"]["browser"]["comparisons"]["ordinary"]["optimized"]["failures"], 1)
        optimized["outcome"]["verified"] = True
        with self.assertRaisesRegex(ValueError, "verified completion"):
            diagnostic.score_results(data)

    def test_jev_eligibility_is_enforced(self) -> None:
        data = results()
        case_id = data["records"][0]["case_id"]
        data["protocol"]["jev_eligibility"][case_id] = False
        with self.assertRaisesRegex(ValueError, "ineligible"):
            diagnostic.score_results(data)

    def test_jev_assisted_screen_needs_measured_advice_coverage(self) -> None:
        data = results()
        for row in data["records"]:
            if row["condition"].startswith("C_"):
                row["tool_calls"][0]["kind"] = "other"
                row["jev"].update(status="skipped", skip_reason="no_meaningful_choice",
                                  calls=0, elapsed_ms=0, input_tokens=0, output_tokens=0)
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "incomplete")
        self.assertEqual(report["surfaces"]["browser"]["jev_call_coverage"],
                         {"C_old": 0, "C_new": 0})
        data = results()
        row = next(row for row in data["records"] if row["condition"].startswith("C_"))
        row["tool_calls"][0]["kind"] = "other"
        row["jev"].update(status="skipped", skip_reason="service_unavailable",
                          calls=0, elapsed_ms=0, input_tokens=0, output_tokens=0)
        self.assertEqual(diagnostic.score_results(data)["screening"], "incomplete")

        data = results()
        for row in data["records"]:
            if row["condition"].startswith("C_"):
                row["jev"]["status"] = "abstained"
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "incomplete")
        self.assertTrue(report["surfaces"]["browser"]["jev_call_coverage"]["C_old"])
        self.assertEqual(report["surfaces"]["browser"]["jev_evaluated_coverage"],
                         {"C_old": 0, "C_new": 0})

    def test_timeout_is_included_and_blocks_quality(self) -> None:
        data = results()
        optimized = next(row for row in data["records"] if row["condition"] == "C_new")
        optimized["span"]["end_ms"] = optimized["span"]["start_ms"] + 120000
        optimized["outcome"].update(status="timeout", marker=None, verified=False)
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "does_not_pass")
        self.assertEqual(report["surfaces"]["browser"]["comparisons"]["jev_assisted"]["optimized"]["timeouts"], 1)

    def test_timeout_without_terminal_usage_remains_visible_and_incomplete(self) -> None:
        data = results()
        optimized = next(row for row in data["records"] if row["condition"] == "B_new")
        optimized["span"]["end_ms"] = optimized["span"]["start_ms"] + 120000
        optimized["outcome"].update(status="timeout", marker=None, verified=False,
                                    wrong_actions=None, counter_observed=False,
                                    unsafe_actions=None)
        optimized["codex_usage"] = None
        optimized["counts"]["observations"] = None
        report = diagnostic.score_results(data)
        self.assertEqual(report["screening"], "incomplete")
        self.assertEqual(report["complete_runs"], 71)
        self.assertEqual(report["incomplete"][0]["outcome_status"], "timeout")
        quality = report["surfaces"]["browser"]["observed_quality"]["B_new"]
        self.assertEqual(quality["timeouts"], 1)
        self.assertEqual(quality["wrong_action_counters_missing"], 1)
        self.assertEqual(quality["unsafe_action_counts_missing"], 1)
        self.assertEqual(len(report["cases"][optimized["case_id"]]["observed_elapsed_pairs"]["ordinary"]), 3)

    def test_incomplete_count_cannot_hide_raw_payload_in_allowed_field(self) -> None:
        data = results()
        row = data["records"][0]
        row["counts"]["observations"] = None
        row["jev"]["status"] = "PRIVATE RAW UI TEXT"
        with self.assertRaisesRegex(ValueError, "Jev outcome status"):
            diagnostic.score_results(data)
        row["jev"]["status"] = "not_applicable"
        row["outcome"]["marker"] = "PASS browser-duplicate_label-0\nPRIVATE RAW UI TEXT"
        with self.assertRaisesRegex(ValueError, "exact"):
            diagnostic.score_results(data)

    def test_timeout_becoming_failure_is_quality_regression(self) -> None:
        data = results()
        case_id = "browser-duplicate_label-0"
        current = next(row for row in data["records"] if
                       row["case_id"] == case_id and row["repetition"] == 1
                       and row["condition"] == "B_old")
        optimized = next(row for row in data["records"] if
                         row["case_id"] == case_id and row["repetition"] == 1
                         and row["condition"] == "B_new")
        current["span"]["end_ms"] = current["span"]["start_ms"] + 120000
        current["outcome"].update(status="timeout", marker=None, verified=False)
        optimized["outcome"].update(status="failure", marker=None, verified=False)
        optimized["counts"]["verification_failures"] = 1
        comparison = diagnostic.score_results(data)["surfaces"]["browser"]["comparisons"]["ordinary"]
        self.assertEqual(comparison["current"]["successes"], comparison["optimized"]["successes"])
        self.assertEqual(comparison["current"]["timeouts"], 1)
        self.assertEqual(comparison["optimized"]["failures"], 1)
        self.assertFalse(comparison["quality_pass"])

    def test_reused_context_and_wrong_schedule_order_rejected(self) -> None:
        data = results()
        data["records"][1]["codex_usage"]["session_sha256"] = data["records"][0]["codex_usage"]["session_sha256"]
        with self.assertRaisesRegex(ValueError, "reused"):
            diagnostic.score_results(data)
        data = results()
        data["records"][1]["cua_session_sha256"] = data["records"][0]["cua_session_sha256"]
        with self.assertRaisesRegex(ValueError, "CUA session reused"):
            diagnostic.score_results(data)
        data = results()
        data["records"][0]["order"] = 9
        with self.assertRaisesRegex(ValueError, "preassigned"):
            diagnostic.score_results(data)
        data = results()
        data["records"][0], data["records"][1] = data["records"][1], data["records"][0]
        with self.assertRaisesRegex(ValueError, "sequential"):
            diagnostic.score_results(data)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                diagnostic.read_json(path)

    def test_oversized_numeric_span_is_rejected_without_overflow(self) -> None:
        data = results()
        data["records"][0]["span"]["end_ms"] = 10 ** 1000
        with self.assertRaisesRegex(ValueError, "finite number"):
            diagnostic.score_results(data)


if __name__ == "__main__":
    unittest.main()
