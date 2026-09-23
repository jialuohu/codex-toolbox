"""Offline catalog and local hook contract tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from catalog import (
    build_catalog,
    collect_installed_skills,
    collect_live_tools,
    prepare_route_candidates,
)
from user_prompt_submit import record_outcome, summarize_observed

ROUTING = Path(__file__).resolve().parent


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.version = "1.2.3"
        self.plugin = self.root / "market" / "example" / self.version
        manifest = self.plugin / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "example", "version": self.version,
                                        "skills": "./skills/"}), encoding="utf-8")
        skill = self.plugin / "skills" / "test-skill"
        (skill / "agents").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: \"Read public example records.\"\n---\n"
            "Private body is never cataloged.\n", encoding="utf-8")
        (skill / "agents" / "openai.yaml").write_text(
            "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")

    def listing(self, enabled: bool = True, version: str = "1.2.3") -> dict:
        return {"installed": [{
            "pluginId": "example@market", "name": "example", "marketplaceName": "market",
            "version": version, "installed": True, "enabled": enabled,
        }]}

    def test_only_enabled_exact_cache_entry_and_policy(self) -> None:
        self.assertEqual(collect_installed_skills(self.listing(False), self.root), [])
        self.assertEqual(collect_installed_skills(self.listing(version="2.0.0"), self.root), [])
        rows = collect_installed_skills(self.listing(), self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "skill:example@market/test-skill")
        self.assertEqual(rows[0]["availability"], "installed")
        self.assertFalse(rows[0]["implicit"])
        self.assertNotIn("Private body", str(rows))

    def test_local_cachebuster_version_is_included(self) -> None:
        version = "1.2.3+codex.abcdef"
        copy = self.plugin.parent / version
        shutil.copytree(self.plugin, copy)
        manifest = copy / ".codex-plugin" / "plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = version
        manifest.write_text(json.dumps(data), encoding="utf-8")
        rows = collect_installed_skills(self.listing(version=version), self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_source_version"], version)

    def test_current_tool_evidence_and_digest(self) -> None:
        rows = collect_installed_skills(self.listing(), self.root)
        catalog = build_catalog(rows, [{
            "id": "mcp__example__read", "name": "read", "description": "Read a record.",
            "owner": "example",
        }])
        self.assertEqual([row["id"] for row in catalog["candidates"]], [
            "skill:example@market/test-skill", "tool:mcp__example__read",
        ])
        self.assertEqual(catalog["candidates"][1]["availability"], "available")
        self.assertEqual(build_catalog(rows)["candidates"], [catalog["candidates"][0]])
        self.assertNotEqual(catalog["catalog_digest"], build_catalog(rows)["catalog_digest"])
        changed_version = [dict(rows[0], _source_version="1.2.4")]
        self.assertNotEqual(build_catalog(rows)["catalog_digest"],
                            build_catalog(changed_version)["catalog_digest"])
        with self.assertRaisesRegex(ValueError, "duplicate capability"):
            build_catalog(rows + rows)

    def test_route_requires_host_verification_and_explicit_lock(self) -> None:
        catalog = build_catalog(collect_installed_skills(self.listing(), self.root))
        skill_id = catalog["candidates"][0]["id"]
        with self.assertRaisesRegex(ValueError, "unverified"):
            prepare_route_candidates(catalog, [skill_id], [])
        with self.assertRaisesRegex(ValueError, "explicit-only"):
            prepare_route_candidates(catalog, [skill_id], [skill_id])
        selected = prepare_route_candidates(catalog, [skill_id], [skill_id], [skill_id], [skill_id])
        self.assertEqual(selected, [{**catalog["candidates"][0],
                                     "availability": "available", "required": True}])
        with self.assertRaisesRegex(ValueError, "required candidate omitted"):
            prepare_route_candidates(catalog, [], [skill_id], [skill_id])
        with self.assertRaisesRegex(ValueError, "no selected"):
            prepare_route_candidates(catalog, [], [skill_id])

    def test_host_skill_evidence_merges_installed_identity(self) -> None:
        installed = collect_installed_skills(self.listing(), self.root)
        host = [{
            "id": installed[0]["id"], "name": "test-skill",
            "description": "Host-visible description differs.", "owner": "example@market",
            "implicit": True,
        }]
        catalog = build_catalog(installed, host_skills=host)
        self.assertEqual(len(catalog["candidates"]), 1)
        self.assertEqual(catalog["candidates"][0]["availability"], "available")
        self.assertFalse(catalog["candidates"][0]["implicit"])
        self.assertEqual(catalog["candidates"][0]["description"],
                         "Read public example records.")
        host[0]["owner"] = "other"
        with self.assertRaisesRegex(ValueError, "conflicting host skill identity"):
            build_catalog(installed, host_skills=host)

    def test_capability_ids_have_a_fixed_bound(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid live tool id"):
            build_catalog([], live_tools=[{
                "id": "mcp__" + "x" * 190, "name": "read",
                "description": "Read one record.", "owner": "example",
            }])

    def test_multibyte_description_is_safe_for_server_limit(self) -> None:
        catalog = build_catalog([], live_tools=[{
            "id": "mcp__example__read", "name": "read", "owner": "example",
            "description": "界" * 200,
        }])
        selected = prepare_route_candidates(
            catalog, ["tool:mcp__example__read"], ["tool:mcp__example__read"])
        self.assertLessEqual(len(selected[0]["description"].encode("utf-8")), 300)
        self.assertEqual(selected[0]["description"], "界" * 100)
        self.assertFalse(selected[0]["required"])

    def test_live_tool_adapter_uses_namespace_without_claiming_plugin(self) -> None:
        rows = collect_live_tools([{
            "name": "mcp__zotero__search", "description": "Search saved papers.",
        }, {
            "name": "web__run", "description": "Search public sites.",
        }])
        self.assertEqual([row["owner"] for row in rows], ["mcp:zotero", "web"])
        catalog = build_catalog([], live_tools=rows)
        self.assertEqual(len(catalog["candidates"]), 2)

    def test_malformed_or_symlinked_metadata_is_omitted(self) -> None:
        entry = self.plugin / "skills" / "test-skill" / "SKILL.md"
        entry.write_text("---\nname: other\ndescription: Wrong name\n---\n", encoding="utf-8")
        self.assertEqual(collect_installed_skills(self.listing(), self.root), [])
        entry.unlink()
        entry.symlink_to(self.root / "outside")
        self.assertEqual(collect_installed_skills(self.listing(), self.root), [])

    def test_symlinked_policy_is_not_read(self) -> None:
        policy = self.plugin / "skills" / "test-skill" / "agents" / "openai.yaml"
        policy.unlink()
        outside = self.root / "outside-policy"
        outside.write_text("policy:\n  allow_implicit_invocation: true\n", encoding="utf-8")
        policy.symlink_to(outside)
        self.assertEqual(collect_installed_skills(self.listing(), self.root), [])

    def test_symlinked_marketplace_path_is_not_read(self) -> None:
        (self.root / "alias").symlink_to(self.root / "market")
        listing = self.listing()
        listing["installed"][0]["marketplaceName"] = "alias"
        listing["installed"][0]["pluginId"] = "example@alias"
        self.assertEqual(collect_installed_skills(listing, self.root), [])


class HookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state"
        self.event = {
            "hook_event_name": "UserPromptSubmit", "session_id": "session-1",
            "turn_id": "turn-1", "prompt": "private task and password secret-value",
            "transcript_path": "/private/secret-transcript.jsonl",
            "cwd": "/private/project",
        }

    def run_hook(self, enabled: bool, event: dict | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["TYPESAFE_ROUTING_STATE_DIR"] = str(self.state)
        env.pop("TYPESAFE_ROUTING_HOOK_ENABLED", None)
        if enabled:
            env["TYPESAFE_ROUTING_HOOK_ENABLED"] = "1"
        return subprocess.run(
            [sys.executable, str(ROUTING / "user_prompt_submit.py")],
            input=json.dumps(event if event is not None else self.event), text=True,
            capture_output=True, env=env, timeout=5, check=True,
        )

    def test_disabled_hook_is_inert(self) -> None:
        result = self.run_hook(False)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.state.exists())

    def test_enabled_hook_records_only_ids_and_fixed_reminder(self) -> None:
        result = self.run_hook(True)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {"hookSpecificOutput"})
        self.assertEqual(set(output["hookSpecificOutput"]),
                         {"hookEventName", "additionalContext"})
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"],
                         "UserPromptSubmit")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Review capability routing", context)
        event_path = self.state / "events.jsonl"
        text = event_path.read_text(encoding="utf-8")
        for private in ("private task", "secret-value", "secret-transcript", "/private/project"):
            self.assertNotIn(private, text + result.stdout)
        self.assertEqual(json.loads(text)["turn_id"], "turn-1")
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(event_path.stat().st_mode & 0o777, 0o600)
        record_outcome("session-1", "turn-1", "skipped", "private", state_dir=self.state)
        self.assertEqual(summarize_observed(self.state),
                         {"observed": 1, "terminal": 1, "without_terminal": 0})
        with self.assertRaisesRegex(ValueError, "duplicate routing outcome"):
            record_outcome("session-1", "turn-1", "evaluated", state_dir=self.state)

    def test_bad_event_fails_open(self) -> None:
        bad = dict(self.event, turn_id="../../private")
        result = self.run_hook(True, bad)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertFalse((self.state / "events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
