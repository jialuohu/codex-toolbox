# Research and paper reading

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Paper Library Intake](#paper-library-intake)
- [Private Paper Review Sync](#private-paper-review-sync)
- [Zotero-linked Todoist Reading Tasks](#zotero-linked-todoist-reading-tasks)
- [PaperRead Draft](#paperread-draft)
- [PaperRead Annotation](#paperread-annotation)
- [Optional MinerU Document Extraction](#optional-mineru-document-extraction)

## Paper Library Intake

Use one workflow for public discovery, Zotero deduplication, topical filing, and
attachment verification:

```text
$paper-library-intake find <title|DOI|arXiv URL>
$paper-library-intake add <title|DOI|arXiv URL>
```

`find` is read-only. `add` authorizes that paper's item, lawful attachment,
suitable topical collection memberships, and `Research/ReadLater`. The workflow
checks Zotero first, uses Paper Search first for public scholarly discovery,
cross-source validation, and open-access PDF retrieval, then uses normal Codex
web search when a current canonical page is still needed. It uses Firecrawl only
when that selected canonical page requires clean or dynamic extraction. It never
merges on title alone, enables semantic indexing, or uses Sci-Hub. The toolbox
disables the direct Sci-Hub tool and the unsafe upstream generic fallback; any
separately installed fallback must pass `use_scihub=false`.

The paper-search launcher loads its per-device environment before resolving the
checkout. Its portable default is
`${CODEX_PROJECTS_ROOT:-$HOME/codes}/paper-search-mcp`; override it in the local
secret environment when needed:

```bash
PAPER_SEARCH_MCP_ROOT=<paper-search-mcp-checkout>
```

Attachment storage is detected from the three `ZOTERO_WEBDAV_*` variables. A
complete set selects Koofr/WebDAV, an absent set selects official Zotero
Storage, and a partial set blocks before any library mutation. Configured
WebDAV never silently falls back to Zotero Storage. These variables are the
authoritative auto-detection signal and must match Zotero's **Sync > File
Syncing** setting; endpoint reachability cannot prove that desktop setting. The provider-neutral helper
creates or repairs the same attachment child, verifies the uploaded checksum,
and requires a readable PDF page before success. If no lawful PDF is available,
the receipt says `metadata-only`. For an existing parent with a missing or
broken official-storage child, the same helper exposes `attach-cloud`; it keeps
retries on one attachment key and still requires final
`zotero_read_pdf_pages` verification. A per-parent local-host lock, correlated
lost-create response reconciliation, and same-name post-create checks reduce
duplicate children; definitive API rejections never adopt another host's child,
and final Zotero rechecks still detect concurrency from another host.

Run the redacted storage and WebDAV-connectivity check after loading the local
Zotero environment. In WebDAV mode it returns `reachable: true` before any
library mutation; the helper automatically selects the installed Zotero-MCP
Python runtime when necessary:

```bash
set -a
source "${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/zotero.env"
set +a
python3 plugins/research-tools/skills/paper-library-intake/scripts/zotero_attachment.py detect
```

Do not print or commit the secret environment. A real Zotero write canary should
only be performed for a paper the user explicitly asks to add.

## Private Paper Review Sync

Use the on-demand workflow when the advisor may have appended assignments or
when a review record needs repair:

```text
$paper-review-sync check
$paper-review-sync sync
$paper-review-sync repair <paper-number>
```

`check` is strictly read-only. `sync` and `repair` reconcile only active rows
assigned to the confirmed exact aliases Jialuo Hu or Jialuo with blank Word Count. The orchestrator uses
`$paper-review-library-intake` to store private PDFs under
`Research/PaperReview`, `$paper-review-page` to create exact-Paper-Number pages
under the matching conference edition in `Review Dojo/Review Comments`, and one Todoist surface for tasks in
`Paper Reviews/Assigned` with `paper-review` and `deep-work` labels. Todoist
links use the Zotero parent key for `select` and PDF attachment key for
`open-pdf`. After page and task readback, the sync adds one native Docmost page
mention to the row's blank `Review Comments` cell. A linked row remains active
until `Word Count` is filled. Docmost page bodies preserve the authoritative
conference review form, including venue-provided AI-disclosure fields and
instructions. The reviewer is rendered as `Hao Wang ` followed by a
`hwang9@stevens.edu` link to `mailto:hwang9@stevens.edu`; status, selections,
and filled responses are blanked.
Managed identity and cross-links remain in Todoist and Zotero.

Private submissions, titles, forms, and review text never go to Paper Search,
web search, or Firecrawl. Same-edition pages supply structure only; substantive
peer review content is discarded. The workflow never invents an `AI-involved`
tag or font-color markup, but it does not remove either fixed instructions or
formatting supplied by the authoritative form. Partial runs keep the Todoist assignment and
mark missing managed links for a later repair. Repeated runs are idempotent
snapshots, not continuous monitoring.

## Zotero-linked Todoist Reading Tasks

Use one workflow to turn a saved Zotero collection into trackable Todoist paper
readings or to repair Zotero links on existing reading tasks:

```text
$zotero-todoist-reading-tasks create tasks from Zotero collection Research/ReadLater/video-gen-serving
$zotero-todoist-reading-tasks repair Zotero links in my existing paper-reading tasks
$zotero-todoist-reading-tasks create tasks from Zotero collection Research/ReadLater/video-gen-serving without Obsidian notes
```

The workflow reads Zotero without changing the library and writes through one
Todoist surface only, preferring the connected app over the hosted MCP fallback.
Each task receives a parent-item link and, when exactly one PDF attachment can be
resolved, an attachment-key link that opens the PDF in Zotero Desktop. It
deduplicates by the parent-item URI, preserves unrelated task fields, and stops
when title or attachment matching is ambiguous.

By default, each uniquely resolved Zotero parent gets one bounded PaperRead
create-or-reuse action before its first Todoist write. `$paper-read-draft` owns
note identity, safe creation, and URI generation; this workflow uses only its
returned URI to maintain one canonical `Obsidian: [Open PaperRead note](...)`
line. Say `without Obsidian notes` to skip PaperRead entirely and preserve any
existing Obsidian line. If PaperRead cannot return a URI, Todoist work continues
best-effort with `note-missing`, while stale canonical Obsidian lines are removed.

When scheduling is requested, the task's due date is its planned reading day and
`deadlineDate` remains the final cutoff. An unspecified daily allocation is
distributed evenly across the available dates in reading order. This is an
explicit one-time reconciliation, not continuous Zotero–Todoist synchronization.

## PaperRead Draft

Use `$paper-read-draft` to create a compact Obsidian PaperRead draft for one
paper without filling in the reading itself:

```text
$paper-read-draft <title|DOI|arXiv URL|publisher URL|Zotero item>
```

For a natural-language request, say: “Create a PaperRead draft for this paper
and put it in my Obsidian vault.” The workflow fills factual metadata only and
leaves the three personal sections—One-sentence summary, Summary and takeaway,
and My thoughts—for the user. Open questions belong in My thoughts rather than
a separate section. The note title remains in frontmatter and the body has no
repeated H1. New filenames use
`<first-author-family-name><YY>-<short-method-name>.md`, such as
`feng26-StreamDiffusionV2.md`; the venue publication year takes precedence over
the preprint year. Before creation, the workflow checks all `PaperRead/` notes
for the same paper identity so a legacy title-based note is not duplicated.
The workflow does not add or update Zotero or ingest the Research LLM Wiki.

## PaperRead Annotation

Use `$paper-read-review` to add source-backed feedback inside one completed
PaperRead note:

```text
$paper-read-review annotate PaperRead/<note>.md
```

A request to review, critique, fact-check, strengthen, or annotate one exact
existing `PaperRead/` note authorizes this skill to add Obsidian callouts inside
that note. There is no chat-only review mode. The first run inserts hidden-marker
blocks; later runs replace only those valid skill-owned blocks. Vault edits
prefer `obsidian_files`; an enabled Obsidian CLI may perform guarded `obsidian
read` plus `obsidian eval` exact edits, otherwise the operation is no-write.
The workflow preserves the user's frontmatter and prose, checks technical
accuracy, missing contributions, evidence, limitations, and research questions,
and keeps private note or Zotero content out of public search services. Generated
comments are concise, use no more than two callouts per section, and separate
adjacent callouts with an unquoted blank line so Obsidian renders them
independently. In the current three-section layout, generated feedback is
section-local: One-sentence summary, Summary and takeaway, and My thoughts each
own a distinct hidden-marker block at the end of their corresponding section.

## Optional MinerU Document Extraction

Use `$mineru-document-extraction` for complex, scanned, OCR-heavy, or
layout-sensitive local documents when columns, tables, formulas, figures, or
page structure matter. Keep the source boundary explicit:

- For straightforward born-digital files and simple reads, use the installed
  `pdf` or `documents` skill.
- For an item already saved in the research library, use Zotero.
- For web content, use Defuddle or Firecrawl rather than MinerU.
- For vault reads or writes, use `obsidian_files`. Extract first to a separate
  `<review-directory>` outside the vault, review the artifacts, and only then
  perform a separately requested vault write.

MinerU is a local skill and setup helper, not an MCP server. Check the optional
runtime before extraction:

```bash
scripts/setup-mineru.sh --check
```

If local setup is wanted, install the isolated runtime and opt in to model
downloads as separate steps:

```bash
scripts/setup-mineru.sh --install
scripts/setup-mineru.sh --download-models
```

The extraction skill starts with its quality-first hybrid/high settings. If
resource or latency limits prevent completion, retry hybrid/medium; if the
hybrid accelerator runtime is unavailable, retry pipeline/medium. Preserve OCR
mode across retries for a known scan, use a fresh `<review-directory>` for each
attempt, and do not silently replace MinerU with a simple reader when the
document needs layout reconstruction.

The wrapper requires the managed MinerU 3.4.4 runtime, processes a private
read-only copy instead of the original, uses configured local models with
offline hub behavior, and writes private checksum-verified artifacts.

Keep model caches, extracted outputs, benchmark artifacts, and machine-local
workflow overrides outside this repository and untracked.
