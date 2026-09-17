"""Bounded data-only transport to the fixed OmniGraffle AppleScript adapter.

The caller owns serialization, journals, staging, fingerprints and authorization.
Timeout/error after dispatch is never proof that a mutation did not happen.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile
import time

SCRIPT = Path(__file__).with_suffix('.applescript')
APP_IDS = {'com.omnigroup.OmniGraffle7', 'com.omnigroup.OmniGraffle7.MacAppStore'}
MUTATIONS = {'create', 'update', 'close', 'export', 'save'}


def failure(code, message, unknown=False):
    return {'status': 'error', 'error': {'code': code, 'message': message,
                                       'outcome_unknown': unknown}}


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Expected a finite number between {low} and {high}')
    return value


def _string(value, limit=16384):
    if not isinstance(value, str) or '\x00' in value or len(value) > limit:
        raise ValueError('Invalid or oversized string')
    return value


def _keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('Unknown or missing request fields')


def _path(value, existing=True):
    p = Path(_string(value, 4096))
    if not p.is_absolute():
        raise ValueError('Paths must be absolute')
    p = p.resolve(strict=existing)
    if existing and not p.is_file():
        raise ValueError('Expected a regular file')
    if not existing and (p.exists() or not p.parent.is_dir()):
        raise ValueError('Destination must not exist and its parent must exist')
    return str(p)


def _id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('Native identifiers must be nonnegative integers')
    return value


def connector_points(a, b):
    """Intersect the center-to-center line with each rectangular boundary."""
    ax, ay = a['x'] + a['width'] / 2, a['y'] + a['height'] / 2
    bx, by = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        raise ValueError('Connector endpoints have identical centers')
    def distance(shape):
        return min(shape['width'] / (2 * abs(dx)) if dx else math.inf,
                   shape['height'] / (2 * abs(dy)) if dy else math.inf)
    ta, tb = distance(a), distance(b)
    if ta + tb >= 1:
        raise ValueError('Connector endpoint rectangles overlap or touch on their center line')
    return [[ax + dx * ta, ay + dy * ta], [bx - dx * tb, by - dy * tb]]


def _properties(props):
    _keys(props, {'x', 'y', 'width', 'height', 'text', 'font_size', 'font_name', 'fill', 'stroke'})
    for key in ('x', 'y'):
        if key in props:
            _number(props[key], -100000, 100000)
    for key in ('width', 'height'):
        if key in props:
            _number(props[key], .1, 100000)
    if 'font_size' in props:
        _number(props['font_size'], 1, 1000)
        if int(props['font_size']) != props['font_size']:
            raise ValueError('This native interface supports integer font sizes only')
    for key in ('text', 'font_name'):
        if key in props:
            _string(props[key])
    for key in ('fill', 'stroke'):
        if key in props:
            if not isinstance(props[key], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', props[key]):
                raise ValueError('Colors must be #RRGGBB')
            props['_' + key] = [int(props[key][i:i + 2], 16) * 257 for i in (1, 3, 5)]


def validate_request(request):
    """Return a normalized independent data object; never interpret label text."""
    r = copy.deepcopy(request)
    _keys(r, {'op', 'path', 'spec', 'changes', 'canvas_id', 'document_scope', 'format',
              'output', 'dpi', 'working_copy', 'discard'})
    op = r.get('op')
    fields = {
        'inventory': {'op'}, 'inspect': {'op', 'path'},
        'create': {'op', 'path', 'spec', 'working_copy'},
        'update': {'op', 'path', 'changes', 'working_copy'},
        'close': {'op', 'path', 'working_copy', 'discard'},
        'save': {'op', 'path', 'working_copy'},
        'export': {'op', 'path', 'canvas_id', 'document_scope', 'format', 'output', 'dpi', 'working_copy'},
    }
    if op not in fields or set(r) - fields[op]:
        raise ValueError('Unsupported operation or fields')
    if op != 'inventory':
        r['path'] = _path(r.get('path'), existing=op != 'create')
    if op in MUTATIONS and r.get('working_copy') is not True:
        raise ValueError('Mutations require an explicitly staged working_copy')
    if op == 'close' and not isinstance(r.get('discard', False), bool):
        raise ValueError('discard must be a Boolean')
    if op == 'create':
        _keys(r.get('spec'), {'canvases'}, {'canvases'})
        canvases = r['spec']['canvases']
        if not isinstance(canvases, list) or not 1 <= len(canvases) <= 32:
            raise ValueError('Expected 1 to 32 canvases')
        canvas_keys = set()
        total = 0
        for c in canvases:
            _keys(c, {'key', 'name', 'width', 'height', 'objects'}, {'key', 'name', 'width', 'height', 'objects'})
            key = _string(c['key'], 256)
            if not key or key in canvas_keys:
                raise ValueError('Duplicate or empty canvas key')
            canvas_keys.add(key)
            _string(c['name'], 256)
            for field in ('width', 'height'):
                _number(c[field], 1, 14400)
            if not isinstance(c['objects'], list):
                raise ValueError('objects must be a list')
            total += len(c['objects'])
            if total > 1000:
                raise ValueError('At most 1000 objects are supported')
            objects = {}
            grouped = set()
            for obj in c['objects']:
                _keys(obj, {'key', 'kind', 'x', 'y', 'width', 'height', 'text', 'font_size', 'font_name', 'fill', 'stroke', 'from', 'to', 'children'}, {'key', 'kind'})
                key = _string(obj['key'], 256)
                if not key or key in objects:
                    raise ValueError('Duplicate or empty object key')
                kind = obj['kind']
                if kind not in {'shape', 'text', 'connector', 'group'}:
                    raise ValueError('Unsupported object kind')
                props = {k: v for k, v in obj.items() if k not in {'key', 'kind', 'from', 'to', 'children'}}
                if kind in {'shape', 'text'} and not {'x', 'y', 'width', 'height'} <= props.keys():
                    raise ValueError('Shapes and text require geometry')
                if kind in {'connector', 'group'} and set(props) - {'stroke'}:
                    raise ValueError('Connector/group geometry is derived from endpoints/children')
                if kind != 'connector' and ('from' in obj or 'to' in obj):
                    raise ValueError('Only connectors have endpoints')
                if kind != 'group' and 'children' in obj:
                    raise ValueError('Only groups have children')
                _properties(props)
                obj.update(props)
                objects[key] = obj
            for obj in c['objects']:
                if obj['kind'] == 'connector':
                    for field in ('from', 'to'):
                        endpoint = obj.get(field)
                        if not isinstance(endpoint, str) or endpoint not in objects or objects[endpoint]['kind'] not in {'shape', 'text'}:
                            raise ValueError('Connector endpoints must reference shapes on the same canvas')
                    obj['_points'] = connector_points(objects[obj['from']], objects[obj['to']])
                if obj['kind'] == 'group':
                    children = obj.get('children')
                    if not isinstance(children, list) or len(children) < 2:
                        raise ValueError('Groups require at least two distinct leaf objects')
                    for child in children:
                        if not isinstance(child, str) or child not in objects or child in grouped or objects[child]['kind'] == 'group':
                            raise ValueError('Nested, shared, duplicate or missing group children are unsupported')
                        grouped.add(child)
    if op == 'update':
        changes = r.get('changes')
        if not isinstance(changes, list) or not 1 <= len(changes) <= 1000:
            raise ValueError('Expected 1 to 1000 changes')
        seen = set()
        for change in changes:
            _keys(change, {'canvas_id', 'object_id', 'set'}, {'canvas_id', 'object_id', 'set'})
            identity = (_id(change['canvas_id']), _id(change['object_id']))
            if identity in seen:
                raise ValueError('Duplicate update target')
            seen.add(identity)
            if not change['set']:
                raise ValueError('Empty update')
            _properties(change['set'])
    if op == 'export':
        if ('canvas_id' in r) == (r.get('document_scope') is True):
            raise ValueError('Select exactly one canvas_id or document_scope:true')
        if 'document_scope' in r and r['document_scope'] is not True:
            raise ValueError('document_scope must be true when supplied')
        if 'canvas_id' in r:
            _id(r['canvas_id'])
        if r.get('format') not in {'PDF', 'PNG', 'SVG'}:
            raise ValueError('Unsupported export format')
        r['output'] = _path(r.get('output'), existing=False)
        r['dpi'] = _number(r.get('dpi', 72), 36, 600)
    encoded = json.dumps(r, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) > 1024 * 1024:
        raise ValueError('Request exceeds 1 MiB')
    return r


class NativeAdapter:
    def __init__(self, app_path, timeout=30):
        self.app_path = Path(app_path).resolve()
        self.timeout = _number(timeout, 1, 180)

    def call(self, request):
        return self._call(request, time.monotonic() + self.timeout)

    def _call(self, request, deadline):
        try:
            normalized = validate_request(request)
            with (self.app_path / 'Contents/Info.plist').open('rb') as f:
                info = plistlib.load(f)
            if info.get('CFBundleIdentifier') not in APP_IDS:
                raise ValueError('Not a supported OmniGraffle application bundle')
        except (ValueError, TypeError, OSError, plistlib.InvalidFileException) as exc:
            return failure('invalid_request', str(exc))
        if normalized['op'] in {'inspect', 'update', 'export'}:
            inventory = self._call({'op': 'inventory'}, deadline)
            if inventory['status'] != 'ok':
                return inventory
            matches = [d for d in inventory.get('documents', [])
                       if d.get('path') and str(Path(d['path']).resolve()) == normalized['path']]
            if len(matches) > 1:
                return failure('ambiguous_document', 'Multiple documents have the requested canonical path')
            if not matches:
                try:
                    launch = subprocess.run(['/usr/bin/open', '-a', str(self.app_path), '--', normalized['path']],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            timeout=max(.001, deadline - time.monotonic()), check=False)
                except (OSError, subprocess.TimeoutExpired):
                    return failure('open_unknown', 'LaunchServices open did not return; inspect before retrying', True)
                if launch.returncode:
                    return failure('open_failed', 'LaunchServices could not open the document', True)
                # Poll only read-only identity queries; never repeat open/mutation.
                for attempt in range(5):
                    inventory = self._call({'op': 'inventory'}, deadline)
                    if inventory['status'] != 'ok':
                        return inventory
                    matches = [d for d in inventory.get('documents', [])
                               if d.get('path') and str(Path(d['path']).resolve()) == normalized['path']]
                    if len(matches) == 1:
                        break
                    if len(matches) > 1:
                        return failure('ambiguous_document', 'Multiple documents have the requested canonical path')
                    if attempt < 4:
                        time.sleep(min(.2, max(0, deadline - time.monotonic())))
                else:
                    return failure('open_unverified', 'Opened document identity could not be verified; inspect application dialogs', True)
        # Private files retain bounded stdout/stderr without unbounded PIPE reads.
        if time.monotonic() >= deadline:
            return failure('native_timeout', 'Deadline elapsed before native dispatch')
        with tempfile.TemporaryDirectory(prefix='omnigraffle-native-') as tmp:
            data = Path(tmp) / 'request.json'
            data.write_text(json.dumps(normalized, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            os.chmod(data, 0o600)
            with (Path(tmp) / 'stdout').open('w+b') as out, (Path(tmp) / 'stderr').open('w+b') as err:
                try:
                    result = subprocess.run(['/usr/bin/osascript', str(SCRIPT), str(data), str(self.app_path)],
                                            stdout=out, stderr=err, timeout=max(.001, deadline - time.monotonic()), check=False)
                except subprocess.TimeoutExpired:
                    return failure('native_timeout', 'Native result unknown; reconcile before another mutation', normalized['op'] in MUTATIONS)
                except OSError as exc:
                    return failure('native_unavailable', str(exc))
                if out.tell() > 4 * 1024 * 1024 or err.tell() > 65536:
                    return failure('native_output_limit', 'Native output exceeded bounds', normalized['op'] in MUTATIONS)
                out.seek(0)
                err.seek(0)
                if result.returncode:
                    return failure('native_error', err.read(4096).decode('utf-8', errors='replace'), normalized['op'] in MUTATIONS)
                try:
                    value = json.load(out)
                    if not isinstance(value, dict) or value.get('status') not in {'ok', 'error'}:
                        raise ValueError('Invalid native response envelope')
                    if value['status'] == 'error':
                        value.setdefault('error', {})['outcome_unknown'] = normalized['op'] in MUTATIONS
                    else:
                        # Foundation shortens /private/var to /var. Publish the
                        # same canonical spelling used by Python transactions.
                        documents = value.get('documents', [])
                        if 'document' in value:
                            documents = documents + [value['document']]
                        for doc in documents:
                            if doc.get('path'):
                                doc['path'] = str(Path(doc['path']).resolve())
                            for canvas in doc.get('canvases', []):
                                for obj in canvas.get('objects', []):
                                    for color_key in ('fill_rgb', 'stroke_rgb'):
                                        if color_key in obj:
                                            obj[color_key] = [component / 65535 for component in obj[color_key]]
                    return value
                except (ValueError, TypeError):
                    return failure('native_invalid_response', 'Native response was not valid JSON', normalized['op'] in MUTATIONS)
