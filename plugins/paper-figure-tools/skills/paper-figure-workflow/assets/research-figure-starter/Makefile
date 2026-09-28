PYTHON ?= python3
DIAGRAM_OWNER ?=
FIGURE_DIAGRAM_EXPORTER ?=
TEMPLATE ?= architecture
WIDTH ?= double

.PHONY: plots diagrams figures verify-plots init-diagram

plots:
	$(PYTHON) figures_src/plots/grouped_bars.py --data figures_src/plots/data/grouped-bars.json --out-dir figures --width single
	$(PYTHON) figures_src/plots/line_scaling.py --data figures_src/plots/data/line-scaling.json --out-dir figures --width double
	$(PYTHON) figures_src/plots/empirical_cdf.py --data figures_src/plots/data/empirical-cdf.json --out-dir figures --width single
	$(PYTHON) figures_src/plots/stacked_breakdown.py --data figures_src/plots/data/breakdown-bars.json --out-dir figures --width single
	$(PYTHON) figures_src/plots/stacked_breakdown.py --data figures_src/plots/data/breakdown-area.json --out-dir figures --width double
	$(MAKE) verify-plots

verify-plots:
	$(PYTHON) scripts/verify_exports.py --out-dir figures --expect grouped-bars=3.3 --expect line-scaling=6.9 --expect empirical-cdf=3.3 --expect breakdown-bars=3.3 --expect breakdown-area=6.9

diagrams:
	DIAGRAM_OWNER="$(DIAGRAM_OWNER)" FIGURE_DIAGRAM_EXPORTER="$(FIGURE_DIAGRAM_EXPORTER)" $(PYTHON) scripts/export_diagrams.py --source-dir figures_src/diagrams --out-dir figures

init-diagram:
	$(PYTHON) scripts/init_omni_diagram.py --template "$(TEMPLATE)" --width "$(WIDTH)"

figures: plots diagrams
