"""Portable checks for the native research Draw.io source templates."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


PLUGIN = Path(__file__).resolve().parents[1]
SOURCES = PLUGIN / "assets" / "research-templates"
BUILD = PLUGIN / "scripts" / "build-research-templates.py"
PREVIEW = PLUGIN / "scripts" / "preview-research-templates.py"
NAMES = (
    "architecture-overview.drawio",
    "execution-timeline.drawio",
    "cache-memory-mechanism.drawio",
)


def model(name: str) -> tuple[ET.Element, dict[str, ET.Element]]:
    source = ET.parse(SOURCES / name).getroot()
    page = source.find("diagram")
    assert page is not None
    graph = page.find("mxGraphModel")
    assert graph is not None
    cells = {c.attrib["id"]: c for c in graph.findall("./root/mxCell")}
    return graph, cells


class ResearchTemplatesTest(unittest.TestCase):
    def test_checked_in_templates_are_reproducible(self):
        subprocess.run(["python3", str(BUILD), "--check"], check=True, capture_output=True)

    def test_portable_preview_is_labelled_and_reads_project_copy(self):
        with tempfile.TemporaryDirectory(prefix="drawio-template-preview-") as tmp:
            root = Path(tmp)
            copied = root / "diagrams"
            copied.mkdir()
            for name in NAMES:
                shutil.copy2(SOURCES / name, copied / name)
            edited = copied / NAMES[0]
            edited.write_text(edited.read_text().replace('value="Client"', 'value="Client X"'))
            out = root / "preview"
            subprocess.run(["python3", str(PREVIEW), "--source-dir", str(copied),
                            "--out-dir", str(out)], check=True, capture_output=True)
            for name in NAMES:
                svg = out / name.replace(".drawio", ".preview.svg")
                self.assertTrue(svg.is_file())
                self.assertIn("PORTABLE PREVIEW ONLY", svg.read_text())
                ET.parse(svg)
            self.assertIn("Client X", (out / "architecture-overview.preview.svg").read_text())
            self.assertIn("<polygon ", (out / "architecture-overview.preview.svg").read_text())

    def test_native_sources_have_valid_references_and_editable_geometry(self):
        for name in NAMES:
            with self.subTest(name=name):
                data = (SOURCES / name).read_text()
                self.assertIn("Cobalt #2148B8", data)
                self.assertIn("synthetic", data)
                source = ET.fromstring(data)
                self.assertEqual(source.tag, "mxfile")
                self.assertEqual(len(source.findall("diagram")), 1)
                graph, cells = model(name)
                page_width = int(graph.get("pageWidth", "0"))
                self.assertEqual(len(cells), len(graph.findall("./root/mxCell")))
                self.assertGreater(len(cells), 25)
                self.assertEqual(cells["1"].get("parent"), "0")
                for cell in cells.values():
                    if cell.get("id") in ("0", "1"):
                        continue
                    self.assertIn(cell.get("parent"), cells)
                    self.assertIsNotNone(cell.find("mxGeometry"))
                    if cell.get("edge") == "1":
                        self.assertEqual(len(cell.findall("./mxGeometry/mxPoint")), 2)
                    else:
                        geom = cell.find("mxGeometry")
                        assert geom is not None
                        self.assertGreater(float(geom.get("width", "0")), 0)
                        self.assertGreater(float(geom.get("height", "0")), 0)
                        size = re.search(r"(?:^|;)fontSize=(\d+);", cell.get("style", ""))
                        self.assertIsNotNone(size)
                        assert size is not None
                        effective_pt = int(size.group(1)) * 6.9 / page_width * 72
                        self.assertGreaterEqual(effective_pt, 7.0)

    def test_timeline_states_use_the_same_event_grid(self):
        graph, cells = model("execution-timeline.drawio")
        order = [cell.get("id") for cell in graph.findall("./root/mxCell")]
        for section in ("baseline", "proposed"):
            self.assertLess(order.index(f"{section}-band"),
                            order.index(f"{section}-grid-0"))
            self.assertLess(order.index(f"{section}-grid-0"),
                            order.index(f"{section}-exec-1"))
        for suffix in ("invoke-1", "invoke-2", "exec-1", "exec-2"):
            baseline = cells[f"baseline-{suffix}"].find("mxGeometry")
            proposed = cells[f"proposed-{suffix}"].find("mxGeometry")
            assert baseline is not None and proposed is not None
            self.assertEqual(baseline.get("x"), proposed.get("x"))
            self.assertEqual(baseline.get("width"), proposed.get("width"))
        self.assertIn("do not represent measured time", cells["note"].get("value", ""))

    def test_mechanism_inset_is_native_vector_and_labelled_synthetic(self):
        _, cells = model("cache-memory-mechanism.drawio")
        self.assertEqual(len([c for c in cells if c.startswith("inset-segment-")]), 4)
        self.assertEqual(len([c for c in cells if c.startswith("inset-point-")]), 5)
        self.assertIn("synthetic", cells["inset-title"].get("value", ""))
        for id in ("inset-x", "inset-y"):
            self.assertEqual(cells[id].get("edge"), "1")

    def test_memory_labels_sit_above_editable_layer_blocks(self):
        for name, pairs in (
            ("architecture-overview.drawio", (("memory-heading", "layer-1"),)),
            ("cache-memory-mechanism.drawio", (
                ("fast-tier-heading", "fast-slot-1"),
                ("slow-tier-heading", "slow-slot-1"),
            )),
        ):
            _, cells = model(name)
            for heading, block in pairs:
                with self.subTest(name=name, heading=heading):
                    label = cells[heading].find("mxGeometry")
                    layer = cells[block].find("mxGeometry")
                    assert label is not None and layer is not None
                    self.assertLessEqual(
                        float(label.get("y", "0")) + float(label.get("height", "0")),
                        float(layer.get("y", "0")),
                    )

    def test_operation_arrows_have_forward_source_target_points(self):
        _, cells = model("architecture-overview.drawio")
        for id in ("client-to-queue", "admission-to-scheduler", "scheduler-to-workers", "worker-to-cache"):
            points = cells[id].findall("./mxGeometry/mxPoint")
            self.assertEqual(len(points), 2)
            self.assertEqual(points[0].get("as"), "sourcePoint")
            self.assertEqual(points[1].get("as"), "targetPoint")
            self.assertNotEqual((points[0].get("x"), points[0].get("y")),
                                (points[1].get("x"), points[1].get("y")))
            self.assertIn("endArrow=block", cells[id].get("style", ""))


if __name__ == "__main__":
    unittest.main()
