import importlib.util
import json
import os
import pty
import select
import signal
import stat
import subprocess
import sys
import tempfile
import termios
import textwrap
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
SKILL_FILE = REPO_ROOT / "plugins/web-data-tools/skills/wechat-digest/SKILL.md"
PLUGIN_FILE = REPO_ROOT / "plugins/web-data-tools/.codex-plugin/plugin.json"
TRANSPORT = (
    REPO_ROOT
    / "plugins/web-data-tools/skills/wechat-digest/scripts/sites_source_transport.py"
)
PROJECT_ID = "appgprj_fixture"
REMOTE_URL = "https://git.chatgpt-team.site/fixture-repository/appgprj_fixture.git"
LOCAL_SHA = "1" * 40
SYNTHETIC_TOKEN = "synthetic-" + ("x" * 48)
READINESS_EVENT = {"event": "credential_input_ready"}
READINESS_LINE = json.dumps(READINESS_EVENT, separators=(",", ":")) + "\n"


FAKE_GIT_SOURCE = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

base = Path(__file__).parent
config_path = base / "fake-git-config.json"
log_path = base / "fake-git-log.jsonl"
config = json.loads(config_path.read_text(encoding="utf-8"))
args = sys.argv[1:]
record = {
    "argv": args,
    "env": dict(sorted(os.environ.items())),
}
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True) + "\n")

def emit(value):
    if isinstance(value, list):
        for item in value:
            print(item)
    elif value:
        print(value)

if args == ["rev-parse", "--show-toplevel"]:
    emit(config.get("top_level", config["root"]))
elif args == ["rev-parse", "--is-inside-work-tree"]:
    emit(config.get("inside_work_tree", "true"))
elif args == ["symbolic-ref", "-q", "HEAD"]:
    if config.get("detached"):
        raise SystemExit(1)
    symbolic_refs = config.get("symbolic_refs")
    if symbolic_refs:
        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        call_count = sum(
            record["argv"] == ["symbolic-ref", "-q", "HEAD"]
            for record in records
        )
        emit(symbolic_refs[min(call_count - 1, len(symbolic_refs) - 1)])
    else:
        emit(config.get("symbolic_ref", "refs/heads/main"))
elif args == ["rev-parse", "--verify", "HEAD^{commit}"]:
    emit(config.get("local_sha", "1" * 40))
elif args == ["remote", "get-url", "--all", "sites"]:
    emit(config.get("fetch_urls", [config["remote_url"]]))
elif args == ["remote", "get-url", "--push", "--all", "sites"]:
    emit(config.get("push_urls", [config["remote_url"]]))
elif args == ["status", "--porcelain=v1", "--untracked-files=normal"]:
    emit(config.get("status", ""))
elif args and args[0] == "push":
    if config.get("push_failure"):
        print(os.environ.get("GIT_CONFIG_VALUE_0", ""), file=sys.stderr)
        raise SystemExit(1)
    emit("push accepted")
elif args and args[0] == "ls-remote":
    mode = config.get("readback_mode", "exact")
    if mode == "failure":
        print(os.environ.get("GIT_CONFIG_VALUE_0", ""), file=sys.stderr)
        raise SystemExit(2)
    if mode == "multiple":
        print(config.get("remote_sha", config["local_sha"]) + "\trefs/heads/main")
        print(("2" * 40) + "\trefs/heads/main")
    elif mode == "malformed":
        print("not-a-sha\trefs/heads/main")
    elif mode == "wrong-ref":
        print(config.get("remote_sha", config["local_sha"]) + "\trefs/heads/other")
    elif mode == "empty":
        pass
    else:
        print(config.get("remote_sha", config["local_sha"]) + "\trefs/heads/main")
else:
    print("unexpected fake git invocation", file=sys.stderr)
    raise SystemExit(91)
"""


class TransportFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "info-site"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.fake_git = self.base / "fake git; transport"
        self.fake_git.write_text(
            FAKE_GIT_SOURCE.replace("#!/usr/bin/env python3", "#!" + sys.executable),
            encoding="utf-8",
        )
        self.fake_git.chmod(0o700)
        self.config_path = self.base / "fake-git-config.json"
        self.log_path = self.base / "fake-git-log.jsonl"
        self.runner = self.base / "transport-runner.py"
        self.config = {
            "root": str(self.root),
            "remote_url": REMOTE_URL,
            "local_sha": LOCAL_SHA,
            "remote_sha": LOCAL_SHA,
        }
        self.write_config()
        self.write_runner(self.root)

    def cleanup(self):
        self.temp.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def write_runner(self, runtime_root):
        source = f"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("sites_source_transport", {str(TRANSPORT)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
boundary = module.Boundary(
    root=Path({str(runtime_root)!r}),
    project_id={PROJECT_ID!r},
    remote_url={REMOTE_URL!r},
)
runtime = module.Runtime(
    root=Path({str(runtime_root)!r}),
    git_executable={str(self.fake_git)!r},
)
raise SystemExit(module.main(sys.argv, runtime=runtime, boundary=boundary))
"""
        self.runner.write_text(textwrap.dedent(source), encoding="utf-8")

    def credential(self, **overrides):
        value = {
            "app_repository_id": "repo_fixture",
            "provider": "cloudflare_artifact",
            "repository": PROJECT_ID,
            "branch": "main",
            "remote_url": REMOTE_URL,
            "auth_mode": "http_extra_header",
            "token": SYNTHETIC_TOKEN,
            "token_expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat().replace("+00:00", "Z"),
        }
        value.update(overrides)
        return value

    def records(self):
        if not self.log_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def clear_records(self):
        self.log_path.unlink(missing_ok=True)

    def run_tty(
        self,
        operation,
        credential=None,
        *,
        cwd=None,
        env=None,
        extra_args=(),
        raw_credential=False,
    ):
        credential = self.credential() if credential is None else credential
        master_fd, slave_fd = pty.openpty()
        process_env = os.environ.copy()
        process_env["PWD"] = str(cwd or self.root)
        if env:
            process_env.update(env)
        process = subprocess.Popen(
            [
                sys.executable,
                str(self.runner),
                operation,
                *extra_args,
            ],
            cwd=cwd or self.root,
            env=process_env,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        readiness = b""
        readiness_line = None
        echo_disabled_when_ready = False
        credential_bytes_sent = 0
        credential_bytes_sent_before_readiness = None
        credential_sent_after_readiness = False
        timed_out = False
        try:
            deadline = time.monotonic() + 5
            while (
                time.monotonic() < deadline
                and process.poll() is None
                and b"\n" not in readiness
            ):
                remaining = max(0, deadline - time.monotonic())
                readable, _, _ = select.select(
                    [process.stdout],
                    [],
                    [],
                    min(0.05, remaining),
                )
                if readable:
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    readiness += chunk
            if b"\n" in readiness:
                readiness_line = readiness.split(b"\n", 1)[0] + b"\n"
                credential_bytes_sent_before_readiness = credential_bytes_sent
                attributes = termios.tcgetattr(slave_fd)
                echo_disabled_when_ready = not (
                    attributes[3] & (termios.ECHO | termios.ECHONL)
                )
                if (
                    readiness_line == READINESS_LINE.encode("utf-8")
                    and echo_disabled_when_ready
                ):
                    payload_text = (
                        credential
                        if raw_credential
                        else json.dumps(credential, separators=(",", ":"))
                    )
                    payload = payload_text.encode("utf-8") + b"\n"
                    offset = 0
                    while offset < len(payload):
                        written = os.write(master_fd, payload[offset:])
                        offset += written
                        credential_bytes_sent += written
                    credential_sent_after_readiness = True
                else:
                    process.kill()
            elif process.poll() is None:
                timed_out = True
                process.kill()
            stdout, stderr = process.communicate(timeout=10)
        except Exception:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
            raise
        finally:
            os.close(master_fd)
            os.close(slave_fd)
        result = subprocess.CompletedProcess(
            process.args,
            process.returncode,
            (readiness + stdout).decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
        result.readiness_line = (
            None
            if readiness_line is None
            else readiness_line.decode("utf-8", errors="replace")
        )
        result.echo_disabled_when_ready = echo_disabled_when_ready
        result.credential_bytes_sent_before_readiness = (
            credential_bytes_sent_before_readiness
        )
        result.credential_sent_after_readiness = credential_sent_after_readiness
        result.timed_out = timed_out
        return result

    def run_tty_without_input(self, operation, *, cwd=None, env=None):
        master_fd, slave_fd = pty.openpty()
        process_env = os.environ.copy()
        process_env["PWD"] = str(cwd or self.root)
        if env:
            process_env.update(env)
        process = subprocess.Popen(
            [
                sys.executable,
                str(self.runner),
                operation,
            ],
            cwd=cwd or self.root,
            env=process_env,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        timed_out = False
        try:
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
        finally:
            os.close(master_fd)
            os.close(slave_fd)
        result = subprocess.CompletedProcess(
            process.args,
            process.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
        result.timed_out = timed_out
        return result

    def run_tty_interrupt_after_readiness(self, operation):
        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            [
                sys.executable,
                str(self.runner),
                operation,
            ],
            cwd=self.root,
            env=os.environ.copy(),
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            readiness = process.stdout.readline()
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
        finally:
            os.close(master_fd)
            os.close(slave_fd)
        return subprocess.CompletedProcess(
            process.args,
            process.returncode,
            (readiness + stdout).decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    def run_pipe(self, operation, credential=None, *, cwd=None, env=None, extra_args=()):
        credential = self.credential() if credential is None else credential
        process_env = os.environ.copy()
        process_env["PWD"] = str(cwd or self.root)
        if env:
            process_env.update(env)
        return subprocess.run(
            [
                sys.executable,
                str(self.runner),
                operation,
                *extra_args,
            ],
            cwd=cwd or self.root,
            env=process_env,
            input=json.dumps(credential) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )


class SitesSourceTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = TransportFixture()

    def tearDown(self):
        self.fixture.cleanup()

    def assert_error(self, result, code, *, ready=False):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, READINESS_LINE if ready else "")
        error = json.loads(result.stderr)
        self.assertEqual(error["error"], code)
        self.assertEqual(set(error), {"error", "message"})
        self.assertNotIn(SYNTHETIC_TOKEN, result.stdout + result.stderr)
        self.assertNotIn("Authorization: Bearer", result.stdout + result.stderr)
        return error

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0] + "\n", READINESS_LINE)
        self.assertEqual(json.loads(lines[0]), READINESS_EVENT)
        receipt = json.loads(lines[1])
        self.assertEqual(
            set(receipt),
            {"operation", "local_sha", "remote_sha", "exact"},
        )
        self.assertNotIn(SYNTHETIC_TOKEN, result.stdout + result.stderr)
        return receipt

    def test_transport_exists_is_executable_and_has_only_two_operations(self):
        self.assertTrue(TRANSPORT.is_file())
        self.assertTrue(TRANSPORT.stat().st_mode & stat.S_IXUSR)

        unknown = self.fixture.run_pipe("status")
        self.assert_error(unknown, "INVALID_OPERATION")
        extra = self.fixture.run_pipe("push", extra_args=("credential-value",))
        self.assert_error(extra, "INVALID_ARGUMENTS")
        self.assertEqual(self.fixture.records(), [])

    def test_skill_documents_the_bound_tool_controlled_transport(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        self.assertIn("## Pinned Sites Source Transport", text)
        for clause in (
            "sites-source-transport.json",
            "project_root",
            "project_id",
            "remote_url",
            "mode `600`",
            "owner-only digest Sites source",
            "sites_source_transport.py push",
            "sites_source_transport.py readback",
            "tool-controlled non-echoed stdin",
            READINESS_LINE.strip(),
            "send nothing before",
            "terminal echo is already disabled",
            "one fresh credential JSON line",
            "shell `echo`",
            "command interpolation",
            "credential files",
            "logs",
        ):
            self.assertIn(clause, text, clause)
        self.assertIn("Do not", text)
        self.assertNotIn("/" + "Users" + "/", text)
        self.assertNotIn(SYNTHETIC_TOKEN, text)

        plugin = json.loads(PLUGIN_FILE.read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], "0.3.3")

    def test_boundary_config_is_private_strict_and_fail_closed(self):
        spec = importlib.util.spec_from_file_location(
            "sites_source_transport_config_test",
            TRANSPORT,
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        secrets_dir = self.fixture.base / "secrets"
        secrets_dir.mkdir(mode=0o700)
        environment = {"CODEX_SECRETS_DIR": str(secrets_dir)}
        config_path = secrets_dir / "sites-source-transport.json"

        with self.assertRaises(module.TransportError) as missing:
            module._load_boundary_config(environment)
        self.assertEqual(missing.exception.code, "BOUNDARY_CONFIG_MISSING")

        config_path.write_text(
            json.dumps(
                {
                    "project_root": str(self.fixture.root),
                    "project_id": PROJECT_ID,
                    "remote_url": REMOTE_URL,
                }
            ),
            encoding="utf-8",
        )
        config_path.chmod(0o644)
        with self.assertRaises(module.TransportError) as unsafe:
            module._load_boundary_config(environment)
        self.assertEqual(unsafe.exception.code, "BOUNDARY_CONFIG_UNSAFE")

        config_path.chmod(0o600)
        boundary = module._load_boundary_config(environment)
        self.assertEqual(boundary.root, self.fixture.root)
        self.assertEqual(boundary.project_id, PROJECT_ID)
        self.assertEqual(boundary.remote_url, REMOTE_URL)

        config_path.write_text(
            json.dumps(
                {
                    "project_root": str(self.fixture.root),
                    "project_id": PROJECT_ID,
                    "remote_url": REMOTE_URL,
                    "token": SYNTHETIC_TOKEN,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(module.TransportError) as invalid:
            module._load_boundary_config(environment)
        self.assertEqual(invalid.exception.code, "BOUNDARY_CONFIG_INVALID")

    def test_push_uses_exact_nonforce_refspec_and_redacted_receipt(self):
        result = self.fixture.run_tty("push")

        receipt = self.assert_success(result)
        self.assertEqual(receipt, {
            "operation": "push",
            "local_sha": LOCAL_SHA,
            "remote_sha": LOCAL_SHA,
            "exact": True,
        })
        self.assertNotIn(SYNTHETIC_TOKEN, result.stdout + result.stderr)
        records = self.fixture.records()
        pushes = [record for record in records if record["argv"][:1] == ["push"]]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(
            pushes[0]["argv"],
            [
                "push",
                "--porcelain",
                "--no-verify",
                REMOTE_URL,
                "HEAD:refs/heads/main",
            ],
        )
        joined = "\n".join(" ".join(record["argv"]) for record in records)
        self.assertNotIn("--force", joined)
        self.assertNotIn("--force-with-lease", joined)
        self.assertNotIn("+HEAD", joined)
        self.assertNotIn(SYNTHETIC_TOKEN, joined)
        self.assertNotIn("http.extraHeader", joined)

    def test_network_git_environment_is_minimal_and_disables_hooks_and_prompts(self):
        inherited = {
            "GIT_TRACE": "/tmp/trace",
            "GIT_TRACE_CURL": "1",
            "GIT_CONFIG_COUNT": "99",
            "GIT_CONFIG_PARAMETERS": "'malicious.key'='malicious-value'",
            "GIT_CONFIG_VALUE_0": "malicious-value",
            "GIT_ASKPASS": "/tmp/askpass",
            "SSH_ASKPASS": "/tmp/ssh-askpass",
            "HTTP_PROXY": "http://proxy.invalid",
            "HTTPS_PROXY": "http://proxy.invalid",
            "ALL_PROXY": "socks5://proxy.invalid",
            "NO_PROXY": "*",
            "http_proxy": "http://proxy.invalid",
            "https_proxy": "http://proxy.invalid",
        }
        result = self.fixture.run_tty("push", env=inherited)
        self.assert_success(result)

        network = [
            record
            for record in self.fixture.records()
            if record["argv"][:1] in (["push"], ["ls-remote"])
        ]
        self.assertEqual(len(network), 2)
        for record in network:
            env = record["env"]
            self.assertEqual(env["GIT_CONFIG_COUNT"], "4")
            self.assertEqual(env["GIT_CONFIG_KEY_0"], "http.extraHeader")
            self.assertEqual(
                env["GIT_CONFIG_VALUE_0"],
                "Authorization: Bearer " + SYNTHETIC_TOKEN,
            )
            self.assertEqual(env["GIT_CONFIG_KEY_1"], "core.hooksPath")
            self.assertEqual(env["GIT_CONFIG_VALUE_1"], "/dev/null")
            self.assertEqual(env["GIT_CONFIG_KEY_2"], "credential.helper")
            self.assertEqual(env["GIT_CONFIG_VALUE_2"], "")
            self.assertEqual(env["GIT_CONFIG_KEY_3"], "http.proxy")
            self.assertEqual(env["GIT_CONFIG_VALUE_3"], "")
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")
            self.assertEqual(env["GIT_CONFIG_SYSTEM"], "/dev/null")
            self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertNotIn("GIT_CONFIG_PARAMETERS", env)
            for forbidden in inherited:
                if forbidden.startswith("GIT_CONFIG_"):
                    continue
                self.assertNotIn(forbidden, env)

    def test_readback_never_mutates_remote_and_compares_exact_head(self):
        self.fixture.config["status"] = " M ignored-for-readback.txt"
        self.fixture.write_config()

        result = self.fixture.run_tty("readback")

        self.assertEqual(self.assert_success(result)["operation"], "readback")
        records = self.fixture.records()
        self.assertFalse(any(record["argv"][:1] == ["push"] for record in records))
        readbacks = [record for record in records if record["argv"][:1] == ["ls-remote"]]
        self.assertEqual(len(readbacks), 1)
        self.assertEqual(
            readbacks[0]["argv"],
            [
                "ls-remote",
                "--heads",
                "--exit-code",
                REMOTE_URL,
                "refs/heads/main",
            ],
        )
        self.assertFalse(any(record["argv"][:1] == ["status"] for record in records))

    def test_push_rejects_dirty_worktree_before_credential_or_network(self):
        self.fixture.config["status"] = " M content/status.json"
        self.fixture.write_config()

        result = self.fixture.run_pipe("push")

        self.assert_error(result, "DIRTY_WORKTREE")
        records = self.fixture.records()
        self.assertFalse(any(record["argv"][:1] in (["push"], ["ls-remote"]) for record in records))

    def test_requires_non_echoed_tty_stdin_and_rejects_credential_environment(self):
        piped = self.fixture.run_pipe("readback")
        self.assert_error(piped, "STDIN_TTY_REQUIRED")

        for name in (
            "SITES_SOURCE_TOKEN",
            "SITES_SOURCE_CREDENTIAL",
            "SOURCE_REPOSITORY_TOKEN",
            "SOURCE_REPOSITORY_CREDENTIAL",
            "AUTHORIZATION",
        ):
            with self.subTest(name=name):
                result = self.fixture.run_pipe(
                    "readback",
                    env={name: SYNTHETIC_TOKEN},
                )
                self.assert_error(result, "CREDENTIAL_ENV_FORBIDDEN")

    def test_rejects_generic_credential_environment_before_tty_input_or_git(self):
        result = self.fixture.run_tty_without_input(
            "readback",
            env={"TOKEN": SYNTHETIC_TOKEN},
        )

        self.assertFalse(result.timed_out)
        self.assert_error(result, "CREDENTIAL_ENV_FORBIDDEN")
        self.assertEqual(self.fixture.records(), [])

        for name, value in (
            ("MY_AUTH", SYNTHETIC_TOKEN),
            ("MY_OAUTH", SYNTHETIC_TOKEN),
            ("MY_CRED", SYNTHETIC_TOKEN),
            ("MY_CREDENTIAL", SYNTHETIC_TOKEN),
            ("MY_PASS", SYNTHETIC_TOKEN),
            ("MY_PASSWORD", SYNTHETIC_TOKEN),
            ("MY_PASSWD", SYNTHETIC_TOKEN),
            ("MY_JWT", SYNTHETIC_TOKEN),
            ("MY_COOKIE", SYNTHETIC_TOKEN),
            ("MY_SESSION", SYNTHETIC_TOKEN),
            ("token", SYNTHETIC_TOKEN),
            ("MY_TOKEN_VALUE", SYNTHETIC_TOKEN),
            ("repo_Credential", SYNTHETIC_TOKEN),
            ("authorization", SYNTHETIC_TOKEN),
            ("BEARER", SYNTHETIC_TOKEN),
            ("TOKEN", ""),
            ("SITES_SECRET", ""),
            ("GH_PAT", SYNTHETIC_TOKEN),
            ("APIKEY", SYNTHETIC_TOKEN),
            ("MY_API_KEY", SYNTHETIC_TOKEN),
            ("MY_ACCESS_KEY", SYNTHETIC_TOKEN),
            ("MY_PRIVATE_KEY", SYNTHETIC_TOKEN),
            ("MY_CLIENT_SECRET", SYNTHETIC_TOKEN),
            ("MY_SIGNING_KEY", SYNTHETIC_TOKEN),
            ("MY_KEY", SYNTHETIC_TOKEN),
            ("ssh_auth_sock", SYNTHETIC_TOKEN),
        ):
            with self.subTest(name=name):
                result = self.fixture.run_pipe(
                    "readback",
                    env={name: value},
                )
                self.assert_error(result, "CREDENTIAL_ENV_FORBIDDEN")

        for name, value in (
            ("SSH_AUTH_SOCK", "/tmp/safe-test-agent.sock"),
            ("TOKENIZERS_PARALLELISM", "false"),
            ("CODEX_SECRETS_DIR", "/tmp/safe-test-secrets"),
            ("NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S", "fixture-sha256"),
            ("PATTERN_CACHE", "/tmp/safe-pattern-cache"),
        ):
            with self.subTest(safe_name=name):
                safe = self.fixture.run_pipe(
                    "readback",
                    env={name: value},
                )
                self.assert_error(safe, "STDIN_TTY_REQUIRED")

    def test_rejects_boundary_auth_on_tty_before_readiness_or_git(self):
        result = self.fixture.run_tty_without_input(
            "readback",
            env={"MY_AUTH": SYNTHETIC_TOKEN},
        )

        self.assertFalse(result.timed_out)
        self.assert_error(result, "CREDENTIAL_ENV_FORBIDDEN")
        self.assertEqual(self.fixture.records(), [])

    def test_rejects_credential_token_in_ambient_value_before_network(self):
        ambient_values = (
            SYNTHETIC_TOKEN,
            "prefix-" + SYNTHETIC_TOKEN + "-suffix",
        )
        for value in ambient_values:
            with self.subTest(wrapped=value != SYNTHETIC_TOKEN):
                self.fixture.clear_records()

                result = self.fixture.run_tty(
                    "push",
                    env={"UNRELATED_NAME": value},
                )

                self.assert_error(result, "CREDENTIAL_ENV_FORBIDDEN", ready=True)
                self.assertFalse(
                    any(
                        record["argv"][:1] in (["push"], ["ls-remote"])
                        for record in self.fixture.records()
                    )
                )

    def test_rejects_non_main_branch_before_credential_or_network(self):
        expected_commands = [
            ["rev-parse", "--show-toplevel"],
            ["rev-parse", "--is-inside-work-tree"],
            ["symbolic-ref", "-q", "HEAD"],
        ]
        for operation in ("push", "readback"):
            with self.subTest(operation=operation):
                self.fixture.clear_records()
                self.fixture.config["symbolic_ref"] = (
                    "refs/heads/feature/daily-wechat-digest"
                )
                self.fixture.write_config()

                result = self.fixture.run_pipe(operation)

                error = self.assert_error(result, "LOCAL_BRANCH_MISMATCH")
                self.assertEqual(
                    error["message"],
                    "Local branch must be refs/heads/main.",
                )
                self.assertEqual(
                    [record["argv"] for record in self.fixture.records()],
                    expected_commands,
                )

    def test_branch_change_after_readiness_fails_before_network(self):
        for operation in ("push", "readback"):
            with self.subTest(operation=operation):
                self.fixture.clear_records()
                self.fixture.config["symbolic_refs"] = [
                    "refs/heads/main",
                    "refs/heads/feature/raced-checkout",
                ]
                self.fixture.write_config()

                result = self.fixture.run_tty(operation)

                self.assert_error(result, "LOCAL_STATE_CHANGED", ready=True)
                records = self.fixture.records()
                self.assertEqual(
                    sum(
                        record["argv"] == ["symbolic-ref", "-q", "HEAD"]
                        for record in records
                    ),
                    2,
                )
                self.assertFalse(
                    any(
                        record["argv"][:1] in (["push"], ["ls-remote"])
                        for record in records
                    )
                )

    def test_branch_change_after_network_fails_final_stability_check(self):
        expected_network_calls = {"push": 2, "readback": 1}
        for operation in ("push", "readback"):
            with self.subTest(operation=operation):
                self.fixture.clear_records()
                self.fixture.config["symbolic_refs"] = [
                    "refs/heads/main",
                    "refs/heads/main",
                    "refs/heads/feature/raced-checkout",
                ]
                self.fixture.write_config()

                result = self.fixture.run_tty(operation)

                self.assert_error(result, "LOCAL_STATE_CHANGED", ready=True)
                records = self.fixture.records()
                self.assertEqual(
                    sum(
                        record["argv"] == ["symbolic-ref", "-q", "HEAD"]
                        for record in records
                    ),
                    3,
                )
                self.assertEqual(
                    sum(
                        record["argv"][:1] in (["push"], ["ls-remote"])
                        for record in records
                    ),
                    expected_network_calls[operation],
                )

    def test_emits_exact_readiness_after_echo_off_before_credential_input(self):
        result = self.fixture.run_tty("readback")

        receipt = self.assert_success(result)
        self.assertEqual(result.readiness_line, READINESS_LINE)
        self.assertTrue(result.echo_disabled_when_ready)
        self.assertEqual(result.credential_bytes_sent_before_readiness, 0)
        self.assertTrue(result.credential_sent_after_readiness)
        self.assertFalse(result.timed_out)
        self.assertEqual(receipt["operation"], "readback")
        self.assertEqual(json.loads(result.stdout.splitlines()[0]), READINESS_EVENT)

    def test_interrupt_after_readiness_is_bounded_and_redacted(self):
        result = self.fixture.run_tty_interrupt_after_readiness("readback")

        self.assertEqual(result.returncode, 130)
        self.assertEqual(result.stdout, READINESS_LINE)
        error = json.loads(result.stderr)
        self.assertEqual(error["error"], "INTERRUPTED")
        self.assertEqual(set(error), {"error", "message"})
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn(str(self.fixture.root), result.stderr)

    def test_rejects_wrong_working_directory_and_symlink_runtime_root(self):
        other = self.fixture.base / "other"
        other.mkdir()
        wrong = self.fixture.run_pipe("readback", cwd=other)
        self.assert_error(wrong, "WORKING_DIRECTORY_MISMATCH")

        link = self.fixture.base / "linked-info-site"
        link.symlink_to(self.fixture.root, target_is_directory=True)
        self.fixture.write_runner(link)
        linked = self.fixture.run_pipe("readback", cwd=link)
        self.assert_error(linked, "ROOT_PATH_UNSAFE")

    def test_rejects_malformed_detached_or_mismatched_local_git_state(self):
        cases = (
            ("inside_work_tree", "false", "NOT_A_WORKTREE"),
            ("detached", True, "DETACHED_HEAD"),
            ("symbolic_ref", "unsafe", "MALFORMED_HEAD_REF"),
            ("local_sha", "not-a-sha", "MALFORMED_LOCAL_SHA"),
            ("top_level", str(self.fixture.base), "GIT_TOPLEVEL_MISMATCH"),
        )
        for key, value, expected in cases:
            with self.subTest(key=key):
                self.fixture.config[key] = value
                self.fixture.write_config()
                result = self.fixture.run_pipe("readback")
                self.assert_error(result, expected)
                self.fixture.config = {
                    "root": str(self.fixture.root),
                    "remote_url": REMOTE_URL,
                    "local_sha": LOCAL_SHA,
                    "remote_sha": LOCAL_SHA,
                }
                self.fixture.write_config()

    def test_rejects_missing_ambiguous_or_mismatched_bound_remote(self):
        cases = (
            ("fetch_urls", [], "REMOTE_MISSING"),
            ("fetch_urls", [REMOTE_URL, REMOTE_URL], "REMOTE_AMBIGUOUS"),
            ("fetch_urls", ["https://example.invalid/repo.git"], "REMOTE_MISMATCH"),
            ("push_urls", [REMOTE_URL, REMOTE_URL], "REMOTE_AMBIGUOUS"),
            ("push_urls", ["https://example.invalid/repo.git"], "REMOTE_MISMATCH"),
        )
        for key, value, expected in cases:
            with self.subTest(key=key):
                self.fixture.config[key] = value
                self.fixture.write_config()
                result = self.fixture.run_pipe("readback")
                self.assert_error(result, expected)
                self.fixture.config.pop(key)
                self.fixture.write_config()

    def test_validates_exact_credential_binding_token_and_expiry_margin(self):
        near_expiry = (
            datetime.now(timezone.utc) + timedelta(seconds=30)
        ).isoformat().replace("+00:00", "Z")
        expired = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat().replace("+00:00", "Z")
        cases = (
            ({"repository": "other-project"}, "PROJECT_ID_MISMATCH"),
            ({"provider": "other-provider"}, "PROVIDER_MISMATCH"),
            ({"branch": "feature"}, "BRANCH_MISMATCH"),
            ({"remote_url": "https://example.invalid/repo.git"}, "REMOTE_MISMATCH"),
            ({"auth_mode": "url_token"}, "AUTH_MODE_MISMATCH"),
            ({"token": ""}, "INVALID_TOKEN"),
            ({"token": "has whitespace"}, "INVALID_TOKEN"),
            ({"token_expires_at": "not-a-time"}, "INVALID_EXPIRY"),
            ({"token_expires_at": expired}, "CREDENTIAL_EXPIRED"),
            ({"token_expires_at": near_expiry}, "CREDENTIAL_EXPIRING"),
        )
        for override, expected in cases:
            with self.subTest(override=next(iter(override))):
                result = self.fixture.run_tty(
                    "readback",
                    self.fixture.credential(**override),
                )
                self.assert_error(result, expected, ready=True)

        spec = importlib.util.spec_from_file_location(
            "sites_source_transport_boundary_test",
            TRANSPORT,
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        oversized = self.fixture.credential(token="x" * 4097)
        with self.assertRaises(module.TransportError) as raised:
            module._parse_credential(
                json.dumps(oversized),
                datetime.now(timezone.utc),
                module.Boundary(
                    root=self.fixture.root,
                    project_id=PROJECT_ID,
                    remote_url=REMOTE_URL,
                ),
            )
        self.assertEqual(raised.exception.code, "INVALID_TOKEN")

    def test_rejects_malformed_or_nonobject_stdin_without_disclosure(self):
        malformed = self.fixture.run_tty(
            "readback",
            credential="{not-json",
            raw_credential=True,
        )
        self.assert_error(malformed, "INVALID_CREDENTIAL_JSON", ready=True)

        nonobject = self.fixture.run_tty("readback", credential=["not", "an", "object"])
        self.assert_error(nonobject, "INVALID_CREDENTIAL_OBJECT", ready=True)

    def test_rejects_failed_malformed_multiple_or_mismatched_readback_without_raw_output(self):
        cases = (
            ("failure", "GIT_READBACK_FAILED"),
            ("empty", "REMOTE_READBACK_EMPTY"),
            ("multiple", "REMOTE_READBACK_AMBIGUOUS"),
            ("malformed", "REMOTE_READBACK_MALFORMED"),
            ("wrong-ref", "REMOTE_READBACK_MALFORMED"),
        )
        for mode, expected in cases:
            with self.subTest(mode=mode):
                self.fixture.config["readback_mode"] = mode
                self.fixture.write_config()
                result = self.fixture.run_tty("readback")
                self.assert_error(result, expected, ready=True)

        self.fixture.config["readback_mode"] = "exact"
        self.fixture.config["remote_sha"] = "2" * 40
        self.fixture.write_config()
        mismatch = self.fixture.run_tty("readback")
        self.assert_error(mismatch, "REMOTE_SHA_MISMATCH", ready=True)

    def test_push_failure_cannot_expose_header_or_token(self):
        self.fixture.config["push_failure"] = True
        self.fixture.write_config()

        result = self.fixture.run_tty("push")

        self.assert_error(result, "GIT_PUSH_FAILED", ready=True)
        self.assertNotIn("synthetic", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
