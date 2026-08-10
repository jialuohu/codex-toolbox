---
name: pretty-mermaid
description: Create or render polished Mermaid diagrams while preserving editable .mmd source and exporting self-contained SVG, genuine PNG, or ASCII. Use when Codex needs a themed diagram artifact, Mermaid file conversion, architecture or workflow visualization, batch diagram rendering, terminal-friendly output, or a more polished result than the host's inline Mermaid renderer.
---

# Pretty Mermaid

Save Mermaid source before rendering. Keep an existing `.mmd` file unchanged unless the user asks to edit it. When generating a new diagram, place the `.mmd` beside the requested export.

## Workflow

1. Run `pretty-mermaid doctor --json`. If the launcher is unavailable, resolve this skill directory and run `node scripts/pretty-mermaid.mjs doctor --json`.
2. If the runtime is missing or incompatible, stop and report the setup command from the doctor result. Do not install packages during an ordinary render.
3. Create or validate the `.mmd` source. Use quoted node labels when labels contain punctuation or parentheses.
4. Inspect themes when the user has not chosen one:

   ```bash
   pretty-mermaid themes
   ```

5. Render the requested artifact:

   ```bash
   pretty-mermaid render \
     --input /absolute/path/diagram.mmd \
     --output /absolute/path/diagram.svg \
     --format svg \
     --theme github-light
   ```

6. For PNG, default to `--scale 2` unless the user requests another scale. For terminal output, use `--format ascii`; add `--use-ascii` only when Unicode box drawing is unsuitable.
7. Verify the output exists. Display SVG or PNG using its absolute path in the final response and link the `.mmd` source.

## Selection Rules

- Use native inline Mermaid for a quick in-task explanation that does not need an artifact.
- Use this skill for polished exports, stable files, themes, PNG, ASCII, or batch conversion.
- Use `$paper-figure-workflow` for publication figures requiring draw.io, Matplotlib, SVG/PDF cleanup, or a reproducible paper pipeline.
- Beautiful Mermaid implements a Mermaid subset. Run `capabilities` when syntax support is uncertain. If rendering rejects a diagram family, preserve the `.mmd` and report the limitation; do not silently change its semantics.

## Commands

```text
pretty-mermaid render --input FILE --format svg|png|ascii [--output FILE]
pretty-mermaid batch --input-dir DIR --output-dir DIR --format svg|png|ascii
pretty-mermaid themes [--json]
pretty-mermaid capabilities [--json]
pretty-mermaid doctor [--json]
pretty-mermaid update [--strict]
pretty-mermaid rollback
```

The toolbox setup installs `pretty-mermaid` into `CODEX_LOCAL_BIN_DIR` (default `~/.local/bin`). When that directory is not on `PATH`, run the equivalent `node scripts/pretty-mermaid.mjs ...` command from this skill directory. Read `references/cli.md` for complete flags, exit behavior, and runtime recovery.
