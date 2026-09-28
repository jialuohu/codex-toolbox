"""Offline tests for the metadata-only exploratory trial summary."""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
sys.path.insert(0, str(ROOT / "tests"))

exploratory_summary = importlib.import_module("computer_use_diagnostic.exploratory_summary")
report = importlib.import_module("computer_use_diagnostic.report")
diagnostic_fixtures = importlib.import_module("test_computer_use_diagnostic")
results = diagnostic_fixtures.results
turn_usage = diagnostic_fixtures.turn_usage


def incomplete_first_block() -> dict:
    document = results()
    document["records"] = document["records"][:4]
    for row in document["records"]:
        row["cua_session_sha256"] = None
        row["counts"] = {field: None for field in report.COUNT_FIELDS}
        row["outcome"]["unsafe_actions"] = None
    return document


class ExploratorySummaryTests(unittest.TestCase):
    def test_incomplete_screen_preserves_measured_pairs_and_failures(self) -> None:
        document = incomplete_first_block()
        rows = {row["condition"]: row for row in document["records"]}
        rows["B_new"]["outcome"].update(
            status="failure", marker=None, verified=False, wrong_actions=1,
        )
        timeout = rows["C_new"]
        timeout["span"]["end_ms"] = timeout["span"]["start_ms"] + 120000
        timeout["outcome"].update(
            status="timeout", marker=None, verified=False,
            wrong_actions=None, counter_observed=False,
        )
        timeout["codex_usage"] = None

        summary = exploratory_summary.summarize_results(document)
        self.assertEqual(summary["screening"], "incomplete")
        self.assertEqual(summary["complete_screening_runs"], 0)
        self.assertEqual(summary["measurements_missing"], {
            "codex_total_tokens": 1,
            "cua_session_identity": 4,
            "exact_operation_counts": 4,
            "unsafe_action_count": 4,
        })
        ordinary = summary["cases"]["browser-duplicate_label-0"]["comparisons"]["ordinary"]
        self.assertEqual(ordinary["supplied_pairs"], 1)
        self.assertEqual(ordinary["elapsed_pairs"], 1)
        self.assertEqual(ordinary["token_pairs"], 1)
        self.assertEqual(ordinary["median_paired_elapsed_delta_ms"], -600)
        self.assertEqual(ordinary["median_current_codex_total_tokens"], 120)
        self.assertEqual(ordinary["median_optimized_codex_total_tokens"], 120)
        self.assertEqual(ordinary["optimized_quality"]["failures"], 1)
        self.assertEqual(ordinary["optimized_quality"]["wrong_actions_observed"], 1)
        assisted = summary["surfaces"]["browser"]["comparisons"]["jev_assisted"]
        self.assertEqual(assisted["paired_repetitions"][0]["optimized"]["status"], "timeout")
        self.assertEqual(assisted["optimized_quality"]["timeouts"], 1)
        self.assertEqual(assisted["token_pairs"], 0)
        self.assertIsNone(assisted["median_paired_codex_token_delta"])
        self.assertNotIn("cua_session_sha256", json.dumps(summary))
        self.assertNotIn("codex_usage", json.dumps(summary))

    def test_unpaired_timeout_is_retained_in_quality(self) -> None:
        document = incomplete_first_block()
        document["records"] = [row for row in document["records"]
                               if row["condition"] in {"B_old", "C_new"}]
        timeout = next(row for row in document["records"] if row["condition"] == "C_new")
        timeout["span"]["end_ms"] = timeout["span"]["start_ms"] + 120000
        timeout["outcome"].update(status="timeout", marker=None, verified=False)
        summary = exploratory_summary.summarize_results(document)
        assisted = summary["cases"]["browser-duplicate_label-0"]["comparisons"]["jev_assisted"]
        self.assertEqual(assisted["supplied_pairs"], 0)
        self.assertEqual(assisted["optimized_quality"]["timeouts"], 1)
        self.assertEqual(assisted["current_quality"]["supplied_runs"], 0)
        self.assertEqual(summary["measurements_missing"]["codex_total_tokens"], 1)

    def test_normal_failed_exit_retains_terminal_usage_without_passing_screen(self) -> None:
        document = incomplete_first_block()
        row = next(row for row in document["records"] if row["condition"] == "B_new")
        row["outcome"].update(status="failure", marker=None, verified=False)
        row["codex_usage"] = turn_usage(row)
        row["codex_usage"]["task_complete"]["after_verification"] = False

        self.assertEqual(report.score_results(document)["screening"], "incomplete")
        summary = exploratory_summary.summarize_results(document)
        ordinary = summary["cases"]["browser-duplicate_label-0"]["comparisons"]["ordinary"]
        self.assertEqual(ordinary["token_pairs"], 1)
        self.assertEqual(ordinary["paired_repetitions"][0]["optimized"]["codex_total_tokens"], 120)
        self.assertEqual(ordinary["optimized_quality"]["failures"], 1)

    def test_unverified_terminal_usage_is_not_attributed_to_success_or_timeout(self) -> None:
        document = incomplete_first_block()
        success = next(row for row in document["records"] if row["condition"] == "B_new")
        success["codex_usage"] = turn_usage(success)
        success["codex_usage"]["task_complete"]["after_verification"] = False
        timeout = next(row for row in document["records"] if row["condition"] == "C_new")
        timeout["span"]["end_ms"] = timeout["span"]["start_ms"] + 120000
        timeout["outcome"].update(status="timeout", marker=None, verified=False)
        timeout["codex_usage"] = turn_usage(timeout)
        timeout["codex_usage"]["task_complete"]["after_verification"] = False

        summary = exploratory_summary.summarize_results(document)
        ordinary = summary["cases"]["browser-duplicate_label-0"]["comparisons"]["ordinary"]
        assisted = summary["cases"]["browser-duplicate_label-0"]["comparisons"]["jev_assisted"]
        self.assertIsNone(ordinary["paired_repetitions"][0]["optimized"]["codex_total_tokens"])
        self.assertIsNone(assisted["paired_repetitions"][0]["optimized"]["codex_total_tokens"])
        self.assertEqual(summary["measurements_missing"]["codex_total_tokens"], 2)

    def test_failed_terminal_usage_requires_valid_provenance_and_unique_context(self) -> None:
        document = incomplete_first_block()
        failed = document["records"][1]
        failed["outcome"].update(status="failure", marker=None, verified=False)
        failed["codex_usage"] = turn_usage(failed)
        failed["codex_usage"]["task_complete"]["after_verification"] = False
        failed["provenance"]["usage_isolated"] = False
        summary = exploratory_summary.summarize_results(document)
        ordinary = summary["cases"]["browser-duplicate_label-0"]["comparisons"]["ordinary"]
        self.assertIsNone(ordinary["paired_repetitions"][0]["optimized"]["codex_total_tokens"])

        document["records"][0]["codex_usage"] = failed["codex_usage"]
        with self.assertRaisesRegex(ValueError, "reused across trials"):
            exploratory_summary.summarize_results(document)

        document = incomplete_first_block()
        failed = document["records"][1]
        failed["outcome"].update(status="failure", marker=None, verified=False)
        failed["codex_usage"] = turn_usage(failed)
        failed["codex_usage"]["task_complete"]["after_verification"] = False
        failed["codex_usage"]["task_complete"]["event_index"] = failed["codex_usage"]["event_index"]
        with self.assertRaisesRegex(ValueError, "task_complete must follow"):
            exploratory_summary.summarize_results(document)

    def test_incomplete_screen_does_not_hide_invalid_usage_or_private_payload(self) -> None:
        document = incomplete_first_block()
        document["records"][0]["codex_usage"]["end"]["total_token_usage"]["total_tokens"] += 1
        with self.assertRaisesRegex(ValueError, "inconsistent Codex token counters"):
            exploratory_summary.summarize_results(document)

        document = incomplete_first_block()
        document["records"][0]["ui_text"] = "private fixture data"
        with self.assertRaisesRegex(ValueError, "raw payloads"):
            exploratory_summary.summarize_results(document)

    def test_duplicate_usage_identity_in_incomplete_rows_is_rejected(self) -> None:
        document = incomplete_first_block()
        document["records"][1]["codex_usage"] = document["records"][0]["codex_usage"]
        with self.assertRaisesRegex(ValueError, "reused across trials"):
            exploratory_summary.summarize_results(document)

    def test_complete_fixture_reflects_importer_screening(self) -> None:
        summary = exploratory_summary.summarize_results(results())
        self.assertEqual(summary["screening"], "passes")
        self.assertEqual(summary["complete_screening_runs"], 72)
        ordinary = summary["surfaces"]["native"]["comparisons"]["ordinary"]
        self.assertEqual(ordinary["expected_pairs"], 6)
        self.assertEqual(ordinary["token_pairs"], 6)


if __name__ == "__main__":
    unittest.main()
