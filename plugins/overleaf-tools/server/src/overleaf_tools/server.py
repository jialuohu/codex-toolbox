"""FastMCP surface for guarded Overleaf project operations."""

from __future__ import annotations

import signal
from types import FrameType
from typing import Annotated, Any, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from overleaf_tools.operations import Operations

_READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

Project = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
]
ProjectPath = Annotated[str, Field(min_length=1, max_length=1024)]
Revision = Annotated[str, Field(pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")]
ExpectedBlob = Annotated[
    str,
    Field(pattern=r"^(?:absent|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$"),
]
CommitMessage = Annotated[str, Field(min_length=1, max_length=200)]
TextContent = Annotated[str, Field(max_length=2_097_152)]
EditText = Annotated[str, Field(max_length=2_097_152)]
OldText = Annotated[str, Field(min_length=1, max_length=2_097_152)]
SourcePath = Annotated[str, Field(min_length=1, max_length=4096)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]
Limit = Annotated[int, Field(ge=1, le=500)]
Cursor = Annotated[
    str | None,
    Field(pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64}):[0-9]{1,12}$"),
]


class OperationSurface(Protocol):
    def configuration_status(self) -> dict[str, Any]: ...
    def list_projects(self) -> dict[str, Any]: ...
    def get_project_status(self, project: str) -> dict[str, Any]: ...
    def list_files(self, project: str, *, limit: int, cursor: str | None) -> dict[str, Any]: ...
    def read_text_file(self, project: str, path: str) -> dict[str, Any]: ...
    def get_outline(self, project: str, path: str) -> dict[str, Any]: ...
    def reconcile_commit(self, project: str, candidate_commit: str) -> dict[str, Any]: ...
    def edit_text_file(self, project: str, **kwargs: Any) -> dict[str, Any]: ...
    def write_text_file(self, project: str, **kwargs: Any) -> dict[str, Any]: ...
    def import_file(self, project: str, **kwargs: Any) -> dict[str, Any]: ...
    def move_file(self, project: str, **kwargs: Any) -> dict[str, Any]: ...
    def delete_file(self, project: str, **kwargs: Any) -> dict[str, Any]: ...


def create_server(operations: OperationSurface | None = None) -> FastMCP:
    service = operations or Operations()
    server = FastMCP(name="overleaf")

    @server.tool(name="overleaf_configuration_status", annotations=_READ)
    def configuration_status(  # pyright: ignore[reportUnusedFunction]
    ) -> dict[str, Any]:
        """Check secrets-only configuration without returning project IDs or token values."""

        return service.configuration_status()

    @server.tool(name="overleaf_list_projects", annotations=_READ)
    def list_projects(  # pyright: ignore[reportUnusedFunction]
    ) -> dict[str, Any]:
        """List configured project aliases and token readiness without secret values."""

        return service.list_projects()

    @server.tool(name="overleaf_get_project_status", annotations=_READ)
    def get_project_status(  # pyright: ignore[reportUnusedFunction]
        project: Project,
    ) -> dict[str, Any]:
        """Fetch the allowed default branch and report its revision, size, and warnings."""

        return service.get_project_status(project)

    @server.tool(name="overleaf_list_files", annotations=_READ)
    def list_files(  # pyright: ignore[reportUnusedFunction]
        project: Project,
        limit: Limit = 200,
        cursor: Cursor = None,
    ) -> dict[str, Any]:
        """List 500 files per revision-bound page with path and blob identities."""

        return service.list_files(project, limit=limit, cursor=cursor)

    @server.tool(name="overleaf_read_text_file", annotations=_READ)
    def read_text_file(  # pyright: ignore[reportUnusedFunction]
        project: Project, path: ProjectPath
    ) -> dict[str, Any]:
        """Read one UTF-8 text file up to 2 MiB with exact revision and blob SHA."""

        return service.read_text_file(project, path)

    @server.tool(name="overleaf_get_outline", annotations=_READ)
    def get_outline(  # pyright: ignore[reportUnusedFunction]
        project: Project, path: ProjectPath
    ) -> dict[str, Any]:
        """Parse LaTeX sectioning commands read-only; returned headings are never write anchors."""

        return service.get_outline(project, path)

    @server.tool(name="overleaf_reconcile_commit", annotations=_READ)
    def reconcile_commit(  # pyright: ignore[reportUnusedFunction]
        project: Project, candidate_commit: Revision
    ) -> dict[str, Any]:
        """Check whether a candidate is on the allowed remote default branch."""

        return service.reconcile_commit(project, candidate_commit)

    @server.tool(name="overleaf_edit_text_file", annotations=_WRITE)
    def edit_text_file(  # pyright: ignore[reportUnusedFunction]
        project: Project,
        path: ProjectPath,
        old_text: OldText,
        new_text: EditText,
        expected_revision: Revision,
        expected_blob_sha: Revision,
        commit_message: CommitMessage,
    ) -> dict[str, Any]:
        """Prompt-gated unique literal replacement after exact revision and blob checks."""

        return service.edit_text_file(
            project,
            path=path,
            old_text=old_text,
            new_text=new_text,
            expected_revision=expected_revision,
            expected_blob_sha=expected_blob_sha,
            commit_message=commit_message,
        )

    @server.tool(name="overleaf_write_text_file", annotations=_WRITE)
    def write_text_file(  # pyright: ignore[reportUnusedFunction]
        project: Project,
        path: ProjectPath,
        content: TextContent,
        expected_revision: Revision,
        expected_blob_sha: ExpectedBlob,
        commit_message: CommitMessage,
    ) -> dict[str, Any]:
        """Prompt-gated UTF-8 create or full-file replacement with exact preconditions."""

        return service.write_text_file(
            project,
            path=path,
            content=content,
            expected_revision=expected_revision,
            expected_blob_sha=expected_blob_sha,
            commit_message=commit_message,
        )

    @server.tool(name="overleaf_import_file", annotations=_WRITE)
    def import_file(  # pyright: ignore[reportUnusedFunction]
        project: Project,
        source_path: SourcePath,
        source_sha256: Sha256,
        destination_path: ProjectPath,
        expected_revision: Revision,
        expected_blob_sha: ExpectedBlob,
        commit_message: CommitMessage,
    ) -> dict[str, Any]:
        """Prompt-gated import from an allowlisted local root after an exact SHA-256 check."""

        return service.import_file(
            project,
            source_path=source_path,
            source_sha256=source_sha256,
            destination_path=destination_path,
            expected_revision=expected_revision,
            expected_blob_sha=expected_blob_sha,
            commit_message=commit_message,
        )

    @server.tool(name="overleaf_move_file", annotations=_WRITE)
    def move_file(  # pyright: ignore[reportUnusedFunction]
        project: Project,
        source_path: ProjectPath,
        destination_path: ProjectPath,
        expected_revision: Revision,
        expected_source_blob_sha: Revision,
        commit_message: CommitMessage,
    ) -> dict[str, Any]:
        """Move a file; Overleaf comments and tracked changes may be displaced."""

        return service.move_file(
            project,
            source_path=source_path,
            destination_path=destination_path,
            expected_revision=expected_revision,
            expected_source_blob_sha=expected_source_blob_sha,
            commit_message=commit_message,
        )

    @server.tool(name="overleaf_delete_file", annotations=_WRITE)
    def delete_file(  # pyright: ignore[reportUnusedFunction]
        project: Project,
        path: ProjectPath,
        expected_revision: Revision,
        expected_blob_sha: Revision,
        commit_message: CommitMessage,
    ) -> dict[str, Any]:
        """Prompt-gated regular-file deletion after exact revision and blob checks."""

        return service.delete_file(
            project,
            path=path,
            expected_revision=expected_revision,
            expected_blob_sha=expected_blob_sha,
            commit_message=commit_message,
        )

    return server


class _GracefulTermination(BaseException):
    pass


def _terminate(_signum: int, _frame: FrameType | None) -> None:
    raise _GracefulTermination


def main() -> int:
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        create_server().run(transport="stdio")
    except _GracefulTermination:
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
