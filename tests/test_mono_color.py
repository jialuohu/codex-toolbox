"""Offline import and discovery checks; these do not certify model behavior."""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import audit_skill_instructions as audit


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/photo-tools"
SKILL = PLUGIN / "skills/mono-color"
REFERENCES = SKILL / "references"
CASES = ROOT / "tests/fixtures/mono-color-routing.json"
CATALOGS = {"colors", "typography", "compositions", "carriers", "imperfections", "rhythm"}


def strict_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"non-JSON constant: {value}")

    return json.loads(path.read_text(), object_pairs_hook=unique_pairs,
                      parse_constant=reject_constant)


class MonoColorImportTests(unittest.TestCase):
    def test_all_json_is_strict(self):
        for path in [*PLUGIN.rglob("*.json"), CASES]:
            with self.subTest(path=path):
                strict_json(path)

    def test_complete_snapshot_has_no_extra_artwork_or_nested_entrypoints(self):
        manifest = strict_json(PLUGIN / "mono-color-upstream.json")
        expected = {
            "SKILL.md", "LICENSE", "evals/evals.json", "evals/schema.json",
            "scripts/validate_evals.py",
            *(f"design-system/{name}.json" for name in CATALOGS),
        }
        self.assertEqual({item["upstream_path"] for item in manifest["files"]}, expected)
        recorded = set()
        for item in manifest["files"]:
            path = PLUGIN / item["local_path"]
            self.assertTrue(path.is_relative_to(REFERENCES))
            self.assertFalse(path.is_symlink())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
            recorded.add(path)
        self.assertEqual({p for p in REFERENCES.rglob("*") if p.is_file()}, recorded)
        self.assertEqual(list(SKILL.rglob("SKILL.md")), [SKILL / "SKILL.md"])
        self.assertEqual(
            hashlib.sha256((REFERENCES / "upstream.md").read_bytes()).hexdigest(),
            "8274bc1f30a92a9dc715c03c3fb9aeaa060fb5a12fd58dfe8d977ae98a26bd76",
        )
        license_text = (REFERENCES / "LICENSE").read_text()
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Yan Liu", license_text)

    def test_upstream_eval_validator_runs_offline_without_artwork(self):
        result = subprocess.run(
            [sys.executable, str(REFERENCES / "scripts/validate_evals.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cases = strict_json(REFERENCES / "evals/evals.json")["evals"]
        self.assertIn(f"Validated {len(cases)} mono-color evaluation cases.", result.stdout)
        known_inks = {ink["hex"] for ink in strict_json(REFERENCES / "design-system/colors.json")["inks"]}
        layouts = {layout["layout"] for layout in strict_json(REFERENCES / "design-system/compositions.json")["compositions"]}
        for case in cases:
            self.assertLessEqual(set(case["assertions"]["ink_hexes"]), known_inks)
            self.assertIn(case["assertions"]["layout"], layouts)


class MonoColorCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = {
            path.stem: strict_json(path)
            for path in (REFERENCES / "design-system").glob("*.json")
        }

    def unique_ids(self, items):
        ids = [item["id"] for item in items]
        self.assertTrue(ids)
        self.assertTrue(all(isinstance(value, str) and value for value in ids))
        self.assertEqual(len(ids), len(set(ids)))
        return set(ids)

    def percent_range(self, values):
        self.assertEqual(len(values), 2)
        self.assertTrue(0 < values[0] <= values[1] <= 100)

    def test_catalog_versions_colors_and_palette_references(self):
        self.assertEqual(set(self.catalogs), CATALOGS)
        for catalog in self.catalogs.values():
            self.assertEqual(catalog["schema_version"], 1)
        colors = self.catalogs["colors"]
        inks = self.unique_ids(colors["inks"])
        substrates = self.unique_ids(colors["substrates"])
        palettes = self.unique_ids(colors["palettes"])
        self.assertEqual(len(inks), 19)
        for color in [*colors["inks"], *colors["substrates"]]:
            self.assertRegex(color["hex"], r"^#[0-9A-F]{6}$")
        for substrate in colors["substrates"]:
            self.assertIs(substrate["counts_as_ink"], False)
            self.assertTrue(substrate["use_for"])
        for palette in colors["palettes"]:
            self.assertLessEqual(set(palette["ink_ids"]), inks)
            self.assertEqual(len(palette["ink_ids"]), 1 if palette["mode"] == "pure one-ink" else 2)
            self.assertEqual(len(palette["ink_ids"]), len(set(palette["ink_ids"])))
        defaults = colors["defaults"]
        self.assertIn(defaults["substrate_id"], substrates)
        self.assertIn(defaults["palette_id"], palettes)
        self.assertEqual(defaults["dominant_percent"], [70, 85])
        self.assertEqual(defaults["accent_percent"], [15, 30])

    def test_layout_typography_and_carrier_contracts(self):
        for name, field in (("typography", "roles"), ("compositions", "compositions"), ("carriers", "carriers")):
            self.unique_ids(self.catalogs[name][field])
        for role in self.catalogs["typography"]["roles"]:
            for field in ("display", "support", "behavior"):
                self.assertTrue(role[field])
        for layout in self.catalogs["compositions"]["compositions"]:
            self.percent_range(layout["dominant_subject_percent"])
            self.percent_range(layout["empty_paper_percent"])
            self.assertEqual(layout["manual_gesture_limit"], 1)
        for carrier in self.catalogs["carriers"]["carriers"]:
            self.assertTrue(carrier["ratios"])
            self.assertTrue(carrier["required_signals"])
            self.assertTrue(carrier["forbidden_signals"])
            for ratio in carrier["ratios"]:
                self.assertRegex(ratio, r"^[1-9][0-9]*:[1-9][0-9]*$")

    def test_reproduction_and_rhythm_preserve_structural_bounds(self):
        imperfections = self.catalogs["imperfections"]
        self.unique_ids(imperfections["effects"])
        self.assertEqual(imperfections["selection"]["contemporary_effect_count"], [0, 2])
        self.assertEqual(imperfections["selection"]["material_effect_count"], [2, 3])
        self.assertIs(imperfections["selection"]["preserve_across_retries"], True)
        self.assertTrue(imperfections["selection"]["seed_strategy"])
        for effect in imperfections["effects"]:
            ranges = [v for k, v in effect.items() if k.endswith(("_percent", "_mm"))]
            self.assertEqual(len(ranges), 1)
            self.percent_range(ranges[0])
            self.assertTrue(effect["applies_to"])
        rhythm = self.catalogs["rhythm"]
        self.assertIn(rhythm["default_profile"], self.unique_ids(rhythm["profiles"]))
        self.assertTrue(rhythm["focal_events"])
        self.assertTrue(rhythm["release_devices"])
        for profile in rhythm["profiles"]:
            self.percent_range(profile["empty_paper_percent"])
            self.assertEqual(profile["focal_event_count"], 1)
            self.assertEqual(profile["release_zone_count"], 1)
            self.assertEqual(profile["unresolved_edge"], "optional")


class MonoColorDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = audit.inventory(ROOT)
        cls.by_name = {item["name"]: item for item in cls.inventory["skills"]}

    def test_entry_is_discoverable_and_references_resolve(self):
        self.assertEqual(self.inventory["errors"], [])
        entry = self.by_name["mono-color"]
        self.assertTrue(entry["implicit"])
        self.assertLessEqual(entry["description_chars"], 240)
        for relative in ["upstream.md", *(f"design-system/{n}.json" for n in CATALOGS)]:
            self.assertIn(str((REFERENCES / relative).relative_to(ROOT)), entry["references"])
        meta = audit.read_yaml((SKILL / "agents/openai.yaml").read_text())
        self.assertIn("$mono-color", meta["interface"]["default_prompt"])
        prompts = strict_json(PLUGIN / ".codex-plugin/plugin.json")["interface"]["defaultPrompt"]
        for name in ("mono-color", "rubber-stamp-travel-poster"):
            self.assertTrue(any(f"${name}" in prompt for prompt in prompts))

    def test_acceptance_fixture_references_and_action_expectations_are_consistent(self):
        corpus = strict_json(CASES)
        self.assertEqual(corpus["schema_version"], 1)
        cases = corpus["cases"]
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertGreaterEqual(len(cases), 4)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["prompt"])
                self.assertFalse(set(case["expected_actions"]) & set(case["forbidden_actions"]))
                selected = case["expected_skill"]
                if selected:
                    skill = self.by_name[selected]
                    directory = (ROOT / skill["path"]).parent
                    for relative in case["required_references"]:
                        self.assertIn(str((directory / relative).relative_to(ROOT)), skill["references"])
                else:
                    self.assertEqual(case["required_references"], [])
                if case["expected_workflow"] == "research-palette":
                    self.assertEqual(case["required_references"], ["references/design-system/colors.json"])
                    self.assertIn("generate_image", case["forbidden_actions"])
                if case["expected_workflow"] == "editorial-prompt":
                    self.assertNotIn("generate_image", case["expected_actions"])
        # These are acceptance expectations, not synthetic successful model outcomes.
        self.assertNotIn("outcomes", corpus)


if __name__ == "__main__":
    unittest.main()
