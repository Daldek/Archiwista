"""Producers' commands run as jobs, for every interface (plan of 2026-10-25, A4, A5).

``start`` takes a request for a job of a producer's calls on a configured
store (``POST /jobs``, ``archiwista jobs start``): one job for all the calls of
a report's row or of a pasted list (ADR-044). It refuses before a job exists
what its worker would refuse: a download asked by a principal who may not
write the stores (``403``, ``permission_denied``), a store that is not
configured (``404``), a command outside the producer's catalog (``400``,
``unknown_command``), one that works on no store or has no plan without
effects (``422 unsupported``, ``no_store``, ``no_check``: every run goes
through its plan), an option that is a file path (``403``,
``path_outside_root``), the producer's own refusal of the options (``400``,
its text) and the plans of other calls (``409``, ``plan_mismatch``); a
refusal of one call names its place (``details.call``). Offline mode refuses
a job that needs the network (``409``, ``offline_mode``), and nothing is
recorded. The job keeps the options as the producer read them.
``kept_plans`` returns the plans a ``check`` job kept (``GET /jobs/{job}/plan``,
``archiwista jobs plan``). Nothing here uses the network: the producer's
check and run happen in the job's worker.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import (
    ArchiwistaError,
    ConflictError,
    NotFoundError,
    UnsupportedError,
)
from archiwista.index import IndexQueries, StoredPlan
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.services.commands import actions, checked_call, command_info
from archiwista.services.jobs import visible_job
from archiwista.services.pins import check_plan_pin
from archiwista.sources import ActionAdapter, CommandCall, CommandInfo
from archiwista.sources.registry import PluginRegistry

# The kinds of a job of a producer's calls: ``check`` plans a run of each call
# in the store without its effects (ADR-036), ``download`` runs them there,
# the plans of a ``check`` job if one is named (ADR-037, ADR-044).
type ActionKind = Literal["check", "download"]
ACTION_KINDS: tuple[ActionKind, ...] = get_args(ActionKind.__value__)


@dataclass(frozen=True, slots=True)
class KeptPlans:
    """The plans a ``check`` job kept (``kept_plans``).

    ``job`` is the job as the principal sees it, with the calls it planned
    (``params["calls"]``); ``plans`` the plan of each call planned, in the
    order of the calls: a call whose check failed has none.
    """

    job: JobRecord
    plans: tuple[StoredPlan, ...]


def start(
    registry: PluginRegistry,
    settings: AppSettings,
    jobs: JobSupervisor,
    queries: IndexQueries,
    authorizer: Authorizer,
    *,
    kind: ActionKind,
    store: str,
    calls: Sequence[CommandCall],
    actor: Principal,
    visible: ProjectVisibility,
    plan_job: str | None = None,
    pin: tuple[str, str] | None = None,
) -> JobRecord:
    """Check a request for a job of a producer's calls, then start the job.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins: the producer's catalog and its check of the options.
    settings : AppSettings
        The configured stores.
    jobs : JobSupervisor
        Started supervisor of the job.
    queries : IndexQueries
        The local index: the plans a ``check`` job kept (``plan_job``).
    authorizer : Authorizer
        Decides whether ``actor`` may write the stores (``store.write``).
    kind : {"check", "download"}
        What the job does with the calls (``ACTION_KINDS``): ``check`` plans
        a run of each, ``download`` runs them and writes the store.
    store : str
        Id of the configured store whose producer directory the calls work
        on, never the producer's default root.
    calls : Sequence[CommandCall]
        The calls, in their order: each a command of the catalog of one and
        the same producer with its options (``run`` is not read); 1 to
        ``MAX_JOB_CALLS`` of them.
    actor : Principal
        Who asks: the job's actor.
    visible : ProjectVisibility
        The projects ``actor`` sees: a ``plan_job`` must be a job they see.
    plan_job : str or None, optional
        ``download`` only: the ``check`` job whose kept plans the run runs, a
        job of the same store, producer and calls.
    pin : (str, str) or None, optional
        ``download`` only: the project and the new group the run's files and
        its plans' other positions are pinned into when the job succeeds
        (A-ADR-049 decision 9); the request then also needs
        ``project.write`` of the project.

    Returns
    -------
    JobRecord
        The job, ``queued`` or already ``running``; its parameters hold the
        producer, the calls with the options as the producer read them, and
        a download's ``plan_job`` and ``pin``.

    Raises
    ------
    PermissionDeniedError
        A ``download`` while ``actor`` may not write the stores: neither the
        role ``store_writer`` nor the setting ``store_write_for_all``.
    NotFoundError
        ``store`` is not configured; ``plan_job`` is no job ``actor`` sees
        (``job.not_found``) or kept no plan (``job.no_plan``); ``pin`` names
        no project ``actor`` sees.
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    UnsupportedError
        The producer offers no commands (reason ``no_commands``), or a
        call's command works on no store (``no_store``) or has no plan
        without effects (``no_check``).
    CommandRequestError
        A command is not in the producer's catalog (``unknown_command``), or
        the store has no directory of the producer
        (``store_without_producer``).
    PathOutsideRootError
        An option that is a file path is given (``details.option``).
    ProducerError
        The producer refused a call's options (its code, text and
        ``details.option``).
    ConflictError
        ``plan_job`` planned another store, producer or calls (reason
        ``plan_mismatch``, ``details.job``); the project of ``pin`` holds the
        group (``group_exists``) or names another store of the producer
        (``other_store``) or one matching none (``unknown_store``).
    InvalidChangeError
        The group's name breaks the rule (``invalid_group_name``).
    OfflineModeError
        Offline mode is on; nothing is recorded.
    ValueError
        No call, calls of several producers, or ``plan_job`` or ``pin`` with
        a ``check``.

    A refusal of one call (``UnsupportedError``, ``CommandRequestError``,
    ``PathOutsideRootError``, ``ProducerError``) names its place in
    ``calls`` as ``details.call``.
    """
    if not calls or len({call.producer for call in calls}) != 1:
        raise ValueError(f"a job takes calls of one producer, got {len(calls)} calls")
    if kind == "download":
        authorizer.require(actor, "store.write", target=store)
    elif plan_job is not None or pin is not None:
        raise ValueError(f"a {kind} job runs no plan and pins nothing")
    if settings.store(store) is None:
        raise NotFoundError(message("api.store_not_configured", store=store))
    producer = calls[0].producer
    pinned = None
    if pin is not None:
        pinned = check_plan_pin(
            settings,
            queries,
            authorizer,
            project=pin[0],
            group=pin[1],
            producer=producer,
            store=store,
            actor=actor,
            visible=visible,
        )
    adapter = actions(registry, producer)
    infos: dict[str, CommandInfo] = {}
    checked: list[dict[str, object]] = []
    for place, call in enumerate(calls):
        try:
            valid = _checked(adapter, settings, infos, call, store=store)
        except ArchiwistaError as error:
            error.details["call"] = place
            raise
        checked.append({"command": valid.command, "options": dict(valid.options)})
    params: dict[str, object] = {"producer": producer, "calls": checked}
    if kind == "download":
        if plan_job is not None:
            planned = visible_job(jobs, plan_job, visible)
            _stored_plans(queries, plan_job)
            if _calls_key(planned.store, planned.params) != _calls_key(store, params):
                raise ConflictError(
                    message("job.mismatched_plan", job=plan_job),
                    reason="plan_mismatch",
                    details={"job": plan_job},
                )
        params["plan_job"] = plan_job
        if pinned is not None:
            params["pin"] = pinned
    return jobs.submit(kind, store=store, params=params, actor=actor)


def kept_plans(
    queries: IndexQueries,
    jobs: JobSupervisor,
    job_id: str,
    *,
    visible: ProjectVisibility,
) -> KeptPlans:
    """Return the plans a ``check`` job kept, without the network.

    Raises
    ------
    NotFoundError
        No job ``job_id`` the principal sees (``job.not_found``), or the job
        kept no plan (``job.no_plan``): it is not a ``check``, has not ended
        yet, or failed.
    """
    job = visible_job(jobs, job_id, visible)
    if job.kind != "check":
        raise NotFoundError(message("job.no_plan", job=job_id))
    return KeptPlans(job, _stored_plans(queries, job_id))


def _checked(
    adapter: ActionAdapter,
    settings: AppSettings,
    infos: dict[str, CommandInfo],
    call: CommandCall,
    *,
    store: str,
) -> CommandCall:
    """Return a call as the producer read it, of a command a job may run.

    ``infos`` keeps the catalog's entry of each command looked up, so the
    catalog is read once per command of a request.
    """
    info = infos.get(call.command)
    if info is None:
        info = infos[call.command] = command_info(adapter, call)
    if not info.store:
        raise UnsupportedError(
            message("command.no_store", producer=call.producer, command=call.command),
            reason="no_store",
        )
    if not info.check:
        raise UnsupportedError(
            message("command.no_check", producer=call.producer, command=call.command),
            reason="no_check",
        )
    return checked_call(adapter, settings, info, call, store=store)


def _stored_plans(queries: IndexQueries, job_id: str) -> tuple[StoredPlan, ...]:
    """Return the plans a job kept, else refuse with ``job.no_plan``."""
    stored = queries.plans(job_id)
    if not stored:
        raise NotFoundError(message("job.no_plan", job=job_id))
    return stored


def _calls_key(store: str | None, params: Mapping[str, object]) -> tuple[object, ...]:
    """Return a job's store, producer and calls, the options as jobs compare them."""
    calls = params.get("calls")
    return (
        store,
        params.get("producer"),
        tuple(
            (
                call["command"],
                json.dumps(call["options"], sort_keys=True, ensure_ascii=False),
            )
            for call in (calls if isinstance(calls, list) else ())
        ),
    )
