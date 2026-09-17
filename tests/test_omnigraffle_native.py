"""Portable transport/validation tests. Native app acceptance is separately gated."""
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts/native.py'
spec = importlib.util.spec_from_file_location('omnigraffle_native', MODULE)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.app = self.root / 'OmniGraffle.app'
        (self.app / 'Contents').mkdir(parents=True)
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.omnigroup.OmniGraffle7'}))
        self.doc = self.root / 'existing.graffle'
        self.doc.write_bytes(b'test')
        self.adapter = native.NativeAdapter(self.app)

    def create(self):
        return {'op': 'create', 'working_copy': True, 'path': str(self.root / 'new.graffle'),
                'spec': {'canvases': [{'key': 'c', 'name': 'English / 中文', 'width': 480, 'height': 240,
                                      'objects': [{'key': 's', 'kind': 'shape', 'x': 20, 'y': 20,
                                                   'width': 80, 'height': 40, 'text': 'x²', 'fill': '#AbCD12'}]}]}}

    def test_hostile_text_remains_json_data(self):
        request = self.create()
        text = '"; do shell script "touch /tmp/unsafe"\n$(whoami) `id` 中文'
        request['spec']['canvases'][0]['objects'][0]['text'] = text
        seen = []
        def run(args, **kwargs):
            seen.append(args)
            body = json.loads(Path(args[2]).read_text())
            self.assertEqual(body['spec']['canvases'][0]['objects'][0]['text'], text)
            self.assertNotIn(text, ' '.join(args))
            self.assertEqual(Path(args[2]).stat().st_mode & 0o777, 0o600)
            kwargs['stdout'].write(b'{"status":"ok"}')
            return subprocess.CompletedProcess(args, 0)
        with patch.object(native.subprocess, 'run', side_effect=run):
            self.assertEqual(self.adapter.call(request)['status'], 'ok')
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], str(native.SCRIPT))

    def test_timeout_unknown_without_retry(self):
        with patch.object(native.subprocess, 'run', side_effect=subprocess.TimeoutExpired('osascript', 30)) as run:
            result = self.adapter.call(self.create())
        self.assertEqual(run.call_count, 1)
        self.assertTrue(result['error']['outcome_unknown'])

    def test_read_timeout_not_mutation(self):
        with patch.object(native.subprocess, 'run', side_effect=subprocess.TimeoutExpired('osascript', 30)):
            result = self.adapter.call({'op': 'inventory'})
        self.assertFalse(result['error']['outcome_unknown'])

    def test_arbitrary_script_field_rejected_before_dispatch(self):
        with patch.object(native.subprocess, 'run') as run:
            result = self.adapter.call({'op': 'inventory', 'script': 'bad'})
        run.assert_not_called()
        self.assertEqual(result['error']['code'], 'invalid_request')

    def test_bundle_id_guard(self):
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'other'}))
        self.assertEqual(self.adapter.call({'op': 'inventory'})['error']['code'], 'invalid_request')

    def test_staging_required(self):
        request = self.create()
        del request['working_copy']
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_existing_destination_rejected(self):
        request = self.create()
        request['path'] = str(self.doc)
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_save_requires_staged_exact_path(self):
        request = {'op': 'save', 'path': str(self.doc), 'working_copy': True}
        self.assertEqual(native.validate_request(request)['path'], str(self.doc.resolve()))
        request['working_copy'] = False
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_connector_border_intersections(self):
        a = dict(x=40, y=80, width=140, height=60)
        b = dict(x=300, y=80, width=140, height=60)
        self.assertEqual(native.connector_points(a, b), [[180,110],[300,110]])
        self.assertEqual(native.connector_points(b, a), [[300,110],[180,110]])
        with self.assertRaises(ValueError):
            native.connector_points(a, a)
        c = dict(x=0, y=0, width=20, height=20)
        d = dict(x=40, y=40, width=20, height=20)
        self.assertEqual(native.connector_points(c, d), [[20,20],[40,40]])

    def test_colors_normalized_without_mutating_request(self):
        request = self.create()
        result = native.validate_request(request)
        obj = result['spec']['canvases'][0]['objects'][0]
        self.assertEqual(obj['_fill'], [171*257, 205*257, 18*257])
        self.assertNotIn('_fill', request['spec']['canvases'][0]['objects'][0])

    def test_duplicate_keys(self):
        request = self.create()
        objects = request['spec']['canvases'][0]['objects']
        objects.append(dict(objects[0]))
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_invalid_numbers(self):
        for value in (True, float('nan'), float('inf'), -1, 20000):
            request = self.create()
            request['spec']['canvases'][0]['width'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.validate_request(request)

    def test_connector_missing_endpoint(self):
        request = self.create()
        request['spec']['canvases'][0]['objects'].append({'key':'line', 'kind':'connector', 'from':'s', 'to':'missing'})
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_group_shared_children_rejected(self):
        request = self.create()
        objs = request['spec']['canvases'][0]['objects']
        objs.append(dict(objs[0], key='t'))
        objs.append({'key':'g', 'kind':'group', 'children':['s', 't']})
        native.validate_request(request)
        objs.append({'key':'g2', 'kind':'group', 'children':['s', 't']})
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_update_duplicate_identity(self):
        change = {'canvas_id':1, 'object_id':2, 'set':{'text':'a'}}
        request = {'op':'update', 'path':str(self.doc), 'working_copy':True, 'changes':[change, change]}
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_export_requires_exact_scope_and_bounded_dpi(self):
        request = {'op':'export','path':str(self.doc),'working_copy':True,'output':str(self.root/'out.pdf'),'format':'PDF'}
        with self.assertRaises(ValueError):
            native.validate_request(request)
        request['canvas_id'] = 1
        self.assertEqual(native.validate_request(request)['dpi'], 72)
        request['document_scope'] = True
        with self.assertRaises(ValueError):
            native.validate_request(request)
        del request['document_scope']
        request['dpi'] = 10000
        with self.assertRaises(ValueError):
            native.validate_request(request)

    def test_open_once_then_verify_path(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[0] == '/usr/bin/open':
                self.assertEqual(args, ['/usr/bin/open','-a',str(self.app),'--',str(self.doc)])
                return subprocess.CompletedProcess(args, 0)
            req = json.loads(Path(args[2]).read_text())
            if req['op'] == 'inventory':
                data = {'status':'ok','documents':[] if len(calls) == 1 else [{'path':str(self.doc)}]}
            else:
                data = {'status':'ok','document':{'path':str(self.doc)}}
            kwargs['stdout'].write(json.dumps(data).encode())
            return subprocess.CompletedProcess(args, 0)
        with patch.object(native.subprocess, 'run', side_effect=run):
            result = self.adapter.call({'op':'inspect','path':str(self.doc)})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(sum(c[0] == '/usr/bin/open' for c in calls), 1)

    def test_invalid_response_is_unknown_for_mutation(self):
        def run(args, **kwargs):
            kwargs['stdout'].write(b'not-json')
            return subprocess.CompletedProcess(args, 0)
        with patch.object(native.subprocess, 'run', side_effect=run):
            result = self.adapter.call(self.create())
        self.assertTrue(result['error']['outcome_unknown'])

    def test_inventory_normalizes_paths_and_16_bit_native_colors(self):
        def run(args, **kwargs):
            value = {'status': 'ok', 'documents': [
                {'path':str(self.doc), 'canvases':[{'objects':[{'fill_rgb':[65535,0,32767.5]}]}]},
                {'path':'', 'canvases':[]}]}
            kwargs['stdout'].write(json.dumps(value).encode())
            return subprocess.CompletedProcess(args, 0)
        with patch.object(native.subprocess, 'run', side_effect=run):
            value = self.adapter.call({'op':'inventory'})
        self.assertEqual(value['documents'][0]['path'],str(self.doc.resolve()))
        self.assertEqual(value['documents'][1]['path'],'')
        self.assertEqual(value['documents'][0]['canvases'][0]['objects'][0]['fill_rgb'],[1,0,.5])


if __name__ == '__main__':
    unittest.main()
