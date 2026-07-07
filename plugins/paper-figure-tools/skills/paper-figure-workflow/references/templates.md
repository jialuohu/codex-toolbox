# Figure Workflow Templates

Use these as starting points only after inspecting the target repo.

## Makefile Target

This target lets users regenerate the full figure set with `make figures`.

```makefile
.PHONY: figures
figures:
	python scripts/plot_results.py --data data/results.csv --out-dir figures
	drawio --export --format svg --output figures/pipeline.svg figures_src/pipeline.drawio
	drawio --export --format pdf --output figures/pipeline.pdf figures_src/pipeline.drawio
```

If draw.io export is unavailable but Inkscape is installed, convert a generated SVG to PDF:

```bash
inkscape figures/pipeline.svg --export-type=pdf --export-filename=figures/pipeline.pdf
```

## Python Plot Skeleton

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import scienceplots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("figures"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(args.data)

    plt.style.use(["science", "no-latex"])
    plt.rcParams.update({
        "figure.figsize": (3.3, 2.2),
        "font.size": 8,
        "axes.labelsize": 8,
        "legend.fontsize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    fig, ax = plt.subplots()
    ax.plot(data["x"], data["y"], marker="o", linewidth=1.25, label="method")
    ax.set_xlabel("Input")
    ax.set_ylabel("Metric")
    ax.legend(frameon=False)
    fig.tight_layout()

    for suffix in ("svg", "pdf"):
        fig.savefig(args.out_dir / f"figure.{suffix}", bbox_inches="tight")


if __name__ == "__main__":
    main()
```

This writes `figure.svg` and `figure.pdf` in the selected output directory.

Install minimal plotting dependencies in the target repo's chosen environment:

```bash
python -m pip install matplotlib scienceplots pandas
```
