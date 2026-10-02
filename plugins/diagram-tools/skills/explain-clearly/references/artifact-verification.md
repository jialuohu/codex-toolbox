# Verify the explanation separately from its presentation

Use the owning renderer's checks and inspect the actual delivered result.
Retain editable source and supporting evidence. Never promote a successful
write, build, screenshot capture, or schema check into a claim that people
understand the explanation better.

For an interactive mechanism, choose at least one ordinary case and one
relevant boundary from the inspected source. Calculate expected outputs
independently of the presentation code. Operate the controls and compare the
displayed result and state with those expectations. Verify reset/step behavior
when present. Inspect at narrow and ordinary widths, keyboard operation, labels,
units, a text alternative, and reduced-motion behavior when there is motion.
Record unavailable checks as unverified, not passed.

For requested video, compare the rendered or previewed scene sequence with the
sourced event order and expected states. Check transitions at scene boundaries,
readable labels, timing, captions when needed, and source attribution. Verify
the output duration and format for an export. A preview check does not verify
an exported file; export success does not establish that the scenes are correct.

For publication figures, use Paper Figure Workflow's data, uncertainty,
dimensions, font, vector-export and regeneration checks. For fixed diagrams,
inspect the final-size labels, topology, arrowheads and clipping using the
selected owner's proportionate checks. Keep this process small for a simple
diagram; do not require a video-style evaluation for ordinary prose.

## Repository acceptance fixture

`plugins/diagram-tools/scripts/eval-explanation-artifacts.py` runs the checked-in
synthetic queue example in a JavaScript runtime and compares its actual outputs
with independently calculated event times. It also checks an exported SVG's
labels and diagram relationships against the source trace. Mutation tests prove
the evaluator rejects an incorrect completion time and a reversed dependency.
This is an offline regression fixture, not a universal explanation grader.

Its receipt explicitly leaves browser interaction, visual review, and learning
effectiveness unverified. The separate optional
`plugins/diagram-tools/tests/explanation-browser-evidence.mjs` operates the
synthetic HTML fixture with an already available browser, including keyboard
input/reset and narrow light/dark layouts. That browser receipt still requires
actual screenshot review and does not establish learning effectiveness.
Generated user artifacts require their own cases and actual inspection. The
fixture's passing receipt does not validate arbitrary HTML, SVG, or video and
does not establish better comprehension.
