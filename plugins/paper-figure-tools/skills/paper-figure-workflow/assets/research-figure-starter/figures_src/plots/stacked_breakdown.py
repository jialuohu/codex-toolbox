#!/usr/bin/env python3
"""Additive components as stacked bars or areas on an explicit common grid."""

from __future__ import annotations

from figure_common import (FigureDataError, axis_label, finite_number, main,
                           nonempty_string, require_unit, values)


def validate(data, mapping):
    mode = data.get("mode")
    if mode not in ("bars", "area"):
        raise FigureDataError("mode must be bars or area")
    between = data.get("between_samples")
    if between != ("linear" if mode == "area" else "none"):
        raise FigureDataError("area requires explicit between_samples=linear; bars require none")
    x_values = data.get("x_values")
    if not isinstance(x_values, list) or len(x_values) < 2:
        raise FigureDataError("x_values must be a common grid of at least two positions")
    x_values = [finite_number(value, f"x_values[{index}]") for index, value in enumerate(x_values)]
    if any(right <= left for left, right in zip(x_values, x_values[1:])):
        raise FigureDataError("x_values must be strictly increasing")
    x_label = axis_label(nonempty_string(data.get("x_label"), "x_label"),
                         nonempty_string(data.get("x_unit"), "x_unit"))
    y_unit = nonempty_string(data.get("y_unit"), "y_unit")
    y_label = axis_label(nonempty_string(data.get("y_label"), "y_label"), y_unit)
    components = data.get("components")
    if not isinstance(components, list) or not components:
        raise FigureDataError("components must be a nonempty list")
    names = [nonempty_string(item.get("component"), "component") if isinstance(item, dict)
             else "" for item in components]
    if len(set(names)) != len(names) or "" in names:
        raise FigureDataError("component names must be unique")
    style_order = mapping.get("component_order")
    style_map = mapping.get("component_styles")
    if not isinstance(style_order, list) or not isinstance(style_map, dict):
        raise FigureDataError("component styles are missing")
    unknown = set(names) - set(style_order)
    if unknown:
        raise FigureDataError(f"component styles missing for {sorted(unknown)}")
    ordered = sorted(components, key=lambda item: style_order.index(item["component"]))
    prepared = []
    for entry in ordered:
        name = entry["component"]
        require_unit(entry, y_unit, name)
        prepared.append((name, values(entry, len(x_values), name, nonnegative=True)))
    return mode, x_values, x_label, y_label, prepared


def render(plt, prepared, data, mapping, width):
    mode, x_values, x_label, y_label, components = prepared
    fig, ax = plt.subplots(figsize=(width, 2.55 if width < 5 else 2.8))
    fig.subplots_adjust(left=0.17 if width < 5 else 0.1, right=0.98, bottom=0.27, top=0.79)
    if mode == "bars":
        min_step = min(right - left for left, right in zip(x_values, x_values[1:]))
        bottom = [0.0] * len(x_values)
        for name, component_values in components:
            style = mapping["component_styles"][name]
            ax.bar(x_values, component_values, width=0.7 * min_step, bottom=bottom,
                   color=style["color"], hatch=style["hatch"], edgecolor="#30343A",
                   linewidth=0.4, label=name)
            bottom = [low + addition for low, addition in zip(bottom, component_values)]
    else:
        collections = ax.stackplot(x_values, *[values for _, values in components],
                                   colors=[mapping["component_styles"][name]["color"] for name, _ in components],
                                   labels=[name for name, _ in components], linewidth=0.5,
                                   edgecolor="#30343A")
        for collection, (name, _) in zip(collections, components):
            collection.set_hatch(mapping["component_styles"][name]["hatch"])
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_xticks(x_values)
    ax.set_ylim(bottom=0)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.96),
               ncol=min(3, len(components)), frameon=False, fontsize=7)
    ax.grid(axis="y", color="#D9DFE7", linewidth=0.45)
    ax.set_axisbelow(True)
    fig.text(0.98, 0.025, data["data_label"], ha="right", va="bottom", fontsize=7)
    return fig


if __name__ == "__main__":
    main("stacked_breakdown", "Additive stacked bars or areas from an explicit grid", validate, render)
