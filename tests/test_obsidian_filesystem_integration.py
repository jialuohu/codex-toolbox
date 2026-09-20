"""Isolated qualification of filesystem MCP baseline and proposed update.

Set OBSIDIAN_FILESYSTEM_INTEGRATION=1 to install both exact public npm versions
in a temporary directory. No configured vault, user note, or global runtime is
read or changed. Client roots replacing the CLI root is a known upstream limit,
not a confinement guarantee; the candidate stays deferred while that limit holds.
"""

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = {"filesystem-baseline": "2026.1.14", "filesystem-candidate": "2026.8.31"}


class FilesystemPolicyTests(unittest.TestCase):
    def test_move_file_remains_disabled_in_the_host_manifest(self):
        manifest = json.loads((ROOT / "plugins/obsidian-tools/.mcp.json").read_text())
        self.assertIn("move_file", manifest["mcpServers"]["obsidian_files"]["disabled_tools"])


class Session:
    def __init__(self, executable, script, allowed, *, roots=None):
        self.roots = roots
        self.messages = queue.Queue()
        self.serial = 0
        self.process = subprocess.Popen(
            [executable, str(script), str(allowed)], cwd=allowed,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, env={"PATH": os.environ.get("PATH", ""), "HOME": str(allowed.parent)},
        )
        self.reader = threading.Thread(target=self.read_messages, daemon=True)
        self.reader.start()
        capabilities = {} if roots is None else {"roots": {"listChanged": True}}
        self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": capabilities,
                                    "clientInfo": {"name": "toolbox-fixture", "version": "1"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def read_messages(self):
        for line in self.process.stdout:
            try:
                self.messages.put(json.loads(line))
            except json.JSONDecodeError:
                self.messages.put({"transport_error": "non-JSON stdout"})
        self.messages.put({"transport_error": "server exited"})

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.serial += 1
        request_id = self.serial
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + 15
        while True:
            message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if "transport_error" in message:
                raise AssertionError(message["transport_error"])
            if message.get("method") == "roots/list":
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": {
                    "roots": [{"uri": path.as_uri(), "name": "fixture"} for path in (self.roots or [])]}})
            elif message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise AssertionError(message["error"])
                return message["result"]

    def call(self, name, **arguments):
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def wait_for_root(self, expected):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.call("list_allowed_directories")
            text = "\n".join(item.get("text", "") for item in result.get("content", []))
            if str(expected) in text:
                return
            time.sleep(0.01)
        raise AssertionError("roots negotiation did not complete")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


@unittest.skipUnless(os.environ.get("OBSIDIAN_FILESYSTEM_INTEGRATION") == "1",
                     "opt-in npm installation into temporary fixtures")
class FilesystemConfinementQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        npm = shutil.which("npm")
        if not cls.node or not npm:
            raise unittest.SkipTest("Node and npm required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="toolbox-filesystem-qualification-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.install = Path(cls.temporary.name).resolve()
        (cls.install / "package.json").write_text(json.dumps({
            "private": True,
            "dependencies": {alias: f"npm:@modelcontextprotocol/server-filesystem@{version}"
                             for alias, version in VERSIONS.items()},
        }))
        completed = subprocess.run(
            [npm, "install", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=cls.install, capture_output=True, text=True, timeout=120,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(cls.install),
                 "npm_config_userconfig": os.devnull,
                 "npm_config_registry": "https://registry.npmjs.org/", "CI": "true"},
        )
        if completed.returncode:
            raise RuntimeError("Pinned filesystem qualification installation failed")
        for alias, version in VERSIONS.items():
            package = json.loads((cls.install / "node_modules" / alias / "package.json").read_text())
            if package["version"] != version:
                raise AssertionError("Installed filesystem version differs from qualification pin")

    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="toolbox-vault-fixture-")
        self.addCleanup(self.fixture.cleanup)
        self.base = Path(self.fixture.name).resolve()
        self.allowed = self.base / "allowed"
        self.allowed.mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()
        (self.allowed / "inside.txt").write_text("inside fixture")
        (self.outside / "outside.txt").write_text("outside fixture")
        (self.allowed / "escape").symlink_to(self.outside, target_is_directory=True)

    def session(self, alias, **kwargs):
        session = Session(self.node, self.install / "node_modules" / alias / "dist/index.js",
                          self.allowed, **kwargs)
        self.addCleanup(session.close)
        return session

    def test_cli_root_allows_absolute_relative_reads_and_denies_escape(self):
        for alias in VERSIONS:
            with self.subTest(version=VERSIONS[alias]):
                client = self.session(alias)
                for path in (str(self.allowed / "inside.txt"), "inside.txt"):
                    response = client.call("read_text_file", path=path)
                    self.assertFalse(response.get("isError", False), response)
                    self.assertIn("inside fixture", json.dumps(response))
                for path in (str(self.outside / "outside.txt"), "../outside/outside.txt",
                             str(self.allowed / "escape/outside.txt")):
                    response = client.call("read_text_file", path=path)
                    self.assertTrue(response.get("isError", False), response)
                    self.assertNotIn("outside fixture", json.dumps(response))
                for path in ("../outside/new.txt", str(self.allowed / "escape/new.txt")):
                    self.assertTrue(client.call("write_file", path=path, content="deny").get("isError"))
                self.assertFalse((self.outside / "new.txt").exists())
                client.close()

    def test_client_roots_replace_cli_root_on_both_versions_known_limitation(self):
        for alias in VERSIONS:
            with self.subTest(version=VERSIONS[alias]):
                client = self.session(alias, roots=[self.outside])
                client.wait_for_root(self.outside)
                response = client.call("read_text_file", path=str(self.outside / "outside.txt"))
                self.assertFalse(response.get("isError", False), response)
                self.assertIn("outside fixture", json.dumps(response))
                self.assertTrue(client.call("read_text_file", path=str(self.allowed / "inside.txt")).get("isError"))
                client.roots = [self.allowed]
                client.send({"jsonrpc": "2.0", "method": "notifications/roots/list_changed"})
                client.wait_for_root(self.allowed)
                self.assertTrue(client.call("read_text_file", path=str(self.outside / "outside.txt")).get("isError"))
                client.close()


if __name__ == "__main__":
    unittest.main()
