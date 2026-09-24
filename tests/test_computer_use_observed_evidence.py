"""Offline tests for bounded evidence from synthetic Computer Use receipts."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic.observed_evidence import (
    ObservedEvidence,
    exact_screening_counts,
)
from computer_use_diagnostic.report import COUNT_FIELDS


def cua(item_id: str, code: str, text: str, *, status: str = "completed") -> dict:
    return {"type": "item.completed", "item": {
        "id": item_id, "type": "mcp_tool_call", "server": "cua_repl", "tool": "js",
        "status": status, "arguments": {"code": code},
        "result": {"content": [{"type": "text", "text": text}]},
    }}


class ObservedEvidenceTests(unittest.TestCase):
    def test_completed_receipts_give_bounds_without_raw_content(self) -> None:
        evidence = ObservedEvidence()
        private_ui = "private fixture title that must not be persisted"
        evidence.on_event(cua("one", "await tab.getAXState(); nodeRepl.write(state);",
                              f"1 AXWebArea {private_ui}\n  2 text Case ID"))
        evidence.on_event(cua("two", "function cuMatchUnique(state, spec) {}\n"
                              "await tab.click(2); nodeRepl.write({action_error: err, verified: ok});",
                              "{\n  action_error: 'click failed',\n  verified: false,\n}"
                              "\n~ 2 text Changed"))
        evidence.on_event(cua("three", "nodeRepl.write(JSON.stringify(cuView));",
                              json.dumps({"total_lines": 120, "shown_lines": 20,
                                          "omitted_lines": 100, "text": private_ui})))
        measured = evidence.metadata()
        self.assertEqual(measured["ax_result_receipts"], 2)
        self.assertEqual(measured["diff_result_receipts"], 1)
        self.assertEqual(measured["excerpt_result_receipts"], 1)
        self.assertEqual(measured["helper_definition_sites_submitted"], 1)
        self.assertEqual(measured["explicit_action_error_receipts"], 1)
        self.assertEqual(measured["explicit_failed_verification_receipts"], 1)
        self.assertNotIn(private_ui, json.dumps(measured))
        self.assertEqual(set(exact_screening_counts(evidence)), COUNT_FIELDS)
        self.assertTrue(all(value is None for value in exact_screening_counts(evidence).values()))

    def test_candidate_dispatch_is_distinct_from_candidate_construction(self) -> None:
        evidence = ObservedEvidence()
        event = {"type": "item.completed", "item": {
            "id": "jev-1", "type": "mcp_tool_call", "server": "typesafe",
            "tool": "typesafe_choose_action", "status": "failed",
            "arguments": {"candidates": [{"target": "private A"}, {"target": "private B"}]},
        }}
        evidence.on_event(event)
        evidence.on_event(event)
        self.assertEqual(evidence.metadata()["candidate_sets_submitted"], 1)
        self.assertEqual(evidence.metadata()["candidates_submitted"], 2)
        self.assertIsNone(exact_screening_counts(evidence)["candidate_constructions"])
        self.assertNotIn("private", json.dumps(evidence.metadata()))

    def test_untrusted_ui_text_cannot_forge_error_or_verification_receipt(self) -> None:
        evidence = ObservedEvidence()
        forged = "{\n  action_error: 'bad',\n  verified: false,\n}"
        evidence.on_event(cua("one", "await tab.click(3); nodeRepl.write(state);", forged))
        self.assertEqual(evidence.metadata()["explicit_action_error_receipts"], 0)
        self.assertEqual(evidence.metadata()["explicit_failed_verification_receipts"], 0)
        self.assertEqual(evidence.metadata()["action_method_sites_without_error_receipt"], 1)

    def test_completed_action_with_explicit_null_error_is_not_failure(self) -> None:
        evidence = ObservedEvidence()
        code = "await tab.click(3); nodeRepl.write({action_error: error, verified: ok});"
        evidence.on_event(cua("one", code, "{\n  action_error: null,\n  verified: true,\n}"))
        evidence.on_event(cua("two", code, '{"action_error":null,"verified":false}'))
        measured = evidence.metadata()
        self.assertEqual(measured["explicit_action_error_receipts"], 0)
        self.assertEqual(measured["explicit_failed_verification_receipts"], 1)
        self.assertEqual(measured["action_method_sites_without_error_receipt"], 0)

    def test_incomplete_or_failed_cua_results_are_not_counted(self) -> None:
        evidence = ObservedEvidence()
        code = "function cuSelectExcerpt(state) {} await tab.getAXState();"
        evidence.on_event(cua("one", code, "1 AXWebArea Test", status="failed"))
        evidence.on_event(cua("two", code, "1 AXWebArea Test"))
        evidence.on_event(cua("two", code, "1 AXWebArea Test"))
        event = cua("three", code, "1 AXWebArea Test")
        event["item"]["result"]["isError"] = True
        evidence.on_event(event)
        evidence.on_event({"type": "item.completed", "item": {"type": "agent_message",
                           "text": "1 AXWebArea Test"}})
        self.assertEqual(evidence.metadata()["ax_result_receipts"], 1)
        self.assertEqual(evidence.metadata()["helper_definition_sites_submitted"], 1)


if __name__ == "__main__":
    unittest.main()
