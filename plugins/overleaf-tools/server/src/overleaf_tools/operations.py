"""MCP-facing operations over secrets-backed project bindings."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from overleaf_tools.config import ConfigStore, ProjectConfig
from overleaf_tools.errors import ErrorCode, OverleafError, failure, success
from overleaf_tools.git_client import GitProject, TreeEntry, validate_revision
from overleaf_tools.latex import extract_outline
from overleaf_tools.permissions import assert_private


class ProjectRepository(Protocol):
    def status(self) -> dict[str, Any]: ...
    def list_files(self) -> tuple[str, list[TreeEntry]]: ...
    def read_text(self, path: str) -> dict[str, Any]: ...

    def write_text(
        self,
        *,
        path: str,
        content: str,
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]: ...

    def edit_text(
        self,
        *,
        path: str,
        old_text: str,
        new_text: str,
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]: ...

    def import_file(
        self,
        *,
        source_path: str,
        source_sha256: str,
        destination_path: str,
        allowed_roots: tuple[Path, ...],
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]: ...

    def move_file(
        self,
        *,
        source_path: str,
        destination_path: str,
        expected_revision: str,
        expected_source_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]: ...

    def delete_file(
        self,
        *,
        path: str,
        expected_revision: str,
        expected_blob_sha: str,
        commit_message: str,
    ) -> dict[str, Any]: ...
    def reconcile(self, candidate_commit: str) -> dict[str, Any]: ...


RepositoryFactory = Callable[[ProjectConfig, Path], ProjectRepository]


def _default_repository(project: ProjectConfig, root: Path) -> ProjectRepository:
    return GitProject(project=project, private_root=root)


class Operations:
    def __init__(
        self,
        *,
        store: ConfigStore | None = None,
        repository_factory: RepositoryFactory = _default_repository,
    ) -> None:
        self._configured_store = store
        self._repository_factory = repository_factory

    def _store(self) -> ConfigStore:
        return self._configured_store or ConfigStore()

    def _safe(
        self, operation: Callable[[], dict[str, Any]], *, outcome: str = "read"
    ) -> dict[str, Any]:
        try:
            return success(operation(), outcome=outcome)
        except OverleafError as error:
            return failure(error)
        except (OSError, UnicodeError, ValueError):
            return failure(
                OverleafError(
                    ErrorCode.REMOTE_UNAVAILABLE,
                    "The operation failed safely; private details were withheld.",
                )
            )

    def _project(self, alias: str) -> tuple[ProjectRepository, tuple[Path, ...]]:
        store = self._store()
        config, project = store.project(alias)
        return self._repository_factory(project, store.root), config.allowed_import_roots

    def configuration_status(self) -> dict[str, Any]:
        def inspect() -> dict[str, Any]:
            try:
                store = self._store()
                config = store.load()
            except OverleafError as error:
                return {
                    "configured": False,
                    "errorCode": error.code.value,
                    "tokenValuesReported": False,
                }
            configured_tokens = 0
            for project in config.projects.values():
                try:
                    assert_private(project.token_path, directory=False)
                    configured_tokens += 1
                except OverleafError:
                    pass
            return {
                "configured": True,
                "projectCount": len(config.projects),
                "configuredTokenCount": configured_tokens,
                "allowedImportRootCount": len(config.allowed_import_roots),
                "tokenValuesReported": False,
            }

        return self._safe(inspect)

    def list_projects(self) -> dict[str, Any]:
        def list_configured() -> dict[str, Any]:
            config = self._store().load()
            projects: list[dict[str, Any]] = []
            for alias, project in sorted(config.projects.items()):
                token_configured = False
                try:
                    assert_private(project.token_path, directory=False)
                    token_configured = True
                except OverleafError:
                    pass
                projects.append(
                    {
                        "alias": alias,
                        "displayName": project.display_name,
                        "tokenConfigured": token_configured,
                    }
                )
            return {"projects": projects, "tokenValuesReported": False}

        return self._safe(list_configured)

    def get_project_status(self, project: str) -> dict[str, Any]:
        return self._safe(lambda: self._project(project)[0].status())

    def list_files(self, project: str, *, limit: int, cursor: str | None) -> dict[str, Any]:
        def list_page() -> dict[str, Any]:
            repository, _roots = self._project(project)
            revision, entries = repository.list_files()
            if cursor is None:
                offset = 0
            else:
                try:
                    cursor_revision, raw_offset = cursor.rsplit(":", 1)
                    validate_revision(cursor_revision)
                    if not raw_offset.isascii() or not raw_offset.isdigit():
                        raise ValueError
                    offset = int(raw_offset)
                except (OverleafError, ValueError) as exc:
                    raise OverleafError(
                        ErrorCode.INVALID_ARGUMENT, "The file cursor is invalid."
                    ) from exc
                if cursor_revision.lower() != revision:
                    raise OverleafError(
                        ErrorCode.STALE_REVISION,
                        "The project changed between file-list pages.",
                        outcome="stale",
                        data={"remoteRevision": revision},
                    )
            if offset > len(entries):
                raise OverleafError(ErrorCode.INVALID_ARGUMENT, "The file cursor is out of range.")
            page = entries[offset : offset + limit]
            next_offset = offset + len(page)
            return {
                "project": project,
                "revision": revision,
                "files": [
                    {
                        "path": entry.path,
                        "blobSha": entry.blob_sha,
                        "size": entry.size,
                        "kind": "text" if entry.is_text else "binary",
                    }
                    for entry in page
                ],
                "nextCursor": (f"{revision}:{next_offset}" if next_offset < len(entries) else None),
            }

        return self._safe(list_page)

    def read_text_file(self, project: str, path: str) -> dict[str, Any]:
        return self._safe(lambda: self._project(project)[0].read_text(path))

    def get_outline(self, project: str, path: str) -> dict[str, Any]:
        def outline() -> dict[str, Any]:
            data = self._project(project)[0].read_text(path)
            return {
                "project": project,
                "path": path,
                "revision": data["revision"],
                "blobSha": data["blobSha"],
                "headings": extract_outline(str(data["content"])),
            }

        return self._safe(outline)

    def reconcile_commit(self, project: str, candidate_commit: str) -> dict[str, Any]:
        def reconcile() -> dict[str, Any]:
            return self._project(project)[0].reconcile(candidate_commit)

        result = self._safe(reconcile)
        if result["ok"]:
            result["outcome"] = "committed" if result["data"]["committed"] else "not_committed"
        return result

    def edit_text_file(self, project: str, **kwargs: Any) -> dict[str, Any]:
        return self._safe(
            lambda: self._project(project)[0].edit_text(**kwargs), outcome="committed"
        )

    def write_text_file(self, project: str, **kwargs: Any) -> dict[str, Any]:
        return self._safe(
            lambda: self._project(project)[0].write_text(**kwargs), outcome="committed"
        )

    def import_file(self, project: str, **kwargs: Any) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            repository, roots = self._project(project)
            return repository.import_file(allowed_roots=roots, **kwargs)

        return self._safe(run, outcome="committed")

    def move_file(self, project: str, **kwargs: Any) -> dict[str, Any]:
        return self._safe(
            lambda: self._project(project)[0].move_file(**kwargs), outcome="committed"
        )

    def delete_file(self, project: str, **kwargs: Any) -> dict[str, Any]:
        return self._safe(
            lambda: self._project(project)[0].delete_file(**kwargs), outcome="committed"
        )
