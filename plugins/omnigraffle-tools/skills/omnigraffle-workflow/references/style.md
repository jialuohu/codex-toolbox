# Research figure composition

Apply these defaults to **new research figures**. An explicit request overrides a
project or venue convention, which overrides this research guidance, which
overrides the general diagram default. Preserve an existing figure's style
unless restyling was requested. The [FineMoE architecture](https://arxiv.org/pdf/2502.05370v2),
[Stellaris workflow](https://intellisys.haow.us/assets/pdf/SC41406.2024.00045.pdf),
[RainbowCake timeline](https://intellisys.haow.us/assets/pdf/hanfei-asplos24spring.pdf),
and [Nitro workflow](https://www.vldb.org/pvldb/vol18/p66-yu.pdf) are visual
references for composition, not reusable art or evidence for a new system.

- Start with a white full-canvas background shape, pale component groups,
  white or very light native shapes, dark text, and one restrained accent per
  semantic role. Use the supported native `shape_type`, `fill`, `stroke`,
  `stroke_width`, `stroke_pattern`, text color/alignment/padding, and whole-point
  font size. Solid and dashed outlines are available; arbitrary opacity and
  hatch patterns are not part of this contract.
- Compose at the final 3.3- or 6.9-inch canvas width, using Helvetica/Helvetica
  Bold at 8 pt with a 7 pt minimum unless the venue specifies otherwise. Do
  not silently shrink text to fit a custom width. Record font substitutions
  from saved native readback and inspect glyph coverage. Use an installed
  CJK-capable font for Chinese text and visually verify glyphs.
- Repeat node dimensions, padding and alignment. Place input, processing,
  memory/cache, and output along a clear reading path; group only real
  component boundaries. Use short action labels and numbered operations when
  order matters. A memory or cache icon should show the actual unit and state
  (for example, model layers in GPU memory), with a legend if colors encode
  residency or reuse. Do not turn a generic cylinder into a quantitative claim.
- Align baseline and proposed timelines on the same lanes and state labels.
  Give measured axes units and source data; label a purely illustrative
  timeline **schematic**. Keep comparisons at matched scale and explain any
  changed stage count or state encoding.
- Route each arrow according to an actual dependency and inspect direction. The
  adapter supports straight and native-managed orthogonal routing, endpoint
  side midpoints, and explicit arrowheads. Native creation currently places
  connectors above shapes; leave clear paths around components and labels. Do not
  invent edges, measurements or execution claims. Keep legends near the
  reading start and distinguish numbered steps from component-type badges.
- Preserve semantic method colors across a figure set. Record method-to-color
  assignments in project-local source and keep them stable when methods are
  reordered or absent. If native shapes cannot provide a second channel such
  as hatching, use labels, separate panels, or another supported tool rather
  than relying on similar colors.
- Align equations and prose by visible baselines. Preserve exact notation,
  source, preamble, mode and separately editable LaTeXiT identity; do not
  flatten equations into a background image. Inspect arrowheads, joins,
  clipping, equations and text at final publication size.

The [research template sources](../../../assets/research-templates/README.md)
provide three synthetic native compositions at both publication widths. The
project source stores exact geometry and semantic encodings, with a sibling
palette sidecar. Saved `.graffle` documents are authoritative after creation.
The publication pipeline owner sets regeneration commands. Never treat an
approximate SVG preview as evidence of native appearance or editability.

English, Chinese and mixed instructions have equal status. Preserve an
existing figure's language unless translation is requested. Example:
“统一 node margin 和 icon alignment，图内 labels 保留英文” changes geometry while
retaining English labels.
