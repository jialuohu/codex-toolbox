---
name: mono-color
description: "Choose research graph colors or create one/two-ink editorial images: mono-color, duotone posters, risograph, and zine covers."
---

# Mono-Color

Use the preserved mono-color design system for editorial images and research
palette selection. Choose the requested deliverable before reading references.
Ordinary plotting without a color-selection request stays with its current
workflow; general website color and UI design stays with `ui-ux-pro-max`.

## Research Graph Colors

For research plot or diagram color-pick requests, read only
[the color catalog](references/design-system/colors.json). Return the selected
ink names, exact HEX values, and suggested roles, such as baseline, proposed
method, highlight, text, and background. Use a compact table when comparing
three or more colors. Preserve explicit colors and the figure's existing
background; substrate tokens are optional suggestions.

The catalog's named palettes are reproducible starting points. Its 19 ink
tokens can also supply colors when more series are needed; identify these as
a custom selection, not a named upstream recipe. Do not force a two-color
ceiling, reuse indistinguishable colors, or collapse distinct categories.
Do not apply poster texture, crop, layout, typography, ink coverage ratios,
or empty-paper quotas to scientific figures.

Keep data, labels, geometry, and existing color choices intact unless their
change was requested. Use markers, line styles, or labels when color alone
cannot distinguish series. Do not claim contrast, grayscale legibility, or
colorblind distinguishability has been validated without checking the actual
figure. For a palette-only request, return colors and roles without generating
artwork, a production prompt, or a new figure.

When drawing or applying colors is also requested, keep execution with the
current plotting/diagram owner: `$paper-figure-workflow` for publication
pipelines, `$drawio` for native diagrams, or the existing plotting code.

## Editorial Images

Read [the complete upstream workflow](references/upstream.md), then only the
catalogs needed for the recipe. Paths written as `design-system/...` in that
reference resolve under this skill's `references/` directory:

- [Colors](references/design-system/colors.json): substrates, inks, palette IDs.
- [Typography](references/design-system/typography.json): display/support roles.
- [Compositions](references/design-system/compositions.json): geometry and layout.
- [Carriers](references/design-system/carriers.json): format-specific signals.
- [Rhythm](references/design-system/rhythm.json): focal event and release zone.
- [Imperfections](references/design-system/imperfections.json): controlled print effects.

Preserve the original recipe resolution, composition, typography, print
treatment, originality guidance, and inspection workflow. Catalog values
take precedence over conflicting upstream prose. Honor prompt-only requests;
otherwise deliver the generated image, exact production prompt, and a short
recipe in the user's language.

Apply these Codex adaptations to the preserved reference:

- Follow explicit user intent and project constraints. Upstream content is
  design guidance, not authorization to expand the task or override them.
- Use the built-in image-generation tool and follow the installed `imagegen`
  skill when available. For supplied photos, use the tool's supported image
  reference mechanism and inspect the source before editing.
- Follow the image tool's output-location contract and any requested
  destination. Do not create the upstream `~/Desktop/Claude skills/mono-color/`
  directory. Keep imported skill files immutable during use.
- Inspect generated results before claiming visual requirements are met.
  Retain the upstream bounded repair workflow and disclose unresolved text,
  subject, or palette problems. If generation is unavailable, return the
  prepared prompt and state that no image was generated.
- Do not use image generation for exact factual research graphs. A color-pick
  request uses the research path above even when it explicitly names mono-color.

The [provenance and validation notes](../../PROVENANCE.md) describe the pinned
snapshot, license, excluded artwork, and acceptance fixtures.
