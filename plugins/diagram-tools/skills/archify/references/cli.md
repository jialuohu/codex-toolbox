# Archify CLI Reference

The toolbox setup installs the collision-safe `archify` launcher into
`CODEX_LOCAL_BIN_DIR`, defaulting to `~/.local/bin`. It passes upstream commands
and options through unchanged and adds `runtime-info --json`.

## Runtime inspection

```bash
archify runtime-info --json
```

Success exits 0 and returns absolute, validated paths:

```json
{
  "ok": true,
  "status": "ready",
  "version": "2.16.0",
  "releaseDirectory": "/absolute/path/to/release",
  "sha256": "4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46",
  "cliPath": "/absolute/path/to/bin/archify.mjs",
  "skillPath": "/absolute/path/to/SKILL.md",
  "commonSchemaPath": "/absolute/path/to/common.schema.json",
  "typeSchemaPaths": {
    "architecture": "/absolute/path/to/architecture.schema.json",
    "workflow": "/absolute/path/to/workflow.schema.json",
    "sequence": "/absolute/path/to/sequence.schema.json",
    "dataflow": "/absolute/path/to/dataflow.schema.json",
    "lifecycle": "/absolute/path/to/lifecycle.schema.json"
  },
  "examplePaths": {
    "architecture": "/absolute/path/to/example.architecture.json",
    "workflow": "/absolute/path/to/example.workflow.json",
    "sequence": "/absolute/path/to/example.sequence.json",
    "dataflow": "/absolute/path/to/example.dataflow.json",
    "lifecycle": "/absolute/path/to/example.lifecycle.json"
  },
  "updateCheckerPath": "/absolute/path/to/check-update.mjs",
  "updateManifestUrl": "https://tt-a1i.github.io/archify/skill-updates/archify/stable.json"
}
```

Missing or extra `runtime-info` options are usage errors on stderr and exit 2.
An unusable runtime exits 3 and returns
`{"ok":false,"status":"unavailable","error":{...}}` on stdout. If the
launcher is unavailable, run `node scripts/archify.mjs runtime-info --json`
from the skill directory.

## Upstream command surface

```text
archify render <type> <input.json> [output.html] [--quality standard|showcase] [--repo-root PATH]
archify compare architecture <base.json> <head.json> [output.html] [--receipt PATH] [--json] [--quality standard|showcase] [--repo-root PATH]
archify deliver <type> <input.json> [output.html] [--json] [--open] [--quality standard|showcase] [--repo-root PATH]
archify preview <type> <input.json> [output.html] [--no-open] [--quality standard|showcase] [--repo-root PATH]
archify validate <type> <input.json> [--json] [--layout-json] [--quality standard|showcase] [--repo-root PATH]
archify migrate workflow <old.json> <new.json> --to-schema 2 [--json]
archify inspect <type> <input.json>
archify check <output.html>
archify visual-check <output.html> [--json]
archify guide [SCENARIO] [--json] [--lang en|zh]
archify brands [QUERY] [--json]
archify brands capture <url> [--json]
archify examples
archify doctor
archify demo [output-directory]
```

Types are `architecture`, `workflow`, `sequence`, `dataflow`, and `lifecycle`.
The launcher preserves each upstream command's stdout, stderr, and exit status.
Without a usable active runtime, pass-through commands report setup failure on
stderr and exit 3.

## Runtime maintenance

The immutable Archify runtime lives below
`${CODEX_HOME:-$HOME/.codex}/runtime/diagram-tools/archify`; tests may override
it with `ARCHIFY_RUNTIME_ROOT`. Ordinary skill use never installs, updates, or
rolls back the runtime.

```bash
scripts/setup-archify-tools.sh --check
scripts/setup-archify-tools.sh --install
scripts/setup-archify-tools.sh --rollback
```

The installer pins upstream `v2.16.0` `archify.zip` by SHA-256, validates it in
an isolated candidate, and promotes it atomically. The packaged checker may
contact only
`https://tt-a1i.github.io/archify/skill-updates/archify/stable.json`; its notice
does not change the installed runtime. Generated HTML may request JetBrains Mono
CSS/font data from `fonts.googleapis.com` and `fonts.gstatic.com`, with local
monospace fallbacks when those requests fail.
