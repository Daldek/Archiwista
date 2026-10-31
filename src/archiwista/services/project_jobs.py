"""The jobs over a project's groups, for every interface (A-ADR-049 decision 11).

``start`` takes a request for a job of a project's groups (``POST
/projects/{project}/jobs``, ``archiwista project-verify``, ``project-check``,
``project-repin`` and ``project-restore``) and refuses before a job exists
what its worker would refuse: a project the principal does not see (``404``,
as an unknown one), a re-pin or a restore asked by a principal who may not
change the project (``project.write``) or write the stores (``store.write``;
``403 permission_denied``), a group the project does not have (``404``), a
group whose producer offers no commands (``422 unsupported``,
``no_commands``) for the jobs that run calls, a re-pin of a local group with
a pin whose call the index knows cannot be rebuilt (``422 unsupported``,
``command_not_rebuildable``, A-ADR-049 D5) and a group whose producer's store
the project names matches no configured store (``409 conflict``,
``unknown_store``). The supervisor then refuses a second job of the project
(``409 conflict``) and, offline, a job that needs the network (``409``,
``offline_mode``). A verification and a check need only that the principal
sees the project. ``require`` asks the same of a retry
(``archiwista.services.jobs.retry``). Nothing here uses the network: the
producer runs in the job's worker.

``chosen_groups``, ``group_producers`` and ``group_store`` are shared with the
jobs' runners (``archiwista.jobs.project_jobs``), which import this module
without the supervisor.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, get_args

from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import ConflictError, NotFoundError
from archiwista.index import IndexQueries, PinGroupRef, ProjectRecord, ProjectRef
from archiwista.messages import message
from archiwista.services.commands import actions, not_rebuildable, version_commands
from archiwista.sources.registry import PluginRegistry

if TYPE_CHECKING:
    from archiwista.jobs import JobKind, JobRecord, JobSupervisor

# What a job of a project does with its groups: ``verify`` hashes the pinned
# files in the store, ``check`` compares the pins with the source, ``repin``
# pins one group anew to the source's newer versions and ``restore``
# downloads the missing pinned versions again (A-ADR-049 decision 11).
type ProjectJobKind = Literal["verify", "check", "repin", "restore"]
PROJECT_JOB_KINDS: tuple[ProjectJobKind, ...] = get_args(ProjectJobKind.__value__)
# The job kind of each.
JOB_KIND: Mapping[ProjectJobKind, "JobKind"] = {
    "verify": "project_verify",
    "check": "project_check",
    "repin": "project_repin",
    "restore": "project_restore",
}
# The kinds that write the store and need ``project.write``.
_WRITING: frozenset[str] = frozenset({"project_repin", "project_restore"})
# The kinds that run the producer's calls.
_CALLING: frozenset[str] = frozenset(
    {"project_check", "project_repin", "project_restore"}
)


def start(
    registry: PluginRegistry,
    settings: AppSettings,
    jobs: "JobSupervisor",
    queries: IndexQueries,
    authorizer: Authorizer,
    key: str,
    *,
    kind: ProjectJobKind,
    groups: Sequence[str] | None,
    actor: Principal,
    visible: ProjectVisibility,
) -> "JobRecord":
    """Check a request for a job of a project's groups, then start the job.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins: the producers of the groups run the calls.
    settings : AppSettings
        The configured stores.
    jobs : JobSupervisor
        Started supervisor of the job.
    queries : IndexQueries
        The local index: the project, its groups and pins.
    authorizer : Authorizer
        Decides whether ``actor`` may change the project (``project.write``)
        and write the stores (``store.write``).
    key : str
        Project key.
    kind : {"verify", "check", "repin", "restore"}
        What the job does (``PROJECT_JOB_KINDS``).
    groups : Sequence[str] or None
        The groups by name (compared case-folded), ``None`` for every group;
        a re-pin names exactly one.
    actor : Principal
        Who asks: the job's actor.
    visible : ProjectVisibility
        The projects ``actor`` sees.

    Returns
    -------
    JobRecord
        The job, ``queued`` or already ``running``, with no store; its
        parameters are ``project`` and ``groups`` (the names as the file
        writes them, ``None`` for every group).

    Raises
    ------
    NotFoundError
        No project ``key`` that ``actor`` sees; a group it does not have.
    PermissionDeniedError
        A re-pin or a restore while ``actor`` may not change the project or
        may not write the stores.
    SourceUnavailableError, SourceIncompatibleError
        A group's producer's plugin is not available.
    UnsupportedError
        A check, a re-pin or a restore of a group whose producer offers no
        commands (reason ``no_commands``); a re-pin of a local group with a
        pin known ``not_rebuildable`` (``command_not_rebuildable``).
    ConflictError
        A check, a re-pin or a restore of a group whose producer's store
        the project names matches no configured store (``unknown_store``).
    JobConflictError
        The project has a job that waits or runs (``details.job``).
    OfflineModeError
        Offline mode is on and the job needs the network; nothing is
        recorded.
    ValueError
        ``groups`` is empty, or a re-pin does not name exactly one group.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    project = record.project
    job_kind = JOB_KIND[kind]
    require(authorizer, actor, job_kind, project)
    if groups is not None and not groups:
        raise ValueError("a project job names its groups or none")
    if kind == "repin" and (
        groups is None or len({name.casefold() for name in groups}) != 1
    ):
        raise ValueError(f"a re-pin takes one group, got {groups!r}")
    chosen = chosen_groups(record, groups)
    if job_kind in _CALLING:
        for group in chosen:
            for producer in group_producers(group):
                actions(registry, producer)
                if group.origin == "local":
                    version_commands(registry, producer)
                group_store(project, producer)
    if kind == "repin":
        for pin in chosen[0].pins:
            if chosen[0].origin == "local" and pin.command == "not_rebuildable":
                raise not_rebuildable(
                    pin.producer, pin.version, pin.command_refusal or ""
                )
    names = None if groups is None else [group.name for group in chosen]
    return jobs.submit(
        job_kind, params={"project": project.key, "groups": names}, actor=actor
    )


def require(
    authorizer: Authorizer, actor: Principal, kind: str, project: ProjectRef
) -> None:
    """Refuse a job of a project its kind does not allow ``actor``.

    A re-pin and a restore write the store (and a re-pin the project file):
    they need ``project.write`` of the project, then ``store.write``. A
    verification and a check need only that ``actor`` sees the project, which
    the caller has made sure of.

    Raises
    ------
    PermissionDeniedError
        The first of the two permissions ``actor`` lacks.
    """
    if kind in _WRITING:
        authorizer.require(actor, "project.write", project.access_key)
        authorizer.require(actor, "store.write", target=project.access_key)


def chosen_groups(
    record: ProjectRecord, names: Sequence[str] | None
) -> tuple[PinGroupRef, ...]:
    """Return the groups ``names`` choose, in the file's order; every one for ``None``.

    Raises
    ------
    NotFoundError
        The project has no group of a name (``project.group_not_found``).
    """
    if names is None:
        return record.groups
    by_name = {group.name.casefold(): group for group in record.groups}
    chosen: dict[str, PinGroupRef] = {}
    for name in names:
        group = by_name.get(name.casefold())
        if group is None:
            raise NotFoundError(
                message(
                    "project.group_not_found", project=record.project.key, group=name
                )
            )
        chosen[group.name] = group
    return tuple(group for group in record.groups if group.name in chosen)


def group_producers(group: PinGroupRef) -> tuple[str, ...]:
    """Return the producers of a group: a plan group's, a local group's pins'."""
    if group.origin == "plan" and group.producer is not None:
        return (group.producer,)
    return tuple(dict.fromkeys(pin.producer for pin in group.pins))


def group_store(project: ProjectRef, producer: str) -> str:
    """Return the configured store the project names for ``producer``.

    Raises
    ------
    ConflictError
        The project names no store of ``producer``, or one that matches no
        configured store (``unknown_store``).
    """
    entry = project.store(producer)
    if entry is None or entry.store is None:
        raise ConflictError(
            message("project.unknown_store", producer=producer),
            reason="unknown_store",
            details={"producer": producer},
        )
    return entry.store
