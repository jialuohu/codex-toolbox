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
    # Parsed dictionaries reject duplicate keys on assignment. Convert the
    # comparison copy to plain containers; never mutate the strict parsed tree.
    def plain_container(item):
        if isinstance(item, dict):
            return {key: plain_container(child) for key, child in item.items()}
        if isinstance(item, list):
            return [plain_container(child) for child in item]
        return item
    value = plain_container(graphic)
    # OmniGraffle 7.26 may reopen an explicit RGB style color by converting
    # numeric strings to plist numbers. Normalize only that observed shape,
    # retaining its color-space tag and every other style field.
    styles = value.get("Style")
    for style_name in ("fill", "stroke", "shadow"):
        style = styles.get(style_name) if isinstance(styles, dict) else None
        if not isinstance(style, dict):
            continue
        color = style.get("Color")
        if (not isinstance(color, dict) or set(color) != {"r", "g", "b", "space"}
                or color.get("space") not in {"srgb", "RGB", "rgb"}):
            continue
        converted = {}
        for component_name in ("r", "g", "b"):
            component = color[component_name]
            if isinstance(component, str):
                if len(component) > 64 or not re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", component):
                    raise CommandError("verification_failed", "Unqualified explicit RGB style color")
                component = float(component)
            if type(component) not in (int, float) or not math.isfinite(component) or not 0 <= component <= 1:
                raise CommandError("verification_failed", "Invalid explicit RGB style color")
            converted[component_name] = float(component)
        style["Color"] = {**converted, "space": color["space"]}
    # Observed native default normalization after restarting OmniGraffle 7.26.
    # Only explicit numeric RGB black is equivalent to an absent stroke Color;
    # do not normalize opaque color archives or other color spaces.
    if value.get("Class") == "LineGraphic" and isinstance(styles, dict) and isinstance(styles.get("stroke", {}), dict):
        stroke = value.get("Style", {}).get("stroke", {})
        color = stroke.get("Color")
        if (isinstance(color, dict) and set(color) <= {"r", "g", "b", "space"}
                and color.get("space", "RGB") == "RGB"
                and all(type(color.get(k)) in (int, float) and color[k] == 0 for k in ("r", "g", "b"))):
            stroke.pop("Color")
    for children_field in ("Graphics", "GraphicsList"):
        children = value.get(children_field)
        if isinstance(children, list):
            value[children_field] = [normalized_graphic(child) if isinstance(child, dict) else child
                                     for child in children]
    return value


def verify_preservation(before, after, changed, native_before=None, native_after=None, incident_geometry=()):
    a, b = graph_map(before), graph_map(after)
    # Ancestors contain nested child dictionaries and necessarily change with
    # an explicitly targeted descendant. All other objects compare in full.
    incident_geometry = set(incident_geometry) - set(changed)
    allowed = set(changed) | incident_geometry
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
        if key in incident_geometry:
            if left.get("Class") != right.get("Class") or left.get("Class") != "LineGraphic":
                raise CommandError("verification_failed", f"Incident connector {key} changed class")
            geometry_fields = {"Points", "LogicalPath", "ControlPoints", "Bounds"}
            if left.get("OrthogonalBarAutomatic") is True:
                geometry_fields |= {"OrthogonalBarPoint", "OrthogonalBarPosition"}
            if (normalized_graphic({k: v for k, v in left.items() if k not in geometry_fields})
                    != normalized_graphic({k: v for k, v in right.items() if k not in geometry_fields})):
                raise CommandError("verification_failed", f"Incident connector {key} changed style, attachment, or manual-route metadata")
            continue
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
            left_field, right_field = sheet.get(field), after_sheets[key].get(field)
            if field == "BackgroundGraphic" and isinstance(left_field, dict) and isinstance(right_field, dict):
                left_field, right_field = normalized_graphic(left_field), normalized_graphic(right_field)
            if left_field != right_field:
                raise CommandError("verification_failed", f"Unrelated canvas field {field} changed")
    return {"unrelated_objects": "verified", "comparison": "parsed objects; explicit RGB component strings may normalize to numbers; black line color serialization may normalize with matching native RGB readback"}


TEXT_STYLE_FIELDS = {"font_size", "font_name", "text_color", "text_align", "text_valign", "text_padding"}
TEXT_READBACK_FIELDS = {"font_size", "font_name", "text_color", "text_align"}
CONNECTOR_STYLE_FIELDS = {"stroke", "stroke_width", "stroke_pattern", "line_type",
                          "head_arrow", "tail_arrow", "from_side", "to_side"}


def _qualified_rtf_body(stored):
    if not isinstance(stored, str) or len(stored) > 65536 or not stored.startswith("{\\rtf"):
        return None
    stack, tables = [], []
    index = 0
    while index < len(stored):
        char = stored[index]
        if char == "\\" and index + 1 < len(stored) and stored[index + 1] in "\\{}":
            index += 2
            continue
        if char == "{":
            stack.append(index)
            if len(stack) > 16:
                return None
        elif char == "}":
            if not stack:
                return None
            start = stack.pop()
            content = stored[start + 1:index]
            if re.match(r"\\(?:fonttbl|colortbl)\b|\\\*\\expandedcolortbl\b", content):
                tables.append((start, index + 1, content))
            if not stack and stored[index + 1:].strip():
                return None
        index += 1
    if stack:
        return None
    font_tables = [content for _, _, content in tables if content.startswith("\\fonttbl")]
    if len(font_tables) != 1 or len(re.findall(r"\\f\d+(?=[^A-Za-z\d])", font_tables[0])) != 1:
        return None
    body = stored
    for start, end, _ in sorted(tables, reverse=True):
        body = body[:start] + body[end:]
    index, depth = 0, 0
    while index < len(body):
        if body[index] == "\\" and index + 1 < len(body) and body[index + 1] in "\\{}":
            index += 2
            continue
        if body[index] == "{":
            depth += 1
            if depth > 1:
                return None
        elif body[index] == "}":
            depth -= 1
        index += 1
    return body


def _body_text_attributes(body, *, require_color=True):
    """Qualify one explicit body font/size/color before every text token."""
    attributes = {} if require_color else {"cf": 0}
    first = None
    index = 0
    while index < len(body):
        char = body[index]
        if char in "{}\r\n":
            index += 1
            continue
        if char == "\\":
            control = re.match(r"\\([A-Za-z]+)(-?\d+)? ?", body[index:])
            if control:
                name, number = control.groups()
                if name in {"f", "fs", "cf"}:
                    if number is None or len(number) > 6 or number.startswith("-"):
                        return None
                    attributes[name] = int(number)
                if name != "u":
                    index += len(control.group())
                    continue
        if first is None:
            if char.isspace():
                index += 1
                continue
            if set(attributes) != {"f", "fs", "cf"}:
                return None
            first = dict(attributes)
        if attributes != first:
            return None
        if char == "\\" and index + 1 < len(body):
            index += 2
        else:
            index += 1
    return first if first is not None and attributes == first else None


def uniform_text_attributes(graphic):
    """Conservatively recognize labels for which a whole-text style write is safe.

    Native text archives may contain arbitrary RTF. This does not parse or
    rewrite that archive; unfamiliar or mixed runs are rejected before dispatch.
    """
    stored = graphic.get("Text", "")
    if isinstance(stored, dict):
        stored = stored.get("Text", "")
    if not isinstance(stored, str):
        return False
    if not stored.startswith("{\\rtf"):
        return True
    body = _qualified_rtf_body(stored)
    attributes = _body_text_attributes(body, require_color=False) if body is not None else None
    if attributes is None:
        return False
    color_indices = set(re.findall(r"\\cf(-?\d+)(?=[^A-Za-z\d])", stored))
    if color_indices and color_indices != {str(attributes["cf"])}:
        return False
    fallback_tables = re.findall(r"\{\\colortbl([^{}]*)\}", stored)
    if "\\colortbl" in stored:
        if len(fallback_tables) != 1:
            return False
        fallback = fallback_tables[0]
        if (not re.fullmatch(r"(?:;|\\red\d{1,3}\\green\d{1,3}\\blue\d{1,3};)*", fallback)
                or any(int(item) > 255 for item in re.findall(r"\\(?:red|green|blue)(\d+)", fallback))):
            return False
    # The observed expanded table carries sRGB components in 1/100000 units.
    # Qualify those controls only inside that table, not as arbitrary body text
    # formatting. Unobserved color models or nested destinations fail closed.
    expanded_tables = re.findall(r"\{\\\*\\expandedcolortbl([^{}]*)\}", stored)
    if "\\expandedcolortbl" in stored:
        if len(expanded_tables) != 1:
            return False
        table = expanded_tables[0]
        if (not re.fullmatch(r"(?:;|\\cssrgb\\c\d{1,6}\\c\d{1,6}\\c\d{1,6};)*", table)
                or any(int(component) > 100000 for component in re.findall(r"\\c(\d+)", table))):
            return False
        if not fallback_tables or len(table.split(";")[:-1]) != len(fallback_tables[0].split(";")[:-1]):
            return False
    if fallback_tables:
        entry_count = len(fallback_tables[0].split(";")[:-1])
        if not 0 <= attributes["cf"] < entry_count <= 256:
            return False
    elif attributes["cf"] != 0:
        return False
    control_source = re.sub(r"\{\\\*\\expandedcolortbl[^{}]*\}", "", stored)
    # The allowed controls are the plain, single-run RTF envelope observed in
    # OmniGraffle 7.26 saved labels. Unknown controls may carry formatting that
    # the fixed attributed-text write cannot retain, so they fail closed.
    allowed = {"rtf", "ansi", "ansicpg", "cocoartf", "cocoatextscaling",
               "cocoaplatform", "fonttbl", "deff", "f", "fnil", "fswiss",
               "froman", "fmodern", "fdecor", "ftech", "fbidi", "fcharset",
               "colortbl", "red", "green", "blue", "expandedcolortbl",
               "pard", "tx", "pardirnatural", "qc", "ql", "qr", "qj",
               "partightenfactor", "fs", "cf", "uc", "u"}
    controls = set(re.findall(r"\\([A-Za-z]+)(?:-?\d+)? ?", control_source))
    if controls - allowed:
        return False
    for attr in ("f", "fs", "cf"):
        values = set(re.findall(rf"\\{attr}(-?\d+)(?=[^A-Za-z])", stored))
        if len(values) > 1:
            return False
    aligns = set(re.findall(r"\\q([lrcj])(?=[^A-Za-z])", stored))
    return len(aligns) <= 1


def qualified_saved_text_color(graphic):
    """Recover an exact 16-bit sRGB setter from one qualified saved RTF run.

    The expanded table stores decimal components in 1/100000 units. Accept a
    component only when it identifies a 16-bit value that serializes to exactly
    the same decimal component. Other color models and fractional colors that
    cannot survive this setter are rejected before native mutation.
    """
    if not uniform_text_attributes(graphic):
        raise CommandError("mixed_text_attributes", "Unqualified saved text attributes")
    stored = graphic.get("Text")
    stored = stored.get("Text") if isinstance(stored, dict) else stored
    if not isinstance(stored, str) or len(stored) > 65536:
        raise CommandError("mixed_text_attributes", "Unqualified saved text color")
    body = _qualified_rtf_body(stored)
    attributes = _body_text_attributes(body) if body is not None else None
    if attributes is None:
        raise CommandError("mixed_text_attributes", "Saved text needs explicit uniform body attributes")
    tables = re.findall(r"\{\\\*\\expandedcolortbl([^{}]*)\}", stored)
    fallback_tables = re.findall(r"\{\\colortbl([^{}]*)\}", stored)
    indices = set(re.findall(r"\\cf(\d{1,3})(?=[^A-Za-z\d])", stored))
    if len(tables) != 1 or len(fallback_tables) != 1 or len(indices) != 1:
        raise CommandError("mixed_text_attributes", "Saved text needs one explicit expanded sRGB color")
    fallback = fallback_tables[0]
    if (not re.fullmatch(r"(?:;|\\red\d{1,3}\\green\d{1,3}\\blue\d{1,3};)*", fallback)
            or any(int(item) > 255 for item in re.findall(r"\\(?:red|green|blue)(\d+)", fallback))):
        raise CommandError("mixed_text_attributes", "Saved fallback color table is unsupported")
    entries = tables[0].split(";")[:-1]
    if len(fallback.split(";")[:-1]) != len(entries):
        raise CommandError("mixed_text_attributes", "Saved color table indices disagree")
    index = int(next(iter(indices)))
    if index != attributes["cf"]:
        raise CommandError("mixed_text_attributes", "Saved text color scope is unsupported")
    if not 0 < index < len(entries) or len(entries) > 256:
        raise CommandError("mixed_text_attributes", "Saved text color index is unsupported")
    color = re.fullmatch(r"\\cssrgb\\c(\d{1,6})\\c(\d{1,6})\\c(\d{1,6})", entries[index])
    if not color:
        raise CommandError("mixed_text_attributes", "Saved text color is not explicit sRGB")
    components = [int(item) for item in color.groups()]
    result = [(item * 65535 + 50000) // 100000 for item in components]
    if any((item * 100000 + 32767) // 65535 != original for item, original in zip(result, components)):
        raise CommandError("mixed_text_attributes", "Saved text color cannot be retained exactly by the native setter")
    return result


def verify_retained_text_attributes(before_native, after_native, canvas_id, object_id, requested):
    if "text" in requested:
        return
    prior = target_object(before_native, canvas_id, object_id)
    current = target_object(after_native, canvas_id, object_id)
    fields = {"text": None, "font_name": "font_name", "font_size": "font_size",
              "text_rgb": "text_color", "text_align": "text_align", "text_valign": "text_valign",
              "side_padding": "text_padding", "vertical_padding": "text_padding"}
    for field, public_name in fields.items():
        if public_name not in requested and prior.get(field) != current.get(field):
            raise CommandError("verification_failed", f"Style or geometry change altered unrequested {field}")


def preflight_update_styles(before_raw, changes):
    graphics = graph_map(before_raw)
    moved = set()
    for change in changes:
        key = (change["canvas_id"], change["object_id"])
        graphic = graphics[key]
        requested = change["set"]
        kind = graphic.get("Class")
        if kind == "LineGraphic":
            if set(requested) - CONNECTOR_STYLE_FIELDS:
                raise CommandError("invalid_request", "Unsupported connector property")
        elif kind in ("ShapedGraphic", "SolidGraphic"):
            if "ImageID" in graphic:
                raise CommandError("invalid_request", "Generic updates to image or LinkBack objects are unsupported")
            if kind == "SolidGraphic" and "shape_type" in requested:
                raise CommandError("invalid_request", "Shape type on a non-shape solid")
            if set(requested) & {"line_type", "head_arrow", "tail_arrow", "from_side", "to_side"}:
                raise CommandError("invalid_request", "Connector property on a shape")
            if (set(requested) & TEXT_READBACK_FIELDS and not requested.get("text")
                    and graphic.get("Text") in (None, "", {"Text": ""})):
                raise CommandError("invalid_request", "Text styling requires a nonempty label for native readback")
            if set(requested) & TEXT_STYLE_FIELDS and "text" not in requested and not uniform_text_attributes(graphic):
                raise CommandError("mixed_text_attributes", "Mixed or unqualified text attributes require explicit whole-label replacement")
            if (set(requested) & {"font_size", "font_name", "text_align"}
                    and "text" not in requested and "text_color" not in requested):
                qualified_saved_text_color(graphic)
            if set(requested) & {"x", "y", "width", "height"}:
                moved.add(key)
        else:
            raise CommandError("invalid_request", "Unsupported update for this native graphic class")
    if not moved:
        return set()
    incident = set()
    for key, graphic in graphics.items():
        if graphic.get("Class") != "LineGraphic":
            continue
        endpoint_ids = {graphic.get(side, {}).get("ID") for side in ("Head", "Tail")}
        if not any(canvas_id == key[0] and object_id in endpoint_ids for canvas_id, object_id in moved):
            continue
        points = graphic.get("Points", [])
        stroke = graphic.get("Style", {}).get("stroke", {})
        line_type = stroke.get("LineType")
        auto_orthogonal = line_type == 2 and graphic.get("OrthogonalBarAutomatic") is True
        valid_points = isinstance(points, list) and len(points) >= 2
        simple_segment = valid_points and len(points) == 2 and line_type in (None, 0, 2)
        if (not valid_points or graphic.get("ControlPoints")
                or graphic.get("OrthogonalBarAutomatic") is False
                or not (simple_segment or auto_orthogonal)):
            raise CommandError("manual_connector_route", "Move would alter an incident connector with a manual or unqualified route")
        if any(other.get("Line", {}).get("ID") == key[1] for other_key, other in graphics.items()
               if other_key[0] == key[0]):
            raise CommandError("manual_connector_route", "Move would alter a connector with an attached label")
        incident.add(key)
    return incident


def target_object(report, canvas_id, object_id):
    objects = [o for c in report["canvases"] if c["id"] == canvas_id for o in c["objects"] if o["id"] == object_id]
    if len(objects) != 1:
        raise CommandError("ambiguous_object", "Expected one inspected canvas/object identity")
    return objects[0]


def preflight_native_text_readback(before_native, changes):
    """Reject an empty native label before dispatching an update mutation."""
    for change in changes:
        requested = change["set"]
        if not set(requested) & TEXT_READBACK_FIELDS:
            continue
        if requested.get("text"):
            continue
        obj = target_object(before_native, change["canvas_id"], change["object_id"])
        if not obj.get("text"):
            raise CommandError("invalid_request", "Text styling requires a nonempty native label")


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
    substitutions = []
    for key, expected in properties.items():
        if key in ("x", "y", "width", "height"):
            actual = obj.get("origin" if key in ("x", "y") else "size", [None, None])[0 if key in ("x", "width") else 1]
        elif key in ("fill", "stroke", "text_color"):
            actual = obj.get("text_rgb" if key == "text_color" else key + "_rgb")
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
            if key == "font_name" and isinstance(actual, str) and actual:
                substitutions.append({"canvas_id": canvas_id, "object_id": object_id,
                                      "requested": expected, "native": actual})
                continue
            raise CommandError("verification_failed", f"Native property {key} did not match the requested value")
    return substitutions


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
    if b"\x00" in raw or len(raw) > 16 * 1024 * 1024:
        raise CommandError("verification_failed", "Unsupported SVG envelope")
    # OmniGraffle 7.26 emits this external declaration. Remove its exact,
    # recognized spelling before parsing; never load a DTD or accept entities.
    declaration = (b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                   b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">')
    declarations = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
    sanitized = raw
    if declarations.search(raw):
        if raw.count(declaration) != 1:
            raise CommandError("verification_failed", "Unsupported SVG envelope")
        prefix, suffix = raw.split(declaration)
        prolog = prefix.removeprefix(b"\xef\xbb\xbf").strip()
        if prolog and not re.fullmatch(br"<\?xml\s+[^<>?]*\?>", prolog):
            raise CommandError("verification_failed", "Unsupported SVG envelope")
        sanitized = prefix + suffix
        if declarations.search(sanitized):
            raise CommandError("verification_failed", "Unsupported SVG envelope")
    try:
        # Decode explicitly so another XML encoding cannot conceal declarations
        # from the envelope check or invoke encoding-dependent entity parsing.
        root = ET.fromstring(sanitized.decode("utf-8"))
        if root.tag.split("}")[-1] != "svg":
            raise ValueError()
    except (ET.ParseError, ValueError, UnicodeDecodeError) as error:
        raise CommandError("verification_failed", "Invalid SVG export") from error
    verification = {"format": "SVG", "visual_check": "required"}
    if sanitized != raw:
        # Only the private staged export changes. Its original bytes remain
        # traceable; the native document's source fingerprint is unaffected.
        Path(path).write_bytes(sanitized)
        verification["sanitization"] = {
            "external_doctype_removed": True,
            "original_export_sha256": hashlib.sha256(raw).hexdigest(),
            "sanitized_export_sha256": hashlib.sha256(sanitized).hexdigest(),
        }
    return verification


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
                incident_geometry = set()
                if command == "update":
                    for change in request["changes"]:
                        target_object(before_report, change["canvas_id"], change["object_id"])
                        changed.add((change["canvas_id"], change["object_id"]))
                    incident_geometry = preflight_update_styles(before_raw, request["changes"])
                if command in ("equation-source", "equation-update"):
                    obj = target_object(before_report, request["canvas_id"], request["object_id"])
                    if obj.get("linkback", {}).get("owner", {}).get("bundle_id") != STOCK_OWNER:
                        raise CommandError("foreign_equation_owner", "Only an existing stock-LaTeXiT equation may be edited; ownership migration is not implicit")
                    changed.add((request["canvas_id"], request["object_id"]))
                self.store.save(receipt, phase="adapter_pending", status="pending")
                dispatched = True
                equations = []
                adapter_warnings = []
                font_substitutions = []
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
                    preflight_native_text_readback(before_native, request["changes"])
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
                    saved_hash = digest(working)
                    checked(self.native.call({"op": "close", "path": str(working), "working_copy": True, "discard": False}))
                    check_fingerprint(working, saved_hash, "Working file after saved-readback close")
                    native_report = checked(self.native.call({"op": "inspect", "path": str(working)}))["document"]
                    check_fingerprint(working, saved_hash, "Working file after saved-readback reopen")
                    if native_report.get("modified") is not False:
                        raise CommandError("verification_failed", "Working document still has unsaved changes")
                    after_report, after_raw = read_document(working)
                    verification = verify_preservation(before_raw, after_raw, changed, before_native, native_report,
                                                       incident_geometry=incident_geometry) if before_raw else {"native_structure": "verified"}
                    if before_report:
                        verify_assets(before_report, after_report, changed)
                    if command == "update":
                        for change in request["changes"]:
                            font_substitutions.extend(verify_properties(native_report, change["canvas_id"],
                                                                        change["object_id"], change["set"]))
                            verify_retained_text_attributes(before_native, native_report, change["canvas_id"],
                                                            change["object_id"], change["set"])
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
                                    font_substitutions.extend(verify_properties(native_report, mapped["canvas_id"],
                                                                                mapped["objects"][obj["key"]], props))
                                elif obj["kind"] == "connector":
                                    connector_properties = {key: value for key, value in obj.items() if key in CONNECTOR_STYLE_FIELDS}
                                    font_substitutions.extend(verify_properties(native_report, mapped["canvas_id"],
                                                                                mapped["objects"][obj["key"]],
                                                                               {"source_id": mapped["objects"][obj["from"]],
                                                                                "destination_id": mapped["objects"][obj["to"]],
                                                                                **connector_properties}))
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
                                      "native_document": native_report, "versions": receipt.get("versions", {}),
                                      "palette": palette, "font_substitutions": font_substitutions, "warnings": warnings})
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
