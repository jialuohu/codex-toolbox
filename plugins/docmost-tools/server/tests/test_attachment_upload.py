"""Security contracts for local PDF upload staging."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from docmost_tools.attachment_upload import PdfUploadValidator, PdfValidationError

PDF_BYTES = b"%PDF-1.4\nminimal contract fixture\n%%EOF\n"


def write_pdf(path: Path, content: bytes = PDF_BYTES) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def validator(home: Path, *, max_bytes: int = 50 * 1024 * 1024) -> PdfUploadValidator:
    return PdfUploadValidator(
        home=home,
        secrets_root=home / "codex-secrets",
        max_bytes=max_bytes,
    )


def assert_rejected(
    upload_validator: PdfUploadValidator,
    path: str,
    digest: str,
    kind: str,
) -> None:
    with pytest.raises(PdfValidationError) as raised:
        with upload_validator.open(path, digest):
            pytest.fail("unsafe PDF must not be yielded")
    assert raised.value.kind == kind


def test_valid_pdf_is_hashed_and_held_open_under_home(tmp_path: Path) -> None:
    path = tmp_path / "reports" / "week-1.pdf"
    digest = write_pdf(path)

    with validator(tmp_path).open(str(path), digest) as validated:
        assert validated.filename == "week-1.pdf"
        assert validated.size_bytes == len(PDF_BYTES)
        assert validated.sha256 == digest
        assert validated.stream.read(5) == b"%PDF-"
        validated.assert_stable()


@pytest.mark.parametrize(
    "relative_path",
    [
        ".hidden/report.pdf",
        "Library/report.pdf",
        "work/.ssh/report.pdf",
        "work/credentials/report.pdf",
        "work/oauth-token/report.pdf",
        "work/keys/report.pdf",
        "codex-secrets/report.pdf",
    ],
)
def test_hidden_secret_and_credential_like_paths_are_rejected(
    tmp_path: Path,
    relative_path: str,
) -> None:
    path = tmp_path / relative_path
    digest = write_pdf(path)

    assert_rejected(validator(tmp_path), str(path), digest, "forbidden_path")


def test_relative_and_outside_home_paths_are_rejected(tmp_path: Path) -> None:
    inside = tmp_path / "inside.pdf"
    digest = write_pdf(inside)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.pdf"
    outside_digest = write_pdf(outside)
    try:
        assert_rejected(validator(tmp_path), "inside.pdf", digest, "forbidden_path")
        assert_rejected(
            validator(tmp_path),
            str(outside),
            outside_digest,
            "forbidden_path",
        )
    finally:
        outside.unlink(missing_ok=True)


def test_symlink_and_hard_link_paths_are_rejected(tmp_path: Path) -> None:
    original = tmp_path / "original.pdf"
    digest = write_pdf(original)
    symlink = tmp_path / "symlink.pdf"
    symlink.symlink_to(original)
    hard_link = tmp_path / "hard-link.pdf"
    os.link(original, hard_link)

    assert_rejected(validator(tmp_path), str(symlink), digest, "forbidden_path")
    assert_rejected(validator(tmp_path), str(hard_link), digest, "forbidden_path")


@pytest.mark.parametrize(
    ("filename", "content", "max_bytes", "kind"),
    [
        ("report.txt", PDF_BYTES, 1_024, "unsupported_attachment"),
        ("id_rsa.pdf", PDF_BYTES, 1_024, "forbidden_path"),
        ("report.pem.pdf", PDF_BYTES, 1_024, "forbidden_path"),
        ("report.pdf", b"not a pdf", 1_024, "unsupported_attachment"),
        ("empty.pdf", b"", 1_024, "unsupported_attachment"),
        ("large.pdf", PDF_BYTES, len(PDF_BYTES) - 1, "attachment_too_large"),
    ],
)
def test_invalid_and_oversized_files_are_rejected(
    tmp_path: Path,
    filename: str,
    content: bytes,
    max_bytes: int,
    kind: str,
) -> None:
    path = tmp_path / filename
    digest = write_pdf(path, content)

    assert_rejected(validator(tmp_path, max_bytes=max_bytes), str(path), digest, kind)


def test_checksum_mismatch_and_file_change_race_are_conflicts(tmp_path: Path) -> None:
    path = tmp_path / "report.pdf"
    digest = write_pdf(path)
    assert_rejected(validator(tmp_path), str(path), "0" * 64, "conflict")

    with validator(tmp_path).open(str(path), digest) as validated:
        path.write_bytes(PDF_BYTES + b"changed")
        with pytest.raises(PdfValidationError) as raised:
            validated.assert_stable()
    assert raised.value.kind == "conflict"
