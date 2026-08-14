# Delivery workflow

## Authoring

1. Read `template-manifest.json` and select the theme asset.
2. Import the bundled PPTX with `@oai/artifact-tool`.
3. Plan every output slide against an archetype and duplicate the inherited
   exemplar slide. Preserve its master/layout assignment and edit its native
   placeholders, charts, tables, text, and images in place.
4. Keep visible copy audience-facing. Add `[Sources]` speaker-note blocks and
   remove stale exemplar content.
5. Establish the final slide set and order before visual QA; delete the template
   index and unused exemplars last.

## Local verification

- Render every slide and inspect each full-size image.
- Run overflow, placeholder, contrast, font, asset-checksum, and PPTX-structure
  checks. Repair clipping, unintended overlap, unresolved prompts, missing
  layouts, altered marks, and unreadable charts or tables.
- Confirm titles use no more than two lines and body text was shortened before
  any font reduction.

## Native Google Slides

For a net-new native deck, import the verified PPTX with
`mcp__codex_apps__google_drive_import_presentation` and
`upload_mode: "native_google_slides"`. Do not construct blank Slides directly.
Read back the native presentation, verify slide/master/layout counts and fonts,
export it once to PDF, and inspect every rendered page. Use at most two
consolidated repair passes. The untouched theme templates contain 18 slides,
2 masters, 39 layouts, and 18 notes slides; the gallery contains 5 slides,
2 masters, 22 layouts, and 5 notes slides. A generated deck may contain a
different planned slide count, but it must preserve the inherited master and
layout hierarchy and retain one notes page per output slide.

If native import, readback, or export is unavailable, finish and verify the
local PPTX, keep it as the portable deliverable, and report the unavailable
native conversion as the sole blocker. Do not substitute a blank Slides deck.
