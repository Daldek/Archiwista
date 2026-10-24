"""Projects' own data and their snapshots over HTTP (plan v0.2, step 9).

Under ``/projects/{project}`` (decisions 8–10):

- ``GET …/files?q&state&limit&cursor``: ``OwnFileList``, the data folder with
  its state and problems and its files by path, each with its change since
  its last snapshot; a folder not scanned yet has ``scanned_at: null``;
- ``POST …/scan``: ``202 JobDetail`` of the ``own_scan`` of the project's
  folder (a waiting run covering it is joined), as „Odśwież” does;
- ``PUT …/data-dir`` (``{"path": … | null}``): ``OwnFolder``, another data
  folder or the default ``dane/`` again, for an administrator
  (``settings.write``); its scan starts at once;
- ``GET …/files/{file_id}``: ``OwnFileCard``, with snapshots, history and
  preview;
- ``GET|POST …/files/{file_id}/preview``, ``…/preview.png``,
  ``…/tiles/{z}/{x}/{y}.png``, ``…/features``, ``…/members``: the previews of
  the working file, as of a version;
- ``GET …/files/{file_id}/snapshot-plan``: ``SnapshotPlan``, nothing written;
- ``GET …/files/{file_id}/layers``: ``LayerSet`` of the Wachlarz, the working
  file and then its snapshots newest first, in the frame of their extents;
- ``POST …/files/{file_id}/snapshots`` (``{"note": …}``): ``202 JobDetail`` of
  the ``snapshot`` job, for the project's owner or an administrator
  (``project.write``); ``409 snapshot_blocked`` (``reason``) when the plan
  refuses it, ``409 conflict`` while a snapshot of the file runs;
- ``GET|POST …/files/{file_id}/snapshots/{label}/preview`` and its images:
  the previews of a snapshot.

A project the principal does not see answers ``404 not_found`` everywhere,
as an unknown one (A-ADR-029). Images and data of own data carry
``Cache-Control: private, no-cache`` with an ``ETag``: every reuse in the
browser asks again, so visibility is checked again (``304`` after that). A
working file changed since its scan is ``409 own_file_changed`` for images
and data (``POST …/scan`` refreshes it). Routes only translate: the
functions here are what ``archiwista files``, ``file`` and ``snapshot``
call too. The routes starting jobs (``…/scan``, ``…/snapshots``) are in
``job_router``, served with the job supervisor.
"""

import asyncio
import os
from dataclasses import replace
from pathlib import Path as FilePath
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Request
from fastapi.responses import Response

from archiwista.api import API_PREFIX
from archiwista.api.dependencies import (
    authorizer,
    index_queries,
    plugin_registry,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.jobs import job_supervisor
from archiwista.api.models import JobDetail
from archiwista.api.models_layers import LayerSet
from archiwista.api.models_owndata import (
    DataDirRequest,
    OwnFileCard,
    OwnFileList,
    OwnFilesQuery,
    OwnFolder,
    SnapshotPlan,
    SnapshotRequest,
)
from archiwista.api.models_previews import (
    MAX_ZOOM,
    ArchiveMembers,
    BuildRequest,
    FeaturesQuery,
    PreviewInfo,
    ThumbnailQuery,
    TileQuery,
)
from archiwista.api.previews import (
    CLIENT_GONE,
    GEOJSON,
    PNG,
    ClientGone,
    build_answer,
    image_responses,
    info_answer,
    members_answer,
    optional_jobs,
    preview_problems,
    preview_service,
    require_tile,
    respond,
    while_connected,
)
from archiwista.auth import ALL_PROJECTS, Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppPaths, AppSettings, SettingsService
from archiwista.errors import (
    NotFoundError,
    PathOutsideRootError,
    PreviewBusyError,
    SnapshotBlockedError,
)
from archiwista.index import IndexQueries, OwnFileDetail, ProjectRecord
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import MESSAGES
from archiwista.owndata.snapshots import check_snapshot
from archiwista.previews.service import PreviewService
from archiwista.refs import FileRef, ObjectRef, SnapshotRef, format_ref
from archiwista.sandbox import process_work_dir
from archiwista.security import current_principal
from archiwista.services.layers import read_own_file_layers
from archiwista.services.owndata import (
    file_problems,
    folder_check,
    folder_problems,
    own_problems,
    set_data_dir,
)
from archiwista.sources.registry import PluginRegistry

router = APIRouter(prefix="/projects/{project}", tags=["own data"])
job_router = APIRouter(prefix="/projects/{project}", tags=["own data"])

# Own data changes and its visibility is per project: every reuse asks again.
OWN_CACHE_CONTROL = "private, no-cache"
_FILE = "/files/{file_id}"
_SNAPSHOT = "/files/{file_id}/snapshots/{label}"


def app_paths(request: Request) -> AppPaths:
    """Return the server's data directory: the index's (``AppPaths.data_dir``).

    Only the data directory counts here (the folder rules, the process's
    work directory); the settings come from the settings service.
    """
    index_path: FilePath = request.app.state.index_path
    return AppPaths(config_file=FilePath(os.devnull), data_dir=index_path.parent)


def own_previews(request: Request) -> PreviewService | None:
    """Return the previews of the server, or ``None`` without render processes."""
    try:
        return preview_service(request)
    except PreviewBusyError:
        return None


_Principal = Annotated[Principal, Depends(current_principal)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_Paths = Annotated[AppPaths, Depends(app_paths)]
_OptionalJobs = Annotated[JobSupervisor | None, Depends(optional_jobs)]
_Jobs = Annotated[JobSupervisor, Depends(job_supervisor)]
_Service = Annotated[PreviewService, Depends(preview_service)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
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
_IfNoneMatch = Annotated[
    str | None,
    Header(description="`ETag` of the answer the client holds: `304` when equal."),
]


# What the routes do, also for the command line.


def visible_project(
    queries: IndexQueries, project: str, *, visible: ProjectVisibility
) -> ProjectRecord:
    """Return a project the principal sees.

    Raises
    ------
    NotFoundError
        Unknown, or not visible: both answer alike.
    """
    record = queries.project(project, visible=visible)
    if record is None:
        raise NotFoundError(MESSAGES["project_not_found"].format(project=project))
    return record


def own_file(
    queries: IndexQueries, project: str, file_id: str, *, visible: ProjectVisibility
) -> OwnFileDetail:
    """Return the indexed file of a project the principal sees.

    Raises
    ------
    NotFoundError
        An unknown or invisible project, a file the index does not know.
    """
    visible_project(queries, project, visible=visible)
    detail = queries.own_file(project, file_id, visible=visible)
    if detail is None:
        message = MESSAGES["own_file_not_found"].format(
            project=project, file_id=file_id
        )
        raise NotFoundError(message)
    return detail


def read_own_files(
    queries: IndexQueries,
    settings: AppSettings,
    paths: AppPaths,
    project: str,
    query: OwnFilesQuery,
    *,
    visible: ProjectVisibility,
) -> OwnFileList:
    """Return a page of a project's own files and its data folder.

    A folder never scanned is described as it is now (``scanned_at: null``,
    no files).

    Raises
    ------
    NotFoundError
        An unknown or invisible project.
    IndexQueryError
        An unknown state, or a cursor of other filters.
    """
    record = visible_project(queries, project, visible=visible)
    page = queries.own_files(
        project,
        visible=visible,
        q=query.q,
        state=query.state,
        limit=query.limit,
        cursor=query.cursor,
    )
    if page is not None:
        return OwnFileList.of(
            page, settings=settings, problems=own_problems(page.folder)
        )
    check = folder_check(settings, queries, paths, record.project.access_key)
    folder = OwnFolder.checked(
        check, settings=settings, problems=folder_problems(check, project)
    )
    return OwnFileList(folder=folder, items=[], next_cursor=None)


async def own_file_card(
    queries: IndexQueries,
    settings: AppSettings,
    previews: PreviewService | None,
    project: str,
    file_id: str,
    *,
    principal: Principal,
    visible: ProjectVisibility,
) -> OwnFileCard:
    """Return the card of an own file with its preview, as the route answers it.

    ``preview`` is ``null`` when it cannot be told now: no render processes,
    a full render queue, or a file linked out of its folder.

    Raises
    ------
    NotFoundError
        An unknown or invisible project, an unknown file.
    """
    detail = await asyncio.to_thread(
        own_file, queries, project, file_id, visible=visible
    )
    preview: PreviewInfo | None = None
    if previews is not None:
        ref = format_ref(FileRef(project, detail.file.path))
        try:
            preview = await previews.info(ref, principal=principal)
        except (PreviewBusyError, PathOutsideRootError):
            preview = None
    return OwnFileCard.of(
        project,
        detail,
        settings=settings,
        problems=file_problems(detail),
        preview=preview,
    )


def snapshot_plan(
    queries: IndexQueries,
    settings: AppSettings,
    paths: AppPaths,
    project: str,
    file_id: str,
    *,
    visible: ProjectVisibility,
) -> SnapshotPlan:
    """Plan a snapshot of a file without writing anything (``check_snapshot``).

    Raises
    ------
    NotFoundError
        An unknown or invisible project, an unknown file.
    PathOutsideRootError
        The file, a member of its set or ``.wersje/`` leads out of the folder.
    """
    record = visible_project(queries, project, visible=visible)
    detail = own_file(queries, project, file_id, visible=visible)
    check = folder_check(settings, queries, paths, record.project.access_key)
    plan = check_snapshot(check, detail, work_dir=process_work_dir(paths))
    return SnapshotPlan.of(plan, settings=settings)


def start_snapshot(
    decisions: Authorizer,
    principal: Principal,
    jobs: JobSupervisor,
    queries: IndexQueries,
    settings: AppSettings,
    paths: AppPaths,
    project: str,
    file_id: str,
    note: str,
) -> JobRecord:
    """Submit the ``snapshot`` job of a file after its permission and plan.

    Raises
    ------
    NotFoundError
        An unknown or invisible project, an unknown file.
    PermissionDeniedError
        Not the project's owner nor an administrator (``project.write``).
    SnapshotBlockedError
        The plan refuses the snapshot now (``reason``).
    JobConflictError
        A snapshot of the file runs already (``409 conflict`` with ``job``).
    """
    visible = decisions.visible_projects(principal)
    record = visible_project(queries, project, visible=visible)
    decisions.require(principal, "project.write", record.project.access_key)
    detail = own_file(queries, project, file_id, visible=visible)
    check = folder_check(settings, queries, paths, record.project.access_key)
    plan = check_snapshot(check, detail, work_dir=process_work_dir(paths))
    if plan.blocked is not None:
        raise SnapshotBlockedError(plan.blocked.reason, plan.blocked.message)
    params = {"project": project, "file_id": detail.file.file_id, "note": note}
    return jobs.submit("snapshot", params=params, actor=principal)


def start_own_scan(
    jobs: JobSupervisor,
    queries: IndexQueries,
    project: str | None,
    *,
    principal: Principal,
    visible: ProjectVisibility,
) -> JobRecord:
    """Submit the ``own_scan`` of a project's folder, or of every project's.

    Raises
    ------
    NotFoundError
        An unknown or invisible project.
    """
    if project is None:
        return jobs.submit("own_scan", params={}, actor=principal)
    visible_project(queries, project, visible=visible)
    return jobs.submit("own_scan", params={"project": project}, actor=principal)


def change_data_dir(
    decisions: Authorizer,
    principal: Principal,
    settings: SettingsService,
    queries: IndexQueries,
    paths: AppPaths,
    jobs: JobSupervisor | None,
    project: str,
    path: str | None,
) -> OwnFolder:
    """Give a project another data folder (or its default) and scan it.

    Raises
    ------
    PermissionDeniedError
        Not an administrator (``settings.write``).
    NotFoundError
        An unknown or invisible project.
    SettingsValidationError
        The folder breaks a rule of decision 8; nothing changes.
    """
    check = set_data_dir(decisions, principal, settings, queries, paths, project, path)
    if jobs is not None:
        jobs.submit("own_scan", params={"project": project}, actor=principal)
    current = settings.get()
    record = queries.own_folder(project, visible=ALL_PROJECTS)
    if record is not None and record.path == str(check.path):
        found = replace(record, state=check.state, reason=check.reason)
        return OwnFolder.of(found, settings=current, problems=own_problems(found))
    problems = folder_problems(check, project)
    return OwnFolder.checked(check, settings=current, problems=problems)


async def own_ref(
    queries: IndexQueries,
    project: str,
    file_id: str,
    *,
    visible: ProjectVisibility,
    label: str | None = None,
) -> ObjectRef:
    """Return the ``ref`` of a file, or of its snapshot, named in a route."""
    detail = await asyncio.to_thread(
        own_file, queries, project, file_id, visible=visible
    )
    if label is None:
        return FileRef(project, detail.file.path)
    return SnapshotRef(project, label, detail.file.path)


# Routes.

_JOB_PROBLEMS: dict[int | str, dict[str, Any]] = {
    409: {
        "description": (
            "Conflicts with the current state: reason `snapshot_blocked` (the"
            " plan refuses it now: `details.blocked_by` `folder_invalid`,"
            " `read_only_folder`, `insufficient_space`, `file_missing`) or no"
            " reason (a snapshot of the file runs; `details.job` names it)."
        ),
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                "examples": {
                    "snapshot_blocked": {
                        "value": problem_example(
                            "conflict",
                            MESSAGES["snapshot_blocked_read_only_folder"].format(
                                path="/mnt/nas/raba/dane/.wersje"
                            ),
                            reason="snapshot_blocked",
                            details={"blocked_by": "read_only_folder"},
                        )
                    }
                },
            }
        },
    }
}
_CHANGED_PROBLEM: dict[int | str, dict[str, Any]] = {
    409: {
        "description": (
            "`own_file_changed` (reason: the file changed since its scan: `POST"
            " /projects/{project}/scan`) or `preview_not_ready` (reason:"
            " `details.job`, `details.building` or `details.build_required`)."
        ),
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                "examples": {
                    "own_file_changed": {
                        "value": problem_example(
                            "conflict",
                            MESSAGES["own_file_changed"].format(
                                path="sieci/kanalizacja.gpkg", project="raba"
                            ),
                            reason="own_file_changed",
                        )
                    }
                },
            }
        },
    }
}
_RENDERED = ("preview_unavailable", "preview_busy", "preview_timeout")


def _images(media_type: str, *codes: str) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI responses of an own-data image or data route."""
    responses = image_responses(media_type, *codes)
    changed = _CHANGED_PROBLEM[409]
    conflict = responses.get(409)
    if conflict is None:
        responses[409] = changed
    else:
        examples = conflict["content"][PROBLEM_MEDIA_TYPE]["examples"]
        examples.update(changed["content"][PROBLEM_MEDIA_TYPE]["examples"])
        conflict["description"] = changed["description"]
    return responses


@router.get(
    "/files",
    response_model=OwnFileList,
    responses=problem_responses(404, 400),
)
def list_own_files(
    project: _Project,
    query: Annotated[OwnFilesQuery, Query()],
    visible: _Visible,
    queries: _Queries,
    settings: _Settings,
    paths: _Paths,
) -> OwnFileList:
    """List a project's own files by path, with their data folder.

    `state` filters by the file's state (`ok`, `unrecognized`, `unreadable`,
    `missing`) or its change since its last snapshot (`unsnapshotted`,
    `unchanged`, `changed`). A folder not scanned yet has `scanned_at: null`
    and no files: `POST /projects/{project}/scan` reads it.
    """
    return read_own_files(
        queries, settings.get(), paths, project, query, visible=visible
    )


@router.put(
    "/data-dir",
    response_model=OwnFolder,
    responses=problem_responses(403, 404, 400),
)
def put_data_dir(
    project: _Project,
    body: DataDirRequest,
    principal: _Principal,
    decisions: _Authorizer,
    settings: _Settings,
    queries: _Queries,
    paths: _Paths,
    jobs: _OptionalJobs,
) -> OwnFolder:
    """Give a project another data folder, or its default `dane/` again (`null`).

    Administrators only (the folder is where snapshots are written). The
    folder must be an existing, readable directory outside every store,
    Archiwista's data and other projects' folders (`422 validation_error`
    with `problems` otherwise). Its scan starts at once (`own_scan`).
    """
    return change_data_dir(
        decisions, principal, settings, queries, paths, jobs, project, body.path
    )


@router.get(
    _FILE,
    response_model=OwnFileCard,
    responses=problem_responses(404, 400),
)
async def get_own_file(
    project: _Project,
    file_id: _FileId,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    settings: _Settings,
) -> OwnFileCard:
    """Return everything known of an own file: layers, extent, snapshots, preview.

    `history` holds its observed states (newest first, at most 200),
    `snapshots` its snapshots in `.wersje/` with their `ref`, and `preview`
    the answer of `GET …/preview`.
    """
    return await own_file_card(
        queries,
        settings.get(),
        own_previews(request),
        project,
        file_id,
        principal=principal,
        visible=visible,
    )


@router.get(
    f"{_FILE}/snapshot-plan",
    response_model=SnapshotPlan,
    responses=problem_responses(403, 404, 400),
)
def get_snapshot_plan(
    project: _Project,
    file_id: _FileId,
    visible: _Visible,
    queries: _Queries,
    settings: _Settings,
    paths: _Paths,
) -> SnapshotPlan:
    """Plan a snapshot of a file without writing anything.

    What would be copied (size, destination, copy and content method),
    whether the last snapshot already holds the content (`unchanged_since`),
    why a snapshot would be refused now (`blocked`), free space and warnings
    (`editing_detected`).
    """
    return snapshot_plan(
        queries, settings.get(), paths, project, file_id, visible=visible
    )


@router.get(
    f"{_FILE}/layers",
    response_model=LayerSet,
    responses={**problem_responses(404, 400), **preview_problems("preview_busy")},
)
async def get_own_file_layers(
    project: _Project,
    file_id: _FileId,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    registry: _Registry,
    service: _Service,
) -> LayerSet | Response:
    """Return the layers of an own file for the Wachlarz: its versions.

    The working file (`key` `file`, „plik roboczy”) on top, then its
    snapshots newest first (`snapshot:<label>`), one object each with the
    state and addresses of its own `…/preview`: a file changed since its
    scan is `unavailable`. `frame` holds all their extents (their union with
    room for markers on its edges) in the planar CRS of their country (PL:
    EPSG:2180, CZ: EPSG:5514); each `thumbnail_url` draws its object in it,
    `tiles_url` are its map tiles.
    """
    detail = await asyncio.to_thread(
        own_file, queries, project, file_id, visible=visible
    )
    work = read_own_file_layers(detail, registry, service, principal=principal)
    try:
        return await while_connected(request, work)
    except ClientGone:
        return Response(status_code=CLIENT_GONE)


@job_router.post(
    "/scan",
    response_model=JobDetail,
    status_code=202,
    responses=problem_responses(404),
)
def start_project_scan(
    project: _Project,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    jobs: _Jobs,
    response: Response,
) -> JobDetail:
    """Scan the project's data folder in the background (`own_scan`, „Odśwież”).

    A waiting scan covering the folder is joined (`202` with that job).
    Follow it with `GET /jobs/{job}/events`.
    """
    job = start_own_scan(jobs, queries, project, principal=principal, visible=visible)
    return _accepted(job, response, jobs, visible)


@job_router.post(
    f"{_FILE}/snapshots",
    response_model=JobDetail,
    status_code=202,
    responses={**problem_responses(403, 404, 400), **_JOB_PROBLEMS},
)
def start_file_snapshot(
    project: _Project,
    file_id: _FileId,
    principal: _Principal,
    decisions: _Authorizer,
    queries: _Queries,
    settings: _Settings,
    paths: _Paths,
    jobs: _Jobs,
    response: Response,
    body: Annotated[SnapshotRequest | None, Body()] = None,
) -> JobDetail:
    """Snapshot a file into `.wersje/` in the background (`snapshot` job).

    The project's owner or an administrator only (`403 permission_denied`
    otherwise). The plan is checked first (`409 snapshot_blocked` with
    `reason`); one snapshot of a file at a time (`409 conflict` naming the
    running job: follow it instead). The result: `status` (`created`, or
    `unchanged` when the last snapshot holds the content), `label`,
    `content_sha256`, `size_bytes` and `seconds`.
    """
    note = "" if body is None else body.note
    job = start_snapshot(
        decisions,
        principal,
        jobs,
        queries,
        settings.get(),
        paths,
        project,
        file_id,
        note,
    )
    return _accepted(job, response, jobs, decisions.visible_projects(principal))


_INFO_RESPONSES = {
    **problem_responses(403, 404, 400),
    **preview_problems("preview_busy"),
}
_BUILD_RESPONSES = {
    200: {"model": PreviewInfo, "description": "Nothing needs building."},
    202: {"model": JobDetail, "description": "The `preview` job building it."},
    **problem_responses(403, 404, 400),
    **_CHANGED_PROBLEM,
    **preview_problems("preview_busy"),
}
_THUMBNAIL_RESPONSES = _images(PNG, *_RENDERED)
_TILE_RESPONSES = _images(PNG, *_RENDERED, "preview_not_ready")
_FEATURES_RESPONSES = _images(GEOJSON, *_RENDERED, "preview_not_ready")
_MEMBERS_RESPONSES = _images("application/json", *_RENDERED)
_Z = Annotated[int, Path(ge=0, le=MAX_ZOOM, description="Zoom level.")]
_X = Annotated[int, Path(ge=0, description="Column, 0 to 2^z - 1.")]
_Y = Annotated[int, Path(ge=0, description="Row, 0 to 2^z - 1.")]


@router.get(f"{_FILE}/preview", response_model=PreviewInfo, responses=_INFO_RESPONSES)
async def get_own_preview(
    project: _Project,
    file_id: _FileId,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
) -> PreviewInfo | Response:
    """Return the preview of an own file: state, styles, legend and addresses.

    A file changed since its scan is described with the reason
    `changed_since_scan` (`POST /projects/{project}/scan` refreshes it). Use
    the addresses it gives (`thumbnail_url`, `tiles_url`, `features_url`,
    `members_url`); never compose them.
    """
    ref = await own_ref(queries, project, file_id, visible=visible)
    return await info_answer(request, service, format_ref(ref), principal)


@router.get(
    f"{_SNAPSHOT}/preview", response_model=PreviewInfo, responses=_INFO_RESPONSES
)
async def get_snapshot_preview(
    project: _Project,
    file_id: _FileId,
    label: _Label,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
) -> PreviewInfo | Response:
    """Return the preview of a snapshot: state, styles, legend and addresses."""
    ref = await own_ref(queries, project, file_id, visible=visible, label=label)
    return await info_answer(request, service, format_ref(ref), principal)


@router.post(f"{_FILE}/preview", response_model=None, responses=_BUILD_RESPONSES)
async def build_own_preview(
    project: _Project,
    file_id: _FileId,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    jobs: _OptionalJobs,
    body: Annotated[BuildRequest | None, Body()] = None,
) -> Response:
    """Build the local preview of an own file (its COG or copy) in the background.

    As for a version: `202` with the `preview` job (`Location`), or `200`
    with the `PreviewInfo` when nothing needs building; past the auto-build
    limits it needs `force: true`.
    """
    ref = await own_ref(queries, project, file_id, visible=visible)
    return await _build(service, jobs, ref, principal, visible, body)


@router.post(f"{_SNAPSHOT}/preview", response_model=None, responses=_BUILD_RESPONSES)
async def build_snapshot_preview(
    project: _Project,
    file_id: _FileId,
    label: _Label,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    jobs: _OptionalJobs,
    body: Annotated[BuildRequest | None, Body()] = None,
) -> Response:
    """Build the local preview of a snapshot in the background, as of a file."""
    ref = await own_ref(queries, project, file_id, visible=visible, label=label)
    return await _build(service, jobs, ref, principal, visible, body)


@router.get(
    f"{_FILE}/preview.png", response_class=Response, responses=_THUMBNAIL_RESPONSES
)
async def get_own_thumbnail(
    project: _Project,
    file_id: _FileId,
    query: Annotated[ThumbnailQuery, Query()],
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return a PNG thumbnail of an own file, at most `size` pixels a side.

    In the file's CRS, or in the frame `bbox` (in `bbox_crs`) when given.
    """
    ref = await own_ref(queries, project, file_id, visible=visible)
    return await _thumbnail(request, service, ref, principal, query, if_none_match)


@router.get(
    f"{_SNAPSHOT}/preview.png", response_class=Response, responses=_THUMBNAIL_RESPONSES
)
async def get_snapshot_thumbnail(
    project: _Project,
    file_id: _FileId,
    label: _Label,
    query: Annotated[ThumbnailQuery, Query()],
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return a PNG thumbnail of a snapshot, at most `size` pixels a side."""
    ref = await own_ref(queries, project, file_id, visible=visible, label=label)
    return await _thumbnail(request, service, ref, principal, query, if_none_match)


@router.get(
    f"{_FILE}/tiles/{{z}}/{{x}}/{{y}}.png",
    response_class=Response,
    responses=_TILE_RESPONSES,
)
async def get_own_tile(
    project: _Project,
    file_id: _FileId,
    z: _Z,
    x: _X,
    y: _Y,
    query: Annotated[TileQuery, Query()],
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the map tile `z/x/y` of an own file (EPSG:3857, 256 pixels).

    Outside its `minzoom`–`maxzoom` or extent: `404`; before its local
    preview is built: `409 preview_not_ready`.
    """
    require_tile(z, x, y)
    ref = await own_ref(queries, project, file_id, visible=visible)
    return await _tile(
        request, service, ref, principal, (z, x, y), query, if_none_match
    )


@router.get(
    f"{_SNAPSHOT}/tiles/{{z}}/{{x}}/{{y}}.png",
    response_class=Response,
    responses=_TILE_RESPONSES,
)
async def get_snapshot_tile(
    project: _Project,
    file_id: _FileId,
    label: _Label,
    z: _Z,
    x: _X,
    y: _Y,
    query: Annotated[TileQuery, Query()],
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the map tile `z/x/y` of a snapshot (EPSG:3857, 256 pixels)."""
    require_tile(z, x, y)
    ref = await own_ref(queries, project, file_id, visible=visible, label=label)
    return await _tile(
        request, service, ref, principal, (z, x, y), query, if_none_match
    )


@router.get(f"{_FILE}/features", response_class=Response, responses=_FEATURES_RESPONSES)
async def get_own_features(
    project: _Project,
    file_id: _FileId,
    query: Annotated[FeaturesQuery, Query()],
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the features of a map view of an own file as GeoJSON in WGS84.

    Simplified to `zoom`, at most `limit` features; `number_matched`,
    `truncated` and `simplified` tell what was left out.
    """
    ref = await own_ref(queries, project, file_id, visible=visible)
    return await _features(request, service, ref, principal, query, if_none_match)


@router.get(
    f"{_SNAPSHOT}/features", response_class=Response, responses=_FEATURES_RESPONSES
)
async def get_snapshot_features(
    project: _Project,
    file_id: _FileId,
    label: _Label,
    query: Annotated[FeaturesQuery, Query()],
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the features of a map view of a snapshot as GeoJSON in WGS84."""
    ref = await own_ref(queries, project, file_id, visible=visible, label=label)
    return await _features(request, service, ref, principal, query, if_none_match)


@router.get(
    f"{_FILE}/members", response_model=ArchiveMembers, responses=_MEMBERS_RESPONSES
)
async def get_own_members(
    project: _Project,
    file_id: _FileId,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the members of an own archive: names, sizes; nothing unpacked."""
    ref = await own_ref(queries, project, file_id, visible=visible)
    return await members_answer(
        request, service, format_ref(ref), principal, if_none_match, OWN_CACHE_CONTROL
    )


@router.get(
    f"{_SNAPSHOT}/members",
    response_model=ArchiveMembers,
    responses=_MEMBERS_RESPONSES,
)
async def get_snapshot_members(
    project: _Project,
    file_id: _FileId,
    label: _Label,
    request: Request,
    principal: _Principal,
    visible: _Visible,
    queries: _Queries,
    service: _Service,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the members of a snapshot of an archive; nothing unpacked."""
    ref = await own_ref(queries, project, file_id, visible=visible, label=label)
    return await members_answer(
        request, service, format_ref(ref), principal, if_none_match, OWN_CACHE_CONTROL
    )


# What the preview routes of files and snapshots share.


async def _build(
    service: PreviewService,
    jobs: JobSupervisor | None,
    ref: ObjectRef,
    principal: Principal,
    visible: ProjectVisibility,
    body: BuildRequest | None,
) -> Response:
    force = body is not None and body.force
    return await build_answer(
        service,
        format_ref(ref),
        principal=principal,
        visible=visible,
        jobs=jobs,
        force=force,
    )


async def _thumbnail(
    request: Request,
    service: PreviewService,
    ref: ObjectRef,
    principal: Principal,
    query: ThumbnailQuery,
    if_none_match: str | None,
) -> Response:
    work = service.thumbnail(
        format_ref(ref),
        principal=principal,
        style=query.style,
        size=query.size,
        frame=query.frame(),
        if_none_match=if_none_match,
    )
    return await respond(request, work, PNG, OWN_CACHE_CONTROL)


async def _tile(
    request: Request,
    service: PreviewService,
    ref: ObjectRef,
    principal: Principal,
    tile: tuple[int, int, int],
    query: TileQuery,
    if_none_match: str | None,
) -> Response:
    z, x, y = tile
    work = service.tile(
        format_ref(ref),
        principal=principal,
        z=z,
        x=x,
        y=y,
        style=query.style,
        rescale=query.rescale_values(),
        if_none_match=if_none_match,
    )
    return await respond(request, work, PNG, OWN_CACHE_CONTROL)


async def _features(
    request: Request,
    service: PreviewService,
    ref: ObjectRef,
    principal: Principal,
    query: FeaturesQuery,
    if_none_match: str | None,
) -> Response:
    work = service.features(
        format_ref(ref),
        principal=principal,
        bbox=query.bbox_values(),
        zoom=query.zoom,
        layer=query.layer,
        limit=query.limit,
        if_none_match=if_none_match,
    )
    return await respond(request, work, GEOJSON, OWN_CACHE_CONTROL)


def _accepted(
    job: JobRecord, response: Response, jobs: JobSupervisor, visible: ProjectVisibility
) -> JobDetail:
    """Return a started job as the principal sees it, naming where to follow it."""
    response.headers["Location"] = f"{API_PREFIX}/jobs/{job.id}"
    return JobDetail.of(jobs.get(job.id, visible=visible) or job)
