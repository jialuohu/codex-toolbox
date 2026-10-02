# Figure Workflow Templates

Use the project-local starter in `../assets/research-figure-starter/` after inspecting the paper repo. It includes four editable Matplotlib scripts: `grouped_bars.py`, `line_scaling.py`, `empirical_cdf.py`, and `stacked_breakdown.py`. The last script produces either additive stacked bars or stacked areas. Fixed, labeled synthetic inputs show ablation uncertainty, aligned scaling panels with a shared legend, empirical percentile annotations, and both breakdown forms.

Copy all scripts, `figure_common.py`, `research.mplstyle`, `method_styles.json`, input data, `requirements.txt`, Makefile, and selected native diagram sources into the research project. The copier is:

```bash
python3 plugins/diagram-tools/skills/paper-figure-workflow/scripts/scaffold_research_figures.py --project /absolute/paper/project --diagram-owner auto
```

Choose `--diagram-owner auto|omnigraffle|drawio`. The selected owner, selection basis and reason are recorded once in `figures_src/diagram-owner.json`. Explicit choices, existing `.graffle` or `.drawio` sources, and recorded project owners are preserved without probing or switching applications. The source-owned native preference is active after template and foreground-Terminal equation/restart acceptance. Only new unowned `auto` projects run a fresh `doctor --probe-app`; responsive OmniGraffle scripting and advertised PDF export select OmniGraffle, otherwise the recorded reason discloses Draw.io fallback before native dispatch. Project metadata and a doctor result cannot activate the release gate. The probe establishes drawing readiness, not equation GUI access: the accepted foreground Terminal profile does not grant System Events permission to an SSH caller. `--drawio-templates /absolute/dir` and `--omnigraffle-plugin /absolute/plugin` override plugin discovery. The copier refuses source-file overwrites and copies the complete guarded OmniGraffle runtime and accepted native starter assets for native projects. If selected templates are unavailable, scaffolding fails unless `--plots-only` is explicitly chosen.

Resolve the active `$omnigraffle-workflow` skill from the current catalog; its plugin root is two parents above the skill directory. Read `<active-omnigraffle-plugin>/assets/research-templates/README.md` under that root for the six accepted native starters and their manifest. Pass the exact root with `--omnigraffle-plugin` when invoking the scaffold from an installed skill. Do not construct paths across sibling versioned caches. Copy a selected `.graffle` to a new filename under `figures_src/diagrams` to edit it directly, or initialize a fresh source from the generator. Preserve its adjacent palette provenance. Later `make diagrams` builds use the saved native file without initialization seeds.

## Build and export

Install exact Python versions from the copied `requirements.txt` into an isolated environment. Poppler `pdffonts` is required for the plot verification gate. Draw.io Desktop is required for its diagram owner. Then run:

```bash
make plots PYTHON=.venv/bin/python
make diagrams
make figures PYTHON=.venv/bin/python
```

`make diagrams` reads the recorded owner. A conflicting `DIAGRAM_OWNER` fails instead of switching tools. For OmniGraffle, run `make init-diagram TEMPLATE=architecture WIDTH=double` once per new native source; it creates a seed and editable `.graffle` through the copied guarded runtime. Later builds export the saved native file, keeping manual edits. The built-in native path stages PDF/SVG/PNG, checks source fingerprints and physical widths, and fails on missing dependencies. Other diagram owners can still use a project-local `FIGURE_DIAGRAM_EXPORTER` adapter, including Archify's existing review gate.

All plot scripts retain `--data`, `--out-dir`, and `--width single|double`; `--width-in` is a mutually exclusive positive custom override. The renderers use `import scienceplots` before `plt.style.use(['science', 'no-latex', project_style])`. The project style declares DejaVu Sans, 8-point body text, a 7-point minimum, `svg.fonttype='none'`, and `pdf.fonttype=42`. For fixed width, `fig.savefig(..., bbox_inches=None)` is required. Do not use a tight bounding-box crop: it changes the saved canvas width. A simple exporter writes `figure.svg` and `figure.pdf`:

```python
fig.savefig("figure.svg", bbox_inches=None)
fig.savefig("figure.pdf", bbox_inches=None)
```

`make verify-plots` checks SVG/PDF physical widths within 0.01 inch, editable SVG text, text size after any requested placement scaling, and PDF font embedding. Use `pdftotext` and a visual inspection for unusual glyphs. See [research-style.md](research-style.md) for the source-grounded composition and data rules.

The native owner may use `drawio --export` when available; the installed Draw.io Desktop helper handles `svg` and `pdf`. If a project uses Inkscape for a supported conversion, `inkscape figure.svg --export-type=pdf --export-filename=figure.pdf` is a separate explicit step, never a silent fallback for a missing owner export.
