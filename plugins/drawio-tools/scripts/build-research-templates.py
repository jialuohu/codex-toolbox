#!/usr/bin/env python3
"""Build the editable, synthetic Draw.io research-figure templates.

Only Python's standard library is needed.  The checked-in .drawio files are
uncompressed XML, and each visible part remains an individual editable cell.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "assets" / "research-templates"

# Selected from photo-tools/skills/mono-color/references/design-system/colors.json.
# Copy these values with a research project; never require the installed catalog.
INK = "#30343A"
COBALT = "#2148B8"
TERRACOTTA = "#C65F38"
GREEN = "#008A4B"
PALE_BLUE = "#F0F4FC"
PALE_ORANGE = "#FCF3ED"
PALE_GREEN = "#EFF8F2"
PALE_GRAY = "#F4F5F6"
GRAY = "#65707C"
LINE = "#B9C0C7"
WHITE = "#FFFFFF"


class Diagram:
    def __init__(self, name: str, width: int, height: int):
        self.width = width
        # At a 6.9-inch final placement, every editable text cell is >= 7 pt.
        # Draw.io's SVG font sizes and viewBox coordinates both use px.
        self.min_font = math.ceil(7 * width / (6.9 * 72))
        self.file = ET.Element(
            "mxfile", {"host": "app.diagrams.net", "agent": "codex-toolbox research templates"}
        )
        self.file.append(
            ET.Comment(
                " Palette: Cobalt #2148B8, Terracotta #C65F38, Botanical Green "
                "#008A4B, Charcoal #30343A from photo-tools mono-color "
                "colors.json. All timing and plotted values are schematic/synthetic. "
            )
        )
        page = ET.SubElement(self.file, "diagram", {"id": name, "name": name})
        model = ET.SubElement(
            page,
            "mxGraphModel",
            {
                "dx": str(width),
                "dy": str(height),
                "grid": "1",
                "gridSize": "10",
                "guides": "1",
                "tooltips": "1",
                "connect": "1",
                "arrows": "1",
                "fold": "1",
                "page": "1",
                "pageScale": "1",
                "pageWidth": str(width),
                "pageHeight": str(height),
                "math": "0",
                "shadow": "0",
            },
        )
        self.root = ET.SubElement(model, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})
        self.ids: set[str] = {"0", "1"}

    def _id(self, value: str) -> str:
        if value in self.ids:
            raise ValueError(f"duplicate Draw.io ID: {value}")
        self.ids.add(value)
        return value

    def box(
        self,
        id: str,
        x: int,
        y: int,
        width: int,
        height: int,
        label: str = "",
        *,
        fill: str = WHITE,
        stroke: str = LINE,
        font: int = 18,
        color: str = INK,
        rounded: bool = True,
        align: str = "center",
        bold: bool = False,
        dashed: bool = False,
        spacing: int = 6,
    ) -> None:
        font = max(font, self.min_font)
        style = (
            f"rounded={int(rounded)};whiteSpace=wrap;html=0;fillColor={fill};"
            f"strokeColor={stroke};fontColor={color};fontFamily=Helvetica;"
            f"fontSize={font};fontStyle={int(bold)};align={align};verticalAlign=middle;"
            f"spacing={spacing};strokeWidth=1.5;dashed={int(dashed)};"
        )
        cell = ET.SubElement(
            self.root,
            "mxCell",
            {"id": self._id(id), "value": label, "style": style, "vertex": "1", "parent": "1"},
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {"x": str(x), "y": str(y), "width": str(width), "height": str(height), "as": "geometry"},
        )

    def text(
        self,
        id: str,
        x: int,
        y: int,
        width: int,
        height: int,
        label: str,
        *,
        font: int = 18,
        color: str = INK,
        align: str = "left",
        bold: bool = False,
    ) -> None:
        self.box(
            id, x, y, width, height, label,
            fill="none", stroke="none", font=font, color=color,
            rounded=False, align=align, bold=bold, spacing=0,
        )

    def circle(self, id: str, x: int, y: int, label: str, *, color: str = COBALT) -> None:
        self.box(
            id, x, y, 34, 34, label,
            fill=WHITE, stroke=color, font=17, color=color,
            rounded=False,
        )
        cell = self.root[-1]
        cell.set("style", cell.get("style", "") + "shape=ellipse;strokeWidth=2;")

    def segment(
        self, id: str, x: int, y: int, width: int, height: int, label: str,
        *, fill: str, color: str = INK, font: int = 15,
    ) -> None:
        self.box(
            id, x, y, width, height, label,
            fill=fill, stroke=WHITE, font=font, color=color,
            rounded=False,
        )

    def line(
        self,
        id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        color: str = INK,
        width: float = 2,
        arrow: bool = False,
        dashed: bool = False,
    ) -> None:
        style = (
            f"edgeStyle=none;html=0;rounded=0;strokeColor={color};strokeWidth={width};"
            f"endArrow={'block' if arrow else 'none'};endFill=1;dashed={int(dashed)};"
        )
        edge = ET.SubElement(
            self.root,
            "mxCell",
            {"id": self._id(id), "style": style, "edge": "1", "parent": "1"},
        )
        geom = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        ET.SubElement(geom, "mxPoint", {"x": str(x1), "y": str(y1), "as": "sourcePoint"})
        ET.SubElement(geom, "mxPoint", {"x": str(x2), "y": str(y2), "as": "targetPoint"})

    def bytes(self) -> bytes:
        ET.indent(self.file, space="  ")
        return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            self.file, encoding="utf-8"
        ) + b"\n"


def architecture() -> Diagram:
    d = Diagram("Numbered architecture overview", 1240, 720)
    d.text("title", 48, 32, 1144, 46, "Numbered architecture overview", font=30, bold=True)
    d.text("subtitle", 48, 78, 1144, 32,
           "Schematic example: replace roles and arrows with the verified system workflow", font=17, color=GRAY)

    d.box("requests-group", 48, 142, 245, 410, fill=PALE_GRAY, stroke=LINE)
    d.box("control-group", 328, 142, 450, 410, fill=PALE_BLUE, stroke=LINE)
    d.box("workers-group", 812, 142, 380, 410, fill=PALE_GREEN, stroke=LINE)
    d.text("requests-heading", 72, 163, 197, 32, "REQUESTS", font=18, bold=True)
    d.text("control-heading", 350, 163, 405, 32, "CONTROL", font=18, bold=True)
    d.text("workers-heading", 836, 163, 332, 32, "EXECUTION", font=18, bold=True)

    d.box("client", 75, 236, 190, 66, "Client", font=19, bold=True)
    d.box("request-queue", 75, 390, 190, 66, "Request queue", font=19)
    d.box("admission", 355, 236, 175, 66, "Admission", font=19)
    d.box("scheduler", 573, 236, 177, 66, "Scheduler", font=19, bold=True)
    d.box("state", 462, 395, 190, 76, "Resource state", font=19)
    d.box("worker-a", 839, 236, 150, 66, "Worker A", font=19)
    d.box("worker-b", 1014, 236, 150, 66, "Worker B", font=19)
    d.box("memory", 854, 387, 295, 88)
    d.text("memory-heading", 869, 394, 265, 28, "Memory / cache", font=19, bold=True)
    for i, (x, fill, label) in enumerate(
        [(872, PALE_BLUE, "L1"), (960, PALE_ORANGE, "L2"), (1048, PALE_GREEN, "L3")], 1
    ):
        d.segment(f"layer-{i}", x, 436, 82, 30, label, fill=fill)

    d.line("client-to-queue", 170, 302, 170, 390, arrow=True)
    d.line("queue-to-admission", 265, 423, 355, 268, arrow=True)
    d.line("admission-to-scheduler", 530, 269, 573, 269, arrow=True)
    d.line("state-to-scheduler", 557, 395, 642, 302, arrow=True, dashed=True)
    d.line("scheduler-to-workers", 750, 269, 839, 269, arrow=True)
    d.line("worker-to-cache", 914, 302, 914, 387, arrow=True)
    d.line("cache-to-state", 854, 429, 652, 429, arrow=True, dashed=True)

    d.circle("step-1", 292, 326, "1")
    d.text("step-1-label", 275, 365, 91, 30, "Submit", font=16, color=COBALT)
    d.circle("step-2", 542, 206, "2")
    d.text("step-2-label", 505, 185, 111, 26, "Assign", font=16, color=COBALT)
    d.circle("step-3", 783, 220, "3")
    d.text("step-3-label", 769, 190, 108, 26, "Execute", font=16, color=COBALT)
    d.circle("step-4", 788, 410, "4", color=TERRACOTTA)
    d.text("step-4-label", 752, 449, 106, 27, "Update", font=16, color=TERRACOTTA)

    d.text("legend", 48, 591, 1144, 72,
           "Solid arrows: work flow.  Dashed arrows: state feedback.  Colored layer blocks illustrate distinct cached layers; they are not measured capacity.",
           font=17, color=GRAY)
    return d


def timeline() -> Diagram:
    d = Diagram("Aligned execution timeline", 1410, 820)
    d.text("title", 50, 30, 1300, 44, "Baseline / proposed execution timeline", font=29, bold=True)
    d.text("note", 50, 76, 1300, 40,
           "Schematic event order only. Equal column widths do not represent measured time or latency.",
           font=18, color=GRAY)
    left, cw = 260, 174
    labels = ["Request 1", "Load", "Run 1", "Idle", "Request 2", "Run 2"]
    for j, label in enumerate(labels):
        x = left + j * cw
        d.text(f"event-{j}", x, 120, cw, 35, label, font=16, align="center", color=GRAY)

    def row(section: str, top: int, proposed: bool) -> None:
        d.box(f"{section}-band", 49, top, 1302, 275,
              fill=PALE_GREEN if proposed else PALE_GRAY, stroke=LINE)
        # Draw guides after the opaque section band, before state bars.
        for j in range(7):
            x = left + j * cw
            d.line(f"{section}-grid-{j}", x, top + 50, x, top + 265,
                   color="#D8DDE2", width=1)
        d.text(f"{section}-heading", 70, top + 12, 170, 35,
               "PROPOSED" if proposed else "BASELINE", font=20, bold=True,
               color=GREEN if proposed else INK)
        lane_names = ["Invocation", "Keep-alive", "Execution", "Layer cache"]
        y_positions = [top + 56, top + 108, top + 160, top + 212]
        for lane, y in zip(lane_names, y_positions):
            d.text(f"{section}-{lane}-label", 72, y, 166, 36, lane, font=16)
            d.line(f"{section}-{lane}-rule", left, y + 40, left + 6 * cw, y + 40,
                   color="#CFD5DA", width=1)

        def bar(id: str, first: int, count: int, lane: int, label: str, fill: str) -> None:
            d.box(id, left + first * cw + 7, y_positions[lane] + 2,
                  count * cw - 14, 35, label, fill=fill, stroke=fill,
                  font=15, color=WHITE if fill in (COBALT, TERRACOTTA, GREEN) else INK,
                  rounded=False)

        bar(f"{section}-invoke-1", 0, 1, 0, "invoke", COBALT)
        bar(f"{section}-invoke-2", 4, 1, 0, "invoke", COBALT)
        bar(f"{section}-keep", 2 if proposed else 3, 3 if proposed else 1,
            1, "retained" if proposed else "idle", "#DDE6F7")
        bar(f"{section}-exec-1", 2, 1, 2, "run", GREEN)
        bar(f"{section}-exec-2", 5, 1, 2, "run", GREEN)
        if proposed:
            bar(f"{section}-cache-1", 1, 2, 3, "L1 + L2 loaded", TERRACOTTA)
            bar(f"{section}-cache-2", 3, 3, 3, "L1 + L2 retained", TERRACOTTA)
        else:
            bar(f"{section}-cache-1", 1, 2, 3, "load L1 + L2", TERRACOTTA)
            bar(f"{section}-cache-2", 4, 2, 3, "reload L1 + L2", TERRACOTTA)

    row("baseline", 163, False)
    row("proposed", 456, True)
    d.text("footer", 49, 756, 1302, 38,
           "Replace event order and states from evidence; add a numeric axis only when measurements are available.",
           font=17, color=GRAY)
    return d


def mechanism() -> Diagram:
    d = Diagram("Cache memory mechanism", 1280, 810)
    d.text("title", 48, 27, 1180, 45, "Cache / memory mechanism detail", font=29, bold=True)
    d.text("subtitle", 48, 74, 1180, 37,
           "Schematic layer placement; the optional inset uses synthetic normalized values", font=18, color=GRAY)

    d.box("model-group", 50, 145, 296, 447, fill=PALE_GRAY)
    d.box("policy-group", 395, 145, 362, 447, fill=PALE_BLUE)
    d.box("memory-group", 807, 145, 423, 447, fill=PALE_ORANGE)
    d.text("model-heading", 73, 164, 250, 32, "MODEL LAYERS", font=18, bold=True)
    d.text("policy-heading", 419, 164, 317, 32, "PLACEMENT POLICY", font=18, bold=True)
    d.text("memory-heading", 830, 164, 376, 32, "MEMORY TIERS", font=18, bold=True)

    d.box("request", 79, 221, 236, 50, "Incoming request", font=18)
    for i, (y, label, fill) in enumerate(
        [(309, "Layer L1", PALE_BLUE), (366, "Layer L2", PALE_GREEN), (423, "Layer L3", PALE_ORANGE)], 1
    ):
        d.box(f"source-layer-{i}", 103, y, 188, 45, label,
              fill=fill, stroke=LINE, font=17, rounded=False)
    d.text("source-note", 73, 524, 250, 39,
           "One block per layer", font=15, color=GRAY)

    d.box("lookup", 425, 225, 302, 61, "Look up resident layers", font=18, bold=True)
    d.box("decision", 425, 348, 302, 65, "Select transfers", font=18, bold=True)
    d.box("launch", 425, 477, 302, 65, "Launch execution", font=18, bold=True)
    d.line("lookup-to-decision", 575, 286, 575, 348, arrow=True)
    d.line("decision-to-launch", 575, 413, 575, 477, arrow=True)

    d.box("fast-tier", 833, 225, 371, 122)
    d.text("fast-tier-heading", 851, 237, 335, 31, "Fast memory", font=18, bold=True)
    for i, (x, fill, label) in enumerate(
        [(851, PALE_BLUE, "L1"), (961, PALE_GREEN, "L2"), (1071, WHITE, "free")], 1
    ):
        d.segment(f"fast-slot-{i}", x, 292, 101, 42, label, fill=fill)
    d.box("slow-tier", 833, 420, 371, 122)
    d.text("slow-tier-heading", 851, 432, 335, 31, "Backing store", font=18, bold=True)
    for i, (x, fill, label) in enumerate(
        [(851, PALE_ORANGE, "L3"), (961, PALE_GRAY, "L4"), (1071, PALE_GRAY, "L5")], 1
    ):
        d.segment(f"slow-slot-{i}", x, 487, 101, 42, label, fill=fill)

    d.line("layers-to-lookup", 291, 389, 425, 254, arrow=True)
    d.line("lookup-to-fast", 727, 254, 833, 254, arrow=True, dashed=True)
    d.line("decision-to-store", 727, 381, 833, 479, arrow=True)
    d.line("store-to-fast", 1018, 420, 1018, 347, arrow=True, color=TERRACOTTA)
    d.circle("step-1", 353, 279, "1")
    d.circle("step-2", 755, 340, "2")
    d.circle("step-3", 1028, 370, "3", color=TERRACOTTA)
    d.text("step-1-label", 342, 316, 75, 25, "Lookup", font=15, color=COBALT)
    d.text("step-2-label", 748, 377, 90, 25, "Select", font=15, color=COBALT)
    d.text("step-3-label", 1065, 373, 117, 25, "Transfer L3", font=15, color=TERRACOTTA)

    # Each axis, polyline segment, and marker is a native editable vector cell.
    d.box("inset-panel", 709, 614, 521, 163, fill=WHITE, stroke=LINE)
    d.text("inset-title", 726, 621, 488, 28,
           "Optional explanatory inset (synthetic)", font=16, bold=True)
    d.line("inset-x", 815, 743, 1181, 743, width=1.5)
    d.line("inset-y", 815, 659, 815, 743, width=1.5)
    d.text("inset-x-label", 855, 748, 311, 24, "Cache budget (normalized)", font=14, align="center")
    d.text("inset-y-label", 727, 664, 80, 58, "Cold\nstarts", font=13, align="center")
    points = [(849, 678), (929, 695), (1009, 712), (1089, 720), (1160, 725)]
    for i, ((x1, y1), (x2, y2)) in enumerate(zip(points, points[1:]), 1):
        d.line(f"inset-segment-{i}", x1, y1, x2, y2, color=COBALT, width=2)
    for i, (x, y) in enumerate(points, 1):
        d.box(f"inset-point-{i}", x - 4, y - 4, 8, 8,
              fill=COBALT, stroke=COBALT, rounded=False)
        d.root[-1].set("style", d.root[-1].get("style", "") + "shape=ellipse;")
    d.text("inset-caveat", 48, 646, 620, 105,
           "Use the inset only to explain a mechanism. Replace synthetic marks and axes with explicit data before reporting a measured effect.",
           font=17, color=GRAY)
    return d


TEMPLATES = {
    "architecture-overview.drawio": architecture,
    "execution-timeline.drawio": timeline,
    "cache-memory-mechanism.drawio": mechanism,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="fail if checked-in templates differ")
    args = parser.parse_args()
    if not args.check:
        args.out_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    for filename, make in TEMPLATES.items():
        path = args.out_dir / filename
        data = make().bytes()
        if args.check:
            if not path.is_file() or path.read_bytes() != data:
                errors.append(str(path))
        else:
            path.write_bytes(data)
    if errors:
        parser.error("templates missing or changed: " + ", ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
