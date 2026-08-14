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
```

Mail remains the only send surface. This package has no programmatic send or
permanent-delete operation.
