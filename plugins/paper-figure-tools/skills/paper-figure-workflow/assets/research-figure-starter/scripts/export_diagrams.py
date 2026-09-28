#!/usr/bin/env python3
"""Export the recorded diagram owner from editable project-local sources."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


EXTENSIONS = {"drawio": ".drawio", "omnigraffle": ".graffle",
              "pretty-mermaid": ".mmd", "archify": ".json"}
OMNI_RUNTIME = Path("scripts/omnigraffle-tools/skills/omnigraffle-workflow/scripts/omnigraffle.py")
WIDTH_TOLERANCE_IN = 0.01
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
KNOWN_SVG_DOCTYPE = b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'


class NativeExportError(RuntimeError):
    def __init__(self, code: str, message: str, operation_id: str | None = None,
                 outcome_unknown: bool = False):
        self.code = code
        self.operation_id = operation_id
        self.outcome_unknown = outcome_unknown
        detail = f"{code}: {message}"
        if operation_id:
            detail += f" (operation_id {operation_id}"
            if outcome_unknown:
                detail += "; outcome unknown; reconcile before retry"
            detail += ")"
        super().__init__(detail)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_tool(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise RuntimeError(f"required dependency {name} is missing")
    return command


def selected_owner(source_dir: Path) -> str:
    recorded = source_dir.parent / "diagram-owner.json"
    override = os.environ.get("DIAGRAM_OWNER", "").strip()
    if recorded.is_file():
        config = json.loads(recorded.read_text(encoding="utf-8"))
        if (not isinstance(config, dict) or config.get("schema_version") != 1
                or config.get("owner") not in ("drawio", "omnigraffle")):
            raise RuntimeError(f"invalid recorded diagram owner: {recorded}")
        owner = config["owner"]
        if override and override != owner:
            raise RuntimeError(f"DIAGRAM_OWNER={override} conflicts with recorded owner {owner} in {recorded}")
        return owner
    owner = override or "drawio"
    if owner not in EXTENSIONS:
        raise RuntimeError(f"DIAGRAM_OWNER must be one of {', '.join(EXTENSIONS)}")
    return owner


def drawio_binary() -> str:
    configured = os.environ.get("DRAWIO_DESKTOP_BIN")
    if configured:
        if Path(configured).is_file() and os.access(configured, os.X_OK):
            return configured
        raise RuntimeError(f"DRAWIO_DESKTOP_BIN is not executable: {configured}")
    candidates = [shutil.which("drawio"), shutil.which("draw.io"),
                  "/Applications/draw.io.app/Contents/MacOS/draw.io",
                  "/mnt/c/Program Files/draw.io/draw.io.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("draw.io Desktop CLI is required; set DRAWIO_DESKTOP_BIN")


def subprocess_output(command: list[str], *, timeout: int = 150) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}): {detail[:600]}")
    return result.stdout


def native_command(cli: Path, *args: str, timeout: int = 150) -> dict:
    result = subprocess.run([sys.executable, str(cli), *args],
                            capture_output=True, text=True, timeout=timeout)
    try:
        receipt = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(f"OmniGraffle CLI returned invalid JSON: {result.stderr[:400]}") from error
    if result.returncode or receipt.get("status") not in ("inspected", "completed", "committed",
                                                           "reconciled_unchanged", "prerequisites_present"):
        details = receipt.get("error", {})
        raise NativeExportError(details.get("code", "native_export_failed"),
                                details.get("message", receipt.get("status", "unknown")),
                                receipt.get("operation_id"),
                                details.get("outcome_unknown") is True)
    return receipt


def native_export_formats(cli: Path) -> dict[str, bool]:
    """Inspect the copied export dictionary reader without sending AppleEvents."""
    helper = cli.with_name("preflight.py")
    spec = importlib.util.spec_from_file_location("project_omnigraffle_preflight", helper)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"project-local export capability reader is missing: {helper}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.export_capabilities(Path("/Applications/OmniGraffle.app"), {})
    if report.get("status") != "dictionary_inspected":
        raise RuntimeError("installed OmniGraffle export dictionary could not be inspected")
    return {name: report.get("formats", {}).get(name, {}).get("advertised") is True
            for name in ("PDF", "SVG")}


def pdf_width_in(pdf: Path) -> float:
    report = subprocess_output([required_tool("pdfinfo"), str(pdf)])
    page = re.search(r"^Page size:\s+([0-9]+(?:\.[0-9]+)?)\s+x\s+", report, re.MULTILINE)
    if page is None:
        raise RuntimeError(f"cannot determine PDF page width: {pdf}")
    return float(page.group(1)) / 72.0


def svg_width_in(svg: Path) -> tuple[float, bool]:
    try:
        root = ET.parse(svg).getroot()
    except ET.ParseError as error:
        raise RuntimeError(f"invalid SVG export: {svg}") from error
    if root.tag.split("}")[-1] != "svg":
        raise RuntimeError(f"invalid SVG root: {svg}")
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(in|pt|px|mm|cm)\s*",
                         root.attrib.get("width", ""))
    if match is None:
        raise RuntimeError(f"SVG has no unambiguous physical width: {svg}")
    value, unit = float(match.group(1)), match.group(2)
    factor = {"in": 1.0, "pt": 1 / 72, "px": 1 / 96,
              "mm": 1 / 25.4, "cm": 1 / 2.54}[unit]
    return value * factor, bool(root.findall(".//{http://www.w3.org/2000/svg}text"))


def normalize_native_svg(svg: Path, canvas_size: list[float]) -> dict:
    """Assign point units only to observed native dimensions matching saved points."""
    raw = svg.read_bytes()
    original_sha256 = hashlib.sha256(raw).hexdigest()
    if len(raw) > 16 * 1024 * 1024 or b"<!ENTITY" in raw.upper():
        raise RuntimeError("unsupported native SVG envelope")
    doctype_removed = False
    if b"<!DOCTYPE" in raw.upper():
        if raw.count(KNOWN_SVG_DOCTYPE) != 1:
            raise RuntimeError("unrecognized native SVG document type")
        raw = raw.replace(KNOWN_SVG_DOCTYPE, b"", 1)
        if b"<!DOCTYPE" in raw.upper():
            raise RuntimeError("multiple native SVG document types")
        doctype_removed = True
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise RuntimeError("invalid native SVG export") from error
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        raise RuntimeError("native SVG must retain the SVG namespace")
    if (len(canvas_size) != 2 or any(type(value) not in (int, float)
                                   or not math.isfinite(value) or value <= 0 for value in canvas_size)):
        raise RuntimeError("saved canvas has invalid point dimensions")
    number = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
    original = {key: root.attrib.get(key, "") for key in ("width", "height")}
    unitless = [re.fullmatch(number, original[key].strip()) is not None for key in ("width", "height")]
    if not all(unitless):
        if any(unitless):
            raise RuntimeError("native SVG mixes unitless and physical dimensions")
        # Known explicit units remain unchanged; the physical width gate still runs.
        for key in ("width", "height"):
            if re.fullmatch(rf"\s*({number})\s*(in|pt|px|mm|cm)\s*", original[key]) is None:
                raise RuntimeError("native SVG has unknown physical dimension units")
        return {"status": "explicit_units_preserved", "applied": False}
    dimensions = [float(original[key]) for key in ("width", "height")]
    try:
        viewbox = [float(value) for value in re.split(r"[\s,]+", root.attrib.get("viewBox", "").strip())]
    except ValueError as error:
        raise RuntimeError("native unitless SVG has invalid viewBox") from error
    tolerance = WIDTH_TOLERANCE_IN * 72
    if (any(not math.isfinite(value) or value <= 0 for value in dimensions)
            or len(viewbox) != 4 or any(not math.isfinite(value) for value in viewbox)
            or any(abs(value) > 1e-9 for value in viewbox[:2])
            or any(abs(dimensions[index] - canvas_size[index]) > tolerance
                   or abs(viewbox[index + 2] - canvas_size[index]) > tolerance
                   or abs(dimensions[index] - viewbox[index + 2]) > tolerance
                   for index in range(2))):
        raise RuntimeError("native unitless SVG dimensions/viewBox do not match saved canvas points")
    for key in ("width", "height"):
        root.set(key, original[key].strip() + "pt")
    ET.register_namespace("", SVG_NAMESPACE)
    ET.register_namespace("xlink", XLINK_NAMESPACE)
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    svg.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n")
    return {"status": "unitless_native_points_normalized", "applied": True,
            "original_dimensions": original,
            "physical_dimensions": {key: root.attrib[key] for key in ("width", "height")},
            "saved_canvas_size_points": canvas_size, "known_doctype_removed": doctype_removed,
            "original_export_sha256": original_sha256, "normalized_export_sha256": sha256(svg),
            "svg_text_elements_retained": len(root.findall(f".//{{{SVG_NAMESPACE}}}text")),
            "basis": "both unitless dimensions and viewBox match saved fixed canvas points"}


def verify_native_exports(pdf: Path, svg: Path, expected_width: float | None) -> dict:
    pdf_width = pdf_width_in(pdf)
    svg_width, editable_svg_text = svg_width_in(svg)
    if abs(pdf_width - svg_width) > WIDTH_TOLERANCE_IN:
        raise RuntimeError(f"PDF/SVG widths differ: {pdf_width:.3f} and {svg_width:.3f} in")
    if expected_width is not None and (abs(pdf_width - expected_width) > WIDTH_TOLERANCE_IN
                                       or abs(svg_width - expected_width) > WIDTH_TOLERANCE_IN):
        raise RuntimeError(f"export width differs from source canvas: expected {expected_width:.3f} in, "
                           f"PDF {pdf_width:.3f} in, SVG {svg_width:.3f} in")
    fonts = subprocess_output([required_tool("pdffonts"), str(pdf)]).splitlines()[2:]
    if any(len(fields := line.split()) >= 7 and fields[-5] != "yes" for line in fonts if line.strip()):
        raise RuntimeError("PDF contains a font that is not embedded")
    extracted = subprocess_output([required_tool("pdftotext"), str(pdf), "-"]).strip()
    if not extracted:
        raise RuntimeError("PDF text extraction is empty; inspect glyphs and text before publication")
    return {"pdf_width_in": pdf_width, "svg_width_in": svg_width,
            "pdf_fonts_embedded": True, "svg_editable_text": editable_svg_text,
            "glyph_review": "required"}


def native_export(cli: Path, source: Path, stage: Path) -> list[tuple[Path, str]]:
    if platform.system() != "Darwin":
        raise RuntimeError("OmniGraffle export requires macOS")
    if not cli.is_file():
        raise RuntimeError(f"project-local guarded OmniGraffle runtime is missing: {cli}")
    formats = native_export_formats(cli)
    if not formats["PDF"]:
        raise RuntimeError("installed OmniGraffle dictionary does not advertise required PDF export")
    inspected = native_command(cli, "inspect", str(source))
    canvases = inspected.get("canvases", [])
    if len(canvases) != 1:
        raise RuntimeError(f"{source.name} must have one selected canvas for PDF/SVG export")
    canvas_id = canvases[0]["id"]
    canvas_size = canvases[0].get("size")
    if (canvases[0].get("size_units") != "points"
            or not isinstance(canvas_size, list) or len(canvas_size) != 2
            or type(canvas_size[0]) not in (int, float)
            or not math.isfinite(canvas_size[0]) or canvas_size[0] <= 0):
        raise RuntimeError(f"saved .graffle canvas has no verified physical size: {source}")
    expected_width = canvas_size[0] / 72.0
    fingerprint = inspected.get("file_sha256")
    if fingerprint != sha256(source):
        raise RuntimeError(f"source changed during inspection: {source}")
    reports = {}
    outputs = {suffix: stage / f"{source.stem}.{suffix}" for suffix in ("pdf", "svg", "png")}
    for suffix in (("pdf", "svg") if formats["SVG"] else ("pdf",)):
        request = {"operation_id": str(uuid.uuid4()), "input": str(source),
                   "expected_sha256": fingerprint, "output": str(outputs[suffix]),
                   "scope": "canvas", "canvas_id": canvas_id, "format": suffix.upper()}
        request_file = stage / f"{source.stem}-{suffix}-request.json"
        request_file.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        try:
            reports[suffix] = native_command(cli, "export", "--request", str(request_file))
        except subprocess.TimeoutExpired as error:
            raise NativeExportError(
                "timeout",
                f"{suffix.upper()} export timed out; run {sys.executable} {cli} reconcile {request['operation_id']}",
                request["operation_id"],
                outcome_unknown=True,
            ) from error
    if not formats["SVG"]:
        subprocess_output([required_tool("pdftocairo"), "-svg", str(outputs["pdf"]),
                           str(outputs["svg"])])
        reports["svg"] = {"status": "pdf_vector_conversion",
                          "reason": "SVG not advertised by installed export dictionary",
                          "text_editability": "outlined by Poppler"}
    svg_normalization = (normalize_native_svg(outputs["svg"], canvas_size)
                         if formats["SVG"] else {"status": "converted_svg_units_preserved", "applied": False})
    subprocess_output([required_tool("pdftoppm"), "-f", "1", "-l", "1", "-singlefile",
                       "-r", "144", "-png", str(outputs["pdf"]), str(stage / source.stem)])
    verification = verify_native_exports(outputs["pdf"], outputs["svg"], expected_width)
    if sha256(source) != fingerprint:
        raise RuntimeError(f"source changed during export: {source}")
    metadata = stage / f"{source.stem}.export.json"
    converted_svg = reports["svg"].get("status") == "pdf_vector_conversion"
    native_reports = {
        suffix: {"status": report.get("status"), "operation_id": report.get("operation_id"),
                 "output_sha256": report.get("result", {}).get("sha256"),
                 "verification": report.get("result", {}).get("verification")}
        for suffix, report in reports.items() if report.get("status") != "pdf_vector_conversion"
    }
    metadata.write_text(json.dumps({"source": source.name, "source_sha256": fingerprint,
                                    "native_svg": "advertised" if formats["SVG"] else "not_advertised",
                                    "svg_origin": "pdf_vector_conversion" if converted_svg else "native",
                                    "svg_conversion": "pdftocairo -svg" if converted_svg else None,
                                    "svg_text_outlined": True if converted_svg else not verification["svg_editable_text"],
                                    "svg_normalization": svg_normalization,
                                    "native_export_reports": native_reports,
                                    "native_export_formats_advertised": formats,
                                    "verification": verification}, indent=2) + "\n", encoding="utf-8")
    return [(outputs[suffix], suffix) for suffix in ("pdf", "svg", "png")] + [(metadata, "export.json")]


def generic_export(owner: str, source: Path, stage: Path, exporter: str) -> list[tuple[Path, str]]:
    targets = {suffix: stage / f"{source.stem}.{suffix}" for suffix in ("svg", "pdf")}
    if owner == "drawio":
        binary = drawio_binary()
        targets["png"] = stage / f"{source.stem}.png"
        for suffix, target in targets.items():
            subprocess_output([binary, "-x", "-f", suffix, "-e", "-b", "10", "-o",
                               str(target), str(source)], timeout=120)
    else:
        if not exporter:
            raise RuntimeError(f"{owner} requires FIGURE_DIAGRAM_EXPORTER, a project-local owner adapter")
        command = shlex.split(exporter)
        if not command:
            raise RuntimeError("FIGURE_DIAGRAM_EXPORTER is empty")
        executable = shutil.which(command[0]) if not Path(command[0]).is_file() else command[0]
        if executable is None:
            raise RuntimeError(f"diagram exporter not found: {command[0]}")
        subprocess_output([executable, *command[1:], "--owner", owner, "--source", str(source),
                           "--svg", str(targets["svg"]), "--pdf", str(targets["pdf"])])
    return [(path, suffix) for suffix, path in targets.items()]


def publish(staged: list[tuple[Path, Path]], backups: Path,
            before: dict[Path, str | None]) -> None:
    for _, target in staged:
        if target.is_symlink() or (target.exists() and
                                  (not target.is_file() or target.stat().st_nlink != 1)):
            raise RuntimeError(f"export destination must be a regular unaliased file: {target}")
    for source, _ in staged:
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f"diagram exporter did not produce a nonempty {source.name}")
    for _, target in staged:
        if before[target] is not None:
            shutil.copy2(target, backups / target.name)
    published = []
    try:
        for source, target in staged:
            current = sha256(target) if target.exists() else None
            if current != before[target]:
                raise RuntimeError(f"existing export changed during build: {target}")
            os.replace(source, target)
            published.append(target)
    except (OSError, RuntimeError):
        for target in reversed(published):
            backup = backups / target.name
            if backup.exists():
                os.replace(backup, target)
            else:
                target.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    source_dir = args.source_dir.expanduser().resolve()
    try:
        owner = selected_owner(source_dir)
        sources = sorted(source_dir.glob(f"*{EXTENSIONS[owner]}"))
        if not sources:
            raise RuntimeError(f"no {EXTENSIONS[owner]} sources in {source_dir}")
        out_dir = args.out_dir.expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        project = source_dir.parent.parent
        cli = project / OMNI_RUNTIME
        suffixes = (("pdf", "svg", "png", "export.json") if owner == "omnigraffle"
                    else (("svg", "pdf", "png") if owner == "drawio" else ("svg", "pdf")))
        prior = {}
        for source in sources:
            for suffix in suffixes:
                target = out_dir / f"{source.stem}.{suffix}"
                if target.is_symlink() or (target.exists() and
                                          (not target.is_file() or target.stat().st_nlink != 1)):
                    raise RuntimeError(f"export destination must be a regular unaliased file: {target}")
                prior[target] = sha256(target) if target.exists() else None
        source_hashes = {source: sha256(source) for source in sources}
        staged = []
        with tempfile.TemporaryDirectory(prefix=".diagram-stage-", dir=out_dir) as temporary:
            stage_root = Path(temporary)
            for source in sources:
                stage = stage_root / source.stem
                stage.mkdir()
                generated = (native_export(cli, source, stage) if owner == "omnigraffle"
                             else generic_export(owner, source, stage,
                                                 os.environ.get("FIGURE_DIAGRAM_EXPORTER", "")))
                staged.extend((path, out_dir / f"{source.stem}.{suffix}") for path, suffix in generated)
            for source, fingerprint in source_hashes.items():
                if sha256(source) != fingerprint:
                    raise RuntimeError(f"source changed during diagram build: {source}")
            backup = stage_root / "backups"
            backup.mkdir()
            publish(staged, backup, prior)
        for _, target in staged:
            print(target)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired,
            subprocess.CalledProcessError) as error:
        raise SystemExit(f"diagram build failed: {error}") from error


if __name__ == "__main__":
    main()
