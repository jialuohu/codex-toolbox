"""One-time browser-session bootstrap contracts for the MCP runtime."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode, OperationResult
from docmost_tools.profile import ProfileBusyError, profile_paths
from docmost_tools.runtime import bootstrap_runtime
from docmost_tools.server import create_server


class FakeContext:
    def __init__(self) -> None:
        self.cookie_urls: list[list[str]] = []
        self.closed = False

    def cookies(self, urls: list[str]) -> list[dict[str, str]]:
        self.cookie_urls.append(urls)
        return [
            {"name": "irrelevant", "value": "ignore"},
            {"name": "authToken", "value": "fixture-session"},
        ]

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.launches: list[tuple[str, bool]] = []

    @property
    def chromium(self) -> FakePlaywright:
        return self

    def __enter__(self) -> FakePlaywright:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def launch_persistent_context(self, profile: str, *, headless: bool) -> FakeContext:
        self.launches.append((profile, headless))
        return self.context


class FakeReadClient:
    def __init__(self, _: DocmostSettings, session_cookie: str) -> None:
        self.session_cookie = session_cookie
        self.version_calls = 0
        self.closed = False

    def version(self) -> OperationResult[object]:
        self.version_calls += 1
        return OperationResult[object].success({})

    def current_user(self) -> OperationResult[object]:
        return OperationResult[object].success({"user": {"id": "u1"}})

    def list_spaces(self, *, limit: int, cursor: str | None = None) -> OperationResult[object]:
        return OperationResult[object].success({"items": [], "limit": limit, "cursor": cursor})

    def close(self) -> None:
        self.closed = True


class RaisingVersionClient(FakeReadClient):
    instance: RaisingVersionClient | None = None

    def __init__(self, settings: DocmostSettings, session_cookie: str) -> None:
        super().__init__(settings, session_cookie)
        type(self).instance = self

    def version(self) -> OperationResult[object]:
        raise RuntimeError("version probe unavailable")


def settings() -> DocmostSettings:
    return DocmostSettings.model_validate({"base_url": "https://docs.example.test"})


def test_bootstrap_opens_profile_once_extracts_only_api_cookie_probes_once_and_closes_browser(
    tmp_path: Path,
) -> None:
    context = FakeContext()
    playwright = FakePlaywright(context)
    runtime = bootstrap_runtime(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: playwright,
        client_factory=FakeReadClient,
    )

    assert runtime.startup_error is None
    assert isinstance(runtime.client, FakeReadClient)
    assert runtime.client.session_cookie == "fixture-session"
    assert runtime.client.version_calls == 1
    assert playwright.launches == [(str(tmp_path / "docmost" / "browser-profile"), True)]
    assert context.cookie_urls == [["https://docs.example.test/api/users/me"]]
    assert context.closed is True
    runtime.close()
    assert runtime.client.closed is True


def test_bootstrap_converts_missing_cookie_to_exact_auth_required_without_client(
    tmp_path: Path,
) -> None:
    context = FakeContext()
    context.cookies = lambda _: []  # type: ignore[method-assign]
    runtime = bootstrap_runtime(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: FakePlaywright(context),
        client_factory=FakeReadClient,
    )

    assert runtime.client is None
    assert runtime.startup_error is not None
    assert runtime.startup_error.code is ErrorCode.AUTH_REQUIRED
    assert runtime.startup_error.message == (
        '"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth" login'
    )
    assert context.closed is True


def test_bootstrap_maps_profile_failures_without_launching_a_browser(tmp_path: Path) -> None:
    context = FakeContext()

    @contextmanager
    def busy_lock(_: object) -> Any:
        raise ProfileBusyError("PROFILE_BUSY: Docmost browser profile is in use")
        yield

    runtime = bootstrap_runtime(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: FakePlaywright(context),
        client_factory=FakeReadClient,
        lock_factory=busy_lock,
    )

    assert runtime.client is None
    assert runtime.startup_error is not None
    assert runtime.startup_error.code is ErrorCode.PROFILE_BUSY
    assert context.closed is False


def test_bootstrap_closes_a_client_when_its_version_probe_raises(tmp_path: Path) -> None:
    RaisingVersionClient.instance = None
    context = FakeContext()
    runtime = bootstrap_runtime(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: FakePlaywright(context),
        client_factory=RaisingVersionClient,
    )

    assert runtime.client is None
    assert runtime.startup_error is not None
    assert runtime.startup_error.code is ErrorCode.UPSTREAM_ERROR
    assert RaisingVersionClient.instance is not None
    assert RaisingVersionClient.instance.closed is True


def test_protocol_tool_calls_never_reopen_the_browser_after_bootstrap(tmp_path: Path) -> None:
    context = FakeContext()
    playwright = FakePlaywright(context)
    runtime = bootstrap_runtime(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: playwright,
        client_factory=FakeReadClient,
    )

    async def exercise() -> None:
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(
            create_server(client=cast(Any, runtime.client), startup_error=runtime.startup_error)
        ) as session:
            current_user = await session.call_tool("get_current_user", {})
            spaces = await session.call_tool("list_spaces", {})
            assert current_user.isError is False
            assert current_user.structuredContent is not None
            assert current_user.structuredContent["ok"] is True
            assert spaces.isError is False
            assert spaces.structuredContent is not None
            assert spaces.structuredContent["ok"] is True

    import anyio

    anyio.run(exercise)

    assert len(playwright.launches) == 1
