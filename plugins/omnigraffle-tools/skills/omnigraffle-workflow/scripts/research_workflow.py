#!/usr/bin/env python3
"""Validate, preview, or prepare a create request for the research workflow source.

This command never launches OmniGraffle. A later explicit `omnigraffle.py
create --request ...` operation is required to produce a native .graffle file.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import tempfile
import textwrap
import uuid
import xml.etree.ElementTree as ET

import contracts
import native


HERE = Path(__file__).resolve().parent
DEFAULT_SPEC = HERE.parents[2] / "assets" / "research-templates" / "workflow.json"
TEMPLATE_ASSETS = HERE.parents[2] / "assets" / "research-templates"
PALETTE_SOURCE = TEMPLATE_ASSETS / "palette.json"
STANDARD_WIDTHS = {"single": 3.3, "double": 6.9}

WHITE = "#FFFFFF"
INK = "#30343A"
BLUE = "#2148B8"
TERRA = "#C65F38"
PALE_BLUE = "#F0F4FC"
PALE_TERRA = "#FCF3ED"
PALE_GRAY = "#F4F5F6"
HAIRLINE = "#B9C0C7"


class Composition:
    """Small library of reusable, editable native primitives.

    Coordinates are final publication points. Font sizes remain whole points
    when a custom width expands the gaps between objects.
    """

    def __init__(self, key: str, name: str, width: float, height: float):
        self.key, self.name = key, name
        self.width, self.height = round(width, 3), round(height, 3)
        self.objects: list[dict] = []
        self.box("background", 0, 0, width, height, fill=WHITE, stroke=WHITE,
                 shape_type="rectangle", stroke_width=0.5)

    def box(self, key: str, x: float, y: float, width: float, height: float,
            label: str = "", *, fill: str = WHITE, stroke: str = INK,
            shape_type: str = "rounded_rectangle", stroke_width: float = 0.8,
            stroke_pattern: str = "solid", font_size: int = 8,
            font_name: str = "Helvetica", text_color: str = INK,
            text_align: str = "center", text_valign: str = "center",
            text_padding: float = 2) -> str:
        obj = {"key": key, "kind": "shape", "x": round(x, 3), "y": round(y, 3),
               "width": round(width, 3), "height": round(height, 3),
               "shape_type": shape_type, "fill": fill, "stroke": stroke,
               "stroke_width": stroke_width, "stroke_pattern": stroke_pattern}
        if label:
            obj.update(text=label, font_name=font_name, font_size=font_size,
                       text_color=text_color, text_align=text_align,
                       text_valign=text_valign, text_padding=text_padding)
        self.objects.append(obj)
        return key

    def label(self, key: str, x: float, y: float, width: float, height: float,
              value: str, *, size: int = 8, bold: bool = False,
              align: str = "left", color: str = INK) -> str:
        self.objects.append({
            "key": key, "kind": "text", "x": round(x, 3), "y": round(y, 3),
            "width": round(width, 3), "height": round(height, 3),
            "text": value, "font_name": "Helvetica Bold" if bold else "Helvetica",
            "font_size": size, "text_color": color, "text_align": align,
            "text_valign": "center", "text_padding": 0,
        })
        return key

    def edge(self, key: str, source: str, destination: str, *,
             color: str = BLUE, line_type: str = "orthogonal",
             from_side: str = "right", to_side: str = "left",
             head_arrow: str = "filled", stroke_pattern: str = "solid",
             stroke_width: float = 1.0) -> str:
        self.objects.append({
            "key": key, "kind": "connector", "from": source, "to": destination,
            "stroke": color, "stroke_width": stroke_width,
            "stroke_pattern": stroke_pattern, "line_type": line_type,
            "from_side": from_side, "to_side": to_side,
            "head_arrow": head_arrow, "tail_arrow": "none",
        })
        return key

    def group(self, key: str, *children: str) -> None:
        self.objects.append({"key": key, "kind": "group", "children": list(children)})

    def heading(self, title: str, subtitle: str) -> None:
        title_key = self.label("title", 10, 5, self.width - 20, 16, title,
                               size=10, bold=True)
        subtitle_key = self.label("subtitle", 10, 22, self.width - 20, 12,
                                  subtitle, size=7)
        # A small, flat native group supports independent UI movement without
        # grouping any connector endpoint or separately editable equation.
        self.group("heading-group", title_key, subtitle_key)

    def footer(self, value: str) -> None:
        self.label("schematic-note", 10, self.height - 18, self.width - 20, 12,
                   value, size=7)

    def spec(self) -> dict:
        return {"canvases": [{"key": self.key, "name": self.name,
                              "width": self.width, "height": self.height,
                              "objects": self.objects}]}


def _architecture(variant: str) -> Composition:
    if variant == "single":
        c = Composition("research-architecture", "Architecture (schematic)", 237.6, 221)
        c.heading("Numbered architecture", "Four steps; component regions are schematic")
        for key, x, y, fill, title in (
            ("request-region", 12, 42, PALE_GRAY, "REQUESTS"),
            ("control-region", 126, 42, PALE_BLUE, "CONTROL"),
            ("cache-region", 12, 122, PALE_BLUE, "GPU MEMORY"),
            ("worker-region", 126, 122, PALE_TERRA, "EXECUTION"),
        ):
            c.box(key, x, y, 99, 59 if y == 42 else 70, fill=fill,
                  stroke=HAIRLINE, shape_type="rectangle", stroke_width=0.6)
            if key == "cache-region":
                # Keep the short heading beside the feedback stem at x=61.5;
                # native Helvetica Bold wraps "GPU MEMORY" in this space.
                c.label(key + "-heading", 70, y + 4, 39, 11,
                        "MEMORY", size=7, bold=True)
            else:
                c.label(key + "-heading", x + 7, y + 4, 86, 11,
                        title, size=7, bold=True)
        c.box("queue", 24, 66, 75, 26, "Request queue", stroke=BLUE)
        c.box("scheduler", 138, 66, 75, 26, "Scheduler", stroke=BLUE)
        c.box("worker", 138, 151, 75, 26, "Worker", stroke=TERRA)
        c.box("gpu-memory", 21, 145, 81, 41, fill=WHITE, stroke=BLUE)
        c.label("gpu-heading", 28, 147, 67, 12, "GPU cache", size=7, bold=True)
        c.box("layer-1", 28, 164, 29, 17, "L1", fill=PALE_BLUE,
              stroke=BLUE, shape_type="rectangle", font_size=7)
        c.box("layer-2", 64, 164, 29, 17, "L2", fill=PALE_TERRA,
              stroke=TERRA, shape_type="rectangle", font_size=7)
        c.edge("submit", "queue", "scheduler")
        c.edge("dispatch", "scheduler", "worker", from_side="bottom", to_side="top")
        c.edge("populate", "worker", "gpu-memory", color=TERRA,
               from_side="left", to_side="right")
        c.edge("reuse", "gpu-memory", "queue", from_side="top", to_side="bottom")
        c.label("step-1", 103, 54, 31, 11, "1 send", size=7, align="center")
        c.label("step-2", 183, 103, 43, 11, "2 dispatch", size=7, align="center")
        c.label("step-3", 103, 143, 33, 11, "3 store", size=7, align="center")
        c.label("step-4", 13, 106, 43, 11, "4 reuse", size=7, align="center")
        c.footer("Schematic; arrows and layer blocks are illustrative.")
        return c
    c = Composition("research-architecture", "Architecture (schematic)", 496.8, 232)
    c.heading("Numbered architecture and workflow",
              "Example roles and directed operations; no measured latency or capacity")
    for key, x, width, fill, title in (
        ("request-region", 12, 126, PALE_GRAY, "REQUESTS"),
        ("control-region", 184, 128, PALE_BLUE, "CONTROL"),
        ("execution-region", 360, 124, PALE_TERRA, "EXECUTION + MEMORY"),
    ):
        c.box(key, x, 49, width, 143, fill=fill, stroke=HAIRLINE,
              shape_type="rectangle", stroke_width=0.6)
        c.label(key + "-heading", x + 9, 57, width - 18, 12, title,
                size=8, bold=True)
    c.box("queue", 24, 95, 101, 34, "Request queue", stroke=BLUE)
    c.box("scheduler", 198, 95, 99, 34, "Scheduler", stroke=BLUE)
    c.box("worker", 375, 83, 94, 34, "Worker", stroke=TERRA)
    c.box("gpu-memory", 373, 139, 99, 43, fill=WHITE, stroke=BLUE)
    c.label("gpu-heading", 381, 140, 83, 12, "GPU cache", size=8, bold=True)
    for key, x, label, fill, border in (
        ("layer-1", 383, "L1", PALE_BLUE, BLUE),
        ("layer-2", 413, "L2", PALE_BLUE, BLUE),
        ("layer-3", 443, "L3", PALE_TERRA, TERRA),
    ):
        c.box(key, x, 157, 25, 18, label, fill=fill, stroke=border,
              shape_type="rectangle", font_size=7)
    c.edge("submit", "queue", "scheduler")
    c.edge("dispatch", "scheduler", "worker")
    c.edge("populate", "worker", "gpu-memory", color=TERRA,
           from_side="bottom", to_side="top")
    c.edge("reuse", "gpu-memory", "scheduler", from_side="left", to_side="bottom")
    for key, x, y, label in (
        ("step-1", 145, 85, "1 Submit"),
        ("step-2", 316, 85, "2 Dispatch"),
        ("step-3", 430, 120, "3 Populate"),
        ("step-4", 316, 164, "4 Reuse"),
    ):
        c.label(key, x, y, 49, 12, label, size=7, align="center")
    c.footer("Schematic sequence; block sizes do not encode memory capacity or duration.")
    return c


def _timeline_cell(c: Composition, key: str, x: float, y: float,
                   width: float, text: str, state: str) -> None:
    styles = {
        "invoke": (WHITE, BLUE, "solid"),
        "wait": (PALE_GRAY, HAIRLINE, "dashed"),
        "execute": (PALE_TERRA, TERRA, "solid"),
        "retain": (PALE_BLUE, BLUE, "solid"),
        "idle": (PALE_GRAY, HAIRLINE, "dashed"),
    }
    fill, stroke, pattern = styles[state]
    c.box(key, x, y, width, 29 if c.width < 300 else 35, text,
          fill=fill, stroke=stroke, shape_type="rectangle",
          stroke_pattern=pattern, font_size=8)


def _timeline(variant: str) -> Composition:
    if variant == "single":
        c = Composition("research-timeline", "Execution comparison (schematic)", 237.6, 223)
        c.heading("Execution comparison", "Equal cells show order, not elapsed time")
        xs, cell_w, baseline_y, proposed_y = (12, 68, 124, 180), 45, 68, 130
        c.label("baseline-label", 12, 47, 115, 14, "BASELINE", size=8, bold=True)
        c.label("proposed-label", 12, 109, 115, 14, "PROPOSED", size=8, bold=True)
        legend_y = 178
    else:
        c = Composition("research-timeline", "Execution comparison (schematic)", 496.8, 215)
        c.heading("Aligned execution comparison", "Shared state encoding; cells indicate sequence, not measured time")
        xs, cell_w, baseline_y, proposed_y = (104, 202, 300, 398), 87, 65, 124
        c.label("baseline-label", 12, 76, 84, 15, "BASELINE", size=8, bold=True)
        c.label("proposed-label", 12, 135, 84, 15, "PROPOSED", size=8, bold=True)
        legend_y = 178
    baseline = (("invoke", "Invoke"), ("wait", "Wait"),
                ("execute", "Run"), ("retain", "Retain"))
    proposed = (("invoke", "Invoke"), ("execute", "Run"),
                ("retain", "Retain"), ("idle", "Idle"))
    for lane, states, y in (("baseline", baseline, baseline_y),
                            ("proposed", proposed, proposed_y)):
        for index, ((state, label), x) in enumerate(zip(states, xs)):
            _timeline_cell(c, f"{lane}-{state}", x, y, cell_w, label, state)
            if index:
                prev = f"{lane}-{states[index - 1][0]}"
                c.edge(f"{lane}-transition-{index}", prev, f"{lane}-{state}",
                       line_type="straight", stroke_width=0.9)
    if variant == "single":
        c.label("legend", 12, legend_y, 213, 16,
                "Blue: invoke/retain | Orange: run | Dashed: wait/idle", size=7)
    else:
        c.label("legend", 104, legend_y, 380, 14,
                "Blue: invoked/retained   Orange: executing   Dashed gray: waiting/idle",
                size=8)
    c.footer("Schematic states; cell widths are not measured durations.")
    return c


def _mechanism_inset(c: Composition, top: float, left: float,
                     width: float) -> None:
    """A labelled, editable vector explanation, never an empirical plot."""
    height = 92
    c.box("inset-panel", left, top, width, height, fill=WHITE,
          stroke=HAIRLINE, shape_type="rectangle", stroke_width=0.6)
    c.label("inset-heading", left + 8, top + 4, width - 16, 13,
            "Illustrative relationship", size=8, bold=True)
    c.label("inset-y-label", left + 8, top + 18, width - 16, 11,
            "Resident memory (qualitative)", size=7)
    x0, y0 = left + 28, top + 70
    x1 = left + width - 13
    c.box("inset-y-axis", x0, top + 32, 0.8, 39, fill=INK,
          stroke=INK, shape_type="rectangle", stroke_width=0.5)
    c.box("inset-x-axis", x0, y0, x1 - x0, 0.8, fill=INK,
          stroke=INK, shape_type="rectangle", stroke_width=0.5)
    points = (("inset-point-a", x0 + 24, y0 - 11),
              ("inset-point-b", x0 + (x1 - x0) * 0.57, y0 - 23),
              ("inset-point-c", x1 - 13, y0 - 32))
    for key, px, py in points:
        c.box(key, px, py, 4, 4, fill=BLUE, stroke=BLUE,
              shape_type="ellipse", stroke_width=0.5)
    c.edge("inset-segment-ab", points[0][0], points[1][0],
           line_type="straight", head_arrow="none", stroke_width=0.8)
    c.edge("inset-segment-bc", points[1][0], points[2][0],
           line_type="straight", head_arrow="none", stroke_width=0.8)
    c.label("inset-x-label", x0, y0 + 5, x1 - x0, 11,
            "More resident layers", size=7, align="center")


def _mechanism(variant: str, with_inset: bool) -> Composition:
    if variant == "single":
        c = Composition("research-mechanism", "Cache and memory detail (schematic)",
                        237.6, 461 if with_inset else 370)
        c.heading("Memory mechanism", "Illustrative layer and slot states")
        for key, y, height, title, fill in (
            ("cpu-region", 44, 95, "CPU LAYER STORE", PALE_GRAY),
            ("gpu-region", 158, 93, "GPU SLOTS", PALE_BLUE),
            ("request-region", 272, 56, "REQUEST", PALE_TERRA),
        ):
            c.box(key, 12, y, 213, height, fill=fill, stroke=HAIRLINE,
                  shape_type="rectangle", stroke_width=0.6)
            if key == "gpu-region":
                c.label(key + "-heading", 132, y + 4, 80, 11, title,
                        size=7, bold=True)
            else:
                c.label(key + "-heading", 22, y + 4, 190, 11, title,
                        size=7, bold=True)
        for key, x, text in (("cpu-layer-1", 28, "L1"),
                             ("cpu-layer-2", 94, "L2"),
                             ("cpu-layer-3", 160, "L3")):
            c.box(key, x, 79, 52, 25, text, fill=WHITE,
                  stroke=BLUE, shape_type="rectangle")
        for key, x, text, fill, border, pattern in (
            ("gpu-slot-0", 27, "L2 active", PALE_TERRA, TERRA, "solid"),
            ("gpu-slot-1", 94, "L3 ready", PALE_BLUE, BLUE, "solid"),
            ("gpu-slot-2", 161, "Empty", WHITE, HAIRLINE, "dashed"),
        ):
            c.box(key, x, 193, 51, 27, text, fill=fill, stroke=border,
                  shape_type="rectangle", stroke_pattern=pattern,
                  font_size=7)
        c.box("request", 26, 293, 85, 27, "Request", stroke=TERRA)
        c.box("output", 143, 293, 68, 27, "Output", stroke=BLUE)
        c.edge("load-layer", "cpu-layer-2", "gpu-slot-0", from_side="bottom", to_side="top")
        c.edge("run-request", "gpu-slot-0", "request", color=TERRA,
               from_side="bottom", to_side="top")
        c.edge("write-output", "request", "output", color=TERRA,
               line_type="straight")
        c.label("load-label", 128, 141, 86, 11, "1 Load layer", size=7)
        c.label("serve-label", 124, 254, 92, 11, "2 Use slot", size=7)
        c.label("output-label", 106, 281, 91, 11, "3 Produce", size=7)
        if with_inset:
            _mechanism_inset(c, 346, 12, 213)
        else:
            c.label("state-legend", 12, 330, 213, 11,
                    "Orange: active  |  Blue: ready  |  Dashed: empty", size=7)
        c.footer("Schematic; colored slots do not report measured capacity.")
        return c
    c = Composition("research-mechanism", "Cache and memory detail (schematic)",
                    496.8, 331 if with_inset else 248)
    c.heading("Cache and memory mechanism", "Layer movement and residency are schematic")
    for key, x, width, title, fill in (
        ("cpu-region", 12, 141, "CPU LAYER STORE", PALE_GRAY),
        ("gpu-region", 177, 141, "GPU SLOTS", PALE_BLUE),
        ("request-region", 342, 142, "REQUEST + OUTPUT", PALE_TERRA),
    ):
        c.box(key, x, 49, width, 159, fill=fill, stroke=HAIRLINE,
              shape_type="rectangle", stroke_width=0.6)
        c.label(key + "-heading", x + 9, 56, width - 18, 13, title,
                size=8, bold=True)
    c.box("cpu-store", 23, 77, 119, 112, fill=WHITE, stroke=BLUE)
    c.label("cpu-heading", 30, 81, 105, 12, "Layer blocks", size=8, bold=True)
    for key, x, y, text in (
        ("cpu-layer-1", 31, 103, "L1"), ("cpu-layer-2", 86, 103, "L2"),
        ("cpu-layer-3", 31, 143, "L3"), ("cpu-layer-4", 86, 143, "L4"),
    ):
        c.box(key, x, y, 47, 26, text, fill=PALE_BLUE,
              stroke=BLUE, shape_type="rectangle")
    c.box("gpu-store", 188, 77, 119, 112, fill=WHITE, stroke=BLUE)
    c.label("gpu-heading", 195, 81, 104, 12, "Resident slots", size=8, bold=True)
    for key, x, y, text, fill, border, pattern in (
        ("gpu-slot-0", 196, 103, "L2 active", PALE_TERRA, TERRA, "solid"),
        ("gpu-slot-1", 251, 103, "L3 ready", PALE_BLUE, BLUE, "solid"),
        ("gpu-slot-2", 196, 143, "Empty", WHITE, HAIRLINE, "dashed"),
        ("gpu-slot-3", 251, 143, "Empty", WHITE, HAIRLINE, "dashed"),
    ):
        c.box(key, x, y, 47, 26, text, fill=fill, stroke=border,
              stroke_pattern=pattern, shape_type="rectangle", font_size=7)
    c.box("request", 353, 87, 119, 35, "Request", stroke=TERRA)
    c.box("output", 353, 151, 119, 35, "Output", stroke=BLUE)
    c.edge("load-layer", "cpu-layer-2", "gpu-slot-0")
    c.edge("run-request", "gpu-store", "request", color=TERRA)
    c.edge("write-output", "request", "output", color=TERRA,
           from_side="bottom", to_side="top")
    c.label("load-label", 144, 84, 43, 11, "1 Load", size=7, align="center")
    c.label("serve-label", 308, 84, 45, 11, "2 Use", size=7, align="center")
    c.label("output-label", 430, 127, 43, 11, "3 Produce", size=7, align="center")
    if with_inset:
        _mechanism_inset(c, 218, 159, 180)
        c.label("state-legend", 12, 231, 135, 25,
                "Orange: active\nBlue: ready\nDashed: empty", size=7)
    else:
        c.label("state-legend", 12, 215, 468, 11,
                "Orange: active   Blue: ready   Dashed gray: empty", size=8)
    c.footer("Schematic; the inset is explanatory and has no measured data." if with_inset
             else "Schematic; slots and layer blocks do not report measured capacity.")
    return c


def _expand_width(spec: dict, requested_width: float,
                  template: str, variant: str) -> dict:
    """Reflow outer gaps while preserving object/font sizes and canvas height."""
    canvas = spec["canvases"][0]
    original = canvas["width"]
    extra = requested_width - original
    if extra < -0.001:
        raise ValueError(f"requested width does not fit this composition; minimum is {original / 72:.2f} in")
    if extra < 0.001:
        return spec
    canvas["width"] = round(requested_width, 3)
    anchors = {
        ("architecture", "single"): (61.5, 175.5),
        ("architecture", "double"): (75, 247, 422),
        ("timeline", "single"): (34.5, 90.5, 146.5, 202.5),
        ("timeline", "double"): (147.5, 245.5, 343.5, 441.5),
        ("mechanism", "single"): (54, 120, 186),
        ("mechanism", "double"): (82, 247, 413),
    }[(template, variant)]
    inset_axis = next(((item["x"], item["width"]) for item in canvas["objects"]
                       if item["key"] == "inset-x-axis"), None)
    for obj in canvas["objects"]:
        if obj["kind"] not in ("shape", "text"):
            continue
        if obj["key"] == "background":
            obj["width"] = canvas["width"]
        elif obj["key"] in ("title", "subtitle", "schematic-note"):
            obj["width"] = round(obj["width"] + extra, 3)
        else:
            if template == "mechanism" and variant == "single" and obj["key"].startswith("inset-"):
                if obj["key"] in ("inset-panel", "inset-heading", "inset-x-axis", "inset-x-label"):
                    obj["width"] = round(obj["width"] + extra, 3)
                elif obj["key"].startswith("inset-point-") and inset_axis is not None:
                    relative_x = (obj["x"] - inset_axis[0]) / inset_axis[1]
                    obj["x"] = round(obj["x"] + extra * relative_x, 3)
                # The y-axis stays at the left plot origin. Segments are native
                # connectors and follow the point identities automatically.
                continue
            if ((template == "mechanism" and variant == "single"
                 and (obj["key"].endswith("-region") or obj["key"] in
                      ("state-legend",)))
                    or (template == "timeline" and obj["key"] == "legend")):
                obj["width"] = round(obj["width"] + extra, 3)
                continue
            # Move each component as a unit with its nearest column. Internal
            # layer/slot blocks stay inside their pale region at custom widths.
            center = obj["x"] + obj["width"] / 2
            if template == "mechanism" and variant == "double" and obj["key"].startswith("inset-"):
                index = 1
            else:
                index = min(range(len(anchors)), key=lambda i: abs(center - anchors[i]))
            obj["x"] = round(obj["x"] + extra * index / (len(anchors) - 1), 3)
    return spec


def template_spec(name: str, width_in: float, *, with_inset: bool = False) -> dict:
    if name not in ("architecture", "timeline", "mechanism"):
        raise ValueError("unknown research template")
    if not isinstance(width_in, (int, float)) or isinstance(width_in, bool) or not math.isfinite(width_in) or width_in <= 0:
        raise ValueError("--width-in must be a positive finite number")
    if width_in < 3.3 - 1e-9:
        raise ValueError("requested width does not fit the single-column composition; minimum is 3.30 in")
    if width_in > 12:
        raise ValueError("requested width exceeds the supported 12-inch research canvas")
    if with_inset and name != "mechanism":
        raise ValueError("--with-inset is supported for the mechanism template only")
    variant = "double" if width_in >= 6.9 - 1e-9 else "single"
    builder = {"architecture": lambda: _architecture(variant),
               "timeline": lambda: _timeline(variant),
               "mechanism": lambda: _mechanism(variant, with_inset)}[name]()
    return _expand_width(builder.spec(), round(width_in * 72, 3), name, variant)


def checked_spec(source: Path | dict) -> tuple[dict, dict]:
    spec = contracts.load_json(source) if isinstance(source, Path) else source
    contracts.specification(spec)
    with tempfile.TemporaryDirectory(prefix="omnigraffle-research-check-") as tmp:
        # The native adapter validates connector geometry without launching an app.
        normalized = native.validate_request({
            "op": "create", "path": str(Path(tmp) / "check.graffle"),
            "spec": spec, "working_copy": True,
        })["spec"]
    return spec, normalized


def _preview_point(obj: dict, side: str) -> tuple[float, float]:
    x, y, width, height = (float(obj[key]) for key in ("x", "y", "width", "height"))
    return {"top": (x + width / 2, y), "right": (x + width, y + height / 2),
            "bottom": (x + width / 2, y + height), "left": (x, y + height / 2)}[side]


def _preview_route(obj: dict, objects_by_key: dict) -> list[tuple[float, float]]:
    if "_points" in obj:
        return [tuple(point) for point in obj["_points"]]
    source = objects_by_key[obj["from"]]
    target = objects_by_key[obj["to"]]
    start = _preview_point(source, obj.get("from_side", "right"))
    end = _preview_point(target, obj.get("to_side", "left"))
    if obj.get("line_type") != "orthogonal" or start[0] == end[0] or start[1] == end[1]:
        return [start, end]
    if obj.get("from_side") in ("top", "bottom"):
        return [start, (start[0], (start[1] + end[1]) / 2),
                (end[0], (start[1] + end[1]) / 2), end]
    return [start, ((start[0] + end[0]) / 2, start[1]),
            ((start[0] + end[0]) / 2, end[1]), end]


def preview(normalized: dict, output: Path) -> None:
    canvases = normalized["canvases"]
    if len(canvases) != 1:
        raise ValueError("preview supports one research canvas")
    canvas = canvases[0]
    width, height = int(canvas["width"]), int(canvas["height"])
    svg = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg",
        "width": str(width), "height": str(height + 38),
        "viewBox": f"0 0 {width} {height + 38}",
        "role": "img",
        "aria-label": "Portable preview of OmniGraffle research workflow JSON source",
    })
    ET.SubElement(svg, "rect", {"width": str(width), "height": str(height), "fill": WHITE})
    objects = canvas["objects"]
    objects_by_key = {obj["key"]: obj for obj in objects}
    definitions = ET.SubElement(svg, "defs")
    for color in sorted({obj.get("stroke", INK) for obj in objects
                         if obj["kind"] == "connector" and obj.get("head_arrow") == "filled"}):
        marker = ET.SubElement(definitions, "marker", {
            "id": "arrow-" + color[1:].lower(), "viewBox": "0 0 6 6",
            "refX": "5.7", "refY": "3", "markerWidth": "5", "markerHeight": "5",
            "orient": "auto-start-reverse",
        })
        ET.SubElement(marker, "path", {"d": "M 0 0 L 6 3 L 0 6 z", "fill": color})
    for kind in ("shape", "text", "connector"):
        for obj in objects:
            if obj["kind"] != kind:
                continue
            if kind == "connector":
                points = _preview_route(obj, objects_by_key)
                a, b = points[0], points[-1]
                ink = obj.get("stroke", INK)
                attrs = {"stroke": ink, "stroke-width": str(obj.get("stroke_width", 2)),
                         "fill": "none"}
                if obj.get("stroke_pattern") == "dashed":
                    attrs["stroke-dasharray"] = "4 3"
                if obj.get("head_arrow") == "filled":
                    attrs["marker-end"] = "url(#arrow-" + ink[1:].lower() + ")"
                if len(points) > 2:
                    attrs["points"] = " ".join(f"{x},{y}" for x, y in points)
                    ET.SubElement(svg, "polyline", attrs)
                else:
                    attrs.update(x1=str(a[0]), y1=str(a[1]), x2=str(b[0]), y2=str(b[1]))
                    ET.SubElement(svg, "line", attrs)
                continue
            x, y, w, h = (float(obj[k]) for k in ("x", "y", "width", "height"))
            if kind == "shape":
                attrs = {"fill": obj.get("fill", WHITE),
                         "stroke": obj.get("stroke", INK),
                         "stroke-width": str(obj.get("stroke_width", 1.5))}
                if obj.get("stroke_pattern") == "dashed":
                    attrs["stroke-dasharray"] = "4 3"
                if obj.get("shape_type") == "ellipse":
                    attrs.update(cx=str(x + w / 2), cy=str(y + h / 2),
                                 rx=str(w / 2), ry=str(h / 2))
                    ET.SubElement(svg, "ellipse", attrs)
                else:
                    attrs.update(x=str(x), y=str(y), width=str(w), height=str(h),
                                 rx="4" if obj.get("shape_type", "rounded_rectangle") == "rounded_rectangle" else "0")
                    ET.SubElement(svg, "rect", attrs)
            label = obj.get("text", "")
            if not label:
                continue
            size = int(obj.get("font_size", 16))
            font = obj.get("font_name", "Helvetica")
            padding = float(obj.get("text_padding", 0))
            chars = max(1, int((w - 2 * padding) / (size * 0.53)))
            lines = []
            for explicit in label.split("\n"):
                lines.extend(textwrap.wrap(explicit, width=chars, break_long_words=False,
                                           break_on_hyphens=False) or [""])
            leading = size * 1.15
            valign = obj.get("text_valign", "center")
            if valign == "top":
                first_y = y + padding + size
            elif valign == "bottom":
                first_y = y + h - padding - (len(lines) - 1) * leading
            else:
                first_y = y + h / 2 - (len(lines) - 1) * leading / 2 + size * 0.36
            align = obj.get("text_align", "center")
            anchor = {"left": "start", "center": "middle", "right": "end"}[align]
            anchor_x = {"left": x + padding, "center": x + w / 2,
                        "right": x + w - padding}[align]
            for i, line in enumerate(lines):
                ET.SubElement(svg, "text", {
                    "x": str(anchor_x), "y": str(first_y + i * leading),
                    "text-anchor": anchor, "font-family": "Helvetica, Arial, sans-serif",
                    "font-size": str(size),
                    "font-weight": "bold" if "Bold" in font else "normal",
                    "fill": obj.get("text_color", INK),
                }).text = line
    ET.SubElement(svg, "rect", {
        "x": "0", "y": str(height), "width": str(width), "height": "38",
        "fill": "#FCF3ED",
    })
    ET.SubElement(svg, "text", {
        "x": "10", "y": str(height + 15), "font-family": "Arial, sans-serif",
        "font-size": "11" if width > 300 else "9", "fill": "#63365F",
    }).text = "PORTABLE PREVIEW ONLY"
    ET.SubElement(svg, "text", {
        "x": "10", "y": str(height + 30), "font-family": "Arial, sans-serif",
        "font-size": "10" if width > 300 else "8", "fill": "#63365F",
    }).text = "No native .graffle was created or inspected"
    ET.indent(svg, space="  ")
    output.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n'
                       + ET.tostring(svg, encoding="utf-8") + b"\n")


def new_request(spec: dict, output: Path, request_out: Path) -> dict:
    if not output.is_absolute() or not request_out.is_absolute():
        raise ValueError("output and request paths must be absolute")
    if output == request_out or output.suffix != ".graffle" or request_out.suffix != ".json":
        raise ValueError("choose distinct .graffle output and .json request paths")
    if output.exists() or request_out.exists() or output.is_symlink() or request_out.is_symlink():
        raise ValueError("refusing to replace an existing native file or request")
    if not output.parent.is_dir() or not request_out.parent.is_dir():
        raise ValueError("output and request parent directories must exist")
    request = {"operation_id": str(uuid.uuid4()), "output": str(output), "spec": spec}
    contracts.validate_request("create", request)
    # The native adapter validates placement on a non-existing output path.
    native.validate_request({"op": "create", "path": str(output),
                             "spec": spec, "working_copy": True})
    return request


def _fresh_file(path: Path) -> None:
    if not path.is_absolute() or not path.parent.is_dir() or path.exists() or path.is_symlink():
        raise ValueError(f"output must be a new absolute file in an existing directory: {path}")


def write_source(spec: dict, output: Path) -> Path:
    if output.suffix != ".json":
        raise ValueError("source output must end in .json")
    palette_out = output.with_name(output.stem + ".palette.json")
    _fresh_file(output)
    _fresh_file(palette_out)
    palette = contracts.load_json(PALETTE_SOURCE)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(spec, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    try:
        with palette_out.open("x", encoding="utf-8") as stream:
            json.dump(palette, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except OSError:
        output.unlink()
        raise
    return palette_out


def write_gallery(output_dir: Path) -> dict:
    if not output_dir.is_absolute() or not output_dir.is_dir() or any(output_dir.iterdir()):
        raise ValueError("gallery requires a new empty absolute directory")
    entries = []
    for name in ("architecture", "timeline", "mechanism"):
        for width_name, width_in in STANDARD_WIDTHS.items():
            spec, normalized = checked_spec(template_spec(name, width_in))
            filename = f"{name}-{width_name}.preview.svg"
            preview(normalized, output_dir / filename)
            entries.append((name, width_name, filename, len(spec["canvases"][0]["objects"])))
    cards = "\n".join(
        f'<article><h2>{name.title()} · {width_name}</h2>'
        f'<object data="{filename}" type="image/svg+xml"></object>'
        '<p>Portable approximation only. Native save, reopen, export, and visual acceptance are pending.</p></article>'
        for name, width_name, filename, _ in entries)
    page = ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>OmniGraffle research template previews</title>'
            '<style>body{font:16px system-ui;margin:2rem;color:#30343A;background:#f4f5f6}'
            'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(20rem,1fr));gap:1rem}'
            'article{background:white;padding:1rem;border:1px solid #b9c0c7}'
            'object{width:100%;height:27rem;border:1px solid #ddd}</style>'
            '<h1>Research figure template previews</h1><p>Six synthetic, editable-source compositions.'
            ' Each displayed SVG is an offline preview. No native .graffle output is implied.</p>'
            f'<main>{cards}</main></html>')
    (output_dir / "index.html").write_text(page, encoding="utf-8")
    return {"status": "portable_gallery_only", "index": str(output_dir / "index.html"),
            "previews": len(entries)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--spec", type=Path)
    source.add_argument("--template", choices=("architecture", "timeline", "mechanism"))
    sizes = parser.add_mutually_exclusive_group()
    sizes.add_argument("--width", choices=("single", "double"))
    sizes.add_argument("--width-in", type=float)
    parser.add_argument("--with-inset", action="store_true")
    command = parser.add_subparsers(dest="command", required=True)
    command.add_parser("validate")
    view = command.add_parser("preview")
    view.add_argument("--out", type=Path, required=True)
    source_command = command.add_parser("source")
    source_command.add_argument("--out", type=Path, required=True)
    prepare = command.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--request-out", type=Path, required=True)
    gallery = command.add_parser("gallery")
    gallery.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "gallery":
        if args.spec or args.template or args.width or args.width_in or args.with_inset:
            parser.error("gallery generates all six standard templates; do not select one source")
        try:
            print(json.dumps(write_gallery(args.out_dir)))
        except (ValueError, contracts.CommandError, OSError) as error:
            parser.error(str(error))
        return 0
    if args.template:
        width_in = args.width_in if args.width_in is not None else STANDARD_WIDTHS[args.width or "double"]
        try:
            input_source = template_spec(args.template, width_in,
                                         with_inset=args.with_inset)
        except ValueError as error:
            parser.error(str(error))
    else:
        if args.width or args.width_in is not None or args.with_inset:
            parser.error("--width, --width-in and --with-inset require --template")
        input_source = args.spec or DEFAULT_SPEC
    if args.command == "source" and not args.template:
        parser.error("source requires --template")
    try:
        spec, normalized = checked_spec(input_source)
    except (ValueError, contracts.CommandError, OSError) as error:
        parser.error(str(error))
    canvas = spec["canvases"][0]
    if args.command == "validate":
        result = {"status": "validated_source_spec", "canvases": len(spec["canvases"]),
                  "objects": len(canvas["objects"])}
        if args.template:
            result.update(template=args.template, width_in=round(canvas["width"] / 72, 4))
        print(json.dumps(result))
    elif args.command == "preview":
        try:
            _fresh_file(args.out)
        except ValueError as error:
            parser.error(str(error))
        preview(normalized, args.out)
        print(json.dumps({"status": "portable_preview_only", "path": str(args.out)}))
    elif args.command == "source":
        try:
            palette_out = write_source(spec, args.out)
        except (ValueError, contracts.CommandError, OSError) as error:
            parser.error(str(error))
        print(json.dumps({"status": "source_written_not_created", "spec": str(args.out),
                          "palette": str(palette_out)}))
    else:
        try:
            request = new_request(spec, args.output, args.request_out)
        except (ValueError, contracts.CommandError) as error:
            parser.error(str(error))
        with args.request_out.open("x", encoding="utf-8") as stream:
            json.dump(request, stream, indent=2)
            stream.write("\n")
        print(json.dumps({"status": "request_prepared_not_created",
                          "request": str(args.request_out), "output": str(args.output),
                          "operation_id": request["operation_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
