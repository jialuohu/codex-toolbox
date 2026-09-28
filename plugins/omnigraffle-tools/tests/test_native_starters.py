"""Portable package verification of actual accepted native starter archives."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
RUNTIME = PLUGIN / "skills/omnigraffle-workflow/scripts"
sys.path.insert(0, str(RUNTIME))
from verify_research_starters import check_decoded_metadata, verify_bundle

NATIVE = PLUGIN / "assets/research-templates/native"
PRIVATE_PREFIX = "/" + "Users" + "/example/"


class NativeStarterTest(unittest.TestCase):
    def test_actual_bundled_sources_match_recorded_native_acceptance(self):
        result = verify_bundle(NATIVE)
        self.assertEqual(result["starters"], 6)
        self.assertFalse(result["application_called"])

    def test_corrupted_package_or_acceptance_metadata_is_rejected(self):
        mutations = {
            "boolean_schema": lambda m: m.__setitem__("schema_version", True),
            "private_manifest_path": lambda m: m.__setitem__("provenance", PRIVATE_PREFIX + "private-source"),
            "duplicate_record": lambda m: m["starters"].__setitem__(1, copy.deepcopy(m["starters"][0])),
            "missing_record": lambda m: m["starters"].pop(),
            "altered_source_hash": lambda m: m["starters"][0].__setitem__("sha256", "0" * 64),
            "wrong_width_tag": lambda m: m["starters"][0].__setitem__("width", "double"),
            "canvas_disagreement": lambda m: m["starters"][0].__setitem__("size_pt", [999, 221]),
            "font_disagreement": lambda m: m["starters"][0].__setitem__("fonts", ["Arial"]),
            "stale_svg_hash": lambda m: m["starters"][0]["native_export_evidence"]["output_sha256"].__setitem__("svg", "0" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory(prefix="native-starter-test-") as temporary:
                directory = Path(temporary) / "native"
                shutil.copytree(NATIVE, directory)
                manifest = json.loads((directory / "manifest.json").read_text())
                mutate(manifest)
                (directory / "manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    verify_bundle(directory)

    def test_nested_author_and_decoded_paths_are_rejected(self):
        for value in ({"Sheets": [{"Author": "example"}]}, {"Text": PRIVATE_PREFIX + "figure"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_decoded_metadata(value, author_fields=True)

    def test_decoded_palette_path_is_rejected_even_with_matching_digest(self):
        with tempfile.TemporaryDirectory(prefix="native-starter-palette-test-") as temporary:
            directory = Path(temporary) / "native"
            shutil.copytree(NATIVE, directory)
            palette = json.loads((directory / "palette.json").read_text())
            palette["note"] = "/private/var/example/source"
            (directory / "palette.json").write_text(json.dumps(palette))
            manifest = json.loads((directory / "manifest.json").read_text())
            manifest["palette"]["sha256"] = hashlib.sha256((directory / "palette.json").read_bytes()).hexdigest()
            (directory / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify_bundle(directory)


if __name__ == "__main__":
    unittest.main()
