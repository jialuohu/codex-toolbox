"""Portable structural tests, not substitutes for OmniGraffle/LinkBack acceptance."""

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/omnigraffle/document.py"
SPEC = importlib.util.spec_from_file_location("omni_document", SCRIPT)
document = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(document)


def fixture():
    # Field shapes observed in the task's OmniGraffle 7.26 saved prototype.
    return {"GraphDocumentVersion": 16, "FileType": "zipped",
            "ApplicationVersion": ["com.omnigroup.OmniGraffle7", "205.57.23"],
            "MasterSheets": [], "Sheets": [{"UniqueID": 1, "SheetTitle": "Test canvas",
                "BackgroundGraphic": {"ID": 0, "Class": "GraffleShapes.CanvasBackgroundGraphic"},
                "GraphicsList": [
                    {"ID": 2, "Class": "ShapedGraphic", "Name": "unchanged",
                     "Bounds": "{{40, 80}, {140, 60}}", "UnknownData": b"opaque"},
                    {"ID": 3, "Class": "ShapedGraphic", "Name": "target"},
                    {"ID": 4, "Class": "LineGraphic", "Head": {"ID": 3}, "Tail": {"ID": 2}},
                ]}]}


def zip_bytes(plist=None, extras=(), raw_plist=None, fmt=plistlib.FMT_XML):
    result = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("data.plist", raw_plist if raw_plist is not None else
                             plistlib.dumps(fixture() if plist is None else plist, fmt=fmt))
            for name, data in extras:
                archive.writestr(name, data)
    return result.getvalue()


class OmniGraffleDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "example.graffle"

    def inspect(self, plist=None, *, extras=(), raw_plist=None, fmt=plistlib.FMT_XML, limits=None):
        self.path.write_bytes(zip_bytes(plist, extras, raw_plist, fmt))
        return document.inspect_document(self.path, limits=limits)

    def reject(self, plist=None, **kwargs):
        with self.assertRaises(document.DocumentError):
            self.inspect(plist, **kwargs)

    def test_observed_shape_and_opaque_bytes_are_read_only(self):
        report = self.inspect()
        original = self.path.read_bytes()
        self.assertEqual(report["path"], str(self.path.resolve()))
        self.assertEqual(report["file_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(report["file_bytes"], len(original))
        self.assertEqual(report["status"], "inspected")
        self.assertFalse(report["native_app_verified"])
        self.assertFalse(report["live_linkback_verified"])
        self.assertNotIn("opaque", json.dumps(report).replace(report["limitations"], ""))
        self.assertEqual(len(report["canvases"][0]["objects"]), 4)
        self.assertEqual(self.path.read_bytes(), original)

    def test_binary_plist_is_supported_without_unarchiving_data(self):
        item = fixture()
        item["OpaqueArchive"] = b"bplist00NOT AN ARCHIVE"
        report = self.inspect(item, fmt=plistlib.FMT_BINARY)
        self.assertEqual(report["graph_document_version"], 16)
        self.assertNotIn("NOT AN ARCHIVE", json.dumps(report))

    def test_structural_hashes_ignore_key_order_and_isolate_changed_object(self):
        before = self.inspect()
        item = fixture()
        item["Sheets"][0]["GraphicsList"][1]["Name"] = "changed"
        after = self.inspect(item)
        a = {o["id"]: o["structural_sha256"] for o in before["canvases"][0]["objects"]}
        b = {o["id"]: o["structural_sha256"] for o in after["canvases"][0]["objects"]}
        self.assertEqual(a[2], b[2])
        self.assertNotEqual(a[3], b[3])
        self.assertEqual(document._hash({"a": 1, "b": b"raw"}), document._hash({"b": b"raw", "a": 1}))

    def test_duplicate_canvas_and_object_ids_are_rejected(self):
        item = fixture()
        item["Sheets"].append(copy.deepcopy(item["Sheets"][0]))
        self.reject(item)
        item = fixture()
        item["Sheets"][0]["GraphicsList"][1]["ID"] = 2
        self.reject(item)
        item["Sheets"][0]["GraphicsList"][1]["ID"] = 0
        self.reject(item)

    def test_object_ids_are_scoped_to_canvas(self):
        item = fixture()
        another = copy.deepcopy(item["Sheets"][0])
        another["UniqueID"] = 5
        item["Sheets"].append(another)
        self.assertEqual(len(self.inspect(item)["canvases"]), 2)

    def test_malformed_canvas_and_graphic_shapes(self):
        for value in (True, "1", -1):
            item = fixture()
            item["Sheets"][0]["UniqueID"] = value
            self.reject(item)
        item = fixture()
        del item["Sheets"][0]["UniqueID"]
        self.reject(item)
        for key, value in (("GraphicsList", {}), ("BackgroundGraphic", [])):
            item = fixture()
            item["Sheets"][0][key] = value
            self.reject(item)
        for key, value in (("ID", True), ("Class", b"ShapedGraphic"), ("Bounds", []), ("Head", "text")):
            item = fixture()
            item["Sheets"][0]["GraphicsList"][0][key] = value
            self.reject(item)

    def test_missing_endpoint_is_reported_without_inventing_target(self):
        item = fixture()
        item["Sheets"][0]["GraphicsList"][2]["Head"]["ID"] = 99
        report = self.inspect(item)
        self.assertEqual(report["canvases"][0]["warnings"], [
            {"kind": "missing_line_endpoint", "object_id": 4, "endpoint": "head_id", "target_id": 99}])

    def test_nested_groups_are_bounded_and_explicitly_unqualified(self):
        item = fixture()
        graphics = item["Sheets"][0]["GraphicsList"]
        graphics.append({"ID": 5, "Class": "Group", "Graphics": [{"ID": 6, "Class": "ShapedGraphic"}]})
        report = self.inspect(item)
        child = next(o for o in report["canvases"][0]["objects"] if o["id"] == 6)
        self.assertEqual(child["parent_id"], 5)
        self.assertTrue(any("group schema" in q for q in report["qualifications"]))
        graphics[-1]["Graphics"][0]["ID"] = 2
        self.reject(item)
        graphics[-1]["Graphics"] = {}
        self.reject(item)

    def test_image_envelopes_are_opaque_and_associations_unqualified(self):
        item = fixture()
        item["ImageList"] = ["exact.pdf", "missing.png"]
        item["ImageLinkBack"] = [{"appData": b"bplist00INVALID", "untrusted": "not instructions"}, ""]
        item["Sheets"][0]["GraphicsList"][0]["ImageID"] = 123
        report = self.inspect(item, extras=[("exact.pdf", b"%PDF-test")])
        self.assertEqual([r["exists"] for r in report["asset_references"]], [True, False])
        self.assertFalse(report["schema_qualified"])
        self.assertFalse(report["live_linkback_verified"])
        self.assertEqual(report["linkback_envelopes"][0]["opaque_data"]["appData"]["bytes"], 15)
        self.assertNotIn("INVALID", json.dumps(report))
        self.assertNotIn("image123", json.dumps(report))

    def test_unobserved_image_shapes_and_master_sheets_rejected(self):
        for key, value in (("ImageList", {}), ("ImageList", [3]), ("ImageLinkBack", {}), ("MasterSheets", [{}])):
            item = fixture()
            item[key] = value
            self.reject(item)

    def test_unsupported_or_malformed_document_roots_and_versions(self):
        self.reject([])
        for key, value in (("GraphDocumentVersion", 15), ("GraphDocumentVersion", "16"),
                           ("FileType", "flat"), ("Sheets", []), ("Sheets", {})):
            item = fixture()
            item[key] = value
            self.reject(item)

    def test_malformed_report_fields_cannot_escape_to_json(self):
        for value in (b"bytes", ["one"], ["a", b"bytes"], {"a": "b"}):
            item = fixture()
            item["ApplicationVersion"] = value
            self.reject(item)
        item = fixture()
        item["Sheets"][0]["SheetTitle"] = b"binary title"
        self.reject(item)

    def test_unsafe_duplicate_and_casefold_zip_paths(self):
        for name in ("../escape", "/absolute", "a/../b", "a//b", "./data", "a\\b", "C:drive", "x\nname"):
            with self.subTest(name=name):
                self.reject(extras=[(name, b"x")])
        for extras in ([('data.plist', b'x')], [('DATA.PLIST', b'x')], [('a', b'x'), ('a/', b'')],
                       [('caf\u00e9', b'x'), ('cafe\u0301', b'x')]):
            self.reject(extras=extras)

    def test_nul_name_is_rejected_using_original_member_name(self):
        info = zipfile.ZipInfo("a\x00suffix")
        with self.assertRaises(document.DocumentError):
            document._member_name(info)

    def test_symlink_special_file_and_unsupported_compression_rejected(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO):
            info = zipfile.ZipInfo("special")
            info.create_system = 3
            info.external_attr = (mode | 0o777) << 16
            self.reject(extras=[(info, b"somewhere")])
        info = zipfile.ZipInfo("compressed")
        info.compress_type = zipfile.ZIP_BZIP2
        self.reject(extras=[(info, b"compressed data")])

    def test_encrypted_member_flag_rejected_before_decompression(self):
        raw = bytearray(zip_bytes())
        offset = raw.index(b"PK\x01\x02")
        flags = struct.unpack_from("<H", raw, offset + 8)[0]
        struct.pack_into("<H", raw, offset + 8, flags | 1)
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(document.DocumentError, "encrypted"):
            document.inspect_document(self.path)

    def test_resource_limits(self):
        for key in ("file_bytes", "compressed_member_bytes", "member_bytes", "total_member_bytes", "plist_bytes", "plist_nodes", "depth", "graphics"):
            with self.subTest(key=key):
                self.reject(limits={key: 1})
        self.reject(extras=[("extra", b"x")], limits={"members": 1})
        self.reject(extras=[("bomb", b"x" * 100000)], limits={"member_bytes": 10000})
        for limits in ({"unknown": 1}, {"depth": 0}, {"members": True}):
            self.reject(limits=limits)

    def test_declared_member_count_is_checked_before_zipfile_allocation(self):
        raw = bytearray(zip_bytes())
        end = raw.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", raw, end + 8, 3000, 3000)
        self.path.write_bytes(raw)
        with patch.object(document.zipfile, "ZipFile") as constructor:
            with self.assertRaises(document.DocumentError):
                document.inspect_document(self.path)
        constructor.assert_not_called()

    def test_duplicate_plist_keys_and_xml_entities_rejected(self):
        raw = plistlib.dumps(fixture()).replace(b"<key>FileType</key>", b"<key>FileType</key><string>zipped</string><key>FileType</key>")
        self.reject(raw_plist=raw)
        entity = b'<?xml version="1.0"?><!DOCTYPE plist [<!ENTITY x "entity">]><plist version="1.0"><string>&x;</string></plist>'
        self.reject(raw_plist=entity)

    def test_cyclic_binary_plist_and_nonfinite_number_rejected(self):
        item = fixture()
        item["cycle"] = item
        self.reject(item, fmt=plistlib.FMT_BINARY)
        item = fixture()
        item["unknown_float"] = float("nan")
        self.reject(item)

    def test_corrupt_archive_missing_plist_and_unrelated_nonzip_rejected(self):
        for raw in (b"not zip", zip_bytes()[:-5], zip_bytes(raw_plist=b"not plist")):
            self.path.write_bytes(raw)
            with self.assertRaises(document.DocumentError):
                document.inspect_document(self.path)
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w") as archive:
            archive.writestr("elsewhere.plist", plistlib.dumps(fixture()))
        self.path.write_bytes(result.getvalue())
        with self.assertRaises(document.DocumentError):
            document.inspect_document(self.path)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_fifo_is_rejected_without_waiting_for_writer(self):
        os.mkfifo(self.path)
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.path)], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "rejected")

    def test_symlink_is_canonicalized_and_symlink_loop_rejected(self):
        self.inspect()
        alias = Path(self.temp.name) / "alias.graffle"
        alias.symlink_to(self.path)
        self.assertEqual(document.inspect_document(alias)["path"], str(self.path.resolve()))
        loop = Path(self.temp.name) / "loop"
        loop.symlink_to(loop)
        with self.assertRaises(document.DocumentError):
            document.inspect_document(loop)

    def test_cli_stdout_only_and_no_output_argument(self):
        self.inspect()
        original = self.path.read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.path)], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "inspected")
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.path), "--output", str(self.path)], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
