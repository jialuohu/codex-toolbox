"""Synthetic, offline checks for the computer-use activation scorer."""

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "plugins/typesafe-tools/computer_use_benchmark"
sys.path.insert(0, str(BENCHMARK.parent))
from computer_use_benchmark import score as benchmark


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def usage(input_tokens, output_tokens, cached_input_tokens, reasoning_output_tokens):
    return {"input_tokens": input_tokens, "cached_input_tokens": cached_input_tokens,
            "cache_write_input_tokens": 0, "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "total_tokens": input_tokens + output_tokens}


def snapshot_usage(key, input_tokens, output_tokens, cached_input_tokens):
    start = usage(100, 20, 10, 5)
    end = usage(100 + input_tokens, 20 + output_tokens,
                10 + cached_input_tokens, 5 + min(output_tokens, 30))
    return {"source": "codex_rollout_token_count", "session_sha256": digest("session:" + key),
            "start": {"event_index": 1, "event_sha256": digest("start:" + key),
                      "total_token_usage": start},
            "end": {"event_index": 2, "event_sha256": digest("end:" + key),
                    "total_token_usage": end}}


class ComputerUseBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.fixture_hash, cls.cases = benchmark.load_fixtures()

    def make_results(self):
        document = {"schema_version": 1, "fixture_sha256": self.fixture_hash, "records": []}
        for case in self.cases:
            if case["split"] != "heldout":
                continue
            for repetition in range(1, 4):
                order = benchmark.condition_order(self.fixture_hash, case["case_id"], repetition)
                for condition in benchmark.CONDITIONS:
                    tokens, elapsed = {"A": (1000, 1000), "B": (800, 800), "C": (600, 600)}[condition]
                    key = f"{case['case_id']}:{repetition}:{condition}"
                    jev_called = condition == "C" and case["jev_eligible"]
                    document["records"].append({
                        "case_id": case["case_id"], "repetition": repetition,
                        "condition": condition, "order": order[condition],
                        "elapsed_ms": elapsed, "success": True, "marker_seen": True,
                        "wrong_actions": 0, "unsafe_actions": 0, "tool_calls": 4,
                        "reset_verified": True, "observation_complete": True,
                        "usage_isolated": True, "timing_complete": True,
                        "codex_usage": snapshot_usage(key, tokens * 4 // 5,
                                                       tokens // 5, tokens * 2 // 5),
                        "jev_usage": {"calls": int(jev_called),
                                      "input_tokens": 30 if jev_called else 0,
                                      "output_tokens": 4 if jev_called else 0,
                                      "elapsed_ms": 100 if jev_called else 0},
                        "jev_decision": ({"status": "evaluated", "skip_reason": ""}
                                         if jev_called else
                                         {"status": "skipped", "skip_reason": "ineligible_fixture"}
                                         if condition == "C" else
                                         {"status": "not_applicable", "skip_reason": ""}),
                    })
        return document

    def test_frozen_fixtures_match_disposable_gui_case_ids(self):
        self.assertEqual(len(self.cases), 80)
        self.assertEqual(len({case["case_id"] for case in self.cases}), 80)
        for surface in benchmark.SURFACES:
            grouped = [case for case in self.cases if case["surface"] == surface]
            self.assertEqual(len([case for case in grouped if case["split"] == "tuning"]), 10)
            self.assertEqual(len([case for case in grouped if case["split"] == "heldout"]), 30)
            self.assertEqual(len({case["category"] for case in grouped}), 10)
            self.assertEqual(sum(case["jev_eligible"] for case in grouped if case["split"] == "heldout"), 15)
            self.assertTrue(all(case["expected_result"] == "PASS " + case["case_id"] for case in grouped))
            for case in grouped:
                action_ids = {action["id"] for action in case["actions"]}
                if case["jev_eligible"]:
                    self.assertIn(case["expected_action_id"], action_ids)
                    self.assertGreaterEqual(len(action_ids), 4)
                    self.assertFalse(action_ids & {"other", "refresh", "abandon"})
                else:
                    self.assertEqual(case["decision_stage"], "none")
                    self.assertEqual(case["actions"], [])
                    self.assertIsNone(case["expected_action_id"])
            self.assertEqual(next(case for case in grouped if case["category"] == "dialog")
                             ["decision_stage"], "picker_open")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fixtures.json").write_bytes((BENCHMARK / "fixtures.json").read_bytes())
            (root / "freeze.json").write_bytes((BENCHMARK / "freeze.json").read_bytes())
            (root / "fixtures.json").write_text((root / "fixtures.json").read_text() + " ")
            with self.assertRaisesRegex(ValueError, "frozen fixture digest"):
                benchmark.load_fixtures(root)

    def test_frozen_schedule_has_three_conditions_and_three_repetitions(self):
        schedule = benchmark.prepare_schedule()
        self.assertEqual(len(schedule["runs"]), 540)
        self.assertEqual(schedule["fixture_sha256"], self.fixture_hash)
        keys = {(row["case_id"], row["repetition"]) for row in schedule["runs"]}
        for key in keys:
            triplet = [row for row in schedule["runs"] if (row["case_id"], row["repetition"]) == key]
            self.assertEqual({row["condition"] for row in triplet}, set(benchmark.CONDITIONS))
            self.assertEqual({row["order"] for row in triplet}, {1, 2, 3})

    def test_measured_usage_and_quality_gate_qualify_each_surface(self):
        result = benchmark.score_results(self.make_results())
        self.assertFalse(result["automatic_use_enabled"])
        for surface in benchmark.SURFACES:
            report = result["surfaces"][surface]
            self.assertTrue(report["complete"])
            self.assertTrue(report["activation_ready"])
            self.assertEqual(report["expected_runs"], 270)
            self.assertEqual(report["conditions"]["C"]["runs"], 90)
            self.assertEqual(report["conditions"]["C"]["mean_codex_tokens"], 600)
            self.assertEqual(report["conditions"]["C"]["total_cached_input_tokens"], 90 * 240)
            self.assertEqual(report["conditions"]["C"]["total_codex_input_tokens"], 90 * 480)
            self.assertEqual(report["jev_coverage"]["eligible_runs"], 45)
            self.assertEqual(report["jev_coverage"]["fraction"], 1)
            self.assertGreater(report["comparisons"]["C_vs_B"]["latency"]["paired_difference_ci"][0], 0)

    def test_missing_records_or_counters_disable_only_the_affected_surface(self):
        results = self.make_results()
        results["records"].pop(0)
        report = benchmark.score_results(results)["surfaces"]
        self.assertFalse(report["browser"]["complete"])
        self.assertFalse(report["browser"]["activation_ready"])
        self.assertTrue(report["native"]["activation_ready"])
        results = self.make_results()
        browser = results["records"][0]
        browser["codex_usage"]["end"]["total_token_usage"].pop("cached_input_tokens")
        report = benchmark.score_results(results)["surfaces"]
        self.assertEqual(report["browser"]["incomplete_runs"], 1)
        self.assertFalse(report["browser"]["activation_ready"])
        self.assertTrue(report["native"]["activation_ready"])

    def test_unisolated_tokens_and_incomplete_timing_fail_closed(self):
        for field in ("usage_isolated", "timing_complete", "reset_verified", "observation_complete"):
            with self.subTest(field=field):
                results = self.make_results()
                results["records"][0][field] = False
                report = benchmark.score_results(results)["surfaces"]["browser"]
                self.assertFalse(report["complete"])
                self.assertFalse(report["activation_ready"])

    def test_jev_coverage_requires_more_than_one_incidental_call(self):
        results = self.make_results()
        retained = False
        for row in results["records"]:
            if row["condition"] == "C" and row["jev_usage"]["calls"]:
                if not retained and row["case_id"].startswith("browser-"):
                    retained = True
                    continue
                row["jev_usage"] = {"calls": 0, "input_tokens": 0,
                                    "output_tokens": 0, "elapsed_ms": 0}
                row["jev_decision"] = {"status": "skipped", "skip_reason": "no_meaningful_choice"}
        report = benchmark.score_results(results)["surfaces"]
        self.assertTrue(report["browser"]["complete"])
        self.assertEqual(report["browser"]["jev_coverage"]["evaluated_or_abstained_runs"], 1)
        self.assertFalse(report["browser"]["activation_ready"])
        self.assertFalse(report["native"]["activation_ready"])

    def test_quality_regressions_and_unsafe_actions_block_activation(self):
        for edit in (lambda row: row.update(success=False, marker_seen=False),
                     lambda row: row.update(wrong_actions=1),
                     lambda row: row.update(unsafe_actions=1)):
            with self.subTest(edit=edit):
                results = self.make_results()
                assisted = next(row for row in results["records"]
                                if row["case_id"].startswith("browser-") and row["condition"] == "C")
                edit(assisted)
                report = benchmark.score_results(results)["surfaces"]
                self.assertFalse(report["browser"]["activation_ready"])
                self.assertTrue(report["native"]["activation_ready"])

    def test_latency_and_token_benefit_are_separate(self):
        results = self.make_results()
        for row in results["records"]:
            if row["case_id"].startswith("browser-") and row["condition"] == "C":
                row["elapsed_ms"] = 790
        report = benchmark.score_results(results)["surfaces"]["browser"]
        self.assertTrue(report["complete"])
        self.assertFalse(report["comparisons"]["C_vs_B"]["latency"]["passes"])
        self.assertTrue(report["comparisons"]["C_vs_B"]["codex_tokens"]["passes"])
        self.assertFalse(report["activation_ready"])

    def test_clustered_interval_can_reject_heterogeneous_benefit(self):
        results = self.make_results()
        categories = sorted({case["category"] for case in self.cases})
        for row in results["records"]:
            if row["case_id"].startswith("browser-") and row["condition"] == "C":
                category = next(category for category in categories
                                if row["case_id"].startswith("browser-" + category + "-"))
                row["elapsed_ms"] = 300 if category in categories[:5] else 950
        report = benchmark.score_results(results)["surfaces"]["browser"]
        self.assertGreater(report["comparisons"]["C_vs_B"]["latency"]["mean_reduction_fraction"], 0.10)
        self.assertLessEqual(report["comparisons"]["C_vs_B"]["latency"]["paired_difference_ci"][0], 0)
        self.assertFalse(report["activation_ready"])

    def test_provenance_payloads_reused_telemetry_and_order_are_rejected(self):
        results = self.make_results()
        wrong_hash = copy.deepcopy(results)
        wrong_hash["fixture_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "provenance"):
            benchmark.score_results(wrong_hash)
        payload = copy.deepcopy(results)
        payload["records"][0]["observation"] = "private screen contents"
        with self.assertRaisesRegex(ValueError, "UI payloads"):
            benchmark.score_results(payload)
        reused = copy.deepcopy(results)
        reused["records"][1]["codex_usage"] = reused["records"][0]["codex_usage"]
        with self.assertRaisesRegex(ValueError, "overlap"):
            benchmark.score_results(reused)
        order = copy.deepcopy(results)
        order["records"][0]["order"] = order["records"][0]["order"] % 3 + 1
        self.assertFalse(benchmark.score_results(order)["surfaces"]["browser"]["activation_ready"])

    def test_delta_usage_is_accepted_without_double_counting_cache(self):
        results = self.make_results()
        row = results["records"][0]
        measured = usage(800, 200, 400, 30)
        row["codex_usage"] = {"source": "codex_runtime_usage_event_delta",
                              "events": [{"event_sha256": digest("delta:event"), **measured}]}
        report = benchmark.score_results(results)["surfaces"]["browser"]
        self.assertTrue(report["activation_ready"])
        self.assertEqual(report["conditions"]["A"]["mean_codex_tokens"], 1000)


if __name__ == "__main__":
    unittest.main()
