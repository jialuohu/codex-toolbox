from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "zotero-todoist-reading-tasks"
    / "SKILL.md"
)
OPENAI_METADATA = SKILL.parent / "agents" / "openai.yaml"
RESEARCH_PLUGIN = ROOT / "plugins" / "research-tools" / ".codex-plugin" / "plugin.json"
RESEARCH_MCP = ROOT / "plugins" / "research-tools" / ".mcp.json"
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
README = ROOT / "README.md"
SETUP_CHECKER = ROOT / "scripts" / "check-codex-toolbox-setup.py"


class ZoteroTodoistReadingTasksContractTests(unittest.TestCase):
    def skill_text(self) -> str:
        self.assertTrue(SKILL.exists(), "reading-task skill must exist")
        return SKILL.read_text()

    def test_skill_has_discoverable_frontmatter_and_agent_metadata(self) -> None:
        text = self.skill_text()
        self.assertTrue(OPENAI_METADATA.exists(), "skill must include agents/openai.yaml")
        frontmatter = text.split("---", 2)[1]
        keys = re.findall(r"^([a-z_]+):", frontmatter, flags=re.MULTILINE)

        self.assertEqual(keys, ["name", "description"])
        self.assertIn("name: zotero-todoist-reading-tasks", frontmatter)
        description = re.search(r"^description: (.+)$", frontmatter, flags=re.MULTILINE)
        self.assertIsNotNone(description)
        self.assertTrue(description.group(1).startswith("Use when"))
        self.assertIn("Zotero", description.group(1))
        self.assertIn("Todoist", description.group(1))

        metadata = OPENAI_METADATA.read_text()
        for expected in (
            'display_name: "Zotero Todoist Reading Tasks"',
            'short_description: "Link Zotero papers to Todoist reading tasks."',
            'default_prompt: "Use $zotero-todoist-reading-tasks to create or repair linked Todoist reading tasks and PaperRead notes from Zotero."',
            'value: "zotero"',
            'value: "todoist"',
            'value: "obsidian_files"',
            'url: "https://ai.todoist.net/mcp"',
        ):
            self.assertIn(expected, metadata)

        mcp = json.loads(RESEARCH_MCP.read_text())
        self.assertNotIn("obsidian_files", mcp["mcpServers"])

    def test_skill_keeps_zotero_read_only_and_uses_one_todoist_surface(self) -> None:
        text = self.skill_text()

        for expected in (
            "Do not mutate Zotero",
            "zotero_get_collection_items",
            "zotero_get_items_children",
            "one Todoist task per Zotero parent item",
            "Prefer the connected Todoist app",
            "Choose exactly one Todoist tool surface",
            "$paper-library-intake",
        ):
            self.assertIn(expected, text)

    def test_skill_defines_parent_and_attachment_deep_links(self) -> None:
        text = self.skill_text()

        for expected in (
            "zotero://select/library/items/<PARENT_KEY>",
            "zotero://open-pdf/library/items/<ATTACHMENT_KEY>",
            "zotero://select/groups/<GROUP_ID>/items/<PARENT_KEY>",
            "zotero://open-pdf/groups/<GROUP_ID>/items/<ATTACHMENT_KEY>",
            "PDF attachment key",
            "parent item key",
            "Zotero: [Open PDF]",
            "[Show item]",
        ):
            self.assertIn(expected, text)

    def test_skill_handles_missing_and_ambiguous_pdf_children(self) -> None:
        text = self.skill_text()
        normalized = " ".join(text.split())

        for expected in (
            "no PDF child",
            "Show item",
            "multiple PDF children",
            "authoritative primary attachment",
            "ask instead of guessing",
        ):
            self.assertIn(expected, normalized)

    def test_skill_deduplicates_and_repairs_descriptions_idempotently(self) -> None:
        text = " ".join(self.skill_text().split())

        for expected in (
            "parent-key select URI",
            "normalized title",
            "unique one-to-one match",
            "stop on ambiguity",
            "exactly one managed `Zotero:` line",
            "preserve every other description line",
            "continuous synchronization",
        ):
            self.assertIn(expected, text)

    def test_skill_couples_one_paperread_draft_per_resolved_parent_by_default(self) -> None:
        text = " ".join(self.skill_text().split())

        for expected in (
            "after Zotero identity resolution and before any Todoist write",
            "`$paper-read-draft` exactly once per uniquely resolved Zotero parent",
            "named Zotero item or collection request",
            "at most one create-or-reuse action per uniquely resolved Zotero parent",
            "without Obsidian notes",
            "Use only the URI returned by `$paper-read-draft`",
            "Do not independently infer a note filename or URI",
        ):
            self.assertIn(expected, text)

    def test_skill_manages_the_exact_obsidian_line_without_touching_other_content(self) -> None:
        text = " ".join(self.skill_text().split())

        for expected in (
            "Obsidian: [Open PaperRead note](obsidian://open?vault=<ENCODED_VAULT>&file=<ENCODED_NOTE_PATH>)",
            "exactly one managed `Obsidian:` line",
            "replace all existing managed `Obsidian:` lines with exactly one",
            "preserve every other description line unchanged and in order",
            "`obsidian://` URI appears outside a managed line",
            "ambiguous for manual review",
        ):
            self.assertIn(expected, text)

    def test_skill_preserves_obsidian_lines_on_opt_out_and_reports_note_failures(self) -> None:
        text = " ".join(self.skill_text().split())

        for expected in (
            "perform no PaperRead note operation",
            "preserve any existing Obsidian line",
            "`note-missing`",
            "without adding a stale Obsidian line",
            "with the reason",
        ):
            self.assertIn(expected, text)

    def test_skill_reads_back_obsidian_state_and_includes_it_in_the_receipt(self) -> None:
        text = " ".join(self.skill_text().split())

        for expected in (
            "managed Obsidian line",
            "PaperRead note status",
            "`note-missing` with the reason",
            "opt-out",
        ):
            self.assertIn(expected, text)

    def test_skill_defines_scheduling_and_preservation_rules(self) -> None:
        text = self.skill_text()

        for expected in (
            "planned reading day",
            "`deadlineDate`",
            "evenly across the available calendar days",
            "remainder on earlier days",
            "`reschedule-tasks`",
            "titles, labels, priority, hierarchy",
            "Do not create a project, section, or label",
        ):
            self.assertIn(expected, text)

    def test_skill_requires_scoped_writes_and_returns_a_receipt(self) -> None:
        text = self.skill_text()

        for expected in (
            "exact task identity",
            "explicit deletion request",
            "Read back",
            "created",
            "reused",
            "repaired",
            "skipped",
        ):
            self.assertIn(expected, text)

    def test_plugin_docs_and_setup_checker_expose_the_workflow(self) -> None:
        manifest = json.loads(RESEARCH_PLUGIN.read_text())
        mcp = json.loads(RESEARCH_MCP.read_text())
        prompts = manifest["interface"]["defaultPrompt"]

        self.assertEqual(manifest["version"], "0.5.0")
        self.assertLessEqual(len(prompts), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in prompts))
        prompt_text = " ".join(prompts)
        for expected in (
            "$zotero-todoist-reading-tasks",
            "$paper-library-intake",
            "$paper-read-draft",
            "$paper-read-review",
            "MinerU",
        ):
            self.assertIn(expected, prompt_text)
        self.assertNotIn("todoist", mcp["mcpServers"])

        for path, expected in (
            (README, "$zotero-todoist-reading-tasks"),
            (GLOBAL_AGENTS, "$zotero-todoist-reading-tasks"),
            (SETUP_CHECKER, "ZOTERO_TODOIST_READING_TASKS_SKILL"),
            (SETUP_CHECKER, "ZOTERO_TODOIST_READING_TASKS_OPENAI"),
            (SETUP_CHECKER, '"0.5.0"'),
        ):
            self.assertIn(expected, path.read_text())


if __name__ == "__main__":
    unittest.main()
