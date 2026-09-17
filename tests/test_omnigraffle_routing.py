"""Portable packaging and native-diagram ownership regression checks."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/omnigraffle-tools"


class OmniGraffleRoutingTests(unittest.TestCase):
    def test_plugin_registration_is_files_only(self):
        manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "omnigraffle-tools")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("mcpServers", manifest)
        self.assertFalse((PLUGIN / ".mcp.json").exists())
        entries = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())["plugins"]
        matches = [p for p in entries if p["name"] == "omnigraffle-tools"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["source"]["path"], "./plugins/omnigraffle-tools")
        setup = (ROOT / "scripts/setup-codex-toolbox.sh").read_text()
        self.assertEqual(setup.count('  "omnigraffle-tools"'), 1)

    def test_visual_owners_observe_application_and_format(self):
        paths = [
            "paper-figure-tools/skills/paper-figure-workflow/SKILL.md",
            "diagram-tools/skills/archify/SKILL.md",
            "diagram-tools/skills/pretty-mermaid/SKILL.md",
            "drawio-tools/skills/drawio/SKILL.md",
            "photo-tools/skills/mono-color/SKILL.md",
            "workflow-tools/skills/explain-clearly/SKILL.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                text = (ROOT / "plugins" / path).read_text()
                self.assertIn("$omnigraffle-workflow", text)
                self.assertIn(".graffle", text)
                self.assertIn("Explicit application choice takes precedence, followed by the existing artifact format", text)
        paper = (ROOT / "plugins" / paths[0]).read_text()
        self.assertNotIn("Use draw.io or diagrams.net for AI/ML/system pipeline and architecture diagrams.", paper)
        self.assertIn("publication directories, regeneration commands, and cross-figure checks", paper)

    def test_palette_and_stock_application_boundaries(self):
        skill = (PLUGIN / "skills/omnigraffle-workflow/SKILL.md").read_text()
        self.assertIn("references/design-system/colors.json", skill)
        self.assertIn("exact absolute catalog path", skill)
        self.assertIn("unlocked desktop", skill)
        self.assertIn("Stock official LaTeXiT", skill)
        self.assertFalse(list(PLUGIN.rglob("*catalog*.json")))
        provenance = (PLUGIN / "PROVENANCE.md").read_text()
        self.assertIn("3185a7766217236248e085ee0898331165b581ff8275dfd17c4436224dd48f2f", provenance)
        self.assertIn("permission to adapt and publish", provenance)

    def test_global_instruction_budget_and_route(self):
        global_path = ROOT / "config/codex/AGENTS.global.md"
        self.assertLessEqual(len(global_path.read_bytes()), 8192)
        self.assertLessEqual(len(global_path.read_bytes()) + len((ROOT / "AGENTS.md").read_bytes()), 16384)
        self.assertIn("$omnigraffle-workflow", global_path.read_text())


if __name__ == "__main__":
    unittest.main()
