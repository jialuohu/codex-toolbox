"""Offline runtime setup and non-interactive readiness contracts."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup-codex-toolbox.sh"
HEALTH_SETUP = ROOT / "scripts/setup-toolbox-health.sh"


class ToolboxHealthSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "checkout/scripts"
        scripts.mkdir(parents=True)
        self.script = scripts / HEALTH_SETUP.name
        shutil.copyfile(HEALTH_SETUP, self.script)
        self.requirements = scripts.parent / "plugins/workflow-tools/skills/sync-toolbox/scripts/requirements.txt"
        self.requirements.parent.mkdir(parents=True)
        self.requirements.write_text("PyYAML==6.0.3\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "commands.log"
        self.codex = self.root / "codex"
        self.runtime = self.codex / "runtime/toolbox-health"
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.root),
            "CODEX_HOME": str(self.codex),
            "CODEX_LOCAL_BIN_DIR": str(self.bin),
            "TEST_LOG": str(self.log),
            "TEST_RUNTIME": str(self.runtime),
        }

    def executable(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\nset -eu\n" + text)
        path.chmod(0o755)

    def fake_uv(self) -> None:
        self.executable(self.bin / "uv", '''
printf '%s\\n' "$*" >> "$TEST_LOG"
if [ "${TEST_UV_FAIL:-0}" = 1 ]; then exit 7; fi
if [ "$1" = venv ]; then
  mkdir -p "$TEST_RUNTIME/bin"
  cat > "$TEST_RUNTIME/bin/python" <<'PY'
#!/bin/bash
test -f "$TEST_RUNTIME/ready"
PY
  chmod +x "$TEST_RUNTIME/bin/python"
elif [ "$1" = pip ] && [ "${TEST_BAD_INSTALL:-0}" != 1 ]; then
  touch "$TEST_RUNTIME/ready"
fi
''')

    def run_setup(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(self.script), *args], env=self.env,
                              capture_output=True, text=True, check=False)

    def test_check_missing_runtime_is_offline_and_does_not_create_state(self) -> None:
        self.fake_uv()
        result = self.run_setup("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing or stale", result.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.codex.exists())

    def test_install_pinned_runtime_and_repeat_without_package_mutation(self) -> None:
        self.fake_uv()
        result = self.run_setup("--install")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn("venv --python 3.12 --allow-existing", log)
        self.assertIn(f"pip sync --python {self.runtime}/bin/python {self.requirements}", log)
        for mode in ("--install", "--check"):
            result = self.run_setup(mode)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ready", result.stdout)
        self.assertEqual(self.log.read_text(), log)

    def test_stale_runtime_is_repaired_without_recreating_venv(self) -> None:
        self.fake_uv()
        self.executable(self.runtime / "bin/python", 'test -f "$TEST_RUNTIME/ready"\n')
        self.assertEqual(self.run_setup("--check").returncode, 1)
        result = self.run_setup("--install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("venv", self.log.read_text())

    def test_install_errors_stay_fail_fast(self) -> None:
        self.fake_uv()
        self.env["TEST_UV_FAIL"] = "1"
        self.assertEqual(self.run_setup("--install").returncode, 7)
        self.assertNotIn("pip sync", self.log.read_text())

    def test_failed_verification_never_reports_installed(self) -> None:
        self.fake_uv()
        self.env["TEST_BAD_INSTALL"] = "1"
        result = self.run_setup("--install")
        self.assertEqual(result.returncode, 1)
        self.assertIn("verification failed", result.stderr)
        self.assertNotIn("runtime: installed", result.stdout)

    def test_unreviewed_requirements_and_symlink_runtime_are_rejected(self) -> None:
        self.fake_uv()
        self.requirements.write_text("PyYAML==6.0.3\nother-package\n")
        self.assertEqual(self.run_setup("--install").returncode, 1)
        self.assertFalse(self.log.exists())
        self.requirements.write_text("PyYAML==6.0.3\n")
        self.runtime.parent.mkdir(parents=True)
        self.runtime.symlink_to(self.root)
        self.assertEqual(self.run_setup("--install").returncode, 1)
        self.assertFalse(self.log.exists())

    def test_unknown_option_rejected_before_prerequisite_mutations(self) -> None:
        result = subprocess.run(["bash", str(SETUP), "--unknown"], env=self.env,
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.codex.exists())
        source = SETUP.read_text()
        self.assertLess(source.index('NON_INTERACTIVE=0'),
                        source.index('python3 "$PREREQUISITES"'))

    def run_readiness(self, *, component: str, non_interactive: bool,
                      status: int = 0, install_status: int = 0) -> subprocess.CompletedProcess[str]:
        source = SETUP.read_text()
        helper = self.root / "readiness-helper"
        self.executable(helper, '''
printf '%s\\n' "$*" >> "$TEST_LOG"
case "$1" in
  --install) exit "${TEST_INSTALL_STATUS}" ;;
  --status) exit "${TEST_STATUS}" ;;
  --check) exit "${TEST_CHECK_STATUS:-0}" ;;
esac
''')
        if component == "docmost":
            functions = source.split('docmost_setup_command() {', 1)[1].split('installed_docmost_server_dir() {', 1)[0]
            body = 'docmost_setup_command() {' + functions + '\nensure_docmost_ready ""\necho continued\n'
        else:
            functions = source.split('check_apple_mail_readiness() {', 1)[1].split('installed_apple_mail_server_dir() {', 1)[0]
            body = 'check_apple_mail_readiness() {' + functions + '\ncheck_apple_mail_readiness /installed/server\necho continued\n'
        env = {**self.env, "TEST_STATUS": str(status), "TEST_INSTALL_STATUS": str(install_status),
               "DOCMOST_SETUP": str(helper), "APPLE_MAIL_SETUP": str(helper)}
        return subprocess.run(["bash", "-c", f"set -euo pipefail\nNON_INTERACTIVE={int(non_interactive)}\n" + body],
                              env=env, text=True, capture_output=True, check=False)

    def test_noninteractive_docmost_defers_only_authentication(self) -> None:
        result = self.run_readiness(component="docmost", non_interactive=True, status=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("auth_required", result.stdout)
        self.assertIn("continued", result.stdout)
        self.assertEqual(self.log.read_text().splitlines(), ["--install", "--status"])

    def test_docmost_install_and_other_errors_stop_setup(self) -> None:
        for status, install_status in ((1, 0), (75, 0), (0, 9)):
            with self.subTest(status=status, install_status=install_status):
                result = self.run_readiness(component="docmost", non_interactive=True,
                                            status=status, install_status=install_status)
                self.assertEqual(result.returncode, install_status or status)
                self.assertNotIn("continued", result.stdout)
                self.assertNotIn("--login", self.log.read_text())

    def test_default_docmost_behavior_keeps_login(self) -> None:
        self.run_readiness(component="docmost", non_interactive=False, status=3)
        self.assertEqual(self.log.read_text().splitlines(),
                         ["--install", "--status", "--login", "--status"])

    def test_apple_mail_noninteractive_uses_check_and_defers_permissions(self) -> None:
        result = self.run_readiness(component="apple_mail", non_interactive=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("permission_check", result.stdout)
        self.assertEqual(self.log.read_text().splitlines(), ["--check"])

    def test_apple_mail_check_failure_stops_setup(self) -> None:
        self.env["TEST_CHECK_STATUS"] = "75"
        result = self.run_readiness(component="apple_mail", non_interactive=True)
        self.assertEqual(result.returncode, 75)
        self.assertNotIn("continued", result.stdout)

    def test_default_apple_mail_behavior_keeps_status(self) -> None:
        result = self.run_readiness(component="apple_mail", non_interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ["--status"])

    def full_setup_fixture(self) -> Path:
        """Run the complete orchestration with every external boundary stubbed."""
        scripts = self.script.parent
        setup = scripts / "setup-codex-toolbox.sh"
        shutil.copyfile(SETUP, setup)
        for name in (
            "sync-agents.sh", "setup-docmost-tools.sh", "setup-diagram-tools.sh",
            "setup-archify-tools.sh", "setup-apple-mail-tools.sh",
            "setup-diagram-publish.sh",
            "setup-toolbox-health.sh", "setup-drawio-tools.sh",
        ):
            self.executable(scripts / name, '''
printf '%s %s\\n' "${0##*/}" "$*" >> "$TEST_LOG"
if [ "${0##*/}" = setup-toolbox-health.sh ]; then
  exit "${TEST_HEALTH_INSTALL_STATUS:-0}"
fi
''')
        codex = self.bin / "codex"
        self.executable(codex, '''
printf 'codex %s\\n' "$*" >> "$TEST_LOG"
printf '%s\\n' '{"installed":[],"marketplaces":[]}'
''')
        # The real installed-source validation is covered by owner setup tests;
        # this fixture isolates the full shell orchestration and failure ordering.
        self.executable(self.bin / "python3", '''
if [ "${2:-}" = resolve-codex ]; then
  printf '%s\\n' "$TEST_CODEX_BIN"
elif [ "${DOCMOST_MCP_JSON+x}" = x ]; then
  printf '%s\\n' /synthetic-installed/docmost/server
elif [ "${APPLE_MAIL_MCP_JSON+x}" = x ]; then
  printf '%s\\n' /synthetic-installed/apple-mail/server
fi
''')
        self.env["TEST_CODEX_BIN"] = str(codex)
        self.env["CODEX_TOOLBOX_MARKETPLACE_MODE"] = "git"
        self.env["CODEX_TOOLBOX_INSTALL_DRAWIO_DESKTOP"] = "0"
        return setup

    def test_full_setup_installs_health_after_noninteractive_apple_mail_check(self) -> None:
        setup = self.full_setup_fixture()
        result = subprocess.run(["bash", str(setup), "--non-interactive"],
                                env=self.env, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertIn("setup-diagram-publish.sh --install-launcher", commands)
        self.assertNotIn("setup-diagram-publish.sh --install-runtime", commands)
        apple_install = commands.index("setup-apple-mail-tools.sh --install")
        apple_check = commands.index("setup-apple-mail-tools.sh --check")
        health_install = commands.index("setup-toolbox-health.sh --install")
        drawio_install = commands.index("setup-drawio-tools.sh --install")
        self.assertLess(apple_install, apple_check)
        self.assertLess(apple_check, health_install)
        self.assertLess(health_install, drawio_install)
        self.assertNotIn("setup-apple-mail-tools.sh --status", commands)
        self.assertEqual(commands[-1], "codex plugin marketplace list")

    def test_full_setup_stops_after_health_install_failure(self) -> None:
        setup = self.full_setup_fixture()
        self.env["TEST_HEALTH_INSTALL_STATUS"] = "9"
        result = subprocess.run(["bash", str(setup), "--non-interactive"],
                                env=self.env, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 9, result.stdout + result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertIn("setup-apple-mail-tools.sh --check", commands)
        self.assertNotIn("setup-apple-mail-tools.sh --status", commands)
        self.assertEqual(commands[-1], "setup-toolbox-health.sh --install")
        self.assertNotIn("setup-drawio-tools.sh --install", commands)


if __name__ == "__main__":
    unittest.main()
