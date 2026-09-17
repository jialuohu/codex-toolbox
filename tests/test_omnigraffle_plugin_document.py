"""Portable tests of the native-observed image/LinkBack outer schema."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_omnigraffle_document import fixture, zip_bytes

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts/document.py'
SPEC = importlib.util.spec_from_file_location('plugin_omni_document', SCRIPT)
document = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(document)


class ImageAssociationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.graffle'
        self.data = fixture()
        self.data['ImageList'] = ['image1.pdf']
        self.payload = b'opaque-native-archive-not-decoded'
        self.data['ImageLinkBack'] = [{'bundleId':'fr.chachatelier.pierre.LaTeXiT',
                                     'serverName':'LaTeXiT', 'serverAppName':'LaTeXiT',
                                     'version':'A', 'refresh':0.0, 'appData':self.payload}]
        self.data['Sheets'][0]['GraphicsList'][1]['ImageID'] = 1

    def write(self, extras=None):
        self.path.write_bytes(zip_bytes(self.data, [('image1.pdf', b'%PDF-test')] if extras is None else extras))

    def test_native_observed_owner_association_and_opaque_bytes(self):
        self.write()
        original = self.path.read_bytes()
        report, parsed = document.read_document(self.path)
        obj = next(x for x in report['canvases'][0]['objects'] if x['id'] == 3)
        self.assertEqual(obj['image_id'], 1)
        self.assertEqual(obj['image']['path'], 'image1.pdf')
        self.assertEqual(obj['linkback']['owner']['bundle_id'], 'fr.chachatelier.pierre.LaTeXiT')
        self.assertEqual(obj['linkback']['payload_sha256'], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(parsed['ImageLinkBack'][0]['appData'], self.payload)
        self.assertNotIn(self.payload.decode(), json.dumps(report))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(report['schema_qualified'])

    def test_missing_asset_audit_finding_and_strict_rejection(self):
        self.write([])
        report = document.inspect_document(self.path)
        self.assertEqual(report['findings'][0]['kind'], 'missing_image_asset')
        with self.assertRaises(document.DocumentError):
            document.read_document(self.path)

    def test_malformed_linkback_records(self):
        for record in (b'archive-alone', 0, [], {'appData':self.payload},
                       dict(self.data['ImageLinkBack'][0], appData='bad'),
                       dict(self.data['ImageLinkBack'][0], version='B'),
                       dict(self.data['ImageLinkBack'][0], refresh=True)):
            with self.subTest(record=repr(record)[:100]):
                self.data['ImageLinkBack'] = [record]
                self.write()
                report = document.inspect_document(self.path)
                self.assertFalse(report['schema_qualified'])
                with self.assertRaises(document.DocumentError):
                    document.read_document(self.path)

    def test_zero_is_not_assumed_to_mean_no_image(self):
        self.data['Sheets'][0]['GraphicsList'][1]['ImageID'] = 0
        self.write()
        self.assertEqual(document.inspect_document(self.path)['findings'][0]['kind'], 'invalid_image_reference')
        with self.assertRaises(document.DocumentError):
            document.read_document(self.path)

    def test_explicit_empty_slots_do_not_shift_owner(self):
        owner = self.data['ImageLinkBack'][0]
        self.data['ImageList'] = ['image1.pdf', 'image2.pdf', 'image3.pdf']
        self.data['ImageLinkBack'] = [{}, '', owner]
        self.data['Sheets'][0]['GraphicsList'][1]['ImageID'] = 3
        self.write([(name,b'%PDF') for name in self.data['ImageList']])
        report, _ = document.read_document(self.path)
        obj = next(x for x in report['canvases'][0]['objects'] if x['id'] == 3)
        self.assertEqual(obj['image']['path'], 'image3.pdf')
        self.assertEqual(obj['linkback']['owner']['server_name'], 'LaTeXiT')

    def test_short_or_long_linkback_array_not_guessed(self):
        for records in ([], self.data['ImageLinkBack'] + [{}]):
            self.data['ImageLinkBack'] = records
            self.write()
            with self.assertRaises(document.DocumentError):
                document.read_document(self.path)

    def test_non_linked_images_without_array(self):
        del self.data['ImageLinkBack']
        self.write()
        report, _ = document.read_document(self.path)
        obj = next(x for x in report['canvases'][0]['objects'] if x['id'] == 3)
        self.assertNotIn('linkback', obj)

    def test_bounds_preserved(self):
        self.write()
        with self.assertRaises(document.DocumentError):
            document.read_document(self.path, limits={'member_bytes':1})

    def test_unsupported_array_shapes_reject_strict(self):
        self.data['ImageLinkBack'] = {'not':'an array'}
        self.write()
        with self.assertRaises(document.DocumentError):
            document.read_document(self.path)


if __name__ == '__main__':
    unittest.main()
