#!/usr/bin/env python3
"""Scoped macOS remote-sidebar recovery with portable layouts and durable receipts."""
import argparse
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import legacy_sidebar as legacy
import recovery_runtime as runtime

VERSION = 2
STATE, ATOM, LAYOUTS = legacy.STATE, legacy.ATOM, legacy.LAYOUTS
Refusal = legacy.Refusal
require, read, encoded, atomic, digest = legacy.require, legacy.read, legacy.encoded, legacy.atomic, legacy.digest
MAX_RECORD = 8 * 1024 * 1024

def fingerprint(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))

def private_read(path):
    path = Path(path).expanduser().absolute()
    require(not any(p.is_symlink() for p in [path, *path.parents]), 'Private input contains a symlink')
    st = path.stat()
    require(st.st_uid == os.getuid() and not st.st_mode & 0o077 and st.st_size <= MAX_RECORD,
            'Private input must be owned, mode 600, and within size limit')
    return read(path)

def private_write(path, data):
    path = Path(path).expanduser().absolute()
    legacy.private_directory(path.parent)
    require(not path.exists() and not path.is_symlink(), 'Choose a new private output file')
    atomic(path, encoded(data))

def save_status(directory, phase, **extra):
    legacy.status(directory, phase, **extra)

def sections(state, account):
    return legacy.sections(legacy.layouts(state).get(account, {}))

def owner(state, account, pid):
    owners = [s for s in sections(state, account) if 'codex:project:' + pid in s['itemKeys']]
    pinned = state.get('pinned-project-ids', [])
    require(isinstance(pinned, list) and all(isinstance(p, str) for p in pinned), 'Unsupported pinned project storage')
    if pid in pinned:
        owners.append({'id': 'pinned', 'name': 'Pinned', 'itemKeys': ['codex:project:' + p for p in pinned]})
    require(len(owners) <= 1, 'Conflicting destination section placement')
    return owners[0] if owners else None

def registrations(state):
    ps = state.get('remote-projects', [])
    require(isinstance(ps, list), 'Unsupported remote registry')
    for p in ps:
        require(isinstance(p, dict) and set(p) == {'id', 'label', 'hostId', 'remotePath'}
                and all(isinstance(v, str) and v for v in p.values())
                and Path(p['remotePath']).is_absolute(), 'Unsupported remote registration')
    require(len({p['id'] for p in ps}) == len(ps), 'Duplicate registration IDs')
    return ps

def source_view(state, account, host, section_ids=None):
    ps = [p for p in registrations(state) if p['hostId'] == host]
    require(ps, 'No projects for selected source connection')
    order = state.get('project-order', [])
    require(isinstance(order, list) and all(isinstance(x, str) for x in order), 'Unsupported project order')
    ps.sort(key=lambda p: order.index(p['id']) if p['id'] in order else len(order))
    ss = sections(state, account)
    if section_ids is not None:
        ss = [s for s in ss if s['id'] in section_ids]
    require(account in legacy.layouts(state), 'Selected source layout is unavailable')
    so = legacy.layouts(state)[account].get('sectionOrder', [])
    require(isinstance(so, list), 'Unsupported section order')
    ss = sorted(ss, key=lambda s: so.index('custom:' + s['id']) if 'custom:' + s['id'] in so else len(so) + ss.index(s))
    ids = {p['id'] for p in ps}
    # Only selected source project memberships: same-account additions do not invalidate it.
    source_sections = [{'id': s['id'], 'name': s['name'],
                        'items': [x for x in s['itemKeys'] if x.startswith('codex:project:') and x[14:] in ids]}
                       for s in ss]
    pinned = state.get('pinned-project-ids', [])
    require(isinstance(pinned, list) and all(isinstance(p, str) for p in pinned), 'Unsupported pinned project storage')
    return {'projects': copy.deepcopy(ps), 'sections': source_sections, 'pinned': [p for p in pinned if p in ids],
            'appearances': {p['id']: legacy.get_slot(state, ['project-appearances', p['id']]) for p in ps},
            'expanded': {p['id']: legacy.get_slot(state, [ATOM, 'sidebar-project-expanded-v1-codex:' + p['id']]) for p in ps}}

def appearance(value):
    # Appearance is data; accept only the desktop's documented scalar/marker shape.
    require(value is None or isinstance(value, dict), 'Unsupported project appearance')
    if value is None:
        return None
    require(set(value) <= {'color', 'marker', 'icon'}, 'Unsupported appearance fields')
    if 'color' in value:
        require(isinstance(value['color'], str) and len(value['color']) <= 80, 'Invalid appearance color')
    if 'icon' in value:
        require(isinstance(value['icon'], str) and len(value['icon']) <= 120, 'Invalid appearance icon')
    if 'marker' in value:
        m = value['marker']
        require(isinstance(m, dict) and set(m) <= {'kind', 'icon', 'emoji'}
                and m.get('kind') in ('icon', 'emoji') and all(isinstance(v, str) and len(v) <= 120 for v in m.values()),
                'Unsupported appearance marker')
    return copy.deepcopy(value)

def validate_layout(data):
    require(isinstance(data, dict) and set(data) == {'schema', 'kind', 'provenance', 'projects', 'sections'}
            and data['schema'] == VERSION and data['kind'] == 'sidebar-layout', 'Unsupported layout snapshot')
    provenance = data['provenance']
    require(isinstance(provenance, dict) and set(provenance) == {'source_machine', 'project_machine', 'captured_at'}
            and all(isinstance(provenance[k], str) and len(provenance[k]) == 64 for k in ('source_machine', 'project_machine'))
            and isinstance(provenance['captured_at'], (int, float)), 'Invalid layout provenance')
    ss, ps = data['sections'], data['projects']
    require(isinstance(ss, list) and len(ss) <= 500 and isinstance(ps, list) and 0 < len(ps) <= 5000, 'Invalid layout size')
    require(all(isinstance(s, dict) and set(s) == {'key', 'name'}
                and isinstance(s['key'], str) and s['key'] != '@pinned'
                and isinstance(s['name'], str) and 0 < len(s['name']) <= 200 for s in ss),
            'Invalid portable section')
    require(len({s['key'] for s in ss}) == len(ss) and len({s['name'] for s in ss}) == len(ss),
            'Ambiguous portable sections')
    require(all(isinstance(p, dict) and set(p) == {'key', 'path', 'label', 'section', 'section_position', 'appearance', 'expanded'}
                and isinstance(p['key'], str) and isinstance(p['path'], str) and Path(p['path']).is_absolute()
                and '\x00' not in p['path'] and isinstance(p['label'], str) and 0 < len(p['label']) <= 500
                and (p['section'] in (None, '@pinned') or p['section'] in {s['key'] for s in ss})
                and isinstance(p['section_position'], int) and p['section_position'] >= 0
                and (p['expanded'] is None or isinstance(p['expanded'], bool)) for p in ps), 'Invalid portable project')
    require(len({p['key'] for p in ps}) == len(ps) and len({p['path'] for p in ps}) == len(ps), 'Duplicate portable project')
    for p in ps:
        appearance(p['appearance'])
    return data

def export_data(state, account, host, evidence, source_machine):
    view = source_view(state, account, host)
    ss = [{'key': 's' + str(i), 'name': s['name']} for i, s in enumerate(view['sections'])]
    ps = []
    for i, p in enumerate(view['projects']):
        memberships = [(j, s['items'].index('codex:project:' + p['id']))
                       for j, s in enumerate(view['sections']) if 'codex:project:' + p['id'] in s['items']]
        require(len(memberships) + int(p['id'] in view['pinned']) <= 1, 'Ambiguous source placement')
        a, e = view['appearances'][p['id']], view['expanded'][p['id']]
        ps.append({'key': 'p' + str(i), 'path': p['remotePath'], 'label': p['label'],
                   'section': '@pinned' if p['id'] in view['pinned'] else ss[memberships[0][0]]['key'] if memberships else None,
                   'section_position': view['pinned'].index(p['id']) if p['id'] in view['pinned'] else memberships[0][1] if memberships else i,
                   'appearance': appearance(a['value']) if a['present'] else None,
                   'expanded': e['value'] if e['present'] else None})
    return validate_layout({'schema': VERSION, 'kind': 'sidebar-layout',
        'provenance': {'source_machine': source_machine, 'project_machine': evidence['machine'], 'captured_at': time.time()},
        'projects': ps, 'sections': ss})

def task_choices(state, tids):
    assignments = state.get('thread-project-assignments', {}) or {}
    projectless = state.get('projectless-thread-ids', []) or []
    require(isinstance(assignments, dict) and isinstance(projectless, list), 'Unsupported task choice storage')
    return {tid: {'assignment': copy.deepcopy(assignments.get(tid)), 'projectless': tid in projectless} for tid in sorted(tids)}

def destination_view(state, target, hosts, paths):
    ps = [p for p in registrations(state) if p['hostId'] in hosts and p['remotePath'] in paths]
    ss = sections(state, target)
    return {'projects': ps, 'placements': {p['id']: (owner(state, target, p['id']) or {}).get('id') for p in ps},
            'section_names': [[s['id'], s['name']] for s in ss],
            'appearances': {p['id']: legacy.get_slot(state, ['project-appearances', p['id']]) for p in ps}}

def make_plan(state, layout, target, new_host, aliases, evidence):
    validate_layout(layout)
    require(layout['provenance']['project_machine'] == evidence['machine'], 'Layout belongs to a different project Mac')
    require(isinstance(new_host, str) and new_host and new_host != 'local', 'Select a remote destination connection')
    ps = registrations(state)
    ss = sections(state, target)
    require(len({s['name'] for s in ss}) == len(ss), 'Ambiguous destination section names')
    host_set = set(aliases) | {new_host}
    selected_paths = {p['path'] for p in layout['projects']}
    native, creations, expected = [], [], []
    section_by_key = {s['key']: s for s in layout['sections']}
    seen_paths, seen_files = set(), set()
    for source in layout['projects']:
        info = evidence['paths'].get(source['path'])
        require(info is not None, 'Missing or inaccessible source path: ' + source['path'])
        canonical, file_id = info['canonical'], tuple(info['file_id'])
        require(canonical not in seen_paths and file_id not in seen_files, 'Ambiguous source filesystem identity')
        seen_paths.add(canonical); seen_files.add(file_id)
        def matches(p):
            other = evidence['paths'].get(p['remotePath'])
            return other and (other['canonical'] == canonical or tuple(other['file_id']) == file_id)
        current = [p for p in ps if p['hostId'] == new_host and matches(p)]
        require(len(current) <= 1, 'Ambiguous destination project identity')
        old = [p for p in ps if p['hostId'] in aliases
               and p['hostId'] != new_host and matches(p)]
        alias_choices = [(p['label'], (owner(state, target, p['id']) or {}).get('id'),
                          legacy.get_slot(state, ['project-appearances', p['id']])) for p in old]
        require(current or not alias_choices or all(c == alias_choices[0] for c in alias_choices), 'Conflicting destination alias choices')
        chosen_section = None
        if current:
            project = current[0]
            chosen_section = owner(state, target, project['id'])
        else:
            reference = old[0] if old else None
            chosen_section = owner(state, target, reference['id']) if reference else None
            placement_known = reference is not None and (target in legacy.layouts(state) or chosen_section is not None)
            if not placement_known and source['section'] == '@pinned':
                chosen_section = {'id': 'pinned', 'name': 'Pinned'}
            elif not placement_known and source['section'] is not None:
                group = section_by_key[source['section']]
                chosen_section = next((s for s in ss if s['name'] == group['name']), {'id': None, 'name': group['name']})
            project = {'id': str(uuid.uuid4()), 'label': reference['label'] if reference else source['label'],
                       'hostId': new_host, 'remotePath': source['path']}
            a = legacy.get_slot(state, ['project-appearances', reference['id']]) if reference else {'present': False}
            e = legacy.get_slot(state, [ATOM, 'sidebar-project-expanded-v1-codex:' + reference['id']]) if reference else {'present': False}
            creations.append({'project': project, 'appearance': a.get('value') if reference else source['appearance'],
                              'expanded': e.get('value') if reference else source['expanded']})
            if chosen_section:
                native.append({'id': 'place:' + project['id'], 'kind': 'place-project', 'project_id': project['id'],
                               'section_id': chosen_section['id'], 'section_name': chosen_section['name'],
                               'position': source['section_position']})
        candidates = evidence.get('tasks', {}).get(source['path'], [])
        choices = task_choices(state, candidates)
        eligible = [tid for tid in candidates if choices[tid]['assignment'] is None and not choices[tid]['projectless']
                    and evidence.get('server_task_assignments', {}).get(tid) is None]
        expected.append({'id': project['id'], 'hostId': new_host, 'remotePath': project['remotePath'],
                         'registration': copy.deepcopy(project),
                         'canonical': canonical, 'file_id': list(file_id), 'candidate_task_ids': sorted(eligible),
                         'preserved_task_choices': choices, 'section_id': chosen_section['id'] if chosen_section else None,
                         'section_name': chosen_section['name'] if chosen_section else None})
    # New empty groups from an explicitly selected portable layout are included.
    requested = {a['section_name'] for a in native if a['section_id'] is None}
    for s in layout['sections']:
        if not any(p['section'] == s['key'] for p in layout['projects']) and not any(t['name'] == s['name'] for t in ss):
            requested.add(s['name'])
    creates = [{'id': 'section:' + s['key'], 'kind': 'create-section', 'section_name': s['name']}
               for s in layout['sections'] if s['name'] in requested]
    rank = {s['name']: i for i, s in enumerate(layout['sections'])}
    native.sort(key=lambda a: (rank.get(a['section_name'], len(rank)), a['position']))
    tasks = {t for p in expected for t in p['preserved_task_choices']}
    trust = [{'path': c['project']['remotePath'], 'reason': 'folder_consent_required'}
             for c in creations if evidence['paths'][c['project']['remotePath']].get('trust') != 'trusted']
    return {'schema': VERSION, 'adapter': 'client-remote-registry-v2', 'target_account': target,
            'new_host': new_host, 'aliases': list(aliases), 'layout': layout, 'created': creations, 'expected': expected,
            'native_actions': creates + native, 'trust_blockers': trust, 'tasks_complete': evidence.get('tasks_complete', False),
            'server_task_assignments': {t: evidence.get('server_task_assignments', {}).get(t) for t in tasks},
            'task_choices': task_choices(state, tasks), 'source_paths': sorted(selected_paths),
            'destination_guard': destination_view(state, target, host_set, set(evidence['paths']))}

def inspect(home, project_host=None, app_path=None, summary=False, connection_host=None):
    state = read(home / STATE)
    app, profile = None, {'supported': False, 'reason': 'desktop_unavailable'}
    try:
        app = runtime.desktop(app_path)
        profile = runtime.compatibility(state, home, app)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        profile['reason'] = 'desktop_evidence_unavailable'
    try:
        projects = registrations(state)
        registrations_supported = True
    except (ValueError, KeyError, TypeError):
        projects, registrations_supported = [], False
    try:
        accounts = legacy.layouts(state)
        layouts_supported = True
    except (ValueError, KeyError, TypeError, AttributeError):
        accounts, layouts_supported = {}, False
    result = {'schema': VERSION, 'app_running': legacy.running(), 'compatibility': profile,
              'desktop': app, 'remote_registration_count': len(state.get('remote-projects', [])) if isinstance(state.get('remote-projects', []), list) else None,
              'registrations_supported': registrations_supported, 'layouts_supported': layouts_supported,
              'layout_count': len(accounts) if layouts_supported else None, 'server_inventory': None}
    if project_host and registrations_supported:
        hosts = {p['hostId'] for p in projects}
        require(connection_host in hosts or len(hosts) <= 1,
                'Select --old-host for the registration batch before probing a project Mac')
        selected = connection_host or next(iter(hosts), None)
        paths = sorted({p['remotePath'] for p in projects if p['hostId'] == selected})
        evidence = runtime.probe(project_host, paths)
        result['server_inventory'] = {'count': len(evidence['server_projects']),
            'complete': evidence['server_inventory_complete'], 'tasks_complete': evidence['tasks_complete']}
        result['trust_counts'] = {'trusted': sum(bool(x and x.get('trust') == 'trusted') for x in evidence['paths'].values()),
                                  'other': sum(not x or x.get('trust') != 'trusted' for x in evidence['paths'].values())}
        if not summary:
            result['project_host'] = {'machine': evidence['machine'], 'codex_home': evidence['codex_home'],
                                      'selected_connection': selected, 'paths': evidence['paths']}
    if not summary:
        result.update(sidebar_machine=legacy.machine_id(), codex_home=str(home),
                      active_account=legacy.identity(home), accounts=list(accounts),
                      projects=projects,
                      connections=[{k: c.get(k) for k in ('hostId', 'source', 'alias')}
                                   for c in (state.get('codex-managed-remote-connections') or []) if isinstance(c, dict)])
    elif app:
        result['desktop'] = {k: app[k] for k in ('version', 'build')}
    return result

def prepare(home, directory, source_account=None, old_host=None, new_host=None, project_host=None,
            source_layout=None, aliases=(), app_path=None):
    original = (home / STATE).read_bytes()
    state, target = legacy.decode(original), legacy.identity(home)
    require(project_host and new_host, 'Explicit project host and destination connection are required')
    aliases = list(dict.fromkeys([*aliases, *([old_host] if old_host else [])]))
    source = None
    if source_layout:
        require(not source_account and not old_host, 'Choose either portable or local source')
        layout = validate_layout(private_read(source_layout))
        source_paths = [p['path'] for p in layout['projects']]
    else:
        require(source_account and old_host, 'Select a source account and connection')
        view = source_view(state, source_account, old_host)
        source = {'account': source_account, 'host': old_host, 'sha256': fingerprint(view),
                  'section_ids': [s['id'] for s in view['sections']]}
        source_paths = [p['remotePath'] for p in view['projects']]
    paths = sorted(set(source_paths) | {p['remotePath'] for p in registrations(state) if p['hostId'] in set(aliases) | {new_host}})
    connection = runtime.connection_binding(state, new_host, project_host)
    evidence = runtime.probe(project_host, paths)
    if not source_layout:
        layout = export_data(state, source_account, old_host, evidence, legacy.machine_id())
    app = runtime.desktop(app_path)
    compatibility = runtime.compatibility(state, home, app)
    require(compatibility['supported'], compatibility.get('reason', 'Unsupported desktop'))
    plan = make_plan(state, layout, target, new_host, aliases, evidence)
    plan.update(codex_home=str(home), sidebar_machine=legacy.machine_id(), project_host=project_host,
                project_machine=evidence['machine'], project_codex_home=evidence['codex_home'],
                desktop=app, compatibility=compatibility, source=source, connection=connection, prepared_at=time.time())
    backup = home / (STATE + '.bak')
    require(not backup.is_symlink(), 'Backup must not be a symlink')
    if backup.exists() and plan['created']:
        try:
            add_delta(read(backup), plan)
        except (ValueError, KeyError, TypeError) as exc:
            raise Refusal('Historical backup cannot accept this recovery; inspect ' + STATE + '.bak before preparation. No files changed') from exc
    require((home / STATE).read_bytes() == original and legacy.identity(home) == target, 'State changed while preparing')
    directory = legacy.private_directory(directory)
    require(not list(directory.iterdir()), 'Choose a new empty recovery directory')
    raw = encoded(plan)
    atomic(directory / 'plan.json', raw)
    atomic(directory / 'plan.sha256.json', encoded({'sha256': digest(raw)}))
    atomic(directory / 'native.json', encoded({'schema': VERSION, 'events': []}))
    save_status(directory, 'prepared-blocked' if plan['trust_blockers'] else 'prepared')
    return preview(directory, plan)

def preview(directory, plan):
    return {'phase': read(directory / 'status.json')['phase'], 'record': str(directory),
            'added_projects': [c['project'] for c in plan['created']], 'native_actions': plan['native_actions'],
            'trust_blockers': plan['trust_blockers'], 'tasks_complete': plan['tasks_complete'],
            'requires_app_exit': bool(plan['created'])}

def load_record(directory):
    directory = Path(directory).expanduser().absolute()
    legacy.private_directory(directory)
    plan = private_read(directory / 'plan.json')
    if plan.get('schema') == 1:
        return legacy.load_record(directory)
    require(plan.get('schema') == VERSION and plan.get('adapter') == 'client-remote-registry-v2', 'Unsupported receipt')
    require(private_read(directory / 'plan.sha256.json')['sha256'] == digest((directory / 'plan.json').read_bytes()),
            'Recovery plan changed')
    validate_layout(plan['layout'])
    require(all(set(c) == {'project', 'appearance', 'expanded'} for c in plan['created']), 'Invalid creation journal')
    ids = []
    for c in plan['created']:
        p = c['project']
        require(set(p) == {'id', 'hostId', 'remotePath', 'label'} and p['hostId'] == plan['new_host']
                and p['remotePath'] in plan['source_paths'] and all(isinstance(v, str) and v for v in p.values()),
                'Invalid recovery-owned registration')
        appearance(c['appearance'])
        require(c['expanded'] is None or isinstance(c['expanded'], bool), 'Invalid expansion state')
        ids.append(p['id'])
    require(len(set(ids)) == len(ids), 'Duplicate recovery-owned IDs')
    return directory, plan

def guard(home, plan, closed=True):
    require(str(home) == plan['codex_home'] and legacy.machine_id() == plan['sidebar_machine'], 'Wrong sidebar Mac or Codex home')
    require(legacy.identity(home) == plan['target_account'], 'Active account changed')
    require(runtime.desktop(plan['desktop']['app_path']) == plan['desktop'], 'Desktop build changed')
    state = read(home / STATE)
    require(runtime.connection_binding(state, plan['new_host'], plan['project_host']) == plan['connection'],
            'Destination connection changed')
    require(runtime.compatibility(state, home, plan['desktop']) == plan['compatibility'], 'Storage ownership changed')
    if closed:
        require(not legacy.running(), 'Close the affected desktop app; it will not be terminated')
    return state

def created_slots(plan):
    for c in plan['created']:
        pid = c['project']['id']
        for path, value in [(['project-appearances', pid], c['appearance']),
                            ([ATOM, 'sidebar-project-expanded-v1-codex:' + pid], c['expanded'])]:
            if value is not None:
                yield path, value

def add_delta(state, plan):
    out = copy.deepcopy(state)
    ps = registrations(out)
    existing = {p['id'] for p in ps}
    order = out.setdefault('project-order', [])
    require(isinstance(order, list), 'Invalid project order')
    for c in plan['created']:
        p = c['project']
        require(p['id'] not in existing and not any(q['hostId'] == p['hostId'] and q['remotePath'] == p['remotePath'] for q in ps),
                'Destination registration changed; prepare again')
        ps.append(copy.deepcopy(p)); existing.add(p['id']); order.append(p['id'])
    out['remote-projects'] = ps
    for path, value in created_slots(plan):
        require(not legacy.get_slot(out, path)['present'], 'Recovery-owned metadata ID already exists')
        legacy.put_slot(out, path, {'present': True, 'value': copy.deepcopy(value)})
    return out

def remove_delta(state, plan, before_slots, before_order=None):
    out = copy.deepcopy(state)
    ps = registrations(out)
    for c in plan['created']:
        match = [p for p in ps if p['id'] == c['project']['id']]
        require(not match or match == [c['project']], 'Later project edit conflicts with rollback')
    ids = {c['project']['id'] for c in plan['created']}
    if before_order is not None:
        order = out.get('project-order', [])
        baseline = before_order + [c['project']['id'] for c in plan['created']]
        surviving = set(order) & set(before_order)
        # Appended unrelated projects are allowed; moving an owned project is not.
        owned_order = [p for p in order if p in ids]
        require(owned_order == [p for p in baseline if p in ids and p in order]
                and all(surviving <= set(order[:order.index(pid)]) for pid in owned_order),
                'Later project ordering conflicts with rollback')
    out['remote-projects'] = [p for p in ps if p['id'] not in ids]
    out['project-order'] = [p for p in out.get('project-order', []) if p not in ids]
    for c in plan['created']:
        pid = c['project']['id']
        for path, value in [(['project-appearances', pid], c['appearance']),
                            ([ATOM, 'sidebar-project-expanded-v1-codex:' + pid], c['expanded'])]:
            slot = legacy.get_slot(out, path)
            require(not slot['present'] or (value is not None and slot['value'] == value),
                    'Later appearance edit conflicts with rollback')
            if value is not None:
                legacy.put_slot(out, path, {'present': False, 'value': None})
    # Restore absence of containers only if no subsequent data would be removed.
    for key in ('remote-projects', 'project-order', 'project-appearances', ATOM):
        if not before_slots.get(key, True) and not out.get(key):
            out.pop(key, None)
    return out

def recheck_evidence(state, plan):
    paths = [p for p in registrations(state) if p['hostId'] in set(plan['aliases']) | {plan['new_host']}]
    all_paths = sorted(set(plan['source_paths']) | {p['remotePath'] for p in paths})
    ev = runtime.probe(plan['project_host'], all_paths)
    require(ev['machine'] == plan['project_machine'] and ev['codex_home'] == plan['project_codex_home'], 'Project host identity/home changed')
    for p in plan['expected']:
        info = ev['paths'].get(p['remotePath'])
        require(info and info['canonical'] == p['canonical'] and info['file_id'] == p['file_id'], 'Project path changed')
    for c in plan['created']:
        require(ev['paths'][c['project']['remotePath']].get('trust') == 'trusted', 'Folder consent still required; no trust configuration will be changed')
    require(task_choices(state, plan['task_choices']) == plan['task_choices'], 'Existing task choices changed')
    require(all(ev.get('server_task_assignments', {}).get(t) == assignment
                for t, assignment in plan['server_task_assignments'].items()), 'Existing server task assignments changed')
    if plan['source']:
        source = plan['source']
        require(fingerprint(source_view(state, source['account'], source['host'])) == source['sha256'], 'Selected source layout changed')
    require(destination_view(state, plan['target_account'], set(plan['aliases']) | {plan['new_host']},
                             set(ev['paths'])) == plan['destination_guard'], 'Destination choices changed; prepare again')

@contextmanager
def record_lock(directory):
    directory = legacy.private_directory(directory)
    path = directory / 'record.lock'
    require(not path.is_symlink(), 'Unsafe receipt lock')
    with os.fdopen(os.open(str(path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield

def transact(home, directory, rollback=False):
    with record_lock(directory):
        return transact_locked(home, directory, rollback)

def transact_locked(home, directory, rollback=False):
    directory, plan = load_record(directory)
    if plan['schema'] == 1:
        return legacy.transact(home, directory, rollback)
    require(rollback or private_read(directory / 'status.json')['phase'] != 'metadata-rolled-back',
            'Recovery was rolled back; prepare a new record before applying again')
    if not plan['created']:
        state = guard(home, plan, closed=False)
        if not rollback:
            recheck_evidence(state, plan)
        save_status(directory, 'metadata-rolled-back' if rollback else 'applied-unverified')
        return {'phase': read(directory / 'status.json')['phase'], 'file_changes': 0}
    guard(home, plan)
    lock_path = home / '.sidebar-recovery.lock'
    require(not lock_path.is_symlink(), 'Unsafe writer lock')
    with os.fdopen(os.open(str(lock_path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = guard(home, plan)
        paths = [home / (STATE + '.bak'), home / STATE]
        require(not any(p.is_symlink() for p in paths), 'State files must not be symlinks')
        originals = {p.name: p.read_bytes() if p.exists() else None for p in paths}
        journal_path = directory / 'journal.json'
        journal = private_read(journal_path) if journal_path.exists() else None
        desired = {}
        if rollback:
            require(journal is not None, 'No file transaction to roll back')
            ids = {'codex:project:' + c['project']['id'] for c in plan['created']}
            require(not any(ids.intersection(s['itemKeys']) for s in sections(state, plan['target_account'])),
                    'Reverse native placements through owning tools first')
            require(not {c['project']['id'] for c in plan['created']}.intersection(state.get('pinned-project-ids', [])),
                    'Reverse native pinned placement through owning tools first')
            for p in paths:
                raw = originals[p.name]
                j = journal['files'][p.name]
                if raw is None:
                    require(j['before_hash'] is None, 'State file disappeared')
                    desired[p.name] = None
                elif j['before_hash'] is None and digest(raw) == j['after_hash']:
                    desired[p.name] = None
                else:
                    desired[p.name] = encoded(remove_delta(legacy.decode(raw), plan, j['containers'], j.get('before_order')))
        else:
            if journal is None:
                recheck_evidence(state, plan)
                journal = {'schema': VERSION, 'files': {}}
                for p in paths:
                    raw = originals[p.name]
                    before = legacy.decode(raw) if raw is not None else state
                    # A backup with incompatible destination registrations is not guessed at.
                    after = add_delta(before, plan)
                    desired[p.name] = encoded(after)
                    journal['files'][p.name] = {'before_hash': digest(raw) if raw is not None else None,
                        'after_hash': digest(desired[p.name]), 'before_order': before.get('project-order', []),
                        'containers': {k: k in before for k in ('remote-projects', 'project-order', 'project-appearances', ATOM)}}
                atomic(journal_path, encoded(journal))
            else:
                # Resume only known before/after versions of each file, never replay against later edits.
                ev = runtime.probe(plan['project_host'], plan['source_paths'])
                require(ev['machine'] == plan['project_machine'] and ev['codex_home'] == plan['project_codex_home'], 'Project host changed during recovery')
                for expected in plan['expected']:
                    info = ev['paths'].get(expected['remotePath'])
                    require(info and info['canonical'] == expected['canonical'] and info['file_id'] == expected['file_id'], 'Project path changed during recovery')
                for c in plan['created']:
                    require(ev['paths'][c['project']['remotePath']].get('trust') == 'trusted', 'Folder consent changed')
                for p in paths:
                    raw = originals[p.name]; j = journal['files'][p.name]
                    h = digest(raw) if raw is not None else None
                    require(h in (j['before_hash'], j['after_hash']), 'Interrupted transaction has later edits; inspect rollback')
                    if h == j['after_hash']:
                        desired[p.name] = raw
                    else:
                        before = legacy.decode(raw) if raw is not None else legacy.decode(originals[STATE])
                        desired[p.name] = encoded(add_delta(before, plan))
                        require(digest(desired[p.name]) == j['after_hash'], 'Interrupted transaction cannot be reconstructed safely')
        save_status(directory, 'rollback-writing' if rollback else 'writing')
        for p in paths:
            guard(home, plan)
            require((p.read_bytes() if p.exists() else None) == originals[p.name], 'State changed during commit')
            if desired[p.name] is None:
                if p.exists():
                    p.unlink()
            elif desired[p.name] != originals[p.name]:
                atomic(p, desired[p.name])
        require(all((p.read_bytes() if p.exists() else None) == desired[p.name] for p in paths), 'Commit readback failed')
        phase = 'metadata-rolled-back' if rollback else 'applied-unverified'
        save_status(directory, phase, app_reappeared=legacy.running())
        return {'phase': phase, 'native_actions': plan['native_actions']}

def native_event(directory, event, remove_empty_sections=False, home=None):
    with record_lock(directory):
        return native_event_locked(directory, event, remove_empty_sections, home)

def native_event_locked(directory, event, remove_empty_sections=False, home=None):
    directory, plan = load_record(directory)
    require(plan['schema'] == VERSION, 'Native receipts require v2')
    guard(Path(home) if home is not None else Path(plan['codex_home']), plan, closed=False)
    status = private_read(directory / 'status.json')
    require(set(event) == {'operation_id', 'stage', 'observed_at', 'sections'}
            and event['stage'] in ('intent', 'confirmed', 'unresolved', 'rollback-intent', 'rollback-unresolved', 'reversed')
            and isinstance(event['observed_at'], (int, float))
            and status['time'] <= event['observed_at'] <= time.time() + 30,
            'Invalid native observation event')
    require(read(directory / 'status.json')['phase'] in ('applied-unverified', 'verified'), 'Apply file stage before native operations')
    action = next((a for a in plan['native_actions'] if a['id'] == event['operation_id']), None)
    require(action is not None, 'Unknown native operation')
    ss = legacy.sections({'sections': event['sections']})
    require(all(set(s) == {'id', 'name', 'itemKeys'} and all(isinstance(k, str) for k in s['itemKeys']) for s in ss),
            'Native evidence must contain only section identity and membership')
    receipt = private_read(directory / 'native.json')
    require(not receipt['events'] or event['observed_at'] >= receipt['events'][-1]['observed_at'], 'Stale native observation')
    previous = [x for x in receipt['events'] if x['operation_id'] == action['id']]
    if event['stage'] == 'intent':
        require(not previous, 'Inspect existing native intent; do not retry blindly')
        if action['kind'] == 'create-section':
            require(not any(s['name'] == action['section_name'] for s in ss), 'Section already exists; replan instead of creating a duplicate')
        else:
            require(not any('codex:project:' + action['project_id'] in s['itemKeys'] for s in ss), 'Placement changed before native intent')
            target_sections = [s for s in ss if (s['id'] == action['section_id'] if action['section_id'] else s['name'] == action['section_name'])]
            require(len(target_sections) == 1 and target_sections[0]['name'] == action['section_name'],
                    'Intended section changed before native intent')
    else:
        require(previous and previous[0]['stage'] == 'intent', 'Record native intent first')
        require(event['observed_at'] >= previous[-1]['observed_at'], 'Stale native evidence')
        if previous[-1]['stage'] == 'confirmed':
            require(event['stage'] == 'rollback-intent', 'Confirmed native operation cannot be replayed')
        require(previous[-1]['stage'] != 'reversed', 'Reversed native operation cannot be replayed')
        if previous[-1]['stage'] in ('rollback-intent', 'rollback-unresolved'):
            require(event['stage'] in ('rollback-unresolved', 'reversed'), 'Reconcile pending native rollback')
        elif event['stage'] in ('rollback-unresolved', 'reversed'):
            raise Refusal('Record rollback intent first')
    if event['stage'] == 'rollback-intent':
        require(previous and previous[-1]['stage'] == 'confirmed', 'Confirm the forward native result before rollback')
        recorded = next((s for s in previous[-1]['sections'] if
                        (s['id'] == action['section_id'] if action.get('section_id') else s['name'] == action['section_name'])), None)
        require(recorded is not None, 'Native confirmation no longer matches this plan')
        current = [s for s in ss if s['id'] == recorded['id']]
        require(len(current) == 1 and current[0]['name'] == recorded['name'], 'Later section edit conflicts with rollback')
        if action['kind'] == 'create-section':
            require(remove_empty_sections and not current[0]['itemKeys'],
                    'Removing a created section requires explicit selection and an empty section')
        else:
            key = 'codex:project:' + action['project_id']
            require([s['id'] for s in ss if key in s['itemKeys']] == [recorded['id']],
                    'Later placement edit conflicts with rollback')
            old_items, current_items = recorded['itemKeys'], current[0]['itemKeys']
            before = set(old_items[:old_items.index(key)]) & set(current_items)
            after = set(old_items[old_items.index(key) + 1:]) & set(current_items)
            require(before <= set(current_items[:current_items.index(key)])
                    and after <= set(current_items[current_items.index(key) + 1:]),
                    'Later placement ordering conflicts with rollback')
    if event['stage'] == 'confirmed':
        candidates = [s for s in ss if (s['id'] == action['section_id'] if action.get('section_id') else s['name'] == action['section_name'])]
        require(len(candidates) == 1 and candidates[0]['name'] == action['section_name'],
                'Native result needs a unique observed section with its planned name')
        if action['kind'] == 'create-section':
            before_ids = {s['id'] for s in previous[0]['sections']}
            require(candidates[0]['id'] not in before_ids, 'Section was not created by this operation')
        else:
            require('codex:project:' + action['project_id'] in candidates[0]['itemKeys']
                    and (action['section_id'] is None or candidates[0]['id'] == action['section_id']),
                    'Native placement not observed')
    if event['stage'] == 'reversed':
        require(previous[-1]['stage'] in ('rollback-intent', 'rollback-unresolved'), 'Record rollback intent first')
        if action['kind'] == 'place-project':
            require(not any('codex:project:' + action['project_id'] in s['itemKeys'] for s in ss),
                    'Native placement still present')
        else:
            confirmed = next((x for x in previous if x['stage'] == 'confirmed'), None)
            require(confirmed is not None, 'Confirmed native creation is unavailable')
            created = next((s for s in confirmed['sections'] if s['name'] == action['section_name']), None)
            require(created is not None, 'Native confirmation no longer matches this plan')
            require(not any(s['id'] == created['id'] for s in ss), 'Created section still present')
    receipt['events'].append(copy.deepcopy(event))
    require(len(encoded(receipt)) <= MAX_RECORD, 'Native receipt exceeds size limit')
    atomic(directory / 'native.json', encoded(receipt))
    return {'phase': 'native-' + event['stage'], 'operation_id': action['id']}

def audit_inventory(home, directory):
    """Audit all recorded task metadata without claiming client membership."""
    with record_lock(directory):
        directory, plan = load_record(directory)
        require(plan['schema'] == VERSION, 'Inventory-only verification requires a v2 receipt')
        state = guard(home, plan, closed=False)
        status = private_read(directory / 'status.json')
        require(status['phase'] in ('applied-unverified', 'verified'),
                'Apply the recovery before auditing its task inventory')
        started = time.time()
        choices = task_choices(state, plan['task_choices'])
        paths = sorted(set(plan['source_paths']) | {p['remotePath'] for p in plan['expected']})
        evidence = runtime.probe(plan['project_host'], paths)
        require(evidence['machine'] == plan['project_machine']
                and evidence['codex_home'] == plan['project_codex_home'],
                'Project host identity/home changed')
        for project in plan['expected']:
            info = evidence['paths'].get(project['remotePath'])
            require(info and info['canonical'] == project['canonical']
                    and info['file_id'] == project['file_id'], 'Project path changed')
        fresh = guard(home, plan, closed=False)
        require(task_choices(fresh, plan['task_choices']) == choices,
                'Task choices changed during inventory audit; retry')
        present = {tid for tids in evidence.get('tasks', {}).values() for tid in tids}
        baseline = plan['server_task_assignments']
        missing = sorted(set(baseline) - present)
        changed = sorted(tid for tid, assignment in baseline.items() if tid in present
                         and evidence.get('server_task_assignments', {}).get(tid) != assignment)
        client_changed = sorted(tid for tid, choice in plan['task_choices'].items()
                                if choices[tid] != choice)
        candidates = {tid for project in plan['expected'] for tid in project['candidate_task_ids']}
        matched = {tid for project in plan['expected'] for tid in project['candidate_task_ids']
                   if tid in evidence.get('tasks', {}).get(project['remotePath'], [])}
        complete = evidence.get('tasks_complete') is True
        conflicts = bool(changed or client_changed or (complete and (missing or candidates - matched)))
        result = {'schema': 1, 'kind': 'task-inventory-audit', 'phase': status['phase'],
                  'started_at': started, 'collected_at': time.time(),
                  'inventory_status': 'conflicts' if conflicts else
                      'verified' if complete and plan['tasks_complete'] else 'incomplete',
                  'prepared_inventory_complete': plan['tasks_complete'],
                  'backend_inventory': dict(evidence.get('task_inventory', {}), complete=complete),
                  'recorded_tasks': len(baseline), 'recorded_tasks_observed': len(set(baseline) & present),
                  'candidate_tasks': len(candidates), 'candidates_at_expected_paths': len(matched),
                  'server_assignment_changes': len(changed), 'client_choice_changes': len(client_changed),
                  'application_membership_checked': False,
                  'not_observed_task_ids': missing,
                  'candidate_path_mismatch_ids': sorted(candidates - matched),
                  'changed_server_assignment_ids': changed, 'changed_client_choice_ids': client_changed}
        receipt = directory / ('inventory-audit-' + uuid.uuid4().hex + '.json')
        private_write(receipt, result)
        # Keep identifiers in the private receipt; stdout is a coverage summary.
        return {k: v for k, v in dict(result, receipt=str(receipt)).items()
                if k not in ('not_observed_task_ids', 'changed_server_assignment_ids',
                             'changed_client_choice_ids', 'candidate_path_mismatch_ids')}

def verify(home, directory, observations):
    with record_lock(directory):
        return verify_locked(home, directory, observations)

def verify_locked(home, directory, observations):
    directory, plan = load_record(directory)
    if plan['schema'] == 1:
        return legacy.verify(home, directory, observations)
    state = guard(home, plan, closed=False)
    status = private_read(directory / 'status.json')
    require(status['phase'] in ('applied-unverified', 'verified')
            and observations.get('account_id') == plan['target_account']
            and observations.get('sidebar_machine') == plan['sidebar_machine']
            and status['time'] <= observations.get('collected_at', 0) <= time.time() + 30,
            'Fresh owning-app observations required')
    require(observations.get('complete') == {'projects': True, 'sections': True, 'task_associations': True}
            and plan['tasks_complete'], 'Complete task and application evidence required')
    require(task_choices(state, plan['task_choices']) == plan['task_choices'], 'Explicit task choices changed')
    host_evidence = runtime.probe(plan['project_host'], plan['source_paths'])
    require(host_evidence['machine'] == plan['project_machine']
            and host_evidence['codex_home'] == plan['project_codex_home']
            and host_evidence.get('tasks_complete'), 'Fresh complete project-host evidence required')
    current_tasks = {t for tids in host_evidence.get('tasks', {}).values() for t in tids}
    require(all(t in current_tasks and host_evidence.get('server_task_assignments', {}).get(t) == assignment
                for t, assignment in plan['server_task_assignments'].items()), 'Existing server task assignments changed')
    actual = {p['id']: p for p in observations.get('projects', [])}
    require(len(actual) == len(observations.get('projects', [])), 'Duplicate project observations')
    live_sections = legacy.sections({'sections': observations.get('sections', [])})
    local_sections = sections(state, plan['target_account'])
    if state.get('pinned-project-ids'):
        local_sections = local_sections + [{'id': 'pinned', 'name': 'Pinned',
                                           'itemKeys': ['codex:project:' + p for p in state['pinned-project-ids']]}]
    receipt = private_read(directory / 'native.json')
    require(not receipt['events'] or observations['collected_at'] >= receipt['events'][-1]['observed_at'],
            'Application observations predate native operations')
    final_events = {x['operation_id']: x for x in receipt['events']}
    require(all(final_events.get(a['id'], {}).get('stage') == 'confirmed' for a in plan['native_actions']),
            'Native operation evidence incomplete')
    if plan['source']:
        source = plan['source']
        view = source_view(state, source['account'], source['host'])
        allowed_ids = set()
        if source['account'] == plan['target_account']:
            for action in plan['native_actions']:
                if action['kind'] == 'create-section':
                    event = final_events[action['id']]
                    allowed_ids.update(s['id'] for s in event['sections'] if s['name'] == action['section_name'])
        view['sections'] = [s for s in view['sections'] if s['id'] not in allowed_ids]
        require(fingerprint(view) == source['sha256'], 'Selected source choices changed')
    reads = set(observations.get('historical_task_reads', []))
    all_candidates = set()
    for p in plan['expected']:
        require(next((x for x in registrations(state) if x['id'] == p['id']), None) == p['registration'],
                'Recovered registration changed')
        observed = actual.get(p['id'], {})
        require(all(observed.get(k) == p[k] for k in ('hostId', 'remotePath')), 'Project absent from actual client')
        require(set(p['candidate_task_ids']) <= set(observed.get('task_ids', [])), 'Candidate task association was not established')
        all_candidates.update(p['candidate_task_ids'])
        observed_owners = [s for s in live_sections if 'codex:project:' + p['id'] in s['itemKeys']]
        persisted = [s for s in local_sections if 'codex:project:' + p['id'] in s['itemKeys']]
        require([(s['id'], s['name']) for s in observed_owners] == [(s['id'], s['name']) for s in persisted],
                'Client and persisted placement differ')
        if p['section_name'] is None:
            require(not observed_owners, 'Existing ungrouped placement changed')
        else:
            require(len(observed_owners) == 1 and observed_owners[0]['name'] == p['section_name']
                    and (p['section_id'] is None or observed_owners[0]['id'] == p['section_id']), 'Intended section missing')
    require(not all_candidates or reads.intersection(all_candidates), 'Read a pre-existing task through owning app tools')
    save_status(directory, 'verified', projects=len(plan['expected']), tasks=len(all_candidates))
    return {'phase': 'verified', 'projects': len(plan['expected']), 'tasks': len(all_candidates)}

def wait_and_transact(home, directory, seconds, rollback=False):
    """One bounded worker per receipt; waiting must not erase transaction status."""
    require(0 < seconds <= 600, 'Wait must be between 1 and 600 seconds')
    with record_lock(directory):
        directory, plan = load_record(directory)
        deadline = time.monotonic() + seconds
        receipt = {'phase': 'waiting-for-app-exit', 'pid': os.getpid(), 'started_at': time.time(),
                   'maximum_wait_seconds': seconds, 'operation': 'rollback' if rollback else 'apply'}
        atomic(directory / 'worker.json', encoded(receipt))
        while legacy.running() and time.monotonic() < deadline:
            time.sleep(0.5)
        if legacy.running():
            receipt.update(phase='expired', files_written_by_worker=False)
            atomic(directory / 'worker.json', encoded(receipt))
            raise Refusal('App-exit wait expired; existing transaction status preserved')
        try:
            result = transact_locked(home, directory, rollback)
        except Exception:
            receipt.update(phase='stopped', inspect_transaction_status=True)
            atomic(directory / 'worker.json', encoded(receipt))
            raise
        receipt.update(phase='finished', result_phase=result['phase'])
        atomic(directory / 'worker.json', encoded(receipt))
        return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['inspect', 'export-layout', 'prepare', 'apply', 'verify', 'rollback'])
    p.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    p.add_argument('--record', type=Path)
    p.add_argument('--source-account')
    p.add_argument('--old-host')
    p.add_argument('--new-host')
    p.add_argument('--alias-host', action='append', default=[])
    p.add_argument('--project-host')
    p.add_argument('--source-layout', type=Path)
    p.add_argument('--app-path')
    p.add_argument('--output', type=Path)
    p.add_argument('--summary', action='store_true')
    p.add_argument('--observations', type=Path)
    p.add_argument('--inventory-only', action='store_true',
                   help='Audit recorded task metadata; never mark sidebar recovery verified')
    p.add_argument('--native-event', type=Path)
    p.add_argument('--remove-empty-sections', action='store_true')
    p.add_argument('--wait-seconds', type=int, default=0)
    args = p.parse_args()
    home = args.codex_home.expanduser().resolve()
    try:
        require(legacy.platform.system() == 'Darwin', 'Sidebar repair supports macOS only')
        require(not args.remove_empty_sections or args.operation == 'rollback', 'Section removal belongs to rollback')
        require(not args.inventory_only or (args.operation == 'verify' and args.observations is None),
                '--inventory-only belongs to verify without --observations')
        if args.operation == 'inspect':
            if args.record:
                directory, plan = load_record(args.record)
                result = {'schema': plan['schema'], 'phase': private_read(directory / 'status.json')['phase']}
            else:
                result = inspect(home, args.project_host, args.app_path, args.summary, args.old_host)
        elif args.operation == 'export-layout':
            require(args.source_account and args.old_host and args.project_host and args.output, 'Select source, host and private output')
            state = read(home / STATE)
            paths = [p['remotePath'] for p in source_view(state, args.source_account, args.old_host)['projects']]
            data = export_data(state, args.source_account, args.old_host, runtime.probe(args.project_host, paths), legacy.machine_id())
            private_write(args.output, data)
            result = {'phase': 'exported', 'projects': len(data['projects']), 'output': str(args.output)}
        else:
            require(args.record is not None, '--record is required')
            if args.operation == 'prepare':
                result = prepare(home, args.record, args.source_account, args.old_host, args.new_host,
                                 args.project_host, args.source_layout, args.alias_host, args.app_path)
            elif args.native_event:
                require(args.operation in ('apply', 'rollback'), 'Native events belong to apply/rollback')
                event = private_read(args.native_event)
                reversing = event.get('stage') in ('rollback-intent', 'rollback-unresolved', 'reversed')
                require(reversing == (args.operation == 'rollback'), 'Native event does not match apply/rollback operation')
                require(not args.remove_empty_sections or args.operation == 'rollback', 'Section removal belongs to rollback')
                result = native_event(args.record, event, args.remove_empty_sections, home)
            elif args.operation == 'verify':
                if args.inventory_only:
                    result = audit_inventory(home, args.record)
                else:
                    require(args.observations is not None, '--observations is required')
                    result = verify(home, args.record, private_read(args.observations))
            else:
                require(0 <= args.wait_seconds <= 600, 'Wait must be between 0 and 600 seconds')
                if args.wait_seconds:
                    result = wait_and_transact(home, args.record, args.wait_seconds, args.operation == 'rollback')
                else:
                    result = transact(home, args.record, args.operation == 'rollback')
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('inventory_status', 'verified') == 'verified' else 2
    except (ValueError, OSError, KeyError, TypeError, legacy.subprocess.SubprocessError) as exc:
        print(json.dumps({'phase': 'refused', 'reason': str(exc)}))
        return 2

if __name__ == '__main__':
    sys.exit(main())
