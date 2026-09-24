"""Offline tests for pinned computer-use trial preparation and ordering."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import native_ipc, report, runner, stream_capture


def valid_preflight() -> dict[str, bool]:
    return {
        "browser_cua_approved": True,
        "native_cua_approved": True,
        "browser_reset_verified": True,
        "native_reset_verified": True,
        "fresh_codex_contexts": True,
        "fresh_cua_repl_probe": True,
        "monotonic_span": True,
        "tool_timing_attributable": True,
        "six_token_counters": True,
        "jev_available": True,
        "fixture_sources_pinned": True,
        "browser_session_mapping_verified": True,
    }


def cua_event(text: str, *, code: str = "await cuFixtureTab.getAXState();",
              status: str = "completed") -> dict:
    return {"type": "item.completed", "item": {"type": "mcp_tool_call",
            "server": "cua_repl", "tool": "js", "status": status,
            "arguments": {"code": code, "title": "Synthetic fixture"},
            "result": {"content": [{"type": "text", "text": text}]}}}


def browser_reset_event() -> dict:
    return cua_event("\t5 text Case ID: browser-duplicate_label-0\n\t23 container Task result\n"
                     "\t\t24 text Task incomplete\n\t\t25 text Wrong actions: 0",
                     code="await cuFixtureTab.reload(); await cuFixtureTab.getAXState();")


def browser_pass_event(case_id: str = "browser-duplicate_label-0", wrong: int = 0) -> dict:
    return cua_event(f"Case ID: {case_id}\n\t23 container Task result\n"
                     f"\t\t24 text PASS {case_id}\n\t\t25 text Wrong actions: {wrong}",
                     code="await cuFixtureTab.click(12); await cuFixtureTab.getAXState();")


def fake_result(sequence: int, *, timed_out: bool = False, returncode: int = 0):
    base = sequence * 130000.0
    return SimpleNamespace(
        start_ms=base, end_ms=base + (120000 if timed_out else 500),
        timed_out=timed_out, returncode=returncode,
        thread_id_sha256=hashlib.sha256(f"thread-{sequence}".encode()).hexdigest(),
        tool_calls=[{"kind": "cua", "start_ms": base + 100,
                     "end_ms": base + 200, "code_bytes": 10, "output_bytes": 20}],
        codex_usage={"source": "codex_turn_token_usage_record"}, usage_isolated=True,
        timing_basis="jsonl_stream_receipt", runtime_tool_durations_ms=[100],
        runtime_durations_covered=True, timing_complete=True,
        event_count=5, stderr_bytes=0, error_kind=None, warnings=[],
    )


def scheduled_capture(slots: list[dict], visited: list[int]):
    """Emit metadata-only synthetic receipts for an exact schedule slice."""
    pending = iter(slots)

    def capture(argv, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start):
        slot = next(pending)
        sequence, case_id = slot["sequence"], slot["case_id"]
        visited.append(sequence)
        prepare_stdin()
        on_process_start(1000 + sequence)
        base = sequence * 130000.0
        if slot["surface"] == "native":
            on_event(cua_event("0 standard window Computer Use Native Fixture",
                               code="var cuFixtureApp = await cua.getApp('ai.typesafe.codex.JevCUFixture');"),
                     base + 150)
        on_event(cua_event("CU_REPL_PROBE fresh"), base + 200)
        if slot["surface"] == "browser":
            on_event(cua_event(f"\t5 text Case ID: {case_id}\n\t23 container Task result\n"
                               "\t\t24 text Task incomplete\n\t\t25 text Wrong actions: 0",
                               code="await cuFixtureTab.reload(); await cuFixtureTab.getAXState();"),
                     base + 300)
            on_event(browser_pass_event(case_id), base + 400)
        else:
            on_event(cua_event(
                f"\t5 text Case ID: {case_id} Goal: Synthetic task\n"
                "\t15 text Value: Task incomplete Wrong actions: 0, ID: fixture-result",
                code=f"await cuFixtureApp.setValue('{case_id}'); await cuFixtureApp.click(4); await cuFixtureApp.getAXState();",
            ), base + 300)
            on_event(cua_event(
                f"Case ID: {case_id}\n15 text Value: PASS {case_id} Wrong actions: 0, ID: fixture-result",
                code="await cuFixtureApp.click(11); await cuFixtureApp.getAXState();",
            ), base + 400)
        return fake_result(sequence)

    return capture


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime_dir = tempfile.TemporaryDirectory()
        self.addCleanup(runtime_dir.cleanup)
        cua_manifest = Path(runtime_dir.name) / "cua.json"
        typesafe_manifest = Path(runtime_dir.name) / "typesafe.json"
        cua_manifest.write_text(json.dumps({"mcpServers": {"cua_repl": {
            "command": "/fixture/cua", "args": ["run"], "env": {"CUA_TEST": "fixture"},
        }}}))
        typesafe_manifest.write_text(json.dumps({"mcpServers": {"typesafe": {
            "command": "uv", "args": ["run", "typesafe-mcp"], "cwd": ".",
            "env_vars": ["CODEX_HOME", "CODEX_SECRETS_DIR"],
        }}}))
        for name, value in (("CUA_MCP_MANIFEST", cua_manifest),
                            ("TYPESAFE_MCP_MANIFEST", typesafe_manifest)):
            patcher = patch.object(runner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime_patch = patch.object(runner, "pinned_runtime", return_value=runner.RUNTIME_SHA256)
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)

    def test_pins_schedule_prompts_recipes_and_all_six_case_eligibility(self) -> None:
        protocol = runner.pinned_protocol()
        self.assertEqual(report.prepare_schedule()["schedule_sha256"], runner.SCHEDULE_SHA256)
        self.assertEqual(protocol["model"], "gpt-6-astra")
        self.assertEqual(protocol["reasoning"], "medium")
        self.assertEqual(protocol["prompt_sha256"], runner.PROMPT_SHA256)
        self.assertEqual(protocol["recipe_sha256"], runner.RECIPE_SHA256)
        self.assertEqual(set(protocol["jev_eligibility"].values()), {True})
        self.assertEqual(set(protocol["jev_eligibility"]), set(report.CASE_SURFACE))
        self.assertEqual(protocol["timeout_ms"], 120000)
        self.assertEqual(protocol["reset_rules"], runner.RESET_RULES)
        self.assertIn("/private/tmp/codex-toolbox-cu-prep-diagnostic/JevCUFixture.app",
                      runner.case_prompt("native-duplicate_label-0"))
        self.assertIn("cua.createBrowserTab('1', '<case URL from prompt>')",
                      runner.COMMON_RECIPE_PREFIX)
        self.assertIn("cua.getApp('ai.typesafe.codex.JevCUFixture')",
                      runner.COMMON_RECIPE_PREFIX)
        self.assertNotIn("markHandoff()", runner.COMMON_RECIPE_PREFIX)
        self.assertEqual(runner.pinned_runtime(), runner.RUNTIME_SHA256)
        config = runner.isolated_config_args()
        self.assertIn("features.plugins=false", config)
        self.assertNotIn("mcp_servers.node_repl.enabled=false", config)
        self.assertIn("mcp_servers.cua_repl.enabled=true", config)
        self.assertIn("mcp_servers.typesafe.enabled=true", config)

    def test_source_or_prompt_drift_fails_before_capture(self) -> None:
        broken = dict(runner.SOURCE_SHA256)
        broken["native_fixture"] = "0" * 64
        with patch.object(runner, "SOURCE_SHA256", broken), self.assertRaisesRegex(runner.PinError, "native_fixture"):
            runner.pinned_protocol()
        with (patch.object(runner, "PROMPT_TEMPLATE", runner.PROMPT_TEMPLATE + " changed"),
              self.assertRaisesRegex(runner.PinError, "prompt or recipe")):
            runner.pinned_protocol()

    def test_preflight_false_missing_or_unknown_blocks_execution(self) -> None:
        for altered in (
            {**valid_preflight(), "native_cua_approved": False},
            {key: value for key, value in valid_preflight().items() if key != "monotonic_span"},
            {**valid_preflight(), "raw_ui": "private text"},
        ):
            with self.subTest(altered=altered), self.assertRaises(runner.PreflightError):
                runner.validate_preflight(altered)

    def test_recipes_load_inside_capture_and_slots_are_sequential(self) -> None:
        slots = report.prepare_schedule()["slots"][:4]
        calls = []
        persisted = []
        entered = False

        def capture(argv, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start):
            nonlocal entered
            entered = True
            text = prepare_stdin()
            self.assertTrue(entered)
            self.assertEqual(argv[0:3], ["codex", "exec", "--json"])
            self.assertIn("--approve-for-me", argv)
            self.assertIn("--ignore-user-config", argv)
            self.assertIn("model_reasoning_effort=medium", argv)
            self.assertEqual(cwd, ROOT)
            self.assertEqual(timeout_ms, 120000)
            self.assertIn("CU_REPL_PROBE", text)
            self.assertIn("Task incomplete", text)
            self.assertIn("Wrong actions: 0", text)
            self.assertIn("browser-duplicate_label-0", text)
            condition = next(condition for condition in report.CONDITIONS
                             if ("Jev is disabled" in text) == condition.startswith("B_")
                             and ("cuSelectExcerpt" in text) == condition.endswith("new"))
            calls.append(condition)
            sequence = len(calls)
            base = sequence * 130000.0
            on_event(cua_event("CU_REPL_PROBE fresh"), base + 200)
            on_event(browser_reset_event(), base + 300)
            on_event(browser_pass_event(), base + 400)
            return fake_result(sequence)

        result = runner.run_slots(capture=capture, preflight=valid_preflight(), slots=slots,
                                  on_attempt=lambda attempt: persisted.append(attempt.to_metadata()))
        self.assertEqual(len(result), 4)
        self.assertEqual(calls, [slot["condition"] for slot in slots])
        self.assertEqual([item.status for item in result], ["success"] * 4)
        self.assertEqual([item.end_ms - item.start_ms for item in result], [400] * 4)
        self.assertTrue(all(item.cua_repl_probe_fresh and item.reset_verified for item in result))
        self.assertTrue(all(item.timing_complete for item in result))
        self.assertEqual([row["sequence"] for row in persisted], [1, 2, 3, 4])
        self.assertTrue(all(isinstance(row["observed_evidence"], dict) for row in persisted))
        self.assertNotIn("Task incomplete", json.dumps(persisted))

    def test_native_slot_records_client_ipc_without_claiming_backend_session(self) -> None:
        slot = next(slot for slot in report.prepare_schedule()["slots"]
                    if slot["case_id"] == "native-duplicate_label-0")
        attestation = native_ipc.NativeClientAttestation(
            True, "a" * 64, "b" * 64, "c" * 64, 1234.5, None,
        )

        def capture(argv, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start):
            prepare_stdin()
            on_process_start(123)
            base = 130000.0
            on_event(cua_event("0 standard window Computer Use Native Fixture",
                               code="var cuFixtureApp = await cua.getApp('ai.typesafe.codex.JevCUFixture');"),
                     base + 150)
            on_event(cua_event("CU_REPL_PROBE fresh"), base + 200)
            on_event(cua_event("\t5 text Case ID: native-duplicate_label-0 Goal: Synthetic task\n"
                               "\t15 text Value: Task incomplete Wrong actions: 0, ID: fixture-result",
                               code="await cuFixtureApp.setValue('native-duplicate_label-0'); await cuFixtureApp.click(4); await cuFixtureApp.getAXState();"),
                     base + 300)
            on_event(cua_event("Case ID: native-duplicate_label-0\n15 text Value: PASS native-duplicate_label-0 Wrong actions: 0, ID: fixture-result",
                               code="await cuFixtureApp.click(11); await cuFixtureApp.getAXState();"),
                     base + 400)
            return fake_result(1)

        with (patch.object(report, "prepare_schedule", return_value={"slots": [slot]}),
              patch.object(runner, "pinned_protocol", return_value={}),
              patch.object(runner, "prepared_stdin", return_value="pinned synthetic recipe"),
              patch.object(native_ipc, "attest_native_client", return_value=attestation) as attest):
            attempts = runner.run_slots(capture=capture, preflight=valid_preflight())
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, "success")
        self.assertTrue(attempts[0].native_client_attestation["verified"])
        self.assertFalse(attempts[0].native_client_attestation["backend_session_id_observed"])
        self.assertIsNone(attempts[0].to_report_record()["cua_session_sha256"])
        attest.assert_called_once_with(123, seen_contexts=frozenset())

        unavailable = native_ipc.NativeClientAttestation(
            False, None, None, None, 1234.5, "native_client_socket_ambiguous",
        )
        with (patch.object(report, "prepare_schedule", return_value={"slots": [slot]}),
              patch.object(runner, "pinned_protocol", return_value={}),
              patch.object(runner, "prepared_stdin", return_value="pinned synthetic recipe"),
              patch.object(native_ipc, "attest_native_client", return_value=unavailable),
              self.assertRaisesRegex(runner.CampaignStopped, "client IPC") as failure):
            runner.run_slots(capture=capture, preflight=valid_preflight())
        self.assertEqual(len(failure.exception.attempts), 1)
        self.assertFalse(failure.exception.attempts[0].native_client_attestation["verified"])

    def test_timeout_is_recorded_and_next_slot_still_runs(self) -> None:
        slots = report.prepare_schedule()["slots"][:2]
        calls = 0

        def capture(argv, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start):
            nonlocal calls
            calls += 1
            prepare_stdin()
            base = calls * 130000.0
            on_event(cua_event("CU_REPL_PROBE fresh"), base + 200)
            on_event(browser_reset_event(), base + 300)
            if calls > 1:
                on_event(browser_pass_event(), base + 400)
            return fake_result(calls, timed_out=calls == 1,
                               returncode=-15 if calls == 1 else 0)

        result = runner.run_slots(capture=capture, preflight=valid_preflight(), slots=slots)
        self.assertEqual(len(result), 2)
        self.assertEqual(calls, 2)
        self.assertEqual([item.status for item in result], ["timeout", "success"])

    def test_nonprefix_schedule_is_rejected_and_nonzero_exit_is_retained(self) -> None:
        slots = report.prepare_schedule()["slots"]
        with self.assertRaisesRegex(ValueError, "schedule prefix"):
            runner.run_slots(capture=lambda *args, **kwargs: None,
                             preflight=valid_preflight(), slots=[slots[1]])
        def failed(argv, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start):
            prepare_stdin()
            on_event(cua_event("CU_REPL_PROBE fresh"), 130200)
            on_event(browser_reset_event(), 130300)
            on_event(cua_event("Case ID: browser-duplicate_label-0\nTask incomplete\nWrong actions: 1",
                               code="await cuFixtureTab.click(12); await cuFixtureTab.getAXState();"), 130350)
            return fake_result(1, returncode=1)
        attempts = runner.run_slots(capture=failed, preflight=valid_preflight(), slots=slots[:1])
        self.assertEqual(attempts[0].status, "failure")
        self.assertEqual(attempts[0].returncode, 1)

    def test_unverified_reset_is_retained_but_reused_cua_repl_stops_campaign(self) -> None:
        slots = report.prepare_schedule()["slots"][:2]
        for probe, reset in (("fresh", False), ("reused", True)):
            with self.subTest(probe=probe, reset=reset):
                calls = 0
                def capture(argv, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start,
                            probe=probe, reset=reset):
                    nonlocal calls
                    calls += 1
                    prepare_stdin()
                    base = calls * 130000.0
                    on_event(cua_event("CU_REPL_PROBE " + probe), base + 200)
                    if reset:
                        on_event(browser_reset_event(), base + 300)
                    return fake_result(calls)
                if probe == "reused":
                    with self.assertRaises(runner.CampaignStopped) as failure:
                        runner.run_slots(capture=capture, preflight=valid_preflight(), slots=slots)
                    self.assertEqual(len(failure.exception.attempts), 1)
                else:
                    attempts = runner.run_slots(capture=capture, preflight=valid_preflight(), slots=slots)
                    self.assertEqual(len(attempts), 2)
                    self.assertEqual([item.status for item in attempts], ["failure", "failure"])

    def test_prompt_echo_extra_marker_and_buffered_call_are_not_verified(self) -> None:
        observer = runner.TrialObserver("native-duplicate_label-0")
        observer.on_event({"type": "item.completed", "item": {"type": "agent_message",
                          "text": "CU_REPL_PROBE fresh Case ID: native-duplicate_label-0 Task incomplete Wrong actions: 0"}}, 1)
        self.assertFalse(observer.probe_fresh)
        observer.on_event(cua_event("CU_REPL_PROBE fresh", status="failed"), 1.5)
        self.assertFalse(observer.probe_fresh)
        observer.on_event(cua_event("CU_REPL_PROBE fresh"), 2)
        observer.on_event(cua_event("\t5 text Case ID: native-duplicate_label-0 Goal: Synthetic task\n"
                                    "\t15 text Value: Task incomplete Wrong actions: 0, ID: fixture-result",
                                    code="await app.setValue('native-duplicate_label-0'); await app.click(2); await app.getAXState();"), 3)
        observer.on_event(cua_event("Case ID: native-duplicate_label-0\nPASS native-duplicate_label-0 extra Wrong actions: 0",
                                    code="await app.click(4); await app.getAXState();"), 4)
        self.assertFalse(observer.marker_verified)
        observer.on_event(cua_event("PASS native-long_tree-0 Wrong actions: 0"), 5)
        self.assertFalse(observer.marker_verified)
        observer.on_event(cua_event('Case ID: native-duplicate_label-0\n15 text Value: PASS native-duplicate_label-0 Wrong actions: 0, ID: fixture-result\n{"verified":false}'), 5.5)
        self.assertFalse(observer.marker_verified)
        observer.on_event(cua_event("Case ID: native-duplicate_label-0\n15 text Value: PASS native-duplicate_label-0 Wrong actions: 1, ID: fixture-result"), 6)
        self.assertTrue(observer.marker_verified)
        self.assertEqual(observer.wrong_actions, 1)
        self.assertEqual(observer.verified_ms, 6)
        buffered = fake_result(1)
        buffered.runtime_tool_durations_ms = [5000]
        observer.verified_ms = buffered.start_ms + 400
        self.assertFalse(runner._tool_timing_complete(buffered, observer))
        wrapper = fake_result(2)
        wrapper.tool_calls[0]["kind"] = "jev"
        wrapper.tool_calls[0]["end_ms"] = wrapper.start_ms + 400
        wrapper.runtime_tool_durations_ms = [100]
        self.assertTrue(runner._tool_timing_complete(wrapper,
                         runner.TrialObserver("browser-duplicate_label-0")))
        wrapper.runtime_tool_durations_ms = [1000]
        self.assertFalse(runner._tool_timing_complete(wrapper,
                          runner.TrialObserver("browser-duplicate_label-0")))

    def test_reset_and_pass_in_one_cua_result_do_not_verify_completion(self) -> None:
        observer = runner.TrialObserver("browser-duplicate_label-0")
        observer.on_event(cua_event("CU_REPL_PROBE fresh"), 1)
        observer.on_event(cua_event("\t5 text Case ID: browser-duplicate_label-0\n\t23 container Task result\n"
                                    "\t\t24 text Task incomplete\n\t\t25 text Wrong actions: 0\n"
                                    "\t\t26 text PASS browser-duplicate_label-0\n\t\t27 text Wrong actions: 0",
                                    code="await cuFixtureTab.reload(); await cuFixtureTab.getAXState();"), 2)
        self.assertTrue(observer.reset_verified)
        self.assertFalse(observer.marker_verified)

    def test_action_error_with_side_effect_requires_later_ax_verification(self) -> None:
        observer = runner.TrialObserver("browser-duplicate_label-0")
        observer.on_event(cua_event("CU_REPL_PROBE fresh"), 1)
        observer.on_event(browser_reset_event(), 2)
        observer.on_event(cua_event("action failed after click",
                                    code="await cuFixtureTab.click(12);", status="failed"), 3)
        self.assertFalse(observer.marker_verified)
        self.assertEqual(observer.action_errors, 1)
        later = browser_pass_event()
        later["item"]["arguments"]["code"] = "await cuFixtureTab.getAXState();"
        observer.on_event(later, 4)
        self.assertTrue(observer.marker_verified)
        self.assertEqual(observer.verified_ms, 4)

    def test_browser_marker_counter_must_share_task_result_container(self) -> None:
        case_id = "browser-duplicate_label-0"
        marker = f"PASS {case_id}"
        self.assertIsNone(runner._browser_result_counter(
            f"\t23 container Task result\n\t\t24 text {marker}\n"
            "\t26 container Other\n\t\t27 text Wrong actions: 0", marker))
        self.assertIsNone(runner._browser_result_counter(
            f"result: '\\t23 container Task result\\n' +\n"
            f"  '\\t\\t24 text {marker}\\n' +\n"
            "  '\\t\\t25 text Wrong actions: 0\\n'", marker))

    def test_jev_result_extracts_only_status_and_provider_usage(self) -> None:
        event = {"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "typesafe", "tool": "typesafe_choose_action",
            "status": "completed", "result": {"structuredContent": {
                "ok": True, "status": "evaluated", "abstain": False,
                "candidate_id": "private-opaque-id", "request_id": "private-opaque-id",
                "usage": {"input_tokens": 795, "output_tokens": 60}}}}}
        self.assertEqual(runner._jev_result(event), ("evaluated", 795, 60))
        observer = runner.TrialObserver("browser-duplicate_label-0")
        observer.on_event(event, 1)
        self.assertEqual(observer.jev_results, [("evaluated", 795, 60)])
        event["item"]["result"]["structuredContent"]["abstain"] = True
        self.assertEqual(runner._jev_result(event), ("abstained", 795, 60))
        event["item"]["result"]["structuredContent"]["usage"] = {"input_tokens": True,
                                                               "output_tokens": 60}
        self.assertEqual(runner._jev_result(event), ("abstained", None, None))

        slot = next(row for row in report.prepare_schedule()["slots"]
                    if row["case_id"] == "browser-duplicate_label-0"
                    and row["condition"] == "C_new")
        observer = runner.TrialObserver(slot["case_id"])
        base = slot["sequence"] * 130000.0
        observer.on_event(cua_event("CU_REPL_PROBE fresh"), base + 200)
        observer.on_event(browser_reset_event(), base + 300)
        event["item"]["result"]["structuredContent"]["usage"] = {
            "input_tokens": 795, "output_tokens": 60}
        event["item"]["result"]["structuredContent"]["abstain"] = False
        observer.on_event(event, base + 350)
        observer.on_event(browser_pass_event(), base + 400)
        captured = fake_result(slot["sequence"])
        captured.tool_calls.append({"kind": "jev", "start_ms": base + 250,
                                    "end_ms": base + 350, "code_bytes": 10,
                                    "output_bytes": 20})
        captured.runtime_tool_durations_ms.append(100)
        attempt = runner._attempt(slot, captured, observer,
                                  browser_session_mapping_verified=True)
        jev = attempt.to_report_record()["jev"]
        self.assertEqual((jev["status"], jev["skip_reason"], jev["calls"]),
                         ("evaluated", "", 1))
        self.assertEqual((jev["input_tokens"], jev["output_tokens"]), (795, 60))
        self.assertEqual(report._jev(jev, slot["condition"], True,
                                     attempt.end_ms - attempt.start_ms)["status"], "evaluated")

    def test_unplanned_skill_or_ui_tool_is_detected_from_trace(self) -> None:
        observer = runner.TrialObserver("browser-duplicate_label-0")
        observer.on_event({"type": "item.started", "item": {
            "type": "command_execution", "command": "sed -n '1,30p' /tmp/SKILL.md"}}, 1)
        observer.on_event({"type": "item.started", "item": {
            "type": "mcp_tool_call", "server": "node_repl", "tool": "js"}}, 2)
        self.assertTrue(observer.unplanned_skill_load)
        self.assertTrue(observer.unapproved_ui_tool)

    def test_report_import_retains_quality_and_unknown_measurements(self) -> None:
        slots = report.prepare_schedule()["slots"][:2]
        records = []
        attempts = []
        for index, slot in enumerate(slots, 1):
            base = index * 130000.0
            observer = runner.TrialObserver(slot["case_id"])
            observer.on_event(cua_event("CU_REPL_PROBE fresh"), base + 200)
            observer.on_event(browser_reset_event(), base + 300)
            if index == 1:
                observer.on_event(browser_pass_event(), base + 400)
            capture = fake_result(index, timed_out=index == 2,
                                  returncode=0 if index == 1 else -15)
            attempt = runner._attempt(slot, capture, observer,
                                      browser_session_mapping_verified=True)
            attempts.append(attempt)
            records.append(attempt.to_report_record())
        document = {"schema_version": report.SCHEMA_VERSION,
                    "schedule_sha256": runner.SCHEDULE_SHA256,
                    "protocol": runner.pinned_protocol(), "records": records}
        scored = report.score_results(document)
        self.assertEqual(scored["complete_runs"], 0)
        self.assertEqual(scored["supplied_runs"], 2)
        self.assertEqual(len(scored["incomplete"]), 2)
        quality = scored["cases"]["browser-duplicate_label-0"]["observed_quality"]
        self.assertEqual(sum(item["successes"] for item in quality.values()), 1)
        self.assertEqual(sum(item["timeouts"] for item in quality.values()), 1)
        self.assertEqual(sum(item["unsafe_action_counts_missing"] for item in quality.values()), 2)
        self.assertEqual(scored["screening"], "incomplete")
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            sink = runner.ResultSink(path)
            for attempt in attempts:
                sink.add(attempt)
            imported = report.score_results(report.read_json(path))
            self.assertEqual(imported["supplied_runs"], 2)
            self.assertEqual(report.read_json(sink.pins_path)["runtime_sha256"],
                             runner.RUNTIME_SHA256)
            metrics = report.read_json(sink.metrics_path)
            self.assertEqual([row["sequence"] for row in metrics["records"]], [1, 2])
            self.assertIn("wrapper_overhead_ms", metrics["records"][0])
            self.assertNotIn("Task incomplete", path.read_text())
            self.assertNotIn("SKILL.md", path.read_text())
            self.assertNotIn("Task incomplete", sink.metrics_path.read_text())
            with self.assertRaisesRegex(ValueError, "sequential"):
                sink.add(attempts[0])

    def test_attempt_rejects_raw_tool_payload(self) -> None:
        slot = report.prepare_schedule()["slots"][0]
        observer = runner.TrialObserver(slot["case_id"])
        observer.on_event(cua_event("CU_REPL_PROBE fresh"), 130200)
        observer.on_event(browser_reset_event(), 130300)
        observer.on_event(browser_pass_event(), 130400)
        capture = fake_result(1)
        capture.tool_calls[0]["raw_ui"] = "private page"
        with self.assertRaisesRegex(ValueError, "raw payloads"):
            runner._attempt(slot, capture, observer)

    def test_dry_run_outputs_only_metadata_and_live_cli_is_gated(self) -> None:
        output = io.StringIO()
        with patch.object(sys, "argv", ["runner.py", "--dry-run"]), contextlib.redirect_stdout(output):
            runner.main()
        data = json.loads(output.getvalue())
        self.assertEqual(len(data["slots"]), 72)
        self.assertEqual(data["protocol"]["recipe_sha256"], runner.RECIPE_SHA256)
        self.assertNotIn("CU_REPL_PROBE", output.getvalue())
        self.assertNotIn("http://127.0.0.1", output.getvalue())
        self.assertNotIn("For this synthetic", output.getvalue())
        with (patch.object(sys, "argv", ["runner.py"]),
              contextlib.redirect_stderr(io.StringIO()),
              self.assertRaises(SystemExit) as error):
            runner.main()
        self.assertEqual(error.exception.code, 2)

    def test_execute_adapter_persists_browser_prefix_and_gates_native(self) -> None:
        def capture(argv, *, prepare_stdin, timeout_ms, cwd, on_event, on_process_start):
            prepare_stdin()
            on_event(cua_event("CU_REPL_PROBE fresh"), 130200)
            on_event(browser_reset_event(), 130300)
            on_event(browser_pass_event(), 130400)
            return fake_result(1)

        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            attempts = runner.execute_campaign(preflight=valid_preflight(),
                                               results_path=path, limit=1, capture=capture)
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0].status, "success")
            self.assertEqual(report.score_results(report.read_json(path))["supplied_runs"], 1)
            with self.assertRaisesRegex(runner.PreflightError, "native backend"):
                runner.execute_campaign(preflight=valid_preflight(),
                                        results_path=Path(dirname) / "native.json",
                                        limit=49, capture=capture)
            self.assertFalse((Path(dirname) / "native.json").exists())

    def test_exploratory_mode_records_native_without_claiming_complete_screen(self) -> None:
        slots = report.prepare_schedule()["slots"]
        visited: list[int] = []

        def attest(pid, *, seen_contexts):
            context = hashlib.sha256(f"native-{pid}".encode()).hexdigest()
            self.assertNotIn(context, seen_contexts)
            return native_ipc.NativeClientAttestation(
                True, context, "b" * 64, "c" * 64, 1234.5, None,
            )

        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            with (patch.object(runner.native_lifecycle, "reset_native"),
                  patch.object(native_ipc, "attest_native_client", side_effect=attest)):
                attempts = runner.execute_exploratory_campaign(
                    preflight=valid_preflight(), results_path=path, limit=49,
                    capture=scheduled_capture(slots[:49], visited),
                )
            self.assertEqual(visited, list(range(1, 50)))
            self.assertEqual(len(attempts), 49)
            self.assertEqual(attempts[-1].surface, "native")
            self.assertTrue(attempts[-1].native_client_attestation["verified"])
            document = report.read_json(path)
            native = document["records"][-1]
            self.assertIsNone(native["cua_session_sha256"])
            self.assertTrue(all(value is None for value in native["counts"].values()))
            self.assertIsNone(native["outcome"]["unsafe_actions"])
            scored = report.score_results(document)
            self.assertEqual(scored["supplied_runs"], 49)
            self.assertEqual(scored["complete_runs"], 0)
            self.assertEqual(scored["screening"], "incomplete")
            for metadata_path in (path, path.with_name(path.name + ".pins.json"),
                                  path.with_name(path.name + ".metrics.json"),
                                  path.with_name(path.name + ".campaign.lock")):
                self.assertEqual(metadata_path.stat().st_mode & 0o777, 0o600)

    def test_exploratory_resume_skips_validated_prefix(self) -> None:
        slots = report.prepare_schedule()["slots"]
        visited: list[int] = []
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            runner.execute_exploratory_campaign(
                preflight=valid_preflight(), results_path=path, limit=2,
                capture=scheduled_capture(slots[:2], visited),
            )
            later = runner.execute_exploratory_campaign(
                preflight=valid_preflight(), results_path=path, limit=4,
                capture=scheduled_capture(slots[2:4], visited), resume=True,
            )
            self.assertEqual(visited, [1, 2, 3, 4])
            self.assertEqual([item.sequence for item in later], [3, 4])
            self.assertEqual([item["sequence"] for item in report.read_json(path)["records"]],
                             [1, 2, 3, 4])
            no_more = runner.execute_exploratory_campaign(
                preflight=valid_preflight(), results_path=path, limit=4,
                capture=lambda *args, **kwargs: self.fail("already completed slot reran"),
                resume=True,
            )
            self.assertEqual(no_more, [])

    def test_exploratory_resume_rejects_drift_tampering_and_weak_permissions(self) -> None:
        slots = report.prepare_schedule()["slots"]
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            runner.execute_exploratory_campaign(
                preflight=valid_preflight(), results_path=path, limit=1,
                capture=scheduled_capture(slots[:1], []),
            )
            pins_path = path.with_name(path.name + ".pins.json")
            metrics_path = path.with_name(path.name + ".metrics.json")

            def reject() -> None:
                with self.assertRaises(ValueError):
                    runner.execute_exploratory_campaign(
                        preflight=valid_preflight(), results_path=path, limit=2,
                        capture=lambda *args, **kwargs: self.fail("unvalidated resume ran"),
                        resume=True,
                    )

            original_pins = pins_path.read_bytes()
            pins = report.read_json(pins_path)
            pins["runtime_sha256"]["browser_service"] = "0" * 64
            pins_path.write_text(json.dumps(pins))
            reject()
            pins_path.write_bytes(original_pins)

            original_metrics = metrics_path.read_bytes()
            metrics = report.read_json(metrics_path)
            metrics["records"][0]["sequence"] = 2
            metrics_path.write_text(json.dumps(metrics))
            reject()
            metrics_path.write_bytes(original_metrics)

            metrics = report.read_json(metrics_path)
            metrics["records"][0]["warnings"] = ["private fixture text"]
            metrics_path.write_text(json.dumps(metrics))
            reject()
            metrics_path.write_bytes(original_metrics)

            metrics = report.read_json(metrics_path)
            metrics["records"] = []
            metrics_path.write_text(json.dumps(metrics))
            reject()
            metrics_path.write_bytes(original_metrics)

            os.chmod(path, 0o644)
            reject()
            os.chmod(path, 0o600)

            original_results = path.read_bytes()
            document = report.read_json(path)
            document["records"][0]["sequence"] = 2
            path.write_text(json.dumps(document))
            reject()
            path.write_bytes(original_results)
            self.assertEqual(len(runner.ResultSink.resume(path).records), 1)

    def test_campaign_lock_and_resume_flag_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            def competing_writer() -> None:
                with runner._campaign_lock(path):
                    self.fail("concurrent campaign writer acquired lock")
            with runner._campaign_lock(path), self.assertRaisesRegex(ValueError, "already being written"):
                competing_writer()
            with self.assertRaisesRegex(ValueError, "missing"):
                runner.ResultSink.resume(path)
        with (patch.object(sys, "argv", ["runner.py", "--execute", "--resume",
                                             "--preflight", "flags.json", "--results", "results.json"]),
              contextlib.redirect_stderr(io.StringIO()),
              self.assertRaises(SystemExit) as error):
            runner.main()
        self.assertEqual(error.exception.code, 2)

    def test_resume_waits_for_older_writer_with_same_results_path(self) -> None:
        slots = report.prepare_schedule()["slots"]
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            runner.execute_exploratory_campaign(
                preflight=valid_preflight(), results_path=path, limit=1,
                capture=scheduled_capture(slots[:1], []),
            )
            other_pid = os.getpid() + 10000
            process_rows = (
                f"{other_pid} /Applications/Python.app/Contents/MacOS/Python "
                f"-m computer_use_diagnostic.runner --execute --results {path} --limit 12\n"
            )
            inventory = subprocess.CompletedProcess(
                args=["ps"], returncode=0, stdout=process_rows, stderr="",
            )
            pinned = runner.pinned_protocol()
            with (patch.object(runner, "pinned_protocol", return_value=pinned),
                  patch.object(runner.subprocess, "run", return_value=inventory),
                  self.assertRaisesRegex(ValueError, "still active")):
                runner.execute_exploratory_campaign(
                    preflight=valid_preflight(), results_path=path, limit=2,
                    capture=lambda *args, **kwargs: self.fail("active writer was ignored"),
                    resume=True,
                )
            self.assertEqual(len(report.read_json(path)["records"]), 1)

    def test_live_exploratory_clock_probe_rejects_process_relative_time(self) -> None:
        relative = subprocess.CompletedProcess(
            args=["python"], returncode=0, stdout="50000000\n", stderr="",
        )
        with (patch.object(runner.time, "monotonic_ns",
                           side_effect=[300_000_000, 300_000_000, 400_000_000]),
              patch.object(runner.subprocess, "run", return_value=relative),
              self.assertRaisesRegex(runner.PreflightError, "shared monotonic")):
            runner._require_shared_monotonic_clock()
        shared = subprocess.CompletedProcess(
            args=["python"], returncode=0, stdout="1000050000000\n", stderr="",
        )
        with (patch.object(runner.time, "monotonic_ns",
                           side_effect=[1_000_000_000_000, 1_000_000_000_000,
                                        1_000_100_000_000]),
              patch.object(runner.subprocess, "run", return_value=shared)):
            self.assertEqual(runner._require_shared_monotonic_clock(), 1_000_100.0)

    def test_live_exploratory_clock_guard_precedes_new_or_resumed_action(self) -> None:
        slots = report.prepare_schedule()["slots"]
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            with (patch.object(runner, "_require_shared_monotonic_clock",
                               side_effect=runner.PreflightError("clock unavailable")),
                  self.assertRaisesRegex(runner.PreflightError, "clock unavailable")):
                runner.execute_exploratory_campaign(
                    preflight=valid_preflight(), results_path=path, limit=1,
                    capture=stream_capture.capture_command,
                )
            self.assertFalse(path.exists())
            runner.execute_exploratory_campaign(
                preflight=valid_preflight(), results_path=path, limit=1,
                capture=scheduled_capture(slots[:1], []),
            )
            with (patch.object(runner, "_require_shared_monotonic_clock",
                               return_value=1_000_000.0),
                  self.assertRaisesRegex(ValueError, "pins changed")):
                runner.execute_exploratory_campaign(
                    preflight=valid_preflight(), results_path=path, limit=2,
                    capture=stream_capture.capture_command, resume=True,
                )
            pins_path = path.with_name(path.name + ".pins.json")
            pins = report.read_json(pins_path)
            pins["clock_basis"] = runner.CLOCK_BASIS
            runner.ResultSink._write_atomic(pins_path, pins)
            with (patch.object(runner, "_require_shared_monotonic_clock",
                               return_value=1.0),
                  self.assertRaisesRegex(runner.PreflightError, "precedes")):
                runner.execute_exploratory_campaign(
                    preflight=valid_preflight(), results_path=path, limit=2,
                    capture=stream_capture.capture_command, resume=True,
                )
            self.assertEqual(len(report.read_json(path)["records"]), 1)

    def test_live_exploratory_new_run_pins_shared_clock_basis(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "results.json"
            with (patch.object(runner, "_require_shared_monotonic_clock",
                               return_value=1_000_000.0),
                  patch.object(runner, "run_slots", return_value=[])):
                runner.execute_exploratory_campaign(
                    preflight=valid_preflight(), results_path=path, limit=1,
                    capture=stream_capture.capture_command,
                )
            pins = report.read_json(path.with_name(path.name + ".pins.json"))
            self.assertEqual(pins["clock_basis"], runner.CLOCK_BASIS)


class RuntimePinTests(unittest.TestCase):
    def test_runtime_hash_drift_blocks_live_trials(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            paths = {name: Path(dirname) / name for name in runner.RUNTIME_SHA256}
            for path in paths.values():
                path.write_bytes(b"pinned synthetic runtime")
            hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for name, path in paths.items()}
            with (patch.object(runner, "BROWSER_RUNTIME", paths["browser_service"]),
                  patch.object(runner, "CUA_MCP_MANIFEST", paths["cua_mcp_manifest"]),
                  patch.object(runner, "TYPESAFE_MCP_MANIFEST", paths["typesafe_mcp_manifest"]),
                  patch.object(runner, "RUNTIME_SHA256", hashes)):
                self.assertEqual(runner.pinned_runtime(), hashes)
                paths["browser_service"].write_bytes(b"changed")
                with self.assertRaisesRegex(runner.PinError, "browser_service changed"):
                    runner.pinned_runtime()


if __name__ == "__main__":
    unittest.main()
