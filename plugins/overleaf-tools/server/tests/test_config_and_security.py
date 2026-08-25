from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from overleaf_tools import cli, permissions
from overleaf_tools.config import ConfigStore
from overleaf_tools.errors import ErrorCode, OverleafError
from overleaf_tools.git_client import validate_commit_message, validate_project_path
from overleaf_tools.latex import extract_outline


def test_config_defaults_to_codex_home_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.delenv("CODEX_SECRETS_DIR", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    store = ConfigStore()

    assert store.secrets_dir == codex_home / "secrets"
    assert store.root == codex_home / "secrets" / "overleaf-tools"


def test_config_defaults_to_user_codex_home_when_env_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_home = tmp_path / "user-home"
    monkeypatch.delenv("CODEX_SECRETS_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)

    def fake_home(_cls: type[Path]) -> Path:
        return user_home

    monkeypatch.setattr(Path, "home", classmethod(fake_home))

    store = ConfigStore()

    assert store.secrets_dir == user_home / ".codex" / "secrets"
    assert store.root == user_home / ".codex" / "secrets" / "overleaf-tools"


def test_config_prefers_explicit_secrets_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets_dir = tmp_path / "explicit-secrets"
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(secrets_dir))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))

    store = ConfigStore()

    assert store.secrets_dir == secrets_dir


def test_config_requires_an_absolute_explicit_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEX_SECRETS_DIR", raising=False)

    monkeypatch.setenv("CODEX_HOME", "relative-codex-home")
    with pytest.raises(OverleafError) as relative:
        ConfigStore()
    assert relative.value.code == ErrorCode.CONFIGURATION_INVALID


def test_config_is_private_and_never_embeds_token(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "secrets")
    assert store.initialize() is True
    token_path = store.set_token("default", "private-value")
    store.write_raw(
        {
            "version": 1,
            "projects": {
                "weekly-report": {
                    "projectId": "project12345678",
                    "tokenFile": "tokens/default.token",
                    "displayName": "Weekly Report",
                }
            },
            "allowedImportRoots": [],
        }
    )
    loaded = store.load()
    assert loaded.projects["weekly-report"].token_path == token_path
    assert "private-value" not in store.config_path.read_text(encoding="utf-8")
    if os.name != "nt":
        assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(store.config_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_windows_acl_readback_uses_native_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested: list[tuple[str, int, int]] = []

    class FakeAcl:
        def GetAceCount(self) -> int:
            return 2

        def GetAce(self, index: int) -> object:
            return ((0, 0), 0x1F01FF, ("S-1-5-18", "S-1-5-21-123")[index])

    class FakeDescriptor:
        def GetSecurityDescriptorDacl(self) -> FakeAcl:
            return FakeAcl()

    class FakeSecurity:
        DACL_SECURITY_INFORMATION = 4
        INHERITED_ACE = 0x10
        SE_FILE_OBJECT = 1

        def GetNamedSecurityInfo(
            self, object_name: str, object_type: int, security_info: int
        ) -> FakeDescriptor:
            requested.append((object_name, object_type, security_info))
            return FakeDescriptor()

        def ConvertSidToStringSid(self, sid: object) -> str:
            assert isinstance(sid, str)
            return sid

    class FakeConstants:
        ACCESS_ALLOWED_ACE_TYPE = 0
        ACCESS_DENIED_ACE_TYPE = 1

    def fake_modules() -> tuple[FakeSecurity, FakeConstants]:
        return FakeSecurity(), FakeConstants()

    monkeypatch.setattr(permissions, "_load_windows_security_modules", fake_modules)
    path = tmp_path / "private path with 'quotes'"

    actual = permissions._windows_acl_sids(path)  # pyright: ignore[reportPrivateUsage]

    assert actual == {"S-1-5-18", "S-1-5-21-123"}
    assert requested == [(str(path), 1, 4)]


def test_windows_hardening_applies_exact_protected_dacl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_sid = "S-1-5-21-123"
    applied: list[tuple[object, ...]] = []

    class FakeAcl:
        def __init__(self) -> None:
            self.entries: list[tuple[int, int, int, object]] = []

        def AddAccessAllowedAceEx(
            self, revision: int, flags: int, access_mask: int, sid: object
        ) -> None:
            self.entries.append((revision, flags, access_mask, sid))

    acl = FakeAcl()

    class FakeSecurity:
        ACL_REVISION_DS = 4
        DACL_SECURITY_INFORMATION = 4
        PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
        SE_FILE_OBJECT = 1

        def ACL(self) -> FakeAcl:
            return acl

        def GetBinarySid(self, sid: str) -> object:
            return f"binary:{sid}"

        def SetNamedSecurityInfo(
            self,
            object_name: str,
            object_type: int,
            security_info: int,
            owner: object | None,
            group: object | None,
            dacl: FakeAcl,
            sacl: object | None,
        ) -> None:
            applied.append(
                (object_name, object_type, security_info, owner, group, dacl, sacl)
            )

    class FakeConstants:
        CONTAINER_INHERIT_ACE = 2
        FILE_ALL_ACCESS = 0x1F01FF
        OBJECT_INHERIT_ACE = 1

    def fake_current_sid() -> str:
        return current_sid

    def fake_modules() -> tuple[FakeSecurity, FakeConstants]:
        return FakeSecurity(), FakeConstants()

    monkeypatch.setattr(permissions, "_windows_current_sid", fake_current_sid)
    monkeypatch.setattr(permissions, "_load_windows_security_modules", fake_modules)

    permissions._harden_windows_path(  # pyright: ignore[reportPrivateUsage]
        tmp_path, directory=True
    )

    assert acl.entries == [
        (4, 3, 0x1F01FF, f"binary:{current_sid}"),
        (4, 3, 0x1F01FF, "binary:S-1-5-18"),
    ]
    assert applied == [(str(tmp_path), 1, 0x80000004, None, None, acl, None)]


def test_insecure_config_mode_and_link_are_rejected(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode and symlink contract")
    store = ConfigStore(tmp_path / "secrets")
    store.initialize()
    store.config_path.chmod(0o644)
    with pytest.raises(OverleafError, match="group/world"):
        store.load()
    store.config_path.chmod(0o600)
    real = store.root / "real.json"
    store.config_path.rename(real)
    store.config_path.symlink_to(real)
    with pytest.raises(OverleafError, match="symlink"):
        store.load()


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../main.tex",
        "/tmp/main.tex",
        "C:/main.tex",
        "a\\b.tex",
        ".git/config",
        "a//b",
        "CON.tex",
        "folder/name.",
        "bad?.tex",
        "line\nbreak.tex",
        "e\u0301.tex",
    ],
)
def test_unsafe_project_paths_are_rejected(path: str) -> None:
    with pytest.raises(OverleafError) as caught:
        validate_project_path(path)
    assert caught.value.code == ErrorCode.INVALID_PATH


def test_commit_messages_are_single_line() -> None:
    assert validate_commit_message("Update weekly report") == "Update weekly report"
    with pytest.raises(OverleafError):
        validate_commit_message("line one\nline two")


def test_outline_ignores_comments_and_balances_nested_braces() -> None:
    source = (
        "% \\section{Hidden}\n"
        "\\section[Short]{Visible {Nested} Title}\n"
        "escaped \\% value\n"
        "\\subsection*{Method}\n"
    )
    assert extract_outline(source) == [
        {"level": "section", "title": "Visible {Nested} Title", "line": 2},
        {"level": "subsection", "title": "Method", "line": 4},
    ]


def test_config_rejects_token_traversal(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "secrets")
    store.initialize()
    raw = json.loads(store.config_path.read_text(encoding="utf-8"))
    raw["projects"]["bad"] = {
        "projectId": "project12345678",
        "tokenFile": "../outside.token",
    }
    store.write_raw(raw)
    with pytest.raises(OverleafError, match="tokenFile"):
        store.load()


def test_remove_project_preserves_other_private_configuration(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    import_root = tmp_path / "imports"
    import_root.mkdir()
    store = ConfigStore(secrets)
    store.initialize()
    token_path = store.set_token("codex-overleaf", "private-token-value")
    store.write_raw(
        {
            "version": 1,
            "projects": {
                "sandbox": {
                    "projectId": "sandbox12345678",
                    "tokenFile": "tokens/codex-overleaf.token",
                },
                "weekly-report": {
                    "projectId": "weeklyreport1234",
                    "tokenFile": "tokens/codex-overleaf.token",
                    "displayName": "Weekly Report",
                },
            },
            "allowedImportRoots": [str(import_root)],
        }
    )

    store.remove_project("sandbox")

    loaded = store.load()
    assert set(loaded.projects) == {"weekly-report"}
    assert loaded.allowed_import_roots == (import_root,)
    assert token_path.read_text(encoding="utf-8") == "private-token-value"
    if os.name != "nt":
        assert stat.S_IMODE(store.config_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("alias", ["missing", "../invalid"])
def test_remove_project_cli_rejects_unknown_or_invalid_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    alias: str,
) -> None:
    secrets = tmp_path / "secrets"
    store = ConfigStore(secrets)
    store.initialize()
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(secrets))
    monkeypatch.setattr(sys, "argv", ["overleaf-config", "remove-project", alias])

    assert cli.main() == 2

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert "private" not in json.dumps(output).lower()


def test_remove_project_cli_reports_no_token_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secrets = tmp_path / "secrets"
    store = ConfigStore(secrets)
    store.initialize()
    store.set_token("codex-overleaf", "private-token-value")
    store.write_raw(
        {
            "version": 1,
            "projects": {
                "sandbox": {
                    "projectId": "sandbox12345678",
                    "tokenFile": "tokens/codex-overleaf.token",
                }
            },
            "allowedImportRoots": [],
        }
    )
    monkeypatch.setenv("CODEX_SECRETS_DIR", str(secrets))
    monkeypatch.setattr(sys, "argv", ["overleaf-config", "remove-project", "sandbox"])

    assert cli.main() == 0

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output == {
        "ok": True,
        "project": "sandbox",
        "removed": True,
        "tokenRetained": True,
    }
    assert "private-token-value" not in output_text
