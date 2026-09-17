"""Portable adapter contract tests; no applications, compiler or clipboard used."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts"
spec = importlib.util.spec_from_file_location("omnigraffle_latexit", SCRIPTS / "latexit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
LatexitAdapter, AdapterError = module.LatexitAdapter, module.AdapterError


class LatexitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.document = self.root / 'quote " $(touch nope).graffle'
        self.document.write_bytes(b"native fixture owned by caller")
        self.adapter = LatexitAdapter(runtime_dir=self.root)
        self.equation = {"source": "x^2+1", "preamble": "\\documentclass{article}", "mode": "display", "font_size": 12}

    def request(self, op="equation-render"):
        return dict(op=op, equation=dict(self.equation), output_dir=str(self.root / "output"), path=str(self.document), canvas_id=1, object_id=5, key="equation-1", x=12, y=24)

    def ready(self):
        return {"unlocked": True, "accessibility": True, "composition_profile": {"status": "safe"}, "apps": [{"bundle_id": "com.omnigroup.OmniGraffle7", "path": self.adapter.omni_app, "pid": 123}, {"bundle_id": "fr.chachatelier.pierre.LaTeXiT", "path": self.adapter.latexit_app, "pid": 234}]}

    def test_unknown_operation_rejected_before_tools(self):
        with patch.object(self.adapter, "_helper") as helper:
            self.assertEqual(self.adapter.call({"op": "eval", "script": "danger"})["code"], "invalid_request")
            helper.assert_not_called()

    def test_equation_types_bounds(self):
        for key, value in (("source", "x\0y"), ("source", "中" * 30000), ("preamble", []), ("mode", "shell"), ("font_size", float("nan")), ("font_size", True), ("font_size", 257)):
            with self.subTest(key=key, value=str(value)[:30]):
                r = self.request()
                r["equation"][key] = value
                with self.assertRaises(AdapterError):
                    self.adapter._validate(r)

    def test_native_identity_and_coordinate_validation(self):
        for key, value in (("canvas_id", "1"), ("canvas_id", True), ("x", float("inf")), ("y", "1"), ("key", "")):
            with self.subTest(key=key):
                r = self.request("equation-insert")
                r[key] = value
                with self.assertRaises(AdapterError):
                    self.adapter._validate(r)

    def test_existing_output_rejected(self):
        (self.root / "output").mkdir()
        with self.assertRaises(AdapterError):
            self.adapter._validate(self.request())

    def test_source_does_not_require_render_fields(self):
        r = self.adapter._validate(dict(op="equation-source", path=str(self.document), canvas_id=1, object_id=5))
        self.assertNotIn("equation", r)

    def test_labels_and_paths_are_json_data(self):
        r = self.request("equation-insert")
        r["key"] = '" & do shell script "touch /tmp/bad"'
        with patch.object(self.adapter, "_run", return_value={"status": "ok"}) as run:
            self.adapter._script("paste", r, self.root, mutation=True)
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["/usr/bin/osascript", str(SCRIPTS / "latexit.applescript")])
        self.assertNotIn(r["key"], args)
        self.assertEqual(json.loads(Path(args[-1]).read_text()), r)
        self.assertEqual(Path(args[-1]).stat().st_mode & 0o777, 0o600)

    def test_timeout_never_retries_mutation(self):
        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired("osascript", 30)) as run:
            with self.assertRaises(AdapterError) as raised:
                self.adapter._run(["fixed"], mutation=True)
        self.assertEqual(raised.exception.code, "outcome_unknown")
        self.assertEqual(run.call_count, 1)

    def test_read_timeout_distinguished(self):
        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired("osascript", 30)):
            with self.assertRaises(AdapterError) as raised:
                self.adapter._run(["fixed"])
        self.assertEqual(raised.exception.code, "timeout")

    def test_stderr_is_not_exposed(self):
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "PRIVATE TEX SOURCE")):
            with self.assertRaises(AdapterError) as raised:
                self.adapter._run(["fixed"], mutation=True)
        self.assertNotIn("PRIVATE", str(raised.exception))

    def test_locked_or_untrusted_stops_before_gui(self):
        for key in ("unlocked", "accessibility"):
            readiness = self.ready()
            readiness[key] = False
            with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", return_value=readiness), patch.object(self.adapter, "_script") as script:
                self.assertEqual(self.adapter.call(self.request())["code"], "desktop_unavailable")
                script.assert_not_called()

    def test_duplicate_or_wrong_app_stops_before_gui(self):
        for wrong in (False, True):
            readiness = self.ready()
            if wrong:
                readiness["apps"][1]["path"] = "/Applications/Other.app"
            else:
                readiness["apps"].append(readiness["apps"][1])
            with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", return_value=readiness), patch.object(self.adapter, "_script") as script:
                self.assertEqual(self.adapter.call(self.request())["code"], "application_identity")
                script.assert_not_called()

    def test_source_operation_closes_only_owned_editor(self):
        replies = [{"status": "ok"}, {"editor_title": "Equation linked with another application"}, {"status": "ok", "equation": self.equation}, {"status": "ok"}]
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", return_value=self.ready()), patch.object(self.adapter, "_script", side_effect=replies) as script:
            result = self.adapter.call(self.request("equation-source"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual([c.args[0] for c in script.call_args_list], ["preflight", "begin", "read", "close"])

    def test_linked_preamble_change_stops_before_render_and_closes_owned_editor(self):
        previous = {**self.equation, "preamble": "\\documentclass{standalone}"}
        replies = [{}, {"editor_title": "Equation linked with another application"}, {"status": "ok", "equation": previous}, {}]
        runs = [self.ready(), {"change_count": 19}, {"status": "restored"}]
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=runs), patch.object(self.adapter, "_script", side_effect=replies) as script:
            result = self.adapter.call(self.request("equation-update"))
        self.assertEqual(result["code"], "protected_preamble")
        self.assertEqual([c.args[0] for c in script.call_args_list], ["preflight", "begin", "read", "close"])

    def test_failed_begin_is_not_closed_or_retried(self):
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=[self.ready(), {"change_count": 19}, {"status": "restored"}]), patch.object(self.adapter, "_script", side_effect=[{}, AdapterError("outcome_unknown", "timeout")]) as script:
            result = self.adapter.call(self.request())
        self.assertEqual(result["code"], "outcome_unknown")
        self.assertEqual([c.args[0] for c in script.call_args_list], ["preflight", "begin"])

    def test_render_timeout_does_not_close_active_editor(self):
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=[self.ready(), {"change_count": 19}, self.ready(), {"status": "restored"}]), patch.object(self.adapter, "_script", side_effect=[{}, {"editor_title": "LaTeXiT-1"}, AdapterError("outcome_unknown", "timeout")]) as script:
            result = self.adapter.call(self.request())
        self.assertEqual(result["code"], "outcome_unknown")
        self.assertIn("editor_outcome_unknown_left_open_for_reconciliation", result["warnings"])
        self.assertEqual(script.call_count, 3)

    def test_invalid_tex_never_copies_or_pastes(self):
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=[self.ready(), {"change_count": 19}, self.ready(), {"status": "restored"}]), patch.object(self.adapter, "_script", side_effect=[{}, {"editor_title": "LaTeXiT-1"}, {"status": "invalid_tex", "change_count": 20}, {}]) as script:
            result = self.adapter.call(self.request("equation-insert"))
        self.assertEqual(result["code"], "invalid_tex")
        self.assertEqual([c.args[0] for c in script.call_args_list], ["preflight", "begin", "render", "close"])

    def test_render_capture_and_clipboard_restore(self):
        scripts = [{}, {"editor_title": "LaTeXiT-1"}, {"status": "ok", "equation": self.equation, "change_count": 20}, {"change_count": 21}, {}]
        runs = [self.ready(), {"change_count": 19}, self.ready(), {"status": "captured", "change_count": 21}, {"status": "restored"}]
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=runs) as run, patch.object(self.adapter, "_script", side_effect=scripts):
            result = self.adapter.call(self.request())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(run.call_args_list[-1].args[0][-1], "21")
        self.assertEqual([c.args[0][1] for c in run.call_args_list], ["readiness", "snapshot", "readiness", "capture", "restore"])
        self.assertEqual(result["warnings"], [])

    def test_new_equation_import_is_private_and_preserves_requested_tex(self):
        scripts = [{}, {"editor_title": "equation"}, {"status": "ok", "equation": self.equation, "change_count": 19}, {"change_count": 20}, {}]
        runs = [self.ready(), {"change_count": 19}, self.ready(), {"status": "captured", "change_count": 20}, {"status": "restored"}]
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=runs), patch.object(self.adapter, "_script", side_effect=scripts) as script:
            result = self.adapter.call(self.request())
        self.assertEqual(result["status"], "ok")
        tex = Path(script.call_args_list[1].args[1]["tex_input"])
        self.assertEqual(tex.stat().st_mode & 0o777, 0o600)
        self.assertEqual(tex.read_text(), self.equation["preamble"] + "\n\\begin{document}\n" + self.equation["source"] + "\n\\end{document}\n")

    def test_capture_failure_still_restores_clipboard(self):
        scripts = [{}, {"editor_title": "LaTeXiT-1"}, {"status": "ok", "equation": self.equation, "change_count": 20}, {"change_count": 21}, {}]
        runs = [self.ready(), {"change_count": 19}, self.ready(), AdapterError("native_error", "capture failed"), {"status": "restored"}]
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=runs) as run, patch.object(self.adapter, "_script", side_effect=scripts):
            result = self.adapter.call(self.request())
        self.assertEqual(result["code"], "native_error")
        self.assertEqual(run.call_args_list[-1].args[0][1], "restore")

    def test_unavailable_legacy_alias_warning_keeps_clipboard_restore(self):
        scripts = [{}, {"editor_title": "LaTeXiT-1"}, {"status": "ok", "equation": self.equation, "change_count": 20}, {"change_count": 21}, {}]
        runs = [self.ready(), {"change_count": 19, "unavailable_legacy_text_aliases": 1}, self.ready(), {"status": "captured", "change_count": 21}, {"status": "restored"}]
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", side_effect=runs) as run, patch.object(self.adapter, "_script", side_effect=scripts):
            result = self.adapter.call(self.request())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(run.call_args_list[-1].args[0][1], "restore")
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("unavailable legacy text alias", result["warnings"][0])

    def test_shared_deadline_decreases_between_phases(self):
        self.adapter._deadline = 100
        with patch.object(module.time, "monotonic", side_effect=[70, 80]), patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"status":"ok"}', "")) as run:
            self.adapter._run(["first"])
            self.adapter._run(["second"])
        self.assertEqual([c.kwargs["timeout"] for c in run.call_args_list], [30, 20])

    def test_exhausted_deadline_does_not_start_process(self):
        self.adapter._deadline = 100
        with patch.object(module.time, "monotonic", return_value=101), patch.object(module.subprocess, "run") as run:
            with self.assertRaises(AdapterError):
                self.adapter._run(["mutation"], mutation=True)
        run.assert_not_called()

    def test_close_failure_cannot_report_success(self):
        replies = [{}, {"editor_title": "linked"}, {"status": "ok", "equation": self.equation}, AdapterError("outcome_unknown", "close timed out")]
        with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", return_value=self.ready()), patch.object(self.adapter, "_script", side_effect=replies):
            result = self.adapter.call(self.request("equation-source"))
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["outcome_unknown"])

    def test_unsafe_profile_rejected_before_gui(self):
        for profile in ({}, {"status": "unsafe"}, {"status": "unavailable"}):
            ready = self.ready()
            ready["composition_profile"] = profile
            with patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", return_value=ready), patch.object(self.adapter, "_script") as script:
                result = self.adapter.call(self.request())
            self.assertEqual(result["code"], "unsafe_composition_profile")
            script.assert_not_called()

    def test_cleanup_has_one_five_second_allowance(self):
        observed = []
        def script(phase, *_args, **_kwargs):
            if phase == "begin":
                return {"editor_title": "linked"}
            if phase == "read":
                return {"status": "ok", "equation": self.equation}
            if phase == "close":
                observed.append(self.adapter._deadline)
            return {}
        with patch.object(module.time, "monotonic", side_effect=[100, 129]), patch.object(self.adapter, "_helper", return_value="helper"), patch.object(self.adapter, "_run", return_value=self.ready()), patch.object(self.adapter, "_script", side_effect=script):
            result = self.adapter.call(self.request("equation-source"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(observed, [134])
        self.assertIsNone(self.adapter._deadline)

    def test_zero_exit_error_response_is_not_success(self):
        for response in ({"status": "error"}, {"status": "restore_failed"}, {}, []):
            with self.subTest(response=response), patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")):
                with self.assertRaises(AdapterError) as raised:
                    self.adapter._run(["fixed"], mutation=True)
                self.assertEqual(raised.exception.code, "outcome_unknown")

    def test_close_phase_requires_its_own_success_status(self):
        with patch.object(self.adapter, "_run", return_value={"status": "invalid_tex"}):
            with self.assertRaises(AdapterError) as raised:
                self.adapter._script("close", self.request(), self.root, mutation=True)
        self.assertEqual(raised.exception.code, "outcome_unknown")

    def test_ax_collections_materialized_before_iteration(self):
        # Regression for live System Events -1700: direct entire-contents iteration
        # produces unevaluated item specifiers rather than the returned AX objects.
        source = (SCRIPTS / "latexit.applescript").read_text()
        self.assertNotRegex(source, r"repeat with \w+ in entire contents")
        self.assertIn("set elementsList to entire contents of w", source)
        self.assertIn("set w to my editor(p, expectedTitle)", source)

    def test_only_verified_clipboard_change_can_skip_restore(self):
        safe = {"status": "restore_skipped", "reason": "clipboard_changed"}
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 3, json.dumps(safe), "")):
            self.assertEqual(self.adapter._run(["helper", "restore", "backup", "20"], mutation=True), safe)
            with self.assertRaises(AdapterError):
                self.adapter._run(["helper", "capture", "output", "20"], mutation=True)

    def test_diagnostics_are_private_bounded_and_not_in_error(self):
        self.adapter._operation_dir = self.root
        message = "PRIVATE source " + "x" * 70000
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", message)):
            with self.assertRaises(AdapterError) as raised:
                self.adapter._run(["/usr/bin/osascript", "fixed.applescript", "render", "data.json"], mutation=True)
        self.assertNotIn("PRIVATE", str(raised.exception))
        path = Path(self.adapter._diagnostic_paths[0])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        record = json.loads(path.read_text())
        self.assertEqual(record["phase"], "render")
        self.assertEqual(len(record["stderr"].encode()), 65536)
        self.assertTrue(record["truncated"])

    def test_timeout_retains_private_native_diagnostics(self):
        self.adapter._operation_dir = self.root
        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired("osascript", 30, stderr=b"timed out native event")):
            with self.assertRaises(AdapterError):
                self.adapter._run(["fixed"], mutation=True)
        self.assertEqual(json.loads(Path(self.adapter._diagnostic_paths[0]).read_text())["returncode"], "timeout")

    def test_render_controls_do_not_assume_direct_window_children(self):
        source = (SCRIPTS / "latexit.applescript").read_text()
        self.assertNotIn('button "LaTeX it!" of w', source)
        self.assertIn('my namedButton(w, "LaTeX it!")', source)
        render = source[source.index('if phase is "render" then'):source.index('if phase is "copy" then')]
        self.assertLess(render.index("click item 1 of modeControls"), render.index('my field(eq, "preamble")'))

    def test_only_stale_ax_reads_are_refreshed_after_render(self):
        source = (SCRIPTS / "latexit.applescript").read_text()
        polling = source[source.index("repeat 100 times"):source.index('if not renderIdle then error')]
        self.assertIn("if errorNumber is not -1728 then error errorMessage number errorNumber", polling)
        self.assertNotIn("click ", polling)

    def test_unicode_tex_targets_accessible_value_without_keyboard_or_clipboard(self):
        source = (SCRIPTS / "latexit.applescript").read_text()
        entry = source[source.index("on setEditorText("):source.index("end setEditorText")]
        self.assertIn('set value of attribute "AXSelectedText" of areaValue to textValue', entry)
        self.assertNotIn("keystroke textValue", entry)
        self.assertNotIn("clearContents", entry)

    def test_text_entry_verifies_target_focus_and_readback_including_empty_text(self):
        source = (SCRIPTS / "latexit.applescript").read_text()
        entry = source[source.index("on setEditorText("):source.index("end setEditorText")]
        self.assertLess(entry.index('error "Equation text focus unavailable"'), entry.index('set value of attribute "AXSelectedText"'))
        self.assertIn('if actualText is not textValue then error', entry)

    def test_font_scalar_edit_commits_before_source_paste(self):
        source = (SCRIPTS / "latexit.applescript").read_text()
        render = source[source.index('if phase is "render" then'):source.index('if phase is "copy" then')]
        self.assertLess(render.index('error "Font field focus unavailable"'), render.index('set value of item 1 of fontControls'))
        self.assertLess(render.index('set value of item 1 of fontControls'), render.index("key code 48"))
        self.assertLess(render.index("key code 48"), render.index("my setEditorText("))


if __name__ == "__main__":
    unittest.main()
