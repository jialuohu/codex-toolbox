"""Behavior and syntax checks for the disposable computer-use fixtures."""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "plugins" / "typesafe-tools" / "computer_use_fixtures"


class LongTreeFixtureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_browser_long_tree_flow_and_reset(self) -> None:
        completed = subprocess.run(
            ["node", str(ROOT / "tests" / "fixture_long_tree_dom.cjs"),
             str(FIXTURES / "browser" / "index.html")],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"),
                         "macOS Swift compiler is required")
    def test_native_fixture_parses(self) -> None:
        completed = subprocess.run(
            ["swiftc", "-parse", str(FIXTURES / "native" / "JevCUFixture.swift")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
