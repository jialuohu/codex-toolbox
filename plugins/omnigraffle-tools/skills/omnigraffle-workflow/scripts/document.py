#!/usr/bin/env python3
"""Read-only inventory of the observed OmniGraffle version-16 ZIP/plist format.

This does not certify native-app behavior or functional LinkBack editing. Embedded
archives are opaque bytes: this module never unarchives application objects.
"""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import plistlib
import stat
import struct
import unicodedata
import xml.parsers.expat
import zipfile
import zlib


DEFAULT_LIMITS = {
    "file_bytes": 64 * 1024 * 1024,
    "members": 2048,
    "compressed_member_bytes": 32 * 1024 * 1024,
    "member_bytes": 64 * 1024 * 1024,
    "total_member_bytes": 128 * 1024 * 1024,
    "plist_bytes": 8 * 1024 * 1024,
    "plist_nodes": 100000,
    "depth": 128,
    "graphics": 50000,
    "canvases": 256,
}


class DocumentError(ValueError):
    """Input cannot be safely inspected as the supported document subset."""


class _UniqueDictionary(dict):
    def __setitem__(self, key, value):
        if key in self:
            raise DocumentError("duplicate plist dictionary key")
        super().__setitem__(key, value)


def _limits(overrides):
    result = DEFAULT_LIMITS.copy()
    if overrides:
        if set(overrides) - set(result):
            raise DocumentError("unknown inspection limit")
        result.update(overrides)
    if any(type(value) is not int or value <= 0 for value in result.values()):
        raise DocumentError("inspection limits must be positive integers")
    return result


def _fingerprint(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns)


def _read_file(path, limits):
    canonical = Path(path).expanduser().resolve(strict=True)
    descriptor = os.open(canonical, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
                         | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise DocumentError("input must be a regular file")
        if before.st_size > limits["file_bytes"]:
            raise DocumentError("compressed file size limit exceeded")
        data = stream.read(limits["file_bytes"] + 1)
        after = os.fstat(stream.fileno())
    if len(data) > limits["file_bytes"]:
        raise DocumentError("compressed file size limit exceeded")
    if (_fingerprint(before) != _fingerprint(after)
            or _fingerprint(after) != _fingerprint(canonical.stat())
            or len(data) != before.st_size):
        raise DocumentError("input changed during inspection")
    return canonical, data


def _member_name(info):
    name = info.orig_filename
    if (not name or "\x00" in name or "\\" in name or name.startswith("/")
            or ":" in name or any(ord(char) < 32 for char in name)):
        raise DocumentError("unsafe ZIP member path")
    components = name.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in components):
        raise DocumentError("unsafe ZIP member path")
    return name


def _read_archive(raw, limits):
    members = []
    plist_data = None
    # Check the small end record before ZipFile allocates an object per member.
    end_offset = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
    if end_offset < 0 or len(raw) - end_offset < 22:
        raise DocumentError("missing ZIP end record")
    (_, disk, directory_disk, disk_count, count, directory_bytes, directory_offset,
     comment_bytes) = struct.unpack_from("<4s4H2IH", raw, end_offset)
    if disk or directory_disk or disk_count != count:
        raise DocumentError("multidisk ZIP is unsupported")
    if count == 65535 or directory_bytes == 0xffffffff or directory_offset == 0xffffffff:
        raise DocumentError("ZIP64 is outside the observed format subset")
    if count > limits["members"]:
        raise DocumentError("ZIP member count limit exceeded")
    if (end_offset + 22 + comment_bytes != len(raw)
            or directory_offset + directory_bytes != end_offset
            or not raw.startswith(b"PK\x03\x04")):
        raise DocumentError("unsupported ZIP envelope")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > limits["members"]:
            raise DocumentError("ZIP member count limit exceeded or empty archive")
        names = set()
        normalized_names = set()
        declared_total = 0
        for info in infos:
            name = _member_name(info)
            normalized = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
            if name in names or normalized in normalized_names:
                raise DocumentError("duplicate or casefold-colliding ZIP member paths")
            names.add(name)
            normalized_names.add(normalized)
            if info.flag_bits & (1 | 64):
                raise DocumentError("encrypted ZIP members are unsupported")
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise DocumentError("symlink or special ZIP member is unsupported")
            if (mode == stat.S_IFDIR) != info.is_dir() and mode != 0:
                raise DocumentError("inconsistent ZIP directory metadata")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise DocumentError("unsupported ZIP compression")
            if info.compress_size > limits["compressed_member_bytes"]:
                raise DocumentError("compressed member size limit exceeded")
            if info.file_size > limits["member_bytes"]:
                raise DocumentError("decompressed member size limit exceeded")
            if name == "data.plist" and info.file_size > limits["plist_bytes"]:
                raise DocumentError("plist size limit exceeded")
            if info.is_dir() and info.file_size:
                raise DocumentError("nonempty ZIP directory member")
            declared_total += info.file_size
        if declared_total > limits["total_member_bytes"]:
            raise DocumentError("total decompressed size limit exceeded")
        actual_total = 0
        for info in infos:
            digest = hashlib.sha256()
            size = 0
            chunks = [] if info.filename == "data.plist" else None
            with archive.open(info, "r") as source:
                while True:
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    actual_total += len(chunk)
                    if size > limits["member_bytes"] or actual_total > limits["total_member_bytes"]:
                        raise DocumentError("actual decompressed size limit exceeded")
                    if chunks is not None:
                        if size > limits["plist_bytes"]:
                            raise DocumentError("plist size limit exceeded")
                        chunks.append(chunk)
                    digest.update(chunk)
            if size != info.file_size:
                raise DocumentError("ZIP member length mismatch")
            if chunks is not None:
                plist_data = b"".join(chunks)
            members.append({"path": info.filename, "bytes": size,
                            "compressed_bytes": info.compress_size,
                            "sha256": digest.hexdigest(), "directory": info.is_dir()})
    if plist_data is None:
        raise DocumentError("modern ZIP document requires root data.plist")
    return members, plist_data


def _xml_preflight(raw, limits):
    parser = xml.parsers.expat.ParserCreate()
    depth = 0
    nodes = 0

    def start(_name, _attrs):
        nonlocal depth, nodes
        depth += 1
        nodes += 1
        if depth > limits["depth"] or nodes > limits["plist_nodes"]:
            raise DocumentError("plist nesting or node limit exceeded")

    def end(_name):
        nonlocal depth
        depth -= 1

    def reject_entity(*_args):
        raise DocumentError("XML entity declarations and external entities are unsupported")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.EntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_entity
    parser.Parse(raw, True)


def _validate_tree(root, limits):
    stack = [(root, 0, False)]
    active = set()
    nodes = 0
    while stack:
        value, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(value))
            continue
        nodes += 1
        if nodes > limits["plist_nodes"] or depth > limits["depth"]:
            raise DocumentError("plist nesting or node limit exceeded")
        if isinstance(value, float) and not math.isfinite(value):
            raise DocumentError("non-finite plist number")
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise DocumentError("cyclic plist containers")
            active.add(id(value))
            stack.append((value, depth, True))
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise DocumentError("plist dictionary keys must be strings")
                children = value.values()
            else:
                children = value
            stack.extend((child, depth + 1, False) for child in children)


def _parse_plist(raw, limits):
    if raw.startswith(b"bplist00"):
        if len(raw) < 40:
            raise DocumentError("truncated binary plist")
        object_count = int.from_bytes(raw[-24:-16], "big")
        if object_count > limits["plist_nodes"]:
            raise DocumentError("binary plist object count limit exceeded")
    else:
        _xml_preflight(raw, limits)
    result = plistlib.loads(raw, dict_type=_UniqueDictionary)
    _validate_tree(result, limits)
    return result


def _hash(value):
    """Hash the parsed structure, including opaque data without interpreting it."""
    return hashlib.sha256(plistlib.dumps(value, fmt=plistlib.FMT_BINARY, sort_keys=True)).hexdigest()


def _identifier(value, subject):
    if type(value) is not int or value < 0:
        raise DocumentError(f"{subject} must be a nonnegative integer")
    return value


def _canvas(sheet, limits, qualifications):
    if not isinstance(sheet, dict):
        raise DocumentError("canvas must be a dictionary")
    canvas_id = _identifier(sheet.get("UniqueID"), "canvas UniqueID")
    if "SheetTitle" in sheet and not isinstance(sheet["SheetTitle"], str):
        raise DocumentError("SheetTitle must be a string")
    graphics = sheet.get("GraphicsList")
    if not isinstance(graphics, list):
        raise DocumentError("canvas GraphicsList must be an array")
    background = sheet.get("BackgroundGraphic")
    if background is not None and not isinstance(background, dict):
        raise DocumentError("BackgroundGraphic must be a dictionary")
    roots = [(item, None, "GraphicsList") for item in graphics]
    if background is not None:
        roots.append((background, None, "BackgroundGraphic"))
    stack = [(graphic, parent, location, 0) for graphic, parent, location in reversed(roots)]
    seen = set()
    objects = []
    while stack:
        graphic, parent, location, depth = stack.pop()
        if depth > limits["depth"] or len(objects) >= limits["graphics"]:
            raise DocumentError("graphic nesting or count limit exceeded")
        if not isinstance(graphic, dict):
            raise DocumentError("graphic must be a dictionary")
        identifier = _identifier(graphic.get("ID"), "graphic ID")
        if identifier in seen:
            raise DocumentError("duplicate graphic ID within canvas")
        seen.add(identifier)
        if not isinstance(graphic.get("Class"), str) or not graphic["Class"]:
            raise DocumentError("graphic Class must be a nonempty string")
        record = {"id": identifier, "class": graphic["Class"], "parent_id": parent,
                  "location": location, "structural_sha256": _hash(graphic)}
        for field in ("Name", "Bounds"):
            if field in graphic:
                if not isinstance(graphic[field], str):
                    raise DocumentError(f"graphic {field} must be a string")
                record[field.lower()] = graphic[field]
        for endpoint in ("Head", "Tail"):
            if endpoint in graphic:
                target = graphic[endpoint]
                if not isinstance(target, dict):
                    raise DocumentError("line endpoint must be a dictionary")
                record[endpoint.lower() + "_id"] = _identifier(target.get("ID"), "line endpoint ID")
        if "ImageID" in graphic:
            record["image_id"] = _identifier(graphic["ImageID"], "image ID")
        for children_key in ("Graphics", "GraphicsList"):
            if children_key in graphic:
                children = graphic[children_key]
                if not isinstance(children, list):
                    raise DocumentError("nested graphics must be an array")
                qualifications.add("nested group schema requires native-app qualification")
                stack.extend((child, identifier, children_key, depth + 1) for child in reversed(children))
        objects.append(record)
    warnings = []
    for obj in objects:
        for endpoint in ("head_id", "tail_id"):
            if endpoint in obj and obj[endpoint] not in seen:
                warnings.append({"kind": "missing_line_endpoint", "object_id": obj["id"],
                                 "endpoint": endpoint, "target_id": obj[endpoint]})
    return {"id": canvas_id, "title": sheet.get("SheetTitle"),
            "structural_sha256": _hash(sheet), "objects": objects, "warnings": warnings}


def _images(document, members, canvases):
    """Version-16 associations observed in native saved LinkBack fixtures.

    ImageID is one-based; ImageList and ImageLinkBack use the same zero-based
    array index. Explicit empty dictionaries/strings denote no LinkBack data;
    missing array tails and other shapes remain unqualified, never guessed.
    """
    result = {"asset_references": [], "linkback_envelopes": [],
              "schema_qualified": True, "findings": []}
    by_path = {m['path']: m for m in members if not m['directory']}
    def finding(kind, **details):
        result['schema_qualified'] = False
        result['findings'].append({'severity': 'error', 'kind': kind, **details})
    images = document.get('ImageList', [])
    links = document.get('ImageLinkBack')
    if not isinstance(images, list) or any(not isinstance(x, str) or not x for x in images):
        finding('malformed_image_list')
        images = []
    if links is not None and not isinstance(links, list):
        finding('malformed_linkback_array')
        links = []
    if links is not None and len(links) != len(images):
        finding('linkback_array_length_mismatch', image_count=len(images), linkback_count=len(links))
    for index, filename in enumerate(images):
        member = by_path.get(filename)
        asset = {'field': 'ImageList', 'index': index, 'image_id': index + 1,
                 'path': filename, 'exists': member is not None}
        if member:
            asset['sha256'] = member['sha256']
        else:
            finding('missing_image_asset', image_id=index + 1, path=filename)
        result['asset_references'].append(asset)
    envelopes = {}
    for index, item in enumerate(links or []):
        envelope = {'index': index, 'image_id': index + 1, 'structural_sha256': _hash(item),
                    'empty': item == {} or item == '', 'valid': False}
        if envelope['empty']:
            envelope['valid'] = True
        elif not isinstance(item, dict):
            finding('malformed_linkback_record', image_id=index + 1)
        else:
            required = ('bundleId', 'serverName', 'serverAppName', 'version')
            valid = all(isinstance(item.get(k), str) and bool(item[k]) and '\x00' not in item[k]
                        for k in required)
            valid = valid and item.get('version') == 'A' and isinstance(item.get('appData'), bytes) and bool(item['appData'])
            if 'refresh' in item and (isinstance(item['refresh'], bool) or not isinstance(item['refresh'], (int, float)) or item['refresh'] < 0):
                valid = False
            for optional in ('ApplicationURL', 'serverActionKey'):
                if optional in item and not isinstance(item[optional], str):
                    valid = False
            if valid:
                envelope.update({'valid': True, 'owner': {'bundle_id': item['bundleId'],
                    'server_name': item['serverName'], 'app_name': item['serverAppName']},
                    'payload_sha256': hashlib.sha256(item['appData']).hexdigest(),
                    'payload_bytes': len(item['appData'])})
            else:
                finding('malformed_linkback_record', image_id=index + 1)
        result['linkback_envelopes'].append(envelope)
        envelopes[index + 1] = envelope
    for canvas in canvases:
        for obj in canvas['objects']:
            if 'image_id' not in obj:
                continue
            image_id = obj['image_id']
            if not 1 <= image_id <= len(images):
                finding('invalid_image_reference', canvas_id=canvas['id'], object_id=obj['id'], image_id=image_id)
                continue
            obj['image'] = result['asset_references'][image_id - 1].copy()
            envelope = envelopes.get(image_id)
            if envelope and envelope['valid'] and not envelope['empty']:
                obj['linkback'] = {k: envelope[k] for k in ('owner', 'payload_sha256', 'payload_bytes')}
    return result


def _read_document(path, *, limits=None):
    bounds = _limits(limits)
    try:
        canonical, raw = _read_file(path, bounds)
        members, plist_data = _read_archive(raw, bounds)
        document = _parse_plist(plist_data, bounds)
        if not isinstance(document, dict):
            raise DocumentError("document root must be a dictionary")
        if type(document.get("GraphDocumentVersion")) is not int or document["GraphDocumentVersion"] != 16:
            raise DocumentError("unsupported GraphDocumentVersion; only observed version 16 is inspected")
        if document.get("FileType") != "zipped":
            raise DocumentError("unsupported FileType; expected zipped")
        application_version = document.get("ApplicationVersion")
        if application_version is not None and (
                not isinstance(application_version, list) or len(application_version) != 2
                or any(not isinstance(value, str) for value in application_version)):
            raise DocumentError("unsupported ApplicationVersion shape")
        sheets = document.get("Sheets")
        if not isinstance(sheets, list) or not sheets or len(sheets) > bounds["canvases"]:
            raise DocumentError("invalid canvas array or canvas count limit exceeded")
        if document.get("MasterSheets", []) != []:
            raise DocumentError("nonempty MasterSheets schema is not qualified")
        qualifications = set()
        canvases = [_canvas(sheet, bounds, qualifications) for sheet in sheets]
        if len({canvas["id"] for canvas in canvases}) != len(canvases):
            raise DocumentError("duplicate canvas UniqueID")
        if sum(len(canvas["objects"]) for canvas in canvases) > bounds["graphics"]:
            raise DocumentError("total graphic count limit exceeded")
        images = _images(document, members, canvases)
        inspection = {"status": "inspected", "path": str(canonical), "file_bytes": len(raw),
                "file_sha256": hashlib.sha256(raw).hexdigest(), "format": "zip/plist",
                "graph_document_version": 16, "application_version": document.get("ApplicationVersion"),
                "document_structural_sha256": _hash(document), "members": members,
                "canvases": canvases, **images, "qualifications": sorted(qualifications),
                "native_app_verified": False, "live_linkback_verified": False,
                "limitations": "Structural inventory only. Opaque archives were not deserialized; no native app or visual checks ran."}
        return inspection, document
    except DocumentError:
        raise
    except (OSError, EOFError, KeyError, IndexError, TypeError, ValueError, OverflowError,
            RecursionError, zipfile.BadZipFile, NotImplementedError, xml.parsers.expat.ExpatError,
            struct.error, zlib.error, RuntimeError) as error:
        raise DocumentError(f"cannot inspect document ({type(error).__name__})") from error


def inspect_document(path, *, limits=None):
    """Read-only audit; association defects are findings, unsafe envelopes reject."""
    return _read_document(path, limits=limits)[0]


def read_document(path, *, limits=None):
    """Return (inspection, parsed plist) for mutation planning, never unarchiving.

    Reject malformed LinkBack records, dangling image/connector references and
    missing assets. Callers must additionally apply their own fingerprint,
    document-state and preservation checks. Returned appData remains opaque.
    """
    inspection, parsed = _read_document(path, limits=limits)
    defects = inspection['findings'] + [warning for canvas in inspection['canvases'] for warning in canvas['warnings']]
    if defects:
        raise DocumentError('document has unsafe structural findings: ' + ', '.join(sorted({x['kind'] for x in defects})))
    return inspection, parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect_document(args.file)
    except DocumentError as error:
        print(json.dumps({"status": "rejected", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
