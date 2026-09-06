---
name: explain-clearly
description: "Use for explanations, comparisons, teaching, or code walkthroughs when understanding needs more than a terse fact. Skip execution-only requests."
---

# Explain Clearly

## Explain the requested distinction

Lead with the direct answer. Choose the depth and structure needed for this
question; a terse factual query or an explicit brevity request may need only
that answer. Explicit user instructions for length, audience, format, and
examples take precedence.

Use a mental model, concrete example, or comparison when it improves understanding.
There is no required example count or fixed sequence of answer layers. Explain
the real mechanism and limits that matter, label an analogy as an analogy,
and define unavoidable jargon inline. For code, trace the relevant input,
state changes, and output; for errors, distinguish symptoms from causes.

## Choose the Smallest Useful Format

Use prose for a simple conclusion, or a Markdown table for three or more comparable
entities. Add visuals only when they materially help. Respect workspace routing;
otherwise use `$archify` for graphical maps, `$pretty-mermaid` for explicit
Mermaid or compact static diagrams, bundled Visualize for adjustable spatial
views, `$drawio` for native editable diagrams, and `$paper-figure-workflow` for
publication figures. Build standalone applications with project files or Sites.
Use native inline Mermaid only when explicitly requested or as a disclosed
renderer fallback. The owning visual skill supplies its export and validation
requirements; do not load it until a visual is selected.

## Accuracy and concision

Establish sourced facts with the domain skill or source first. Preserve uncertainty
and validate visual data, coordinates, calculations, and legal state. For chess,
verify the position, orientation, side to move, and move legality before drawing.
Do not use generative images for exact factual diagrams. Visualize must be
responsive and accessible; use prose, tables, or ASCII in a CLI or IDE when needed.

Avoid repeated summaries, decorative analogies, unnecessary caveats, and closing
offers. Do not restate what a visual already shows.
