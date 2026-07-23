from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins" / "research-tools" / "skills" / "paper-read-draft"
SKILL = SKILL_DIR / "SKILL.md"
OPENAI_METADATA = SKILL_DIR / "agents" / "openai.yaml"
TEMPLATE = SKILL_DIR / "references" / "paper-read-template.md"
OBSIDIAN_MCP = ROOT / "plugins" / "obsidian-tools" / ".mcp.json"


class PaperReadDraftSkillTests(unittest.TestCase):
    def read(self, path: Path) -> str:
        self.assertTrue(path.is_file(), f"missing required asset: {path.relative_to(ROOT)}")
        return path.read_text(encoding="utf-8")

    def test_skill_frontmatter_is_discoverable_and_trigger_only(self) -> None:
        skill = self.read(SKILL)
        frontmatter = re.match(r"\A---\n(?P<body>.*?)\n---\n", skill, re.DOTALL)
        self.assertIsNotNone(frontmatter, "SKILL.md must begin with YAML frontmatter")
        body = frontmatter.group("body")  # type: ignore[union-attr]
        self.assertRegex(body, r"(?m)^name: paper-read-draft$")
        description = re.search(r"(?m)^description: (.+)$", body)
        self.assertIsNotNone(description)
        description_text = description.group(1)  # type: ignore[union-attr]
        self.assertTrue(description_text.startswith("Use when"))
        self.assertRegex(
            description_text.lower(),
            r"\b(set up|create|prepare|start)\b.*\b(obsidian )?(paperread|paper-reading note|draft)\b",
        )
        self.assertNotRegex(
            description_text.lower(),
            r"\b(resolve|lookup|write|check|metadata|template|duplicate)\b",
        )

    def test_openai_metadata_enables_implicit_invocation(self) -> None:
        metadata = self.read(OPENAI_METADATA)
        self.assertRegex(metadata, r'(?m)^\s*display_name: "PaperRead Draft"$')
        self.assertRegex(metadata, r'(?m)^\s*short_description: ".+"$')
        self.assertRegex(metadata, r'(?m)^\s*default_prompt: ".*\$paper-read-draft.*"$')
        self.assertRegex(
            metadata,
            r"(?ms)^policy:\n\s+allow_implicit_invocation: true\s*$",
        )

    def test_template_is_the_exact_three_section_note_contract(self) -> None:
        template = self.read(TEMPLATE)
        frontmatter = re.match(r"\A---\n(?P<body>.*?)\n---\n(?P<note>.*)\Z", template, re.DOTALL)
        self.assertIsNotNone(frontmatter, "template must have YAML frontmatter")
        metadata = frontmatter.group("body")  # type: ignore[union-attr]
        self.assertEqual(
            metadata,
            "\n".join(
                [
                    'title: ""',
                    "authors: []",
                    'year: ""',
                    'venue: ""',
                    'url: ""',
                    "tags: [paper-read]",
                    'created: ""',
                ]
            ),
        )

        body = frontmatter.group("note")  # type: ignore[union-attr]
        self.assertEqual(
            body,
            "\n".join(
                [
                    "",
                    "## Summary and takeaway",
                    "",
                    "%% Summarize the paper and state its core takeaway in your own words. %%",
                    "",
                    "## My thoughts",
                    "",
                    "%% Add your reflections. %%",
                    "",
                    "## Questions",
                    "",
                    "%% Record open questions. %%",
                    "",
                ]
            ),
        )

    def test_skill_resolves_the_configured_vault_and_only_paperread(self) -> None:
        skill = self.read(SKILL)
        self.assertIn("CODEX_OBSIDIAN_VAULT", skill)
        self.assertIn("obsidian_files", skill)
        self.assertIn("PaperRead/", skill)
        self.assertRegex(skill, r"(?i)never use the current working directory as the vault")
        self.assertRegex(skill, r"(?i)write only beneath `?PaperRead/?`?")

    def test_obsidian_files_forwards_the_configured_vault_environment(self) -> None:
        mcp = json.loads(self.read(OBSIDIAN_MCP))
        server = mcp["mcpServers"]["obsidian_files"]
        self.assertIn("CODEX_OBSIDIAN_VAULT", server.get("env_vars", []))

    def test_skill_handles_identity_and_metadata_without_invention(self) -> None:
        skill = self.read(SKILL)
        self.assertRegex(skill, r"(?i)title, DOI, arXiv ID or URL, publisher URL, or Zotero item")
        self.assertRegex(skill, r"(?is)user-supplied facts.*?read-only Zotero.*?canonical scholarly source")
        self.assertRegex(skill, r"(?i)identity is ambiguous.*?ask one focused question")
        self.assertRegex(skill, r"(?i)do not guess")
        self.assertRegex(skill, r"(?i)metadata remains unavailable.*?leave optional fields blank")
        self.assertRegex(skill, r"(?i)metadata-only")

    def test_skill_requires_current_evidence_before_filling_or_claiming_metadata_lookups(self) -> None:
        skill = self.read(SKILL)
        self.assertIn(
            "Fill a metadata field only when the user supplied it or current-task source/tool output actually observed it.",
            skill,
        )
        self.assertIn(
            "Never claim a Zotero or canonical lookup occurred without actual returned evidence.",
            skill,
        )
        self.assertIn("Missing evidence means blank optional fields.", skill)

    def test_skill_preserves_template_filename_and_existing_note_protections(self) -> None:
        skill = self.read(SKILL)
        self.assertIn(
            "Use the vault template at `PaperRead/_Paper Read Template.md` when it exists and satisfies the contract.",
            skill,
        )
        self.assertIn(
            "If that exact vault template is missing or malformed, never silently rewrite the vault template; use the bundled fallback at `references/paper-read-template.md` for note creation.",
            skill,
        )
        self.assertRegex(skill, r"(?is)canonical title.*?normalized.*?whitespace collapsed.*?\.md")
        self.assertRegex(skill, r"(?i)preserve the real title in frontmatter")
        self.assertRegex(skill, r"(?i)do not add a body H1")
        self.assertRegex(skill, r"(?is)before any write.*?exact-path check")
        self.assertRegex(skill, r"(?is)note already exists.*?return its path.*?without modifying")
        self.assertRegex(skill, r"(?is)normalized filename collision.*?distinct paper.*?ask")

    def test_skill_limits_tags_and_create_authority(self) -> None:
        skill = self.read(SKILL)
        self.assertRegex(skill, r"(?i)base tag is `?paper-read`?")
        self.assertRegex(skill, r"(?i)at most three.*?lowercase hyphenated topic tags")
        self.assertRegex(skill, r"(?i)if uncertain.*?only `?paper-read`?")
        self.assertRegex(skill, r"(?i)standard create-draft request authorizes only one new note")

    def test_skill_leaves_personal_sections_as_hidden_prompts_by_default(self) -> None:
        skill = self.read(SKILL)
        self.assertIn(
            "Do not fill personal sections by default; each is hidden-prompt-only.",
            skill,
        )

    def test_skill_has_no_zotero_or_llm_wiki_mutation_path(self) -> None:
        skill = self.read(SKILL)
        self.assertRegex(skill, r"(?i)do not add or update Zotero")
        self.assertRegex(skill, r"(?i)do not ingest the LLM Wiki")
        self.assertRegex(skill, r"(?i)do not provide.*?(paper summary|claims|methods|evaluation|critique|quotes|reading log)")


if __name__ == "__main__":
    unittest.main()
