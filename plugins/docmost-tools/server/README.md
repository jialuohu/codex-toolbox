# docmost-tools server

This package provides guarded browser-session HTTP access and stable MCP result contracts. The
v0.95 page URL compatibility path derives display slugs from title plus the authoritative `slugId`;
search uses opaque versioned cursors.

The toolbox setup requires `uv` and `python3` on `PATH`; this locked project requires Python 3.12.
After plugin refresh, setup builds this package from the absolute installed MCP cwd reported by
`codex mcp get docmost --json`, not from the marketplace source checkout.

The eight ordinary reads tolerate additive response fields. The private attachment download/release
pair validates page association, accepts only bounded PDF or UTF-8 text files, stages mode-`0600`
snapshots under a mode-`0700` temporary root, and removes them by opaque token or server shutdown.
The three prompt-gated writes require an explicit
`DOCMOST_WRITE_PROFILE=v0_95`: page creation uses Markdown import, optional nesting is a separate
non-retried move, title changes use a disclosed non-atomic timestamp precondition, and comments use
a conservative Markdown-to-Tiptap converter. Ambiguous write outcomes are never retried. If a
nesting move has an ambiguous outcome, the created page is returned with
`placement_status="unknown"` and an explicit read-before-retry warning.

`docmost-smoke` is a setup-only, bounded headless check. It obtains the existing isolated browser
session once, verifies `current_user`, and lists one page of spaces. It does not expose the cookie,
continuously synchronize, or monitor the workspace. Before login or logout, close the active Codex
task so its lifetime shared runtime lock and in-memory cookie are released. Then run
`CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" "$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login`
or the corresponding `--logout` command. Start a fresh task or reconnect Docmost afterward so the
MCP process loads the new authentication state. Only login opens a headed browser.

The Docker contract is opt-in and never targets a configured hosted instance:

```sh
DOCMOST_RUN_CONTRACT_TESTS=1 uv run --frozen pytest tests/contract/test_v095_contract.py -vv
```

It launches `docmost/docmost:0.95.0` with isolated PostgreSQL and Redis services under a generated
Compose project name, creates an ephemeral admin through `/api/auth/setup`, and always tears down
that exact project's containers and volumes.
