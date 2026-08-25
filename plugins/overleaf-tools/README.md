# Overleaf Tools (Unofficial)

`overleaf-tools` is an opt-in Codex plugin for guarded project-file operations through Overleaf's
Git integration. It is not affiliated with or endorsed by Overleaf.

The MCP exposes seven read tools and five prompt-gated mutation tools. Every mutation detects and
fetches the Overleaf default branch (`main` or legacy `master`), verifies an exact project revision
and target blob, creates at most one commit in a private ephemeral worktree, and pushes without
force. An ambiguous push returns
`OUTCOME_UNKNOWN`; callers must reconcile its candidate commit and must not retry blindly.

Configuration and bare Git mirrors live only under `$CODEX_SECRETS_DIR/overleaf-tools` when that
variable is set, otherwise under `${CODEX_HOME:-$HOME/.codex}/secrets/overleaf-tools`. Git tokens
are read by the bundled askpass helper from a mode-`600` private file (or a
current-user/SYSTEM-only Windows ACL), never from argv, a credentialed URL, repository
configuration, or source control.

From this repository checkout, configure the plugin with:

```bash
uv run --frozen --project plugins/overleaf-tools/server overleaf-config init
uv run --frozen --project plugins/overleaf-tools/server overleaf-config set-token default
uv run --frozen --project plugins/overleaf-tools/server overleaf-config add-project \
  weekly-report PROJECT_ID --token default --display-name "Weekly Report"
uv run --frozen --project plugins/overleaf-tools/server overleaf-config remove-project sandbox
uv run --frozen --project plugins/overleaf-tools/server overleaf-config add-import-root \
  /absolute/path/to/imports
uv run --frozen --project plugins/overleaf-tools/server overleaf-config status
```

`set-token` reads hidden input. Do not put the token on the command line. The configuration schema
is documented in [server/README.md](server/README.md). `remove-project` atomically removes only the
named alias; it retains shared token files, allowed import roots, and private Git caches.

Overleaf currently restricts Git integration to plans that include the feature. Development and
local tests do not require an Overleaf subscription; a live account is needed only for the final
remote smoke test.
