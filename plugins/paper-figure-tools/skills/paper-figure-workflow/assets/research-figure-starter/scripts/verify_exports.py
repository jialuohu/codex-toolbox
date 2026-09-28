#!/usr/bin/env python3
"""Verify fixed SVG/PDF canvases, editable text, and embedded PDF fonts."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def inches(value: str) -> float:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(pt|in|px)", value)
    if not match:
        raise ValueError(f"unsupported SVG dimension: {value!r}")
    number = float(match.group(1))
    return number / 72 if match.group(2) == "pt" else number if match.group(2) == "in" else number / 96


def svg_geometry(path: Path) -> tuple[float, list[float]]:
    root = ET.parse(path).getroot()
    width = inches(root.attrib["width"])
    text_nodes = root.findall(".//{http://www.w3.org/2000/svg}text")
    if not text_nodes:
        raise ValueError(f"{path} has no editable SVG text nodes")
    sizes = []
    for node in text_nodes:
        style = node.attrib.get("style", "")
        match = re.search(r"(?:font-size:\s*|font:\s*)([0-9]+(?:\.[0-9]+)?)px", style)
        if match:
            sizes.append(float(match.group(1)))
    if not sizes:
        raise ValueError(f"{path} has no inspectable SVG font sizes")
    return width, sizes


def pdf_width(path: Path) -> float:
    content = path.read_bytes()
    match = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]", content)
    if not match:
        raise ValueError(f"{path} has no inspectable PDF MediaBox")
    return float(match.group(1)) / 72


def verify_fonts(path: Path) -> None:
    tool = shutil.which("pdffonts")
    if tool is None:
        raise RuntimeError("pdffonts (Poppler) is required to verify PDF font embedding")
    result = subprocess.run([tool, str(path)], capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines()[2:]
    if not lines:
        raise ValueError(f"{path} contains no inspectable fonts")
    if not any("DejaVuSans" in line for line in lines):
        raise ValueError(f"{path} does not embed the DejaVu Sans baseline")
    names = []
    for line in lines:
        match = re.search(r"\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$", line)
        if not match or match.group(1) != "yes":
            raise ValueError(f"{path} contains an uninspectable or non-embedded font")
        names.append(line.split()[0])
    report_path = path.with_suffix(".fonts.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["pdf_fonts"] = names
    report["unexpected_pdf_fonts"] = [name for name in names if "DejaVuSans" not in name]
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["unexpected_pdf_fonts"]:
        raise ValueError(f"{path} uses additional fonts; inspect recorded substitutions in {report_path}")


def verify(path: Path, width: float, target_width: float | None) -> None:
    svg = path.with_suffix(".svg")
    pdf = path.with_suffix(".pdf")
    if not svg.is_file() or not pdf.is_file():
        raise FileNotFoundError(f"missing SVG/PDF pair for {path.name}")
    actual_svg, sizes = svg_geometry(svg)
    actual_pdf = pdf_width(pdf)
    for format_name, actual in (("SVG", actual_svg), ("PDF", actual_pdf)):
        if abs(actual - width) > 0.01:
            raise ValueError(f"{format_name} width for {path.name} is {actual:.3f} in; expected {width:.3f} in")
    scaled_min = min(sizes) * ((target_width or width) / actual_svg)
    if scaled_min < 7 - 1e-6:
        raise ValueError(f"{path.name} text falls below 7 pt after placement: {scaled_min:.2f} pt")
    verify_fonts(pdf)
    print(f"{path.name}: SVG {actual_svg:.3f} in, PDF {actual_pdf:.3f} in, minimum placed text {scaled_min:.2f} pt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--expect", action="append", required=True, metavar="NAME=WIDTH_IN")
    parser.add_argument("--target-width-in", type=float, help="Optional final placement width for text-size check")
    args = parser.parse_args()
    if args.target_width_in is not None and (not math.isfinite(args.target_width_in) or args.target_width_in <= 0):
        parser.error("--target-width-in must be a positive finite number")
    try:
        for item in args.expect:
            name, raw_width = item.split("=", 1)
            width = float(raw_width)
            if not math.isfinite(width) or width <= 0:
                raise ValueError("expected width must be a positive finite number")
            verify(args.out_dir / name, width, args.target_width_in)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"figure verification failed: {exc}") from exc


if __name__ == "__main__":
    main()
