"""Producers' commands run as jobs, for every interface (plan of 2026-10-25, A4, A5).

``start`` takes a request for a job of a producer's command on a configured
store (``POST /jobs``, ``archiwista jobs start``) and refuses before a job
exists what its worker would refuse: a download asked by a principal who may
not write the stores (``403``, ``permission_denied``), a store that is not
configured (``404``), a command outside the producer's catalog (``400``,
``unknown_command``), one that works on no store or has no plan without
effects (``422 unsupported``, ``no_store``, ``no_check``: every run goes
through its plan), an option that is a file path (``403``,
``path_outside_root``), the producer's own refusal of the options (``400``,
its text) and the plan of another call (``409``, ``plan_mismatch``); offline
mode refuses a job that needs the network (``409``, ``offline_mode``), and
nothing is recorded. The job keeps the options as the producer read them.
``kept_plan`` returns the plan a ``check`` job kept (``GET /jobs/{job}/plan``,
``archiwista jobs plan``). Nothing here uses the network: the producer's check
and run happen in the job's worker.
"""

import json
from collections.abc import Mapping
from typing import Literal, get_args

from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import ConflictError, NotFoundError, UnsupportedError
from archiwista.index import IndexQueries, StoredPlan
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.services.commands import actions, checked_call, command_info
from archiwista.sources import CommandCall
from archiwista.sources.registry import PluginRegistry

# The kinds of a job of a producer's command: ``check`` plans a run of the
# command in the store without its effects (ADR-036), ``download`` runs it
# there, the plan of a ``check`` job if one is named (ADR-037).
type ActionKind = Literal["check", "download"]
ACTION_KINDS: tuple[ActionKind, ...] = get_args(ActionKind.__value__)


def start(
    registry: PluginRegistry,
    settings: AppSettings,
    jobs: JobSupervisor,
    queries: IndexQueries,
    authorizer: Authorizer,
    *,
    kind: ActionKind,
    store: str,
    call: CommandCall,
    actor: Principal,
    visible: ProjectVisibility,
    plan_job: str | None = None,
) -> JobRecord:
    """Check a request for a job of a producer's command, then start the job.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins: the producer's catalog and its check of the options.
    settings : AppSettings
        The configured stores.
    jobs : JobSupervisor
        Started supervisor of the job.
    queries : IndexQueries
        The local index: the plan a ``check`` job kept (``plan_job``).
    authorizer : Authorizer
        Decides whether ``actor`` may write the stores (``store.write``).
    kind : {"check", "download"}
        What the job does with the command (``ACTION_KINDS``): ``check``
        plans a run, ``download`` runs it and writes the store.
    store : str
        Id of the configured store whose producer directory the command works
        on, never the producer's default root.
    call : CommandCall
        The producer, the command of its catalog and the options; ``run`` is
        not read.
    actor : Principal
        Who asks: the job's actor.
    visible : ProjectVisibility
        The projects ``actor`` sees: a ``plan_job`` must be a job they see.
    plan_job : str or None, optional
        ``download`` only: the ``check`` job whose kept plan the run runs, a
        plan of the same store, producer, command and options.

    Returns
    -------
    JobRecord
        The job, ``queued`` or already ``running``; its parameters hold the
        producer, the command and the options as the producer read them, and
        a download's ``plan_job``.

    Raises
    ------
    PermissionDeniedError
        A ``download`` while ``actor`` may not write the stores: neither the
        role ``store_writer`` nor the setting ``store_write_for_all``.
    NotFoundError
        ``store`` is not configured; ``plan_job`` is no job ``actor`` sees
        (``job.not_found``) or kept no plan (``job.no_plan``).
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    UnsupportedError
        The producer offers no commands (reason ``no_commands``), or the
        command works on no store (``no_store``) or has no plan without
        effects (``no_check``).
    CommandRequestError
        The command is not in the producer's catalog (``unknown_command``),
        or the store has no directory of the producer
        (``store_without_producer``).
    PathOutsideRootError
        An option that is a file path is given (``details.option``).
    ProducerError
        The producer refused the options (its code, text and
        ``details.option``).
    ConflictError
        ``plan_job`` planned another store or call (reason
        ``plan_mismatch``, ``details.job``).
    OfflineModeError
        Offline mode is on; nothing is recorded.
    ValueError
        ``plan_job`` with a ``check``.
    """
    if kind == "download":
        authorizer.require(actor, "store.write")
    elif plan_job is not None:
        raise ValueError(f"a {kind} job runs no plan, got plan job {plan_job!r}")
    if settings.store(store) is None:
        raise NotFoundError(message("api.store_not_configured", store=store))
    adapter = actions(registry, call.producer)
    info = command_info(adapter, call)
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
    checked = checked_call(adapter, settings, info, call, store=store)
    params: dict[str, object] = {
        "producer": checked.producer,
        "command": checked.command,
        "options": dict(checked.options),
    }
    if kind == "download":
        if plan_job is not None:
            planned = _visible_job(jobs, plan_job, visible)
            _stored_plan(queries, plan_job)
            if _call_key(planned.store, planned.params) != _call_key(store, params):
                raise ConflictError(
                    message("job.mismatched_plan", job=plan_job),
                    reason="plan_mismatch",
                    details={"job": plan_job},
                )
        params["plan_job"] = plan_job
    return jobs.submit(kind, store=store, params=params, actor=actor)


def kept_plan(
    queries: IndexQueries,
    jobs: JobSupervisor,
    job_id: str,
    *,
    visible: ProjectVisibility,
) -> StoredPlan:
    """Return the plan a ``check`` job kept, without the network.

    Raises
    ------
    NotFoundError
        No job ``job_id`` the principal sees (``job.not_found``), or the job
        kept no plan (``job.no_plan``): it is not a ``check``, has not ended
        yet, or failed.
    """
    _visible_job(jobs, job_id, visible)
    return _stored_plan(queries, job_id)


def _visible_job(
    jobs: JobSupervisor, job_id: str, visible: ProjectVisibility
) -> JobRecord:
    """Return a job the principal sees, else refuse with ``job.not_found``."""
    record = jobs.get(job_id, visible=visible)
    if record is None:
        raise NotFoundError(message("job.not_found", job=job_id))
    return record


def _stored_plan(queries: IndexQueries, job_id: str) -> StoredPlan:
    """Return the plan a job kept, else refuse with ``job.no_plan``."""
    stored = queries.plan(job_id)
    if stored is None:
        raise NotFoundError(message("job.no_plan", job=job_id))
    return stored


def _call_key(store: str | None, params: Mapping[str, object]) -> tuple[object, ...]:
    """Return a job's store and call, its options as the jobs compare them."""
    options = json.dumps(params.get("options"), sort_keys=True, ensure_ascii=False)
    return (store, params.get("producer"), params.get("command"), options)
