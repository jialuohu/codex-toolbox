---
name: paper-figure-workflow
description: Use when Codex needs to create, review, or repair reproducible AI/systems paper figure workflows with editable draw.io or diagrams.net pipeline diagrams, Matplotlib and SciencePlots experimental plots, SVG/PDF exports, Inkscape cleanup, figures_src/, figures/, Makefile targets, or publication-quality vector figures.
---

# Paper Figure Workflow

## Overview

Build figure workflows that another researcher can rerun and manually edit. Inspect the target repo first, keep source files editable, export vector SVG and PDF, and add one simple regeneration command.

## Repo Inspection

Before editing, identify:

- Existing paper directories, figure folders, plotting scripts, notebooks, Makefiles, dependency files, and data files.
- Existing naming conventions for figure outputs and source artifacts.
- Whether draw.io, diagrams.net, Inkscape, Python, Matplotlib, SciencePlots, pandas, or repo-specific plotting tools are already documented.

Prefer the repo's conventions when they are clear. Otherwise use `figures_src/` for editable sources and `figures/` for generated outputs. Use no hard-coded absolute paths.

## Diagram Workflow

Use draw.io or diagrams.net for AI/ML/system pipeline and architecture diagrams.

- Keep `.drawio` source files under the chosen source directory.
- Use clean vector shapes, consistent alignment, limited color, readable labels, and publication-scale spacing.
- Export final diagrams as both SVG and PDF under the generated figure directory.
- Use the draw.io CLI when available; manual export is acceptable when the repo documents it.
- Use Inkscape for conversion, validation, or light cleanup when useful.
- Do not rasterize unless the user explicitly asks or a specific source asset requires it.

## Plot Workflow

Use Python with Matplotlib and SciencePlots for experimental result figures.

- Generate plots from existing repo data or scripts when available.
- Keep plotting code readable, parameterized, and deterministic.
- Use `import scienceplots` before `plt.style.use(...)`.
- Default to `plt.style.use(['science', 'no-latex'])` unless the repo already uses LaTeX fonts.
- Save each final plot as SVG and PDF with consistent size, font sizes, axis labels, and legends.
- Avoid unnecessary decoration, 3D effects, heavy grids, and raster-only outputs.

## Automation And Docs

Add or update the smallest reproducible command:

- Prefer `make figures` when the repo already has a Makefile or simple shell workflow.
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
- Generated outputs are not manually patched in ways that cannot be reproduced.
- The final response identifies the regeneration command and any dependency gap.

## Reference

Read `references/templates.md` when adding new figure commands or plotting scripts.
