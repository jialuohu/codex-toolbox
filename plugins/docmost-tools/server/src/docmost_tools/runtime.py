"""One-time, headless session bootstrap for the read-only MCP process."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol, cast

from playwright.sync_api import sync_playwright

from docmost_tools.client import AUTH_REQUIRED_MESSAGE, DocmostReadClient
from docmost_tools.config import DocmostSettings
from docmost_tools.models import ErrorCode, OperationError, OperationResult
from docmost_tools.profile import ProfileBusyError, ProfilePathError, ProfilePaths, profile_lock


class _BrowserContext(Protocol):
    def cookies(self, urls: list[str]) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


class _Chromium(Protocol):
    def launch_persistent_context(self, profile: str, *, headless: bool) -> _BrowserContext: ...


class _PlaywrightManager(Protocol):
    def __enter__(self) -> _Playwright: ...

    def __exit__(self, *args: object) -> None: ...


class _Playwright(Protocol):
    @property
    def chromium(self) -> _Chromium: ...


class ReadClient(Protocol):
    def version(self) -> OperationResult[Any]: ...

    def current_user(self) -> OperationResult[Any]: ...

    def list_spaces(self, *, limit: int, cursor: str | None = None) -> OperationResult[Any]: ...

    def close(self) -> None: ...


ReadClientFactory = Callable[[DocmostSettings, str], ReadClient]
ProfileLockFactory = Callable[[ProfilePaths], AbstractContextManager[None]]
CONFIGURATION_INVALID_MESSAGE = "Docmost MCP configuration is invalid"


def _default_playwright_factory() -> _PlaywrightManager:
    """Adapt Playwright's context manager to the small local protocol."""

    return cast(_PlaywrightManager, sync_playwright())


@dataclass
class RuntimeState:
    """The initialized HTTP client or a safe error exposed by every tool."""

    client: ReadClient | None
    startup_error: OperationError | None

    def close(self) -> None:
        """Release HTTP resources after the stdio transport exits."""

        if self.client is not None:
            self.client.close()


def bootstrap_runtime(
    settings: DocmostSettings,
    paths: ProfilePaths,
    *,
    playwright_factory: Callable[[], _PlaywrightManager] = _default_playwright_factory,
    client_factory: ReadClientFactory = DocmostReadClient,
    lock_factory: ProfileLockFactory = profile_lock,
) -> RuntimeState:
    """Create one HTTP client from a briefly opened, isolated browser profile.

    The browser exists only before MCP stdio starts. Cookie data stays in the
    client process memory and is neither written nor surfaced by the tool API.
    """

    client: ReadClient | None = None
    try:
        with lock_factory(paths):
            cookie = _extract_session_cookie(settings, paths, playwright_factory)
        client = client_factory(settings, cookie)
        version = client.version()
        if (
            not version.ok
            and version.error is not None
            and version.error.code is ErrorCode.AUTH_REQUIRED
        ):
            client.close()
            return RuntimeState(client=None, startup_error=_auth_required_error())
        return RuntimeState(client=client, startup_error=None)
    except ProfileBusyError:
        return RuntimeState(
            client=None,
            startup_error=OperationError(
                code=ErrorCode.PROFILE_BUSY,
                message="PROFILE_BUSY: Docmost browser profile is in use",
                retryable=True,
            ),
        )
    except ProfilePathError as error:
        del error
        return RuntimeState(
            client=None,
            startup_error=OperationError(
                code=ErrorCode.CONFIGURATION_INVALID,
                message=CONFIGURATION_INVALID_MESSAGE,
            ),
        )
    except _AuthenticationRequired:
        return RuntimeState(client=None, startup_error=_auth_required_error())
    except Exception:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        return RuntimeState(
            client=None,
            startup_error=OperationError(
                code=ErrorCode.UPSTREAM_ERROR,
                message="Docmost MCP session bootstrap failed",
                retryable=True,
            ),
        )


class _AuthenticationRequired(RuntimeError):
    """The persistent profile lacks the one configured session cookie."""


def _extract_session_cookie(
    settings: DocmostSettings,
    paths: ProfilePaths,
    playwright_factory: Callable[[], _PlaywrightManager],
) -> str:
    profile = paths.ensure_profile_directory()
    with playwright_factory() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile), headless=True)
        try:
            endpoint = f"{str(settings.base_url).rstrip('/')}/api/users/me"
            for cookie in context.cookies([endpoint]):
                if cookie.get("name") == settings.session_cookie:
                    value = cookie.get("value")
                    if isinstance(value, str) and value:
                        return value
            raise _AuthenticationRequired()
        finally:
            context.close()


def _auth_required_error() -> OperationError:
    return OperationError(code=ErrorCode.AUTH_REQUIRED, message=AUTH_REQUIRED_MESSAGE)
