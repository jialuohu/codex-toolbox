"""Historical diagnostic scoring tests with synthetic CUA receipts."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import correction, runner


def _event(code: str, text: str, *, status: str = "completed") -> dict:
    return {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "McpToolCall", "server": "cua_repl", "tool": "js",
        "status": status, "arguments": {"code": code},
        "result": {"content": [{"type": "text", "text": text}]},
    }}}


class CorrectionTests(unittest.TestCase):
    def _audit(self, case_id: str, events: list[dict], *, status: str = "failure") -> dict:
        identity = "01a0d3bb-2015-7941-bc20-c65028cd4a1d"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-2026-09-24T10-04-11-{identity}.jsonl"
            rows = [{"type": "session_meta", "payload": {"id": identity}},
                    *events]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            metric = {
                "case_id": case_id, "sequence": 1, "surface": case_id.split("-", 1)[0],
                "condition": "B_old", "repetition": 1,
                "thread_id_sha256": hashlib.sha256(identity.encode()).hexdigest(),
                "tool_calls": [{"kind": "cua", "start_ms": 100 * n - 50,
                                "end_ms": 100 * n} for n, event in enumerate(events, 1)
                               if event.get("payload", {}).get("type") == "item_completed"],
                "start_ms": 0, "end_ms": 500, "status": status,
                "reset_verified": True, "returncode": 0,
            }
            return correction._audit_trial(metric, path)

    def test_native_diff_uses_verified_reset_identity(self) -> None:
        case_id = "native-duplicate_label-0"
        result = self._audit(case_id, [
            _event("await app.getAXState();", "CU_REPL_PROBE fresh"),
            _event(f"await app.setValue('{case_id}'); await app.click(4); await app.getAXState();",
                   f"\t5 text Case ID: {case_id} Goal: Synthetic task\n"
                   "\t15 text Value: Task incomplete Wrong actions: 0, ID: fixture-result"),
            _event("await app.click(8); await app.getAXState();",
                   f"The following is a diff from the previous accessibility tree.\n"
                   f"~\t15 text Value: PASS {case_id} Wrong actions: 0, ID: fixture-result"),
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ])
        self.assertEqual(result["corrected_status"], "success")
        self.assertTrue(result["ui_verified"])
        self.assertEqual(result["wrong_actions_at_verification"], 0)
        self.assertEqual(result["ui_verified_elapsed_ms"], 300)
        self.assertTrue(result["agent_finalized_after_ui"])
        self.assertNotIn("Synthetic task", json.dumps(result))

    def test_browser_excerpt_without_parent_remains_bound_to_reset(self) -> None:
        case_id = "browser-long_tree-0"
        observer = runner.TrialObserver(case_id)
        observer.on_event({"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "cua_repl", "tool": "js",
            "status": "completed", "arguments": {"code": "await tab.reload(); await tab.getAXState();"},
            "result": {"content": [{"type": "text", "text":
                f"CU_REPL_PROBE fresh\n{{\"excerpt\":\"L6: \\t5 text Case ID: {case_id}\\n"
                "L22: \\t23 container Task result\\nL23: \\t\\t24 text Task incomplete\\n"
                "L24: \\t\\t25 text Wrong actions: 0\"}"}]}}}, 100)
        self.assertTrue(observer.reset_verified)
        result = {"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "cua_repl", "tool": "js",
            "status": "completed", "arguments": {"code": "await tab.click(10); await tab.getAXState();"},
            "result": {"content": [{"type": "text", "text":
                f"\t5 text Case ID: {case_id}\n\t26 text PASS {case_id}\n"
                "\t27 text Wrong actions: 0"}]}}}
        observer.on_event(result, 200)
        self.assertTrue(observer.marker_verified)
        self.assertEqual(observer.wrong_actions, 0)

    def test_timeout_diff_marker_is_reported_without_inventing_counter(self) -> None:
        case_id = "browser-long_tree-0"
        result = self._audit(case_id, [
            _event("await tab.reload(); await tab.getAXState();",
                   f"CU_REPL_PROBE fresh\n\t5 text Case ID: {case_id}\n"
                   "\t23 container Task result\n\t\t24 text Task incomplete\n"
                   "\t\t25 text Wrong actions: 0"),
            _event("await tab.click(8); await tab.getAXState();",
                   f"The following is a diff from the previous accessibility tree.\n"
                   f"~\t\t26 text PASS {case_id}"),
        ], status="timeout")
        self.assertEqual(result["corrected_status"], "timeout")
        self.assertTrue(result["ui_pass_observed"])
        self.assertFalse(result["ui_verified"])
        self.assertIsNone(result["wrong_actions_at_verification"])
        self.assertFalse(result["agent_finalized"])

    def test_code_echo_wrong_case_and_failed_verification_do_not_complete(self) -> None:
        case_id = "browser-duplicate_label-0"
        observer = runner.TrialObserver(case_id)
        reset = {"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "cua_repl", "tool": "js",
            "status": "completed", "arguments": {"code": "await tab.reload(); await tab.getAXState();"},
            "result": {"content": [{"type": "text", "text":
                f"CU_REPL_PROBE fresh\n\t5 text Case ID: {case_id}\n"
                "\t23 container Task result\n\t\t24 text Task incomplete\n"
                "\t\t25 text Wrong actions: 0"}]}}}
        observer.on_event(reset, 100)
        self.assertTrue(observer.reset_verified)
        for text, code in (
            (f"'\\t24 text PASS {case_id}\\n' + '\\t25 text Wrong actions: 0\\n'",
             "await tab.getAXState();"),
            (f"\t24 text PASS {case_id}\n\t25 text Wrong actions: 0",
             "nodeRepl.write('controller verified');"),
            ("\t24 text PASS browser-tabs-0\n\t25 text Wrong actions: 0",
             "await tab.getAXState();"),
        ):
            event = json.loads(json.dumps(reset))
            event["item"]["arguments"]["code"] = code
            event["item"]["result"]["content"][0]["text"] = text
            observer.on_event(event, 200)
            self.assertFalse(observer.marker_verified)
        failed = json.loads(json.dumps(reset))
        failed["item"]["arguments"]["code"] = "await tab.click(8); await tab.getAXState();"
        failed["item"]["result"]["content"][0]["text"] = (
            f"\t24 text PASS {case_id}\n\t25 text Wrong actions: 0\n{{\"verified\":false}}")
        observer.on_event(failed, 300)
        self.assertFalse(observer.marker_verified)
        self.assertEqual(observer.verification_failures, 1)

    def test_frozen_artifact_hashes_reject_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            path.write_text("{}")
            path.with_name(path.name + ".pins.json").write_text("{}")
            path.with_name(path.name + ".metrics.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "input hashes changed"):
                correction.build_correction(path, Path(directory))

    def test_local_frozen_72_replay_when_available(self) -> None:
        base = Path("/private/tmp/codex-toolbox-cu-prep-diagnostic")
        results = base / "full72-py312-20260924.json"
        sessions = Path.home() / ".codex/sessions/2026/09/24"
        if not results.is_file() or not sessions.is_dir():
            self.skipTest("historical local trial artifacts are unavailable")
        audited = correction.build_correction(results, sessions)
        self.assertEqual(audited["summary"]["corrected_statuses"],
                         {"success": 48, "timeout": 24})
        self.assertEqual(len(audited["summary"]["corrected_false_failure_sequences"]), 15)
        self.assertEqual(audited["summary"]["timeouts_with_observed_pass_sequences"],
                         [38, 41, 47])
        self.assertEqual(audited["summary"]["timeouts_with_verified_ui"], 1)
        self.assertNotIn("Synthetic records", json.dumps(audited))


if __name__ == "__main__":
    unittest.main()
