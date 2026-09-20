# Setup and updates

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Obsidian filesystem roots](#obsidian-filesystem-roots)
- [New Device Setup](#new-device-setup)
- [Sync Toolbox](#sync-toolbox)
- [AGENTS.md Sync](#agentsmd-sync)
- [Managed Codex Pet](#managed-codex-pet)

## Obsidian filesystem roots

`obsidian_files` uses Filesystem MCP `2026.1.14` with the configured vault as
its command-line root; `move_file` remains disabled. This is not a fixed server
confinement boundary: a client advertising MCP roots can replace that directory
during initialization or a roots-change notification. The proposed `2026.8.31`
upgrade has the same behavior and is deferred pending a separately reviewed
confinement solution. See the isolated qualification in
[`test_obsidian_filesystem_integration.py`](../tests/test_obsidian_filesystem_integration.py).

## New Device Setup

1. Clone the repository:

   ```bash
   git clone <repo-url> codex-toolbox
   cd codex-toolbox
   ```

2. Create the required per-device Docmost configuration described in
   [Docmost Tools](docmost.md#docmost-tools). The default setup fails closed until
   `docmost.env` exists with mode `600`; it will open the isolated SSO login
   when authentication is required.

3. Add any other per-device secrets outside the repository as needed. Keep
   OAuth state, API keys, tokens, credential files, and env-file contents out
   of version control.

   Connector-specific credential paths, account details, and companion tool
   install locations should stay in local, untracked configuration.

4. Run the setup script:

   ```bash
   scripts/setup-codex-toolbox.sh
   ```

   The script registers the configured toolbox marketplace from the Git-backed
   marketplace source `jialuohu/codex-toolbox` on `main`, refreshes default
   plugins, installs third-party marketplace pins, removes stale direct MCP
   overrides for managed servers, and copies
   `config/codex/AGENTS.global.md` to `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`.
   Before Codex operations, it safely removes only the seven known duplicate
   user-skill links that still point into `.cc-switch/skills`, preserves their
   targets and `hatch-pet`, ensures a working `rg` through Homebrew when needed,
   and resolves Codex from `PATH`, the current ChatGPT app, then the legacy
   Codex app. Inspect those prerequisites without changing local state with:

   ```bash
   python3 scripts/setup-codex-prerequisites.py legacy-skills --check
   python3 scripts/setup-codex-prerequisites.py ensure-rg --check
   python3 scripts/setup-codex-prerequisites.py resolve-codex
   ```

   Because the toolbox marketplace is Git-backed, users can refresh it later
   from the Codex Desktop app by clicking **Upgrade**, or from the CLI:

   ```bash
   codex plugin marketplace upgrade jialuo-codex-toolbox
   ```

   After any marketplace upgrade that changes `docmost-tools` or
   `apple-mail-tools`, rerun the full setup so shared runtimes are rebuilt from
   the exact active plugin sources and smoke-checked before opening a fresh
   Codex task:

   ```bash
   scripts/setup-codex-toolbox.sh
   ```

   Running the full toolbox setup performs those runtime gates automatically.

   For local plugin development before changes are pushed to GitHub, register
   the checkout directly instead:

   ```bash
   CODEX_TOOLBOX_MARKETPLACE_MODE=local scripts/setup-codex-toolbox.sh
   ```

5. Run MCP login or connector setup commands for any other services that need
   local authentication.

6. Start a fresh Codex session so the installed global `AGENTS.md`, plugins, and
   MCP servers are loaded from the beginning of the run.

## Sync Toolbox

Use `$sync-toolbox`, or ask to sync and apply the latest codex-toolbox to this
machine. It checks the published revision and relevant CI, fast-forwards a clean
`main` checkout, runs the full managed setup, and verifies the installed result.
Setup covers instructions, pets, default plugins, runtime dependencies, managed
migrations, and third-party marketplace pins. Sync also checks previously
installed optional toolbox plugins, preserving their selection and enabled state.

Sync runs setup with `--non-interactive`, deferring Docmost login and Apple Mail
checks that can request permissions. It then checks all installed plugins, MCP
servers, and discoverable skills, including external plugins. Checks distinguish
installation integrity, runtime availability, and authentication. Static file
checks and an MCP listing do not prove a working connection or valid login.

The report summarizes coverage and repairs, lists **Needs your action** with
specific next steps, and separates other failures and unverified checks. Safe
probes never perform paid calls, grant permissions, or execute user workflows.
Only Toolbox-managed components are eligible for a targeted repair during sync.

Status-only requests inspect without changing the machine. An update stops on
unsafe Git state, unavailable or failed required CI, setup failures, and live
runtime locks; it does not repair history or stop services automatically.
Sync does not commit or publish changes. Use the explicitly invoked
[shipping workflow](development.md#ship-toolbox) for a completed repository change.

```text
Use $sync-toolbox to update this machine from published main and verify the full managed setup.
Use $sync-toolbox in health-only mode to check installed plugins, MCP servers, and skills without updates or repairs.
```

Health-only works from a dirty checkout and does not require rollout. Reports
default to stdout; optional JSON and Markdown files must stay outside Git.
Unsupported live probes remain unverified. See the
[health-check contract](../plugins/workflow-tools/skills/sync-toolbox/references/health-checks.md)
for evidence, time limits, safe probes, and report commands.

## AGENTS.md Sync

The canonical global instructions live at `config/codex/AGENTS.global.md` and
stay within an 8 KiB budget. Repository-specific development and shipping rules
live in the root `AGENTS.md`; together they stay below 16 KiB so nested project
instructions retain headroom. Detailed workflow, quota, and validation
contracts belong to their owning skills rather than the always-loaded global
file.

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

## Managed Codex Pet

The toolbox keeps the validated `stinky-penguin` v2 package under
`config/codex/pets/stinky-penguin/`. Setup copies repository-managed pets into
`${CODEX_HOME:-$HOME/.codex}/pets/` atomically, backs up a different package
with the same ID, and preserves unrelated custom pets. It installs the pet
without selecting it or changing the current Codex avatar preference.

Use the synchronizer directly when validating or installing pet updates:

```bash
python3 scripts/sync-codex-pets.py --install
python3 scripts/sync-codex-pets.py --check
```

A marketplace **Upgrade** refreshes plugins but does not copy runtime pet
files. Rerun the toolbox setup after upgrading when a managed pet changes, then
start a fresh Codex Desktop session to load and animate the updated atlas.
