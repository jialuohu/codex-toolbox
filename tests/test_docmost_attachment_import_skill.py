from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "docmost-tools"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MCP = PLUGIN / ".mcp.json"
SKILL = PLUGIN / "skills" / "docmost-attachment-import" / "SKILL.md"


class DocmostAttachmentImportSkillTests(unittest.TestCase):
    def test_plugin_registers_one_self_contained_attachment_skill(self) -> None:
        manifest = json.loads(MANIFEST.read_text())

        self.assertEqual(manifest["version"], "0.8.0")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertTrue(SKILL.is_file())
        self.assertEqual(
            {path.name for path in SKILL.parent.iterdir()},
            {"SKILL.md"},
        )
        text = SKILL.read_text()
        self.assertIn("name: docmost-attachment-import", text)
        self.assertIn("authenticated `gh` access", text)
        self.assertIn("in-memory manifest", text)
        self.assertIn("docmost_attach_pdf_to_page", text)
        self.assertIn("docmost_link_uploaded_pdf", text)
        self.assertIn("Never retry an `OUTCOME_UNKNOWN`", text)
        self.assertIn("finally", text)

    def test_exact_seven_write_tools_are_prompt_gated(self) -> None:
        server = json.loads(MCP.read_text())["mcpServers"]["docmost"]
        expected = {
            "docmost_create_page",
            "docmost_update_page_title",
            "docmost_edit_page_text",
            "docmost_patch_page_content",
            "docmost_attach_pdf_to_page",
            "docmost_link_uploaded_pdf",
            "docmost_create_comment",
        }

        self.assertEqual(server["default_tools_approval_mode"], "auto")
        self.assertEqual(set(server["tools"]), expected)
        self.assertTrue(
            all(server["tools"][name] == {"approval_mode": "prompt"} for name in expected)
        )

    def test_mocked_six_pdf_create_reuse_manifest_never_reuploads_recovery(self) -> None:
        source_names = [f"week-{index}.pdf" for index in range(1, 7)]
        existing_titles = {"week-1", "week-2", "week-3"}
        already_verified = {"week-1"}
        recovery_targets = {"week-2", "week-5"}

        manifest = [
            {
                "source": name,
                "title": name.removesuffix(".pdf"),
                "page_action": (
                    "reuse" if name.removesuffix(".pdf") in existing_titles else "create"
                ),
                "attachment_action": (
                    "skip"
                    if name.removesuffix(".pdf") in already_verified
                    else "upload"
                ),
            }
            for name in source_names
        ]
        upload_calls = sum(row["attachment_action"] == "upload" for row in manifest)
        link_only_calls = sum(row["title"] in recovery_targets for row in manifest)

        self.assertEqual(len(manifest), 6)
        self.assertEqual(len({row["title"] for row in manifest}), 6)
        self.assertEqual(sum(row["page_action"] == "reuse" for row in manifest), 3)
        self.assertEqual(sum(row["page_action"] == "create" for row in manifest), 3)
        self.assertEqual(upload_calls, 5)
        self.assertEqual(link_only_calls, 2)
        self.assertEqual(upload_calls, 5, "link-only recovery must not add upload calls")


if __name__ == "__main__":
    unittest.main()
