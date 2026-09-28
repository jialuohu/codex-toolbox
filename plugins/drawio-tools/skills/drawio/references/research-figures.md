# Editable research-diagram composition

This is a default for **new research figures**. Per setting, use the explicit
request first, then project/venue conventions, then this research default, then
the general diagram default. Preserve existing figures unless asked to restyle.

The composition is informed by the inspected [FineMoE Figure 5](https://arxiv.org/pdf/2502.05370v2),
[Stellaris Figure 4](https://intellisys.haow.us/assets/pdf/SC41406.2024.00045.pdf),
[RainbowCake Figures 4–5](https://intellisys.haow.us/assets/pdf/hanfei-asplos24spring.pdf),
and [Nitro Figure 6](https://www.vldb.org/pvldb/vol18/p66-yu.pdf). Adapt their
use of groups, numbered operations, aligned states, and mechanism insets; do
not copy artwork or claim their measurements for a new system.

## Source templates

| Source | Use | Required changes |
| --- | --- | --- |
| `assets/research-templates/architecture-overview.drawio` | Roles and numbered operations | Replace roles, topology, operation labels, and cache layers with verified system facts. |
| `assets/research-templates/execution-timeline.drawio` | Baseline/proposed event sequence | Keep the two timelines aligned. Replace every state and event. The template is schematic: equal columns imply no elapsed time. |
| `assets/research-templates/cache-memory-mechanism.drawio` | Layer placement, transfer, or cache policy | Replace layers and memory tiers. Delete the optional vector inset unless it helps explain a mechanism. Its values are synthetic. |

All cells, including arrows, cache blocks, inset axes, line segments, and
markers, remain editable native Draw.io objects. Copy the `.drawio` sources
into the research project before editing. Keep the copied sources even when
exporting SVG/PDF/PNG. The XML comment and adjacent template README record
the selected palette and source; retain them with the figure source.

Use white backgrounds, pale enclosing groups, charcoal labels, and only a few
semantic accents. Keep labels short, use consistent alignment and arrow
direction, and number operations in actual execution order. Draw real memory
tiers as separate groups and individual cached objects as discrete blocks;
do not use a generic cylinder when residency or transfer is the point. The
template canvases are 1240, 1410, and 1280 px wide, respectively. Their
smallest source type is 18, 20, and 19 px; at a 6.9-inch final placement, that
is at least 7 pt under a linear SVG viewBox scale. Inspect the actual export at
final size for clipping and overlap. For a 3.3-inch placement, simplify and
recompose the diagram rather than shrinking the double-column template. An
explicit venue size or type rule takes priority.

For a measured timeline, replace the schematic event headings with a numeric
axis, units, data provenance, and true interval widths. Do not infer durations
from the schematic equal-width columns. In the optional inset, replace every
synthetic point from explicit data before presenting it as a measured result.
The inset is a mechanism aid, not a substitute for the reproducible plot
scripts owned by Paper Figure Tools.

Export a selected project-owned `.drawio` source with the Desktop helper, for
example:

```bash
plugins/drawio-tools/scripts/drawio-desktop.sh --export svg \
  /absolute/project/diagrams/architecture-overview.drawio \
  /absolute/project/figures/architecture-overview.svg
```

For a project `make diagrams` target, select Draw.io explicitly and fail if
Desktop is missing or any export fails. Do not accept an older exported file as
success after an error. Preserve the Archify owner's validation, delivery,
and visual-review gates when that owner is selected instead.

For gallery inspection when Desktop is unavailable, the bundled portable
preview can read **project copies** of these three template files:

```bash
python3 plugins/drawio-tools/scripts/preview-research-templates.py \
  --source-dir /absolute/project/diagrams \
  --out-dir /absolute/project/preview
```

Its `*.preview.svg` outputs carry a visible **PORTABLE PREVIEW ONLY** footer.
It supports only the simple cells used by these templates. It is not a native
Draw.io export and does not verify Draw.io text wrapping, font substitution,
arrow routing, embedded source, or final publication appearance. Keep native
export failure visible; never let preview generation satisfy `make diagrams`.
