from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (
    ROOT
    / "plugins"
    / "workflow-tools"
    / "skills"
    / "claude-counselor"
    / "scripts"
    / "claude_counselor.py"
)


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

directory = Path(__file__).resolve().parent
log_path = directory / "calls.jsonl"
record = {
    "args": sys.argv[1:],
    "api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
    "auth_token_present": bool(os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    "home_present": bool(os.environ.get("HOME")),
    "unrelated_present": bool(os.environ.get("SHOULD_NOT_REACH_CLAUDE")),
}
with open(log_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")

mode_path = directory / "mode"
mode = mode_path.read_text(encoding="utf-8") if mode_path.exists() else "ok"
if sys.argv[1:] == ["--version"]:
    if mode == "version_timeout":
        time.sleep(2)
    print("2.1.test (Claude Code)")
    raise SystemExit(0)
if sys.argv[1:] == ["auth", "status", "--json"]:
    if mode == "auth_timeout":
        time.sleep(2)
    if mode == "auth_scalar":
        print('"private-output-marker"')
        raise SystemExit(0)
    print(json.dumps({
        "loggedIn": True,
        "authMethod": "claude.ai",
        "email": "must-not-escape@example.invalid",
        "orgName": "must-not-escape",
    }))
    raise SystemExit(0)

(directory / "model.pid").write_text(str(os.getpid()))
payload = sys.stdin.read()
if mode == "fail":
    print("private-output-marker")
    print("private-output-marker", file=sys.stderr)
    raise SystemExit(9)
if mode == "malformed":
    print("private-output-marker")
    raise SystemExit(0)
if mode == "schema":
    print(json.dumps({"structured_output": {"unexpected": True}}))
    raise SystemExit(0)
if mode == "sleep":
    time.sleep(2)
if mode == "active_timeout":
    for _ in range(60):
        print("private-output-marker", flush=True)
        print("private-output-marker", file=sys.stderr, flush=True)
        time.sleep(.05)
if mode == "invalid_utf8":
    sys.stdout.buffer.write(b'private-output-marker\xff')
    raise SystemExit(0)
if mode == "slow_success":
    time.sleep(.3)

if "planning counselor" in sys.argv[-1]:
    structured = {
        "summary": "Independent plan",
        "assumptions": [],
        "risks": [{"severity": "medium", "issue": "Risk", "mitigation": "Check it"}],
        "alternatives": [{"option": "Alternative", "tradeoffs": "Different cost"}],
        "recommended_changes": ["Verify the boundary"],
        "questions": [],
    }
else:
    structured = {
        "findings": [{
            "severity": "low",
            "title": "Example finding",
            "evidence": "Supplied diff",
            "recommendation": "Verify locally",
        }],
        "overall_assessment": "pass_with_findings",
    }
if mode == "bad_severity":
    structured["findings"][0]["severity"] = ["private-output-marker"]
if mode == "bad_assessment":
    structured["overall_assessment"] = {"private-output-marker": True}
if mode == "bad_plan_severity":
    structured["risks"][0]["severity"] = ["private-output-marker"]
response = {
    "subtype": "success",
    "structured_output": structured,
    "payload_length": len(payload),
    "result": "private-output-marker",
    "session_id": "private-output-marker",
    "duration_ms": 300,
    "duration_api_ms": 250,
    "num_turns": 2,
    "usage": {"input_tokens": 7, "output_tokens": 11, "private-output-marker": 9},
    "modelUsage": {"claude-opus-5[1m]": {}, "private-output-marker": {}},
}
if mode == "error_result":
    response["is_error"] = True
    response["subtype"] = "error_max_structured_output_retries"
    response["errors"] = ["private-output-marker"]
if mode == "bad_metrics":
    response.update(duration_ms="private-output-marker", duration_api_ms=True, num_turns=-1)
    response["usage"] = {"input_tokens": True, "output_tokens": 10**13}
    response["modelUsage"] = {"claude-opus-5-private-output-marker": {}}
    response["subtype"] = ["private-output-marker"]
print("private-output-marker", file=sys.stderr)
print(json.dumps(response))
'''


class ClaudeCounselorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.fake_claude = self.directory / "claude"
        self.fake_claude.write_text(textwrap.dedent(FAKE_CLAUDE), encoding="utf-8")
        self.fake_claude.chmod(0o755)
        self.log = self.directory / "calls.jsonl"
        self.mode = self.directory / "mode"

    def run_wrapper(
        self,
        mode: str,
        *,
        payload: bytes = b"task-scoped context",
        fake_mode: str = "ok",
        timeout_seconds: int | None = 5,
        preflight_timeout_seconds: float = 20,
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.directory}{os.pathsep}{environment.get('PATH', '')}"
        environment["SHOULD_NOT_REACH_CLAUDE"] = "marker"
        environment.pop("ANTHROPIC_API_KEY", None)
        environment.pop("ANTHROPIC_AUTH_TOKEN", None)
        self.mode.write_text(fake_mode, encoding="utf-8")
        if extra_environment:
            environment.update(extra_environment)
        # Speed up heartbeats and optional preflight timeouts only in this test
        # process, without adding production flags or environment escape hatches.
        runner = (
            "import runpy, sys; "
            "namespace = runpy.run_path(sys.argv[1]); "
            "settings = namespace['main'].__globals__; "
            "settings['PROGRESS_INTERVAL_SECONDS'] = .05; "
            "settings['PREFLIGHT_TIMEOUT_SECONDS'] = float(sys.argv[2]); "
            "sys.exit(namespace['main'](sys.argv[3:]))"
        )
        command = [sys.executable, "-c", runner, str(WRAPPER), str(preflight_timeout_seconds), mode]
        if timeout_seconds is not None:
            command.extend(["--timeout-seconds", str(timeout_seconds)])
        return subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=10,
            check=False,
        )

    def calls(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def diagnostics(self, result: subprocess.CompletedProcess[bytes]) -> list[dict[str, object]]:
        return [json.loads(line) for line in result.stderr.decode().splitlines()]

    def assert_private_text_hidden(self, result: subprocess.CompletedProcess[bytes]) -> None:
        for marker in (b"private-output-marker", b"must-not-escape"):
            self.assertNotIn(marker, result.stdout)
            self.assertNotIn(marker, result.stderr)

    def test_doctor_reports_only_bounded_status(self) -> None:
        result = self.run_wrapper("doctor", payload=b"")

        self.assertEqual(result.returncode, 0, result.stderr.decode())
        output = json.loads(result.stdout)
        self.assertEqual(
            output,
            {
                "auth_method": "claude.ai",
                "claude_version": "2.1.test (Claude Code)",
                "mode": "doctor",
                "ok": True,
            },
        )
        self.assertNotIn("must-not-escape", result.stdout.decode())
        self.assertEqual(len(self.calls()), 2)

    def test_plan_uses_guarded_flags_and_structured_output(self) -> None:
        result = self.run_wrapper("plan")

        self.assertEqual(result.returncode, 0, result.stderr.decode())
        output = json.loads(result.stdout)
        self.assertTrue(output["ok"])
        self.assertEqual(output["mode"], "plan")
        self.assertEqual(output["result"]["summary"], "Independent plan")
        model_call = self.calls()[-1]
        arguments = model_call["args"]
        for expected in (
            "--safe-mode",
            "--print",
            "--no-session-persistence",
            "--no-chrome",
            "--permission-mode",
            "dontAsk",
            "--tools",
            "--output-format",
            "json",
            "--json-schema",
        ):
            self.assertIn(expected, arguments)
        self.assertEqual(arguments[arguments.index("--tools") + 1], "")
        self.assertFalse(model_call["api_key_present"])
        self.assertFalse(model_call["auth_token_present"])
        self.assertTrue(model_call["home_present"])
        self.assertFalse(model_call["unrelated_present"])

    def test_review_returns_findings(self) -> None:
        result = self.run_wrapper("review", payload=b"diff and tests")

        self.assertEqual(result.returncode, 0, result.stderr.decode())
        output = json.loads(result.stdout)
        self.assertEqual(output["result"]["overall_assessment"], "pass_with_findings")
        self.assertEqual(len(output["result"]["findings"]), 1)

    def test_authentication_environment_conflict_fails_before_launch(self) -> None:
        result = self.run_wrapper(
            "plan",
            extra_environment={"ANTHROPIC_API_KEY": "configured"},
        )

        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertEqual(output["error"]["code"], "auth_environment_conflict")
        self.assertFalse(self.log.exists())

    def test_failed_model_call_is_not_retried(self) -> None:
        result = self.run_wrapper("review", fake_mode="fail")

        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertEqual(output["error"]["code"], "claude_failed")
        self.assertEqual(len(self.calls()), 3)

    def test_invalid_responses_and_timeout_are_typed_failures(self) -> None:
        malformed = self.run_wrapper("plan", fake_mode="malformed")
        self.assertEqual(json.loads(malformed.stdout)["error"]["code"], "invalid_response")

        self.log.unlink()
        schema = self.run_wrapper("plan", fake_mode="schema")
        self.assertEqual(json.loads(schema.stdout)["error"]["code"], "schema_mismatch")

        self.log.unlink()
        timed_out = self.run_wrapper("review", fake_mode="sleep", timeout_seconds=1)
        self.assertEqual(json.loads(timed_out.stdout)["error"]["code"], "timeout")
        self.assertEqual(len(self.calls()), 3)

    def test_empty_and_oversized_inputs_do_not_make_model_calls(self) -> None:
        empty = self.run_wrapper("plan", payload=b"")
        self.assertEqual(json.loads(empty.stdout)["error"]["code"], "empty_input")
        self.assertEqual(len(self.calls()), 2)

        self.log.unlink()
        oversized = self.run_wrapper("review", payload=b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(json.loads(oversized.stdout)["error"]["code"], "input_too_large")
        self.assertEqual(len(self.calls()), 2)

    def test_default_and_large_review_deadlines_and_cli_bounds(self) -> None:
        default = self.run_wrapper("plan", timeout_seconds=None)
        model = [d for d in self.diagnostics(default) if d["stage"] == "model"]
        self.assertTrue(model)
        self.assertTrue(all(d["timeout_seconds"] == 600 for d in model))
        self.assertEqual(default.returncode, 0)
        large = self.run_wrapper("review", timeout_seconds=900)
        self.assertEqual(large.returncode, 0)
        self.assertEqual(self.diagnostics(large)[-1]["timeout_seconds"], 900)
        self.log.unlink()
        for limit in (0, 901):
            result = self.run_wrapper("plan", timeout_seconds=limit)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(self.log.exists())

    def test_heartbeats_preserve_single_stdout_result_and_safe_metrics(self) -> None:
        result = self.run_wrapper("plan", fake_mode="slow_success", payload=b"private-output-marker")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        events = self.diagnostics(result)
        progress = [event for event in events if event["event"] == "progress"]
        self.assertGreaterEqual(len(progress), 1)
        self.assertTrue(all(event["stage"] == "model" for event in progress))
        self.assertTrue(all(event["elapsed_seconds"] > 0 for event in progress))
        finished = events[-1]
        self.assertEqual(finished["event"], "exited")
        self.assertEqual(finished["models"], ["claude-opus-5[1m]"])
        self.assertEqual(finished["duration_ms"], 300)
        self.assertEqual(finished["result_subtype"], "success")
        self.assertEqual(finished["output_tokens"], 11)
        self.assertEqual(len(self.calls()), 3)
        self.assert_private_text_hidden(result)

    def test_progress_never_extends_deadline_and_timed_out_child_is_reaped(self) -> None:
        for fake_mode in ("sleep", "active_timeout"):
            with self.subTest(fake_mode=fake_mode):
                if self.log.exists():
                    self.log.unlink()
                started = time.monotonic()
                result = self.run_wrapper("review", fake_mode=fake_mode, timeout_seconds=1)
                self.assertLess(time.monotonic() - started, 2.5)
                error = json.loads(result.stdout)["error"]
                self.assertEqual(error["code"], "timeout")
                details = error["diagnostics"]
                self.assertEqual(details["stage"], "model")
                self.assertEqual(details["timeout_seconds"], 1)
                self.assertGreaterEqual(details["elapsed_seconds"], 1)
                self.assertEqual(len(self.calls()), 3)
                self.assert_private_text_hidden(result)
                if os.name == "posix":
                    pid = int((self.directory / "model.pid").read_text())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)

    def test_preflight_timeout_identifies_stage_without_model_call(self) -> None:
        for stage, call_count in (("version", 1), ("auth", 2)):
            with self.subTest(stage=stage):
                if self.log.exists():
                    self.log.unlink()
                result = self.run_wrapper(
                    "plan", fake_mode=f"{stage}_timeout", preflight_timeout_seconds=.5,
                )
                error = json.loads(result.stdout)["error"]
                self.assertEqual(error["code"], "timeout")
                self.assertEqual(error["diagnostics"]["stage"], stage)
                self.assertEqual(error["diagnostics"]["timeout_seconds"], .5)
                self.assertEqual(len(self.calls()), call_count)
                self.assert_private_text_hidden(result)

    def test_failure_diagnostics_never_forward_untrusted_cli_text(self) -> None:
        for fake_mode, code in (
            ("fail", "claude_failed"), ("malformed", "invalid_response"),
            ("invalid_utf8", "encoding_failed"), ("error_result", "claude_failed"),
            ("auth_scalar", "auth_status_invalid"), ("bad_severity", "schema_mismatch"),
            ("bad_assessment", "schema_mismatch"), ("bad_plan_severity", "schema_mismatch"),
        ):
            with self.subTest(fake_mode=fake_mode):
                mode = "plan" if fake_mode == "bad_plan_severity" else "review"
                result = self.run_wrapper(mode, fake_mode=fake_mode)
                self.assertEqual(result.returncode, 1)
                error = json.loads(result.stdout)["error"]
                self.assertEqual(error["code"], code)
                self.assertIn("stage", error["diagnostics"])
                if fake_mode == "error_result":
                    self.assertEqual(error["diagnostics"]["result_subtype"], "error_max_structured_output_retries")
                self.assert_private_text_hidden(result)

    def test_malformed_metrics_are_omitted_without_failing_valid_counsel(self) -> None:
        result = self.run_wrapper("review", fake_mode="bad_metrics")
        self.assertEqual(result.returncode, 0)
        final = self.diagnostics(result)[-1]
        for key in ("duration_ms", "duration_api_ms", "num_turns", "input_tokens", "output_tokens", "models", "result_subtype"):
            self.assertNotIn(key, final)
        self.assert_private_text_hidden(result)


if __name__ == "__main__":
    unittest.main()
