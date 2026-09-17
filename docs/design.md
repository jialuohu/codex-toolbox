# Design, photos, and presentations

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Design Engineering Tools](#design-engineering-tools)
- [Photo Tools](#photo-tools)
- [Stevens Presentation Tools](#stevens-presentation-tools)

## Design Engineering Tools

The default `design-engineering-tools` plugin supplies focused guidance for
motion vocabulary, Apple-like interaction, focused design craft, motion
discovery, and animation audits. `review-animations`, `pick-ui-library`, and
`prototype` are explicit-only skills; broad page or component visual design,
layout, typography/color, and accessibility remain the `ui-ux-pro-max` default.
Project conventions, explicit user direction, accessibility, and current
official documentation override imported opinions.

The skills adapt the MIT-licensed
[emilkowalski/skills](https://github.com/emilkowalski/skills) snapshot at commit
`70744e3816f1d93eafb697161a8b880a7384c5ff`; they are an unofficial,
non-affiliated adaptation. Start a fresh Codex task after installing or
upgrading so the plugin is available to the task from its start.

## Photo Tools

The default `photo-tools` plugin provides `$mono-color` and
`$rubber-stamp-travel-poster`.

Use Mono-Color for research graph color-pick requests or its full one/two-ink
editorial image workflow. Color selection returns exact HEX values and
suggested roles, while existing plotting and diagram tools handle scientific
figures. It preserves explicit colors and supports more than two graph series
without imposing poster styling. Editorial requests produce the image, exact
production prompt, and recipe; prompt-only requests skip generation.

```text
Use mono-color to create a duotone poster.
Pick mono-color colors for this research graph.
```

The workflow preserves the MIT-licensed
[mono-color-skill](https://github.com/yanliudesign/mono-color-skill) snapshot at
`c8ff70597ddedcd65f21a0b528f6a70c35690b0a`; separately licensed example artwork
is linked rather than bundled. See [provenance and validation](../plugins/photo-tools/PROVENANCE.md).
Start a fresh Codex task after installing or upgrading Photo Tools.

Give Rubber Stamp Travel Poster one or more travel photos to create a separate
4:3 landscape journal poster for each: the photograph occupies the left half,
and a small rubber stamp drawn from that scene sits on aged paper on the right. The workflow
preserves the original subjects, uses two to four source colors, and checks
layout, photo fidelity, print texture, and restrained English field notes.

```text
Use $rubber-stamp-travel-poster to make one independent poster for each attached photo.
```

Location names, entry numbers, and years can be supplied with the photos.
Uncertain places receive descriptive scene labels; missing capture years use
a labeled journal year. The skill uses Codex's built-in image editing, requires
no additional MCP or credentials, and reports unresolved preservation or text
errors rather than promising pixel-identical output.

## Stevens Presentation Tools

The default `stevens-presentation-tools` plugin provides reusable 16:9 Stevens
PowerPoint templates, a compact theme gallery, and a local-PPTX-first workflow
for native Google Slides delivery. `$stevens-slides` selects White unless a
theme is named; `$stevens-slides-white` and `$stevens-slides-dark` select a
theme explicitly.

| Theme | Intended use | Core treatment |
|---|---|---|
| White | General presentations and research updates | White canvas, Dark Gray text, Stevens Red accents |
| Dark | Technical and systems talks | Dark Gray canvas, white text, gold/orange/blue data accents |

Both themes preserve the same 17 named layouts and editable exemplars. The
bundled manifest, brand references, checksums, fonts, official identifiers,
source template, and validation script form the reusable authoring contract.
Generated decks start from a bundled PPTX, preserve inherited layouts, add
`[Sources]` speaker notes, verify locally, and then use native Google Slides
conversion when Slides is the requested destination.
