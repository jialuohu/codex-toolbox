from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts" / "check-codex-toolbox-setup.py"
SPEC = importlib.util.spec_from_file_location("check_codex_toolbox_setup", CHECKER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load setup checker: {CHECKER_PATH}")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class SetupCheckerScanTests(unittest.TestCase):
    def test_retired_reference_scan_checks_a_repo_nested_below_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / ".worktrees" / "fixture-repo"
            forbidden = repo_root / "docs" / "forbidden.md"
            ignored = repo_root / ".worktrees" / "ignored.md"
            retired_orchestrator = "sym" + "phony"
            forbidden.parent.mkdir(parents=True)
            ignored.parent.mkdir(parents=True)
            forbidden.write_text(f"{retired_orchestrator} is forbidden here\n")
            ignored.write_text(f"{retired_orchestrator} stays ignored here\n")

            scan = getattr(CHECKER, "scan_retired_reference_mentions", None)
            self.assertIsNotNone(scan, "setup checker must expose its retired-reference scan")
            if scan is None:
                return
            retired_mentions, tracker_mentions = scan(
                repo_root,
                CHECKER_PATH,
                retired_orchestrator,
            )

        self.assertEqual(
            retired_mentions,
            [("docs/forbidden.md", 1, f"{retired_orchestrator} is forbidden here")],
        )
        self.assertEqual(tracker_mentions, [])


if __name__ == "__main__":
    unittest.main()
