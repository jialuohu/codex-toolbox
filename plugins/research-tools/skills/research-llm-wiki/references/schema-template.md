# Research LLM Wiki Schema Template

Use this content when creating or repairing `Research/LLM Wiki/_schema.md`.

```markdown
# Research LLM Wiki Schema

This directory is the Codex-owned synthesis layer for research knowledge. Raw source notes, Zotero records, PDFs, and web clips remain the source of truth and are not rewritten during wiki maintenance.

## Root

Vault root: `CODEX_OBSIDIAN_VAULT`

Wiki root: `Research/LLM Wiki/`

## Required Files

- `_schema.md`: this schema and workflow contract.
- `index.md`: content-oriented catalog of generated wiki pages.
- `log.md`: append-only chronological log of ingests, queries, and lint passes.

## Page Types

- `Sources/`: generated source summaries. One page per paper, article, chapter, talk, or raw-note bundle.
- `Concepts/`: reusable mechanisms, ideas, terms, and claims that span sources.
- `Comparisons/`: side-by-side or cross-source synthesis.
- `Questions/`: open questions, contradictions, weak evidence, and follow-up reading queues.
- `Analyses/`: durable answers generated from user queries.

## Source Identity

Every `Sources/` page should identify at least one raw source:

- Obsidian wikilink such as `[[PaperNotes/Example Paper]]`
- Local path relative to the vault
- Zotero key
- DOI, arXiv id, PubMed id, or URL

If source identity is incomplete, set `status: unverified` and avoid strong claims.

## Citation Rules

- Cite raw sources for nontrivial factual claims.
- Cite generated wiki pages only for navigation or previously compiled synthesis.
- Keep direct quotes short.
- Mark uncertainty as `well-supported`, `mixed`, `weak`, or `open question`.

## Operation Log

Use parseable headings:

- `## [YYYY-MM-DD] ingest | <source title>`
- `## [YYYY-MM-DD] query | <question>`
- `## [YYYY-MM-DD] lint | <scope>`

Each entry should list changed wiki pages and source material inspected.

## Maintenance Rules

- Do not rewrite raw source notes.
- Keep generated pages concise.
- Prefer concept pages only when they compress knowledge across sources.
- Link contradictions from `Questions/`.
- Update `index.md` whenever a page is added, removed, or materially changed.
- Keep `log.md` append-only except for typo fixes in the latest entry.
```
