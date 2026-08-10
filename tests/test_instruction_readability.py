import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
REPO_AGENTS = ROOT / "AGENTS.md"
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
            "inline Mermaid",
            "bundled Visualize",
            "`$pretty-mermaid`",
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
            "inline Mermaid",
            "bundled Visualize",
            "`$pretty-mermaid`",
            "A visual is presentation, not evidence",
            "For chess",
            "responsive and accessible",
            "CLI or IDE",
        ):
            self.assertIn(expected, text)

    def test_workflow_version_bumped_without_implicit_ship_toolbox(self) -> None:
        manifest = json.loads(WORKFLOW_PLUGIN.read_text(encoding="utf-8"))
        ship_agent_text = SHIP_AGENT.read_text(encoding="utf-8")

        self.assertEqual(manifest["version"], "0.4.0")
        self.assertIn("allow_implicit_invocation: false", ship_agent_text)


if __name__ == "__main__":
    unittest.main()
