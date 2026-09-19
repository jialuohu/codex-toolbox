"""Synthetic recovery-v2 regressions. No test touches an installed app or real home."""
import copy
import importlib.util
import io
import json
import plistlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/workflow-tools/skills/recover-codex-sidebar/scripts/recover_sidebar.py'
spec = importlib.util.spec_from_file_location('sidebar_recovery_v2', SCRIPT)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
rt = r.runtime
MACHINE = 'a' * 64
SIDEBAR = 'b' * 64
PATH = '/example/project'
OLD = 'old-host'
NEW = 'remote-ssh-discovered:fixture-ssh'
PROFILE = json.loads((SCRIPT.parent.parent / 'references/desktop-profiles.json').read_text())['profiles'][0]
APP = {k: PROFILE[k] for k in ('bundle_id', 'version', 'build', 'implementation_sha256')}
APP['app_path'] = '/Applications/Fixture.app'


def section(sid='target-section', name='Research', items=None):
    return {'id': sid, 'name': name, 'itemKeys': list(items or [])}


def fixture():
    source = section('source-section', items=['codex:project:old'])
    source['hostSectionIds'] = {'old-host': 'opaque-source-binding'}
    state = {
        'remote-projects': [{'id': 'old', 'hostId': OLD, 'label': 'Example', 'remotePath': PATH}],
        'project-order': ['old'],
        'codex-managed-remote-connections': [
            {'hostId': NEW, 'source': 'discovered', 'alias': 'fixture-ssh'},
            {'hostId': 'remote-ssh-discovered:explicit-destination', 'source': 'discovered',
             'alias': 'explicit-destination'},
        ],
        'project-appearances': {'old': {'icon': 'book'}},
        r.ATOM: {r.LAYOUTS: {
            'source': {'sections': [source]},
            'target': {'sections': [section(items=['codex:project:old'])]},
        }},
        'unrelated': {'keep': True},
    }
    evidence = {'machine': MACHINE, 'codex_home': '/custom/codex-home',
                'paths': {PATH: {'canonical': PATH, 'file_id': [7, 101], 'trust': 'trusted'}},
                'tasks': {PATH: ['existing-task']}, 'tasks_complete': True,
                'server_projects': [], 'server_inventory_complete': True}
    return state, evidence


def layout(state, evidence, account='source'):
    return r.export_data(state, account, OLD, evidence, SIDEBAR)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.state, self.evidence = fixture()
        self.layout = layout(self.state, self.evidence)

    def plan(self, aliases=(OLD,)):
        return r.make_plan(self.state, self.layout, 'target', NEW, aliases, self.evidence)

    def test_export_is_portable_bounded_and_does_not_import_bindings_or_trust(self):
        text = json.dumps(self.layout)
        self.assertNotIn('opaque-source-binding', text)
        self.assertNotIn('source-section', text)
        self.assertNotIn('target-section', text)
        self.assertNotIn('trusted', text)
        self.assertNotIn('existing-task', text)
        self.assertNotIn('/custom/codex-home', text)
        self.assertEqual(self.layout['projects'][0]['section'], 's0')
        bad = copy.deepcopy(self.layout)
        bad['projects'][0]['trust_level'] = 'trusted'
        with self.assertRaises(r.Refusal):
            r.validate_layout(bad)

    def test_empty_donor_destination_and_input_preserved(self):
        self.state[r.ATOM][r.LAYOUTS]['target'] = {'sections': []}
        before = copy.deepcopy(self.state)
        plan = self.plan(aliases=())
        self.assertEqual(self.state, before)
        self.assertEqual(len(plan['created']), 1)
        self.assertEqual([a['kind'] for a in plan['native_actions']], ['create-section', 'place-project'])
        self.assertEqual(plan['native_actions'][0]['section_name'], 'Research')

    def test_missing_target_account_uses_source_placement(self):
        del self.state[r.ATOM][r.LAYOUTS]['target']
        plan = self.plan()
        self.assertEqual(plan['expected'][0]['section_name'], 'Research')

    def test_same_account_preserves_source_after_recorded_addition(self):
        before = r.source_view(self.state, 'target', OLD)
        plan = r.make_plan(self.state, layout(self.state, self.evidence, 'target'),
                           'target', NEW, [OLD], self.evidence)
        after = r.add_delta(self.state, plan)
        pid = plan['created'][0]['project']['id']
        after[r.ATOM][r.LAYOUTS]['target']['sections'][0]['itemKeys'].append('codex:project:' + pid)
        self.assertEqual(r.source_view(after, 'target', OLD), before)
        again = r.make_plan(after, layout(after, self.evidence, 'target'), 'target', NEW, [OLD], self.evidence)
        self.assertEqual(again['created'], [])
        self.assertEqual(again['native_actions'], [])

    def test_existing_destination_keeps_name_appearance_and_ungrouped(self):
        current = {'id': 'current', 'hostId': NEW, 'label': 'My title', 'remotePath': PATH}
        self.state['remote-projects'].append(current)
        self.state['project-appearances']['current'] = {'icon': 'star'}
        before = copy.deepcopy(self.state)
        plan = self.plan()
        self.assertEqual(plan['created'], [])
        self.assertEqual(plan['native_actions'], [])
        self.assertIsNone(plan['expected'][0]['section_id'])
        self.assertEqual(self.state, before)

    def test_current_destination_beats_conflicting_historical_aliases(self):
        self.state['remote-projects'].extend([
            {'id': 'current', 'hostId': NEW, 'label': 'Current', 'remotePath': PATH},
            {'id': 'other-old', 'hostId': 'older-host', 'label': 'Historical name', 'remotePath': PATH},
        ])
        plan = self.plan(aliases=(OLD, 'older-host'))
        self.assertEqual(plan['created'], [])

    def test_surviving_destination_choice_beats_source_section(self):
        self.state[r.ATOM][r.LAYOUTS]['target']['sections'][0]['name'] = 'My group'
        plan = self.plan()
        self.assertEqual(plan['expected'][0]['section_name'], 'My group')
        self.assertEqual([a['kind'] for a in plan['native_actions']], ['place-project'])
        self.state[r.ATOM][r.LAYOUTS]['target']['sections'][0]['itemKeys'] = []
        self.assertIsNone(self.plan()['expected'][0]['section_name'])

    def test_conflicting_alias_placements_require_resolution(self):
        self.state['remote-projects'].append(
            {'id': 'older', 'hostId': 'older-host', 'label': 'Example', 'remotePath': PATH})
        with self.assertRaisesRegex(r.Refusal, 'Conflicting destination alias'):
            self.plan(aliases=(OLD, 'older-host'))

    def test_host_identity_missing_path_and_duplicate_identity_refused(self):
        self.evidence['machine'] = 'c' * 64
        with self.assertRaisesRegex(r.Refusal, 'different project Mac'):
            self.plan()
        self.evidence['machine'] = MACHINE
        self.evidence['paths'][PATH] = None
        with self.assertRaisesRegex(r.Refusal, 'Missing'):
            self.plan()
        self.state, self.evidence = fixture()
        self.state['remote-projects'].extend(
            {'id': str(i), 'hostId': NEW, 'label': 'Duplicate', 'remotePath': PATH} for i in range(2))
        with self.assertRaisesRegex(r.Refusal, 'Ambiguous destination project'):
            self.plan()

    def test_case_distinction_preserved_but_same_inode_is_one_identity(self):
        alternate = '/Example/project'
        self.state['remote-projects'].append(
            {'id': 'case-sensitive', 'hostId': NEW, 'label': 'Different', 'remotePath': alternate})
        self.evidence['paths'][alternate] = {'canonical': alternate, 'file_id': [7, 102], 'trust': 'trusted'}
        self.assertEqual(len(self.plan()['created']), 1)
        self.evidence['paths'][alternate]['file_id'] = [7, 101]
        self.assertEqual(self.plan()['created'], [])

    def test_duplicate_source_filesystem_identity_refused(self):
        project = dict(self.layout['projects'][0], key='p1', path='/alias/project')
        self.layout['projects'].append(project)
        self.evidence['paths']['/alias/project'] = copy.deepcopy(self.evidence['paths'][PATH])
        with self.assertRaisesRegex(r.Refusal, 'Ambiguous source filesystem'):
            self.plan()

    def test_explicit_assignments_and_projectless_choices_are_not_cwd_membership(self):
        self.evidence['tasks'][PATH] += ['assigned', 'projectless']
        self.state['thread-project-assignments'] = {'assigned': 'another-project'}
        self.state['projectless-thread-ids'] = ['projectless']
        plan = self.plan()
        self.assertEqual(plan['expected'][0]['candidate_task_ids'], ['existing-task'])
        self.assertEqual(plan['task_choices']['assigned']['assignment'], 'another-project')
        self.assertTrue(plan['task_choices']['projectless']['projectless'])

    def test_trust_gap_is_visible_without_state_mutation(self):
        self.evidence['paths'][PATH]['trust'] = None
        before = copy.deepcopy(self.state)
        plan = self.plan()
        self.assertEqual(plan['trust_blockers'], [{'path': PATH, 'reason': 'folder_consent_required'}])
        self.assertEqual(before, self.state)

    def test_partial_restore_and_source_order(self):
        second = dict(self.layout['projects'][0], key='p1', path='/example/second', section_position=1)
        self.layout['projects'].insert(0, second)
        self.evidence['paths'][second['path']] = {'canonical': second['path'], 'file_id': [7, 102], 'trust': 'trusted'}
        self.state['remote-projects'].append(
            {'id': 'existing', 'hostId': NEW, 'label': 'Keep', 'remotePath': PATH})
        plan = self.plan()
        self.assertEqual([x['project']['remotePath'] for x in plan['created']], ['/example/second'])
        self.assertEqual([x['remotePath'] for x in plan['expected']], ['/example/second', PATH])

    def test_unknown_snapshot_fields_and_duplicate_sections_refused(self):
        self.layout['sections'].append({'key': 's1', 'name': 'Research'})
        with self.assertRaisesRegex(r.Refusal, 'Ambiguous portable'):
            self.plan()
        self.layout = layout(self.state, self.evidence)
        self.layout['provenance']['account_id'] = 'untrusted-imported-account'
        with self.assertRaisesRegex(r.Refusal, 'provenance'):
            self.plan()


    def test_alias_name_and_appearance_survive_without_destination_layout(self):
        del self.state[r.ATOM][r.LAYOUTS]['target']
        self.state['remote-projects'][0]['label'] = 'Surviving label'
        self.state['project-appearances']['old'] = {'icon': 'star'}
        plan = self.plan()
        self.assertEqual(plan['created'][0]['project']['label'], 'Surviving label')
        self.assertEqual(plan['created'][0]['appearance'], {'icon': 'star'})
        self.assertEqual(plan['expected'][0]['section_name'], 'Research')


    def test_backend_explicit_assignment_excludes_cwd_candidate_and_is_frozen(self):
        self.evidence['tasks'][PATH].append('backend-assigned-task')
        self.evidence['server_task_assignments'] = {
            'existing-task': None, 'backend-assigned-task': 'explicit-server-project'}
        before = copy.deepcopy(self.state)
        plan = self.plan()
        self.assertEqual(plan['expected'][0]['candidate_task_ids'], ['existing-task'])
        self.assertEqual(plan['server_task_assignments'],
                         {'existing-task': None, 'backend-assigned-task': 'explicit-server-project'})
        self.assertEqual(self.state, before)
        self.evidence['server_task_assignments']['backend-assigned-task'] = 'later-edit'
        self.assertEqual(plan['server_task_assignments']['backend-assigned-task'], 'explicit-server-project')


    def test_pinned_export_uses_reserved_marker_and_preserves_pin_order(self):
        for account in ('source', 'target'):
            self.state[r.ATOM][r.LAYOUTS][account]['sections'][0]['itemKeys'] = []
        self.state['remote-projects'].append(
            {'id': 'second', 'hostId': OLD, 'label': 'Second', 'remotePath': '/example/second'})
        self.state['project-order'].append('second')
        self.state['pinned-project-ids'] = ['second', 'old']
        self.evidence['paths']['/example/second'] = {
            'canonical': '/example/second', 'file_id': [7, 102], 'trust': 'trusted'}
        portable = layout(self.state, self.evidence)
        self.assertEqual([p['section'] for p in portable['projects']], ['@pinned', '@pinned'])
        self.assertEqual([p['section_position'] for p in portable['projects']], [1, 0])
        self.assertNotIn('pinned-project-ids', json.dumps(portable))
        bad = copy.deepcopy(portable)
        bad['sections'].append({'key': '@pinned', 'name': 'A custom group'})
        with self.assertRaises(r.Refusal):
            r.validate_layout(bad)

    def test_pinned_donor_reuses_builtin_section_without_creating_one(self):
        self.layout['projects'][0]['section'] = '@pinned'
        self.state[r.ATOM][r.LAYOUTS]['target']['sections'].append(section('custom-pinned', 'Pinned'))
        plan = self.plan(aliases=())
        self.assertEqual(plan['expected'][0]['section_id'], 'pinned')
        self.assertEqual(len(plan['native_actions']), 1)
        self.assertEqual(plan['native_actions'][0]['kind'], 'place-project')
        self.assertEqual(plan['native_actions'][0]['section_id'], 'pinned')

    def test_existing_pinned_destination_wins_over_donor_section(self):
        self.state['remote-projects'].append(
            {'id': 'current', 'hostId': NEW, 'label': 'My current name', 'remotePath': PATH})
        self.state['pinned-project-ids'] = ['current']
        plan = self.plan()
        self.assertEqual(plan['created'], [])
        self.assertEqual(plan['native_actions'], [])
        self.assertEqual(plan['expected'][0]['section_id'], 'pinned')

    def test_pinned_and_custom_placement_conflict_is_refused(self):
        self.state['pinned-project-ids'] = ['old']
        with self.assertRaisesRegex(r.Refusal, 'Conflicting'):
            self.plan()
        with self.assertRaisesRegex(r.Refusal, 'Ambiguous source placement'):
            layout(self.state, self.evidence)



class RuntimeTests(unittest.TestCase):
    def probe_pages(self, pages):
        calls = []
        class RPC:
            def __init__(self, cli): pass
            def request(self, method, params):
                if method == 'thread/list':
                    page = copy.deepcopy(pages[len(calls)])
                    calls.append(copy.deepcopy(params))
                    if isinstance(page, Exception):
                        raise page
                    for task in page.get('data', []):
                        task['cwd'] = str(project)
                    return page
                return {'initialize': {'codexHome': '/custom/codex-home'},
                        'config/read': {'config': {}},
                        'project/list': {'data': [], 'nextCursor': None}}[method]
            def send(self, message): pass
            def close(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            with patch.object(rt, 'ReadOnlyRPC', RPC), \
                 patch.object(rt.shutil, 'which', return_value='/fixture/codex'), \
                 patch.object(rt, 'hardware_id', return_value=MACHINE):
                result = rt.probe_local([str(project)])
        return result, calls

    def test_task_inventory_exhausts_pages_beyond_app_limit_without_content(self):
        tasks = [{'id': str(i), 'projectId': None, 'preview': 'PRIVATE CONTENT'} for i in range(151)]
        result, calls = self.probe_pages([
            {'data': tasks[:100], 'nextCursor': 'older'},
            {'data': tasks[100:], 'nextCursor': None},
        ])
        self.assertTrue(result['tasks_complete'])
        self.assertEqual(result['task_inventory'], {
            'scope': 'unarchived_all_sources_all_providers', 'pages': 2,
            'tasks_seen': 151, 'complete': True, 'reason': None})
        self.assertEqual([c['cursor'] for c in calls], [None, 'older'])
        self.assertEqual(len(result['server_task_assignments']), 151)
        self.assertNotIn('PRIVATE CONTENT', json.dumps(result))

    def test_task_inventory_rejects_missing_terminal_cursor_duplicate_ids_and_bad_metadata(self):
        first = {'data': [{'id': 'first', 'projectId': None}], 'nextCursor': 'older'}
        cases = [
            ({'data': []}, 'invalid_task_page'),
            ({'data': [], 'nextCursor': ''}, 'invalid_task_page'),
            ({'data': [], 'nextCursor': 'older'}, 'repeated_task_cursor'),
            ({'data': [{'id': 'first', 'projectId': None}], 'nextCursor': None}, 'duplicate_task_id'),
            ({'data': [{'id': 'second'}], 'nextCursor': None}, 'invalid_task_metadata'),
            (rt.EvidenceError('PRIVATE API RESPONSE'), 'task_api_unavailable'),
        ]
        for last, reason in cases:
            with self.subTest(reason=reason):
                result, _ = self.probe_pages([first, last])
                self.assertFalse(result['tasks_complete'])
                self.assertFalse(result['task_inventory']['complete'])
                self.assertEqual(result['task_inventory']['reason'], reason)
                self.assertNotIn('PRIVATE API RESPONSE', json.dumps(result))

    def test_task_inventory_page_bound_does_not_claim_exhaustion(self):
        result, calls = self.probe_pages([
            {'data': [{'id': str(i), 'projectId': None}], 'nextCursor': str(i)} for i in range(200)])
        self.assertEqual(len(calls), 200)
        self.assertFalse(result['tasks_complete'])
        self.assertEqual(result['task_inventory']['reason'], 'page_limit')

    def test_profile_accepts_only_audited_desktop_and_local_owned_migration(self):
        home = Path('/fixture/home')
        state = {k: {'local:' + str(home): {'complete': True}} for k in (
            'app-server-projects-migration-by-host',
            'app-server-project-id-by-legacy-project-id-by-host',
            'app-server-pending-project-deletions-by-host')}
        self.assertTrue(rt.compatibility(state, home, APP)['supported'])
        for key in ('version', 'build', 'implementation_sha256'):
            with self.subTest(key=key):
                self.assertFalse(rt.compatibility(state, home, dict(APP, **{key: 'unknown'}))['supported'])
        for key in state:
            with self.subTest(key=key):
                bad = copy.deepcopy(state)
                bad[key][NEW] = {'unknown': True}
                self.assertFalse(rt.compatibility(bad, home, APP)['supported'])
        self.assertFalse(rt.compatibility({'app-server-projects-migration-by-host': []}, home, APP)['supported'])

    def test_rpc_mutations_and_unsafe_host_alias_refused(self):
        client = rt.ReadOnlyRPC.__new__(rt.ReadOnlyRPC)
        with self.assertRaisesRegex(rt.EvidenceError, 'Mutation'):
            client.request('project/create', {})
        for host in ('-oProxyCommand=bad', 'host;command', 'host\ncommand'):
            with self.subTest(host=host), self.assertRaises(rt.EvidenceError):
                rt.probe(host, [])

    def test_probe_uses_reported_codex_home_and_never_retains_task_content(self):
        class RPC:
            closed = False
            calls = []
            def __init__(self, cli): pass
            def request(self, method, params):
                RPC.calls.append((method, copy.deepcopy(params)))
                return {'initialize': {'codexHome': '/nondefault/codex'},
                        'config/read': {'config': {'projects': {str(project): {'trust_level': 'trusted'}}}},
                        'project/list': {'data': [], 'nextCursor': None},
                        'thread/list': {'data': [{'id': 'task', 'cwd': str(project), 'projectId': 'server-project',
                                                  'preview': 'PRIVATE TASK CONTENT'}], 'nextCursor': None}}[method]
            def send(self, message): pass
            def close(self): RPC.closed = True
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            with patch.object(rt, 'ReadOnlyRPC', RPC), patch.object(rt.shutil, 'which', return_value='/fixture/codex'), \
                 patch.object(rt, 'hardware_id', return_value=MACHINE):
                result = rt.probe_local([str(project)])
        self.assertEqual(result['codex_home'], '/nondefault/codex')
        self.assertTrue(result['tasks_complete'])
        self.assertEqual(result['tasks'][str(project)], ['task'])
        self.assertEqual(result['server_task_assignments'], {'task': 'server-project'})
        params = next(params for method, params in RPC.calls if method == 'thread/list')
        self.assertTrue(params['useStateDbOnly'])
        self.assertEqual(params['modelProviders'], [])
        self.assertEqual(set(params['sourceKinds']), {
            'cli', 'vscode', 'exec', 'appServer', 'subAgent', 'subAgentReview',
            'subAgentCompact', 'subAgentThreadSpawn', 'subAgentOther', 'unknown'})
        self.assertEqual(len(params['sourceKinds']), 10)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertTrue(RPC.closed)


    def test_saved_connection_identity_cannot_come_from_snapshot(self):
        state, _ = fixture()
        bound = rt.connection_binding(state, NEW, 'fixture-ssh')
        self.assertEqual(bound['hostId'], NEW)
        for bad_state, host, alias in [
            ({}, NEW, 'fixture-ssh'),
            (state, NEW, 'wrong-ssh'),
            (dict(state, **{'codex-managed-remote-connections':
              state['codex-managed-remote-connections'] * 2}), NEW, 'fixture-ssh'),
        ]:
            with self.subTest(alias=alias), self.assertRaises(rt.EvidenceError):
                rt.connection_binding(bad_state, host, alias)
        custom = copy.deepcopy(state)
        custom['codex-managed-remote-connections'][0]['codexHome'] = '/unverified/home'
        with self.assertRaisesRegex(rt.EvidenceError, 'Custom'):
            rt.connection_binding(custom, NEW, 'fixture-ssh')

    def test_probe_incomplete_task_api_cannot_claim_coverage(self):
        class RPC:
            closed = False
            def __init__(self, cli): pass
            def request(self, method, params):
                if method == 'thread/list':
                    raise rt.EvidenceError('not available')
                return {'initialize': {'codexHome': '/nondefault/codex'},
                        'config/read': {'config': {}},
                        'project/list': {'data': [], 'nextCursor': None}}[method]
            def send(self, message): pass
            def close(self): RPC.closed = True
        with patch.object(rt, 'ReadOnlyRPC', RPC), patch.object(rt.shutil, 'which', return_value='/fixture/codex'), \
             patch.object(rt, 'hardware_id', return_value=MACHINE):
            result = rt.probe_local([])
        self.assertFalse(result['tasks_complete'])
        self.assertTrue(result['server_inventory_complete'])
        self.assertTrue(RPC.closed)


    def test_local_keyword_cannot_be_bound_to_remote_sidebar_connection(self):
        state = {'codex-managed-remote-connections': [
            {'hostId': 'remote-ssh-discovered:local', 'source': 'discovered', 'alias': 'local'}]}
        with self.assertRaises(rt.EvidenceError):
            rt.connection_binding(state, 'remote-ssh-discovered:local', 'local')

    def test_truncated_desktop_archive_produces_structured_evidence_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'Fixture.app'
            resources = app / 'Contents/Resources'
            resources.mkdir(parents=True)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': APP['bundle_id'],
                'CFBundleShortVersionString': APP['version'], 'CFBundleVersion': APP['build']}))
            (resources / 'app.asar').write_bytes(b'bad')
            with self.assertRaises(rt.EvidenceError):
                rt.desktop(str(app))

    def test_project_and_sidebar_physical_identity_use_identical_ioreg_evidence(self):
        raw = b'| IOPlatformExpertDevice\n    "IOPlatformUUID" = "SYNTHETIC-MACHINE-UUID"\n'
        result = r.legacy.subprocess.CompletedProcess([], 0, stdout=raw)
        with patch.object(rt.subprocess, 'check_output', return_value=raw) as project_probe, \
             patch.object(r.legacy.subprocess, 'run', return_value=result) as sidebar_probe:
            self.assertEqual(rt.hardware_id(), r.legacy.machine_id())
            self.assertEqual(project_probe.call_args.args[0], sidebar_probe.call_args.args[0])


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.state, self.evidence = fixture()
        self.state['remote-projects'].append(
            {'id': 'other-device-project', 'hostId': 'different-physical-mac',
             'label': 'Private other device', 'remotePath': '/other-mac/private-project'})
        r.atomic(self.home / r.STATE, r.encoded(self.state))
        r.atomic(self.home / 'auth.json', r.encoded({'tokens': {'account_id': 'target'}}))
        self.originals = {p.name: p.read_bytes() for p in self.home.iterdir()}
        self.patches = [
            patch.object(r.legacy, 'machine_id', return_value=SIDEBAR),
            patch.object(r.legacy, 'running', return_value=True),
            patch.object(rt, 'desktop', return_value=APP),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def assert_read_only(self):
        self.assertEqual({p.name: p.read_bytes() for p in self.home.iterdir()}, self.originals)

    def test_ambiguous_client_hosts_require_selection_before_any_probe(self):
        with patch.object(rt, 'probe') as probe:
            with self.assertRaisesRegex(r.Refusal, 'old-host'):
                r.inspect(self.home, project_host='fixture-ssh')
            probe.assert_not_called()
            with self.assertRaisesRegex(r.Refusal, 'old-host'):
                r.inspect(self.home, project_host='fixture-ssh', connection_host='not-registered')
            probe.assert_not_called()
        self.assert_read_only()

    def test_selected_batch_never_probes_another_client_host_path(self):
        with patch.object(rt, 'probe', return_value=self.evidence) as probe:
            result = r.inspect(self.home, project_host='fixture-ssh', connection_host=OLD)
            probe.assert_called_once_with('fixture-ssh', [PATH])
        self.assertEqual(result['project_host']['machine'], MACHINE)
        self.assertEqual(result['project_host']['codex_home'], '/custom/codex-home')
        self.assertEqual(result['project_host']['selected_connection'], OLD)
        self.assertEqual(result['project_host']['paths'], self.evidence['paths'])
        self.assertEqual(result['connections'][0], {'hostId': NEW, 'source': 'discovered', 'alias': 'fixture-ssh'})
        self.assert_read_only()

    def test_summary_has_counts_without_private_identity_or_inventory(self):
        with patch.object(rt, 'probe', return_value=self.evidence) as probe:
            result = r.inspect(self.home, project_host='fixture-ssh', connection_host=OLD, summary=True)
            probe.assert_called_once_with('fixture-ssh', [PATH])
        self.assertEqual(result['remote_registration_count'], 2)
        self.assertEqual(result['trust_counts'], {'trusted': 1, 'other': 0})
        self.assertEqual(result['desktop'], {'version': APP['version'], 'build': APP['build']})
        text = json.dumps(result)
        for private_value in (PATH, '/other-mac/private-project', '/custom/codex-home',
                              'Private other device', MACHINE, SIDEBAR, NEW, 'fixture-ssh', 'source-section'):
            self.assertNotIn(private_value, text)
        for private_key in ('projects', 'accounts', 'connections', 'active_account', 'sidebar_machine',
                            'codex_home', 'project_host'):
            self.assertNotIn(private_key, result)
        self.assert_read_only()

    def test_inspection_without_project_host_never_probes(self):
        with patch.object(rt, 'probe') as probe:
            result = r.inspect(self.home, summary=True)
            probe.assert_not_called()
        self.assertIsNone(result['server_inventory'])
        self.assert_read_only()

    def test_unknown_registration_fields_are_diagnosed_without_host_probe(self):
        self.state['remote-projects'][0]['future-schema-field'] = {'private': 'unknown-data'}
        r.atomic(self.home / r.STATE, r.encoded(self.state))
        self.originals = {p.name: p.read_bytes() for p in self.home.iterdir()}
        with patch.object(rt, 'probe') as probe:
            result = r.inspect(self.home, project_host='fixture-ssh', connection_host=OLD, summary=True)
            probe.assert_not_called()
        self.assertFalse(result['registrations_supported'])
        self.assertIn('compatibility', result)
        self.assertIn('supported', result['compatibility'])
        self.assertNotIn('unknown-data', json.dumps(result))
        self.assert_read_only()



class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / 'home'
        self.home.mkdir()
        self.record = self.home.parent / 'recovery'
        self.state, self.evidence = fixture()
        self.patches = [
            patch.object(r.legacy, 'machine_id', return_value=SIDEBAR),
            patch.object(r.legacy, 'running', return_value=False),
            patch.object(rt, 'desktop', return_value=APP),
            patch.object(rt, 'probe', side_effect=lambda *args: copy.deepcopy(self.evidence)),
        ]
        for item in self.patches:
            item.start()
        self.write_state(self.state)
        r.atomic(self.home / (r.STATE + '.bak'), r.encoded(self.state))
        r.atomic(self.home / 'auth.json', r.encoded({'tokens': {'account_id': 'target'}}))
        r.prepare(self.home, self.record, 'source', OLD, NEW, 'fixture-ssh')
        self.plan = r.read(self.record / 'plan.json')
        self.pid = self.plan['created'][0]['project']['id']

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def write_state(self, state):
        r.atomic(self.home / r.STATE, r.encoded(state))

    def apply(self):
        return r.transact(self.home, self.record)

    def event(self, action, stage, sections, **options):
        return r.native_event(self.record, {'operation_id': action['id'], 'stage': stage,
                                            'observed_at': time.time(), 'sections': sections}, **options)

    def placed(self):
        return [section(items=['codex:project:old', 'codex:project:' + self.pid])]

    def observations(self):
        return {'account_id': 'target', 'sidebar_machine': SIDEBAR, 'collected_at': time.time(),
                'complete': {'projects': True, 'sections': True, 'task_associations': True},
                'projects': [{'id': self.pid, 'hostId': NEW, 'remotePath': PATH, 'task_ids': ['existing-task']}],
                'sections': self.placed(), 'historical_task_reads': ['existing-task']}

    def finish_native(self):
        action = self.plan['native_actions'][0]
        self.event(action, 'intent', [section(items=['codex:project:old'])])
        state = r.read(self.home / r.STATE)
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = self.placed()
        self.write_state(state)
        self.event(action, 'confirmed', self.placed())

    def test_apply_repeat_and_second_prepare_are_idempotent(self):
        self.assertEqual(self.apply()['phase'], 'applied-unverified')
        once = (self.home / r.STATE).read_bytes()
        self.assertEqual(self.apply()['phase'], 'applied-unverified')
        self.assertEqual((self.home / r.STATE).read_bytes(), once)
        self.finish_native()
        self.assertEqual(r.verify(self.home, self.record, self.observations())['phase'], 'verified')
        next_record = self.record.parent / 'again'
        result = r.prepare(self.home, next_record, 'source', OLD, NEW, 'fixture-ssh')
        self.assertEqual(result['added_projects'], [])
        self.assertEqual(result['native_actions'], [])

    def test_stale_source_destination_account_and_home_refused(self):
        for change, message in [
            (lambda s: s['remote-projects'][0].update(label='Source changed'), 'source'),
            (lambda s: s[r.ATOM][r.LAYOUTS]['target']['sections'][0].update(name='Renamed'), 'Destination'),
        ]:
            with self.subTest(message=message):
                state = copy.deepcopy(self.state)
                change(state)
                self.write_state(state)
                with self.assertRaisesRegex(r.Refusal, message):
                    self.apply()
        self.write_state(self.state)
        r.atomic(self.home / 'auth.json', r.encoded({'tokens': {'account_id': 'other'}}))
        with self.assertRaisesRegex(r.Refusal, 'account changed'):
            self.apply()

    def test_rechecks_machine_home_path_and_trust_before_files(self):
        for key, value, message in [
            ('machine', 'c' * 64, 'identity/home'),
            ('codex_home', '/different/home', 'identity/home'),
        ]:
            with self.subTest(key=key):
                original = self.evidence[key]
                self.evidence[key] = value
                with self.assertRaisesRegex(r.Refusal, message):
                    self.apply()
                self.evidence[key] = original
        self.evidence['paths'][PATH]['file_id'] = [7, 999]
        with self.assertRaisesRegex(r.Refusal, 'path changed'):
            self.apply()
        self.evidence['paths'][PATH]['file_id'] = [7, 101]
        self.evidence['paths'][PATH]['trust'] = None
        with self.assertRaisesRegex(r.Refusal, 'consent'):
            self.apply()
        self.assertEqual(r.read(self.home / r.STATE), self.state)
        self.assertFalse((self.record / 'journal.json').exists())

    def test_trust_gap_prepare_is_reviewable_and_blocks_entire_batch(self):
        self.evidence['paths'][PATH]['trust'] = None
        blocked = self.record.parent / 'blocked'
        preview = r.prepare(self.home, blocked, 'source', OLD, NEW, 'fixture-ssh')
        self.assertEqual(preview['phase'], 'prepared-blocked')
        self.assertEqual(preview['trust_blockers'][0]['path'], PATH)
        with self.assertRaisesRegex(r.Refusal, 'consent'):
            r.transact(self.home, blocked)
        self.assertEqual(r.read(self.home / r.STATE), self.state)

    def test_unrelated_shutdown_edits_and_later_registration_survive_rollback(self):
        self.state['unrelated']['shutdown'] = True
        self.write_state(self.state)
        self.apply()
        later = {'id': 'later', 'hostId': NEW, 'label': 'Later', 'remotePath': '/example/later'}
        for name in (r.STATE, r.STATE + '.bak'):
            state = r.read(self.home / name)
            state['remote-projects'].append(later)
            state['project-order'].append('later')
            state['project-appearances']['later'] = {'icon': 'star'}
            state['unrelated']['new'] = 7
            r.atomic(self.home / name, r.encoded(state))
        result = r.transact(self.home, self.record, True)
        self.assertEqual(result['phase'], 'metadata-rolled-back')
        final = r.read(self.home / r.STATE)
        self.assertEqual(final['remote-projects'], self.state['remote-projects'] + [later])
        self.assertEqual(final['project-order'], ['old', 'later'])
        self.assertEqual(final['unrelated'], {'keep': True, 'shutdown': True, 'new': 7})

    def test_interrupted_backup_main_resumes_without_duplicate_registrations(self):
        real = r.atomic
        def fail(path, raw):
            if path == self.home / r.STATE:
                raise OSError('simulated interruption')
            return real(path, raw)
        with patch.object(r, 'atomic', side_effect=fail), self.assertRaises(OSError):
            self.apply()
        self.assertEqual(r.read(self.home / r.STATE), self.state)
        self.assertEqual(len(r.read(self.home / (r.STATE + '.bak'))['remote-projects']), 2)
        self.assertEqual(self.apply()['phase'], 'applied-unverified')
        for name in (r.STATE, r.STATE + '.bak'):
            self.assertEqual(len(r.read(self.home / name)['remote-projects']), 2)

    def test_interrupted_backup_main_can_rollback(self):
        real = r.atomic
        def fail(path, raw):
            if path == self.home / r.STATE:
                raise OSError('simulated interruption')
            return real(path, raw)
        with patch.object(r, 'atomic', side_effect=fail), self.assertRaises(OSError):
            self.apply()
        r.transact(self.home, self.record, True)
        self.assertEqual(r.read(self.home / r.STATE), self.state)
        self.assertEqual(r.read(self.home / (r.STATE + '.bak')), self.state)

    def test_running_app_and_relaunch_between_writes_are_refused(self):
        with patch.object(r.legacy, 'running', return_value=True), self.assertRaisesRegex(r.Refusal, 'Close'):
            self.apply()
        real = r.atomic
        running = [False]
        def relaunch(path, raw):
            real(path, raw)
            if path == self.home / (r.STATE + '.bak'):
                running[0] = True
        with patch.object(r, 'atomic', side_effect=relaunch), \
             patch.object(r.legacy, 'running', side_effect=lambda: running[0]), self.assertRaisesRegex(r.Refusal, 'Close'):
            self.apply()
        self.assertEqual(r.read(self.home / r.STATE), self.state)
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'writing')

    def test_app_hash_account_and_migration_rechecked_between_writes(self):
        real = r.atomic
        def migrate(path, raw):
            real(path, raw)
            if path == self.home / (r.STATE + '.bak'):
                state = r.read(self.home / r.STATE)
                state['app-server-projects-migration-by-host'] = {NEW: {'complete': True}}
                self.write_state(state)
        with patch.object(r, 'atomic', side_effect=migrate), self.assertRaisesRegex(r.Refusal, 'ownership changed'):
            self.apply()
        self.assertEqual(len(r.read(self.home / r.STATE)['remote-projects']), 1)

    def test_rollback_refuses_owned_registration_and_appearance_edits(self):
        self.apply()
        applied = r.read(self.home / r.STATE)
        for field in ('label', 'appearance'):
            state = copy.deepcopy(applied)
            if field == 'label':
                state['remote-projects'][-1]['label'] = 'Later name'
            else:
                state['project-appearances'][self.pid] = {'icon': 'later'}
            self.write_state(state)
            with self.subTest(field=field), self.assertRaisesRegex(r.Refusal, 'Later'):
                r.transact(self.home, self.record, True)
            self.assertEqual(r.read(self.home / r.STATE), state)

    def test_rollback_refuses_owned_order_edits(self):
        self.apply()
        state = r.read(self.home / r.STATE)
        state['project-order'] = [self.pid, 'old']
        self.write_state(state)
        with self.assertRaisesRegex(r.Refusal, 'order|edit'):
            r.transact(self.home, self.record, True)

    def test_native_intent_must_precede_results_and_uncertain_result_is_reconciled(self):
        self.apply()
        action = self.plan['native_actions'][0]
        with self.assertRaisesRegex(r.Refusal, 'intent first'):
            self.event(action, 'confirmed', self.placed())
        self.event(action, 'intent', [section(items=['codex:project:old'])])
        self.event(action, 'unresolved', self.placed())
        with self.assertRaisesRegex(r.Refusal, 'existing native intent'):
            self.event(action, 'intent', self.placed())
        self.event(action, 'confirmed', self.placed())
        with self.assertRaisesRegex(r.Refusal, 'cannot be replayed'):
            self.event(action, 'confirmed', self.placed())
        events = r.read(self.record / 'native.json')['events']
        self.assertEqual([e['stage'] for e in events], ['intent', 'unresolved', 'confirmed'])

    def test_native_placement_must_reverse_before_file_rollback(self):
        self.apply()
        self.finish_native()
        with self.assertRaisesRegex(r.Refusal, 'native placements'):
            r.transact(self.home, self.record, True)
        self.event(self.plan['native_actions'][0], 'rollback-intent', self.placed())
        state = r.read(self.home / r.STATE)
        state[r.ATOM][r.LAYOUTS]['target']['sections'][0]['itemKeys'] = ['codex:project:old']
        self.write_state(state)
        self.event(self.plan['native_actions'][0], 'reversed', [section(items=['codex:project:old'])])
        r.transact(self.home, self.record, True)

    def test_verification_needs_complete_native_task_and_read_evidence(self):
        self.apply()
        obs = self.observations()
        with self.assertRaisesRegex(r.Refusal, 'Native operation evidence'):
            r.verify(self.home, self.record, obs)
        self.finish_native()
        obs = self.observations()
        for mutate, message in [
            (lambda o: o['complete'].update(task_associations=False), 'Complete'),
            (lambda o: o.update(historical_task_reads=[]), 'pre-existing'),
            (lambda o: o['projects'][0].update(task_ids=[]), 'association'),
            (lambda o: o.update(sections=[]), 'placement differ'),
            (lambda o: o.update(collected_at=0), 'Fresh'),
        ]:
            candidate = copy.deepcopy(obs)
            mutate(candidate)
            with self.subTest(message=message), self.assertRaisesRegex(r.Refusal, message):
                r.verify(self.home, self.record, candidate)
            self.assertEqual(r.read(self.record / 'status.json')['phase'], 'applied-unverified')
        self.assertEqual(r.verify(self.home, self.record, obs)['phase'], 'verified')

    def test_inventory_audit_with_running_app_preserves_status_and_requires_separate_membership(self):
        self.apply()
        before = {p.name: p.read_bytes() for p in self.home.iterdir() if p.is_file()}
        status = (self.record / 'status.json').read_bytes()
        with patch.object(r.legacy, 'running', return_value=True):
            first = r.audit_inventory(self.home, self.record)
            second = r.audit_inventory(self.home, self.record)
        self.assertEqual(first['inventory_status'], 'verified')
        self.assertEqual(first['phase'], 'applied-unverified')
        self.assertEqual(first['recorded_tasks_observed'], 1)
        self.assertEqual(first['candidates_at_expected_paths'], 1)
        self.assertFalse(first['application_membership_checked'])
        self.assertNotEqual(first['receipt'], second['receipt'])
        self.assertEqual(Path(first['receipt']).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.record / 'status.json').read_bytes(), status)
        self.assertEqual({p.name: p.read_bytes() for p in self.home.iterdir() if p.is_file()}, before)
        self.finish_native()
        observations = self.observations()
        observations['complete']['task_associations'] = False
        with self.assertRaisesRegex(r.Refusal, 'Complete'):
            r.verify(self.home, self.record, observations)

    def test_inventory_audit_distinguishes_partial_unobserved_tasks_from_complete_conflicts(self):
        self.apply()
        self.evidence['tasks'][PATH] = []
        self.evidence['tasks_complete'] = False
        result = r.audit_inventory(self.home, self.record)
        self.assertEqual(result['inventory_status'], 'incomplete')
        self.assertEqual(result['recorded_tasks_observed'], 0)
        self.evidence['tasks_complete'] = True
        result = r.audit_inventory(self.home, self.record)
        self.assertEqual(result['inventory_status'], 'conflicts')
        self.assertEqual(r.read(Path(result['receipt']))['not_observed_task_ids'], ['existing-task'])
        self.assertNotIn('existing-task', json.dumps(result))
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'applied-unverified')

    def test_inventory_audit_reports_later_assignment_choices_without_rewriting(self):
        self.apply()
        state = r.read(self.home / r.STATE)
        state['projectless-thread-ids'] = ['existing-task']
        self.write_state(state)
        self.evidence['server_task_assignments'] = {'existing-task': 'later-project'}
        result = r.audit_inventory(self.home, self.record)
        self.assertEqual(result['inventory_status'], 'conflicts')
        self.assertEqual(result['server_assignment_changes'], 1)
        self.assertEqual(result['client_choice_changes'], 1)
        self.assertEqual(r.read(self.home / r.STATE), state)

    def test_inventory_audit_rechecks_host_home_and_paths(self):
        self.apply()
        original = copy.deepcopy(self.evidence)
        for key, value in [('machine', 'different'), ('codex_home', '/different/home'),
                           ('paths', {PATH: {'canonical': PATH, 'file_id': [8, 202]}})]:
            self.evidence = dict(original, **{key: value})
            with self.subTest(key=key), self.assertRaisesRegex(r.Refusal, 'changed'):
                r.audit_inventory(self.home, self.record)
        self.assertFalse(list(self.record.glob('inventory-audit-*.json')))

    def test_inventory_audit_refuses_client_choice_drift_during_probe(self):
        self.apply()
        def drift(*args):
            state = r.read(self.home / r.STATE)
            state['projectless-thread-ids'] = ['existing-task']
            self.write_state(state)
            return self.evidence
        with patch.object(rt, 'probe', side_effect=drift), self.assertRaisesRegex(r.Refusal, 'during inventory audit'):
            r.audit_inventory(self.home, self.record)
        self.assertFalse(list(self.record.glob('inventory-audit-*.json')))

    def test_inventory_audit_resolves_reused_destination_alias_path(self):
        alias = '/example/project-alias'
        state = copy.deepcopy(self.state)
        state['remote-projects'].append({'id': 'current', 'hostId': NEW,
                                         'label': 'Existing', 'remotePath': alias})
        self.evidence['paths'][alias] = copy.deepcopy(self.evidence['paths'][PATH])
        self.evidence['tasks'][alias] = ['existing-task']
        self.write_state(state)
        record = self.record.parent / 'alias-recovery'
        r.prepare(self.home, record, 'source', OLD, NEW, 'fixture-ssh')
        r.transact(self.home, record)
        with patch.object(rt, 'probe', return_value=self.evidence) as probe:
            result = r.audit_inventory(self.home, record)
        self.assertEqual(set(probe.call_args.args[1]), {PATH, alias})
        self.assertEqual(result['inventory_status'], 'verified')
        self.assertEqual(result['candidates_at_expected_paths'], 1)

    def test_inventory_audit_cli_needs_no_observations_and_reports_incomplete_exit(self):
        self.apply()
        args = ['helper', 'verify', '--inventory-only', '--codex-home', str(self.home), '--record', str(self.record)]
        with patch.object(r.sys, 'argv', args), patch.object(r.sys, 'stdout', io.StringIO()), \
             patch.object(r.legacy.platform, 'system', return_value='Darwin'):
            self.assertEqual(r.main(), 0)
            self.evidence['tasks_complete'] = False
            self.assertEqual(r.main(), 2)
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'applied-unverified')

    def test_inventory_mode_cannot_change_legacy_receipt_semantics(self):
        with patch.object(r, 'load_record', return_value=(self.record, {'schema': 1})), \
             self.assertRaisesRegex(r.Refusal, 'v2 receipt'):
            r.audit_inventory(self.home, self.record)

    def test_same_account_apply_and_verify_permit_only_recorded_additions(self):
        same = self.record.parent / 'same-account'
        r.prepare(self.home, same, 'target', OLD, NEW, 'fixture-ssh')
        r.transact(self.home, same)
        plan = r.read(same / 'plan.json')
        pid = plan['created'][0]['project']['id']
        action = plan['native_actions'][0]
        r.native_event(same, {'operation_id': action['id'], 'stage': 'intent',
                             'observed_at': time.time(), 'sections': [section(items=['codex:project:old'])]})
        state = r.read(self.home / r.STATE)
        ss = [section(items=['codex:project:old', 'codex:project:' + pid])]
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = ss
        self.write_state(state)
        r.native_event(same, {'operation_id': action['id'], 'stage': 'confirmed',
                             'observed_at': time.time(), 'sections': ss})
        obs = self.observations()
        obs['projects'][0]['id'] = pid
        obs['sections'] = ss
        self.assertEqual(r.verify(self.home, same, obs)['phase'], 'verified')

    def test_missing_backup_round_trip_and_private_artifacts(self):
        (self.home / (r.STATE + '.bak')).unlink()
        self.apply()
        self.assertTrue((self.home / (r.STATE + '.bak')).exists())
        r.transact(self.home, self.record, True)
        self.assertFalse((self.home / (r.STATE + '.bak')).exists())
        self.assertEqual(self.record.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in self.record.iterdir()))
        text = ''.join(p.read_text() for p in self.record.iterdir() if p.is_file())
        self.assertNotIn('"tokens"', text)
        self.assertNotIn('auth.json', text)

    def test_owned_id_cannot_collide_with_historical_registration_even_with_rehashed_plan(self):
        plan = copy.deepcopy(self.plan)
        plan['created'][0]['project']['id'] = 'old'
        raw = r.encoded(plan)
        r.atomic(self.record / 'plan.json', raw)
        r.atomic(self.record / 'plan.sha256.json', r.encoded({'sha256': r.digest(raw)}))
        with self.assertRaises(r.Refusal):
            self.apply()
        self.assertEqual(r.read(self.home / r.STATE), self.state)

    def test_native_section_creation_reconciles_interruption_without_duplicate_intent(self):
        snapshot = self.record.parent / 'portable' / 'layout.json'
        r.private_write(snapshot, layout(self.state, self.evidence))
        state = copy.deepcopy(self.state)
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = []
        self.write_state(state)
        # The backup may have older section metadata; file repair leaves it intact.
        record = self.record.parent / 'new-section'
        r.prepare(self.home, record, new_host=NEW, project_host='fixture-ssh', source_layout=snapshot)
        r.transact(self.home, record)
        plan = r.read(record / 'plan.json')
        action = plan['native_actions'][0]
        self.assertEqual(action['kind'], 'create-section')
        def event(stage, ss, **options):
            return r.native_event(record, {'operation_id': action['id'], 'stage': stage,
                                          'observed_at': time.time(), 'sections': ss}, **options)
        event('intent', [])
        created = [section('created-section', 'Research')]
        event('unresolved', created)
        event('confirmed', created)
        with self.assertRaisesRegex(r.Refusal, 'existing native intent'):
            event('intent', created)
        with self.assertRaises(r.Refusal):
            event('reversed', [])
        with self.assertRaises(r.Refusal):
            event('rollback-intent', created)
        for changed in [
            [section('created-section', 'Changed name')],
            [section('different-id', 'Research')],
            [section('created-section', 'Research', ['codex:project:unrelated'])],
        ]:
            with self.subTest(changed=changed), self.assertRaises(r.Refusal):
                event('rollback-intent', changed, remove_empty_sections=True)
        event('rollback-intent', created, remove_empty_sections=True)
        with self.assertRaisesRegex(r.Refusal, 'still present'):
            event('reversed', created)
        event('rollback-unresolved', [])
        event('reversed', [])
        with self.assertRaisesRegex(r.Refusal, 'cannot be replayed'):
            event('confirmed', created)

    def test_explicit_task_choice_edit_after_prepare_blocks_apply(self):
        state = copy.deepcopy(self.state)
        state['thread-project-assignments'] = {'existing-task': 'another-project'}
        self.write_state(state)
        with self.assertRaisesRegex(r.Refusal, 'task choices changed'):
            self.apply()

    def test_noop_preview_rechecks_source_drift(self):
        self.apply()
        self.finish_native()
        record = self.record.parent / 'noop'
        r.prepare(self.home, record, 'source', OLD, NEW, 'fixture-ssh')
        self.assertEqual(r.read(record / 'plan.json')['created'], [])
        state = r.read(self.home / r.STATE)
        state['remote-projects'][0]['label'] = 'Changed source'
        self.write_state(state)
        with self.assertRaisesRegex(r.Refusal, 'source'):
            r.transact(self.home, record)

    def test_duplicate_native_section_result_is_not_confirmed(self):
        snapshot = self.record.parent / 'portable' / 'layout.json'
        r.private_write(snapshot, layout(self.state, self.evidence))
        state = copy.deepcopy(self.state)
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = []
        self.write_state(state)
        record = self.record.parent / 'ambiguous-section'
        r.prepare(self.home, record, new_host=NEW, project_host='fixture-ssh', source_layout=snapshot)
        r.transact(self.home, record)
        action = r.read(record / 'plan.json')['native_actions'][0]
        self.assertEqual(action['kind'], 'create-section')
        def event(stage, sections):
            return r.native_event(record, {'operation_id': action['id'], 'stage': stage,
                                          'observed_at': time.time(), 'sections': sections})
        event('intent', [])
        with self.assertRaisesRegex(r.Refusal, 'unique observed section'):
            event('confirmed', [section('first', 'Research'), section('duplicate', 'Research')])
        self.assertEqual(r.read(record / 'native.json')['events'][-1]['stage'], 'intent')


    def test_native_rollback_requires_intent_and_reconciles_unknown_result(self):
        self.apply()
        self.finish_native()
        action = self.plan['native_actions'][0]
        restored = [section(items=['codex:project:old'])]
        with self.assertRaises(r.Refusal):
            self.event(action, 'reversed', restored)
        for changed in [
            [section('different-section', 'Research', ['codex:project:' + self.pid])],
            [section('target-section', 'Renamed', ['codex:project:' + self.pid])],
        ]:
            with self.subTest(changed=changed), self.assertRaises(r.Refusal):
                self.event(action, 'rollback-intent', changed)
        self.event(action, 'rollback-intent', self.placed())
        self.event(action, 'rollback-unresolved', restored)
        self.event(action, 'reversed', restored)
        self.assertEqual([x['stage'] for x in r.read(self.record / 'native.json')['events']],
                         ['intent', 'confirmed', 'rollback-intent', 'rollback-unresolved', 'reversed'])

    def test_later_appearance_added_to_originally_absent_slot_blocks_rollback(self):
        state = copy.deepcopy(self.state)
        state.pop('project-appearances')
        self.write_state(state)
        r.atomic(self.home / (r.STATE + '.bak'), r.encoded(state))
        record = self.record.parent / 'without-appearance'
        r.prepare(self.home, record, 'source', OLD, NEW, 'fixture-ssh')
        plan = r.read(record / 'plan.json')
        self.assertIsNone(plan['created'][0]['appearance'])
        r.transact(self.home, record)
        state = r.read(self.home / r.STATE)
        pid = plan['created'][0]['project']['id']
        state['project-appearances'] = {pid: {'icon': 'user-choice'}}
        self.write_state(state)
        with self.assertRaisesRegex(r.Refusal, 'appearance|edit'):
            r.transact(self.home, record, True)
        self.assertEqual(r.read(self.home / r.STATE), state)

    def test_unrelated_original_order_edits_survive_rollback(self):
        state = copy.deepcopy(self.state)
        other = {'id': 'unrelated-original', 'hostId': 'another-host',
                 'label': 'Other original', 'remotePath': '/other/project'}
        state['remote-projects'].append(other)
        state['project-order'].append(other['id'])
        self.write_state(state)
        r.atomic(self.home / (r.STATE + '.bak'), r.encoded(state))
        record = self.record.parent / 'unrelated-order'
        r.prepare(self.home, record, 'source', OLD, NEW, 'fixture-ssh')
        pid = r.read(record / 'plan.json')['created'][0]['project']['id']
        r.transact(self.home, record)
        state = r.read(self.home / r.STATE)
        state['project-order'] = [other['id'], 'old', pid]
        self.write_state(state)
        r.transact(self.home, record, True)
        self.assertEqual(r.read(self.home / r.STATE)['project-order'], [other['id'], 'old'])

    def test_source_new_section_after_preview_refused(self):
        state = copy.deepcopy(self.state)
        state[r.ATOM][r.LAYOUTS]['source']['sections'].append(section('later-source', 'Later'))
        self.write_state(state)
        with self.assertRaisesRegex(r.Refusal, 'source'):
            self.apply()
        self.assertFalse((self.record / 'journal.json').exists())

    def test_source_new_unrelated_section_after_apply_refused_by_verify(self):
        self.apply()
        self.finish_native()
        state = r.read(self.home / r.STATE)
        state[r.ATOM][r.LAYOUTS]['source']['sections'].append(section('later-source', 'Later'))
        self.write_state(state)
        with self.assertRaisesRegex(r.Refusal, 'source'):
            r.verify(self.home, self.record, self.observations())
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'applied-unverified')

    def test_cli_section_removal_flag_is_rollback_only(self):
        args = ['helper', 'apply', '--codex-home', str(self.home), '--record', str(self.record),
                '--remove-empty-sections']
        with patch.object(r.sys, 'argv', args), patch.object(r.sys, 'stdout', io.StringIO()), \
             patch.object(r.legacy.platform, 'system', return_value='Darwin'), \
             patch.object(r, 'transact') as transaction:
            self.assertEqual(r.main(), 2)
            transaction.assert_not_called()


    def test_expired_worker_preserves_interrupted_transaction_status(self):
        r.save_status(self.record, 'writing', interruption='fixture')
        status_before = (self.record / 'status.json').read_bytes()
        files_before = {name: (self.home / name).read_bytes() for name in (r.STATE, r.STATE + '.bak')}
        with patch.object(r.legacy, 'running', return_value=True), \
             patch.object(r.time, 'monotonic', side_effect=[0, 0, 2]), \
             patch.object(r.time, 'sleep') as sleep, \
             patch.object(r, 'transact_locked') as transaction:
            with self.assertRaisesRegex(r.Refusal, 'expired'):
                r.wait_and_transact(self.home, self.record, 1)
            sleep.assert_called_once_with(0.5)
            transaction.assert_not_called()
        self.assertEqual((self.record / 'status.json').read_bytes(), status_before)
        self.assertEqual({name: (self.home / name).read_bytes() for name in files_before}, files_before)
        receipt = r.read(self.record / 'worker.json')
        self.assertEqual(receipt['phase'], 'expired')
        self.assertFalse(receipt['files_written_by_worker'])

    def test_worker_with_closed_app_applies_and_records_completion(self):
        with patch.object(r.time, 'sleep') as sleep:
            result = r.wait_and_transact(self.home, self.record, 10)
            sleep.assert_not_called()
        self.assertEqual(result['phase'], 'applied-unverified')
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'applied-unverified')
        receipt = r.read(self.record / 'worker.json')
        self.assertEqual(receipt['phase'], 'finished')
        self.assertEqual(receipt['result_phase'], 'applied-unverified')
        self.assertEqual(receipt['operation'], 'apply')

    def test_worker_resumes_after_app_exit_without_terminating_app(self):
        running = [True]
        def user_closes_app(_):
            running[0] = False
        with patch.object(r.legacy, 'running', side_effect=lambda: running[0]), \
             patch.object(r.time, 'sleep', side_effect=user_closes_app) as sleep:
            result = r.wait_and_transact(self.home, self.record, 10)
            sleep.assert_called_once_with(0.5)
        self.assertEqual(result['phase'], 'applied-unverified')
        self.assertEqual(r.read(self.record / 'worker.json')['phase'], 'finished')

    def test_worker_deadline_bounds_refuse_before_receipt_or_state_changes(self):
        before = (self.record / 'status.json').read_bytes()
        for seconds in (0, -1, 601):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(r.Refusal, 'Wait'):
                r.wait_and_transact(self.home, self.record, seconds)
        self.assertFalse((self.record / 'worker.json').exists())
        self.assertEqual((self.record / 'status.json').read_bytes(), before)
        self.assertEqual(r.read(self.home / r.STATE), self.state)

    def test_worker_error_leaves_transaction_diagnostic_and_stopped_receipt(self):
        def failed_transaction(*args):
            r.save_status(self.record, 'writing', interruption='fixture')
            raise OSError('fixture interrupted write')
        with patch.object(r, 'transact_locked', side_effect=failed_transaction), self.assertRaises(OSError):
            r.wait_and_transact(self.home, self.record, 10)
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'writing')
        self.assertEqual(r.read(self.record / 'worker.json')['phase'], 'stopped')
        self.assertTrue(r.read(self.record / 'worker.json')['inspect_transaction_status'])

    def test_second_worker_cannot_overwrite_active_worker_receipt(self):
        active = {'phase': 'waiting-for-app-exit', 'pid': 12345}
        r.atomic(self.record / 'worker.json', r.encoded(active))
        with r.record_lock(self.record):
            with self.assertRaises(BlockingIOError):
                r.wait_and_transact(self.home, self.record, 10)
        self.assertEqual(r.read(self.record / 'worker.json'), active)
        self.assertEqual(r.read(self.home / r.STATE), self.state)

    def test_rolled_back_record_cannot_apply_again(self):
        self.apply()
        r.transact(self.home, self.record, True)
        before = {name: (self.home / name).read_bytes() for name in (r.STATE, r.STATE + '.bak')}
        with self.assertRaisesRegex(r.Refusal, 'prepare|Prepare'):
            self.apply()
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'metadata-rolled-back')
        self.assertEqual({name: (self.home / name).read_bytes() for name in before}, before)


    def test_pinned_live_evidence_and_unpin_before_rollback(self):
        state = copy.deepcopy(self.state)
        for account in ('source', 'target'):
            state[r.ATOM][r.LAYOUTS][account]['sections'][0]['itemKeys'] = []
        state[r.ATOM][r.LAYOUTS]['target']['sections'].append(section('custom-pinned', 'Pinned'))
        state['pinned-project-ids'] = ['old']
        self.write_state(state)
        r.atomic(self.home / (r.STATE + '.bak'), r.encoded(state))
        record = self.record.parent / 'pinned'
        r.prepare(self.home, record, 'source', OLD, NEW, 'fixture-ssh')
        plan = r.read(record / 'plan.json')
        pid = plan['created'][0]['project']['id']
        action = plan['native_actions'][0]
        self.assertEqual(action['section_id'], 'pinned')
        r.transact(self.home, record)
        custom = state[r.ATOM][r.LAYOUTS]['target']['sections']
        before = custom + [section('pinned', 'Pinned', ['codex:project:old'])]
        after = custom + [section('pinned', 'Pinned', ['codex:project:old', 'codex:project:' + pid])]
        def event(stage, sections):
            return r.native_event(record, {'operation_id': action['id'], 'stage': stage,
                                          'observed_at': time.time(), 'sections': sections})
        event('intent', before)
        applied = r.read(self.home / r.STATE)
        applied['pinned-project-ids'].append(pid)
        self.write_state(applied)
        event('confirmed', after)
        obs = self.observations()
        obs['projects'][0]['id'] = pid
        obs['sections'] = custom
        with self.assertRaisesRegex(r.Refusal, 'placement differ'):
            r.verify(self.home, record, obs)
        obs['sections'] = after
        self.assertEqual(r.verify(self.home, record, obs)['phase'], 'verified')
        again = self.record.parent / 'pinned-again'
        preview = r.prepare(self.home, again, 'source', OLD, NEW, 'fixture-ssh')
        self.assertEqual(preview['added_projects'], [])
        self.assertEqual(preview['native_actions'], [])
        with self.assertRaisesRegex(r.Refusal, 'pinned placement'):
            r.transact(self.home, record, True)
        changed = [section('custom-pinned', 'Pinned', ['codex:project:' + pid]),
                   section('pinned', 'Pinned', ['codex:project:old'])]
        with self.assertRaises(r.Refusal):
            event('rollback-intent', changed)
        event('rollback-intent', after)
        applied['pinned-project-ids'].remove(pid)
        self.write_state(applied)
        event('reversed', before)
        r.transact(self.home, record, True)
        restored = r.read(self.home / r.STATE)
        self.assertEqual(restored['pinned-project-ids'], ['old'])
        self.assertEqual(restored['remote-projects'], state['remote-projects'])
        self.assertEqual(restored[r.ATOM][r.LAYOUTS]['target']['sections'], custom)


    def test_backend_assignment_changed_after_prepare_blocks_file_apply(self):
        self.evidence['server_task_assignments'] = {'existing-task': 'new-explicit-project'}
        with self.assertRaisesRegex(r.Refusal, 'server task assignments changed'):
            self.apply()
        self.assertEqual(r.read(self.home / r.STATE), self.state)
        self.assertFalse((self.record / 'journal.json').exists())

    def test_backend_assignment_changed_after_apply_blocks_verification(self):
        self.apply()
        self.finish_native()
        self.evidence['server_task_assignments'] = {'existing-task': 'new-explicit-project'}
        with self.assertRaisesRegex(r.Refusal, 'server task assignments changed'):
            r.verify(self.home, self.record, self.observations())
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'applied-unverified')

    def test_verify_rechecks_complete_host_task_inventory(self):
        self.apply()
        self.finish_native()
        self.evidence['tasks_complete'] = False
        with self.assertRaisesRegex(r.Refusal, 'complete project-host evidence'):
            r.verify(self.home, self.record, self.observations())
        self.evidence['tasks_complete'] = True
        self.evidence['tasks'][PATH] = []
        with self.assertRaisesRegex(r.Refusal, 'server task assignments changed'):
            r.verify(self.home, self.record, self.observations())
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'applied-unverified')


    def test_added_canonical_equivalent_registration_invalidates_stale_preview(self):
        alias_path = '/alias/same-project'
        state = copy.deepcopy(self.state)
        state['remote-projects'].append(
            {'id': 'added-after-prepare', 'hostId': NEW, 'label': 'User added',
             'remotePath': alias_path})
        state['project-order'].append('added-after-prepare')
        self.write_state(state)
        evidence = copy.deepcopy(self.evidence)
        evidence['paths'][alias_path] = copy.deepcopy(evidence['paths'][PATH])
        def probe(host, paths):
            result = copy.deepcopy(evidence)
            result['paths'] = {path: evidence['paths'][path] for path in paths}
            return result
        with patch.object(rt, 'probe', side_effect=probe) as fresh_probe:
            with self.assertRaisesRegex(r.Refusal, 'Destination|registration'):
                self.apply()
            self.assertIn(alias_path, fresh_probe.call_args.args[1])
        self.assertEqual(r.read(self.home / r.STATE), state)
        self.assertFalse((self.record / 'journal.json').exists())

    def test_benign_json_key_reordering_does_not_stale_source_fingerprint(self):
        def reverse_keys(value):
            if isinstance(value, dict):
                return {key: reverse_keys(value[key]) for key in reversed(list(value))}
            if isinstance(value, list):
                return [reverse_keys(item) for item in value]
            return value
        reordered = reverse_keys(self.state)
        self.assertNotEqual(r.encoded(reordered), r.encoded(self.state))
        self.write_state(reordered)
        self.assertEqual(self.apply()['phase'], 'applied-unverified')
        self.finish_native()
        self.assertEqual(r.verify(self.home, self.record, self.observations())['phase'], 'verified')

    def test_backup_destination_conflict_is_diagnosed_during_prepare(self):
        backup = copy.deepcopy(self.state)
        backup['remote-projects'].append(
            {'id': 'backup-existing', 'hostId': NEW, 'label': 'Earlier registration', 'remotePath': PATH})
        r.atomic(self.home / (r.STATE + '.bak'), r.encoded(backup))
        record = self.record.parent / 'backup-conflict'
        with self.assertRaisesRegex(r.Refusal, r'Backup|backup|\.bak'):
            r.prepare(self.home, record, 'source', OLD, NEW, 'fixture-ssh')
        self.assertEqual(r.read(self.home / (r.STATE + '.bak')), backup)
        self.assertEqual(r.read(self.home / r.STATE), self.state)
        self.assertFalse((record / 'journal.json').exists())

    def test_cli_native_event_rejects_different_selected_codex_home(self):
        self.apply()
        event_file = self.record.parent / 'event' / 'intent.json'
        r.private_write(event_file, {
            'operation_id': self.plan['native_actions'][0]['id'], 'stage': 'intent',
            'observed_at': time.time(), 'sections': [section(items=['codex:project:old'])]})
        another_home = self.record.parent / 'another-home'
        another_home.mkdir()
        args = ['helper', 'apply', '--codex-home', str(another_home), '--record', str(self.record),
                '--native-event', str(event_file)]
        with patch.object(r.sys, 'argv', args), patch.object(r.sys, 'stdout', io.StringIO()), \
             patch.object(r.legacy.platform, 'system', return_value='Darwin'):
            self.assertEqual(r.main(), 2)
        self.assertEqual(r.read(self.record / 'native.json')['events'], [])


    def test_donor_snapshot_preparation_uses_selected_destination_and_no_imported_account(self):
        snapshot = self.record.parent / 'portable' / 'layout.json'
        r.private_write(snapshot, layout(self.state, self.evidence))
        donor = self.record.parent / 'donor'
        result = r.prepare(self.home, donor, new_host='remote-ssh-discovered:explicit-destination', project_host='explicit-destination',
                           source_layout=snapshot)
        plan = r.read(donor / 'plan.json')
        self.assertEqual(plan['target_account'], 'target')
        self.assertEqual(plan['project_host'], 'explicit-destination')
        self.assertEqual(plan['new_host'], 'remote-ssh-discovered:explicit-destination')
        self.assertIsNone(plan['source'])
        self.assertEqual(len(result['added_projects']), 1)


if __name__ == '__main__':
    unittest.main()
