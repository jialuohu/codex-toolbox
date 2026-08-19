from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable


ROOT = Path(__file__).resolve().parents[1]
DOCMOST = ROOT / "plugins" / "docmost-tools"
SERVER = DOCMOST / "server"


class DocmostToolsIntegrationTests(unittest.TestCase):
    """Pin the generation launcher, tool surface, and setup integration."""

    def run_checker(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, root / "scripts" / "check-codex-toolbox-setup.py"],
            check=False,
            cwd=root,
            text=True,
            capture_output=True,
        )

    def copy_toolbox(self, destination: Path) -> None:
        shutil.copytree(
            ROOT,
            destination,
            ignore=shutil.ignore_patterns(
                ".git",
                ".superpowers",
                ".worktrees",
                ".tmp",
                ".venv",
                ".pytest_cache",
                ".ruff_cache",
                "__pycache__",
            ),
        )

    def assert_checker_rejects(
        self, mutate: Callable[[Path], None], expected_message: str
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_root = Path(temporary_directory) / "toolbox"
            self.copy_toolbox(copied_root)
            mutate(copied_root)
            result = self.run_checker(copied_root)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(expected_message, result.stdout + result.stderr)

    def test_setup_checker_accepts_complete_docmost_contract(self) -> None:
        result = self.run_checker(ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mcp_config_uses_the_checked_in_generation_bootstrap(self) -> None:
        value = json.loads((DOCMOST / ".mcp.json").read_text())
        configured = value["mcpServers"]["docmost"]
        launcher = (SERVER / "scripts" / "docmost-mcp").read_text()

        self.assertEqual(configured["command"], "/bin/bash")
        self.assertEqual(configured["args"], ["server/scripts/docmost-mcp"])
        self.assertEqual(configured["env_vars"], ["CODEX_SECRETS_DIR", "CODEX_HOME"])
        self.assertEqual(configured["tool_timeout_sec"], 900)
        self.assertIn("docmost-tools-generations", launcher)
        self.assertIn("--kind session --mode shared", launcher)
        self.assertIn("--kind generation --mode shared", launcher)
        self.assertIn('exec "$MCP_EXECUTABLE"', launcher)
        self.assertNotIn("uv run", launcher)
        self.assertNotIn("playwright", launcher)

    def test_exact_installed_launcher_initializes_and_lists_all_tools(self) -> None:
        uv = shutil.which("uv")
        self.assertIsNotNone(uv, "uv is required for the launcher integration test")
        assert uv is not None
        expected_tools = {
            "docmost_get_current_user",
            "docmost_list_spaces",
            "docmost_get_space",
            "docmost_search_pages",
            "docmost_get_page",
            "docmost_list_pages",
            "docmost_list_child_pages",
            "docmost_get_comments",
            "docmost_download_attachment",
            "docmost_release_attachment_download",
            "docmost_prepare_workspace_snapshot",
            "docmost_release_workspace_snapshot",
            "docmost_create_page",
            "docmost_update_page_title",
            "docmost_edit_page_text",
            "docmost_create_comment",
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            codex_home = temporary_root / "codex-home"
            plugin_version = json.loads(
                (DOCMOST / ".codex-plugin" / "plugin.json").read_text()
            )["version"]
            installed_plugin = (
                codex_home
                / "plugins"
                / "cache"
                / "jialuo-codex-toolbox"
                / "docmost-tools"
                / plugin_version
            )
            shutil.copytree(
                DOCMOST,
                installed_plugin,
                ignore=shutil.ignore_patterns(
                    ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"
                ),
            )
            server_dir = installed_plugin / "server"
            secrets_dir = temporary_root / "secrets"
            secrets_dir.mkdir(mode=0o700)
            secret_file = secrets_dir / "docmost.env"
            # Invalid settings keep this test fully offline while still exposing
            # the complete MCP tool schema.
            secret_file.write_text("DOCMOST_SESSION_COOKIE=authToken\n")
            secret_file.chmod(0o600)
            environment = os.environ.copy()
            environment.update(
                {
                    "CODEX_HOME": str(codex_home),
                    "CODEX_SECRETS_DIR": str(secrets_dir),
                }
            )
            stamp_source = server_dir / "src" / "docmost_tools" / "runtime_stamp.py"
            fingerprint_result = subprocess.run(
                [sys.executable, str(stamp_source), "fingerprint", str(server_dir)],
                cwd=installed_plugin,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(
                fingerprint_result.returncode,
                0,
                fingerprint_result.stdout + fingerprint_result.stderr,
            )
            fingerprint = fingerprint_result.stdout.strip()
            generation_root = codex_home / "runtime" / "docmost-tools-generations"
            runtime_dir = generation_root / "envs" / fingerprint
            (generation_root / "envs").mkdir(parents=True)
            (generation_root / "locks").mkdir()
            environment["UV_PROJECT_ENVIRONMENT"] = str(runtime_dir)

            lock_check = subprocess.run(
                [uv, "lock", "--check", "--directory", str(server_dir)],
                cwd=installed_plugin,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(lock_check.returncode, 0, lock_check.stdout + lock_check.stderr)
            sync = subprocess.run(
                [
                    uv,
                    "sync",
                    "--frozen",
                    "--no-dev",
                    "--no-editable",
                    "--reinstall-package",
                    "docmost-tools",
                    "--directory",
                    str(server_dir),
                ],
                cwd=installed_plugin,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
            self.assertEqual(sync.returncode, 0, sync.stdout + sync.stderr)
            stamp = subprocess.run(
                [
                    sys.executable,
                    str(stamp_source),
                    "write",
                    str(server_dir),
                    str(runtime_dir / ".docmost-tools-source.sha256"),
                    "--expected",
                    fingerprint,
                ],
                cwd=installed_plugin,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(stamp.returncode, 0, stamp.stdout + stamp.stderr)

            messages = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "generation-test", "version": "1"},
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    }
                )
                + "\n"
            )
            configured = json.loads((installed_plugin / ".mcp.json").read_text())[
                "mcpServers"
            ]["docmost"]
            protocol = subprocess.run(
                [configured["command"], *configured["args"]],
                cwd=installed_plugin,
                env=environment,
                input=messages,
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )

        self.assertEqual(protocol.returncode, 0, protocol.stdout + protocol.stderr)
        responses = [json.loads(line) for line in protocol.stdout.splitlines() if line.strip()]
        initialize = next(response for response in responses if response.get("id") == 1)
        tools_list = next(response for response in responses if response.get("id") == 2)
        self.assertEqual(initialize["result"]["serverInfo"]["name"], "docmost")
        listed_tools = {tool["name"] for tool in tools_list["result"]["tools"]}
        self.assertEqual(len(tools_list["result"]["tools"]), 16)
        self.assertEqual(listed_tools, expected_tools)

    def test_checker_rejects_write_policy_and_transport_regressions(self) -> None:
        def mutate_write(root: Path) -> None:
            path = root / "plugins" / "docmost-tools" / ".mcp.json"
            value = json.loads(path.read_text())
            value["mcpServers"]["docmost"]["tools"]["docmost_create_page"][
                "approval_mode"
            ] = "auto"
            path.write_text(json.dumps(value, indent=2) + "\n")

        def mutate_transport(root: Path) -> None:
            path = root / "plugins" / "docmost-tools" / ".mcp.json"
            value = json.loads(path.read_text())
            value["mcpServers"]["docmost"]["args"].append("unexpected")
            path.write_text(json.dumps(value, indent=2) + "\n")

        for mutate, message in (
            (mutate_write, "prompt-gate exactly the approved write tools"),
            (mutate_transport, "checked-in generation bootstrap"),
        ):
            with self.subTest(mutate=mutate.__name__):
                self.assert_checker_rejects(mutate, message)

    def test_checker_rejects_an_altered_bootstrap(self) -> None:
        def mutate(root: Path) -> None:
            path = (
                root
                / "plugins"
                / "docmost-tools"
                / "server"
                / "scripts"
                / "docmost-mcp"
            )
            path.write_text(path.read_text() + "\ntrue\n")

        self.assert_checker_rejects(mutate, "bootstrap hash must be intentionally approved")

    def test_checker_rejects_generation_install_and_lock_regressions(self) -> None:
        def remove_stamp_publication(root: Path) -> None:
            path = root / "scripts" / "setup-docmost-tools.sh"
            value = path.read_text()
            old = '"$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" write'
            self.assertIn(old, value)
            path.write_text(value.replace(old, '"$SYSTEM_PYTHON" /bin/false', 1))

        def remove_setup_lock(root: Path) -> None:
            path = (
                root
                / "plugins"
                / "docmost-tools"
                / "server"
                / "src"
                / "docmost_tools"
                / "runtime_lock.py"
            )
            value = path.read_text()
            old = 'SETUP_LOCK_NAME = ".setup.lock"'
            self.assertIn(old, value)
            path.write_text(value.replace(old, 'SETUP_LOCK_NAME = ".unsafe"', 1))

        for mutate, message in (
            (remove_stamp_publication, "setup helper must include"),
            (remove_setup_lock, "runtime lock must include"),
        ):
            with self.subTest(mutate=mutate.__name__):
                self.assert_checker_rejects(mutate, message)

    def test_checker_rejects_installed_launcher_verifier_regression(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "scripts" / "setup-codex-toolbox.sh"
            value = path.read_text()
            old = "9d67581f0bf57fd92ba4cf1cf8d8612dde1a82c3ec09bc4d3dddeaea8ad05125"
            self.assertIn(old, value)
            path.write_text(value.replace(old, "0" * 64, 1))

        self.assert_checker_rejects(mutate, "installed Docmost verification must include")

    def test_checker_rejects_restart_documentation_regression(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "README.md"
            value = path.read_text()
            old = "Settings → MCP servers → Restart"
            self.assertIn(old, value)
            path.write_text(value.replace(old, "restart control", 1))

        self.assert_checker_rejects(mutate, "README must document Docmost Settings")


if __name__ == "__main__":
    unittest.main()
