"""``archiwista reindex``: full scans of stores, run in the foreground.

Each scan is a job like any other (``JobSupervisor``, table ``jobs``, actor
``local``), so a running server shows it, and a job already writing the
store's index makes it a conflict (code ``conflict``). Progress and notices
go to standard error, the summary of each store to standard output. Ctrl+C
cancels the scan: its pass is abandoned and nothing is marked missing.
"""

from collections.abc import Sequence
from typing import TextIO

from archiwista.api.errors import problem_of
from archiwista.auth import LOCAL_PRINCIPAL_ID
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
    SourceRegistryView,
)
from archiwista.errors import JobConflictError
from archiwista.index.schema import IndexUnsupportedError, initialize
from archiwista.jobs.supervisor import (
    WORKER_COMMAND,
    JobEvent,
    JobRecord,
    JobSupervisor,
    label,
)
from archiwista.messages import MESSAGES, with_detail


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
        ``0`` when every scan succeeded, ``1`` when one failed, was
        interrupted or met a running job of its store (``conflict``), ``2``
        for an unknown store.
    """
    try:
        settings = SettingsService(ConfigStore(paths.config_file), registry)
        initialize(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError) as error:
        err.write(with_detail(MESSAGES["reindex_failed"], str(error)) + "\n")
        return 1
    current = settings.get()
    if store is not None and current.store(store) is None:
        err.write(MESSAGES["job_store_unknown"].format(store=store) + "\n")
        return 2
    stores = [store] if store is not None else [item.id for item in current.stores]
    if not stores:
        err.write(MESSAGES["reindex_no_stores"] + "\n")
        return 1
    status = 0
    with JobSupervisor(paths, settings, worker_command=worker_command) as jobs:
        for store_id in stores:
            status = max(status, _reindex(jobs, store_id, out, err))
    return status


def _reindex(jobs: JobSupervisor, store: str, out: TextIO, err: TextIO) -> int:
    """Fully scan one store and report it."""
    try:
        job = jobs.submit(
            "scan", store=store, params={"mode": "full"}, actor=LOCAL_PRINCIPAL_ID
        )
    except JobConflictError as error:
        problem = problem_of(error)
        code = "conflict" if problem is None else problem[1]
        err.write(MESSAGES["reindex_error"].format(message=error, code=code) + "\n")
        return 1
    err.write(MESSAGES["reindex_started"].format(store=store, job=job.id) + "\n")

    def follow(event: JobEvent) -> None:
        if event.type == "progress":
            message = MESSAGES["reindex_progress"].format(
                store=store,
                current=event.data["current"],
                total=event.data["total"],
                entries=event.data.get("entries", 0),
            )
        elif event.type == "notice":
            message = MESSAGES["reindex_notice"].format(
                store=store, message=event.data["message"]
            )
        else:
            return
        err.write(message + "\n")
        err.flush()

    unsubscribe = jobs.subscribe(follow, job_id=job.id)
    try:
        try:
            record = jobs.wait(job.id)
        except KeyboardInterrupt:
            err.write(MESSAGES["reindex_cancelling"].format(job=job.id) + "\n")
            jobs.cancel(job.id)
            record = jobs.wait(job.id)
    finally:
        unsubscribe()
    return _report(record, store, out, err)


def _report(record: JobRecord, store: str, out: TextIO, err: TextIO) -> int:
    if record.state == "succeeded" and record.result is not None:
        result = record.result
        out.write(
            MESSAGES["reindex_succeeded"].format(
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
    detail = record.error.detail if record.error is not None else ""
    code = record.error.code if record.error is not None else record.state
    message = MESSAGES["reindex_job_failed"].format(
        store=store,
        job=record.id,
        state=label("job_state", record.state),
        detail=detail,
    )
    err.write(MESSAGES["reindex_error"].format(message=message, code=code) + "\n")
    return 1
