"""Configuration contracts for the local Docmost adapter."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_COOKIE_NAME_PATTERN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,256}\Z")


class ApiProfile(StrEnum):
    """Read API compatibility profile selected by a later client layer."""

    AUTO = "auto"


class WriteProfile(StrEnum):
    """Explicit write compatibility profiles supported by future transport code."""

    V0_95 = "v0_95"


class DocmostSettings(BaseSettings):
    """Environment-backed settings without performing authentication or I/O."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_prefix="DOCMOST_",
        extra="forbid",
    )

    base_url: AnyHttpUrl = Field(
        description="Absolute base URL for the Docmost instance.",
    )
    login_url: AnyHttpUrl | None = Field(
        default=None,
        description="Optional explicit browser login URL.",
    )
    session_cookie: str = Field(
        default="authToken",
        min_length=1,
        description="Name of the browser session cookie to extract after SSO login.",
    )
    api_profile: ApiProfile = Field(
        default=ApiProfile.AUTO,
        description="Read API compatibility profile; automatic selection is the only initial mode.",
    )
    write_profile: WriteProfile | None = Field(
        default=None,
        description="Optional explicit write API compatibility profile.",
    )
    ca_bundle: Path | None = Field(
        default=None,
        description="Optional CA bundle for trusted internal certificate authorities.",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        cls._validate_docmost_url(value, allow_path=False)
        return value

    @field_validator("login_url")
    @classmethod
    def validate_login_url(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None:
            cls._validate_docmost_url(value, allow_path=True)
        return value

    @field_validator("session_cookie")
    @classmethod
    def validate_session_cookie(cls, value: str) -> str:
        if _COOKIE_NAME_PATTERN.fullmatch(value) is None:
            msg = "DOCMOST_SESSION_COOKIE must be a valid cookie name"
            raise ValueError(msg)
        return value

    @field_validator("ca_bundle")
    @classmethod
    def validate_ca_bundle(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            msg = "DOCMOST_CA_BUNDLE must be an absolute path"
            raise ValueError(msg)
        return value

    @staticmethod
    def _validate_docmost_url(value: AnyHttpUrl, *, allow_path: bool) -> None:
        host = (value.host or "").strip("[]").lower()
        loopback_hosts = {"localhost", "127.0.0.1", "::1"}
        if value.scheme != "https" and host not in loopback_hosts:
            msg = "Docmost URLs must use HTTPS unless the host is loopback"
            raise ValueError(msg)
        if value.username is not None or value.password is not None:
            msg = "Docmost URLs must not embed credentials"
            raise ValueError(msg)
        if value.fragment is not None:
            msg = "Docmost URLs must not include fragments"
            raise ValueError(msg)
        if value.query is not None:
            msg = "Docmost URLs must not include query strings"
            raise ValueError(msg)
        if not allow_path and value.path not in {"", "/"}:
            msg = "DOCMOST_BASE_URL must not include a path"
            raise ValueError(msg)
