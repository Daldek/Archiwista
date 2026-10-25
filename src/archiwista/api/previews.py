"""Previews of store versions over HTTP (plan v0.2, step 6; SPEC 9.2, 5.7).

Under ``/stores/{store}/versions/{version}``:

- ``GET …/preview``: the ``PreviewInfo`` of the version;
- ``POST …/preview`` (``{"force": false}``): ``200 PreviewInfo`` when
  nothing needs building, else ``202 JobDetail`` of the ``preview`` job
  building it, a new one or one building it already (``Location``);
- ``GET …/preview.png?style&size&bbox&bbox_crs``: the thumbnail;
- ``GET …/tiles/{z}/{x}/{y}.png?style&rescale``: a map tile (EPSG:3857);
- ``GET …/features?bbox&zoom&layer&limit``: the features of a map view as
  GeoJSON in WGS84;
- ``GET …/members``: the members of an archive.

Images and data carry ``Cache-Control: private, max-age=86400, immutable``
(a version's content never changes and everyone sees the store) and an
``ETag``; ``If-None-Match`` naming it is answered ``304``. A request whose
client goes away before its answer gives its render up, so the tiles of a
map moved on leave the render queue unrendered. The ``preview`` job a build
starts or joins is shown as the session sees it: a joined job may hold refs
of projects it does not see. Routes only translate: ``PreviewService`` does
the work, ``archiwista preview`` calls it too; the own-data routes
(``archiwista.api.owndata``) answer with the helpers here. This router comes
before the catalog's, whose ``/stores/{store}/versions/{version}`` would
otherwise take these addresses.
"""

import asyncio
import contextlib
import json
from collections.abc import Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from archiwista.api import API_PREFIX
from archiwista.api.dependencies import visible_projects
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.models import JobDetail
from archiwista.api.models_previews import (
    MAX_ZOOM,
    ArchiveMembers,
    BuildRequest,
    FeaturesQuery,
    PreviewInfo,
    ThumbnailQuery,
    TileQuery,
)
from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import SettingsService
from archiwista.errors import PreviewBusyError
from archiwista.jobs import JobSupervisor
from archiwista.messages import message
from archiwista.previews.pool import RETRY_AFTER_S, RenderPool
from archiwista.previews.service import Payload, PreviewService
from archiwista.refs import ObjectResolver, version_ref
from archiwista.security import current_principal

router = APIRouter(tags=["previews"])

PNG = "image/png"
GEOJSON = "application/geo+json"
# A version's content never changes, and everyone sees the store (decision 3).
VERSION_CACHE_CONTROL = "private, max-age=86400, immutable"
# Status of an answer nobody receives: the client went away first.
CLIENT_GONE = 499
_VERSION_PREFIX = "/stores/{store}/versions/{version:path}"


class ClientGone(Exception):
    """The client disconnected before its answer was ready."""


def preview_service(request: Request) -> PreviewService:
    """Return the previews of the application's render pool and index.

    Own data and snapshots are resolved for whoever sees their project
    (``Authorizer.visible_projects``).

    Raises
    ------
    PreviewBusyError
        The server runs no render pool (``503 preview_busy``).
    """
    state = request.app.state
    pool: RenderPool | None = state.previews
    if pool is None:
        raise PreviewBusyError(message("preview.closed"), retry_after_s=RETRY_AFTER_S)
    settings: SettingsService = state.settings
    decisions: Authorizer = state.authorizer
    resolver = ObjectResolver(
        state.queries, settings.get, visible=decisions.visible_projects
    )
    return PreviewService(pool, resolver, state.jobs)


def optional_jobs(request: Request) -> JobSupervisor | None:
    """Return the server's supervisor of background jobs, if it runs one."""
    value: JobSupervisor | None = request.app.state.jobs
    return value


_Principal = Annotated[Principal, Depends(current_principal)]
_Service = Annotated[PreviewService, Depends(preview_service)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_OptionalJobs = Annotated[JobSupervisor | None, Depends(optional_jobs)]
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
_IfNoneMatch = Annotated[
    str | None,
    Header(description="`ETag` of the answer the client holds: `304` when equal."),
]


def preview_problems(*codes: str) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI problems of the preview routes, by reason."""
    unavailable = message("preview.reason_document_no_preview")
    examples: dict[str, dict[str, object]] = {
        "preview_unavailable": problem_example(
            "unsupported",
            message(
                "preview.unavailable_detail",
                message=unavailable,
                fix=message("preview.fix_document_no_preview"),
            ),
            reason="preview_unavailable",
            details={
                "preview_reason": {
                    "code": "document_no_preview",
                    "message": unavailable,
                    "fix": message("preview.fix_document_no_preview"),
                    "detail": None,
                }
            },
            hint=message("preview.fix_document_no_preview"),
        ),
        "preview_not_ready": problem_example(
            "conflict",
            message("preview.not_ready_build"),
            reason="preview_not_ready",
            details={"build_required": True},
        ),
        "preview_busy": problem_example(
            "rate_limited",
            message("preview.busy", seconds=RETRY_AFTER_S),
            reason="preview_busy",
            details={"retry_after_s": RETRY_AFTER_S},
        ),
        "store_unavailable": problem_example(
            "store_unavailable",
            message("preview.reason_store_unavailable"),
            reason="store_unreadable",
        ),
        "preview_timeout": problem_example(
            "calculation_error",
            message("preview.timeout", seconds=30),
            reason="preview_timeout",
        ),
    }
    descriptions = {
        409: (
            "`preview_not_ready` (reason): map tiles before their build, with"
            " the visible `details.job`, the hidden `details.building`, or"
            " `details.build_required`."
        ),
        422: (
            "`unsupported` (reason `preview_unavailable`: `details.preview_reason`"
            " has the code, Polish description and fix) or `calculation_error`"
            " (reason `preview_timeout`: the render ran past its time limit)."
        ),
        429: (
            "`rate_limited` (reason `preview_busy`): the render queue is full;"
            " `Retry-After` says when to ask again."
        ),
        503: (
            "`store_unavailable`: not in the preview cache, and the store is out"
            " of reach."
        ),
    }
    responses: dict[int | str, dict[str, Any]] = {}
    for code in codes:
        body = examples[code]
        status = int(str(body["status"]))
        entry = responses.setdefault(
            status,
            {
                "description": descriptions[status],
                "content": {
                    PROBLEM_MEDIA_TYPE: {
                        "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                        "examples": {},
                    }
                },
            },
        )
        entry["content"][PROBLEM_MEDIA_TYPE]["examples"][code] = {"value": body}
    return responses


def image_responses(media_type: str, *codes: str) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI responses of an image route with its problems by code."""
    return {
        200: {
            "description": "The image or data; `ETag` and `Cache-Control` set.",
            "content": {media_type: {}},
        },
        304: {"description": "Not modified: the client holds this `ETag`."},
        **problem_responses(403, 404, 400),
        **preview_problems(*codes),
    }


_RENDERED = ("preview_unavailable", "preview_busy", "store_unavailable")


@router.get(
    f"{_VERSION_PREFIX}/preview",
    response_model=PreviewInfo,
    responses={
        **problem_responses(403, 404, 400),
        **preview_problems("preview_busy"),
    },
)
async def get_preview(
    store: _Store,
    version: _Version,
    request: Request,
    principal: _Principal,
    service: _Service,
) -> PreviewInfo | Response:
    """Return the preview of a version: state, styles, legend and addresses.

    A version that cannot be read now is described with its `reason`
    (`store_unavailable`, `missing_file`, `timeout`…), not refused. Use the
    addresses it gives (`thumbnail_url`, `tiles_url`, `features_url`,
    `members_url`); never compose them.
    """
    return await info_answer(request, service, version_ref(store, version), principal)


@router.post(
    f"{_VERSION_PREFIX}/preview",
    response_model=None,
    responses={
        200: {"model": PreviewInfo, "description": "Nothing needs building."},
        202: {
            "model": JobDetail,
            "description": "The `preview` job building it (`Location`).",
        },
        **problem_responses(403, 404, 400),
        **preview_problems("preview_unavailable", "preview_busy", "store_unavailable"),
    },
)
async def build_preview(
    store: _Store,
    version: _Version,
    principal: _Principal,
    visible: _Visible,
    service: _Service,
    jobs: _OptionalJobs,
    body: Annotated[BuildRequest | None, Body()] = None,
) -> Response:
    """Build the local preview of a version (its COG) in the background.

    Answers `202` with the `preview` job (a new one, or the one already
    building the same content) and `Location: /api/v1/jobs/{job}`, or `200`
    with the `PreviewInfo` when nothing needs building. A file past the
    auto-build limits needs `force: true` (`409 preview_unavailable`,
    `too_large`, otherwise). A joined job lists only the refs of projects
    the session sees.
    """
    force = body is not None and body.force
    return await build_answer(
        service,
        version_ref(store, version),
        principal=principal,
        visible=visible,
        jobs=jobs,
        force=force,
    )


@router.get(
    f"{_VERSION_PREFIX}/preview.png",
    response_class=Response,
    responses=image_responses(PNG, *_RENDERED, "preview_timeout"),
)
async def get_thumbnail(
    store: _Store,
    version: _Version,
    query: Annotated[ThumbnailQuery, Query()],
    request: Request,
    principal: _Principal,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return a PNG thumbnail of a version, at most `size` pixels a side.

    In the file's CRS, or in the frame `bbox` (in `bbox_crs`) when given.
    """
    work = service.thumbnail(
        version_ref(store, version),
        principal=principal,
        style=query.style,
        size=query.size,
        frame=query.frame(),
        if_none_match=if_none_match,
    )
    return await respond(request, work, PNG, VERSION_CACHE_CONTROL)


@router.get(
    f"{_VERSION_PREFIX}/tiles/{{z}}/{{x}}/{{y}}.png",
    response_class=Response,
    responses=image_responses(PNG, *_RENDERED, "preview_not_ready", "preview_timeout"),
)
async def get_tile(
    store: _Store,
    version: _Version,
    z: Annotated[int, Path(ge=0, le=MAX_ZOOM, description="Zoom level.")],
    x: Annotated[int, Path(ge=0, description="Column, 0 to 2^z - 1.")],
    y: Annotated[int, Path(ge=0, description="Row, 0 to 2^z - 1.")],
    query: Annotated[TileQuery, Query()],
    request: Request,
    principal: _Principal,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the map tile `z/x/y` of a version (EPSG:3857, 256 pixels).

    Outside the version's `minzoom`–`maxzoom` or extent: `404`. A file
    whose map needs its local preview built first: `409 preview_not_ready`.
    """
    require_tile(z, x, y)
    work = service.tile(
        version_ref(store, version),
        principal=principal,
        z=z,
        x=x,
        y=y,
        style=query.style,
        rescale=query.rescale_values(),
        if_none_match=if_none_match,
    )
    return await respond(request, work, PNG, VERSION_CACHE_CONTROL)


@router.get(
    f"{_VERSION_PREFIX}/features",
    response_class=Response,
    responses=image_responses(
        GEOJSON, *_RENDERED, "preview_not_ready", "preview_timeout"
    ),
)
async def get_features(
    store: _Store,
    version: _Version,
    query: Annotated[FeaturesQuery, Query()],
    request: Request,
    principal: _Principal,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the features of a map view as a GeoJSON `FeatureCollection`.

    In WGS84, simplified to `zoom`, at most `limit` features and 500 000
    vertices together; `number_matched`, `truncated` (more: zoom in or open
    the file in QGIS) and `simplified` tell what was left out.
    """
    work = service.features(
        version_ref(store, version),
        principal=principal,
        bbox=query.bbox_values(),
        zoom=query.zoom,
        layer=query.layer,
        limit=query.limit,
        if_none_match=if_none_match,
    )
    return await respond(request, work, GEOJSON, VERSION_CACHE_CONTROL)


@router.get(
    f"{_VERSION_PREFIX}/members",
    response_model=ArchiveMembers,
    responses={
        304: {"description": "Not modified: the client holds this `ETag`."},
        **problem_responses(403, 404, 400),
        **preview_problems(*_RENDERED, "preview_timeout"),
    },
)
async def get_members(
    store: _Store,
    version: _Version,
    request: Request,
    principal: _Principal,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the members of an archive: names, sizes, formats; nothing unpacked.

    At most the first 10 000 (`truncated` beyond them); an archive whose
    directory declares over 100 000 members is `too_large`.
    """
    ref = version_ref(store, version)
    return await members_answer(
        request, service, ref, principal, if_none_match, VERSION_CACHE_CONTROL
    )


# What the preview routes of versions, own files and snapshots share.


async def info_answer(
    request: Request, service: PreviewService, ref: str, principal: Principal
) -> PreviewInfo | Response:
    """Answer ``GET …/preview``: the ``PreviewInfo`` of an object."""
    try:
        return await while_connected(request, service.info(ref, principal=principal))
    except ClientGone:
        return Response(status_code=CLIENT_GONE)


async def build_answer(
    service: PreviewService,
    ref: str,
    *,
    principal: Principal,
    visible: ProjectVisibility,
    jobs: JobSupervisor | None,
    force: bool,
) -> Response:
    """Answer ``POST …/preview``: ``200 PreviewInfo``, or ``202`` with its job.

    The job, a new one or one building the same content that the request
    joined, is shown as the session sees it (``JobSupervisor.get`` with
    ``visible``): a joined job may hold refs of projects it does not see.
    """
    record = await service.build([ref], principal=principal, force=force)
    if record is None:
        info = await service.info(ref, principal=principal)
        return JSONResponse(info.model_dump(mode="json"))
    if jobs is not None:  # the request's own ref keeps the job visible
        record = await asyncio.to_thread(jobs.get, record.id, visible=visible) or record
    return JSONResponse(
        JobDetail.of(record).model_dump(mode="json"),
        status_code=202,
        headers={"Location": f"{API_PREFIX}/jobs/{record.id}"},
    )


def require_tile(z: int, x: int, y: int) -> None:
    """Refuse a column or a row past the last one of zoom ``z`` (``422``)."""
    last = 2**z - 1
    errors = [
        {
            "loc": ("path", name),
            "msg": message("preview.tile_range", z=z, last=last),
            "type": "value_error",
        }
        for name, value in (("x", x), ("y", y))
        if value > last
    ]
    if errors:
        raise RequestValidationError(errors)


async def respond(
    request: Request,
    work: Coroutine[Any, Any, Payload],
    media_type: str,
    cache_control: str,
) -> Response:
    """Answer an image or data, ``304`` when the client holds it.

    ``cache_control``: ``VERSION_CACHE_CONTROL`` for a store version, a
    revalidated one for own data, whose content and visibility change.
    """
    try:
        payload = await while_connected(request, work)
    except ClientGone:
        return Response(status_code=CLIENT_GONE)
    if payload.data is None:
        return _not_modified(payload, cache_control)
    return Response(
        payload.data,
        media_type=media_type,
        headers=_cache_headers(payload, cache_control),
    )


async def members_answer(
    request: Request,
    service: PreviewService,
    ref: str,
    principal: Principal,
    if_none_match: str | None,
    cache_control: str,
) -> Response:
    """Answer ``GET …/members``: an archive's ``ArchiveMembers``, or ``304``."""
    work = service.members(ref, principal=principal, if_none_match=if_none_match)
    try:
        payload = await while_connected(request, work)
    except ClientGone:
        return Response(status_code=CLIENT_GONE)
    if payload.data is None:
        return _not_modified(payload, cache_control)
    members = ArchiveMembers.model_validate({"ref": ref, **json.loads(payload.data)})
    return Response(
        members.model_dump_json(),
        media_type="application/json",
        headers=_cache_headers(payload, cache_control),
    )


def _cache_headers(payload: Payload, cache_control: str) -> dict[str, str]:
    return {"Cache-Control": cache_control, "ETag": payload.etag}


def _not_modified(payload: Payload, cache_control: str) -> Response:
    return Response(status_code=304, headers=_cache_headers(payload, cache_control))


async def while_connected[T](request: Request, work: Coroutine[Any, Any, T]) -> T:
    """Await ``work``; cancel it when the client disconnects first.

    Cancelling gives a waiting render request up (``RenderPool.arequest``).

    Raises
    ------
    ClientGone
        The client went away; ``work`` was cancelled.
    """
    task = asyncio.ensure_future(work)
    watcher = asyncio.ensure_future(_disconnected(request))
    try:
        await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
    finally:
        watcher.cancel()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
    if task.cancelled():
        raise ClientGone
    return task.result()


async def _disconnected(request: Request) -> None:
    """Return when the client has disconnected (its body read first)."""
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return
