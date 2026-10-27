"""File download over HTTP (plan v0.4 C11, A-ADR-047 decision 5; SPEC 9.2, 10.2).

- ``GET|HEAD /stores/{store}/versions/{version}/file``: a version's file;
- ``GET|HEAD /projects/{project}/files/{file_id}/file?member=``: an own-data
  working file, or one file of its set;
- ``GET|HEAD …/files/{file_id}/snapshots/{label}/file?member=``: a file of a
  snapshot.

``archiwista.services.files`` finds the file: only what the index knows and
the session sees (a hidden project is ``404``), inside its root, and an own
file or a snapshot only from a data folder that may be read now (the
resolver's ``archiwista.owndata.scan.folder_check``). The answer opens it
once at its real path without following a link (``open_download``) and
streams that descriptor, never the path again (a link swapped in since the
check is ``403 path_outside_root``), as Starlette's ``FileResponse`` streams
a file (``Range`` answered ``206`` with ``Content-Range``, ``Accept-Ranges``,
``Content-Length``), as an attachment with its name (``filename*`` of RFC
6266 for a name that is not plain ASCII), the media type of its format and
``Cache-Control: private, no-store``; ``nosniff`` and the CSP come from
``SecurityMiddleware``, which also lets a link of the interface in without
the CSRF header (``Sec-Fetch-Site`` ``same-origin`` or ``none``,
``security.file_link``). Nothing is shown inline, a PDF neither. A ``GET``
streams within the person's limit (``app.state.file_streams``, ``429
too_many_downloads``) and, without ``Range`` or from byte 0, is logged
(``file.download`` with ``size_bytes``); a ``HEAD`` answers the headers
only. This router comes before the catalog's, whose
``/stores/{store}/versions/{version}`` would otherwise take ``…/file``.
"""

import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.types import Receive, Scope, Send

from archiwista.api.dependencies import (
    app_paths,
    authorizer,
    index_queries,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.owndata import own_file as indexed_own_file
from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppPaths, SettingsService
from archiwista.index import IndexQueries
from archiwista.messages import message
from archiwista.refs import ObjectResolver
from archiwista.security import current_principal
from archiwista.services.files import (
    FILE_DOWNLOADS_PER_PERSON,
    RETRY_AFTER_S,
    FileDownload,
    FileStreams,
    open_download,
    own_file,
    snapshot_file,
    version_file,
)

router = APIRouter(tags=["files"])

# A file is fetched again each time: who sees it is checked each time.
CACHE_CONTROL = "private, no-store"
_VERSION_FILE = "/stores/{store}/versions/{version:path}/file"
_OWN_FILE = "/projects/{project}/files/{file_id}/file"
_SNAPSHOT_FILE = "/projects/{project}/files/{file_id}/snapshots/{label}/file"
# A request for the file from its first byte: no ``Range``, or one from 0.
_FROM_START = re.compile(r"\s*bytes\s*=\s*0\s*-", re.IGNORECASE)

_Principal = Annotated[Principal, Depends(current_principal)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_Paths = Annotated[AppPaths, Depends(app_paths)]
_Store = Annotated[str, Path(description="Store id.", examples=["zespol"])]
_Version = Annotated[
    str,
    Path(
        description="Version path in the store.",
        examples=[
            "nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/d/2/4/"
            "2025-04-26_82710_fdd30535/N-34-130-D-d-2-4.asc"
        ],
    ),
]
_Project = Annotated[
    str, Path(description="Project id (`project` of /projects).", examples=["raba"])
]
_FileId = Annotated[
    str,
    Path(
        description="File id (`file_id` of the file list): 16 hex characters.",
        pattern="^[0-9a-f]{16}$",
        examples=["9c1e04b3f27a5d68"],
    ),
]
_Label = Annotated[
    str,
    Path(
        description="Snapshot label (`label` of the file card).",
        pattern="^[A-Za-z0-9][A-Za-z0-9._-]*$",
        examples=["2026-10-18_471d37c0"],
    ),
]
_Member = Annotated[
    str | None,
    Query(
        description=(
            "One file of the set by its name (`members` of the card); the main"
            " file when omitted."
        ),
        max_length=255,
        examples=["dzialki.dbf"],
    ),
]


def _responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI answers of a file route: the file, a part, problems."""
    busy = problem_example(
        "rate_limited",
        message("api.too_many_downloads", "en", limit=FILE_DOWNLOADS_PER_PERSON),
        reason="too_many_downloads",
        details={"retry_after_s": RETRY_AFTER_S},
    )
    return {
        200: {
            "description": (
                "The file, `Content-Disposition: attachment` with its name, the"
                " media type of its format."
            ),
            "content": {"application/octet-stream": {}},
        },
        206: {
            "description": "The part `Range` asked for, with `Content-Range`.",
            "content": {"application/octet-stream": {}},
        },
        **problem_responses(403, 404, *statuses, 503),
        429: {
            "description": (
                "`rate_limited` (reason `too_many_downloads`): the person streams"
                f" {FILE_DOWNLOADS_PER_PERSON} downloads already; `Retry-After`"
                " says when to ask again."
            ),
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                    "example": busy,
                }
            },
        },
    }


def file_resolver(
    queries: _Queries, settings: _Settings, decisions: _Authorizer, paths: _Paths
) -> ObjectResolver:
    """Return the resolver of refs, own data seen by whoever sees its project."""
    return ObjectResolver(
        queries, settings.get, visible=decisions.visible_projects, paths=paths
    )


_Resolver = Annotated[ObjectResolver, Depends(file_resolver)]


@router.head(_VERSION_FILE, include_in_schema=False)
@router.get(_VERSION_FILE, response_class=Response, responses=_responses())
def download_version_file(
    store: _Store,
    version: _Version,
    request: Request,
    principal: _Principal,
    resolver: _Resolver,
    decisions: _Authorizer,
) -> Response:
    """Download a version's file (also `HEAD`); `Range` gives a part.

    A version the index knows, resolved inside its store; a link of the
    interface needs no `X-Archiwista-CSRF` (`Sec-Fetch-Site: same-origin`).
    """
    found = version_file(resolver, store, version, principal=principal)
    return _answer(request, found, principal, decisions)


@router.head(_OWN_FILE, include_in_schema=False)
@router.get(_OWN_FILE, response_class=Response, responses=_responses(409))
def download_own_file(
    project: _Project,
    file_id: _FileId,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    resolver: _Resolver,
    decisions: _Authorizer,
    member: _Member = None,
) -> Response:
    """Download an own file, or one file of its set (`member`), also `HEAD`.

    For those who see the project, from a data folder the rules of its scan
    let be read now (else `409 own_folder_invalid`); a file changed since its
    scan is `409 own_file_changed` (`POST /projects/{project}/scan` refreshes
    it).
    """
    detail = indexed_own_file(queries, project, file_id, visible=visible)
    found = own_file(resolver, project, detail, principal=principal, member=member)
    return _answer(request, found, principal, decisions)


@router.head(_SNAPSHOT_FILE, include_in_schema=False)
@router.get(_SNAPSHOT_FILE, response_class=Response, responses=_responses(409))
def download_snapshot_file(
    project: _Project,
    file_id: _FileId,
    label: _Label,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    resolver: _Resolver,
    decisions: _Authorizer,
    member: _Member = None,
) -> Response:
    """Download a snapshot's file, or one file of its set (`member`), also `HEAD`.

    A snapshot that is not valid (`modified`, `invalid`) is `409`, so is one
    of a data folder the rules of its scan do not let be read now.
    """
    detail = indexed_own_file(queries, project, file_id, visible=visible)
    found = snapshot_file(
        resolver, project, detail, label, principal=principal, member=member
    )
    return _answer(request, found, principal, decisions)


class _Opened(FileResponse):
    """A file answered from the descriptor ``open_download`` checked.

    Starlette's ``FileResponse`` reads the file it opens by its path; this one
    reads the descriptor it is given (``_open_file``) and never sends the
    path to the server (``http.response.pathsend``), so the answer is the
    file that was checked inside its root. The descriptor closes when the
    answer ends, however it ends (the client leaving too), and so does the
    person's count in ``FileStreams`` (``end``).
    """

    def __init__(
        self,
        found: FileDownload,
        descriptor: int,
        *,
        end: Callable[[], None] | None = None,
    ) -> None:
        self._file = os.fdopen(descriptor, "rb")
        self._end = end
        try:
            status = os.fstat(descriptor)
        except BaseException:
            self.close()
            raise
        super().__init__(
            found.path,
            media_type=found.media_type,
            filename=found.name,
            headers={"Cache-Control": CACHE_CONTROL},
            stat_result=status,
        )
        self.size = status.st_size

    def close(self) -> None:
        """Close the descriptor and end the count; idempotent."""
        self._file.close()
        end, self._end = self._end, None
        if end is not None:
            end()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Send the file; the client leaving closes it too."""
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.close()

    @asynccontextmanager
    async def _open_file(self) -> AsyncIterator[anyio.AsyncFile[bytes]]:
        yield anyio.AsyncFile(self._file)

    async def _handle_simple(
        self, send: Send, send_header_only: bool, send_pathsend: bool
    ) -> None:
        await super()._handle_simple(send, send_header_only, False)


def _answer(
    request: Request, found: FileDownload, principal: Principal, decisions: Authorizer
) -> Response:
    """Answer a found file: its headers to a ``HEAD``, else stream and log it."""
    if request.method == "HEAD":
        return _Opened(found, open_download(found))
    streams: FileStreams = request.app.state.file_streams
    end = streams.start(principal.id)
    try:
        answer = _Opened(found, open_download(found), end=end)
    except BaseException:
        end()
        raise
    try:
        part = request.headers.get("range")
        if part is None or _FROM_START.match(part):
            decisions.state.record(
                principal,
                "file.download",
                found.ref,
                details={"size_bytes": answer.size},
            )
    except BaseException:
        answer.close()
        raise
    return answer
