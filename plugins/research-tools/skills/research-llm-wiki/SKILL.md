---
name: research-llm-wiki
description: Maintain a Karpathy-style, source-backed research LLM Wiki in the user's Obsidian vault. Use when the user asks to ingest papers, Zotero items, web clips, PDFs, or paper notes into `Research/LLM Wiki`; query or synthesize from that wiki; file durable research analyses; lint the wiki for stale claims, missing citations, orphan pages, duplicate concepts, or contradictions; or mentions `$research-llm-wiki ingest`, `$research-llm-wiki query`, or `$research-llm-wiki lint`.
---

# Research LLM Wiki

## Overview

Maintain a generated research wiki under `CODEX_RESEARCH_LLM_WIKI`. Treat raw sources as immutable and use the wiki as the compiled, source-backed synthesis layer that Codex owns.

Use Obsidian Markdown conventions: internal links use `[[wikilinks]]`, external sources use Markdown links, and nontrivial claims carry source citations. Do not rewrite raw source notes, Zotero records, PDFs, or web clips during wiki maintenance.

## Wiki Layout

The wiki root is `Research/LLM Wiki/` inside the Obsidian vault. Keep this layout:

- `_schema.md`: domain schema, page conventions, and workflow rules.
- `index.md`: content-oriented catalog. Read it first for query and ingest routing.
- `log.md`: append-only chronological operation log.
- `Sources/`: one generated summary per raw paper, article, book chapter, talk, or note bundle.
- `Concepts/`: reusable topic and mechanism pages.
- `Comparisons/`: cross-source comparison pages.
- `Questions/`: open questions, contradictions, weak claims, and research gaps.
- `Analyses/`: saved answers and durable syntheses created from queries.

If `_schema.md` is missing or obviously incomplete, initialize it from `references/schema-template.md` and adapt only concrete local paths or domain categories.

## Source Handling

Prefer the narrowest local or connected source:

- Use `obsidian_files` or local filesystem reads for vault notes under `CODEX_OBSIDIAN_VAULT`.
- Use Zotero MCP for saved library metadata, notes, annotations, and PDFs.
- Use `paper_search_mcp` for discovering or downloading public scholarly sources.
- Use Firecrawl for public web pages or clean web extraction.
- Use existing `Paper Notes/` pages as raw source notes; do not edit them unless the user explicitly asks.

Before writing wiki updates, identify the raw source path, URL, DOI, arXiv id, Zotero key, or note link. If no reliable source identity exists, record the source as `unverified` and keep claims conservative.

## `$research-llm-wiki ingest <source>`

1. Resolve the source and read enough content to summarize it accurately.
2. Ensure the wiki scaffold exists: `_schema.md`, `index.md`, `log.md`, and the page-type directories.
3. Create or update one `Sources/` page for the source. Include title, source identity, status, short summary, key claims, methods or evidence, limitations, and links to related concept pages.
4. Update or create `Concepts/`, `Comparisons/`, and `Questions/` pages only when the source materially changes the synthesis.
5. Update `index.md` with new or changed pages and one-line summaries.
6. Append one parseable entry to `log.md` using `## [YYYY-MM-DD] ingest | <source title>`.
7. Report which wiki pages changed and which raw source was used.

Do not create many tiny entity pages on first ingest. Start with source pages plus concept pages that compress facts across multiple sources.

## `$research-llm-wiki query <question>`

1. Read `index.md` first, then open the smallest set of relevant wiki pages.
2. Read raw sources only when citations are missing, weak, contradicted, or the user asks for source verification.
3. Answer with citations to wiki pages and raw sources where material claims depend on them.
4. If the answer is durable and the user asks to save or file it, write an `Analyses/` page and append `## [YYYY-MM-DD] query | <question>` to `log.md`.
5. If the query reveals a contradiction or gap, add or update a `Questions/` page when writing is in scope.

Do not file ordinary chat answers back into the wiki without user intent or a clear durable research value.

## `$research-llm-wiki lint`

Run a bounded health check over `Research/LLM Wiki`:

1. Run the deterministic helper first:

   ```bash
   python3 <skill-dir>/scripts/lint_research_llm_wiki.py --wiki-root "CODEX_RESEARCH_LLM_WIKI"
   ```

2. Inspect any findings and then do a judgment pass for higher-level contradictions or synthesis gaps.

The helper checks:

- Missing required scaffold files or directories.
- Pages absent from `index.md`.
- `Sources/` pages without source identity.
- Nontrivial claims with no citation or source link.
- Orphan concept pages with no inbound wiki links.
- Duplicate or near-duplicate concept pages.
- Stale pages whose source was updated after the generated page.
- Contradictions that should be linked from `Questions/`.

Report findings by severity. Only edit files during lint when the user asks for automatic cleanup.

## Page Rules

- Keep wiki pages concise. A page should compress source material, not mirror it.
- Prefer one strong page over many thin pages.
- Use stable filenames: title case is fine, but avoid `/`, `:`, and shell-hostile characters.
- Preserve Obsidian links when renaming would be needed; ask before broad moves or renames.
- Mark uncertainty explicitly: `well-supported`, `mixed`, `weak`, or `open question`.
- Never hide contradictions. Link them from both affected pages and a `Questions/` page.
- Keep `log.md` append-only except for typo fixes in the latest entry.

## References

- `references/schema-template.md`: starter `_schema.md` content for initializing or repairing the wiki schema.
- `scripts/lint_research_llm_wiki.py`: deterministic scaffold, index, source identity, citation, and orphan concept checks.
