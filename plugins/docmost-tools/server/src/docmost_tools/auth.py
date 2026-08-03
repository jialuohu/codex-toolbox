"""Browser-profile authentication for a local Docmost instance."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol, cast

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode, OperationError, OperationResult
from docmost_tools.profile import ProfileBusyError, ProfilePathError, ProfilePaths, profile_lock
from docmost_tools.recovery import AUTH_LOGIN_COMMAND, AUTH_REQUIRED_SENTENCE

AUTH_REQUIRED_MESSAGE = AUTH_REQUIRED_SENTENCE
_COOKIE_WAIT_SECONDS = 300.0


class _AuthenticationRequired(RuntimeError):
    """The browser profile does not hold a working session."""


class _ProbeFailure(RuntimeError):
    """The authenticated Docmost HTTP contract was not available."""


class _BrowserLaunchFailure(RuntimeError):
    """The headed browser could not be created for interactive login."""


class _LoginNavigationFailure(RuntimeError):
    """The configured interactive login page could not be opened."""


class _PlaywrightManager(Protocol):
    """The small Playwright surface used by this module and its tests."""

    def __enter__(self) -> Any: ...

    def __exit__(self, *args: object) -> None: ...


class AuthService:
    """Perform isolated browser login, status checks, and logout."""

    def __init__(
        self,
        settings: DocmostSettings,
        paths: ProfilePaths,
        *,
        playwright_factory: Callable[[], _PlaywrightManager] = sync_playwright,
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._playwright_factory = playwright_factory

    def login(self) -> OperationResult[dict[str, object]]:
        """Open a headed persistent browser and verify the resulting session."""

        try:
            with profile_lock(self._paths):
                identity = self._login_identity()
        except Exception as error:  # Converted to the stable public result boundary below.
            return self._failure(error)
        return self._success(identity)

    def status(self) -> OperationResult[dict[str, object]]:
        """Check the existing persistent profile without exposing its cookie."""

        try:
            with profile_lock(self._paths):
                cookie = self._browser_cookie(headless=True)
                identity = self._identity(cookie)
                version = self._version(cookie)
        except Exception as error:  # Converted to the stable public result boundary below.
            return self._failure(error)
        return self._success({**identity, "version": version})

    def logout(self) -> OperationResult[dict[str, object]]:
        """Remove only the isolated persistent browser profile while holding its lock."""

        return self.logout_paths(self._paths)

    @classmethod
    def logout_paths(cls, paths: ProfilePaths) -> OperationResult[dict[str, object]]:
        """Remove a validated profile without requiring Docmost connection settings."""

        try:
            with profile_lock(paths):
                paths.remove_profile()
        except Exception as error:  # Converted to the stable public result boundary below.
            return cls._failure(error)
        return cls._success({"logged_out": True})

    def _browser_cookie(self, *, headless: bool) -> str:
        profile = self._paths.ensure_profile_directory()
        with self._playwright_factory() as playwright:
            context = playwright.chromium.launch_persistent_context(str(profile), headless=headless)
            try:
                return self._cookie_from_context(context)
            finally:
                context.close()

    def _login_identity(self) -> dict[str, object]:
        profile = self._paths.ensure_profile_directory()
        deadline = time.monotonic() + _COOKIE_WAIT_SECONDS
        try:
            playwright_manager = self._playwright_factory()
            playwright_context = playwright_manager.__enter__()
        except PlaywrightError as error:
            raise _BrowserLaunchFailure from error
        try:
            try:
                context = playwright_context.chromium.launch_persistent_context(
                    str(profile), headless=False
                )
            except PlaywrightError as error:
                raise _BrowserLaunchFailure from error
            try:
                page = context.pages[0] if context.pages else context.new_page()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _AuthenticationRequired(AUTH_REQUIRED_MESSAGE)
                try:
                    page.goto(
                        self._login_url(),
                        wait_until="domcontentloaded",
                        timeout=remaining * 1000,
                    )
                except PlaywrightError as error:
                    raise _LoginNavigationFailure from error
                invalid_cookie: str | None = None
                while True:
                    try:
                        session_cookie = self._session_cookie(context)
                    except _AuthenticationRequired:
                        session_cookie = None
                    if session_cookie is not None:
                        cookie = self._cookie_value(session_cookie)
                        if cookie != invalid_cookie:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise _AuthenticationRequired(AUTH_REQUIRED_MESSAGE)
                            try:
                                return self._identity(cookie, timeout=min(15.0, remaining))
                            except _AuthenticationRequired:
                                invalid_cookie = cookie
                                self._clear_session_cookie(context, session_cookie)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise _AuthenticationRequired(AUTH_REQUIRED_MESSAGE)
                    page.wait_for_timeout(min(250.0, remaining * 1000))
            finally:
                context.close()
        finally:
            playwright_manager.__exit__(None, None, None)

    def _cookie_from_context(self, context: Any) -> str:
        return self._cookie_value(self._session_cookie(context))

    def _session_cookie(self, context: Any) -> dict[str, Any]:
        for cookie in context.cookies([self._endpoint("/api/users/me")]):
            if cookie.get("name") == self._settings.session_cookie:
                value = cookie.get("value")
                if isinstance(value, str) and value:
                    return cast(dict[str, Any], cookie)
        raise _AuthenticationRequired(AUTH_REQUIRED_MESSAGE)

    @staticmethod
    def _cookie_value(cookie: dict[str, Any]) -> str:
        value = cookie["value"]
        assert isinstance(value, str)
        return value

    def _clear_session_cookie(self, context: Any, cookie: dict[str, Any]) -> None:
        filters = {"name": self._settings.session_cookie}
        for field in ("domain", "path"):
            value = cookie.get(field)
            if isinstance(value, str) and value:
                filters[field] = value
        context.clear_cookies(**filters)

    def _identity(self, cookie: str, *, timeout: float = 15.0) -> dict[str, object]:
        data = self._post("/api/users/me", cookie, timeout=timeout)
        user = data.get("user")
        workspace = data.get("workspace")
        if not isinstance(user, dict) or not isinstance(workspace, dict):
            msg = "Docmost identity response did not include user and workspace objects"
            raise _ProbeFailure(msg)
        return {"user": user, "workspace": workspace}

    def _version(self, cookie: str) -> dict[str, object]:
        data = self._post("/api/version", cookie)
        return data

    def _post(self, path: str, cookie: str, *, timeout: float = 15.0) -> dict[str, object]:
        try:
            with httpx.Client(
                verify=True if self._settings.ca_bundle is None else str(self._settings.ca_bundle),
                follow_redirects=False,
                trust_env=False,
                timeout=timeout,
            ) as client:
                response = client.post(
                    self._endpoint(path),
                    json={},
                    headers={"Cookie": f"{self._settings.session_cookie}={cookie}"},
                )
        except httpx.HTTPError as error:
            raise _ProbeFailure("Docmost authentication probe failed") from error
        if response.status_code == 401:
            raise _AuthenticationRequired(AUTH_REQUIRED_MESSAGE)
        if response.status_code != 200:
            msg = f"Docmost authentication probe returned HTTP {response.status_code}"
            raise _ProbeFailure(msg)
        try:
            payload = cast(object, response.json())
        except ValueError as error:
            raise _ProbeFailure("Docmost authentication probe returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise _ProbeFailure("Docmost authentication probe returned an invalid envelope")
        envelope = cast(dict[str, object], payload)
        data = envelope.get("data")
        if (
            envelope.get("success") is not True
            or envelope.get("status") != 200
            or not isinstance(data, dict)
        ):
            raise _ProbeFailure("Docmost authentication probe returned an invalid envelope")
        return cast(dict[str, object], data)

    def _base_url(self) -> str:
        return str(self._settings.base_url)

    def _login_url(self) -> str:
        if self._settings.login_url is not None:
            return str(self._settings.login_url)
        return f"{self._base_url().rstrip('/')}/login"

    def _endpoint(self, path: str) -> str:
        return f"{self._base_url().rstrip('/')}{path}"

    @staticmethod
    def _failure(error: Exception) -> OperationResult[dict[str, object]]:
        if isinstance(error, _AuthenticationRequired):
            return AuthService._error(ErrorCode.AUTH_REQUIRED, AUTH_REQUIRED_MESSAGE)
        if isinstance(error, _BrowserLaunchFailure):
            return AuthService._error(
                ErrorCode.INTERNAL_ERROR,
                "Docmost browser could not start. Reinstall the Docmost runtime from "
                f"the toolbox checkout, then from a desktop GUI run `{AUTH_LOGIN_COMMAND}`.",
            )
        if isinstance(error, _LoginNavigationFailure):
            return AuthService._error(
                ErrorCode.UPSTREAM_ERROR,
                "Docmost login page could not be opened. Verify DOCMOST_LOGIN_URL and "
                f"network access, then run `{AUTH_LOGIN_COMMAND}`.",
                retryable=True,
            )
        if isinstance(error, PlaywrightError):
            return AuthService._error(
                ErrorCode.INTERNAL_ERROR,
                "Docmost browser authentication failed. Run "
                f"`{AUTH_LOGIN_COMMAND}` from a "
                "desktop GUI and verify DOCMOST_LOGIN_URL and network access.",
            )
        if isinstance(error, ProfileBusyError):
            return AuthService._error(
                ErrorCode.PROFILE_BUSY,
                "PROFILE_BUSY: Docmost browser profile is in use",
                retryable=True,
            )
        if isinstance(error, ProfilePathError):
            return AuthService._error(
                ErrorCode.CONFIGURATION_INVALID,
                "Docmost MCP configuration is invalid",
            )
        if isinstance(error, _ProbeFailure):
            return AuthService._error(ErrorCode.UPSTREAM_ERROR, str(error), retryable=True)
        return AuthService._error(
            ErrorCode.INTERNAL_ERROR,
            "Docmost authentication operation failed",
        )

    @staticmethod
    def _success(data: dict[str, object]) -> OperationResult[dict[str, object]]:
        return OperationResult[dict[str, object]](ok=True, data=data)

    @staticmethod
    def _error(
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> OperationResult[dict[str, object]]:
        return OperationResult[dict[str, object]](
            ok=False,
            error=OperationError(code=code, message=message, retryable=retryable),
        )
