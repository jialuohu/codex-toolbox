# Research composition with Diagram Tools

These are defaults for **new research figures** when Mermaid or Archify is the
selected owner. Apply each setting in this order: explicit request, project or
venue convention, research default, general default. Preserve existing
diagrams unless restyling is requested. The purpose is a readable research
composition, not a new renderer, preset, or data format.

The inspected [FineMoE](https://arxiv.org/pdf/2502.05370v2),
[Stellaris](https://intellisys.haow.us/assets/pdf/SC41406.2024.00045.pdf),
[RainbowCake](https://intellisys.haow.us/assets/pdf/hanfei-asplos24spring.pdf),
and [Nitro](https://www.vldb.org/pvldb/vol18/p66-yu.pdf) figures motivate
numbered operations, grouped components, aligned comparisons, visible
memory/cache state, and short labels. They are visual references; draw each
new figure from its own evidence and retain its own source.

## Pretty Mermaid

Use existing CLI flags for an ordinary white-page research treatment:

```bash
pretty-mermaid render \
  --input figure.mmd --output figure.svg --format svg \
  --theme github-light --font 'DejaVu Sans' \
  --bg '#FFFFFF' --surface '#F3F5F7' --fg '#30343A' \
  --line '#607080' --border '#C7D1D9' \
  --accent '#2148B8' --muted '#65717A'
```

The values above are starting points. The cobalt ink is from Mono-Color's
[`ink_cobalt`](../../photo-tools/skills/mono-color/references/design-system/colors.json)
catalog entry; the neutral grays are local presentation choices. If Mono-Color
selects a different palette, pass its exact HEX values through the same
supported flags and record them beside the `.mmd` source. The font flag names
a recipient font; inspect substitutions and glyph coverage on the actual
export. Pretty Mermaid does not expose publication font size or per-method
color/marker/hatch mappings through these flags.

Write topology with short action labels, explicit arrow direction, and
numbered steps only when order is real. Use Mermaid groups for actual system
boundaries. Label cache or memory state in text; a color alone does not explain
capacity, residency, or timing. For baseline/proposed comparisons, align the
same stages and states in the source, or use two clearly labeled panels.
Mark a qualitative timeline **schematic**. Measured time needs data, units,
and an appropriate plot or native diagram owner. Test the Mermaid family
with `capabilities`; do not rely on unverified syntax or silently change the
source when the renderer rejects it. Inspect final-size text, overlap,
arrowheads, and grayscale distinction. If method-specific encodings or exact
spatial alignment are required beyond these controls, use the selected native
diagram or publication figure owner.

## Archify

Use the type that matches the semantics: `architecture` for components and
boundaries, `workflow` for ordered operations, `sequence` for interactions,
`dataflow` for data movement, or `lifecycle` for state transitions. Compose a
single clear reading path with short labels, real boundaries, and an explicit
legend for any state encoding. Put long explanations in supported cards or
notes. When comparing baseline and proposed behavior, keep equivalent stages
and states in the same order and label a non-measured sequence **schematic**.
Number operations only when the typed source supports them without inventing
extra components or edges.

The active schemas accept `meta.visual_preset` values `classic`,
`signal-flow`, `blueprint`, and `editorial`. `editorial` is a reasonable
publication-style starting point; choose another existing preset if an
explicit request or venue fits it better. Presets only change viewer styling,
not semantics or geometry, and cannot guarantee a white canvas or a 7-point
minimum in a printed figure. Do not add unsupported palette, font, or
research-theme fields to the typed JSON. If a venue requires exact page
colors, physical dimensions, or font sizes, use an owner that supports those
controls. Preserve Archify's packaged schema validation, atomic delivery,
visual-check, actual visual review, and publication gates unchanged.
