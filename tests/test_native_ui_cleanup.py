"""Instruction contracts for cleanup without claiming runtime app ownership."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
OWNERS = {
    "omnigraffle": "plugins/omnigraffle-tools/skills/omnigraffle-workflow",
    "drawio": "plugins/drawio-tools/skills/drawio",
    "paper-figure": "plugins/diagram-tools/skills/paper-figure-workflow",
}


class NativeUICleanupTests(unittest.TestCase):
    def read_owner(self, name):
        directory = ROOT / OWNERS[name]
        skill = (directory / "SKILL.md").read_text()
        links = re.findall(r"\[[^\]]+\]\((references/ui-cleanup\.md)\)", skill)
        self.assertEqual(links, ["references/ui-cleanup.md"], name)
        reference = directory / links[0]
        self.assertTrue(reference.is_file(), name)
        return skill, " ".join(reference.read_text().split())

    def test_owners_load_cleanup_before_launch_capable_work(self):
        triggers = {"omnigraffle": "doctor --probe-app", "drawio": "open_drawio_mermaid",
                    "paper-figure": "doctor --probe-app"}
        for name, trigger in triggers.items():
            with self.subTest(owner=name):
                skill, cleanup = self.read_owner(name)
                self.assertLess(skill.index("references/ui-cleanup.md"), skill.index(trigger))
                self.assertIn("non-launching inventory", cleanup)
                self.assertRegex(cleanup, r"inventory difference.*does not prove ownership|inventory difference.*not ownership proof")
                self.assertRegex(cleanup, r"[Oo]n completion or failure.*control is available")
                self.assertRegex(cleanup, r"[Cc]lose only (?:an )?exact task-created.*saved.*idle")
                self.assertIn("open/show/keep-open", cleanup)
                self.assertIn("active interactive handoff", cleanup)
                self.assertIn("file links", cleanup)
                self.assertIn("new/untracked", cleanup)
                self.assertIn("unsaved", cleanup)
                self.assertIn("pending", cleanup)
                self.assertRegex(cleanup, r"[Nn]ever[^.]*force-quit")
                self.assertRegex(cleanup, r"[Bb]ound (?:cleanup )?attempts")

    def test_native_cleanup_preserves_backend_and_reconciliation(self):
        _, cleanup = self.read_owner("omnigraffle")
        self.assertIn("backend already closes verified private working copies", cleanup)
        self.assertIn("Do not repeat its close operations", cleanup)
        self.assertRegex(cleanup, r"unknown mutation outcome.*open for `reconcile`")
        self.assertRegex(cleanup, r"normal quit only for a proven task-started app.*recorded instance")
        self.assertIn("no operation awaits reconciliation", cleanup)

    def test_drawio_requires_returned_identity_and_no_duplicate_open(self):
        skill, cleanup = self.read_owner("drawio")
        self.assertNotIn("Open the retained `.drawio` source unless", skill)
        self.assertIn("Reuse an editor already opened for this task", skill)
        self.assertIn("exact returned handle/ID", cleanup)
        self.assertIn("do not provide a stable page/window ownership receipt", cleanup)
        self.assertRegex(cleanup, r"ownership cannot be verified.*keep that resource")
        self.assertIn("Do not invent MCP output arguments", cleanup)
        self.assertIn("Desktop helper has no close/quit API", cleanup)
        self.assertIn("does not prove app ownership or isolation", cleanup)

    def test_paper_owner_covers_implicit_probe_and_fallback(self):
        _, cleanup = self.read_owner("paper-figure")
        self.assertRegex(cleanup, r"before invoking `scaffold_research_figures.py`.*auto owner selection")
        self.assertIn("probe can launch OmniGraffle before drawing starts", cleanup)
        self.assertIn("even if a different owner completes the figure", cleanup)
        self.assertIn("same owner-selection", cleanup)
        self.assertIn("Preserve unknown mutation state", cleanup)
        self.assertIn("no reconciliation is pending", cleanup)
        self.assertIn("no process-management API", cleanup)


if __name__ == "__main__":
    unittest.main()
