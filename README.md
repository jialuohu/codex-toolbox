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
   Before Codex operations, it safely removes only the seven known duplicate
   user-skill links that still point into `.cc-switch/skills`, preserves their
   targets and `hatch-pet`, ensures a working `rg` through Homebrew when needed,
   and resolves Codex from `PATH`, the current ChatGPT app, then the legacy
   Codex app. Inspect those prerequisites without changing local state with:

   ```bash
   python3 scripts/setup-codex-prerequisites.py legacy-skills --check
   python3 scripts/setup-codex-prerequisites.py ensure-rg --check
   python3 scripts/setup-codex-prerequisites.py resolve-codex
   ```

   Because the toolbox marketplace is Git-backed, users can refresh it later
   from the Codex Desktop app by clicking **Upgrade**, or from the CLI:

   ```bash
   codex plugin marketplace upgrade jialuo-codex-toolbox
   ```

   After any marketplace upgrade that changes `docmost-tools` or
   `apple-mail-tools`, rerun the full setup so shared runtimes are rebuilt from
   the exact active plugin sources and smoke-checked before opening a fresh
   Codex task:

   ```bash
   scripts/setup-codex-toolbox.sh
   ```

   Running the full toolbox setup performs those runtime gates automatically.

   For local plugin development before changes are pushed to GitHub, register
   the checkout directly instead:

   ```bash
   CODEX_TOOLBOX_MARKETPLACE_MODE=local scripts/setup-codex-toolbox.sh
   ```

5. Run MCP login or connector setup commands for any other services that need
   local authentication.

6. Start a fresh Codex session so the installed global `AGENTS.md`, plugins, and
   MCP servers are loaded from the beginning of the run.

## Diagram Tools

The default `diagram-tools` plugin makes `$pretty-mermaid` the default renderer
whenever Mermaid is the chosen visual format. It preserves editable `.mmd`
source and exports self-contained SVG, real PNG through Resvg, or plain
ASCII/Unicode. Graphical surfaces default to SVG, while terminals use ASCII;
automatic artifacts go in a task-scoped temporary directory when no destination
is requested. Native inline Mermaid is reserved for explicit requests or a
disclosed runtime or syntax fallback. Use `$paper-figure-workflow` for
publication pipelines, and `$drawio` for explicit native draw.io work.

The renderer uses a contract-gated rolling runtime under
`${CODEX_HOME:-$HOME/.codex}/runtime/diagram-tools`. Toolbox setup resolves the
newest stable `beautiful-mermaid` release, installs it into an isolated
candidate with lifecycle scripts disabled, verifies package integrity and
production audit results, renders the compatibility fixtures, and promotes it
atomically. A rejected release cannot replace the working runtime. Fresh
installations fall back to the lockfile-approved release; Dependabot proposes
updates to that fallback separately.

Normal rendering is offline. Check, update, or roll back the runtime with:

```bash
scripts/setup-diagram-tools.sh --check
scripts/setup-diagram-tools.sh --update
scripts/setup-diagram-tools.sh --update --strict
scripts/setup-diagram-tools.sh --rollback
```

Toolbox setup installs the stable CLI in `CODEX_LOCAL_BIN_DIR`, defaulting to
`~/.local/bin`:

```bash
pretty-mermaid themes
pretty-mermaid capabilities --json
pretty-mermaid render --input diagram.mmd --output diagram.svg --format svg --theme github-light
pretty-mermaid render --input diagram.mmd --output diagram.png --format png --theme tokyo-night --scale 2
pretty-mermaid batch --input-dir diagrams --output-dir rendered --format svg --workers 4
```

Beautiful Mermaid intentionally supports a subset of Mermaid syntax. The
active capability report names the tested diagram families and available
themes; unsupported syntax fails without rewriting the `.mmd` source.

## Draw.io Tools

The default `drawio-tools` plugin provides `$drawio` and the `drawio` MCP
server for explicit draw.io or diagrams.net requests, editable `.drawio`
source, multi-page inspection and editing, specialized shape libraries,
browser editing, and optional Desktop exports. Pretty Mermaid remains the
default for ordinary Mermaid diagrams. `$paper-figure-workflow` remains the
owner of publication pipelines and delegates native draw.io execution here.

The MCP exposes exactly `open_drawio_xml`, `open_drawio_csv`,
`open_drawio_mermaid`, `search_shapes`, `list_pages`, `get_page`, and
`set_page`. Read/open tools are auto-approved; `set_page` prompts because it
mutates a local file. `DRAWIO_BASE_URL` may select a trusted self-hosted editor
instead of the default `https://app.diagrams.net/`.

Toolbox setup installs exact `@drawio/mcp@1.4.0` dependencies under
`${CODEX_HOME:-$HOME/.codex}/runtime/drawio-tools/active` with lifecycle
scripts disabled. It audits the production tree and installs a SHA-256-checked
shape index pinned to an upstream commit before atomic promotion. Normal MCP
startup validates this receipt and uses no `npm`, `npx`, or network access.

Use the focused setup helper directly with:

```bash
scripts/setup-drawio-tools.sh --check
scripts/setup-drawio-tools.sh --install
scripts/setup-drawio-tools.sh --install --with-desktop
```

draw.io Desktop is opt-in. The full toolbox setup installs and smoke-tests it
only when requested; on macOS this may run `brew install --cask drawio`:

```bash
CODEX_TOOLBOX_INSTALL_DRAWIO_DESKTOP=1 scripts/setup-codex-toolbox.sh
```

Set `DRAWIO_DESKTOP_BIN` to reuse another Desktop executable. Managed PNG,
SVG, and PDF exports retain the `.drawio` source and run Desktop with
`-x -f FORMAT -e -b 10 -o OUTPUT INPUT`, embedding diagram XML. If Desktop is
unavailable, the workflow leaves the editable `.drawio` source and exact local
export command; it does not silently use cloud rasterization. With no requested
destination, artifacts go in a task-scoped temporary directory.

## Apple Mail Tools

The default macOS-only `apple-mail-tools` plugin exposes every enabled Mail.app
account, including Exchange accounts whose reported type is `unknown`, through
the local `apple_mail` MCP. It uses Mail's supported AppleScript dictionary; it
does not use Microsoft Graph, IMAP, SMTP, Keychain credentials, Accessibility
automation, Mail's private database, remote HTML, or a programmatic send path.

The pinned Python 3.12/FastMCP runtime is installed at
`${CODEX_HOME:-$HOME/.codex}/runtime/apple-mail-tools`. Toolbox setup resolves
the exact installed plugin source from `codex mcp get apple_mail --json`, checks
that it is beneath the marketplace cache, then installs and fingerprints that
copy. Normal MCP startup runs the verified environment without dependency
synchronization or network access.

Use the focused helper with:

```bash
scripts/setup-apple-mail-tools.sh --install
scripts/setup-apple-mail-tools.sh --check
scripts/setup-apple-mail-tools.sh --status
scripts/setup-apple-mail-tools.sh --init-config
```

The first status or MCP call may trigger macOS Automation permission. Allow the
calling Codex process or `osascript` to control Mail under **System Settings →
Privacy & Security → Automation**. The health check reads no messages.

Private configuration, HMAC handles, intents, attachment leases, and the
SQLite FTS5 history index live below
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/apple-mail-tools`.
Directories use mode `700`; configuration, keys, SQLite files, and receipts use
mode `600`. Full-history indexing stores normalized plain text and metadata, not
raw MIME, HTML, or attachment bytes. It excludes `Junk`, `Junk Email`, `Spam`,
`Trash`, `Deleted Items`, and `Deleted Messages` by default. Edit the private
`config.json` to override mailbox-name exclusions. Index creation is blocked
when FileVault is off or indeterminate unless that file explicitly sets
`allow_unencrypted_index` to `true`.

Index commits process at most 500 message locations or ten minutes, checkpoint
progress, and resume after another prepare/commit pair. Search results always
report freshness, exclusions, and completeness; a live read revalidates every
indexed location before it can be used for a mutation. `apple_mail_erase_index`
is the explicit prompt-gated cleanup path.
Plugin uninstall preserves private index data.

Incoming attachments are prompt-gated, limited to 25 MiB, stored in private
24-hour leases, and removed with `apple_mail_release_attachment`. Outgoing
drafts accept up to ten attachments, 25 MiB each and 50 MiB total, from the home
folder. A non-overridable denylist rejects hidden paths, `~/Library`, Codex
secrets, SSH/GPG/keychain material, credential-like files, private keys,
symlinks, and non-regular files.

Message changes use a preview and a ten-minute single-use commit token. Batches
are limited to 20 exact signed handles, prevalidate every target, act one message
at a time, and stop on the first mismatch. Trash is a recoverable move to a
configured Trash mailbox; permanent deletion and empty-trash tools do not
exist. New, reply, reply-all, and forward operations create, save, and visibly
open drafts. Inspect the draft and click **Send** in Mail; the MCP cannot send
mail.

Mail content is untrusted input. It cannot authorize writes, select tools, run
shell commands, open links, or change permissions. The owning `$apple-mail`
skill enforces exact previews and keeps Gmail and Outlook connector workflows
separate.

## Docmost Tools

The default `docmost-tools` plugin runs a local browser-authenticated MCP adapter
for a private Docmost instance. It reads its per-device settings only from
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/docmost.env`; create
that file with mode `600`. Its isolated browser profile is stored under the
same secrets directory with mode `700`. Never commit the environment file,
browser profile, session cookie, or workspace content.

Setup requires a working Codex CLI plus `uv` and `python3` on `PATH`; the locked
server project requires Python 3.12, which `uv` must be able to resolve. These
are runtime prerequisites, not vendored portability fallbacks.

Locked Python environments are immutable, source-addressed generations under
`${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools-generations/envs/<source-sha256>`.
Setup builds directly at the final hash path and writes the verified source stamp
last; a partial generation therefore remains unreachable and can be repaired on
the next install. The checked-in MCP bootstrap acquires the backward-compatible
session lock and that generation's lock, validates the stamp, and directly
executes `bin/docmost-mcp`. Startup retains no `uv` parent and never creates an
environment or downloads dependencies. The legacy runtime at
`${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools` is retained for rollback and
is never modified or deleted automatically in v0.5.

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

`docmost_prepare_workspace_snapshot` is the bulk read boundary used by the Lab
Wiki workflow. It traverses selected spaces and every descendant page, retries
page revision races, assembles long Markdown bodies, and writes versioned JSONL
with mode `600` beneath `CODEX_SECRETS_DIR`. The MCP result contains only an
opaque cleanup token, local path, SHA-256, schema/workspace identifiers, and
counts; bodies never enter the tool result. Authentication failures, incomplete
pagination or hierarchy traversal, duplicate/cyclic page identities, repeated
revision races, and safety-cap overflows return no receipt. Consumers must call
`docmost_release_workspace_snapshot` in a `finally` path. This snapshot route
never reads comments or attachment bodies and cannot call Docmost write routes.

The regular toolbox setup installs the matching runtime generation and Chromium, then
runs a headless `current-user` and `list-spaces` smoke check before it refreshes
the marketplace or plugins. After refresh, setup reads
`codex mcp get docmost --json`, validates the absolute installed MCP cwd beneath
`${CODEX_HOME:-$HOME/.codex}/plugins/cache/jialuo-codex-toolbox/docmost-tools/<version>`,
checks that copy's `.mcp.json` and server package, and rebuilds the runtime from
that exact installed server. Marketplace `source.path` is not treated as the
installed distribution. When the profile is not authenticated, setup opens the
interactive browser login and reruns the smoke check; any configuration, SSO,
or smoke failure stops the relevant setup phase.

Use the helper directly when troubleshooting the isolated local auth profile:

```bash
scripts/setup-docmost-tools.sh --check
scripts/setup-docmost-tools.sh --install
scripts/setup-docmost-tools.sh --login
scripts/setup-docmost-tools.sh --status
scripts/setup-docmost-tools.sh --logout
scripts/setup-docmost-tools.sh --prune
```

Installation serializes through a setup-only lock and takes an exclusive lock
only on the target generation. It does not wait for the lifetime session locks
held by old or current MCP processes, so an upgrade can be staged while tasks
continue using earlier generations. Concurrent setup reports a busy exit rather
than modifying shared assets. `--prune` never contacts Docmost: it removes only
unlocked, unreferenced generation directories while preserving the current
source, every fingerprint referenced by an installed plugin copy, active
generations, and the legacy runtime.

After an upgraded plugin and generation are installed, wait until no Docmost
tool call or workspace snapshot is active, then use Codex **Settings → MCP servers → Restart**.
Restarting is host-driven and must happen while Docmost is idle,
because closing stdio cancels an in-flight call. Old task-owned processes may
remain on their old generation safely. The 900-second snapshot timeout, tool
schemas, and approval policy are unchanged.

Before login or logout, close every active Codex task using Docmost so the shared
session locks and in-memory cookies are released. Login and logout retain the
legacy global lock filename, so they remain exclusive against both old and new
MCP processes. An MCP `AUTH_REQUIRED` result gives this
recovery command:

```bash
CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" "$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login
```

After login or logout, start a fresh task or reconnect Docmost so the MCP
process loads the new authentication state. Graceful SIGTERM and normal stdio
EOF both close HTTP clients and release temporary downloads and snapshots;
SIGKILL or system failure cannot guarantee process-level cleanup.

Docmost content is untrusted input. Read tools can be used automatically.
`docmost_download_attachment` stages only an authorized PDF or UTF-8 text file in a
private bounded temporary directory and returns a checksum receipt; callers
must invoke `docmost_release_attachment_download` in a `finally` path. The MCP asks
before `docmost_create_page`, `docmost_update_page_title`,
`docmost_edit_page_text`, or `docmost_create_comment`. The text-edit tool replaces one
unique literal occurrence inside a single ProseMirror text node. It preserves marks, IDs,
comments, and rich sibling blocks by submitting JSON rather than rebuilding Markdown.
Its required `expected_updated_at` check is non-atomic; formatting and structural edits are
outside this tool's contract.

## Read-only Docmost Lab Wiki

`$docmost-lab-wiki` maintains a separate `Research/Lab Wiki` in the configured
Obsidian vault. It never changes the existing `Research/LLM Wiki`. A sync asks
Docmost only for a complete receipt-only workspace snapshot, passes the private
JSONL path directly to the locked local runtime, and releases the snapshot in a
`finally` path. No Docmost comment, attachment body, or write tool is used.

The vault mirror uses stable
`Sources/Docmost/<space-id>/<page-id>.md` paths, readable per-space maps,
hash-protected generated regions, and preserved personal-note regions. Raw HTML
and automatic media embeds are inert. Secret-like pages become metadata-only
quarantine stubs and are excluded from search; pages missing from a complete
scan become bodyless tombstones. Incomplete scans change nothing, and local
managed-region conflicts warn without overwrite.

The private index remains beneath `CODEX_SECRETS_DIR`. It combines SQLite FTS5
with exact cosine search over local FastEmbed 0.8.0 vectors, reusing unchanged
chunks. Setup pins `BAAI/bge-small-en-v1.5` to the quantized 384-dimensional,
512-token model at revision
`c32e6154d1bb7a0e47c5e745fd895e7700f44385` and verifies the ONNX SHA-256 before
atomic promotion. Normal operation opens that exact local path with network
access disabled.

Install and prewarm the isolated Python 3.12 runtime, then initialize the new
folder:

```bash
scripts/setup-docmost-lab-wiki.sh --install
plugins/research-tools/scripts/docmost-lab-wiki.sh init
```

The setup helper detects the sole registered Obsidian vault unless
`DOCMOST_LAB_WIKI_VAULT` is explicitly set, then creates a mode-`600`
`${CODEX_SECRETS_DIR}/docmost-lab-wiki.env`. It does not perform a Docmost sync.
Use the skill for the receipt lifecycle:

```text
$docmost-lab-wiki sync
$docmost-lab-wiki query <question>
$docmost-lab-wiki distill <scope>
$docmost-lab-wiki status
$docmost-lab-wiki lint
$docmost-lab-wiki rebuild-index
```

Queries return at most 12 untrusted excerpts, two per page, and warn after 36
hours without triggering an implicit refresh. Answers and durable synthesis
cite both the local Obsidian source and canonical Docmost URL. Source changes
make synthesis lint-stale rather than rewriting it automatically. Warning-level
syncs exit nonzero so a scheduled refresh can notify only when attention is
required.

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

## Stevens Presentation Tools

The default `stevens-presentation-tools` plugin provides reusable 16:9 Stevens
PowerPoint templates, a compact theme gallery, and a local-PPTX-first workflow
for native Google Slides delivery. `$stevens-slides` selects White unless a
theme is named; `$stevens-slides-white` and `$stevens-slides-dark` select a
theme explicitly.

| Theme | Intended use | Core treatment |
|---|---|---|
| White | General presentations and research updates | White canvas, Dark Gray text, Stevens Red accents |
| Dark | Technical and systems talks | Dark Gray canvas, white text, gold/orange/blue data accents |

Both themes preserve the same 17 named layouts and editable exemplars. The
bundled manifest, brand references, checksums, fonts, official identifiers,
source template, and validation script form the reusable authoring contract.
Generated decks start from a bundled PPTX, preserve inherited layouts, add
`[Sources]` speaker notes, verify locally, and then use native Google Slides
conversion when Slides is the requested destination.

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

Add each account separately with a non-secret alias. During each browser login,
select the matching account and approve the displayed `gmail.modify` permission
plus the three identity scopes; abort if any other scope is shown:

```bash
scripts/setup-gws.sh --add-account account-one@example.com --alias account-one
scripts/setup-gws.sh --add-account account-two@example.net --alias account-two
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

Reauthenticate an existing profile, including one with an expired or revoked
token, without changing its expected identity, then check it again:

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

## Private Paper Review Sync

Use the on-demand workflow when the advisor may have appended assignments or
when a review record needs repair:

```text
$paper-review-sync check
$paper-review-sync sync
$paper-review-sync repair <paper-number>
```

`check` is strictly read-only. `sync` and `repair` reconcile only active rows
assigned exactly to Jialuo Hu with blank Review Comments. The orchestrator uses
`$paper-review-library-intake` to store private PDFs under
`Research/PaperReview`, `$paper-review-page` to create exact-Paper-Number pages
under `Jialuo Hu/Paper Review`, and one Todoist surface for tasks in
`Paper Reviews/Assigned` with `paper-review` and `deep-work` labels. Todoist
links use the Zotero parent key for `select` and PDF attachment key for
`open-pdf`.

Private submissions, titles, forms, and review text never go to Paper Search,
web search, or Firecrawl. Same-venue pages supply structure only; substantive
peer review content is discarded. Partial runs keep the Todoist assignment and
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

## Firecrawl Routing and Budget

The default `web-data-tools` plugin exposes a metered Firecrawl surface for
public HTML content. It supports only bounded `firecrawl_search`, bounded
Markdown-only `firecrawl_scrape`, and the read-only
`firecrawl_budget_status` tool. Search reserves 2 credits per request, matching
the current price for up to ten results, and basic Scrape reserves 1 credit per
page ([Firecrawl pricing](https://www.firecrawl.dev/pricing)). The proxy rejects
Crawl, Map, Monitor, Agent, Interact, Parse, Extract, structured JSON, actions,
profiles, enhanced or automatic proxies, unknown tools, and other unbounded
options.

The implicitly invocable `$community-research` skill owns requests that seek
public community or forum discussions, user reports, sentiment, or community
troubleshooting. Firecrawl is mandatory within that bounded workflow. A known
thread URL goes directly to Scrape. Discovery uses one web source with
highlights and at most five results, then scrapes no more than two selected
threads when the highlights are insufficient. Built-in Codex web search remains
the corroboration route for official or canonical sources.

The proxy enforces a fixed 900-credit cap per authenticated Firecrawl billing
period with no environment override. It reconciles local reservations against
the team's current usage through Firecrawl's read-only
[credit-usage endpoint](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage),
so traffic from another client can reduce the allowance. Reservations are
persisted before forwarding and are not refunded after a failed request.
Budget, state, lock, account-credit, period-rollover, API, or
parameter-validation failures fail closed before the upstream MCP is called.
Failures use the stable codes `FIRECRAWL_BUDGET_EXHAUSTED`,
`FIRECRAWL_BUDGET_UNAVAILABLE`, and `FIRECRAWL_REQUEST_NOT_BOUNDED`. When that
blocks a required community pass, use built-in web search and include a
degraded-coverage notice. Never bypass the cap through another endpoint,
another client, or the separate connected Firecrawl app.

Budget state is stored atomically with private permissions at
`${CODEX_HOME:-~/.codex}/state/firecrawl-budget.json`. Inspect the read-only
status without spending Search or Scrape credits:

```bash
plugins/web-data-tools/scripts/run-firecrawl-mcp.sh status
```

The status reports the cap, counted credits, remaining toolbox allowance,
account remaining credits, billing-period dates, and the allowed tool names. It
never reports Firecrawl credentials. Firecrawl remains prohibited for private
local files, saved Zotero content, Obsidian vault content, and other private
workspace data unless the user explicitly asks to send that data to Firecrawl.

## Execution Routing

For large decomposable projects, start naturally in Plan mode. For example:

```text
Build a polished business website for a small AI consulting agency.
```

The global instructions let Codex plan first and then select the narrowest
execution lane. Tiny changes stay in the main task. Independent, testable work
can run through native Codex subagents. Other implementation work uses normal
Codex behavior. Use OpenSpec when durable requirements, acceptance criteria, or
spec governance should be settled before implementation.

## Deep Planning

Plan Mode uses `$deep-planning` when the user explicitly requests adversarial
planning or when work is architectural or high-risk. Ordinary multi-step work
uses normal Codex planning. The skill is a read-only critique gate: it gathers
observed facts, states assumptions and material unknowns, drafts the strongest
plan, challenges product value, architecture, implementation risk, edge cases,
tests, rollout, and scope, then chooses Codex-only, native Codex subagents, or
OpenSpec routing. It does not create artifacts, dispatch workers, or perform
verification after code changes.

## Explain Clearly

Use `$explain-clearly` when a concept, why/how question, comparison, or code
walkthrough needs a clear mental model and concrete example. It leads with the
direct answer, uses one accurate example by default, and adds only the mechanism
or caveat needed to avoid a misleading simplification. It also chooses the
smallest useful format: prose for simple results, a table for repeated
comparisons, `$pretty-mermaid` by default for static relationships, and bundled
Visualize for spatial or interactive explanations. Pretty Mermaid saves `.mmd`
source and renders SVG or terminal ASCII; native inline Mermaid is an explicit
choice or disclosed renderer fallback. Exact data and legal state are validated
before rendering; ambiguous
chess positions are reported rather than invented, and CLI or IDE tasks receive
text, table, Mermaid, ASCII, or coordinate fallbacks.

Example prompt:

```text
Use $explain-clearly to explain JavaScript closures with a simple mental model and one concrete example.
```

## Ship Toolbox

Use `$ship-toolbox` explicitly after completing a task-scoped plugin or skill
change. It requires synchronized `main`, runs repository and affected-plugin
gates, stages only explicit paths and hunks, commits and pushes without a second
confirmation, verifies the remote SHA and relevant CI, then refreshes and
checks the Git-backed local marketplace. It does not create branches, pull
requests, tags, releases, empty commits, or history rewrites, and it preserves
unrelated worktree changes.

Example prompt:

```text
Use $ship-toolbox to validate, commit, push, refresh, and verify the current toolbox changes.
```

## Paper Figure Workflow

Use `$paper-figure-workflow` when a research repo needs reproducible paper
figures. The skill guides Codex to inspect the repo first, keep draw.io source
diagrams editable through `$drawio`, generate Matplotlib and SciencePlots result
plots from repo data, export SVG/PDF figures, use Inkscape only for conversion
or light cleanup, and add a command such as `make figures`.

Example prompt:

```text
Use $paper-figure-workflow to set up clean, reproducible figures for this AI/systems paper repo.
```

## AGENTS.md Sync

The canonical global instructions live at `config/codex/AGENTS.global.md` and
stay within an 8 KiB budget. Repository-specific development and shipping rules
live in the root `AGENTS.md`; together they stay below 16 KiB so nested project
instructions retain headroom. Detailed workflow, quota, and validation
contracts belong to their owning skills rather than the always-loaded global
file.

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
