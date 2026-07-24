---
name: paper-read-draft
description: Use when a user asks to set up, create, prepare, or start a brief Obsidian PaperRead draft or paper-reading note.
---

# PaperRead Draft

Create one compact, factual note shell for a paper. The note records verified metadata and leaves all reading content to the user through hidden Obsidian prompts.

## Scope and Authority

- A standard create-draft request authorizes only one new note.
- Resolve the configured vault through `CODEX_OBSIDIAN_VAULT` and `obsidian_files`. Write only beneath `PaperRead/`; never use the current working directory as the vault.
- Accept a title, DOI, arXiv ID or URL, publisher URL, or Zotero item.
- Do not add or update Zotero and do not ingest the LLM Wiki.

## Resolve Identity and Metadata

1. Use metadata in this order: user-supplied facts; read-only Zotero when available; then one canonical scholarly source.
2. If identity is ambiguous, ask one focused question and do not guess, even under time pressure.
3. Fill a metadata field only when the user supplied it or current-task source/tool output actually observed it. Never claim a Zotero or canonical lookup occurred without actual returned evidence. Missing evidence means blank optional fields.
4. For `year`, prefer the official venue publication year; use the canonical preprint year only when no venue publication year is available.
5. If metadata remains unavailable, leave optional fields blank rather than blocking or inventing values. Report the result as metadata-only when that is the appropriate status.
6. Keep only facts in frontmatter. Do not provide a paper summary, claims, methods, evaluation, critique, quotes, or a reading log.

## Note Contract

Use the vault template at `PaperRead/_Paper Read Template.md` when it exists and satisfies the contract. If that exact vault template is missing or malformed, never silently rewrite the vault template; use the bundled fallback at `references/paper-read-template.md` for note creation.

The frontmatter contains only `title`, `authors`, `year`, `venue`, `url`, `tags`, and `created`. Do not add a body H1. The body has exactly these H2 sections, in order: `Summary and takeaway`, `My thoughts`, and `Questions`. Each section contains only its short `%% ... %%` prompt.

The base tag is `paper-read`. A concrete note may add at most three conservative lowercase hyphenated topic tags. If uncertain, use only `paper-read`.

## Filename Contract

Build every new note name as:

```text
PaperRead/<first-author-family-name><YY>-<short-method-name>.md
```

Establish all three components from current evidence before creating the note:

- Use the verified family name of the first listed author, lowercased. Replace its spaces and punctuation with single hyphens.
- Use the final two digits of the official venue publication year when available; otherwise use the canonical preprint publication year.
- Use the paper's short official proposed method, system, or model name. Preserve its official capitalization and numbers, but replace spaces and punctuation with single hyphens. Do not derive it mechanically from the full title or invent one; ask one focused question when it is unclear.

Run `python3 scripts/paper_read_filename.py --author-family <name> --year <YYYY> --method <short-name>` to generate the basename. Examples:

- Tianrui Feng, MLSys 2026, StreamDiffusionV2 → `feng26-StreamDiffusionV2.md`
- Luo et al., OSDI 2026, DirectKV Offloading → `luo26-DirectKV-Offloading.md`

Preserve the complete canonical paper title in frontmatter; the short method name affects only the filename.

## Safe Creation

1. Before any write, search `PaperRead/` for the same DOI, arXiv identifier, canonical URL, or exact normalized title. If the same paper already exists under any filename, return that path without creating, copying, renaming, or modifying it.
2. Perform an exact target-path check. If it contains the same paper, return it unchanged. If it contains a distinct paper or its identity cannot be established, return no-write and ask before choosing a disambiguated filename.
3. Never migrate legacy title-based filenames automatically. A separate explicit rename request is required.
4. Create the one note only under `PaperRead/`, then report the created path and any unresolved metadata.

## Completion Check

- Return an existing path unchanged when the exact note exists.
- Return an existing legacy-named path unchanged when paper-identity deduplication finds it.
- Otherwise return the created path, with unresolved optional metadata called out plainly.
- Do not fill personal sections by default; each is hidden-prompt-only.
