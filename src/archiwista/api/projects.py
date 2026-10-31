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
writes an export ``zestawy/<name>/`` from the pins (``project.write``) and
``GET /projects/{project}/exports`` lists them to whoever sees the project
(``project-export``, ``project-exports``). Nothing here uses the network or
writes a store.
"""

from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

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
from archiwista.api.errors import problem_responses
from archiwista.api.models import (
    AreaChoice,
    Preferences,
    ProjectCard,
    ProjectChange,
    ProjectItem,
    ProjectList,
    ProjectRequest,
    StoreChoice,
    staleness,
)
from archiwista.api.models_exports import (
    ExportRequest,
    ProjectExport,
    ProjectExportItem,
    ProjectExports,
)
from archiwista.api.models_owndata import copy_path
from archiwista.api.slots import checked_store
from archiwista.auth import Principal, ProjectVisibility, WritableProjects
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import project_detail
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
        decisions,
        key,
        name=body.name,
        groups=body.groups,
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
) -> ProjectExport:
    """Write the export `zestawy/<name>/` of a project from its pins (`project.export`).

    `pliki.txt` lists each pinned version's file once, in the order of the
    groups and their pins, relative to the export when both lie on one
    share, else absolute; `ATRYBUCJE.txt` each attribution the sources require
    once. Both UTF-8 with LF, each replaced whole when written again. A pin
    whose store is not configured, or whose version is not present, is left
    out and counted in `skipped`. Needs the project's owner or an
    administrator (`403 permission_denied`). Refused: an unknown group
    (`404`), a project file Archiwista cannot read (`409`,
    `invalid_project_file`, `unsupported_project_schema`) and a file that
    cannot be written (`500`, `io_error`). Offline; the project file is not
    written.
    """
    return export_answer(
        settings.get(),
        queries,
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
    export may no longer show its pins; write it again. For whoever sees the
    project.
    """
    return exports_answer(
        settings.get(), queries, preferences, project, visible=visible
    )
