"""Check the scoped research-figure routing contract and fixture inventory."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "fixtures" / "research-figure-routing.json"
SKILLS = {
    "paper-figure-workflow": ROOT / "plugins/diagram-tools/skills/paper-figure-workflow/SKILL.md",
    "drawio": ROOT / "plugins/drawio-tools/skills/drawio/SKILL.md",
    "omnigraffle-workflow": ROOT / "plugins/omnigraffle-tools/skills/omnigraffle-workflow/SKILL.md",
    "archify": ROOT / "plugins/diagram-tools/skills/archify/SKILL.md",
    "pretty-mermaid": ROOT / "plugins/diagram-tools/skills/pretty-mermaid/SKILL.md",
}


class ResearchFigureRoutingTests(unittest.TestCase):
    def test_fixture_covers_precedence_and_ordinary_diagrams(self) -> None:
        corpus = json.loads(CASES.read_text(encoding="utf-8"))
        self.assertEqual(corpus["schema_version"], 1)
        cases = corpus["cases"]
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertGreaterEqual(len(cases), 7)
        self.assertEqual(set(SKILLS), {case["owner"] for case in cases})
        self.assertTrue(any(case["research_style"] for case in cases))
        self.assertTrue(any(not case["research_style"] for case in cases))
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["prompt"])
                self.assertTrue(case["reason"])
                self.assertIs(type(case["research_style"]), bool)
                self.assertTrue(SKILLS[case["owner"]].is_file())

    def test_skill_scope_preserves_existing_and_ordinary_diagrams(self) -> None:
        paper = SKILLS["paper-figure-workflow"].read_text(encoding="utf-8")
        drawio = SKILLS["drawio"].read_text(encoding="utf-8")
        omni = SKILLS["omnigraffle-workflow"].read_text(encoding="utf-8")
        archify = SKILLS["archify"].read_text(encoding="utf-8")
        mermaid = SKILLS["pretty-mermaid"].read_text(encoding="utf-8")
        self.assertIn("existing", paper.lower())
        self.assertIn("venue", paper.lower())
        self.assertIn("new research architecture, workflow and mechanism diagrams", paper.lower())
        self.assertIn("native acceptance", paper.lower())
        self.assertIn("`doctor --probe-app`", paper)
        self.assertIn("scripting.status=responding", paper)
        self.assertIn("make init-diagram", paper)
        self.assertIn("saved native document", paper)
        self.assertIn("ordinary workflow-map routing remains", paper.lower())
        self.assertIn("research", drawio.lower())
        self.assertIn("Preserve established figure style", omni)
        self.assertIn("ordinary diagrams retain", archify.lower())
        self.assertIn("ordinary diagrams retain", mermaid.lower())

    def test_research_workflow_preference_keeps_explicit_and_ordinary_owners(self) -> None:
        cases = {case["id"]: case for case in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
        self.assertEqual(cases["new-research-workflow-prefers-omni"]["owner"], "omnigraffle-workflow")
        self.assertEqual(cases["new-research-architecture-prefers-omni"]["owner"], "omnigraffle-workflow")
        self.assertEqual(cases["new-research-mechanism-prefers-omni"]["owner"], "omnigraffle-workflow")
        self.assertEqual(cases["implicit-omni-unready-fallback-drawio"]["owner"], "drawio")
        self.assertEqual(cases["research-workflow-explicit-drawio"]["owner"], "drawio")
        self.assertEqual(cases["research-workflow-project-drawio"]["owner"], "drawio")
        self.assertEqual(cases["explicit-omni-doctor-blocked"]["owner"], "omnigraffle-workflow")
        self.assertEqual(cases["ordinary-workflow-negative"]["owner"], "archify")


if __name__ == "__main__":
    unittest.main()
