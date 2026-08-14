from __future__ import annotations

from pathlib import Path

import pytest

from apple_mail_tools.models import AppleMailError, ErrorCode
from apple_mail_tools.path_security import MAX_ATTACHMENT_BYTES, validate_outgoing_attachments


def test_regular_home_file_is_hashed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    secrets = home / ".codex" / "secrets"
    secrets.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    document = home / "Documents" / "report.txt"
    document.parent.mkdir()
    document.write_text("report")

    result = validate_outgoing_attachments([str(document)], secrets_root=secrets)
    assert result[0].path == document.resolve()
    assert result[0].size == 6
    assert len(result[0].sha256) == 64


@pytest.mark.parametrize(
    "relative,contents",
    [
        (".hidden/file.txt", b"safe"),
        ("Library/file.txt", b"safe"),
        ("Documents/oauth-token.txt", b"safe"),
        (
            "Documents/innocent.txt",
            b"-----BEGIN " + b"PRIVATE KEY-----\nsynthetic-test-payload",
        ),
    ],
)
def test_hidden_system_credential_and_key_files_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    contents: bytes,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    secrets = home / ".codex" / "secrets"
    secrets.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    candidate = home / relative
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(contents)
    with pytest.raises(AppleMailError) as rejected:
        validate_outgoing_attachments([str(candidate)], secrets_root=secrets)
    assert rejected.value.code is ErrorCode.FORBIDDEN_PATH


def test_symlink_and_oversize_files_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    secrets = home / ".codex" / "secrets"
    secrets.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    target = home / "target.txt"
    target.write_text("safe")
    link = home / "link.txt"
    link.symlink_to(target)
    with pytest.raises(AppleMailError) as symlinked:
        validate_outgoing_attachments([str(link)], secrets_root=secrets)
    assert symlinked.value.code is ErrorCode.FORBIDDEN_PATH

    huge = home / "huge.bin"
    with huge.open("wb") as stream:
        stream.truncate(MAX_ATTACHMENT_BYTES + 1)
    with pytest.raises(AppleMailError) as oversized:
        validate_outgoing_attachments([str(huge)], secrets_root=secrets)
    assert oversized.value.code is ErrorCode.ATTACHMENT_TOO_LARGE
