from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Error as PlaywrightError

from docmost_tools import auth
from docmost_tools.auth import AuthService
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode
from docmost_tools.profile import profile_paths


class FakePage:
    def __init__(self) -> None:
        self.visits: list[tuple[str, str, float]] = []

    def goto(self, url: str, *, wait_until: str, timeout: float) -> None:
        self.visits.append((url, wait_until, timeout))

    def wait_for_timeout(self, timeout: float) -> None:
        del timeout


class FakeContext:
    def __init__(self, cookies: list[dict[str, Any]]) -> None:
        self._cookies = cookies
        self.pages: list[FakePage] = []
        self.closed = False
        self.cleared_cookies: list[dict[str, str]] = []
        self.cookie_urls: list[list[str]] = []

    def cookies(self, urls: list[str]) -> list[dict[str, Any]]:
        self.cookie_urls.append(urls)
        return self._cookies

    def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True

    def clear_cookies(self, **kwargs: str) -> None:
        self.cleared_cookies.append(kwargs)


class SequencedCookieContext(FakeContext):
    def __init__(self, cookie_sequence: list[list[dict[str, Any]]]) -> None:
        super().__init__([])
        self._cookie_sequence = cookie_sequence
        self._cookie_index = 0

    def cookies(self, urls: list[str]) -> list[dict[str, Any]]:
        self.cookie_urls.append(urls)
        cookie_index = min(self._cookie_index, len(self._cookie_sequence) - 1)
        self._cookie_index += 1
        return self._cookie_sequence[cookie_index]


class FakeChromium:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.launches: list[tuple[str, bool]] = []

    def launch_persistent_context(self, user_data_dir: str, *, headless: bool) -> FakeContext:
        self.launches.append((user_data_dir, headless))
        return self.context


class FakePlaywrightManager:
    def __init__(self, context: FakeContext) -> None:
        self.chromium = FakeChromium(context)
        self.entered = False
        self.exited = False

    def __enter__(self) -> FakePlaywrightManager:
        self.entered = True
        return self

    def __exit__(self, *args: object) -> None:
        self.exited = True


def settings() -> DocmostSettings:
    return DocmostSettings.model_validate({"base_url": "http://127.0.0.1:9321"})


def install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    original_client = httpx.Client
    transport = httpx.MockTransport(handler)

    def client_with_transport(**kwargs: Any) -> httpx.Client:
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(auth.httpx, "Client", client_with_transport)


def test_status_uses_httponly_cookie_for_identity_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = FakeContext([{"name": "authToken", "value": "session-secret", "httpOnly": True}])
    manager = FakePlaywrightManager(context)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/users/me":
            return httpx.Response(
                200,
                json={
                    "data": {"user": {"id": "u-1"}, "workspace": {"id": "w-1"}},
                    "success": True,
                    "status": 200,
                },
            )
        return httpx.Response(
            200,
            json={"data": {"currentVersion": "0.95.0"}, "success": True, "status": 200},
        )

    install_transport(monkeypatch, handler)
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.status()

    assert result.ok is True
    assert result.data == {
        "user": {"id": "u-1"},
        "workspace": {"id": "w-1"},
        "version": {"currentVersion": "0.95.0"},
    }
    assert [request.url.path for request in requests] == ["/api/users/me", "/api/version"]
    assert [request.method for request in requests] == ["POST", "POST"]
    assert [request.content for request in requests] == [b"{}", b"{}"]
    assert all(request.headers["cookie"] == "authToken=session-secret" for request in requests)
    assert manager.chromium.launches == [(str(tmp_path / "docmost" / "browser-profile"), True)]
    assert context.closed is True
    assert manager.exited is True


def test_login_defaults_to_a_headed_context_and_base_login_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = FakeContext([{"name": "authToken", "value": "session-secret", "httpOnly": True}])
    manager = FakePlaywrightManager(context)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/users/me"
        return httpx.Response(
            200,
            json={
                "data": {"user": {"id": "u-1"}, "workspace": {"id": "w-1"}},
                "success": True,
                "status": 200,
            },
        )

    install_transport(monkeypatch, handler)
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.login()

    assert result.ok is True
    assert result.data == {"user": {"id": "u-1"}, "workspace": {"id": "w-1"}}
    assert manager.chromium.launches == [(str(tmp_path / "docmost" / "browser-profile"), False)]
    login_url, wait_until, timeout = context.pages[0].visits[0]
    assert login_url == "http://127.0.0.1:9321/login"
    assert wait_until == "domcontentloaded"
    assert 0 < timeout <= 300000.0
    assert context.closed is True


def test_status_missing_cookie_returns_the_login_recovery_command(tmp_path: Path) -> None:
    context = FakeContext([])
    manager = FakePlaywrightManager(context)
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.status()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED
    assert result.error.message == (
        "Authentication required. Run "
        "`\"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth\" login`."
    )
    assert context.closed is True


def test_status_401_returns_the_login_recovery_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = FakeContext([{"name": "authToken", "value": "session-secret", "httpOnly": True}])
    manager = FakePlaywrightManager(context)
    install_transport(monkeypatch, lambda _: httpx.Response(401, json={"message": "expired"}))
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.status()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED
    assert result.error.message == (
        "Authentication required. Run "
        "`\"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth\" login`."
    )


def test_status_reads_a_cookie_scoped_to_the_identity_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = FakeContext(
        [
            {
                "name": "authToken",
                "value": "api-scoped-session",
                "httpOnly": True,
                "path": "/api",
            }
        ]
    )
    manager = FakePlaywrightManager(context)
    install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": {"user": {}, "workspace": {}}
                if request.url.path.endswith("/me")
                else {"currentVersion": "0.95.0"},
                "success": True,
                "status": 200,
            },
        ),
    )
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.status()

    assert result.ok is True
    assert context.cookie_urls == [["http://127.0.0.1:9321/api/users/me"]]


def test_status_uses_tls_verification_when_no_ca_bundle_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = FakeContext([{"name": "authToken", "value": "session-secret", "httpOnly": True}])
    manager = FakePlaywrightManager(context)
    captured: dict[str, Any] = {}
    original_client = httpx.Client

    def client_with_transport(**kwargs: Any) -> httpx.Client:
        captured.update(kwargs)
        return original_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "data": {"user": {}, "workspace": {}}
                        if request.url.path.endswith("/me")
                        else {"currentVersion": "0.95.0"},
                        "success": True,
                        "status": 200,
                    },
                )
            ),
            **kwargs,
        )

    monkeypatch.setattr(auth.httpx, "Client", client_with_transport)
    result = AuthService(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: manager,
    ).status()

    assert result.ok is True
    assert captured["verify"] is True


def test_status_disables_ambient_httpx_proxy_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = FakeContext([{"name": "authToken", "value": "session-secret", "httpOnly": True}])
    manager = FakePlaywrightManager(context)
    captured: dict[str, Any] = {}
    original_client = httpx.Client

    def client_with_transport(**kwargs: Any) -> httpx.Client:
        captured.update(kwargs)
        return original_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "data": {"user": {}, "workspace": {}}
                        if request.url.path.endswith("/me")
                        else {"currentVersion": "0.95.0"},
                        "success": True,
                        "status": 200,
                    },
                )
            ),
            **kwargs,
        )

    monkeypatch.setattr(auth.httpx, "Client", client_with_transport)
    result = AuthService(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: manager,
    ).status()

    assert result.ok is True
    assert captured["trust_env"] is False


def test_login_replaces_a_stale_cookie_without_closing_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = SequencedCookieContext(
        [
            [{"name": "authToken", "value": "stale-session", "httpOnly": True}],
            [{"name": "authToken", "value": "fresh-session", "httpOnly": True}],
        ]
    )
    manager = FakePlaywrightManager(context)
    observed_cookies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cookie = request.headers["cookie"]
        observed_cookies.append(cookie)
        if cookie == "authToken=stale-session":
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(
            200,
            json={
                "data": {"user": {"id": "u-1"}, "workspace": {"id": "w-1"}},
                "success": True,
                "status": 200,
            },
        )

    install_transport(monkeypatch, handler)
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.login()

    assert result.ok is True
    assert observed_cookies == ["authToken=stale-session", "authToken=fresh-session"]
    assert context.cleared_cookies == [{"name": "authToken"}]
    assert context.closed is True


def test_login_waits_for_a_cookie_created_after_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = SequencedCookieContext(
        [
            [],
            [{"name": "authToken", "value": "fresh-session", "httpOnly": True}],
        ]
    )
    manager = FakePlaywrightManager(context)
    install_transport(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json={
                "data": {"user": {"id": "u-1"}, "workspace": {"id": "w-1"}},
                "success": True,
                "status": 200,
            },
        ),
    )
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.login()

    assert result.ok is True
    assert context.closed is True


def test_login_identity_probe_timeout_is_capped_to_the_remaining_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monotonic_values = iter([100.0, 100.0, 397.5])
    monkeypatch.setattr(auth.time, "monotonic", lambda: next(monotonic_values))
    context = FakeContext([{"name": "authToken", "value": "fresh-session", "httpOnly": True}])
    manager = FakePlaywrightManager(context)
    captured: dict[str, Any] = {}
    original_client = httpx.Client

    def client_with_transport(**kwargs: Any) -> httpx.Client:
        captured.update(kwargs)
        return original_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "data": {"user": {"id": "u-1"}, "workspace": {"id": "w-1"}},
                        "success": True,
                        "status": 200,
                    },
                )
            ),
            **kwargs,
        )

    monkeypatch.setattr(auth.httpx, "Client", client_with_transport)
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.login()

    assert result.ok is True
    assert captured["timeout"] == 2.5


def test_login_with_deadline_exhausted_before_identity_probe_does_not_send_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monotonic_values = iter([100.0, 100.0, 400.0])
    monkeypatch.setattr(auth.time, "monotonic", lambda: next(monotonic_values))
    context = FakeContext([{"name": "authToken", "value": "fresh-session", "httpOnly": True}])
    manager = FakePlaywrightManager(context)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {"user": {"id": "u-1"}, "workspace": {"id": "w-1"}},
                "success": True,
                "status": 200,
            },
        )

    install_transport(monkeypatch, handler)
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.login()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED
    assert requests == []


def test_login_stale_cookie_times_out_with_recovery_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "_COOKIE_WAIT_SECONDS", 0.01)
    monotonic_values = iter([0.0, 0.0, 0.0, 0.1])
    monkeypatch.setattr(auth.time, "monotonic", lambda: next(monotonic_values))
    context = SequencedCookieContext(
        [[{"name": "authToken", "value": "stale-session", "httpOnly": True}]]
    )
    manager = FakePlaywrightManager(context)
    install_transport(monkeypatch, lambda _: httpx.Response(401, json={"message": "expired"}))
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.login()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED
    assert result.error.message == (
        "Authentication required. Run "
        "`\"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth\" login`."
    )
    assert context.cleared_cookies == [{"name": "authToken"}]
    assert context.closed is True


def test_login_with_an_exhausted_deadline_does_not_navigate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "_COOKIE_WAIT_SECONDS", 0.0)
    context = FakeContext([])
    manager = FakePlaywrightManager(context)
    service = AuthService(settings(), profile_paths(tmp_path), playwright_factory=lambda: manager)

    result = service.login()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_REQUIRED
    assert context.pages[0].visits == []


def test_login_reports_actionable_gui_recovery_without_leaking_playwright_details(
    tmp_path: Path,
) -> None:
    def unavailable_browser() -> Any:
        raise PlaywrightError("private display and profile details")

    service = AuthService(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=unavailable_browser,
    )

    result = service.login()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INTERNAL_ERROR
    assert result.error.message == (
        "Docmost browser could not start. Reinstall the Docmost runtime from the "
        "toolbox checkout, then from a desktop GUI run "
        "`\"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth\" login`."
    )
    assert "private display" not in result.error.message


def test_login_reports_actionable_navigation_recovery_without_leaking_details(
    tmp_path: Path,
) -> None:
    class UnavailableLoginPage(FakePage):
        def goto(self, url: str, *, wait_until: str, timeout: float) -> None:
            del url, wait_until, timeout
            raise PlaywrightError("private login URL and network details")

    context = FakeContext([])
    context.pages = [UnavailableLoginPage()]
    manager = FakePlaywrightManager(context)
    service = AuthService(
        settings(),
        profile_paths(tmp_path),
        playwright_factory=lambda: manager,
    )

    result = service.login()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert result.error.retryable is True
    assert result.error.message == (
        "Docmost login page could not be opened. Verify DOCMOST_LOGIN_URL and network "
        "access, then run "
        "`\"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth\" login`."
    )
    assert "private login URL" not in result.error.message
    assert context.closed is True
