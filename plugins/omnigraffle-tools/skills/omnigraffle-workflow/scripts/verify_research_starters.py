#!/usr/bin/env python3
"""Verify the bundled research starters and recorded acceptance; no app calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from document import read_document


EXPECTED = {f"{family}-{width}.graffle" for family in ("architecture", "timeline", "mechanism")
            for width in ("single", "double")}
PRIVATE_PREFIXES = ("/Users/", "/private/var/", "/tmp/", "/Volumes/", "/home/", "/var/folders/", "C:\\Users\\")


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate manifest field")
            result[key] = value
        return result
    data = path.read_bytes()
    if len(data) > 1024 * 1024:
        raise ValueError("manifest exceeds size limit")
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite manifest value")))


def native_text(document):
    sizes, fonts, count = [], set(), 0
    stack = [graphic for sheet in document["Sheets"] for graphic in sheet["GraphicsList"]]
    while stack:
        graphic = stack.pop()
        stack.extend(graphic.get("Graphics", []))
        stack.extend(graphic.get("GraphicsList", []))
        stored = graphic.get("Text", {})
        stored = stored.get("Text", "") if isinstance(stored, dict) else stored
        if not stored:
            continue
        if not isinstance(stored, str) or not stored.startswith("{\\rtf"):
            raise ValueError("unqualified native starter text")
        table = re.search(r"\{\\fonttbl((?:[^{}]|\{[^{}]*\})*)\}", stored)
        names = re.findall(r"\\f[0-9]+(?:\\[a-z]+[0-9]*\s*)*\s+([^;{}\\]+);", table.group(1)) if table else []
        label_sizes = [int(value) / 2 for value in re.findall(r"\\fs([0-9]+)\b", stored)]
        if not names or not label_sizes:
            raise ValueError("unqualified native starter font/size")
        fonts.update(name.strip() for name in names)
        sizes.extend(label_sizes)
        count += 1
    if not sizes or min(sizes) < 7 or fonts - {"Helvetica", "Helvetica-Bold"}:
        raise ValueError("native starter text differs from native research typography contract")
    return {"minimum_text_size_pt": min(sizes), "fonts": sorted(fonts), "editable_text_objects": count}


def check_decoded_metadata(value, *, author_fields=False):
    if isinstance(value, dict):
        for key, item in value.items():
            if author_fields and key in ("Modifier", "Creator", "Author"):
                raise ValueError("native starter retains author metadata")
            check_decoded_metadata(key)
            check_decoded_metadata(item, author_fields=author_fields)
    elif isinstance(value, list):
        for item in value:
            check_decoded_metadata(item, author_fields=author_fields)
    elif isinstance(value, str) and any(prefix in value for prefix in PRIVATE_PREFIXES):
        raise ValueError("decoded starter metadata contains private path prefixes")


def verify_bundle(directory):
    directory = Path(directory)
    manifest = strict_json(directory / "manifest.json")
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or manifest.get("status") != "native_reopen_and_export_verified"):
        raise ValueError("native starter acceptance manifest is unqualified")
    check_decoded_metadata(manifest)
    records = manifest.get("starters")
    if (not isinstance(records, list) or len(records) != 6
            or any(not isinstance(record, dict) or not isinstance(record.get("file"), str) for record in records)
            or {record["file"] for record in records} != EXPECTED):
        raise ValueError("expected six unique native starter filenames")
    palette = manifest.get("palette", {})
    if (not isinstance(palette, dict) or palette.get("file") != "palette.json"
            or fingerprint(directory / "palette.json") != palette.get("sha256")):
        raise ValueError("selected palette fingerprint mismatch")
    selected_palette = strict_json(directory / "palette.json")
    if not isinstance(selected_palette, dict):
        raise ValueError("selected palette metadata is malformed")
    check_decoded_metadata(selected_palette)
    for record in records:
        source = directory / record["file"]
        expected_width = "single" if source.stem.endswith("-single") else "double"
        width_in = 3.3 if expected_width == "single" else 6.9
        if record.get("width") != expected_width or fingerprint(source) != record.get("sha256"):
            raise ValueError("native starter width tag or source fingerprint mismatch")
        inspected, document = read_document(source)
        if len(inspected["canvases"]) != 1:
            raise ValueError("native starter requires exactly one canvas")
        canvas = inspected["canvases"][0]
        if (canvas.get("size_units") != "points" or record.get("size_pt") != canvas.get("size")
                or abs(canvas["size"][0] / 72 - width_in) > .01):
            raise ValueError("native starter canvas metadata mismatch")
        text = native_text(document)
        if any(record.get(key) != text[key] for key in ("minimum_text_size_pt", "fonts")):
            raise ValueError("native starter typography metadata mismatch")
        check_decoded_metadata(document, author_fields=True)
        with zipfile.ZipFile(source) as archive:
            data = [archive.comment]
            for member in archive.infolist():
                data.extend((archive.read(member), member.filename.encode(), member.comment, member.extra))
            if any(prefix.encode(encoding) in value for value in data for prefix in PRIVATE_PREFIXES
                   for encoding in ("utf-8", "utf-16-le", "utf-16-be")):
                raise ValueError("native starter archive contains private path prefixes")
        if (record.get("native_reopen_after_sanitization") != "verified_by_acceptance_run"
                or record.get("native_export_after_sanitization") != "guarded_native_pdf_svg_committed"):
            raise ValueError("native starter lacks recorded native lifecycle acceptance")
        evidence = record.get("native_export_evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("native starter export acceptance metadata is malformed")
        verification = evidence.get("verification", {})
        metrics = evidence.get("svg_text_metrics", {})
        normalization = evidence.get("svg_normalization", {})
        if any(not isinstance(value, dict) for value in (verification, metrics, normalization)):
            raise ValueError("native starter export acceptance metadata is malformed")
        if (any(type(verification.get(key)) not in (int, float) or abs(verification[key] - width_in) > .01
                for key in ("pdf_width_in", "svg_width_in"))
                or verification.get("pdf_fonts_embedded") is not True
                or verification.get("svg_editable_text") is not True
                or metrics.get("status") != "qualified_native_svg_text"
                or metrics.get("minimum_effective_font_size_pt") != text["minimum_text_size_pt"]
                or metrics.get("editable_text_elements") != text["editable_text_objects"]):
            raise ValueError("native starter export acceptance metadata mismatch")
        if (normalization.get("applied") is True and normalization.get("normalized_export_sha256")
                != evidence.get("output_sha256", {}).get("svg")):
            raise ValueError("native starter normalized SVG fingerprint mismatch")
    return {"status": "verified_native_starter_bundle", "starters": 6, "application_called": False,
            "basis": "Current archive integrity/typography/privacy and consistency of recorded native acceptance; no fresh rendering or LaTeXiT check."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path,
                        default=Path(__file__).resolve().parents[3] / "assets/research-templates/native")
    args = parser.parse_args()
    try:
        print(json.dumps(verify_bundle(args.dir)))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"native starter verification failed: {error}\n")


if __name__ == "__main__":
    main()
