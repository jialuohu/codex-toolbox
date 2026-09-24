"""Run the pasteable CUA controller against synthetic browser and native AX states."""

import os
import subprocess
import unittest
from pathlib import Path


class ComputerUseControllerTests(unittest.TestCase):
    def test_controller(self):
        root = Path(__file__).resolve().parents[1]
        for variant in ("readable", "compact"):
            with self.subTest(variant=variant):
                result = subprocess.run(
                    ["node", "--test", "--test-reporter=tap",
                     str(root / "tests/typesafe_computer_use_controller.cjs")],
                    capture_output=True, text=True, timeout=30, check=False,
                    env={**os.environ, "CU_CONTROLLER_VARIANT": variant},
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("# tests 30", result.stdout)


if __name__ == "__main__":
    unittest.main()
