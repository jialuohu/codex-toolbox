# Canvas Tools

Canvas Tools packages [vishalsachdev/canvas-mcp](https://github.com/vishalsachdev/canvas-mcp)
for a single student's local Codex session. The launcher pins `canvas-mcp==1.12.0`,
forces the student tool profile, disables TypeScript execution, and exposes only
the positive allowlist in `.mcp.json`. It also includes a workflow for preparing
one Canvas assignment in Overleaf while preserving source questions and figures.

## Configure

Create the private configuration directory outside this repository, using your
actual Canvas hostname:

```bash
secrets_root="${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"
mkdir -p "$secrets_root/canvas-tools"
chmod 700 "$secrets_root/canvas-tools"
```

Create `$secrets_root/canvas-tools/canvas.env` with exactly these required values:

```dotenv
CANVAS_API_URL=https://your-institution.instructure.com/api/v1
CANVAS_API_TOKEN=replace_with_your_personal_access_token
```

Then restrict and test it:

```bash
chmod 600 "$secrets_root/canvas-tools/canvas.env"
plugins/canvas-tools/scripts/run-canvas-mcp.sh --test
```

The URL must use HTTPS and end in `/api/v1`. Canvas tokens inherit the full
permissions of the account that created them; never paste a token into chat,
command arguments, screenshots, repository files, or logs. If your institution
does not expose personal access-token creation, follow its official request
process instead of trying to bypass that policy.

## Use

Install the opt-in plugin from the toolbox marketplace and start a fresh Codex
task so the MCP server and skill are loaded:

```bash
codex plugin add canvas-tools@jialuo-codex-toolbox
```

Example requests:

```text
Use $canvas-student-planning to show what I have due in the next seven days.
Use $canvas-student-planning to reconcile my incomplete Canvas assignments into Todoist.
Use $canvas-student-planning to submit this PDF after showing me the complete preview.
Use $canvas-overleaf-homework to set up this Canvas assignment in Overleaf using problems 2, 13, and 15 from this source, including figures, and link it in Todoist.
```

`$canvas-overleaf-homework` requires the configured `overleaf-tools` plugin,
one authenticated Todoist surface, and a local compiler available through
`$latex-compile`. It accepts a Canvas assignment, configured Overleaf project,
user-supplied public problem-source URL, and selected problem numbers. It copies
the selected statements exactly, imports their original figures, compiles a
temporary snapshot, performs guarded sequential Overleaf writes, and adds one
canonical Overleaf link to the matching Todoist task. When no matching task
exists, an explicit Todoist-linking request creates one from the Canvas record.

The workflow does not solve or submit homework. It stops on ambiguous problem
numbering, missing source figures, compile errors, or disagreement between live
Canvas and Todoist deadlines. It never stores personal project URLs, assignment
content, or credentials in this plugin.

Canvas-to-Todoist reconciliation runs only when explicitly requested. It does
not create Calendar events, run in the background, or automatically complete or
delete tasks.
