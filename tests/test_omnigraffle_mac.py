"""Opt-in licensed-Mac acceptance. Never installs dependencies or grants access.

OMNIGRAFFLE_MAC_INTEGRATION=1 enables native tests on an unlocked, prepared Mac.
OMNIGRAFFLE_MAC_EQUATIONS=1 additionally enables real stock-LaTeXiT callbacks.
OMNIGRAFFLE_MAC_RESTART_APPS=1 explicitly permits guarded application restarts.
Artifacts and receipts are retained even on failure for inspection/reconciliation.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts"
CLI = SCRIPTS / "omnigraffle.py"
NATIVE_ENABLED = platform.system() == "Darwin" and os.environ.get("OMNIGRAFFLE_MAC_INTEGRATION") == "1"
EQUATIONS_ENABLED = os.environ.get("OMNIGRAFFLE_MAC_EQUATIONS") == "1"


@unittest.skipUnless(NATIVE_ENABLED, "Requires macOS and explicit OMNIGRAFFLE_MAC_INTEGRATION=1; licensed OmniGraffle must already be running")
class LicensedMacAcceptance(unittest.TestCase):
    def setUp(self):
        # Do not remove evidence or working copies if an operation times out.
        self.root = Path(tempfile.mkdtemp(prefix="omnigraffle-mac-acceptance-"))
        self.state = self.root / "receipts"
        self.calls = []
        print(f"\nOmniGraffle acceptance evidence: {self.root}", flush=True)

    def cli(self, command, request=None, *args):
        argv = [sys.executable, str(CLI), "--state-dir", str(self.state), "--timeout", "120", command]
        if request is not None:
            request = {"operation_id": str(uuid.uuid4()), **request}
            path = self.root / (request["operation_id"] + ".request.json")
            path.write_text(json.dumps(request, ensure_ascii=False))
            os.chmod(path, 0o600)
            argv += ["--request", str(path)]
        argv += list(map(str, args))
        result = subprocess.run(argv, capture_output=True, text=True, timeout=150)
        self.calls.append({"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        (self.root / "cli-results.json").write_text(json.dumps(self.calls, ensure_ascii=False, indent=2))
        self.assertEqual(result.returncode, 0, f"{command}: {result.stdout}\n{result.stderr}; inspect evidence; do not retry unknown mutations")
        return json.loads(result.stdout)

    @staticmethod
    def fingerprint(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def existing(self, path, **fields):
        return {"input": str(path), "expected_sha256": self.fingerprint(path), **fields}

    def create(self):
        path = self.root / "created.graffle"
        self.cli("create", {"output": str(path), "spec": {"canvases": [
            {"key": "main", "name": "Workflow / 工作流", "width": 480, "height": 240, "objects": [
                {"key": "input", "kind": "shape", "x": 30, "y": 50, "width": 120, "height": 50, "text": "Input / 输入", "font_size": 16},
                {"key": "output", "kind": "shape", "x": 300, "y": 50, "width": 120, "height": 50, "text": "Output / 输出", "font_size": 16},
                {"key": "edge", "kind": "connector", "from": "input", "to": "output"},
                {"key": "caption", "kind": "text", "x": 30, "y": 160, "width": 180, "height": 40, "text": "Editable / 可编辑", "font_size": 16}]},
            {"key": "detail", "name": "Grouped detail", "width": 320, "height": 180, "objects": [
                {"key": "left", "kind": "shape", "x": 20, "y": 20, "width": 80, "height": 40, "text": "A"},
                {"key": "right", "kind": "shape", "x": 180, "y": 20, "width": 80, "height": 40, "text": "B"},
                {"key": "pair", "kind": "group", "children": ["left", "right"]}]}]}})
        return path

    def inspect(self, path):
        return self.cli("inspect", None, path)

    def test_native_multicanvas_groups_update_and_canvas_exports(self):
        path = self.create()
        before = self.inspect(path)
        self.assertEqual(len(before["canvases"]), 2)
        main = next(c for c in before["canvases"] if c["title"] == "Workflow / 工作流")
        target = next(o for o in main["objects"] if o.get("name") == "caption")
        output = self.root / "updated.graffle"
        result = self.cli("update", self.existing(path, output=str(output), changes=[{"canvas_id": main["id"], "object_id": target["id"], "set": {"text": "Revised / 已修改"}}]))
        self.assertEqual(result["result"]["verification"]["unrelated_objects"], "verified")
        # The update opens a saved copy, so this catches attributes that existed
        # only on transient text objects and disappeared after save/reopen.
        native_main = next(c for c in result["result"]["native_document"]["canvases"] if c["id"] == main["id"])
        for obj in native_main["objects"]:
            if obj["name"] in ("input", "output", "caption"):
                self.assertEqual(obj["font_size"], 16)
        self.assertEqual(self.fingerprint(path), before["file_sha256"])
        after = self.inspect(output)
        original = {(c["id"], o["id"]): o for c in before["canvases"] for o in c["objects"]}
        revised = {(c["id"], o["id"]): o for c in after["canvases"] for o in c["objects"]}
        self.assertEqual(set(original), set(revised))
        self.assertNotEqual(original[main["id"], target["id"]]["structural_sha256"], revised[main["id"], target["id"]]["structural_sha256"])
        for fmt in ("PDF", "PNG"):
            export = self.root / ("canvas." + fmt.lower())
            exported = self.cli("export", self.existing(output, output=str(export), scope="canvas", canvas_id=main["id"], format=fmt, dpi=72))
            self.assertTrue(export.is_file())
            verification = exported["result"]["verification"]
            if fmt == "PNG":
                self.assertEqual(verification["pixel_dimensions"], [480, 240])
            self.assertEqual(verification["visual_check"], "required")
        # Automated signatures/dimensions are not a visual inspection.
        (self.root / "VISUAL-REVIEW-REQUIRED.txt").write_text("Inspect canvas.pdf and canvas.png for bilingual glyphs, clipping, geometry and final reading size. This suite does not claim visual acceptance.\n")

    @unittest.skipUnless(EQUATIONS_ENABLED, "Requires OMNIGRAFFLE_MAC_EQUATIONS=1, running official LaTeXiT, prepared TeX profile and existing GUI permissions")
    def test_actual_linkback_insert_two_updates_and_optional_restart(self):
        path = self.create()
        report = self.inspect(path)
        canvas_id = report["canvases"][0]["id"]
        equation = {"source": "x^2+1", "preamble": "\\documentclass[10pt]{article}\n\\usepackage{amsmath}\n\\pagestyle{empty}", "mode": "display", "font_size": 16}
        output = self.root / "equation-0.graffle"
        self.cli("equation-insert", self.existing(path, output=str(output), canvas_id=canvas_id, key="acceptance-equation", x=240, y=160, equation=equation))
        inspected = self.inspect(output)
        obj = next(o for c in inspected["canvases"] if c["id"] == canvas_id for o in c["objects"] if o.get("name") == "acceptance-equation")
        object_id = obj["id"]
        self.assertEqual(obj["linkback"]["owner"]["bundle_id"], "fr.chachatelier.pierre.LaTeXiT")
        for iteration in (1, 2):
            equation = {**equation, "source": f"x^2+{iteration + 1}"}
            next_output = self.root / f"equation-{iteration}.graffle"
            result = self.cli("equation-update", self.existing(output, output=str(next_output), canvas_id=canvas_id, object_id=object_id, equation=equation))
            self.assertEqual(result["result"]["verification"]["unrelated_objects"], "verified")
            output = next_output
            readback = self.cli("equation-source", self.existing(output, canvas_id=canvas_id, object_id=object_id))
            self.assertEqual({k: readback["result"]["equations"][0][k] for k in equation}, equation)
        if os.environ.get("OMNIGRAFFLE_MAC_RESTART_APPS") != "1":
            (self.root / "RESTART-NOT-TESTED.txt").write_text("Both application restart acceptance requires explicit OMNIGRAFFLE_MAC_RESTART_APPS=1. Two update/save/reopen cycles passed; restart acceptance is not claimed.\n")
        else:
            self.restart_idle_applications()
            equation = {**equation, "source": "x^2+4"}
            final = self.root / "equation-after-restart.graffle"
            self.cli("equation-update", self.existing(output, output=str(final), canvas_id=canvas_id, object_id=object_id, equation=equation))
            readback = self.cli("equation-source", self.existing(final, canvas_id=canvas_id, object_id=object_id))
            self.assertEqual({k: readback["result"]["equations"][0][k] for k in equation}, equation)
            output = final
        for fmt in ("PDF", "PNG"):
            self.cli("export", self.existing(output, output=str(self.root / ("equation-final." + fmt.lower())),
                     scope="canvas", canvas_id=canvas_id, format=fmt, dpi=72))
        (self.root / "VISUAL-REVIEW-REQUIRED.txt").write_text("Inspect equation-final.pdf and equation-final.png for the final equation, baseline, bilingual glyphs and clipping.\n")

    def restart_idle_applications(self):
        # Explicit restart flag is additional authorization; no forced quit,
        # discard, preference writes, or closure of unrelated windows is allowed.
        sys.path.insert(0, str(SCRIPTS))
        try:
            from transactions import Store
            from engine import app_processes
        finally:
            sys.path.pop(0)
        store = Store(self.state)
        with store.locked():
            self.assertFalse((store.guard / "pending.json").exists(), "Reconcile pending operation before restarting apps")
            old_processes = app_processes()
            self.assertEqual(len(old_processes), 2, "Expected exactly one instance of each application")
            old_pids = {p["pid"] for p in old_processes}
            script = '''tell application "/Applications/OmniGraffle.app"
if (count documents) is not 0 then error "Refusing restart: OmniGraffle has open documents"
end tell
tell application "System Events"
repeat with bid in {"com.omnigroup.OmniGraffle7", "fr.chachatelier.pierre.LaTeXiT"}
set ps to every process whose bundle identifier is bid
if (count ps) is not 1 then error "Refusing restart: ambiguous application"
if (count windows of item 1 of ps) is not 0 then error "Refusing restart: application has windows"
end repeat
end tell
tell application "/Applications/LaTeXiT.app" to quit
tell application "/Applications/OmniGraffle.app" to quit
'''
            result = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            deadline = time.monotonic() + 10
            while old_pids & {p["pid"] for p in app_processes()} and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertFalse(old_pids & {p["pid"] for p in app_processes()}, "Normal quit did not finish; no force quit attempted")
            for app in ("/Applications/OmniGraffle.app", "/Applications/LaTeXiT.app"):
                subprocess.run(["/usr/bin/open", "-a", app], check=True, timeout=10)
            deadline = time.monotonic() + 10
            restarted = app_processes()
            while len(restarted) != 2 and time.monotonic() < deadline:
                time.sleep(0.25)
                restarted = app_processes()
            self.assertEqual(len(restarted), 2)
            self.assertFalse(old_pids & {p["pid"] for p in restarted})
            self.close_empty_startup_windows(restarted)

    def close_empty_startup_windows(self, processes):
        """Only a just-launched, PID-matched blank may be closed normally.

        Restored content, user input, a modification indicator, a preview, a
        dialog or an unknown title stops acceptance. A normal close never
        dismisses save prompts when LaTeXiT omits its AXEdited attribute.
        """
        pids = {p["bundle_id"]: p["pid"] for p in processes}
        script = '''on run argv
set omniPID to item 1 of argv as integer
set latexPID to item 2 of argv as integer
tell application "System Events"
set ops to every process whose unix id is omniPID
set lps to every process whose unix id is latexPID
if (count ops) is not 1 or (count lps) is not 1 then error "Startup process changed"
if bundle identifier of item 1 of ops is not "com.omnigroup.OmniGraffle7" then error "Wrong OmniGraffle process"
if bundle identifier of item 1 of lps is not "fr.chachatelier.pierre.LaTeXiT" then error "Wrong LaTeXiT process"
end tell
tell application "/Applications/OmniGraffle.app"
if (count documents) > 1 then error "Restored or unrelated documents present"
if (count documents) is 1 then
set d to document 1
if modified of d then error "Startup document modified"
try
set docPath to path of d
if docPath is not missing value and docPath is not "" then error "Startup document has saved path"
on error msg number num
if num is not -2753 then error msg number num
end try
if name of d does not start with "Untitled" then error "Unknown startup document"
if (count canvases of d) is not 1 then error "Startup document has multiple canvases"
if (count graphics of canvas 1 of d) is not 0 then error "Startup document has graphics"
close d saving no
end if
if (count documents) is not 0 then error "Startup document remained open"
end tell
tell application "System Events"
set lp to item 1 of lps
if (count windows of lp) > 1 then error "Restored or unrelated LaTeXiT windows present"
if (count windows of lp) is 1 then
set w to window 1 of lp
if name of w is not "LaTeXiT-1" and name of w is not "LaTeXiT-2" then error "Unknown startup equation window"
if (count sheets of w) is not 0 then error "Startup equation has a dialog"
if exists attribute "AXEdited" of w then
if value of attribute "AXEdited" of w is not false then error "Startup equation modified"
end if
set areas to {}
set previews to {}
set startupElements to entire contents of w
repeat with el in startupElements
if class of el is text area then set end of areas to contents of el
if class of el is slider then set end of previews to contents of el
end repeat
if (count areas) < 1 or (count areas) > 2 then error "Cannot identify startup equation body"
if value of last item of areas is not "" then error "Startup equation contains source"
if (count previews) is not 1 then error "Cannot identify startup preview"
if enabled of item 1 of previews then error "Startup equation has a rendered preview"
set closeButtons to every button of w whose subrole is "AXCloseButton"
if (count closeButtons) is not 1 then error "Cannot identify startup close button"
click item 1 of closeButtons
end if
if (count windows of lp) is not 0 then error "LaTeXiT startup editor did not close; leave any save prompt for inspection"
end tell
end run'''
        result = subprocess.run(["/usr/bin/osascript", "-e", script, str(pids["com.omnigroup.OmniGraffle7"]), str(pids["fr.chachatelier.pierre.LaTeXiT"])], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, f"Refused startup cleanup: {result.stderr}; inspect remaining window manually")


if __name__ == "__main__":
    unittest.main()
