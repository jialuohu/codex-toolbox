"""Offline checks for the research workflow JSON source and preview."""

from pathlib import Path
import json
import subprocess
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET


PLUGIN = Path(__file__).resolve().parents[1]
SOURCE = PLUGIN / "assets" / "research-templates" / "workflow.json"
CLI = PLUGIN / "skills" / "omnigraffle-workflow" / "scripts" / "research_workflow.py"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", str(CLI), "--spec", str(SOURCE), *args],
                          capture_output=True, text=True, check=check)


class ResearchWorkflowTest(unittest.TestCase):
    def test_source_passes_both_contracts_and_final_size_type_check(self):
        status = json.loads(run("validate").stdout)
        self.assertEqual(status, {"status": "validated_source_spec", "canvases": 1, "objects": 26})
        canvas = json.loads(SOURCE.read_text())["canvases"][0]
        self.assertEqual(canvas["width"], 900)
        objects = {obj["key"]: obj for obj in canvas["objects"]}
        self.assertEqual(len(objects), 26)
        self.assertEqual(objects["submit"]["from"], "queue")
        self.assertEqual(objects["submit"]["to"], "scheduler")
        self.assertEqual(objects["dispatch"]["to"], "worker")
        self.assertEqual(objects["populate"]["to"], "memory")
        for obj in canvas["objects"]:
            if "font_size" in obj:
                self.assertGreaterEqual(obj["font_size"] * 6.9 * 72 / canvas["width"], 7)

    def test_preview_is_source_derived_and_visibly_limited(self):
        with tempfile.TemporaryDirectory(prefix="omni-research-test-") as tmp:
            root = Path(tmp)
            copied = root / "workflow.json"
            copied.write_text(SOURCE.read_text().replace("Request queue", "Example queue"))
            output = root / "workflow.preview.svg"
            result = subprocess.run(["python3", str(CLI), "--spec", str(copied),
                                     "preview", "--out", str(output)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["status"], "portable_preview_only")
            svg = output.read_text()
            self.assertIn("Example queue", svg)
            self.assertIn("PORTABLE PREVIEW ONLY", svg)
            root_tag = ET.fromstring(svg)
            namespace = "{http://www.w3.org/2000/svg}"
            self.assertEqual(root_tag.tag, namespace + "svg")
            self.assertEqual(len(root_tag.findall(namespace + "line")), 3)
            self.assertGreaterEqual(len(root_tag.findall(namespace + "rect")), 12)

    def test_prepare_writes_fresh_request_without_native_file(self):
        with tempfile.TemporaryDirectory(prefix="omni-research-test-") as tmp:
            root = Path(tmp)
            output = root / "workflow.graffle"
            request = root / "create.json"
            result = run("prepare", "--output", str(output), "--request-out", str(request))
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "request_prepared_not_created")
            self.assertFalse(output.exists())
            payload = json.loads(request.read_text())
            self.assertEqual(payload["output"], str(output))
            self.assertEqual(payload["operation_id"], str(uuid.UUID(payload["operation_id"])))
            self.assertEqual(payload["spec"], json.loads(SOURCE.read_text()))
            again = run("prepare", "--output", str(output), "--request-out", str(request), check=False)
            self.assertNotEqual(again.returncode, 0)

    def test_connector_overlap_is_rejected_offline(self):
        with tempfile.TemporaryDirectory(prefix="omni-research-test-") as tmp:
            copied = Path(tmp) / "invalid.json"
            spec = json.loads(SOURCE.read_text())
            for obj in spec["canvases"][0]["objects"]:
                if obj["key"] == "scheduler":
                    obj["x"] = 100
            copied.write_text(json.dumps(spec))
            result = subprocess.run(["python3", str(CLI), "--spec", str(copied), "validate"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlap", result.stderr)


if __name__ == "__main__":
    unittest.main()
