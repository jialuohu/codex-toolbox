"""Bounded diagnostic subprocess capture, without live service probes."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugins/workflow-tools/skills/sync-toolbox/scripts/health_check.py"
SPEC = importlib.util.spec_from_file_location("health_command_under_test", HELPER)
assert SPEC and SPEC.loader
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


class HealthCommandTests(unittest.TestCase):
    def command(self, code: str, timeout: float = 2):
        return health.run_command([sys.executable, "-c", code], timeout=timeout)

    def test_success_preserves_stdout_bytes_and_discards_stderr(self) -> None:
        self.assertEqual(self.command("import os; os.write(1,b'output'); os.write(2,b'private-error')"),
                         (b"output", "ok"))

    def test_failed_command_exposes_only_returncode(self) -> None:
        result = self.command("import sys; print('private-output'); print('private-error',file=sys.stderr); sys.exit(7)")
        self.assertEqual(result, (7, "probe_failed"))

    def test_missing_command_is_source_unavailable(self) -> None:
        self.assertEqual(health.run_command(["/nonexistent/toolbox-health-test-command"]),
                         (None, "source_unavailable"))

    def test_output_at_limit_is_accepted_and_overflow_terminates_early(self) -> None:
        with patch.object(health, "MAX_BYTES", 1024):
            self.assertEqual(self.command("import os; os.write(1,b'x'*1024)"), (b"x" * 1024, "ok"))
            started = time.monotonic()
            result = self.command("import os,time; os.write(1,b'x'*1025); time.sleep(30)")
            self.assertEqual(result, (None, "invalid_inventory"))
            self.assertLess(time.monotonic() - started, 1.5)

    def test_large_stderr_never_enters_capture(self) -> None:
        with patch.object(health, "MAX_BYTES", 32):
            result = self.command("import os; os.write(2,b'x'*(1024*1024)); os.write(1,b'ok')")
        self.assertEqual(result, (b"ok", "ok"))

    def test_timeout_even_after_stdout_is_closed(self) -> None:
        started = time.monotonic()
        result = self.command("import os,time; os.close(1); time.sleep(30)", timeout=0.15)
        self.assertEqual(result, (None, "probe_timeout"))
        self.assertLess(time.monotonic() - started, 1.5)

    def test_timeout_terminates_child_holding_pipe_after_parent_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child-survived"
            child = f"import time,pathlib; time.sleep(0.6); pathlib.Path({str(marker)!r}).touch()"
            parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])"
            started = time.monotonic()
            self.assertEqual(self.command(parent, timeout=0.2), (None, "probe_timeout"))
            self.assertLess(time.monotonic() - started, 1.5)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "Timeout left the pipe-holding child running")

    def test_overflow_terminates_child_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child-survived"
            child = f"import time,pathlib; time.sleep(0.6); pathlib.Path({str(marker)!r}).touch()"
            parent = (f"import subprocess,sys,os,time; subprocess.Popen([sys.executable,'-c',{child!r}]); "
                      "os.write(1,b'x'*1025); time.sleep(30)")
            with patch.object(health, "MAX_BYTES", 1024):
                self.assertEqual(self.command(parent), (None, "invalid_inventory"))
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "Overflow left a child process running")


if __name__ == "__main__":
    unittest.main()
