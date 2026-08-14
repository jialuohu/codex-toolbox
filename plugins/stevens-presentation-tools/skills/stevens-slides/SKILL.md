---
name: stevens-slides
description: Create, edit, restyle, or convert Stevens Institute of Technology presentations in PowerPoint or native Google Slides using the bundled White or Dark 16:9 theme templates. Use for Stevens-branded decks, university presentations, research talks, systems talks, slide templates, and theme selection; default to White when the user does not name a theme.
---

# Stevens Slides

## Select the theme

Use White unless the request explicitly names Dark. If a theme-specific
Stevens skill invoked this workflow, keep that theme unless the user overrides
it.

Read [the template manifest](references/template-manifest.json), then read:

- [brand rules](references/brand-system.md) before planning or styling;
- [layout catalog](references/layout-catalog.md) when mapping slide roles;
- [delivery workflow](references/delivery-workflow.md) before authoring;
- [source notes](references/source-notes.md) when citing or redistributing assets.

## Build the deck

1. Use the Presentations skill for local PPTX work and net-new Google Slides.
2. Start from the selected bundled PPTX. Do not construct a blank Google Slides
   deck or flatten inherited masters and layouts.
3. Map every planned slide to one manifest archetype. Duplicate the matching
   exemplar, preserve its layout, and replace inherited placeholders and
   editable objects in place. Delete the template index and unused exemplars
   only after the final slide order is verified.
4. Keep geometry stable across themes. Use Saira Condensed for titles and IBM
   Plex Sans for narrative copy. Shorten copy or choose another archetype before
   shrinking type.
5. Add a `[Sources]` block to every slide's speaker notes for externally sourced
   claims and assets. Mark illustrative template data as illustrative.
6. Verify the PPTX locally, then import it with native Google Slides conversion
   when Google Slides is the target. Never build a blank Slides deck directly.

Run `scripts/check_templates.py` when modifying the bundled templates or brand
assets. Do not recolor, redraw, stretch, or combine the official identifiers.
