"""Projects over HTTP: list, card and the changes of the project file (SPEC 9.2, 4.7).

A project is its directory holding ``archiwista-project.json``, Archiwista's
own file (A-ADR-049): a name, a description, an area, the store of each
producer and groups of pinned versions with their state in the index, and
problems with instructions. Every answer is filtered by the projects the
session's principal sees (A-ADR-029): another project is ``404 not_found``,
as if it did not exist. ``POST /projects`` writes a new project file: for any
person or their agent, who owns it (``project.create``). ``PATCH
/projects/{project}`` changes its name or description, ``PUT
/projects/{project}/area`` its area and ``PUT
/projects/{project}/stores/{producer}`` the store of a producer's pins: each
needs ``project.write`` (the owner or an administrator), takes the file's
lock and answers the project's card as the index holds it right after the
change. They translate only: ``archiwista.services.projects`` does the work,
and ``archiwista project-init``, ``project-edit``, ``project-area`` and
``project-store`` call the same functions. ``POST /projects/{project}/exports``
writes an export ``eksport/<name>/`` (and its zip) from the pins
(``project.write``), ``GET /projects/{project}/exports`` lists them and ``GET
…/exports/{name}/zip`` sends an export's zip to whoever sees the project
(``project-export``, ``project-exports``). ``GET
/projects/{project}/activity`` pages the project's entries of the action log
to whoever sees it (A-ADR-049 decision 14, ``project-activity``). The groups
are sets (A-ADR-049 erratum 6): ``POST /projects/{project}/groups`` writes a
new one (closed, or open with ``open``: a set in the making, also without
pins), ``…/groups/{group}/pins`` and ``…/unpin`` change an open one, ``DELETE
…/groups/{group}/calls/{call}`` removes a call of an open one and
``…/reopen`` opens a closed one for editing (``project-draft``,
``project-pin``, ``project-unpin``, ``project-uncall``, ``project-reopen``).
``POST /projects/{project}/jobs`` starts a job over the project's groups
(``archiwista.services.project_jobs``; ``project-verify``, ``project-check``,
``project-repin`` and ``project-restore``), ``POST
…/groups/{group}/close`` closes an open set no job writes into
(``project-close``) and ``DELETE /projects/{project}`` removes a project from
Archiwista, never its data, refused while a job of the project waits or runs
(``project-delete``): they need the job supervisor and are in ``job_router``.
Nothing here uses the network or writes a store: the jobs' workers do.
"""

from pathlib import Path as FilePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.responses import FileResponse

from archiwista.api import API_PREFIX
from archiwista.api.areas import index_path
from archiwista.api.dependencies import (
    authorizer,
    index_queries,
    plugin_registry,
    principal_preferences,
    settings_service,
    visible_projects,
    writable_projects,
)
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.files import CACHE_CONTROL
from archiwista.api.jobs import job_supervisor
from archiwista.api.models import (
    AreaChoice,
    GroupRequest,
    JobDetail,
    PinOutcome,
    PinsRequest,
    Preferences,
    ProjectCard,
    ProjectChange,
    ProjectItem,
    ProjectList,
    ProjectRequest,
    StoreChoice,
    UnpinRequest,
    staleness,
)
from archiwista.api.models_activity import ProjectActivity, ProjectActivityQuery
from archiwista.api.models_exports import (
    ExportRequest,
    ProjectExport,
    ProjectExportItem,
    ProjectExports,
)
from archiwista.api.models_owndata import copy_path
from archiwista.api.models_project_jobs import ProjectJobRequest
from archiwista.api.slots import checked_store
from archiwista.auth import Principal, ProjectVisibility, WritableProjects
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries
from archiwista.jobs import JobSupervisor
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import activity as activity_service
from archiwista.services import pins as pin_service
from archiwista.services import project_detail, project_jobs
from archiwista.services import projects as project_service
from archiwista.sources.registry import PluginRegistry

router = APIRouter(prefix="/projects", tags=["projects"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Writable = Annotated[WritableProjects, Depends(writable_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Preferences = Annotated[Preferences, Depends(principal_preferences)]
_Index = Annotated[FilePath, Depends(index_path)]
_Project = Annotated[
    str, Path(description="Project id (`project` of /projects).", examples=["raba"])
]
_Producer = Annotated[
    str,
    Path(
        description="Producer of the store, e.g. `kartograf`.", examples=["kartograf"]
    ),
]
_Group = Annotated[
    str,
    Path(description="A group's name (compared case-folded).", examples=["NMT 2023"]),
]
_Call = Annotated[
    int,
    Path(
        ge=0,
        description=(
            "The call's place in the group's `origin.calls`, from 0 (as"
            " `files[].call` of the download that made the set)."
        ),
        examples=[1],
    ),
]
# What every change of a project file may answer besides its card.
_CHANGE_RESPONSES = problem_responses(400, 403, 404, 409, 500)


def read_projects(
    queries: IndexQueries,
    settings: AppSettings,
    store: str | None,
    *,
    visible: ProjectVisibility,
    writable: WritableProjects,
) -> ProjectList:
    """Return the projects the principal sees, of all stores or one.

    ``writable`` says of each project whether the principal may change it.
    """
    freshness = queries.freshness()
    stores = checked_store(store, settings, freshness)
    projects = queries.projects(visible=visible, store=store)
    return ProjectList(
        items=[ProjectItem.of(project, writable=writable) for project in projects],
        **staleness(freshness, stores),
    )


def project_card(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    key: str,
    *,
    visible: ProjectVisibility,
    writable: WritableProjects,
) -> ProjectCard:
    """Return a project's groups, pins and problems from the index.

    ``writable`` says whether the principal may change the project.

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    """
    detail = project_detail(queries, key, visible=visible)
    if detail is None:
        raise NotFoundError(message("project.not_found", project=key))
    stores = {item.store for item in detail.project.stores if item.store is not None}
    freshness = staleness(queries.freshness(), stores)
    path = copy_path(settings, preferences, FilePath(detail.project.path))
    return ProjectCard.of(detail, path, freshness, writable=writable)


def _changed_card(
    decisions: Authorizer,
    principal: Principal,
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    key: str,
) -> ProjectCard:
    """Return the card of a project just changed, read after the change."""
    return project_card(
        queries,
        settings,
        preferences,
        key,
        visible=decisions.visible_projects(principal),
        writable=decisions.writable_projects(principal),
    )


@router.get("", response_model=ProjectList, responses=problem_responses(400))
def list_projects(
    visible: _Visible,
    writable: _Writable,
    settings: _Settings,
    queries: _Queries,
    store: Annotated[
        str | None,
        Query(description="Only projects whose store of a producer is this one."),
    ] = None,
) -> ProjectList:
    """List projects the session's principal sees, with their counts.

    `project_write` says of each project whether the principal may change it.
    """
    return read_projects(
        queries, settings.get(), store, visible=visible, writable=writable
    )


@router.post(
    "", response_model=ProjectCard, status_code=201, responses=_CHANGE_RESPONSES
)
def create_project(
    body: ProjectRequest,
    principal: _Principal,
    decisions: _Authorizer,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
    response: Response,
) -> ProjectCard:
    """Create a project: Archiwista writes `archiwista-project.json` in `path`.

    The directory is made when missing; the project names no store until its
    first pin, and the area, when given, is written into its `obszary/`. The
    index holds the project at once: the answer is `201` with its card and
    `Location: /api/v1/projects/{project}`. Where no project was, any person
    or their agent creates one and owns it, with the visibility of the
    setting `default_project_visibility` (the owner changes it with `PUT
    /projects/{project}/access`); a directory with an access entry needs its
    owner or an administrator (`403 permission_denied`). The creation is in
    the action log (`project.create`). Refused: a path that is not absolute
    or leaves the project directories of the settings (`403`,
    `path_outside_root`), a place a scan would not find (`400`,
    `project_not_discoverable`: more than four levels down, in a hidden
    directory or in a store), a project directory of the settings that is
    missing (`400`, `project_dir_missing`), an unknown area (`404`), a
    directory that holds a project file (`409`, `project_exists`), a lock
    another change holds (`409`, `project_locked`, `details.lock`) and a
    directory that cannot be written (`500`, `io_error`,
    `project_file_write_failed`). Nothing uses the network.
    """
    config = settings.get()
    key = project_service.create_project(
        registry,
        config,
        queries,
        index,
        decisions,
        path=body.path,
        name=body.name,
        description=body.description,
        area_id=body.area_id,
        actor=principal,
    )
    response.headers["Location"] = f"{API_PREFIX}/projects/{key}"
    # Read after the creation: a new project is the creator's now.
    return _changed_card(decisions, principal, queries, config, preferences, key)


@router.get("/{project}", response_model=ProjectCard, responses=problem_responses(404))
def get_project(
    project: _Project,
    visible: _Visible,
    writable: _Writable,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
) -> ProjectCard:
    """Return a project: its stores, area, groups with their pins, and problems.

    Pins carry their state in the index (`ok`, `missing`, `sha256_mismatch`,
    `unknown`); problems carry fix instructions. An invalid project file or
    one of a newer format is listed with its problem and nothing else of it.
    `project_write` says whether the principal may change the project.
    """
    return project_card(
        queries,
        settings.get(),
        preferences,
        project,
        visible=visible,
        writable=writable,
    )


@router.patch("/{project}", response_model=ProjectCard, responses=_CHANGE_RESPONSES)
def update_project(
    project: _Project,
    body: ProjectChange,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Change a project's name or description (`project.update` in the log).

    Needs the project's owner or an administrator (`403 permission_denied`).
    Refused: a project file Archiwista cannot read (`409`,
    `invalid_project_file`, `unsupported_project_schema`), a lock another
    change holds (`409`, `project_locked`), a name that breaks the file's
    rule (`409`, `invalid_project_file` with the member's pointer) and a file
    that cannot be written (`500`, `io_error`).
    """
    config = settings.get()
    key = project_service.update_project(
        registry,
        config,
        queries,
        index,
        decisions,
        project,
        name=body.name,
        description=body.description,
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


@router.put("/{project}/area", response_model=ProjectCard, responses=_CHANGE_RESPONSES)
def set_project_area(
    project: _Project,
    body: AreaChoice,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Set a project's area from `/areas`, or clear it with `null` (`project.area`).

    The area is written into the project's `obszary/` as `<area id>.geojson`;
    a file of another area is never overwritten or removed. Needs the
    project's owner or an administrator. Refused as `PATCH` is, and an
    unknown area (`404`).
    """
    config = settings.get()
    key = project_service.set_area(
        registry,
        config,
        queries,
        index,
        decisions,
        project,
        area_id=body.area_id,
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


@router.put(
    "/{project}/stores/{producer}",
    response_model=ProjectCard,
    responses=_CHANGE_RESPONSES,
)
def set_project_store(
    project: _Project,
    producer: _Producer,
    body: StoreChoice,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Set the configured store of a producer's pins (`project.store` in the log).

    For a store that moved or is mounted at another path: the pins are
    relative to the store, so they stay. The root is written relative to the
    project directory when the store has path aliases, else absolute. Needs
    the project's owner or an administrator. Refused as `PATCH` is, a store
    that is not configured (`404`) and one without a directory of the
    producer (`400`, `store_without_producer`).
    """
    config = settings.get()
    key = project_service.set_store(
        registry,
        config,
        queries,
        index,
        decisions,
        project,
        producer=producer,
        store=body.store,
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


def export_answer(
    settings: AppSettings,
    queries: IndexQueries,
    registry: PluginRegistry,
    decisions: Authorizer,
    preferences: Preferences,
    key: str,
    body: ExportRequest,
    *,
    actor: Principal,
    visible: ProjectVisibility,
) -> ProjectExport:
    """Write a project's export and return the route's answer (API and CLI)."""
    done = project_service.export_project(
        settings,
        queries,
        registry,
        decisions,
        key,
        name=body.name,
        groups=body.groups,
        with_zip=body.zip,
        actor=actor,
        visible=visible,
    )
    return ProjectExport.of(done, settings, preferences)


def exports_answer(
    settings: AppSettings,
    queries: IndexQueries,
    preferences: Preferences,
    key: str,
    *,
    visible: ProjectVisibility,
) -> ProjectExports:
    """Return a project's exports as the route answers them (API and CLI)."""
    listings = project_service.project_exports(settings, queries, key, visible=visible)
    return ProjectExports(
        items=[ProjectExportItem.of(item, settings, preferences) for item in listings]
    )


def activity_answer(
    decisions: Authorizer,
    queries: IndexQueries,
    key: str,
    query: ProjectActivityQuery,
    *,
    visible: ProjectVisibility,
) -> ProjectActivity:
    """Return a page of a project's activity as the route answers it (API and CLI)."""
    found = activity_service.project_activity(
        decisions.state,
        queries,
        key,
        visible=visible,
        cursor=query.cursor,
        limit=query.limit,
    )
    return ProjectActivity.of(found)


@router.post(
    "/{project}/groups",
    response_model=PinOutcome,
    status_code=201,
    responses=_CHANGE_RESPONSES,
)
def add_project_group(
    project: _Project,
    body: GroupRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> PinOutcome:
    """Pin versions the store holds into a new group, or make an empty draft.

    The versions are named (`versions`: a store and a path, older ones too)
    or chosen by the query of `GET /slots` (`query`: the versions of its
    rows on every page, `current` by default). Their SHA-256, size, unit and
    label come from the index: no network, no producer. A version that is
    not present or has no SHA-256 is not pinned and is listed in `skipped`;
    one named twice is counted in `already`. The first pin of a producer
    names the project's store of that producer. The group is written closed
    with its digest (`pins_sha256`); with `open` it is left open, a set in
    the making, and `versions`, `query` and `from` may then be left out (an
    empty draft); a group whose every version was skipped is open too.
    Logged as `project.pin` with `open`. Needs the project's owner or an
    administrator (`403`). Refused: a taken name (`409`, `group_exists`), a
    name breaking the rule (`400`, `invalid_group_name`), more than 10,000
    versions (`400`, `too_many_pins`, `details.count`; nothing written), an
    open group given versions of several producers (`409`, `set_producer`),
    a version of another store than the project's (`409`, `other_store`), a
    project store matching no configured one (`409`, `unknown_store`), and
    as `PATCH /projects/{project}` refuses.
    """
    return pin_outcome(
        project,
        body,
        body.name,
        principal=principal,
        decisions=decisions,
        visible=visible,
        registry=registry,
        settings=settings.get(),
        preferences=preferences,
        queries=queries,
        index=index,
        new=True,
    )


@router.post(
    "/{project}/exports",
    response_model=ProjectExport,
    status_code=201,
    responses=problem_responses(400, 403, 404, 409, 500),
)
def export_project(
    project: _Project,
    body: ExportRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    registry: _Registry,
) -> ProjectExport:
    """Write the export `eksport/<name>/` of a project from its pins (`project.export`).

    Each pinned version once, copied (never linked) under its original name
    into the folder of its category (`NMT`, `BDOT`, `ORTO`…, by its
    producer), with the companion files the store holds beside it (`.prj`,
    `.tfw`, `.aux.xml`, the parts of a Shapefile; never a `*.meta.json`);
    two files of one name in a folder both get their version's label before
    the extension. `README.txt` (Polish) describes every file (product,
    year and label, coordinate and height systems, size, SHA-256, the groups
    that pin it) and lists each data source's attribution once. With `zip`
    the folder's content is also `eksport/<name>.zip`. An export of that
    name is replaced whole, its ZIP too (removed when `zip` is false). A pin
    whose store is not configured, or whose version is not present, is left
    out and counted in `skipped`. Needs the project's owner or an
    administrator (`403 permission_denied`). Refused: an unknown group
    (`404`), a project file Archiwista cannot read (`409`,
    `invalid_project_file`, `unsupported_project_schema`) and a file that
    cannot be copied or written (`500`, `io_error`; the old export stays).
    Offline; the project file is not written.
    """
    return export_answer(
        settings.get(),
        queries,
        registry,
        decisions,
        preferences,
        project,
        body,
        actor=principal,
        visible=visible,
    )


@router.get(
    "/{project}/exports",
    response_model=ProjectExports,
    responses=problem_responses(403, 404),
)
def list_project_exports(
    project: _Project,
    visible: _Visible,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
) -> ProjectExports:
    """List a project's exports, each saying whether the project changed after it.

    `changed_since`: the project file was written after the export, so the
    export may no longer show its pins; write it again. `zip`: the export
    has its ZIP (`GET …/exports/{name}/zip`). For whoever sees the project.
    """
    return exports_answer(
        settings.get(), queries, preferences, project, visible=visible
    )


@router.get(
    "/{project}/exports/{name}/zip",
    response_class=FileResponse,
    responses={
        200: {
            "description": (
                "The export's ZIP, `Content-Disposition: attachment` as"
                " `<name>.zip`: its folders and `README.txt`; `Cache-Control:"
                " private, no-store`."
            ),
            "content": {"application/zip": {}},
        },
        **problem_responses(403, 404),
    },
)
def get_project_export_zip(
    project: _Project,
    name: Annotated[
        str, Path(description="The export's name.", examples=["raba-2024"])
    ],
    visible: _Visible,
    settings: _Settings,
    queries: _Queries,
) -> FileResponse:
    """Send the ZIP of a project's export, written with `zip` (`eksport/<name>.zip`).

    For whoever sees the project; `404 not_found` for an export without
    one. A link of the interface (`Sec-Fetch-Site: same-origin`) needs no
    `X-Archiwista-CSRF` and nothing is cached, as a file download.
    """
    found = project_service.project_export_zip(
        settings.get(), queries, project, name, visible=visible
    )
    return FileResponse(
        found,
        media_type="application/zip",
        filename=found.name,
        headers={"Cache-Control": CACHE_CONTROL},
    )


@router.get(
    "/{project}/activity",
    response_model=ProjectActivity,
    responses=problem_responses(400, 404),
)
def get_project_activity(
    project: _Project,
    query: Annotated[ProjectActivityQuery, Query()],
    visible: _Visible,
    decisions: _Authorizer,
    queries: _Queries,
) -> ProjectActivity:
    """Page what was done to a project and its jobs, newest first.

    The project's entries of the action log: its changes (`project.*`) and
    the start, retry and cancelling of its jobs, done or failed. For whoever
    sees the project; the client address and the session are not given.
    """
    return activity_answer(decisions, queries, project, query, visible=visible)


@router.post(
    "/{project}/groups/{group}/pins",
    response_model=PinOutcome,
    responses=_CHANGE_RESPONSES,
)
def add_group_pins(
    project: _Project,
    group: _Group,
    body: PinsRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> PinOutcome:
    """Pin versions the store holds into an open group (`project.pin`).

    As `POST /projects/{project}/groups`, into a set in the making of either
    origin: a version the group pins already is counted in `already`; into a
    group of the plan window the pins are hand pins (`calls` `[]`, checked
    and re-pinned by their own calls) and the request is kept in
    `origin.selections`. Refused also: an unknown group (`404`,
    `group_not_found`), a closed one (`409`, `set_closed`: open it for
    editing first) and a version of another producer than the group's
    (`409`, `set_producer`).
    """
    return pin_outcome(
        project,
        body,
        group,
        principal=principal,
        decisions=decisions,
        visible=visible,
        registry=registry,
        settings=settings.get(),
        preferences=preferences,
        queries=queries,
        index=index,
        new=False,
    )


@router.post(
    "/{project}/groups/{group}/unpin",
    response_model=ProjectCard,
    responses=_CHANGE_RESPONSES,
)
def unpin_group_pins(
    project: _Project,
    group: _Group,
    body: UnpinRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Remove pins of an open group (`project.unpin`); the versions stay in the store.

    A pin the group does not hold is ignored. Needs the project's owner or
    an administrator. Refused: an unknown group (`404`, `group_not_found`),
    a closed one (`409`, `set_closed`), and as `PATCH /projects/{project}`
    refuses.
    """
    config = settings.get()
    key = pin_service.unpin(
        registry,
        config,
        queries,
        index,
        decisions,
        project,
        group=group,
        pins=[(item.producer, item.version) for item in body.pins],
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


@router.delete(
    "/{project}/groups/{group}",
    response_model=ProjectCard,
    responses=_CHANGE_RESPONSES,
)
def remove_project_group(
    project: _Project,
    group: _Group,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Remove a group with its pins (`project.unpin`); the versions stay.

    Open or closed. Needs the project's owner or an administrator. Refused:
    an unknown group (`404`, `group_not_found`), and as `PATCH
    /projects/{project}` refuses.
    """
    config = settings.get()
    key = pin_service.unpin(
        registry,
        config,
        queries,
        index,
        decisions,
        project,
        group=group,
        pins=None,
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


@router.delete(
    "/{project}/groups/{group}/calls/{call}",
    response_model=ProjectCard,
    responses=_CHANGE_RESPONSES,
)
def remove_group_call(
    project: _Project,
    group: _Group,
    call: _Call,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Remove a call of an open group with the pins only its run pinned.

    `call` is the place in `origin.calls`, from 0; the higher places shift
    down in every pin's `calls`. A pin whose `calls` becomes empty goes; a
    pin added by hand (`calls` `[]`) and a pin of another call too stay. The
    last call removed, the group is a local one. Logged as `project.unpin`
    with `call` and the pins removed; the versions stay in the store. Needs
    the project's owner or an administrator. Refused: an unknown group
    (`404`, `group_not_found`) or call (`404`, `call_not_found`), a closed
    group (`409`, `set_closed`), a group holding a pin written before the
    sets had states, which belongs to every call (`409`,
    `pins_without_calls`: re-pin it first), and as `PATCH
    /projects/{project}` refuses.
    """
    config = settings.get()
    key = pin_service.remove_call(
        registry,
        config,
        queries,
        index,
        decisions,
        project,
        group=group,
        call=call,
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


@router.post(
    "/{project}/groups/{group}/reopen",
    response_model=ProjectCard,
    responses=_CHANGE_RESPONSES,
)
def reopen_project_group(
    project: _Project,
    group: _Group,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Open a closed set for editing (`project.set_open`), „Otwórz do edycji”.

    `state` becomes `open` and `closed_at`, `closed_by` and `pins_sha256`
    go; programs that read only closed sets refuse it until it is closed
    again. A group written before the sets had states is opened alike.
    Needs the project's owner or an administrator. Refused: an unknown group
    (`404`, `group_not_found`), an open one (`409`, `set_open`), and as
    `PATCH /projects/{project}` refuses.
    """
    config = settings.get()
    key = pin_service.reopen_set(
        registry,
        config,
        queries,
        index,
        decisions,
        project,
        group=group,
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


def pin_outcome(
    project: str,
    body: PinsRequest | GroupRequest,
    group: str,
    *,
    principal: Principal,
    decisions: Authorizer,
    visible: ProjectVisibility,
    registry: PluginRegistry,
    settings: AppSettings,
    preferences: Preferences,
    queries: IndexQueries,
    index: FilePath,
    new: bool,
) -> PinOutcome:
    """Pin a request's versions into a group; return the outcome with the card."""
    result = pin_service.pin_local(
        registry,
        settings,
        queries,
        index,
        decisions,
        project,
        group=group,
        new=new,
        source=body.source,
        versions=body.chosen(),
        query=body.query,
        actor=principal,
        visible=visible,
        open_set=isinstance(body, GroupRequest) and body.open,
    )
    card = _changed_card(
        decisions, principal, queries, settings, preferences, result.project
    )
    return PinOutcome.of(result, card)


job_router = APIRouter(prefix="/projects", tags=["projects"])

_Jobs = Annotated[JobSupervisor, Depends(job_supervisor)]
_JOB_UNSUPPORTED: dict[int | str, dict[str, Any]] = {
    422: {
        "description": (
            "`unsupported`: a group's producer offers no commands (`no_commands`),"
            " or a local group to re-pin has a pin whose call the producer cannot"
            " rebuild (`command_not_rebuildable`)."
        ),
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                "example": problem_example(
                    "unsupported",
                    message("command.no_commands", "en", producer="obserwator"),
                    reason="no_commands",
                ),
            }
        },
    }
}


@job_router.post(
    "/{project}/jobs",
    response_model=JobDetail,
    status_code=202,
    responses={**problem_responses(400, 403, 404, 409, 503), **_JOB_UNSUPPORTED},
)
def start_project_job(
    project: _Project,
    body: ProjectJobRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    queries: _Queries,
    jobs: _Jobs,
    response: Response,
) -> JobDetail:
    """Start a job over a project's groups; answer `202` with the job.

    `groups` names the groups, every group when left out. `verify` hashes the
    pinned files in their store without the network; `check` compares the
    pins with the source, without effects; `repin` runs one group's calls in
    the producer's update mode and pins the group anew only when every call
    and unit succeeded; `restore` downloads the missing pinned versions
    again in the default mode and never changes the file. A `repin` or a
    `restore` may name `plan_job`, the `check` job whose plan the person
    confirmed (the card's plan window, ADR-042 erratum 2); the worker plans
    again. The job has no store (`store` `null`) and the parameters `project`
    and `groups`, a `repin` and a `restore` also `plan_job` (`null` when not
    given); its `result` is described in AGENT_API 9. The answer has
    `Location: /api/v1/jobs/{job}`; follow the job with `GET
    /jobs/{job}/events`. A project the session does not see is `404`, as is
    a group it does not have; `repin` and `restore` need `project.write` and
    `store.write` (`403 permission_denied`). Refused before a job exists: a
    `repin` without exactly one group and a `plan_job` of a `verify` or a
    `check` (`400`), a `repin` of a closed set (`409 set_closed`: open it for
    editing first), a group whose producer offers no commands (`422
    no_commands`), a local group, or a pin added by hand to a plan group, to
    re-pin with a pin known not rebuildable (`422 command_not_rebuildable`), a
    group whose producer's store the project names matches no configured
    store (`409 unknown_store`), a `plan_job` the session does not see or
    without a plan yet (`404`: waiting, running or failed) or that is no
    check of the named groups of the project as they are now (`409
    plan_mismatch`, the job in `details.job`), a second job of the project
    (`409 conflict`, that job in `details.job`), offline mode for all but
    `verify` (`409 offline_mode`) and a producer whose plugin is missing
    (`503`).
    """
    job = project_jobs.start(
        registry,
        settings.get(),
        jobs,
        queries,
        decisions,
        project,
        kind=body.kind,
        groups=body.groups,
        actor=principal,
        visible=visible,
        plan_job=body.plan_job,
    )
    response.headers["Location"] = f"{API_PREFIX}/jobs/{job.id}"
    return JobDetail.of(job)


@job_router.post(
    "/{project}/groups/{group}/close",
    response_model=ProjectCard,
    responses=_CHANGE_RESPONSES,
)
def close_project_group(
    project: _Project,
    group: _Group,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
    index: _Index,
    jobs: _Jobs,
) -> ProjectCard:
    r"""Close an open set (`project.set_close`), „Zamknij zestaw”.

    Writes `state` `closed` with `closed_at`, `closed_by` and `pins_sha256`:
    the SHA-256 of the lines `<producer>\t<version>\t<sha256>\n`, one per
    pin, sorted by producer and version. A closed set takes no pin, loses
    none and is not re-pinned until it is opened for editing. The pins'
    states are the index's, from the last scan (run `verify` first to hash
    them). Needs the project's owner or an administrator. Refused, in this
    order: an unknown group (`404`, `group_not_found`); a closed set (`409`,
    `set_closed`); a job that writes into it waits or runs, a `download`
    pinning into it or a `repin` of it (`409`, `set_job_active`, that job in
    `details.job`); no pin (`409`, `set_empty`); a pin that is not `ok`
    (`409`, `set_pins_not_ok`: `details.counts` by state, the first 100 in
    `details.pins`); and as `PATCH /projects/{project}` refuses.
    """
    config = settings.get()
    key = pin_service.close_set(
        registry,
        config,
        queries,
        index,
        decisions,
        jobs,
        project,
        group=group,
        actor=principal,
        visible=visible,
    )
    return _changed_card(decisions, principal, queries, config, preferences, key)


@job_router.delete(
    "/{project}",
    status_code=204,
    response_class=Response,
    responses=_CHANGE_RESPONSES,
)
def delete_project(
    project: _Project,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    settings: _Settings,
    queries: _Queries,
    index: _Index,
    jobs: _Jobs,
) -> Response:
    """Remove a project from Archiwista, never its data (`project.delete`); `204`.

    Under the project's lock it removes only what Archiwista wrote in the
    directory: `archiwista-project.json`, the area files of `obszary/` and
    the exports `eksport/`. The own data (`dane/`, its snapshots `.wersje/`)
    and every other file stay; the directory goes only when it is then
    empty. The project's access entry and its rows of the index go; no store
    is touched, so its pinned versions stay there. Its activity stays in the
    action log. Needs the project's owner or an administrator (`403
    permission_denied`); a project the session does not see is `404`.
    Refused: a job of the project that waits or runs (`409 conflict`, that
    job in `details.job`), a project file Archiwista cannot read (`409`,
    `invalid_project_file`, `unsupported_project_schema`), a lock another
    change holds (`409`, `project_locked`) and an entry that cannot be
    removed (`500`, `io_error`).
    """
    project_service.delete_project(
        settings.get(),
        queries,
        index,
        decisions,
        jobs,
        project,
        actor=principal,
        visible=visible,
    )
    return Response(status_code=204)
