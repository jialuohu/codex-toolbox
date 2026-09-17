"""Portable transaction failure boundaries; never invoke installed applications."""
import copy
import importlib.util
import os
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

from tests.test_omnigraffle_document import fixture, zip_bytes

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts"
# Keep imports consistent with the executable's adjacent-module imports.
sys.path.insert(0, str(SCRIPTS))
import contracts
import engine
import transactions as tx
sys.path.pop(0)


class FakeNative:
    def __init__(self):
        self.calls = []
        self.documents = []
        self.fail_update = False
        self.after_close = None

    def call(self, request):
        self.calls.append(copy.deepcopy(request))
        op = request["op"]
        if op == "inventory":
            return {"status": "ok", "documents": self.documents}
        if op == "update":
            if self.fail_update:
                raise TimeoutError("Native response lost")
            report, raw = engine.read_document(request["path"])
            for change in request["changes"]:
                obj = engine.graph_map(raw)[change["canvas_id"], change["object_id"]]
                obj["Text"] = change["set"].get("text", "changed")
            Path(request["path"]).write_bytes(zip_bytes(raw))
        if op == "close" and self.after_close:
            self.after_close()
        report, raw = engine.read_document(request["path"])
        for canvas in report["canvases"]:
            for obj in canvas["objects"]:
                obj["text"] = engine.graph_map(raw)[canvas["id"], obj["id"]].get("Text", "")
        return {"status": "ok", "document": {"modified": False, "canvases": report["canvases"]}}


class NeverGUI:
    def call(self, request):
        raise AssertionError("Unexpected equation GUI dispatch")


class TransactionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = tx.Store(self.root / "receipts", guard=self.root / "guard")
        self.native = FakeNative()
        self.processes = [{"bundle_id": "com.omnigroup.OmniGraffle7", "pid": 101, "path": "/fake/OmniGraffle.app"},
                          {"bundle_id": engine.STOCK_OWNER, "pid": 102, "path": "/fake/LaTeXiT.app"}]
        self.engine = engine.Engine(self.native, NeverGUI(), self.store, lambda: self.processes)
        self.source = self.root / "input.graffle"
        self.source.write_bytes(zip_bytes())
        self.output = self.root / "output.graffle"
        self.request = {"operation_id": str(uuid.uuid4()), "input": str(self.source),
                        "expected_sha256": tx.digest(self.source), "output": str(self.output),
                        "changes": [{"canvas_id": 1, "object_id": 3, "set": {"text": "new"}}]}

    def reject(self, code, request=None):
        receipt = self.engine.perform("update", request or self.request)
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["error"]["code"], code)
        self.assertFalse(any(c["op"] == "update" for c in self.native.calls))
        return receipt

    def test_commit_receipt_survives_recreation_without_replay(self):
        first = self.engine.perform("update", self.request)
        self.assertEqual(first["status"], "committed")
        calls = len(self.native.calls)
        recreated = engine.Engine(self.native, NeverGUI(), tx.Store(self.root / "receipts", guard=self.root / "guard"), lambda: self.processes)
        second = recreated.perform("update", self.request)
        self.assertTrue(second["replayed_receipt"])
        self.assertEqual(len(self.native.calls), calls)
        self.assertEqual(tx.digest(self.source), self.request["expected_sha256"])
        changed = copy.deepcopy(self.request)
        changed["changes"][0]["set"]["text"] = "different"
        with self.assertRaises(contracts.CommandError) as error:
            recreated.perform("update", changed)
        self.assertEqual(error.exception.code, "operation_id_conflict")

    def test_receipt_override_does_not_bypass_lock_or_pending_guard(self):
        other = tx.Store(self.root / "other-receipts", guard=self.root / "guard")
        with self.store.locked():
            with self.assertRaises(contracts.CommandError) as error:
                with other.locked():
                    self.fail("Contending guard admitted a second owner")
            self.assertEqual(error.exception.code, "busy")
        self.store.begin(self.request["operation_id"], "update", self.request)
        with self.assertRaises(contracts.CommandError) as error:
            other.begin(str(uuid.uuid4()), "update", self.request)
        self.assertEqual(error.exception.code, "reconciliation_required")

    def test_receipt_override_cannot_replay_completed_operation(self):
        first = self.engine.perform("update", self.request)
        self.assertEqual(first["status"], "committed")
        other = tx.Store(self.root / "different-receipts", guard=self.root / "guard")
        other_engine = engine.Engine(self.native, NeverGUI(), other, lambda: self.processes)
        count = len(self.native.calls)
        replay = other_engine.perform("update", self.request)
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(len(self.native.calls), count)
        self.assertEqual(other.receipt_path(self.request["operation_id"]), Path(first["receipt"]))

    def test_overwrite_preserves_destination_mode_and_backup(self):
        self.output.write_bytes(b"original destination")
        self.output.chmod(0o640)
        self.request.update(overwrite=True, expected_output_sha256=tx.digest(self.output))
        receipt = self.engine.perform("update", self.request)
        self.assertEqual(receipt["status"], "committed")
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o640)
        self.assertEqual(Path(receipt["backup_path"]).read_bytes(), b"original destination")

    def test_stale_source_rejected_before_dispatch(self):
        self.source.write_bytes(zip_bytes({**fixture(), "Changed": True}))
        self.reject("stale_file")

    def test_existing_destination_requires_matching_authorized_hash(self):
        self.output.write_bytes(b"user output")
        self.request.update(overwrite=True, expected_output_sha256="0" * 64)
        self.reject("overwrite_not_authorized")
        self.assertEqual(self.output.read_bytes(), b"user output")

    def test_unsaved_source_is_not_overwritten(self):
        self.native.documents = [{"path": str(self.source), "modified": True}]
        self.reject("unsaved_document")

    def test_saved_but_open_destination_is_not_replaced(self):
        self.native.documents = [{"path": str(self.output), "modified": False}]
        self.reject("destination_open")

    def test_symlink_and_hardlink_output_aliases_rejected(self):
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    self.output.symlink_to(self.source)
                else:
                    os.link(self.source, self.output)
                self.request["operation_id"] = str(uuid.uuid4())
                self.reject("output_alias")
                self.output.unlink()

    def test_timeout_blocks_new_mutation_and_reconcile_never_dispatches(self):
        self.native.fail_update = True
        receipt = self.engine.perform("update", self.request)
        self.assertEqual(receipt["status"], "outcome_unknown")
        calls = len(self.native.calls)
        different = {**self.request, "operation_id": str(uuid.uuid4())}
        with self.assertRaises(contracts.CommandError) as error:
            self.engine.perform("update", different)
        self.assertEqual(error.exception.code, "reconciliation_required")
        self.assertEqual(self.engine.reconcile(receipt["operation_id"])["status"], "outcome_unknown")
        self.assertEqual(len(self.native.calls), calls)
        self.processes[0] = {**self.processes[0], "pid": 201}
        self.assertEqual(self.engine.reconcile(receipt["operation_id"])["status"], "outcome_unknown")
        self.processes = [{**p, "pid": p["pid"] + 100} for p in self.processes]
        self.assertEqual(self.engine.reconcile(receipt["operation_id"])["status"], "reconciled_unchanged")
        self.assertEqual(len(self.native.calls), calls)

    def test_source_changed_before_publication_preserves_destination(self):
        self.native.after_close = lambda: self.source.write_bytes(zip_bytes({**fixture(), "ManualEdit": True}))
        receipt = self.engine.perform("update", self.request)
        self.assertEqual(receipt["status"], "outcome_unknown")
        self.assertEqual(receipt["error"]["code"], "stale_file")
        self.assertFalse(self.output.exists())

    def test_destination_changed_during_native_work_is_not_replaced(self):
        self.output.write_bytes(b"prior export")
        self.request.update(overwrite=True, expected_output_sha256=tx.digest(self.output))
        self.native.after_close = lambda: self.output.write_bytes(b"concurrent user change")
        receipt = self.engine.perform("update", self.request)
        self.assertEqual(receipt["status"], "outcome_unknown")
        self.assertEqual(receipt["error"]["code"], "stale_file")
        self.assertEqual(self.output.read_bytes(), b"concurrent user change")

    def test_publication_crash_after_rename_reconciles_by_verified_hash(self):
        original_save = self.store.save
        def crash(receipt, **updates):
            if updates.get("phase") == "published":
                raise OSError("Simulated receipt failure after publication")
            return original_save(receipt, **updates)
        with patch.object(self.store, "save", side_effect=crash):
            receipt = self.engine.perform("update", self.request)
        self.assertEqual(receipt["status"], "outcome_unknown")
        self.assertTrue(self.output.exists())
        calls = len(self.native.calls)
        result = self.engine.reconcile(receipt["operation_id"])
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["result"]["sha256"], tx.digest(self.output))
        self.assertEqual(len(self.native.calls), calls)

    def test_publication_crash_before_rename_requires_restart_boundary(self):
        with patch.object(tx.os, "link", side_effect=OSError("Simulated pre-publication failure")):
            receipt = self.engine.perform("update", self.request)
        self.assertEqual(receipt["phase"], "publish_pending")
        self.assertFalse(self.output.exists())
        self.assertEqual(self.engine.reconcile(receipt["operation_id"])["status"], "outcome_unknown")
        self.processes = []
        self.assertEqual(self.engine.reconcile(receipt["operation_id"])["status"], "reconciled_unchanged")

    def test_hostile_label_reaches_fixed_adapter_unchanged_as_data(self):
        label = '中文 $(touch /tmp/not-run) `id` " & do shell script "false'
        self.request["changes"][0]["set"]["text"] = label
        receipt = self.engine.perform("update", self.request)
        self.assertEqual(receipt["status"], "committed")
        update = next(c for c in self.native.calls if c["op"] == "update")
        self.assertEqual(update["changes"][0]["set"]["text"], label)

    def test_cli_audit_refuses_same_symlink_hardlink_and_existing_outputs(self):
        symlink = self.root / "symlink.graffle"
        symlink.symlink_to(self.source)
        hardlink = self.root / "hardlink.graffle"
        os.link(self.source, hardlink)
        existing = self.root / "existing.json"
        existing.write_bytes(b"retain report")
        for destination in (self.source, symlink, hardlink, existing):
            with self.subTest(destination=destination.name):
                before = destination.read_bytes()
                run = subprocess.run([sys.executable, str(SCRIPTS / "omnigraffle.py"), "audit", str(self.source), "--output", str(destination)], capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertEqual(json.loads(run.stdout)["status"], "rejected")
                self.assertEqual(destination.read_bytes(), before)
        report = self.root / "new-report.json"
        run = subprocess.run([sys.executable, str(SCRIPTS / "omnigraffle.py"), "audit", str(self.source), "--output", str(report)], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(report.read_text())["audit"]["native_editability"], "not_verified")


class PreservationAndRequestTests(unittest.TestCase):
    def test_unrelated_object_change_and_target_deletion_rejected(self):
        before = fixture()
        after = copy.deepcopy(before)
        after["Sheets"][0]["GraphicsList"][0]["Bounds"] = "changed"
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, {(1, 3)})
        after = copy.deepcopy(before)
        after["Sheets"][0]["GraphicsList"] = [g for g in after["Sheets"][0]["GraphicsList"] if g["ID"] != 3]
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, {(1, 3)})

    def test_only_observed_numeric_black_normalization_is_equivalent(self):
        before = fixture()
        line = before["Sheets"][0]["GraphicsList"][2]
        line["Style"] = {"stroke": {}}
        after = copy.deepcopy(before)
        stroke = after["Sheets"][0]["GraphicsList"][2]["Style"]["stroke"]
        stroke["Color"] = {"r": 0, "g": 0, "b": 0}
        engine.verify_preservation(before, after, set())
        for color in ({"r": 1, "g": 0, "b": 0}, b"opaque-black", {"r": 0, "g": 0, "b": 0, "profile": "unknown"}):
            stroke["Color"] = color
            with self.assertRaises(contracts.CommandError):
                engine.verify_preservation(before, after, set())

    def test_editing_child_does_not_authorize_group_metadata_changes(self):
        before = fixture()
        children = before["Sheets"][0]["GraphicsList"][:2]
        before["Sheets"][0]["GraphicsList"] = [{"ID": 9, "Class": "Group", "Name": "keep", "Graphics": children}]
        after = copy.deepcopy(before)
        after["Sheets"][0]["GraphicsList"][0]["Graphics"][1]["Name"] = "requested"
        engine.verify_preservation(before, after, {(1, 3)})
        after["Sheets"][0]["GraphicsList"][0]["Name"] = "unrequested group rename"
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, {(1, 3)})

    def test_opaque_black_line_reencoding_requires_independent_native_proof(self):
        before = fixture()
        before["Sheets"][0]["GraphicsList"][2]["Style"] = {"stroke": {"Color": b"original-opaque-color", "Width": 1}}
        after = copy.deepcopy(before)
        after["Sheets"][0]["GraphicsList"][2]["Style"]["stroke"]["Color"] = b"reserialized-opaque-color"
        black = {"canvases": [{"id": 1, "objects": [{"id": 4, "stroke_rgb": [0, 0, 0]}]}]}
        colored = {"canvases": [{"id": 1, "objects": [{"id": 4, "stroke_rgb": [1, 0, 0]}]}]}
        for first, second in ((None, None), (black, None), (None, black), (black, colored), (colored, black)):
            with self.subTest(first=first, second=second):
                with self.assertRaises(contracts.CommandError):
                    engine.verify_preservation(before, after, set(), first, second)
        engine.verify_preservation(before, after, set(), black, black)
        after["Sheets"][0]["GraphicsList"][2]["Style"]["stroke"]["Width"] = 2
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, set(), black, black)

    def test_ambiguous_native_black_readback_is_not_preservation_proof(self):
        before = fixture()
        before["Sheets"][0]["GraphicsList"][2]["Style"] = {"stroke": {"Color": b"opaque"}}
        after = copy.deepcopy(before)
        after["Sheets"][0]["GraphicsList"][2]["Style"]["stroke"]["Color"] = b"changed"
        report = {"canvases": [{"id": 1, "objects": [{"id": 4, "stroke_rgb": [0, 0, 0]}, {"id": 4, "stroke_rgb": [0, 0, 0]}]}]}
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, set(), report, report)

    def test_duplicate_keys_nonfinite_and_oversized_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "request.json"
            for raw in ('{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}', '{"x":NaN}', ' ' * (1024 * 1024 + 1)):
                path.write_text(raw)
                with self.assertRaises(contracts.CommandError):
                    contracts.load_json(path)

    def test_unknown_fields_and_duplicate_native_changes_rejected(self):
        request = {"operation_id": str(uuid.uuid4()), "input": "/data/a.graffle", "expected_sha256": "a" * 64,
                   "output": "/data/b.graffle", "changes": [{"canvas_id": 1, "object_id": 2, "set": {"text": "safe"}}]}
        with self.assertRaises(contracts.CommandError):
            contracts.validate_request("update", {**request, "script": "danger"})
        request["changes"] *= 2
        with self.assertRaises(contracts.CommandError):
            contracts.validate_request("update", request)


if __name__ == "__main__":
    unittest.main()
