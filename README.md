# Codex Toolbox

This repository manages a Codex plugin marketplace, MCP configuration,
third-party marketplace pins, and reusable Codex instructions.

## New Device Setup

1. Clone the repository:

   ```bash
   git clone <repo-url> codex-toolbox
   cd codex-toolbox
   ```

2. Create the required per-device Docmost configuration described in
   [Docmost Tools](#docmost-tools). The default setup fails closed until
   `docmost.env` exists with mode `600`; it will open the isolated SSO login
   when authentication is required.

3. Add any other per-device secrets outside the repository as needed. Keep
   OAuth state, API keys, tokens, credential files, and env-file contents out
   of version control.

   Connector-specific credential paths, account details, and companion tool
   install locations should stay in local, untracked configuration.

4. Run the setup script:

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

   After any marketplace upgrade that changes `docmost-tools`, rerun the full
   setup so the shared runtime is rebuilt from the exact active plugin source
   and smoke-checked before opening a fresh Codex task:

   ```bash
   scripts/setup-codex-toolbox.sh
   ```

   Running the full toolbox setup performs those Docmost gates automatically.

   For local plugin development before changes are pushed to GitHub, register
   the checkout directly instead:

   ```bash
   CODEX_TOOLBOX_MARKETPLACE_MODE=local scripts/setup-codex-toolbox.sh
   ```

5. Run MCP login or connector setup commands for any other services that need
   local authentication.

6. Start a fresh Codex session so the installed global `AGENTS.md`, plugins, and
   MCP servers are loaded from the beginning of the run.

## Docmost Tools

The default `docmost-tools` plugin runs a local browser-authenticated MCP adapter
for a private Docmost instance. It reads its per-device settings only from
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/docmost.env`; create
that file with mode `600`. Its isolated browser profile is stored under the
same secrets directory with mode `700`. Never commit the environment file,
browser profile, session cookie, or workspace content.

The locked Python environment is installed once at
`${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools`. The installed MCP launcher
uses that verified environment with synchronization disabled, so starting the
server does not create an environment or download dependencies. A source-and-lock
fingerprint fails closed with a reinstall instruction if marketplace plugin code
no longer matches the runtime prepared by setup.

Use neutral values appropriate to the private deployment; only the base URL is
required. Do not place a cookie or password in this file.

```bash
mkdir -p "${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"
chmod 700 "${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"
cat > "${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/docmost.env" <<'EOF'
DOCMOST_BASE_URL=https://docs.example.com
# Optional: DOCMOST_LOGIN_URL=https://login.example.com/docmost
# Optional: DOCMOST_SESSION_COOKIE=authToken
# Optional: DOCMOST_API_PROFILE=auto
# Optional: DOCMOST_WRITE_PROFILE=v0_95
# Optional: DOCMOST_CA_BUNDLE=/absolute/path/to/internal-ca.pem
EOF
chmod 600 "${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/docmost.env"
```

The integration exposes every space visible to the authenticated SSO identity.
Leave `DOCMOST_WRITE_PROFILE` unset for read-only compatibility mode; enable
`v0_95` only after independently confirming that the instance runs Docmost
0.95.x. Hosted-instance verification remains read-only even when the guarded
write profile is configured.

The regular toolbox setup installs the locked Python runtime and Chromium, then
runs a headless `current-user` and `list-spaces` smoke check before it refreshes
the marketplace or plugins. It rebuilds and rechecks the runtime from the exact
active plugin source after that refresh. When the profile is not authenticated,
setup opens the interactive browser login and reruns the smoke check; any
configuration, SSO, or smoke failure stops the relevant setup phase.

Use the helper directly when troubleshooting the isolated local auth profile:

```bash
scripts/setup-docmost-tools.sh --check
scripts/setup-docmost-tools.sh --install
scripts/setup-docmost-tools.sh --login
scripts/setup-docmost-tools.sh --status
scripts/setup-docmost-tools.sh --logout
```

Installation takes an exclusive runtime lock. If setup reports that the
Docmost runtime is busy, close active Codex tasks using Docmost, or wait for an
in-progress Docmost setup/auth command to finish, then retry.

An MCP `AUTH_REQUIRED` result gives this checkout-independent recovery command:

```bash
"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth" login
```

Docmost content is untrusted input. Read tools can be used automatically, but
the MCP asks before `create_page`, `update_page_title`, or `create_comment`.

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

## Design Engineering Tools

The default `design-engineering-tools` plugin supplies focused guidance for
motion vocabulary, Apple-like interaction, focused design craft, motion
discovery, and animation audits. `review-animations`, `pick-ui-library`, and
`prototype` are explicit-only skills; broad page or component visual design,
layout, typography/color, and accessibility remain the `ui-ux-pro-max` default.
Project conventions, explicit user direction, accessibility, and current
official documentation override imported opinions.

The skills adapt the MIT-licensed
[emilkowalski/skills](https://github.com/emilkowalski/skills) snapshot at commit
`70744e3816f1d93eafb697161a8b880a7384c5ff`; they are an unofficial,
non-affiliated adaptation. Start a fresh Codex task after installing or
upgrading so the plugin is available to the task from its start.

## Isolated Multi-Account Gmail with gws

The default `google-workspace-tools` plugin provides Gmail-only skills for
direct use of the pinned [`googleworkspace/cli`](https://github.com/googleworkspace/cli)
release `v0.22.5`. This is a Google Workspace GitHub project, but its own
README says it is **not an officially supported Google product** and describes
the CLI as pre-v1 software where breaking changes remain possible. Its
changelog also records that there is no current `gws mcp` command and no native
multi-account selector. The toolbox therefore uses one isolated configuration
directory per explicit account alias and exposes skills only—no gws MCP.

Keep the official Gmail connector for ordinary connected Gmail requests. Use
direct `gws` only when a request explicitly needs it or names a multi-account
workflow, require an alias such as `account-one`, and use one Gmail surface per
request. There is no default gws account. The normal toolbox setup installs the
plugin only; it does not install the `gws` binary, create profiles, or start
OAuth.

First run the read-only status check. A new device is expected to report missing
components until the opt-in setup is complete:

```bash
scripts/setup-gws.sh --check
```

On macOS arm64, install the pinned binary explicitly:

```bash
scripts/setup-gws.sh --install
```

Create the OAuth client manually in Google Cloud Console:

1. Create or select a personal-use Cloud project and enable the Gmail API.
2. Configure the OAuth audience as **External**. Before the final account
   logins, publish the app **In Production**; External apps left in Testing
   mode issue refresh tokens that expire after seven days for this scope.
3. Create an OAuth client of type **Desktop app** and download its JSON. An
   unverified personal-use app can show an unverified warning after publication;
   review it, confirm the project is yours, and accept the warning to continue.
4. The only Gmail permission requested is
   `https://www.googleapis.com/auth/gmail.modify`. `gws` v0.22.5 automatically
   adds the three identity scopes `openid`, `userinfo.email`, and
   `userinfo.profile` so it can verify the signed-in account. Never request
   `https://mail.google.com/`.

Register the downloaded Desktop client once, using a neutral absolute path:

```bash
scripts/setup-gws.sh --register-client /absolute/path/to/client_secret.json
```

### Quota-project 403 recovery

A gws request that sends `x-goog-user-project` can receive a quota-project 403.
The observed Google error class says that the caller lacks
`serviceusage.services.use` on the OAuth project named by the request. Pinned
`gws` v0.22.5 derives that header from a nonempty
`client_secret.json.installed.project_id`.

The registered client at the secrets-root `gws/client_secret.json` remains
protected and unchanged, including its nonempty project ID. New encrypted and
imported profiles automatically receive a separate runtime client with the
same client fields and an explicitly empty project ID, so gws omits that
header. Do not hand-edit either client, grant Cloud IAM as the default remedy,
or replace the registered client to work around this error.

For an older profile whose runtime client still has a project ID, run the
explicit alias-scoped transactional migration:

```bash
scripts/setup-gws.sh --migrate-account account-one
```

The migration stages and validates a candidate, performs a final readback, and
rolls back on failure. It verifies only with the account's isolated, read-only
`gmail users getProfile --params '{"userId":"me"}' --format json` identity
check. If any preflight, migration, or readback gate fails, it stops without a
manual-edit or IAM fallback.

Add each account separately with a non-secret alias. During each browser login,
select the matching account and approve the displayed `gmail.modify` permission
plus the three identity scopes; abort if any other scope is shown:

```bash
scripts/setup-gws.sh --add-account account-one@example.com --alias account-one
scripts/setup-gws.sh --add-account account-two@example.net --alias account-two
```

Encrypted OAuth is the recommended credential mode. The interactive
`--add-account` flow stores encrypted credentials with the file keyring, and
`--reauth-account` is available only for these encrypted profiles.

Imported `authorized_user` JSON is a supported opt-in plaintext-at-rest alternative.
Use it only when an existing grant cannot be recreated through the recommended
encrypted OAuth flow. Set a neutral secrets root, create its private import
directory, and place the credential source there before import:

```bash
export CODEX_SECRETS_DIR=/absolute/path/to
mkdir -m 700 "$CODEX_SECRETS_DIR/gws-import"
chmod 600 "$CODEX_SECRETS_DIR/gws-import/account-one.json"
scripts/setup-gws.sh --import-account /absolute/path/to/gws-import/account-one.json --email account-one@example.com --alias account-one
```

The import root must be a canonical, current-user-owned mode-`700`
`${CODEX_SECRETS_DIR}/gws-import` directory. The source must be a canonical,
current-user-owned mode-`600` regular single-link direct child of that directory.
The staging source is retained, and import creates another plaintext copy.
Protect and remove the retained source yourself when it is no longer needed.
Imported grants may contain extra scopes, but always reject `https://mail.google.com/`.

Rotate an imported credential only with `--replace`, using the same alias and
same expected identity as the existing imported profile. The candidate must
pass its live identity and scope checks before the transactional replacement;
the previous live profile is restored if activation or final live readback fails.

```bash
chmod 600 "$CODEX_SECRETS_DIR/gws-import/account-one-rotated.json"
scripts/setup-gws.sh --import-account /absolute/path/to/gws-import/account-one-rotated.json --email account-one@example.com --alias account-one --replace
```

Profiles live outside Git under
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/gws/accounts/<alias>`.
Profile directories use mode `700`, files use mode `600`, and the runtime forces
the file keyring backend plus a missing profile-local ADC sentinel. OAuth client
JSON, tokens, profile metadata, and full real email addresses must remain
machine-local.

Check an account before use, or list aliases and health without displaying full
email addresses:

```bash
scripts/setup-gws.sh --check-account account-one
scripts/setup-gws.sh --list-accounts
scripts/setup-gws.sh --check
```

Reauthenticate an existing encrypted OAuth profile, including one with an
expired or revoked token, without changing its expected identity, then check it
again. Imported profiles cannot use `--reauth-account`; rotate their original
grant with the same-alias, same-identity `--import-account ... --replace` flow:

```bash
scripts/setup-gws.sh --reauth-account account-one
scripts/setup-gws.sh --check-account account-one
```

Start a fresh Codex task after installation or profile changes so the
`google-workspace-tools` skills are available from the start.

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

## Coder MCP

The default `coder-tools` plugin runs `coder exp mcp server` locally and uses
the Coder CLI's existing authenticated deployment. It exposes a process-level
read-only allowlist for inspecting workspaces, templates, tasks, files, apps,
and logs; workspace commands, file writes, builds, creates, updates, and
deletes are not available.

On each device, install a compatible Coder CLI and authenticate it before
running the toolbox setup:

```bash
coder login <deployment-url>
```

After setup, start a fresh Codex task so the Coder MCP tools are loaded. The
plugin intentionally uses the local stdio server rather than Coder's remote
HTTP MCP endpoint, so the deployment does not need the HTTP MCP or OAuth2
experiments enabled.

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
