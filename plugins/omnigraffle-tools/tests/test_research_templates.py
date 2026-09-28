"""Portable acceptance for the three native-ready research compositions."""

from pathlib import Path
import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


PLUGIN = Path(__file__).resolve().parents[1]
CLI = PLUGIN / "skills" / "omnigraffle-workflow" / "scripts" / "research_workflow.py"
PALETTE = PLUGIN / "assets" / "research-templates" / "palette.json"
TEMPLATES = ("architecture", "timeline", "mechanism")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", str(CLI), *args], capture_output=True,
                          text=True, check=check)


def source(directory: Path, name: str, width: str, *options: str) -> dict:
    target = directory / f"{name}-{width}.json"
    run("--template", name, "--width", width, *options, "source", "--out", str(target))
    return json.loads(target.read_text())


class ResearchTemplateTest(unittest.TestCase):
    def test_all_six_compositions_are_native_contract_valid_at_final_size(self):
        with tempfile.TemporaryDirectory(prefix="omni-templates-") as temporary:
            root = Path(temporary)
            for name in TEMPLATES:
                for width, expected_points in (("single", 237.6), ("double", 496.8)):
                    with self.subTest(template=name, width=width):
                        spec = source(root, name, width)
                        canvas = spec["canvases"][0]
                        self.assertAlmostEqual(canvas["width"], expected_points)
                        self.assertIn("schematic", canvas["name"].lower())
                        self.assertGreaterEqual(len(canvas["objects"]), 20)
                        self.assertEqual(len({obj["key"] for obj in canvas["objects"]}),
                                         len(canvas["objects"]))
                        self.assertTrue(any(obj["kind"] == "group" for obj in canvas["objects"]))
                        for obj in canvas["objects"]:
                            if "font_size" in obj:
                                self.assertGreaterEqual(obj["font_size"], 7)
                            if obj["kind"] in ("shape", "text"):
                                self.assertGreaterEqual(obj["x"], 0)
                                self.assertGreaterEqual(obj["y"], 0)
                                self.assertLessEqual(obj["x"] + obj["width"], canvas["width"] + .001)
                                self.assertLessEqual(obj["y"] + obj["height"], canvas["height"] + .001)
                        result = json.loads(run("--spec", str(root / f"{name}-{width}.json"),
                                                "validate").stdout)
                        self.assertEqual(result["status"], "validated_source_spec")
                        sidecar = root / f"{name}-{width}.palette.json"
                        self.assertEqual(json.loads(sidecar.read_text()), json.loads(PALETTE.read_text()))

    def test_meaning_and_encoding_are_stable_across_widths(self):
        with tempfile.TemporaryDirectory(prefix="omni-templates-") as temporary:
            root = Path(temporary)
            for width in ("single", "double"):
                architecture = {obj["key"]: obj for obj in
                                source(root, "architecture", width)["canvases"][0]["objects"]}
                self.assertEqual(architecture["reuse"]["from"], "gpu-memory")
                self.assertEqual(architecture["reuse"]["to"], "scheduler" if width == "double" else "queue")
                self.assertEqual(architecture["reuse"]["head_arrow"], "filled")
                self.assertEqual(architecture["submit"]["from_side"], "right")
                self.assertIn("GPU cache", architecture["gpu-heading"]["text"])
                if width == "double":
                    stem_right = max(architecture[key]["x"] + architecture[key]["width"] / 2
                                     for key in ("worker", "gpu-memory"))
                    self.assertGreaterEqual(architecture["step-3"]["x"] - stem_right, 6)
                    self.assertGreaterEqual(architecture["step-3"]["y"],
                                            architecture["worker"]["y"] + architecture["worker"]["height"])
                    self.assertLessEqual(architecture["step-3"]["y"] + architecture["step-3"]["height"],
                                         architecture["gpu-memory"]["y"])
                else:
                    memory_header = architecture["cache-region-heading"]
                    self.assertEqual(memory_header["text"], "MEMORY")
                    stem_right = max(architecture[key]["x"] + architecture[key]["width"] / 2
                                     for key in ("queue", "gpu-memory"))
                    self.assertGreaterEqual(memory_header["x"] - stem_right, 6)
                    self.assertGreaterEqual(memory_header["font_size"], 7)

                timeline = {obj["key"]: obj for obj in
                            source(root, "timeline", width)["canvases"][0]["objects"]}
                self.assertEqual(timeline["baseline-execute"]["fill"],
                                 timeline["proposed-execute"]["fill"])
                self.assertEqual(timeline["baseline-retain"]["stroke"],
                                 timeline["proposed-retain"]["stroke"])
                self.assertEqual(timeline["baseline-wait"]["stroke_pattern"], "dashed")
                self.assertEqual(timeline["proposed-idle"]["stroke_pattern"], "dashed")
                self.assertIn("not measured", timeline["schematic-note"]["text"])
                if width == "single":
                    self.assertIn("invoke/retain", timeline["legend"]["text"])
                    self.assertIn("wait/idle", timeline["legend"]["text"])

                mechanism = {obj["key"]: obj for obj in
                             source(root, "mechanism", width)["canvases"][0]["objects"]}
                self.assertEqual(mechanism["gpu-slot-0"]["stroke"], "#C65F38")
                self.assertEqual(mechanism["gpu-slot-2"]["stroke_pattern"], "dashed")
                self.assertEqual(mechanism["load-layer"]["head_arrow"], "filled")
                self.assertIn("capacity", mechanism["schematic-note"]["text"])

    def test_custom_width_preserves_font_sizes_and_rejects_unfittable_canvas(self):
        with tempfile.TemporaryDirectory(prefix="omni-templates-") as temporary:
            root = Path(temporary)
            standard = source(root, "timeline", "single")
            custom_path = root / "custom.json"
            run("--template", "timeline", "--width-in", "4.5", "source", "--out", str(custom_path))
            custom = json.loads(custom_path.read_text())
            standard_objects = {obj["key"]: obj for obj in standard["canvases"][0]["objects"]}
            custom_objects = {obj["key"]: obj for obj in custom["canvases"][0]["objects"]}
            self.assertAlmostEqual(custom["canvases"][0]["width"], 324)
            self.assertEqual(set(standard_objects), set(custom_objects))
            for key in standard_objects:
                for property_name in ("font_size", "height"):
                    if property_name in standard_objects[key]:
                        self.assertEqual(standard_objects[key][property_name],
                                         custom_objects[key][property_name])
            for bad in ("0", "-1", "nan", "inf", "2.9", "15"):
                with self.subTest(width_in=bad):
                    failed = run("--template", "timeline", "--width-in", bad,
                                 "validate", check=False)
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertTrue("width" in failed.stderr or "fit" in failed.stderr)
            conflict = run("--template", "timeline", "--width", "single",
                           "--width-in", "4", "validate", check=False)
            self.assertNotEqual(conflict.returncode, 0)

    def test_optional_inset_is_editable_vector_and_only_on_mechanism(self):
        with tempfile.TemporaryDirectory(prefix="omni-templates-") as temporary:
            root = Path(temporary)
            for width in ("single", "double"):
                spec = source(root, "mechanism", width, "--with-inset")
                objects = {obj["key"]: obj for obj in spec["canvases"][0]["objects"]}
                self.assertEqual(objects["inset-point-a"]["shape_type"], "ellipse")
                self.assertEqual(objects["inset-segment-ab"]["head_arrow"], "none")
                self.assertEqual(objects["inset-segment-ab"]["kind"], "connector")
                self.assertFalse(any(obj["kind"] == "equation" for obj in objects.values()))
                self.assertIn("Illustrative", objects["inset-heading"]["text"])
                self.assertIn("Resident memory", objects["inset-y-label"]["text"])
                self.assertIn("qualitative", objects["inset-y-label"]["text"])
                label_bottom = objects["inset-y-label"]["y"] + objects["inset-y-label"]["height"]
                for key in ("inset-point-a", "inset-point-b", "inset-point-c"):
                    self.assertGreater(objects[key]["y"], label_bottom)
            failed = run("--template", "timeline", "--with-inset", "validate", check=False)
            self.assertNotEqual(failed.returncode, 0)

    def test_custom_width_keeps_inset_axes_points_and_segments_together(self):
        with tempfile.TemporaryDirectory(prefix="omni-templates-") as temporary:
            root = Path(temporary)
            standard = source(root, "mechanism", "single", "--with-inset")
            custom_path = root / "mechanism-custom.json"
            run("--template", "mechanism", "--width-in", "4.5", "--with-inset",
                "source", "--out", str(custom_path))
            custom = json.loads(custom_path.read_text())
            before = {obj["key"]: obj for obj in standard["canvases"][0]["objects"]}
            after = {obj["key"]: obj for obj in custom["canvases"][0]["objects"]}
            extra = custom["canvases"][0]["width"] - standard["canvases"][0]["width"]
            self.assertAlmostEqual(extra, 86.4)
            self.assertEqual(after["inset-y-axis"]["x"], before["inset-y-axis"]["x"])
            self.assertEqual(after["inset-x-axis"]["x"], before["inset-x-axis"]["x"])
            self.assertAlmostEqual(after["inset-x-axis"]["width"],
                                   before["inset-x-axis"]["width"] + extra)
            self.assertAlmostEqual(after["inset-panel"]["width"],
                                   before["inset-panel"]["width"] + extra)
            for key in ("inset-point-a", "inset-point-b", "inset-point-c"):
                old_fraction = ((before[key]["x"] - before["inset-x-axis"]["x"])
                                / before["inset-x-axis"]["width"])
                new_fraction = ((after[key]["x"] - after["inset-x-axis"]["x"])
                                / after["inset-x-axis"]["width"])
                self.assertAlmostEqual(old_fraction, new_fraction, places=3)
                self.assertGreater(after[key]["x"], after["inset-x-axis"]["x"])
                self.assertLess(after[key]["x"] + after[key]["width"],
                                after["inset-panel"]["x"] + after["inset-panel"]["width"])
            self.assertEqual(after["inset-segment-ab"]["from"], "inset-point-a")
            self.assertEqual(after["inset-segment-ab"]["to"], "inset-point-b")
            self.assertEqual(after["inset-segment-bc"]["to"], "inset-point-c")
            for key in before:
                if "font_size" in before[key]:
                    self.assertEqual(before[key]["font_size"], after[key]["font_size"])

    def test_preview_and_gallery_do_not_claim_native_acceptance(self):
        with tempfile.TemporaryDirectory(prefix="omni-templates-") as temporary:
            root = Path(temporary)
            gallery_dir = root / "gallery"
            gallery_dir.mkdir()
            receipt = json.loads(run("gallery", "--out-dir", str(gallery_dir)).stdout)
            self.assertEqual(receipt["status"], "portable_gallery_only")
            self.assertEqual(receipt["previews"], 6)
            self.assertEqual(len(list(gallery_dir.glob("*.svg"))), 6)
            self.assertFalse(list(gallery_dir.glob("*.graffle")))
            self.assertIn("No native .graffle output is implied",
                          (gallery_dir / "index.html").read_text())
            for svg_file in gallery_dir.glob("*.svg"):
                svg = svg_file.read_text()
                self.assertIn("PORTABLE PREVIEW ONLY", svg)
                self.assertIn("marker-end", svg)
                self.assertEqual(ET.fromstring(svg).tag, "{http://www.w3.org/2000/svg}svg")
            duplicate = run("gallery", "--out-dir", str(gallery_dir), check=False)
            self.assertNotEqual(duplicate.returncode, 0)


if __name__ == "__main__":
    unittest.main()
