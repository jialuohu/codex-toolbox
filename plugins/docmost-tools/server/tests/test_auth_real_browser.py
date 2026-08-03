from __future__ import annotations

import json
import threading
import time
from collections.abc import Generator
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import sync_playwright

from docmost_tools.auth import AuthService
from docmost_tools.config import DocmostSettings
from docmost_tools.profile import profile_paths


class HeadlessChromium:
    """Test-only adapter that proves production login requests a headed browser."""

    def __init__(self, chromium: Any) -> None:
        self._chromium = chromium
        self.requested_headless: list[bool] = []

    def launch_persistent_context(self, user_data_dir: str, *, headless: bool) -> Any:
        self.requested_headless.append(headless)
        return self._chromium.launch_persistent_context(user_data_dir, headless=True)


class HeadlessLoginPlaywright:
    """Use a headless real browser only to keep the integration test nonintrusive."""

    def __init__(self) -> None:
        self._manager: Any = sync_playwright()
        self.chromium: HeadlessChromium | None = None

    def __enter__(self) -> HeadlessLoginPlaywright:
        playwright = self._manager.__enter__()
        self.chromium = HeadlessChromium(playwright.chromium)
        return self

    def __exit__(self, *args: object) -> None:
        self._manager.__exit__(*args)


def chromium_available() -> bool:
    with sync_playwright() as playwright:
        return Path(playwright.chromium.executable_path).is_file()


@pytest.fixture
def fake_docmost() -> Generator[tuple[str, list[str]]]:
    received_cookies: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/login":
                self.send_error(404)
                return
            self.send_response(200)
            expires = formatdate(time.time() + 3600, usegmt=True)
            self.send_header(
                "Set-Cookie",
                f"authToken=real-session; HttpOnly; Path=/; Max-Age=3600; Expires={expires}",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            cookie = self.headers.get("Cookie", "")
            received_cookies.append(cookie)
            if cookie != "authToken=real-session":
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body: dict[str, object]
            if self.path == "/api/users/me":
                body = {"data": {"user": {"id": "u-real"}, "workspace": {"id": "w-real"}}}
            elif self.path == "/api/version":
                body = {"data": {"currentVersion": "0.95.0"}}
            else:
                self.send_error(404)
                return
            body["success"] = True
            body["status"] = 200
            serialized = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(serialized)))
            self.end_headers()
            self.wfile.write(serialized)

        def log_message(self, format: str, *args: object) -> None:
            del format, args
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        port = int(server.server_address[1])
        yield f"http://127.0.0.1:{port}", received_cookies
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.real_browser
@pytest.mark.skipif(not chromium_available(), reason="Playwright Chromium is not installed")
def test_real_login_persists_httponly_sso_cookie_and_logout_is_bounded(
    tmp_path: Path, fake_docmost: tuple[str, list[str]]
) -> None:
    base_url, received_cookies = fake_docmost
    paths = profile_paths(tmp_path)
    paths.prepare_lock_directory()
    sibling = paths.parent / "unrelated-state"
    sibling.write_text("preserve")

    settings = DocmostSettings.model_validate({"base_url": base_url})
    assert httpx.post(f"{base_url}/api/users/me", json={}).status_code == 401
    assert (
        httpx.post(
            f"{base_url}/api/users/me",
            json={},
            headers={"Cookie": "authToken=wrong-session"},
        ).status_code
        == 401
    )
    login_browser = HeadlessLoginPlaywright()
    login_result = AuthService(
        settings,
        paths,
        playwright_factory=lambda: login_browser,
    ).login()
    status_result = AuthService(settings, paths).status()
    logout_result = AuthService(settings, paths).logout()

    assert login_result.ok is True
    assert login_browser.chromium is not None
    assert login_browser.chromium.requested_headless == [False]
    assert status_result.ok is True
    assert status_result.data == {
        "user": {"id": "u-real"},
        "workspace": {"id": "w-real"},
        "version": {"currentVersion": "0.95.0"},
    }
    assert logout_result.ok is True
    assert not paths.profile.exists()
    assert sibling.read_text() == "preserve"
    assert paths.parent.is_dir()
    assert received_cookies == [
        "",
        "authToken=wrong-session",
        "authToken=real-session",
        "authToken=real-session",
        "authToken=real-session",
    ]
