---
name: pretty-mermaid
description: Default renderer for Mermaid diagrams. Preserve editable .mmd source and export self-contained SVG, genuine PNG, or ASCII for explanations, architecture, workflows, file conversion, themed output, or batch rendering.
---

# Pretty Mermaid

Use this skill whenever Mermaid is the chosen visual format. Save Mermaid source before rendering. Keep an existing `.mmd` file unchanged unless the user asks to edit it, and place new source beside its export.

## Workflow

1. Run `pretty-mermaid doctor --json`. If the launcher is unavailable, resolve this skill directory and run `node scripts/pretty-mermaid.mjs doctor --json`.
2. If the runtime is missing or incompatible, use native inline Mermaid with the unchanged source, briefly disclose the fallback, and report the setup command from the doctor result. Do not install packages during an ordinary render.
3. Create or validate the `.mmd` source. Use quoted node labels when labels contain punctuation or parentheses. If the user gave no destination, create a task-scoped temporary directory with `mktemp -d` and keep the source and export there; do not add automatic artifacts to the active repository.
4. On a graphical surface, default to SVG and the renderer's default theme (`github-light` when available). In a terminal, render ASCII and include the editable `.mmd`. Honor an explicit destination, format, theme, color, scale, or transparency setting.
5. Render the artifact, for example:

   ```bash
   pretty-mermaid render \
     --input /absolute/path/diagram.mmd \
     --output /absolute/path/diagram.svg \
     --format svg \
     --theme github-light
   ```

6. For PNG, default to `--scale 2` unless the user requests another scale. For terminal output, use `--format ascii`; add `--use-ascii` only when Unicode box drawing is unsuitable.
7. Verify the output exists. Display SVG or PNG using its absolute path in the final response and link the `.mmd` source. For ASCII, include the rendered text and the `.mmd` path.

## Selection Rules

- Use this skill by default whenever Mermaid is selected, including quick explanations.
- Use native inline Mermaid only when the user explicitly requests it or when the runtime is unavailable or rejects the syntax. Briefly disclose automatic fallback, reuse the exact source, and do not silently change semantics.
- Use `$paper-figure-workflow` for publication figures requiring draw.io, Matplotlib, SVG/PDF cleanup, or a reproducible paper pipeline.
- Beautiful Mermaid implements a Mermaid subset. Run `capabilities` when syntax support is uncertain. If rendering rejects a diagram family, preserve the `.mmd`, fall back to native inline Mermaid, and report the limitation.

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
