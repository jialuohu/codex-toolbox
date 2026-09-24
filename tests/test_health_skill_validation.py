"""Regression cases for installed-skill reference checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "plugins/workflow-tools/skills/sync-toolbox/scripts/skill_validation.py"
SPEC = importlib.util.spec_from_file_location("health_skill_validation_under_test", VALIDATOR)
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class InstalledSkillReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)
        self.skill = self.package / "skills/sample"
        self.skill.mkdir(parents=True)
        self.entry = self.skill / "SKILL.md"

    def write(self, path: str, contents: str) -> Path:
        target = self.skill / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
        return target

    def test_nested_inline_reference_uses_skill_root(self) -> None:
        self.write("SKILL.md", "Read [guide](references/guide.md).\n")
        self.write("references/guide.md", "Read `references/support.md`.\n")
        self.write("references/support.md", "Support details.\n")

        reached, errors = validation.reference_graph(self.entry, self.package, external=True)

        self.assertEqual(errors, [])
        self.assertEqual(set(reached), {
            "skills/sample/references/guide.md",
            "skills/sample/references/support.md",
        })

    def test_hosted_documentation_path_is_not_a_local_missing_file(self) -> None:
        self.write("SKILL.md", "Read [guide](references/guide.md).\n")
        self.write(
            "references/guide.md",
            "See [Trainer](/docs/transformers/v5.2.0/en/main_classes/trainer#transformers.Trainer).\n",
        )

        reached, errors = validation.reference_graph(self.entry, self.package, external=True)

        self.assertEqual(reached, ["skills/sample/references/guide.md"])
        self.assertEqual(errors, [])

    def test_relative_extensionless_documentation_route_is_not_a_local_file(self) -> None:
        self.write("SKILL.md", "Read [guide](references/guide.md).\n")
        self.write(
            "references/guide.md",
            "See [ViT](../model_doc/vit) and [training](../training#train-with-pytorch-trainer).\n",
        )

        reached, errors = validation.reference_graph(self.entry, self.package, external=True)

        self.assertEqual(reached, ["skills/sample/references/guide.md"])
        self.assertEqual(errors, [])

    def test_illustrative_inline_paths_are_not_required_files(self) -> None:
        self.write(
            "SKILL.md",
            "- **Examples:** `references/finance.md` for a sample schema, "
            "`references/policies.md` for sample policy text.\n",
        )

        reached, errors = validation.reference_graph(self.entry, self.package, external=True)

        self.assertEqual(reached, [])
        self.assertEqual(errors, [])

    def test_broken_relative_markdown_link_still_fails(self) -> None:
        self.write("SKILL.md", "Read [variables](references/working-with-design-systems/wwds-variables.md).\n")
        self.write(
            "references/working-with-design-systems/wwds-variables.md",
            "See [token creation](../../figma-generate-library/references/token-creation.md).\n",
        )
        sibling = self.package / "skills/figma-generate-library/references/token-creation.md"
        sibling.parent.mkdir(parents=True)
        sibling.write_text("Token creation.\n", encoding="utf-8")

        _, errors = validation.reference_graph(self.entry, self.package, external=True)

        self.assertEqual(len(errors), 1)
        self.assertIn("missing reference: ../../figma-generate-library/references/token-creation.md", errors[0])

    def test_default_strict_inline_mode_keeps_authoring_validation(self) -> None:
        self.write("SKILL.md", "Read `references/missing.md`.\n")

        _, errors = validation.reference_graph(self.entry, self.package)

        self.assertEqual(len(errors), 1)
        self.assertIn("missing reference: references/missing.md", errors[0])

    def test_external_inline_reference_symlink_outside_package_is_reported(self) -> None:
        self.write("SKILL.md", "Read `references/outside.md`.\n")
        outside = Path(self.temp.name).parent / f"{self.package.name}-outside.md"
        outside.write_text("External file.\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        (self.skill / "references").mkdir()
        (self.skill / "references/outside.md").symlink_to(outside)

        _, errors = validation.reference_graph(self.entry, self.package, external=True)

        self.assertEqual(len(errors), 1)
        self.assertIn("reference escapes repository", errors[0])


if __name__ == "__main__":
    unittest.main()
