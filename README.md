# Personal Codex Toolbox

This repository is the portable source for a Codex plugin marketplace,
managed MCP configuration, third-party marketplace pins, and global Codex
instructions.

## New Device Setup

1. Clone the repository:

   ```bash
   git clone git@github.com:jialuohu/codex-toolbox.git codex-toolbox
   cd codex-toolbox
   ```

2. Run the setup script:

   ```bash
   scripts/setup-codex-toolbox.sh
   ```

   The script registers the `jialuo-codex-toolbox` marketplace, refreshes default
   plugins, installs third-party marketplace pins, removes stale direct MCP
   overrides for managed servers, and copies
   `config/codex/AGENTS.global.md` to `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`.

3. Add per-device secrets under `CODEX_SECRETS_DIR/` as needed. Keep OAuth state,
   API keys, tokens, and env-file contents out of this repo.

   Symphony Tools expects:

   - `CODEX_SECRETS_DIR/symphony-linear.env` with the local Linear credentials.
   - `symphony` installed on `PATH` or at `~/.local/bin/symphony`, usually by
     running `make install-local` in `SYMPHONY_ROOT`.
   - Optional always-on operation uses `symphony service install/start`, which
     sources the same env file at runtime and does not embed secrets in the
     LaunchAgent plist.

4. Run MCP login or connector setup commands for services that need local auth,
   such as Robinhood Trading or other account-backed connectors.

5. Start a fresh Codex session so the installed global `AGENTS.md`, plugins, and
   MCP servers are loaded from the beginning of the run.

## Symphony Routing

For large decomposable projects, start naturally in Plan mode. For example:

```text
Build a polished business website for a small AI consulting agency.
```

The global instructions should let Codex plan first, recognize when the work
breaks into three or more independent testable tasks, and recommend the
Codex + Symphony + Linear lane without requiring the prompt to name Symphony.
Plan mode may prepare issue breakdowns, a project-specific workflow dry-run,
and Linear issue dry-runs. Live issue creation, scheduler refreshes, workflow
writes, and Linear closeout still require explicit approval. After approval,
dry-run is only the preflight; Codex should write the reviewed workflow, create
the approved issues, and start or refresh Symphony so workers run.

For projects outside `SYMPHONY_ROOT`, create a project workflow first:

```bash
symphony workflow init \
  --target-root ~/codes/example-project \
  --output ~/codes/example-project/WORKFLOW.md \
  --project-slug <PROJECT_SLUG> \
  --team-key <LINEAR_TEAM_KEY> \
  --port 4001 \
  --concurrency 4 \
  --dry-run
```

## AGENTS.md Sync

The canonical global instructions live at `config/codex/AGENTS.global.md`.

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
