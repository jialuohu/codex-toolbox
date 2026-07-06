# Codex Toolbox

This repository manages a Codex plugin marketplace, MCP configuration,
third-party marketplace pins, and reusable Codex instructions.

## New Device Setup

1. Clone the repository:

   ```bash
   git clone <repo-url> codex-toolbox
   cd codex-toolbox
   ```

2. Run the setup script:

   ```bash
   scripts/setup-codex-toolbox.sh
   ```

   The script registers the configured toolbox marketplace, refreshes default
   plugins, installs third-party marketplace pins, removes stale direct MCP
   overrides for managed servers, and copies
   `config/codex/AGENTS.global.md` to `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`.

3. Add per-device secrets outside the repository as needed. Keep OAuth state,
   API keys, tokens, credential files, and env-file contents out of version
   control.

   Connector-specific credential paths, account details, and companion tool
   install locations should stay in local, untracked configuration.

4. Run MCP login or connector setup commands for any services that need local
   authentication.

5. Start a fresh Codex session so the installed global `AGENTS.md`, plugins, and
   MCP servers are loaded from the beginning of the run.

## Symphony Routing

For large decomposable projects, start naturally in Plan mode. For example:

```text
Build a polished business website for a small AI consulting agency.
```

The global instructions should let Codex plan first, recognize when the work
breaks into three or more independent testable tasks, and route to the
Codex + Symphony + Linear lane without requiring the prompt to name Symphony.
Plan mode may prepare issue breakdowns, a project-specific workflow preview,
and reviewed Linear issue preflight payloads. Live issue creation, scheduler
refreshes, workflow writes, and Linear closeout still require explicit approval.
After approval, preflight is no longer the endpoint; Codex should write the
reviewed workflow, create the approved issues, and start or refresh Symphony so
workers run. Do not offer Codex-only as an equal path for Symphony-eligible
plans unless the user explicitly asks for quick single-session execution or
opts out of Symphony/Linear.

## Deep Planning

Plan Mode uses `$deep-planning` by default for non-trivial work before the
final plan is presented. The skill is a critique gate: it gathers observed
facts, states assumptions and material unknowns, drafts the strongest plan,
challenges product value, architecture, implementation risk, edge cases, tests,
rollout, and scope, then chooses Codex-only, Superpowers, OpenSpec, or
Symphony/Linear routing.

Superpowers remains the design and implementation workflow. Deep Planning does
not write `docs/superpowers/` artifacts, create issues, dispatch workers, or
perform verification after code changes.

For projects outside the Symphony source repo
([jialuohu/symphony-go](https://github.com/jialuohu/symphony-go)), create a
project workflow first:

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
