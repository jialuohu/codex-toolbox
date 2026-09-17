#!/usr/bin/env python3
"""On-demand macOS sidebar recovery. No credentials or task bodies in receipts."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import uuid

ATOM = 'electron-persisted-atom-state'
LAYOUTS = 'sidebar-custom-sections-v3'
STATE = '.codex-global-state.json'
VERSION = 1


class Refusal(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def decode(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'Duplicate JSON key')
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def read(path):
    return decode(Path(path).read_bytes())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def atomic(path, raw):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_directory(path):
    path = Path(path).expanduser().absolute()
    require(not any(p.is_symlink() for p in [path, *path.parents]), 'Recovery directory contains a symlink')
    require(not any((p / '.git').exists() for p in [path, *path.parents]), 'Recovery artifacts must stay outside Git')
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    require(path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0,
            'Recovery directory must be owned by you with mode 700')
    return path


def identity(home):
    # Read only the account identifier into the result, never tokens or email.
    value = read(home / 'auth.json').get('tokens', {}).get('account_id')
    require(isinstance(value, str) and value, 'No cached account identity; establish the destination login first')
    return value


def running():
    result = subprocess.run(['ps', '-axo', 'comm='], check=True, capture_output=True, text=True)
    return any(line.strip().endswith(('/Contents/MacOS/ChatGPT',
                                     '/Contents/MacOS/Codex'))
               for line in result.stdout.splitlines())


def machine_id():
    result = subprocess.run(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                            check=True, capture_output=True, timeout=10)
    identifiers = [line.strip() for line in result.stdout.splitlines() if b'"IOPlatformUUID"' in line]
    require(len(identifiers) == 1, 'Cannot identify the sidebar Mac')
    return digest(identifiers[0])


def probe(host, paths):
    """Resolve paths and list task IDs on the explicitly bound project host."""
    require(host == 'local' or re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host), 'Invalid SSH alias')
    program = '''import hashlib,json,pathlib,sqlite3,subprocess
paths=INPUT_PATHS
raw=subprocess.check_output(['ioreg','-rd1','-c','IOPlatformExpertDevice'])
hardware=next(line.strip() for line in raw.splitlines() if b'"IOPlatformUUID"' in line)
result={'machine':hashlib.sha256(hardware).hexdigest(),'paths':{},'tasks':{}}
for path in paths:
 p=pathlib.Path(path)
 result['paths'][path]=str(p.resolve(strict=True)) if p.is_dir() else None
db=pathlib.Path.home()/'.codex/state_5.sqlite'
if db.exists():
 con=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
 try:
  con.execute('PRAGMA query_only=ON')
  for tid,cwd in con.execute('SELECT id,cwd FROM threads WHERE archived=0'):
   for path,canonical in result['paths'].items():
    if canonical and str(pathlib.Path(cwd).resolve())==canonical:
     result['tasks'].setdefault(path,[]).append(tid)
 finally: con.close()
else: result['tasks_unavailable']=True
print(json.dumps(result))
'''.replace('INPUT_PATHS', repr(paths))
    command = [sys.executable, '-'] if host == 'local' else ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--', host, 'python3 -']
    result = subprocess.run(command, input=program, capture_output=True, text=True, timeout=45)
    require(result.returncode == 0, 'Project-host path/task probe failed; check the selected Mac and read access')
    return decode(result.stdout)


def layouts(state):
    value = state.get(ATOM, {}).get(LAYOUTS, {})
    require(isinstance(value, dict), 'Unsupported account layout storage')
    return value


def sections(layout):
    require(isinstance(layout, dict) and isinstance(layout.get('sections', []), list), 'Unsupported section storage')
    result = layout.get('sections', [])
    ids = []
    for section in result:
        require(isinstance(section, dict) and isinstance(section.get('id'), str)
                and isinstance(section.get('name'), str) and isinstance(section.get('itemKeys'), list),
                'Unsupported section record')
        ids.append(section['id'])
    require(len(ids) == len(set(ids)), 'Duplicate section IDs')
    return result


def inventory(home):
    state = read(home / STATE)
    accounts = layouts(state)
    return {'schema': VERSION, 'device': platform.node(), 'device_id': machine_id(), 'codex_home': str(home),
            'active_account': identity(home), 'app_running': running(),
            'accounts': [{'id': key, 'sections': [{'id': s['id'], 'name': s['name'], 'items': len(s['itemKeys'])}
                                                for s in sections(value)]} for key, value in accounts.items()],
            'projects': [{k: p.get(k) for k in ('id', 'label', 'hostId', 'remotePath')}
                         for p in state.get('remote-projects', [])],
            'has_project_migrations': bool(state.get('app-server-projects-migration-by-host'))}


def get_slot(state, path):
    node = state
    for key in path[:-1]:
        node = node.get(key, {})
    return {'present': path[-1] in node, 'value': copy.deepcopy(node.get(path[-1]))}


def put_slot(state, path, value):
    node = state
    for key in path[:-1]:
        node = node.setdefault(key, {})
    if value['present']:
        node[path[-1]] = copy.deepcopy(value['value'])
    else:
        node.pop(path[-1], None)


def make_plan(state, source, target, old_host, new_host, evidence):
    require(source != target and old_host != new_host, 'Choose distinct account and host mappings')
    account_layouts = layouts(state)
    require(source in account_layouts, 'Source account layout is unavailable')
    source_sections = sections(account_layouts[source])
    target_sections = sections(account_layouts.get(target, {}))
    projects = state.get('remote-projects')
    require(isinstance(projects, list), 'Unsupported project storage')
    require(all(isinstance(p, dict) and all(isinstance(p.get(k), str) and p[k]
                for k in ('id', 'label', 'hostId', 'remotePath')) for p in projects), 'Unsupported project record')
    require(len({p['id'] for p in projects}) == len(projects), 'Duplicate project IDs')
    source_projects = [p for p in projects if p['hostId'] == old_host]
    require(source_projects, 'No projects for the selected source host')
    order = state.get('project-order', [])
    require(isinstance(order, list) and all(isinstance(v, str) for v in order), 'Unsupported project ordering')
    source_projects.sort(key=lambda p: order.index(p['id']) if p['id'] in order else len(order))
    after = copy.deepcopy(state)
    mapping, created, expected, actions = {}, [], [], []
    canonical_seen = set()
    touched = [['remote-projects'], ['project-order']]
    for old in source_projects:
        canonical = evidence['paths'].get(old['remotePath'])
        require(canonical, 'Missing or inaccessible source path: ' + old['remotePath'])
        require(canonical not in canonical_seen, 'Ambiguous source projects resolve to the same directory')
        canonical_seen.add(canonical)
        matches = [p for p in projects if p['hostId'] == new_host
                   and evidence['paths'].get(p['remotePath']) == canonical]
        require(len(matches) <= 1, 'Ambiguous destination projects resolve to the same directory')
        if matches:
            current = matches[0]
        else:
            allowed = {'id', 'label', 'hostId', 'remotePath'}
            require(set(old) <= allowed, 'Unknown source project fields; adapter update required')
            current = dict(old, id=str(uuid.uuid4()), hostId=new_host)
            after['remote-projects'].append(current)
            created.append(current['id'])
            after.setdefault('project-order', []).append(current['id'])
            for path in [['project-appearances', old['id']], [ATOM, 'sidebar-project-expanded-v1-codex:' + old['id']]]:
                value = get_slot(state, path)
                if value['present']:
                    new_path = [path[0], current['id'] if path[0] == 'project-appearances'
                                else 'sidebar-project-expanded-v1-codex:' + current['id']]
                    put_slot(after, new_path, value)
                    touched.append(new_path)
            owners = [s for s in source_sections if 'codex:project:' + old['id'] in s['itemKeys']]
            require(len(owners) <= 1, 'Source project belongs to multiple sections')
            if owners:
                owner = owners[0]
                require(sum(s['name'] == owner['name'] for s in source_sections) == 1,
                        'Ambiguous source section name: ' + owner['name'])
                candidates = [s for s in target_sections if s['name'] == owner['name']]
                require(len(candidates) <= 1, 'Ambiguous destination section name: ' + owner['name'])
                actions.append({'project_id': current['id'], 'section_name': owner['name'],
                                'section_id': candidates[0]['id'] if candidates else None})
        mapping[old['id']] = current['id']
        placements = [s for s in target_sections if 'codex:project:' + current['id'] in s['itemKeys']]
        require(len(placements) <= 1, 'Destination project has conflicting placements')
        expected.append({'id': current['id'], 'hostId': new_host, 'remotePath': current['remotePath'],
                         'canonical': canonical, 'task_ids': sorted(evidence.get('tasks', {}).get(old['remotePath'], [])),
                         'section_id': placements[0]['id'] if placements else None})
    changes = [{'path': path, 'before': get_slot(state, path), 'after': get_slot(after, path)}
               for path in touched if get_slot(state, path) != get_slot(after, path)]
    # Nonempty migration state can make the legacy cache non-authoritative.
    # A no-op audit remains useful, but never write through an unvalidated backend.
    if changes:
        legacy_writable(state)
    section_order = account_layouts[source].get('sectionOrder', [])
    def action_order(action):
        section = next(s for s in source_sections if s['name'] == action['section_name'])
        key = 'custom:' + section['id']
        group = section_order.index(key) if key in section_order else len(section_order) + source_sections.index(section)
        old_id = next(k for k, v in mapping.items() if v == action['project_id'])
        return group, section['itemKeys'].index('codex:project:' + old_id)
    actions.sort(key=action_order)
    return {'schema': VERSION, 'source_account': source, 'target_account': target,
            'old_host': old_host, 'new_host': new_host, 'source_layout': account_layouts[source],
            'target_layout': account_layouts.get(target),
            'machine': evidence['machine'], 'mapping': mapping, 'created': created,
            'changes': changes, 'expected': expected, 'app_actions': actions,
            'tasks_unavailable': evidence.get('tasks_unavailable', False)}


def legacy_writable(state):
    require(not state.get('app-server-projects-migration-by-host')
            and not state.get('app-server-project-id-by-legacy-project-id-by-host')
            and not state.get('app-server-pending-project-deletions-by-host'),
            'Unsupported app-server project migration: use owning project APIs; legacy writes refused')


def status(directory, phase, **extra):
    atomic(directory / 'status.json', encoded(dict(phase=phase, time=time.time(), **extra)))


def load_record(directory):
    directory = private_directory(directory)
    p = directory / 'plan.json'
    require(not p.is_symlink() and p.stat().st_uid == os.getuid() and p.stat().st_mode & 0o077 == 0,
            'Unsafe recovery record permissions')
    plan = read(p)
    require(plan.get('schema') == VERSION, 'Unsupported recovery record')
    require(read(directory / 'plan.sha256.json')['sha256'] == digest(p.read_bytes()), 'Recovery plan changed')
    allowed = {('remote-projects',), ('project-order',)}
    for pid in plan['created']:
        allowed.add(('project-appearances', pid))
        allowed.add((ATOM, 'sidebar-project-expanded-v1-codex:' + pid))
    changed_paths = [tuple(c['path']) for c in plan['changes']]
    require(len(changed_paths) == len(set(changed_paths)) and set(changed_paths) <= allowed,
            'Recovery record contains unsupported field changes')
    return directory, plan


def prepare(home, directory, source, old_host, new_host, project_host):
    path = home / STATE
    original = path.read_bytes()
    state = decode(original)
    target = identity(home)
    paths = sorted({p['remotePath'] for p in state.get('remote-projects', []) if p.get('hostId') in (old_host, new_host)})
    evidence = probe(project_host, paths)
    plan = make_plan(state, source, target, old_host, new_host, evidence)
    require(path.read_bytes() == original and identity(home) == target, 'State changed during preparation; inspect again')
    backup = path.with_name(path.name + '.bak')
    backup_raw = backup.read_bytes() if backup.exists() else None
    backup_state = decode(backup_raw) if backup_raw is not None else {}
    plan.update(codex_home=str(home), sidebar_device=platform.node(), sidebar_machine=machine_id(), project_host=project_host,
                prepared_at=time.time(), hashes={STATE: digest(original),
                STATE + '.bak': digest(backup_raw) if backup_raw is not None else None},
                backup_before=[{'path': c['path'], 'value': get_slot(backup_state, c['path'])} for c in plan['changes']])
    directory = private_directory(directory)
    require(not list(directory.iterdir()), 'Choose a new empty recovery directory')
    raw = encoded(plan)
    atomic(directory / 'plan.json', raw)
    atomic(directory / 'plan.sha256.json', encoded({'sha256': digest(raw)}))
    status(directory, 'prepared', additions=len(plan['created']), app_actions=len(plan['app_actions']))
    return {'phase': 'prepared', 'directory': str(directory), 'added_projects': len(plan['created']),
            'app_actions': plan['app_actions'], 'requires_app_exit': bool(plan['changes'])}


def guard(home, plan):
    require(platform.system() == 'Darwin', 'File repair supports macOS only')
    require(str(home) == plan['codex_home'] and machine_id() == plan['sidebar_machine'], 'Wrong sidebar device or Codex home')
    require(identity(home) == plan['target_account'], 'Active account changed')
    require(not running(), 'Close the affected desktop app; no process will be terminated')


def reverse_patch(state, plan):
    result = copy.deepcopy(state)
    for change in plan['changes']:
        current = get_slot(state, change['path'])
        require(current in (change['before'], change['after']), 'Later edits conflict with rollback: ' + '/'.join(change['path']))
        put_slot(result, change['path'], change['before'])
    return result


def transact(home, directory, rollback=False):
    _, plan = load_record(directory)
    if not plan['changes']:
        return transact_locked(home, directory, rollback)
    guard(home, plan)
    shared_lock = home / '.sidebar-recovery.lock'
    require(not shared_lock.is_symlink(), 'Unsafe shared lock')
    with os.fdopen(os.open(str(shared_lock), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return transact_locked(home, directory, rollback)


def transact_locked(home, directory, rollback=False):
    directory, plan = load_record(directory)
    lock_path = directory / 'operation.lock'
    require(not lock_path.is_symlink(), 'Unsafe lock path')
    with os.fdopen(os.open(str(lock_path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(str(home) == plan['codex_home'] and machine_id() == plan['sidebar_machine'], 'Wrong recovery target')
        require(identity(home) == plan['target_account'], 'Active account changed')
        if not plan['changes']:
            phase = 'metadata-rolled-back' if rollback else 'applied-unverified'
            status(directory, phase)
            return {'phase': phase, 'metadata_changes': 0}
        guard(home, plan)
        paths = [home / STATE, home / (STATE + '.bak')]
        require(not any(p.is_symlink() for p in paths), 'State files must not be symlinks')
        originals = {p.name: p.read_bytes() if p.exists() else None for p in paths}
        main = decode(originals[STATE])
        legacy_writable(main)
        require(layouts(main).get(plan['source_account']) == plan['source_layout'], 'Source account layout changed')
        if rollback:
            require((directory / 'journal.json').exists(), 'No applied transaction to roll back')
            journal = read(directory / 'journal.json')
            created_keys = {'codex:project:' + pid for pid in plan['created']}
            require(not any(created_keys.intersection(s['itemKeys']) for s in sections(layouts(main).get(plan['target_account'], {}))),
                    'Reverse native placement operations first; inspect their receipts')
            desired = {}
            for p in paths:
                raw = originals[p.name]
                if raw is None:
                    require(journal['before_hashes'][p.name] is None, 'State file disappeared')
                    desired[p.name] = None
                elif journal['before_hashes'][p.name] is None:
                    require(digest(raw) == journal['after_hashes'][p.name], 'New backup has subsequent edits')
                    desired[p.name] = None
                else:
                    rollback_plan = copy.deepcopy(plan)
                    if p.name.endswith('.bak'):
                        for change, item in zip(rollback_plan['changes'], journal['backup_before']):
                            require(change['path'] == item['path'], 'Invalid backup journal')
                            change['before'] = item['value']
                    result = reverse_patch(decode(raw), rollback_plan)
                    desired[p.name] = encoded(result)
        else:
            if (directory / 'journal.json').exists():
                journal = read(directory / 'journal.json')
                require(all(raw is not None and digest(raw) == journal['after_hashes'][name]
                            for name, raw in originals.items()), 'Interrupted or changed transaction; run rollback before preparing again')
                status(directory, 'applied-unverified')
                return {'phase': 'applied-unverified', 'metadata_changes': 0}
            require(layouts(main).get(plan['target_account']) == plan['target_layout'], 'Stale destination layout; prepare again')
            require(all(get_slot(main, c['path']) == c['before'] for c in plan['changes']), 'Stale preview; prepare again')
            require((originals[STATE + '.bak'] is None) == (plan['hashes'][STATE + '.bak'] is None), 'Backup presence changed')
            if originals[STATE + '.bak'] is not None:
                backup_now = decode(originals[STATE + '.bak'])
                require(all(get_slot(backup_now, c['path']) == c['value'] for c in plan['backup_before']), 'Stale backup fields')
            paths_to_probe = sorted({p['remotePath'] for p in plan['expected']})
            evidence = probe(plan['project_host'], paths_to_probe)
            require(evidence['machine'] == plan['machine'] and all(evidence['paths'].get(p['remotePath']) == p['canonical']
                    for p in plan['expected']), 'Project host or paths changed')
            after = copy.deepcopy(main)
            for change in plan['changes']:
                require(get_slot(after, change['path']) == change['before'], 'Stale planned field')
                put_slot(after, change['path'], change['after'])
            backup = decode(originals[STATE + '.bak']) if originals[STATE + '.bak'] is not None else copy.deepcopy(main)
            backup_before = [{'path': c['path'], 'value': get_slot(backup, c['path'])} for c in plan['changes']]
            for c in plan['changes']:
                put_slot(backup, c['path'], c['after'])
            desired = {STATE: encoded(after), STATE + '.bak': encoded(backup)}
            journal = {'before_hashes': {k: digest(v) if v is not None else None for k, v in originals.items()},
                       'after_hashes': {k: digest(v) for k, v in desired.items()},
                       'backup_before': backup_before}
            atomic(directory / 'journal.json', encoded(journal))
        status(directory, 'rollback-writing' if rollback else 'writing')
        # Two renames are NOT one atomic transaction. The durable journal makes
        # a partial commit recognizable and explicitly reversible after a crash.
        for p in reversed(paths):
            guard(home, plan)
            require((p.read_bytes() if p.exists() else None) == originals[p.name], 'State changed during commit')
            if desired[p.name] is None:
                if p.exists():
                    p.unlink()
            else:
                atomic(p, desired[p.name])
        require(all((p.read_bytes() if p.exists() else None) == desired[p.name] for p in paths), 'Commit readback failed')
        phase = 'metadata-rolled-back' if rollback else 'applied-unverified'
        status(directory, phase, app_reappeared=running(), native_actions_require_separate_verification=True)
        return {'phase': phase, 'app_actions': plan['app_actions'], 'native_rollback_required': rollback and bool(plan['app_actions'])}


def verify(home, directory, observations):
    directory, plan = load_record(directory)
    state = read(home / STATE)
    require(str(home) == plan['codex_home'] and identity(home) == plan['target_account']
            and machine_id() == plan['sidebar_machine'], 'Wrong verification target')
    require(layouts(state).get(plan['source_account']) == plan['source_layout'], 'Source layout changed')
    require(observations.get('account_id') == plan['target_account']
            and observations.get('sidebar_device') == plan['sidebar_device']
            and read(directory / 'status.json')['phase'] in ('applied-unverified', 'verified')
            and read(directory / 'status.json')['time'] <= observations.get('collected_at', 0) <= time.time() + 30,
            'Fresh owning-app observations are required')
    require(not plan['tasks_unavailable'], 'Task baseline unavailable; cannot fully verify')
    by_id = {p['id']: p for p in observations.get('projects', [])}
    ss = sections(layouts(state).get(plan['target_account'], {}))
    live_sections = sections({'sections': observations.get('sections', [])})
    all_tasks = set()
    for expected in plan['expected']:
        actual = by_id.get(expected['id'], {})
        require(all(actual.get(k) == expected[k] for k in ('hostId', 'remotePath')), 'Restored project absent from live app')
        require(set(expected['task_ids']) <= set(actual.get('task_ids', [])), 'Existing task association missing')
        all_tasks.update(expected['task_ids'])
        owners = [s for s in ss if 'codex:project:' + expected['id'] in s['itemKeys']]
        live_owners = [s for s in live_sections if 'codex:project:' + expected['id'] in s['itemKeys']]
        require([(s['id'], s['name']) for s in owners] == [(s['id'], s['name']) for s in live_owners],
                'Live app section placement differs from persisted state')
        actions = [a for a in plan['app_actions'] if a['project_id'] == expected['id']]
        if actions:
            a = actions[0]
            require(len(owners) == 1 and owners[0]['name'] == a['section_name']
                    and (a['section_id'] is None or owners[0]['id'] == a['section_id']), 'Restored section placement missing')
        else:
            require([s['id'] for s in owners] == ([expected['section_id']] if expected['section_id'] else []),
                    'Existing destination placement changed')
    require(not all_tasks or bool(all_tasks & set(observations.get('historical_task_reads', []))), 'Read one existing task through the owning app')
    status(directory, 'verified', projects=len(plan['expected']), tasks=len(all_tasks))
    return {'phase': 'verified', 'projects': len(plan['expected']), 'tasks': len(all_tasks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['inspect', 'prepare', 'apply', 'verify', 'rollback'])
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    parser.add_argument('--record', type=Path)
    parser.add_argument('--source-account')
    parser.add_argument('--old-host')
    parser.add_argument('--new-host')
    parser.add_argument('--project-host', help='Explicit SSH alias or local; bind both host IDs to this same Mac first')
    parser.add_argument('--observations', type=Path)
    parser.add_argument('--wait-seconds', type=int, default=0, help='Bounded wait for user to close the app, maximum 600 seconds')
    args = parser.parse_args()
    home = args.codex_home.expanduser().resolve()
    try:
        require(platform.system() == 'Darwin', 'This helper supports macOS only')
        if args.operation == 'inspect':
            result = inventory(home)
        else:
            require(args.record is not None, '--record is required')
            if args.operation == 'prepare':
                require(all([args.source_account, args.old_host, args.new_host, args.project_host]), 'Explicit source account and host mapping required')
                result = prepare(home, args.record, args.source_account, args.old_host, args.new_host, args.project_host)
            elif args.operation in ('apply', 'rollback'):
                require(0 <= args.wait_seconds <= 600, 'Wait must be between 0 and 600 seconds')
                if args.wait_seconds:
                    directory, _ = load_record(args.record)
                    status(directory, 'waiting-for-app-exit')
                    deadline = time.monotonic() + args.wait_seconds
                    while running() and time.monotonic() < deadline:
                        time.sleep(0.5)
                    if running():
                        status(directory, 'expired', configuration_changed=False)
                        raise Refusal('App-exit wait expired')
                result = transact(home, args.record, args.operation == 'rollback')
            else:
                require(args.observations is not None, '--observations from owning app tools is required')
                result = verify(home, args.record, read(args.observations))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (Refusal, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'phase': 'refused', 'reason': str(exc)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
