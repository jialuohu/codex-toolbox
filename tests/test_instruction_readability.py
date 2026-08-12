import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
REPO_AGENTS = ROOT / "AGENTS.md"
README = ROOT / "README.md"
PRETTY_SKILL = (
    ROOT / "plugins" / "diagram-tools" / "skills" / "pretty-mermaid" / "SKILL.md"
)
DIAGRAM_PLUGIN = ROOT / "plugins" / "diagram-tools" / ".codex-plugin" / "plugin.json"
EXPLAIN_SKILL = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "explain-clearly" / "SKILL.md"
)
SHIP_AGENT = (
    ROOT
    / "plugins"
    / "workflow-tools"
    / "skills"
    / "ship-toolbox"
    / "agents"
    / "openai.yaml"
)
WORKFLOW_PLUGIN = ROOT / "plugins" / "workflow-tools" / ".codex-plugin" / "plugin.json"


class InstructionBudgetTests(unittest.TestCase):
    def test_global_and_combined_instruction_budgets(self) -> None:
        global_size = GLOBAL_AGENTS.stat().st_size
        repo_size = REPO_AGENTS.stat().st_size

        self.assertLessEqual(global_size, 8_192)
        self.assertLessEqual(global_size + repo_size, 16_384)

    def test_global_points_detailed_contracts_to_owning_skills(self) -> None:
        global_text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        repo_text = REPO_AGENTS.read_text(encoding="utf-8")

        self.assertIn("Detailed workflow, quota, state-machine, and validation contracts", global_text)
        self.assertIn("Put detailed trigger, state-machine, quota, fallback", repo_text)
        self.assertNotIn("Current default plugins are", global_text)


class ReadabilityContractTests(unittest.TestCase):
    def test_global_defines_the_format_ladder_and_validation_guards(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")

        for expected in (
            "One conclusion or simple procedure",
            "Three or more comparable entities",
            "`$pretty-mermaid` by default",
            "native inline Mermaid only",
            "task-scoped temporary directory",
            "bundled Visualize",
            "standalone or hosted application",
            "not inline Visualize",
            "A visual is presentation, not evidence",
            "side to move",
            "move legality",
            "report ambiguity instead of inventing pieces",
            "Do not use generative image models for exact factual diagrams",
            "in CLI or IDE surfaces",
        ):
            self.assertIn(expected, text)

    def test_explanation_skill_uses_the_same_smallest_useful_format_contract(self) -> None:
        text = EXPLAIN_SKILL.read_text(encoding="utf-8")

        for expected in (
            "Choose the Smallest Useful Format",
            "Markdown table for three or more comparable entities",
            "`$pretty-mermaid` by default",
            "native inline Mermaid only",
            "editable `.mmd` source",
            "SVG on graphical surfaces",
            "ASCII in a terminal",
            "bundled Visualize",
            "A visual is presentation, not evidence",
            "For chess",
            "responsive and accessible",
            "CLI or IDE",
        ):
            self.assertIn(expected, text)

    def test_pretty_mermaid_default_routing_and_fallback_contract(self) -> None:
        global_text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        skill_text = PRETTY_SKILL.read_text(encoding="utf-8")
        explain_text = EXPLAIN_SKILL.read_text(encoding="utf-8")
        readme_text = README.read_text(encoding="utf-8")

        for expected in (
            "Use this skill by default whenever Mermaid is selected",
            "task-scoped temporary directory with `mktemp -d`",
            "default to SVG",
            "render ASCII",
            "explicit destination, format, theme, color, scale, or transparency",
            "native inline Mermaid only",
            "runtime is unavailable or rejects the syntax",
            "reuse the exact source",
            "$paper-figure-workflow",
        ):
            self.assertIn(expected, skill_text)

        for text in (global_text, explain_text, readme_text):
            self.assertIn("$pretty-mermaid", text)
            self.assertIn("default", text)
            self.assertIn("native inline Mermaid", text)

        for retired in (
            "Static relationships, hierarchy, or sequence: inline Mermaid",
            "Use native Mermaid for quick response diagrams",
            "Use native inline Mermaid for a quick in-task explanation",
            "inline Mermaid for static relationships",
            "inline Mermaid for quick task explanations",
        ):
            for text in (global_text, skill_text, explain_text, readme_text):
                self.assertNotIn(retired, text)

    def test_plugin_versions_bumped_without_implicit_ship_toolbox(self) -> None:
        workflow_manifest = json.loads(WORKFLOW_PLUGIN.read_text(encoding="utf-8"))
        diagram_manifest = json.loads(DIAGRAM_PLUGIN.read_text(encoding="utf-8"))
        ship_agent_text = SHIP_AGENT.read_text(encoding="utf-8")

        self.assertEqual(workflow_manifest["version"], "0.5.0")
        self.assertEqual(diagram_manifest["version"], "0.2.0")
        self.assertIn("allow_implicit_invocation: false", ship_agent_text)


if __name__ == "__main__":
    unittest.main()
