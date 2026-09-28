#!/usr/bin/env python3
"""Render a limited, clearly labelled SVG preview of research .drawio templates.

This is for gallery/visual QA only. It is not a Draw.io export and cannot
validate Draw.io-specific layout, fonts, or embedded-source behavior.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import textwrap
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE.parent / "assets" / "research-templates"
NAMES = (
    "architecture-overview.drawio",
    "execution-timeline.drawio",
    "cache-memory-mechanism.drawio",
)


def style_map(raw: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in raw.split(";") if "=" in part)


def css_color(raw: str | None, fallback: str = "none") -> str:
    if not raw or raw == "none":
        return fallback
    if raw.startswith("#") and len(raw) in (4, 7):
        return raw
    raise ValueError(f"unsupported template color: {raw}")


def wrap_label(value: str, width: float, size: int) -> list[str]:
    max_chars = max(1, int(width / (size * 0.54)))
    lines: list[str] = []
    for explicit in value.split("\n"):
        lines.extend(textwrap.wrap(explicit, width=max_chars, break_long_words=False,
                                   break_on_hyphens=False) or [""])
    return lines


def render(source: Path, output: Path) -> None:
    tree = ET.parse(source)
    file = tree.getroot()
    if file.tag != "mxfile" or len(file.findall("diagram")) != 1:
        raise ValueError(f"expected one uncompressed Draw.io page: {source}")
    model = file.find("./diagram/mxGraphModel")
    if model is None:
        raise ValueError(f"missing uncompressed mxGraphModel: {source}")
    width = int(model.attrib["pageWidth"])
    height = int(model.attrib["pageHeight"])
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid Draw.io page size: {source}")

    svg = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg",
        "width": str(width),
        "height": str(height + 38),
        "viewBox": f"0 0 {width} {height + 38}",
        "role": "img",
        "aria-label": f"Portable preview of {source.name}; verify native Draw.io export",
    })
    ET.SubElement(svg, "rect", {"width": str(width), "height": str(height), "fill": "#FFFFFF"})

    for cell in model.findall("./root/mxCell"):
        if cell.get("id") in ("0", "1"):
            continue
        style = style_map(cell.get("style", ""))
        geometry = cell.find("mxGeometry")
        if geometry is None:
            raise ValueError(f"cell {cell.get('id')} lacks geometry: {source}")
        stroke = css_color(style.get("strokeColor"), "none")
        stroke_width = style.get("strokeWidth", "1")
        dash = "5,4" if style.get("dashed") == "1" else None
        if cell.get("edge") == "1":
            points = {p.get("as"): p for p in geometry.findall("mxPoint")}
            if set(points) != {"sourcePoint", "targetPoint"}:
                raise ValueError(f"unsupported edge geometry: {cell.get('id')}")
            start, end = points["sourcePoint"], points["targetPoint"]
            attrs = {
                "x1": start.attrib["x"], "y1": start.attrib["y"],
                "x2": end.attrib["x"], "y2": end.attrib["y"],
                "stroke": stroke, "stroke-width": stroke_width,
            }
            if dash:
                attrs["stroke-dasharray"] = dash
            ET.SubElement(svg, "line", attrs)
            if style.get("endArrow") == "block":
                x1, y1 = float(start.attrib["x"]), float(start.attrib["y"])
                x2, y2 = float(end.attrib["x"]), float(end.attrib["y"])
                length = math.hypot(x2 - x1, y2 - y1)
                if length == 0:
                    raise ValueError(f"zero-length arrow: {cell.get('id')}")
                ux, uy = (x2 - x1) / length, (y2 - y1) / length
                bx, by = x2 - 11 * ux, y2 - 11 * uy
                points = (
                    f"{x2},{y2} "
                    f"{bx - 4.5 * uy},{by + 4.5 * ux} "
                    f"{bx + 4.5 * uy},{by - 4.5 * ux}"
                )
                ET.SubElement(svg, "polygon", {"points": points, "fill": stroke})
            continue
        if cell.get("vertex") != "1":
            raise ValueError(f"unsupported cell type: {cell.get('id')}")
        if style.get("shape") not in (None, "ellipse"):
            raise ValueError(f"unsupported preview shape: {cell.get('id')}")
        x = float(geometry.attrib["x"])
        y = float(geometry.attrib["y"])
        w = float(geometry.attrib["width"])
        h = float(geometry.attrib["height"])
        fill = css_color(style.get("fillColor"), "none")
        if fill != "none" or stroke != "none":
            common = {"fill": fill, "stroke": stroke, "stroke-width": stroke_width}
            if dash:
                common["stroke-dasharray"] = dash
            if style.get("shape") == "ellipse":
                ET.SubElement(svg, "ellipse", {
                    **common, "cx": str(x + w / 2), "cy": str(y + h / 2),
                    "rx": str(w / 2), "ry": str(h / 2),
                })
            else:
                radius = "8" if style.get("rounded") == "1" else "0"
                ET.SubElement(svg, "rect", {
                    **common, "x": str(x), "y": str(y), "width": str(w),
                    "height": str(h), "rx": radius,
                })
        value = cell.get("value", "")
        if not value:
            continue
        size = int(style.get("fontSize", "18"))
        lines = wrap_label(value, w - 12, size)
        line_height = size * 1.12
        start_y = y + h / 2 - (len(lines) - 1) * line_height / 2 + size * 0.35
        align = style.get("align", "center")
        tx, anchor = (x + w / 2, "middle") if align == "center" else (x + 6, "start")
        common_text = {
            "x": str(tx), "text-anchor": anchor,
            "font-family": style.get("fontFamily", "Helvetica") + ", Arial, sans-serif",
            "font-size": str(size),
            "font-weight": "bold" if style.get("fontStyle") == "1" else "normal",
            "fill": css_color(style.get("fontColor"), "#30343A"),
        }
        for i, line in enumerate(lines):
            ET.SubElement(svg, "text", {
                **common_text, "y": str(start_y + i * line_height),
            }).text = line

    ET.SubElement(svg, "rect", {
        "x": "0", "y": str(height), "width": str(width), "height": "38", "fill": "#FCF3ED",
    })
    ET.SubElement(svg, "text", {
        "x": "18", "y": str(height + 25), "font-family": "Arial, sans-serif",
        "font-size": "16", "fill": "#63365F",
    }).text = "PORTABLE PREVIEW ONLY - verify native Draw.io export before publication"
    ET.indent(svg, space="  ")
    output.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n'
                       + ET.tostring(svg, encoding="utf-8") + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        source = args.source_dir / name
        if not source.is_file():
            parser.error(f"missing Draw.io template: {source}")
        render(source, args.out_dir / name.replace(".drawio", ".preview.svg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
