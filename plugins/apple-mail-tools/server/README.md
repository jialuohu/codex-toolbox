# apple-mail-tools server

This pinned Python 3.12 FastMCP server controls Mail.app through one fixed
AppleScriptObjC bridge. Tool input is written to private JSON request files;
input is never interpolated into script source or shell commands.

Runtime state lives under
`${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}/apple-mail-tools`.
It includes a mode-0600 configuration, signing key, intent store, private FTS5
index, and expiring attachment leases. Message content is never logged.

Install or inspect the isolated runtime from the repository root:

```bash
scripts/setup-apple-mail-tools.sh --install
scripts/setup-apple-mail-tools.sh --check
scripts/setup-apple-mail-tools.sh --status
scripts/setup-apple-mail-tools.sh --init-config
scripts/setup-apple-mail-tools.sh --prune
```

Runtimes are immutable source-fingerprinted generations below
`${CODEX_HOME:-$HOME/.codex}/runtime/apple-mail-tools-generations/envs`.
Installation creates the new generation without waiting for the legacy fixed
runtime or unrelated active generations. Existing MCP processes retain their
locked generation until they exit; new processes select the newly installed
generation. The legacy `${CODEX_HOME:-$HOME/.codex}/runtime/apple-mail-tools`
environment is never mutated or removed by normal setup. `--prune` is a manual
operation that removes only unlocked, unreferenced generations.

Mail remains the only send surface. This package has no programmatic send or
permanent-delete operation.
