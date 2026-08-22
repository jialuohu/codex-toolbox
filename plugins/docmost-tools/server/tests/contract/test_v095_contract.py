"""Opt-in end-to-end contracts against an isolated Docmost v0.95.0 stack."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import pytest

from docmost_tools.client import DocmostReadClient
from docmost_tools.config import DocmostSettings
from docmost_tools.page_content import validate_patch_operations

pytestmark = pytest.mark.contract
_COMPOSE_FILE = Path(__file__).with_name("docker-compose.yml")
_STARTUP_TIMEOUT_SECONDS = 240.0


@dataclass(frozen=True)
class ContractInstance:
    """The loopback-only ephemeral instance and its in-memory setup cookie."""

    base_url: str
    session_cookie: str


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _compose(
    project: str,
    environment: dict[str, str],
    *arguments: str,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            project,
            "--file",
            str(_COMPOSE_FILE),
            *arguments,
        ],
        cwd=_COMPOSE_FILE.parent,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _wait_until_ready(base_url: str) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    last_error = "no response"
    with httpx.Client(
        base_url=base_url,
        follow_redirects=False,
        trust_env=False,
        timeout=5.0,
    ) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get("/api/health")
                payload = cast(object, response.json())
                payload_dict = (
                    cast(dict[str, object], payload) if isinstance(payload, dict) else {}
                )
                if (
                    response.status_code == 200
                    and payload_dict.get("status") == "ok"
                ):
                    return
                last_error = f"HTTP {response.status_code}"
            except (httpx.HTTPError, ValueError) as error:
                last_error = type(error).__name__
            time.sleep(1.0)
    raise AssertionError(f"Docmost v0.95.0 fixture did not become ready: {last_error}")


def _setup_admin(base_url: str) -> str:
    with httpx.Client(
        base_url=base_url,
        follow_redirects=False,
        trust_env=False,
        timeout=20.0,
    ) as client:
        response = client.post(
            "/api/auth/setup",
            json={
                "name": "Contract Admin",
                "email": "contract-admin@example.test",
                "password": "contract-only-password",
                "workspaceName": "Contract Workspace",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["status"] == 200
        cookie = client.cookies.get("authToken")
        assert cookie
        return cookie


@pytest.fixture(scope="session")
def contract_instance() -> Iterator[ContractInstance]:
    """Launch and exactly tear down one isolated Compose project."""

    if os.environ.get("DOCMOST_RUN_CONTRACT_TESTS") != "1":
        pytest.skip("set DOCMOST_RUN_CONTRACT_TESTS=1 to launch the v0.95.0 contract stack")
    if shutil.which("docker") is None:
        pytest.fail("Docker is required for Docmost contract tests")

    project = f"docmost-v095-{os.getpid()}-{secrets.token_hex(4)}"
    port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = {**os.environ, "DOCMOST_CONTRACT_PORT": str(port)}
    try:
        started = _compose(project, environment, "up", "--detach", "--wait")
        if started.returncode != 0:
            pytest.fail(
                "Docmost v0.95.0 Compose startup failed:\n"
                f"{started.stdout}\n{started.stderr}"
            )
        _wait_until_ready(base_url)
        yield ContractInstance(
            base_url=base_url,
            session_cookie=_setup_admin(base_url),
        )
    finally:
        stopped = _compose(
            project,
            environment,
            "down",
            "--volumes",
            "--remove-orphans",
            timeout=180.0,
        )
        if stopped.returncode != 0:
            pytest.fail(
                "Docmost contract project teardown failed:\n"
                f"{stopped.stdout}\n{stopped.stderr}"
            )


def test_v095_reads_and_safe_writes(contract_instance: ContractInstance) -> None:
    """Exercise every v1 read and safe-write operation against v0.95.0."""

    settings = DocmostSettings.model_validate(
        {
            "base_url": contract_instance.base_url,
            "write_profile": "v0_95",
        }
    )
    unique = secrets.token_hex(5)
    root_title = f"Contract Root {unique}"
    child_title = f"Contract Child {unique}"
    pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    with (
        tempfile.TemporaryDirectory(
            prefix="docmost-contract-",
            dir=Path.home(),
        ) as staging_directory,
        DocmostReadClient(settings, contract_instance.session_cookie) as client,
    ):
        pdf_path = Path(staging_directory) / f"contract-{unique}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        version = client.version()
        assert version.ok is True and version.data is not None
        assert version.data.current_version == "0.95.0"

        current_user = client.current_user()
        assert current_user.ok is True and current_user.data is not None
        assert current_user.data.user.email == "contract-admin@example.test"

        spaces = client.list_spaces()
        assert spaces.ok is True and spaces.data is not None
        assert spaces.data.items
        space = spaces.data.items[0]
        space_readback = client.get_space(space.id)
        assert space_readback.ok is True and space_readback.data is not None
        assert space_readback.data.id == space.id

        root = client.create_page(space.id, root_title, f"Root **body {unique}**")
        assert root.ok is True and root.data is not None
        assert root.data.partial_success is False
        root_page = client.get_page(root.data.page.id)
        assert root_page.ok is True and root_page.data is not None
        assert root_page.data.title == root_title
        assert root_page.data.markdown == f"Root **body {unique}**"

        roots = client.list_pages(space.id)
        assert roots.ok is True and roots.data is not None
        assert root.data.page.id in {page.id for page in roots.data.items}

        search = client.search(unique, space_id=space.id)
        assert search.ok is True and search.data is not None
        assert root.data.page.id in {page.id for page in search.data.items}

        child = client.create_page(
            space.id,
            child_title,
            f"Child body {unique}",
            parent_page_id=root.data.page.id,
        )
        assert child.ok is True and child.data is not None
        assert child.data.partial_success is False
        assert child.data.page.parent == root.data.page.id

        children = client.list_child_pages(root.data.page.id)
        assert children.ok is True and children.data is not None
        assert child.data.page.id in {page.id for page in children.data.items}

        child_content = client.get_page_content(child.data.page.id)
        assert child_content.ok is True and child_content.data is not None
        assert child_content.data.page.updated_at is not None
        attached = client.attach_pdf_to_page(
            child.data.page.id,
            str(pdf_path),
            pdf_sha256,
            child_content.data.page.updated_at,
            child_content.data.content_sha256,
        )
        assert attached.ok is True and attached.data is not None
        assert attached.data.link_status == "linked"
        assert attached.data.attachment.checksum_verified is True
        assert attached.data.attachment.sha256 == pdf_sha256
        assert attached.data.page.updated_at is not None
        assert attached.data.content_sha256 is not None

        repeated = client.attach_pdf_to_page(
            child.data.page.id,
            str(pdf_path),
            pdf_sha256,
            attached.data.page.updated_at,
            attached.data.content_sha256,
        )
        assert repeated.ok is True and repeated.data is not None
        assert repeated.data.link_status == "already_linked"
        assert repeated.data.attachment.id == attached.data.attachment.id

        downloaded = client.download_attachment(
            child.data.page.id,
            attached.data.attachment.id,
        )
        assert downloaded.ok is True and downloaded.data is not None
        try:
            assert downloaded.data.sha256 == pdf_sha256
            assert Path(downloaded.data.local_path).read_bytes() == pdf_bytes
        finally:
            released = client.release_attachment_download(
                downloaded.data.download_token,
            )
            assert released.ok is True and released.data is not None
            assert released.data.released is True

        assert root_page.data.updated_at is not None
        edited = client.edit_page_text(
            root.data.page.id,
            f"body {unique}",
            f"text {unique}",
            root_page.data.updated_at,
        )
        assert edited.ok is True and edited.data is not None
        assert edited.data.replacements == 1
        assert edited.data.page.updated_at is not None
        edited_readback = client.get_page(root.data.page.id)
        assert edited_readback.ok is True and edited_readback.data is not None
        assert edited_readback.data.markdown == f"Root **text {unique}**"

        raw_content = client.get_page_content(root.data.page.id)
        assert raw_content.ok is True and raw_content.data is not None
        assert raw_content.data.page.updated_at is not None
        expected_document = cast(dict[str, object], deepcopy(raw_content.data.content))
        expected_blocks = expected_document.get("content")
        assert isinstance(expected_blocks, list)
        first_block = cast(list[object], expected_blocks)[0]
        assert isinstance(first_block, dict)
        first_block_content = cast(dict[str, object], first_block).get("content")
        assert isinstance(first_block_content, list)
        red_text: dict[str, object] = {
            "type": "text",
            "text": f" Red review {unique}",
            "marks": [
                {"type": "textStyle", "attrs": {"color": "#ff0000"}}
            ],
        }
        cast(list[object], first_block_content).append(red_text)
        raw_patch: list[object] = [
            {"op": "add", "path": "/content/0/content/-", "value": red_text}
        ]
        rich_patch = client.patch_page_content(
            root.data.page.id,
            validate_patch_operations(raw_patch),
            raw_content.data.page.updated_at,
            raw_content.data.content_sha256,
        )
        if not rich_patch.ok:
            ambiguous_readback = client.get_page_content(root.data.page.id)
            pytest.fail(
                "rich patch outcome was ambiguous; "
                f"error={rich_patch.error!r}, expected={expected_document!r}, "
                f"readback={ambiguous_readback!r}"
            )
        assert rich_patch.data is not None
        assert rich_patch.data.operations_applied == 1
        rich_readback = client.get_page_content(root.data.page.id)
        assert rich_readback.ok is True and rich_readback.data is not None
        assert rich_readback.data.content == expected_document
        assert rich_readback.data.content_sha256 == rich_patch.data.content_sha256

        assert rich_patch.data.page.updated_at is not None
        renamed = client.update_page_title(
            root.data.page.id,
            f"Renamed Root {unique}",
            rich_patch.data.page.updated_at,
        )
        assert renamed.ok is True and renamed.data is not None
        assert renamed.data.title == f"Renamed Root {unique}"

        comment = client.create_comment(
            root.data.page.id,
            f"Contract **comment** `{unique}`",
        )
        assert comment.ok is True and comment.data is not None
        comments = client.list_comments(root.data.page.id)
        assert comments.ok is True and comments.data is not None
        assert comment.data.id in {item.id for item in comments.data.items}
