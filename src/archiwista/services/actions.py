"""Producers' commands run as jobs, for every interface (plan of 2026-10-25, A4).

``start`` takes a request for a job of a producer's command on a configured
store (``POST /jobs``, ``archiwista jobs start``) and refuses before a job
exists what its worker would refuse: a store that is not configured (``404``),
a command outside the producer's catalog (``400``, ``unknown_command``), one
that works on no store or has no plan without effects (``422 unsupported``,
``no_store``, ``no_check``), an option that is a file path (``403``,
``path_outside_root``) and the producer's own refusal of the options (``400``,
its text); offline mode refuses a job that needs the network (``409``,
``offline_mode``), and nothing is recorded. The job keeps the options as the
producer read them. ``kept_plan`` returns the plan a ``check`` job kept
(``GET /jobs/{job}/plan``, ``archiwista jobs plan``). Nothing here uses the
network: the producer's check runs in the job's worker.
"""

from typing import Literal, get_args

from archiwista.auth import Principal, ProjectVisibility
from archiwista.config import AppSettings
from archiwista.errors import NotFoundError, UnsupportedError
from archiwista.index import IndexQueries, StoredPlan
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.services.commands import actions, checked_call, command_info
from archiwista.sources import CommandCall
from archiwista.sources.registry import PluginRegistry

# The kinds of a job of a producer's command: ``check`` plans a run of the
# command in the store without its effects (ADR-036).
type ActionKind = Literal["check"]
ACTION_KINDS: tuple[ActionKind, ...] = get_args(ActionKind.__value__)


def start(
    registry: PluginRegistry,
    settings: AppSettings,
    jobs: JobSupervisor,
    *,
    kind: ActionKind,
    store: str,
    call: CommandCall,
    actor: Principal,
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
    kind : {"check"}
        What the job does with the command (``ACTION_KINDS``).
    store : str
        Id of the configured store whose producer directory the command works
        on, never the producer's default root.
    call : CommandCall
        The producer, the command of its catalog and the options; ``run`` is
        not read.
    actor : Principal
        Who asks: the job's actor.

    Returns
    -------
    JobRecord
        The job, ``queued`` or already ``running``; its parameters hold the
        producer, the command and the options as the producer read them.

    Raises
    ------
    NotFoundError
        ``store`` is not configured.
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
    OfflineModeError
        Offline mode is on; nothing is recorded.
    """
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
    params = {
        "producer": checked.producer,
        "command": checked.command,
        "options": dict(checked.options),
    }
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
    if jobs.get(job_id, visible=visible) is None:
        raise NotFoundError(message("job.not_found", job=job_id))
    stored = queries.plan(job_id)
    if stored is None:
        raise NotFoundError(message("job.no_plan", job=job_id))
    return stored
