# Codex Toolbox

This repository manages a Codex plugin marketplace, MCP configuration,
third-party marketplace pins, and reusable Codex instructions.

## New Device Setup

1. Clone the repository:

   ```bash
   git clone <repo-url> codex-toolbox
   cd codex-toolbox
   ```

2. Run the setup script:

   ```bash
   scripts/setup-codex-toolbox.sh
   ```

   The script registers the configured toolbox marketplace from the Git-backed
   marketplace source `jialuohu/codex-toolbox` on `main`, refreshes default
   plugins, installs third-party marketplace pins, removes stale direct MCP
   overrides for managed servers, and copies
   `config/codex/AGENTS.global.md` to `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`.
   Because the toolbox marketplace is Git-backed, users can refresh it later
   from the Codex Desktop app by clicking **Upgrade**, or from the CLI:

   ```bash
   codex plugin marketplace upgrade jialuo-codex-toolbox
   ```

   For local plugin development before changes are pushed to GitHub, register
   the checkout directly instead:

   ```bash
   CODEX_TOOLBOX_MARKETPLACE_MODE=local scripts/setup-codex-toolbox.sh
   ```

3. Add per-device secrets outside the repository as needed. Keep OAuth state,
   API keys, tokens, credential files, and env-file contents out of version
   control.

   Connector-specific credential paths, account details, and companion tool
   install locations should stay in local, untracked configuration.

4. Run MCP login or connector setup commands for any services that need local
   authentication.

5. Start a fresh Codex session so the installed global `AGENTS.md`, plugins, and
   MCP servers are loaded from the beginning of the run.

## Managed Codex Pet

The toolbox keeps the validated `stinky-penguin` v2 package under
`config/codex/pets/stinky-penguin/`. Setup copies repository-managed pets into
`${CODEX_HOME:-$HOME/.codex}/pets/` atomically, backs up a different package
with the same ID, and preserves unrelated custom pets. It installs the pet
without selecting it or changing the current Codex avatar preference.

Use the synchronizer directly when validating or installing pet updates:

```bash
python3 scripts/sync-codex-pets.py --install
python3 scripts/sync-codex-pets.py --check
```

A marketplace **Upgrade** refreshes plugins but does not copy runtime pet
files. Rerun the toolbox setup after upgrading when a managed pet changes, then
start a fresh Codex Desktop session to load and animate the updated atlas.

## Todoist Task Planning

The default `productivity-tools` plugin bundles `$todoist-task-planning` and
Todoist's official hosted MCP at `https://ai.todoist.net/mcp`. Prefer the
connected Todoist app in ChatGPT or Codex Desktop. The hosted MCP is the Codex
CLI fallback when app tools are unavailable; use one Todoist tool surface per
request so a task is never written twice.

Todoist remains the durable source of truth for tasks; Google Calendar is used
only for explicit meetings and focused work blocks. Deadline-only tasks stay in
Todoist, including deadlines with a clock time.

If the connected app is unavailable in a CLI session, authorize the hosted MCP
on that device:

```bash
codex mcp login todoist
```

Start a fresh Codex task after login. Example requests include:

```text
Add "submit expense report" to my Todoist for Friday.
Block two hours tomorrow afternoon to work on the proposal.
Schedule a 30-minute remote check-in with Alice next Tuesday at 2 PM.
Show my overdue tasks and what is due this week.
```

Task creation is allowed when explicitly requested. Calendar writes, attendee
invitations, deletions, and ambiguous updates remain confirmation-gated. A
one-time task/event cross-link is not ongoing bidirectional synchronization.

## Daily Command Center

Use `$daily-command-center` for a read-only daily brief that brings together
Gmail context, Google Calendar commitments, and Todoist priorities. It reads
the connected sources on each run, keeps Todoist authoritative for actionable
tasks and Calendar authoritative for time commitments, and proposes follow-up
actions without changing email, calendar, or task records.

Invoke it manually when you want a morning or daily planning pass:

```text
Use $daily-command-center to prepare my read-only daily brief.
```

It can also be used from a scheduled task at your preferred local time. The
scheduled run remains read-only and reports partial coverage if a connected
source is unavailable; use the relevant interactive workflow for any later
email, calendar, or Todoist change.

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

## PaperRead Draft

Use `$paper-read-draft` to create a compact Obsidian PaperRead draft for one
paper without filling in the reading itself:

```text
$paper-read-draft <title|DOI|arXiv URL|publisher URL|Zotero item>
```

For a natural-language request, say: “Create a PaperRead draft for this paper
and put it in my Obsidian vault.” The workflow fills factual metadata only and
leaves the four personal sections—Takeaway, Summary in my own words, My
thoughts, and Questions—for the user. It does not add or update Zotero or
ingest the Research LLM Wiki.

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

## Execution Routing

For large decomposable projects, start naturally in Plan mode. For example:

```text
Build a polished business website for a small AI consulting agency.
```

The global instructions let Codex plan first and then select the narrowest
execution lane. Tiny changes stay in the main task. Independent, testable work
can run through native Codex subagents, while non-trivial coding uses the
Superpowers planning and subagent-driven-development workflow. Use OpenSpec
when durable requirements, acceptance criteria, or spec governance should be
settled before implementation.

## Deep Planning

Plan Mode uses `$deep-planning` by default for non-trivial work before the
final plan is presented. The skill is a critique gate: it gathers observed
facts, states assumptions and material unknowns, drafts the strongest plan,
challenges product value, architecture, implementation risk, edge cases, tests,
rollout, and scope, then chooses Codex-only, native Codex subagents,
Superpowers, or OpenSpec routing.

Superpowers remains the design and implementation workflow. Deep Planning does
not write `docs/superpowers/` artifacts, create issues, dispatch workers, or
perform verification after code changes.

## Explain Clearly

Use `$explain-clearly` when a concept, why/how question, comparison, or code
walkthrough needs a clear mental model and concrete example. It leads with the
direct answer, uses one accurate example by default, and adds only the mechanism
or caveat needed to avoid a misleading simplification.

Example prompt:

```text
Use $explain-clearly to explain JavaScript closures with a simple mental model and one concrete example.
```

## Paper Figure Workflow

Use `$paper-figure-workflow` when a research repo needs reproducible paper
figures. The skill guides Codex to inspect the repo first, keep draw.io source
diagrams editable, generate Matplotlib and SciencePlots result plots from repo
data, export SVG/PDF figures, use Inkscape only for conversion or light cleanup,
and add a command such as `make figures`.

Example prompt:

```text
Use $paper-figure-workflow to set up clean, reproducible figures for this AI/systems paper repo.
```

## AGENTS.md Sync

The canonical global instructions live at `config/codex/AGENTS.global.md`.

Use:

```bash
scripts/sync-agents.sh --check
scripts/sync-agents.sh --install
```

`--install` creates `${CODEX_HOME:-$HOME/.codex}` if needed, backs up a
different existing `AGENTS.md`, installs the managed copy, and writes a local
marker under `${CODEX_HOME:-$HOME/.codex}/.codex-toolbox/`.

If `${CODEX_HOME:-$HOME/.codex}/AGENTS.override.md` exists, Codex will prefer
that file over the managed `AGENTS.md`; the sync script warns about this.
