#!/usr/bin/env python3
"""Aligned scaling panels; null values remain visible gaps."""

from __future__ import annotations

from figure_common import (FigureDataError, axis_label, finite_number, main,
                           nonempty_string, ordered_series, require_unit, values)


def validate(data, mapping):
    if data.get("between_samples") != "straight_segments":
        raise FigureDataError("line plots require explicit between_samples=straight_segments; gaps stay gaps")
    x_values = data.get("x_values")
    if not isinstance(x_values, list) or len(x_values) < 2:
        raise FigureDataError("x_values must have at least two numeric positions")
    x_values = [finite_number(value, f"x_values[{index}]") for index, value in enumerate(x_values)]
    if any(right <= left for left, right in zip(x_values, x_values[1:])):
        raise FigureDataError("x_values must be strictly increasing; interpolation is not performed")
    x_label = axis_label(nonempty_string(data.get("x_label"), "x_label"),
                         nonempty_string(data.get("x_unit"), "x_unit"))
    y_label = axis_label(nonempty_string(data.get("y_label"), "y_label"),
                         nonempty_string(data.get("y_unit"), "y_unit"))
    panels = data.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 3:
        raise FigureDataError("panels must contain one to three aligned comparisons")
    prepared = []
    for number, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise FigureDataError("each panel must be an object")
        title = nonempty_string(panel.get("title"), f"panels[{number}].title")
        series = ordered_series(panel.get("series"), mapping)
        panel_series = []
        for entry in series:
            name = entry["method"]
            require_unit(entry, data["y_unit"], name)
            panel_series.append((name, values(entry, len(x_values), name, allow_missing=True)))
        prepared.append((title, panel_series))
    return x_values, x_label, y_label, prepared


def render(plt, prepared, data, mapping, width):
    x_values, x_label, y_label, panels = prepared
    fig, axes = plt.subplots(1, len(panels), sharex=True, sharey=True,
                             figsize=(width, 2.6 if width < 5 else 2.8))
    fig.subplots_adjust(left=0.16 if width < 5 else 0.1, right=0.98,
                        bottom=0.27, top=0.73, wspace=0.18)
    if len(panels) == 1:
        axes = [axes]
    legend = {}
    for ax, (title, series) in zip(axes, panels):
        ax.set_title(title)
        for name, y_values in series:
            style = mapping["styles"][name]
            line, = ax.plot(x_values, [float("nan") if value is None else value for value in y_values],
                            color=style["color"], marker=style["marker"],
                            linestyle=style["linestyle"], linewidth=1.25, markersize=3.5,
                            label=name)
            legend[name] = line
        ax.set_xlabel(x_label)
        ax.set_xticks(x_values)
        ax.grid(axis="y", color="#D9DFE7", linewidth=0.45)
        ax.set_axisbelow(True)
    axes[0].set_ylabel(y_label)
    labels = [name for name in mapping["method_order"] if name in legend]
    fig.legend([legend[name] for name in labels], labels, ncol=min(3, len(labels)),
               loc="upper center", bbox_to_anchor=(0.5, 0.96), frameon=False, fontsize=7)
    fig.text(0.98, 0.025, data["data_label"], ha="right", va="bottom", fontsize=7)
    return fig


if __name__ == "__main__":
    main("line_scaling", "Aligned scaling panels with a shared method legend", validate, render)
