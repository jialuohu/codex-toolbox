# Overleaf Tools server

This Python 3.12 FastMCP server uses one secrets-backed project alias per Overleaf project. It
detects the remote default branch and permits only `refs/heads/main` or legacy
`refs/heads/master`; other branches, tags, submodules, symlinks, and Git LFS are outside the
contract.

## Configuration

The server uses `$CODEX_SECRETS_DIR/overleaf-tools` when `CODEX_SECRETS_DIR` is set. Otherwise it
uses `${CODEX_HOME:-$HOME/.codex}/secrets/overleaf-tools`. Its configuration file is `config.json`
beneath that private root:

```json
{
  "version": 1,
  "projects": {
    "weekly-report": {
      "projectId": "PROJECT_ID",
      "tokenFile": "tokens/default.token",
      "displayName": "Weekly Report"
    }
  },
  "allowedImportRoots": [
    "/absolute/path/to/imports"
  ]
}
```

Use `overleaf-config`; do not hand-write token files or pass token values in argv. Multiple project
aliases may reference the same private token file. On POSIX, directories must be owned by the
current user with no group/world access and files must be mode `600`. On Windows, created paths use
an inheritance-disabled ACL restricted to the current account and SYSTEM. Link-backed secret paths
are rejected on both platforms.

Remove a retired alias with `overleaf-config remove-project ALIAS`. This atomically updates only
`config.json`; shared token files, allowed import roots, and private Git caches are retained.

## Git and write semantics

The mirror remote is always uncredentialed: `https://git.overleaf.com/PROJECT_ID`. Network Git gets
the token only through `GIT_ASKPASS`; global/system Git configuration and credential helpers are
disabled. Every call fetches current remote state under a per-project file lock.

Text reads are UTF-8 and capped at 2 MiB. Imports are capped at 50 MiB, require an allowed canonical
root and exact SHA-256, and apply the text limit to editable text extensions. New files are rejected
at 2,000 project files, and project status warns above 100 MiB. All paths are canonical relative
POSIX paths and exclude traversal, drive syntax, `.git`, links, submodules, and LFS pointers.

Each write requires the current revision, target blob (or literal `absent`), and a one-line commit
message. Push targets only the detected `HEAD:refs/heads/main` or
`HEAD:refs/heads/master`, never force. The response reports `committed`, `stale`, or `unknown`
with the applicable revisions, commit, paths, and hashes.

## Development

```bash
uv sync --frozen --project plugins/overleaf-tools/server
uv run --frozen --project plugins/overleaf-tools/server pytest
uv run --frozen --project plugins/overleaf-tools/server ruff check
uv run --frozen --project plugins/overleaf-tools/server pyright
```
