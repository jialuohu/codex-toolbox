import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/workflow-tools/skills/recover-codex-sidebar/scripts/recover_sidebar.py'
spec = importlib.util.spec_from_file_location('sidebar_recovery', SCRIPT)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def fixture():
    section = {'id': 'source-section', 'name': 'Research', 'itemKeys': ['codex:project:old'],
               'hostSectionIds': {'old-host': 'opaque-source-binding'}}
    return {'remote-projects': [{'id': 'old', 'hostId': 'old-host', 'label': 'Example', 'remotePath': '/example/project'}],
            'project-order': ['old'], 'project-appearances': {'old': {'icon': 'book'}},
            r.ATOM: {r.LAYOUTS: {'source': {'sections': [section]}, 'target': {'sections': []}}},
            'unrelated': {'keep': True}}, {'machine': 'fixture-machine', 'paths': {'/example/project': '/example/project'},
                                          'tasks': {'/example/project': ['existing-task']}}


class PlanningTests(unittest.TestCase):
    def plan(self, state, evidence):
        return r.make_plan(state, 'source', 'target', 'old-host', 'new-host', evidence)

    def test_empty_destination_and_source_preserved(self):
        state, evidence = fixture()
        original = copy.deepcopy(state)
        plan = self.plan(state, evidence)
        self.assertEqual(state, original)
        self.assertEqual(len(plan['created']), 1)
        self.assertEqual(plan['app_actions'][0]['section_name'], 'Research')
        self.assertNotIn('hostSectionIds', json.dumps(plan['changes']))
        self.assertEqual(plan['expected'][0]['task_ids'], ['existing-task'])

    def test_repeat_and_existing_destination_choices(self):
        state, evidence = fixture()
        plan = self.plan(state, evidence)
        for c in plan['changes']:
            r.put_slot(state, c['path'], c['after'])
        pid = plan['created'][0]
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = [{'id': 'different', 'name': 'My choice', 'itemKeys': ['codex:project:' + pid]}]
        again = self.plan(state, evidence)
        self.assertEqual(again['changes'], [])
        self.assertEqual(again['app_actions'], [])
        self.assertEqual(again['expected'][0]['section_id'], 'different')

    def test_existing_ungrouped_stays_ungrouped(self):
        state, evidence = fixture()
        state['remote-projects'].append(dict(state['remote-projects'][0], id='current', hostId='new-host', label='Renamed'))
        self.assertEqual(self.plan(state, evidence)['app_actions'], [])

    def test_duplicate_section_name_refused(self):
        state, evidence = fixture()
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = [dict(id=str(i), name='Research', itemKeys=[]) for i in range(2)]
        with self.assertRaisesRegex(r.Refusal, 'Ambiguous destination section'):
            self.plan(state, evidence)

    def test_duplicate_paths_and_case_distinctions(self):
        state, evidence = fixture()
        for i in range(2):
            state['remote-projects'].append(dict(state['remote-projects'][0], id='new' + str(i), hostId='new-host'))
        with self.assertRaisesRegex(r.Refusal, 'Ambiguous destination'):
            self.plan(state, evidence)
        state['remote-projects'] = state['remote-projects'][:1]
        state['remote-projects'].append(dict(state['remote-projects'][0], id='other', hostId='new-host', remotePath='/Example/project'))
        evidence['paths']['/Example/project'] = '/Example/project'
        self.assertEqual(len(self.plan(state, evidence)['created']), 1)

    def test_missing_path_unknown_fields_migrations(self):
        state, evidence = fixture()
        evidence['paths']['/example/project'] = None
        with self.assertRaisesRegex(r.Refusal, 'Missing'):
            self.plan(state, evidence)
        state, evidence = fixture()
        state['remote-projects'][0]['future'] = True
        with self.assertRaisesRegex(r.Refusal, 'Unknown source'):
            self.plan(state, evidence)
        state, evidence = fixture()
        state['app-server-projects-migration-by-host'] = {'some-host': {'done': True}}
        with self.assertRaisesRegex(r.Refusal, 'migration'):
            self.plan(state, evidence)
        state['remote-projects'].append(dict(state['remote-projects'][0], id='current', hostId='new-host'))
        self.assertEqual(self.plan(state, evidence)['changes'], [])

    def test_source_order_and_partial_recovery(self):
        state, evidence = fixture()
        state['remote-projects'].append(dict(state['remote-projects'][0], id='second', remotePath='/example/second'))
        state['project-order'] = ['second', 'old']
        source = state[r.ATOM][r.LAYOUTS]['source']['sections'][0]
        source['itemKeys'] = ['codex:project:second', 'codex:project:old']
        evidence['paths']['/example/second'] = '/example/second'
        state['remote-projects'].append(dict(state['remote-projects'][0], id='already', hostId='new-host'))
        plan = self.plan(state, evidence)
        self.assertEqual(len(plan['created']), 1)
        self.assertEqual(plan['expected'][0]['remotePath'], '/example/second')
        self.assertEqual(plan['mapping']['old'], 'already')

    def test_ambiguous_source_sections_and_host(self):
        state, evidence = fixture()
        state[r.ATOM][r.LAYOUTS]['source']['sections'].append({'id': 'another', 'name': 'Research', 'itemKeys': []})
        with self.assertRaisesRegex(r.Refusal, 'Ambiguous source section'):
            self.plan(state, evidence)
        with self.assertRaisesRegex(r.Refusal, 'No projects'):
            r.make_plan(state, 'source', 'target', 'wrong-host', 'new-host', evidence)

    def test_duplicate_json_and_unsupported_platform(self):
        with self.assertRaisesRegex(r.Refusal, 'Duplicate JSON'):
            r.decode('{"id":1,"id":2}')
        with patch.object(r.platform, 'system', return_value='Windows'):
            with self.assertRaisesRegex(r.Refusal, 'macOS'):
                r.guard(Path('/example'), {})

    def test_renamed_desktop_app_is_still_a_writer(self):
        result = r.subprocess.CompletedProcess([], 0, stdout='/Applications/ChatGPT Copy.app/Contents/MacOS/ChatGPT\n')
        with patch.object(r.subprocess, 'run', return_value=result):
            self.assertTrue(r.running())


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / 'home'
        self.home.mkdir()
        self.record = Path(self.tmp.name).resolve() / 'recovery'
        self.state, self.evidence = fixture()
        r.atomic(self.home / r.STATE, r.encoded(self.state))
        r.atomic(self.home / (r.STATE + '.bak'), r.encoded(self.state))
        r.atomic(self.home / 'auth.json', r.encoded({'tokens': {'account_id': 'target'}}))
        self.patches = [patch.object(r.platform, 'system', return_value='Darwin'), patch.object(r, 'running', return_value=False),
                        patch.object(r, 'probe', return_value=self.evidence),
                        patch.object(r, 'machine_id', return_value='fixture-sidebar-machine')]
        for p in self.patches:
            p.start()
        r.prepare(self.home, self.record, 'source', 'old-host', 'new-host', 'local')

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_apply_repeat_and_rollback_preserve_other_values(self):
        self.assertEqual(r.transact(self.home, self.record)['phase'], 'applied-unverified')
        self.assertEqual(r.transact(self.home, self.record)['metadata_changes'], 0)
        for name in [r.STATE, r.STATE + '.bak']:
            state = r.read(self.home / name)
            state['unrelated']['new'] = 7
            r.atomic(self.home / name, r.encoded(state))
        r.transact(self.home, self.record, True)
        self.assertEqual(r.read(self.home / r.STATE)['remote-projects'], self.state['remote-projects'])
        self.assertEqual(r.read(self.home / r.STATE)['unrelated']['new'], 7)

    def test_stale_preview_account_change_and_running_app(self):
        with patch.object(r, 'running', return_value=True):
            with self.assertRaisesRegex(r.Refusal, 'Close'):
                r.transact(self.home, self.record)
        r.atomic(self.home / 'auth.json', r.encoded({'tokens': {'account_id': 'another'}}))
        with self.assertRaisesRegex(r.Refusal, 'account changed'):
            r.transact(self.home, self.record)
        r.atomic(self.home / 'auth.json', r.encoded({'tokens': {'account_id': 'target'}}))
        self.state['remote-projects'][0]['label'] = 'Changed after preview'
        r.atomic(self.home / r.STATE, r.encoded(self.state))
        with self.assertRaisesRegex(r.Refusal, 'Stale preview'):
            r.transact(self.home, self.record)

    def test_unrelated_shutdown_updates_preserved_before_apply(self):
        self.state['unrelated']['shutdown'] = True
        r.atomic(self.home / r.STATE, r.encoded(self.state))
        r.transact(self.home, self.record)
        self.assertTrue(r.read(self.home / r.STATE)['unrelated']['shutdown'])

    def test_interrupted_between_backup_and_main_is_reversible(self):
        real = r.atomic
        def interrupt(path, raw):
            if path == self.home / r.STATE:
                raise OSError('simulated power failure')
            real(path, raw)
        with patch.object(r, 'atomic', side_effect=interrupt):
            with self.assertRaises(OSError):
                r.transact(self.home, self.record)
        with self.assertRaisesRegex(r.Refusal, 'Interrupted'):
            r.transact(self.home, self.record)
        r.transact(self.home, self.record, True)
        self.assertEqual(r.read(self.home / r.STATE), self.state)
        self.assertEqual(r.read(self.home / (r.STATE + '.bak')), self.state)

    def test_rollback_refuses_later_project_edits(self):
        r.transact(self.home, self.record)
        state = r.read(self.home / r.STATE)
        state['remote-projects'][-1]['label'] = 'Later choice'
        r.atomic(self.home / r.STATE, r.encoded(state))
        with self.assertRaisesRegex(r.Refusal, 'Later edits'):
            r.transact(self.home, self.record, True)
        self.assertEqual(r.read(self.home / r.STATE), state)

    def test_app_reappears_receipt_never_claims_verified(self):
        with patch.object(r, 'running', side_effect=[False, False, False, False, True]):
            result = r.transact(self.home, self.record)
        self.assertEqual(result['phase'], 'applied-unverified')
        self.assertTrue(r.read(self.record / 'status.json')['app_reappeared'])

    def test_verification_needs_fresh_app_tasks_and_placement(self):
        r.transact(self.home, self.record)
        plan = r.read(self.record / 'plan.json')
        pid = plan['created'][0]
        obs = {'account_id': 'target', 'sidebar_device': r.platform.node(), 'collected_at': r.time.time() + 1,
               'projects': [{'id': pid, 'hostId': 'new-host', 'remotePath': '/example/project', 'task_ids': ['existing-task']}],
               'historical_task_reads': ['existing-task']}
        with self.assertRaisesRegex(r.Refusal, 'placement'):
            r.verify(self.home, self.record, obs)
        state = r.read(self.home / r.STATE)
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = [{'id': 'fresh-section', 'name': 'Research', 'itemKeys': ['codex:project:' + pid]}]
        r.atomic(self.home / r.STATE, r.encoded(state))
        obs['sections'] = state[r.ATOM][r.LAYOUTS]['target']['sections']
        missing = copy.deepcopy(obs)
        missing['projects'][0]['task_ids'] = []
        with self.assertRaisesRegex(r.Refusal, 'association'):
            r.verify(self.home, self.record, missing)
        no_read = dict(obs, historical_task_reads=[])
        with self.assertRaisesRegex(r.Refusal, 'Read one existing task'):
            r.verify(self.home, self.record, no_read)
        self.assertEqual(r.verify(self.home, self.record, obs)['phase'], 'verified')

    def test_private_artifacts_and_no_task_bodies(self):
        self.assertEqual(self.record.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in self.record.iterdir()))
        text = (self.record / 'plan.json').read_text()
        self.assertNotIn('auth.json', text)
        self.assertNotIn('tokens', text)

    def test_changed_host_and_symlink_refused(self):
        changed = copy.deepcopy(self.evidence)
        changed['machine'] = 'another-machine'
        with patch.object(r, 'probe', return_value=changed):
            with self.assertRaisesRegex(r.Refusal, 'host or paths changed'):
                r.transact(self.home, self.record)
        backup = self.home / (r.STATE + '.bak')
        backup.unlink()
        backup.symlink_to(self.home / r.STATE)
        with self.assertRaisesRegex(r.Refusal, 'symlinks'):
            r.transact(self.home, self.record)

    def test_plan_tampering_refused(self):
        plan = r.read(self.record / 'plan.json')
        plan['target_account'] = 'modified'
        r.atomic(self.record / 'plan.json', r.encoded(plan))
        with self.assertRaisesRegex(r.Refusal, 'plan changed'):
            r.transact(self.home, self.record)

    def test_native_placement_must_be_undone_before_file_rollback(self):
        r.transact(self.home, self.record)
        state = r.read(self.home / r.STATE)
        plan = r.read(self.record / 'plan.json')
        state[r.ATOM][r.LAYOUTS]['target']['sections'] = [{'id': 'new', 'name': 'Research',
             'itemKeys': ['codex:project:' + plan['created'][0]]}]
        r.atomic(self.home / r.STATE, r.encoded(state))
        with self.assertRaisesRegex(r.Refusal, 'native placement'):
            r.transact(self.home, self.record, True)

    def test_no_backup_is_created_and_removed_on_rollback(self):
        (self.home / (r.STATE + '.bak')).unlink()
        record = self.record.parent / 'without-backup'
        r.prepare(self.home, record, 'source', 'old-host', 'new-host', 'local')
        r.transact(self.home, record)
        self.assertTrue((self.home / (r.STATE + '.bak')).exists())
        r.transact(self.home, record, True)
        self.assertFalse((self.home / (r.STATE + '.bak')).exists())

    def test_different_backup_before_values_survive_rollback(self):
        backup = copy.deepcopy(self.state)
        backup['project-order'] = []
        r.atomic(self.home / (r.STATE + '.bak'), r.encoded(backup))
        record = self.record.parent / 'different-backup'
        r.prepare(self.home, record, 'source', 'old-host', 'new-host', 'local')
        r.transact(self.home, record)
        r.transact(self.home, record, True)
        self.assertEqual(r.read(self.home / (r.STATE + '.bak')), backup)

    def test_verify_refuses_stale_evidence(self):
        r.transact(self.home, self.record)
        with self.assertRaisesRegex(r.Refusal, 'Fresh'):
            r.verify(self.home, self.record, {'collected_at': 0})

    def test_missing_task_database_cannot_claim_verified(self):
        evidence = dict(self.evidence, tasks_unavailable=True)
        record = self.record.parent / 'no-task-baseline'
        with patch.object(r, 'probe', return_value=evidence):
            r.prepare(self.home, record, 'source', 'old-host', 'new-host', 'local')
        r.transact(self.home, record)
        obs = {'account_id': 'target', 'sidebar_device': r.platform.node(), 'collected_at': r.time.time() + 1}
        with self.assertRaisesRegex(r.Refusal, 'baseline unavailable'):
            r.verify(self.home, record, obs)

    def test_bounded_wait_expires_without_configuration_write(self):
        args = ['helper', 'apply', '--codex-home', str(self.home), '--record', str(self.record), '--wait-seconds', '1']
        with patch.object(r.sys, 'argv', args), patch.object(r.sys, 'stdout', io.StringIO()), \
             patch.object(r, 'running', return_value=True), patch.object(r.time, 'monotonic', side_effect=[0, 2]):
            self.assertEqual(r.main(), 2)
        self.assertEqual(r.read(self.record / 'status.json')['phase'], 'expired')
        self.assertEqual(r.read(self.home / r.STATE), self.state)

    def test_artifacts_cannot_be_written_inside_git(self):
        git_root = self.home / 'checkout'
        git_root.mkdir()
        (git_root / '.git').mkdir()
        with self.assertRaisesRegex(r.Refusal, 'outside Git'):
            r.private_directory(git_root / 'recovery')

    def test_migration_appearing_after_preview_refused(self):
        state = r.read(self.home / r.STATE)
        state['app-server-projects-migration-by-host'] = {'local': {'complete': True}}
        r.atomic(self.home / r.STATE, r.encoded(state))
        with self.assertRaisesRegex(r.Refusal, 'migration'):
            r.transact(self.home, self.record)

    def test_multiple_records_share_one_writer_lock(self):
        lock_path = self.home / '.sidebar-recovery.lock'
        with lock_path.open('w') as lock:
            r.fcntl.flock(lock, r.fcntl.LOCK_EX | r.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                r.transact(self.home, self.record)
        self.assertEqual(r.read(self.home / r.STATE), self.state)

    def test_record_cannot_target_unrelated_fields(self):
        plan = r.read(self.record / 'plan.json')
        plan['changes'][0]['path'] = ['unrelated']
        raw = r.encoded(plan)
        r.atomic(self.record / 'plan.json', raw)
        r.atomic(self.record / 'plan.sha256.json', r.encoded({'sha256': r.digest(raw)}))
        with self.assertRaisesRegex(r.Refusal, 'unsupported field'):
            r.transact(self.home, self.record)

    def test_same_hostname_different_sidebar_mac_refused(self):
        with patch.object(r, 'machine_id', return_value='different-sidebar-machine'):
            with self.assertRaisesRegex(r.Refusal, 'Wrong sidebar device'):
                r.transact(self.home, self.record)


if __name__ == '__main__':
    unittest.main()
