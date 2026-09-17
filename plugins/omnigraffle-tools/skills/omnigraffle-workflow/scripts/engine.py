"""Transaction coordinator. Native files remain authoritative; no archive writes."""
import copy
import hashlib
import json
import math
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import time
import xml.etree.ElementTree as ET

from contracts import CommandError, validate_request, load_json
from document import inspect_document, read_document
from transactions import Store, canonical, checked_copy, check_fingerprint, digest, publish, read_json, write_json


STOCK_OWNER = "fr.chachatelier.pierre.LaTeXiT"


def checked(result):
    if not isinstance(result, dict) or result.get("status") != "ok":
        details = result.get("error", result) if isinstance(result, dict) else {}
        error = CommandError(details.get("code", "adapter_error"), details.get("message", "Invalid adapter response"),
                             unknown=details.get("outcome_unknown", True))
        error.adapter_details = {k: result[k] for k in ("operation_dir", "diagnostics_paths", "warnings")
                                 if isinstance(result, dict) and k in result}
        raise error
    return result


def app_processes():
    script = """ObjC.import('AppKit'); const result=[];
for (const bid of ['com.omnigroup.OmniGraffle7','fr.chachatelier.pierre.LaTeXiT']) {
 const apps=$.NSRunningApplication.runningApplicationsWithBundleIdentifier(bid);
 for(let i=0;i<apps.count;i++){const a=apps.objectAtIndex(i);result.push({bundle_id:bid,pid:Number(a.processIdentifier),path:ObjC.unwrap(a.bundleURL.path)});}
} JSON.stringify(result);"""
    try:
        p = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script], capture_output=True, text=True, timeout=5)
        if p.returncode or len(p.stdout) > 16384:
            raise ValueError()
        result = json.loads(p.stdout)
        if not isinstance(result, list) or any(not isinstance(i, dict) or type(i.get("pid")) is not int for i in result):
            raise ValueError()
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise CommandError("process_inventory_unavailable", "Cannot verify application process identities") from error


def graph_map(document):
    result = {}
    for sheet in document["Sheets"]:
        stack = list(sheet["GraphicsList"])
        if sheet.get("BackgroundGraphic"):
            stack.append(sheet["BackgroundGraphic"])
        while stack:
            graphic = stack.pop()
            result[(sheet["UniqueID"], graphic["ID"])] = graphic
            for field in ("Graphics", "GraphicsList"):
                stack.extend(graphic.get(field, []))
    return result


def normalized_graphic(graphic):
    value = copy.deepcopy(graphic)
    # Observed native default normalization after restarting OmniGraffle 7.26.
    # Only explicit numeric RGB black is equivalent to an absent stroke Color;
    # do not normalize opaque color archives or other color spaces.
    if value.get("Class") == "LineGraphic":
        stroke = value.get("Style", {}).get("stroke", {})
        color = stroke.get("Color")
        if (isinstance(color, dict) and set(color) <= {"r", "g", "b", "space"}
                and color.get("space", "RGB") == "RGB"
                and all(type(color.get(k)) in (int, float) and color[k] == 0 for k in ("r", "g", "b"))):
            stroke.pop("Color")
    return value


def verify_preservation(before, after, changed, native_before=None, native_after=None):
    a, b = graph_map(before), graph_map(after)
    # Ancestors contain nested child dictionaries and necessarily change with
    # an explicitly targeted descendant. All other objects compare in full.
    allowed = set(changed)
    ancestors = set()
    for key, g in a.items():
        descendants = []
        stack = list(g.get("Graphics", [])) + list(g.get("GraphicsList", []))
        while stack:
            child = stack.pop()
            descendants.append((key[0], child["ID"]))
            stack.extend(child.get("Graphics", [])); stack.extend(child.get("GraphicsList", []))
        if any(c in allowed for c in descendants):
            ancestors.add(key)
    for key, original in a.items():
        if key not in b:
            raise CommandError("verification_failed", f"Original object {key} disappeared")
        left, right = original, b[key]
        if key in ancestors and key not in allowed:
            left = {k: v for k, v in original.items() if k not in ("Graphics", "GraphicsList")}
            right = {k: v for k, v in b[key].items() if k not in ("Graphics", "GraphicsList")}
        if key not in allowed and normalized_graphic(left) != normalized_graphic(right):
            # OmniGraffle can reserialize a black line's color archive on open.
            # Never decode it or trust its textual RGB: require independent
            # native readback on both sides, and compare every remaining field.
            def native_black(report):
                matches = [o for c in (report or {}).get("canvases", []) if c["id"] == key[0]
                           for o in c["objects"] if o["id"] == key[1]]
                return len(matches) == 1 and matches[0].get("stroke_rgb") == [0, 0, 0]
            def without_color(g):
                g = copy.deepcopy(g)
                g.get("Style", {}).get("stroke", {}).pop("Color", None)
                return g
            if not (left.get("Class") == right.get("Class") == "LineGraphic"
                    and native_black(native_before) and native_black(native_after)
                    and without_color(left) == without_color(right)):
                raise CommandError("verification_failed", f"Unrelated object {key} changed")
    # Original canvases, backgrounds, dimensions, and non-graphic metadata.
    before_sheets = {s["UniqueID"]: s for s in before["Sheets"]}
    after_sheets = {s["UniqueID"]: s for s in after["Sheets"]}
    if before_sheets.keys() != after_sheets.keys():
        raise CommandError("verification_failed", "Canvas identities changed")
    for key, sheet in before_sheets.items():
        for field in ("SheetTitle", "CanvasSize", "BackgroundGraphic"):
            if sheet.get(field) != after_sheets[key].get(field):
                raise CommandError("verification_failed", f"Unrelated canvas field {field} changed")
    return {"unrelated_objects": "verified", "comparison": "parsed objects; black line color serialization may normalize with matching native RGB readback"}


def target_object(report, canvas_id, object_id):
    objects = [o for c in report["canvases"] if c["id"] == canvas_id for o in c["objects"] if o["id"] == object_id]
    if len(objects) != 1:
        raise CommandError("ambiguous_object", "Expected one inspected canvas/object identity")
    return objects[0]


def verify_assets(before, after, changed):
    for canvas in before["canvases"]:
        for obj in canvas["objects"]:
            if (canvas["id"], obj["id"]) in changed:
                continue
            current = target_object(after, canvas["id"], obj["id"])
            for field in ("image", "linkback"):
                if obj.get(field) != current.get(field):
                    raise CommandError("verification_failed", "An unrelated image or LinkBack payload changed")


def application_versions(native, latexit):
    versions = {}
    for label, path in (("omnigraffle", getattr(native, "app_path", None)),
                        ("latexit", getattr(latexit, "latexit_app", None))):
        if path:
            try:
                with (Path(path) / "Contents/Info.plist").open("rb") as stream:
                    info = plistlib.load(stream)
                versions[label] = {"version": info.get("CFBundleShortVersionString"), "bundle_id": info.get("CFBundleIdentifier")}
            except (OSError, plistlib.InvalidFileException):
                versions[label] = {"status": "unavailable"}
    return versions


def verify_properties(native_document, canvas_id, object_id, properties):
    matches = [o for c in native_document["canvases"] if c["id"] == canvas_id for o in c["objects"] if o["id"] == object_id]
    if len(matches) != 1:
        raise CommandError("verification_failed", "Native result does not uniquely identify the requested object")
    obj = matches[0]
    for key, expected in properties.items():
        if key in ("x", "y", "width", "height"):
            actual = obj.get("origin" if key in ("x", "y") else "size", [None, None])[0 if key in ("x", "width") else 1]
        elif key in ("fill", "stroke"):
            actual = obj.get(key + "_rgb")
            rgb = [int(expected[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            if not isinstance(actual, list) or len(actual) != 3 or any(abs(a - b) > 0.0001 for a, b in zip(actual, rgb)):
                raise CommandError("verification_failed", f"Native {key} did not match the requested color")
            continue
        else:
            actual = obj.get(key)
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            equal = isinstance(actual, (int, float)) and abs(actual - expected) <= 0.0001
        else:
            equal = actual == expected
        if not equal:
            raise CommandError("verification_failed", f"Native property {key} did not match the requested value")


def export_check(path, format_name):
    raw = Path(path).read_bytes()
    if not raw or len(raw) > 64 * 1024 * 1024:
        raise CommandError("verification_failed", "Missing or oversized export")
    if format_name == "PNG":
        if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 33:
            raise CommandError("verification_failed", "Invalid PNG signature")
        width, height = struct.unpack(">II", raw[16:24])
        if min(width, height) < 1 or max(width, height) > 16384 or width * height > 16_000_000:
            raise CommandError("verification_failed", "PNG dimensions exceed limits")
        return {"format": "PNG", "pixel_dimensions": [width, height], "visual_check": "required"}
    if format_name == "PDF":
        if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-1024:]:
            raise CommandError("verification_failed", "Incomplete PDF export")
        return {"format": "PDF", "visual_check": "required"}
    if b"<!ENTITY" in raw or b"<!DOCTYPE" in raw or len(raw) > 16 * 1024 * 1024:
        raise CommandError("verification_failed", "Unsupported SVG envelope")
    try:
        root = ET.fromstring(raw)
        if root.tag.split("}")[-1] != "svg":
            raise ValueError()
    except (ET.ParseError, ValueError) as error:
        raise CommandError("verification_failed", "Invalid SVG export") from error
    return {"format": "SVG", "visual_check": "required"}


class Engine:
    def __init__(self, native, latexit, store=None, process_reader=app_processes):
        self.native, self.latexit = native, latexit
        self.store = store or Store()
        self.process_reader = process_reader

    def inventory(self):
        return checked(self.native.call({"op": "inventory"})).get("documents", [])

    def guard_documents(self, source, destination, *, require_destination_closed=True):
        docs = self.inventory()
        for path in set(p for p in (source, destination) if p):
            matches = [d for d in docs if d.get("path") and Path(d["path"]).resolve() == path]
            if len(matches) > 1:
                raise CommandError("ambiguous_document", "Multiple open documents match a canonical path")
            if matches and matches[0].get("modified") is not False:
                raise CommandError("unsaved_document", "Save or close unsaved application changes first")
            if path == destination and matches and require_destination_closed:
                raise CommandError("destination_open", "Close the destination in OmniGraffle before replacing it, or choose a new output")

    def perform(self, command, request):
        validate_request(command, request)
        with self.store.locked():
            receipt, reused = self.store.begin(request["operation_id"], command, request)
            if reused:
                return {**receipt, "replayed_receipt": True}
            dispatched = False
            try:
                source = canonical(request["input"]) if "input" in request else None
                output = canonical(request["output"], output=True) if "output" in request else None
                palette = None
                if "palette" in request:
                    catalog = canonical(request["palette"]["catalog_path"])
                    if not isinstance(load_json(catalog), (dict, list)):
                        raise CommandError("invalid_palette", "Expected a JSON color catalog")
                    palette = {"catalog_path": str(catalog), "sha256": digest(catalog)}
                before_report, before_raw = read_document(source) if source else (None, None)
                if (command == "export" and request["scope"] == "document" and request["format"] != "PDF"
                        and len(before_report["canvases"]) != 1):
                    raise CommandError("unsupported_export", "Multi-canvas document export requires PDF; select one canvas for PNG/SVG")
                if output and command not in ("export", "equation-render") and output.suffix.lower() != ".graffle":
                    raise CommandError("invalid_request", "Native output must use .graffle extension")
                if source:
                    check_fingerprint(source, request["expected_sha256"], "Source")
                expected_output = digest(output) if output else None
                if expected_output is not None:
                    if request.get("overwrite") is not True or request.get("expected_output_sha256") != expected_output:
                        raise CommandError("overwrite_not_authorized", "Existing output requires overwrite:true and its expected_output_sha256")
                elif request.get("expected_output_sha256") is not None:
                    raise CommandError("stale_file", "Expected output no longer exists")
                if source and output and source != output and output.exists() and source.samefile(output):
                    raise CommandError("output_alias", "Input/output hard-link alias")
                self.guard_documents(source, output)
                processes = self.process_reader()
                if len([p for p in processes if p.get("bundle_id") == "com.omnigroup.OmniGraffle7"]) != 1:
                    raise CommandError("application_identity", "Start exactly one selected OmniGraffle instance")
                workdir = Path(receipt["work_directory"])
                working = workdir / "working.graffle"
                if source:
                    checked_copy(source, working, request["expected_sha256"])
                self.store.save(receipt, phase="validated", source=str(source) if source else None,
                                source_sha256=request.get("expected_sha256"), output=str(output) if output else None,
                                expected_output_sha256=expected_output, working_path=str(working), processes=processes,
                                versions=application_versions(self.native, self.latexit), palette=palette)
                changed = set()
                if command == "update":
                    for change in request["changes"]:
                        target_object(before_report, change["canvas_id"], change["object_id"])
                        changed.add((change["canvas_id"], change["object_id"]))
                if command in ("equation-source", "equation-update"):
                    obj = target_object(before_report, request["canvas_id"], request["object_id"])
                    if obj.get("linkback", {}).get("owner", {}).get("bundle_id") != STOCK_OWNER:
                        raise CommandError("foreign_equation_owner", "Only an existing stock-LaTeXiT equation may be edited; ownership migration is not implicit")
                    changed.add((request["canvas_id"], request["object_id"]))
                self.store.save(receipt, phase="adapter_pending", status="pending")
                dispatched = True
                equations = []
                adapter_warnings = []
                native_report = None
                before_native = checked(self.native.call({"op": "inspect", "path": str(working)}))["document"] if source else None
                if command == "create":
                    spec = copy.deepcopy(request["spec"])
                    eq_specs = [(c["key"], o) for c in spec["canvases"] for o in c["objects"] if o["kind"] == "equation"]
                    for c in spec["canvases"]:
                        c["objects"] = [o for o in c["objects"] if o["kind"] != "equation"]
                    created = checked(self.native.call({"op": "create", "path": str(working), "spec": spec, "working_copy": True}))
                    native_report = created["document"]
                    for i, (canvas_key, eq) in enumerate(eq_specs):
                        cid = created["mapping"][canvas_key]["canvas_id"]
                        result = checked(self.latexit.call({"op": "equation-insert", "path": str(working), "canvas_id": cid,
                            "key": eq["key"], "x": eq["x"], "y": eq["y"], "equation": eq["equation"], "output_dir": str(workdir / f"equation-{i}")}))
                        equations.append({"canvas_id": cid, "object_id": result["object_id"], **eq["equation"]})
                        adapter_warnings.extend(result.get("warnings", []))
                        checked(self.native.call({"op": "save", "path": str(working), "working_copy": True}))
                elif command == "update":
                    result = checked(self.native.call({"op": "update", "path": str(working), "changes": request["changes"], "working_copy": True}))
                    native_report = result["document"]
                elif command.startswith("equation-"):
                    if source:
                        checked(self.native.call({"op": "inspect", "path": str(working)}))
                    adapter_request = {k: request[k] for k in ("canvas_id", "object_id", "key", "x", "y", "equation") if k in request}
                    adapter_request["op"] = command
                    if source:
                        adapter_request["path"] = str(working)
                    if command in ("equation-render", "equation-insert"):
                        adapter_request["output_dir"] = str(workdir / "equation-output")
                    result = checked(self.latexit.call(adapter_request))
                    adapter_warnings.extend(result.get("warnings", []))
                    equations.append({"canvas_id": request.get("canvas_id"), "object_id": result.get("object_id", request.get("object_id")),
                                      **result.get("equation", request.get("equation", {}))})
                    if command in ("equation-insert", "equation-update"):
                        checked(self.native.call({"op": "save", "path": str(working), "working_copy": True}))
                if command == "export":
                    final_stage = workdir / ("export." + request["format"].lower())
                    native_request = {"op": "export", "path": str(working), "output": str(final_stage), "format": request["format"],
                                      "dpi": request.get("dpi", 72), "working_copy": True}
                    if request["scope"] == "document":
                        native_request["document_scope"] = True
                    if "canvas_id" in request:
                        native_request["canvas_id"] = request["canvas_id"]
                    checked(self.native.call(native_request))
                    verification = export_check(final_stage, request["format"])
                elif command == "equation-render":
                    final_stage = Path(result["output_dir"]) / "equation.pdf"
                    verification = export_check(final_stage, "PDF")
                else:
                    final_stage = working
                    native_report = checked(self.native.call({"op": "inspect", "path": str(working)}))["document"]
                    if native_report.get("modified") is not False:
                        raise CommandError("verification_failed", "Working document still has unsaved changes")
                    after_report, after_raw = read_document(working)
                    verification = verify_preservation(before_raw, after_raw, changed, before_native, native_report) if before_raw else {"native_structure": "verified"}
                    if before_report:
                        verify_assets(before_report, after_report, changed)
                    if command == "update":
                        for change in request["changes"]:
                            verify_properties(native_report, change["canvas_id"], change["object_id"], change["set"])
                    if command == "create":
                        for canvas in request["spec"]["canvases"]:
                            mapped = created["mapping"][canvas["key"]]
                            native_canvases = [c for c in native_report["canvases"] if c["id"] == mapped["canvas_id"]]
                            if (len(native_canvases) != 1 or native_canvases[0]["name"] != canvas["name"]
                                    or native_canvases[0]["size"] != [canvas["width"], canvas["height"]]):
                                raise CommandError("verification_failed", "Requested canvas name or dimensions did not persist")
                            for obj in canvas["objects"]:
                                if obj["kind"] in ("shape", "text"):
                                    props = {k: v for k, v in obj.items() if k not in ("key", "kind")}
                                    verify_properties(native_report, mapped["canvas_id"], mapped["objects"][obj["key"]], props)
                                elif obj["kind"] == "connector":
                                    verify_properties(native_report, mapped["canvas_id"], mapped["objects"][obj["key"]],
                                                      {"source_id": mapped["objects"][obj["from"]], "destination_id": mapped["objects"][obj["to"]]})
                                elif obj["kind"] == "group":
                                    for child in obj["children"]:
                                        item = target_object(after_report, mapped["canvas_id"], mapped["objects"][child])
                                        if item.get("parent_id") != mapped["objects"][obj["key"]]:
                                            raise CommandError("verification_failed", "Native group membership did not persist")
                    for eq in equations:
                        if eq.get("object_id"):
                            obj = target_object(after_report, eq["canvas_id"], eq["object_id"])
                            if obj.get("linkback", {}).get("owner", {}).get("bundle_id") != STOCK_OWNER:
                                raise CommandError("verification_failed", "Expected a genuine stock-owned LinkBack equation")
                before_close_hash = digest(working) if working.exists() else None
                if working.exists():
                    checked(self.native.call({"op": "close", "path": str(working), "working_copy": True, "discard": False}))
                    check_fingerprint(working, before_close_hash, "Working file after close")
                self.guard_documents(source, output)
                if source:
                    check_fingerprint(source, request["expected_sha256"], "Source before publication")
                self.store.save(receipt, phase="verified_closed", verification=verification, native_document=native_report,
                                equations=equations, staged_sha256=digest(final_stage))
                if command == "equation-source":
                    self.store.finish(receipt, "completed", result={"equations": equations, "source_sha256": request["expected_sha256"]})
                else:
                    output_hash = publish(self.store, receipt, final_stage, output, expected_output)
                    if native_report:
                        native_report = {**native_report, "path": str(output)}
                    warnings = list(adapter_warnings)
                    metadata = None
                    if equations:
                        metadata = Path(str(output) + "." + request["operation_id"] + ".equations.json")
                        try:
                            with metadata.open("x", encoding="utf-8") as f:
                                json.dump({"schema_version": 1, "native_artifact_sha256": output_hash, "equations": equations,
                                           "authority": "Native artifact wins; verify hash and retrieve source again after manual edits."}, f, ensure_ascii=False, indent=2)
                        except OSError:
                            metadata = None
                            warnings.append("Equation metadata remains in the private operation receipt; adjacent sidecar could not be written")
                    self.store.finish(receipt, "committed", result={"output": str(output), "sha256": output_hash,
                                      "equation_metadata": str(metadata) if metadata else None, "verification": verification,
                                      "native_document": native_report, "versions": receipt.get("versions", {}), "palette": palette, "warnings": warnings})
                return receipt
            except Exception as error:
                code = getattr(error, "code", "operation_error")
                unknown = dispatched or getattr(error, "unknown", False)
                self.store.finish(receipt, "outcome_unknown" if unknown else "rejected",
                                  error={"code": code, "message": str(error), "outcome_unknown": unknown,
                                         **getattr(error, "adapter_details", {})})
                return receipt

    def reconcile(self, operation_id):
        with self.store.locked():
            receipt = read_json(self.store.receipt_path(operation_id))
            if receipt["status"] in ("committed", "completed", "rejected", "reconciled_unchanged"):
                return receipt
            output = Path(receipt["output"]) if receipt.get("output") else None
            actual = digest(output) if output else None
            if (receipt.get("phase") in ("publish_pending", "published")
                    and actual is not None and actual == receipt.get("verified_output_sha256")):
                self.store.finish(receipt, "committed", reconciled=True, result={"output": str(output), "sha256": actual,
                                  "verification": receipt.get("verification"), "warnings": ["Publication reconciled; no mutation retried"]})
                return receipt
            # A read-only observation cannot exclude a queued AppleEvent. A
            # restart of both affected processes provides a conservative boundary.
            current = self.process_reader()
            old = {p["pid"] for p in receipt.get("processes", [])}
            now = {p["pid"] for p in current}
            source = Path(receipt["source"]) if receipt.get("source") else None
            source_ok = not source or digest(source) == receipt.get("source_sha256")
            target_ok = actual == receipt.get("expected_output_sha256")
            if old and not old & now and source_ok and target_ok:
                self.store.finish(receipt, "reconciled_unchanged", reconciled=True,
                                  result={"source_unchanged": True, "destination_unchanged": True, "working_copy_retained": receipt.get("working_path")})
            else:
                self.store.save(receipt, reconciliation={"status": "unknown", "source_unchanged": source_ok,
                                "destination_unchanged": target_ok, "old_application_processes_still_running": bool(old & now),
                                "instruction": "Inspect application dialogs and retained working copy. Close/restart the affected apps safely, then reconcile again; no mutation was retried."})
            return receipt
