"""Doctor reports are discovery evidence, never native export acceptance."""
import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/omnigraffle-tools/skills/omnigraffle-workflow/scripts/preflight.py'
SPEC = importlib.util.spec_from_file_location('plugin_omni_preflight', SCRIPT)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class ProductionDoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_stock_gui_compiler_and_sdk_discovery_without_compilation(self):
        clang = self.root / 'clang'
        clang.write_text('not executed')
        clang.chmod(0o700)
        sdk = self.root / 'SDK'
        sdk.mkdir()
        def run(args):
            self.assertIn(args, [['/usr/bin/xcrun','--find','clang'], ['/usr/bin/xcrun','--show-sdk-path']])
            return {'status':'ok','output':str(clang if args[-1]=='clang' else sdk)}
        with patch.object(preflight, 'run_command', side_effect=run):
            result = preflight.stock_helper_tools()
        self.assertEqual(result['status'],'present')
        self.assertEqual(result['compilation_test'],'not_run')

    def test_stock_gui_missing_compiler(self):
        with patch.object(preflight,'run_command',return_value={'status':'unavailable','output':''}):
            result = preflight.stock_helper_tools()
        self.assertEqual(result['status'],'missing')

    def dictionary(self, description):
        resources = self.root / 'Contents/Resources'
        resources.mkdir(parents=True)
        (resources/'OmniGraffle.scriptSuite').write_bytes(plistlib.dumps({'Commands':{'Export':{'AppleEventCode':'OGEx'}}}))
        (resources/'OmniGraffle.scriptTerminology').write_bytes(plistlib.dumps({'Commands':{'Export':{'Arguments':{'Format':{'Description':description}}}}}))

    def test_exports_advertised_not_verified_despite_professional(self):
        self.dictionary('Formats "PDF", "PNG", "SVG".')
        scripting = {'checks':{'professional':{'status':'ok','output':'true'}}}
        with patch.object(preflight,'run_command') as command:
            result = preflight.export_capabilities(self.root,scripting)
        command.assert_not_called()
        self.assertTrue(result['license']['professional'])
        self.assertEqual(result['status'],'dictionary_inspected')
        for entry in result['formats'].values():
            self.assertTrue(entry['advertised'])
            self.assertFalse(entry['export_verified'])

    def test_missing_format_not_inferred_from_license(self):
        self.dictionary('Formats "PDF", "PNG".')
        result = preflight.export_capabilities(self.root,{'checks':{'professional':{'status':'ok','output':'true'}}})
        self.assertFalse(result['formats']['SVG']['advertised'])

    def test_dictionary_failure_remains_unknown(self):
        result = preflight.export_capabilities(self.root,{})
        self.assertEqual(result['status'],'unknown')
        self.assertIsNone(result['license']['professional'])

    def test_collect_requires_stock_gui_helper(self):
        with patch.object(preflight.platform,'system',return_value='Darwin'), \
             patch.object(preflight,'app_info',return_value={'status':'present','path':str(self.root)}), \
             patch.object(preflight,'linkback_sandbox',return_value={'status':'exception_present'}), \
             patch.object(preflight,'probe_app',return_value={'status':'responding'}), \
             patch.object(preflight,'stock_helper_tools',return_value={'status':'missing'}), \
             patch.object(preflight,'tex_tools',return_value={'status':'present'}):
            result = preflight.collect(self.root,True,5,[],'stock-gui',self.root)
        self.assertIn('stock_gui_helper_build_tools_unavailable',result['blockers'])
        self.assertFalse(result['release_accepted'])

    def test_ssh_appleevent_timeout_reports_conditional_permission_hint(self):
        inventory = {'status': 'ok', 'instances': [
            {'pid': 101, 'path': '/Applications/OmniGraffle.app', 'bundle_id': preflight.APP_ID},
        ]}
        with patch.dict(os.environ, {'SSH_CONNECTION': 'test session'}, clear=True), \
             patch.object(preflight, 'running_instances', return_value=inventory), \
             patch.object(preflight, 'run_command', side_effect=[
                 {'status': 'ok', 'output': '7.26'}, {'status': 'timeout', 'error': '(-1712)'},
             ]) as command:
            report = preflight.probe_app(5, Path('/Applications/OmniGraffle.app'))
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(list(report['checks']), ['version', 'documents'])
        self.assertEqual(command.call_count, 2)
        diagnostic = report['timeout_diagnostic']
        self.assertEqual(diagnostic['status'], 'cause_unconfirmed')
        self.assertTrue(diagnostic['ssh_environment_detected'])
        self.assertIn('automation_decision_pending', diagnostic['possible_causes'])
        self.assertTrue(any('sshd-keygen-wrapper' in step for step in diagnostic['next_steps']))

    def test_timeout_without_ssh_does_not_assert_ssh_attribution(self):
        inventory = {'status': 'ok', 'instances': [
            {'pid': 101, 'path': '/Applications/OmniGraffle.app', 'bundle_id': preflight.APP_ID},
        ]}
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(preflight, 'running_instances', return_value=inventory), \
             patch.object(preflight, 'run_command', return_value={'status': 'timeout'}):
            report = preflight.probe_app(5, Path('/Applications/OmniGraffle.app'))
        diagnostic = report['timeout_diagnostic']
        self.assertFalse(diagnostic['ssh_environment_detected'])
        self.assertFalse(any('sshd-keygen-wrapper' in step for step in diagnostic['next_steps']))

    def test_permission_denial_is_not_reported_as_timeout(self):
        inventory = {'status': 'ok', 'instances': [
            {'pid': 101, 'path': '/Applications/OmniGraffle.app', 'bundle_id': preflight.APP_ID},
        ]}
        with patch.object(preflight, 'running_instances', return_value=inventory), \
             patch.object(preflight, 'run_command', return_value={'status': 'permission_denied'}):
            report = preflight.probe_app(5, Path('/Applications/OmniGraffle.app'))
        self.assertEqual(report['status'], 'blocked')
        self.assertNotIn('timeout_diagnostic', report)


if __name__ == '__main__':
    unittest.main()
