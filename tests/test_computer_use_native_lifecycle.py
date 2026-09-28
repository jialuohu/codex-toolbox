"""Offline guards for the disposable native fixture reset adapter."""

from __future__ import annotations

import plistlib
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import native_lifecycle as native


class NativeLifecycleTests(unittest.TestCase):
    def test_exact_executable_path_scopes_termination(self) -> None:
        inventory = """ 101 /private/tmp/codex-toolbox-cu-prep-diagnostic/JevCUFixture.app/Contents/MacOS/JevCUFixture --case-id native-long_tree-0
 202 /private/tmp/other-build/JevCUFixture.app/Contents/MacOS/JevCUFixture --case-id native-long_tree-0
 303 /bin/zsh -c /private/tmp/codex-toolbox-cu-prep-diagnostic/JevCUFixture.app/Contents/MacOS/JevCUFixture
"""
        with patch.object(native.subprocess, "run", return_value=SimpleNamespace(stdout=inventory)) as run:
            self.assertEqual(native._fixture_pids(), {101})
        self.assertEqual(run.call_args.args[0], ["ps", "-axo", "pid=,command="])

    def test_bundle_identity_is_pinned_before_reset(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            app = Path(dirname) / "JevCUFixture.app"
            info_path = app / "Contents/Info.plist"
            info_path.parent.mkdir(parents=True)
            with (patch.object(native, "APP_PATH", app),
                  patch.object(native, "EXECUTABLE_PATH", app / "Contents/MacOS/JevCUFixture")):
                info_path.write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": native.BUNDLE_ID,
                    "CFBundleExecutable": "JevCUFixture",
                }))
                native._validate_bundle_identity()
                info_path.write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": "other.app",
                    "CFBundleExecutable": "JevCUFixture",
                }))
                with self.assertRaisesRegex(native.NativeResetError, "identity changed"):
                    native._validate_bundle_identity()

    def test_reset_terminates_only_pinned_pid_and_launches_exact_path(self) -> None:
        with (patch.object(native, "_validate_bundle_identity"),
              patch.object(Path, "is_file", return_value=True),
              patch.object(native, "_fixture_pids", side_effect=[{101}, set(), {111}]),
              patch.object(native.os, "kill") as kill,
              patch.object(native.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run):
            native.reset_native("native-long_tree-0")
        kill.assert_called_once_with(101, signal.SIGTERM)
        self.assertEqual(run.call_args.args[0],
                         ["open", "-n", "-a", str(native.APP_PATH), "--args", "--case-id", "native-long_tree-0"])
        self.assertTrue(all(call.args[0][0] != "ioreg" for call in run.call_args_list))

    def test_multiple_pinned_instances_after_launch_are_rejected(self) -> None:
        with (patch.object(native, "_validate_bundle_identity"),
              patch.object(Path, "is_file", return_value=True),
              patch.object(native, "_fixture_pids", side_effect=[set(), {101, 102}]),
              patch.object(native.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
              self.assertRaisesRegex(native.NativeResetError, "multiple running instances")):
            native.reset_native("native-duplicate_label-0")

    def test_invalid_case_and_launch_failure_do_not_expand_scope(self) -> None:
        with self.assertRaises(ValueError):
            native.reset_native("native-long_tree-1")
        with (patch.object(native, "_validate_bundle_identity"),
              patch.object(Path, "is_file", return_value=True),
              patch.object(native, "_fixture_pids", return_value=set()),
              patch.object(native.os, "kill") as kill,
              patch.object(native.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "open")),
              self.assertRaisesRegex(native.NativeResetError, "failed to launch")):
            native.reset_native("native-duplicate_label-0")
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
