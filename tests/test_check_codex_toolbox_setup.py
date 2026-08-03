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

    def test_retired_reference_scan_distinguishes_tracker_integration_from_motion_vocabulary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "fixture-repo"
            policy = repo_root / "docs" / "policy.md"
            planning = repo_root / ".superpowers" / "plan.md"
            imported_motion = (
                repo_root
                / "plugins"
                / "design-engineering-tools"
                / "skills"
                / "animation-vocabulary"
                / "references"
                / "upstream.md"
            )
            tracker_name = "lin" + "ear"
            tracker_brand = tracker_name.title()
            tracker_url = f"https://{tracker_name}.app/example/issue/ABC-1"
            tracker_env = f"{tracker_name.upper()}_TEAM_ID"
            brand_policy = repo_root / "docs" / "brand-policy.md"
            policy.parent.mkdir(parents=True)
            planning.parent.mkdir(parents=True)
            imported_motion.parent.mkdir(parents=True)
            policy.write_text(f"Retired tracker: {tracker_url}\n")
            planning.write_text(f"Retired integration uses {tracker_env}.\n")
            brand_policy.write_text(
                "\n".join(
                    (
                        f"Use {tracker_brand} to track work.",
                        f"Retired {tracker_brand} client configuration.",
                        f"Remove the {tracker_brand} app integration.",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            imported_motion.write_text(
                f"Use a {tracker_name} timing function for a spinner.\n", encoding="utf-8"
            )

            retired_mentions, tracker_mentions = CHECKER.scan_retired_reference_mentions(
                repo_root,
                CHECKER_PATH,
                "sym" + "phony",
            )

        self.assertEqual(retired_mentions, [])
        self.assertEqual(
            sorted(tracker_mentions),
            sorted(
                [
                    (
                        "docs/policy.md",
                        1,
                        f"Retired tracker: {tracker_url}",
                    ),
                    (
                        ".superpowers/plan.md",
                        1,
                        f"Retired integration uses {tracker_env}.",
                    ),
                    (
                        "docs/brand-policy.md",
                        1,
                        f"Use {tracker_brand} to track work.",
                    ),
                    (
                        "docs/brand-policy.md",
                        2,
                        f"Retired {tracker_brand} client configuration.",
                    ),
                    (
                        "docs/brand-policy.md",
                        3,
                        f"Remove the {tracker_brand} app integration.",
                    ),
                ]
            ),
        )

    def test_retired_reference_scan_ignores_generated_runtime_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "fixture-repo"
            tracker_name = "lin" + "ear"
            for directory in (".venv", ".pytest_cache", ".ruff_cache", "node_modules"):
                generated = repo_root / directory / "generated.txt"
                generated.parent.mkdir(parents=True)
                generated.write_text(
                    f"Generated {tracker_name.title()} client metadata\n",
                    encoding="utf-8",
                )

            retired_mentions, tracker_mentions = CHECKER.scan_retired_reference_mentions(
                repo_root,
                CHECKER_PATH,
                "sym" + "phony",
            )

        self.assertEqual(retired_mentions, [])
        self.assertEqual(tracker_mentions, [])


if __name__ == "__main__":
    unittest.main()
