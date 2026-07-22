from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "paper-library-intake"
    / "SKILL.md"
)
OPENAI_METADATA = SKILL.parent / "agents" / "openai.yaml"
RESEARCH_MCP = ROOT / "plugins" / "research-tools" / ".mcp.json"
RESEARCH_PLUGIN = ROOT / "plugins" / "research-tools" / ".codex-plugin" / "plugin.json"
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
README = ROOT / "README.md"
RESEARCH_LLM_WIKI = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "research-llm-wiki"
    / "SKILL.md"
)
SETUP_CHECKER = ROOT / "scripts" / "check-codex-toolbox-setup.py"
HELPER = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "paper-library-intake"
    / "scripts"
    / "zotero_attachment.py"
)

SPEC = importlib.util.spec_from_file_location("paper_library_zotero_attachment", HELPER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load helper from {HELPER}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def webdav_env() -> dict[str, str]:
    return {
        "ZOTERO_WEBDAV_URL": "https://app.koofr.net/dav/Koofr/Zotero/",
        "ZOTERO_WEBDAV_USERNAME": "private-user",
        "ZOTERO_WEBDAV_PASSWORD": "private-password",
        "ZOTERO_LIBRARY_ID": "1234567",
        "ZOTERO_LIBRARY_TYPE": "user",
        "ZOTERO_API_KEY": "private-api-key",
    }


def zotero_cloud_env() -> dict[str, str]:
    return {
        "ZOTERO_LIBRARY_ID": "1234567",
        "ZOTERO_LIBRARY_TYPE": "user",
        "ZOTERO_API_KEY": "private-api-key",
    }


def attachment(key: str, parent: str, filename: str, **metadata: object) -> dict:
    data = {
        "itemType": "attachment",
        "linkMode": "imported_file",
        "parentItem": parent,
        "filename": filename,
        "title": filename,
        "contentType": "application/pdf",
    }
    data.update(metadata)
    return {"key": key, "data": data}


class FakeClient:
    def __init__(self, children: list[dict] | None = None) -> None:
        self.events: list[tuple] = []
        self.children_data = list(children or [])
        self.created_payloads: list[dict] = []
        self.create_count = 0

    def item(self, key: str) -> dict:
        self.events.append(("item", key))
        if key == "PARENT01":
            return {"key": key, "data": {"itemType": "journalArticle"}}
        for child in self.children_data:
            if child["key"] == key:
                return child
        raise KeyError(key)

    def children(self, parent_key: str) -> list[dict]:
        self.events.append(("children", parent_key))
        return self.children_data

    def item_template(self, item_type: str, linkmode: str | None = None) -> dict:
        self.events.append(("template", item_type, linkmode))
        return {"itemType": item_type, "linkMode": linkmode}

    def create_items(self, payloads: list[dict]) -> dict:
        self.events.append(("create",))
        self.create_count += 1
        payload = dict(payloads[0])
        self.created_payloads.append(payload)
        child = {"key": "ATTACH01", "data": payload}
        self.children_data.append(child)
        return {"success": {"0": "ATTACH01"}, "unchanged": {}, "failed": {}}

    def update_item(self, item: dict) -> object:
        self.events.append(("update", item["key"]))
        for index, child in enumerate(self.children_data):
            if child["key"] == item["key"]:
                self.children_data[index] = item
                break
        return FakeResponse()

    def upload_attachments(
        self, payloads: list[dict], parentid: str | None = None, basedir: Path | None = None
    ) -> dict:
        self.events.append(("cloud-upload", payloads[0]["key"]))
        return {"success": payloads, "failure": [], "unchanged": []}


class FakeResponse:
    status_code = 204

    def raise_for_status(self) -> None:
        return None


class PaperLibraryAttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.pdf = self.root / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\n" + b"0" * 2048 + b"\n%%EOF\n")

    @staticmethod
    def parser(_path: Path) -> int:
        return 3

    @staticmethod
    def preflight(_env: dict[str, str]) -> None:
        return None

    def test_detects_webdav_without_exposing_credentials(self) -> None:
        env = webdav_env()

        result = MODULE.detect_storage(env)
        rendered = json.dumps(result)

        self.assertEqual(result["backend"], "webdav")
        self.assertEqual(result["provider"], "koofr")
        for secret in env.values():
            self.assertNotIn(secret, rendered)

    def test_detects_zotero_cloud_when_all_webdav_variables_are_absent(self) -> None:
        result = MODULE.detect_storage(
            {
                "ZOTERO_LIBRARY_ID": "1234567",
                "ZOTERO_LIBRARY_TYPE": "user",
                "ZOTERO_API_KEY": "private-api-key",
            }
        )

        self.assertEqual(
            result,
            {"backend": "zotero-cloud", "configured": True, "provider": "zotero"},
        )

    def test_partial_webdav_configuration_is_blocking_and_redacted(self) -> None:
        result = MODULE.detect_storage(
            {
                "ZOTERO_WEBDAV_URL": "https://example.invalid/private/",
                "ZOTERO_WEBDAV_USERNAME": "private-user",
            }
        )

        self.assertEqual(result["backend"], "incomplete")
        self.assertFalse(result["configured"])
        self.assertEqual(result["missing"], ["ZOTERO_WEBDAV_PASSWORD"])
        self.assertNotIn("example.invalid", json.dumps(result))
        self.assertNotIn("private-user", json.dumps(result))

    def test_partial_configuration_blocks_before_file_or_client_access(self) -> None:
        env = {"ZOTERO_WEBDAV_URL": "https://example.invalid/private/"}

        with self.assertRaisesRegex(MODULE.IntakeError, "incomplete_webdav_configuration"):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                file_path=self.root / "missing.pdf",
                env=env,
                client_factory=lambda _env: self.fail("client must not be constructed"),
                preflight_fn=lambda _env: self.fail("preflight must not run"),
                parser_fn=self.parser,
            )

    def test_validate_pdf_rejects_html_and_unparseable_content(self) -> None:
        html = self.root / "fake.pdf"
        html.write_bytes(b"<html>not a pdf</html>" + b" " * 2048)

        with self.assertRaisesRegex(MODULE.IntakeError, "invalid_pdf_magic"):
            MODULE.validate_pdf(html, parser_fn=self.parser)
        with self.assertRaisesRegex(MODULE.IntakeError, "unparseable_pdf"):
            MODULE.validate_pdf(
                self.pdf,
                parser_fn=lambda _path: (_ for _ in ()).throw(ValueError("bad pdf")),
            )

    def test_validate_pdf_enforces_bounds_and_rejects_symlinks(self) -> None:
        small = self.root / "small.pdf"
        small.write_bytes(b"%PDF-1.7\n%%EOF\n")
        symlink = self.root / "linked.pdf"
        symlink.symlink_to(self.pdf)

        with self.assertRaisesRegex(MODULE.IntakeError, "pdf_too_small"):
            MODULE.validate_pdf(small, parser_fn=self.parser)
        with self.assertRaisesRegex(MODULE.IntakeError, "pdf_too_large"):
            MODULE.validate_pdf(self.pdf, parser_fn=self.parser, max_bytes=100)
        with self.assertRaisesRegex(MODULE.IntakeError, "symlink_not_allowed"):
            MODULE.validate_pdf(symlink, parser_fn=self.parser)

    def test_new_attachment_uses_metadata_first_then_webdav_and_verifies(self) -> None:
        client = FakeClient()
        events = client.events

        def upload(key: str, file_path: Path, md5: str, mtime_ms: int) -> tuple[str, int]:
            events.append(("upload", key, file_path.name))
            return md5, mtime_ms

        def download(key: str, destination: Path, expected_filename: str) -> Path:
            events.append(("download", key, expected_filename))
            output = destination / expected_filename
            output.write_bytes(self.pdf.read_bytes())
            return output

        result = MODULE.attach_webdav(
            parent_key="PARENT01",
            file_path=self.pdf,
            env=webdav_env(),
            client=client,
            preflight_fn=lambda _env: events.append(("preflight",)),
            upload_fn=upload,
            download_fn=download,
            parser_fn=self.parser,
        )

        names = [event[0] for event in events]
        self.assertEqual(
            names,
            [
                "preflight",
                "item",
                "children",
                "template",
                "create",
                "children",
                "upload",
                "item",
                "update",
                "item",
                "download",
            ],
        )
        payload = client.created_payloads[0]
        self.assertEqual(payload["parentItem"], "PARENT01")
        self.assertEqual(payload["linkMode"], "imported_file")
        self.assertEqual(payload["filename"], "paper.pdf")
        self.assertEqual(payload["contentType"], "application/pdf")
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["backend"], "webdav")
        self.assertEqual(result["parent_key"], "PARENT01")
        self.assertEqual(result["attachment_key"], "ATTACH01")
        self.assertEqual(result["basename"], "paper.pdf")
        self.assertEqual(result["pages"], 3)
        self.assertEqual(result["md5"], hashlib.md5(self.pdf.read_bytes()).hexdigest())
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_retry_after_partial_upload_reuses_the_same_child_key(self) -> None:
        client = FakeClient()
        attempts: list[str] = []

        def upload(key: str, _file: Path, md5: str, mtime_ms: int) -> tuple[str, int]:
            attempts.append(key)
            if len(attempts) == 1:
                raise RuntimeError("prop upload failed at a private URL")
            return md5, mtime_ms

        def download(_key: str, destination: Path, expected_filename: str) -> Path:
            output = destination / expected_filename
            output.write_bytes(self.pdf.read_bytes())
            return output

        kwargs = {
            "parent_key": "PARENT01",
            "file_path": self.pdf,
            "env": webdav_env(),
            "client": client,
            "preflight_fn": self.preflight,
            "upload_fn": upload,
            "download_fn": download,
            "parser_fn": self.parser,
        }

        with self.assertRaises(MODULE.AttachmentMutationError) as raised:
            MODULE.attach_webdav(**kwargs)
        self.assertEqual(raised.exception.attachment_key, "ATTACH01")
        self.assertEqual(raised.exception.stage, "webdav-upload")
        result = MODULE.attach_webdav(**kwargs)

        self.assertEqual(client.create_count, 1)
        self.assertEqual(attempts, ["ATTACH01", "ATTACH01"])
        self.assertEqual(result["attachment_key"], "ATTACH01")
        self.assertEqual(result["status"], "repaired")

    def test_webdav_recovers_child_key_when_create_commits_then_times_out(self) -> None:
        class CommitThenTimeoutClient(FakeClient):
            def create_items(self, payloads: list[dict]) -> dict:
                super().create_items(payloads)
                raise TimeoutError("response lost after commit")

        client = CommitThenTimeoutClient()

        def download(_key: str, destination: Path, expected_filename: str) -> Path:
            output = destination / expected_filename
            output.write_bytes(self.pdf.read_bytes())
            return output

        result = MODULE.attach_webdav(
            parent_key="PARENT01",
            file_path=self.pdf,
            env=webdav_env(),
            client=client,
            preflight_fn=self.preflight,
            upload_fn=lambda _key, _file, md5, mtime_ms: (md5, mtime_ms),
            download_fn=download,
            parser_fn=self.parser,
        )

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["attachment_key"], "ATTACH01")
        self.assertEqual(client.create_count, 1)

    def test_create_rejection_never_adopts_concurrent_foreign_child(self) -> None:
        class RejectedCreateClient(FakeClient):
            def create_items(self, payloads: list[dict]) -> dict:
                self.create_count += 1
                self.children_data.append(
                    attachment("ATTACH99", "PARENT01", "paper.pdf", md5="0" * 32)
                )
                return {"success": {}, "failed": {"0": {"message": "rejected"}}}

        client = RejectedCreateClient()

        with self.assertRaisesRegex(MODULE.IntakeError, "attachment_metadata_create_failed"):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=self.preflight,
                upload_fn=lambda *_args: self.fail("must not upload a foreign child"),
                parser_fn=self.parser,
            )

        self.assertEqual(client.create_count, 1)

    def test_lost_create_response_requires_our_correlation_marker(self) -> None:
        class ForeignCommitClient(FakeClient):
            def create_items(self, payloads: list[dict]) -> dict:
                self.create_count += 1
                self.children_data.append(attachment("ATTACH99", "PARENT01", "paper.pdf"))
                raise TimeoutError("our response was lost while another host created a child")

        client = ForeignCommitClient()

        with self.assertRaisesRegex(
            MODULE.IntakeError, "attachment_metadata_create_outcome_unknown"
        ):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=self.preflight,
                upload_fn=lambda *_args: self.fail("must not upload a foreign child"),
                parser_fn=self.parser,
            )

        self.assertEqual(client.create_count, 1)

    def test_matching_healthy_attachment_is_unchanged(self) -> None:
        digest = hashlib.md5(self.pdf.read_bytes()).hexdigest()
        client = FakeClient(
            [attachment("ATTACH02", "PARENT01", "paper.pdf", md5=digest, mtime=123)]
        )
        uploaded: list[str] = []

        def download(_key: str, destination: Path, expected_filename: str) -> Path:
            output = destination / expected_filename
            output.write_bytes(self.pdf.read_bytes())
            return output

        result = MODULE.attach_webdav(
            parent_key="PARENT01",
            file_path=self.pdf,
            env=webdav_env(),
            client=client,
            preflight_fn=self.preflight,
            upload_fn=lambda key, *_args: uploaded.append(key),
            download_fn=download,
            parser_fn=self.parser,
        )

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["attachment_key"], "ATTACH02")
        self.assertEqual(result["mtime"], 123)
        self.assertEqual(uploaded, [])
        self.assertEqual(client.create_count, 0)

    def test_duplicate_matching_children_are_ambiguous_without_explicit_key(self) -> None:
        client = FakeClient(
            [
                attachment("ATTACH02", "PARENT01", "paper.pdf"),
                attachment("ATTACH03", "PARENT01", "paper.pdf"),
            ]
        )

        with self.assertRaisesRegex(MODULE.IntakeError, "ambiguous_attachment_children"):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=self.preflight,
                upload_fn=lambda *_args: self.fail("must not upload"),
                parser_fn=self.parser,
            )

    def test_explicit_attachment_key_must_belong_to_parent(self) -> None:
        client = FakeClient([attachment("ATTACH02", "PARENT01", "other.pdf")])

        with self.assertRaisesRegex(MODULE.IntakeError, "attachment_not_child_of_parent"):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                attachment_key="ATTACH03",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=self.preflight,
                upload_fn=lambda *_args: self.fail("must not upload"),
                parser_fn=self.parser,
            )

    def test_explicit_attachment_key_rejects_non_imported_file_children(self) -> None:
        linked = attachment("ATTACH02", "PARENT01", "paper.pdf")
        linked["data"].update({"linkMode": "linked_url", "url": "https://example.org/paper"})
        client = FakeClient([linked])

        with self.assertRaisesRegex(MODULE.IntakeError, "attachment_not_imported_file_pdf"):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                attachment_key="ATTACH02",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=self.preflight,
                upload_fn=lambda *_args: self.fail("must not upload"),
                parser_fn=self.parser,
            )

    def test_same_basename_with_different_checksum_is_not_overwritten(self) -> None:
        client = FakeClient(
            [attachment("ATTACH02", "PARENT01", "paper.pdf", md5="0" * 32, mtime=123)]
        )

        with self.assertRaisesRegex(MODULE.IntakeError, "attachment_checksum_conflict"):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=self.preflight,
                upload_fn=lambda *_args: self.fail("must not upload"),
                parser_fn=self.parser,
            )

        self.assertEqual(client.create_count, 0)

    def test_explicit_attachment_key_repairs_same_record_and_filename(self) -> None:
        digest = hashlib.md5(self.pdf.read_bytes()).hexdigest()
        client = FakeClient(
            [attachment("ATTACH02", "PARENT01", "old-name.pdf", md5=digest, mtime=123)]
        )

        def download(_key: str, destination: Path, expected_filename: str) -> Path:
            output = destination / expected_filename
            output.write_bytes(self.pdf.read_bytes())
            return output

        result = MODULE.attach_webdav(
            parent_key="PARENT01",
            attachment_key="ATTACH02",
            file_path=self.pdf,
            env=webdav_env(),
            client=client,
            preflight_fn=self.preflight,
            upload_fn=lambda _key, _file, md5, mtime_ms: (md5, mtime_ms),
            download_fn=download,
            parser_fn=self.parser,
        )

        self.assertEqual(result["status"], "repaired")
        self.assertEqual(result["attachment_key"], "ATTACH02")
        self.assertEqual(client.children_data[0]["data"]["filename"], "paper.pdf")
        self.assertEqual(client.create_count, 0)

    def test_parent_and_attachment_keys_are_strictly_validated(self) -> None:
        for key in ("../BAD!!", "short", "lowerabc"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(MODULE.IntakeError, "invalid_zotero_key"):
                    MODULE.attach_webdav(
                        parent_key=key,
                        file_path=self.pdf,
                        env=webdav_env(),
                        preflight_fn=self.preflight,
                        parser_fn=self.parser,
                    )

    def test_webdav_preflight_failure_blocks_before_zotero_mutation(self) -> None:
        client = FakeClient()

        def fail_preflight(_env: dict[str, str]) -> None:
            raise MODULE.IntakeError("webdav_preflight_failed")

        with self.assertRaisesRegex(MODULE.IntakeError, "webdav_preflight_failed"):
            MODULE.attach_webdav(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=fail_preflight,
                parser_fn=self.parser,
            )

        self.assertEqual(client.events, [])

    def test_cli_redacts_unexpected_credential_bearing_errors_and_paths(self) -> None:
        output = io.StringIO()
        secret_error = RuntimeError("https://private-user:private-password@example.invalid/dav")
        with mock.patch.object(MODULE, "_reexec_with_zotero_runtime"), mock.patch.object(
            MODULE, "attach_webdav", side_effect=secret_error
        ), redirect_stdout(output):
            return_code = MODULE.main(
                ["attach", "--parent-key", "PARENT01", "--file", str(self.pdf)]
            )

        rendered = output.getvalue()
        self.assertEqual(return_code, 1)
        self.assertIn("attachment_operation_failed", rendered)
        for forbidden in ("private-user", "private-password", "example.invalid", str(self.root)):
            self.assertNotIn(forbidden, rendered)

    def test_cli_incomplete_receipt_preserves_safe_retry_key(self) -> None:
        output = io.StringIO()
        error = MODULE.AttachmentMutationError(
            "webdav_upload_failed",
            parent_key="PARENT01",
            attachment_key="ATTACH01",
            basename="paper.pdf",
            stage="webdav-upload",
        )
        with mock.patch.object(MODULE, "_reexec_with_zotero_runtime"), mock.patch.object(
            MODULE, "attach_webdav", side_effect=error
        ), redirect_stdout(output):
            return_code = MODULE.main(
                ["attach", "--parent-key", "PARENT01", "--file", str(self.pdf)]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(return_code, 1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["attachment_key"], "ATTACH01")
        self.assertEqual(result["stage"], "webdav-upload")
        self.assertNotIn(str(self.root), output.getvalue())

    def test_cli_detect_preflights_webdav_before_reporting_ready(self) -> None:
        output = io.StringIO()
        events: list[str] = []
        with mock.patch.dict(os.environ, webdav_env(), clear=True), mock.patch.object(
            MODULE,
            "_reexec_with_zotero_runtime",
            side_effect=lambda _argv: events.append("runtime"),
        ), mock.patch.object(
            MODULE,
            "_preflight_webdav",
            side_effect=lambda _env: events.append("preflight"),
        ), redirect_stdout(output):
            return_code = MODULE.main(["detect"])

        result = json.loads(output.getvalue())
        self.assertEqual(return_code, 0)
        self.assertEqual(events, ["runtime", "preflight"])
        self.assertEqual(result["backend"], "webdav")
        self.assertTrue(result["reachable"])

    def test_webdav_preflight_requires_dav_multistatus_not_redirect_or_html(self) -> None:
        class Response:
            def __init__(self, status: int, content: bytes) -> None:
                self.status_code = status
                self.headers = {"Content-Length": str(len(content))}
                self._content = content

            def iter_content(self, chunk_size: int) -> object:
                del chunk_size
                yield self._content

        class Session:
            def __init__(self, response: Response) -> None:
                self.response = response

            def request(self, *_args: object, **_kwargs: object) -> Response:
                return self.response

            def close(self) -> None:
                return None

        valid_xml = (
            b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/Koofr/Zotero/</d:href>'
            b'<d:propstat><d:status>HTTP/1.1 200 OK</d:status></d:propstat>'
            b'</d:response></d:multistatus>'
        )
        forbidden_xml = (
            b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/Koofr/Zotero/</d:href>'
            b'<d:propstat><d:status>HTTP/1.1 403 Forbidden</d:status></d:propstat>'
            b'</d:response></d:multistatus>'
        )
        MODULE._preflight_webdav(
            webdav_env(), session_factory=lambda _env: Session(Response(207, valid_xml))
        )
        for response in (
            Response(200, b"<html>login</html>"),
            Response(302, valid_xml),
            Response(207, b'<d:multistatus xmlns:d="DAV:"/>'),
            Response(207, forbidden_xml),
        ):
            with self.subTest(status=response.status_code):
                with self.assertRaisesRegex(
                    MODULE.IntakeError, "invalid_webdav_preflight_response"
                ):
                    MODULE._preflight_webdav(
                        webdav_env(), session_factory=lambda _env, value=response: Session(value)
                    )

    def test_webdav_endpoint_normalizes_one_trailing_separator(self) -> None:
        env = webdav_env()
        env["ZOTERO_WEBDAV_URL"] = env["ZOTERO_WEBDAV_URL"].rstrip("/")

        endpoint = MODULE._webdav_endpoint(env)

        self.assertEqual(endpoint, "https://app.koofr.net/dav/Koofr/Zotero/")

    def test_webdav_preflight_streams_and_rejects_oversize_before_buffering(self) -> None:
        class OversizeResponse:
            status_code = 207
            headers = {"Content-Length": str(1024 * 1024 + 1)}

            def iter_content(self, chunk_size: int) -> object:
                self.fail(f"must reject content length before reading {chunk_size}")
                yield b""

        request_kwargs: dict[str, object] = {}

        class Session:
            def request(self, *_args: object, **kwargs: object) -> OversizeResponse:
                request_kwargs.update(kwargs)
                return OversizeResponse()

            def close(self) -> None:
                return None

        with self.assertRaisesRegex(MODULE.IntakeError, "invalid_webdav_preflight_response"):
            MODULE._preflight_webdav(webdav_env(), session_factory=lambda _env: Session())

        self.assertIs(request_kwargs.get("stream"), True)

    def test_parent_lock_is_stable_across_basenames_for_one_attachment_key(self) -> None:
        opened: list[Path] = []
        real_open = os.open

        def recording_open(path: object, flags: int, mode: int) -> int:
            opened.append(Path(path))
            return real_open(path, flags, mode)

        with mock.patch.object(MODULE.os, "open", side_effect=recording_open):
            with MODULE._attachment_lock(webdav_env(), "PARENT01", "first.pdf"):
                pass
            with MODULE._attachment_lock(webdav_env(), "PARENT01", "second.pdf"):
                pass

        self.assertEqual(opened[0], opened[1])

    def test_metadata_update_requires_response_and_readback(self) -> None:
        class NoResponseClient(FakeClient):
            def update_item(self, item: dict) -> object:
                super().update_item(item)
                return object()

        client = NoResponseClient()

        with self.assertRaises(MODULE.AttachmentMutationError) as raised:
            MODULE.attach_webdav(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                preflight_fn=self.preflight,
                upload_fn=lambda _key, _file, md5, mtime_ms: (md5, mtime_ms),
                download_fn=lambda *_args: self.fail("verification must not run"),
                parser_fn=self.parser,
            )

        self.assertEqual(raised.exception.code, "zotero_metadata_update_failed")
        self.assertEqual(raised.exception.attachment_key, "ATTACH01")
        self.assertEqual(raised.exception.stage, "zotero-metadata")

    def test_bounded_zip_extraction_rejects_oversize_and_unsafe_members(self) -> None:
        oversize = self.root / "oversize.zip"
        with zipfile.ZipFile(oversize, "w") as archive:
            archive.writestr("paper.pdf", b"%PDF-1.7\n" + b"0" * 512)
        unsafe = self.root / "unsafe.zip"
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("../paper.pdf", self.pdf.read_bytes())

        with self.assertRaisesRegex(MODULE.IntakeError, "webdav_archive_too_large"):
            MODULE.extract_bounded_webdav_zip(
                oversize,
                self.root / "out-one",
                expected_filename="paper.pdf",
                max_bytes=100,
            )
        with self.assertRaisesRegex(MODULE.IntakeError, "unsafe_webdav_archive"):
            MODULE.extract_bounded_webdav_zip(
                unsafe,
                self.root / "out-two",
                expected_filename="paper.pdf",
                max_bytes=10_000,
            )

    def test_upload_uses_private_snapshot_not_mutable_source(self) -> None:
        original = self.pdf.read_bytes()
        client = FakeClient()

        def upload(key: str, staged: Path, md5: str, mtime_ms: int) -> tuple[str, int]:
            self.assertNotEqual(staged, self.pdf)
            self.pdf.write_bytes(b"%PDF-1.7\n" + b"changed" * 400)
            self.assertEqual(staged.read_bytes(), original)
            return md5, mtime_ms

        def download(_key: str, destination: Path, expected_filename: str) -> Path:
            output = destination / expected_filename
            output.write_bytes(original)
            return output

        result = MODULE.attach_webdav(
            parent_key="PARENT01",
            file_path=self.pdf,
            env=webdav_env(),
            client=client,
            preflight_fn=self.preflight,
            upload_fn=upload,
            download_fn=download,
            parser_fn=self.parser,
        )

        self.assertEqual(result["status"], "created")

    def test_official_storage_helper_repairs_existing_child_without_new_parent(self) -> None:
        client = FakeClient([attachment("ATTACH02", "PARENT01", "paper.pdf")])

        result = MODULE.attach_zotero_cloud(
            parent_key="PARENT01",
            attachment_key="ATTACH02",
            file_path=self.pdf,
            env=zotero_cloud_env(),
            client=client,
            parser_fn=self.parser,
        )

        self.assertEqual(result["status"], "repaired")
        self.assertEqual(result["backend"], "zotero-cloud")
        self.assertEqual(result["attachment_key"], "ATTACH02")
        self.assertEqual(result["verification"], "requires_zotero_read_pdf_pages")
        self.assertEqual(client.create_count, 0)
        self.assertIn(("cloud-upload", "ATTACH02"), client.events)

    def test_official_storage_rejects_concurrent_same_name_child_after_create(self) -> None:
        class ConcurrentClient(FakeClient):
            def create_items(self, payloads: list[dict]) -> dict:
                result = super().create_items(payloads)
                self.children_data.append(attachment("ATTACH99", "PARENT01", "paper.pdf"))
                return result

        client = ConcurrentClient()

        with self.assertRaises(MODULE.AttachmentMutationError) as raised:
            MODULE.attach_zotero_cloud(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=zotero_cloud_env(),
                client=client,
                parser_fn=self.parser,
            )

        self.assertEqual(raised.exception.code, "concurrent_attachment_conflict")
        self.assertEqual(raised.exception.attachment_key, "ATTACH01")
        self.assertNotIn(("cloud-upload", "ATTACH01"), client.events)

    def test_official_storage_recovers_child_key_when_create_commits_then_times_out(self) -> None:
        class CommitThenTimeoutClient(FakeClient):
            def create_items(self, payloads: list[dict]) -> dict:
                super().create_items(payloads)
                raise TimeoutError("response lost after commit")

        client = CommitThenTimeoutClient()

        result = MODULE.attach_zotero_cloud(
            parent_key="PARENT01",
            file_path=self.pdf,
            env=zotero_cloud_env(),
            client=client,
            parser_fn=self.parser,
        )

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["attachment_key"], "ATTACH01")
        self.assertEqual(client.create_count, 1)
        self.assertIn(("cloud-upload", "ATTACH01"), client.events)

    def test_official_storage_helper_blocks_when_webdav_is_configured(self) -> None:
        client = FakeClient()

        with self.assertRaisesRegex(MODULE.IntakeError, "zotero_cloud_backend_required"):
            MODULE.attach_zotero_cloud(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=webdav_env(),
                client=client,
                parser_fn=self.parser,
            )

        self.assertEqual(client.events, [])

    def test_official_storage_upload_failure_preserves_retry_key(self) -> None:
        class FailingCloudClient(FakeClient):
            def upload_attachments(
                self,
                payloads: list[dict],
                parentid: str | None = None,
                basedir: Path | None = None,
            ) -> dict:
                self.events.append(("cloud-upload", payloads[0]["key"]))
                raise RuntimeError("quota 413 at a private endpoint")

        client = FailingCloudClient()

        with self.assertRaises(MODULE.AttachmentMutationError) as raised:
            MODULE.attach_zotero_cloud(
                parent_key="PARENT01",
                file_path=self.pdf,
                env=zotero_cloud_env(),
                client=client,
                parser_fn=self.parser,
            )

        self.assertEqual(raised.exception.backend, "zotero-cloud")
        self.assertEqual(raised.exception.attachment_key, "ATTACH01")
        self.assertEqual(raised.exception.stage, "zotero-storage-upload")


class PaperLibrarySkillContractTests(unittest.TestCase):
    def test_skill_declares_read_only_find_and_authorized_add_modes(self) -> None:
        text = SKILL.read_text()

        for expected in (
            "name: paper-library-intake",
            "$paper-library-intake find",
            "$paper-library-intake add",
            "read-only",
            "explicitly authorizes",
            "Do not mutate",
        ):
            self.assertIn(expected, text)

    def test_skill_orders_private_lookup_public_discovery_and_identifier_recheck(self) -> None:
        text = SKILL.read_text()

        self.assertLess(text.index("Search Zotero first"), text.index("Use Firecrawl first"))
        self.assertLess(text.index("Use Firecrawl first"), text.index("Use Paper Search"))
        for expected in (
            "DOI",
            "arXiv",
            "Recheck Zotero",
            'if_exists="file"',
            "create_missing_collections=false",
            "Never merge by title",
            "private Zotero",
        ):
            self.assertIn(expected, text)

    def test_skill_requires_topical_and_readlater_filing_with_bounded_creation(self) -> None:
        text = SKILL.read_text()

        for expected in (
            "Research/ReadLater",
            "full collection paths",
            "overlapping",
            "at most one",
            "Never use the paper title",
            "acronym alone",
            "`MISC`",
            "active and trashed",
            "stop for clarification",
        ):
            self.assertIn(expected, text)

    def test_skill_defines_storage_gates_and_readable_pdf_completion(self) -> None:
        text = SKILL.read_text()

        for expected in (
            "ZOTERO_WEBDAV_URL",
            "ZOTERO_WEBDAV_USERNAME",
            "ZOTERO_WEBDAV_PASSWORD",
            "incomplete",
            "Never fall back",
            'attach_mode="none"',
            'attach_mode="auto"',
            "use_scihub=false",
            "zotero_attachment.py detect",
            "zotero_attachment.py attach",
            "attach-cloud",
            "zotero_read_pdf_pages",
            "metadata-only",
        ):
            self.assertIn(expected, text)

    def test_skill_receipt_and_agent_metadata_are_installed(self) -> None:
        text = SKILL.read_text()
        metadata = OPENAI_METADATA.read_text()

        for expected in (
            "Canonical identity",
            "Zotero status",
            "Filing",
            "Storage",
            "Verification",
            "parent key",
            "attachment key",
        ):
            self.assertIn(expected, text)
        self.assertIn("$paper-library-intake", metadata)

    def test_paper_search_launcher_loads_env_before_root_validation_and_disables_scihub(self) -> None:
        config = json.loads(RESEARCH_MCP.read_text())
        server = config["mcpServers"]["paper_search_mcp"]
        launcher = server["args"][1]

        self.assertLess(launcher.index('source "$SECRET_FILE"'), launcher.index("PAPER_SEARCH_MCP_ROOT"))
        self.assertIn("paper-search-mcp", launcher)
        self.assertIn("download_scihub", server["disabled_tools"])
        self.assertIn("download_with_fallback", server["disabled_tools"])

    def test_research_plugin_minor_version_and_prompts_expose_intake_and_drafts(self) -> None:
        manifest = json.loads(RESEARCH_PLUGIN.read_text())

        self.assertEqual(manifest["version"], "0.3.0")
        prompts = " ".join(manifest["interface"]["defaultPrompt"])
        self.assertIn("$paper-library-intake", prompts)
        self.assertIn("$paper-read-draft", prompts)

    def test_global_routing_readme_wiki_and_checker_expose_one_workflow(self) -> None:
        agents = GLOBAL_AGENTS.read_text()
        readme = README.read_text()
        wiki = RESEARCH_LLM_WIKI.read_text()
        checker = SETUP_CHECKER.read_text()

        for expected in (
            "$paper-library-intake",
            "Zotero first",
            "Firecrawl first",
            "Paper Search",
            "Research/ReadLater",
            "explicit `add`, `save`, or `import`",
        ):
            self.assertIn(expected, agents)
        for expected in (
            "$paper-library-intake find",
            "$paper-library-intake add",
            "PAPER_SEARCH_MCP_ROOT",
            "Koofr/WebDAV",
            "metadata-only",
            "use_scihub=false",
        ):
            self.assertIn(expected, readme)
        self.assertIn("$paper-library-intake", wiki)
        for expected in (
            "PAPER_LIBRARY_INTAKE_SKILL",
            "PAPER_LIBRARY_INTAKE_OPENAI",
            "PAPER_LIBRARY_ATTACHMENT",
            "download_scihub",
            "download_with_fallback",
            "incomplete_webdav_configuration",
            "attach_zotero_cloud",
        ):
            self.assertIn(expected, checker)


if __name__ == "__main__":
    unittest.main()
