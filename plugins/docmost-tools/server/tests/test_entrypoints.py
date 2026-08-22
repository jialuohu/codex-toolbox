from __future__ import annotations

import os
import signal

import pytest


def test_package_imports_without_initializing_network_or_browser() -> None:
    from docmost_tools import __version__, server

    assert __version__ == "0.8.0"
    assert callable(server.main)


def test_mcp_main_closes_its_runtime_client_after_stdio_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docmost_tools import server

    class FakeRuntime:
        client = None
        startup_error = None
        closed = False

        def close(self) -> None:
            self.closed = True

    class FakeMcp:
        transport: str | None = None

        def run(self, *, transport: str) -> None:
            self.transport = transport

    runtime = FakeRuntime()
    mcp = FakeMcp()

    def fake_create_server(**_: object) -> FakeMcp:
        return mcp

    monkeypatch.setattr(server, "_runtime_from_environment", lambda: runtime)
    monkeypatch.setattr(server, "create_server", fake_create_server)

    assert server.main() == 0
    assert mcp.transport == "stdio"
    assert runtime.closed is True


def test_sigterm_unwinds_through_runtime_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docmost_tools import server

    class FakeRuntime:
        client = None
        startup_error = None
        closed = False

        def close(self) -> None:
            self.closed = True

    class FakeMcp:
        def run(self, *, transport: str) -> None:
            assert transport == "stdio"
            os.kill(os.getpid(), signal.SIGTERM)

    runtime = FakeRuntime()

    def fake_create_server(**_: object) -> FakeMcp:
        return FakeMcp()

    monkeypatch.setattr(server, "_runtime_from_environment", lambda: runtime)
    monkeypatch.setattr(server, "create_server", fake_create_server)

    assert server.main() == 0
    assert runtime.closed is True
