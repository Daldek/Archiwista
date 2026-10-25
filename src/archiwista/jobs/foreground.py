"""Jobs run in the foreground of a command (plan v0.2, contract "Zadania").

``run_foreground`` submits a job to the command's own ``JobSupervisor`` and
follows it to its end: what the command makes of each event (progress,
notices) goes to standard error, and Ctrl+C cancels the job and waits until
it ends (a scan abandons its pass). ``archiwista reindex`` and ``preview
--build`` run on it.

A kind that joins active jobs (``preview``, ``own_scan``) may hand the
request to a job another process supervises, e.g. a running server's. That
job's worker may have started before the request joined it, so the command
follows the job to its end and then submits again: its own job runs after
the other one, as a request joining a waiting job would (a ``preview`` of a
file the other job built finds nothing left to build). Ctrl+C meanwhile
stops only the waiting: the other process's job goes on. A conflict
(``JobConflictError``: another job writes the store's index) is raised to
the command, not waited for.

A command exits with the outcome of its job (ERR §1, ``exit_status``): ``0``
when it succeeded, ``11`` when it failed, ``130`` when it was cancelled or
interrupted, and after Ctrl+C. These are outcomes, not errors: the command
prints no error document for them.
"""

import time
from collections.abc import Callable
from typing import TextIO

from archiwista._errors import OUTCOMES
from archiwista.jobs.supervisor import (
    FINISHED_STATES,
    JobEvent,
    JobRecord,
    JobState,
    JobSupervisor,
)
from archiwista.messages import label, message

# Seconds between two looks at a job of another process.
POLL_S = 0.5


def exit_status(state: JobState) -> int:
    """Return the exit status of a command whose job is in ``state`` (ERR §1).

    Parameters
    ----------
    state : JobState
        The job's state when the command stopped following it.

    Returns
    -------
    int
        ``0`` for ``succeeded``, ``11`` for ``failed``, ``130`` for
        ``cancelled``, ``interrupted`` and a job still active after Ctrl+C.
    """
    if state == "succeeded":
        return OUTCOMES["ok"]
    return OUTCOMES["failed"] if state == "failed" else OUTCOMES["cancelled"]


def run_foreground[R: (JobRecord, JobRecord | None)](
    jobs: JobSupervisor,
    submit: Callable[[], R],
    err: TextIO,
    *,
    started: Callable[[JobRecord], str],
    event: Callable[[JobEvent], str | None],
    cancelling: Callable[[JobRecord], str],
    poll_s: float = POLL_S,
) -> R:
    """Submit a job and follow it to its end (see the module).

    Parameters
    ----------
    jobs : JobSupervisor
        The command's started supervisor.
    submit : Callable[[], JobRecord or None]
        Submits the job to ``jobs`` and returns it, or ``None`` when there
        is nothing to do; called again after a job of another process that
        the request joined has ended.
    err : TextIO
        Where the messages go.
    started, event, cancelling : Callable
        The command's messages: its job started, one of the job's events
        (``None``: nothing to say), Ctrl+C cancelling its job.
    poll_s : float, default 0.5
        Seconds between two looks at a job of another process.

    Returns
    -------
    JobRecord or None
        The command's job as it ended; ``None`` when ``submit`` found
        nothing to do. After Ctrl+C while a job of another process was
        followed: that job as it is then, still active.

    Raises
    ------
    ArchiwistaError
        What ``submit`` raises, e.g. ``JobConflictError``.
    """
    while True:
        record = submit()
        if record is None:
            return record
        if record.state in FINISHED_STATES or jobs.supervises(record.id):
            # Also a job that ended at once, when its start failed.
            return _follow(jobs, record, err, started, event, cancelling)
        kind = label("job.kind", record.kind)
        _say(err, message("job.foreground_waiting", job=record.id, kind=kind))
        if not _follow_other(jobs, record, err, event, poll_s):
            return jobs.get(record.id) or record


def _follow(
    jobs: JobSupervisor,
    record: JobRecord,
    err: TextIO,
    started: Callable[[JobRecord], str],
    event: Callable[[JobEvent], str | None],
    cancelling: Callable[[JobRecord], str],
) -> JobRecord:
    """Follow the command's own job to its end; Ctrl+C cancels it."""
    _say(err, started(record))
    unsubscribe = jobs.subscribe(
        lambda heard: _say(err, event(heard)), job_id=record.id
    )
    try:
        try:
            return jobs.wait(record.id)
        except KeyboardInterrupt:
            _say(err, cancelling(record))
            jobs.cancel(record.id)
            return jobs.wait(record.id)
    finally:
        unsubscribe()


def _follow_other(
    jobs: JobSupervisor,
    record: JobRecord,
    err: TextIO,
    event: Callable[[JobEvent], str | None],
    poll_s: float,
) -> bool:
    """Follow a job of another process to its end; ``False`` after Ctrl+C.

    Only its events from now on are told. A job whose process is gone ends
    ``interrupted`` here (``recover``), so the waiting ends with it.
    """
    known = jobs.events(record.id)
    seen = known[-1].seq if known else 0
    try:
        while True:
            # The state first: every event up to the end is read after it.
            current = jobs.get(record.id)
            for heard in jobs.events(record.id, after=seen):
                seen = heard.seq
                _say(err, event(heard))
            if current is None or current.state in FINISHED_STATES:
                return True
            time.sleep(poll_s)
            jobs.recover()
    except KeyboardInterrupt:
        _say(err, message("job.foreground_stopped", job=record.id))
        return False


def _say(err: TextIO, message: str | None) -> None:
    if message is not None:
        err.write(message + "\n")
        err.flush()
