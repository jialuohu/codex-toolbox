#!/usr/bin/env python3
"""Behavioral tests for immutable Apple Mail runtime generations."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-apple-mail-tools.sh"
SERVER = ROOT / "plugins" / "apple-mail-tools" / "server"
LOCK_HELPER = SERVER / "src" / "apple_mail_tools" / "runtime_lock.py"
STAMP_HELPER = SERVER / "src" / "apple_mail_tools" / "runtime_stamp.py"
LAUNCHER = SERVER / "scripts" / "apple-mail-mcp"


@unittest.skipUnless(sys.platform == "darwin", "Apple Mail setup is macOS-only")
class SetupAppleMailToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.secrets_dir = self.home / "secrets"
        self.secrets_dir.mkdir(mode=0o700)
        self.codex_home = self.home / "codex-home"
        self.log_file = self.home / "commands.log"
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin_dir}:/usr/bin:/bin",
                "CODEX_HOME": str(self.codex_home),
                "CODEX_SECRETS_DIR": str(self.secrets_dir),
                "FAKE_APPLE_MAIL_LOG": str(self.log_file),
            }
        )

    def write_executable(self, name: str, body: str) -> Path:
        path = self.bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def install_fake_uv(self, *, preinstalled: bool = False) -> None:
        template = self.home / "fake-apple-mail-runtime"
        runtime_bin = template / "bin"
        runtime_bin.mkdir(parents=True)
        self.env["FAKE_APPLE_MAIL_RUNTIME_TEMPLATE"] = str(template)
        self.write_executable(
            "uv",
            "#!/bin/sh\n"
            "printf 'UV_PROJECT_ENVIRONMENT=%s %s\\n' \"${UV_PROJECT_ENVIRONMENT:-}\" \"$*\" >> \"$FAKE_APPLE_MAIL_LOG\"\n"
            "if [ \"${FAKE_APPLE_MAIL_LOCK:-fresh}\" = stale ] && [ \"$1\" = lock ]; then exit 1; fi\n"
            "case \"$*\" in\n"
            "  *'sync '*'--reinstall-package apple-mail-tools'*)\n"
            "    if [ -n \"${FAKE_APPLE_MAIL_SYNC_STARTED:-}\" ]; then\n"
            "      : > \"$FAKE_APPLE_MAIL_SYNC_STARTED\"\n"
            "      while [ ! -e \"$FAKE_APPLE_MAIL_SYNC_RELEASE\" ]; do /bin/sleep 0.01; done\n"
            "    fi\n"
            "    [ \"${FAKE_APPLE_MAIL_SYNC:-ready}\" = ready ] || exit 1\n"
            "    mkdir -p \"$UV_PROJECT_ENVIRONMENT\"\n"
            "    cp -R \"$FAKE_APPLE_MAIL_RUNTIME_TEMPLATE/.\" \"$UV_PROJECT_ENVIRONMENT/\"\n"
            "    if [ -n \"${FAKE_APPLE_MAIL_SYNC_MUTATE_SOURCE:-}\" ]; then\n"
            "      printf '\\n' >> \"$FAKE_APPLE_MAIL_SYNC_MUTATE_SOURCE\"\n"
            "    fi\n"
            "    ;;\n"
            "esac\n",
        )

        def runtime_executable(name: str, body: str) -> None:
            path = runtime_bin / name
            path.write_text(body)
            path.chmod(0o755)

        runtime_executable(
            "python",
            "#!/bin/sh\n"
            "printf 'runtime-python %s\\n' \"$*\" >> \"$FAKE_APPLE_MAIL_LOG\"\n"
            "case \"$*\" in\n"
            "  *'AppleMailService().health_check'*) printf '%s\\n' '{\"status\":\"ready\"}' ;;\n"
            "esac\n",
        )
        runtime_executable(
            "apple-mail-mcp",
            "#!/bin/sh\n"
            "printf 'apple-mail-mcp %s\\n' \"$*\" >> \"$FAKE_APPLE_MAIL_LOG\"\n",
        )
        runtime_executable("apple-mail-runtime-stamp", "#!/bin/sh\nexit 0\n")
        if preinstalled:
            self.prepare_fake_generation()

    def source_fingerprint(self, server: Path = SERVER) -> str:
        result = subprocess.run(
            [sys.executable, str(STAMP_HELPER), "fingerprint", str(server)],
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def generation_root(self) -> Path:
        return self.codex_home / "runtime" / "apple-mail-tools-generations"

    def generation_runtime(self, server: Path = SERVER) -> Path:
        return self.generation_root() / "envs" / self.source_fingerprint(server)

    def ensure_generation_roots(self) -> None:
        (self.generation_root() / "envs").mkdir(parents=True, exist_ok=True)
        (self.generation_root() / "locks").mkdir(parents=True, exist_ok=True)

    def prepare_fake_generation(self, server: Path = SERVER) -> Path:
        runtime = self.generation_runtime(server)
        self.ensure_generation_roots()
        if runtime.is_symlink():
            runtime.unlink()
        elif runtime.exists():
            shutil.rmtree(runtime)
        shutil.copytree(Path(self.env["FAKE_APPLE_MAIL_RUNTIME_TEMPLATE"]), runtime)
        subprocess.run(
            [
                sys.executable,
                str(STAMP_HELPER),
                "write",
                str(server),
                str(runtime / ".apple-mail-tools-source.sha256"),
                "--expected",
                self.source_fingerprint(server),
            ],
            check=True,
        )
        return runtime

    def run_script(
        self, action: str, *, server: Path = SERVER, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = (env or self.env).copy()
        environment["APPLE_MAIL_SERVER_DIR"] = str(server)
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), action],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def wait_for(self, path: Path, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 5
        while not path.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=5)
                self.fail(f"holder exited early: {stdout}{stderr}")
            if time.monotonic() >= deadline:
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                log = self.log_file.read_text() if self.log_file.exists() else ""
                self.fail(f"holder did not start: {stdout}{stderr}\nlog:\n{log}")
            time.sleep(0.01)

    def start_generation_holder(self, generation: str) -> tuple[subprocess.Popen[str], Path]:
        self.ensure_generation_roots()
        started = self.home / f"generation-{generation[:8]}-started"
        release = self.home / f"generation-{generation[:8]}-release"
        holder = subprocess.Popen(
            [
                sys.executable,
                str(LOCK_HELPER),
                "--kind",
                "generation",
                "--mode",
                "shared",
                "--root",
                str(self.generation_root()),
                "--generation",
                generation,
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
        self.wait_for(started, holder)
        return holder, release

    def start_legacy_holder(self) -> tuple[subprocess.Popen[str], Path]:
        runtime_parent = self.codex_home / "runtime"
        runtime_parent.mkdir(parents=True, exist_ok=True)
        started = self.home / "legacy-started"
        release = self.home / "legacy-release"
        lock = runtime_parent / ".apple-mail-tools-runtime.lock"
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl, pathlib, sys, time; "
                    "stream=open(sys.argv[1], 'a+'); "
                    "fcntl.flock(stream.fileno(), fcntl.LOCK_SH); "
                    "pathlib.Path(sys.argv[2]).touch(); "
                    "release=pathlib.Path(sys.argv[3]); "
                    "[(time.sleep(0.01)) for _ in iter(lambda: release.exists(), True)]"
                ),
                str(lock),
                str(started),
                str(release),
            ],
            cwd=ROOT,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.wait_for(started, holder)
        return holder, release

    @staticmethod
    def release_holder(holder: subprocess.Popen[str], release: Path) -> None:
        release.touch()
        holder.communicate(timeout=5)

    def test_install_succeeds_while_legacy_and_other_generation_are_active(self) -> None:
        self.install_fake_uv()
        legacy_holder, legacy_release = self.start_legacy_holder()
        old_holder, old_release = self.start_generation_holder("a" * 64)
        try:
            result = self.run_script("--install")
            self.assertIsNone(legacy_holder.poll(), "install must not signal the legacy holder")
            self.assertIsNone(old_holder.poll(), "install must not signal an unrelated generation")
        finally:
            self.release_holder(old_holder, old_release)
            self.release_holder(legacy_holder, legacy_release)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            (self.generation_runtime() / ".apple-mail-tools-source.sha256").is_file()
        )
        status = self.run_script("--status")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn('{"status":"ready"}', status.stdout)

    def test_repeated_install_is_idempotent(self) -> None:
        self.install_fake_uv()

        first = self.run_script("--install")
        second = self.run_script("--install")

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("runtime generation: ready", second.stdout)
        commands = self.log_file.read_text()
        self.assertEqual(commands.count("--reinstall-package apple-mail-tools"), 1)

    def test_source_race_never_publishes_a_generation_stamp(self) -> None:
        self.install_fake_uv()
        copied_server = self.home / "install-racing-server"
        shutil.copytree(
            SERVER,
            copied_server,
            ignore=shutil.ignore_patterns(".venv", ".pytest_cache", ".ruff_cache", "__pycache__"),
        )
        fingerprint = self.source_fingerprint(copied_server)
        stamp = (
            self.generation_root()
            / "envs"
            / fingerprint
            / ".apple-mail-tools-source.sha256"
        )
        environment = self.env.copy()
        environment["FAKE_APPLE_MAIL_SYNC_MUTATE_SOURCE"] = str(
            copied_server / "src" / "apple_mail_tools" / "models.py"
        )

        result = self.run_script("--install", server=copied_server, env=environment)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stamp.exists())
        self.assertIn("source changed during runtime installation", result.stderr)

    def test_concurrent_setup_and_active_target_mutation_fail_busy(self) -> None:
        self.install_fake_uv()
        started = self.home / "sync-started"
        release = self.home / "sync-release"
        first_env = self.env.copy()
        first_env.update(
            {
                "FAKE_APPLE_MAIL_SYNC_STARTED": str(started),
                "FAKE_APPLE_MAIL_SYNC_RELEASE": str(release),
                "APPLE_MAIL_SERVER_DIR": str(SERVER),
            }
        )
        first = subprocess.Popen(
            ["/bin/bash", str(SCRIPT), "--install"],
            cwd=ROOT,
            env=first_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.wait_for(started, first)
        try:
            second = self.run_script("--install")
        finally:
            release.touch()
            first_stdout, first_stderr = first.communicate(timeout=5)

        self.assertEqual(first.returncode, 0, first_stdout + first_stderr)
        self.assertEqual(second.returncode, 75, second.stdout + second.stderr)
        self.assertIn("runtime setup is busy", second.stderr)

        runtime = self.generation_runtime()
        shutil.rmtree(runtime)
        runtime.mkdir()
        marker = runtime / "active-marker"
        marker.write_text("retained")
        target_holder, target_release = self.start_generation_holder(self.source_fingerprint())
        try:
            active_result = self.run_script("--install")
        finally:
            self.release_holder(target_holder, target_release)
        self.assertEqual(active_result.returncode, 75, active_result.stdout + active_result.stderr)
        self.assertEqual(marker.read_text(), "retained")
        self.assertIn("runtime generation is busy", active_result.stderr)

    def test_launcher_executes_only_the_matching_stamped_generation(self) -> None:
        self.install_fake_uv(preinstalled=True)

        result = subprocess.run(
            [str(LAUNCHER)],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("apple-mail-mcp", self.log_file.read_text())
        self.assertNotIn("uv ", self.log_file.read_text())

    def test_launcher_rejects_missing_unstamped_mismatched_and_symlinked_generations(self) -> None:
        self.install_fake_uv()
        self.ensure_generation_roots()
        runtime = self.generation_runtime()

        result = subprocess.run(
            [str(LAUNCHER)], env=self.env, text=True, capture_output=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime is stale", result.stderr)

        runtime = self.prepare_fake_generation()
        (runtime / ".apple-mail-tools-source.sha256").unlink()
        result = subprocess.run(
            [str(LAUNCHER)], env=self.env, text=True, capture_output=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime is stale", result.stderr)

        runtime = self.prepare_fake_generation()
        (runtime / ".apple-mail-tools-source.sha256").write_text("0" * 64 + "\n")
        result = subprocess.run(
            [str(LAUNCHER)], env=self.env, text=True, capture_output=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime is stale", result.stderr)

        runtime = self.prepare_fake_generation()
        shutil.rmtree(runtime)
        outside = self.home / "outside-generation"
        outside.mkdir()
        runtime.symlink_to(outside, target_is_directory=True)
        result = subprocess.run(
            [str(LAUNCHER)], env=self.env, text=True, capture_output=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime is stale", result.stderr)

    def test_launcher_rejects_a_source_race(self) -> None:
        self.install_fake_uv()
        copied_server = self.home / "racing-server"
        shutil.copytree(
            SERVER,
            copied_server,
            ignore=shutil.ignore_patterns(".venv", ".pytest_cache", ".ruff_cache", "__pycache__"),
        )
        copied_lock = copied_server / "src" / "apple_mail_tools" / "runtime_lock.py"
        lock_source = copied_lock.read_text()
        needle = "        os.execvpe(command[0], list(command), environment)\n"
        replacement = (
            "        hook = os.environ.get('FAKE_APPLE_MAIL_MUTATE_SOURCE')\n"
            "        if hook:\n"
            "            with open(hook, 'a') as stream:\n"
            "                stream.write('\\n')\n"
            + needle
        )
        self.assertIn(needle, lock_source)
        copied_lock.write_text(lock_source.replace(needle, replacement, 1))
        self.prepare_fake_generation(copied_server)
        environment = self.env.copy()
        environment["FAKE_APPLE_MAIL_MUTATE_SOURCE"] = str(
            copied_server / "src" / "apple_mail_tools" / "models.py"
        )

        result = subprocess.run(
            [str(copied_server / "scripts" / "apple-mail-mcp")],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("source changed during startup", result.stderr)
        self.assertFalse(self.log_file.exists(), "a raced source must not execute the MCP")

    def test_prune_preserves_current_installed_active_and_legacy_runtimes(self) -> None:
        self.install_fake_uv(preinstalled=True)
        generation_root = self.generation_root()
        legacy = self.codex_home / "runtime" / "apple-mail-tools"
        legacy.mkdir()
        (legacy / "rollback-marker").write_text("retained")
        stale = generation_root / "envs" / ("b" * 64)
        stale.mkdir()

        installed_server = (
            self.codex_home
            / "plugins"
            / "cache"
            / "fixture-marketplace"
            / "apple-mail-tools"
            / "0.1.5"
            / "server"
        )
        shutil.copytree(
            SERVER,
            installed_server,
            ignore=shutil.ignore_patterns(".venv", ".pytest_cache", ".ruff_cache", "__pycache__"),
        )
        models = installed_server / "src" / "apple_mail_tools" / "models.py"
        models.write_text(models.read_text() + "\n# installed rollback fixture\n")
        referenced = generation_root / "envs" / self.source_fingerprint(installed_server)
        referenced.mkdir()

        result = self.run_script("--prune")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stale.exists())
        self.assertTrue(self.generation_runtime().is_dir())
        self.assertTrue(referenced.is_dir())
        self.assertEqual((legacy / "rollback-marker").read_text(), "retained")
        self.assertIn("pruned=1", result.stdout)
        self.assertIn("legacy_retained=1", result.stdout)

        active_id = "c" * 64
        active = generation_root / "envs" / active_id
        active.mkdir()
        holder, release = self.start_generation_holder(active_id)
        try:
            active_result = self.run_script("--prune")
        finally:
            self.release_holder(holder, release)

        self.assertEqual(active_result.returncode, 75, active_result.stdout + active_result.stderr)
        self.assertTrue(active.is_dir())
        self.assertIn("busy=1", active_result.stdout)


if __name__ == "__main__":
    unittest.main()
