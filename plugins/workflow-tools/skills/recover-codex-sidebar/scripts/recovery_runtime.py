"""Read-only, bounded desktop compatibility and project-host evidence."""
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import selectors
import shutil
import struct
import subprocess
import sys
import tempfile
import time

class EvidenceError(ValueError):
    pass

def unique_json(raw):
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise EvidenceError("Duplicate JSON key")
            d[k] = v
        return d
    return json.loads(raw, object_pairs_hook=pairs)

def hardware_id():
    raw = subprocess.check_output(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'], timeout=10)
    lines = [x.strip() for x in raw.splitlines() if b'"IOPlatformUUID"' in x]
    if len(lines) != 1:
        raise EvidenceError("Physical Mac identity unavailable")
    return hashlib.sha256(lines[0]).hexdigest()

def desktop(app_path=None):
    candidates = [Path(app_path)] if app_path else [
        p for p in (Path('/Applications/ChatGPT.app'), Path('/Applications/Codex.app')) if p.exists()]
    if len(candidates) != 1:
        raise EvidenceError("Select one installed desktop with --app-path")
    app = candidates[0].resolve()
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    with (app / 'Contents/Resources/app.asar').open('rb') as f:
        raw_header = f.read(16)
        if len(raw_header) != 16:
            raise EvidenceError('Incomplete desktop archive header')
        header = struct.unpack('<4I', raw_header)
        if header[3] > 16 * 1024 * 1024:
            raise EvidenceError("Unsupported desktop archive header")
        tree = unique_json(f.read(header[3]))
        files = tree['files']['.vite']['files']['build']['files']
        main = [k for k in files if k.startswith('main-') and k.endswith('.js')]
        if len(main) != 1:
            raise EvidenceError("Unsupported desktop implementation layout")
        entry = files[main[0]]
        if entry.get('unpacked') or entry['size'] > 64 * 1024 * 1024:
            raise EvidenceError("Unsupported desktop implementation size")
        f.seek(8 + header[1] + int(entry['offset']))
        raw = f.read(entry['size'])
        if len(raw) != entry['size']:
            raise EvidenceError("Incomplete desktop implementation")
    return {'app_path': str(app), 'bundle_id': info['CFBundleIdentifier'],
            'version': info['CFBundleShortVersionString'], 'build': info['CFBundleVersion'],
            'implementation_sha256': hashlib.sha256(raw).hexdigest()}

def compatibility(state, home, app):
    profiles = unique_json((Path(__file__).parent.parent / 'references/desktop-profiles.json').read_bytes())
    keys = ('bundle_id', 'version', 'build', 'implementation_sha256')
    matches = [p for p in profiles['profiles'] if all(p[k] == app.get(k) for k in keys)]
    if len(matches) != 1:
        return {'supported': False, 'reason': 'unsupported_desktop_build'}
    local_namespace = 'local:' + str(home)
    for key in ('app-server-projects-migration-by-host',
                'app-server-project-id-by-legacy-project-id-by-host',
                'app-server-pending-project-deletions-by-host'):
        value = state.get(key, {})
        if value is None:
            continue
        if not isinstance(value, dict):
            return {'supported': False, 'reason': 'unknown_migration_ownership'}
        if any(owner != local_namespace and data for owner, data in value.items()):
            return {'supported': False, 'reason': 'target_or_unknown_host_migration'}
    return {'supported': True, 'adapter': matches[0]['adapter'], 'profile': matches[0]['id']}

def connection_binding(state, host_id, ssh_alias):
    """Use the audited client's saved SSH connection, never an imported host ID."""
    if ssh_alias == 'local':
        raise EvidenceError('local is reserved for same-Mac inspection, not a remote destination')
    connections = state.get('codex-managed-remote-connections', [])
    if not isinstance(connections, list):
        raise EvidenceError('Unsupported client connection storage')
    matches = [c for c in connections if isinstance(c, dict) and c.get('hostId') == host_id]
    if len(matches) != 1:
        raise EvidenceError('Destination connection is absent or ambiguous in the sidebar client')
    c = matches[0]
    # This profile covers discovered SSH entries using the login environment.
    # Custom connection commands/homes require another audited adapter.
    if c.get('source') != 'discovered' or c.get('alias') != ssh_alias or host_id != 'remote-ssh-discovered:' + ssh_alias:
        raise EvidenceError('Select the saved discovered SSH connection matching the project host')
    allowed = {'hostId', 'displayName', 'source', 'alias', 'hostname', 'sshPort', 'identity', 'connectionAnalyticsId'}
    if set(c) - allowed or any(c.get(k) for k in ('hostname', 'sshPort', 'identity')):
        raise EvidenceError('Custom connection configuration needs a validated adapter')
    return {k: c.get(k) for k in ('hostId', 'source', 'alias', 'hostname', 'sshPort', 'identity')}

class ReadOnlyRPC:
    METHODS = {'initialize', 'config/read', 'project/list', 'thread/list'}
    def __init__(self, cli):
        self.stderr = tempfile.TemporaryFile()
        self.proc = subprocess.Popen([cli, 'app-server', '--listen', 'stdio://'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.buffer = b''
        self.counter = 0
    def send(self, message):
        self.proc.stdin.write((json.dumps(message) + '\n').encode())
        self.proc.stdin.flush()
    def request(self, method, params):
        if method not in self.METHODS:
            raise EvidenceError("Mutation is not permitted by the evidence client")
        self.counter += 1
        request_id = self.counter
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                msg = unique_json(line)
                if msg.get('id') != request_id:
                    continue
                if 'error' in msg:
                    raise EvidenceError("Read-only API request failed: " + method)
                return msg['result']
            if not self.selector.select(max(0, deadline - time.monotonic())):
                break
            data = os.read(self.proc.stdout.fileno(), 65536)
            if not data:
                break
            self.buffer += data
            if len(self.buffer) > 32 * 1024 * 1024:
                raise EvidenceError("API response exceeded evidence limit")
        raise EvidenceError("Read-only API response unavailable: " + method)
    def close(self):
        try:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Only the disposable inspection process, never an existing server.
                self.proc.terminate()
                self.proc.wait(timeout=5)
        finally:
            self.selector.close()
            self.proc.stdout.close()
            self.stderr.close()

def probe_local(paths):
    cli = shutil.which('codex')
    if not cli:
        raise EvidenceError("Codex CLI unavailable in project-host login environment")
    rpc = ReadOnlyRPC(cli)
    started = time.monotonic()
    try:
        init = rpc.request('initialize', {'clientInfo': {'name': 'sidebar_recovery_evidence', 'version': '2'},
                                        'capabilities': {'experimentalApi': True}})
        rpc.send({'method': 'initialized'})
        home = init.get('codexHome')
        if not isinstance(home, str) or not Path(home).is_absolute():
            raise EvidenceError("Connection did not report its actual Codex home")
        config = rpc.request('config/read', {'includeLayers': False})['config']
        if not isinstance(config, dict):
            raise EvidenceError('Unsupported configuration API response')
        trust = config.get('projects', {})
        if not isinstance(trust, dict):
            raise EvidenceError('Unsupported effective folder-trust response')
        result = {'machine': hardware_id(), 'codex_home': home, 'paths': {}, 'tasks': {},
                  'server_task_assignments': {},
                  'tasks_complete': False, 'server_projects': [], 'server_inventory_complete': False}
        for path in paths:
            p = Path(path)
            if not p.is_absolute() or not p.is_dir():
                result['paths'][path] = None
                continue
            canonical = p.resolve(strict=True)
            st = canonical.stat()
            selected_trust, resolved_trust = trust.get(str(p), {}), trust.get(str(canonical), {})
            if not isinstance(selected_trust, dict) or not isinstance(resolved_trust, dict):
                raise EvidenceError('Unsupported folder-trust entry')
            effective = resolved_trust.get('trust_level')
            # Require consent for both the selected registration and resolved folder.
            if selected_trust.get('trust_level') != 'trusted':
                effective = None
            result['paths'][path] = {'canonical': str(canonical), 'file_id': [st.st_dev, st.st_ino],
                'trust': effective}
        # Optional server inventory remains separate from client registrations.
        cursor, seen = None, set()
        try:
            for _ in range(100):
                if time.monotonic() - started > 120:
                    raise EvidenceError("Evidence collection deadline")
                page = rpc.request('project/list', {'cursor': cursor, 'limit': 100})
                for p in page['data']:
                    result['server_projects'].append({'id': p['id'], 'name': p['name'],
                                                      'roots': [x['path'] for x in p['roots']]})
                cursor = page.get('nextCursor')
                if cursor is None:
                    result['server_inventory_complete'] = True
                    break
                if cursor in seen:
                    raise EvidenceError("Repeated inventory cursor")
                seen.add(cursor)
        except EvidenceError:
            result['server_inventory_complete'] = False
        cursor, seen = None, set()
        task_ids = set()
        inventory = {'scope': 'unarchived_all_sources_all_providers', 'pages': 0,
                     'tasks_seen': 0, 'complete': False, 'reason': 'page_limit'}
        result['task_inventory'] = inventory
        try:
            for _ in range(200):
                if time.monotonic() - started > 120:
                    raise EvidenceError('task_inventory_deadline')
                # Defaults omit noninteractive sources and may repair rollout metadata.
                page = rpc.request('thread/list', {'cursor': cursor, 'limit': 100, 'archived': False,
                    'useStateDbOnly': True, 'modelProviders': [],
                    'sourceKinds': ['cli', 'vscode', 'exec', 'appServer', 'subAgent', 'subAgentReview',
                                    'subAgentCompact', 'subAgentThreadSpawn', 'subAgentOther', 'unknown']})
                if (not isinstance(page, dict) or not isinstance(page.get('data'), list)
                        or 'nextCursor' not in page
                        or (page['nextCursor'] is not None
                            and (not isinstance(page['nextCursor'], str) or not page['nextCursor']))):
                    raise EvidenceError('invalid_task_page')
                inventory['pages'] += 1
                for task in page['data']:
                    if (not isinstance(task, dict) or not isinstance(task.get('id'), str)
                            or not task['id'] or 'projectId' not in task
                            or (task['projectId'] is not None and not isinstance(task['projectId'], str))):
                        raise EvidenceError('invalid_task_metadata')
                    if task['id'] in task_ids:
                        raise EvidenceError('duplicate_task_id')
                    task_ids.add(task['id'])
                    inventory['tasks_seen'] = len(task_ids)
                    cwd = task.get('cwd')
                    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
                        continue
                    canonical = str(Path(cwd).resolve())
                    for path, info in result['paths'].items():
                        if info and info['canonical'] == canonical:
                            result['tasks'].setdefault(path, []).append(task['id'])
                            result['server_task_assignments'][task['id']] = task.get('projectId')
                cursor = page.get('nextCursor')
                if cursor is None:
                    result['tasks_complete'] = True
                    inventory.update(complete=True, reason=None)
                    break
                if cursor in seen:
                    raise EvidenceError('repeated_task_cursor')
                seen.add(cursor)
        except EvidenceError as exc:
            result['tasks_complete'] = False
            # Do not persist arbitrary API errors, which may contain private data.
            known = {'task_inventory_deadline', 'invalid_task_page', 'invalid_task_metadata',
                     'duplicate_task_id', 'repeated_task_cursor'}
            inventory['reason'] = str(exc) if str(exc) in known else 'task_api_unavailable'
        for path in result['tasks']:
            result['tasks'][path] = sorted(set(result['tasks'][path]))
        return result
    finally:
        rpc.close()

def probe(host, paths):
    if host == 'local':
        return probe_local(paths)
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host):
        raise EvidenceError("Invalid explicitly selected SSH alias")
    # Send reviewed code, not a command from a snapshot or remote metadata.
    marker = 'CODEX_SIDEBAR_EVIDENCE:'
    program = Path(__file__).read_text() + '\nprint(' + repr(marker) + ' + json.dumps(probe_local(' + repr(paths) + ')))\n'
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--',
                             host, "/bin/zsh -lc 'python3 -'"],
                            input=program, text=True, encoding='utf-8', capture_output=True, timeout=150)
    if result.returncode:
        raise EvidenceError("Project-host evidence probe failed; verify connection and CLI availability")
    payloads = [line[len(marker):] for line in result.stdout.splitlines() if line.startswith(marker)]
    if len(payloads) != 1:
        raise EvidenceError('Project-host evidence framing failed; check login-shell output')
    try:
        return unique_json(payloads[0])
    except (ValueError, TypeError) as exc:
        raise EvidenceError('Project-host evidence JSON is invalid') from exc
