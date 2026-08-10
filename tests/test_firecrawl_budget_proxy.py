import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXY_PATH = (
    ROOT
    / "plugins"
    / "web-data-tools"
    / "scripts"
    / "firecrawl_budget_proxy.py"
)
LAUNCHER_PATH = (
    ROOT
    / "plugins"
    / "web-data-tools"
    / "scripts"
    / "run-firecrawl-mcp.sh"
)

SPEC = importlib.util.spec_from_file_location("firecrawl_budget_proxy", PROXY_PATH)
proxy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proxy
SPEC.loader.exec_module(proxy)


PERIOD = {
    "billingPeriodStart": "2026-08-01T00:00:00Z",
    "billingPeriodEnd": "2026-09-01T00:00:00Z",
}


FAKE_CHILD = r"""
import json
import os
import sys

log_path = os.environ["FAKE_FIRECRAWL_LOG"]
print("fake-firecrawl-stderr", file=sys.stderr, flush=True)

def record(message):
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(message, sort_keys=True) + "\n")

def respond(message, result):
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)

for line in sys.stdin:
    message = json.loads(line)
    record(message)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "initialize":
        respond(message, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-firecrawl", "version": "1"},
            "instructions": "Use Crawl, Map, Agent, Parse, Extract, Monitor, and JSON output.",
        })
    elif method == "tools/list":
        respond(message, {"tools": [
            {"name": "firecrawl_search", "inputSchema": {"type": "object", "additionalProperties": True}},
            {"name": "firecrawl_scrape", "inputSchema": {"type": "object", "additionalProperties": True}},
            {"name": "firecrawl_crawl", "inputSchema": {"type": "object"}},
            {"name": "firecrawl_map", "inputSchema": {"type": "object"}},
            {"name": "firecrawl_agent", "inputSchema": {"type": "object"}},
            {"name": "future_unknown_tool", "inputSchema": {"type": "object"}},
        ]})
    elif method == "tools/call":
        arguments = message["params"].get("arguments", {})
        response = {
            "content": [{"type": "text", "text": json.dumps(arguments, sort_keys=True)}],
            "structuredContent": {"arguments": arguments},
            "isError": os.environ.get("FAKE_FIRECRAWL_FAIL_CALL") == "1",
        }
        respond(message, response)
    elif method == "shutdown":
        respond(message, {})
    else:
        respond(message, {"echoMethod": method})
"""


class UsageService:
    def __init__(self, payload=None):
        self.payload = payload or {
            "planCredits": 1000,
            "remainingCredits": 1000,
            **PERIOD,
        }
        self.status_code = 200
        self.calls = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.calls.append(
                    {"path": self.path, "authorization": self.headers.get("Authorization")}
                )
                body = json.dumps(owner.payload).encode("utf-8")
                self.send_response(owner.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = (
            f"http://127.0.0.1:{self.server.server_address[1]}"
            "/v2/team/credit-usage"
        )

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class ProxyProcess:
    def __init__(
        self,
        base: Path,
        usage: UsageService,
        *,
        fail_calls=False,
        child_source=FAKE_CHILD,
    ):
        self.base = base
        self.codex_home = base / "codex-home"
        self.log_path = base / "fake-child.jsonl"
        self.child_path = base / "fake-child.py"
        self.child_path.write_text(textwrap.dedent(child_source), encoding="utf-8")
        self.runner_path = base / "proxy-runner.py"
        self.runner_path.write_text(
            textwrap.dedent(
                f"""
                import importlib.util
                import sys

                spec = importlib.util.spec_from_file_location("firecrawl_budget_proxy_runner", {str(PROXY_PATH)!r})
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                raise SystemExit(module.main(sys.argv[1:], usage_url={usage.url!r}))
                """
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "CODEX_HOME": str(self.codex_home),
                proxy.FIRECRAWL_CREDENTIAL_ENV: "test-firecrawl-key",
                "FAKE_FIRECRAWL_LOG": str(self.log_path),
                "PYTHONUNBUFFERED": "1",
            }
        )
        if fail_calls:
            env["FAKE_FIRECRAWL_FAIL_CALL"] = "1"
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(self.runner_path),
                "serve",
                "--",
                sys.executable,
                str(self.child_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )
        self._next_id = 1
        self._closed = False
        self._closed_output = ("", "")

    @property
    def state_path(self):
        return self.codex_home / "state" / proxy.STATE_FILENAME

    def request(self, method, params=None):
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        self.assert_response_id(response, request_id)
        return response

    @staticmethod
    def assert_response_id(response, request_id):
        if response.get("id") != request_id:
            raise AssertionError(f"unexpected response: {response!r}")

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def records(self):
        if not self.log_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def close(self):
        if self._closed:
            return self._closed_output
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        stdout = self.process.stdout.read()
        stderr = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self._closed = True
        self._closed_output = (stdout, stderr)
        return self._closed_output


class FirecrawlBudgetProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.usage = UsageService()
        self.clients = []
        self.old_credential = os.environ.get(proxy.FIRECRAWL_CREDENTIAL_ENV)
        os.environ[proxy.FIRECRAWL_CREDENTIAL_ENV] = "test-firecrawl-key"

    def tearDown(self):
        for client in self.clients:
            if client.process.poll() is None:
                client.close()
        self.usage.close()
        if self.old_credential is None:
            os.environ.pop(proxy.FIRECRAWL_CREDENTIAL_ENV, None)
        else:
            os.environ[proxy.FIRECRAWL_CREDENTIAL_ENV] = self.old_credential
        self.temp.cleanup()

    def client(self, **kwargs):
        client = ProxyProcess(self.base, self.usage, **kwargs)
        self.clients.append(client)
        return client

    def write_state(self, path, *, counted, period=None, mode=0o600):
        period = period or PERIOD
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "capCredits": 900,
                    "countedCredits": counted,
                    "accountPlanCredits": 1000,
                    "accountRemainingCredits": max(0, 1000 - counted),
                    **period,
                    "updatedAt": "2026-08-09T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        path.chmod(mode)

    def assert_tool_failure(self, response, code):
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["code"], code)

    def test_initialization_notifications_filtering_status_and_shutdown(self):
        client = self.client()
        initialized = client.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "fake-firecrawl")
        self.assertEqual(
            initialized["result"]["instructions"],
            proxy.BOUNDED_SERVER_INSTRUCTIONS,
        )
        for hidden_capability in (
            "Crawl",
            "Map",
            "Agent",
            "Parse",
            "Extract",
            "Monitor",
            "JSON output",
        ):
            self.assertNotIn(hidden_capability, initialized["result"]["instructions"])
        client.notify("notifications/initialized")

        listed = client.request("tools/list", {})
        tools = listed["result"]["tools"]
        self.assertEqual(
            [tool["name"] for tool in tools],
            ["firecrawl_search", "firecrawl_scrape", "firecrawl_budget_status"],
        )
        for tool in tools:
            self.assertFalse(tool["inputSchema"].get("additionalProperties", True))

        status_response = client.request(
            "tools/call", {"name": "firecrawl_budget_status", "arguments": {}}
        )
        status = status_response["result"]["structuredContent"]
        self.assertEqual(status["capCredits"], 900)
        self.assertEqual(status["countedCredits"], 0)
        self.assertEqual(status["remainingAllowanceCredits"], 900)
        self.assertEqual(status["accountRemainingCredits"], 1000)
        self.assertEqual(status["billingPeriodStart"], PERIOD["billingPeriodStart"])
        self.assertEqual(status["billingPeriodEnd"], PERIOD["billingPeriodEnd"])
        self.assertEqual(status["allowedTools"], sorted(proxy.ALLOWED_TOOLS))
        self.assertNotIn("test-firecrawl-key", json.dumps(status))
        self.assertFalse(
            any(
                record.get("params", {}).get("name") == "firecrawl_budget_status"
                for record in client.records()
            )
        )

        ping = client.request("ping")
        self.assertEqual(ping["result"]["echoMethod"], "ping")
        client.request("shutdown")
        _stdout, stderr = client.close()
        self.assertIn("fake-firecrawl-stderr", stderr)
        self.assertEqual(client.process.returncode, 0)
        self.assertTrue(
            any(record.get("method") == "notifications/initialized" for record in client.records())
        )

    def test_search_reserves_two_credits_and_injects_bounded_defaults(self):
        client = self.client()
        response = client.request(
            "tools/call",
            {"name": "firecrawl_search", "arguments": {"query": "forum reports"}},
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["arguments"],
            {
                "query": "forum reports",
                "limit": 5,
                "sources": [{"type": "web"}],
            },
        )
        state = json.loads(client.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["countedCredits"], 2)
        self.assertEqual(state["accountRemainingCredits"], 998)
        self.assertEqual(stat.S_IMODE(client.state_path.stat().st_mode), 0o600)
        self.assertEqual(len(self.usage.calls), 1)
        self.assertEqual(self.usage.calls[0]["path"], "/v2/team/credit-usage")
        self.assertEqual(self.usage.calls[0]["authorization"], "Bearer test-firecrawl-key")

    def test_wechat_shaped_scrape_reserves_one_credit_and_is_normalized(self):
        client = self.client()
        arguments = {
            "url": "https://mp.weixin.qq.com/s/example",
            "formats": ["markdown"],
            "onlyMainContent": True,
            "mobile": True,
            "storeInCache": False,
            "proxy": "basic",
        }
        response = client.request(
            "tools/call", {"name": "firecrawl_scrape", "arguments": arguments}
        )
        forwarded = response["result"]["structuredContent"]["arguments"]
        self.assertEqual(
            forwarded,
            {
                **arguments,
                "parsers": [],
            },
        )
        state = json.loads(client.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["countedCredits"], 1)

    def test_unknown_tools_and_costly_parameters_never_reach_child(self):
        client = self.client()
        calls = [
            {"name": "firecrawl_crawl", "arguments": {"url": "https://example.com"}},
            {"name": "firecrawl_map", "arguments": {"url": "https://example.com"}},
            {"name": "firecrawl_agent", "arguments": {"prompt": "browse everything"}},
            {
                "name": "firecrawl_search",
                "arguments": {"query": "x", "scrapeOptions": {"formats": ["markdown"]}},
            },
            {
                "name": "firecrawl_search",
                "arguments": {"query": "x", "categories": ["research"]},
            },
            {
                "name": "firecrawl_search",
                "arguments": {"query": "x", "enterprise": True},
            },
            {
                "name": "firecrawl_scrape",
                "arguments": {"url": "https://example.com", "formats": ["json"]},
            },
            {
                "name": "firecrawl_scrape",
                "arguments": {"url": "https://example.com", "actions": [{"type": "wait"}]},
            },
            {
                "name": "firecrawl_scrape",
                "arguments": {"url": "https://example.com", "proxy": "auto"},
            },
            {
                "name": "firecrawl_scrape",
                "arguments": {"url": "https://example.com", "parsers": ["pdf"]},
            },
            {
                "name": "firecrawl_scrape",
                "arguments": {"url": "https://example.com/report.pdf"},
            },
            {
                "name": "firecrawl_scrape",
                "arguments": {"url": "https://example.com", "mobile": "yes"},
            },
        ]
        for call in calls:
            with self.subTest(call=call):
                response = client.request("tools/call", call)
                self.assert_tool_failure(response, proxy.ERROR_REQUEST_NOT_BOUNDED)
        self.assertFalse(
            any(record.get("method") == "tools/call" for record in client.records())
        )
        self.assertEqual(self.usage.calls, [])

    def test_exact_cap_boundaries_and_no_refund_after_child_error(self):
        client = self.client(fail_calls=True)
        self.write_state(client.state_path, counted=898)
        response = client.request(
            "tools/call",
            {"name": "firecrawl_search", "arguments": {"query": "x", "limit": 1}},
        )
        self.assertTrue(response["result"]["isError"])
        state = json.loads(client.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["countedCredits"], 900)

        denied = client.request(
            "tools/call",
            {"name": "firecrawl_scrape", "arguments": {"url": "https://example.com"}},
        )
        self.assert_tool_failure(denied, proxy.ERROR_BUDGET_EXHAUSTED)
        self.assertEqual(
            sum(record.get("method") == "tools/call" for record in client.records()), 1
        )
        state = json.loads(client.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["countedCredits"], 900)

    def test_concurrent_reservations_are_serialized_at_the_cap(self):
        state_path = self.base / "concurrent-home" / "state" / proxy.STATE_FILENAME
        self.write_state(state_path, counted=899)
        manager_one = proxy.BudgetManager(state_path=state_path, usage_url=self.usage.url)
        manager_two = proxy.BudgetManager(state_path=state_path, usage_url=self.usage.url)
        barrier = threading.Barrier(3)
        outcomes = []

        def reserve(manager):
            barrier.wait()
            try:
                manager.reserve(1)
                outcomes.append("ok")
            except proxy.ProxyFailure as failure:
                outcomes.append(failure.code)

        threads = [
            threading.Thread(target=reserve, args=(manager_one,)),
            threading.Thread(target=reserve, args=(manager_two,)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertCountEqual(outcomes, ["ok", proxy.ERROR_BUDGET_EXHAUSTED])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["countedCredits"], 900)

    def test_remote_usage_reconciliation_and_newer_period_rollover(self):
        state_path = self.base / "manager-home" / "state" / proxy.STATE_FILENAME
        self.write_state(state_path, counted=20)
        self.usage.payload["remainingCredits"] = 958
        manager = proxy.BudgetManager(state_path=state_path, usage_url=self.usage.url)
        reconciled = manager.status()
        self.assertEqual(reconciled["countedCredits"], 42)

        self.usage.payload = {
            "planCredits": 1000,
            "remainingCredits": 995,
            "billingPeriodStart": "2026-09-01T00:00:00Z",
            "billingPeriodEnd": "2026-10-01T00:00:00Z",
        }
        rolled = manager.status()
        self.assertEqual(rolled["countedCredits"], 5)
        self.assertEqual(rolled["remainingAllowanceCredits"], 895)

    def test_denied_remote_high_water_is_durable_and_cannot_reopen(self):
        state_path = self.base / "high-water-home" / "state" / proxy.STATE_FILENAME
        self.write_state(state_path, counted=10)
        manager = proxy.BudgetManager(state_path=state_path, usage_url=self.usage.url)
        self.usage.payload["remainingCredits"] = 50

        with self.assertRaises(proxy.ProxyFailure) as denied:
            manager.reserve(1)
        self.assertEqual(denied.exception.code, proxy.ERROR_BUDGET_EXHAUSTED)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["countedCredits"], 950)

        self.usage.payload["remainingCredits"] = 980
        with self.assertRaises(proxy.ProxyFailure) as still_denied:
            manager.reserve(1)
        self.assertEqual(
            still_denied.exception.code, proxy.ERROR_BUDGET_EXHAUSTED
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["countedCredits"], 950)

    def test_unsuccessful_direct_usage_payload_fails_closed(self):
        state_path = self.base / "unsuccessful-usage" / "state" / proxy.STATE_FILENAME
        manager = proxy.BudgetManager(state_path=state_path, usage_url=self.usage.url)
        self.usage.payload["success"] = False
        with self.assertRaises(proxy.ProxyFailure) as failure:
            manager.status()
        self.assertEqual(failure.exception.code, proxy.ERROR_BUDGET_UNAVAILABLE)

    def test_proxy_exits_when_child_exits_while_client_stdin_is_open(self):
        client = self.client(
            child_source='''
            import sys
            print("child-exited", file=sys.stderr, flush=True)
            '''
        )
        client.process.wait(timeout=3)
        self.assertEqual(client.process.returncode, 0)
        _stdout, stderr = client.close()
        self.assertIn("child-exited", stderr)

    def test_fail_closed_states_and_api_fail_before_child_execution(self):
        scenarios = ("corrupt", "oversized", "symlink", "rollback", "api", "account")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                case_base = self.base / scenario
                case_base.mkdir()
                usage = UsageService()
                self.addCleanup(usage.close)
                client = ProxyProcess(case_base, usage)
                self.clients.append(client)
                state_path = client.state_path
                state_path.parent.mkdir(parents=True, exist_ok=True)
                expected = proxy.ERROR_BUDGET_UNAVAILABLE
                if scenario == "corrupt":
                    state_path.write_text("{not-json", encoding="utf-8")
                    state_path.chmod(0o600)
                elif scenario == "oversized":
                    state_path.write_bytes(b"x" * (proxy.MAX_STATE_BYTES + 1))
                    state_path.chmod(0o600)
                elif scenario == "symlink":
                    target = case_base / "target-state"
                    target.write_text("{}", encoding="utf-8")
                    state_path.symlink_to(target)
                elif scenario == "rollback":
                    self.write_state(
                        state_path,
                        counted=1,
                        period={
                            "billingPeriodStart": "2026-09-01T00:00:00Z",
                            "billingPeriodEnd": "2026-10-01T00:00:00Z",
                        },
                    )
                elif scenario == "api":
                    usage.status_code = 503
                elif scenario == "account":
                    usage.payload["planCredits"] = 1
                    usage.payload["remainingCredits"] = 1
                    expected = proxy.ERROR_BUDGET_EXHAUSTED

                response = client.request(
                    "tools/call",
                    {
                        "name": "firecrawl_search",
                        "arguments": {"query": "bounded", "limit": 1},
                    },
                )
                self.assert_tool_failure(response, expected)
                self.assertFalse(
                    any(record.get("method") == "tools/call" for record in client.records())
                )

    def test_period_rollback_and_bad_permissions_fail_closed(self):
        for scenario in ("rollback", "permissions", "lock-symlink"):
            with self.subTest(scenario=scenario):
                state_path = self.base / f"direct-{scenario}" / "state" / proxy.STATE_FILENAME
                if scenario == "rollback":
                    self.write_state(
                        state_path,
                        counted=10,
                        period={
                            "billingPeriodStart": "2026-09-01T00:00:00Z",
                            "billingPeriodEnd": "2026-10-01T00:00:00Z",
                        },
                    )
                elif scenario == "permissions":
                    self.write_state(state_path, counted=10, mode=0o644)
                else:
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    target = state_path.parent / "lock-target"
                    target.write_text("", encoding="utf-8")
                    state_path.with_name(state_path.name + ".lock").symlink_to(target)
                manager = proxy.BudgetManager(state_path=state_path, usage_url=self.usage.url)
                with self.assertRaises(proxy.ProxyFailure) as caught:
                    manager.status()
                self.assertEqual(caught.exception.code, proxy.ERROR_BUDGET_UNAVAILABLE)

    def test_lock_failure_and_every_persisted_state_field_fail_closed(self):
        state_path = self.base / "strict-state" / "state" / proxy.STATE_FILENAME
        self.write_state(state_path, counted=10)
        manager = proxy.BudgetManager(state_path=state_path, usage_url=self.usage.url)
        with mock.patch.object(proxy.fcntl, "flock", side_effect=OSError("lock failed")):
            with self.assertRaises(proxy.ProxyFailure) as caught:
                manager.status()
        self.assertEqual(caught.exception.code, proxy.ERROR_BUDGET_UNAVAILABLE)

        malformed_values = {
            "accountRemainingCredits": 999,
            "updatedAt": "not-a-timestamp",
            "countedCredits": -1,
            "accountPlanCredits": proxy.MAX_CREDIT_VALUE + 1,
        }
        for field, value in malformed_values.items():
            with self.subTest(field=field):
                self.write_state(state_path, counted=10)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state[field] = value
                state_path.write_text(json.dumps(state), encoding="utf-8")
                state_path.chmod(0o600)
                with self.assertRaises(proxy.ProxyFailure) as malformed:
                    manager.status()
                self.assertEqual(
                    malformed.exception.code, proxy.ERROR_BUDGET_UNAVAILABLE
                )

        self.write_state(state_path, counted=10)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["unknownField"] = True
        state_path.write_text(json.dumps(state), encoding="utf-8")
        state_path.chmod(0o600)
        with self.assertRaises(proxy.ProxyFailure) as unknown:
            manager.status()
        self.assertEqual(unknown.exception.code, proxy.ERROR_BUDGET_UNAVAILABLE)

    def test_launcher_and_manifest_use_the_bundled_proxy(self):
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
        self.assertTrue(os.access(LAUNCHER_PATH, os.X_OK))
        for expected in (
            "firecrawl.env",
            "[ ! -f \"$secret_file\" ] || [ -L \"$secret_file\" ]",
            '"$file_mode" != "600"',
            "firecrawl_budget_proxy.py",
            '"$operation" = "status"',
        ):
            self.assertIn(expected, launcher)

        mcp = json.loads(
            (ROOT / "plugins/web-data-tools/.mcp.json").read_text(encoding="utf-8")
        )["mcpServers"]["firecrawl"]
        self.assertEqual(mcp["command"], "/bin/sh")
        self.assertEqual(mcp["args"], ["scripts/run-firecrawl-mcp.sh", "serve"])
        self.assertEqual(mcp["cwd"], ".")
        self.assertNotIn("npx", json.dumps(mcp))


if __name__ == "__main__":
    unittest.main()
