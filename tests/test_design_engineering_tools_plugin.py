import json
import os
import re
import subprocess
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
REQUIRED_SKILL_LINKS = {"references/upstream.md", "../../SHARED-BOUNDARIES.md"}


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
        target.split("#", 1)[0]
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
        if target and not re.match(r"(?:https?://|mailto:|#)", target)
    }


def parse_openai_yaml(path: Path) -> dict:
    """Parse the deliberately small, scalar-only openai.yaml schema safely."""
    root: dict[str, dict] = {}
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, separator, value = line.partition(":")
            if not separator or value.strip():
                raise AssertionError(f"invalid top-level YAML in {path}: {line}")
            if key in root:
                raise AssertionError(f"duplicate YAML section in {path}: {key}")
            root[key] = {}
            section = key
            continue
        if not line.startswith("  ") or line.startswith("   ") or section is None:
            raise AssertionError(f"unsupported YAML indentation in {path}: {line}")
        key, separator, value = line.strip().partition(":")
        if not separator or key in root[section]:
            raise AssertionError(f"invalid YAML field in {path}: {line}")
        value = value.strip()
        if value in {"true", "false"}:
            root[section][key] = value == "true"
        elif len(value) >= 2 and value[0] == value[-1] == '"':
            root[section][key] = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        else:
            raise AssertionError(f"unquoted or unsupported YAML scalar in {path}: {line}")
    return root


def git_path_inventory() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "plugins/design-engineering-tools"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def lexical_relative_path(markdown: Path, reference: str) -> str:
    path = os.path.normpath(str(markdown.parent.relative_to(REPO_ROOT) / reference))
    return Path(path).as_posix()


class DesignEngineeringToolsPluginTests(unittest.TestCase):
    def test_apple_design_implicit_trigger_is_physical_not_generic_ui_guidance(self):
        skill = PLUGIN / "skills" / "apple-design" / "SKILL.md"
        metadata = parse_openai_yaml(
            PLUGIN / "skills" / "apple-design" / "agents" / "openai.yaml"
        )
        frontmatter = read_frontmatter(skill)
        trigger_surface = " ".join(
            (
                frontmatter["description"],
                metadata["interface"]["short_description"],
                metadata["interface"]["default_prompt"],
            )
        ).lower()
        normalized_skill = " ".join(skill.read_text(encoding="utf-8").split())

        self.assertRegex(
            trigger_surface,
            r"apple-like.*(?:physical interaction|gesture|spring|direct manipulation)",
        )
        for generic_concern in (
            "typography",
            "color",
            "accessibility",
            "reduced motion",
            "reduced-motion",
        ):
            self.assertNotIn(generic_concern, trigger_surface)
        self.assertIn(
            "Generic typography, color, accessibility, or reduced-motion requests stay with `ui-ux-pro-max`.",
            normalized_skill,
        )
        self.assertTrue(metadata["policy"]["allow_implicit_invocation"])

    def test_pick_ui_library_requires_current_version_and_license_before_mutation(self):
        picker = (
            PLUGIN / "skills" / "pick-ui-library" / "SKILL.md"
        ).read_text(encoding="utf-8")
        normalized_picker = " ".join(picker.split())

        self.assertRegex(
            normalized_picker,
            r"(?s)Context7 or official documentation.*current version",
        )
        self.assertRegex(
            normalized_picker,
            r"(?s)authoritative.*current license",
        )
        mutation_gate = normalized_picker.index(
            "Before proposing or requesting authorization for a dependency mutation"
        )
        self.assertLess(normalized_picker.index("current version"), mutation_gate)
        self.assertLess(normalized_picker.index("current license"), mutation_gate)
        self.assertRegex(
            normalized_picker[mutation_gate:],
            r"(?s)cannot verify.*do not recommend or install",
        )

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

        inventory = git_path_inventory()
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

            metadata = parse_openai_yaml(metadata_file)
            self.assertEqual(set(metadata), {"interface", "policy"})
            self.assertEqual(
                set(metadata["interface"]),
                {"display_name", "short_description", "default_prompt"},
            )
            self.assertTrue(all(isinstance(value, str) and value for value in metadata["interface"].values()))
            self.assertEqual(set(metadata["policy"]), {"allow_implicit_invocation"})
            self.assertEqual(
                metadata["policy"]["allow_implicit_invocation"], skill not in EXPLICIT_ONLY,
                f"{skill} has the wrong invocation policy",
            )
            references = direct_markdown_references(skill_file.read_text(encoding="utf-8"))
            self.assertTrue(REQUIRED_SKILL_LINKS.issubset(references), f"{skill} omits required linked guidance")
            for reference in references:
                expected = lexical_relative_path(skill_file, reference)
                self.assertIn(expected, inventory, f"{skill}: missing exact-case {reference}")

            for markdown in skill_dir.rglob("*.md"):
                for reference in direct_markdown_references(markdown.read_text(encoding="utf-8")):
                    expected = lexical_relative_path(markdown, reference)
                    self.assertTrue(
                        expected in inventory,
                        f"{markdown.relative_to(PLUGIN)}: missing exact-case {reference}",
                    )

            upstream = skill_dir / "references" / "upstream.md"
            self.assertGreaterEqual(len(upstream.read_text(encoding="utf-8").splitlines()), 40)

        emil = (PLUGIN / "skills" / "emil-design-eng" / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(emil.splitlines()), 500)
        self.assertIn("references/principles.md", emil)

        improve = (PLUGIN / "skills" / "improve-animations" / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(improve, r"(?s)source-read-only.*response-only")
        self.assertRegex(improve, r"(?s)explicit authorization.*save")
        self.assertRegex(improve, r"(?s)Plan Mode.*never write.*dispatch")
        self.assertRegex(improve, r"(?s)superpowers:writing-plans.*superpowers:subagent-driven-development")

        prototype = (PLUGIN / "skills" / "prototype" / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(prototype, r"(?s)Plan Mode.*do not write.*do not dispatch")
        self.assertRegex(prototype, r"(?s)selected variant.*before.*promotion")
        self.assertRegex(prototype, r"(?s)keep <variant>.*selects or promotes only.*never deletes")
        self.assertRegex(prototype, r"(?s)cleanup targets.*separate explicit deletion confirmation")

        picker = (PLUGIN / "skills" / "pick-ui-library" / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(picker, r"(?s)installed dependencies.*package manager.*lockfile")
        self.assertRegex(picker, r"(?s)Context7 or official documentation.*before.*recommendation")
        self.assertRegex(picker, r"(?s)recommendation-only by default.*explicit implementation authorization")

        shared = (PLUGIN / "SHARED-BOUNDARIES.md").read_text(encoding="utf-8")
        hierarchy = [
            "Explicit user direction",
            "Target project conventions and design system",
            "Accessibility requirements",
            "Current official documentation",
            "Imported opinions are advisory",
        ]
        positions = [shared.index(item) for item in hierarchy]
        self.assertEqual(positions, sorted(positions))

        for markdown in PLUGIN.rglob("*.md"):
            self.assertNotIn(
                "disable-model-invocation",
                markdown.read_text(encoding="utf-8"),
                f"unsupported metadata in {markdown.relative_to(PLUGIN)}",
            )


if __name__ == "__main__":
    unittest.main()
