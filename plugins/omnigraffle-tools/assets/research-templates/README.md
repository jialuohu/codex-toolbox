# Editable research diagrams for OmniGraffle

The template generator supplies three **original, fixed synthetic** diagrams in
single-column (3.3 in, 237.6 pt) and double-column (6.9 in, 496.8 pt) layouts:

| Template | Editable content | Visual reference |
| --- | --- | --- |
| `architecture` | Numbered request, scheduler, worker, and GPU-cache workflow with directed feedback | [FineMoE Figure 5](https://arxiv.org/pdf/2502.05370v2#page=5) |
| `timeline` | Aligned baseline/proposed state lanes and a shared state legend | [Stellaris Figure 4](https://intellisys.haow.us/assets/pdf/SC41406.2024.00045.pdf#page=4), [RainbowCake Figures 4–5](https://intellisys.haow.us/assets/pdf/hanfei-asplos24spring.pdf#page=5) |
| `mechanism` | CPU layer store, GPU residency slots, and request/output path; optional native-vector explanatory inset | [Nitro](https://www.vldb.org/pvldb/vol18/p66-yu.pdf) |

The examples borrow composition, not artwork, measurements, or claims. Every
timeline and cache block is labelled schematic. The optional inset has no
empirical data or numeric axes. Its axes, points, and segments are independent
native shapes and connectors. `workflow.json` remains the earlier one-canvas
starter; its CLI contract remains supported.

The six saved editable native starters passed native reopen, PDF/SVG/PNG
export and visual inspection after author metadata was removed from copies:

| Template | Single column | Double column |
| --- | --- | --- |
| Architecture | [architecture-single.graffle](native/architecture-single.graffle) | [architecture-double.graffle](native/architecture-double.graffle) |
| Execution comparison | [timeline-single.graffle](native/timeline-single.graffle) | [timeline-double.graffle](native/timeline-double.graffle) |
| Cache/memory mechanism | [mechanism-single.graffle](native/mechanism-single.graffle) | [mechanism-double.graffle](native/mechanism-double.graffle) |

[The native manifest](native/manifest.json) records source and export hashes,
dimensions, fonts, palette provenance, and the acceptance scope. Native labels,
shapes, connectors, IDs and flat groups remain editable. Copy a starter into a
new project-owned filename before editing; preserve existing project files.
The source generator below provides initialization specifications and reusable
components. Its portable previews remain approximate.

`python3 verify_research_starters.py` from the copied script directory verifies
the bundled archive integrity and recorded acceptance without calling an app.
It does not establish current application readiness or LaTeXiT editability.
SVG text remains editable and depends on the recipient's Helvetica fonts;
the accepted PDF exports have embedded fonts.

The source generator uses reusable primitives for pale regions, state blocks,
numbered operations, memory slots, legends, directed connectors, and flat native
heading groups. These are authored at final canvas size with 8 pt labels, a
7 pt minimum, and Helvetica/Helvetica Bold. A custom `--width-in` of at least
3.3 in expands the spaces between fixed-size components; it does not scale the
font or component sizes. Exactly 6.9 in selects the double-column composition.
Widths below 3.3 in or above the supported 12 in canvas fail with a fit
diagnostic. Explicit venue dimensions and fonts take precedence; recompose if
these layouts do not fit the venue.

From the copied project-local skill script directory, generate a source and
its adjacent palette-provenance record:

```bash
python3 research_workflow.py --template architecture --width double \
  source --out /absolute/project/diagrams/architecture.json
python3 research_workflow.py --template timeline --width single \
  source --out /absolute/project/diagrams/timeline.json
python3 research_workflow.py --template mechanism --width-in 7.2 --with-inset \
  source --out /absolute/project/diagrams/mechanism.json
```

`source` creates `<stem>.palette.json` beside each JSON source. It refuses to
replace either file. The sidecar records selected values and the mono-color
catalog provenance; regeneration reads the local source, not a plugin-cache
catalog. The exact HEX values are in `palette.json` in this directory. Cobalt,
terracotta, and charcoal are catalog inks; pale fills and hairlines are local
companions. Colors also have text, shape, and border encodings.

Validate and preview without opening OmniGraffle:

```bash
python3 research_workflow.py --spec /absolute/project/diagrams/architecture.json validate
python3 research_workflow.py --spec /absolute/project/diagrams/architecture.json \
  preview --out /absolute/project/previews/architecture.preview.svg
```

The optional `gallery --out-dir /absolute/empty/directory` writes six labelled
portable previews and an index. A portable preview approximates routing and
text; it cannot prove the saved native appearance.

Only after `omnigraffle.py doctor --probe-app` reports responsive document
access, prepare a fresh guarded creation request and invoke the creator:

```bash
python3 research_workflow.py --spec /absolute/project/diagrams/architecture.json \
  prepare --output /absolute/project/diagrams/architecture.graffle \
  --request-out /absolute/project/diagrams/architecture-create.json
python3 omnigraffle.py create \
  --request /absolute/project/diagrams/architecture-create.json
```

The preparer writes only request JSON. Never replay a pending operation after
an unknown outcome; use `reconcile`. The saved `.graffle` becomes authoritative
after creation. Export that saved source with the guarded CLI; do not replay
the seed JSON over later manual edits, flat native groups, or separately
editable LaTeXiT equations. Native create/save/reopen/export and actual figure
inspection are required before calling a template accepted.
