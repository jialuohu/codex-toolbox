from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
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

if sys.argv[1:] == ["--version"]:
    print("2.1.test (Claude Code)")
    raise SystemExit(0)
if sys.argv[1:] == ["auth", "status", "--json"]:
    print(json.dumps({
        "loggedIn": True,
        "authMethod": "claude.ai",
        "email": "must-not-escape@example.invalid",
        "orgName": "must-not-escape",
    }))
    raise SystemExit(0)

mode_path = directory / "mode"
mode = mode_path.read_text(encoding="utf-8") if mode_path.exists() else "ok"
payload = sys.stdin.read()
if mode == "fail":
    raise SystemExit(9)
if mode == "malformed":
    print("not-json")
    raise SystemExit(0)
if mode == "schema":
    print(json.dumps({"structured_output": {"unexpected": True}}))
    raise SystemExit(0)
if mode == "sleep":
    time.sleep(2)

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
print(json.dumps({"structured_output": structured, "payload_length": len(payload)}))
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
        timeout_seconds: int = 5,
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
        return subprocess.run(
            [
                sys.executable,
                str(WRAPPER),
                mode,
                "--timeout-seconds",
                str(timeout_seconds),
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=10,
            check=False,
        )

    def calls(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

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


if __name__ == "__main__":
    unittest.main()
