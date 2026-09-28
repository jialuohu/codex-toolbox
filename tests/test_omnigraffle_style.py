"""Portable checks for the bounded research-diagram native interface."""
import copy
import re
import sys
from pathlib import Path
import unittest

from tests.test_omnigraffle_document import fixture, zip_bytes


SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import contracts
    import document
    import engine
    import native
finally:
    sys.path.pop(0)


def styled_spec():
    return {"canvases": [{"key": "main", "name": "Schematic", "width": 475.2, "height": 230,
        "objects": [
            {"key": "a", "kind": "shape", "x": 20, "y": 30, "width": 90, "height": 50,
             "text": "Request", "shape_type": "rounded_rectangle", "stroke_width": 1.25,
             "stroke_pattern": "solid", "text_color": "#202020", "text_align": "center",
             "text_valign": "center", "text_padding": 4},
            {"key": "b", "kind": "shape", "x": 280, "y": 30, "width": 90, "height": 50,
             "text": "Worker", "shape_type": "ellipse"},
            {"key": "flow", "kind": "connector", "from": "a", "to": "b",
             "line_type": "orthogonal", "head_arrow": "filled", "tail_arrow": "none",
             "from_side": "right", "to_side": "left", "stroke_width": 1.5,
             "stroke_pattern": "dashed", "stroke": "#334455"}] }]}


class StyleContracts(unittest.TestCase):
    def test_saved_fixed_canvas_points_are_inspected_without_seed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixed.graffle"
            raw = fixture()
            # Saved/reopened native fixed-canvas archive shape observed in 7.26.
            raw["Sheets"][0].update(CanvasSizingMode=0,
                                    CanvasSize="{237.59999999999999, 221}",
                                    CanvasOrigin="{0, 0}", CanvasDimensionsOrigin="{0, 0}")
            path.write_bytes(zip_bytes(raw))
            report = document.inspect_document(path)
            self.assertAlmostEqual(report["canvases"][0]["size"][0], 237.6)
            self.assertEqual(report["canvases"][0]["size"][1], 221.0)
            self.assertEqual(report["canvases"][0]["size_units"], "points")
            for unknown_mode in (1, 2, 99, False):
                with self.subTest(mode=unknown_mode):
                    raw["Sheets"][0]["CanvasSizingMode"] = unknown_mode
                    path.write_bytes(zip_bytes(raw))
                    self.assertNotIn("size", document.inspect_document(path)["canvases"][0])
            raw["Sheets"][0]["CanvasSizingMode"] = 0
            raw["Sheets"][0]["CanvasSize"] = "{nan, 221}"
            path.write_bytes(zip_bytes(raw))
            with self.assertRaises(document.DocumentError):
                document.inspect_document(path)

    def test_create_accepts_bounded_styles_and_native_transport(self):
        spec = styled_spec()
        contracts.specification(spec)
        self.assertEqual(spec["canvases"][0]["objects"][0]["text_padding"], 4)

    def test_wrong_kind_and_unbounded_style_rejected(self):
        for key, value in (("shape_type", "triangle"), ("stroke_pattern", "custom"),
                           ("text_color", "red"), ("stroke_width", 0), ("text_padding", 2.5),
                           ("from_side", "center")):
            with self.subTest(key=key):
                spec = styled_spec()
                spec["canvases"][0]["objects"][0][key] = value
                with self.assertRaises(contracts.CommandError):
                    contracts.specification(spec)
        spec = styled_spec()
        spec["canvases"][0]["objects"][2]["text_color"] = "#000000"
        with self.assertRaises(contracts.CommandError):
            contracts.specification(spec)
        spec = styled_spec()
        spec["canvases"][0]["objects"][0]["text"] = ""
        with self.assertRaises(contracts.CommandError):
            contracts.specification(spec)
        spec = styled_spec()
        del spec["canvases"][0]["objects"][0]["text"]
        with self.assertRaises(contracts.CommandError):
            contracts.specification(spec)
        spec = styled_spec()
        spec["canvases"][0]["objects"][0]["line_type"] = "straight"
        with self.assertRaises(contracts.CommandError):
            contracts.specification(spec)

    def test_transport_uses_native_magnets_and_keeps_legacy_point_list(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "new.graffle")
            request = {"op": "create", "working_copy": True, "path": path, "spec": styled_spec()}
            normalized = native.validate_request(request)
            objs = normalized["spec"]["canvases"][0]["objects"]
            self.assertNotIn("_points", objs[2])
            self.assertEqual(objs[0]["_text_color"], [32 * 257] * 3)
            self.assertEqual(objs[2]["_stroke"], [51 * 257, 68 * 257, 85 * 257])
            self.assertNotIn("_text_color", request["spec"]["canvases"][0]["objects"][0])
            del objs[2]  # Test the legacy no-side request independently below.
            legacy = styled_spec()
            legacy["canvases"][0]["objects"][2] = {"key": "flow", "kind": "connector", "from": "a", "to": "b"}
            normalized = native.validate_request({**request, "spec": legacy})
            self.assertEqual(len(normalized["spec"]["canvases"][0]["objects"][2]["_points"]), 2)


class Preservation(unittest.TestCase):
    @staticmethod
    def color_label(components):
        return {"Text": {"Text": (
            r"{\rtf1{\fonttbl\f0 Helvetica;}"
            r"{\colortbl;\red255\green255\blue255;\red0\green0\blue0;}"
            r"{\*\expandedcolortbl;;\cssrgb" + "".join(r"\c" + str(item) for item in components)
            + r";}\pard\ql\f0\fs16\cf2 Synthetic}")}}

    def test_saved_srgb_table_recovers_exact_palette_setters(self):
        for color, components in (("30343A", [18824, 20392, 22745]),
                                  ("2148B8", [12941, 28235, 72157]),
                                  ("C65F38", [77647, 37255, 21961])):
            with self.subTest(color=color):
                label = self.color_label(components)
                self.assertEqual(engine.qualified_saved_text_color(label),
                                 [int(color[i:i + 2], 16) * 257 for i in (0, 2, 4)])
        # Every catalog color uses 8-bit channels; their exact 16-bit setters
        # must be identifiable from the observed five-decimal saved table.
        catalog = (SCRIPTS.parents[3] / "photo-tools/skills/mono-color/references/design-system/colors.json").read_text()
        colors = set(re.findall(r"#[0-9A-Fa-f]{6}", catalog))
        self.assertEqual(len(colors), 22)
        for color in colors:
            setters = [int(color[i:i + 2], 16) * 257 for i in (1, 3, 5)]
            components = [(item * 100000 + 32767) // 65535 for item in setters]
            self.assertEqual(engine.qualified_saved_text_color(self.color_label(components)), setters)

    def test_saved_color_parser_rejects_unqualified_or_unrepresentable_colors(self):
        source = self.color_label([12941, 28235, 72157])["Text"]["Text"]
        for changed in (source.replace(r"\cf2", r"\cf0"), source.replace(r"\cf2", r"\cf9999"),
                        source.replace("Synthetic", r"Synthetic \cf1 mixed"),
                        source.replace(r"\cssrgb", r"\cssgray"),
                        source.replace(r"\c12941", r"\c100001"),
                        source.replace(r"\c12941", r"\c10000"),
                        source.replace(r"\c12941", r"\c" + "9" * 5000),
                        source.replace(r"\cssrgb", r"{\cssrgb}"),
                        source.replace(r"\red255\green255\blue255;", ""),
                        source.replace(r"\red255", r"\red256"),
                        source.replace(r"\colortbl", r"\colortbl\red1;"),
                        source[:-1], source + "}",
                        source.replace(r"\cf2 Synthetic", r"Synthetic\cf2"),
                        source.replace(r"\fonttbl\f0 Helvetica;", r"\fonttbl{\f0 Helvetica;}{\f0 Arial;}"),
                        source.replace(r"\f0\fs16\cf2 Synthetic", r"{\f0\fs16\cf2 Synthetic} Default"),
                        source.replace(r"\f0\fs16\cf2", r"\f0\cf2"),
                        source.replace(r"\f0\fs16\cf2", r"\fs16\cf2"),
                        source.replace(r"\f0\fs16", r"\f0\fs16\b")):
            with self.subTest(changed=changed[:100]), self.assertRaises(contracts.CommandError):
                engine.qualified_saved_text_color({"Text": {"Text": changed}})

    def test_explicit_color_update_also_rejects_unqualified_body_scope(self):
        source = self.color_label([12941, 28235, 72157])["Text"]["Text"]
        for changed in (source.replace(r"\f0\fs16\cf2 Synthetic", r"{\f0\fs16\cf2 Synthetic} Default"),
                        source.replace(r"\fs16\cf2 Synthetic", r"Synthetic\fs16\cf2"),
                        source.replace(r"\cf2", r"\cf9999"),
                        source.replace(r"\red255\green255\blue255;", ""),
                        source.replace(r"\cf2 Synthetic", "Synthetic").replace(r"\colortbl;", r"\colortbl\cf2;")):
            before = fixture()
            before["Sheets"][0]["GraphicsList"][1]["Text"] = {"Text": changed}
            with self.assertRaises(contracts.CommandError):
                engine.preflight_update_styles(before, [{"canvas_id": 1, "object_id": 3,
                                                        "set": {"text_color": "#30343A"}}])

    def test_native_retained_color_is_derived_from_strict_saved_source(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "saved.graffle"
            raw = fixture()
            raw["Sheets"][0]["GraphicsList"][1].update(self.color_label([12941, 28235, 72157]))
            path.write_bytes(zip_bytes(raw))
            request = {"op": "update", "path": str(path), "working_copy": True, "changes": [
                {"canvas_id": 1, "object_id": 3, "set": {"font_size": 9}}]}
            normalized = native.validate_request(request)
            self.assertEqual(normalized["changes"][0]["set"]["_preserved_text_color"], [8481, 18504, 47288])
            self.assertEqual(request["changes"][0]["set"], {"font_size": 9})
            self.assertEqual(engine.preflight_update_styles(raw, request["changes"]), set())
            request["changes"][0]["set"]["_preserved_text_color"] = [0, 0, 0]
            with self.assertRaises(ValueError):
                native.validate_request(request)

    def test_strict_parsed_dictionaries_are_normalized_only_in_plain_comparison_copy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            before = fixture()
            before["Sheets"][0]["GraphicsList"][0]["Style"] = {"fill": {"Color": {
                "r": "0.25", "g": "0.5", "b": "0.75", "space": "srgb"}}}
            after = copy.deepcopy(before)
            after["Sheets"][0]["GraphicsList"][0]["Style"]["fill"]["Color"].update(r=0.25, g=0.5, b=0.75)
            path = Path(tmp) / "parsed.graffle"
            path.write_bytes(zip_bytes(before))
            _, strict_before = document.read_document(path)
            path.write_bytes(zip_bytes(after))
            _, strict_after = document.read_document(path)
            self.assertNotEqual(type(strict_before), dict)
            engine.verify_preservation(strict_before, strict_after, {(1, 3)})
            color = strict_before["Sheets"][0]["GraphicsList"][0]["Style"]["fill"]["Color"]
            self.assertEqual(color["r"], "0.25")
            with self.assertRaises(document.DocumentError):
                color["r"] = 0.25

    def test_explicit_rgb_numeric_strings_normalize_without_hiding_color_changes(self):
        before = fixture()
        color = {"r": "0.9529411764705882", "g": "0.9411764705882353",
                 "b": "0.9058823529411765", "space": "srgb"}
        before["Sheets"][0]["GraphicsList"][0]["Style"] = {"fill": {"Color": color}}
        after = copy.deepcopy(before)
        normalized = after["Sheets"][0]["GraphicsList"][0]["Style"]["fill"]["Color"]
        for name in ("r", "g", "b"):
            normalized[name] = float(normalized[name])
        engine.verify_preservation(before, after, {(1, 3)})
        self.assertIsInstance(color["r"], str, "Comparison must not rewrite saved source data")
        normalized["b"] = 0.8
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, {(1, 3)})

    def test_flat_group_children_and_incident_stroke_normalize_recursively(self):
        before = fixture()
        child = before["Sheets"][0]["GraphicsList"].pop(0)
        child["Style"] = {"fill": {"Color": {"r": "0.25", "g": "0.5", "b": "0.75", "space": "srgb"}}}
        before["Sheets"][0]["GraphicsList"].append({"ID": 5, "Class": "Group", "Graphics": [child]})
        line = before["Sheets"][0]["GraphicsList"][1]
        line["Points"] = ["{0,0}", "{1,1}"]
        line["Style"] = {"stroke": {"Color": {"r": "0.1", "g": "0.2", "b": "0.3", "space": "RGB"}}}
        after = copy.deepcopy(before)
        after_child = after["Sheets"][0]["GraphicsList"][2]["Graphics"][0]
        after_child["Style"]["fill"]["Color"].update(r=0.25, g=0.5, b=0.75)
        after_line = after["Sheets"][0]["GraphicsList"][1]
        after_line["Style"]["stroke"]["Color"].update(r=0.1, g=0.2, b=0.3)
        after_line["Points"][1] = "{2,2}"
        engine.verify_preservation(before, after, {(1, 3)}, incident_geometry={(1, 4)})
        after_child["Style"]["fill"]["Color"]["r"] = 0.3
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, {(1, 3)}, incident_geometry={(1, 4)})
        after_child["Style"]["fill"]["Color"]["r"] = 0.25
        after_line["Style"]["stroke"]["Color"]["r"] = 0.15
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, {(1, 3)}, incident_geometry={(1, 4)})

    def test_color_normalization_rejects_invalid_and_retains_unknown_encodings(self):
        for component in ("nan", "inf", "1.1", -0.1, float("nan"), True):
            with self.subTest(component=component):
                graphic = {"Style": {"fill": {"Color": {"r": component, "g": "0", "b": "0", "space": "srgb"}}}}
                with self.assertRaises(contracts.CommandError):
                    engine.normalized_graphic(graphic)
        for color in ({"r": "0.25", "g": "0.5", "b": "0.75", "space": "unknown"},
                      {"r": "0.25", "g": "0.5", "b": "0.75", "space": "srgb", "Profile": b"opaque"},
                      b"opaque color archive"):
            with self.subTest(color=color):
                before = fixture()
                before["Sheets"][0]["GraphicsList"][0]["Style"] = {"fill": {"Color": color}}
                self.assertEqual(engine.normalized_graphic(before["Sheets"][0]["GraphicsList"][0]),
                                 before["Sheets"][0]["GraphicsList"][0])
                after = copy.deepcopy(before)
                changed = after["Sheets"][0]["GraphicsList"][0]["Style"]["fill"]
                if isinstance(color, dict):
                    changed["Color"].update(r=0.25, g=0.5, b=0.75)
                else:
                    changed["Color"] = b"different archive"
                with self.assertRaises(contracts.CommandError):
                    engine.verify_preservation(before, after, {(1, 3)})

    def test_mixed_rtf_requires_explicit_whole_label_replacement(self):
        before = fixture()
        graphic = before["Sheets"][0]["GraphicsList"][1]
        graphic["Text"] = {"Text": r"{\rtf1{\fonttbl{\f0 Helvetica;}{\f1 Helvetica-Bold;}}\f0\fs16 A \f1 B}"}
        change = {"canvas_id": 1, "object_id": 3, "set": {"text_color": "#112233"}}
        with self.assertRaises(contracts.CommandError) as raised:
            engine.preflight_update_styles(before, [change])
        self.assertEqual(raised.exception.code, "mixed_text_attributes")
        change["set"] = {"text": "A B", "text_color": "#112233"}
        self.assertEqual(engine.preflight_update_styles(before, [change]), set())
        graphic["Text"] = {"Text": r"{\rtf1{\fonttbl{\f0 Helvetica;}}\pard\qc\f0\fs16 Plain}"}
        change["set"] = {"text_color": "#112233"}
        self.assertEqual(engine.preflight_update_styles(before, [change]), set())
        graphic["Text"] = {"Text": r"{\rtf1{\fonttbl{\f0 Helvetica;}}\pard\sl240\f0\fs16 Plain}"}
        with self.assertRaises(contracts.CommandError):
            engine.preflight_update_styles(before, [change])

    def test_observed_single_run_expanded_srgb_table_is_qualified(self):
        graphic = {"Text": {"Text": (
            "{\\rtf1\\ansi\\ansicpg1252\\cocoartf2870\n"
            "\\cocoatextscaling0\\cocoaplatform0{\\fonttbl\\f0\\fswiss\\fcharset0 Helvetica;}\n"
            "{\\colortbl;\\red255\\green255\\blue255;\\red24\\green24\\blue24;}\n"
            "{\\*\\expandedcolortbl;;\\cssrgb\\c12549\\c12549\\c12549;}\n"
            "\\pard\\tx560\\tx1120\\pardirnatural\\partightenfactor0\n"
            "\\f0\\fs16 \\cf2 Editable text}")}}
        self.assertTrue(engine.uniform_text_attributes(graphic))
        source = graphic["Text"]["Text"]
        for changed in (source.replace("\\c12549", "\\c100001", 1),
                        source.replace("\\cssrgb", "\\cssgray"),
                        source.replace("Editable text", "Editable \\f1 text"),
                        source.replace("Editable text", "Editable \\cssrgb\\c1\\c2\\c3 text")):
            graphic["Text"]["Text"] = changed
            self.assertFalse(engine.uniform_text_attributes(graphic))

    def test_unrequested_native_text_attributes_must_survive_style_update(self):
        before = {"canvases": [{"id": 1, "objects": [{"id": 3, "text": "A", "font_name": "Helvetica",
            "font_size": 8, "text_rgb": [0, 0, 0], "text_align": "center",
            "text_valign": "center", "side_padding": 3, "vertical_padding": 3}]}]}
        after = copy.deepcopy(before)
        after["canvases"][0]["objects"][0]["text_rgb"] = [0.2, 0.2, 0.2]
        engine.verify_retained_text_attributes(before, after, 1, 3, {"text_color": "#333333"})
        after["canvases"][0]["objects"][0]["font_size"] = 9
        with self.assertRaises(contracts.CommandError):
            engine.verify_retained_text_attributes(before, after, 1, 3, {"text_color": "#333333"})

    def test_incident_connector_geometry_only_and_manual_route_guard(self):
        before = fixture()
        line = before["Sheets"][0]["GraphicsList"][2]
        line["Points"] = ["{0,0}", "{1,1}"]
        changed = [{"canvas_id": 1, "object_id": 3, "set": {"x": 200}}]
        self.assertEqual(engine.preflight_update_styles(before, changed), {(1, 4)})
        after = copy.deepcopy(before)
        after["Sheets"][0]["GraphicsList"][2]["Points"][1] = "{2,2}"
        engine.verify_preservation(before, after, {(1, 3)}, incident_geometry={(1, 4)})
        after["Sheets"][0]["GraphicsList"][2]["Style"] = {"stroke": {"Width": 9}}
        with self.assertRaises(contracts.CommandError):
            engine.verify_preservation(before, after, {(1, 3)}, incident_geometry={(1, 4)})
        line["Points"].append("{3,3}")
        with self.assertRaises(contracts.CommandError) as raised:
            engine.preflight_update_styles(before, changed)
        self.assertEqual(raised.exception.code, "manual_connector_route")
        line["Style"] = {"stroke": {"LineType": 2}}
        line["OrthogonalBarAutomatic"] = True
        line["OrthogonalBarPoint"] = "{4,4}"
        self.assertEqual(engine.preflight_update_styles(before, changed), {(1, 4)})
        after = copy.deepcopy(before)
        after["Sheets"][0]["GraphicsList"][2]["OrthogonalBarPoint"] = "{5,5}"
        engine.verify_preservation(before, after, {(1, 3)}, incident_geometry={(1, 4)})
        line["OrthogonalBarAutomatic"] = False
        with self.assertRaises(contracts.CommandError):
            engine.preflight_update_styles(before, changed)

    def test_direct_line_geometry_and_image_style_reject_before_dispatch(self):
        before = fixture()
        with self.assertRaises(contracts.CommandError) as raised:
            engine.preflight_update_styles(before, [{"canvas_id": 1, "object_id": 4, "set": {"x": 20}}])
        self.assertEqual(raised.exception.code, "invalid_request")
        before["Sheets"][0]["GraphicsList"][1]["Class"] = "SolidGraphic"
        with self.assertRaises(contracts.CommandError) as raised:
            engine.preflight_update_styles(before, [{"canvas_id": 1, "object_id": 3,
                                                     "set": {"shape_type": "ellipse"}}])
        self.assertEqual(raised.exception.code, "invalid_request")
        before["Sheets"][0]["GraphicsList"][1]["ImageID"] = 1
        with self.assertRaises(contracts.CommandError) as raised:
            engine.preflight_update_styles(before, [{"canvas_id": 1, "object_id": 3, "set": {"stroke_width": 1.5}}])
        self.assertEqual(raised.exception.code, "invalid_request")

    def test_empty_label_text_style_rejects_before_native_mutation(self):
        before = fixture()
        change = {"canvas_id": 1, "object_id": 3, "set": {"text_color": "#202020"}}
        with self.assertRaises(contracts.CommandError):
            engine.preflight_update_styles(before, [change])
        before_report = {"canvases": [{"id": 1, "objects": [{"id": 3, "text": ""}]}]}
        with self.assertRaises(contracts.CommandError):
            engine.preflight_native_text_readback(before_report, [change])
        with self.assertRaises(contracts.CommandError):
            contracts.properties({"text": "", "text_color": "#202020"})

    def test_native_readback_checks_new_style_fields(self):
        report = {"canvases": [{"id": 1, "objects": [{"id": 3, "shape_type": "ellipse",
            "stroke_width": 1.25, "stroke_pattern": "dashed", "text_rgb": [32 / 255] * 3,
            "text_align": "center", "text_valign": "top", "text_padding": 3}]}]}
        engine.verify_properties(report, 1, 3, {"shape_type": "ellipse", "stroke_width": 1.25,
            "stroke_pattern": "dashed", "text_color": "#202020", "text_align": "center",
            "text_valign": "top", "text_padding": 3})
        with self.assertRaises(contracts.CommandError):
            engine.verify_properties(report, 1, 3, {"stroke_pattern": "solid"})
        report["canvases"][0]["objects"][0]["font_name"] = "Helvetica Neue"
        self.assertEqual(engine.verify_properties(report, 1, 3, {"font_name": "Helvetica"}),
                         [{"canvas_id": 1, "object_id": 3,
                           "requested": "Helvetica", "native": "Helvetica Neue"}])


if __name__ == "__main__":
    unittest.main()
