"""Offline parser/scorer invariants; synthetic result records are test data only."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("typesafe_pilot", Path(__file__).with_name("pilot.py"))
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


class PilotTests(unittest.TestCase):
    def setUp(self):
        cases, frozen = pilot.validate()
        self.results = {"version": 1, "frozen_sha256": frozen,
                        "run_notes": "Unit-test fabricated records; never a real model evaluation.", "records": []}
        for case in cases:
            for arm in ("baseline", "jev"):
                self.results["records"].append({
                    "case_id": case["id"], "condition": arm, "model": "unit-test-only",
                    "prediction": copy.deepcopy(case["gold"]), "final_answer": "Test-only answer",
                    "elapsed_seconds": 2 if arm == "baseline" else 3,
                    "jev_elapsed_seconds": 0 if arm == "baseline" else 1,
                    "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0,
                              "jev_calls": int(arm == "jev"), "jev_cost_usd": 0},
                    "adjudication": {"reviewer": "test-only", "blinded": True, "final_correct": True,
                                     "unsupported_conclusions": 0, "notes": "Synthetic test assertion"}})

    def score(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            path.write_text(json.dumps(self.results))
            return pilot.score(path)

    def test_complete_pairs_metrics_never_activate(self):
        result = self.score()
        self.assertFalse(result["automatic_use_enabled"])
        self.assertTrue(result["exploratory"])
        self.assertEqual(result["conditions"]["baseline"]["prediction_accuracy"], 1)
        self.assertEqual(result["paired"]["ranking-1"]["elapsed_change_seconds"], 1)

    def test_wrong_answers_scored_separately(self):
        row = self.results["records"][0]
        row["prediction"].reverse()
        row["adjudication"].update(final_correct=False, unsupported_conclusions=1)
        result = self.score()["conditions"]["baseline"]
        self.assertEqual(result["unsupported_conclusions"], 1)
        self.assertLess(result["prediction_accuracy"], 1)

    def test_unknown_charges_preserve_usage_and_do_not_become_zero(self):
        for row in self.results["records"]:
            row["usage"]["cost_usd"] = None
            if row["condition"] == "jev":
                row["usage"]["jev_cost_usd"] = None
        report = self.score()
        for arm in ("baseline", "jev"):
            metrics = report["conditions"][arm]
            self.assertIsNone(metrics["cost_usd"])
            self.assertIsNone(metrics["usage"]["cost_usd"])
            self.assertEqual(metrics["unknown_cost_records"], 60)
            self.assertEqual(metrics["usage"]["input_tokens"], 60)
            self.assertEqual(metrics["final_answer_accuracy"], 1)
            self.assertFalse(report["automatic_use_enabled"])
        baseline, jev = (report["conditions"][arm] for arm in ("baseline", "jev"))
        self.assertEqual(baseline["jev_cost_usd"], 0)
        self.assertEqual(baseline["unknown_jev_cost_records"], 0)
        self.assertIsNone(jev["jev_cost_usd"])
        self.assertIsNone(jev["usage"]["jev_cost_usd"])
        self.assertEqual(jev["unknown_jev_cost_records"], 60)

    def test_mixed_known_and_unknown_charges_propagate_with_counts(self):
        for row in self.results["records"]:
            row["usage"]["cost_usd"] = 1
            if row["condition"] == "jev":
                row["usage"]["jev_cost_usd"] = 0.25
        first = self.results["records"][1]
        first["usage"].update(cost_usd=None, jev_cost_usd=None)
        metrics = self.score()["conditions"]["jev"]
        self.assertIsNone(metrics["cost_usd"])
        self.assertIsNone(metrics["jev_cost_usd"])
        self.assertEqual(metrics["unknown_cost_records"], 1)
        self.assertEqual(metrics["unknown_jev_cost_records"], 1)
        self.assertIsNone(metrics["by_task"]["ranking"]["cost_usd"])
        self.assertEqual(metrics["by_task"]["ranking"]["unknown_cost_records"], 1)
        self.assertEqual(metrics["by_task"]["claim"]["cost_usd"], 30)
        self.assertEqual(metrics["by_task"]["claim"]["unknown_cost_records"], 0)
        affected = [m for m in metrics["by_category"].values() if m["unknown_cost_records"]]
        self.assertEqual(len(affected), 1)
        self.assertIsNone(affected[0]["cost_usd"])

    def test_known_total_with_unknown_jev_breakdown_is_not_invented(self):
        row = self.results["records"][1]
        row["usage"].update(cost_usd=0.5, jev_cost_usd=None)
        metrics = self.score()["conditions"]["jev"]
        self.assertEqual(metrics["cost_usd"], 0.5)
        self.assertIsNone(metrics["jev_cost_usd"])
        self.assertEqual(metrics["unknown_cost_records"], 0)
        self.assertEqual(metrics["unknown_jev_cost_records"], 1)

    def test_unknown_total_with_known_jev_breakdown(self):
        row = self.results["records"][1]
        row["usage"].update(cost_usd=None, jev_cost_usd=0.5)
        metrics = self.score()["conditions"]["jev"]
        self.assertIsNone(metrics["cost_usd"])
        self.assertEqual(metrics["jev_cost_usd"], 0.5)

    def test_unknown_baseline_jev_cost_is_explicitly_unknown(self):
        self.results["records"][0]["usage"]["jev_cost_usd"] = None
        metrics = self.score()["conditions"]["baseline"]
        self.assertIsNone(metrics["jev_cost_usd"])
        self.assertEqual(metrics["unknown_jev_cost_records"], 1)

    def test_unknown_cost_does_not_relax_measurement_or_numeric_validation(self):
        original = copy.deepcopy(self.results)
        mutations = [lambda r: r["usage"].update(input_tokens=None),
                     lambda r: r["usage"].update(output_tokens=None),
                     lambda r: r["usage"].update(jev_calls=None),
                     lambda r: r["usage"].update(cost_usd=-1),
                     lambda r: r["usage"].update(cost_usd=True),
                     lambda r: r["usage"].update(jev_cost_usd="unknown"),
                     lambda r: r["usage"].update(cost_usd=0.1, jev_cost_usd=0.2)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.results = copy.deepcopy(original)
                row = self.results["records"][1]
                row["usage"].update(cost_usd=None, jev_cost_usd=None)
                mutation(row)
                with self.assertRaises(ValueError):
                    self.score()

    def test_missing_duplicate_and_tuning_rejected(self):
        original = copy.deepcopy(self.results)
        for mutation in (lambda r: r["records"].pop(),
                         lambda r: r["records"].append(r["records"][0]),
                         lambda r: r["records"][0].update(case_id="tuning-ranking-1")):
            with self.subTest(mutation=mutation):
                self.results = copy.deepcopy(original)
                mutation(self.results)
                with self.assertRaises(ValueError):
                    self.score()

    def test_dropped_candidate_nonfinite_cost_and_unblinded_review_rejected(self):
        original = copy.deepcopy(self.results)
        mutations = [lambda r: r["prediction"].pop(),
                     lambda r: r["usage"].update(cost_usd=float("nan")),
                     lambda r: r["usage"].update(input_tokens=True),
                     lambda r: r["adjudication"].update(blinded=False),
                     lambda r: r.update(elapsed_seconds=0),
                     lambda r: r["adjudication"].update(unsupported_conclusions=1)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.results = copy.deepcopy(original)
                mutation(self.results["records"][0])
                with self.assertRaises(ValueError):
                    self.score()

    def test_billing_gate_cannot_be_faked_with_empty_jev_arm(self):
        self.results["records"][1]["usage"]["jev_calls"] = 0
        with self.assertRaises(ValueError):
            self.score()

    def test_changed_freeze_rejected(self):
        self.results["frozen_sha256"]["protocol.json"] = "0" * 64
        with self.assertRaises(ValueError):
            self.score()

    def test_fixture_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (*pilot.FROZEN, "freeze.json"):
                (root / name).write_bytes((pilot.ROOT / name).read_bytes())
            with (root / "cases.json").open("a") as stream:
                stream.write(" ")
            with self.assertRaises(ValueError):
                pilot.validate(root)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"records": [], "records": []}')
            with self.assertRaises(ValueError):
                pilot.read_json(path)


if __name__ == "__main__":
    unittest.main()
