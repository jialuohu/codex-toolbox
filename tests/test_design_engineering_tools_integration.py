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
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".tmp",
                    ".venv",
                    ".pytest_cache",
                    ".ruff_cache",
                    "__pycache__",
                ),
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
        def rewrite_json(path: Path, change: Callable[[dict], None]) -> None:
            value = json.loads(path.read_text(encoding="utf-8"))
            change(value)
            path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

        def rewrite_marketplace(root: Path, change: Callable[[dict], None]) -> None:
            rewrite_json(root / ".agents" / "plugins" / "marketplace.json", change)

        def rewrite_manifest(root: Path, change: Callable[[dict], None]) -> None:
            rewrite_json(
                root / "plugins" / "design-engineering-tools" / ".codex-plugin" / "plugin.json",
                change,
            )

        def design_marketplace_entry(marketplace: dict) -> dict:
            return next(
                plugin
                for plugin in marketplace["plugins"]
                if plugin["name"] == "design-engineering-tools"
            )

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
                plugin = design_marketplace_entry(marketplace)
                plugin["policy"]["installation"] = "REQUIRES_APPROVAL"

            rewrite_marketplace(root, change)

        def change_marketplace_authentication(root: Path) -> None:
            rewrite_marketplace(
                root,
                lambda marketplace: design_marketplace_entry(marketplace)["policy"].update(
                    {"authentication": "NEVER"}
                ),
            )

        def change_marketplace_source(root: Path) -> None:
            rewrite_marketplace(
                root,
                lambda marketplace: design_marketplace_entry(marketplace)["source"].update(
                    {"source": "git"}
                ),
            )

        def change_marketplace_path(root: Path) -> None:
            rewrite_marketplace(
                root,
                lambda marketplace: design_marketplace_entry(marketplace)["source"].update(
                    {"path": "./plugins/wrong-tools"}
                ),
            )

        def change_manifest_name(root: Path) -> None:
            rewrite_manifest(root, lambda manifest: manifest.update({"name": "wrong-tools"}))

        def change_manifest_version(root: Path) -> None:
            rewrite_manifest(root, lambda manifest: manifest.update({"version": "0.1.1"}))

        def change_manifest_skills_path(root: Path) -> None:
            rewrite_manifest(root, lambda manifest: manifest.update({"skills": "./wrong-skills/"}))

        def change_manifest_capabilities(root: Path) -> None:
            def change(manifest: dict) -> None:
                manifest["interface"]["capabilities"] = ["Read"]

            rewrite_manifest(root, change)

        def add_manifest_mcp_declaration(root: Path) -> None:
            rewrite_manifest(root, lambda manifest: manifest.update({"mcpServers": "./.mcp.json"}))

        def remove_default_install(root: Path) -> None:
            path = root / "scripts" / "setup-codex-toolbox.sh"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    '  "design-engineering-tools"\n', '  # "design-engineering-tools"\n', 1
                ),
                encoding="utf-8",
            )

        def remove_one_skill(root: Path) -> None:
            (root / "plugins" / "design-engineering-tools" / "skills" / "prototype").rename(
                root / "plugins" / "design-engineering-tools" / "skills" / "prototype-missing"
            )

        def change_skill_invocation_policy(root: Path) -> None:
            path = (
                root
                / "plugins"
                / "design-engineering-tools"
                / "skills"
                / "prototype"
                / "agents"
                / "openai.yaml"
            )
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "allow_implicit_invocation: false",
                    "allow_implicit_invocation: true",
                    1,
                ),
                encoding="utf-8",
            )

        def remove_provenance(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "PROVENANCE.md"
            path.write_text("# Provenance\n\nUnavailable.\n", encoding="utf-8")

        def remove_provenance_url(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "PROVENANCE.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "https://github.com/emilkowalski/skills",
                    "https://example.invalid/skills",
                    1,
                ),
                encoding="utf-8",
            )

        def remove_provenance_commit(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "PROVENANCE.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "70744e3816f1d93eafb697161a8b880a7384c5ff",
                    "missing-commit",
                    1,
                ),
                encoding="utf-8",
            )

        def remove_provenance_license(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "PROVENANCE.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("MIT", "other license", 1),
                encoding="utf-8",
            )

        def remove_boundary_rule(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "SHARED-BOUNDARIES.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Target project conventions and design system",
                    "Target project conventions",
                    1,
                ),
                encoding="utf-8",
            )

        def remove_explicit_user_boundary(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "SHARED-BOUNDARIES.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Explicit user direction", "User direction", 1
                ),
                encoding="utf-8",
            )

        def remove_accessibility_boundary(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "SHARED-BOUNDARIES.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Accessibility requirements", "Accessibility guidance", 1
                ),
                encoding="utf-8",
            )

        def remove_official_docs_boundary(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "SHARED-BOUNDARIES.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Current official documentation", "Current documentation", 1
                ),
                encoding="utf-8",
            )

        def remove_advisory_opinions_boundary(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "SHARED-BOUNDARIES.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Imported opinions are advisory", "Imported opinions are binding", 1
                ),
                encoding="utf-8",
            )

        def reorder_authority_boundary(root: Path) -> None:
            path = root / "plugins" / "design-engineering-tools" / "SHARED-BOUNDARIES.md"
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            explicit_index = next(index for index, line in enumerate(lines) if "Explicit user direction" in line)
            project_index = next(
                index
                for index, line in enumerate(lines)
                if "Target project conventions and design system" in line
            )
            lines[explicit_index], lines[project_index] = lines[project_index], lines[explicit_index]
            path.write_text("".join(lines), encoding="utf-8")

        def erase_routing_boundary(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Use `ui-ux-pro-max` for broad UI/UX",
                    "Use the broad design default",
                    1,
                ),
                encoding="utf-8",
            )

        def erase_animation_vocabulary_routing(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "$animation-vocabulary", "$motion-glossary", 1
                ),
                encoding="utf-8",
            )

        def erase_apple_routing(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "`$apple-design` for explicitly Apple-like physical interaction",
                    "Use `$ios-design` for interactions",
                    1,
                ),
                encoding="utf-8",
            )

        def erase_apple_generic_ui_boundary(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "layout, typography, color, accessibility, and visual polish",
                    "Generic visual requests may use either skill",
                    1,
                ),
                encoding="utf-8",
            )

        def erase_emil_routing(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "`$emil-design-eng` for explicit Emil Kowalski-style motion craft",
                    "generic motion craft",
                    1,
                ),
                encoding="utf-8",
            )

        def erase_discovery_routing(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "read-only animation audit skills for their named purposes",
                    "generic animation guidance",
                    1,
                ),
                encoding="utf-8",
            )

        def erase_audit_routing(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "$improve-animations", "$improve-motion", 1
                ),
                encoding="utf-8",
            )

        def erase_explicit_only_routing(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "are explicit-only skills", "are default skills", 1
                ),
                encoding="utf-8",
            )

        def erase_authority_routing(root: Path) -> None:
            path = root / "config" / "codex" / "AGENTS.global.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Project design systems and accessibility requirements override imported advice",
                    "Imported advice overrides project requirements",
                    1,
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

        def erase_readme_scope(root: Path) -> None:
            path = root / "README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "motion vocabulary", "motion guidance", 1
                ),
                encoding="utf-8",
            )

        def erase_readme_url(root: Path) -> None:
            path = root / "README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "https://github.com/emilkowalski/skills", "https://example.invalid/skills", 1
                ),
                encoding="utf-8",
            )

        def erase_readme_commit(root: Path) -> None:
            path = root / "README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "70744e3816f1d93eafb697161a8b880a7384c5ff", "missing-commit", 1
                ),
                encoding="utf-8",
            )

        def erase_readme_explicit_only(root: Path) -> None:
            path = root / "README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "are explicit-only skills", "are default skills", 1
                ),
                encoding="utf-8",
            )

        def add_plugin_mcp_file(root: Path) -> None:
            (root / "plugins" / "design-engineering-tools" / ".mcp.json").write_text(
                "{}\n", encoding="utf-8"
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
            (change_manifest_name, "design-engineering-tools manifest name must be exact"),
            (change_manifest_version, "design-engineering-tools manifest version must be 0.1.0"),
            (change_manifest_skills_path, "design-engineering-tools manifest must expose ./skills/"),
            (change_manifest_capabilities, "design-engineering-tools manifest capabilities must be Read, Write, and Interactive"),
            (add_manifest_mcp_declaration, "design-engineering-tools manifest must not declare MCP servers"),
            (remove_marketplace_plugin, "marketplace must include design-engineering-tools"),
            (change_marketplace_source, "design-engineering-tools marketplace source must be local"),
            (change_marketplace_path, "design-engineering-tools marketplace path must be ./plugins/design-engineering-tools"),
            (make_marketplace_policy_unsafe, "design-engineering-tools marketplace installation policy must be AVAILABLE"),
            (change_marketplace_authentication, "design-engineering-tools marketplace authentication policy must be ON_INSTALL"),
            (remove_default_install, "setup script must install design-engineering-tools as an active default plugin"),
            (remove_one_skill, "design-engineering-tools skills inventory must be exactly eight expected skills"),
            (change_skill_invocation_policy, "design-engineering-tools skill invocation policies must preserve explicit-only skills"),
            (remove_provenance_url, "design-engineering-tools provenance must cite the upstream URL"),
            (remove_provenance_commit, "design-engineering-tools provenance must cite the upstream commit"),
            (remove_provenance_license, "design-engineering-tools provenance must cite the MIT license"),
            (remove_explicit_user_boundary, "design-engineering-tools shared authority boundary must preserve explicit user direction"),
            (remove_boundary_rule, "design-engineering-tools shared authority boundary must preserve the project design system"),
            (remove_accessibility_boundary, "design-engineering-tools shared authority boundary must preserve accessibility requirements"),
            (remove_official_docs_boundary, "design-engineering-tools shared authority boundary must preserve current official documentation"),
            (remove_advisory_opinions_boundary, "design-engineering-tools shared authority boundary must preserve imported opinions as advisory"),
            (reorder_authority_boundary, "design-engineering-tools shared authority boundary must preserve priority order"),
            (erase_routing_boundary, "global AGENTS design-engineering routing must keep ui-ux-pro-max broad"),
            (erase_animation_vocabulary_routing, "global AGENTS design-engineering routing must map vague motion naming to animation-vocabulary"),
            (erase_apple_routing, "global AGENTS design-engineering routing must map Apple-like interactions to apple-design"),
            (erase_apple_generic_ui_boundary, "global AGENTS design-engineering routing must keep generic typography, accessibility, and reduced motion with ui-ux-pro-max"),
            (erase_emil_routing, "global AGENTS design-engineering routing must reserve emil-design-eng for explicit Emil or animations.dev requests"),
            (erase_discovery_routing, "global AGENTS design-engineering routing must map motion discovery and audits to their skills"),
            (erase_authority_routing, "global AGENTS design-engineering routing must preserve the authority override order"),
            (erase_readme_scope, "README design-engineering section must describe motion vocabulary scope"),
            (erase_readme_url, "README design-engineering section must cite the upstream URL"),
            (erase_readme_commit, "README design-engineering section must cite the upstream commit"),
            (erase_readme_explicit_only, "README design-engineering section must identify explicit-only skills"),
            (erase_readme_reload_guidance, "README design-engineering section must require a fresh Codex task"),
            (add_plugin_mcp_file, "design-engineering-tools must not define an MCP config file"),
            (manage_a_design_plugin_mcp, "design-engineering-tools must not be a managed MCP server"),
        )

        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                self.assert_checker_rejects(mutate, expected_message)


if __name__ == "__main__":
    unittest.main()
