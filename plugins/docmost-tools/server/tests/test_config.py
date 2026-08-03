from __future__ import annotations

import pytest
from pydantic import ValidationError

from docmost_tools.config import ApiProfile, DocmostSettings, WriteProfile


def settings_from_values(**values: object) -> DocmostSettings:
    return DocmostSettings.model_validate(values)


def test_settings_accepts_approved_configuration_values() -> None:
    settings = settings_from_values(
        base_url="https://docs.example.test/",
        login_url="https://docs.example.test/login",
        write_profile="v0_95",
        ca_bundle="/private/tmp/docmost-ca.pem",
    )

    assert str(settings.base_url) == "https://docs.example.test/"
    assert str(settings.login_url) == "https://docs.example.test/login"
    assert settings.session_cookie == "authToken"
    assert settings.api_profile is ApiProfile.AUTO
    assert settings.write_profile is WriteProfile.V0_95
    assert str(settings.ca_bundle) == "/private/tmp/docmost-ca.pem"


def test_settings_rejects_relative_ca_bundle_path() -> None:
    with pytest.raises(ValidationError, match="ca_bundle"):
        settings_from_values(
            base_url="https://docs.example.test",
            ca_bundle="certificates/docmost-ca.pem",
        )


def test_settings_has_browser_only_safe_defaults() -> None:
    settings = settings_from_values(base_url="https://docs.example.test")

    assert settings.login_url is None
    assert settings.session_cookie == "authToken"
    assert settings.api_profile is ApiProfile.AUTO
    assert settings.write_profile is None
    assert settings.ca_bundle is None


@pytest.mark.parametrize("cookie_name", ["authToken; admin=true", "auth Token", "auth\r\nToken"])
def test_settings_rejects_unsafe_session_cookie_names(cookie_name: str) -> None:
    with pytest.raises(ValidationError, match="session_cookie"):
        settings_from_values(base_url="https://docs.example.test", session_cookie=cookie_name)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://docs.example.test",
        "https://docs.example.test/workspace",
        "https://docs.example.test/#fragment",
        "https://user:password@docs.example.test",
    ],
)
def test_settings_rejects_unsafe_or_non_root_base_urls(base_url: str) -> None:
    with pytest.raises(ValidationError, match="Value error"):
        settings_from_values(base_url=base_url)


@pytest.mark.parametrize("base_url", ["http://localhost:3000", "http://[::1]:3000"])
def test_settings_allows_http_for_loopback_development_only(base_url: str) -> None:
    settings = settings_from_values(base_url=base_url)

    assert settings.base_url.scheme == "http"


def test_settings_reads_only_docmost_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCMOST_BASE_URL", raising=False)
    monkeypatch.setenv("BASE_URL", "https://wrong.example.test")

    with pytest.raises(ValidationError, match="base_url"):
        settings_from_values()

    monkeypatch.setenv("DOCMOST_BASE_URL", "https://docs.example.test")
    settings = settings_from_values()

    assert str(settings.base_url) == "https://docs.example.test/"


@pytest.mark.parametrize("field", ["DOCMOST_USERNAME", "DOCMOST_PASSWORD", "DOCMOST_VERIFY_TLS"])
def test_settings_rejects_removed_credential_and_tls_options(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        settings_from_values(base_url="https://docs.example.test", **{field: "value"})
