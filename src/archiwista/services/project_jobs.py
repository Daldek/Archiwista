"""The jobs of a project for every interface (plan of 2026-10-25, A8; ADR-040).

``start`` takes a request for a job of a project's tasks (``POST
/projects/{project}/jobs``, ``archiwista project-download``,
``project-repin``, ``project-check`` and ``project-verify``) and refuses
before a job exists what its worker would refuse: a project the principal
does not see (``404``, as an unknown one), a project of several producers'
manifests without the producer whose tasks the job runs, or a producer
without a manifest in it (``400``, ``producer_required``,
``other_producer``), a download or a repin asked by a principal who may not
change the project (``project.write``) or write the stores
(``store.write``; ``403 permission_denied``), a producer that runs no
project jobs (``422 unsupported``, ``no_project_actions``), a project
directory that left the project directories (``403``,
``path_outside_root``) and, for a download or a repin, a manifest naming no
configured store (``409 conflict``, ``unknown_store``). The supervisor then
refuses a second job of the project (``409 conflict``) and, offline, a job
that needs the network (``409``, ``offline_mode``). A check and a
verification need only that the principal sees the project. ``require``
asks the same of a retry (``archiwista.services.jobs.retry``). Nothing here
uses the network: the producer runs in the job's worker.
"""

from collections.abc import Mapping, Sequence
from typing import Literal, get_args

from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries, ProjectRef
from archiwista.jobs import JobKind, JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.services.projects import (
    project_actions,
    project_directory,
    project_manifest,
    project_store,
)
from archiwista.sources.registry import PluginRegistry

# What a job of a project does with its tasks: ``download`` downloads and
# pins what is not pinned yet and restores missing pinned versions,
# ``repin`` pins one task anew to the source's newer versions, ``check``
# compares the pins with the source and ``verify`` checks the pinned files in
# the store (ADR-040).
type ProjectJobKind = Literal["download", "repin", "check", "verify"]
PROJECT_JOB_KINDS: tuple[ProjectJobKind, ...] = get_args(ProjectJobKind.__value__)
# The job kind of each.
JOB_KIND: Mapping[ProjectJobKind, JobKind] = {
    "download": "project_download",
    "repin": "project_repin",
    "check": "project_check",
    "verify": "project_verify",
}
# The kinds whose producer writes the store and the manifest.
_WRITING: frozenset[JobKind] = frozenset({"project_download", "project_repin"})


def start(
    registry: PluginRegistry,
    settings: AppSettings,
    jobs: JobSupervisor,
    queries: IndexQueries,
    authorizer: Authorizer,
    key: str,
    *,
    kind: ProjectJobKind,
    tasks: Sequence[str] | None,
    producer: str | None = None,
    actor: Principal,
    visible: ProjectVisibility,
) -> JobRecord:
    """Check a request for a job of a project's tasks, then start the job.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins: the manifest's producer runs its jobs.
    settings : AppSettings
        The configured stores and project directories.
    jobs : JobSupervisor
        Started supervisor of the job.
    queries : IndexQueries
        The local index: the project.
    authorizer : Authorizer
        Decides whether ``actor`` may change the project (``project.write``)
        and write the stores (``store.write``).
    key : str
        Project key.
    kind : {"download", "repin", "check", "verify"}
        What the job does (``PROJECT_JOB_KINDS``).
    tasks : Sequence[str] or None
        The tasks by name, ``None`` for every task; a repin names one.
    producer : str or None, optional
        The producer whose manifest's tasks the job runs; ``None``: the
        producer of the project's only manifest.
    actor : Principal
        Who asks: the job's actor.
    visible : ProjectVisibility
        The projects ``actor`` sees.

    Returns
    -------
    JobRecord
        The job, ``queued`` or already ``running``, with no store; its
        parameters are ``project`` and ``tasks``, with ``producer`` when the
        request named it.

    Raises
    ------
    NotFoundError
        No project ``key`` that ``actor`` sees.
    CommandRequestError
        The project holds no manifest of ``producer`` (``other_producer``)
        or holds several and ``producer`` is left out (``producer_required``).
    PermissionDeniedError
        A download or a repin while ``actor`` may not change the project
        (neither its owner nor an administrator) or may not write the
        stores (neither the role ``store_writer`` nor the setting
        ``store_write_for_all``).
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    UnsupportedError
        The producer runs no project jobs (reason ``no_project_actions``).
    PathOutsideRootError
        The project's directory now leaves the project directories.
    ConflictError
        A download or a repin of a manifest that names no configured store
        (reason ``unknown_store``).
    JobConflictError
        The project has a job that waits or runs (``details.job``).
    OfflineModeError
        Offline mode is on and the job needs the network; nothing is
        recorded.
    ValueError
        ``tasks`` is empty or names an empty task, or a repin does not name
        exactly one task.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    project = record.project
    job_kind = JOB_KIND[kind]
    require(authorizer, actor, job_kind, project)
    manifest = project_manifest(project, producer)
    project_actions(registry, manifest.producer)
    project_directory(project, settings, manifest.producer)
    if job_kind in _WRITING and manifest.problem is None:
        project_store(manifest, settings)
    params: dict[str, object] = {
        "project": project.key,
        "tasks": None if tasks is None else list(tasks),
    }
    if producer is not None:
        params["producer"] = producer
    return jobs.submit(job_kind, params=params, actor=actor)


def require(
    authorizer: Authorizer, actor: Principal, kind: JobKind, project: ProjectRef
) -> None:
    """Refuse a job of a project its kind does not allow ``actor``.

    A download and a repin write the store and the manifest: they need
    ``project.write`` of the project, then ``store.write``. A check and a
    verification need only that ``actor`` sees the project, which the
    caller has made sure of.

    Raises
    ------
    PermissionDeniedError
        The first of the two permissions ``actor`` lacks.
    """
    if kind in _WRITING:
        authorizer.require(actor, "project.write", project.access_key)
        authorizer.require(actor, "store.write", target=project.access_key)
