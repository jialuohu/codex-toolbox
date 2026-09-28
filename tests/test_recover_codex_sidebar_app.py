"""Synthetic owning-app sidebar recovery tests; never touches an installed Codex app."""

import ast
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/workflow-tools/skills/recover-codex-sidebar/scripts/recover_sidebar.py'
spec = importlib.util.spec_from_file_location('sidebar_recovery_app_tests', SCRIPT)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)

SIDEBAR_MACHINE = 'b' * 64
PROJECT_MACHINE = 'a' * 64
HOST = 'remote-ssh-discovered:fixture-ssh'
PATH = '/example/project'


def section(sid, name, *items):
    return {'sectionId': sid, 'name': name, 'itemKeys': list(items)}


def project(pid='existing-id', path=PATH, host=HOST):
    return {'projectId': pid, 'projectKind': 'remote', 'label': 'Example', 'path': path,
            'hostId': host, 'hostDisplayName': 'fixture-ssh', 'isGitRepository': True}


def snapshot():
    return {'schema': 2, 'kind': 'sidebar-layout',
            'provenance': {'source_machine': 'c' * 64, 'project_machine': PROJECT_MACHINE,
                           'captured_at': time.time()},
            'sections': [{'key': 's0', 'name': 'Research'}],
            'projects': [{'key': 'p0', 'path': PATH, 'label': 'Example', 'section': 's0',
                          'section_position': 0, 'appearance': None, 'expanded': None}]}


def observation(*, projects=None, sections=None, account='target', machine=SIDEBAR_MACHINE,
                unavailable_hosts=None, unavailable_sources=None):
    visible_projects = copy.deepcopy([project()] if projects is None else projects)
    custom_sections = copy.deepcopy(
        [section('research-id', 'Research'),
         section('unrelated-id', 'Unrelated', 'codex:thread:unrelated',
                 'codex:project:opaque-host-project')]
        if sections is None else sections)
    claimed = {key for group in custom_sections for key in group['itemKeys']}
    if not any(group['sectionId'] == 'pinned' for group in custom_sections):
        custom_sections.insert(0, section('pinned', 'Pinned'))
    if not any(group['sectionId'] == 'threads' for group in custom_sections):
        default_projects = ['codex:project:' + p['projectId'] for p in visible_projects
                            if 'codex:project:' + p['projectId'] not in claimed]
        custom_sections.insert(1, section('threads', 'Projects', *default_projects))
    if not any(group['sectionId'] == 'chats' for group in custom_sections):
        custom_sections.insert(2, section('chats', 'Tasks'))
    return {'schema': 1, 'kind': 'owning-app-sidebar-observation',
            'collected_at': time.time(), 'sidebar_machine': machine, 'account_id': account,
            'projects_result': {'schemaVersion': 2, 'projects': visible_projects},
            'threads_result': {'schemaVersion': 4,
                               'sections': custom_sections,
                               'unavailableHosts': [] if unavailable_hosts is None else unavailable_hosts,
                               'unavailableSources': [] if unavailable_sources is None else unavailable_sources}}


def evidence():
    return {'machine': PROJECT_MACHINE, 'codex_home': '/fixture/project-codex-home',
            'paths': {PATH: {'canonical': PATH, 'file_id': [7, 101], 'trust': 'trusted'}},
            'tasks': {PATH: []}, 'tasks_complete': True,
            'server_projects': [], 'server_inventory_complete': True}


class AppOwnedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.home = root / 'home'
        self.home.mkdir()
        self.record = root / 'receipt'
        self.layout_file = root / 'layout.json'
        self.layout = snapshot()
        self.obs = observation()
        self.host_evidence = evidence()
        recovery.private_write(self.layout_file, self.layout)
        recovery.atomic(self.home / 'auth.json', recovery.encoded({'tokens': {'account_id': 'target'}}))
        self.patches = [
            patch.object(recovery.legacy, 'machine_id', return_value=SIDEBAR_MACHINE),
            patch.object(recovery.runtime, 'probe_paths',
                         side_effect=lambda *args: copy.deepcopy(self.host_evidence)),
            patch.object(recovery.runtime, 'probe',
                         side_effect=AssertionError('App route invoked Codex CLI probe')),
            patch.object(recovery.runtime, 'desktop', side_effect=AssertionError('App route inspected desktop build')),
            patch.object(recovery.legacy, 'running', side_effect=AssertionError('App route requested app exit')),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def prepare(self, obs=None, record=None):
        return recovery.prepare_app(self.home, record or self.record, self.layout_file,
                                    'fixture-ssh', HOST, obs or self.obs)

    def action(self, kind='place-project'):
        plan = recovery.private_read(self.record / 'plan.json')
        return next(a for a in plan['native_actions'] if a['kind'] == kind)

    def event(self, stage, obs, action=None):
        fresh = copy.deepcopy(obs)
        fresh['collected_at'] = time.time()
        return recovery.app_event(self.home, self.record, {
            'operation_id': (action or self.action())['id'], 'stage': stage,
            'observed_at': fresh['collected_at'], 'observation': fresh})

    def placed(self):
        return observation(sections=[
            section('research-id', 'Research', 'codex:project:existing-id'),
            section('unrelated-id', 'Unrelated', 'codex:thread:unrelated',
                    'codex:project:opaque-host-project')])

    def test_unknown_build_uses_owning_app_route_without_legacy_file_access(self):
        # A malformed legacy state detects accidental reads, and unchanged bytes detect writes.
        legacy_file = self.home / recovery.STATE
        legacy_file.write_bytes(b'{legacy storage is intentionally unsupported')
        original = legacy_file.read_bytes()
        result = self.prepare()
        self.assertEqual(result['phase'], 'prepared')
        self.assertEqual([a['kind'] for a in result['native_actions']], ['place-project'])
        self.assertEqual(legacy_file.read_bytes(), original)
        self.assertFalse((self.home / (recovery.STATE + '.bak')).exists())
        self.assertEqual(recovery.private_read(self.record / 'plan.json')['adapter'],
                         'app-owned-placement-v1')
        self.assertEqual(self.record.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in self.record.iterdir()))

    def test_cli_explicit_app_route_succeeds_with_unknown_desktop_build(self):
        obs_file = self.record.parent / 'observations.json'
        recovery.private_write(obs_file, self.obs)
        args = ['helper', 'prepare', '--route', 'app-owned', '--codex-home', str(self.home),
                '--record', str(self.record), '--source-layout', str(self.layout_file),
                '--project-host', 'fixture-ssh', '--new-host', HOST,
                '--observations', str(obs_file)]
        stdout = io.StringIO()
        with patch.object(recovery.sys, 'argv', args), patch.object(recovery.sys, 'stdout', stdout), \
             patch.object(recovery.legacy.platform, 'system', return_value='Darwin'):
            self.assertEqual(recovery.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())['phase'], 'prepared')
        self.assertEqual(recovery.private_read(self.record / 'plan.json')['adapter'],
                         'app-owned-placement-v1')

    def test_unknown_build_still_refuses_legacy_registration_writes(self):
        state = {'remote-projects': [], 'project-order': [],
                 'codex-managed-remote-connections': [
                     {'hostId': HOST, 'source': 'discovered', 'alias': 'fixture-ssh'}],
                 'project-appearances': {},
                 recovery.ATOM: {recovery.LAYOUTS: {'target': {'sections': []}}}}
        raw = recovery.encoded(state)
        recovery.atomic(self.home / recovery.STATE, raw)
        unknown = {'bundle_id': 'com.openai.codex', 'version': '99.0', 'build': 'unknown',
                   'implementation_sha256': '0' * 64, 'app_path': '/Applications/Unknown.app'}
        with patch.object(recovery.runtime, 'desktop', return_value=unknown), \
             patch.object(recovery.runtime, 'probe',
                          side_effect=lambda *args: copy.deepcopy(self.host_evidence)), \
             self.assertRaisesRegex(recovery.Refusal, 'unsupported_desktop_build'):
            recovery.prepare(self.home, self.record, new_host=HOST,
                             project_host='fixture-ssh', source_layout=self.layout_file)
        self.assertEqual((self.home / recovery.STATE).read_bytes(), raw)
        self.assertFalse((self.home / (recovery.STATE + '.bak')).exists())
        self.assertFalse(self.record.exists())

    def test_existing_custom_or_pinned_placement_wins_over_snapshot(self):
        for current in [section('mine-id', 'Mine', 'codex:project:existing-id'),
                        section('pinned', 'Pinned', 'codex:project:existing-id')]:
            with self.subTest(current=current['name']):
                obs = observation(sections=[section('research-id', 'Research'), current])
                result = self.prepare(obs, self.record.parent / ('receipt-' + current['name']))
                self.assertEqual(result['native_actions'], [])

    def test_missing_registration_is_a_blocker_but_independent_moves_remain(self):
        self.layout['projects'].append({'key': 'p1', 'path': '/example/missing', 'label': 'Missing',
                                        'section': 's0', 'section_position': 1,
                                        'appearance': None, 'expanded': None})
        self.host_evidence['paths']['/example/missing'] = {
            'canonical': '/example/missing', 'file_id': [7, 102], 'trust': 'trusted'}
        self.layout_file.unlink()
        recovery.private_write(self.layout_file, self.layout)
        result = self.prepare()
        self.assertEqual([a['kind'] for a in result['native_actions']], ['place-project'])
        self.assertTrue(result['missing_projects'])
        self.assertNotIn('/example/missing', json.dumps(result['native_actions']))
        recovery.begin_app_apply(self.home, self.record, self.obs)
        self.event('intent', self.obs)
        self.event('confirmed', self.placed())
        verified = recovery.verify_app(self.home, self.record, self.placed())
        self.assertEqual(verified['phase'], 'placement-partial')
        self.assertEqual(verified['placement_status'], 'partial')
        self.assertIs(verified['task_associations_verified'], False)

    def test_wrong_machine_account_host_path_and_ambiguous_projects_refused(self):
        cases = [
            ('machine', observation(machine='d' * 64)),
            ('account', observation(account='other')),
            ('host', observation(projects=[project(host='remote-ssh-discovered:other')])),
            ('path', observation(projects=[project(path='/example/other')])),
            ('duplicate', observation(projects=[project(), project('another-id')])),
        ]
        for name, obs in cases:
            with self.subTest(name=name), self.assertRaises(recovery.Refusal):
                self.prepare(obs, self.record.parent / ('receipt-' + name))
        self.host_evidence['machine'] = 'e' * 64
        with self.assertRaises(recovery.Refusal):
            self.prepare(self.obs, self.record.parent / 'receipt-project-machine')

    def test_cross_host_duplicate_of_selected_source_path_refused(self):
        obs = observation(projects=[project(), project('other-host-id', PATH,
                                                       'remote-ssh-discovered:other')])
        with self.assertRaises(recovery.Refusal):
            self.prepare(obs)

    def test_late_registration_drift_refused_before_action_and_verification(self):
        self.prepare()
        same_host = observation(projects=[project(), project('alias-id', '/example/alias')])
        other_host = observation(projects=[project(), project('other-host-id', PATH,
                                                              'remote-ssh-discovered:other')])
        for name, changed in [('same-host', same_host), ('cross-host', other_host)]:
            with self.subTest(name=name), self.assertRaises(recovery.Refusal):
                recovery.begin_app_apply(self.home, self.record, changed)
        recovery.begin_app_apply(self.home, self.record, self.obs)
        for name, changed in [('same-host', same_host), ('cross-host', other_host)]:
            with self.subTest(name=name), self.assertRaises(recovery.Refusal):
                self.event('intent', changed)
        self.event('intent', self.obs)
        self.event('confirmed', self.placed())
        for name, changed in [('same-host', same_host), ('cross-host', other_host)]:
            placed = copy.deepcopy(changed)
            placed['threads_result']['sections'] = self.placed()['threads_result']['sections']
            placed['collected_at'] = time.time()
            with self.subTest(name=name), self.assertRaises(recovery.Refusal):
                recovery.verify_app(self.home, self.record, placed)

    def test_unrelated_future_project_kind_is_preserved_but_source_path_claim_refused(self):
        future = {'projectId': 'future-id', 'projectKind': 'future-cloud', 'label': 'Future'}
        obs = observation(projects=[project(), future])
        result = self.prepare(obs)
        self.assertEqual([a['kind'] for a in result['native_actions']], ['place-project'])
        recovery.begin_app_apply(self.home, self.record, obs)
        self.event('intent', obs)
        after = observation(projects=[project(), future], sections=[
            section('research-id', 'Research', 'codex:project:existing-id'),
            section('unrelated-id', 'Unrelated', 'codex:thread:unrelated',
                    'codex:project:opaque-host-project')])
        self.event('confirmed', after)
        after['collected_at'] = time.time()
        self.assertEqual(recovery.verify_app(self.home, self.record, after)['phase'],
                         'placement-verified')

        claimed = dict(future, path=PATH)
        with self.assertRaises(recovery.Refusal):
            self.prepare(observation(projects=[project(), claimed]),
                         self.record.parent / 'receipt-unknown-source-claim')

    def test_incomplete_app_observation_refused(self):
        for name, obs in [
            ('host', observation(unavailable_hosts=[HOST])),
            ('source', observation(unavailable_sources=['remote'])),
            ('projects', dict(self.obs, projects_result={'schemaVersion': 2})),
            ('sections', dict(self.obs, threads_result={'schemaVersion': 4})),
        ]:
            with self.subTest(name=name), self.assertRaises(recovery.Refusal):
                self.prepare(obs, self.record.parent / ('receipt-' + name))

    def test_missing_section_creation_is_ordered_and_unrelated_keys_are_opaque(self):
        obs = observation(sections=[section('unrelated-id', 'Unrelated', 'codex:thread:unrelated',
                                            'codex:project:opaque-host-project')])
        result = self.prepare(obs)
        self.assertEqual([a['kind'] for a in result['native_actions']],
                         ['create-section', 'place-project'])
        self.assertEqual(result['native_actions'][0]['section_name'], 'Research')

    def test_duplicate_destination_section_name_refused(self):
        obs = observation(sections=[section('first', 'Research'),
                                    section('second', 'Research')])
        with self.assertRaises(recovery.Refusal):
            self.prepare(obs)

    def test_missing_sections_follow_source_order(self):
        self.layout['sections'].append({'key': 's1', 'name': 'Study'})
        self.layout['projects'].append({'key': 'p1', 'path': '/example/second', 'label': 'Second',
                                        'section': 's1', 'section_position': 0,
                                        'appearance': None, 'expanded': None})
        self.host_evidence['paths']['/example/second'] = {
            'canonical': '/example/second', 'file_id': [7, 102], 'trust': 'trusted'}
        self.layout_file.unlink()
        recovery.private_write(self.layout_file, self.layout)
        obs = observation(projects=[project(), project('second-id', '/example/second')],
                          sections=[section('unrelated-id', 'Unrelated', 'codex:thread:unrelated')])
        result = self.prepare(obs)
        names = [a['section_name'] for a in result['native_actions'] if a['kind'] == 'create-section']
        self.assertEqual(names, ['Research', 'Study'])

    def test_app_export_uses_live_ownership_and_portable_section_keys(self):
        source_obs = observation(sections=[section('source-private-id', 'Research',
                                                   'codex:project:existing-id')])
        result = recovery.export_app_data(self.home, source_obs, 'fixture-ssh', HOST)
        self.assertEqual(result['schema'], 2)
        self.assertEqual(result['projects'][0]['section'], 's0')
        self.assertIsNone(result['projects'][0]['appearance'])
        self.assertIsNone(result['projects'][0]['expanded'])
        self.assertNotIn('source-private-id', json.dumps(result))
        ungrouped = recovery.export_app_data(self.home, observation(), 'fixture-ssh', HOST)
        self.assertIsNone(ungrouped['projects'][0]['section'])

    def test_apply_rechecks_active_account_and_project_identity(self):
        self.prepare()
        recovery.atomic(self.home / 'auth.json', recovery.encoded({'tokens': {'account_id': 'other'}}))
        with self.assertRaises(recovery.Refusal):
            recovery.begin_app_apply(self.home, self.record, self.obs)
        recovery.atomic(self.home / 'auth.json', recovery.encoded({'tokens': {'account_id': 'target'}}))
        changed = observation(projects=[project('different-id')])
        with self.assertRaises(recovery.Refusal):
            recovery.begin_app_apply(self.home, self.record, changed)

    def test_intent_and_uncertain_result_reconcile_from_fresh_app_readback(self):
        self.prepare()
        recovery.begin_app_apply(self.home, self.record, self.obs)
        with self.assertRaises(recovery.Refusal):
            self.event('confirmed', self.placed())
        self.event('intent', self.obs)
        self.event('unresolved', self.placed())
        with self.assertRaises(recovery.Refusal):
            self.event('intent', self.placed())
        self.event('confirmed', self.placed())
        with self.assertRaises(recovery.Refusal):
            self.event('confirmed', self.placed())
        events = recovery.private_read(self.record / 'native.json')['events']
        self.assertEqual([e['stage'] for e in events], ['intent', 'unresolved', 'confirmed'])

    def test_not_applied_action_allows_prior_created_section_rollback(self):
        before = observation(sections=[section('unrelated-id', 'Unrelated',
                                                'codex:thread:unrelated')])
        actions = self.prepare(before)['native_actions']
        created_action, placement_action = actions
        recovery.begin_app_apply(self.home, self.record, before)
        self.event('intent', before, created_action)
        created = copy.deepcopy(before)
        created['threads_result']['sections'].append(section('created-id', 'Research'))
        self.event('confirmed', created, created_action)
        self.event('intent', created, placement_action)
        self.event('unresolved', created, placement_action)
        self.event('not-applied', created, placement_action)
        with self.assertRaises(recovery.Refusal):
            self.event('confirmed', created, placement_action)
        fresh = copy.deepcopy(created)
        fresh['collected_at'] = time.time()
        recovery.app_event(self.home, self.record, {
            'operation_id': created_action['id'], 'stage': 'rollback-intent',
            'observed_at': fresh['collected_at'], 'observation': fresh},
            remove_empty_sections=True)
        self.event('reversed', before, created_action)
        final = copy.deepcopy(before)
        final['collected_at'] = time.time()
        self.assertEqual(recovery.finish_app_rollback(self.home, self.record, final)['phase'],
                         'rolled-back')

    def test_verify_checks_placement_and_preserves_unrelated_section_items(self):
        self.prepare()
        recovery.begin_app_apply(self.home, self.record, self.obs)
        self.event('intent', self.obs)
        self.event('confirmed', self.placed())
        good = recovery.verify_app(self.home, self.record, self.placed())
        self.assertEqual(good['phase'], 'placement-verified')
        self.assertEqual(good['placement_status'], 'verified')
        self.assertIs(good['task_associations_verified'], False)
        altered = observation(sections=[
            section('research-id', 'Research', 'codex:project:existing-id'),
            section('unrelated-id', 'Unrelated', 'codex:thread:unrelated')])
        with self.assertRaises(recovery.Refusal):
            recovery.verify_app(self.home, self.record, altered)

    def test_rollback_restores_exact_prior_owner_and_refuses_later_project_move(self):
        self.prepare()
        recovery.begin_app_apply(self.home, self.record, self.obs)
        self.event('intent', self.obs)
        self.event('confirmed', self.placed())
        self.event('rollback-intent', self.placed())
        later_choice = observation(sections=[
            section('research-id', 'Research'),
            section('pinned', 'Pinned', 'codex:project:existing-id'),
            section('unrelated-id', 'Unrelated', 'codex:thread:unrelated',
                    'codex:project:opaque-host-project')])
        with self.assertRaises(recovery.Refusal):
            self.event('reversed', later_choice)
        with self.assertRaises(recovery.Refusal):
            recovery.finish_app_rollback(self.home, self.record, later_choice)
        vanished = observation(sections=[
            section('pinned', 'Pinned'), section('threads', 'Projects'), section('chats', 'Tasks'),
            section('research-id', 'Research'),
            section('unrelated-id', 'Unrelated', 'codex:thread:unrelated',
                    'codex:project:opaque-host-project')])
        with self.assertRaises(recovery.Refusal):
            self.event('reversed', vanished)
        self.event('reversed', self.obs)
        result = recovery.finish_app_rollback(self.home, self.record, observation())
        self.assertEqual(result['phase'], 'rolled-back')

    def test_verification_refuses_project_identity_and_section_drift(self):
        self.prepare()
        recovery.begin_app_apply(self.home, self.record, self.obs)
        self.event('intent', self.obs)
        self.event('confirmed', self.placed())
        for name, current in [
            ('project', observation(projects=[project('different-id')], sections=self.placed()['threads_result']['sections'])),
            ('section', observation(sections=[section('research-id', 'Research'),
                                         section('unrelated-id', 'Unrelated', 'codex:thread:unrelated',
                                                 'codex:project:opaque-host-project')])),
        ]:
            with self.subTest(name=name), self.assertRaises(recovery.Refusal):
                recovery.verify_app(self.home, self.record, current)


class PathProbeTests(unittest.TestCase):
    def test_remote_program_preserves_special_path_as_python_literal(self):
        unusual = "/tmp/literal CODEX_SIDEBAR_PATHS: MARKER 'quoted'\nnext"
        payload = {'machine': PROJECT_MACHINE,
                   'paths': {unusual: {'canonical': unusual, 'file_id': [7, 101]}}}
        programs = []

        def fake_run(command, **kwargs):
            self.assertEqual(command[0], 'ssh')
            programs.append(kwargs['input'])
            return SimpleNamespace(returncode=0,
                                   stdout='noise\nCODEX_SIDEBAR_PATHS:' + json.dumps(payload) + '\n')

        with patch.object(recovery.runtime.subprocess, 'run', side_effect=fake_run):
            observed = recovery.runtime.probe_paths('fixture-ssh', [unusual])
        self.assertEqual(observed, payload)
        self.assertEqual(len(programs), 1)
        parsed = ast.parse(programs[0])
        assignment = next(node for node in parsed.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'paths'
                                  for target in node.targets))
        self.assertEqual(ast.literal_eval(assignment.value), [unusual])


if __name__ == '__main__':
    unittest.main()
