import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
PLUGIN = REPO_ROOT / "plugins" / "design-engineering-tools"
SKILLS = (
    "animation-vocabulary",
    "apple-design",
    "emil-design-eng",
    "find-animation-opportunities",
    "improve-animations",
    "pick-ui-library",
    "prototype",
    "review-animations",
)
EXPLICIT_ONLY = {"pick-ui-library", "prototype", "review-animations"}
UPSTREAM_COMMIT = "70744e3816f1d93eafb697161a8b880a7384c5ff"


def read_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError(f"{path} has no YAML frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"unsupported frontmatter line in {path}: {line}")
        fields[key] = value.strip().strip('"')
    return fields


def direct_markdown_references(text: str) -> set[str]:
    return {
        target
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
        if not re.match(r"(?:https?://|mailto:|#)", target)
    }


class DesignEngineeringToolsPluginTests(unittest.TestCase):
    def test_plugin_artifact_contract(self):
        """The vendored plugin remains a safe, self-contained skill package."""
        manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
        self.assertTrue(manifest_path.is_file(), "Task 1 plugin manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "design-engineering-tools")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertRegex(manifest["version"], r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("mcpServers", manifest)
        self.assertEqual(
            manifest["interface"]["capabilities"], ["Read", "Write", "Interactive"]
        )

        license_text = (PLUGIN / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        provenance = (PLUGIN / "PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/emilkowalski/skills", provenance)
        self.assertIn(UPSTREAM_COMMIT, provenance)

        actual_skills = {path.name for path in (PLUGIN / "skills").iterdir() if path.is_dir()}
        self.assertEqual(actual_skills, set(SKILLS))
        for skill in SKILLS:
            skill_dir = PLUGIN / "skills" / skill
            skill_file = skill_dir / "SKILL.md"
            metadata_file = skill_dir / "agents" / "openai.yaml"
            self.assertTrue(skill_file.is_file(), f"{skill} is missing SKILL.md")
            self.assertTrue(metadata_file.is_file(), f"{skill} is missing UI metadata")

            frontmatter = read_frontmatter(skill_file)
            self.assertEqual(set(frontmatter), {"name", "description"})
            self.assertEqual(frontmatter["name"], skill)
            self.assertTrue(frontmatter["description"].startswith("Use when"))
            self.assertNotIn("disable-model-invocation", skill_file.read_text(encoding="utf-8"))

            metadata = metadata_file.read_text(encoding="utf-8")
            self.assertIn("display_name:", metadata)
            self.assertIn("short_description:", metadata)
            self.assertIn("default_prompt:", metadata)
            expected_policy = "false" if skill in EXPLICIT_ONLY else "true"
            self.assertIn(
                f"allow_implicit_invocation: {expected_policy}", metadata,
                f"{skill} has the wrong invocation policy",
            )
            for reference in direct_markdown_references(skill_file.read_text(encoding="utf-8")):
                self.assertTrue((skill_dir / reference).is_file(), f"{skill}: missing {reference}")

        emil = (PLUGIN / "skills" / "emil-design-eng" / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(emil.splitlines()), 500)
        self.assertIn("references/principles.md", emil)

        improve = (PLUGIN / "skills" / "improve-animations" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("source-read-only", improve)
        self.assertIn("explicit authorization", improve)
        self.assertIn("superpowers:writing-plans", improve)
        self.assertIn("superpowers:subagent-driven-development", improve)

        prototype = (PLUGIN / "skills" / "prototype" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Plan Mode", prototype)
        self.assertIn("selected variant", prototype)
        self.assertIn("separate explicit deletion confirmation", prototype)

        picker = (PLUGIN / "skills" / "pick-ui-library" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("installed dependencies", picker)
        self.assertIn("Context7 or official documentation", picker)


if __name__ == "__main__":
    unittest.main()
