import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("omni_preflight", ROOT / "scripts/omnigraffle/preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)
APP = Path("/Applications/OmniGraffle.app")


def inventory(app=APP, pid=101):
    return {"status": "ok", "instances": [{"path": str(app.resolve()), "pid": pid, "bundle_id": preflight.APP_ID}]}


class OmniGrafflePreflightTests(unittest.TestCase):
    def test_missing_and_wrong_application_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Example.app"
            self.assertEqual(preflight.app_info(app)["status"], "unavailable")
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "other.app"}))
            self.assertEqual(preflight.app_info(app)["status"], "unavailable")

    def test_bundle_metadata_does_not_claim_runtime_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "OmniGraffle.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": preflight.APP_ID, "CFBundleShortVersionString": "7.26",
            }))
            self.assertEqual(preflight.app_info(app)["status"], "present")
            self.assertNotIn("ready", preflight.app_info(app))

    def test_version_success_followed_by_timeout_stops_without_retry(self):
        with patch.object(preflight, "running_instances", return_value=inventory()), patch.object(preflight, "run_command", side_effect=[
            {"status": "ok", "output": "7.26"}, {"status": "timeout"},
        ]) as runner:
            report = preflight.probe_app(2, APP)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(list(report["checks"]), ["version", "documents"])
        self.assertEqual(runner.call_count, 2)

    def test_invalid_response_is_not_a_pass(self):
        with patch.object(preflight, "running_instances", return_value=inventory()), patch.object(preflight, "run_command", return_value={"status": "ok", "output": ""}):
            self.assertEqual(preflight.probe_app(2, APP)["checks"]["version"]["status"], "invalid_response")

    def test_fixed_script_and_arguments_only(self):
        responses = [{"status": "ok", "output": value} for value in ("7.26", "0", "true", "2")]
        with patch.object(preflight, "running_instances", return_value=inventory()), patch.object(preflight, "run_command", side_effect=responses) as runner:
            report = preflight.probe_app(3, APP)
        self.assertEqual(report["status"], "responding")
        for call, probe in zip(runner.call_args_list, preflight.PROBES):
            self.assertEqual(call.args[0], ["/usr/bin/osascript", str(preflight.PROBE_SCRIPT), probe, "3", "/Applications/OmniGraffle.app"])
        self.assertNotIn("release_accepted", report)

    def test_application_path_is_an_argument_not_script_source(self):
        app = Path('/tmp/An App; "quoted" $name.app')
        with patch.object(preflight, "running_instances", return_value=inventory(app)), patch.object(preflight, "run_command", return_value={"status": "timeout"}) as runner:
            preflight.probe_app(2, app)
        self.assertEqual(runner.call_args.args[0][-1], str(app.resolve()))
        self.assertEqual(runner.call_args.args[0][1], str(preflight.PROBE_SCRIPT))

    def test_javascript_real_number_response(self):
        for value, expected in (("2.0", "responding"), ("3.0", "blocked"), ("NaN", "blocked")):
            with self.subTest(value=value):
                responses = [{"status": "ok", "output": item} for item in ("7.26", "1", "true", value)]
                with patch.object(preflight, "running_instances", return_value=inventory()), patch.object(preflight, "run_command", side_effect=responses):
                    self.assertEqual(preflight.probe_app(3, APP)["status"], expected)

    def test_subprocess_timeout_and_permission_failure(self):
        with patch.object(preflight.subprocess, "run", side_effect=subprocess.TimeoutExpired(["probe"], 1)):
            self.assertEqual(preflight.run_command(["probe"], 1)["status"], "timeout")
        response = subprocess.CompletedProcess(["probe"], 1, "", "Not authorized (-1743)")
        with patch.object(preflight.subprocess, "run", return_value=response):
            self.assertEqual(preflight.run_command(["probe"])["status"], "permission_denied")

    def test_passive_check_does_not_send_appleevents(self):
        with patch.object(preflight.platform, "system", return_value="Darwin"), \
             patch.object(preflight, "app_info", return_value={"status": "present", "path": str(APP)}), \
             patch.object(preflight, "linkback_sandbox", return_value={"status": "exception_present"}), \
             patch.object(preflight, "run_command", return_value={"status": "ok"}), \
             patch.object(preflight, "tex_tools", return_value={"status": "present"}), \
             patch.object(preflight, "probe_app") as probe:
            report = preflight.collect(Path("example.app"), False, 2, [])
        probe.assert_not_called()
        self.assertFalse(report["release_accepted"])
        self.assertIn("omnigraffle_scripting_not_verified", report["blockers"])

    def test_preflight_cannot_certify_acceptance_even_when_all_prerequisites_pass(self):
        with patch.object(preflight.platform, "system", return_value="Darwin"), \
             patch.object(preflight, "app_info", return_value={"status": "present", "path": str(APP)}), \
             patch.object(preflight, "linkback_sandbox", return_value={"status": "exception_present"}), \
             patch.object(preflight, "run_command", return_value={"status": "ok"}), \
             patch.object(preflight, "tex_tools", return_value={"status": "present"}), \
             patch.object(preflight, "probe_app", return_value={"status": "responding"}):
            report = preflight.collect(Path("example.app"), True, 2, [])
        self.assertEqual(report["status"], "prerequisites_present")
        self.assertFalse(report["release_accepted"])
        self.assertEqual(report["live_linkback_test"], "not_run")

    def test_unsupported_platform_does_not_run_native_commands(self):
        with patch.object(preflight.platform, "system", return_value="Linux"), \
             patch.object(preflight, "run_command") as runner:
            report = preflight.collect(Path("example.app"), True, 2, [])
        runner.assert_not_called()
        self.assertEqual(report["blockers"], ["macos_required"])

    def test_timeout_boundaries(self):
        for seconds in (0, 31):
            with self.assertRaises(ValueError):
                preflight.probe_app(seconds, APP)

    def test_uses_the_validated_application_path(self):
        with patch.object(preflight.platform, "system", return_value="Darwin"), \
             patch.object(preflight, "app_info", return_value={"status": "present", "path": "/tmp/Validated.app"}), \
             patch.object(preflight, "linkback_sandbox", return_value={"status": "exception_present"}), \
             patch.object(preflight, "run_command", return_value={"status": "ok"}), \
             patch.object(preflight, "tex_tools", return_value={"status": "present"}), \
             patch.object(preflight, "probe_app", return_value={"status": "responding"}) as probe:
            preflight.collect(Path("/tmp/Alias.app"), True, 2, [])
        probe.assert_called_once_with(2, Path("/tmp/Validated.app"))

    def test_command_failures_keep_the_report_fields(self):
        for error in (OSError("unavailable"), subprocess.TimeoutExpired(["probe"], 1)):
            with patch.object(preflight.subprocess, "run", side_effect=error):
                self.assertEqual(set(preflight.run_command(["probe"])), {"status", "exit_code", "output", "error"})

    def test_entitlements_distinguish_isolated_and_stock_services(self):
        for sandboxed, names, status in (
            (True, [preflight.STOCK_LINKBACK_SERVICE], "isolated_service_not_listed"),
            (True, [preflight.ISOLATED_LINKBACK_SERVICE], "exception_present"),
            (True, [], "isolated_service_not_listed"),
            (False, [], "sandbox_not_enabled"),
        ):
            data = {"com.apple.security.app-sandbox": sandboxed,
                    "com.apple.security.temporary-exception.mach-lookup.global-name": names}
            with self.subTest(status=status), patch.object(preflight, "run_command", return_value={
                "status": "ok", "output": plistlib.dumps(data).decode(),
            }) as runner:
                result = preflight.linkback_sandbox(APP)
            self.assertEqual(result["status"], status)
            self.assertFalse(result["live_linkback_verified"])
            self.assertEqual(result["stock_latexit_service_exception"], preflight.STOCK_LINKBACK_SERVICE in names)
            self.assertEqual(runner.call_args.args[0], ["/usr/bin/codesign", "-d", "--entitlements", "-", "--xml", str(APP.resolve())])

    def test_malformed_or_truncated_entitlements_cannot_pass(self):
        invalid = ("", "<plist><dict>", plistlib.dumps([]).decode(),
                   plistlib.dumps({"com.apple.security.app-sandbox": "true"}).decode(),
                   plistlib.dumps({"com.apple.security.temporary-exception.mach-lookup.global-name": "service"}).decode())
        for output in invalid:
            with self.subTest(output=output), patch.object(preflight, "run_command", return_value={"status": "ok", "output": output}):
                self.assertEqual(preflight.linkback_sandbox(APP)["status"], "unknown")
        for status in ("timeout", "unavailable", "error"):
            with patch.object(preflight, "run_command", return_value={"status": status}):
                self.assertEqual(preflight.linkback_sandbox(APP)["status"], "unknown")

    def test_missing_exception_blocks_before_appleevents(self):
        with patch.object(preflight.platform, "system", return_value="Darwin"), \
             patch.object(preflight, "app_info", return_value={"status": "present", "path": str(APP)}), \
             patch.object(preflight, "linkback_sandbox", return_value={"status": "isolated_service_not_listed"}), \
             patch.object(preflight, "run_command", return_value={"status": "ok"}), \
             patch.object(preflight, "tex_tools", return_value={"status": "present"}), \
             patch.object(preflight, "probe_app") as probe:
            result = preflight.collect(APP, True, 2, [])
        probe.assert_not_called()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("isolated_linkback_service_exception_missing", result["blockers"])
        self.assertFalse(result["release_accepted"])

    def test_stock_exception_does_not_require_isolated_service(self):
        data = {"com.apple.security.app-sandbox": True,
                "com.apple.security.temporary-exception.mach-lookup.global-name": [preflight.STOCK_LINKBACK_SERVICE]}
        with patch.object(preflight, "run_command", return_value={"status": "ok", "output": plistlib.dumps(data).decode()}):
            stock = preflight.linkback_sandbox(APP, preflight.STOCK_LINKBACK_SERVICE)
            isolated = preflight.linkback_sandbox(APP)
        self.assertEqual(stock["status"], "exception_present")
        self.assertTrue(stock["selected_service_exception"])
        self.assertFalse(stock["isolated_service_exception"])
        self.assertFalse(stock["live_linkback_verified"])
        self.assertEqual(isolated["status"], "isolated_service_not_listed")

    def test_stock_backend_does_not_require_xcode_or_certify_gui(self):
        with patch.object(preflight.platform, "system", return_value="Darwin"), \
             patch.object(preflight, "app_info", return_value={"status": "present", "path": str(APP)}) as info, \
             patch.object(preflight, "linkback_sandbox", return_value={"status": "exception_present"}) as sandbox, \
             patch.object(preflight, "run_command") as run, \
             patch.object(preflight, "tex_tools", return_value={"status": "present"}), \
             patch.object(preflight, "probe_app", return_value={"status": "responding"}):
            result = preflight.collect(APP, True, 2, [], "stock-gui", Path('/tmp/Stock "App".app'))
        run.assert_not_called()
        info.assert_any_call(Path('/tmp/Stock "App".app'), preflight.LATEXIT_APP_ID)
        sandbox.assert_called_once_with(APP, preflight.STOCK_LINKBACK_SERVICE)
        self.assertEqual(result["status"], "prerequisites_present")
        self.assertEqual(result["build_tools"]["status"], "not_required_for_stock_gui")
        self.assertEqual(result["gui"]["status"], "not_probed")
        self.assertFalse(result["release_accepted"])

    def test_missing_stock_app_and_exception_are_blockers(self):
        with patch.object(preflight.platform, "system", return_value="Darwin"), \
             patch.object(preflight, "app_info", side_effect=[{"status": "present", "path": str(APP)}, {"status": "unavailable"}]), \
             patch.object(preflight, "linkback_sandbox", return_value={"status": "stock_service_not_listed"}), \
             patch.object(preflight, "tex_tools", return_value={"status": "present"}), \
             patch.object(preflight, "probe_app") as probe:
            result = preflight.collect(APP, True, 2, [], "stock-gui")
        probe.assert_not_called()
        self.assertIn("stock_latexit_unavailable", result["blockers"])
        self.assertIn("stock_linkback_service_exception_missing", result["blockers"])

    def test_unknown_backend_and_service_rejected_without_commands(self):
        with patch.object(preflight, "run_command") as runner:
            with self.assertRaises(ValueError):
                preflight.collect(APP, True, 2, [], "arbitrary")
            with self.assertRaises(ValueError):
                preflight.linkback_sandbox(APP, "arbitrary")
        runner.assert_not_called()

    def test_duplicate_instances_block_before_native_queries(self):
        duplicate = {"status": "ok", "instances": [*inventory()["instances"], *inventory(Path("/Volumes/Example/OmniGraffle.app"), 202)["instances"]]}
        with patch.object(preflight, "running_instances", return_value=duplicate), patch.object(preflight, "run_command") as runner:
            report = preflight.probe_app(2, APP)
        runner.assert_not_called()
        self.assertEqual(report["reason"], "ambiguous_running_instances")
        self.assertEqual(report["checks"], {})

    def test_wrong_running_copy_blocks_before_native_queries(self):
        with patch.object(preflight, "running_instances", return_value=inventory(Path("/Volumes/Example/OmniGraffle.app"))), patch.object(preflight, "run_command") as runner:
            report = preflight.probe_app(2, APP)
        runner.assert_not_called()
        self.assertEqual(report["reason"], "running_instance_path_mismatch")

    def test_no_instance_allows_version_then_validates_started_copy(self):
        for started, reason in ((inventory(), None), ({"status": "ok", "instances": []}, "selected_app_not_running_after_launch"),
                                (inventory(Path("/Volumes/Example/OmniGraffle.app")), "running_instance_path_mismatch")):
            with self.subTest(reason=reason):
                discoveries = [{"status": "ok", "instances": []}, started, started, started]
                replies = [{"status": "ok", "output": x} for x in ("7.26", "0", "true", "2.0")]
                with patch.object(preflight, "running_instances", side_effect=discoveries), patch.object(preflight, "run_command", side_effect=replies) as runner:
                    report = preflight.probe_app(2, APP)
                if reason:
                    self.assertEqual(report["reason"], reason)
                    self.assertEqual(runner.call_count, 1)
                else:
                    self.assertEqual(report["status"], "responding")

    def test_changed_pid_blocks_later_queries(self):
        with patch.object(preflight, "running_instances", side_effect=[inventory(), inventory(pid=202)]), patch.object(preflight, "run_command", return_value={"status": "ok", "output": "7.26"}) as runner:
            report = preflight.probe_app(2, APP)
        self.assertEqual(report["reason"], "running_instance_changed")
        self.assertEqual(runner.call_count, 1)

    def test_process_discovery_uses_fixed_appkit_code(self):
        data = inventory()["instances"]
        with patch.object(preflight, "run_command", return_value={"status": "ok", "output": json.dumps(data)}) as runner:
            report = preflight.running_instances(2)
        self.assertEqual(report, inventory())
        self.assertEqual(runner.call_args.args[0], ["/usr/bin/osascript", "-l", "JavaScript", "-e", preflight.PROCESS_SCRIPT])
        self.assertIn("NSRunningApplication.runningApplicationsWithBundleIdentifier", preflight.PROCESS_SCRIPT)
        self.assertNotIn("Application(", preflight.PROCESS_SCRIPT)

    def test_unavailable_or_malformed_discovery_blocks_native_queries(self):
        invalid = ("", "{}", "null", '[{"pid":true,"path":"/Example.app","bundle_id":"other"}]',
                   '[{"pid":1,"path":"relative","bundle_id":"com.omnigroup.OmniGraffle7"}]')
        for output in invalid:
            with self.subTest(output=output), patch.object(preflight, "run_command", return_value={"status": "ok", "output": output}) as runner:
                report = preflight.probe_app(2, APP)
            self.assertEqual(report["reason"], "running_instance_discovery_unavailable")
            self.assertEqual(runner.call_count, 1)
            self.assertEqual(runner.call_args.args[0][1:3], ["-l", "JavaScript"])
        with patch.object(preflight, "run_command", return_value={"status": "timeout"}) as runner:
            report = preflight.probe_app(2, APP)
        self.assertEqual(report["reason"], "running_instance_discovery_unavailable")
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
