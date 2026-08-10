# Pretty Mermaid CLI Reference

The toolbox setup installs the `pretty-mermaid` launcher into `CODEX_LOCAL_BIN_DIR`, defaulting to `~/.local/bin`. It refuses to replace an unrelated executable or symlink at that path.

## Rendering

`render` requires a `.mmd` input path and one format:

```text
--format svg|png|ascii
--output FILE
--theme NAME
--scale 1|2|3|4
--transparent
--font FAMILY
--bg COLOR
--fg COLOR
--line COLOR
--accent COLOR
--muted COLOR
--surface COLOR
--border COLOR
--use-ascii
```

SVG and PNG require an output file. ASCII defaults to stdout and may instead use a `.txt` output. Theme names apply to SVG and PNG. Custom colors override the selected theme. PNG defaults to scale 2.

`batch` accepts the same rendering flags plus `--input-dir`, `--output-dir`, and `--workers`. It processes top-level `.mmd` files only, uses real worker threads, and refuses worker counts below 1 or above 16.

## Inspection and maintenance

- `themes [--json]` lists themes exported by the active Beautiful Mermaid package.
- `capabilities [--json]` reports the active version, selected API exports, formats, themes, and conformance contract.
- `doctor [--json]` is offline and checks the active runtime and its installation receipt.
- `update [--strict]` contacts npm, stages the newest stable release, runs conformance in a bounded process, and atomically promotes it. Without `--strict`, a rejected candidate is a warning when an active or approved fallback runtime remains usable. CI uses `--strict`.
- `rollback` validates and swaps to the previous active release.

Normal rendering never contacts npm. When doctor reports no usable runtime, run the repository's `scripts/setup-diagram-tools.sh --update`, or rerun `scripts/setup-codex-toolbox.sh`.

## Exit behavior

- `0`: requested operation succeeded, or a non-strict update safely retained a usable runtime.
- `2`: invalid CLI usage.
- `3`: no usable runtime or setup failure.
- `4`: Mermaid parsing or rendering failure.
- `5`: strict candidate rejection or failed rollback.

Errors go to stderr. JSON inspection commands emit one JSON object on stdout.
