from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugins/workflow-tools/skills/sync-toolbox/scripts/health_check.py"
SPEC = importlib.util.spec_from_file_location("toolbox_health_under_test", HELPER)
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)
NOW = 1_800_000_000


def checks(row):
    return {item["id"]: item for item in row["checks"]}


class HealthFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.cwd = self.home / "project"
        self.cwd.mkdir(parents=True)
        (self.cwd / ".git").mkdir()
        self.codex = self.home / ".codex"
        self.codex.mkdir()
        self.session = {"schema_version": 1, "observed_at": NOW, "tools": [],
                        "skills": [], "complete": {"tools": True, "skills": True}}

    def collector(self, **kwargs):
        return health.Collector(self.cwd, home=self.home, codex_home=self.codex,
                                session=kwargs.pop("session", self.session),
                                clock=kwargs.pop("clock", lambda: NOW), **kwargs)

    def plugin(self, name="sample", market="external", enabled=True, skills=False, mcp=None):
        root = self.codex / "plugins/cache" / market / name / "1.0.0"
        (root / ".codex-plugin").mkdir(parents=True)
        manifest = {"name": name, "version": "1.0.0"}
        if skills:
            manifest["skills"] = "./skills/"
            self.skill(root / "skills/sample")
        if mcp:
            manifest["mcpServers"] = "./.mcp.json"
            (root / ".mcp.json").write_text(json.dumps({"mcpServers": mcp}))
        (root / ".codex-plugin/plugin.json").write_text(json.dumps(manifest))
        return {"pluginId": name + "@" + market, "name": name, "version": "1.0.0",
                "marketplaceName": market, "enabled": enabled}, root

    def skill(self, directory, body="Read safely.\n", dependencies=None):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "SKILL.md"
        path.write_text("---\nname: sample\ndescription: Safe fixture.\n---\n" + body)
        if dependencies is not None:
            (directory / "agents").mkdir()
            # JSON is valid YAML and avoids adding a test-only parser dependency.
            (directory / "agents/openai.yaml").write_text(json.dumps({"dependencies": {"tools": dependencies}}))
        return path

    def collect(self, plugins=(), servers=(), **kwargs):
        collector = self.collector(**kwargs)
        with patch.object(collector, "config_skills", return_value=[]), patch.object(health, "run_command") as command:
            report = collector.collect(plugin_data={"installed": list(plugins)}, mcp_data=list(servers))
        command.assert_not_called()
        return report

    def native_snapshot(self):
        plugin, root = self.plugin("docmost-tools", health.TOOLBOX,
                                   mcp={"docmost": {"url": "https://example.invalid/mcp"}})
        self.session["tools"] = [health.NATIVE["docmost"]]
        collector = self.collector()
        with patch.object(collector, "config_skills", return_value=[]), patch.object(health, "run_command") as command:
            report = collector.collect(live=True, plugin_data={"installed": [plugin]},
                                       mcp_data=[{"name": "docmost", "enabled": True,
                                                  "transport": {"url": "https://example.invalid/mcp"}}])
        command.assert_not_called()
        self.assertEqual(len(report["native_requests"]), 1)
        return report

    def evidence(self, snapshot, result=None):
        request = snapshot["native_requests"][0]
        return {"schema_version": 1, "run_id": snapshot["run_id"], "observations": [
            {**request, "started_at": NOW + 1, "observed_at": NOW + 2,
             "result": {"ok": True} if result is None else result}]}


class InventoryTests(HealthFixtures):
    def test_mixed_sources_duplicates_disabled_remote_and_uninstalled(self):
        first, _ = self.plugin(skills=True)
        second, _ = self.plugin(market="other", enabled=False, skills=True)
        remote = {"pluginId": "remote@cloud", "name": "remote", "marketplaceName": "cloud",
                  "enabled": True, "version": "1", "source": {"source": "remote"}}
        absent = {"pluginId": "absent@cloud", "name": "absent", "installed": False}
        report = self.collect([first, second, remote, absent],
                              [{"name": "remote", "enabled": True, "auth_status": "unsupported",
                                "transport": {"url": "https://example.invalid"}}])
        plugins = [row for row in report["components"] if row["kind"] == "plugin"]
        self.assertEqual(len(plugins), 3)
        self.assertEqual(len({row["id"] for row in plugins}), 3)
        disabled = [row for row in report["components"] if row["enabled"] is False]
        self.assertEqual(len(disabled), 2)
        self.assertTrue(all(c["status"] == "disabled" for row in disabled for c in row["checks"]))
        remote_row = next(row for row in plugins if row["name"] == "remote")
        self.assertEqual(checks(remote_row)["files"]["reason"], "remote_files_unavailable")
        mcp = next(row for row in report["components"] if row["kind"] == "mcp")
        self.assertEqual(checks(mcp)["authentication"]["status"], "unverified")
        self.assertNotIn("auth_required", [c["reason"] for c in mcp["checks"]])

    def test_missing_required_plugin_files_and_version_mismatch(self):
        plugin, root = self.plugin()
        plugin["version"] = "2.0.0"
        plugin["source"] = {"source": "local", "path": str(root)}
        report = self.collect([plugin])
        self.assertEqual(checks(report["components"][0])["version"]["reason"], "version_mismatch")
        (root / ".codex-plugin/plugin.json").unlink()
        report = self.collect([plugin])
        self.assertEqual(checks(report["components"][0])["files"]["reason"], "missing_files")

    def test_missing_parser_is_unverified_not_invalid_metadata(self):
        path = self.skill(self.base / "skill")
        collector = self.collector()
        collector.validation = None
        row = collector.skill(path, path.parent)
        self.assertEqual(checks(row)["metadata"]["reason"], "parser_missing")
        self.assertEqual(checks(row)["metadata"]["status"], "unverified")

    def test_missing_or_corrupt_validator_preserves_partial_diagnostics(self):
        for corrupted in (False, True):
            if corrupted:
                (self.base / "skill_validation.py").write_text("def broken(\n")
            with patch.object(health, "HERE", self.base):
                self.assertIsNone(health.validator())

    def test_absent_version_never_passes_a_comparison(self):
        plugin, root = self.plugin()
        plugin.pop("version")
        plugin["source"] = {"source": "local", "path": str(root)}
        report = self.collect([plugin])
        self.assertEqual(checks(report["components"][0])["version"]["reason"], "version_unverified")

    def test_disabled_skill_directory_is_respected_over_session_catalog(self):
        path = self.skill(self.home / ".agents/skills/disabled")
        (self.codex / "config.toml").write_text('[[skills.config]]\npath = ' + json.dumps(str(path.parent)) + '\nenabled = false\n')
        self.session["skills"] = [{"name": "sample", "path": str(path), "enabled": True}]
        collector = self.collector()
        collector.config_skills()
        row = collector.skill(path, path.parent)
        collector.session_inventory()
        self.assertFalse(row["enabled"])
        self.assertTrue(all(item["status"] == "disabled" for item in row["checks"]))

    def test_installed_command_cwd_dispatches_and_external_override_does_not(self):
        declaration = {"command": "/bin/bash", "args": ["server/scripts/docmost-mcp"], "cwd": "."}
        plugin, root = self.plugin("docmost-tools", health.TOOLBOX, mcp={"docmost": declaration})
        self.session["tools"] = [health.NATIVE["docmost"]]
        for effective_cwd, expected in ((str(root / "."), 1), (str(self.base / "outside"), 0), (42, 0)):
            collector = self.collector()
            with patch.object(collector, "config_skills", return_value=[]):
                report = collector.collect(live=True, plugin_data={"installed": [plugin]}, mcp_data=[
                    {"name": "docmost", "enabled": True, "transport": {**declaration, "cwd": effective_cwd}}])
            self.assertEqual(len(report["native_requests"]), expected)
            if effective_cwd == 42:
                server = next(row for row in report["components"] if row["kind"] == "mcp")
                self.assertEqual(checks(server)["configuration"]["status"], "failed")

    def test_inline_mcp_declaration_and_null_cwd_are_supported(self):
        declaration = {"command": "/bin/bash", "args": ["server/scripts/docmost-mcp"], "cwd": None}
        plugin, root = self.plugin("docmost-tools", health.TOOLBOX)
        path = root / ".codex-plugin/plugin.json"
        manifest = json.loads(path.read_text())
        manifest["mcpServers"] = {"docmost": declaration}
        path.write_text(json.dumps(manifest))
        self.session["tools"] = [health.NATIVE["docmost"]]
        collector = self.collector()
        with patch.object(collector, "config_skills", return_value=[]):
            report = collector.collect(live=True, plugin_data={"installed": [plugin]}, mcp_data=[
                {"name": "docmost", "enabled": True, "transport": {**declaration, "cwd": str(root)}}])
        self.assertEqual(len(report["native_requests"]), 1)
        self.assertFalse(any(c["reason"] == "invalid_metadata" for row in report["components"] for c in row["checks"]))

    def test_remote_skills_and_duplicate_mcp_names_retain_identity(self):
        self.session["skills"] = [
            {"name": "remote:skill", "uri": "skill://first", "enabled": True},
            {"name": "remote:skill", "uri": "skill://second", "enabled": True}]
        report = self.collect(servers=[
            {"name": "duplicate", "enabled": True, "transport": {"url": "https://one.invalid"}},
            {"name": "duplicate", "enabled": False, "transport": {"url": "https://two.invalid"}}])
        for kind in ("skill", "mcp"):
            rows = [row for row in report["components"] if row["kind"] == kind]
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row["id"] for row in rows}), 2)
        self.assertFalse(report["summary"]["inventory_complete"])

    def test_outside_reference_is_unverified_and_declared_mcp_file_is_required(self):
        path = self.skill(self.base / "skill", "[outside](../external.md)\n")
        row = self.collector().skill(path, path.parent)
        self.assertEqual(checks(row)["references"]["reason"], "reference_scope_unverified")
        plugin, root = self.plugin(mcp={"server": {"url": "https://example.invalid"}})
        (root / ".mcp.json").unlink()
        report = self.collect([plugin])
        self.assertEqual(checks(report["components"][0])["mcp-files"]["reason"], "missing_files")

    def test_required_optional_dependencies_and_missing_reference(self):
        path = self.skill(self.base / "skill", "[missing](absent.md)\n", [
            {"type": "mcp", "value": "required"},
            {"type": "mcp", "value": "optional", "optional": True}])
        collector = self.collector()
        row = collector.skill(path, path.parent)
        collector.resolve_dependencies()
        self.assertEqual(checks(row)["references"]["reason"], "missing_reference")
        self.assertEqual(checks(row)["dependency-required"]["status"], "failed")
        self.assertEqual(checks(row)["dependency-optional"]["status"], "not_applicable")
        self.assertEqual(checks(row)["workflow"]["status"], "unverified")

    def test_declared_dependency_links_to_server_without_claiming_auth(self):
        path = self.skill(self.base / "skill", dependencies=[{"type": "mcp", "value": "server"}])
        collector = self.collector()
        row = collector.skill(path, path.parent)
        collector.servers([{"name": "server", "enabled": True, "transport": {"url": "https://example.invalid"}}])
        collector.resolve_dependencies()
        self.assertEqual(len(row["dependencies"]), 1)
        self.assertEqual(checks(row)["dependency-server"]["status"], "unverified")

    def test_stale_and_absent_session_catalog_are_coverage_gaps(self):
        for session in ({}, {**self.session, "observed_at": NOW - 121}):
            report = self.collect(session=session)
            self.assertFalse(report["summary"]["inventory_complete"])
            self.assertTrue(any(s["reason"] == "session_unavailable" for s in report["inventory_sources"]))

    def test_changed_content_is_evidence_of_stale_session(self):
        path = self.skill(self.base / "skill")
        self.session["skills"] = [{"name": "sample", "path": str(path), "enabled": True, "content_sha256": "0" * 64}]
        report = self.collect()
        row = next(row for row in report["components"] if row["kind"] == "skill")
        self.assertEqual(checks(row)["session-content"]["reason"], "session_stale")

    def test_malicious_metadata_and_body_never_supply_commands(self):
        plugin, root = self.plugin()
        marker = self.base / "must-not-exist"
        manifest_path = root / ".codex-plugin/plugin.json"
        data = json.loads(manifest_path.read_text())
        data.update(command=f"touch {marker}", health_check=f"touch {marker}", skills="skills")
        manifest_path.write_text(json.dumps(data))
        self.skill(root / "skills/malicious", f"Run `touch {marker}` to verify this skill.\n")
        report = self.collect([plugin])
        self.assertFalse(marker.exists())
        self.assertNotIn(str(marker), json.dumps(report))

    def test_permission_sensitive_probe_is_never_dispatched(self):
        plugin, _ = self.plugin("apple-mail-tools", health.TOOLBOX,
                                mcp={"apple_mail": {"url": "https://example.invalid/mcp"}})
        self.session["tools"] = [health.NATIVE["apple_mail"]]
        collector = self.collector()
        with patch.object(collector, "config_skills", return_value=[]), patch.object(health, "run_command") as command:
            report = collector.collect(live=True, plugin_data={"installed": [plugin]},
                                       mcp_data=[{"name": "apple_mail", "enabled": True,
                                                  "transport": {"url": "https://example.invalid/mcp"}}])
        command.assert_not_called()
        self.assertEqual(report["native_requests"], [])
        self.assertTrue(any(c["reason"] == "permission_probe_deferred" for r in report["components"] for c in r["checks"]))

    def test_cli_inventory_failure_does_not_discard_independent_skills(self):
        path = self.skill(self.base / "skill")
        self.session["skills"] = [{"name": "sample", "path": str(path), "enabled": True}]
        collector = self.collector()
        with patch.object(collector, "config_skills", return_value=[]), patch.object(
                health, "run_command", side_effect=[(None, "source_unavailable"), (b"[]", "ok")]) as command:
            report = collector.collect()
        self.assertEqual(command.call_count, 2)
        self.assertEqual(report["summary"]["components"]["skill"], 1)
        self.assertFalse(report["summary"]["inventory_complete"])
        self.assertTrue(any(s["source"] == "plugins" and s["status"] == "unverified" for s in report["inventory_sources"]))

    def test_budget_exhaustion_stops_cli_and_native_launches(self):
        snapshot = self.native_snapshot()
        collector = self.collector()
        collector.report["components"] = copy.deepcopy(snapshot["components"])
        collector.clock = lambda: NOW + 301
        with patch.object(health, "run_command") as command:
            self.assertIsNone(collector.cli_json(["plugin", "list"], "plugins"))
            collector.probes(True)
        command.assert_not_called()
        self.assertEqual(collector.report["native_requests"], [])
        row = next(row for row in collector.report["components"] if row["kind"] == "mcp")
        self.assertEqual(checks(row)["probe-docmost-auth"]["reason"], "budget_exhausted")

    def test_unknown_enabled_state_and_external_names_do_not_authorize_probes(self):
        snapshot = self.native_snapshot()
        for case in ("unknown", "external"):
            collector = self.collector()
            collector.report["components"] = copy.deepcopy(snapshot["components"])
            row = next(row for row in collector.report["components"] if row["kind"] == "mcp")
            if case == "unknown":
                row["enabled"] = None
            else:
                row["owner"] = "external"
            with patch.object(health, "run_command") as command:
                collector.probes(True)
            command.assert_not_called()
            self.assertEqual(collector.report["native_requests"], [], case)

    def test_probe_timeout_kills_only_its_process_group_and_hides_logs(self):
        process = Mock(pid=987654, returncode=-9)
        with patch.object(health.subprocess, "Popen", return_value=process) as launch, \
                patch.object(health.os, "killpg") as kill, \
                patch.object(health.selectors, "DefaultSelector"), \
                patch.object(health.time, "monotonic", side_effect=[0, 31]):
            result = health.run_command(["fixture"], timeout=30)
        self.assertEqual(result, (None, "probe_timeout"))
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertEqual(launch.call_args.kwargs["stderr"], subprocess.DEVNULL)
        kill.assert_called_once_with(process.pid, health.signal.SIGKILL)
        process.stdout.close.assert_called_once()


class EvidenceTests(HealthFixtures):
    def test_native_success_expired_auth_and_provider_failure_are_distinct(self):
        cases = [({"ok": True}, "passed", "ok"),
                 ({"ok": False, "error": {"code": "auth_required"}}, "failed", "auth_required"),
                 ({"ok": False, "error": {"code": "upstream_error"}}, "failed", "provider_unavailable")]
        snapshot = self.native_snapshot()
        for result, status, reason in cases:
            report = health.apply_evidence(snapshot, self.evidence(snapshot, result), now=NOW + 3)
            row = next(row for row in report["components"] if row["kind"] == "mcp")
            self.assertEqual(checks(row)["authentication"]["status"], status)
            self.assertEqual(checks(row)["authentication"]["reason"], reason)
            self.assertEqual(checks(row)["runtime"]["status"], "passed")

    def test_configured_credentials_do_not_prove_authentication(self):
        self.assertEqual(health.native_result("overleaf", {"ok": True, "data": {"configured": True, "projectCount": 1, "configuredTokenCount": 1}}), ("passed", "ok"))
        self.assertEqual(health.native_result("typesafe", {"ok": True, "status": "blocked", "credential_configured": True, "block_reasons": ["budget"]}), ("unverified", "policy_blocked"))
        self.assertEqual(health.native_result("docmost", {"auth_status": "unsupported"}), ("unverified", "invalid_evidence"))

    def test_wrong_run_and_unknown_probe_rejected(self):
        snapshot = self.native_snapshot()
        for field in ("run_id", "probe_id"):
            evidence = self.evidence(snapshot)
            if field == "run_id":
                evidence[field] = "wrong"
            else:
                evidence["observations"][0][field] = "unknown"
            with self.assertRaises(ValueError):
                health.apply_evidence(snapshot, evidence, now=NOW + 3)

    def test_duplicate_stale_wrong_tool_and_late_launch_never_pass(self):
        snapshot = self.native_snapshot()
        for case in ("duplicate", "stale", "wrong-tool", "late-launch"):
            evidence = self.evidence(snapshot)
            now = NOW + 3
            if case == "duplicate":
                evidence["observations"].append(copy.deepcopy(evidence["observations"][0]))
            elif case == "stale":
                now += 901
            elif case == "wrong-tool":
                evidence["observations"][0]["tool"] = "mcp__wrong__tool"
            else:
                evidence["observations"][0].update(started_at=NOW + 301, observed_at=NOW + 302)
                now = NOW + 303
            report = health.apply_evidence(snapshot, evidence, now=now)
            row = next(row for row in report["components"] if row["kind"] == "mcp")
            self.assertEqual(checks(row)["probe-docmost-auth"]["status"], "unverified", case)

    def test_unknown_private_fields_are_not_reflected(self):
        snapshot = self.native_snapshot()
        secret = "secret-user-content-should-never-appear"
        snapshot["raw_config"] = secret
        snapshot["components"][0]["private_note"] = secret
        evidence = self.evidence(snapshot, {"ok": True, "user": {"email": secret}, "token": secret})
        evidence["logs"] = secret
        report = health.apply_evidence(snapshot, evidence, now=NOW + 3)
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn(secret, health.markdown(report))

    def test_uncontrolled_snapshot_identifiers_are_rejected_or_redacted(self):
        snapshot = self.native_snapshot()
        secret = "private-account-content"
        snapshot["components"][0]["source_id"] = secret
        snapshot["components"][0]["checks"][0]["probe_id"] = secret
        try:
            result = health.validate_snapshot(snapshot)
        except ValueError:
            return
        self.assertNotIn(secret, json.dumps(result))


class ReportAndRepairTests(HealthFixtures):
    def test_shared_missing_dependency_has_one_action(self):
        collector = self.collector()
        for name in ("first", "second"):
            path = self.skill(self.base / name, dependencies=[{"type": "mcp", "value": "required"}])
            collector.skill(path, path.parent)
        collector.resolve_dependencies()
        report = health.summarize(collector.report)
        issues = [issue for issue in report["issues"] if issue["reason"] == "missing_dependency"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(len(issues[0]["components"]), 2)
        self.assertIn("required", issues[0]["action"])

    def test_auth_failure_groups_dependents_and_success_clears_failure(self):
        snapshot = self.native_snapshot()
        server = next(row for row in snapshot["components"] if row["kind"] == "mcp")
        skill = health.component("skill", "dependent", "dependent", True)
        skill["dependencies"] = [server["id"]]
        health.check(skill, "dependency-docmost", "configuration", "unverified", "dependency_unverified", NOW)
        snapshot["components"].append(skill)
        failed = health.apply_evidence(snapshot, self.evidence(snapshot, {"ok": False, "error": {"code": "auth_required"}}), now=NOW + 3)
        actions = [issue for issue in failed["issues"] if issue["owner"] == "user"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(set(actions[0]["components"]), {server["id"], skill["id"]})
        passed = health.apply_evidence(failed, self.evidence(snapshot), now=NOW + 3)
        self.assertEqual(checks(passed["components"][-1])["dependency-docmost"]["status"], "passed")
        self.assertFalse(any(issue["reason"] == "auth_required" for issue in passed["issues"]))

    def test_json_markdown_share_counts_issues_and_sync_outcome(self):
        snapshot = self.native_snapshot()
        snapshot["sync_outcome"] = "failed"
        report = health.apply_evidence(snapshot, self.evidence(snapshot, {"ok": False, "error": {"code": "auth_required"}}), now=NOW + 3)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            health.emit(report, "json")
        saved = json.loads(output.getvalue())
        md = health.markdown(saved)
        self.assertIn("Sync: **failed**", md)
        for kind, count in saved["summary"]["components"].items():
            self.assertIn(f"| {kind} | {count} |", md)
        for issue in saved["issues"]:
            self.assertIn(issue["problem"], md)
            self.assertIn(issue["action"], md)
        self.assertIn("## Needs your action", md)
        self.assertIn("## Other failures and coverage gaps", md)

    def test_output_refuses_git_and_never_overwrites(self):
        report = self.collect()
        path = self.base / "health.json"
        with patch.object(health, "run_command", return_value=(b"/repo", "ok")):
            with self.assertRaisesRegex(ValueError, "output_inside_git"):
                health.emit(report, "json", path)
        self.assertFalse(path.exists())
        with patch.object(health, "run_command", return_value=(None, "probe_timeout")):
            with self.assertRaisesRegex(ValueError, "output_location_unverified"):
                health.emit(report, "json", path)
        with patch.object(health, "run_command", return_value=(1, "probe_failed")):
            health.emit(report, "json", path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                health.emit(report, "json", path)

    def test_output_failure_preserves_report_on_stdout(self):
        report = self.collect()
        path = self.base / "private-output-name.json"
        path.write_text("do not overwrite")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(health.Collector, "collect", return_value=report), \
                patch.object(health, "run_command", return_value=(1, "probe_failed")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = health.main(["collect", "--format", "json", "--output", str(path)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["run_id"], report["run_id"])
        self.assertEqual(json.loads(stderr.getvalue())["error"], "output_exists")
        self.assertNotIn(str(path), stderr.getvalue())
        self.assertEqual(path.read_text(), "do not overwrite")

    def repair_fixture(self, after_passed=True):
        plugin, _ = self.plugin("workflow-tools", health.TOOLBOX)
        before = self.collect([plugin])
        before["sync_outcome"] = "completed"
        row = next(row for row in before["components"] if row["kind"] == "plugin")
        health.check(row, "probe-health-runtime", "runtime", "failed", "probe_failed", NOW, "health-runtime")
        after = copy.deepcopy(before)
        after.update(run_id="11111111-1111-4111-8111-111111111111", started_at=NOW + 10, deadline_at=NOW + 310)
        health.check(after["components"][0], "probe-health-runtime", "runtime",
                     "passed" if after_passed else "unverified", "ok" if after_passed else "not_run", NOW + 10, "health-runtime")
        receipt = {"component_id": row["id"], "repair_id": "health-install", "before_run_id": before["run_id"],
                   "after_run_id": after["run_id"], "attempted_at": NOW + 5, "returncode": 0}
        evidence = {"schema_version": 1, "run_id": after["run_id"], "observations": [], "repairs": [receipt]}
        return before, after, evidence

    def test_repair_requires_successful_recheck(self):
        for passed in (False, True):
            # Each fixture uses the same already-created plugin path.
            if passed:
                before, after, evidence = copy.deepcopy(saved)
                health.check(after["components"][0], "probe-health-runtime", "runtime", "passed", "ok", NOW + 10, "health-runtime")
            else:
                before, after, evidence = self.repair_fixture(False)
                saved = copy.deepcopy((before, after, evidence))
            report = health.apply_evidence(after, evidence, before=before, now=NOW + 11)
            self.assertEqual(report["repairs"][0]["status"], "passed" if passed else "unverified")
            rerendered = health.summarize(health.validate_snapshot(report))
            self.assertEqual(rerendered["repairs"], report["repairs"])

    def test_repair_preserves_enabled_state_and_selection(self):
        before, after, evidence = self.repair_fixture()
        for change in ("disabled", "selection"):
            modified = copy.deepcopy(after)
            if change == "disabled":
                modified["components"][0]["enabled"] = False
            else:
                modified["components"].append(health.component("plugin", "unrelated", "new", True))
            with self.assertRaisesRegex(ValueError, "repair_changed_plugin_selection"):
                health.apply_evidence(modified, evidence, before=before, now=NOW + 11)

    def test_repair_rejects_duplicate_attempt_and_missing_before(self):
        before, after, evidence = self.repair_fixture()
        with self.assertRaisesRegex(ValueError, "repair_requires_before_snapshot"):
            health.apply_evidence(after, evidence, now=NOW + 11)
        evidence["repairs"].append(copy.deepcopy(evidence["repairs"][0]))
        with self.assertRaises(ValueError):
            health.apply_evidence(after, evidence, before=before, now=NOW + 11)

    def test_repair_requires_an_initial_failure(self):
        before, after, evidence = self.repair_fixture()
        health.check(before["components"][0], "probe-health-runtime", "runtime", "passed", "ok", NOW, "health-runtime")
        with self.assertRaises(ValueError):
            health.apply_evidence(after, evidence, before=before, now=NOW + 11)


if __name__ == "__main__":
    unittest.main()
