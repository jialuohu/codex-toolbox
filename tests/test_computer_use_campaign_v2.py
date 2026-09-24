"""Offline v2 campaign pins, fair prompts, and serial cleanup gates."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import (
    campaign_v2,
    report,
    runner,
    tab_lease,
    timeout_cleanup,
)

THREAD = "01a0d41c-0c36-7293-ac9a-c0df74912eee"


def cua_event(code: str, text: str) -> dict:
    return {"type": "item.completed", "item": {"type": "mcp_tool_call",
            "server": "cua_repl", "tool": "js", "status": "completed",
            "arguments": {"code": code}, "result": {"content": [{"type": "text", "text": text}]}}}


class CampaignV2Tests(unittest.TestCase):
    def test_canary_has_one_repetition_of_each_case_condition(self) -> None:
        canary = campaign_v2.schedule("canary")
        comparison = campaign_v2.schedule("comparison")
        self.assertEqual((len(canary), len(comparison)), (24, 72))
        self.assertEqual([slot["sequence"] for slot in canary], list(range(1, 25)))
        self.assertEqual({slot["repetition"] for slot in canary}, {1})
        self.assertEqual({(slot["case_id"], slot["condition"]) for slot in canary},
                         {(case, condition) for case in report.CASE_SURFACE
                          for condition in report.CONDITIONS})

    def test_treatment_prompt_reads_frozen_code_inside_measured_preparation(self) -> None:
        pinned = campaign_v2.protocol("canary")
        slot = campaign_v2.schedule("canary")[0]
        prompt = campaign_v2.trial_prompt(slot, "a" * 32, pinned)
        self.assertIn(tab_lease.create_script(tab_lease.trial_url(slot["case_id"], "a" * 32)), prompt)
        self.assertIn(tab_lease.owner_script(tab_lease.trial_url(slot["case_id"], "a" * 32)), prompt)
        self.assertIn(tab_lease.close_script(), prompt)
        self.assertIn("inspect the fresh accessibility state and decide whether a safe "
                      "task-specific controller manifest can be built before installing", prompt)
        self.assertIn("The manifest may contain only observed role/label/context and "
                      "actions authorized by the displayed goal", prompt)
        self.assertIn("Do not create a controller transition for a flat repeated control", prompt)
        self.assertIn("Hand off unless the fresh accessibility state shows a structural row/container", prompt)
        self.assertIn("independently identifying exact AX ID/label", prompt)
        self.assertIn("record name and adjacent metadata alone are insufficient", prompt)
        self.assertIn("If a safe manifest can be built, include scope, initial, verification, "
                      "stages, and per-transition preconditions and expected results; then "
                      "install the exact controller source once", prompt)
        self.assertIn("If a safe manifest cannot be built from the visible UI, do not "
                      "install the controller; hand off", prompt)
        self.assertIn("For an unbound flat repeated control, a fresh screenshot may "
                      "establish a unique visual row; act once only if it does", prompt)
        self.assertIn("After ordinary fallback appears complete, make a separate CUA "
                      "call containing only `await cuFixtureTab.getAXState({disableDiffing:true});`; "
                      "require PASS for the exact case and Wrong actions: 0", prompt)
        self.assertNotIn("For flat rows with repeated controls, include both", prompt)
        self.assertIn("var cuController", prompt)
        self.assertIn("Do not search for or read SKILL.md", prompt)
        self.assertIn("Send at most 15 reviewed candidates", prompt)
        self.assertIn("reviewedOptions.map(([id,target,intended_result])=>({"
                      "id,target,operation:\"click\",arguments:\"none\","
                      "preconditions:\"Visible and enabled in this observation\","
                      "intended_result}))", prompt)
        self.assertIn("Each candidate has exactly six strings: id, target, operation, "
                      "arguments, preconditions, intended_result", prompt)
        self.assertIn("otherwise write explicit objects", prompt)
        self.assertIn("status/privacy gates, task_scope_id, fresh per-observation "
                      "snapshot_id, surface, objective, observation, classification, "
                      "invocation, 2.5-second deadline, duplicate protection, and no retry", prompt)
        self.assertIn("Immediately after verified close", prompt)
        self.assertIn("finish with one line: `verified browser-duplicate_label-0` only "
                      "for independent full-AX exact PASS and Wrong actions: 0; "
                      "otherwise `unverified browser-duplicate_label-0`", prompt)
        self.assertNotIn("__CASE_ID__", prompt)
        self.assertNotIn("Open the Research queue", prompt)
        self.assertLess(len(prompt.encode()), 23_000)
        self.assertIn("controller_compact", pinned["source_sha256"])
        self.assertIn("controller_readable", pinned["source_sha256"])
        self.assertEqual(pinned["protocol_revision"], "v2.3-compact-candidates-finalization")
        disabled = next(item for item in campaign_v2.schedule("canary")
                        if item["condition"] == "B_new")
        disabled_prompt = campaign_v2.trial_prompt(disabled, "c" * 32, pinned)
        self.assertIn("Jev is disabled. Do not call typesafe_choose_action", disabled_prompt)
        self.assertNotIn("Jev enabled: use typesafe_choose_action", disabled_prompt)
        self.assertIn("finish with one line: `verified browser-duplicate_label-0`", disabled_prompt)
        old = next(item for item in campaign_v2.schedule("canary")
                   if item["condition"] == "B_old")
        baseline = campaign_v2.trial_prompt(old, "b" * 32, pinned)
        self.assertIn("installed TypeSafe 0.4.0", baseline)
        self.assertNotIn("var cuController", baseline)
        self.assertIn("Do not search for or read SKILL.md", baseline)
        native = next(item for item in campaign_v2.schedule("canary")
                      if item["case_id"] == "native-long_tree-0"
                      and item["condition"] == "C_new")
        native_prompt = campaign_v2.trial_prompt(native, "d" * 32, pinned)
        self.assertIn("finish with one line: `verified native-long_tree-0`", native_prompt)
        self.assertIn("For native trials, do not close any app", native_prompt)

    def _single_run(self, *, include_close: bool, quiescent: bool = True,
                    recovery: timeout_cleanup.RecoveryResult | None = None,
                    missing_independent_verification: bool = False):
        slot = campaign_v2.schedule("canary")[0]
        recorded = []

        def capture(_command, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start):
            self.assertEqual(timeout_ms, 120000)
            self.assertEqual(cwd, ROOT)
            prompt = prepare_stdin()
            nonce_match = re.search(r"trial=([0-9a-f]{32})", prompt)
            if nonce_match is None:
                raise AssertionError("trial nonce missing from prompt")
            nonce = nonce_match.group(1)
            lease_url = tab_lease.trial_url(slot["case_id"], nonce)
            on_process_start(123)
            if recovery is not None:
                on_event({"type": "thread.started", "thread_id": THREAD}, 15)
            events = [
                (tab_lease.create_script(lease_url), "0 AXWebArea Computer Use Browser Fixture", 20),
                (tab_lease.owner_script(lease_url),
                 "CU_REPL_PROBE fresh\nCU_TAB_OWNER " + json.dumps({"id": "tab-42",
                 "url": lease_url, "browserId": "1", "present": True,
                 "existingFixtureCount": 60}), 30),
                ("await cuFixtureTab.reload(); await cuFixtureTab.getAXState();",
                 (f"0 AXWebArea Computer Use Browser Fixture\n\t1 text Case ID: {slot['case_id']}\n"
                  "\t2 container Task result\n\t\t3 text Task incomplete\n"
                  "\t\t4 text Wrong actions: 0"), 40),
                ("await cuFixtureTab.click(12); await cuFixtureTab.getAXState({disableDiffing:true});",
                 (f"0 AXWebArea Computer Use Browser Fixture\n\t1 text Case ID: {slot['case_id']}\n"
                  "\t22 container Task result\n"
                  f"\t\t23 text PASS {slot['case_id']}\n\t\t24 text Wrong actions: 0"), 60),
                ("await cuFixtureTab.getAXState({disableDiffing:true});",
                 (f"0 AXWebArea Computer Use Browser Fixture\n\t1 text Case ID: {slot['case_id']}\n"
                  "\t22 container Task result\n"
                  f"\t\t23 text PASS {slot['case_id']}\n\t\t24 text Wrong actions: 0"), 70),
            ]
            if missing_independent_verification:
                events.pop()
            if include_close:
                events.append((tab_lease.close_script(),
                               'CU_TAB_CLOSED {"id":"tab-42","absent":true}', 80))
            for code, output, ms in events:
                on_event(cua_event(code, output), ms)
            return SimpleNamespace(start_ms=10, process_exited_ms=90,
                                   process_group_quiescent=quiescent,
                                   thread_id_sha256=sha256(THREAD.encode()).hexdigest())

        class Attempt:
            wrong_actions = 0
            status = "success"
            ui_verified_ms = None if missing_independent_verification else 70
            def to_metadata(self):
                return {"controller_terminated_ms": 90, "status": "success"}

        recovery_patch = (patch.object(timeout_cleanup, "recover", return_value=recovery)
                          if recovery is not None else nullcontext())
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(campaign_v2, "schedule", return_value=[slot]), \
             patch.object(runner, "validate_preflight"), \
             patch.object(runner, "isolated_config_args", return_value=[]), \
             patch.object(runner, "_attempt", return_value=Attempt()), recovery_patch:
            path = Path(temp) / "v2.json"
            try:
                result = campaign_v2.run(
                    mode="canary", results_path=path, limit=1,
                    preflight={"browser_session_mapping_verified": True}, capture=capture,
                )
                recorded.append(result)
            except campaign_v2.V2Stopped as error:
                recorded.append(str(error))
            stored = json.loads(path.read_text())
            self.assertEqual(len(stored["slots"]), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("tab-42", path.read_text())
            return recorded[0], stored

    def test_same_task_close_is_required_before_next_slot(self) -> None:
        result, stored = self._single_run(include_close=True)
        self.assertIsInstance(result, dict)
        self.assertTrue(stored["slots"][0]["cleanup"]["close_verified"])
        stopped, stored = self._single_run(include_close=False)
        self.assertIn("cleanup was not verified", stopped)
        self.assertFalse(stored["slots"][0]["cleanup"]["close_verified"])
        stopped, _ = self._single_run(include_close=True, quiescent=False)
        self.assertIn("not quiescent", stopped)

    def test_stopped_trial_can_recover_only_exact_owned_tab(self) -> None:
        recovered = timeout_cleanup.RecoveryResult(True, True, 1200, 1290, 2, None)
        result, stored = self._single_run(include_close=False, recovery=recovered)
        self.assertIsInstance(result, dict)
        cleanup = stored["slots"][0]["cleanup"]
        self.assertTrue(cleanup["close_verified"])
        self.assertEqual(cleanup["close_phase"], "same_thread_resume")
        self.assertEqual(cleanup["recovery_tool_calls"], 2)

        failed = timeout_cleanup.RecoveryResult(True, False, 1200, 1290, 1,
                                                "recovery_receipt_unverified")
        stopped, stored = self._single_run(include_close=False, recovery=failed)
        self.assertIn("cleanup was not verified", stopped)
        self.assertFalse(stored["slots"][0]["cleanup"]["close_verified"])

    def test_success_claim_with_two_missing_verification_timestamps_stops(self) -> None:
        stopped, stored = self._single_run(
            include_close=True, missing_independent_verification=True,
        )
        self.assertIn("independent fresh full AX verification was not captured", stopped)
        self.assertIsNone(stored["slots"][0]["verification"]["fresh_full_ax_receipt_ms"])


if __name__ == "__main__":
    unittest.main()
