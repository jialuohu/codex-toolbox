---
name: paper-figure-workflow
description: "Use for reproducible AI/systems paper figures: editable native workflow diagrams, experimental plots, vector exports, and publication build/verification workflows."
---

# Paper Figure Workflow

## Overview

Build figure workflows that another researcher can rerun and manually edit. Inspect the target repo first, keep source files editable, export vector SVG and PDF, and add one simple regeneration command.

Before scaffolding or any app access, read [UI cleanup](references/ui-cleanup.md) and capture initial state without launching apps. Auto owner selection can launch OmniGraffle through its readiness probe; cleanup also applies after a fallback or failure.

For **new research figures**, apply each setting in this order: explicit user request, project or venue convention, research default, then general default. Existing figures keep their style unless restyling is requested. Read `references/research-style.md` for the inspected-paper citations, visual composition, and data contracts. Do not treat the examples as measured results.

## Repo Inspection

Before editing, identify:

- Existing paper directories, figure folders, plotting scripts, notebooks, Makefiles, dependency files, and data files.
- Existing naming conventions for figure outputs and source artifacts.
- Whether OmniGraffle, draw.io, diagrams.net, Inkscape, Python, Matplotlib, SciencePlots, pandas, or repo-specific plotting tools are already documented.

Prefer the repo's conventions when they are clear. Otherwise use `figures_src/` for editable sources and `figures/` for generated outputs. Use no hard-coded absolute paths.

## Diagram Workflow

Explicit application choice takes precedence, followed by the existing artifact format and project or venue convention. Delegate OmniGraffle or `.graffle` to `$omnigraffle-workflow`; delegate draw.io, diagrams.net or `.drawio` to `$drawio`. Following **native acceptance** of all three template families through save, reopen, edit and PDF/SVG export, prefer OmniGraffle for new research architecture, workflow and mechanism diagrams without a selected owner. For a new unowned request, a fresh `doctor --probe-app` must report `scripting.status=responding` and advertised PDF export; if drawing readiness fails, disclose Draw.io fallback before native dispatch and record its reason. Explicit OmniGraffle, existing `.graffle` sources and recorded project owners retain ownership during an app blocker. Ordinary workflow-map routing remains `$archify`.

The accepted [native workflow](../../../omnigraffle-tools/ACCEPTANCE.md) includes genuine LaTeXiT editing after both apps restarted, verified in the user's foreground Terminal. This acceptance does not grant another caller access: SSH-to-System Events remained denied in the tested profile. Drawing readiness checks do not establish equation GUI readiness. Verify the current caller's unlocked desktop, System Events access and LaTeXiT controls before equation operations; report blocked native output while preserving the selected owner.

- Preserve native `.graffle` sources when OmniGraffle owns drawing. Scaffold with `--diagram-owner auto|omnigraffle|drawio`; the resolved owner is recorded in `figures_src/diagram-owner.json` and later builds reject a conflicting override. The copied guarded runtime retains the shared application lock and journals. Initialize a native source separately with `make init-diagram TEMPLATE=architecture WIDTH=double`; `make diagrams` exports the saved native document and never replays its seed JSON.

- Use `$drawio` for native `.drawio` creation, page-level MCP inspection or edits, browser opening, specialized shape search, and Desktop export. This skill owns publication directories, regeneration commands, and cross-figure checks.
- Keep native source files under the chosen source directory.
- Use clean vector shapes, consistent alignment, limited color, readable labels, and publication-scale spacing.
- Use white backgrounds, pale groups, short action labels, numbered operations, and resource-state detail where it explains a mechanism. Align baseline/proposed states on shared rows. Label schematic timelines as schematic; attach measured units only to measured timing.
- Export final Draw.io diagrams as SVG and PDF. For OmniGraffle, retain the editable `.graffle`, export verified PDF and native SVG when supported, or convert verified PDF with the copied project-local Poppler command and report SVG text outlining. Generate a PNG gallery preview. Stage and validate outputs before replacing prior exports; a missing dependency or output fails the build.
- Use the `$drawio` Desktop helper when Draw.io owns drawing and it is available; manual export is acceptable when the repo documents it.
- Use Inkscape for conversion, validation, or light cleanup when useful.
- Do not rasterize unless the user explicitly asks or a specific source asset requires it.

## Plot Workflow

Use Python with Matplotlib and SciencePlots for experimental result figures.

- Generate plots from existing repo data or scripts when available.
- When no project convention exists, scaffold the project-local starter with `scripts/scaffold_research_figures.py`. The four templates cover grouped bars, line/scaling, empirical cumulative distributions, and additive stacked breakdowns. Copy the helpers, style, method mapping, examples, pinned requirements, and Makefile; regeneration must not depend on plugin-cache paths.
- Keep plotting code readable, parameterized, and deterministic.
- Use `import scienceplots` before `plt.style.use(...)`.
- Default to `plt.style.use(['science', 'no-latex', project_style])` unless a project or venue overrides it. Use the portable DejaVu Sans baseline. The starter records any font substitution, retains editable SVG text, and checks PDF font embedding.
- Save each final plot as SVG and PDF with consistent size, font sizes, axis labels, and legends.
- Default to 3.3-inch or 6.9-inch widths, 8-point body text, and at least 7 points after final placement; explicit venue requirements win. Keep `--data`, `--out-dir`, and `--width single|double`; use a mutually exclusive positive `--width-in` for custom widths. Use `bbox_inches=None` so the canvas width remains fixed.
- Declare method order and color/marker/hatch/line mappings once for the figure set. Reordering or omitting data series must not change other methods' appearances. Reject unregistered or indistinguishable methods.
- Use raw observations for empirical distributions and explicit values for other templates. Missing line values stay gaps; incomplete stacks and incompatible units fail. Aggregate, normalize, or interpolate only when explicitly specified. Empirical cumulative distributions plot the fraction of observations at or below each value, including ties.
- Uncertainty must identify bounds, statistic, interval type, calculation method, sample count, and confidence level for confidence intervals. Validate that each estimate lies inside its bounds.
- Avoid unnecessary decoration, 3D effects, heavy grids, and raster-only outputs.

## Automation And Docs

Add or update the smallest reproducible command:

- Prefer `make figures` when the repo already has a Makefile or simple shell workflow.
- The starter exposes `make plots`, selected-owner `make diagrams`, and aggregate `make figures`; missing dependencies must fail rather than accepting stale exports.
- Otherwise add a clearly named script such as `scripts/build_figures.sh`.
- Document required dependencies briefly in README, paper notes, or the repo's existing setup docs.
- Research current tool usage or documentation if a command option is uncertain.
- Check that the generated figures build successfully before claiming completion.

## Quality Bar

For AI/systems paper figures:

- Source files stay editable and version-controlled.
- Final outputs are vector SVG and PDF unless explicitly impossible.
- Text and shapes remain editable where possible.
- Figure dimensions and naming are consistent across related plots.
- Verify SVG and PDF widths within 0.01 inch, effective text size, PDF font embedding, glyphs, labels, overlaps, arrow direction, and grayscale distinguishability at final size. Editable SVG text depends on fonts installed by the recipient.
- Generated outputs are not manually patched in ways that cannot be reproduced.
- The final response identifies the regeneration command and any dependency gap.
- After verification, return source/export links and close owned saved idle previews. Retain requested open/show/keep-open deliverables or active interactive handoffs, following the cleanup reference and selected native owner's guards.

## Reference

Read `references/templates.md` when adding new figure commands or plotting scripts.
