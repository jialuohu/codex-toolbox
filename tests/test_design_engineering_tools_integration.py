from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-codex-toolbox-setup.py"


class DesignEngineeringToolsIntegrationTests(unittest.TestCase):
    """Protect the installation and routing contract for focused design tools.

    These tests fail if the checker stops rejecting a broken marketplace, setup,
    policy, provenance, routing, documentation, or MCP boundary. The contract
    is intentionally exercised through a copied toolbox so it runs the same
    checker users rely on, rather than asserting source-text fragments.
    """

    def run_checker(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, root / "scripts" / "check-codex-toolbox-setup.py"],
            check=False,
            cwd=root,
            text=True,
            capture_output=True,
        )

    def assert_checker_rejects(
        self,
        mutate: Callable[[Path], None],
        expected_message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_root = Path(temporary_directory) / "toolbox"
            shutil.copytree(
                ROOT,
                copied_root,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )
            mutate(copied_root)

            result = self.run_checker(copied_root)

        self.assertNotEqual(
            result.returncode,
            0,
            "setup checker accepted a broken design-engineering-tools contract",
        )
        self.assertIn(expected_message, result.stdout + result.stderr)

    def test_setup_checker_accepts_the_complete_design_engineering_contract(self) -> None:
        result = self.run_checker(ROOT)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_setup_checker_rejects_design_engineering_contract_regressions(self) -> None:
        def rewrite_marketplace(root: Path, change: Callable[[dict], None]) -> None:
            path = root / ".agents" / "plugins" / "marketplace.json"
            marketplace = json.loads(path.read_text(encoding="utf-8"))
            change(marketplace)
            path.write_text(json.dumps(marketplace, indent=2) + "\n", encoding="utf-8")

        def remove_marketplace_plugin(root: Path) -> None:
            rewrite_marketplace(
                root,
                lambda marketplace: marketplace.update(
                    {
                        "plugins": [
                            plugin
                            for plugin in marketplace["plugins"]
                            if plugin["name"] != "design-engineering-tools"
                        ]
                    }
                ),
            )

        def make_marketplace_policy_unsafe(root: Path) -> None:
            def change(marketplace: dict) -> None:
                plugin = next(
                    plugin
                    for plugin in marketplace["plugins"]
                    if plugin["name"] == "design-engineering-tools"
                )
                plugin["policy"]["installation"] = "REQUIRES_APPROVAL"

            rewrite_marketplace(root, change)

        def remove_default_install(root: Path) -> None:
            path = root / "scripts" / "setup-codex-toolbox.sh"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    '  "design-engineering-tools"\n', "", 1
                ),
                encoding="utf-8",
            )

        def remove_one_skill(root: Path) -> None:
            (root / "plugins" / "design-engineering-tools" / "skills" / "prototype").rename(
                root / "plugins" / "design-engineering-tools" / "skills" / "prototype-missing"
            )

        def remove_provenance(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "PROVENANCE.md"
            path.write_text("# Provenance\n\nUnavailable.\n", encoding="utf-8")

        def erase_routing_boundary(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Use the `ui-ux-pro-max` skill", "Use the broad design skill", 1
                ),
                encoding="utf-8",
            )

        def erase_readme_reload_guidance(root: Path) -> None:
            path = root / "README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Start a fresh Codex task after installing or\nupgrading",
                    "Restart Codex",
                    1,
                ),
                encoding="utf-8",
            )

        def manage_a_design_plugin_mcp(root: Path) -> None:
            path = root / "scripts" / "setup-codex-toolbox.sh"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'MANAGED_MCP_SERVERS=(\n',
                    'MANAGED_MCP_SERVERS=(\n  "design-engineering-tools"\n',
                    1,
                ),
                encoding="utf-8",
            )

        cases: tuple[tuple[Callable[[Path], None], str], ...] = (
            (remove_marketplace_plugin, "marketplace must include design-engineering-tools"),
            (make_marketplace_policy_unsafe, "design-engineering-tools marketplace policy"),
            (remove_default_install, "setup script must install the design-engineering-tools plugin"),
            (remove_one_skill, "design-engineering-tools must expose exactly eight skills"),
            (remove_provenance, "design-engineering-tools provenance must cite the upstream URL and commit"),
            (erase_routing_boundary, "global AGENTS design-engineering routing must keep ui-ux-pro-max broad"),
            (erase_readme_reload_guidance, "README design-engineering guidance must require a fresh task"),
            (manage_a_design_plugin_mcp, "design-engineering-tools must not be a managed MCP server"),
        )

        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)


if __name__ == "__main__":
    unittest.main()
