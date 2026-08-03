from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-codex-toolbox-setup.py"


class DocmostToolsIntegrationTests(unittest.TestCase):
    """Pin the published Docmost MCP contract and its setup integration."""

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
                ".git", ".superpowers", ".worktrees", ".venv", ".pytest_cache",
                ".ruff_cache", "__pycache__",
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

    def test_mcp_launcher_uses_the_setup_verified_shared_runtime(self) -> None:
        value = json.loads((ROOT / "plugins/docmost-tools/.mcp.json").read_text())
        server = value["mcpServers"]["docmost"]
        launcher = server["args"][1]

        self.assertIn("UV_PROJECT_ENVIRONMENT", launcher)
        self.assertIn('DOCMOST_RUNTIME_PARENT="$DOCMOST_CODEX_ROOT/runtime"', launcher)
        self.assertIn('DOCMOST_RUNTIME_DIR="$DOCMOST_RUNTIME_PARENT/docmost-tools"', launcher)
        self.assertIn("run --frozen --no-sync", launcher)
        self.assertIn("docmost-runtime-stamp", launcher)
        self.assertIn(".docmost-tools-source.sha256", launcher)
        self.assertIn("CODEX_HOME", server["env_vars"])
        self.assertIn("if SECRET_MODE=", launcher)
        self.assertIn("elif SECRET_MODE=", launcher)
        self.assertNotIn("|| stat -c", launcher)

    def test_setup_checker_rejects_docmost_write_approval_regressions(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "plugins/docmost-tools/.mcp.json"
            value = json.loads(path.read_text())
            value["mcpServers"]["docmost"]["tools"]["create_page"]["approval_mode"] = "auto"
            path.write_text(json.dumps(value, indent=2) + "\n")

        self.assert_checker_rejects(
            mutate,
            "docmost create_page must require approval",
        )

    def test_setup_checker_rejects_docmost_registration_regressions(self) -> None:
        def remove_marketplace(root: Path) -> None:
            path = root / ".agents/plugins/marketplace.json"
            value = json.loads(path.read_text())
            value["plugins"] = [
                plugin for plugin in value["plugins"] if plugin.get("name") != "docmost-tools"
            ]
            path.write_text(json.dumps(value, indent=2) + "\n")

        def remove_default(root: Path) -> None:
            path = root / "scripts/setup-codex-toolbox.sh"
            path.write_text(path.read_text().replace('  "docmost-tools"\n', "", 1))

        def remove_managed_server(root: Path) -> None:
            path = root / "scripts/setup-codex-toolbox.sh"
            path.write_text(path.read_text().replace('  "docmost"\n', "", 1))

        cases = (
            (remove_marketplace, "marketplace must include docmost-tools"),
            (remove_default, "setup script must refresh docmost-tools by default"),
            (remove_managed_server, "setup script must manage the docmost MCP migration"),
        )
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                self.assert_checker_rejects(mutate, expected)

    def test_setup_checker_rejects_docmost_launcher_boundary_regressions(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "plugins/docmost-tools/.mcp.json"
            value = json.loads(path.read_text())
            server = value["mcpServers"]["docmost"]
            server["cwd"] = "server"
            server["env_vars"].remove("CODEX_HOME")
            path.write_text(json.dumps(value, indent=2) + "\n")

        self.assert_checker_rejects(mutate, "docmost MCP must use plugin-root relative cwd")

    def test_setup_checker_rejects_an_invalid_zsh_argument_shape(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "plugins/docmost-tools/.mcp.json"
            value = json.loads(path.read_text())
            value["mcpServers"]["docmost"]["args"][0] = \
                "--definitely-not-a-zsh-option"
            path.write_text(json.dumps(value, indent=2) + "\n")

        self.assert_checker_rejects(
            mutate,
            "docmost MCP must use exactly one nonempty zsh -lc launcher",
        )

    def test_setup_checker_rejects_docmost_secret_and_runtime_guard_regressions(self) -> None:
        def replace_launcher(root: Path, old: str, new: str) -> None:
            path = root / "plugins/docmost-tools/.mcp.json"
            value = json.loads(path.read_text())
            launcher = value["mcpServers"]["docmost"]["args"][1]
            self.assertIn(old, launcher)
            value["mcpServers"]["docmost"]["args"][1] = launcher.replace(old, new, 1)
            path.write_text(json.dumps(value, indent=2) + "\n")

        cases = (
            (
                lambda root: replace_launcher(
                    root,
                    '[ ! -f "$SECRET_FILE" ] || [ -L "$SECRET_FILE" ]',
                    '[ ! -f "$SECRET_FILE" ]',
                ),
                "docmost MCP launcher must include [ ! -f",
            ),
            (
                lambda root: replace_launcher(
                    root,
                    'if [ "$SECRET_MODE" != 600 ]',
                    'if [ "$SECRET_MODE" != 644 ]',
                ),
                "docmost MCP launcher must include if [",
            ),
            (
                lambda root: replace_launcher(
                    root,
                    "readonly DOCMOST_CODEX_ROOT DOCMOST_SECRETS_ROOT DOCMOST_RUNTIME_PARENT DOCMOST_RUNTIME_DIR",
                    "readonly DOCMOST_RUNTIME_DIR",
                ),
                "docmost MCP launcher must include readonly DOCMOST_CODEX_ROOT",
            ),
            (
                lambda root: replace_launcher(
                    root,
                    'docmost-runtime-stamp" check',
                    'docmost-runtime-stamp" write',
                ),
                "docmost MCP launcher must include docmost-runtime-stamp",
            ),
        )
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                self.assert_checker_rejects(mutate, expected)

    def test_setup_checker_rejects_docmost_install_transaction_regressions(self) -> None:
        def replace_helper(root: Path, old: str, new: str) -> None:
            path = root / "scripts/setup-docmost-tools.sh"
            helper = path.read_text()
            self.assertIn(old, helper)
            path.write_text(helper.replace(old, new, 1))

        def replace_runtime_lock(root: Path, old: str, new: str) -> None:
            path = (
                root
                / "plugins/docmost-tools/server/src/docmost_tools/runtime_lock.py"
            )
            runtime_lock = path.read_text()
            self.assertIn(old, runtime_lock)
            path.write_text(runtime_lock.replace(old, new, 1))

        cases = (
            (
                lambda root: replace_helper(
                    root,
                    '[ ! -L "$RUNTIME_PARENT" ]',
                    '[ -e "$RUNTIME_PARENT" ]',
                ),
                "Docmost setup must reject a symlinked runtime parent",
            ),
            (
                lambda root: replace_helper(
                    root,
                    '[ ! -L "$UV_PROJECT_ENVIRONMENT" ]',
                    '[ -d "$UV_PROJECT_ENVIRONMENT" ]',
                ),
                "Docmost setup must reject a symlinked runtime directory",
            ),
            (
                lambda root: replace_helper(
                    root,
                    "--reinstall-package docmost-tools",
                    "",
                ),
                "Docmost setup must force reinstall the non-editable package",
            ),
            (
                lambda root: replace_runtime_lock(
                    root,
                    "os.set_inheritable(descriptor, True)",
                    "os.set_inheritable(descriptor, False)",
                ),
                "Docmost runtime lock must pass the held descriptor",
            ),
            (
                lambda root: replace_runtime_lock(
                    root,
                    "environment[LOCK_FD_ENV] = str(descriptor)",
                    "environment.pop(LOCK_FD_ENV, None)",
                ),
                "Docmost runtime lock must pass the held descriptor",
            ),
            (
                lambda root: replace_helper(
                    root,
                    "run_locked shared --check-locked",
                    "bash \"$ROOT/scripts/setup-docmost-tools.sh\" --check-locked",
                ),
                "Docmost setup must keep check and status under shared locks",
            ),
            (
                lambda root: replace_helper(
                    root,
                    "run_locked exclusive --login-locked",
                    "run_locked shared --login-locked",
                ),
                "Docmost setup must keep install, login, and logout under exclusive locks",
            ),
            (
                lambda root: replace_helper(
                    root,
                    "run_locked exclusive --install-locked",
                    "bash \"$ROOT/scripts/setup-docmost-tools.sh\" --install-locked",
                ),
                "Docmost setup must keep install, login, and logout under exclusive locks",
            ),
            (
                lambda root: replace_runtime_lock(
                    root,
                    "(inherited.st_dev, inherited.st_ino) != (current.st_dev, current.st_ino)",
                    "False",
                ),
                "Docmost runtime lock must validate the inherited descriptor identity",
            ),
            (
                lambda root: replace_runtime_lock(
                    root,
                    "return not shared_probe_succeeds and not exclusive_probe_succeeds",
                    "return True",
                ),
                "Docmost runtime lock must validate the inherited shared or exclusive mode",
            ),
        )
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                self.assert_checker_rejects(mutate, expected)

    def test_setup_checker_rejects_a_browser_launch_in_the_stdio_launcher(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "plugins/docmost-tools/.mcp.json"
            value = json.loads(path.read_text())
            launcher = value["mcpServers"]["docmost"]["args"][1]
            value["mcpServers"]["docmost"]["args"][1] = launcher.replace(
                "set -euo pipefail; ",
                "set -euo pipefail; docmost-auth status; ",
                1,
            )
            path.write_text(json.dumps(value, indent=2) + "\n")

        self.assert_checker_rejects(
            mutate,
            "docmost MCP launcher must not launch browser authentication",
        )
