"""Projects over HTTP: list, detail, the producers' status and changes (SPEC 9.2, 4.7).

A project is its directory, with the manifest of one producer or of both:
tasks with their producer, existing commands and options, pinned versions
(older ones too) and problems with instructions. Every answer is filtered by
the projects the session's principal sees (A-ADR-029): another project is
``404 not_found``, as if it did not exist. ``/projects/{project}/status``
asks each manifest's producer now (no network, no hashing); while a
manifest's store is unavailable it answers that manifest's check of the last
scan as ``stale``, and ``503 store_unavailable`` when there is none. ``POST
/projects`` creates a manifest through its producer, ``POST
/projects/{project}/tasks`` adds a task and ``DELETE
/projects/{project}/tasks/{name}`` removes one (ADR-039): each needs
``project.write`` (the owner or an administrator) and answers the project's
card as the index holds it right after the change. ``POST
/projects/{project}/jobs`` starts a job of the project's tasks (ADR-040):
``download`` and ``repin`` need ``project.write`` and ``store.write``,
``check`` and ``verify`` only to see the project; it answers ``202`` with the
job and is in ``job_router``, served with the job supervisor. A change and a
job act on one manifest: the one of the ``producer`` they name, else the
project's only one. They translate only: ``archiwista.services.projects``
and ``archiwista.services.project_jobs`` do the work, and ``archiwista
project-init``, ``project-add``, ``project-remove``, ``project-download``,
``project-repin``, ``project-check`` and ``project-verify`` call the same
functions. Nothing here uses the network or writes a store: a job's worker
does.
"""

from datetime import UTC, datetime
from pathlib import Path as FilePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response

from archiwista.api import API_PREFIX
from archiwista.api.areas import index_path
from archiwista.api.dependencies import (
    authorizer,
    index_queries,
    plugin_registry,
    settings_service,
    visible_projects,
    writable_projects,
)
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.jobs import job_supervisor
from archiwista.api.models import (
    JobDetail,
    ManifestStatus,
    ProjectCard,
    ProjectItem,
    ProjectJobRequest,
    ProjectList,
    ProjectRequest,
    ProjectStatus,
    TaskRequest,
    TaskStatus,
    staleness,
)
from archiwista.api.slots import checked_store
from archiwista.auth import Principal, ProjectVisibility, WritableProjects
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import NotFoundError, SourceUnavailableError
from archiwista.index import IndexQueries, ProjectManifestRef, ProjectRecord
from archiwista.jobs import JobSupervisor
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import project_detail, project_jobs, project_status
from archiwista.services import projects as project_service
from archiwista.sources.registry import PluginRegistry

router = APIRouter(prefix="/projects", tags=["projects"])
job_router = APIRouter(prefix="/projects", tags=["projects"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Writable = Annotated[WritableProjects, Depends(writable_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Index = Annotated[FilePath, Depends(index_path)]
_Jobs = Annotated[JobSupervisor, Depends(job_supervisor)]
_Project = Annotated[
    str, Path(description="Project id (`project` of /projects).", examples=["raba"])
]
_Task = Annotated[
    str,
    Path(description="Task name (`task` of /projects/{project}).", examples=["teren"]),
]
_Producer = Annotated[
    str | None,
    Query(
        min_length=1,
        description=(
            "The producer whose manifest holds the task; left out: the project's"
            " only one (`producer_required` for a project of several)."
        ),
        examples=["kartograf"],
    ),
]


def _unsupported(*, commands: bool) -> dict[int | str, dict[str, Any]]:
    """Return the ``422`` of a producer that changes no projects or has no commands."""
    text = (
        "`unsupported`: the producer creates and changes no projects"
        " (`no_project_actions`)"
    )
    if commands:
        text += " or offers no commands (`no_commands`)"
    return {
        422: {
            "description": f"{text}.",
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                    "example": problem_example(
                        "unsupported",
                        message("project.no_actions", "en", producer="imgw"),
                        reason="no_project_actions",
                    ),
                }
            },
        }
    }


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
    key: str,
    *,
    visible: ProjectVisibility,
    writable: WritableProjects,
) -> ProjectCard:
    """Return a project's tasks, pins and problems from the index.

    ``writable`` says whether the principal may change the project.

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    """
    detail = project_detail(queries, key, visible=visible)
    if detail is None:
        raise NotFoundError(message("project.not_found", project=key))
    stores = {
        manifest.store
        for manifest in detail.project.manifests
        if manifest.store is not None
    }
    freshness = staleness(queries.freshness(), stores)
    return ProjectCard.of(detail, freshness, writable=writable)


def check_project(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    key: str,
    *,
    visible: ProjectVisibility,
) -> ProjectStatus:
    """Ask each manifest's producer for its status, or answer the scan's check.

    The manifests are checked in their order; the first refusal is the
    answer.

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    SourceStateError
        A manifest's producer plugin is not available.
    SourceUnavailableError
        Without a ``state``: a manifest's store is unavailable and no scan
        checked it (``503 store_unavailable``).
    PathOutsideRootError
        The project's directory or a manifest resolves outside the project
        directories (``403 path_outside_root``).
    ProducerError
        A producer cannot read its manifest.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    return ProjectStatus(
        project=key,
        manifests=[
            _manifest_status(
                queries, settings, registry, record, manifest, visible=visible
            )
            for manifest in record.project.manifests
        ],
    )


def _manifest_status(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    record: ProjectRecord,
    manifest: ProjectManifestRef,
    *,
    visible: ProjectVisibility,
) -> ManifestStatus:
    """Ask a manifest's producer for its status, or answer the scan's check."""
    key = record.project.key
    producer = manifest.producer
    registry.adapter(producer)
    if manifest.store is not None and _unavailable(
        queries, settings, registry, manifest.store, producer
    ):
        if manifest.status is None:
            text = message(
                "api.project_store_unavailable", project=key, store=manifest.store
            )
            raise SourceUnavailableError(text)
        return ManifestStatus(
            producer=producer,
            status=manifest.status,
            checked_at=manifest.scanned_at,
            stale=True,
            stale_reason="store_unavailable",
            tasks=[
                TaskStatus(task=task.task_id, status=task.status)
                for task in record.tasks
                if task.producer == producer
            ],
        )
    checked_at = datetime.now(UTC)
    info = project_status(
        queries,
        registry,
        key,
        producer=producer,
        visible=visible,
        project_dirs=settings.project_dirs,
    )
    if info is None:  # pragma: no cover - removed by a scan in between
        raise NotFoundError(message("project.not_found", project=key))
    return ManifestStatus(
        producer=producer,
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


@router.get("", response_model=ProjectList, responses=problem_responses(400))
def list_projects(
    visible: _Visible,
    writable: _Writable,
    settings: _Settings,
    queries: _Queries,
    store: Annotated[
        str | None, Query(description="Only projects of this store.")
    ] = None,
) -> ProjectList:
    """List projects the session's principal sees, with their counts.

    `project_write` says of each project whether the principal may change it.
    """
    return read_projects(
        queries, settings.get(), store, visible=visible, writable=writable
    )


@router.post(
    "",
    response_model=ProjectCard,
    status_code=201,
    responses={
        **problem_responses(400, 403, 404, 409, 503),
        **_unsupported(commands=False),
    },
)
def create_project(
    body: ProjectRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    writable: _Writable,
    registry: _Registry,
    settings: _Settings,
    queries: _Queries,
    index: _Index,
    response: Response,
) -> ProjectCard:
    """Create a project of a producer bound to a configured store.

    The producer writes its manifest in `path`, made when missing, naming the
    store's directory of the producer: relative to the project directory
    when the store has path aliases, else absolute, never the producer's
    default root. A directory that holds another producer's manifest stays
    one project with both. The index holds the project at once: the answer
    is `201` with its card and `Location: /api/v1/projects/{project}`. A new
    project has no owner yet, so only an administrator creates one (`403
    permission_denied`). Refused: a path that is not absolute or leaves the
    project directories of the settings (`403`, `path_outside_root`), a place
    a scan would not find (`400`, `project_not_discoverable`: more than four
    levels down, in a hidden directory or in a store), a project directory of
    the settings that is missing (`400`, `project_dir_missing`), a store that
    is not configured (`404`), has no directory of the producer (`400`,
    `store_without_producer`) or cannot be read now (`503
    store_unavailable`), a producer that creates no projects (`422`,
    `no_project_actions`), the producer's refusal (`400` with its text,
    e.g. a manifest of its own that is there already) and a lock of the
    manifest that stays (`409`, `project_locked`, `details.lock`). Nothing
    uses the network.
    """
    key = project_service.create_project(
        registry,
        settings.get(),
        index,
        decisions,
        producer=body.producer,
        path=body.path,
        store=body.store,
        actor=principal,
    )
    response.headers["Location"] = f"{API_PREFIX}/projects/{key}"
    return project_card(queries, key, visible=visible, writable=writable)


@router.get("/{project}", response_model=ProjectCard, responses=problem_responses(404))
def get_project(
    project: _Project, visible: _Visible, writable: _Writable, queries: _Queries
) -> ProjectCard:
    """Return a project: each manifest, tasks with commands and options, pins, problems.

    Tasks and pins carry the producer of their manifest; an invalid manifest
    hides nothing of the other. Pins carry their state in the index (`ok`,
    `missing`, `sha256_mismatch`, `unknown`); problems carry fix instructions,
    a task name in the manifests of several producers among them
    (`duplicate_task`). `project_write` says whether the principal may change
    the project.
    """
    return project_card(queries, project, visible=visible, writable=writable)


@router.get(
    "/{project}/status",
    response_model=ProjectStatus,
    responses=problem_responses(403, 404, 400, 503),
)
def get_project_status(
    project: _Project,
    visible: _Visible,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> ProjectStatus:
    """Return each producer's check of its manifest now: each task's worst file.

    No network and no hashing. While a manifest's store is unavailable its
    answer is the last scan's check, marked `stale`. A project directory or
    manifest that leaves the project directories (a symbolic link) is
    refused (`path_outside_root`).
    """
    return check_project(queries, settings.get(), registry, project, visible=visible)


@router.post(
    "/{project}/tasks",
    response_model=ProjectCard,
    status_code=201,
    responses={
        **problem_responses(400, 403, 404, 409, 503),
        **_unsupported(commands=True),
    },
)
def add_project_task(
    project: _Project,
    body: TaskRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    writable: _Writable,
    registry: _Registry,
    settings: _Settings,
    queries: _Queries,
    index: _Index,
) -> ProjectCard:
    """Add a task to a project's manifest through its producer: a command and options.

    The producer checks the call without the network and writes the task in
    its manifest; nothing is downloaded. The index holds the task at once:
    the answer is `201` with the project's card. Only the project's owner or
    an administrator changes a project: one the session does not see is
    `404`, one it sees but may not change `403 permission_denied`. Refused:
    a producer without a manifest in the project (`400`, `other_producer`),
    no producer for a project of several (`400`, `producer_required`), a
    command outside its catalog (`400`, `unknown_command`), an option that is
    a file path (`403`, `path_outside_root`, `details.option`), a producer
    that changes no projects or has no commands (`422`), the producer's
    refusal (`400` with its text and `details.option`: an invalid or taken
    name, an invalid option) and a lock of the manifest that stays (`409`,
    `project_locked`, `details.lock`: Archiwista never removes it).
    """
    key = project_service.add_project_task(
        registry,
        settings.get(),
        queries,
        index,
        decisions,
        project,
        name=body.name,
        command=body.command,
        options=body.options,
        producer=body.producer,
        actor=principal,
        visible=visible,
    )
    return project_card(queries, key, visible=visible, writable=writable)


@router.delete(
    "/{project}/tasks/{name}",
    response_model=ProjectCard,
    responses={
        **problem_responses(400, 403, 404, 409, 503),
        **_unsupported(commands=False),
    },
)
def remove_project_task(
    project: _Project,
    name: _Task,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    writable: _Writable,
    registry: _Registry,
    settings: _Settings,
    queries: _Queries,
    index: _Index,
    producer: _Producer = None,
) -> ProjectCard:
    """Remove a task and its pins from a project's manifest through its producer.

    The task is the one of the manifest of `producer`, else of the project's
    only manifest (`400`, `producer_required` for a project of several; a
    producer without a manifest in it is `400`, `other_producer`). The
    task's files stay in the store: other projects may pin them. The index
    holds the change at once: the answer is the project's card. A project
    the session does not see is `404`, one it may not change `403
    permission_denied`; a task the manifest does not hold is the producer's
    refusal (`400`, `details.option` `name`); a lock of the manifest that
    stays is `409` (`project_locked`, `details.lock`).
    """
    key = project_service.remove_project_task(
        registry,
        settings.get(),
        queries,
        index,
        decisions,
        project,
        name=name,
        producer=producer,
        actor=principal,
        visible=visible,
    )
    return project_card(queries, key, visible=visible, writable=writable)


@job_router.post(
    "/{project}/jobs",
    response_model=JobDetail,
    status_code=202,
    responses={
        **problem_responses(400, 403, 404, 409, 503),
        **_unsupported(commands=False),
    },
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
    """Start a job of the tasks of a project's manifest; answer `202` with the job.

    The tasks are those of the manifest of `producer`, else of the project's
    only manifest. `download` downloads and pins the tasks not downloaded
    yet and restores missing pinned versions into the configured store the
    manifest names; `repin` pins one task anew to the source's newer
    versions; `check` compares the pins with the source without effects;
    `verify` checks the pinned files in the store without the network.
    `tasks` names the tasks, every task when left out. The answer has
    `Location: /api/v1/jobs/{job}`; follow the job with `GET
    /jobs/{job}/events`. A project the session does not see is `404`; a
    download and a repin need the project's owner or an administrator and
    the role `store_writer` or the setting `store_write_for_all` (`403
    permission_denied`). Refused before a job exists: a repin without
    exactly one task (`400`), no producer for a project of several (`400`,
    `producer_required`) or a producer without a manifest in it (`400`,
    `other_producer`), a producer that runs no project jobs (`422`,
    `no_project_actions`), a project directory that left the project
    directories (`403`, `path_outside_root`), a download or a repin of a
    manifest that names no configured store (`409`, `unknown_store`), a
    second job of the project (`409 conflict`, that job in `details.job`),
    offline mode for every kind but `verify` (`409`, `offline_mode`) and a
    producer whose plugin is missing (`503`). A lock of the manifest that
    stays fails the job (`project_locked`, `details.lock`).
    """
    job = project_jobs.start(
        registry,
        settings.get(),
        jobs,
        queries,
        decisions,
        project,
        kind=body.kind,
        tasks=body.tasks,
        producer=body.producer,
        actor=principal,
        visible=visible,
    )
    response.headers["Location"] = f"{API_PREFIX}/jobs/{job.id}"
    return JobDetail.of(job)
