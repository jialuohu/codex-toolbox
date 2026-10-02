#!/usr/bin/env python3
"""Grouped comparison bars from explicit estimates and optional uncertainty."""

from __future__ import annotations

from figure_common import (FigureDataError, axis_label, finite_number, main,
                           nonempty_string, ordered_series, require_unit,
                           validate_uncertainty, values)


def validate(data, mapping):
    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        raise FigureDataError("categories must be a nonempty list")
    categories = [nonempty_string(value, "category") for value in categories]
    if len(set(categories)) != len(categories):
        raise FigureDataError("categories must be unique")
    x_label = nonempty_string(data.get("x_label"), "x_label")
    y_label = nonempty_string(data.get("y_label"), "y_label")
    y_unit = nonempty_string(data.get("y_unit"), "y_unit")
    series = ordered_series(data.get("series"), mapping)
    prepared = []
    for entry in series:
        name = entry["method"]
        require_unit(entry, y_unit, name)
        estimates = values(entry, len(categories), name)
        bounds = validate_uncertainty(entry, estimates, name)
        prepared.append((name, estimates, bounds))
    lower_limit = finite_number(data.get("y_min", 0), "y_min")
    if any(value < lower_limit for _, estimates, bounds in prepared
           for value in (bounds[0] if bounds is not None else estimates)):
        raise FigureDataError("y_min would hide a supplied estimate or uncertainty bound")
    return categories, x_label, axis_label(y_label, y_unit), lower_limit, prepared


def render(plt, prepared, data, mapping, width):
    categories, x_label, y_label, lower_limit, series = prepared
    slot_width_in = width * (0.81 if width < 5 else 0.88) / len(categories)
    if any(len(label) * 0.053 > slot_width_in for label in categories):
        raise FigureDataError("crowded category labels at requested width; shorten labels, use --width double, or separate panels")
    fig, ax = plt.subplots(figsize=(width, 2.55 if width < 5 else 2.8))
    fig.subplots_adjust(left=0.17 if width < 5 else 0.1, right=0.98, bottom=0.26, top=0.79)
    count = len(series)
    bar_width = 0.74 / count
    for index, (name, estimates, bounds) in enumerate(series):
        style = mapping["styles"][name]
        positions = [number - 0.37 + (index + 0.5) * bar_width for number in range(len(categories))]
        ax.bar(positions, estimates, width=bar_width, label=name, color=style["color"],
               edgecolor="#30343A", linewidth=0.55, hatch=style["hatch"])
        if bounds is not None:
            lower, upper = bounds
            ax.errorbar(positions, estimates,
                        yerr=[[estimate - low for estimate, low in zip(estimates, lower)],
                              [high - estimate for estimate, high in zip(estimates, upper)]],
                        fmt="none", ecolor="#30343A", elinewidth=0.8, capsize=2, capthick=0.8)
    ax.set_xticks(range(len(categories)), categories)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_ylim(bottom=lower_limit)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.96),
               ncol=min(count, 3), frameon=False, fontsize=7)
    ax.grid(axis="y", color="#D9DFE7", linewidth=0.45)
    ax.set_axisbelow(True)
    fig.text(0.98, 0.025, data["data_label"], ha="right", va="bottom", fontsize=7)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_boxes = [label.get_window_extent(renderer) for label in ax.get_xticklabels()]
    if any(left.overlaps(right) for left, right in zip(label_boxes, label_boxes[1:])):
        plt.close(fig)
        raise FigureDataError("crowded category labels at requested width; shorten labels, use --width double, or separate panels")
    return fig


if __name__ == "__main__":
    main("grouped_bars", "Grouped research comparison with explicit uncertainty", validate, render)
