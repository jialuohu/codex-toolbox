"""Global planner behavior with synthetic browser/native observations only."""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/workflow-tools/skills/chatgpt-planner/scripts/planner_state.py"
SPEC = importlib.util.spec_from_file_location("planner", SCRIPT)
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)
TASK = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
PROBE = "55555555-5555-4555-8555-555555555555"
CID = "33333333-3333-4333-8333-333333333333"
SECOND_CID = "44444444-4444-4444-8444-444444444444"


def packet(**changes):
    result = dict(objective_key="test", objective="Plan an export filename fix",
                  requirements="Preserve Unicode and extensions",
                  context="Inspected export.py save handler", snapshot="revision-one")
    return dict(result, **changes)


def browser_snapshot(prepared, cid=CID, body="Check the save handler and Unicode filenames.", generating=False):
    rid = prepared["request"]["id"]
    return {"url": "https://chatgpt.com/c/" + cid, "signed_in": True,
            "model": "GPT-6 Pro", "generating": generating,
            "messages": [
                {"role": "user", "text": prepared["prompt"], "truncated": False},
                {"role": "assistant", "text": f"Planning reply {rid}\n{body}\nEnd planning reply {rid}",
                 "truncated": False}]}


def native_snapshot(prepared, cid=CID, body="Check the save handler and Unicode filenames.", active=False):
    data = browser_snapshot(prepared, cid, body)
    return {"thread": {"id": cid, "kind": "chatgpt", "status": {"type": "active" if active else "idle"}},
            "turns": [{"id": "native-turn", "status": "completed", "items": [
                {"type": "userMessage", "content": [{"type": "text", "text": prepared["prompt"]}]},
                {"type": "agentMessage", "id": "native-answer", "text": data["messages"][1]["text"]}]}]}


class GlobalPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="planner-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / "private"
        self.clock = 1000.
        self.store = self.new_store()

    def new_store(self, task=TASK, probe=False):
        return planner.Store(self.state, task, probe, now=lambda: self.clock)

    def cli(self, action, *args, payload=None, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), action, "--state-dir", str(self.state), *args],
                              input=json.dumps(payload) if payload is not None else "",
                              text=True, capture_output=True, cwd=cwd, timeout=10)

    def error(self, code, function, *args, **kwargs):
        with self.assertRaises(planner.PlannerError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def setup_global(self):
        probe = self.new_store(PROBE, True)
        prepared = probe.plan("default", packet(context="private source must not enter probe"), True)
        self.assertNotIn("private source", prepared["prompt"])
        probe.observe("default", prepared["request"]["id"],
                      browser_snapshot(prepared, SECOND_CID, "READY"))
        probe.setup(prepared["request"]["id"])
        return prepared

    def prepare(self, **changes):
        self.setup_global()
        return self.store.plan("plan", packet(**changes), True)

    def observe(self, prepared, **changes):
        return self.store.observe("plan", prepared["request"]["id"], browser_snapshot(prepared, **changes))

    def test_status_and_missing_setup_are_read_only(self):
        self.assertFalse(self.store.status()["ready"])
        self.assertEqual(self.store.plan("plan", packet(), True)["reason"], "global_setup_required")
        self.assertFalse(self.state.exists())

    def test_mode_gates_skip_invalid_input_and_state_paths(self):
        for mode in ("default", "unknown"):
            result = subprocess.run([sys.executable, str(SCRIPT), "plan", "--mode", mode,
                                     "--state-dir", "relative"], input="INVALID",
                                    capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout)["action"], "skip")
        self.assertFalse(self.state.exists())
        for action in ("setup", "abandon"):
            self.assertEqual(json.loads(self.cli(action, "--mode", "plan").stdout)["action"], "skip")

    def test_setup_requires_completed_browser_pro_model_probe(self):
        probe = self.new_store(PROBE, True)
        p = probe.plan("default", packet(), True)
        self.error("COMPLETED_BROWSER_PROBE_REQUIRED", probe.setup, p["request"]["id"])
        self.error("BROWSER_CREATION_NOT_VERIFIED", probe.observe, "default", p["request"]["id"],
                   native_snapshot(p, SECOND_CID, "READY"), "native")
        bad = browser_snapshot(p, SECOND_CID, "READY")
        bad["model"] = "Another model"
        self.error("MODEL_NOT_CONFIRMED", probe.observe, "default", p["request"]["id"], bad)
        self.assertFalse(probe.status()["ready"])
        self.assertEqual(probe.observe("default", p["request"]["id"],
                                      browser_snapshot(p, SECOND_CID, "Wrong"))["reason"], "invalid_probe_reply")
        probe.observe("default", p["request"]["id"], browser_snapshot(p, SECOND_CID, "READY"))
        self.assertTrue(probe.setup(p["request"]["id"])["ready"])

    def test_probe_and_normal_conversations_are_separate_even_with_same_task_id(self):
        self.setup_global()
        store = self.new_store(PROBE)
        self.assertEqual(store.plan("plan", packet(), True)["action"], "create_browser")

    def test_no_model_confirmation_no_reservation(self):
        self.setup_global()
        self.assertEqual(self.store.plan("plan", packet())["reason"], "model_not_confirmed")
        self.assertIsNone(self.store.status()["task"])

    def test_distinct_tasks_get_distinct_chats_and_matching_request_only_can_attach(self):
        p = self.prepare()
        other = self.new_store(OTHER)
        q = other.plan("plan", packet(), True)
        self.assertEqual((p["action"], q["action"]), ("create_browser", "create_browser"))
        self.observe(p)
        self.error("CONVERSATION_ALREADY_ASSIGNED", other.observe, "plan", q["request"]["id"],
                   browser_snapshot(q))
        result = other.observe("plan", q["request"]["id"],
                               browser_snapshot(q, "66666666-6666-4666-8666-666666666666"))
        self.assertEqual(result["action"], "complete")

    def test_workspaces_and_resume_do_not_change_task_identity(self):
        self.setup_global()
        a, b = self.base / "a", self.base / "b"
        a.mkdir()
        b.mkdir()
        first = json.loads(self.cli("plan", "--mode", "plan", "--task-id", TASK,
                                   "--model-confirmed", payload=packet(), cwd=a).stdout)
        second = json.loads(self.cli("plan", "--mode", "plan", "--task-id", TASK,
                                    "--model-confirmed", payload=packet(), cwd=b).stdout)
        self.assertEqual(first["action"], "create_browser")
        self.assertEqual(second["action"], "reconcile")
        self.assertEqual(first["request"]["id"], second["request"]["id"])

    def test_uncertain_creation_and_send_never_repeat(self):
        p = self.prepare()
        self.assertEqual(self.new_store().plan("plan", packet(), True)["action"], "reconcile")
        self.observe(p)
        q = self.store.plan("plan", packet(requirements="new requirement"), True)
        self.assertEqual(q["action"], "send_browser")
        self.assertEqual(self.new_store().plan("plan", packet(requirements="new requirement"), True)["action"], "reconcile")
        self.assertEqual(self.store.plan("plan", packet(requirements="third"), True)["reason"], "conversation_busy")

    def test_browser_to_native_and_fallback_do_not_duplicate_send(self):
        p = self.prepare()
        self.observe(p, generating=True)
        result = self.store.observe("plan", p["request"]["id"], native_snapshot(p), "native")
        self.assertEqual(result["action"], "complete")
        q = self.store.plan("plan", packet(requirements="new"), True)
        self.assertEqual(q["action"], "send_native")
        self.assertEqual(q["send_arguments"]["threadId"], CID)
        self.assertEqual(self.store.fallback("plan", q["request"]["id"])["action"], "reconcile")
        self.assertEqual(self.store.plan("plan", packet(requirements="new"), True)["action"], "reconcile")
        self.observe(q)
        r = self.store.plan("plan", packet(requirements="next"), True)
        self.assertEqual(r["action"], "send_browser")

    def test_native_handoff_requires_exact_prompt_and_chat(self):
        p = self.prepare()
        self.observe(p, generating=True)
        self.error("WRONG_CONVERSATION", self.store.observe, "plan", p["request"]["id"],
                   native_snapshot(p, SECOND_CID), "native")
        snapshot = native_snapshot(p)
        snapshot["turns"][0]["items"][0]["content"][0]["text"] = "unrelated"
        self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot, "native")["action"], "reconcile")
        self.assertEqual(self.store.status()["task"]["transport"], "browser")

    def test_full_browser_flow_and_unchanged_advice_reuse(self):
        p = self.prepare()
        self.assertEqual(self.observe(p)["action"], "complete")
        self.assertEqual(self.store.plan("plan", packet(), True)["action"], "reuse")
        self.assertEqual(self.store.plan("default", packet(), True)["action"], "skip")
        self.assertEqual(self.new_store().plan("plan", packet(), True)["action"], "reuse")
        self.assertEqual(self.store.plan("plan", packet(snapshot="changed"), True)["action"], "revalidate")

    def test_mode_switch_never_observes_or_falls_back(self):
        p = self.prepare()
        self.assertEqual(self.store.observe("default", p["request"]["id"], {})["action"], "skip")
        self.assertEqual(self.store.fallback("default", p["request"]["id"])["action"], "skip")
        self.assertEqual(self.store.status()["requests"][0]["status"], "pending")

    def test_incomplete_or_truncated_browser_request_does_not_attach(self):
        p = self.prepare()
        for field, value in (("text", "wrong"), ("truncated", True)):
            snapshot = browser_snapshot(p)
            snapshot["messages"][0][field] = value
            self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot)["action"], "reconcile")
        self.assertIsNone(self.store.status()["task"]["conversation_id"])

    def test_active_thread_never_completes_even_with_end_marker(self):
        p = self.prepare()
        self.assertEqual(self.observe(p, generating=True)["action"], "wait")
        self.assertEqual(self.store.observe("plan", p["request"]["id"], native_snapshot(p, active=True),
                                           "native")["action"], "wait")

    def test_invalid_replies_remain_pending(self):
        p = self.prepare()
        for change, reason in (({"text": "missing markers"}, "incomplete_reply"),
                               ({"truncated": True}, "truncated_reply"),
                               ({"text": "x" * 20001}, "reply_too_long")):
            snapshot = browser_snapshot(p)
            snapshot["messages"][1].update(change)
            self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot)["reason"], reason)
        self.assertEqual(self.store.status()["requests"][0]["status"], "pending")

    def test_browser_requires_explicit_model_signin_generation_and_truncation_evidence(self):
        p = self.prepare()
        for field, value in (("model", "GPT-6"), ("signed_in", False)):
            snapshot = browser_snapshot(p)
            snapshot[field] = value
            self.error("MODEL_NOT_CONFIRMED", self.store.observe, "plan", p["request"]["id"], snapshot)
        for field in ("generating", "messages"):
            snapshot = browser_snapshot(p)
            del snapshot[field]
            self.error("INVALID_BROWSER_SNAPSHOT", self.store.observe, "plan", p["request"]["id"], snapshot)
        snapshot = browser_snapshot(p)
        del snapshot["messages"][0]["truncated"]
        self.error("INVALID_BROWSER_SNAPSHOT", self.store.observe, "plan", p["request"]["id"], snapshot)

    def test_duplicate_prompt_is_ambiguous(self):
        p = self.prepare()
        snapshot = browser_snapshot(p)
        snapshot["messages"] *= 2
        self.error("AMBIGUOUS_REQUEST", self.store.observe, "plan", p["request"]["id"], snapshot)

    def test_cross_task_access_and_untrusted_urls_rejected(self):
        p = self.prepare()
        self.error("UNKNOWN_REQUEST", self.new_store(OTHER).observe, "plan", p["request"]["id"], browser_snapshot(p))
        for url in ("https://example.com/c/" + CID, "https://chatgpt.com/share/" + CID,
                    "https://chatgpt.com/c/" + CID + "?token=x", "not-an-id"):
            snapshot = browser_snapshot(p)
            snapshot["url"] = url
            with self.assertRaises(planner.PlannerError):
                self.store.observe("plan", p["request"]["id"], snapshot)

    def test_changed_accepted_response_rejected_across_transports(self):
        p = self.prepare()
        self.observe(p)
        self.assertEqual(self.store.observe("plan", p["request"]["id"], native_snapshot(p), "native")["action"], "complete")
        self.error("RESPONSE_CHANGED", self.store.observe, "plan", p["request"]["id"],
                   native_snapshot(p, body="Changed answer"), "native")

    def test_timeout_keeps_reservation_late_reply_can_complete_in_plan_mode(self):
        p = self.prepare()
        self.clock += 901
        self.assertEqual(self.store.plan("plan", packet(), True)["reason"], "timeout")
        self.assertEqual(self.store.status()["requests"][0]["status"], "pending")
        self.assertEqual(self.observe(p)["action"], "complete")

    def test_completed_missing_turn_requests_retrieval_even_after_deadline(self):
        p = self.prepare()
        self.observe(p)
        self.clock += 901
        snapshot = browser_snapshot(p)
        snapshot["messages"] = []
        self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot)["action"], "retrieve")

    def test_abandon_requires_explicit_confirmation_and_never_recreates_unknown_chat(self):
        p = self.prepare()
        self.error("EXPLICIT_ABANDON_REQUIRED", self.store.abandon, p["request"]["id"], False)
        self.store.abandon(p["request"]["id"], True)
        self.assertEqual(self.store.plan("plan", packet(), True)["reason"], "abandoned")
        self.assertEqual(self.store.plan("plan", packet(requirements="new"), True)["reason"], "creation_unresolved")

    def test_concurrent_calls_reserve_only_one_creation(self):
        self.setup_global()
        def call(_):
            return json.loads(self.cli("plan", "--mode", "plan", "--task-id", TASK,
                                       "--model-confirmed", payload=packet()).stdout)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(call, range(4)))
        self.assertEqual(sum(r["action"] == "create_browser" for r in results), 1)
        self.assertEqual(len({r["request"]["id"] for r in results}), 1)

    def legacy(self, pending=False):
        self.state.mkdir(mode=0o700)
        data = {"version": 1, "bindings": {"project-hash": {"verified": True}},
                "requests": {"77777777-7777-4777-8777-777777777777":
                             {"id": "77777777-7777-4777-8777-777777777777",
                              "status": "pending" if pending else "complete"}}}
        path = self.state / "state.json"
        path.write_text(json.dumps(data))
        path.chmod(0o600)
        return data

    def test_legacy_migration_is_backed_up_and_not_activated_implicitly(self):
        old = self.legacy()
        self.assertTrue(self.store.status()["migration_required"])
        self.assertEqual(self.store.plan("plan", packet(), True)["reason"], "global_setup_required")
        self.assertFalse((self.state / "state.v1.backup.json").exists())
        self.setup_global()
        self.assertEqual(json.loads((self.state / "state.v1.backup.json").read_text()), old)
        state = json.loads((self.state / "state.json").read_text())
        self.assertEqual(state["version"], 2)
        self.assertNotIn("bindings", state)
        self.assertNotIn("project-hash", json.dumps(state))

    def test_pending_legacy_blocks_migration_until_explicitly_resolved(self):
        self.legacy(True)
        probe = self.new_store(PROBE, True)
        self.error("LEGACY_REQUESTS_PENDING", probe.plan, "default", packet(), True)
        self.assertFalse((self.state / "state.v1.backup.json").exists())
        self.store.abandon("77777777-7777-4777-8777-777777777777", True, legacy=True)
        self.setup_global()
        self.assertTrue(self.store.status()["ready"])

    def test_state_contains_metadata_only_and_private_permissions(self):
        p = self.prepare()
        self.observe(p)
        raw = (self.state / "state.json").read_text()
        for text in ("Inspected export.py", "Preserve Unicode", "Check the save handler", p["prompt"]):
            self.assertNotIn(text, raw)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.state / "state.json").stat().st_mode & 0o777, 0o600)

    def test_unsafe_state_paths_and_permissions_fail(self):
        self.error("STATE_PATH_NOT_ABSOLUTE", planner.Store, Path("relative"))
        git = self.base / "repo"
        (git / ".git").mkdir(parents=True)
        self.error("STATE_INSIDE_GIT", planner.Store, git / "state")
        self.state.mkdir(mode=0o755)
        self.state.chmod(0o755)
        self.error("STATE_PERMISSIONS", self.store.status)

    def test_invalid_and_oversized_packet_does_not_reserve(self):
        self.setup_global()
        self.error("INVALID_PACKET", self.store.plan, "plan", {}, True)
        self.error("PACKET_TOO_LARGE", self.store.plan, "plan", packet(context="x"*70000), True)
        self.error("PROMPT_TOO_LARGE", self.store.plan, "plan", packet(context="x"*19000), True)
        self.assertIsNone(self.store.status()["task"])

    def test_emoji_response_limit_uses_utf16_units(self):
        p = self.prepare()
        snapshot = browser_snapshot(p, body="😀"*10000)
        self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot)["reason"], "reply_too_long")

    def test_cli_rejects_removed_project_binding_and_malformed_json(self):
        result = self.cli("plan", "--mode", "plan", "--task-id", TASK, payload=[])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], "INVALID_JSON")
        self.assertNotEqual(self.cli("bind").returncode, 0)
        self.assertNotEqual(self.cli("status", "--project", str(self.base)).returncode, 0)

    def test_temporary_web_id_never_attaches_a_conversation(self):
        p = self.prepare()
        snapshot = browser_snapshot(p)
        snapshot["url"] = "https://chatgpt.com/c/WEB:" + CID
        self.error("CONVERSATION_NOT_PERSISTED", self.store.observe,
                   "plan", p["request"]["id"], snapshot)
        self.assertIsNone(self.store.status()["task"]["conversation_id"])

    def test_native_error_is_scoped_to_matching_request(self):
        p = self.prepare()
        self.observe(p, generating=True)
        snapshot = native_snapshot(p)
        snapshot["thread"]["status"]["type"] = "systemError"
        self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot,
                                           "native")["reason"], "conversation_error")
        self.assertEqual(self.store.status()["requests"][0]["status"], "pending")
        snapshot["turns"][0]["error"] = {"message": "synthetic error"}
        self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot,
                                           "native")["reason"], "remote_error")
        self.assertEqual(self.store.status()["requests"][0]["status"], "failed")

    def test_native_split_or_truncated_prompt_cannot_promote_transport(self):
        p = self.prepare()
        self.observe(p, generating=True)
        for split in (False, True):
            snapshot = native_snapshot(p)
            content = snapshot["turns"][0]["items"][0]["content"]
            if split:
                content.append({"type": "text", "text": "extra"})
            else:
                content[0]["truncated"] = True
            self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot,
                                               "native")["action"], "reconcile")
        self.assertEqual(self.store.status()["task"]["transport"], "browser")

    def test_missing_native_status_waits_and_does_not_complete(self):
        p = self.prepare()
        self.observe(p, generating=True)
        snapshot = native_snapshot(p)
        snapshot["thread"]["status"] = None
        self.assertEqual(self.store.observe("plan", p["request"]["id"], snapshot,
                                           "native")["action"], "wait")

    def test_accepted_native_response_keeps_identity_on_same_transport(self):
        p = self.prepare()
        self.observe(p, generating=True)
        snapshot = native_snapshot(p)
        self.store.observe("plan", p["request"]["id"], snapshot, "native")
        snapshot["turns"][0]["items"][1]["id"] = "different-answer"
        self.error("RESPONSE_CHANGED", self.store.observe, "plan", p["request"]["id"], snapshot, "native")

    def test_repeated_setup_probes_can_measure_followups_without_task_context(self):
        p = self.setup_global()
        probe = self.new_store(PROBE, True)
        probe.setup(p["request"]["id"], "brave")
        self.assertEqual(probe.status()["setup"]["browser"], "brave")
        q = probe.plan("default", packet(objective_key="followup", context="secret fixture"), True)
        self.assertEqual(q["action"], "send_browser")
        self.assertNotIn("secret fixture", q["prompt"])
        self.assertEqual(probe.plan("default", packet(objective_key="followup"), True)["action"], "reconcile")

    def test_conflicting_legacy_backup_is_not_overwritten(self):
        self.legacy()
        backup = self.state / "state.v1.backup.json"
        backup.write_text("{}")
        backup.chmod(0o600)
        self.error("LEGACY_BACKUP_CONFLICT", self.new_store(PROBE, True).plan,
                   "default", packet(), True)
        self.assertEqual(backup.read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
