#!/usr/bin/env python3
"""Empirical CDF from raw observations, including tied values."""

from __future__ import annotations

import math
from collections import Counter

from figure_common import (FigureDataError, axis_label, finite_number, main,
                           nonempty_string, ordered_series, require_unit)


def empirical_cdf(samples):
    """Return unique observations and F(x)=number of samples <= x divided by n."""
    if not isinstance(samples, list) or not samples:
        raise FigureDataError("samples must be a nonempty raw-observation list")
    observations = [finite_number(value, f"samples[{index}]") for index, value in enumerate(samples)]
    counts = Counter(observations)
    count = 0
    points = []
    for value in sorted(counts):
        count += counts[value]
        points.append((value, count / len(observations)))
    return points


def nearest_rank(samples, percentile):
    """Observed nearest-rank percentile; no quantile interpolation."""
    index = math.ceil(percentile / 100 * len(samples)) - 1
    return sorted(samples)[index]


def validate(data, mapping):
    x_label = axis_label(nonempty_string(data.get("x_label"), "x_label"),
                         nonempty_string(data.get("x_unit"), "x_unit"))
    series = ordered_series(data.get("series"), mapping)
    prepared = []
    for entry in series:
        name = entry["method"]
        require_unit(entry, data["x_unit"], name)
        samples = entry.get("samples")
        points = empirical_cdf(samples)
        prepared.append((name, samples, points))
    raw_range = data.get("x_range")
    if not isinstance(raw_range, list) or len(raw_range) != 2:
        raise FigureDataError("x_range must provide two explicit axis endpoints")
    left, right = (finite_number(value, "x_range") for value in raw_range)
    if left >= right:
        raise FigureDataError("x_range must be increasing")
    if any(points[0][0] <= left or points[-1][0] >= right for _, _, points in prepared):
        raise FigureDataError("x_range must extend beyond every observed sample")
    annotations = data.get("annotations", [])
    if not isinstance(annotations, list):
        raise FigureDataError("annotations must be a list")
    if annotations and data.get("percentile_method") != "nearest_rank":
        raise FigureDataError("percentile annotations require explicit percentile_method=nearest_rank")
    for annotation in annotations:
        if not isinstance(annotation, dict) or annotation.get("method") not in [name for name, _, _ in prepared]:
            raise FigureDataError("annotation must name a plotted method")
        percentile = finite_number(annotation.get("percentile"), "annotation.percentile")
        if not 0 < percentile <= 100:
            raise FigureDataError("annotation.percentile must be in (0, 100]")
        nonempty_string(annotation.get("label"), "annotation.label")
    return x_label, (left, right), prepared, annotations


def render(plt, prepared, data, mapping, width):
    x_label, (left, right), series, annotations = prepared
    fig, ax = plt.subplots(figsize=(width, 2.55 if width < 5 else 2.8))
    fig.subplots_adjust(left=0.2 if width < 5 else 0.11, right=0.98, bottom=0.27, top=0.8)
    by_name = {}
    for name, samples, points in series:
        style = mapping["styles"][name]
        xs = [left] + [x for x, _ in points] + [right]
        ys = [0.0] + [y for _, y in points] + [1.0]
        ax.step(xs, ys, where="post", label=name, color=style["color"],
                linestyle=style["linestyle"], linewidth=1.35)
        by_name[name] = samples
    for index, annotation in enumerate(annotations):
        name = annotation["method"]
        threshold = nearest_rank(by_name[name], annotation["percentile"])
        fraction = sum(value <= threshold for value in by_name[name]) / len(by_name[name])
        inward = threshold > left + 0.68 * (right - left)
        offset = (-5 if inward else 5, -12 - (index % 2) * 10)
        ax.annotate(f"{annotation['label']}: {threshold:g}", xy=(threshold, fraction),
                    xytext=offset, textcoords="offset points", fontsize=7,
                    ha="right" if inward else "left",
                    color=mapping["styles"][name]["color"],
                    arrowprops={"arrowstyle": "-", "color": mapping["styles"][name]["color"], "lw": 0.6})
    ax.set_xlim(left, right)
    ax.set_ylim(0, 1.03)
    ax.set_xlabel(x_label)
    ax.set_ylabel("Fraction of observations ≤ x")
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.96),
               ncol=min(3, len(labels)), frameon=False, fontsize=7)
    ax.grid(axis="y", color="#D9DFE7", linewidth=0.45)
    fig.text(0.98, 0.025, data["data_label"], ha="right", va="bottom", fontsize=7)
    return fig


if __name__ == "__main__":
    main("empirical_cdf", "Empirical distribution from raw samples", validate, render)
