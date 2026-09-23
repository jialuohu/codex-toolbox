"""Offline measurements for a frozen synthetic capability-routing screen."""

import copy
import unittest
from pathlib import Path

from scripts import eval_skill_routing as evaluator

MANIFEST = Path(__file__).resolve().parent / "fixtures/capability-routing-benchmark.json"


class CapabilityRoutingBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.manifest_hash = evaluator.load_benchmark(MANIFEST)

    def response(self, baseline_wrong=False):
        cases = evaluator._benchmark_cases(self.manifest, "heldout")
        response = {"schema_version": 1, "manifest_sha256": self.manifest_hash,
                    "split": "heldout", "runs": []}
        for case in cases:
            expected = case["acceptable_sets"][0]
            allowed = {row["id"] for row in evaluator._allowed_catalog(self.manifest, case)}
            for repetition in range(1, 4):
                baseline = list(expected)
                if baseline_wrong and case["eligible_for_jev"]:
                    baseline = [] if expected else ["skill:archify"]
                response["runs"].append({"case_id": case["case_id"], "repetition": repetition,
                                         "arm": "baseline", "selected_ids": baseline,
                                         "elapsed_ms": 100, "known_cost_usd": 0.01,
                                         "cost_unknown": False})
                response["runs"].append({"case_id": case["case_id"], "repetition": repetition,
                                         "arm": "assisted", "selected_ids": list(expected),
                                         "elapsed_ms": 200, "known_cost_usd": 0.02,
                                         "cost_unknown": False,
                                         "shortlist_ids": sorted(allowed) if case["eligible_for_jev"] else [],
                                         "recommended_ids": list(expected) if case["eligible_for_jev"] else [],
                                         "jev_status": "evaluated" if case["eligible_for_jev"] else "skipped",
                                         "jev_input_sent": case["eligible_for_jev"],
                                         "skip_reason": "private_or_unavailable" if not case["eligible_for_jev"] else ""})
        return response

    def test_frozen_manifest_has_separate_tuning_and_heldout_scenarios(self):
        tuning = evaluator._benchmark_cases(self.manifest, "tuning")
        heldout = evaluator._benchmark_cases(self.manifest, "heldout")
        self.assertEqual(len(tuning), 20)
        self.assertEqual(len(heldout), 200)
        self.assertFalse({case["prompt"] for case in tuning} & {case["prompt"] for case in heldout})
        packet = evaluator.prepare_benchmark(self.manifest, self.manifest_hash, "heldout")
        self.assertEqual(len(packet["requests"]), 140)
        self.assertEqual(len(packet["local_skip_case_ids"]), 60)
        self.assertTrue(all(len(request["catalog"]) <= 16 for request in packet["requests"]))
        self.assertNotIn("acceptable_sets", str(packet))
        self.assertNotIn("forbidden_ids", str(packet))
        self.assertNotIn("confidential assigned submission", str(packet))
        self.assertNotIn("tool:docmost_read", str(packet))
        ordinary = next(request for request in packet["requests"] if request["case_id"] == "ordinary-repo-01")
        explicit = next(request for request in packet["requests"] if request["case_id"] == "explicit-ship-01")
        self.assertNotIn("skill:ship-toolbox", {row["id"] for row in ordinary["catalog"]})
        self.assertIn("skill:ship-toolbox", {row["id"] for row in explicit["catalog"]})

    def test_paired_scores_and_cluster_interval(self):
        equal = evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", self.response())
        self.assertTrue(equal["complete"])
        self.assertEqual(equal["paired_runs"], 600)
        self.assertEqual(equal["eligible_paired_runs"], 420)
        self.assertEqual(equal["paired_accuracy_delta"], 0)
        self.assertFalse(equal["offline_quality_thresholds_met"])
        self.assertFalse(equal["activation_ready"])
        self.assertEqual(equal["assisted_review"]["status_counts"]["evaluated"], 420)
        self.assertEqual(equal["assisted_review"]["status_counts"]["skipped"], 180)
        self.assertEqual(equal["assisted_review"]["shortlist_recall"], 1)
        self.assertEqual(equal["assisted_review"]["candidate_precision"], 1)
        self.assertEqual(equal["assisted_review"]["candidate_recall"], 1)
        self.assertEqual(equal["p95_added_latency_ms"], 100)
        improved = evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout",
                                             self.response(baseline_wrong=True))
        self.assertEqual(improved["eligible_paired_accuracy_delta"], 1)
        self.assertEqual(improved["eligible_cluster_bootstrap_95_percent_interval"], [1, 1])
        self.assertTrue(improved["offline_quality_thresholds_met"])
        self.assertFalse(improved["activation_ready"])
        skipped = self.response(baseline_wrong=True)
        for run in skipped["runs"]:
            if run["arm"] == "assisted" and run["jev_status"] == "evaluated":
                run.update(jev_status="skipped", jev_input_sent=False,
                           recommended_ids=[], skip_reason="not_needed")
        skipped_result = evaluator.score_benchmark(
            self.manifest, self.manifest_hash, "heldout", skipped)
        self.assertFalse(skipped_result["offline_quality_thresholds_met"])
        no_recommendations = self.response(baseline_wrong=True)
        for run in no_recommendations["runs"]:
            if run["arm"] == "assisted":
                run["recommended_ids"] = []
        no_recommendations_result = evaluator.score_benchmark(
            self.manifest, self.manifest_hash, "heldout", no_recommendations)
        self.assertFalse(no_recommendations_result["offline_quality_thresholds_met"])

    def test_privacy_cost_and_missing_runs_stay_visible(self):
        response = self.response(baseline_wrong=True)
        private = next(run for run in response["runs"] if run["case_id"] == "private-review-01" and run["arm"] == "assisted")
        private["jev_input_sent"] = True
        private["cost_unknown"] = True
        result = evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", response)
        self.assertEqual(result["assisted_review"]["privacy_violations"], 1)
        self.assertIsNone(result["known_total_cost_delta_usd"])
        self.assertFalse(result["offline_quality_thresholds_met"])
        unknown_cost = self.response(baseline_wrong=True)
        unknown_cost["runs"][0]["cost_unknown"] = True
        cost_result = evaluator.score_benchmark(
            self.manifest, self.manifest_hash, "heldout", unknown_cost)
        self.assertIsNone(cost_result["known_total_cost_delta_usd"])
        self.assertFalse(cost_result["offline_quality_thresholds_met"])
        response["runs"].remove(private)
        result = evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", response)
        self.assertFalse(result["complete"])
        self.assertEqual(result["assisted_review"]["status_counts"]["missed"], 1)
        self.assertIsNone(result["known_total_cost_delta_usd"])

    def test_provenance_and_invalid_or_duplicate_records_fail(self):
        response = self.response()
        wrong_hash = copy.deepcopy(response)
        wrong_hash["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "provenance"):
            evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", wrong_hash)
        response["runs"].append(copy.deepcopy(response["runs"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", response)
        response.pop("runs")
        with self.assertRaisesRegex(TypeError, "runs must"):
            evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", response)

    def test_forbidden_selection_and_recommendation_scope(self):
        response = self.response(baseline_wrong=True)
        ordinary = next(run for run in response["runs"] if run["case_id"] == "ordinary-repo-01" and run["arm"] == "assisted")
        ordinary["selected_ids"] = ["skill:ship-toolbox"]
        result = evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", response)
        self.assertEqual(result["arms"]["assisted"]["forbidden_selections"], 1)
        self.assertFalse(result["offline_quality_thresholds_met"])
        ordinary["recommended_ids"] = ["tool:docmost_read"]
        with self.assertRaisesRegex(ValueError, "unknown capability"):
            evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", response)

    def test_evaluated_run_requires_recorded_provider_input(self):
        response = self.response()
        assisted = next(run for run in response["runs"] if run["arm"] == "assisted"
                        and run["jev_status"] == "evaluated")
        assisted["jev_input_sent"] = False
        with self.assertRaisesRegex(ValueError, "requires a Jev input"):
            evaluator.score_benchmark(self.manifest, self.manifest_hash, "heldout", response)


if __name__ == "__main__":
    unittest.main()
