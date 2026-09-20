# Diagrams and paper figures

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Diagram Tools](#diagram-tools)
- [Cloudflare Pages sharing](#cloudflare-pages-sharing)
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
commits the HTML atomically. `visual-check` measures light-theme containment at
1440×900, 1600×1000, 1920×1080, and 2048×1320, then captures both themes at the
smallest and largest sizes. Report deterministic delivery, automated
`browser_evidence`, and perceptual `visual_review` separately: automated
screenshots are evidence to inspect, not approval of visual polish. Static
presentation is the default; trace motion is enabled only for a requested demo
or presentation.
Without a requested destination, artifacts go in a task-scoped temporary
directory.

The immutable Archify runtime is pinned to development snapshot
`2.17.0-dev.1` at commit `72c750bb070d95171dbb2244e5b62b1b7da69c12`, using
that commit's canonical
[`archify.zip`](https://raw.githubusercontent.com/tt-a1i/archify/72c750bb070d95171dbb2244e5b62b1b7da69c12/archify.zip)
(1,885,058 bytes; SHA-256
`d2296515b0091fb8f00580ea9e0b665d91ca5839fde651abe3ecd57a3ca178ec`)
under `${CODEX_HOME:-$HOME/.codex}/runtime/diagram-tools/archify`. Installation
validates the archive, upstream license, runtime paths, `doctor`, and fixtures
before atomic promotion; rollback retains the last good generation. This is an
explicit development pin, not the stable `2.16.0` release and not a moving
`main` download. Upgrading an existing `2.16.0` installation retains that stable
generation for `--rollback`; fresh installations have no previous generation.
Rollback is not a persistent version preference: the next toolbox setup
reinstalls the approved pin. After setup, explicitly run
`scripts/setup-archify-tools.sh --rollback` to use the retained stable generation again.
Confirm the restored version with `runtime-info --json`. The
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
downloads or installs an update. This snapshot embeds JetBrains Mono variable
font subsets and their SIL Open Font License 1.1 notice in standalone artifacts;
viewing does not request Google Fonts. Characters outside the subsets, including
CJK, still use system fallbacks. URL-based brand capture is
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

Toolbox setup installs the stable rendering launchers in `CODEX_LOCAL_BIN_DIR`, defaulting
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

## Cloudflare Pages sharing

`diagram-tools` includes the reusable
[$diagram-publish skill](../plugins/diagram-tools/skills/diagram-publish/SKILL.md).
After installation-specific opt-in, Archify automatically publishes the final
HTML only after validation, successful delivery, and actual visual review. The
hosted link accompanies a local browser preview and retained editable JSON.
Pretty Mermaid, draw.io, OmniGraffle, and paper figures keep their existing local
delivery behavior in v1. Low-level rendering and `archify deliver` never publish.

Sharing uses one dedicated Cloudflare Pages Direct Upload project and a distinct
preview deployment per finalized version. Return the immutable deployment URL;
subsequent drawings do not replace it. There is no public gallery, custom domain,
or production-site deployment. Anyone with the URL can read the HTML, including
embedded diagram data. Current Archify artifacts include their font subsets;
older artifacts may retain the font requests from the runtime that generated
them. `noindex` headers do not provide access control.

### One-time setup

Publishing is disabled on new installations. For an authorized setup, install
the launcher and pinned runtime (Node 22 or newer, Wrangler `4.135.0` with locked
dependencies):

```bash
scripts/setup-diagram-publish.sh
diagram-publish setup --install-runtime
diagram-publish status
```

Create an account-scoped **Cloudflare Pages Edit** token and save it in a
protected file beneath `CODEX_SECRETS_DIR`, defaulting to
`${CODEX_HOME:-$HOME/.codex}/secrets`. Do not paste the token into chat or shell
arguments. This token can edit Pages projects throughout the selected account;
the helper restricts its operations to the recorded dedicated project.
Configure the account and reference the file to create a dedicated
`codex-diagrams-<random suffix>` project and enable automatic sharing:

```bash
diagram-publish setup --account-id ACCOUNT_ID --token-file TOKEN_FILE --auto
diagram-publish status --online
```

Account configuration, attempts, and receipts are stored outside repositories
under `${CODEX_HOME:-$HOME/.codex}/diagram-publish`. The credential remains in its
protected file. Ordinary drawing work does not install runtimes or initiate
setup. The default `status` is local and read-only; `--online` explicitly checks
Cloudflare. See [Cloudflare's token setup](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/).

### Accepted HTML and publication history

The generic helper accepts the exact visually reviewed HTML and its final
SHA-256. All commands emit JSON by default:

```bash
diagram-publish publish-html --file ACCEPTED_HTML --expect-sha256 SHA256 --reviewed
diagram-publish list
```

Only `index.html` and generated `_headers` enter an isolated staging directory;
sibling sources, screenshots, and receipts stay local. Changed hashes,
symlinks, local resource references, and oversized files are rejected. A link is
reported ready only after project identity and preview success are checked and
an unauthenticated HTTPS response matches the accepted HTML hash. Interrupted
attempts are reconciled before retrying; local artifacts survive failures.
An upload whose outcome remains unknown is reconciliation-only until the
provider exposes its result; it is never silently reset and uploaded again.
Known deployment IDs remain available for explicit removal even if public
response verification fails.

Set `CODEX_TOOLBOX_NO_PUBLISH=1` to disable publication, or add `--local-only`
for a single local result. Agent workflows do not publish in Plan mode, CI,
private/confidential tasks, or before final acceptance. The helper cannot infer
conversation mode; the owning skill enforces it. Existing public deployments
remain until explicitly removed. To remove one specifically requested recorded
deployment:

```bash
diagram-publish unpublish --deployment-id DEPLOYMENT_ID --confirm
```

There is no automatic deletion or expiry. See the owning skill for authorization,
verification, interruption handling, and the complete handoff contract.

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
