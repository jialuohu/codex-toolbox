"""Descriptive v2 summaries retain timeouts and incomplete measurement."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import campaign_v2, runner, summary_v2


def attempt(slot: dict, *, status: str, verified_ms: float | None,
            tokens: int | None) -> dict:
    value = {item.name: None for item in fields(runner.TrialAttempt)}
    value.update({"sequence": slot["sequence"], "case_id": slot["case_id"],
                  "surface": slot["surface"], "repetition": slot["repetition"],
                  "condition": slot["condition"], "order": slot["order"],
                  "status": status, "start_ms": slot["sequence"] * 130000.0,
                  "end_ms": slot["sequence"] * 130000.0 + 100000,
                  "ui_verified_ms": verified_ms, "wrong_actions": 0,
                  "tool_calls": [], "jev_result_status": None,
                  "usage_isolated": tokens is not None})
    if tokens is not None:
        value["codex_usage"] = {"source": "codex_turn_token_usage_record",
                                "turn_token_usage": {
                                    "input_tokens": tokens - 10, "cached_input_tokens": 0,
                                    "cache_write_input_tokens": 0, "output_tokens": 10,
                                    "reasoning_output_tokens": 0, "total_tokens": tokens}}
    return value


class SummaryV2Tests(unittest.TestCase):
    def test_timeout_is_cap_penalized_and_missing_tokens_stay_missing(self) -> None:
        slots = campaign_v2.schedule("canary")
        one = slots[0]
        two = slots[1]
        document = {"schema_version": 2, "protocol": campaign_v2.protocol("canary"),
                    "slots": [
                        {"slot": one, "attempt": attempt(one, status="timeout",
                                                           verified_ms=None, tokens=None),
                         "cleanup": {"close_verified": True}, "quiescent": True,
                         "verification": {"fresh_full_ax_receipt_ms": None}},
                        {"slot": two, "attempt": attempt(
                            two, status="success", verified_ms=two["sequence"] * 130000.0 + 30000,
                            tokens=200),
                         "cleanup": {"close_verified": True}, "quiescent": True,
                         "verification": {"fresh_full_ax_receipt_ms":
                                          two["sequence"] * 130000.0 + 30000}},
                    ]}
        result = summary_v2.summarize(document)
        self.assertEqual(result["screening"], "incomplete")
        self.assertEqual([row["cap_penalized_ms"] for row in result["trials_metadata"]],
                         [120000.0, 30000.0])
        self.assertEqual([row["codex_total_tokens"] for row in result["trials_metadata"]],
                         [None, 200])
        self.assertEqual(result["trials_metadata"][1]["codex_counters"]["input_tokens"], 190)
        self.assertIsNone(result["trials_metadata"][0]["codex_counters"])
        self.assertIn("six_codex_token_counters_missing", result["incomplete_reasons"])
        self.assertIn("exact_operation_and_unsafe_action_counts_unavailable",
                      result["incomplete_reasons"])
        self.assertNotIn("Case ID", json.dumps(result))

    def test_pair_uses_all_outcomes_and_rejects_nonsequential_rows(self) -> None:
        slots = campaign_v2.schedule("canary")[:4]
        rows = []
        for slot in slots:
            is_new = slot["condition"].endswith("new")
            rows.append({"slot": slot, "attempt": attempt(
                slot, status="success" if is_new else "failure",
                verified_ms=(slot["sequence"] * 130000.0 + 50000 if is_new else None),
                tokens=200 if is_new else 100),
                "cleanup": {"close_verified": True}, "quiescent": True})
            rows[-1]["verification"] = {"fresh_full_ax_receipt_ms": (
                slot["sequence"] * 130000.0 + 50000 if is_new else None)}
        document = {"schema_version": 2, "protocol": campaign_v2.protocol("canary"),
                    "slots": rows}
        result = summary_v2.summarize(document)
        self.assertEqual(len(result["pairs"]), 2)
        self.assertEqual({pair["cap_penalized_delta_ms"] for pair in result["pairs"]},
                         {-70000.0})
        self.assertEqual({pair["codex_total_tokens_delta"] for pair in result["pairs"]},
                         {100})
        reversed_document = dict(document)
        reversed_document["slots"] = rows[::-1]
        with self.assertRaises(ValueError):
            summary_v2.summarize(reversed_document)


if __name__ == "__main__":
    unittest.main()
