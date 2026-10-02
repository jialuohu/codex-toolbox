"""Shared, project-local validation and export code for research plot templates.

This file is copied into a paper repository with the plotting scripts. It must
never import from the toolbox checkout or a plugin cache.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import warnings
from pathlib import Path
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
SINGLE_WIDTH_IN = 3.3
DOUBLE_WIDTH_IN = 6.9


class FigureDataError(ValueError):
    """Input is incomplete or changes the meaning of the supplied data."""


def finite_number(value: Any, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FigureDataError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise FigureDataError(f"{name} must be finite")
    if nonnegative and result < 0:
        raise FigureDataError(f"{name} must be nonnegative")
    return result


def nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FigureDataError(f"{name} must be a nonempty string")
    return value.strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FigureDataError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FigureDataError(f"{path} must contain a JSON object")
    return value


def load_data(path: Path, kind: str) -> dict[str, Any]:
    data = read_json(path)
    if data.get("kind") != kind:
        raise FigureDataError(f"expected kind={kind!r} in {path}")
    nonempty_string(data.get("figure_name"), "figure_name")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", data["figure_name"]):
        raise FigureDataError("figure_name must be a simple lowercase filename stem")
    nonempty_string(data.get("data_label"), "data_label")
    return data


def load_method_styles() -> dict[str, Any]:
    mapping = read_json(HERE / "method_styles.json")
    order = mapping.get("method_order")
    styles = mapping.get("styles")
    if not isinstance(order, list) or not order or len(set(order)) != len(order):
        raise FigureDataError("method_order must contain unique method names")
    if not isinstance(styles, dict) or set(styles) != set(order):
        raise FigureDataError("styles must map every method in method_order exactly once")
    encodings = set()
    # Check the visible channel combinations used by each plot renderer.
    bars = set()
    ecdfs = set()
    lines = set()
    hatches = set()
    line_styles = set()
    for name in order:
        style = styles[name]
        if not isinstance(style, dict):
            raise FigureDataError(f"style for {name} must be an object")
        encoding = tuple(nonempty_string(style.get(key), f"{name}.{key}") for key in
                         ("color", "marker", "linestyle", "hatch"))
        if encoding in encodings:
            raise FigureDataError(f"duplicate method encoding: {name}")
        encodings.add(encoding)
        color, marker, linestyle, hatch = encoding
        if (color, hatch) in bars or (color, linestyle) in ecdfs or (color, marker, linestyle) in lines:
            raise FigureDataError(f"method {name} is indistinguishable in a plot template; use a distinct color/hatch and color/line style")
        if hatch in hatches or linestyle in line_styles:
            raise FigureDataError(f"method {name} needs its own hatch and line style for grayscale comparison")
        bars.add((color, hatch))
        ecdfs.add((color, linestyle))
        lines.add((color, marker, linestyle))
        hatches.add(hatch)
        line_styles.add(linestyle)
    component_order = mapping.get("component_order")
    component_styles = mapping.get("component_styles")
    if (not isinstance(component_order, list) or not component_order
            or len(set(component_order)) != len(component_order)
            or not isinstance(component_styles, dict)
            or set(component_styles) != set(component_order)):
        raise FigureDataError("component_order and component_styles must map components exactly once")
    component_encodings = set()
    component_hatches = set()
    for name in component_order:
        style = component_styles[name]
        if not isinstance(style, dict):
            raise FigureDataError(f"component style for {name} must be an object")
        encoding = (nonempty_string(style.get("color"), f"{name}.color"),
                    nonempty_string(style.get("hatch"), f"{name}.hatch"))
        if encoding in component_encodings:
            raise FigureDataError(f"duplicate component encoding: {name}")
        if encoding[1] in component_hatches:
            raise FigureDataError(f"component {name} needs its own hatch for grayscale comparison")
        component_encodings.add(encoding)
        component_hatches.add(encoding[1])
    return mapping


def ordered_series(series: Any, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(series, list) or not series:
        raise FigureDataError("series must be a nonempty list")
    names = []
    for entry in series:
        if not isinstance(entry, dict):
            raise FigureDataError("each series must be an object")
        names.append(nonempty_string(entry.get("method"), "series.method"))
    if len(set(names)) != len(names):
        raise FigureDataError("duplicate method in one panel")
    unknown = set(names) - set(mapping["method_order"])
    if unknown:
        raise FigureDataError(f"method styles missing for {sorted(unknown)}; add a distinct encoding or use another panel")
    position = {name: index for index, name in enumerate(mapping["method_order"])}
    return sorted(series, key=lambda entry: position[entry["method"]])


def require_unit(entry: dict[str, Any], expected: str, name: str) -> None:
    actual = nonempty_string(entry.get("unit"), f"{name}.unit")
    if actual != expected:
        raise FigureDataError(f"incompatible units: {name} has {actual!r}; expected {expected!r}")


def values(entry: dict[str, Any], count: int, name: str, *,
           allow_missing: bool = False, nonnegative: bool = False) -> list[float | None]:
    raw = entry.get("values")
    if not isinstance(raw, list) or len(raw) != count:
        raise FigureDataError(f"{name}.values must have exactly {count} entries")
    result = []
    for index, value in enumerate(raw):
        if value is None and allow_missing:
            result.append(None)
        else:
            result.append(finite_number(value, f"{name}.values[{index}]", nonnegative=nonnegative))
    return result


def validate_uncertainty(entry: dict[str, Any], estimates: list[float], name: str) -> tuple[list[float], list[float]] | None:
    uncertainty = entry.get("uncertainty")
    if uncertainty is None:
        return None
    if not isinstance(uncertainty, dict):
        raise FigureDataError(f"{name}.uncertainty must be an object")
    statistic = nonempty_string(uncertainty.get("statistic"), f"{name}.uncertainty.statistic")
    interval_type = nonempty_string(uncertainty.get("interval_type"), f"{name}.uncertainty.interval_type")
    if interval_type not in {"confidence_interval", "standard_deviation", "standard_error",
                             "range", "illustrative_interval"}:
        raise FigureDataError(f"{name}.uncertainty.interval_type must name a supported interval")
    nonempty_string(uncertainty.get("method"), f"{name}.uncertainty.method")
    n = uncertainty.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise FigureDataError(f"{name}.uncertainty.n must be a positive sample count")
    if interval_type == "confidence_interval":
        level = finite_number(uncertainty.get("confidence_level"), f"{name}.uncertainty.confidence_level")
        if not 0 < level < 1:
            raise FigureDataError("confidence_level must be between 0 and 1")
    elif uncertainty.get("confidence_level") is not None:
        raise FigureDataError("confidence_level applies only to confidence_interval")
    if statistic not in {"mean", "median"}:
        raise FigureDataError("statistic must identify the supplied estimate (mean or median)")
    lower = values({"values": uncertainty.get("lower")}, len(estimates), f"{name}.uncertainty.lower")
    upper = values({"values": uncertainty.get("upper")}, len(estimates), f"{name}.uncertainty.upper")
    for index, (lo, estimate, hi) in enumerate(zip(lower, estimates, upper)):
        if not lo <= estimate <= hi:
            raise FigureDataError(f"{name}.uncertainty bounds do not contain estimate at index {index}")
    return lower, upper


def axis_label(label: str, unit: str) -> str:
    return label if unit == "1" else f"{label} ({unit})"


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--data", type=Path, required=True, help="Input JSON with explicit values or raw samples")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory for fixed-canvas SVG and PDF")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--width", choices=("single", "double"), help="3.3- or 6.9-inch width")
    group.add_argument("--width-in", type=float, help="Positive custom width in inches")
    args = parser.parse_args()
    if args.width_in is not None and (not math.isfinite(args.width_in) or args.width_in <= 0):
        parser.error("--width-in must be a positive finite number")
    return args


def figure_width(args: argparse.Namespace) -> float:
    if args.width_in is not None:
        return args.width_in
    return DOUBLE_WIDTH_IN if args.width == "double" else SINGLE_WIDTH_IN


def configure_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import scienceplots  # noqa: F401 - registers the SciencePlots styles
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Matplotlib and SciencePlots are required; install pinned requirements.txt") from exc
    plt.style.use(["science", "no-latex", str(HERE / "research.mplstyle")])
    # The project-local style has the final say for portable typography.
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "pdf.fonttype": 42,
                         "savefig.bbox": None})
    return plt


def save_figure(fig: Any, out_dir: Path, figure_name: str, width_in: float) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    actual = float(fig.get_size_inches()[0])
    if abs(actual - width_in) > 1e-9:
        raise RuntimeError("plot renderer changed the requested canvas width")
    for suffix in ("svg", "pdf"):
        path = out_dir / f"{figure_name}.{suffix}"
        temporary = out_dir / f".{figure_name}.tmp.{suffix}"
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("error", message=r".*Glyph .* missing from font.*")
                fig.savefig(temporary, format=suffix, bbox_inches=None,
                            facecolor="white", metadata={"Creator": "Research figure starter"})
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError(f"export did not create {temporary}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    from matplotlib import font_manager
    resolved_path = Path(font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans")))
    resolved_name = font_manager.FontProperties(fname=str(resolved_path)).get_name()
    report = {"requested": "DejaVu Sans", "resolved": resolved_name,
              "font_file": resolved_path.name, "substituted": resolved_name != "DejaVu Sans"}
    (out_dir / f"{figure_name}.fonts.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main(kind: str, description: str,
         validator: Callable[[dict[str, Any], dict[str, Any]], Any],
         renderer: Callable[[Any, Any, dict[str, Any], dict[str, Any], float], Any]) -> None:
    args = parse_args(description)
    try:
        data = load_data(args.data, kind)
        mapping = load_method_styles()
        prepared = validator(data, mapping)
        plt = configure_matplotlib()
        width = figure_width(args)
        fig = renderer(plt, prepared, data, mapping, width)
        try:
            save_figure(fig, args.out_dir, data["figure_name"], width)
        finally:
            plt.close(fig)
    except (FigureDataError, RuntimeError, OSError) as exc:
        raise SystemExit(f"figure error: {exc}") from exc
