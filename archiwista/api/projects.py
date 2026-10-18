"""Projects over HTTP: list, detail and the producer's status (SPEC 9.2, 4.7).

Read only: tasks with their existing commands and options, pinned versions
(older ones too) and problems with instructions; nothing runs or changes a
project. Every answer is filtered by the projects the session's principal
sees (A-ADR-029): another project is ``404 not_found``, as if it did not
exist. ``/projects/{project}/status`` asks the producer now (no network, no
hashing); while the project's store is unavailable it answers the check of
the last scan as ``stale``, and ``503 store_unavailable`` when there is none.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from archiwista.api.dependencies import (
    index_queries,
    plugin_registry,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import problem_responses
from archiwista.api.models import (
    ProjectCard,
    ProjectItem,
    ProjectList,
    ProjectStatus,
    TaskStatus,
    staleness,
)
from archiwista.api.slots import checked_store
from archiwista.auth import ProjectVisibility
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import NotFoundError, SourceUnavailableError
from archiwista.index import IndexQueries
from archiwista.messages import MESSAGES
from archiwista.services import project_detail, project_status
from archiwista.sources.registry import PluginRegistry

router = APIRouter(prefix="/projects", tags=["projects"])

_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Project = Annotated[
    str, Path(description="Project id (`project` of /projects).", examples=["raba"])
]


def read_projects(
    queries: IndexQueries,
    settings: AppSettings,
    store: str | None,
    *,
    visible: ProjectVisibility,
) -> ProjectList:
    """Return the projects the principal sees, of all stores or one."""
    freshness = queries.freshness()
    stores = checked_store(store, settings, freshness)
    projects = queries.projects(visible=visible, store=store)
    return ProjectList(
        items=[ProjectItem.of(project) for project in projects],
        **staleness(freshness, stores),
    )


def project_card(
    queries: IndexQueries, key: str, *, visible: ProjectVisibility
) -> ProjectCard:
    """Return a project's tasks, pins and problems from the index.

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    """
    detail = project_detail(queries, key, visible=visible)
    if detail is None:
        raise NotFoundError(MESSAGES["project_not_found"].format(project=key))
    store = detail.project.store
    stores = set() if store is None else {store}
    return ProjectCard.of(detail, staleness(queries.freshness(), stores))


def check_project(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    key: str,
    *,
    visible: ProjectVisibility,
) -> ProjectStatus:
    """Ask the project's producer for its status, or answer the scan's check.

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    SourceStateError
        The producer's plugin is not available.
    SourceUnavailableError
        Without a ``state``: the project's store is unavailable and no scan
        checked the project (``503 store_unavailable``).
    PathOutsideRootError
        The project's directory or manifest resolves outside the project
        directories (``403 path_outside_root``).
    ProducerError
        The producer cannot read the manifest.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(MESSAGES["project_not_found"].format(project=key))
    project = record.project
    registry.adapter(project.producer)
    if project.store is not None and _unavailable(
        queries, settings, registry, project.store, project.producer
    ):
        if project.status is None:
            message = MESSAGES["api_project_store_unavailable"].format(
                project=key, store=project.store
            )
            raise SourceUnavailableError(message)
        return ProjectStatus(
            project=key,
            producer=project.producer,
            status=project.status,
            checked_at=project.scanned_at,
            stale=True,
            stale_reason="store_unavailable",
            tasks=[
                TaskStatus(task=task.task_id, status=task.status)
                for task in record.tasks
            ],
        )
    checked_at = datetime.now(UTC)
    info = project_status(
        queries, registry, key, visible=visible, project_dirs=settings.project_dirs
    )
    if info is None:  # pragma: no cover - removed by a scan in between
        raise NotFoundError(MESSAGES["project_not_found"].format(project=key))
    return ProjectStatus(
        project=key,
        producer=project.producer,
        status=info.status,
        checked_at=checked_at,
        stale=False,
        stale_reason=None,
        tasks=[
            TaskStatus(task=task.task_id, status=task.status) for task in info.tasks
        ],
    )


def _unavailable(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    store: str,
    producer: str,
) -> bool:
    """Whether a store is unavailable: as last recorded, or by a probe now."""
    if any(item.stale for item in queries.freshness() if item.store == store):
        return True
    config = settings.store(store)
    root = None if config is None else config.roots().get(producer)
    return root is not None and registry.probe(producer, root).status != "available"


@router.get("", response_model=ProjectList, responses=problem_responses(422))
def list_projects(
    visible: _Visible,
    settings: _Settings,
    queries: _Queries,
    store: Annotated[
        str | None, Query(description="Only projects of this store.")
    ] = None,
) -> ProjectList:
    """List projects the session's principal sees, with their counts."""
    return read_projects(queries, settings.get(), store, visible=visible)


@router.get("/{project}", response_model=ProjectCard, responses=problem_responses(404))
def get_project(project: _Project, visible: _Visible, queries: _Queries) -> ProjectCard:
    """Return a project: tasks with commands and options, pins and problems.

    Pins carry their state in the index (`ok`, `missing`, `sha256_mismatch`,
    `unknown`); problems carry Polish fix instructions.
    """
    return project_card(queries, project, visible=visible)


@router.get(
    "/{project}/status",
    response_model=ProjectStatus,
    responses=problem_responses(403, 404, 422, 503),
)
def get_project_status(
    project: _Project,
    visible: _Visible,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> ProjectStatus:
    """Return the producer's check of the project now: each task's worst file.

    No network and no hashing. While the store is unavailable the answer is
    the last scan's check, marked `stale`. A project directory that leaves
    the project directories (a symbolic link) is refused (`path_outside_root`).
    """
    return check_project(queries, settings.get(), registry, project, visible=visible)
