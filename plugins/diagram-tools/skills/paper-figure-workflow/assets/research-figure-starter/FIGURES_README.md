# Research figure starter

All values under `figures_src/plots/data/` are **illustrative synthetic data**. Replace them with traceable measurements before a paper submission. Edit `method_styles.json` once for the whole figure set; order in input files does not assign colors, markers, line styles, or hatches. An unregistered method or component fails rather than silently taking the next color.

Install Python 3.12 and the exact versions in `requirements.txt` in an isolated environment. For example:

```bash
uv venv .venv --python 3.12
uv pip sync --python .venv/bin/python requirements.txt
make plots PYTHON=.venv/bin/python
make diagrams PYTHON=.venv/bin/python
make figures PYTHON=.venv/bin/python
```

`make plots` requires Matplotlib, SciencePlots, and Poppler `pdffonts`; it generates SVG and PDF in `figures/` and verifies the fixed canvas widths, editable SVG text, minimum final text size, and embedded DejaVu Sans. The plot scripts accept `--data`, `--out-dir`, and either `--width single|double` or a positive `--width-in`. The default is single width (3.3 in); double is 6.9 in. Adjust the expected widths in `Makefile` if a venue requires a different size. `scripts/verify_exports.py --target-width-in ...` checks whether resizing in the paper would reduce text below 7 pt.

`figures_src/diagram-owner.json` records the owner, selection basis and reason chosen once by scaffolding. Subsequent builds preserve that owner: `make diagrams` reads it and rejects a conflicting `DIAGRAM_OWNER` override. Draw.io uses Draw.io Desktop (`DRAWIO_DESKTOP_BIN` can select its executable). A native OmniGraffle project includes a complete guarded runtime under `scripts/omnigraffle-tools/`, with no plugin-cache dependency. Other owners retain the project-local `FIGURE_DIAGRAM_EXPORTER` contract (`--owner OWNER --source FILE --svg OUT --pdf OUT`). Keep the selected editable sources in `figures_src/diagrams/`; missing tools, sources and exports fail the build.

For an OmniGraffle project, run `make init-diagram TEMPLATE=architecture WIDTH=double` (or `timeline`/`mechanism`, `single`/`double`). For a custom positive width, use `python3 scripts/init_omni_diagram.py --template architecture --width-in 4.2`; a layout that cannot fit fails without shrinking text. Initialization creates a new seed JSON, palette provenance, and editable native `.graffle`; it refuses existing destinations. For an app blocked during preparation, `python3 scripts/init_omni_diagram.py --template architecture --width double --prepare-only` writes the source and a guarded create request without dispatching; use that same request after resolving the blocker. A failed or uncertain native operation leaves its request in private local state for reconciliation. The saved `.graffle` is authoritative for `make diagrams`, so manual edits and linked equations survive regeneration. Initialization requires a responsive OmniGraffle installation; a blocked app produces no claimed native source.

OmniGraffle export uses the copied guarded CLI to inspect and fingerprint each one-canvas source, then stages PDF, SVG, PNG and a verification report. Before dispatch, it reads the installed export dictionary without application commands. If SVG is advertised, it attempts native SVG and treats any uncertain outcome as a blocker requiring reconciliation. Observed native SVGs with unitless dimensions receive point units only when both dimensions and the view box match the saved canvas within 0.01 in; the coordinate system and text sizes remain unchanged. The report retains native export verification, harmless document-type sanitization, physical-unit normalization, and text-outline decisions. If SVG is not advertised, project-local Poppler `pdftocairo -svg` converts the verified PDF and the report marks text as outlined. Poppler `pdfinfo`, `pdffonts`, `pdftotext`, and `pdftoppm` are required for width, font, glyph and PNG checks. PDF and SVG widths must agree within 0.01 in and match the saved `.graffle` canvas. The exporter stages every source before replacing prior files. It never reads seed JSON during regeneration; manual native changes remain authoritative. Visual inspection of native outputs remains required.

If you scaffolded with `--plots-only`, add native diagram sources before running `make diagrams` or `make figures`. A native timeout requires reconciliation of the printed operation ID before another mutation.

Use the layout, data, and typography rules in the [research style guide](https://github.com/jialuohu/codex-toolbox/blob/main/plugins/diagram-tools/skills/paper-figure-workflow/references/research-style.md) when adapting these examples. The copied plots and helpers have no runtime dependency on the toolbox or plugin cache. Keep this source directory and the selected editable diagram files in version control; generated `figures/` files can be rebuilt.
