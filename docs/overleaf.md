# Overleaf

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Overleaf Tools](#overleaf-tools)

## Overleaf Tools

`overleaf-tools` is an opt-in, unofficial MCP for projects whose Overleaf account has Git access.
It keeps configuration, Git tokens, mirrors, locks, and temporary worktrees beneath
`$CODEX_SECRETS_DIR/overleaf-tools` when that variable is set, otherwise beneath
`${CODEX_HOME:-$HOME/.codex}/secrets/overleaf-tools`; tokens never appear in argv, remote URLs, Git
configuration, logs, or source control. The portable launcher uses the checked-in Python 3.12 lock
through `uv`.

Configure it from this checkout without placing a token in shell history:

```bash
uv run --frozen --project plugins/overleaf-tools/server overleaf-config init
uv run --frozen --project plugins/overleaf-tools/server overleaf-config set-token default
uv run --frozen --project plugins/overleaf-tools/server overleaf-config add-project \
  weekly-report PROJECT_ID --token default --display-name "Weekly Report"
uv run --frozen --project plugins/overleaf-tools/server overleaf-config remove-project sandbox
uv run --frozen --project plugins/overleaf-tools/server overleaf-config status
```

The MCP detects the Overleaf default branch and permits only `main` or legacy `master`. Reads
return exact remote revisions and blob SHAs. Every write is prompt-gated and requires those fresh
preconditions, stages only the named path or paths, creates one fixed-author commit, pushes without
force, and verifies the remote head. An ambiguous push
returns `OUTCOME_UNKNOWN`; never retry it before checking the candidate with
`overleaf_reconcile_commit`. File moves can displace Overleaf comments and Track Changes, so do not
mix Git writes with active collaboration markup. Compilation, settings, collaborators, project
renames, branches, tags, symlinks, submodules, and Git LFS are outside v0.1.

Development and local tests do not require a paid Overleaf plan. Use a plan or trial with Git only
for the final live smoke test; first confirm that the feature is still included in the current
Overleaf offering.
