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
4. If metadata remains unavailable, leave optional fields blank rather than blocking or inventing values. Report the result as metadata-only when that is the appropriate status.
5. Keep only facts in frontmatter. Do not provide a paper summary, claims, methods, evaluation, critique, quotes, or a reading log.

## Note Contract

Use the vault template at `PaperRead/_Paper Read Template.md` when it exists and satisfies the contract. If that exact vault template is missing or malformed, never silently rewrite the vault template; use the bundled fallback at `references/paper-read-template.md` for note creation.

The frontmatter contains only `title`, `authors`, `year`, `venue`, `url`, `tags`, and `created`. The body has one H1 with the real title and exactly these H2 sections, in order: `Takeaway`, `Summary in my own words`, `My thoughts`, and `Questions`. Each section contains only its short `%% ... %%` prompt.

The base tag is `paper-read`. A concrete note may add at most three conservative lowercase hyphenated topic tags. If uncertain, use only `paper-read`.

## Safe Creation

1. Derive the concrete filename from the canonical title, with `/`, `:`, and shell-hostile characters normalized, whitespace collapsed, and `.md` appended. Preserve the real title in frontmatter and H1.
2. Before any write, perform an exact-path check. If the note already exists, return its path without modifying it.
3. If a normalized filename collision represents a distinct paper, ask before choosing a disambiguated filename.
4. Create the one note only under `PaperRead/`, then report the created path and any unresolved metadata.

## Completion Check

- Return an existing path unchanged when the exact note exists.
- Otherwise return the created path, with unresolved optional metadata called out plainly.
- Do not fill personal sections by default; each is hidden-prompt-only.
