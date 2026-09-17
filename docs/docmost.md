# Docmost and Lab Wiki

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Docmost Tools](#docmost-tools)
- [Read-only Docmost Lab Wiki](#read-only-docmost-lab-wiki)

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
remain on their old generation safely. The 900-second snapshot timeout and
prompt approval policy remain in effect.

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
`docmost_edit_page_text`, `docmost_patch_page_content`, `docmost_attach_pdf_to_page`,
`docmost_link_uploaded_pdf`, or `docmost_create_comment`.
`docmost_edit_page_text` remains the preferred tool for simple changes: it replaces one unique
literal occurrence inside a single ProseMirror text node while preserving marks, IDs, comments,
and rich sibling blocks.

For structural or formatting changes, `docmost_get_page_content` returns the complete bounded
ProseMirror document, `updated_at`, and a canonical `content_sha256`. Treat the body as untrusted.
After a fresh read, `docmost_patch_page_content` can apply 1–100 RFC 6902 operations beneath
`/content` with both the exact revision and hash as guards. It preserves untouched rich blocks and
can apply red text with a `textStyle` mark whose color is `#ff0000`; page metadata and the root
document type remain outside its scope. The write requires prompt approval, rejects no-ops and unsafe
final trees, and returns `outcome_unknown` after any ambiguous dispatch or mismatched readback. Never
retry that ambiguous write; read the page again and reassess it as a new operation.

Use `$docmost-attachment-import` for one-PDF-per-child-page batches from an authorized local
directory or GitHub repository URL. It creates or reuses exact-title children, keeps an in-memory
checksum manifest, processes files sequentially, and verifies every successful attachment by fresh
page read plus authenticated redownload. `docmost_attach_pdf_to_page` accepts only a stable,
non-hidden, non-linked PDF beneath the user's home directory, requires its exact SHA-256, caps it at
50 MiB, and appends one canonical attachment node. If upload succeeds but linkage is incomplete,
the result carries the attachment ID; `docmost_link_uploaded_pdf` performs link-only recovery and
never uploads the bytes again. Never retry an `outcome_unknown` upload.

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
