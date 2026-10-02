#!/usr/bin/env python3
"""Check a synthetic mechanism and its SVG; not a visual or learning evaluator."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/explanation-artifacts"
SVG = "{http://www.w3.org/2000/svg}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def expected_schedule(jobs: list[dict]) -> list[dict]:
    """Independent reference calculation from the fixture's stated recurrence."""
    finish = 0
    result = []
    for job in jobs:
        start = max(job["arrival"], finish)
        finish = start + job["service"]
        result.append({"id": job["id"], "start": start, "finish": finish,
                       "wait": start - job["arrival"]})
    return result


def number(element: ET.Element, attribute: str) -> float:
    value = float(element.attrib[attribute])
    require(math.isfinite(value), f"SVG {attribute} must be finite")
    return value


def check_svg(path: Path, trace: list[dict]) -> None:
    """Check visible label text, mark coordinates and dependency geometry."""
    root = ET.parse(path).getroot()
    require(root.tag == SVG + "svg", "Expected an SVG root")
    require(root.findtext(SVG + "title") == "Synthetic first-in, first-out example",
            "SVG must visibly identify the synthetic example")
    require(bool(root.findtext(SVG + "desc")), "SVG needs a text alternative")
    require(root.get("role") == "img", "SVG requires an accessible image role")
    require(root.get("aria-labelledby") == "title description", "SVG accessible labels changed")
    width, height = number(root, "width"), number(root, "height")
    require(root.get("viewBox") == f"0 0 {width:g} {height:g}", "SVG canvas and viewBox differ")
    marks = {node.get("data-job"): node for node in root.iter(SVG + "rect") if node.get("data-job")}
    labels = {node.get("data-label"): node for node in root.iter(SVG + "text") if node.get("data-label")}
    require(set(marks) == set(labels) == {event["id"] for event in trace}, "SVG jobs or labels differ from source")
    for index, event in enumerate(trace):
        mark, label = marks[event["id"]], labels[event["id"]]
        x, y = number(mark, "x"), number(mark, "y")
        w, h = number(mark, "width"), number(mark, "height")
        require((x, y, w, h) == (80 + event["start"] * 40, 48 + index * 60,
                                (event["finish"] - event["start"]) * 40, 24),
                f"SVG timing geometry differs for {event['id']}")
        require(0 <= x <= x + w <= width and 0 <= y <= y + h <= height, "SVG mark exceeds canvas")
        require("".join(label.itertext()) == f"{event['id']}: {event['start']:g}–{event['finish']:g} s",
                f"SVG visible time label differs for {event['id']}")
        require((number(label, "x"), number(label, "y")) == (x, y + 44), "SVG label anchor differs")
    dependencies = [node for node in root.iter(SVG + "line") if node.get("data-from")]
    require(len(dependencies) == max(0, len(trace) - 1), "SVG dependency count differs")
    for edge, before, after in zip(dependencies, trace, trace[1:]):
        require((edge.get("data-from"), edge.get("data-to")) == (before["id"], after["id"]),
                "SVG dependency direction differs from source")
        a, b = marks[before["id"]], marks[after["id"]]
        require((number(edge, "x1"), number(edge, "y1"), number(edge, "x2"), number(edge, "y2")) ==
                (number(a, "x") + number(a, "width"), number(a, "y") + number(a, "height"),
                 number(b, "x"), number(b, "y")), "SVG dependency endpoints differ from source")
        require(edge.get("marker-end") == "url(#arrow)", "SVG dependency needs a forward arrowhead")


def evaluate(fixture: Path) -> dict:
    node = shutil.which("node")
    require(node is not None, "Node.js is unavailable; JavaScript behavior is unverified")
    inputs = json.loads((fixture / "cases.json").read_text())
    require(inputs.get("unit") == "s" and inputs.get("synthetic") is True, "Fixture units and synthetic status changed")
    cases = inputs["cases"]
    require([case["id"] for case in cases] == ["waiting", "idle", "zero-service", "fractional", "empty"],
            "Expected ordinary and boundary cases")
    runner = """import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {schedule} = await import(pathToFileURL(process.argv[1]).href);
const cases = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(c => schedule(c.jobs))));"""
    result = subprocess.run([node, "--input-type=module", "-e", runner,
                             str((fixture / "queue-model.mjs").resolve())],
                            input=json.dumps(cases), text=True, capture_output=True,
                            timeout=10, check=False)
    require(result.returncode == 0, "JavaScript model execution failed")
    actual = json.loads(result.stdout)
    expected = [expected_schedule(case["jobs"]) for case in cases]
    require(actual == expected, "JavaScript outputs differ from independent source calculations")
    check_svg(fixture / "queue.svg", expected[0])
    return {"status": "passed", "scope": "synthetic_fixture_only", "mechanism_cases": len(cases),
            "svg_source_consistency": "passed", "browser_interaction": "unverified",
            "visual_review": "unverified", "learning_effectiveness": "unverified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-dir", type=Path, default=FIXTURE,
                        help="Trusted local fixture directory; executes its queue-model.mjs")
    args = parser.parse_args()
    try:
        receipt = evaluate(args.fixture_dir)
    except (ValueError, OSError, KeyError, ET.ParseError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "failed", "error": str(error),
                          "visual_review": "unverified", "learning_effectiveness": "unverified"}))
        return 1
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
