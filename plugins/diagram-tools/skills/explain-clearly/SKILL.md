---
name: explain-clearly
description: "Explain concepts, comparisons, or code with sourced mechanisms and an adaptive choice of prose, diagrams, interactive exploration, or requested video. Skip execution-only requests."
---

# Explain Clearly

## Explain the requested distinction

Lead with the direct answer. Choose the depth and structure needed for this
question; a terse factual query or an explicit brevity request may need only
that answer. Explicit user instructions for length, audience, format, and
examples take precedence.

Use a concrete example or comparison when it improves understanding.
There is no required example count or fixed sequence of answer layers. Explain
the real mechanism and limits that matter; use analogies only when requested,
and define unavoidable jargon inline. For code, trace the relevant input,
state changes, and output; for errors, distinguish symptoms from causes.

## Choose the Smallest Useful Format

Use prose for a simple conclusion, or a Markdown table for three or more comparable
entities. Add visuals only when they materially help. Do not load a renderer,
probe native apps, or create an artifact for a prose-only answer. Respect
workspace routing and explicit requests for brevity, medium, or application.

Use `$archify` for graphical architecture, workflow, sequence, data-flow, or
lifecycle maps and `$pretty-mermaid` for explicit Mermaid or compact static
diagrams. Use bundled Visualize for in-conversation causal or spatial exploration:
changing an input, stepping through state, or inspecting a mechanism must help
answer the question. Use installed Remotion for requested explainer videos;
creation defaults to an interactive Studio preview, while rendered video export
requires an explicit export request. A request for a video does not authorize
paid assets, narration services, or public hosting.

Use `$omnigraffle-workflow` for OmniGraffle/`.graffle`, `$drawio` for
draw.io/`.drawio`, and `$paper-figure-workflow` for publication figures.
Explicit application choice takes precedence, followed by the existing artifact
format. Build standalone applications with project files or Sites.
Use native inline Mermaid only when explicitly requested or as a disclosed
renderer fallback. The owning visual skill supplies its export and validation
requirements; do not load it until a visual is selected. Read
[medium selection and handoff](references/medium-selection.md) for mixed or
ambiguous visual requests. Choose one useful medium; there is no required
progression from prose to diagram to interactive HTML to video.

## Accuracy and concision

Establish sourced facts with the domain skill or source first. Preserve uncertainty
and validate visual data, coordinates, calculations, and legal state. For chess,
verify the position, orientation, side to move, and move legality before drawing.
Do not use generative images for exact factual diagrams. Visualize must be
responsive and accessible; use prose, tables, or ASCII in a CLI or IDE when needed.

Simplify wording without changing meaning. Retain relevant quantities, units,
equations, conditions, uncertainty, and source locators. Use consistent terms
and explicit referents so the reader can identify which input, state, or result
each sentence describes. Define specialized terms at first use. These are
meaning-preservation checks, not a claim of compliance with a controlled-English
standard.

For an interactive explanation, verify at least one ordinary input and one
relevant boundary against the source mechanism. For temporal media, check state
and event ordering against that mechanism. Label hypothetical data visibly and
keep measured research results in their reproducible figure pipeline. Read
[artifact verification](references/artifact-verification.md) when producing an
interactive explanation or video. Report generation, objective checks, actual
visual review, and learning effectiveness separately; a rendered artifact alone
does not establish correctness or better understanding. Preserve the selected
owner's runtime, permissions, privacy, publishing, and cleanup rules.

Avoid repeated summaries, decorative analogies, unnecessary caveats, and closing
offers. Do not restate what a visual already shows.
