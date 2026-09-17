from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "chatgpt-planner"
    / "scripts" / "planner_state.py"
)
SPEC = importlib.util.spec_from_file_location("chatgpt_planner_state", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)

TASK_ID = "11111111-1111-4111-8111-111111111111"
OTHER_TASK_ID = "22222222-2222-4222-8222-222222222222"
CONVERSATION_ID = "33333333-3333-4333-8333-333333333333"
OTHER_CONVERSATION_ID = "44444444-4444-4444-8444-444444444444"


def task_packet(**changes: str) -> dict:
    packet = {
        "objective_key": "normalize-export-name",
        "objective": "Plan a fix for exported filenames that contain spaces.",
        "requirements": "Preserve Unicode, replace spaces with underscores, and retain the extension.",
        "context": "Inspected export.py: the save handler currently passes the title directly to Path.",
        "snapshot": "revision=fixture-1; export.py=sha256:synthetic-before",
    }
    packet.update(changes)
    return packet


def native_snapshot(prepared: dict, body: str = "Inspect the save handler, normalize spaces, and test Unicode names.") -> dict:
    request = prepared["request"]
    return {
        "thread": {
            "id": request["conversation_id"],
            "kind": "chatgpt",
            "status": {"type": "idle"},
        },
        "turns": [{
            "id": "fixture-turn-" + request["id"],
            "status": "completed",
            "items": [
                {
                    "id": "fixture-user-" + request["id"],
                    "type": "userMessage",
                    "content": [{"type": "text", "text": prepared["send_arguments"]["prompt"]}],
                },
                {
                    "id": "fixture-assistant-" + request["id"],
                    "type": "agentMessage",
                    "text": f"Planning reply {request['id']}\n{body}\nEnd planning reply {request['id']}",
                },
            ],
        }],
    }


class ChatGPTPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="chatgpt-planner-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.project = self.directory / "project"
        self.project.mkdir()
        self.state_dir = self.directory / "private-state"
        self.clock = 1_000.0
        self.store = planner.Store(self.state_dir, self.project, now=lambda: self.clock)

    def assert_planner_error(self, code: str, function, *args, **kwargs) -> None:
        with self.assertRaises(planner.PlannerError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def run_cli(self, action: str, *arguments: str, payload=None, project=None) -> subprocess.CompletedProcess:
        raw = payload if isinstance(payload, str) else json.dumps(payload) if payload is not None else ""
        return subprocess.run(
            [sys.executable, str(SCRIPT), action, "--project", str(project or self.project),
             "--state-dir", str(self.state_dir), *arguments],
            input=raw, text=True, capture_output=True, timeout=10, check=False,
        )

    def cli_result(self, action: str, *arguments: str, payload=None, project=None) -> dict:
        result = self.run_cli(action, *arguments, payload=payload, project=project)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stderr, "")
        response = json.loads(result.stdout)
        self.assertTrue(response["ok"])
        return response

    def complete_probe(self, key: str) -> dict:
        prepared = self.store.plan("default", TASK_ID, task_packet(objective_key=key), probe=True)
        self.assertEqual(prepared["action"], "send")
        self.clock += 1
        observed = self.store.observe(
            "default", prepared["request"]["id"], native_snapshot(prepared, "READY"), probe=True,
        )
        self.assertEqual(observed["action"], "complete")
        return prepared

    def verified_binding(self, conversation_id: str = CONVERSATION_ID) -> tuple[dict, dict]:
        self.store.bind(conversation_id)
        first = self.complete_probe("setup-initial")
        # Reopening the same private store simulates an interrupted local process.
        # Actual desktop restart/model confirmation remains a user assertion.
        self.store = planner.Store(self.state_dir, self.project, now=lambda: self.clock)
        self.clock += 1
        second = self.complete_probe("setup-after-restart")
        verified = self.store.verify(first["request"]["id"], second["request"]["id"], True, True)
        self.assertEqual(verified["action"], "verified")
        return first, second

    def prepared_plan(self, **changes: str) -> dict:
        self.verified_binding()
        prepared = self.store.plan("plan", TASK_ID, task_packet(**changes))
        self.assertEqual(prepared["action"], "send")
        return prepared

    def test_status_without_binding_creates_no_state(self) -> None:
        result = self.cli_result("status")
        self.assertIsNone(result["binding"])
        self.assertEqual(result["requests"], [])
        self.assertFalse(self.state_dir.exists())
        self.assertEqual(list(self.project.iterdir()), [])

    def test_execution_and_unknown_modes_skip_before_input_or_filesystem_access(self) -> None:
        for mode in ("default", "unknown"):
            for action in ("plan", "observe"):
                with self.subTest(mode=mode, action=action):
                    result = self.cli_result(
                        action, "--mode", mode, payload="invalid json",
                        project=self.directory / "does-not-exist",
                    )
                    self.assertEqual(result["action"], "skip")
        self.assertFalse(self.state_dir.exists())

    def test_large_direct_execution_request_with_planning_words_does_not_send_or_create_state(self) -> None:
        packet = task_packet(
            objective="Implement the approved architecture plan and deployment plan now.",
            requirements="Refactor the scheduler, add replica migration, and run integration tests.",
            context=(
                "The design document says to plan the migration, review the plan, and consult a planner. "
                * 900
            ),
        )
        result = self.cli_result("plan", "--mode", "default", "--task-id", TASK_ID, payload=packet)
        self.assertEqual((result["action"], result["reason"]), ("skip", "not_plan_mode"))
        self.assertNotIn("send_arguments", result)
        self.assertFalse(self.state_dir.exists())
        self.assertEqual(list(self.project.iterdir()), [])

    def test_setup_and_recovery_mutations_require_execution_mode(self) -> None:
        for mode in ("plan", "unknown"):
            for action in ("bind", "verify", "abandon"):
                with self.subTest(mode=mode, action=action):
                    result = self.cli_result(action, "--mode", mode)
                    self.assertEqual(result["action"], "skip")
        result = self.cli_result("plan", "--mode", "plan", "--setup-probe", payload="invalid json")
        self.assertEqual(result["action"], "skip")
        self.assertFalse(self.state_dir.exists())

    def test_missing_and_unverified_connections_cannot_prepare_task_context(self) -> None:
        missing = self.store.plan("plan", TASK_ID, task_packet())
        self.assertEqual(missing, {"action": "unavailable", "reason": "missing_binding"})
        self.assertFalse(self.state_dir.exists())
        self.store.bind(f"https://chatgpt.com/c/{CONVERSATION_ID}")
        unverified = self.store.plan("plan", TASK_ID, task_packet())
        self.assertEqual(unverified, {"action": "unavailable", "reason": "unverified_binding"})
        self.assertEqual(self.store.status()["requests"], [])

    def test_two_completed_probes_and_confirmations_verify_connection_after_reopen(self) -> None:
        first, second = self.verified_binding()
        result = self.cli_result("status")
        self.assertTrue(result["binding"]["verified"])
        self.assertEqual(result["binding"]["probe_ids"], [first["request"]["id"], second["request"]["id"]])
        self.assertEqual(result["binding"]["conversation_id"], CONVERSATION_ID)
        self.assertEqual(len(result["requests"]), 2)

    def test_verification_rejects_missing_confirmations_same_probe_and_wrong_order(self) -> None:
        self.store.bind(CONVERSATION_ID)
        first = self.complete_probe("setup-initial")
        self.clock += 1
        second = self.complete_probe("setup-after-restart")
        first_id, second_id = first["request"]["id"], second["request"]["id"]
        for model_confirmed, restart_confirmed in ((False, False), (False, True), (True, False)):
            with self.subTest(model=model_confirmed, restart=restart_confirmed):
                self.assert_planner_error(
                    "VERIFICATION_REQUIRED", self.store.verify,
                    first_id, second_id, model_confirmed, restart_confirmed,
                )
        self.assert_planner_error("VERIFICATION_REQUIRED", self.store.verify, first_id, first_id, True, True)
        self.assert_planner_error("VERIFICATION_ORDER", self.store.verify, second_id, first_id, True, True)
        self.assertFalse(self.store.status()["binding"]["verified"])

    def test_alternate_uuid_spelling_cannot_make_one_probe_count_as_two_exchanges(self) -> None:
        self.store.bind(CONVERSATION_ID)
        prepared = self.store.plan("default", TASK_ID, task_packet(objective_key="setup-initial"), probe=True)
        request_id = prepared["request"]["id"]
        # Equal timestamps avoid relying on the independent ordering check to
        # reject a duplicate exchange disguised by UUID formatting.
        completed = self.store.observe("default", request_id, native_snapshot(prepared, "READY"), probe=True)
        self.assertEqual(completed["request"]["created_at"], completed["request"]["completed_at"])
        before = (self.state_dir / "state.json").read_bytes()
        for spelling in (request_id.upper(), request_id.replace("-", ""), request_id.replace("-", "").upper()):
            with self.subTest(spelling=spelling):
                self.assert_planner_error("VERIFICATION_REQUIRED", self.store.verify, request_id, spelling, True, True)
                self.assertEqual((self.state_dir / "state.json").read_bytes(), before)
        self.assertFalse(self.store.status()["binding"]["verified"])

    def test_verification_rejects_incomplete_probe_and_ordinary_plan(self) -> None:
        first, second = self.verified_binding()
        prepared = self.store.plan("plan", TASK_ID, task_packet())
        self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        self.assert_planner_error(
            "VERIFICATION_REQUIRED", self.store.verify,
            first["request"]["id"], prepared["request"]["id"], True, True,
        )
        pending = self.store.plan("default", TASK_ID, task_packet(objective_key="another-probe"), probe=True)
        self.assert_planner_error(
            "VERIFICATION_REQUIRED", self.store.verify,
            second["request"]["id"], pending["request"]["id"], True, True,
        )

    def test_setup_probe_does_not_send_supplied_repository_context(self) -> None:
        self.store.bind(CONVERSATION_ID)
        packet = task_packet(context="synthetic-repository-content-must-not-be-in-probe")
        prepared = self.store.plan("default", TASK_ID, packet, probe=True)
        prompt = prepared["send_arguments"]["prompt"]
        for key in ("objective", "requirements", "context", "snapshot"):
            self.assertNotIn(packet[key], prompt)
        self.assertEqual(set(prepared["send_arguments"]), {"threadId", "prompt"})

    def test_small_plan_uses_native_send_arguments_and_stores_only_metadata(self) -> None:
        prepared = self.prepared_plan()
        arguments = prepared["send_arguments"]
        self.assertEqual(set(arguments), {"threadId", "prompt"})
        self.assertEqual(arguments["threadId"], CONVERSATION_ID)
        packet = task_packet()
        for key in ("objective", "requirements", "context", "snapshot"):
            self.assertIn(packet[key], arguments["prompt"])
        observed = self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        self.assertEqual(observed["action"], "complete")
        stored = (self.state_dir / "state.json").read_text(encoding="utf-8")
        for value in (*packet.values(), arguments["prompt"], observed["reply"], str(self.project)):
            self.assertNotIn(value, stored)
        self.assertEqual(stat.S_IMODE(self.state_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.state_dir / "state.json").stat().st_mode), 0o600)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_uncertain_dispatch_survives_process_restart_without_resend(self) -> None:
        self.verified_binding()
        prepared = self.cli_result("plan", "--mode", "plan", "--task-id", TASK_ID, payload=task_packet())
        self.assertEqual(prepared["action"], "send")
        repeated = self.cli_result("plan", "--mode", "plan", "--task-id", TASK_ID, payload=task_packet())
        self.assertEqual(repeated["action"], "reconcile")
        self.assertEqual(repeated["request"]["id"], prepared["request"]["id"])
        self.assertNotIn("send_arguments", repeated)
        absent = native_snapshot(prepared)
        absent["turns"] = []
        observed = self.cli_result(
            "observe", "--mode", "plan", "--request-id", prepared["request"]["id"], payload=absent,
        )
        self.assertEqual(observed["action"], "reconcile")
        self.assertEqual(observed["reason"], "request_not_visible")
        pending = next(request for request in self.store.status()["requests"]
                       if request["id"] == prepared["request"]["id"])
        self.assertEqual(pending["status"], "pending")

    def test_complete_result_is_reused_across_processes_and_changed_evidence_requires_revalidation(self) -> None:
        self.verified_binding()
        prepared = self.cli_result("plan", "--mode", "plan", "--task-id", TASK_ID, payload=task_packet())
        completed = self.cli_result(
            "observe", "--mode", "plan", "--request-id", prepared["request"]["id"],
            payload=native_snapshot(prepared),
        )
        self.assertEqual(completed["action"], "complete")
        for packet, action in (
            (task_packet(), "reuse"),
            (task_packet(context="A shorter summary of the same inspected source."), "reuse"),
            (task_packet(snapshot="revision=fixture-2; export.py=sha256:synthetic-after"), "revalidate"),
        ):
            with self.subTest(action=action, snapshot=packet["snapshot"]):
                result = self.cli_result("plan", "--mode", "plan", "--task-id", TASK_ID, payload=packet)
                self.assertEqual(result["action"], action)
                self.assertEqual(result["request"]["id"], prepared["request"]["id"])
                self.assertNotIn("send_arguments", result)

    def test_completed_plan_then_execution_then_plan_reuses_the_same_result(self) -> None:
        self.verified_binding()
        prepared = self.cli_result("plan", "--mode", "plan", "--task-id", TASK_ID, payload=task_packet())
        accepted = self.cli_result(
            "observe", "--mode", "plan", "--request-id", prepared["request"]["id"],
            payload=native_snapshot(prepared),
        )
        self.assertEqual(accepted["action"], "complete")
        before_execution = (self.state_dir / "state.json").read_bytes()
        execution = self.cli_result("plan", "--mode", "default", "--task-id", TASK_ID, payload=task_packet())
        self.assertEqual(execution["action"], "skip")
        self.assertNotIn("send_arguments", execution)
        self.assertEqual((self.state_dir / "state.json").read_bytes(), before_execution)
        returned_to_plan = self.cli_result("plan", "--mode", "plan", "--task-id", TASK_ID, payload=task_packet())
        self.assertEqual(returned_to_plan["action"], "reuse")
        self.assertEqual(returned_to_plan["request"]["id"], accepted["request"]["id"])
        self.assertEqual(returned_to_plan["request"]["response_id"], accepted["request"]["response_id"])
        self.assertNotIn("send_arguments", returned_to_plan)
        self.assertEqual((self.state_dir / "state.json").read_bytes(), before_execution)

    def test_completed_advice_is_reused_only_within_the_same_persistent_native_task(self) -> None:
        prepared = self.prepared_plan()
        self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        same_task = self.cli_result("plan", "--mode", "plan", "--task-id", TASK_ID, payload=task_packet())
        self.assertEqual(same_task["action"], "reuse")
        self.assertEqual(same_task["request"]["id"], prepared["request"]["id"])
        different_task = self.cli_result("plan", "--mode", "plan", "--task-id", OTHER_TASK_ID, payload=task_packet())
        self.assertEqual(different_task["action"], "send")
        self.assertEqual(different_task["request"]["task_id"], OTHER_TASK_ID)
        self.assertNotEqual(different_task["request"]["id"], prepared["request"]["id"])

    def test_changed_requirements_can_create_one_new_consultation_only_after_completion(self) -> None:
        prepared = self.prepared_plan()
        updated = task_packet(requirements="Preserve Unicode and replace all whitespace, including tabs.")
        busy = self.store.plan("plan", TASK_ID, updated)
        self.assertEqual((busy["action"], busy["reason"]), ("unavailable", "conversation_busy"))
        self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        revised = self.store.plan("plan", TASK_ID, updated)
        self.assertEqual(revised["action"], "send")
        self.assertNotEqual(revised["request"]["id"], prepared["request"]["id"])

    def test_execution_mode_never_accepts_a_pending_reply(self) -> None:
        prepared = self.prepared_plan()
        before = (self.state_dir / "state.json").read_bytes()
        result = self.store.observe("default", prepared["request"]["id"], native_snapshot(prepared))
        self.assertEqual(result["action"], "skip")
        self.assertEqual((self.state_dir / "state.json").read_bytes(), before)
        accepted = self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        self.assertEqual(accepted["action"], "complete")

    def test_only_exact_conversation_and_sent_prompt_can_correlate_a_reply(self) -> None:
        prepared = self.prepared_plan()
        request_id = prepared["request"]["id"]
        for field, value in (("id", OTHER_CONVERSATION_ID), ("kind", "codex")):
            with self.subTest(field=field):
                snapshot = native_snapshot(prepared)
                snapshot["thread"][field] = value
                self.assert_planner_error("WRONG_CONVERSATION", self.store.observe, "plan", request_id, snapshot)
        unrelated = native_snapshot(prepared)
        unrelated["turns"][0]["items"][0]["content"][0]["text"] = "An unrelated user message"
        observed = self.store.observe("plan", request_id, unrelated)
        self.assertEqual(observed["reason"], "request_not_visible")
        snapshot = native_snapshot(prepared)
        snapshot["turns"].insert(0, unrelated["turns"][0])
        self.assertEqual(self.store.observe("plan", request_id, snapshot)["action"], "complete")

    def test_equivalent_native_conversation_uuid_spellings_are_normalized(self) -> None:
        conversation_id = "aabbccdd-eeff-4abc-8def-aabbccddeeff"
        self.verified_binding(conversation_id)
        prepared = self.store.plan("plan", TASK_ID, task_packet())
        for spelling in (
            conversation_id.upper(),
            conversation_id.replace("-", ""),
            conversation_id.replace("-", "").upper(),
            conversation_id,
        ):
            with self.subTest(spelling=spelling):
                snapshot = native_snapshot(prepared)
                snapshot["thread"]["id"] = spelling
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual(result["action"], "complete")
                self.assertEqual(result["request"]["conversation_id"], conversation_id)

    def test_different_or_malformed_native_conversation_uuid_never_completes_a_request(self) -> None:
        prepared = self.prepared_plan()
        before = (self.state_dir / "state.json").read_bytes()
        for observed_id in (OTHER_CONVERSATION_ID, "not-a-uuid", "", None, 123):
            with self.subTest(observed_id=observed_id):
                snapshot = native_snapshot(prepared)
                snapshot["thread"]["id"] = observed_id
                with self.assertRaises(planner.PlannerError):
                    self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual((self.state_dir / "state.json").read_bytes(), before)

    def test_truncated_or_nontext_request_cannot_correlate_even_with_matching_reply_markers(self) -> None:
        prepared = self.prepared_plan()
        for update in ({"truncated": True}, {"type": "image"}):
            with self.subTest(update=update):
                snapshot = native_snapshot(prepared)
                snapshot["turns"][0]["items"][0]["content"][0].update(update)
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual(result["reason"], "request_not_visible")
                self.assertEqual(result["request"]["status"], "pending")

    def test_multiple_user_text_parts_cannot_correlate_by_assuming_join_semantics(self) -> None:
        prepared = self.prepared_plan()
        text = {"type": "text", "text": prepared["send_arguments"]["prompt"]}
        blank = {"type": "text", "text": ""}
        before = (self.state_dir / "state.json").read_bytes()
        for parts in ([], [text, blank], [blank, text], [text, blank, blank]):
            with self.subTest(parts=len(parts)):
                snapshot = native_snapshot(prepared)
                snapshot["turns"][0]["items"][0]["content"] = parts
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual((result["action"], result["reason"]), ("reconcile", "request_not_visible"))
                self.assertEqual((self.state_dir / "state.json").read_bytes(), before)
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))["action"], "complete")

    def test_duplicate_matching_turns_are_ambiguous_and_keep_the_request_pending(self) -> None:
        prepared = self.prepared_plan()
        snapshot = native_snapshot(prepared)
        duplicate = copy.deepcopy(snapshot["turns"][0])
        duplicate["id"] = "another-turn-with-the-identical-prompt"
        duplicate["items"][-1]["id"] = "another-response-to-the-identical-prompt"
        snapshot["turns"].append(duplicate)
        before = (self.state_dir / "state.json").read_bytes()
        self.assert_planner_error(
            "AMBIGUOUS_REQUEST", self.store.observe, "plan", prepared["request"]["id"], snapshot,
        )
        self.assertEqual((self.state_dir / "state.json").read_bytes(), before)
        self.assertEqual(self.store.plan("plan", TASK_ID, task_packet())["action"], "reconcile")

    def test_completed_turn_in_active_thread_remains_pending(self) -> None:
        prepared = self.prepared_plan()
        for status in ("running", "active", None):
            with self.subTest(status=status):
                snapshot = native_snapshot(prepared)
                snapshot["thread"]["status"] = {"type": status} if status else None
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual(result["action"], "wait")
                self.assertEqual(result["request"]["status"], "pending")
        snapshot = native_snapshot(prepared)
        snapshot["turns"][0]["status"] = "inProgress"
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], snapshot)["action"], "wait")
        snapshot = native_snapshot(prepared)
        snapshot["turns"][0]["items"].pop()
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], snapshot)["action"], "wait")

    def test_truncated_oversized_and_incomplete_answers_never_release_reservation(self) -> None:
        prepared = self.prepared_plan()
        for mutation, reason in (
            ({"truncated": True}, "truncated_reply"),
            ({"text": "x" * (planner.MAX_REPLY_CHARS + 1)}, "reply_too_long"),
            ({"text": "The final marker is missing."}, "incomplete_reply"),
            ({"id": ""}, "incomplete_reply"),
        ):
            with self.subTest(reason=reason, mutation=list(mutation)):
                snapshot = native_snapshot(prepared)
                snapshot["turns"][0]["items"][-1].update(mutation)
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual((result["action"], result["reason"]), ("unavailable", reason))
                busy = self.store.plan("plan", OTHER_TASK_ID, task_packet())
                self.assertEqual(busy["reason"], "conversation_busy")
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))["action"], "complete")

    def test_complete_reply_beyond_requested_target_is_accepted_within_native_reader_limit(self) -> None:
        self.verified_binding()
        for label, body in (("ascii", "x" * 13_000), ("emoji", "\U0001f642" * 6_500)):
            with self.subTest(encoding=label):
                prepared = self.store.plan("plan", TASK_ID, task_packet(objective_key="long-reply-" + label))
                self.assertRegex(prepared["send_arguments"]["prompt"], r"\b12000\b")
                snapshot = native_snapshot(prepared, body)
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual(result["action"], "complete")
                self.assertEqual(result["reply"], snapshot["turns"][0]["items"][-1]["text"])

    def test_reply_limit_includes_the_required_markers_and_accepts_exactly_20000_units(self) -> None:
        prepared = self.prepared_plan()
        marker_length = len(native_snapshot(prepared, "")["turns"][0]["items"][-1]["text"])
        accepted = self.store.observe(
            "plan", prepared["request"]["id"], native_snapshot(prepared, "x" * (20_000 - marker_length)),
        )
        self.assertEqual(accepted["action"], "complete")
        self.assertEqual(len(accepted["reply"]), 20_000)
        next_request = self.store.plan("plan", TASK_ID, task_packet(objective_key="reply-one-unit-over"))
        too_long = native_snapshot(next_request, "x" * (20_001 - marker_length))
        rejected = self.store.observe("plan", next_request["request"]["id"], too_long)
        self.assertEqual((rejected["action"], rejected["reason"]), ("unavailable", "reply_too_long"))
        self.assertEqual(rejected["request"]["status"], "pending")

    def test_empty_marked_reply_is_incomplete(self) -> None:
        prepared = self.prepared_plan()
        result = self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared, ""))
        self.assertEqual((result["action"], result.get("reason")), ("unavailable", "incomplete_reply"))
        self.assertEqual(self.store.plan("plan", OTHER_TASK_ID, task_packet())["reason"], "conversation_busy")

    def test_setup_probe_requires_the_requested_ready_response(self) -> None:
        self.store.bind(CONVERSATION_ID)
        prepared = self.store.plan("default", TASK_ID, task_packet(objective_key="setup-initial"), probe=True)
        result = self.store.observe(
            "default", prepared["request"]["id"], native_snapshot(prepared, "I could not complete this check."), probe=True,
        )
        self.assertEqual((result["action"], result["reason"]), ("unavailable", "invalid_probe_reply"))
        self.assertFalse(self.store.status()["binding"]["verified"])

    def test_rereading_completed_response_cannot_silently_replace_its_identifier(self) -> None:
        prepared = self.prepared_plan()
        snapshot = native_snapshot(prepared)
        accepted = self.store.observe("plan", prepared["request"]["id"], snapshot)
        self.assertEqual(accepted["action"], "complete")
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], snapshot)["action"], "complete")
        snapshot["turns"][0]["items"][-1]["id"] = "replacement-response"
        self.assert_planner_error("RESPONSE_CHANGED", self.store.observe, "plan", prepared["request"]["id"], snapshot)

    def test_rereading_completed_response_cannot_silently_replace_its_contents_or_turn(self) -> None:
        prepared = self.prepared_plan()
        accepted_snapshot = native_snapshot(prepared)
        accepted = self.store.observe("plan", prepared["request"]["id"], accepted_snapshot)
        self.assertEqual(accepted["action"], "complete")
        before = (self.state_dir / "state.json").read_bytes()
        for change in ("body", "turn"):
            with self.subTest(change=change):
                snapshot = copy.deepcopy(accepted_snapshot)
                if change == "body":
                    snapshot["turns"][0]["items"][-1]["text"] = native_snapshot(
                        prepared, "Replace the accepted advice with a different plan.",
                    )["turns"][0]["items"][-1]["text"]
                else:
                    snapshot["turns"][0]["id"] = "different-turn-for-the-same-answer"
                self.assert_planner_error("RESPONSE_CHANGED", self.store.observe, "plan", prepared["request"]["id"], snapshot)
                self.assertEqual((self.state_dir / "state.json").read_bytes(), before)

    def test_turn_scoped_error_is_terminal_for_the_same_objective(self) -> None:
        prepared = self.prepared_plan()
        snapshot = native_snapshot(prepared)
        snapshot["turns"][0]["error"] = {"message": "Synthetic quota failure"}
        result = self.store.observe("plan", prepared["request"]["id"], snapshot)
        self.assertEqual((result["action"], result["reason"]), ("unavailable", "remote_error"))
        repeated = self.store.plan("plan", TASK_ID, task_packet())
        self.assertEqual((repeated["action"], repeated["reason"]), ("unavailable", "failed"))
        late = self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        self.assertEqual((late["action"], late["reason"]), ("unavailable", "failed"))

    def test_thread_level_error_leaves_pending_request_reserved_for_reconciliation(self) -> None:
        prepared = self.prepared_plan()
        snapshot = native_snapshot(prepared)
        snapshot["thread"]["status"] = {"type": "systemError"}
        before = (self.state_dir / "state.json").read_bytes()
        result = self.store.observe("plan", prepared["request"]["id"], snapshot)
        self.assertEqual((result["action"], result["reason"]), ("unavailable", "conversation_error"))
        self.assertEqual(result["request"]["status"], "pending")
        self.assertEqual((self.state_dir / "state.json").read_bytes(), before)
        self.assertEqual(self.store.plan("plan", TASK_ID, task_packet())["action"], "reconcile")
        self.assertEqual(self.store.plan("plan", OTHER_TASK_ID, task_packet())["reason"], "conversation_busy")
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))["action"], "complete")

    def test_accepted_reply_can_be_retrieved_while_another_turn_is_active_or_errored(self) -> None:
        prepared = self.prepared_plan()
        original = self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        before = (self.state_dir / "state.json").read_bytes()
        self.clock += planner.DEADLINE_SECONDS + 1
        for thread_status in ("active", "systemError"):
            with self.subTest(thread_status=thread_status):
                snapshot = native_snapshot(prepared)
                snapshot["thread"]["status"] = {"type": thread_status}
                snapshot["turns"].insert(0, {
                    "id": "unrelated-later-turn", "status": "inProgress", "items": [],
                })
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual(result["action"], "complete")
                self.assertEqual(result["reply"], original["reply"])
                self.assertEqual(result["request"]["completed_at"], original["request"]["completed_at"])
                self.assertEqual((self.state_dir / "state.json").read_bytes(), before)

    def test_completed_request_missing_from_page_requests_retrieval_even_after_deadline(self) -> None:
        prepared = self.prepared_plan()
        self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))
        before = (self.state_dir / "state.json").read_bytes()
        for elapsed in (0, planner.DEADLINE_SECONDS + 1):
            self.clock += elapsed
            with self.subTest(elapsed=elapsed):
                snapshot = native_snapshot(prepared)
                snapshot["turns"] = []
                result = self.store.observe("plan", prepared["request"]["id"], snapshot)
                self.assertEqual((result["action"], result["reason"]), ("retrieve", "completed_turn_not_visible"))
                self.assertEqual(result["request"]["status"], "complete")
                self.assertNotIn("reply", result)
                self.assertNotIn("send_arguments", result)
                self.assertEqual((self.state_dir / "state.json").read_bytes(), before)
                self.assertEqual(self.store.plan("plan", TASK_ID, task_packet())["action"], "reuse")

    def test_timeout_retains_reservation_and_late_reply_can_be_reconciled_in_plan_mode(self) -> None:
        prepared = self.prepared_plan()
        self.clock += planner.DEADLINE_SECONDS + 1
        timed_out = self.store.plan("plan", TASK_ID, task_packet())
        self.assertEqual((timed_out["action"], timed_out["reason"]), ("unavailable", "timeout"))
        absent = native_snapshot(prepared)
        absent["turns"] = []
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], absent)["reason"], "timeout")
        busy = self.store.plan("plan", OTHER_TASK_ID, task_packet(requirements="New requirements"))
        self.assertEqual(busy["reason"], "conversation_busy")
        self.store = planner.Store(self.state_dir, self.project, now=lambda: self.clock)
        self.assertEqual(self.store.observe("default", prepared["request"]["id"], native_snapshot(prepared))["action"], "skip")
        self.assertEqual(self.store.observe("plan", prepared["request"]["id"], native_snapshot(prepared))["action"], "complete")

    def test_abandonment_requires_confirmation_and_does_not_retry_the_same_objective(self) -> None:
        prepared = self.prepared_plan()
        request_id = prepared["request"]["id"]
        self.assert_planner_error("EXPLICIT_ABANDON_REQUIRED", self.store.abandon, request_id, False)
        result = self.cli_result("abandon", "--mode", "default", "--request-id", request_id, "--confirm-abandon")
        self.assertEqual(result["request"]["status"], "abandoned")
        repeated = self.store.plan("plan", TASK_ID, task_packet())
        self.assertEqual((repeated["action"], repeated["reason"]), ("unavailable", "abandoned"))
        explicit_new = self.store.plan("plan", TASK_ID, task_packet(objective_key="explicit-new-consultation"))
        self.assertEqual(explicit_new["action"], "send")

    def test_abandoning_nonpending_requests_is_a_noop_with_the_existing_status(self) -> None:
        self.verified_binding()
        for status in ("complete", "failed", "abandoned"):
            with self.subTest(status=status):
                prepared = self.store.plan("plan", TASK_ID, task_packet(objective_key="abandon-" + status))
                request_id = prepared["request"]["id"]
                if status == "abandoned":
                    self.store.abandon(request_id, True)
                else:
                    snapshot = native_snapshot(prepared)
                    if status == "failed":
                        snapshot["turns"][0]["error"] = {"message": "Synthetic turn failure"}
                    self.store.observe("plan", request_id, snapshot)
                before = (self.state_dir / "state.json").read_bytes()
                result = self.store.abandon(request_id, True)
                self.assertEqual((result["action"], result["reason"]), ("noop", status))
                self.assertEqual(result["request"]["status"], status)
                self.assertEqual((self.state_dir / "state.json").read_bytes(), before)

    def test_binding_is_dedicated_to_one_project_and_pending_work_prevents_rebinding(self) -> None:
        prepared = self.prepared_plan()
        other_project = self.directory / "other-project"
        other_project.mkdir()
        other_store = planner.Store(self.state_dir, other_project, now=lambda: self.clock)
        self.assert_planner_error("CONVERSATION_ALREADY_BOUND", other_store.bind, CONVERSATION_ID)
        self.assert_planner_error("REQUEST_PENDING", self.store.bind, OTHER_CONVERSATION_ID)
        self.assert_planner_error("UNKNOWN_REQUEST", other_store.observe, "plan", prepared["request"]["id"], native_snapshot(prepared))
        same = self.store.bind(CONVERSATION_ID)
        self.assertTrue(same["binding"]["verified"])
        self.store.abandon(prepared["request"]["id"], True)
        replaced = self.store.bind(OTHER_CONVERSATION_ID)
        self.assertFalse(replaced["binding"]["verified"])
        self.assertEqual(self.store.plan("plan", TASK_ID, task_packet())["reason"], "unverified_binding")

    def test_parallel_processes_prepare_only_one_send_for_the_same_objective(self) -> None:
        self.verified_binding()
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(
                self.run_cli, "plan", "--mode", "plan", "--task-id", TASK_ID, payload=task_packet(),
            ) for _ in range(6)]
            completed = [future.result(timeout=15) for future in futures]
        for result in completed:
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        results = [json.loads(result.stdout) for result in completed]
        self.assertEqual(sum(result["action"] == "send" for result in results), 1)
        self.assertEqual(sum(result["action"] == "reconcile" for result in results), 5)
        self.assertEqual(len({result["request"]["id"] for result in results}), 1)
        self.assertEqual(sum(request["status"] == "pending" for request in self.store.status()["requests"]), 1)

    def test_parallel_distinct_tasks_cannot_share_an_outstanding_conversation(self) -> None:
        self.verified_binding()
        task_ids = [str(uuid.uuid4()) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(
                self.run_cli, "plan", "--mode", "plan", "--task-id", task_id, payload=task_packet(),
            ) for task_id in task_ids]
            completed = [future.result(timeout=15) for future in futures]
        for result in completed:
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        results = [json.loads(result.stdout) for result in completed]
        self.assertEqual(sum(result["action"] == "send" for result in results), 1)
        self.assertEqual(sum(result.get("reason") == "conversation_busy" for result in results), 3)
        self.assertEqual(len({result["request"]["id"] for result in results}), 1)

    def test_invalid_or_oversized_packet_does_not_reserve_the_conversation(self) -> None:
        self.verified_binding()
        before = self.store.status()["requests"]
        for packet, code in (
            ({"objective": "missing fields"}, "INVALID_PACKET"),
            (task_packet(context=" "), "INVALID_PACKET"),
            (task_packet(context="x" * (planner.MAX_PACKET_BYTES + 1)), "PACKET_TOO_LARGE"),
            (task_packet(context="x" * planner.MAX_PROMPT_CHARS), "PROMPT_TOO_LARGE"),
        ):
            with self.subTest(code=code):
                self.assert_planner_error(code, self.store.plan, "plan", TASK_ID, packet)
                self.assertEqual(self.store.status()["requests"], before)

    def test_malformed_native_values_return_structured_failure_without_completing_request(self) -> None:
        prepared = self.prepared_plan()
        snapshots = [{"thread": None, "turns": []}]
        malformed_turn = native_snapshot(prepared)
        malformed_turn["turns"] = [None]
        snapshots.append(malformed_turn)
        malformed_answer = native_snapshot(prepared)
        malformed_answer["turns"][0]["items"][-1]["text"] = None
        snapshots.append(malformed_answer)
        for snapshot in snapshots:
            with self.subTest(snapshot=snapshot):
                result = self.run_cli(
                    "observe", "--mode", "plan", "--request-id", prepared["request"]["id"], payload=snapshot,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                self.assertEqual(json.loads(result.stdout), {"ok": False, "error": "INVALID_SNAPSHOT"})
                self.assertEqual(self.store.plan("plan", TASK_ID, task_packet())["action"], "reconcile")

    def test_emoji_limits_match_native_reader_without_reserving_oversize_requests(self) -> None:
        self.verified_binding()
        self.assert_planner_error(
            "PROMPT_TOO_LARGE", self.store.plan, "plan", TASK_ID,
            task_packet(context="\U0001f642" * 9000),
        )
        self.assertTrue(all(r["status"] == "complete" for r in self.store.status()["requests"]))
        prepared = self.store.plan("plan", TASK_ID, task_packet())
        result = self.store.observe(
            "plan", prepared["request"]["id"], native_snapshot(prepared, "\U0001f642" * 10_001),
        )
        self.assertEqual((result["action"], result["reason"]), ("unavailable", "reply_too_long"))

    def test_default_state_directory_uses_nonempty_codex_home_or_home_fallback(self) -> None:
        simulated_home = self.directory / "simulated-home"
        configured_home = self.directory / "configured-codex-home"
        for environment, expected in (
            ({}, simulated_home / ".codex" / "state" / "chatgpt-planner"),
            ({"CODEX_HOME": ""}, simulated_home / ".codex" / "state" / "chatgpt-planner"),
            ({"CODEX_HOME": str(configured_home)}, configured_home / "state" / "chatgpt-planner"),
        ):
            with self.subTest(environment=environment):
                with mock.patch.dict(planner.os.environ, environment, clear=True):
                    with mock.patch.object(planner.Path, "home", return_value=simulated_home):
                        self.assertEqual(planner.default_state_dir(), expected)
        self.assertFalse(simulated_home.exists())
        self.assertFalse(configured_home.exists())

    def test_relative_state_directory_is_rejected_before_resolution_or_writes(self) -> None:
        for state_path in (Path("relative-state"), Path("."), Path("../relative-state")):
            with self.subTest(state_path=state_path):
                self.assert_planner_error("STATE_PATH_NOT_ABSOLUTE", planner.Store, state_path, self.project)
        with mock.patch.dict(planner.os.environ, {"CODEX_HOME": "relative-codex-home"}, clear=True):
            self.assert_planner_error(
                "STATE_PATH_NOT_ABSOLUTE", planner.Store, planner.default_state_dir(), self.project,
            )
        result = self.run_cli("status", "--state-dir", "relative-state")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), {"ok": False, "error": "STATE_PATH_NOT_ABSOLUTE"})
        self.assertFalse(self.state_dir.exists())

    def test_state_cannot_be_created_inside_project_or_another_git_checkout(self) -> None:
        self.assert_planner_error("STATE_INSIDE_PROJECT", planner.Store, self.project / "state", self.project)
        other_checkout = self.directory / "other-checkout"
        other_checkout.mkdir()
        (other_checkout / ".git").mkdir()
        self.assert_planner_error("STATE_INSIDE_GIT", planner.Store, other_checkout / "state", self.project)
        self.assertFalse((self.project / "state").exists())

    def test_untrusted_conversation_urls_do_not_create_binding(self) -> None:
        for conversation in (
            f"https://chatgpt.com/share/{CONVERSATION_ID}",
            f"https://chatgpt.com.example.invalid/c/{CONVERSATION_ID}",
            f"https://chatgpt.com/c/{CONVERSATION_ID}?token=synthetic",
            "not-a-conversation-id",
        ):
            with self.subTest(conversation=conversation):
                with self.assertRaises(planner.PlannerError):
                    self.store.bind(conversation)
        self.assertFalse(self.state_dir.exists())


if __name__ == "__main__":
    unittest.main()
