"""Bounded data-only request contracts for the local drawing commands."""
import json
import math
from pathlib import Path
import re
import uuid


class CommandError(ValueError):
    def __init__(self, code, message, *, unknown=False):
        super().__init__(message)
        self.code, self.unknown = code, unknown


def reject(message, code="invalid_request"):
    raise CommandError(code, message)


def fields(value, allowed, required=()):
    if not isinstance(value, dict):
        reject("Expected a JSON object")
    if set(value) - set(allowed) or set(required) - set(value):
        reject("Unexpected or missing request fields")
    return value


def string(value, label, limit=4096, empty=False):
    if not isinstance(value, str) or (not empty and not value) or len(value.encode("utf-8")) > limit or "\x00" in value:
        reject(f"Invalid {label}")
    return value


def number(value, label, low=0, high=14400):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        reject(f"Invalid {label}; expected finite points in [{low}, {high}]")
    return value


def identifier(value, label="native ID"):
    if type(value) is not int or value < 1:
        reject(f"Invalid {label}")
    return value


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        reject("Colors must be #RRGGBB")


def equation(value):
    fields(value, {"source", "preamble", "mode", "font_size"}, {"source", "preamble", "mode", "font_size"})
    string(value["source"], "TeX source", 32768)
    string(value["preamble"], "TeX preamble", 16384, empty=True)
    if value["mode"] not in ("display", "inline", "align", "text"):
        reject("Unsupported equation mode")
    number(value["font_size"], "font size", 1, 256)
    # TeX is interpreted by the user's engine. This denylist is an extra guard,
    # not a sandbox; callers must provide trusted equation source only.
    forbidden = r"\\(?:input|include|includeonly|write\d*|openin|openout|read\d*|catcode|csname|directlua|luaexec|special|immediate|everyjob|endlinechar|scantokens|usepackage|documentclass)\b"
    if "^^" in value["source"] or re.search(forbidden, value["source"], re.I):
        reject("Equation body contains unsupported TeX I/O or execution constructs", "unsupported_tex")
    preamble = value["preamble"]
    if "^^" in preamble or re.search(forbidden.replace("|usepackage|documentclass", ""), preamble, re.I):
        reject("Preamble contains unsupported TeX I/O or execution constructs", "unsupported_tex")
    return value


def properties(value):
    fields(value, {"x", "y", "width", "height", "text", "font_size", "font_name", "fill", "stroke"})
    if not value:
        reject("Empty object change")
    for key, item in value.items():
        if key in ("x", "y"):
            number(item, key, -14400, 14400)
        elif key in ("width", "height"):
            number(item, key, 0.1, 14400)
        elif key == "font_size":
            number(item, key, 1, 512)
            if int(item) != item:
                reject("Native text font sizes must be whole points")
        elif key in ("fill", "stroke"):
            color(item)
        else:
            string(item, key, 16384 if key == "text" else 256, empty=key == "text")


def specification(spec):
    fields(spec, {"canvases"}, {"canvases"})
    canvases = spec["canvases"]
    if not isinstance(canvases, list) or not 1 <= len(canvases) <= 32:
        reject("Expected 1 to 32 canvases")
    canvas_keys = set()
    total = 0
    for canvas in canvases:
        fields(canvas, {"key", "name", "width", "height", "objects"}, {"key", "name", "width", "height", "objects"})
        key = string(canvas["key"], "canvas key", 128)
        if key in canvas_keys:
            reject("Duplicate canvas key")
        canvas_keys.add(key)
        string(canvas["name"], "canvas name", 256)
        number(canvas["width"], "canvas width", 1)
        number(canvas["height"], "canvas height", 1)
        objects = canvas["objects"]
        if not isinstance(objects, list) or len(objects) > 1000:
            reject("Expected at most 1000 objects per canvas")
        total += len(objects)
        if total > 1000:
            reject("Object limit exceeded")
        keys = {}
        for obj in objects:
            fields(obj, {"key", "kind", "x", "y", "width", "height", "text", "font_size", "font_name", "fill", "stroke", "from", "to", "children", "equation"}, {"key", "kind"})
            name = string(obj["key"], "object key", 128)
            if name in keys:
                reject("Duplicate object key")
            keys[name] = obj
            kind = obj["kind"]
            if kind not in ("shape", "text", "connector", "group", "equation"):
                reject("Unsupported object kind")
            allowed = {"key", "kind"}
            if kind in ("shape", "text"):
                allowed |= {"x", "y", "width", "height", "text", "font_size", "font_name", "fill", "stroke"}
            elif kind == "equation":
                allowed |= {"x", "y", "equation"}
            elif kind == "connector":
                allowed |= {"from", "to", "stroke"}
            else:
                allowed |= {"children"}
            if set(obj) - allowed:
                reject("Unsupported properties for this object kind")
            props = {k: v for k, v in obj.items() if k in ("x", "y", "width", "height", "text", "font_size", "font_name", "fill", "stroke")}
            if props:
                properties(props)
            if kind in ("shape", "text") and not {"x", "y", "width", "height"} <= obj.keys():
                reject("Native shape/text requires point geometry")
            if kind == "equation":
                if not {"x", "y", "equation"} <= obj.keys():
                    reject("Equation requires source settings and point position")
                equation(obj["equation"])
            elif "equation" in obj:
                reject("Equation settings on non-equation object")
        grouped = set()
        for obj in objects:
            if obj["kind"] == "connector":
                for endpoint in ("from", "to"):
                    target = obj.get(endpoint)
                    if not isinstance(target, str) or target not in keys or keys[target]["kind"] not in ("shape", "text"):
                        reject("Connector endpoints must identify native shape/text keys")
            if obj["kind"] == "group":
                children = obj.get("children")
                if not isinstance(children, list) or len(children) < 2 or any(not isinstance(c, str) for c in children) or len(set(children)) != len(children):
                    reject("Groups require distinct child keys")
                for child in children:
                    if child not in keys or keys[child]["kind"] not in ("shape", "text", "connector") or child in grouped:
                        reject("Nested, shared, or equation group members are unsupported")
                    grouped.add(child)
    return spec


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                reject("Duplicate JSON key")
            result[key] = value
        return result
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            reject("Request exceeds one MiB")
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: reject("Nonfinite JSON number"))
    except CommandError:
        raise
    except (OSError, ValueError, RecursionError) as error:
        raise CommandError("invalid_request", "Cannot read bounded JSON request") from error


def validate_request(command, request):
    common = {"operation_id", "input", "expected_sha256", "output", "overwrite", "expected_output_sha256"}
    extra = {
        "create": {"spec", "palette"}, "update": {"changes", "palette"},
        "export": {"canvas_id", "scope", "format", "dpi"},
        "equation-render": {"equation"},
        "equation-source": {"canvas_id", "object_id"},
        "equation-insert": {"canvas_id", "key", "x", "y", "equation"},
        "equation-update": {"canvas_id", "object_id", "equation"},
    }
    if command not in extra:
        reject("Unknown command")
    if command in ("create", "equation-render"):
        common -= {"input", "expected_sha256"}
    if command == "equation-source":
        common -= {"output", "overwrite", "expected_output_sha256"}
    required = {"operation_id"}
    if command not in ("create", "equation-render"):
        required |= {"input", "expected_sha256"}
    if command != "equation-source":
        required.add("output")
    fields(request, common | extra[command], required)
    if "palette" in request:
        fields(request["palette"], {"catalog_path"}, {"catalog_path"})
        string(request["palette"]["catalog_path"], "palette catalog path", 4096)
    try:
        operation_id = str(uuid.UUID(request["operation_id"]))
    except (ValueError, TypeError, AttributeError):
        reject("operation_id must be a UUID")
    if operation_id != request["operation_id"]:
        reject("operation_id must be a canonical lowercase UUID")
    for key in ("input", "output"):
        if key in request:
            string(request[key], key, 4096)
    for key in ("expected_sha256", "expected_output_sha256"):
        if key in request and (not isinstance(request[key], str) or not re.fullmatch("[0-9a-f]{64}", request[key])):
            reject("Expected a lowercase SHA-256 fingerprint")
    if "overwrite" in request and type(request["overwrite"]) is not bool:
        reject("overwrite must be a boolean")
    if command == "create":
        specification(request.get("spec"))
    elif command == "update":
        changes = request.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= 1000:
            reject("Expected 1 to 1000 changes")
        seen = set()
        for change in changes:
            fields(change, {"canvas_id", "object_id", "set"}, {"canvas_id", "object_id", "set"})
            pair = (identifier(change["canvas_id"]), identifier(change["object_id"]))
            if pair in seen:
                reject("Duplicate change target")
            seen.add(pair)
            properties(change["set"])
    elif command == "export":
        if request.get("format") not in ("PDF", "PNG", "SVG"):
            reject("Export format must be PDF, PNG, or SVG")
        if request.get("scope") not in ("canvas", "document"):
            reject("Export scope must explicitly select canvas or document")
        if request["scope"] == "canvas":
            identifier(request.get("canvas_id"), "canvas ID")
        elif "canvas_id" in request:
            reject("Document scope cannot also select canvas_id")
        number(request.get("dpi", 72), "DPI", 36, 600)
    if command.startswith("equation-"):
        if command != "equation-render":
            identifier(request.get("canvas_id"), "canvas ID")
        if command in ("equation-source", "equation-update"):
            identifier(request.get("object_id"), "object ID")
        if command != "equation-source":
            equation(request.get("equation"))
        if command == "equation-insert":
            string(request.get("key"), "equation key", 128)
            number(request.get("x"), "x", -14400)
            number(request.get("y"), "y", -14400)
    return request
