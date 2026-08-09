---
name: paper-review-library-intake
description: Import or repair one private Docmost paper-review submission in the user's Zotero Research/PaperReview collection with a verified PDF and desktop links. Use only for confidential assigned manuscripts and their Docmost attachments, not for public paper discovery or ordinary library intake.
---

# Paper Review Library Intake

Converge one private assignment into one Zotero parent and one readable PDF. Keep the submission inside the Docmost-to-local-to-Zotero trust boundary.

## Authority and boundaries

- Treat `check` as read-only. Do not call `docmost_download_attachment`, create a parent, change collection membership, or attach a file.
- Treat an explicit paper-review `sync`, `repair`, `import`, or `save` request as authority only for the named assignment, its PDF, and `Research/PaperReview` membership.
- Never send a private title, paper number, PDF, abstract, author list, review form, or review text to Paper Search, web search, Firecrawl, or another public service.
- Do not invoke `$paper-library-intake`: its public-discovery and `Research/ReadLater` behavior is intentionally different.
- Never merge, delete, index, switch libraries, create unrelated collections, or change unrelated Zotero fields.

## Establish identity before writing

Accept the authoritative assignment title, venue, venue year, full Paper Number, assignment page ID/URL, and exactly one row-scoped PDF attachment ID from `$paper-review-sync`.

Build the stable identity as:

```text
<venue-slug>|<four-digit-year>|<full-paper-number>
```

Normalize a venue slug with NFKC, lowercase text, known aliases (`SoCC`, `ACM SoCC`, or `ACM Symposium on Cloud Computing` → `socc`; `TMC`, `IEEE TMC`, or `IEEE Transactions on Mobile Computing` → `tmc`), hyphens for remaining non-alphanumeric runs, and no leading or trailing hyphen. Use the authoritative venue year; if absent, use the assignment deadline year. NFKC-normalize and trim the Paper Number, collapse internal whitespace, and otherwise preserve its canonical source spelling.

Search Zotero first for the exact `Paper Review ID:` value, then the exact Paper Number and title. Reuse only one exact-identity parent. Treat multiple identity matches, a title match carrying another review identity, or multiple possible PDF children as ambiguous; stop without merging or deleting.

Maintain this block in `Extra`, preserving unrelated lines:

```text
Paper Review ID: <identity>
Paper Number: <paper-number>
Review Venue: <venue>
Review Year: <year>
Docmost Assignment: <assignment-url>
```

## Import workflow

1. Resolve the live personal Zotero library and the exact existing collection path `Research/PaperReview`. Do not create or substitute a same-named leaf elsewhere.
2. Call Docmost `docmost_download_attachment(page_id, attachment_id)`. Require `application/pdf`, record its token, path, basename, byte count, and SHA-256, and reject any ambiguous row-to-attachment mapping before this call.
3. Inspect only the staged private PDF locally. Use the assignment title, venue, year, and number as authoritative. Add creators only when the first page clearly names them; leave anonymous or unavailable creators blank. Do not infer identities.
4. Run the redacted storage detector from the existing `$paper-library-intake` helper without printing the environment:

   ```bash
   set -a
   source "${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/zotero.env"
   set +a
   python3 <paper-library-intake-skill-dir>/scripts/zotero_attachment.py detect
   ```

   Block on an incomplete backend or unreachable configured WebDAV.
5. Recheck the exact identity immediately before writing. Create only a bibliographic parent when absent: `conferencePaper` for conference assignments, `journalArticle` for journals; title from the assignment; venue in `publicationTitle`; year in `date`; the managed `Extra` block; and only `Research/PaperReview` membership. Use metadata-only creation with no automatic cloud attachment.
6. For configured WebDAV, attach the staged PDF with:

   ```bash
   python3 <paper-library-intake-skill-dir>/scripts/zotero_attachment.py attach \
     --parent-key <PARENT_KEY> --file <STAGED_PDF> [--attachment-key <BROKEN_CHILD_KEY>]
   ```

   For official Zotero Storage, use the same helper's `attach-cloud` command. Never fall back between configured backends. Reuse a broken child only when the helper's receipt authoritatively identifies it.
7. Always call Docmost `docmost_release_attachment_download(download_token)` in a `finally` path, even after an import or verification failure. Never copy the staged PDF into the repository or an Obsidian vault.

If a parent write succeeds but attachment work fails, keep the parent and return `repair-needed` with its key and any helper-provided child key. Do not create another parent on retry.

## Verify and return

Read Zotero back and require:

- exactly one parent carrying the stable identity;
- membership in `Research/PaperReview`;
- exactly one authoritative imported-file PDF child;
- matching attachment basename/checksum where exposed; and
- readable first-page content through `zotero_read_pdf_pages`.

Return `reused`, `created`, `repaired`, `repair-needed`, `ambiguous`, or `failed`, plus the identity, parent key, PDF attachment key, checksum, and these personal-library links:

```text
zotero://select/library/items/<PARENT_KEY>
zotero://open-pdf/library/items/<ATTACHMENT_KEY>
```

Use the parent key only for `select` and the attachment key only for `open-pdf`.
