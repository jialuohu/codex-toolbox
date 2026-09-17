# Diagrams and paper figures

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Diagram Tools](#diagram-tools)
- [Draw.io Tools](#drawio-tools)
- [OmniGraffle Tools](#omnigraffle-tools)
- [Paper Figure Workflow](#paper-figure-workflow)

## Diagram Tools

The default `diagram-tools` plugin provides two bounded rendering lanes.
`$archify` is the graphical default for architecture and workflow maps and for
polished interactive sequence, data-flow, or lifecycle artifacts.
`$pretty-mermaid` owns explicit Mermaid or `.mmd`, terminal ASCII, and compact
static diagrams. `$drawio` remains the owner of explicit native draw.io,
multi-page, WYSIWYG, specialized-shape, and Desktop export work;
`$paper-figure-workflow` owns publication pipelines; bundled Visualize owns
adjustable, inspectable spatial views in the conversation.

Archify retains editable `<name>.<type>.json` beside a validated standalone
`<name>.html`. New workflows use schema v2; architecture, sequence, data-flow,
and lifecycle sources use schema v1. Showcase delivery validates every source,
commits the HTML atomically, then captures light/dark containment evidence at
1440×900, 1600×1000, 1920×1080, and 2048×1320. Static presentation is the
default; trace motion is enabled only for a requested demo or presentation.
Without a requested destination, artifacts go in a task-scoped temporary
directory.

The immutable Archify runtime is pinned to upstream `v2.16.0` `archify.zip`
(SHA-256
`4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46`)
under `${CODEX_HOME:-$HOME/.codex}/runtime/diagram-tools/archify`. Installation
validates the archive, upstream license, runtime paths, `doctor`, and fixtures
before atomic promotion; rollback retains the last good generation. The
collision-safe launcher passes through the upstream CLI and adds runtime
inspection:

```bash
archify runtime-info --json
archify validate architecture system.architecture.json --quality showcase --json
archify deliver architecture system.architecture.json system.html --quality showcase --json
archify visual-check system.html --json

scripts/setup-archify-tools.sh --check
scripts/setup-archify-tools.sh --install
scripts/setup-archify-tools.sh --rollback
```

Archify preserves upstream's notification-only update checker. It may request
the fixed manifest at
`https://tt-a1i.github.io/archify/skill-updates/archify/stable.json`, but never
downloads or installs an update. Generated HTML may load JetBrains Mono from
`fonts.googleapis.com` and `fonts.gstatic.com`; local/system monospace fallback
keeps the artifact usable when those requests fail. URL-based brand capture is
explicit-only and never runs during rendering or validation.

Pretty Mermaid preserves editable `.mmd` and exports self-contained SVG, real
PNG through Resvg, or plain ASCII/Unicode. Graphical surfaces default to SVG,
while terminals use ASCII. Use native inline Mermaid only for explicit requests
or a disclosed runtime or syntax fallback. Its contract-gated rolling
runtime lives under `${CODEX_HOME:-$HOME/.codex}/runtime/diagram-tools`.
Toolbox setup resolves the newest stable `beautiful-mermaid` release, installs
it into an isolated candidate with lifecycle scripts disabled, verifies package
integrity and production audit results, renders compatibility fixtures, and
promotes it atomically. A rejected release cannot replace the working runtime.
Fresh installations fall back to the lockfile-approved release; Dependabot
proposes updates separately.

Normal Pretty Mermaid rendering is offline. Check, update, or roll back its
runtime with:

```bash
scripts/setup-diagram-tools.sh --check
scripts/setup-diagram-tools.sh --update
scripts/setup-diagram-tools.sh --update --strict
scripts/setup-diagram-tools.sh --rollback
```

Toolbox setup installs both stable launchers in `CODEX_LOCAL_BIN_DIR`, defaulting
to `~/.local/bin`. Pretty Mermaid commands include:

```bash
pretty-mermaid themes
pretty-mermaid capabilities --json
pretty-mermaid render --input diagram.mmd --output diagram.svg --format svg --theme github-light
pretty-mermaid render --input diagram.mmd --output diagram.png --format png --theme tokyo-night --scale 2
pretty-mermaid batch --input-dir diagrams --output-dir rendered --format svg --workers 4
```

Beautiful Mermaid intentionally supports a subset of Mermaid syntax. The
active capability report names the tested diagram families and available
themes; unsupported syntax fails without rewriting the `.mmd` source.

## Draw.io Tools

The default `drawio-tools` plugin provides `$drawio` and the `drawio` MCP
server for explicit draw.io or diagrams.net requests, editable `.drawio`
source, multi-page inspection and editing, specialized shape libraries,
browser editing, and optional Desktop exports. Archify remains the graphical
default for architecture/workflow maps and polished interactive
sequence/data-flow/lifecycle artifacts; Pretty Mermaid owns explicit Mermaid,
terminal ASCII, and compact static diagrams. `$paper-figure-workflow` remains
the owner of publication pipelines and delegates native draw.io execution here.

The MCP exposes exactly `open_drawio_xml`, `open_drawio_csv`,
`open_drawio_mermaid`, `search_shapes`, `list_pages`, `get_page`, and
`set_page`. Read/open tools are auto-approved; `set_page` prompts because it
mutates a local file. `DRAWIO_BASE_URL` may select a trusted self-hosted editor
instead of the default `https://app.diagrams.net/`.

Toolbox setup installs exact `@drawio/mcp@1.4.0` dependencies under
`${CODEX_HOME:-$HOME/.codex}/runtime/drawio-tools/active` with lifecycle
scripts disabled. It audits the production tree and installs a SHA-256-checked
shape index pinned to an upstream commit before atomic promotion. Normal MCP
startup validates this receipt and uses no `npm`, `npx`, or network access.

Use the focused setup helper directly with:

```bash
scripts/setup-drawio-tools.sh --check
scripts/setup-drawio-tools.sh --install
scripts/setup-drawio-tools.sh --install --with-desktop
```

draw.io Desktop is opt-in. The full toolbox setup installs and smoke-tests it
only when requested; on macOS this may run `brew install --cask drawio`:

```bash
CODEX_TOOLBOX_INSTALL_DRAWIO_DESKTOP=1 scripts/setup-codex-toolbox.sh
```

Set `DRAWIO_DESKTOP_BIN` to reuse another Desktop executable. Managed PNG,
SVG, and PDF exports retain the `.drawio` source and run Desktop with
`-x -f FORMAT -e -b 10 -o OUTPUT INPUT`, embedding diagram XML. If Desktop is
unavailable, the workflow leaves the editable `.drawio` source and exact local
export command; it does not silently use cloud rasterization. With no requested
destination, artifacts go in a task-scoped temporary directory.

## OmniGraffle Tools

Use `$omnigraffle-workflow` for explicit OmniGraffle or an existing `.graffle` artifact. Native drawing and exports use OmniGraffle scripting; editable equations use official LaTeXiT and real LinkBack GUI callbacks. Equation automation requires an unlocked Mac. General graphical requests retain `$archify`; explicit Mermaid and compact static diagrams retain `$pretty-mermaid`.

Default setup installs plugin files only. Applications, TeX and permission changes require explicit dependency setup. Start with [the skill and doctor command](../plugins/omnigraffle-tools/skills/omnigraffle-workflow/SKILL.md); [command details](../plugins/omnigraffle-tools/skills/omnigraffle-workflow/references/commands.md) describe inspection, mutation, export and interruption reconciliation. A retained JSON request never replaces later manual native edits. Do not retry an uncertain mutation before reconciliation.

## Paper Figure Workflow

Explicit application choice takes precedence, followed by the existing source format. `$omnigraffle-workflow` owns OmniGraffle/`.graffle`; `$drawio` owns draw.io/`.drawio`. Otherwise publication pipelines retain draw.io as their default. Paper Figure Workflow owns directories, regeneration commands and cross-figure checks.

Use `$paper-figure-workflow` when a research repo needs reproducible paper
figures. The skill guides Codex to inspect the repo first, keep native source
diagrams editable through the selected drawing owner, generate Matplotlib and SciencePlots result
plots from repo data, export SVG/PDF figures, use Inkscape only for conversion
or light cleanup, and add a command such as `make figures`.

Example prompt:

```text
Use $paper-figure-workflow to set up clean, reproducible figures for this AI/systems paper repo.
```
