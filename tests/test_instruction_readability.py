import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
REPO_AGENTS = ROOT / "AGENTS.md"
DIAGRAM_DOC = ROOT / "docs" / "diagrams.md"
WORKFLOW_DOC = ROOT / "docs" / "workflows.md"
PRETTY_SKILL = (
    ROOT / "plugins" / "diagram-tools" / "skills" / "pretty-mermaid" / "SKILL.md"
)
ARCHIFY_SKILL = ROOT / "plugins" / "diagram-tools" / "skills" / "archify" / "SKILL.md"
ARCHIFY_OPENAI = ARCHIFY_SKILL.parent / "agents" / "openai.yaml"
DIAGRAM_PLUGIN = ROOT / "plugins" / "diagram-tools" / ".codex-plugin" / "plugin.json"
DRAWIO_SKILL = ROOT / "plugins" / "drawio-tools" / "skills" / "drawio" / "SKILL.md"
PAPER_FIGURE_SKILL = (
    ROOT / "plugins" / "diagram-tools" / "skills" / "paper-figure-workflow" / "SKILL.md"
)
EXPLAIN_SKILL = (
    ROOT / "plugins" / "diagram-tools" / "skills" / "explain-clearly" / "SKILL.md"
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
CLAUDE_COUNSELOR = (
    ROOT / "plugins" / "workflow-tools" / "skills" / "claude-counselor" / "SKILL.md"
)
CLAUDE_COUNSELOR_AGENT = CLAUDE_COUNSELOR.parent / "agents" / "openai.yaml"
CHATGPT_PLANNER = CLAUDE_COUNSELOR.parent.parent / "chatgpt-planner" / "SKILL.md"
CHATGPT_PLANNER_AGENT = CHATGPT_PLANNER.parent / "agents" / "openai.yaml"


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

    def test_global_routes_cleanup_and_preserves_user_work(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        self.assertIn("$typesafe-computer-use` for GUI observation and cleanup", text)
        for contract in (
            "Track task-opened tabs/windows/apps",
            "close them after verification",
            "Quit only task-started idle apps",
            "pre-existing/unsaved work",
            "active handoffs",
            "explicitly requested or required open results",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, text)


class ReadabilityContractTests(unittest.TestCase):
    def test_archify_preview_cleanup_is_required_and_packaged(self) -> None:
        entry = ARCHIFY_SKILL.read_text(encoding="utf-8")
        reference = ARCHIFY_SKILL.parent / "references" / "cleanup.md"
        publisher = ARCHIFY_SKILL.parent.parent / "diagram-publish" / "SKILL.md"
        self.assertTrue(reference.is_file())
        self.assertIn("](references/cleanup.md)", entry)
        self.assertIn("](../archify/references/cleanup.md)", publisher.read_text())
        text = " ".join(reference.read_text(encoding="utf-8").split())
        for contract in (
            "exact browser/tab handle",
            "--no-open",
            "After success or failure",
            "verify its ID is absent",
            "pre-existing/borrowed",
            "unsaved edits, pending work",
            "open/show/keep-open",
            "Stop the owned preview server",
            "original terminal session or exact child handle",
            "Verify terminal completion",
            "cleanup unverified",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, text)

    def test_global_defines_the_format_ladder_and_validation_guards(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")

        for expected in (
            "One conclusion/simple procedure",
            "Three or more comparable entities/repeated fields",
            "$archify",
            "$pretty-mermaid",
            "task-scoped temporary output",
            "$drawio",
            "Visualize",
            "Standalone or hosted application",
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
            "Markdown table for three or more comparable",
            "$archify",
            "$pretty-mermaid",
            "native inline Mermaid only",
            "bundled Visualize",
            "validate visual data",
            "For chess",
            "responsive and accessible",
            "CLI or IDE",
        ):
            self.assertIn(expected, text)
        self.assertIn("There is no required example count or fixed sequence", text)
        self.assertNotIn("exactly one worked", text)

    def test_pretty_mermaid_default_routing_and_fallback_contract(self) -> None:
        global_text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        skill_text = PRETTY_SKILL.read_text(encoding="utf-8")
        explain_text = EXPLAIN_SKILL.read_text(encoding="utf-8")
        readme_text = DIAGRAM_DOC.read_text(encoding="utf-8")

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
            "$drawio",
        ):
            self.assertIn(expected, skill_text)

        for text in (global_text, explain_text, readme_text):
            self.assertIn("$pretty-mermaid", text)

        for text in (skill_text, explain_text, readme_text):
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

    def test_drawio_owns_advanced_editable_work_without_replacing_mermaid(self) -> None:
        global_text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        pretty_text = PRETTY_SKILL.read_text(encoding="utf-8")
        drawio_text = DRAWIO_SKILL.read_text(encoding="utf-8")
        paper_text = PAPER_FIGURE_SKILL.read_text(encoding="utf-8")

        self.assertIn("Explicit Mermaid/`.mmd`, terminal ASCII", global_text)
        self.assertIn("`$pretty-mermaid`", global_text)
        self.assertIn("$drawio` owns explicit native, multi-page, WYSIWYG", global_text)
        self.assertIn("Use `$drawio` for explicit draw.io", pretty_text)
        self.assertIn("$pretty-mermaid` owns explicit", drawio_text)
        self.assertIn("$paper-figure-workflow", drawio_text)
        self.assertIn("Use `$drawio` for native `.drawio` creation", paper_text)

    def test_archify_owns_graphical_maps_without_erasing_format_boundaries(self) -> None:
        global_text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        explain_text = EXPLAIN_SKILL.read_text(encoding="utf-8")
        readme_text = DIAGRAM_DOC.read_text(encoding="utf-8")
        archify_text = ARCHIFY_SKILL.read_text(encoding="utf-8")
        archify_openai = ARCHIFY_OPENAI.read_text(encoding="utf-8")
        pretty_text = PRETTY_SKILL.read_text(encoding="utf-8")
        drawio_text = DRAWIO_SKILL.read_text(encoding="utf-8")
        paper_text = PAPER_FIGURE_SKILL.read_text(encoding="utf-8")

        for text in (global_text, explain_text, readme_text, archify_text):
            self.assertIn("$archify", text)

        for expected in (
            "architecture",
            "workflow",
            "sequence",
            "dataflow",
            "lifecycle",
            "$pretty-mermaid",
            "$drawio",
            "$paper-figure-workflow",
            "Visualize",
        ):
            self.assertIn(expected, archify_text)

        self.assertIn("allow_implicit_invocation: true", archify_openai)
        self.assertIn("$archify", archify_openai)
        self.assertIn("$archify", pretty_text)
        self.assertIn("$archify", drawio_text)
        self.assertIn("publication", paper_text)
        self.assertIn("Visualize", global_text)
        self.assertIn("terminal", pretty_text)
        self.assertIn("multi-page", drawio_text)

    def test_manifest_versions_and_explicit_shipping(self) -> None:
        workflow_manifest = json.loads(WORKFLOW_PLUGIN.read_text(encoding="utf-8"))
        diagram_manifest = json.loads(DIAGRAM_PLUGIN.read_text(encoding="utf-8"))
        ship_agent_text = SHIP_AGENT.read_text(encoding="utf-8")

        for manifest in (workflow_manifest, diagram_manifest):
            self.assertRegex(manifest["version"], r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
        diagram_package = json.loads((DIAGRAM_PLUGIN.parents[1] / "package.json").read_text())
        self.assertEqual(diagram_manifest["version"], diagram_package["version"])
        self.assertIn("allow_implicit_invocation: false", ship_agent_text)

    def test_claude_counselor_is_bounded_and_implicitly_available(self) -> None:
        global_text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        skill_text = CLAUDE_COUNSELOR.read_text(encoding="utf-8")
        agent_text = CLAUDE_COUNSELOR_AGENT.read_text(encoding="utf-8")
        readme_text = WORKFLOW_DOC.read_text(encoding="utf-8")

        for text in (global_text, skill_text, readme_text):
            self.assertIn("$claude-counselor", text)
        for expected in (
            "at most two calls",
            "600 seconds",
            "--timeout-seconds 900",
            "Metadata-only JSON",
            "do not shorten it to 120 seconds",
            "wrapper never discovers or reads files",
            "disabled tools",
            "no session persistence",
            "Codex remains",
            "make no automatic retry",
        ):
            self.assertIn(expected, skill_text)
        self.assertIn("allow_implicit_invocation: true", agent_text)

    def test_chatgpt_planner_routes_by_mode_without_replacing_claude(self) -> None:
        global_text = GLOBAL_AGENTS.read_text(encoding="utf-8")
        skill_text = CHATGPT_PLANNER.read_text(encoding="utf-8")
        agent_text = CHATGPT_PLANNER_AGENT.read_text(encoding="utf-8")
        docs = WORKFLOW_DOC.read_text(encoding="utf-8")

        self.assertIn("Automatically use `$chatgpt-planner` only in Plan mode", global_text)
        self.assertIn("Use `$claude-counselor` for one plan and review on major changes", global_text)
        self.assertIn("active collaboration mode from the current developer instructions", skill_text)
        self.assertIn("Each task has one", skill_text)
        self.assertIn("global setup", skill_text)
        self.assertIn("execution mode**, skip Pro planning", skill_text)
        self.assertIn("there is no complexity threshold", skill_text)
        self.assertIn("allow_implicit_invocation: true", agent_text)
        self.assertIn("$chatgpt-planner", docs)
        self.assertIn("Direct execution, including major work | None", docs)


if __name__ == "__main__":
    unittest.main()
