"""Offline packaging and explicit installation contracts for TypeSafe."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("typesafe_setup", ROOT / "scripts/setup-typesafe-tools.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class Packaging(unittest.TestCase):
    def test_optional_plugin(self):
        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        entries = [p for p in catalog["plugins"] if p["name"] == setup.PLUGIN]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["policy"]["installation"], "AVAILABLE")
        manifest = json.loads((ROOT / "plugins/typesafe-tools/.codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["version"], "0.1.2")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")

    def test_runtime_is_plugin_owned_and_frozen(self):
        config = json.loads((ROOT / "plugins/typesafe-tools/.mcp.json").read_text())
        server = config["mcpServers"]["typesafe"]
        self.assertEqual(server["command"], "uv")
        self.assertEqual(server["env_vars"], ["CODEX_HOME", "CODEX_SECRETS_DIR"])
        self.assertEqual(server["args"], ["run", "--frozen", "--no-dev", "--no-editable",
                                         "--no-env-file", "--project", "server", "typesafe-mcp"])
        self.assertEqual(server["default_tools_approval_mode"], "auto")


class Installer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.codex = self.home / ".codex"
        self.project = self.home / "project"

    def skill(self, root):
        path = root / "typesafe-ai"
        path.mkdir(parents=True)
        for name in setup.CHECKSUMS:
            (path / name).write_text(name)
        return path

    def test_offline_status_never_executes(self):
        with patch.object(setup, "run", side_effect=AssertionError("network")):
            self.assertEqual(setup.upstream_status(self.home, self.codex, self.project)["state"], "absent")

    def test_setup_status_defers_paid_readiness_to_runtime(self):
        output = io.StringIO()
        with patch.object(setup.sys, "argv", ["setup-typesafe-tools.py", "--status"]), \
                patch.object(setup, "codex_home", return_value=self.codex), \
                patch.object(setup, "upstream_status", return_value={"state": "absent"}), \
                patch.object(setup, "run", side_effect=AssertionError("network")), \
                redirect_stdout(output):
            self.assertEqual(setup.main(), 0)
        status = json.loads(output.getvalue())
        self.assertIsNone(status["paid_ready"])
        self.assertNotIn("blocked", status)
        self.assertIn("typesafe_status", status["readiness"])

    def test_duplicate_distinct_copies_conflict(self):
        self.skill(self.home / ".agents/skills")
        self.skill(self.codex / "skills")
        self.assertEqual(setup.upstream_status(self.home, self.codex, self.project)["state"], "conflict")

    def test_symlink_alias_is_one_copy(self):
        skill = self.skill(self.home / ".agents/skills")
        (self.codex / "skills").mkdir(parents=True)
        (self.codex / "skills/typesafe-ai").symlink_to(skill, target_is_directory=True)
        self.assertEqual(len(setup.candidates(self.home, self.codex, self.project)), 1)

    def test_hash_mismatch_and_extra_files_conflict(self):
        skill = self.skill(self.home / ".agents/skills")
        self.assertEqual(setup.upstream_status(self.home, self.codex, self.project)["state"], "conflict")
        import hashlib
        hashes = {n: hashlib.sha256(n.encode()).hexdigest() for n in setup.CHECKSUMS}
        with patch.object(setup, "CHECKSUMS", hashes):
            self.assertEqual(setup.upstream_status(self.home, self.codex, self.project)["state"], "verified")
            (skill / "untrusted.txt").write_text("extra")
            self.assertEqual(setup.upstream_status(self.home, self.codex, self.project)["state"], "conflict")

    def test_upstream_idempotence(self):
        with patch.object(setup, "upstream_status", return_value={"state": "verified"}), patch.object(setup, "run") as run:
            self.assertEqual(setup.install_upstream(self.home, self.codex, self.project)["action"], "unchanged")
            run.assert_not_called()

    def test_conflict_never_installs(self):
        with patch.object(setup, "upstream_status", return_value={"state": "conflict"}), patch.object(setup, "run") as run:
            with self.assertRaises(setup.SetupError):
                setup.install_upstream(self.home, self.codex, self.project)
            run.assert_not_called()

    def test_single_pinned_install_route(self):
        with patch.object(setup, "upstream_status", side_effect=[{"state": "absent"}, {"state": "verified"}]), patch.object(setup, "run") as run:
            setup.install_upstream(self.home, self.codex, self.project)
            run.assert_called_once_with(["npx", "--yes", "skills@1.7.0", "add", setup.UPSTREAM,
                                         "--skill", "typesafe-ai", "--agent", "codex", "--global", "--yes"], timeout=300)

    def source(self):
        source = self.home / "source"
        for name in [".codex-plugin/plugin.json", ".mcp.json", "server/pyproject.toml", "server/uv.lock"]:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"version":"0.1.2","name":"typesafe-tools"}')
        return source

    def test_export_excludes_caches_and_env(self):
        source = self.source()
        (source / "server/.venv").mkdir()
        (source / "server/.venv/private").write_text("ignored")
        (source / ".env").write_text("ignored")
        files = setup.source_files(source)
        self.assertEqual(len(files), 4)
        destination = self.codex / "local-marketplaces" / setup.MARKETPLACE
        digest = setup.source_digest(source, files)
        setup.export_plugin(source, destination, files, digest)
        catalog = json.loads((destination / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual([p["name"] for p in catalog["plugins"]], ["typesafe-tools"])
        self.assertFalse((destination / "exports" / digest / ".env").exists())

    def installed_fixture(self, source, enabled=True):
        files = setup.source_files(source)
        digest = setup.source_digest(source, files)
        destination = self.codex / "local-marketplaces" / setup.MARKETPLACE
        setup.export_plugin(source, destination, files, digest)
        target = destination / "exports" / digest
        version = json.loads((target / ".codex-plugin/plugin.json").read_text())["version"]
        cache = self.codex / "plugins/cache" / setup.MARKETPLACE / setup.PLUGIN / version
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, cache)
        entry = {"name": setup.PLUGIN, "installed": True, "enabled": enabled,
                 "marketplaceName": setup.MARKETPLACE, "version": version,
                 "source": {"source": "local", "path": str(target)}}
        return entry, target, cache

    def test_disabled_install_preserved_without_mutation(self):
        source = self.source()
        installed = {"installed": [{"name": setup.PLUGIN, "marketplaceName": setup.MARKETPLACE, "enabled": False}]}
        with patch.object(setup, "cli_json", side_effect=[installed, {"marketplaces": []}]), patch.object(setup, "export_plugin") as export:
            result = setup.install_plugin(self.codex, source)
            self.assertEqual(result["action"], "update_skipped_disabled")
            export.assert_not_called()

    def test_repeat_install_noop_preserves_disabled_state(self):
        source = self.source()
        entry, _, _ = self.installed_fixture(source, enabled=False)
        installed = {"installed": [entry]}
        with patch.object(setup, "cli_json", side_effect=[installed, {"marketplaces": []}]), patch.object(setup, "export_plugin") as export:
            result = setup.install_plugin(self.codex, source)
            self.assertEqual(result, {"action": "unchanged", "installed": True, "enabled": False})
            export.assert_not_called()

    def test_existing_published_install_rejects_duplicate(self):
        installed = {"installed": [{"name": setup.PLUGIN, "marketplaceName": "jialuo-codex-toolbox"}]}
        with patch.object(setup, "cli_json", return_value=installed), patch.object(setup, "export_plugin") as export:
            with self.assertRaises(setup.SetupError):
                setup.install_plugin(self.codex, self.source())
            export.assert_not_called()

    def test_success_verifies_discovery_and_only_selected_marketplace(self):
        source = self.source()
        entry, _, _ = self.installed_fixture(source)
        replies = [{"installed": []}, {"marketplaces": []}, {}, {"installed": [entry]}]
        with patch.object(setup, "cli_json", side_effect=replies) as cli, patch.object(setup, "run") as run:
            result = setup.install_plugin(self.codex, source)
            self.assertTrue(result["enabled"])
            self.assertEqual(cli.call_args_list[-1].args[0], ["codex", "plugin", "list", "--marketplace", setup.MARKETPLACE, "--json"])
            self.assertEqual(len(run.call_args_list), 1)
            self.assertIn("marketplace", run.call_args.args[0])

    def test_stale_marker_cannot_hide_tampered_export_or_cache(self):
        source = self.source()
        entry, target, cache = self.installed_fixture(source)
        for root in (target, cache):
            with self.subTest(root=root):
                path = root / ".mcp.json"
                original = path.read_bytes()
                path.write_text("tampered")
                with patch.object(setup, "cli_json", side_effect=[{"installed": [entry]}, {"marketplaces": []}]), patch.object(setup, "run") as run:
                    with self.assertRaises(setup.SetupError):
                        setup.install_plugin(self.codex, source)
                    run.assert_not_called()
                path.write_bytes(original)

    def test_stale_installed_version_rejected(self):
        source = self.source()
        entry, _, _ = self.installed_fixture(source)
        entry["version"] = "0.0.1"
        with patch.object(setup, "cli_json", side_effect=[{"installed": [entry]}, {"marketplaces": []}]):
            with self.assertRaises(setup.SetupError):
                setup.install_plugin(self.codex, source)

    def test_updated_source_keeps_old_export(self):
        source = self.source()
        _, target, _ = self.installed_fixture(source)
        original = (target / ".mcp.json").read_bytes()
        (source / ".mcp.json").write_text('{"changed": true}')
        files = setup.source_files(source)
        digest = setup.source_digest(source, files)
        setup.export_plugin(source, target.parent.parent, files, digest)
        self.assertEqual((target / ".mcp.json").read_bytes(), original)
        self.assertEqual((target.parent / digest / ".mcp.json").read_text(), '{"changed": true}')

    def test_existing_digest_collision_is_never_overwritten(self):
        source = self.source()
        _, target, _ = self.installed_fixture(source)
        (target / ".mcp.json").write_text("tampered")
        files = setup.source_files(source)
        with self.assertRaises(setup.SetupError):
            setup.export_plugin(source, target.parent.parent, files, setup.source_digest(source, files))
        self.assertEqual((target / ".mcp.json").read_text(), "tampered")

    def test_symlink_destination_and_cache_rejected(self):
        source = self.source()
        entry, target, cache = self.installed_fixture(source)
        for root in (target, cache):
            with self.subTest(root=root):
                moved = root.with_name(root.name + "-moved")
                root.rename(moved)
                root.symlink_to(moved, target_is_directory=True)
                with patch.object(setup, "cli_json", side_effect=[{"installed": [entry]}, {"marketplaces": []}]):
                    with self.assertRaises(setup.SetupError):
                        setup.install_plugin(self.codex, source)
                root.unlink()
                moved.rename(root)

    def test_catalog_failure_leaves_previous_export_and_pointer(self):
        source = self.source()
        _, target, _ = self.installed_fixture(source)
        destination = target.parent.parent
        catalog = destination / ".agents/plugins/marketplace.json"
        previous = catalog.read_bytes()
        (source / ".mcp.json").write_text('{"changed": true}')
        files = setup.source_files(source)
        with patch.object(setup, "atomic_text", side_effect=OSError("simulated interrupted publication")):
            with self.assertRaises(OSError):
                setup.export_plugin(source, destination, files, setup.source_digest(source, files))
        self.assertTrue(target.is_dir())
        self.assertEqual(catalog.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
