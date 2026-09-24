"""Fail-closed native CUA client IPC provenance tests."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/typesafe-tools"))
from computer_use_diagnostic import native_ipc


class FakeProbe:
    def __init__(self) -> None:
        self.birth = "Wed Sep 23 23:47:40 2026"
        self.service_birth = "Wed Sep 23 21:00:00 2026"
        self.commands = {
            101: "/Applications/ChatGPT.app/Contents/Resources/codex exec --json -",
            102: native_ipc._MCP_COMMAND,
            103: native_ipc._REPL_COMMAND,
            104: native_ipc._SERVICE_COMMAND,
        }
        self.parents = {101: 1, 102: 101, 103: 102, 104: 1}
        self.children = {101: "102\n", 102: "103\n"}
        self.services = "104\n"
        self.server_lsof = (
            "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            f"SkyComput 104 user 6u unix 0xbbb 0t0 {native_ipc._SOCKET_PATH}\n"
        )
        self.client_lsof = (
            "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            "node_repl 103 user 26u unix 0xaaa 0t0 ->0xbbb\n"
        )
        self.calls: list[tuple[str, ...]] = []
        self.changed_on_recheck: int | None = None
        self._process_reads: dict[int, int] = {}

    def _line(self, pid: int) -> str:
        birth = self.service_birth if pid == 104 else self.birth
        if self.changed_on_recheck == pid and self._process_reads.get(pid, 0) > 1:
            birth = "Wed Sep 23 23:48:40 2026"
        return f"{pid} {self.parents[pid]} {birth} {self.commands[pid]}\n"

    def __call__(self, argv: tuple[str, ...]) -> str:
        self.calls.append(argv)
        if argv[:3] == ("ps", "-ww", "-p"):
            pid = int(argv[3])
            self._process_reads[pid] = self._process_reads.get(pid, 0) + 1
            return self._line(pid)
        if argv[:2] == ("pgrep", "-P"):
            return self.children[int(argv[2])]
        if argv == ("pgrep", "-f", "SkyComputerUseService"):
            return self.services
        if argv[:5] == ("lsof", "-a", "-nP", "-U", "-p"):
            return self.server_lsof if int(argv[5]) == 104 else self.client_lsof
        raise AssertionError(f"unexpected probe command {argv[0]}")


class NativeIpcAttestationTests(unittest.TestCase):
    def test_live_client_chain_is_hashed_and_not_called_backend_session(self) -> None:
        result = native_ipc.attest_native_client(101, probe=FakeProbe())
        self.assertTrue(result.verified)
        self.assertEqual(result.basis, "native_client_process_ipc")
        self.assertFalse(result.backend_session_id_observed)
        self.assertIsNone(result.reason)
        for value in (result.client_context_sha256, result.client_process_sha256,
                      result.ipc_connection_sha256):
            self.assertIsInstance(value, str)
            self.assertEqual(len(value), 64)
        serialized = json.dumps(asdict(result))
        for raw in ("0xaaa", "0xbbb", "SkyComputerUseService", "node_repl",
                    "codex exec"):
            self.assertNotIn(raw, serialized)

    def test_previous_client_context_is_rejected(self) -> None:
        first = native_ipc.attest_native_client(101, probe=FakeProbe())
        second = native_ipc.attest_native_client(
            101, probe=FakeProbe(), seen_contexts={first.client_context_sha256}
        )
        self.assertFalse(second.verified)
        self.assertEqual(second.reason, "native_client_context_reused")
        self.assertIsNone(second.client_context_sha256)

    def test_missing_or_ambiguous_child_is_unverified(self) -> None:
        for children in ("", "102\n105\n", "102\n102\n"):
            with self.subTest(children=children):
                fake = FakeProbe()
                fake.children[101] = children
                if "105" in children:
                    fake.commands[105] = native_ipc._MCP_COMMAND
                    fake.parents[105] = 101
                result = native_ipc.attest_native_client(101, probe=fake)
                self.assertFalse(result.verified)

    def test_incorrect_ancestry_or_command_is_unverified(self) -> None:
        for mutation in ("parent", "mcp", "codex"):
            with self.subTest(mutation=mutation):
                fake = FakeProbe()
                if mutation == "parent":
                    fake.parents[103] = 1
                elif mutation == "mcp":
                    fake.commands[102] = "/tmp/unrelated-node"
                else:
                    fake.commands[101] = "codex app-server"
                result = native_ipc.attest_native_client(101, probe=fake)
                self.assertFalse(result.verified)

    def test_server_and_client_socket_must_pair_uniquely(self) -> None:
        for client in (
            "node_repl 103 user 26u unix 0xaaa 0t0 ->0xccc\n",
            ("node_repl 103 user 26u unix 0xaaa 0t0 ->0xbbb\n"
             "node_repl 103 user 27u unix 0xddd 0t0 ->0xbbb\n"),
        ):
            with self.subTest(client=client):
                fake = FakeProbe()
                fake.client_lsof = client
                result = native_ipc.attest_native_client(101, probe=fake)
                self.assertFalse(result.verified)
                self.assertEqual(result.reason, "native_client_socket_ambiguous")

    def test_service_socket_and_process_must_be_attributable(self) -> None:
        fake = FakeProbe()
        fake.server_lsof = "SkyComput 104 user 6u unix 0xbbb 0t0 /tmp/other.sock\n"
        result = native_ipc.attest_native_client(101, probe=fake)
        self.assertEqual(result.reason, "native_service_socket_unavailable")

        fake = FakeProbe()
        fake.commands[105] = native_ipc._SERVICE_COMMAND
        fake.parents[105] = 1
        fake.services = "104\n105\n"
        result = native_ipc.attest_native_client(101, probe=fake)
        self.assertEqual(result.reason, "native_service_ambiguous")

    def test_process_replacement_during_probe_is_unverified(self) -> None:
        fake = FakeProbe()
        fake.changed_on_recheck = 103
        result = native_ipc.attest_native_client(101, probe=fake)
        self.assertEqual(result.reason, "process_changed_during_probe")

    def test_os_probe_failure_and_invalid_pid_are_unverified(self) -> None:
        self.assertEqual(native_ipc.attest_native_client(0).reason, "codex_pid_invalid")

        def unavailable(_argv: tuple[str, ...]) -> str:
            raise OSError("do not retain this message")

        result = native_ipc.attest_native_client(101, probe=unavailable)
        self.assertEqual(result.reason, "os_probe_failed")
        self.assertNotIn("do not retain", json.dumps(asdict(result)))


if __name__ == "__main__":
    unittest.main()
