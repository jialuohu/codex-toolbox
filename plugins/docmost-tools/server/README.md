# docmost-tools server

This package provides guarded browser-session HTTP access and stable MCP result contracts. The
v0.95 page URL compatibility path derives display slugs from title plus the authoritative `slugId`;
search uses opaque versioned cursors.

The toolbox setup requires `uv` and `python3` on `PATH`; this locked project requires Python 3.12.
After plugin refresh, setup builds this package from the absolute installed MCP cwd reported by
`codex mcp get docmost --json`, not from the marketplace source checkout.

Each source fingerprint has an immutable environment at
`${CODEX_HOME}/runtime/docmost-tools-generations/envs/<source-sha256>`. Setup builds at that final
path, publishes the source stamp last, and does not wait for active MCP session locks. The checked-in
`scripts/docmost-mcp` bootstrap holds the backward-compatible shared session lock plus a shared lock
for its exact generation, validates the stamp, then directly execs the environment entrypoint without
`uv run`. The fixed `${CODEX_HOME}/runtime/docmost-tools` environment is a retained v0.5 rollback and
is not removed by setup or `--prune`.

`scripts/setup-docmost-tools.sh --prune` is local-only and preserves the current source fingerprint,
installed-plugin fingerprints, and every generation whose lock is busy. Runtime upgrades do not alter
the 15 MCP tool names, prompt-gated writes, read-only snapshot protocol, or 900-second tool timeout.

The eight ordinary reads tolerate additive response fields. The private attachment download/release
pair validates page association, accepts only bounded PDF or UTF-8 text files, stages mode-`0600`
snapshots under a mode-`0700` temporary root, and removes them by opaque token or server shutdown.
The workspace snapshot/release pair traverses every selected page through a read-only protocol,
assembles long Markdown pages consistently, retries revision races twice, and emits versioned JSONL
beneath `CODEX_SECRETS_DIR`. Only a receipt containing an opaque token, private path, checksum,
schema, workspace ID, and counts crosses the MCP boundary; incomplete scans create no receipt.
The three prompt-gated writes require an explicit
`DOCMOST_WRITE_PROFILE=v0_95`: page creation uses Markdown import, optional nesting is a separate
non-retried move, title changes use a disclosed non-atomic timestamp precondition, and comments use
a conservative Markdown-to-Tiptap converter. Ambiguous write outcomes are never retried. If a
nesting move has an ambiguous outcome, the created page is returned with
`placement_status="unknown"` and an explicit read-before-retry warning.

`docmost-smoke` is a setup-only, bounded headless check. It obtains the existing isolated browser
session once, verifies `current_user`, and lists one page of spaces. It does not expose the cookie,
continuously synchronize, or monitor the workspace. Before login or logout, close every active Codex
task using Docmost so its lifetime shared session lock and in-memory cookie are released. Then run
`CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" "$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login`
or the corresponding `--logout` command. Start a fresh task or reconnect Docmost afterward so the
MCP process loads the new authentication state. For a runtime upgrade, wait until Docmost is idle and
use Codex **Settings → MCP servers → Restart**; stdio closure cancels in-flight calls. Graceful SIGTERM
and EOF run the same HTTP-client and temporary-snapshot cleanup path. Only login opens a headed browser.

The Docker contract is opt-in and never targets a configured hosted instance:

```sh
DOCMOST_RUN_CONTRACT_TESTS=1 uv run --frozen pytest tests/contract/test_v095_contract.py -vv
```

It launches `docmost/docmost:0.95.0` with isolated PostgreSQL and Redis services under a generated
Compose project name, creates an ephemeral admin through `/api/auth/setup`, and always tears down
that exact project's containers and volumes.
