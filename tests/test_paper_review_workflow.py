from __future__ import annotations

import copy
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


CREATOR_ID = "00000000-0000-4000-8000-000000000001"


def _paragraph(*nodes: dict[str, object], include_content: bool = True) -> dict[str, object]:
    paragraph: dict[str, object] = {
        "type": "paragraph",
        "attrs": {"id": "fixture", "indent": 0},
    }
    if include_content:
        paragraph["content"] = list(nodes)
    return paragraph


def _text_cell(value: str, *, include_content: bool = True) -> dict[str, object]:
    nodes = ({"type": "text", "text": value},) if value else ()
    return {
        "type": "tableCell",
        "attrs": {"colspan": 1, "rowspan": 1},
        "content": [_paragraph(*nodes, include_content=include_content)],
    }


def _mention_cell(label: str) -> dict[str, object]:
    return {
        "type": "tableCell",
        "attrs": {"colspan": 1, "rowspan": 1},
        "content": [
            _paragraph(
                {
                    "type": "mention",
                    "attrs": {
                        "id": "00000000-0000-4000-8000-000000000099",
                        "label": label,
                        "entityId": CREATOR_ID,
                        "creatorId": CREATOR_ID,
                        "entityType": "user",
                    },
                }
            )
        ],
    }


def _review_table(paper_number: str, reviewer_cell: dict[str, object]) -> dict[str, object]:
    headers = ["Paper Number", "Paper Title", "Reviewer", "Review Comments", "Word Count"]
    return {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableHeader",
                        "attrs": {"colspan": 1, "rowspan": 1},
                        "content": [_paragraph({"type": "text", "text": header})],
                    }
                    for header in headers
                ],
            },
            {
                "type": "tableRow",
                "content": [
                    _text_cell(paper_number),
                    _text_cell(f"Title {paper_number}"),
                    reviewer_cell,
                    _text_cell("", include_content=paper_number != "900000001"),
                    _text_cell("", include_content=False),
                ],
            },
        ],
    }


def _assignment_document() -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"id": "infocom", "level": 3, "indent": 0},
                "content": [{"type": "text", "text": "ExampleConf Alpha (01/01/2030)"}],
            },
            _review_table("900000001", _text_cell("@Jialuo")),
            {
                "type": "heading",
                "attrs": {"id": "socc", "level": 3, "indent": 0},
                "content": [{"type": "text", "text": "ExampleConf Beta (01/02/2030)"}],
            },
            _review_table("2001", _mention_cell("Jialuo Hu")),
        ],
    }


def _review_link_targets() -> list[dict[str, object]]:
    return [
        {
            "section_heading": "ExampleConf Alpha (01/01/2030)",
            "paper_number": "900000001",
            "page_id": "00000000-0000-4000-8000-000000000101",
            "slug_id": "AlphaSlug01",
            "title": "900000001",
            "url": "https://docs.example.test/reviews/900000001",
            "mention_id": "00000000-0000-4000-8000-000000000201",
        },
        {
            "section_heading": "ExampleConf Beta (01/02/2030)",
            "paper_number": "2001",
            "page_id": "00000000-0000-4000-8000-000000000102",
            "slug_id": "BetaSlug01",
            "title": "2001",
            "url": "https://docs.example.test/reviews/2001",
            "mention_id": "00000000-0000-4000-8000-000000000202",
        },
    ]


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
            "docmost_download_attachment",
            "docmost_release_attachment_download",
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
        self.assertLess(text.index("**Assignment form:**"), text.index("**Same conference edition:**"))
        self.assertLess(text.index("**Same conference edition:**"), text.index("**Fallback asset:**"))
        for expected in (
            "Never copy an entire peer page",
            "Remove names, paper-specific summaries",
            "Stop on multiple exact-title children",
            "Review Dojo/Review Comments/<conference>/<edition>",
            "resolve-edition-folder",
            "AI-involved",
            "Proper Use of AI",
            "mailto:hwang9@stevens.edu",
            "font-color markup",
            "Do not render a Paper Review ID",
            "authoritative assignment form",
            "only the variable data listed above may be blanked",
            "docmost_create_page",
            "slug_id",
            "does not edit `Review Assignments`",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("> Paper Review ID:", text)
        self.assertNotIn("> Assignment:", text)
        self.assertNotIn("> Confidential review workspace", text)

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
            "`Jialuo Hu` or `Jialuo`",
            "Review Comments",
            "Word Count",
            "Paper Reviews",
            "Assigned",
            "paper-review",
            "deep-work",
            "Review page: repair-needed",
            "Zotero: repair-needed",
            "$paper-review-library-intake",
            "$paper-review-page",
            "not continuous synchronization",
            "review-comments-link",
            "docmost_patch_page_content",
            "OUTCOME_UNKNOWN",
            "serializer normalization",
        ):
            self.assertIn(expected, text)
        self.assertLess(text.index("Create or repair its Todoist task"), text.index("Invoke `$paper-review-library-intake`"))

    def test_plugin_surfaces_workflow_without_embedding_live_assignments(self) -> None:
        manifest = json.loads(
            (ROOT / "plugins" / "research-tools" / ".codex-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(manifest["version"], "0.8.1")
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
                "Review Comments": "linked review page",
                "Word Count": "",
            },
            {
                "Paper Number": "272",
                "Reviewer": "@Jialuo Hu",
                "Review Comments": "linked review page",
                "Word Count": "500",
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
            {
                "Paper Number": "377",
                "Reviewer": "Jialuo",
                "Review Comments": "",
            },
            {
                "Paper Number": "388",
                "Reviewer": "@Jialuo",
                "Review Comments": "",
            },
        ]
        active = self.contract.active_assignment_rows(rows)
        self.assertEqual(
            [row["Paper Number"] for row in active],
            ["314", "271", "358", "377", "388"],
        )
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

    def test_edition_resolution_uses_unique_assignment_child_overlap(self) -> None:
        resolve = self.contract.resolve_edition_folder
        assignment_numbers = ["900000001", "900000002", "900000003"]
        candidates = [
            {"id": "old", "title": "ExampleConf 2029", "paper_numbers": ["1000"]},
            {
                "id": "current",
                "title": "ExampleConf 2030",
                "paper_numbers": ["900000003"],
            },
        ]
        self.assertEqual(
            resolve(assignment_numbers, candidates),
            {
                "id": "current",
                "title": "ExampleConf 2030",
                "overlap": ["900000003"],
            },
        )
        with self.assertRaisesRegex(
            self.contract.ReviewContractError, "ambiguous_edition_mapping"
        ):
            resolve(
                assignment_numbers,
                candidates
                + [
                    {
                        "id": "duplicate",
                        "title": "Another edition",
                        "paper_numbers": ["900000001"],
                    }
                ],
            )
        with self.assertRaisesRegex(
            self.contract.ReviewContractError, "missing_edition_mapping"
        ):
            resolve(assignment_numbers, candidates[:1])

        self.assertEqual(
            resolve(
                ["2001", "2002"],
                [
                    {"id": "old-beta", "title": "ExampleConf Beta 2029", "paper_numbers": ["20"]},
                    {
                        "id": "current-beta",
                        "title": "ExampleConf Beta 2030",
                        "paper_numbers": ["2002"],
                    },
                ],
            )["title"],
            "ExampleConf Beta 2030",
        )

    def test_review_comments_link_plan_builds_one_guarded_native_mention_patch(self) -> None:
        result = self.contract.plan_review_comments_links(
            _assignment_document(),
            _review_link_targets(),
            creator_id=CREATOR_ID,
        )
        self.assertTrue(result["ready"])
        self.assertEqual(
            [item["status"] for item in result["results"]],
            ["blank", "blank"],
        )
        add_operations = [operation for operation in result["patch"] if operation["op"] == "add"]
        self.assertEqual(
            [operation["path"] for operation in add_operations],
            [
                "/content/1/content/1/content/3/content/0/content",
                "/content/3/content/1/content/3/content/0/content",
            ],
        )
        self.assertTrue(all(operation["op"] in {"test", "add"} for operation in result["patch"]))
        first_mention = add_operations[0]["value"][0]
        self.assertEqual(
            first_mention,
            {
                "type": "mention",
                "attrs": {
                    "id": "00000000-0000-4000-8000-000000000201",
                    "label": "900000001",
                    "slugId": "AlphaSlug01",
                    "entityId": "00000000-0000-4000-8000-000000000101",
                    "creatorId": CREATOR_ID,
                    "entityType": "page",
                },
            },
        )
        serialized = json.dumps(result)
        self.assertNotIn("AI-involved", serialized)
        self.assertNotIn("color", serialized.casefold())

    def test_existing_canonical_mention_with_plain_user_text_is_healthy(self) -> None:
        document = _assignment_document()
        target = _review_link_targets()[0]
        initial = self.contract.plan_review_comments_links(
            document,
            [target],
            creator_id=CREATOR_ID,
        )
        mention = copy.deepcopy(initial["results"][0]["mention"])
        comments_paragraph = document["content"][1]["content"][1]["content"][3]["content"][0]
        comments_paragraph["content"] = [mention, {"type": "text", "text": " user tag"}]

        result = self.contract.plan_review_comments_links(
            document,
            [target],
            creator_id=CREATOR_ID,
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["results"][0]["status"], "linked")
        self.assertEqual(result["patch"], [])
        self.assertEqual(comments_paragraph["content"][1]["text"], " user tag")

    def test_wrong_duplicate_and_non_native_links_fail_closed(self) -> None:
        target = _review_link_targets()[0]
        initial = self.contract.plan_review_comments_links(
            _assignment_document(),
            [target],
            creator_id=CREATOR_ID,
        )
        canonical = initial["results"][0]["mention"]

        cases: list[tuple[str, list[dict[str, object]], str]] = []
        wrong = copy.deepcopy(canonical)
        wrong["attrs"]["entityId"] = "00000000-0000-4000-8000-000000000999"
        cases.append(("wrong", [wrong], "wrong_or_non_native_link"))
        cases.append(
            (
                "duplicate",
                [copy.deepcopy(canonical), copy.deepcopy(canonical)],
                "duplicate_canonical_link",
            )
        )
        cases.append(
            (
                "internal-link",
                [
                    {
                        "type": "text",
                        "text": "900000001",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": target["url"]},
                            }
                        ],
                    }
                ],
                "wrong_or_non_native_link",
            )
        )

        for name, nodes, reason in cases:
            with self.subTest(name=name):
                document = _assignment_document()
                document["content"][1]["content"][1]["content"][3]["content"][0]["content"] = nodes
                result = self.contract.plan_review_comments_links(
                    document,
                    [target],
                    creator_id=CREATOR_ID,
                )
                self.assertFalse(result["ready"])
                self.assertEqual(result["patch"], [])
                self.assertEqual(result["results"][0]["reason"], reason)

    def test_review_link_location_rejects_ambiguous_or_historical_rows(self) -> None:
        target = _review_link_targets()[0]
        cases: list[tuple[str, dict[str, object], str]] = []

        duplicate_row = _assignment_document()
        duplicate_row["content"][1]["content"].append(
            copy.deepcopy(duplicate_row["content"][1]["content"][1])
        )
        cases.append(("duplicate-row", duplicate_row, "duplicate_paper_row"))

        duplicate_table = _assignment_document()
        duplicate_table["content"].insert(2, copy.deepcopy(duplicate_table["content"][1]))
        cases.append(("duplicate-table", duplicate_table, "duplicate_review_table"))

        duplicate_section = _assignment_document()
        duplicate_section["content"].extend(copy.deepcopy(duplicate_section["content"][:2]))
        cases.append(("duplicate-section", duplicate_section, "duplicate_section"))

        historical = _assignment_document()
        historical["content"][1]["content"][1]["content"][4] = _text_cell("500")
        cases.append(("word-count", historical, "word_count_filled"))

        reviewer_mismatch = _assignment_document()
        reviewer_mismatch["content"][1]["content"][1]["content"][2] = _text_cell("Colleague")
        cases.append(("reviewer", reviewer_mismatch, "reviewer_mismatch"))

        for name, document, reason in cases:
            with self.subTest(name=name):
                result = self.contract.plan_review_comments_links(
                    document,
                    [target],
                    creator_id=CREATOR_ID,
                )
                self.assertFalse(result["ready"])
                self.assertEqual(result["patch"], [])
                self.assertEqual(result["results"][0]["reason"], reason)

        mixed = _assignment_document()
        mixed["content"][3]["content"][1]["content"][4] = _text_cell("500")
        mixed_result = self.contract.plan_review_comments_links(
            mixed,
            _review_link_targets(),
            creator_id=CREATOR_ID,
        )
        self.assertFalse(mixed_result["ready"])
        self.assertEqual(mixed_result["patch"], [])
        self.assertNotIn("patch", mixed_result["results"][0])

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

    def test_peer_structure_keeps_infocom_singular_and_ai_fields_without_answers(self) -> None:
        peer = """\
**Summary**:

Private summary.

**Strength**:

Private strength.

**Weakness**:

Private weakness.

**Comments:**

<span style="color: red">Private comment.</span>

**Proper Use of AI**:

AI-involved

**Decision**:

Weak reject.
"""
        fallback = "## Generic summary\n\n## Generic decision\n"
        stripped = self.templates.extract_blank_structure(peer, fallback)
        self.assertEqual(stripped.source, "same-venue")
        for heading in (
            "Summary",
            "Strength",
            "Weakness",
            "Comments",
            "Proper Use of AI",
            "Decision",
        ):
            self.assertIn(f"## {heading}", stripped.markdown)
        self.assertNotIn("Private", stripped.markdown)
        self.assertNotIn("AI-involved", stripped.markdown)
        self.assertNotIn("color: red", stripped.markdown)

    def test_hotcrp_blanking_preserves_complete_form_including_ai(self) -> None:
        form = """\
\\==+== ExampleConf 2030 Review Form
\\==-== <span style="color: red">Fixed venue instruction.</span>
\\==+== Reviewer: Hao Wang <hwang9@stevens.edu>
\\==+== Paper #2001
\\==-== Title: Synthetic Systems Study

\\==+== Review Readiness
\\==-== Enter "Ready" if the review is ready for others to see:

Ready

\\==\\*== Paper summary
\\==-== Markdown supported.

Private response.

\\==\\*== Proper Use of AI
\\==-== Example fixed AI-use instruction.
\\==-== Example fixed confidentiality instruction.

(No entry)

\\==+== Scratchpad (for unsaved private notes)

Private scratchpad.

\\==+== End Review
"""
        blanked = self.templates.blank_hotcrp_assignment_form(form)
        source_fixed = [
            line
            for line in form.splitlines()
            if line.startswith("\\==") and "Reviewer:" not in line
        ]
        blanked_fixed = [
            line
            for line in blanked.splitlines()
            if line.startswith("\\==") and "Reviewer:" not in line
        ]
        self.assertEqual(blanked_fixed, source_fixed)
        self.assertEqual(
            blanked.count(
                "\\==+== Reviewer: Hao Wang "
                "[hwang9@stevens.edu](mailto:hwang9@stevens.edu)"
            ),
            1,
        )
        self.assertIn("Proper Use of AI", blanked)
        self.assertIn("Example fixed confidentiality instruction", blanked)
        self.assertIn('<span style="color: red">Fixed venue instruction.</span>', blanked)
        self.assertIn("(No entry)", blanked)
        self.assertNotIn("<hwang9@stevens.edu>", blanked)
        self.assertNotIn("\nReady\n", blanked)
        self.assertNotIn("Private response", blanked)
        self.assertNotIn("Private scratchpad", blanked)

        with self.assertRaisesRegex(ValueError, "unsupported_hotcrp_assignment_form"):
            self.templates.blank_hotcrp_assignment_form("Only reviewer prose.\n")


if __name__ == "__main__":
    unittest.main()
