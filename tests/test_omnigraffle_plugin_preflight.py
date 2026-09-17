"""Doctor reports are discovery evidence, never native export acceptance."""
import importlib.util
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


if __name__ == '__main__':
    unittest.main()
