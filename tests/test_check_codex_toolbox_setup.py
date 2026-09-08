from __future__ import annotations

import copy
import importlib.util
import json
import shutil
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


class PhotoToolsSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.defaults = CHECKER.shell_array_entries(
            (ROOT / "scripts/setup-codex-toolbox.sh").read_text(), "DEFAULT_PLUGINS"
        )

    def test_photo_plugin_is_discoverable_and_installed_by_setup(self) -> None:
        CHECKER.validate_photo_tools_contract(self.marketplace, self.defaults)

    def test_broken_registration_or_default_install_is_rejected(self) -> None:
        for failure in ("missing-entry", "duplicate-entry", "wrong-source", "missing-default"):
            with self.subTest(failure=failure):
                marketplace = copy.deepcopy(self.marketplace)
                defaults = self.defaults.copy()
                entry = next(item for item in marketplace["plugins"] if item["name"] == "photo-tools")
                if failure == "missing-entry":
                    marketplace["plugins"].remove(entry)
                elif failure == "duplicate-entry":
                    marketplace["plugins"].append(copy.deepcopy(entry))
                elif failure == "wrong-source":
                    entry["source"]["path"] = "./plugins/missing-tools"
                else:
                    defaults.remove("photo-tools")
                with self.assertRaises(SystemExit):
                    CHECKER.validate_photo_tools_contract(marketplace, defaults)

    def test_missing_skill_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugins/photo-tools"
            shutil.copytree(ROOT / "plugins/photo-tools", plugin)
            skill = plugin / "skills/rubber-stamp-travel-poster/SKILL.md"
            skill.rename(skill.with_suffix(".missing"))
            with self.assertRaisesRegex(SystemExit, "must include SKILL.md"):
                CHECKER.validate_photo_tools_contract(self.marketplace, self.defaults, root)

    def test_missing_or_changed_mono_color_import_is_rejected(self) -> None:
        for failure in ("entry", "metadata", "catalog", "license", "checksum", "pin", "inventory"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plugin = root / "plugins/photo-tools"
                shutil.copytree(ROOT / "plugins/photo-tools", plugin)
                skill = plugin / "skills/mono-color"
                if failure in ("entry", "metadata", "catalog", "license"):
                    relative = {
                        "entry": "SKILL.md",
                        "metadata": "agents/openai.yaml",
                        "catalog": "references/design-system/colors.json",
                        "license": "references/LICENSE",
                    }[failure]
                    (skill / relative).unlink()
                elif failure == "checksum":
                    (skill / "references/upstream.md").write_text("Truncated import.\n")
                else:
                    path = plugin / "mono-color-upstream.json"
                    data = json.loads(path.read_text())
                    if failure == "pin":
                        data["commit"] = "main"
                    else:
                        data["files"][0]["local_path"] = "../outside"
                    path.write_text(json.dumps(data))
                with self.assertRaises(SystemExit):
                    CHECKER.validate_photo_tools_contract(self.marketplace, self.defaults, root)


class SetupCheckerScanTests(unittest.TestCase):
    def test_retired_tracker_scan_checks_a_repo_nested_below_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / ".worktrees" / "fixture-repo"
            forbidden = repo_root / "docs" / "forbidden.md"
            ignored = repo_root / ".worktrees" / "ignored.md"
            tracker_name = "lin" + "ear"
            tracker_brand = tracker_name.title()
            forbidden.parent.mkdir(parents=True)
            ignored.parent.mkdir(parents=True)
            forbidden.write_text(f"Use {tracker_brand} to track work.\n")
            ignored.write_text(f"Use {tracker_brand} to track work.\n")

            scan = getattr(CHECKER, "scan_retired_tracker_mentions", None)
            self.assertIsNotNone(scan, "setup checker must expose its retired-tracker scan")
            if scan is None:
                return
            tracker_mentions = scan(
                repo_root,
                CHECKER_PATH,
            )

        self.assertEqual(
            tracker_mentions,
            [("docs/forbidden.md", 1, f"Use {tracker_brand} to track work.")],
        )

    def test_retired_tracker_scan_distinguishes_integration_from_motion_vocabulary(
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

            tracker_mentions = CHECKER.scan_retired_tracker_mentions(
                repo_root,
                CHECKER_PATH,
            )

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

    def test_retired_tracker_scan_ignores_generated_runtime_directories(self) -> None:
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

            tracker_mentions = CHECKER.scan_retired_tracker_mentions(
                repo_root,
                CHECKER_PATH,
            )

        self.assertEqual(tracker_mentions, [])


if __name__ == "__main__":
    unittest.main()
