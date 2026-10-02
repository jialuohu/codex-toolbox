"""Executable artifact checks and offline routing expectations, not model grading."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/diagram-tools"
FIXTURE = PLUGIN / "tests/fixtures/explanation-artifacts"
spec = importlib.util.spec_from_file_location("explanation_artifacts", PLUGIN / "scripts/eval-explanation-artifacts.py")
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


class RoutingFixtureContractTests(unittest.TestCase):
    """These checks protect test inputs; they do not run a routing model."""

    def test_compact_prose_contract_preserves_source_meaning(self) -> None:
        text = " ".join((PLUGIN / "skills/explain-clearly/SKILL.md").read_text().split())
        for phrase in ("quantities, units, equations, conditions, uncertainty, and source locators",
                       "consistent terms and explicit referents", "Define specialized terms at first use",
                       "not a claim of compliance"):
            self.assertIn(phrase, text)

    def test_current_cases_cover_medium_intent_and_failure_boundaries(self) -> None:
        fixture = json.loads((PLUGIN / "tests/fixtures/explanation-routing.json").read_text())
        cases = fixture["cases"]
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertEqual({case["medium"] for case in cases}, {
            "prose", "table", "diagram", "interactive", "publication", "native",
            "video_preview", "video_export", "disclosed_fallback"})
        known_owners = {"explain-clearly", "archify", "pretty-mermaid", "visualize",
                        "paper-figure-workflow", "drawio", "omnigraffle-workflow", "remotion"}
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(set(case["owners"]) <= known_owners)
                self.assertTrue(case["prompt"] and case["reason"] and case["forbidden_actions"])
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(by_id["brief-prose"]["forbidden_actions"],
                         ["probe_renderer", "open_native_app", "create_artifact"])
        self.assertIn("automatic_video_export", by_id["requested-video-preview"]["forbidden_actions"])
        self.assertIn("automatic_publication", by_id["local-only-map"]["forbidden_actions"])
        self.assertIn("claim_static_is_interactive", by_id["missing-interactive-owner"]["forbidden_actions"])

    def test_moved_skills_are_canonical_and_native_owners_remain_separate(self) -> None:
        for name in ("explain-clearly", "paper-figure-workflow"):
            candidates = list((ROOT / "plugins").glob(f"*/skills/{name}/SKILL.md"))
            self.assertEqual(candidates, [PLUGIN / f"skills/{name}/SKILL.md"])
        for name in ("drawio-tools", "omnigraffle-tools", "photo-tools", "design-engineering-tools"):
            self.assertTrue((ROOT / f"plugins/{name}/.codex-plugin/plugin.json").is_file())
        self.assertFalse((ROOT / "plugins/paper-figure-tools/.codex-plugin/plugin.json").exists())


@unittest.skipUnless(shutil.which("node"), "Node.js needed for actual JavaScript behavior")
class ArtifactVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Path(self.temporary.name) / "fixture"
        shutil.copytree(FIXTURE, self.fixture)

    def replace(self, name: str, old: str, new: str) -> None:
        path = self.fixture / name
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1))

    def test_actual_model_and_svg_match_independent_source_cases(self) -> None:
        receipt = evaluator.evaluate(self.fixture)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["mechanism_cases"], 5)
        self.assertEqual(receipt["scope"], "synthetic_fixture_only")
        for field in ("browser_interaction", "visual_review", "learning_effectiveness"):
            self.assertEqual(receipt[field], "unverified")

    def test_wrong_computation_fails_even_when_javascript_runs(self) -> None:
        self.replace("queue-model.mjs", "const finish = start + job.service;",
                     "const finish = start + job.service + 1;")
        with self.assertRaisesRegex(ValueError, "independent source calculations"):
            evaluator.evaluate(self.fixture)

    def test_reversed_dependency_fails_even_when_svg_is_well_formed(self) -> None:
        self.replace("queue.svg", 'data-from="A" data-to="B"', 'data-from="B" data-to="A"')
        with self.assertRaisesRegex(ValueError, "dependency direction"):
            evaluator.evaluate(self.fixture)

    def test_stale_visible_label_fails(self) -> None:
        self.replace("queue.svg", "B: 3–5 s", "B: 1–3 s")
        with self.assertRaisesRegex(ValueError, "visible time label"):
            evaluator.evaluate(self.fixture)

    def test_wrong_mark_duration_fails(self) -> None:
        self.replace("queue.svg", 'width="80" height="24"', 'width="120" height="24"')
        with self.assertRaisesRegex(ValueError, "timing geometry"):
            evaluator.evaluate(self.fixture)

    def test_detached_dependency_arrow_fails(self) -> None:
        self.replace("queue.svg", 'x2="200" y2="108"', 'x2="220" y2="108"')
        with self.assertRaisesRegex(ValueError, "dependency endpoints"):
            evaluator.evaluate(self.fixture)

    def test_removed_text_alternative_fails(self) -> None:
        self.replace("queue.svg", '<desc id="description">', '<metadata id="description">')
        self.replace("queue.svg", "</desc>", "</metadata>")
        with self.assertRaisesRegex(ValueError, "text alternative"):
            evaluator.evaluate(self.fixture)


if __name__ == "__main__":
    unittest.main()
