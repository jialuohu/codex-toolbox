# Editable research diagrams

These three `.drawio` files are uncompressed native sources. They contain
**schematic, synthetic examples**. Copy each source into the research project
before editing. The copied `.drawio` files are the editable project sources;
they do not need the toolbox template generator to regenerate exports. Keep
this README or the XML palette comment with the copied source.

The selected inks are Cobalt `#2148B8`, Terracotta `#C65F38`, Botanical Green
`#008A4B`, and Charcoal `#30343A`, copied from the toolbox's
`photo-tools/skills/mono-color/references/design-system/colors.json` catalog.
The light component fills are local tints. Regeneration uses these source-local
values and does not depend on the installed plugin cache or catalog. Preserve
color meaning across related figures and check grayscale distinguishability.

The timeline has equally spaced *events*, not a measured time axis. The
mechanism inset has optional, synthetic normalized values. Replace its points
from explicit data or delete the whole inset before presenting a measured
relationship. The source figures that informed the composition are listed in
the [FineMoE paper, Figure 5](https://arxiv.org/pdf/2502.05370v2),
[Stellaris, Figure 4](https://intellisys.haow.us/assets/pdf/SC41406.2024.00045.pdf),
[RainbowCake, Figures 4–5](https://intellisys.haow.us/assets/pdf/hanfei-asplos24spring.pdf),
and [Nitro, Figure 6](https://www.vldb.org/pvldb/vol18/p66-yu.pdf). These are
composition references, not sources for the synthetic template values.

To verify the checked-in templates without Draw.io Desktop:

```bash
python3 plugins/drawio-tools/scripts/build-research-templates.py --check
```

To export a project copy on a machine with Draw.io Desktop:

```bash
plugins/drawio-tools/scripts/drawio-desktop.sh --export svg \
  /absolute/project/diagrams/execution-timeline.drawio \
  /absolute/project/figures/execution-timeline.svg
```

For a gallery preview when Desktop cannot render, run
`python3 plugins/drawio-tools/scripts/preview-research-templates.py --source-dir
/absolute/project/diagrams --out-dir /absolute/project/preview` from the
toolbox checkout. Its labelled SVGs are approximate and do not replace a
native export or a final-size visual check in Draw.io.
