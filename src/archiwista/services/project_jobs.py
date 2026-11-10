"""The jobs over a project's groups, for every interface (A-ADR-049 decision 11).

``start`` takes a request for a job of a project's groups (``POST
/projects/{project}/jobs``, ``archiwista project-verify``, ``project-check``,
``project-repin`` and ``project-restore``) and refuses before a job exists
what its worker would refuse: a project the principal does not see (``404``,
as an unknown one), a re-pin or a restore asked by a principal who may not
change the project (``project.write``) or write the stores (``store.write``;
``403 permission_denied``), a group the project does not have (``404``), a re-pin
of a closed set (``409 conflict``, ``set_closed``: a set is opened for
editing first, A-ADR-049 erratum 6), a group whose producer offers no
commands (``422 unsupported``, ``no_commands``) for the jobs that run calls,
a re-pin of a local group, or of a pin added by hand to a plan group, whose
call the index knows cannot be rebuilt (``422 unsupported``,
``command_not_rebuildable``, A-ADR-049 D5), a group whose producer's store
the project names matches no configured store (``409 conflict``,
``unknown_store``) and, for a re-pin or a restore that confirms the plan of
a check (``plan_job``, the card's plan window: ADR-042 erratum 2), a job the
principal does not see (``404``, as an unknown one), a check without its
plan (``404``, ``job.no_plan``) or one that did not check the chosen groups
of the project as they are now (``409 conflict``, ``plan_mismatch``). The
supervisor then refuses a second job of the project (``409 conflict``) and,
offline, a job that needs the network (``409``, ``offline_mode``). A
verification and a check need only that the principal sees the project.
``require`` and ``require_open_sets`` ask the same of a retry
(``archiwista.services.jobs.retry``), which keeps the ``plan_job`` of the job
it runs again. Nothing here uses the network: the producer runs in the job's
worker, which plans again.

``chosen_groups``, ``group_producers``, ``group_store``, ``by_hand`` and
``set_closed`` are shared with the jobs' runners
(``archiwista.jobs.project_jobs``) and the pins' services, which import this
module without the supervisor.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, get_args

from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import ConflictError, NotFoundError
from archiwista.index import (
    IndexQueries,
    PinGroupRef,
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
)
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
    plan_job: str | None = None,
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
        The projects ``actor`` sees: a ``plan_job`` must be a job they see.
    plan_job : str or None, optional
        A re-pin or a restore only: the ``project_check`` job whose plan the
        person confirmed. It must have ended with its plan (``succeeded`` or
        ``partial``) of this project and of every chosen group, each group's
        pins (producer, version and SHA-256) still those it checked.

    Returns
    -------
    JobRecord
        The job, ``queued`` or already ``running``, with no store; its
        parameters are ``project`` and ``groups`` (the names as the file
        writes them, ``None`` for every group), and for a re-pin and a
        restore ``plan_job`` (``None`` when not given).

    Raises
    ------
    NotFoundError
        No project ``key`` that ``actor`` sees; a group it does not have;
        ``plan_job`` is no job ``actor`` sees (``job.not_found``) or a check
        of the groups that has no plan, waiting, running or failed
        (``job.no_plan``).
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
        the project names matches no configured store (``unknown_store``); a
        re-pin of a closed set (``set_closed``); ``plan_job`` is no check of
        the chosen groups of the project, or one of them changed since
        (``plan_mismatch``, ``details.job``).
    JobConflictError
        The project has a job that waits or runs (``details.job``).
    OfflineModeError
        Offline mode is on and the job needs the network; nothing is
        recorded.
    ValueError
        ``groups`` is empty, a re-pin does not name exactly one group, or a
        verification or a check names ``plan_job``.
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
    if plan_job is not None and job_kind not in _WRITING:
        raise ValueError(f"a {kind} job confirms no plan")
    chosen = chosen_groups(record, groups)
    if kind == "repin":
        require_open_sets(record, [group.name for group in chosen])
    if job_kind in _CALLING:
        for group in chosen:
            for producer in group_producers(group):
                actions(registry, producer)
                if group.origin == "local" or any(
                    by_hand(pin) for pin in group.pins if pin.producer == producer
                ):
                    version_commands(registry, producer)
                group_store(project, producer)
    if kind == "repin":
        for pin in chosen[0].pins:
            own_call = chosen[0].origin == "local" or by_hand(pin)
            if own_call and pin.command == "not_rebuildable":
                raise not_rebuildable(
                    pin.producer, pin.version, pin.command_refusal or ""
                )
    if plan_job is not None:
        _require_plan(jobs, plan_job, project, chosen, visible=visible)
    names = None if groups is None else [group.name for group in chosen]
    params: dict[str, object] = {"project": project.key, "groups": names}
    if job_kind in _WRITING:
        params["plan_job"] = plan_job
    return jobs.submit(job_kind, params=params, actor=actor)


def _require_plan(
    jobs: "JobSupervisor",
    plan_job: str,
    project: ProjectRef,
    chosen: Sequence[PinGroupRef],
    *,
    visible: ProjectVisibility,
) -> None:
    """Refuse a check whose plan is not that of ``chosen`` as they are now.

    The plan of a re-pin or a restore is the ``project_check`` job the person
    confirmed (ADR-042 erratum 2): a check of ``project`` that named every
    group of ``chosen`` (or every group), ended with its plan, and whose rows
    of each group are the group's pins now, compared by producer, version and
    pinned SHA-256 (names compared case-folded): a pin added, removed or
    pinned anew since makes the plan another set's. The worker plans again;
    this only makes sure the person saw the plan of the sets the job changes.

    Raises
    ------
    NotFoundError
        No job ``plan_job`` that the principal sees (``job.not_found``); a
        check of the groups that waits, runs or did not end with its plan
        (``job.no_plan``).
    ConflictError
        The job is no check of the groups of the project, or a group
        changed since it was checked (``plan_mismatch``, ``details.job``).
    """
    planned = jobs.get(plan_job, visible=visible)
    if planned is None:
        raise NotFoundError(message("job.not_found", job=plan_job))
    asked = planned.params.get("groups")
    if (
        planned.kind != "project_check"
        or planned.params.get("project") != project.key
        or (isinstance(asked, list) and not _named(chosen, asked))
    ):
        raise _plan_mismatch(message("job.project_plan_other", job=plan_job), plan_job)
    result = planned.result
    if result is None:
        raise NotFoundError(message("job.no_plan", job=plan_job))
    checked = result.get("groups")
    rows = result.get("pins")
    if not isinstance(checked, list) or not _named(chosen, checked):
        raise _plan_mismatch(message("job.project_plan_other", job=plan_job), plan_job)
    for group in chosen:
        name = group.name.casefold()
        seen = {
            (row.get("producer"), row.get("version"), row.get("sha256"))
            for row in (rows if isinstance(rows, list) else ())
            if isinstance(row, dict) and str(row.get("group", "")).casefold() == name
        }
        if seen != {(pin.producer, pin.version, pin.sha256) for pin in group.pins}:
            text = message("job.project_plan_changed", job=plan_job, group=group.name)
            raise _plan_mismatch(text, plan_job)


def _named(chosen: Sequence[PinGroupRef], names: Sequence[object]) -> bool:
    """Whether ``names`` hold every group of ``chosen``, compared case-folded."""
    folded = {str(name).casefold() for name in names}
    return all(group.name.casefold() in folded for group in chosen)


def _plan_mismatch(text: str, plan_job: str) -> ConflictError:
    """Return the refusal of a plan of other sets (``plan_mismatch``)."""
    return ConflictError(text, reason="plan_mismatch", details={"job": plan_job})


def by_hand(pin: ProjectPinRef) -> bool:
    """Whether a pin of a ``plan`` group was added by hand (``calls`` ``[]``).

    Such a pin is checked, restored and re-pinned by its own call, as a
    ``local`` group's pin is (A-ADR-049 erratum 6).
    """
    return pin.calls == ()


def set_closed(name: str) -> ConflictError:
    """Return the refusal of a change of a closed set (``set_closed``)."""
    return ConflictError(
        message("project.set_closed", group=name),
        reason="set_closed",
        details={"group": name},
        hint=message("fix.set_closed"),
    )


def require_open_sets(record: ProjectRecord, names: Sequence[str] | None) -> None:
    """Refuse a re-pin of a closed set (``set_closed``) before its job exists.

    ``names`` are the groups of the job (``None``: every group).
    """
    for group in chosen_groups(record, names):
        if group.state != "open":
            raise set_closed(group.name)


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
                ),
                reason="group_not_found",
                details={"group": name},
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
