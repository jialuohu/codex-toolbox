from __future__ import annotations

import json
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "research-tools" / "skills"
LIBRARY = SKILLS / "paper-review-library-intake" / "SKILL.md"
PAGE = SKILLS / "paper-review-page" / "SKILL.md"
SYNC = SKILLS / "paper-review-sync" / "SKILL.md"
SYNC_CONTRACT = SYNC.parent / "scripts" / "paper_review_contract.py"
PAGE_TEMPLATE_HELPER = PAGE.parent / "scripts" / "template_structure.py"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PaperReviewWorkflowTests(unittest.TestCase):
    def test_skills_are_complete_concise_and_have_generated_metadata(self) -> None:
        for name in (
            "paper-review-library-intake",
            "paper-review-page",
            "paper-review-sync",
        ):
            with self.subTest(name=name):
                directory = SKILLS / name
                text = (directory / "SKILL.md").read_text()
                metadata = (directory / "agents" / "openai.yaml").read_text()
                self.assertIn(f"name: {name}", text)
                self.assertNotIn("[TODO", text)
                self.assertLess(len(text.splitlines()), 500)
                self.assertIn(f"${name}", metadata)
        self.assertTrue(SYNC_CONTRACT.is_file())
        self.assertTrue(PAGE_TEMPLATE_HELPER.is_file())

    def test_private_library_intake_owns_identity_storage_and_cleanup(self) -> None:
        text = LIBRARY.read_text()
        for expected in (
            "Paper Review ID:",
            "Research/PaperReview",
            "Never send a private title",
            "Do not invoke `$paper-library-intake`",
            "download_attachment",
            "release_attachment_download",
            "in a `finally` path",
            "zotero_attachment.py attach",
            "zotero_read_pdf_pages",
            "zotero://select/library/items/<PARENT_KEY>",
            "zotero://open-pdf/library/items/<ATTACHMENT_KEY>",
        ):
            self.assertIn(expected, text)
        self.assertLess(text.index("Search Zotero first"), text.index("## Import workflow"))

    def test_page_template_order_and_confidentiality_are_fail_closed(self) -> None:
        text = PAGE.read_text()
        self.assertLess(text.index("**Assignment form:**"), text.index("**Same venue and year:**"))
        self.assertLess(text.index("**Same venue and year:**"), text.index("**Fallback asset:**"))
        for expected in (
            "Never copy an entire peer page",
            "Remove names, paper-specific summaries",
            "Stop on multiple exact-title children",
            "Paper Review ID:",
            "create_page",
        ):
            self.assertIn(expected, text)

        for template_name in ("conference-review-template.md", "journal-review-template.md"):
            template = (PAGE.parent / "assets" / template_name).read_text()
            self.assertIn("## Summary and contributions", template)
            self.assertNotIn("- [x]", template.lower())
            self.assertNotIn("Paper Review ID:", template)

    def test_sync_authority_active_row_and_partial_repair_contracts(self) -> None:
        text = SYNC.read_text()
        for expected in (
            "$paper-review-sync check",
            "$paper-review-sync sync",
            "$paper-review-sync repair",
            "strictly read-only",
            "Reviewer",
            "Assigned To",
            "equals `Jialuo Hu` exactly",
            "Review Comments",
            "Paper Reviews",
            "Assigned",
            "paper-review",
            "deep-work",
            "Review page: repair-needed",
            "Zotero: repair-needed",
            "$paper-review-library-intake",
            "$paper-review-page",
            "not continuous synchronization",
        ):
            self.assertIn(expected, text)
        self.assertLess(text.index("Create or repair its Todoist task"), text.index("Invoke `$paper-review-library-intake`"))

    def test_plugin_surfaces_workflow_without_embedding_live_assignments(self) -> None:
        manifest = json.loads(
            (ROOT / "plugins" / "research-tools" / ".codex-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(manifest["version"], "0.7.0")
        self.assertTrue(
            any(
                "$paper-review-sync" in prompt
                for prompt in manifest["interface"]["defaultPrompt"]
            )
        )

        published_text = "\n".join(
            path.read_text()
            for path in (
                LIBRARY,
                PAGE,
                SYNC,
                ROOT / "README.md",
                ROOT / "config" / "codex" / "AGENTS.global.md",
            )
        )
        self.assertNotRegex(
            published_text,
            r"/api/files/[0-9a-f]{8}-[0-9a-f-]{27}/",
        )
        self.assertNotRegex(
            published_text,
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        )

class PaperReviewWorkflowBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_module("paper_review_contract_test", SYNC_CONTRACT)
        cls.templates = load_module("paper_review_template_test", PAGE_TEMPLATE_HELPER)

    def test_stable_identity_normalizes_known_aliases_and_preserves_number(self) -> None:
        identity = self.contract.paper_review_identity
        self.assertEqual(identity("ACM SoCC", "2027", " 314 "), "socc|2027|314")
        self.assertEqual(
            identity("IEEE Transactions on Mobile Computing", 2027, "JOURNAL-2027-01-0042"),
            "tmc|2027|JOURNAL-2027-01-0042",
        )
        self.assertEqual(identity("Example Venue", 2027, "A  12"), "example-venue|2027|A 12")
        with self.assertRaises(self.contract.ReviewContractError):
            identity("Example Venue", "27", "12")
        with self.assertRaises(self.contract.ReviewContractError):
            identity("Example Venue", "2027", "12|34")

    def test_active_detection_accepts_current_and_alias_headers_and_excludes_completed(self) -> None:
        rows = [
            {
                "Paper Number": "314",
                "Reviewer": "@Jialuo Hu",
                "Review Comments": "  ",
            },
            {
                "Paper Number": "271",
                "Reviewer": "@Jialuo Hu",
                "Review Comments": "submitted",
            },
            {
                "Paper Number": "159",
                "Reviewer": "@Colleague",
                "Review Comments": "",
            },
            {
                "Paper Number": "265",
                "Reviewer": "@Jialuo Hu @Colleague",
                "Review Comments": "",
            },
            {
                "Paper Number": "358",
                "Assigned To": "Jialuo Hu",
                "Review Comments": "",
            },
        ]
        active = self.contract.active_assignment_rows(rows)
        self.assertEqual([row["Paper Number"] for row in active], ["314", "358"])
        with self.assertRaisesRegex(
            self.contract.ReviewContractError, "conflicting_assignee_columns"
        ):
            self.contract.active_assignment_rows(
                [
                    {
                        "Reviewer": "@Jialuo Hu",
                        "Assigned To": "Colleague",
                        "Review Comments": "",
                    }
                ]
            )

    def test_attachment_matching_is_filename_scoped_and_rejects_duplicates(self) -> None:
        attachments = [
            {"filename": "venue27-paper3140.pdf", "attachment_id": "pdf-wrong"},
            {"filename": "venue27-paper314.pdf", "attachment_id": "pdf-right"},
            {"filename": "venue27-review314.txt", "attachment_id": "txt-right"},
            {"filename": "venue27-paper271.pdf", "attachment_id": "pdf-other"},
        ]
        self.assertEqual(
            self.contract.match_row_attachments("314", attachments),
            {"pdf_attachment_id": "pdf-right", "txt_attachment_id": "txt-right"},
        )
        journal = self.contract.match_row_attachments(
            "JOURNAL-2027-01-0042",
            [
                {
                    "filename": "JOURNAL-2027-01-0042_Proof.pdf",
                    "attachment_id": "journal-pdf",
                }
            ],
        )
        self.assertEqual(journal["pdf_attachment_id"], "journal-pdf")
        with self.assertRaisesRegex(
            self.contract.ReviewContractError, "missing_or_ambiguous_pdf"
        ):
            self.contract.match_row_attachments(
                "314",
                attachments
                + [{"filename": "copy-paper314.pdf", "attachment_id": "pdf-duplicate"}],
            )

    def test_managed_description_merge_is_idempotent_and_preserves_unrelated_lines(self) -> None:
        managed = self.contract.managed_description_lines(
            identity="socc|2027|314",
            assignment_url="https://docs.example.test/assignments",
            review_page_url="https://docs.example.test/reviews/314",
            attachment_key="AAAAAAAA",
            parent_key="BBBBBBBB",
        )
        original = (
            "Venue note\n"
            "Paper Review ID: stale\n"
            "User note\n"
            "Docmost: stale\n"
            "Docmost: duplicate\n"
            "Zotero: stale"
        )
        merged = self.contract.merge_managed_description(original, managed)
        self.assertIn("Venue note", merged)
        self.assertIn("User note", merged)
        self.assertEqual(merged.count("Docmost:"), 1)
        self.assertIn("open-pdf/library/items/AAAAAAAA", merged)
        self.assertIn("select/library/items/BBBBBBBB", merged)
        self.assertEqual(self.contract.merge_managed_description(merged, managed), merged)

    def test_duplicate_partial_and_healthy_states_are_classified_without_recreation(self) -> None:
        classify = self.contract.classify_reconciliation
        self.assertEqual(
            classify(
                task_matches=0,
                zotero_matches=0,
                page_matches=0,
                task_healthy=False,
                zotero_healthy=False,
                page_healthy=False,
            ),
            "new",
        )
        self.assertEqual(
            classify(
                task_matches=1,
                zotero_matches=1,
                page_matches=0,
                task_healthy=True,
                zotero_healthy=True,
                page_healthy=False,
            ),
            "repair-needed",
        )
        self.assertEqual(
            classify(
                task_matches=2,
                zotero_matches=1,
                page_matches=1,
                task_healthy=False,
                zotero_healthy=True,
                page_healthy=True,
            ),
            "ambiguous",
        )
        self.assertEqual(
            classify(
                task_matches=1,
                zotero_matches=1,
                page_matches=1,
                task_healthy=True,
                zotero_healthy=True,
                page_healthy=True,
            ),
            "healthy",
        )

    def test_peer_template_stripping_discards_answers_and_uses_generic_fallback(self) -> None:
        peer = """\
**Summary:**

Paper-specific summary that must not survive.

**Strengths:**

+ A substantive claim.

**Decision:**

Weak accept.
"""
        fallback = "## Generic summary\n\n## Generic decision\n"
        stripped = self.templates.extract_blank_structure(peer, fallback)
        self.assertEqual(stripped.source, "same-venue")
        self.assertIn("## Summary", stripped.markdown)
        self.assertIn("## Strengths", stripped.markdown)
        self.assertIn("## Decision", stripped.markdown)
        self.assertNotIn("Paper-specific", stripped.markdown)
        self.assertNotIn("substantive", stripped.markdown.lower())
        self.assertNotIn("Weak accept", stripped.markdown)

        generic = self.templates.extract_blank_structure("Only reviewer prose.", fallback)
        self.assertEqual(generic.source, "fallback")
        self.assertEqual(generic.markdown, fallback)


if __name__ == "__main__":
    unittest.main()
