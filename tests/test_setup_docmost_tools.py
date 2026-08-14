#!/usr/bin/env python3
"""Behavioral tests for the isolated Docmost runtime helper."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-docmost-tools.sh"
RECOVERY_COMMAND = (
    'CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" '
    '"$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login'
)
RECOVERY_SENTENCE = (
    "Authentication required. Close the active task, run "
    f"`{RECOVERY_COMMAND}`, then start a fresh task or reconnect Docmost."
)


class SetupDocmostToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.home = Path(self.tempdir.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.secrets_dir = self.home / "secrets"
        self.secrets_dir.mkdir(mode=0o700)
        self.codex_home = self.home / "codex-home"
        self.plugin_version = json.loads(
            (
                ROOT
                / "plugins"
                / "docmost-tools"
                / ".codex-plugin"
                / "plugin.json"
            ).read_text()
        )["version"]
        self.marketplace_plugin_root = (
            self.home / "marketplace-source" / "docmost-tools"
        )
        self.installed_plugin_root = (
            self.codex_home
            / "plugins"
            / "cache"
            / "jialuo-codex-toolbox"
            / "docmost-tools"
            / self.plugin_version
        )
        self.mcp_fixture = self.home / "docmost-mcp.json"
        self.log_file = self.home / "commands.log"
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin_dir}:/usr/bin:/bin",
                "CODEX_SECRETS_DIR": str(self.secrets_dir),
                "CODEX_HOME": str(self.codex_home),
                "FAKE_DOCMOST_LOG": str(self.log_file),
                "FAKE_DOCMOST_PLUGIN_ROOT": str(self.marketplace_plugin_root),
                "FAKE_DOCMOST_MCP_JSON": str(self.mcp_fixture),
            }
        )

    def write_executable(self, name: str, body: str) -> Path:
        path = self.bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def install_fake_uv(self, *, preinstalled: bool = False) -> None:
        runtime_template = self.home / "fake-docmost-runtime"
        runtime_bin = runtime_template / "bin"
        runtime_bin.mkdir(parents=True)
        self.env["FAKE_DOCMOST_RUNTIME_TEMPLATE"] = str(runtime_template)
        self.env["FAKE_DOCMOST_RUNTIME_LOCK_SOURCE"] = str(
            ROOT
            / "plugins"
            / "docmost-tools"
            / "server"
            / "src"
            / "docmost_tools"
            / "runtime_lock.py"
        )

        def write_runtime_executable(name: str, body: str) -> Path:
            path = runtime_bin / name
            path.write_text(body)
            path.chmod(0o755)
            return path

        self.write_executable(
            "uv",
            "#!/bin/sh\n"
            "printf 'UV_PROJECT_ENVIRONMENT=%s %s\\n' \"${UV_PROJECT_ENVIRONMENT:-}\" \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "if [ \"${FAKE_DOCMOST_LOCK:-fresh}\" = stale ] && [ \"$1\" = lock ] && [ \"$2\" = --check ]; then exit 1; fi\n"
            "if [ \"${FAKE_DOCMOST_SYNC:-ready}\" = fail ] && echo \"$*\" | grep -q 'sync --frozen'; then exit 1; fi\n"
            "if [ -n \"${FAKE_DOCMOST_SYNC_STARTED:-}\" ] && echo \"$*\" | grep -q 'sync --frozen --no-dev --no-editable'; then\n"
            "  : > \"$FAKE_DOCMOST_SYNC_STARTED\"\n"
            "  while [ ! -e \"$FAKE_DOCMOST_SYNC_RELEASE\" ]; do /bin/sleep 0.01; done\n"
            "fi\n"
            "if echo \"$*\" | grep -q 'sync --frozen --no-dev --no-editable'; then\n"
            "  mkdir -p \"$UV_PROJECT_ENVIRONMENT\"\n"
            "  cp -R \"$FAKE_DOCMOST_RUNTIME_TEMPLATE/.\" \"$UV_PROJECT_ENVIRONMENT/\"\n"
            "  if [ -n \"${FAKE_DOCMOST_SYNC_MUTATE_SOURCE:-}\" ]; then\n"
            "    printf '\\n' >> \"$FAKE_DOCMOST_SYNC_MUTATE_SOURCE\"\n"
            "  fi\n"
            "fi\n",
        )
        write_runtime_executable(
            "python",
            "#!/bin/sh\n"
            "printf 'runtime-python %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "case \"$*\" in\n"
            "  *'playwright install chromium'*)\n"
            "    [ \"${FAKE_DOCMOST_CHROMIUM_INSTALL:-ready}\" = ready ] || exit 1\n"
            "    ;;\n"
            "  *'DocmostSettings.model_validate'*)\n"
            "    grep -q '^DOCMOST_BASE_URL=' \"$CODEX_SECRETS_DIR/docmost.env\" || exit 1\n"
            "    ;;\n"
            "  *'chromium.executable_path'*)\n"
            "    if [ \"${FAKE_DOCMOST_CHROMIUM:-ready}\" != ready ]; then\n"
            "      printf '%s\\n' 'Docmost Chromium executable is missing; run --install' >&2\n"
            "      exit 1\n"
            "    fi\n"
            "    ;;\n"
            "esac\n"
        )
        write_runtime_executable(
            "docmost-runtime-lock",
            "#!/bin/sh\n"
            "exec /usr/bin/python3 \"$FAKE_DOCMOST_RUNTIME_LOCK_SOURCE\" \"$@\"\n",
        )
        write_runtime_executable(
            "docmost-mcp",
            "#!/bin/sh\n"
            "printf 'docmost-mcp %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n",
        )
        write_runtime_executable(
            "docmost-smoke",
            "#!/bin/sh\n"
            "printf 'docmost-smoke %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "[ -z \"${FAKE_DOCMOST_STDERR_WARNING:-}\" ] || printf '%s\\n' 'harmless runtime warning' >&2\n"
            "if [ \"${FAKE_DOCMOST_AUTH:-ready}\" = auth ] && [ ! -f \"$CODEX_SECRETS_DIR/docmost/.authenticated\" ]; then\n"
            "  printf '%s\\n' '{\"ok\":false,\"error\":{\"code\":\"AUTH_REQUIRED\"}}'\n"
            "  exit 1\n"
            "fi\n"
            "if [ \"${FAKE_DOCMOST_AUTH:-ready}\" = upstream ]; then\n"
            "  printf '%s\\n' '{\"ok\":false,\"error\":{\"code\":\"upstream_error\"}}'\n"
            "  exit 1\n"
            "fi\n"
            "printf '%s\\n' '{\"ok\":true,\"data\":{\"current_user\":{},\"spaces\":[]}}'\n"
        )
        write_runtime_executable(
            "docmost-auth-internal",
            "#!/bin/sh\n"
            "printf 'docmost-auth-internal %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "case \"$1\" in\n"
            "  login)\n"
            "    mkdir -p \"$CODEX_SECRETS_DIR/docmost/browser-profile\"\n"
            "    chmod 700 \"$CODEX_SECRETS_DIR/docmost/browser-profile\"\n"
            "    : > \"$CODEX_SECRETS_DIR/docmost/.authenticated\"\n"
            "    ;;\n"
            "  logout) rm -rf \"$CODEX_SECRETS_DIR/docmost/browser-profile\" ;;\n"
            "esac\n"
            "printf '%s\\n' '{\"ok\":true,\"data\":{}}'\n"
        )
        if preinstalled:
            self.prepare_fake_generation(runtime_template)

    def prepare_fake_generation(self, runtime_template: Path | None = None) -> Path:
        template = runtime_template or self.home / "fake-docmost-runtime"
        runtime = self.generation_runtime()
        runtime.parent.mkdir(parents=True, exist_ok=True)
        (runtime.parent.parent / "locks").mkdir(parents=True, exist_ok=True)
        if runtime.exists():
            shutil.rmtree(runtime)
        shutil.copytree(template, runtime)
        auth_tool = runtime / "bin" / "docmost-auth"
        auth_tool.write_bytes(
            (
                ROOT
                / "plugins"
                / "docmost-tools"
                / "server"
                / "scripts"
                / "docmost-auth"
            ).read_bytes()
        )
        auth_tool.chmod(0o755)
        subprocess.run(
            [
                "/usr/bin/python3",
                str(
                    ROOT
                    / "plugins"
                    / "docmost-tools"
                    / "server"
                    / "src"
                    / "docmost_tools"
                    / "runtime_stamp.py"
                ),
                "write",
                str(ROOT / "plugins" / "docmost-tools" / "server"),
                str(runtime / ".docmost-tools-source.sha256"),
                "--expected",
                self.source_fingerprint(),
            ],
            check=True,
        )
        return runtime

    def source_fingerprint(self, server_dir: Path | None = None) -> str:
        source = server_dir or ROOT / "plugins" / "docmost-tools" / "server"
        result = subprocess.run(
            [
                "/usr/bin/python3",
                str(source / "src" / "docmost_tools" / "runtime_stamp.py"),
                "fingerprint",
                str(source),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def generation_runtime(self, server_dir: Path | None = None) -> Path:
        return (
            self.codex_home
            / "runtime"
            / "docmost-tools-generations"
            / "envs"
            / self.source_fingerprint(server_dir)
        )

    def write_fake_mcp(self, **transport_overrides: object) -> None:
        configured = json.loads(
            (self.installed_plugin_root / ".mcp.json").read_text()
        )["mcpServers"]["docmost"]
        transport = {
            "type": "stdio",
            "command": configured["command"],
            "args": configured["args"],
            "env_vars": configured["env_vars"],
            "cwd": f"{self.installed_plugin_root}/.",
            **transport_overrides,
        }
        self.mcp_fixture.write_text(
            json.dumps(
                {
                    "name": "docmost",
                    "enabled": True,
                    "disabled_reason": None,
                    "transport": transport,
                }
            )
            + "\n"
        )

    def install_fake_node(self) -> None:
        self.write_executable(
            "node",
            "#!/bin/sh\n"
            "printf 'node %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "if [ \"$1\" = -p ]; then printf '20\\n'; exit 0; fi\n"
            "case \"$*\" in\n"
            "  *'verify-drawio-runtime.mjs --package-tree-sha256'*) printf '%s\\n' '9b8fed587fd1bc61041c4a57ec536ad653673e8f413141d7ff6ef0b03754ac6d' ;;\n"
            "  *'verify-drawio-runtime.mjs'*) exit 0 ;;\n"
            "  *'node_modules/@drawio/mcp/src/index.js --version'*) printf '1.4.0\\n' ;;\n"
            "esac\n",
        )

    def install_fake_drawio_runtime_prerequisites(self) -> None:
        self.write_executable(
            "npm",
            "#!/bin/sh\n"
            "printf 'npm %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "prefix=\n"
            "previous=\n"
            "for argument in \"$@\"; do\n"
            "  if [ \"$previous\" = --prefix ]; then prefix=\"$argument\"; fi\n"
            "  previous=\"$argument\"\n"
            "done\n"
            "if [ \"${1:-}\" = ci ]; then\n"
            "  mkdir -p \"$prefix/node_modules/@drawio/mcp/src\"\n"
            "  : > \"$prefix/node_modules/@drawio/mcp/src/index.js\"\n"
            "fi\n",
        )
        self.write_executable(
            "curl",
            "#!/bin/sh\n"
            "printf 'curl %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "output=\n"
            "previous=\n"
            "for argument in \"$@\"; do\n"
            "  if [ \"$previous\" = --output ]; then output=\"$argument\"; fi\n"
            "  previous=\"$argument\"\n"
            "done\n"
            "[ -n \"$output\" ] || exit 2\n"
            "/bin/dd if=/dev/zero of=\"$output\" bs=1 count=0 seek=4776086 2>/dev/null\n",
        )
        self.write_executable(
            "shasum",
            "#!/bin/sh\n"
            "case \"${3:-}\" in\n"
            "  */search-index.json) printf '%s  %s\\n' '09b84516025e46238e5dd47465cc96ecfd96134ea853ace1063e1ca19dd34601' \"$3\" ;;\n"
            "  *) printf '%064d  %s\\n' 0 \"${3:-}\" ;;\n"
            "esac\n",
        )

    def install_fake_codex(self) -> None:
        self.install_fake_node()
        self.install_fake_drawio_runtime_prerequisites()
        if not self.marketplace_plugin_root.exists():
            shutil.copytree(
                ROOT / "plugins" / "docmost-tools",
                self.marketplace_plugin_root,
                ignore=shutil.ignore_patterns(
                    ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"
                ),
            )
        if not self.installed_plugin_root.exists():
            shutil.copytree(
                self.marketplace_plugin_root,
                self.installed_plugin_root,
                ignore=shutil.ignore_patterns(
                    ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"
                ),
            )
        self.write_fake_mcp()
        self.write_executable(
            "codex",
            "#!/bin/sh\n"
            "printf 'codex %s\\n' \"$*\" >> \"$FAKE_DOCMOST_LOG\"\n"
            "if [ \"$1\" = --version ]; then printf 'codex test\\n'; exit 0; fi\n"
            "if [ \"$1\" = mcp ] && [ \"$2\" = get ] && [ \"$3\" = docmost ] && [ \"$4\" = --json ]; then\n"
            "  [ \"${FAKE_DOCMOST_MCP_GET:-present}\" = present ] || exit 1\n"
            "  /bin/cat \"$FAKE_DOCMOST_MCP_JSON\"\n"
            "  exit 0\n"
            "fi\n"
            "case \"$*\" in\n"
            "  *' --json'*) printf '%s\\n' \"{\\\"marketplaces\\\":[],\\\"installed\\\":[{\\\"name\\\":\\\"docmost-tools\\\",\\\"marketplaceName\\\":\\\"jialuo-codex-toolbox\\\",\\\"installed\\\":true,\\\"source\\\":{\\\"source\\\":\\\"local\\\",\\\"path\\\":\\\"$FAKE_DOCMOST_PLUGIN_ROOT\\\"}}]}\" ;;\n"
            "esac\n",
        )

    def write_env(self, mode: int = 0o600) -> Path:
        path = self.secrets_dir / "docmost.env"
        path.write_text("DOCMOST_BASE_URL=https://docs.example.test\nDOCMOST_SESSION_COOKIE=session\n")
        path.chmod(mode)
        return path

    def run_script(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), mode],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def create_private_browser_profile(self) -> Path:
        parent = self.secrets_dir / "docmost"
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
        profile = parent / "browser-profile"
        profile.mkdir(mode=0o700)
        profile.chmod(0o700)
        return profile

    def start_shared_runtime_holder(
        self,
    ) -> tuple[subprocess.Popen[str], Path]:
        runtime_parent = self.codex_home / "runtime"
        runtime_parent.mkdir(parents=True, exist_ok=True)
        lock_helper = (
            ROOT
            / "plugins"
            / "docmost-tools"
            / "server"
            / "src"
            / "docmost_tools"
            / "runtime_lock.py"
        )
        started = self.home / "shared-lock-started"
        release = self.home / "shared-lock-release"
        started.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        holder = subprocess.Popen(
            [
                "/usr/bin/python3",
                str(lock_helper),
                "--mode",
                "shared",
                "--root",
                str(runtime_parent),
                "--",
                "/bin/sh",
                "-c",
                ': > "$1"; while [ ! -e "$2" ]; do /bin/sleep 0.01; done',
                "holder",
                str(started),
                str(release),
            ],
            cwd=ROOT,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not started.exists():
            if holder.poll() is not None:
                stdout, stderr = holder.communicate()
                self.fail("shared lock holder exited early: " + stdout + stderr)
            if time.monotonic() >= deadline:
                holder.terminate()
                stdout, stderr = holder.communicate()
                self.fail("shared lock holder did not start: " + stdout + stderr)
            time.sleep(0.01)

        def stop_holder() -> None:
            release.touch()
            try:
                holder.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                holder.terminate()
                holder.communicate(timeout=5)

        self.addCleanup(stop_holder)
        return holder, release

    def test_check_validates_the_locked_runtime_and_chromium_executable(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()

        result = self.run_script("--check")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.log_file.read_text()
        self.assertIn("lock --check", commands)
        self.assertIn("chromium.executable_path", commands)
        self.assertNotIn("uv run", commands)
        self.assertLess(commands.index("lock --check"), commands.index("DocmostSettings.model_validate"))

    def test_check_rejects_a_stale_dependency_lock_before_sync(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()
        self.env["FAKE_DOCMOST_LOCK"] = "stale"

        result = self.run_script("--check")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Docmost dependency lock is stale", result.stderr)
        commands = self.log_file.read_text()
        self.assertIn("lock --check", commands)
        self.assertNotIn("sync --frozen", commands)

    def test_check_fails_when_chromium_executable_is_missing(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()
        self.env["FAKE_DOCMOST_CHROMIUM"] = "missing"

        result = self.run_script("--check")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Chromium executable is missing", result.stderr)
        self.assertIn("chromium.executable_path", self.log_file.read_text())

    def test_check_redacts_invalid_docmost_settings(self) -> None:
        self.install_fake_uv(preinstalled=True)
        env_file = self.write_env()
        env_file.write_text("DOCMOST_SESSION_COOKIE=authToken\n")
        self.create_private_browser_profile()

        result = self.run_script("--check")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Docmost configuration is invalid", result.stderr)

    def test_status_requires_a_private_env_file_without_creating_a_profile(self) -> None:
        self.install_fake_uv(preinstalled=True)
        env_file = self.write_env(mode=0o644)

        result = self.run_script("--status")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("docmost.env must have mode 600", result.stderr)
        self.assertFalse((self.secrets_dir / "docmost").exists())
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o644)

    def test_install_rejects_a_symlinked_env_file_before_invoking_uv(self) -> None:
        self.install_fake_uv()
        target = self.home / "outside.env"
        target.write_text("DOCMOST_BASE_URL=https://docs.example.test\n")
        target.chmod(0o600)
        (self.secrets_dir / "docmost.env").symlink_to(target)

        result = self.run_script("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("docmost.env must not be a symlink", result.stderr)
        self.assertFalse(self.log_file.exists(), "install must reject the env before invoking uv")

    def test_install_uses_locked_uv_and_installs_playwright(self) -> None:
        self.install_fake_uv()
        self.write_env()

        result = self.run_script("--install")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.log_file.read_text()
        expected_runtime = self.generation_runtime()
        self.assertIn(f"UV_PROJECT_ENVIRONMENT={expected_runtime}", commands)
        self.assertIn("sync --frozen --no-dev --no-editable", commands)
        self.assertIn("--reinstall-package docmost-tools", commands)
        self.assertNotIn("uv run", commands)
        self.assertIn("playwright install chromium", commands)
        stamp = expected_runtime / ".docmost-tools-source.sha256"
        self.assertEqual(stamp.read_text().strip(), self.source_fingerprint())
        profile = self.secrets_dir / "docmost"
        self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o700)

    def test_install_succeeds_while_a_legacy_session_lock_is_held(self) -> None:
        self.install_fake_uv()
        self.write_env()
        holder, release = self.start_shared_runtime_holder()

        result = self.run_script("--install")
        release.touch()
        holder.communicate(timeout=5)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            (self.generation_runtime() / ".docmost-tools-source.sha256").is_file()
        )

    def test_mcp_bootstrap_executes_the_generation_without_uv(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        launcher = (
            ROOT
            / "plugins"
            / "docmost-tools"
            / "server"
            / "scripts"
            / "docmost-mcp"
        )

        result = subprocess.run(
            [str(launcher)],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.log_file.read_text()
        self.assertIn("docmost-mcp", commands)
        self.assertNotIn("uv ", commands)

    def test_install_rejects_a_stale_dependency_lock_before_sync(self) -> None:
        self.install_fake_uv()
        self.write_env()
        self.env["FAKE_DOCMOST_LOCK"] = "stale"

        result = self.run_script("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Docmost dependency lock is stale", result.stderr)
        commands = self.log_file.read_text()
        self.assertIn("lock --check", commands)
        self.assertNotIn("sync --frozen", commands)

    def test_install_rejects_a_symlinked_setup_lock_without_invoking_uv(self) -> None:
        self.install_fake_uv()
        self.write_env()
        outside = self.home / "outside-lock"
        outside.write_text("unchanged")
        generation_root = (
            self.codex_home / "runtime" / "docmost-tools-generations"
        )
        (generation_root / "envs").mkdir(parents=True)
        (generation_root / "locks").mkdir()
        lock = generation_root / ".setup.lock"
        lock.symlink_to(outside)

        result = self.run_script("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("runtime lock configuration is invalid", result.stderr)
        self.assertEqual(outside.read_text(), "unchanged")
        self.assertFalse(self.log_file.exists(), "unsafe lock must be rejected before uv")

    def test_install_rejects_a_symlinked_runtime_root_without_mutating_target(self) -> None:
        self.write_executable(
            "uv",
            "#!/bin/sh\nprintf '%s\\n' unsafe >> \"$FAKE_DOCMOST_LOG\"\n",
        )
        self.write_env()
        runtime_parent = self.codex_home / "runtime"
        runtime_parent.mkdir(parents=True)
        outside = self.home / "outside-runtime"
        outside.mkdir()
        (runtime_parent / "docmost-tools-generations").symlink_to(
            outside, target_is_directory=True
        )

        result = self.run_script("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("generation root must be a safe directory", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(self.log_file.exists(), "unsafe runtime root must be rejected before uv")

    def test_direct_install_marker_cannot_bypass_the_lock(self) -> None:
        self.install_fake_uv()
        self.write_env()
        environment = self.env.copy()
        environment["DOCMOST_SETUP_LOCK_MODE"] = "exclusive"
        environment["DOCMOST_SETUP_LOCK_FD"] = "9"

        result = subprocess.run(
            ["bash", str(SCRIPT), "--install-setup-locked"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("requires the held setup lock", result.stderr)
        self.assertFalse(self.log_file.exists(), "a forged marker must not reach uv")

    def test_concurrent_install_from_another_plugin_source_fails_closed(self) -> None:
        self.install_fake_uv()
        self.write_env()
        active_plugin = self.home / "active-docmost-tools"
        shutil.copytree(
            ROOT / "plugins" / "docmost-tools",
            active_plugin,
            ignore=shutil.ignore_patterns(
                ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"
            ),
        )
        started = self.home / "sync-started"
        release = self.home / "sync-release"
        first_env = self.env.copy()
        first_env.update(
            {
                "FAKE_DOCMOST_SYNC_STARTED": str(started),
                "FAKE_DOCMOST_SYNC_RELEASE": str(release),
            }
        )
        first = subprocess.Popen(
            ["bash", str(SCRIPT), "--install"],
            cwd=ROOT,
            env=first_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        second: subprocess.CompletedProcess[str] | None = None
        first_stdout = ""
        first_stderr = ""
        try:
            deadline = time.monotonic() + 5
            while not started.exists():
                if first.poll() is not None:
                    first_stdout, first_stderr = first.communicate()
                    self.fail(
                        "first install exited before reaching sync: "
                        + first_stdout
                        + first_stderr
                    )
                if time.monotonic() >= deadline:
                    self.fail("first install did not reach the synchronized sync point")
                time.sleep(0.01)

            second_env = self.env.copy()
            second_env["DOCMOST_SERVER_DIR"] = str(active_plugin / "server")
            second = subprocess.run(
                ["bash", str(SCRIPT), "--install"],
                cwd=ROOT,
                env=second_env,
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
        finally:
            release.touch()
            if first.poll() is None:
                first_stdout, first_stderr = first.communicate(timeout=5)

        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(first.returncode, 0, first_stdout + first_stderr)
        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(second.returncode, 75, second.stdout + second.stderr)
        self.assertIn("runtime setup is busy", second.stderr)
        commands = self.log_file.read_text()
        self.assertEqual(commands.count("sync --frozen --no-dev --no-editable"), 1)
        self.assertNotIn(str((active_plugin / "server").resolve()), commands)

    def test_failed_install_invalidates_the_previous_runtime_stamp(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        stamp = self.generation_runtime() / ".docmost-tools-source.sha256"
        stamp.write_text("0" * 64 + "\n")
        self.env["FAKE_DOCMOST_SYNC"] = "fail"

        result = self.run_script("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stamp.exists())

    def test_failed_chromium_install_never_publishes_the_generation(self) -> None:
        self.install_fake_uv()
        self.write_env()
        self.env["FAKE_DOCMOST_CHROMIUM_INSTALL"] = "fail"

        result = self.run_script("--install")

        stamp = self.generation_runtime() / ".docmost-tools-source.sha256"
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stamp.exists())
        self.env.pop("FAKE_DOCMOST_CHROMIUM_INSTALL")

        repaired = self.run_script("--install")

        self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)
        self.assertEqual(stamp.read_text().strip(), self.source_fingerprint())

    def test_source_revision_race_leaves_no_valid_runtime_stamp(self) -> None:
        self.install_fake_uv()
        self.write_env()
        active_plugin = self.home / "racing-docmost-tools"
        shutil.copytree(
            ROOT / "plugins" / "docmost-tools",
            active_plugin,
            ignore=shutil.ignore_patterns(
                ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"
            ),
        )
        server = active_plugin / "server"
        fingerprint = self.source_fingerprint(server)
        stamp = (
            self.codex_home
            / "runtime"
            / "docmost-tools-generations"
            / "envs"
            / fingerprint
            / ".docmost-tools-source.sha256"
        )
        self.env["DOCMOST_SERVER_DIR"] = str(server)
        self.env["FAKE_DOCMOST_SYNC_MUTATE_SOURCE"] = str(
            server / "src" / "docmost_tools" / "models.py"
        )

        result = self.run_script("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stamp.exists())

    def test_prune_removes_only_unlocked_unreferenced_generations(self) -> None:
        self.install_fake_uv(preinstalled=True)
        generation_root = (
            self.codex_home / "runtime" / "docmost-tools-generations"
        )
        stale = generation_root / "envs" / ("a" * 64)
        stale.mkdir()
        legacy = self.codex_home / "runtime" / "docmost-tools"
        legacy.mkdir()
        (legacy / "rollback-marker").write_text("retained")

        result = self.run_script("--prune")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stale.exists())
        self.assertTrue(self.generation_runtime().is_dir())
        self.assertEqual((legacy / "rollback-marker").read_text(), "retained")
        self.assertIn("pruned=1", result.stdout)
        self.assertIn("legacy_retained=1", result.stdout)

    def test_prune_preserves_an_active_generation(self) -> None:
        self.install_fake_uv(preinstalled=True)
        generation_root = (
            self.codex_home / "runtime" / "docmost-tools-generations"
        )
        active_id = "b" * 64
        active = generation_root / "envs" / active_id
        active.mkdir()
        started = self.home / "active-generation-started"
        release = self.home / "active-generation-release"
        holder = subprocess.Popen(
            [
                "/usr/bin/python3",
                self.env["FAKE_DOCMOST_RUNTIME_LOCK_SOURCE"],
                "--kind",
                "generation",
                "--mode",
                "shared",
                "--root",
                str(generation_root),
                "--generation",
                active_id,
                "--",
                "/bin/sh",
                "-c",
                ': > "$1"; while [ ! -e "$2" ]; do /bin/sleep 0.01; done',
                "holder",
                str(started),
                str(release),
            ],
            cwd=ROOT,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not started.exists():
            if holder.poll() is not None or time.monotonic() >= deadline:
                stdout, stderr = holder.communicate(timeout=5)
                self.fail("active generation holder did not start: " + stdout + stderr)
            time.sleep(0.01)
        try:
            result = self.run_script("--prune")
        finally:
            release.touch()
            holder.communicate(timeout=5)

        self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
        self.assertTrue(active.is_dir())
        self.assertIn("busy=1", result.stdout)

    def test_prune_preserves_generations_referenced_by_installed_plugins(self) -> None:
        self.install_fake_uv(preinstalled=True)
        installed_server = (
            self.codex_home
            / "plugins"
            / "cache"
            / "fixture-marketplace"
            / "docmost-tools"
            / "0.5.0"
            / "server"
        )
        shutil.copytree(
            ROOT / "plugins" / "docmost-tools" / "server",
            installed_server,
            ignore=shutil.ignore_patterns(
                ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"
            ),
        )
        models = installed_server / "src" / "docmost_tools" / "models.py"
        models.write_text(models.read_text() + "\n# installed rollback fixture\n")
        referenced_id = self.source_fingerprint(installed_server)
        referenced = (
            self.codex_home
            / "runtime"
            / "docmost-tools-generations"
            / "envs"
            / referenced_id
        )
        referenced.mkdir()

        result = self.run_script("--prune")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(referenced.is_dir())
        self.assertIn("pruned=0", result.stdout)
        self.assertFalse(self.log_file.exists(), "prune must not execute a Docmost client")

    def test_permission_probe_discards_failed_bsd_stat_output(self) -> None:
        self.install_fake_uv()
        self.write_env()
        self.write_executable(
            "stat",
            "#!/bin/sh\n"
            "if [ \"$1\" = -f ]; then printf '%s\\n' 'gnu-filesystem-output'; exit 1; fi\n"
            "if [ \"$1\" = -c ]; then\n"
            "  case \"$3\" in\n"
            "    *docmost.env) printf '%s\\n' 600 ;;\n"
            "    *docmost) printf '%s\\n' 700 ;;\n"
            "    *) exit 1 ;;\n"
            "  esac\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
        )

        result = self.run_script("--install")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("gnu-filesystem-output", result.stdout + result.stderr)

    def test_install_rejects_a_profile_root_symlink_without_mutating_its_target(self) -> None:
        self.install_fake_uv()
        self.write_env()
        outside = self.home / "outside-profile"
        outside.mkdir(mode=0o755)
        outside.chmod(0o755)
        (self.secrets_dir / "docmost").symlink_to(outside, target_is_directory=True)

        result = self.run_script("--install")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("profile directory must not be a symlink", result.stderr)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
        self.assertFalse(self.log_file.exists(), "install must reject the path before invoking uv")

    def test_status_reports_auth_required_with_a_distinct_exit_code(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        profile = self.secrets_dir / "docmost"
        profile.mkdir(mode=0o700)
        browser_profile = profile / "browser-profile"
        browser_profile.mkdir(mode=0o700)
        self.env["FAKE_DOCMOST_AUTH"] = "auth"

        result = self.run_script("--status")

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"Docmost status: {RECOVERY_SENTENCE}")
        commands = self.log_file.read_text()
        self.assertIn("docmost-smoke", commands)

    def test_status_parses_auth_json_even_when_smoke_warns_on_stderr(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()
        self.env["FAKE_DOCMOST_AUTH"] = "auth"
        self.env["FAKE_DOCMOST_STDERR_WARNING"] = "1"

        result = self.run_script("--status")

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"Docmost status: {RECOVERY_SENTENCE}")
        self.assertIn("harmless runtime warning", result.stderr)

    def test_status_fails_closed_when_the_shared_runtime_is_stale(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()
        (self.generation_runtime() / ".docmost-tools-source.sha256").write_text(
            "0" * 64 + "\n"
        )

        result = self.run_script("--status")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Docmost runtime is stale; rerun the full codex-toolbox setup", result.stderr)
        self.assertFalse(self.log_file.exists(), "stale runtime must not execute smoke")

    def test_status_rejects_a_symlinked_generation_entrypoint(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()
        entrypoint = self.generation_runtime() / "bin" / "docmost-mcp"
        outside = self.home / "outside-entrypoint"
        outside.write_text("unchanged")
        entrypoint.unlink()
        entrypoint.symlink_to(outside)

        result = self.run_script("--status")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Docmost runtime is stale", result.stderr)
        self.assertEqual(outside.read_text(), "unchanged")
        self.assertFalse(self.log_file.exists(), "unsafe entrypoint must not execute")

    def test_status_without_a_browser_profile_requires_login(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        profile = self.secrets_dir / "docmost"
        profile.mkdir(mode=0o700)

        result = self.run_script("--status")

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"Docmost status: {RECOVERY_SENTENCE}")
        self.assertFalse(self.log_file.exists(), "missing profile must not execute smoke")

    def test_status_can_overlap_a_shared_lifetime_runtime_lock(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()
        holder, release = self.start_shared_runtime_holder()

        result = self.run_script("--status")
        release.touch()
        holder.communicate(timeout=5)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Docmost status: ready", result.stdout)

    def test_login_and_logout_cannot_overlap_a_shared_lifetime_runtime_lock(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        self.create_private_browser_profile()
        for command in ("--login", "--logout"):
            with self.subTest(command=command):
                holder, release = self.start_shared_runtime_holder()

                result = self.run_script(command)
                release.touch()
                holder.communicate(timeout=5)

                self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
                self.assertIn("Docmost session is busy", result.stderr)
                if self.log_file.exists():
                    self.assertNotIn("docmost-auth-internal", self.log_file.read_text())

    def test_auth_wrapper_rejects_a_declared_shared_lock_for_login(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        runtime_parent = self.codex_home / "runtime"
        runtime = self.generation_runtime()

        result = subprocess.run(
            [
                "/usr/bin/python3",
                str(
                    ROOT
                    / "plugins"
                    / "docmost-tools"
                    / "server"
                    / "src"
                    / "docmost_tools"
                    / "runtime_lock.py"
                ),
                "--kind",
                "session",
                "--mode",
                "shared",
                "--root",
                str(runtime_parent),
                "--",
                str(runtime / "bin" / "docmost-auth"),
                "login",
            ],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("login requires the held exclusive session lock", result.stderr)
        if self.log_file.exists():
            self.assertNotIn("docmost-auth-internal", self.log_file.read_text())

    def test_status_rejects_a_nonprivate_browser_profile(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()
        profile = self.secrets_dir / "docmost"
        profile.mkdir(mode=0o700)
        browser_profile = profile / "browser-profile"
        browser_profile.mkdir(mode=0o755)
        browser_profile.chmod(0o755)

        result = self.run_script("--status")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("browser profile directory must have mode 700", result.stderr)

    def test_login_is_the_only_interactive_auth_command(self) -> None:
        self.install_fake_uv(preinstalled=True)
        self.write_env()

        result = self.run_script("--login")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.log_file.read_text()
        self.assertIn("docmost-auth-internal login", commands)
        self.assertNotIn("docmost-smoke", commands)

    def test_installed_auth_command_works_outside_the_checkout(self) -> None:
        self.codex_home = self.home / ".codex"
        self.env.pop("CODEX_HOME", None)
        self.install_fake_uv()
        self.write_env()
        install = self.run_script("--install")
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        environment = self.env.copy()
        environment.pop("CODEX_TOOLBOX_ROOT", None)

        result = subprocess.run(
            [
                str(
                    self.generation_runtime() / "bin" / "docmost-auth"
                ),
                "login",
            ],
            cwd=self.home,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("docmost-auth-internal login", self.log_file.read_text())

    def test_logout_clears_the_profile_without_requiring_docmost_env(self) -> None:
        self.install_fake_uv(preinstalled=True)
        profile = self.create_private_browser_profile()
        (profile / "session-state").write_text("sensitive")

        result = self.run_script("--logout")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("docmost-auth-internal logout", self.log_file.read_text())
        self.assertFalse(profile.exists())

    def test_global_setup_recovers_only_from_auth_before_plugin_refresh(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.env["FAKE_DOCMOST_AUTH"] = "auth"

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Apple Mail MCP entry is unavailable", result.stderr)
        log = self.log_file.read_text()
        install = log.index("sync --frozen")
        login = log.index("docmost-auth-internal login")
        final_status = log.index("docmost-smoke")
        first_plugin = log.index("codex plugin marketplace")
        self.assertLess(install, login)
        self.assertLess(login, final_status)
        self.assertLess(final_status, first_plugin)
        self.assertEqual(log.count("sync --frozen --no-dev --no-editable"), 1)

    def test_global_setup_recovers_an_expired_existing_profile(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        self.env["FAKE_DOCMOST_AUTH"] = "auth"

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Apple Mail MCP entry is unavailable", result.stderr)
        log = self.log_file.read_text()
        first_smoke = log.index("docmost-smoke")
        login = log.index("docmost-auth-internal login")
        second_smoke = log.index("docmost-smoke", first_smoke + 1)
        first_plugin = log.index("codex plugin marketplace")
        self.assertEqual(log.count("docmost-smoke"), 3)
        self.assertLess(first_smoke, login)
        self.assertLess(login, second_smoke)
        self.assertLess(second_smoke, first_plugin)

    def test_global_setup_reinstalls_from_the_installed_mcp_copy_after_refresh(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        installed_models = (
            self.installed_plugin_root
            / "server"
            / "src"
            / "docmost_tools"
            / "models.py"
        )
        installed_models.write_text(installed_models.read_text() + "\n# installed fixture\n")

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Apple Mail MCP entry is unavailable", result.stderr)
        log = self.log_file.read_text()
        plugin_refresh = log.index("codex plugin add docmost-tools@jialuo-codex-toolbox")
        installed_sync = log.index(
            f"--directory {(self.installed_plugin_root / 'server').resolve()}"
        )
        self.assertLess(plugin_refresh, installed_sync)
        self.assertNotIn(
            f"--directory {(self.marketplace_plugin_root / 'server').resolve()}",
            log,
        )
        self.assertIn("codex mcp get docmost --json", log)
        self.assertIn("runtime-manager.mjs update", log)
        self.assertEqual(log.count("sync --frozen --no-dev --no-editable"), 2)

    def test_global_setup_rejects_an_absent_installed_docmost_mcp(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        self.env["FAKE_DOCMOST_MCP_GET"] = "absent"

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost MCP entry is unavailable", result.stderr)

    def test_global_setup_rejects_unexpected_installed_docmost_transport(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()

        for overrides in ({"type": "http"}, {"command": "/usr/bin/python3"}):
            with self.subTest(overrides=overrides):
                self.write_fake_mcp(**overrides)
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
                    cwd=ROOT,
                    env=self.env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                self.assertIn(
                    "Installed Docmost MCP transport is unexpected", result.stderr
                )

    def test_global_setup_rejects_an_installed_docmost_cwd_outside_codex_home(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        outside = self.home / "outside" / "docmost-tools" / self.plugin_version
        shutil.copytree(self.installed_plugin_root, outside)
        self.write_fake_mcp(cwd=str(outside))

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost MCP cwd escapes CODEX_HOME", result.stderr)

    def test_global_setup_rejects_a_malformed_installed_docmost_cwd(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()

        for cwd in ("relative/docmost-tools/0.1.1", "", None, 42):
            with self.subTest(cwd=cwd):
                self.write_fake_mcp(cwd=cwd)
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
                    cwd=ROOT,
                    env=self.env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                self.assertIn("Installed Docmost MCP cwd is invalid", result.stderr)

    def test_global_setup_rejects_an_unexpected_installed_docmost_layout(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        (self.installed_plugin_root / ".mcp.json").unlink()

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost plugin layout is invalid", result.stderr)

    def test_global_setup_rejects_a_symlink_within_the_installed_layout(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        manifest_directory = self.installed_plugin_root / ".codex-plugin"
        outside = self.home / "outside-manifest"
        shutil.copytree(manifest_directory, outside)
        shutil.rmtree(manifest_directory)
        manifest_directory.symlink_to(outside, target_is_directory=True)

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost plugin layout is invalid", result.stderr)

    def test_global_setup_rejects_a_symlinked_installed_version_root(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        linked_root = self.installed_plugin_root
        target_root = linked_root.with_name(f"{self.plugin_version}-real")
        linked_root.rename(target_root)
        manifest_path = target_root / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = target_root.name
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        linked_root.symlink_to(target_root, target_is_directory=True)
        self.write_fake_mcp()

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost plugin layout is invalid", result.stderr)

    def test_global_setup_rejects_an_extra_server_in_the_installed_copy(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        mcp_path = self.installed_plugin_root / ".mcp.json"
        mcp = json.loads(mcp_path.read_text())
        mcp["mcpServers"]["unexpected"] = {"command": "/bin/false"}
        mcp_path.write_text(json.dumps(mcp, indent=2) + "\n")
        self.write_fake_mcp()

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost plugin layout is invalid", result.stderr)

    def test_global_setup_rejects_unprompted_writes_in_the_installed_copy(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        mcp_path = self.installed_plugin_root / ".mcp.json"
        mcp = json.loads(mcp_path.read_text())
        mcp["mcpServers"]["docmost"]["tools"]["docmost_create_page"][
            "approval_mode"
        ] = "auto"
        mcp_path.write_text(json.dumps(mcp, indent=2) + "\n")
        self.write_fake_mcp()

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost MCP policy is unexpected", result.stderr)

    def test_global_setup_rejects_scalar_installed_launcher_arguments(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        mcp_path = self.installed_plugin_root / ".mcp.json"
        mcp = json.loads(mcp_path.read_text())
        mcp["mcpServers"]["docmost"]["args"] = "malformed-but-matching"
        mcp_path.write_text(json.dumps(mcp, indent=2) + "\n")
        self.write_fake_mcp()

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost MCP launcher is unexpected", result.stderr)

    def test_global_setup_rejects_altered_installed_launcher_script(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        launcher = self.installed_plugin_root / "server" / "scripts" / "docmost-mcp"
        launcher.write_text(launcher.read_text() + "\ntrue\n")
        self.write_fake_mcp()

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost MCP launcher is unexpected", result.stderr)

    def test_global_setup_rejects_extra_installed_launcher_arguments(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        mcp_path = self.installed_plugin_root / ".mcp.json"
        mcp = json.loads(mcp_path.read_text())
        mcp["mcpServers"]["docmost"]["args"].append("unexpected-extra-argument")
        mcp_path.write_text(json.dumps(mcp, indent=2) + "\n")
        self.write_fake_mcp()

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Installed Docmost MCP launcher is unexpected", result.stderr)

    def test_global_setup_stops_on_non_auth_smoke_failure(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        self.env["FAKE_DOCMOST_AUTH"] = "upstream"

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.log_file.read_text()
        self.assertIn("docmost-smoke", log)
        self.assertNotIn("docmost-auth-internal login", log)
        self.assertNotIn("codex plugin marketplace", log)

    def test_global_setup_does_not_login_or_refresh_plugins_after_non_auth_failure(self) -> None:
        self.install_fake_uv()
        self.install_fake_codex()
        self.write_env()
        self.create_private_browser_profile()
        self.env["FAKE_DOCMOST_AUTH"] = "upstream"

        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "setup-codex-toolbox.sh")],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.log_file.read_text()
        self.assertIn("docmost-smoke", log)
        self.assertNotIn("docmost-auth-internal login", log)
        self.assertNotIn("codex plugin marketplace", log)


if __name__ == "__main__":
    unittest.main()
