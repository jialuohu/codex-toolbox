"""Portable SVG export-envelope checks; never invoke installed applications."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import contracts
    import engine
finally:
    sys.path.pop(0)


DECLARATION = (b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
               b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">')
XML = b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="237.6" height="221"><text>Request</text></svg>'


class SvgExportEnvelopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="omnigraffle-export-check-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "staged.svg"

    def test_native_external_declaration_is_removed_before_parse_and_publication(self):
        original = XML + DECLARATION + b"\n" + SVG
        self.path.write_bytes(original)
        with patch.object(engine.ET, "fromstring", wraps=ET.fromstring) as parse:
            verification = engine.export_check(self.path, "SVG")
        parsed_input = parse.call_args.args[0]
        self.assertIsInstance(parsed_input, str)
        self.assertNotIn("<!DOCTYPE", parsed_input)
        sanitized = self.path.read_bytes()
        self.assertEqual(sanitized, XML + b"\n" + SVG)
        self.assertEqual(verification["sanitization"], {
            "external_doctype_removed": True,
            "original_export_sha256": hashlib.sha256(original).hexdigest(),
            "sanitized_export_sha256": hashlib.sha256(sanitized).hexdigest(),
        })
        self.assertEqual(ET.fromstring(sanitized).tag, "{http://www.w3.org/2000/svg}svg")

    def test_svg_without_declaration_is_unchanged(self):
        self.path.write_bytes(XML + SVG)
        verification = engine.export_check(self.path, "SVG")
        self.assertEqual(self.path.read_bytes(), XML + SVG)
        self.assertNotIn("sanitization", verification)

    def test_only_exact_external_declaration_in_prolog_is_accepted(self):
        variants = [
            DECLARATION.replace(b"http:", b"https:"),
            DECLARATION.replace(b'"', b"'"),
            DECLARATION.replace(b"DOCTYPE svg", b"DOCTYPE  svg"),
            DECLARATION[:-1] + b" []>",
            DECLARATION + b"\n" + DECLARATION,
            b'<!DOCTYPE svg SYSTEM "file:///etc/passwd">',
            b'<!DOCTYPE svg [<!ENTITY payload "expanded">]>',
            b'<!ENTITY payload SYSTEM "file:///etc/passwd">',
        ]
        for declaration in variants:
            with self.subTest(declaration=declaration):
                original = XML + declaration + b"\n" + SVG
                self.path.write_bytes(original)
                with patch.object(engine.ET, "fromstring") as parse:
                    with self.assertRaises(contracts.CommandError):
                        engine.export_check(self.path, "SVG")
                parse.assert_not_called()
                self.assertEqual(self.path.read_bytes(), original)

        misplaced = SVG.replace(b"<text>", DECLARATION + b"<text>")
        self.path.write_bytes(misplaced)
        with self.assertRaises(contracts.CommandError):
            engine.export_check(self.path, "SVG")
        self.assertEqual(self.path.read_bytes(), misplaced)

    def test_known_declaration_does_not_allow_extra_entity(self):
        original = XML + DECLARATION + b'\n<!ENTITY payload "expanded">\n' + SVG
        self.path.write_bytes(original)
        with patch.object(engine.ET, "fromstring") as parse:
            with self.assertRaises(contracts.CommandError):
                engine.export_check(self.path, "SVG")
        parse.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)

    def test_alternate_encoding_cannot_hide_internal_declarations(self):
        original = ('<?xml version="1.0" encoding="UTF-16"?>'
                    '<!DOCTYPE svg [<!ENTITY payload "expanded">]>'
                    '<svg>&payload;</svg>').encode("utf-16")
        self.path.write_bytes(original)
        with patch.object(engine.ET, "fromstring") as parse:
            with self.assertRaises(contracts.CommandError):
                engine.export_check(self.path, "SVG")
        parse.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)

    def test_oversized_svg_is_rejected_without_parse_or_write(self):
        original = b" " * (16 * 1024 * 1024 + 1)
        self.path.write_bytes(original)
        with patch.object(engine.ET, "fromstring") as parse:
            with self.assertRaises(contracts.CommandError):
                engine.export_check(self.path, "SVG")
        parse.assert_not_called()
        self.assertEqual(self.path.stat().st_size, len(original))

    def test_invalid_svg_with_known_declaration_remains_unchanged(self):
        for body in (b"<svg>", b"<html/>"):
            with self.subTest(body=body):
                original = XML + DECLARATION + b"\n" + body
                self.path.write_bytes(original)
                with self.assertRaises(contracts.CommandError):
                    engine.export_check(self.path, "SVG")
                self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
