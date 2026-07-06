#!/usr/bin/env python3
"""Lightweight lint checks for the Research LLM Wiki."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WIKI_ROOT = os.environ.get("CODEX_RESEARCH_LLM_WIKI")
REQUIRED_PATHS = (
    "_schema.md",
    "index.md",
    "log.md",
    "Sources",
    "Concepts",
    "Comparisons",
    "Questions",
    "Analyses",
)
PAGE_DIRS = ("Sources", "Concepts", "Comparisons", "Questions", "Analyses")
CITATION_REQUIRED_HEADINGS = {
    "Key Claims",
    "Passes",
    "Research Workflow Role",
}
SOURCE_IDENTITY_PATTERNS = (
    "source_note:",
    "source_url:",
    "zotero_key:",
    "doi:",
    "arxiv:",
    "pmid:",
    "Raw note:",
    "URL:",
)


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    message: str

    def render(self) -> str:
        return f"{self.severity.upper()} {self.path}: {self.message}"


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def has_citation(line: str) -> bool:
    return "Source:" in line or bool(re.search(r"\[\[[^\]]+\]\]", line))


def iter_markdown_pages(root: Path) -> list[Path]:
    pages: list[Path] = []
    for page_dir in PAGE_DIRS:
        directory = root / page_dir
        if directory.exists():
            pages.extend(sorted(directory.glob("*.md")))
    return pages


def check_required_paths(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for required in REQUIRED_PATHS:
        path = root / required
        if not path.exists():
            findings.append(
                Finding("error", required, "Missing required wiki path")
            )
    return findings


def check_index(root: Path, pages: list[Path]) -> list[Finding]:
    index_path = root / "index.md"
    if not index_path.exists():
        return []

    index_text = index_path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    for page in pages:
        rel = relative(page.with_suffix(""), root)
        link_prefix = f"[[{rel}"
        if link_prefix not in index_text:
            findings.append(
                Finding("warning", relative(page, root), "page is missing from index.md")
            )
    return findings


def check_source_identity(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    sources_dir = root / "Sources"
    if not sources_dir.exists():
        return findings

    for page in sorted(sources_dir.glob("*.md")):
        text = page.read_text(encoding="utf-8")
        if not any(pattern in text for pattern in SOURCE_IDENTITY_PATTERNS):
            findings.append(
                Finding("error", relative(page, root), "source page is missing source identity")
            )
    return findings


def check_citations(root: Path, pages: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for page in pages:
        active_heading: str | None = None
        for line_no, line in enumerate(page.read_text(encoding="utf-8").splitlines(), start=1):
            heading = re.match(r"^##+\s+(.+?)\s*$", line)
            if heading:
                active_heading = heading.group(1).strip()
                continue

            if active_heading not in CITATION_REQUIRED_HEADINGS:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped == "---":
                continue
            if not has_citation(stripped):
                findings.append(
                    Finding(
                        "warning",
                        f"{relative(page, root)}:{line_no}",
                        "citation-required section contains a line without a citation",
                    )
                )
    return findings


def check_orphan_concepts(root: Path, pages: list[Path]) -> list[Finding]:
    concepts_dir = root / "Concepts"
    if not concepts_dir.exists():
        return []

    all_text_by_page = {
        page: page.read_text(encoding="utf-8")
        for page in [root / "index.md", *pages]
        if page.exists()
    }
    findings: list[Finding] = []
    for concept in sorted(concepts_dir.glob("*.md")):
        stem = concept.stem
        inbound = 0
        for page, text in all_text_by_page.items():
            if page == concept:
                continue
            if f"[[Concepts/{stem}" in text or f"[[{stem}" in text:
                inbound += 1
        if inbound == 0:
            findings.append(
                Finding("warning", relative(concept, root), "orphan concept page")
            )
    return findings


def lint(root: Path) -> list[Finding]:
    findings = check_required_paths(root)
    if any(f.severity == "error" for f in findings):
        return findings

    pages = iter_markdown_pages(root)
    findings.extend(check_index(root, pages))
    findings.extend(check_source_identity(root))
    findings.extend(check_citations(root, pages))
    findings.extend(check_orphan_concepts(root, pages))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wiki-root",
        type=Path,
        default=Path(DEFAULT_WIKI_ROOT) if DEFAULT_WIKI_ROOT else None,
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero when any warning or error is found.",
    )
    args = parser.parse_args()
    if args.wiki_root is None:
        raise SystemExit("Pass --wiki-root or set CODEX_RESEARCH_LLM_WIKI")

    findings = lint(args.wiki_root)
    if findings:
        for finding in findings:
            print(finding.render())
        if args.strict:
            return 1
        return 1 if any(f.severity == "error" for f in findings) else 0

    print("OK: no findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
