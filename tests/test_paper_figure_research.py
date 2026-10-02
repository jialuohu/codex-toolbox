"""Research-figure data and independent-regeneration contracts."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/diagram-tools/skills/paper-figure-workflow"
PLOTS = SKILL / "assets/research-figure-starter/figures_src/plots"
sys.path.insert(0, str(PLOTS))
import figure_common as common  # noqa: E402
import grouped_bars  # noqa: E402
import line_scaling  # noqa: E402
import empirical_cdf  # noqa: E402
import stacked_breakdown  # noqa: E402


def example(name: str) -> dict:
    return json.loads((PLOTS / "data" / name).read_text(encoding="utf-8"))


class DataContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapping = common.load_method_styles()

    def test_reordered_and_missing_methods_keep_fixed_order_and_style(self) -> None:
        records = example("grouped-bars.json")["series"]
        expected = ["Baseline", "Ablation", "Proposed"]
        self.assertEqual([entry["method"] for entry in common.ordered_series(records, self.mapping)], expected)
        self.assertEqual([entry["method"] for entry in common.ordered_series(list(reversed(records)), self.mapping)], expected)
        missing = [entry for entry in records if entry["method"] != "Ablation"]
        self.assertEqual([entry["method"] for entry in common.ordered_series(missing, self.mapping)],
                         ["Baseline", "Proposed"])
        self.assertEqual(self.mapping["styles"]["Proposed"]["color"], "#2148B8")
        unknown = copy.deepcopy(records)
        unknown[0]["method"] = "Unregistered"
        with self.assertRaisesRegex(common.FigureDataError, "add a distinct encoding"):
            common.ordered_series(unknown, self.mapping)

    def test_gray_scale_channels_and_component_styles_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            mapping = copy.deepcopy(self.mapping)
            mapping["styles"]["Ablation"]["hatch"] = mapping["styles"]["Baseline"]["hatch"]
            (path / "method_styles.json").write_text(json.dumps(mapping), encoding="utf-8")
            with mock.patch.object(common, "HERE", path):
                with self.assertRaisesRegex(common.FigureDataError, "grayscale"):
                    common.load_method_styles()
            mapping = copy.deepcopy(self.mapping)
            mapping["component_styles"].pop("Queue")
            (path / "method_styles.json").write_text(json.dumps(mapping), encoding="utf-8")
            with mock.patch.object(common, "HERE", path):
                with self.assertRaisesRegex(common.FigureDataError, "map components exactly"):
                    common.load_method_styles()

    def test_conflicting_units_and_uncertainty_bounds_fail(self) -> None:
        data = example("grouped-bars.json")
        data["series"][0]["unit"] = "s"
        with self.assertRaisesRegex(common.FigureDataError, "incompatible units"):
            grouped_bars.validate(data, self.mapping)
        data = example("grouped-bars.json")
        data["series"][0]["uncertainty"]["lower"][0] = 99
        with self.assertRaisesRegex(common.FigureDataError, "bounds do not contain"):
            grouped_bars.validate(data, self.mapping)
        data = example("grouped-bars.json")
        data["series"][0]["uncertainty"]["lower"][0] = -1
        data["y_min"] = 0
        with self.assertRaisesRegex(common.FigureDataError, "uncertainty bound"):
            grouped_bars.validate(data, self.mapping)

    def test_confidence_interval_requires_confidence_level_and_sample_count(self) -> None:
        data = example("grouped-bars.json")
        uncertainty = data["series"][0]["uncertainty"]
        uncertainty["interval_type"] = "confidence_interval"
        with self.assertRaisesRegex(common.FigureDataError, "confidence_level"):
            grouped_bars.validate(data, self.mapping)
        uncertainty["confidence_level"] = 0.95
        uncertainty["n"] = 0
        with self.assertRaisesRegex(common.FigureDataError, "sample count"):
            grouped_bars.validate(data, self.mapping)
        uncertainty["n"] = 20
        grouped_bars.validate(data, self.mapping)

    def test_missing_line_values_remain_gaps_and_units_are_checked(self) -> None:
        data = example("line-scaling.json")
        prepared = line_scaling.validate(data, self.mapping)
        median = prepared[3][0][1]
        baseline = next(values for name, values in median if name == "Baseline")
        self.assertIsNone(baseline[2])
        self.assertEqual(baseline[3], 95)
        data["panels"][0]["series"][0]["unit"] = "s"
        with self.assertRaisesRegex(common.FigureDataError, "incompatible units"):
            line_scaling.validate(data, self.mapping)
        data = example("line-scaling.json")
        data.pop("between_samples")
        with self.assertRaisesRegex(common.FigureDataError, "explicit"):
            line_scaling.validate(data, self.mapping)

    def test_empirical_distribution_preserves_ties_and_raw_sample_semantics(self) -> None:
        self.assertEqual(empirical_cdf.empirical_cdf([2, 1, 2, 3]),
                         [(1.0, 0.25), (2.0, 0.75), (3.0, 1.0)])
        self.assertEqual(empirical_cdf.nearest_rank([1, 2, 2, 3], 50), 2)
        data = example("empirical-cdf.json")
        data["series"][0]["unit"] = "s"
        with self.assertRaisesRegex(common.FigureDataError, "incompatible units"):
            empirical_cdf.validate(data, self.mapping)
        data = example("empirical-cdf.json")
        data.pop("percentile_method")
        with self.assertRaisesRegex(common.FigureDataError, "explicit"):
            empirical_cdf.validate(data, self.mapping)

    def test_incomplete_stack_and_implicit_interpolation_fail(self) -> None:
        data = example("breakdown-area.json")
        data["components"][0]["values"].pop()
        with self.assertRaisesRegex(common.FigureDataError, "exactly 5 entries"):
            stacked_breakdown.validate(data, self.mapping)
        data = example("breakdown-area.json")
        data.pop("between_samples")
        with self.assertRaisesRegex(common.FigureDataError, "explicit"):
            stacked_breakdown.validate(data, self.mapping)
        data = example("breakdown-bars.json")
        data["components"][0]["unit"] = "s"
        with self.assertRaisesRegex(common.FigureDataError, "incompatible units"):
            stacked_breakdown.validate(data, self.mapping)

    def test_width_override_is_mutually_exclusive_and_positive(self) -> None:
        script = PLOTS / "grouped_bars.py"
        base = [sys.executable, str(script), "--data", str(PLOTS / "data/grouped-bars.json"),
                "--out-dir", "/private/tmp/unused-paper-figure-test"]
        for suffix in (["--width", "single", "--width-in", "4"], ["--width-in", "0"],
                       ["--width-in", "nan"]):
            result = subprocess.run([*base, *suffix], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_nonfinite_verification_width_fails(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/verify_exports.py"
        result = subprocess.run([sys.executable, str(script), "--out-dir", "/private/tmp/unused",
                                 "--expect", "figure=nan"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive finite", result.stderr)


class OwnerResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location("research_owner", SKILL / "scripts/scaffold_research_figures.py")
        self.owner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.owner)

    def test_accepted_release_prefers_native_without_claiming_gui_access(self) -> None:
        self.assertTrue(self.owner.NATIVE_RESEARCH_PREFERENCE_ENABLED)
        paper = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("foreground Terminal", paper)
        self.assertIn("Drawing readiness checks do not establish equation GUI readiness", paper)
        self.assertNotIn("expanded preference remains inactive", paper)

    def test_pending_release_gate_does_not_probe_or_trust_project_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
                self.owner, "NATIVE_RESEARCH_PREFERENCE_ENABLED", False), mock.patch.object(
                self.owner, "native_readiness") as probe:
            project = Path(temporary)
            (project / "native-acceptance.json").write_text('{"release_accepted": true}', encoding="utf-8")
            self.assertEqual(self.owner.resolve_owner(project, "auto"),
                             ("drawio", "auto", "native_preference_pending_acceptance"))
            probe.assert_not_called()

    def test_explicit_sources_and_recorded_owners_never_probe_or_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
                self.owner, "NATIVE_RESEARCH_PREFERENCE_ENABLED", True), mock.patch.object(
                self.owner, "native_readiness") as probe:
            project = Path(temporary)
            self.assertEqual(self.owner.resolve_owner(project, "omnigraffle"),
                             ("omnigraffle", "explicit", "explicit_request"))
            source = project / "figures_src/diagrams"
            source.mkdir(parents=True)
            (source / "manual.graffle").write_bytes(b"preserved source")
            self.assertEqual(self.owner.resolve_owner(project, "auto"),
                             ("omnigraffle", "existing_source", "existing_native_source"))
            with self.assertRaisesRegex(ValueError, "conflicts with --diagram-owner"):
                self.owner.resolve_owner(project, "drawio")
            record = project / self.owner.OWNER_FILE
            record.write_text('{"schema_version": 1, "owner": "omnigraffle", "reason": "original_reason"}',
                              encoding="utf-8")
            original = record.read_bytes()
            self.assertEqual(self.owner.resolve_owner(project, "auto"),
                             ("omnigraffle", "recorded_project", "recorded_project_owner"))
            self.assertEqual(record.read_bytes(), original)
            (source / "manual.graffle").unlink()
            self.assertEqual(self.owner.resolve_owner(project, "auto")[0], "omnigraffle")
            (source / "other.drawio").write_bytes(b"different owner")
            with self.assertRaisesRegex(ValueError, "conflict with recorded"):
                self.owner.resolve_owner(project, "auto")
            probe.assert_not_called()

    def test_enabled_auto_uses_fresh_readiness_once_and_discloses_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
                self.owner, "NATIVE_RESEARCH_PREFERENCE_ENABLED", True), mock.patch.object(
                self.owner, "native_readiness", return_value=(True, "native_ready")) as probe:
            project = Path(temporary)
            plugin = project / "plugin"
            self.assertEqual(self.owner.resolve_owner(project, "auto", plugin),
                             ("omnigraffle", "auto", "native_ready"))
            probe.assert_called_once_with(plugin)
            probe.reset_mock()
            probe.return_value = (False, "omnigraffle_scripting_unavailable")
            self.assertEqual(self.owner.resolve_owner(project, "auto", plugin),
                             ("drawio", "auto", "omnigraffle_scripting_unavailable"))
            probe.assert_called_once_with(plugin)

    def test_native_readiness_requires_current_drawing_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
                self.owner.platform, "system", return_value="Darwin"), mock.patch.object(
                self.owner.subprocess, "run") as run:
            plugin = Path(temporary)
            runtime = plugin / "skills/omnigraffle-workflow/scripts/omnigraffle.py"
            runtime.parent.mkdir(parents=True)
            runtime.write_text("# mocked CLI", encoding="utf-8")
            report = {"schema_version": 1, "platform": "Darwin", "status": "blocked",
                      "release_accepted": False, "blockers": ["latexit_tex_dependencies_missing"],
                      "omnigraffle": {"status": "present"}, "scripting": {"status": "responding"},
                      "exports": {"status": "dictionary_inspected", "formats": {"PDF": {"advertised": True}}}}
            run.return_value = subprocess.CompletedProcess([], 2, json.dumps(report), "")
            self.assertEqual(self.owner.native_readiness(plugin), (True, "native_ready"))
            self.assertEqual(run.call_args.args[0][-2:], ["doctor", "--probe-app"])
            for key, value, reason in (
                    ("scripting", {"status": "not_probed"}, "omnigraffle_scripting_unavailable"),
                    ("omnigraffle", {"status": "unavailable"}, "omnigraffle_unavailable"),
                    ("exports", {"status": "dictionary_inspected", "formats": {"PDF": {"advertised": False}}},
                     "native_pdf_not_advertised"),
                    ("scripting", [], "native_readiness_invalid")):
                with self.subTest(key=key, reason=reason):
                    broken = copy.deepcopy(report)
                    broken[key] = value
                    run.return_value = subprocess.CompletedProcess([], 2, json.dumps(broken), "")
                    self.assertEqual(self.owner.native_readiness(plugin), (False, reason))
            run.side_effect = subprocess.TimeoutExpired([], 60)
            self.assertEqual(self.owner.native_readiness(plugin), (False, "native_readiness_timeout"))
            run.side_effect = OSError("unavailable")
            self.assertEqual(self.owner.native_readiness(plugin), (False, "native_readiness_unavailable"))
            run.side_effect = None
            run.return_value = subprocess.CompletedProcess([], 0, "malformed", "")
            self.assertEqual(self.owner.native_readiness(plugin), (False, "native_readiness_invalid"))
            run.reset_mock()
            with mock.patch.object(self.owner.platform, "system", return_value="Linux"):
                self.assertEqual(self.owner.native_readiness(plugin), (False, "macos_required"))
            run.assert_not_called()

    def test_malformed_recorded_owner_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            record = project / self.owner.OWNER_FILE
            record.parent.mkdir(parents=True)
            for content in ('{"schema_version": true, "owner": "omnigraffle"}',
                            '{"schema_version": 1, "owner": "unknown"}', '[]', '{'):
                with self.subTest(content=content):
                    record.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "invalid figures_src/diagram-owner.json"):
                        self.owner.resolve_owner(project, "auto")
                    self.assertEqual(record.read_text(encoding="utf-8"), content)


class ScaffoldTests(unittest.TestCase):
    def test_installed_plugin_layout_copies_diagrams_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "market/diagram-tools/0.6.0/skills/paper-figure-workflow"
            shutil.copytree(SKILL / "assets", skill / "assets")
            (skill / "scripts").mkdir(parents=True)
            shutil.copy2(SKILL / "scripts/scaffold_research_figures.py", skill / "scripts")
            templates = root / "market/drawio-tools/0.1.5/assets/research-templates"
            templates.mkdir(parents=True)
            (templates / "sample.drawio").write_text("<mxfile/>", encoding="utf-8")
            (templates / "README.md").write_text("Project-local provenance", encoding="utf-8")
            project = root / "paper"
            result = subprocess.run([sys.executable, str(skill / "scripts/scaffold_research_figures.py"),
                                     "--project", str(project)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((project / "figures_src/diagrams/sample.drawio").exists())
            self.assertTrue((project / "figures_src/diagrams/README.md").exists())
            owner_record = json.loads((project / "figures_src/diagram-owner.json").read_text())
            self.assertEqual(owner_record["owner"], "drawio")
            self.assertEqual(owner_record["selection"], "auto")
            self.assertTrue(owner_record["reason"])
            self.assertTrue((project / "figures_src/plots/figure_common.py").exists())
            self.assertFalse(any("import plugins." in path.read_text(encoding="utf-8")
                                 for path in (project / "figures_src/plots").glob("*.py")))

    def test_missing_diagram_templates_fail_unless_plots_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "market/diagram-tools/0.6.0/skills/paper-figure-workflow"
            shutil.copytree(SKILL / "assets", skill / "assets")
            (skill / "scripts").mkdir(parents=True)
            shutil.copy2(SKILL / "scripts/scaffold_research_figures.py", skill / "scripts")
            command = [sys.executable, str(skill / "scripts/scaffold_research_figures.py"),
                       "--project", str(root / "paper")]
            missing = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("--plots-only", missing.stderr)
            only = subprocess.run([*command, "--plots-only"], capture_output=True, text=True)
            self.assertEqual(only.returncode, 0, only.stderr)

    def test_selected_diagram_owner_requires_export_adapter(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/export_diagrams.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "diagrams"
            source.mkdir()
            (source / "example.mmd").write_text("flowchart LR\n A-->B\n", encoding="utf-8")
            environment = dict(os.environ, DIAGRAM_OWNER="pretty-mermaid", FIGURE_DIAGRAM_EXPORTER="")
            result = subprocess.run([sys.executable, str(script), "--source-dir", str(source),
                                     "--out-dir", str(root / "figures")], env=environment,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires FIGURE_DIAGRAM_EXPORTER", result.stderr)

    @unittest.skipUnless(shutil.which("make"), "make is required")
    def test_make_diagrams_uses_selected_native_sources_and_checks_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "paper"
            shutil.copytree(SKILL / "assets/research-figure-starter", project)
            source = project / "figures_src/diagrams"
            source.mkdir()
            (source / "overview.drawio").write_text("<mxfile/>", encoding="utf-8")
            fake = root / "fake-drawio"
            fake.write_text("#!/usr/bin/env python3\nimport pathlib, sys\npathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_text('vector export')\n",
                            encoding="utf-8")
            fake.chmod(0o755)
            environment = dict(os.environ, DRAWIO_DESKTOP_BIN=str(fake))
            result = subprocess.run(["make", "diagrams", f"PYTHON={sys.executable}",
                                     "DIAGRAM_OWNER=drawio"], cwd=project, env=environment,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((project / "figures/overview.svg").is_file())
            self.assertTrue((project / "figures/overview.pdf").is_file())

    def test_explicit_omni_scaffold_copies_complete_project_local_runtime(self) -> None:
        script = SKILL / "scripts/scaffold_research_figures.py"
        plugin = ROOT / "plugins/omnigraffle-tools"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "paper"
            result = subprocess.run([sys.executable, str(script), "--project", str(project),
                                     "--diagram-owner", "omnigraffle",
                                     "--omnigraffle-plugin", str(plugin)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((project / "figures_src/diagram-owner.json").read_text())["owner"],
                             "omnigraffle")
            runtime = project / "scripts/omnigraffle-tools/skills/omnigraffle-workflow/scripts"
            self.assertTrue((runtime / "transactions.py").is_file())
            self.assertTrue((runtime / "native.applescript").is_file())
            self.assertTrue((runtime / "latexit.applescript").is_file())
            self.assertTrue((runtime / "pasteboard.m").is_file())
            self.assertTrue((project / "scripts/omnigraffle-tools/assets/research-templates/README.md").is_file())
            local = subprocess.run([sys.executable, str(runtime / "omnigraffle.py"), "--help"],
                                   cwd=project, env=dict(os.environ, PYTHONPATH=""),
                                   capture_output=True, text=True)
            self.assertEqual(local.returncode, 0, local.stderr)

    def test_project_local_omni_initialization_prepares_without_native_mutation(self) -> None:
        script = SKILL / "scripts/scaffold_research_figures.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "paper"
            prepared = subprocess.run([sys.executable, str(script), "--project", str(project),
                                       "--diagram-owner", "omnigraffle",
                                       "--omnigraffle-plugin", str(ROOT / "plugins/omnigraffle-tools")],
                                      capture_output=True, text=True)
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            for template in ("architecture", "timeline", "mechanism"):
                for width in ("single", "double"):
                    with self.subTest(template=template, width=width):
                        name = f"{template}-{width}"
                        request = root / f"{name}.create.json"
                        init = subprocess.run([sys.executable, str(project / "scripts/init_omni_diagram.py"),
                                               "--template", template, "--width", width,
                                               "--prepare-only", "--request-out", str(request)],
                                              cwd=root, env=dict(os.environ, PYTHONPATH=""),
                                              capture_output=True, text=True)
                        self.assertEqual(init.returncode, 0, init.stderr)
                        seed = project / f"figures_src/diagrams/seeds/{name}.json"
                        self.assertTrue(seed.is_file())
                        self.assertTrue((seed.parent / f"{name}.palette.json").is_file())
                        self.assertTrue(request.is_file())
                        self.assertFalse((project / f"figures_src/diagrams/{name}.graffle").exists())
                        self.assertEqual(json.loads(request.read_text())["spec"], json.loads(seed.read_text()))
                        self.assertEqual(Path(json.loads(request.read_text())["palette"]["catalog_path"]),
                                         (seed.parent / f"{name}.palette.json").resolve())

    def test_auto_preserves_existing_native_owner_and_rejects_override(self) -> None:
        script = SKILL / "scripts/scaffold_research_figures.py"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "paper"
            native = project / "figures_src/diagrams"
            native.mkdir(parents=True)
            (native / "manual.graffle").write_bytes(b"existing native source")
            result = subprocess.run([sys.executable, str(script), "--project", str(project)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((project / "figures_src/diagram-owner.json").read_text())["owner"],
                             "omnigraffle")
            self.assertEqual((native / "manual.graffle").read_bytes(), b"existing native source")
            owner_file = project / "figures_src/diagram-owner.json"
            original_record = owner_file.read_bytes()
            repeated = subprocess.run([sys.executable, str(script), "--project", str(project)],
                                      capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("refusing to overwrite", repeated.stderr)
            self.assertEqual(owner_file.read_bytes(), original_record)
            blocked = subprocess.run([sys.executable, str(project / "scripts/export_diagrams.py"),
                                      "--source-dir", str(native), "--out-dir", str(project / "figures")],
                                     env=dict(os.environ, DIAGRAM_OWNER="drawio"),
                                     capture_output=True, text=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("conflicts with recorded owner", blocked.stderr)

    def test_failed_export_does_not_replace_previous_outputs(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/export_diagrams.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "figures_src/diagrams"
            output = root / "figures"
            source.mkdir(parents=True)
            output.mkdir()
            (source / "overview.drawio").write_text("<mxfile/>", encoding="utf-8")
            old = {suffix: b"previous export" for suffix in ("svg", "pdf")}
            for suffix, content in old.items():
                (output / f"overview.{suffix}").write_bytes(content)
            fake = root / "fake-drawio"
            fake.write_text("#!/usr/bin/env python3\nimport pathlib, sys\n"
                            "fmt = sys.argv[sys.argv.index('-f') + 1]\n"
                            "if fmt == 'pdf': sys.exit(9)\n"
                            "pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_text('new output')\n",
                            encoding="utf-8")
            fake.chmod(0o755)
            result = subprocess.run([sys.executable, str(script), "--source-dir", str(source),
                                     "--out-dir", str(output)],
                                    env=dict(os.environ, DRAWIO_DESKTOP_BIN=str(fake)),
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            for suffix, content in old.items():
                self.assertEqual((output / f"overview.{suffix}").read_bytes(), content)
            self.assertFalse((output / "overview.png").exists())

    def test_omni_export_uses_saved_canvas_width_without_reading_seed(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/export_diagrams.py"
        spec = importlib.util.spec_from_file_location("research_export_diagrams", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "overview.graffle"
            source.write_bytes(b"saved native document")
            (root / "omni.py").write_text("# project-local runtime", encoding="utf-8")
            (root / "seeds").mkdir()
            (root / "seeds/overview.json").write_text("{malformed seed", encoding="utf-8")
            stage = root / "stage"
            stage.mkdir()
            observed = []
            def native(_cli, command, *arguments, **_kwargs):
                if command == "inspect":
                    return {"status": "inspected", "file_sha256": module.sha256(source),
                            "canvases": [{"id": 3, "size": [475.2, 300], "size_units": "points"}]}
                request = json.loads(Path(arguments[-1]).read_text())
                Path(request["output"]).write_bytes(b"staged vector")
                return {"status": "completed", "operation_id": request["operation_id"],
                        "result": {"sha256": module.sha256(Path(request["output"])),
                                   "verification": {"format": request["format"],
                                       "sanitization": {"external_doctype_removed": True,
                                                        "original_export_sha256": "a" * 64,
                                                        "sanitized_export_sha256": "b" * 64}}}}
            def command(args):
                if "-png" in args:
                    Path(args[-1] + ".png").write_bytes(b"staged preview")
                return ""
            def verify(_pdf, _svg, width):
                observed.append(width)
                return {"pdf_width_in": width, "svg_editable_text": True}
            with mock.patch.object(module.platform, "system", return_value="Darwin"), \
                 mock.patch.object(module, "native_export_formats", return_value={"PDF": True, "SVG": True}), \
                 mock.patch.object(module, "native_command", side_effect=native), \
                 mock.patch.object(module, "subprocess_output", side_effect=command), \
                 mock.patch.object(module, "required_tool", side_effect=lambda name: name), \
                 mock.patch.object(module, "normalize_native_svg", return_value={"applied": False}), \
                 mock.patch.object(module, "verify_native_exports", side_effect=verify):
                outputs = module.native_export(root / "omni.py", source, stage)
            self.assertAlmostEqual(observed[0], 6.6)
            self.assertEqual(len(outputs), 4)
            report = json.loads((stage / "overview.export.json").read_text())
            self.assertTrue(report["native_export_reports"]["svg"]["verification"][
                "sanitization"]["external_doctype_removed"])

    def test_observed_native_unitless_svg_normalizes_points_and_preserves_text_namespaces(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/export_diagrams.py"
        spec = importlib.util.spec_from_file_location("research_svg_normalization", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = ('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
                  '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                  '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
                  '<svg xmlns:xl="http://www.w3.org/1999/xlink" xmlns="http://www.w3.org/2000/svg" '
                  'viewBox="0 0 237.6 221" width="237.6" height="221">'
                  '<text font-size="8">Request</text><use xl:href="#node"/></svg>')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "native.svg"
            output.write_text(source, encoding="utf-8")
            report = module.normalize_native_svg(output, [237.6, 221.0])
            self.assertTrue(report["applied"])
            self.assertTrue(report["known_doctype_removed"])
            self.assertEqual(report["svg_text_elements_retained"], 1)
            width, editable = module.svg_width_in(output)
            self.assertAlmostEqual(width, 3.3)
            self.assertTrue(editable)
            import xml.etree.ElementTree as element_tree
            root = element_tree.parse(output).getroot()
            self.assertEqual(root.attrib["width"], "237.6pt")
            self.assertEqual(root.attrib["height"], "221pt")
            self.assertEqual(root.find("{http://www.w3.org/2000/svg}text").attrib["font-size"], "8")
            self.assertEqual(root.find("{http://www.w3.org/2000/svg}use").attrib[
                "{http://www.w3.org/1999/xlink}href"], "#node")
            self.assertNotIn("ns0:svg", output.read_text())
            for mismatch in (source.replace('width="237.6"', 'width="239"'),
                             source.replace('viewBox="0 0 237.6 221"', 'viewBox="0 0 237.6 225"'),
                             source.replace('height="221"', 'height="221em"'),
                             source.replace('height="221"', 'height="221pt"')):
                output.write_text(mismatch, encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    module.normalize_native_svg(output, [237.6, 221.0])

    def test_unknown_native_svg_outcome_never_uses_conversion_fallback(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/export_diagrams.py"
        spec = importlib.util.spec_from_file_location("research_export_failure", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, cli = root / "example.graffle", root / "omni.py"
            source.write_bytes(b"saved native document")
            cli.write_text("# project-local runtime", encoding="utf-8")
            stage = root / "stage"
            stage.mkdir()
            def native(_cli, command, *arguments, **_kwargs):
                if command == "inspect":
                    return {"status": "inspected", "file_sha256": module.sha256(source),
                            "canvases": [{"id": 1, "size": [237.6, 144], "size_units": "points"}]}
                request = json.loads(Path(arguments[-1]).read_text())
                if request["format"] == "SVG":
                    raise module.NativeExportError("unsupported_export", "outcome unknown",
                                                   request["operation_id"], outcome_unknown=True)
                Path(request["output"]).write_bytes(b"staged PDF")
                return {"status": "completed"}
            with mock.patch.object(module.platform, "system", return_value="Darwin"), \
                 mock.patch.object(module, "native_export_formats", return_value={"PDF": True, "SVG": True}), \
                 mock.patch.object(module, "native_command", side_effect=native), \
                 mock.patch.object(module, "subprocess_output") as convert:
                with self.assertRaisesRegex(module.NativeExportError, "reconcile before retry"):
                    module.native_export(cli, source, stage)
                convert.assert_not_called()

    def test_native_export_timeout_reports_reconcilable_operation_id(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/export_diagrams.py"
        spec = importlib.util.spec_from_file_location("research_export_timeout", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        timed_out_id = None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, cli = root / "example.graffle", root / "omni.py"
            source.write_bytes(b"saved native document")
            cli.write_text("# project-local runtime", encoding="utf-8")
            stage = root / "stage"
            stage.mkdir()
            def native(_cli, command, *arguments, **_kwargs):
                nonlocal timed_out_id
                if command == "inspect":
                    return {"status": "inspected", "file_sha256": module.sha256(source),
                            "canvases": [{"id": 1, "size": [237.6, 144], "size_units": "points"}]}
                request = json.loads(Path(arguments[-1]).read_text())
                timed_out_id = request["operation_id"]
                raise subprocess.TimeoutExpired([str(cli), command], 150)
            with mock.patch.object(module.platform, "system", return_value="Darwin"), \
                 mock.patch.object(module, "native_export_formats", return_value={"PDF": True, "SVG": True}), \
                 mock.patch.object(module, "native_command", side_effect=native):
                with self.assertRaises(module.NativeExportError) as caught:
                    module.native_export(cli, source, stage)
            self.assertTrue(caught.exception.outcome_unknown)
            self.assertEqual(caught.exception.operation_id, timed_out_id)
            self.assertIn(f"reconcile {timed_out_id}", str(caught.exception))
        self.assertIn(timed_out_id, str(caught.exception))

    def test_unadvertised_svg_uses_pdf_conversion_without_native_svg_dispatch(self) -> None:
        script = SKILL / "assets/research-figure-starter/scripts/export_diagrams.py"
        spec = importlib.util.spec_from_file_location("research_export_conversion", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dispatched = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, cli = root / "example.graffle", root / "omni.py"
            source.write_bytes(b"saved native document")
            cli.write_text("# project-local runtime", encoding="utf-8")
            stage = root / "stage"
            stage.mkdir()
            def native(_cli, command, *arguments, **_kwargs):
                if command == "inspect":
                    return {"status": "inspected", "file_sha256": module.sha256(source),
                            "canvases": [{"id": 1, "size": [237.6, 144], "size_units": "points"}]}
                request = json.loads(Path(arguments[-1]).read_text())
                dispatched.append(request["format"])
                Path(request["output"]).write_bytes(b"verified native PDF")
                return {"status": "completed"}
            def command(args):
                if "-svg" in args:
                    Path(args[-1]).write_bytes(b"converted SVG")
                elif "-png" in args:
                    Path(args[-1] + ".png").write_bytes(b"preview PNG")
                return ""
            with mock.patch.object(module.platform, "system", return_value="Darwin"), \
                 mock.patch.object(module, "native_export_formats", return_value={"PDF": True, "SVG": False}), \
                 mock.patch.object(module, "native_command", side_effect=native), \
                 mock.patch.object(module, "subprocess_output", side_effect=command), \
                 mock.patch.object(module, "required_tool", side_effect=lambda name: name), \
                 mock.patch.object(module, "verify_native_exports", return_value={"svg_editable_text": False}):
                outputs = module.native_export(cli, source, stage)
            self.assertEqual(dispatched, ["PDF"])
            self.assertFalse((stage / "example-svg-request.json").exists())
            report = json.loads((stage / "example.export.json").read_text())
            self.assertEqual(report["svg_origin"], "pdf_vector_conversion")
            self.assertEqual(report["native_svg"], "not_advertised")
            self.assertEqual(report["svg_conversion"], "pdftocairo -svg")
            self.assertTrue(report["svg_text_outlined"])
            self.assertEqual(len(outputs), 4)


@unittest.skipUnless(importlib.util.find_spec("matplotlib") and importlib.util.find_spec("scienceplots"),
                     "pinned Matplotlib and SciencePlots environment required")
class RenderLayoutTests(unittest.TestCase):
    def test_caption_legend_and_annotation_stay_within_reserved_bands(self) -> None:
        plt = common.configure_matplotlib()
        mapping = common.load_method_styles()
        cases = [
            (grouped_bars, example("grouped-bars.json"), 3.3),
            (line_scaling, example("line-scaling.json"), 6.9),
            (empirical_cdf, example("empirical-cdf.json"), 3.3),
            (stacked_breakdown, example("breakdown-bars.json"), 3.3),
            (stacked_breakdown, example("breakdown-area.json"), 6.9),
        ]
        for module, data, width in cases:
            with self.subTest(figure=data["figure_name"]):
                fig = module.render(plt, module.validate(data, mapping), data, mapping, width)
                try:
                    fig.canvas.draw()
                    renderer = fig.canvas.get_renderer()
                    canvas = fig.bbox
                    caption = fig.texts[-1].get_window_extent(renderer)
                    for ax in fig.axes:
                        for label in [ax.xaxis.label, *ax.get_xticklabels()]:
                            self.assertFalse(caption.overlaps(label.get_window_extent(renderer)))
                        for annotation in ax.texts:
                            box = annotation.get_window_extent(renderer)
                            self.assertGreaterEqual(box.x0, canvas.x0)
                            self.assertLessEqual(box.x1, canvas.x1)
                            self.assertGreaterEqual(box.y0, canvas.y0)
                            self.assertLessEqual(box.y1, canvas.y1)
                    for legend in fig.legends:
                        box = legend.get_window_extent(renderer)
                        self.assertFalse(any(box.overlaps(ax.bbox) for ax in fig.axes))
                finally:
                    plt.close(fig)

    def test_crowded_category_labels_fail_with_actionable_message(self) -> None:
        plt = common.configure_matplotlib()
        data = example("grouped-bars.json")
        data["categories"] = ["Very long category one", "Very long category two", "Very long category three"]
        with self.assertRaisesRegex(common.FigureDataError, "use --width double"):
            grouped_bars.render(plt, grouped_bars.validate(data, common.load_method_styles()),
                                data, common.load_method_styles(), 3.3)


if __name__ == "__main__":
    unittest.main()
