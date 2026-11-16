"""``archiwista reindex``: full scans of stores, run in the foreground.

Each scan is a job like any other (``JobSupervisor``, table ``jobs``, actor
``local`` of kind ``local_owner``, without a session), run on
``archiwista.jobs.foreground``, so a running server shows it, and a job
already writing the store's index makes it a conflict (code ``conflict``).
Progress and notices go to standard error, the summary of each store to
standard output. Ctrl+C cancels the scan: its pass is abandoned and nothing
is marked missing.
"""

from collections.abc import Sequence
from typing import TextIO

from archiwista._errors import OUTCOMES
from archiwista.auth import LOCAL_OWNER
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
    SourceRegistryView,
)
from archiwista.error_document import describe, exception_problem, fail, refuse
from archiwista.errors import JobConflictError
from archiwista.index.schema import IndexUnsupportedError, initialize
from archiwista.jobs.foreground import exit_status, run_foreground
from archiwista.jobs.supervisor import (
    WORKER_COMMAND,
    JobEvent,
    JobRecord,
    JobSupervisor,
)
from archiwista.messages import label, message, with_detail


def reindex_main(
    paths: AppPaths,
    registry: SourceRegistryView,
    out: TextIO,
    err: TextIO,
    *,
    store: str | None = None,
    worker_command: Sequence[str] = WORKER_COMMAND,
) -> int:
    """Run ``archiwista reindex [--store ID]``; return the exit status.

    Parameters
    ----------
    paths : AppPaths
        Configuration file and local data.
    registry : SourceRegistryView
        Producer plugins, for the settings.
    out, err : TextIO
        Summaries; progress, notices and errors.
    store : str or None, optional
        The store to scan; every configured store when omitted.
    worker_command : Sequence[str], optional
        Command of the worker processes.

    Returns
    -------
    int
        ``0`` when every scan succeeded; ``10`` when some did and some did
        not; ``130`` when one was cancelled or interrupted; otherwise the worst
        of the scans: ``11`` for a failed scan, ``4`` when a running job of
        its store is in the way (``conflict``). ``3`` for an unknown store,
        ``14`` without stores and the registry's exit code of an unusable
        configuration or index.
    """
    try:
        settings = SettingsService(ConfigStore(paths.config_file), registry)
        initialize(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError) as error:
        return refuse(
            exception_problem(
                error, with_detail(message("reindex.failed"), str(error))
            ),
            err,
        )
    current = settings.get()
    if store is not None and current.store(store) is None:
        text = message("job.store_unknown", store=store)
        return fail(err, "not_found", text, reason="unknown_store")
    stores = [store] if store is not None else [item.id for item in current.stores]
    if not stores:
        return fail(err, "no_data", message("reindex.no_stores"), reason="no_stores")
    statuses: list[int] = []
    with JobSupervisor(paths, settings, worker_command=worker_command) as jobs:
        for store_id in stores:
            statuses.append(_reindex(jobs, store_id, out, err))
    return _overall(statuses)


def _overall(statuses: Sequence[int]) -> int:
    """Return the exit status of scans of several stores (ERR §1)."""
    if not any(statuses):
        return OUTCOMES["ok"]
    if OUTCOMES["cancelled"] in statuses:
        return OUTCOMES["cancelled"]
    return OUTCOMES["partial"] if 0 in statuses else max(statuses)


def _reindex(jobs: JobSupervisor, store: str, out: TextIO, err: TextIO) -> int:
    """Fully scan one store and report it."""

    def event(heard: JobEvent) -> str | None:
        if heard.type == "progress":
            return message(
                "reindex.progress",
                store=store,
                current=heard.data["current"],
                total=heard.data["total"],
                entries=heard.data.get("entries", 0),
            )
        if heard.type == "notice":
            return message("reindex.notice", store=store, message=heard.data["message"])
        return None

    try:
        record = run_foreground(
            jobs,
            lambda: jobs.submit(
                "scan", store=store, params={"mode": "full"}, actor=LOCAL_OWNER
            ),
            err,
            started=lambda job: message("reindex.started", store=store, job=job.id),
            event=event,
            cancelling=lambda job: message("reindex.cancelling", job=job.id),
        )
    except JobConflictError as error:
        return refuse(describe(error), err)
    return _report(record, store, out, err)


def _report(record: JobRecord, store: str, out: TextIO, err: TextIO) -> int:
    if record.state == "succeeded" and record.result is not None:
        result = record.result
        out.write(
            message(
                "reindex.succeeded",
                store=store,
                seconds=f"{result['seconds']:.1f}".replace(".", ","),
                entries=result["entries"],
                versions=result["versions_written"],
                missing=result["missing"],
                removed=result["removed"],
            )
            + "\n"
        )
        return 0
    error = record.error
    detail = error.detail if error is not None else ""
    code = (error.reason or error.code) if error is not None else record.state
    text = message(
        "reindex.job_failed",
        store=store,
        job=record.id,
        state=label("job.state", record.state),
        detail=detail,
    )
    err.write(message("reindex.error", message=text, code=code) + "\n")
    return exit_status(record.state)
