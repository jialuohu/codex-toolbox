"""Family migration tests use synthetic packages and temporary Codex homes only."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("visual_migration", ROOT / "scripts/migrate_visual_communication.py")
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def package(root, name, version, skills=()):
    path = root / "plugins" / name
    (path / ".codex-plugin").mkdir(parents=True)
    (path / ".codex-plugin/plugin.json").write_text(json.dumps({"name": name, "version": version, "skills": "./skills/"}))
    for skill in skills:
        destination = path / "skills" / skill / "SKILL.md"
        destination.parent.mkdir(parents=True)
        destination.write_text(f"---\nname: {skill}\ndescription: Synthetic test skill.\n---\nNo action.\n")
    return path


def source(root, target=False):
    versions = migration.TARGET if target else migration.PREDECESSOR
    for name, version in versions.items():
        skills = (migration.MOVED if name == "diagram-tools" else ()) if target else (
            ("explain-clearly",) if name == "workflow-tools" else
            ("paper-figure-workflow",) if name == "paper-figure-tools" else ())
        package(root, name, version, skills)
    path = root / ".agents/plugins/marketplace.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"name": migration.MARKETPLACE, "plugins": [
        {"name": name, "source": {"source": "local", "path": f"./plugins/{name}"}} for name in versions]}))


def change_version(root, name, version):
    path = root / "plugins" / name / ".codex-plugin/plugin.json"
    document = json.loads(path.read_text())
    document["version"] = version
    path.write_text(json.dumps(document))


class FakeCLI(migration.CodexCLI):
    def __init__(self, home):
        super().__init__("synthetic-codex", home, isolated=True)
        home.mkdir()
        self.rows = {}
        self.operations = []
        self.hidden = set()
        self.failure = None
        self.interruption = None
        self.failed = False
        self.write_config()

    def write_config(self):
        text = ''.join(f'[plugins."{row["pluginId"]}"]\nenabled = {str(row["enabled"]).lower()}\n\n'
                       for row in self.rows.values())
        (self.home / "config.toml").write_text(text)

    def installed(self):
        return [dict(row) for name, row in self.rows.items() if name not in self.hidden]

    def action(self, operation):
        self.operations.append(operation)
        if operation == self.interruption:
            raise KeyboardInterrupt("synthetic interruption")
        if operation == self.failure and not self.failed:
            self.failed = True
            raise migration.Blocked("synthetic_cli_failure")

    def add(self, name, source_root):
        self.action("add:" + name)
        info = migration.package_info(source_root / "plugins" / name, name)
        parent = self.home / "plugins/cache" / migration.MARKETPLACE / name
        if parent.exists():
            shutil.rmtree(parent)
        shutil.copytree(source_root / "plugins" / name, parent / info["version"])
        self.rows[name] = {"pluginId": name + "@" + migration.MARKETPLACE, "name": name,
                           "marketplaceName": migration.MARKETPLACE, "version": info["version"],
                           "installed": True, "enabled": True}
        self.write_config()

    def remove(self, name):
        self.action("remove:" + name)
        self.rows.pop(name, None)
        parent = self.home / "plugins/cache" / migration.MARKETPLACE / name
        if parent.exists():
            shutil.rmtree(parent)
        self.write_config()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.old = self.directory / "old"
        self.target = self.directory / "target"
        source(self.old)
        source(self.target, True)
        self.cli = FakeCLI(self.directory / "codex")

    def install_old(self):
        for name in migration.FAMILY:
            self.cli.add(name, self.old)
        self.cli.operations.clear()

    def add_opaque_remote(self, name="remote-helper", remote_id="remote-helper-id"):
        self.cli.rows[name] = {"pluginId": name + "@elsewhere", "name": name,
                               "marketplaceName": "elsewhere", "version": "1.0.0",
                               "installed": True, "enabled": True,
                               "source": {"source": "remote", "id": remote_id}}
        self.cli.write_config()

    def call_apply(self):
        with patch.object(migration, "rehearse") as rehearsal:
            result = migration.apply(self.target, self.cli)
        return result, rehearsal

    def test_plan_fresh_and_current_do_not_write(self):
        before = {str(p.relative_to(self.cli.home)): p.read_bytes() for p in self.cli.home.rglob("*") if p.is_file()}
        self.assertEqual(migration.plan(self.target, self.cli)["status"], "fresh")
        self.assertEqual(self.call_apply()[0]["status"], "fresh")
        after = {str(p.relative_to(self.cli.home)): p.read_bytes() for p in self.cli.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.cli.home / "state").exists())

    def test_predecessor_plan_preserves_packages_and_reports_owners(self):
        self.install_old()
        before = migration.inventory(self.cli)
        result = migration.plan(self.target, self.cli)
        self.assertEqual(result["status"], "predecessor")
        self.assertEqual(result["owners"], migration.OLD_OWNERS)
        self.assertTrue(result["recoverable_predecessors"])
        self.assertEqual(before, migration.inventory(self.cli))
        self.assertEqual(self.cli.operations, [])
        self.assertFalse((self.cli.home / "state").exists())

    def test_retired_catalog_entry_is_not_mistaken_for_fresh(self):
        self.install_old()
        self.cli.hidden.add("paper-figure-tools")
        self.assertEqual(migration.plan(self.target, self.cli)["status"], "predecessor")

    def test_opaque_remote_is_disclosed_and_preserved_without_assuming_no_skills(self):
        self.install_old()
        self.add_opaque_remote()
        before = migration.inventory(self.cli)
        proposal = migration.plan(self.target, self.cli)
        self.assertEqual(proposal["status"], "predecessor")
        self.assertTrue(proposal["family_skill_names_preserved"])
        self.assertEqual(proposal["ownership_scope"], "verified_family_and_local_skills")
        self.assertEqual(proposal["opaque_remote_plugins"][0]["skill_ownership"], "unverified")
        self.assertEqual(proposal["opaque_remote_plugins"][0]["remote_plugin_id"], "remote-helper-id")
        result, _ = self.call_apply()
        after = migration.inventory(self.cli)
        self.assertEqual(result["status"], "migrated")
        self.assertEqual(result["opaque_remote_plugins"], proposal["opaque_remote_plugins"])
        migration.assert_unrelated(before, after)
        self.assertEqual(self.cli.operations, ["add:diagram-tools", "add:workflow-tools", "remove:paper-figure-tools"])

    def test_opaque_remote_requires_existing_identical_complete_family_skill_set(self):
        self.add_opaque_remote()
        with self.assertRaisesRegex(migration.Blocked, "opaque_remote_plugins_require_unchanged_family_skill_names"):
            migration.plan(self.target, self.cli)
        self.install_old()
        extra = self.target / "plugins/diagram-tools/skills/new-helper/SKILL.md"
        extra.parent.mkdir(parents=True)
        extra.write_text("---\nname: new-helper\ndescription: Synthetic.\n---\n")
        with self.assertRaisesRegex(migration.Blocked, "migration_family_skill_names_changed"):
            migration.plan(self.target, self.cli)
        for name in migration.TARGET:
            self.cli.add(name, self.target)
        self.cli.remove("paper-figure-tools")
        extra.unlink()
        with self.assertRaisesRegex(migration.Blocked, "opaque_remote_plugins_require_unchanged_family_skill_names"):
            migration.plan(self.target, self.cli)

    def test_complete_family_skill_preservation_includes_nonmoved_skills(self):
        self.install_old()
        skill = self.cli.home / "plugins/cache" / migration.MARKETPLACE / "diagram-tools/0.5.3/skills/legacy-diagram/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: legacy-diagram\ndescription: Synthetic.\n---\n")
        with self.assertRaisesRegex(migration.Blocked, "migration_family_skill_names_changed"):
            migration.plan(self.target, self.cli)

    def test_unchanged_name_union_cannot_add_a_duplicate_family_owner(self):
        self.install_old()
        for root, name in ((self.cli.home / "plugins/cache" / migration.MARKETPLACE / "workflow-tools/0.18.2", "existing-helper"),
                           (self.target / "plugins/workflow-tools", "existing-helper"),
                           (self.target / "plugins/diagram-tools", "existing-helper")):
            skill = root / "skills" / name / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(f"---\nname: {name}\ndescription: Synthetic.\n---\n")
        with self.assertRaisesRegex(migration.Blocked, "migration_family_skill_names_changed"):
            migration.plan(self.target, self.cli)

    def test_valid_uppercase_unrelated_skill_name_is_inspected(self):
        self.install_old()
        local = self.cli.home / "skills/spreadsheets/SKILL.md"
        local.parent.mkdir(parents=True)
        local.write_text('---\nname: "Spreadsheets"\ndescription: Synthetic.\n---\n')
        self.assertEqual(migration.plan(self.target, self.cli)["status"], "predecessor")
        local.write_text('---\nname: "explain-clearly"\ndescription: Synthetic.\n---\n')
        with self.assertRaisesRegex(migration.Blocked, "other_skill_owner_collision"):
            migration.plan(self.target, self.cli)

    def test_missing_local_manifest_or_unknown_remote_identity_still_blocks(self):
        self.install_old()
        self.add_opaque_remote()
        for source in ({"source": "local", "path": "/synthetic"}, {"source": "remote"}, None):
            with self.subTest(source=source):
                self.cli.rows["remote-helper"]["source"] = source
                with self.assertRaisesRegex(migration.Blocked, "other_plugin_skill_owner_unknown"):
                    migration.plan(self.target, self.cli)
        self.assertEqual(self.cli.operations, [])

    def test_opaque_remote_source_identity_changes_block_preservation(self):
        self.install_old()
        self.add_opaque_remote()
        before = migration.inventory(self.cli)
        self.cli.rows["remote-helper"]["source"]["id"] = "different-remote-id"
        after = migration.unrelated_observation(self.cli)
        with self.assertRaisesRegex(migration.Blocked, "unrelated_installation_changed"):
            migration.assert_unrelated(before, after)

    def test_opaque_remote_does_not_hide_a_known_collision(self):
        self.install_old()
        self.add_opaque_remote()
        local = self.cli.home / "skills/explain-clearly/SKILL.md"
        local.parent.mkdir(parents=True)
        local.write_text("---\nname: explain-clearly\ndescription: Synthetic.\n---\n")
        with self.assertRaisesRegex(migration.Blocked, "other_skill_owner_collision"):
            migration.plan(self.target, self.cli)

    def test_same_named_other_marketplace_is_never_treated_as_owned_family(self):
        self.install_old()
        self.cli.rows["elsewhere-diagram"] = {"pluginId": "diagram-tools@elsewhere", "name": "diagram-tools",
                                               "marketplaceName": "elsewhere", "version": "1.0.0",
                                               "installed": True, "enabled": True}
        self.cli.write_config()
        with self.assertRaisesRegex(migration.Blocked, "family_namespace_ambiguous"):
            migration.plan(self.target, self.cli)
        # Even a disabled same-named plugin stays in unrelated preservation.
        self.cli.rows["elsewhere-diagram"]["enabled"] = False
        observed = migration.unrelated_observation(self.cli)
        self.assertIn("diagram-tools@elsewhere", [row["pluginId"] for row in observed["unrelated"]])

    def test_disabled_mixed_and_unknown_versions_block_without_mutation(self):
        self.install_old()
        self.cli.rows["diagram-tools"]["enabled"] = False
        self.cli.write_config()
        with self.assertRaisesRegex(migration.Blocked, "family_disabled"):
            migration.plan(self.target, self.cli)
        self.cli.rows["diagram-tools"]["enabled"] = True
        self.cli.write_config()
        self.cli.remove("paper-figure-tools")
        self.cli.operations.clear()
        with self.assertRaisesRegex(migration.Blocked, "mixed_partial"):
            self.call_apply()
        self.assertEqual(self.cli.operations, [])

    def test_candidate_verification_precedes_retirement_and_is_idempotent(self):
        self.install_old()
        self.cli.rows["unrelated"] = {"pluginId": "unrelated@elsewhere", "name": "unrelated",
                                      "marketplaceName": "elsewhere", "version": "1.0.0",
                                      "installed": True, "enabled": False}
        self.cli.write_config()
        before = migration.inventory(self.cli)
        runtime = self.cli.home / "state/diagram-tools/user-runtime-marker"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("preserve me")
        result, rehearsal = self.call_apply()
        self.assertEqual(result["status"], "migrated")
        rehearsal.assert_called_once()
        self.assertEqual(self.cli.operations, ["add:diagram-tools", "add:workflow-tools", "remove:paper-figure-tools"])
        after = migration.inventory(self.cli)
        self.assertEqual(after["owners"], migration.NEW_OWNERS)
        self.assertEqual(after["unrelated"], before["unrelated"])
        self.assertEqual(runtime.read_text(), "preserve me")
        operations = list(self.cli.operations)
        self.assertEqual(self.call_apply()[0]["status"], "current")
        self.assertEqual(self.cli.operations, operations)

    def test_current_family_allows_ordinary_higher_version_updates(self):
        for name in migration.TARGET:
            self.cli.add(name, self.target)
        self.cli.operations.clear()
        change_version(self.target, "diagram-tools", "0.6.1")
        proposal = migration.plan(self.target, self.cli)
        self.assertEqual(proposal["status"], "current")
        self.assertEqual(proposal["target"]["diagram-tools"]["version"], "0.6.1")
        self.assertEqual(self.call_apply()[0]["status"], "current")
        self.assertEqual(self.cli.operations, [])
        with self.assertRaisesRegex(migration.Blocked, "installed_candidate_verification_failed"):
            migration.package_readback(self.target, self.cli, "diagram-tools")
        self.cli.add("diagram-tools", self.target)
        self.assertEqual(migration.package_readback(self.target, self.cli, "diagram-tools")["status"], "verified")
        self.assertEqual(migration.plan(self.target, self.cli)["status"], "current")

    def test_current_preflight_allows_changed_source_but_readback_requires_exact_bytes(self):
        for name in migration.TARGET:
            self.cli.add(name, self.target)
        changed = self.target / "plugins/diagram-tools/skills/explain-clearly/SKILL.md"
        changed.write_text(changed.read_text() + "Updated source at same version.\n")
        self.assertEqual(migration.plan(self.target, self.cli)["status"], "current")
        with self.assertRaisesRegex(migration.Blocked, "installed_candidate_verification_failed"):
            migration.package_readback(self.target, self.cli, "diagram-tools")
        self.cli.add("diagram-tools", self.target)
        self.assertEqual(migration.package_readback(self.target, self.cli, "diagram-tools")["status"], "verified")

    def test_predecessor_migration_still_requires_approved_exact_target(self):
        self.install_old()
        change_version(self.target, "diagram-tools", "0.6.1")
        with self.assertRaisesRegex(migration.Blocked, "candidate_version_mismatch"):
            migration.plan(self.target, self.cli)
        self.assertEqual(self.cli.operations, [])

    def test_config_shape_errors_block_and_transition_errors_leave_recovery_receipt(self):
        self.install_old()
        (self.cli.home / "config.toml").write_text('plugins = "unknown"\n')
        with self.assertRaisesRegex(migration.Blocked, "configuration_shape_unknown"):
            migration.plan(self.target, self.cli)
        self.cli.write_config()

        def malformed_transition(*args):
            (self.cli.home / "config.toml").write_text('plugins = "unknown"\n')
            raise AttributeError("synthetic unexpected config shape")

        with patch.object(migration, "transition", side_effect=malformed_transition):
            with self.assertRaisesRegex(migration.Blocked, "migration_failed_recovery_required"):
                self.call_apply()
        self.assertEqual(migration.read_json(migration.journal_path(self.cli.home))["phase"], "recovery_required")

    def test_rehearsal_failure_performs_no_live_plugin_operations(self):
        self.install_old()
        before = migration.inventory(self.cli)
        with patch.object(migration, "rehearse", side_effect=migration.Blocked("unsupported_cli")):
            with self.assertRaisesRegex(migration.Blocked, "unsupported_cli"):
                migration.apply(self.target, self.cli)
        self.assertEqual(migration.inventory(self.cli), before)
        self.assertEqual(self.cli.operations, [])

    def test_update_failure_restores_exact_predecessor_packages(self):
        self.install_old()
        before = migration.inventory(self.cli)
        self.cli.failure = "add:workflow-tools"
        with self.assertRaisesRegex(migration.Blocked, "predecessors_restored"):
            self.call_apply()
        self.assertEqual(migration.inventory(self.cli), before)
        self.assertNotIn("remove:paper-figure-tools", self.cli.operations)
        self.assertEqual(migration.read_json(migration.journal_path(self.cli.home))["phase"], "recovered")

    def test_failed_candidate_readback_never_retires_figure_plugin(self):
        self.install_old()
        original = migration.verify_package
        seen = []

        def verify(cli, name, expected):
            seen.append(name)
            if len(seen) == 1:
                raise migration.Blocked("candidate_corrupt")
            return original(cli, name, expected)

        with patch.object(migration, "verify_package", side_effect=verify):
            with self.assertRaisesRegex(migration.Blocked, "predecessors_restored"):
                self.call_apply()
        self.assertNotIn("remove:paper-figure-tools", self.cli.operations)

    def test_invisible_successor_prevents_retirement_and_restores_predecessors(self):
        self.install_old()
        before = migration.inventory(self.cli)
        original = self.cli.installed

        def hide_candidate():
            return [row for row in original()
                    if not (row["name"] == "diagram-tools" and row["version"] == "0.6.0")]

        with patch.object(self.cli, "installed", side_effect=hide_candidate):
            with self.assertRaisesRegex(migration.Blocked, "predecessors_restored"):
                self.call_apply()
        self.assertEqual(migration.inventory(self.cli), before)
        self.assertNotIn("remove:paper-figure-tools", self.cli.operations)

    def test_successor_readback_requires_installed_true_in_discovery(self):
        for name in migration.TARGET:
            self.cli.add(name, self.target)
        self.cli.rows["diagram-tools"]["installed"] = False
        with self.assertRaisesRegex(migration.Blocked, "installed_candidate_verification_failed"):
            migration.package_readback(self.target, self.cli, "diagram-tools")

    def test_setup_readback_accepts_git_normalized_permissions_but_migration_is_strict(self):
        source_file = self.target / "plugins/workflow-tools/.codex-plugin/plugin.json"
        source_file.chmod(0o600)
        self.cli.add("workflow-tools", self.target)
        installed_file = self.cli.home / "plugins/cache" / migration.MARKETPLACE / "workflow-tools/0.19.0/.codex-plugin/plugin.json"
        installed_file.chmod(0o644)
        result = migration.package_readback(self.target, self.cli, "workflow-tools")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["mode_semantics"], "git_executable_bit")
        self.assertEqual(source_file.read_bytes(), installed_file.read_bytes())
        with self.assertRaisesRegex(migration.Blocked, "installed_candidate_verification_failed"):
            migration.verify_package(self.cli, "workflow-tools", migration.candidates(self.target)["workflow-tools"])

    def test_setup_git_mode_readback_still_rejects_content_and_executable_changes(self):
        self.cli.add("workflow-tools", self.target)
        installed_file = self.cli.home / "plugins/cache" / migration.MARKETPLACE / "workflow-tools/0.19.0/.codex-plugin/plugin.json"
        content = installed_file.read_text()
        installed_file.write_text(content + "\n")
        with self.assertRaisesRegex(migration.Blocked, "installed_candidate_verification_failed"):
            migration.package_readback(self.target, self.cli, "workflow-tools")
        installed_file.write_text(content)
        installed_file.chmod(0o744)
        with self.assertRaisesRegex(migration.Blocked, "installed_candidate_verification_failed"):
            migration.package_readback(self.target, self.cli, "workflow-tools")

    def test_recovery_rejects_permission_only_edits_with_original_receipt_hashes(self):
        self.install_old()
        self.cli.interruption = "add:workflow-tools"
        with self.assertRaises(KeyboardInterrupt):
            self.call_apply()
        installed_file = self.cli.home / "plugins/cache" / migration.MARKETPLACE / "diagram-tools/0.6.0/.codex-plugin/plugin.json"
        installed_file.chmod(0o600)
        self.cli.interruption = None
        self.cli.operations.clear()
        with self.assertRaisesRegex(migration.Blocked, "recovery_family_package_changed"):
            self.call_apply()
        self.assertEqual(self.cli.operations, [])

    def test_interruption_blocks_setup_and_next_apply_recovers_only(self):
        self.install_old()
        before = migration.inventory(self.cli)
        self.cli.interruption = "add:workflow-tools"
        with self.assertRaises(KeyboardInterrupt):
            self.call_apply()
        with self.assertRaisesRegex(migration.Blocked, "interrupted_migration"):
            migration.plan(self.target, self.cli)
        self.cli.interruption = None
        result, rehearsal = self.call_apply()
        self.assertEqual(result["status"], "recovered")
        rehearsal.assert_not_called()
        self.assertEqual(migration.inventory(self.cli), before)

    def test_failed_add_with_missing_cache_can_restore_predecessors(self):
        self.install_old()
        before = migration.inventory(self.cli)
        original = self.cli.add
        failed = False

        def missing_cache(name, source_root):
            nonlocal failed
            if name == "workflow-tools" and not failed:
                failed = True
                shutil.rmtree(self.cli.home / "plugins/cache" / migration.MARKETPLACE / name)
                raise migration.Blocked("interrupted_add_missing_cache")
            return original(name, source_root)

        with patch.object(self.cli, "add", side_effect=missing_cache):
            with self.assertRaisesRegex(migration.Blocked, "predecessors_restored"):
                self.call_apply()
        self.assertEqual(migration.inventory(self.cli), before)
        self.assertNotIn("remove:paper-figure-tools", self.cli.operations)

    def test_interrupted_add_after_write_reconciles_and_recovers(self):
        self.install_old()
        before = migration.inventory(self.cli)
        original = self.cli.add

        def interrupted_after_write(name, source_root):
            original(name, source_root)
            if name == "diagram-tools":
                raise KeyboardInterrupt("CLI returned after mutation")

        with patch.object(self.cli, "add", side_effect=interrupted_after_write):
            with self.assertRaises(KeyboardInterrupt):
                self.call_apply()
        self.assertEqual(self.call_apply()[0]["status"], "recovered")
        self.assertEqual(migration.inventory(self.cli), before)

    def test_final_retirement_failure_restores_removed_figure_plugin(self):
        self.install_old()
        before = migration.inventory(self.cli)
        original = self.cli.remove

        def removed_then_failed(name):
            original(name)
            raise migration.Blocked("remove_receipt_lost")

        with patch.object(self.cli, "remove", side_effect=removed_then_failed):
            with self.assertRaisesRegex(migration.Blocked, "predecessors_restored"):
                self.call_apply()
        self.assertEqual(migration.inventory(self.cli), before)

    def test_recovery_rejects_changed_snapshots_and_path_escape(self):
        self.install_old()
        self.cli.interruption = "add:workflow-tools"
        with self.assertRaises(KeyboardInterrupt):
            self.call_apply()
        journal = migration.journal_path(self.cli.home)
        saved = migration.read_json(journal)
        saved["snapshot_id"] = "../../elsewhere"
        migration.write_json(journal, saved)
        self.cli.interruption = None
        self.cli.operations.clear()
        with self.assertRaisesRegex(migration.Blocked, "recovery_snapshot_invalid"):
            self.call_apply()
        self.assertEqual(self.cli.operations, [])

    def test_symlinked_lock_never_creates_or_changes_external_target(self):
        self.install_old()
        state = self.cli.home.joinpath(*migration.STATE_PARTS)
        state.mkdir(parents=True)
        external = self.directory / "external-lock-target"
        lock = state / "lock"
        for exists in (False, True):
            with self.subTest(external_exists=exists):
                if exists:
                    external.write_text("preserve external bytes")
                lock.symlink_to(external)
                with self.assertRaises(migration.Blocked):
                    self.call_apply()
                self.assertEqual(external.exists(), exists)
                if exists:
                    self.assertEqual(external.read_text(), "preserve external bytes")
                self.assertEqual(self.cli.operations, [])
                lock.unlink()

    def test_interrupted_symlinked_journal_is_rejected_before_read_or_recovery(self):
        self.install_old()
        state = self.cli.home.joinpath(*migration.STATE_PARTS)
        state.mkdir(parents=True)
        external = self.directory / "external-journal.json"
        external.write_text('{"phase":"prepared","external":"preserve"}')
        (state / "transaction.json").symlink_to(external)
        with patch.object(migration, "read_journal") as reader, patch.object(migration, "recover") as recovery:
            with self.assertRaises(migration.Blocked):
                self.call_apply()
        reader.assert_not_called()
        recovery.assert_not_called()
        self.assertEqual(external.read_text(), '{"phase":"prepared","external":"preserve"}')
        self.assertFalse((state / "lock").exists())
        self.assertEqual(self.cli.operations, [])

    def test_nofollow_blocks_lock_symlink_introduced_after_path_check(self):
        state = self.cli.home.joinpath(*migration.STATE_PARTS)
        state.mkdir(parents=True)
        selected = migration.checked_child(state, "lock")
        external = self.directory / "must-not-be-created"
        selected.symlink_to(external)
        with self.assertRaisesRegex(migration.Blocked, "unsafe_transaction_file"):
            migration.open_transaction_file(selected, lock=True)
        self.assertFalse(external.exists())
        self.assertEqual(self.cli.operations, [])

    def test_journal_rename_is_directory_synced_before_return(self):
        events = []
        original_sync = migration.os.fsync
        original_replace = migration.os.replace

        def sync(descriptor):
            events.append("directory_fsync" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file_fsync")
            return original_sync(descriptor)

        def replace(source, target):
            events.append("replace")
            return original_replace(source, target)

        receipt = self.directory / "journal/transaction.json"
        with patch.object(migration.os, "fsync", side_effect=sync), patch.object(migration.os, "replace", side_effect=replace):
            migration.write_json(receipt, {"phase": "prepared"})
        self.assertEqual(events, ["file_fsync", "replace", "directory_fsync"])
        self.assertEqual(json.loads(receipt.read_text()), {"phase": "prepared"})

    def test_recovery_preserves_same_version_user_edits(self):
        self.install_old()
        self.cli.interruption = "add:workflow-tools"
        with self.assertRaises(KeyboardInterrupt):
            self.call_apply()
        changed = self.cli.home / "plugins/cache" / migration.MARKETPLACE / "diagram-tools/0.6.0/skills/explain-clearly/SKILL.md"
        changed.write_text(changed.read_text() + "User edit after interruption.\n")
        self.cli.interruption = None
        self.cli.operations.clear()
        with self.assertRaisesRegex(migration.Blocked, "recovery_family_package_changed"):
            self.call_apply()
        self.assertEqual(self.cli.operations, [])
        self.assertIn("User edit after interruption.", changed.read_text())

    def test_recovery_rejects_corrupted_predecessor_snapshot(self):
        self.install_old()
        self.cli.interruption = "add:workflow-tools"
        with self.assertRaises(KeyboardInterrupt):
            self.call_apply()
        journal = migration.journal_path(self.cli.home)
        saved = migration.read_json(journal)
        manifest = journal.parent / saved["snapshot_id"] / "previous/plugins/diagram-tools/.codex-plugin/plugin.json"
        manifest.write_text(manifest.read_text() + " ")
        self.cli.interruption = None
        self.cli.operations.clear()
        with self.assertRaisesRegex(migration.Blocked, "recovery_package_changed"):
            self.call_apply()
        self.assertEqual(self.cli.operations, [])

    def test_preservation_hash_covers_marketplace_and_other_configuration(self):
        self.install_old()
        before = migration.inventory(self.cli)
        with (self.cli.home / "config.toml").open("a") as config:
            config.write('[marketplaces.synthetic]\nsource_type = "local"\nsource = "/synthetic"\n')
        after = migration.unrelated_observation(self.cli)
        with self.assertRaisesRegex(migration.Blocked, "unrelated_installation_changed"):
            migration.assert_unrelated(before, after)

    def test_plan_rejects_symlink_packages_and_disabled_moved_skill(self):
        self.install_old()
        (self.target / "plugins/diagram-tools/leak").symlink_to(self.directory)
        with self.assertRaisesRegex(migration.Blocked, "package_symlink"):
            migration.plan(self.target, self.cli)
        (self.target / "plugins/diagram-tools/leak").unlink()
        with (self.cli.home / "config.toml").open("a") as config:
            config.write('[[skills.config]]\npath = "/synthetic/explain-clearly/SKILL.md"\nenabled = false\n')
        with self.assertRaisesRegex(migration.Blocked, "moved_skill_disabled"):
            migration.plan(self.target, self.cli)

    def test_generated_dependencies_do_not_enter_identity_or_snapshots(self):
        plugin = self.target / "plugins/diagram-tools"
        expected = migration.package_info(plugin, "diagram-tools")
        dependencies = plugin / "runtime/bootstrap/node_modules/dependency"
        dependencies.mkdir(parents=True)
        (dependencies / "generated.js").write_text("synthetic generated dependency")
        (dependencies / "linked").symlink_to(self.directory)
        self.assertEqual(migration.package_info(plugin, "diagram-tools"), expected)
        snapshot = self.directory / "snapshot"
        migration.snapshot(snapshot, {"diagram-tools": plugin}, {"diagram-tools": expected})
        self.assertFalse((snapshot / "plugins/diagram-tools/runtime/bootstrap/node_modules").exists())
        self.assertTrue((dependencies / "generated.js").is_file())

    def test_probe_environment_does_not_inherit_credentials(self):
        with patch.dict(os.environ, {"API_KEY": "synthetic", "CODEX_SESSION_ID": "synthetic", "CODEX_SECRETS_DIR": "/synthetic"}):
            environment = migration.clean_environment(self.cli.home, self.directory)
        self.assertEqual(set(environment), {"PATH", "HOME", "CODEX_HOME", "LANG"})
        self.assertEqual(environment["CODEX_HOME"], str(self.cli.home))

    def test_other_plugin_and_aliased_local_skill_collisions_block(self):
        self.install_old()
        other = self.cli.home / "plugins/cache/elsewhere/other/1.0.0"
        source_root = self.directory / "other-source"
        authored = package(source_root, "other", "1.0.0", ["explain-clearly"])
        shutil.copytree(authored, other)
        self.cli.rows["other"] = {"pluginId": "other@elsewhere", "name": "other", "marketplaceName": "elsewhere",
                                  "version": "1.0.0", "installed": True, "enabled": True}
        self.cli.write_config()
        with self.assertRaisesRegex(migration.Blocked, "other_skill_owner_collision"):
            migration.plan(self.target, self.cli)
        self.cli.rows.pop("other")
        self.cli.write_config()
        alias = self.directory / "alternate-name.md"
        alias.write_text("---\nname: explain-clearly\ndescription: Synthetic alias.\n---\nNo action.\n")
        with (self.cli.home / "config.toml").open("a") as config:
            config.write(f'[[skills.config]]\npath = {json.dumps(str(alias))}\nenabled = true\n')
        with self.assertRaisesRegex(migration.Blocked, "other_skill_owner_collision"):
            migration.plan(self.target, self.cli)

    def test_symlinked_local_skill_owner_is_detected(self):
        self.install_old()
        external = self.directory / "external"
        external.mkdir()
        (external / "SKILL.md").write_text("---\nname: explain-clearly\ndescription: Synthetic alias.\n---\nNo action.\n")
        skills = self.cli.home / "skills"
        skills.mkdir()
        (skills / "alias").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(migration.Blocked, "other_skill_owner_collision"):
            migration.plan(self.target, self.cli)

    def test_unparsed_local_skill_name_blocks_ownership_proof(self):
        self.install_old()
        skill = self.cli.home / "skills/alias/SKILL.md"
        skill.parent.mkdir(parents=True)
        for declaration in ("name: explain-clearly # comment", "name: >-\n  explain-clearly"):
            with self.subTest(declaration=declaration):
                skill.write_text(f"---\n{declaration}\ndescription: Synthetic alias.\n---\nNo action.\n")
                with self.assertRaisesRegex(migration.Blocked, "local_skill_metadata_unknown"):
                    migration.plan(self.target, self.cli)
                self.assertEqual(self.cli.operations, [])

    def test_main_check_setup_blocks_predecessors_but_allows_unrelated_only(self):
        self.cli.rows["unrelated"] = {"pluginId": "unrelated@elsewhere", "name": "unrelated",
                                      "marketplaceName": "elsewhere", "version": "1.0.0", "installed": True, "enabled": False}
        self.cli.write_config()
        self.assertEqual(migration.plan(self.target, self.cli)["status"], "fresh")
        self.install_old()
        self.assertEqual(migration.plan(self.target, self.cli)["status"], "predecessor")


@unittest.skipUnless(shutil.which("codex"), "Codex CLI is unavailable; synthetic migration tests still run")
class IsolatedCodexIntegrationTests(unittest.TestCase):
    def test_supported_cli_upgrade_and_recovery_in_temporary_home(self):
        """Never points a CLI invocation at the user's real home or configuration."""
        with tempfile.TemporaryDirectory(prefix="toolbox-cli-integration-") as directory:
            root = Path(directory)
            previous, target = root / "previous", root / "target"
            source(previous)
            source(target, True)
            expected = migration.candidates(target)
            migration.rehearse(shutil.which("codex"), previous, target, expected)
            home = root / "codex"
            home.mkdir()
            cli = migration.CodexCLI(shutil.which("codex"), home, isolated=True)
            cli.run("plugin", "marketplace", "add", str(previous), "--json")
            for name in migration.FAMILY:
                cli.add(name, previous)
            result = migration.apply(target, cli)
            self.assertEqual(result["status"], "migrated")
            self.assertEqual(migration.inventory(cli)["owners"], migration.NEW_OWNERS)
            self.assertEqual(migration.apply(target, cli)["status"], "current")

    def test_supported_cli_same_version_refresh_and_later_upgrade_are_verified(self):
        with tempfile.TemporaryDirectory(prefix="toolbox-cli-refresh-") as directory:
            root = Path(directory)
            target, home = root / "target", root / "codex"
            source(target, True)
            home.mkdir()
            cli = migration.CodexCLI(shutil.which("codex"), home, isolated=True)
            cli.run("plugin", "marketplace", "add", str(target), "--json")
            for name in migration.TARGET:
                cli.add(name, target)
            skill = target / "plugins/diagram-tools/skills/explain-clearly/SKILL.md"
            skill.write_text(skill.read_text() + "Changed synthetic same-version content.\n")
            self.assertEqual(migration.plan(target, cli)["status"], "current")
            with self.assertRaisesRegex(migration.Blocked, "installed_candidate_verification_failed"):
                migration.package_readback(target, cli, "diagram-tools")
            cli.add("diagram-tools", target)
            self.assertEqual(migration.package_readback(target, cli, "diagram-tools")["status"], "verified")
            change_version(target, "diagram-tools", "0.6.1")
            self.assertEqual(migration.plan(target, cli)["status"], "current")
            cli.add("diagram-tools", target)
            self.assertEqual(migration.package_readback(target, cli, "diagram-tools")["version"], "0.6.1")
            self.assertEqual(migration.plan(target, cli)["status"], "current")
            command = [shutil.which("python3"), str(ROOT / "scripts/migrate_visual_communication.py"),
                       "--verify-package", "diagram-tools", "--root", str(target),
                       "--codex-home", str(home), "--codex-bin", shutil.which("codex")]
            result = subprocess.run(command, env=migration.clean_environment(home, root), text=True,
                                    capture_output=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)["scope"], "package")


if __name__ == "__main__":
    unittest.main()
