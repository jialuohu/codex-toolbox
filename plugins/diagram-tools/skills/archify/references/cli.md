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
  "version": "2.17.0-dev.1",
  "channel": "development",
  "sourceCommit": "72c750bb070d95171dbb2244e5b62b1b7da69c12",
  "releaseDirectory": "/absolute/path/to/release",
  "sha256": "d2296515b0091fb8f00580ea9e0b665d91ca5839fde651abe3ecd57a3ca178ec",
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

After rollback to the retained stable `2.16.0` generation, the response reports
`channel: "stable"` and `sourceCommit: null`.

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

The installer pins the canonical `archify.zip` committed at
`72c750bb070d95171dbb2244e5b62b1b7da69c12`, version `2.17.0-dev.1`, by SHA-256.
This is a development snapshot, not the stable `2.16.0` release or a moving
`main` download. It validates an isolated candidate and promotes it atomically.
An upgrade from `2.16.0` retains that stable generation for `--rollback`; verify
the restored version with `runtime-info --json`. Fresh installations have no
previous generation. Rollback is not a persistent version preference: the next
`scripts/setup-codex-toolbox.sh` run reinstalls the approved pin. To use the
retained stable generation after setup, explicitly run
`scripts/setup-archify-tools.sh --rollback` again. The packaged checker may
contact only
`https://tt-a1i.github.io/archify/skill-updates/archify/stable.json`; its notice
does not change the installed runtime or follow development commits. This
snapshot embeds JetBrains Mono variable font subsets and their OFL 1.1 notice in
standalone HTML/SVG, with system fallbacks for uncovered characters. No Google
Fonts request is needed to view a newly generated artifact.

## Browser evidence and visual review

`deliver` proves deterministic checks and specification/artifact byte identity.
`visual-check` measures the exact HTML in Chrome/Chromium and creates its own
artifact-bound receipt and screenshots. It always leaves perceptual
`visualReview: "pending"`. Map exit 0 plus receipt `status: "pass"` to
`browser_evidence: passed`, exit 1 to `failed`, and exit 2 plus receipt
`status: "skipped"` to `skipped` only when the browser is unavailable.
Incomplete runtime/capture evidence is failed, not skipped. Report an actual
reviewer's `visual_review` judgment independently; a manual browser record cannot
overwrite the automated status. For coverage and supplementary record fields,
resolve the installed delivery contract from the directory containing the
returned absolute `skillPath`, then its `references` directory and
`delivery-contract.md` filename. This contract belongs to the active upstream
runtime, not the toolbox wrapper directory.
