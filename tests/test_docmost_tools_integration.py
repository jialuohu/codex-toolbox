from __future__ import annotations

import json
import os
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

    def test_exact_installed_launcher_initializes_and_lists_all_tools(self) -> None:
        uv = shutil.which("uv")
        self.assertIsNotNone(uv, "uv is required for the installed launcher integration test")
        assert uv is not None
        expected_tools = {
            "get_current_user",
            "list_spaces",
            "get_space",
            "search_pages",
            "get_page",
            "list_pages",
            "list_child_pages",
            "get_comments",
            "create_page",
            "update_page_title",
            "create_comment",
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            codex_home = temporary_root / "codex-home"
            plugin_version = json.loads(
                (
                    ROOT
                    / "plugins"
                    / "docmost-tools"
                    / ".codex-plugin"
                    / "plugin.json"
                ).read_text()
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
                ROOT / "plugins" / "docmost-tools",
                installed_plugin,
                ignore=shutil.ignore_patterns(
                    ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"
                ),
            )
            server_dir = installed_plugin / "server"
            secrets_dir = temporary_root / "secrets"
            secrets_dir.mkdir(mode=0o700)
            secret_file = secrets_dir / "docmost.env"
            # Deliberately omit DOCMOST_BASE_URL so startup cannot open a browser
            # or contact Docmost; the MCP surface must still initialize exactly.
            secret_file.write_text("DOCMOST_SESSION_COOKIE=authToken\n")
            secret_file.chmod(0o600)
            runtime_dir = codex_home / "runtime" / "docmost-tools"
            environment = os.environ.copy()
            environment.update(
                {
                    "CODEX_HOME": str(codex_home),
                    "CODEX_SECRETS_DIR": str(secrets_dir),
                    "UV_PROJECT_ENVIRONMENT": str(runtime_dir),
                }
            )

            lock_check = subprocess.run(
                [uv, "lock", "--check", "--directory", str(server_dir)],
                cwd=installed_plugin,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(
                lock_check.returncode,
                0,
                lock_check.stdout + lock_check.stderr,
            )
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

            runtime_lock_helper = runtime_dir / "libexec" / "runtime_lock.py"
            runtime_lock_helper.parent.mkdir()
            shutil.copy2(
                server_dir / "src" / "docmost_tools" / "runtime_lock.py",
                runtime_lock_helper,
            )
            fingerprint = subprocess.run(
                [
                    str(runtime_dir / "bin" / "docmost-runtime-stamp"),
                    "fingerprint",
                    str(server_dir),
                ],
                cwd=installed_plugin,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(
                fingerprint.returncode,
                0,
                fingerprint.stdout + fingerprint.stderr,
            )
            stamp = subprocess.run(
                [
                    str(runtime_dir / "bin" / "docmost-runtime-stamp"),
                    "write",
                    str(server_dir),
                    str(runtime_dir / ".docmost-tools-source.sha256"),
                    "--expected",
                    fingerprint.stdout.strip(),
                ],
                cwd=installed_plugin,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(stamp.returncode, 0, stamp.stdout + stamp.stderr)

            installed_config = json.loads((installed_plugin / ".mcp.json").read_text())
            launcher = installed_config["mcpServers"]["docmost"]
            messages = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "installed-layout-test", "version": "1"},
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
            protocol = subprocess.run(
                [launcher["command"], *launcher["args"]],
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
        self.assertEqual(len(tools_list["result"]["tools"]), 11)
        self.assertEqual(listed_tools, expected_tools)

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
                lambda root: replace_helper(
                    root,
                    'run_uv lock --check --directory "$SERVER_DIR"',
                    "true",
                ),
                "Docmost setup must check lock freshness before synchronization",
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

    def test_setup_checker_rejects_marketplace_source_as_installed_distribution(
        self,
    ) -> None:
        def mutate(root: Path) -> None:
            path = root / "scripts/setup-codex-toolbox.sh"
            setup = path.read_text()
            old = '"$CODEX_BIN" mcp get docmost --json'
            self.assertIn(old, setup)
            path.write_text(
                setup.replace(
                    old,
                    '"$CODEX_BIN" plugin list --marketplace "$MARKETPLACE_NAME" --json',
                    1,
                )
            )

        self.assert_checker_rejects(
            mutate,
            "toolbox setup must resolve Docmost from the installed MCP cwd",
        )

    def test_setup_checker_rejects_docmost_distribution_documentation_regressions(
        self,
    ) -> None:
        def replace_readme(root: Path, old: str, new: str) -> None:
            path = root / "README.md"
            readme = path.read_text()
            self.assertIn(old, readme)
            path.write_text(readme.replace(old, new, 1))

        cases = (
            (
                lambda root: replace_readme(
                    root,
                    "plus `uv` and `python3` on `PATH`",
                    "plus package tooling",
                ),
                "README must document Docmost uv and Python prerequisites",
            ),
            (
                lambda root: replace_readme(
                    root,
                    "Marketplace `source.path` is not treated as the",
                    "The marketplace source is treated as the",
                ),
                "README must distinguish installed Docmost cwd from marketplace source",
            ),
        )
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                self.assert_checker_rejects(mutate, expected)

    def test_setup_checker_rejects_auth_recovery_guidance_regressions(self) -> None:
        recovery_command = (
            'CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" '
            '"$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login'
        )
        close_instruction = "Before login or logout, close the active Codex task"
        fresh_instruction = "After login or logout, start a fresh task or reconnect Docmost"

        def replace_setup(root: Path, old: str, new: str) -> None:
            path = root / "scripts/setup-docmost-tools.sh"
            value = path.read_text()
            self.assertIn(old, value)
            path.write_text(value.replace(old, new, 1))

        def remove_readme_instruction(root: Path, instruction: str) -> None:
            path = root / "README.md"
            value = path.read_text()
            if recovery_command not in value:
                old_command = (
                    '"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/'
                    'docmost-auth" login'
                )
                self.assertIn(old_command, value)
                value = value.replace(
                    old_command,
                    f"{close_instruction}.\n\n{recovery_command}\n\n{fresh_instruction}.",
                    1,
                )
            self.assertIn(instruction, value)
            path.write_text(value.replace(instruction, "", 1))

        cases = (
            (
                lambda root: replace_setup(
                    root,
                    recovery_command,
                    recovery_command.replace("--login", "--status"),
                ),
                "Docmost setup must preserve the canonical auth recovery command",
            ),
            (
                lambda root: replace_setup(
                    root,
                    "Authentication required. Close the active task",
                    "Authentication required. Keep the active task open",
                ),
                "Docmost setup must preserve the canonical AUTH_REQUIRED sentence",
            ),
            (
                lambda root: remove_readme_instruction(root, close_instruction),
                "README must tell users to close the active task before Docmost auth changes",
            ),
            (
                lambda root: remove_readme_instruction(root, fresh_instruction),
                "README must tell users to start a fresh task after Docmost auth changes",
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
