"""Controls of background jobs for every interface (plan of 2026-10-25, A6).

``cancel``, ``retry`` and ``log`` take a job the principal sees and refuse any
other one as an unknown job (``404``, ``job.not_found``), for ``POST
/jobs/{job}/cancel``, ``POST /jobs/{job}/retry``, ``GET /jobs/{job}/log`` and
``archiwista jobs cancel|retry|log`` alike (ADR-038):

- ``cancel`` is for whoever started the job and for administrators
  (``job.cancel``, else ``403 permission_denied``); a job that has ended is a
  ``409 conflict`` (reason ``job_finished``). A waiting job ends
  ``cancelled`` at once, a running one when its worker has stopped, within
  the stop timeout; a job another process supervises (a server's job
  cancelled at the terminal, or the reverse) ends the same way through its
  own supervisor (``JobSupervisor.cancel``). The request is logged
  (``job.cancel``, A-ADR-047).
- ``retry`` submits a new job of the principal with the kind, store and
  parameters of a job that did not succeed (``RETRY_STATES``), as the
  principal sees that job, logged as ``job.retry`` of that job; a job that
  succeeded is a ``409 conflict`` (``job_succeeded``), so is one still
  active (``job_active``). What the
  kind needs at its start is asked again: a ``download`` needs
  ``store.write``, a ``snapshot`` ``project.write`` of its project, a
  ``project_repin`` and a ``project_restore`` ``project.write`` and
  ``store.write``, a
  ``scan``, ``footprints``, ``link_check`` or an ``own_scan`` of every
  project ``store.scan``, and an ``own_scan`` of one project keeps to the
  limits of a person's scans (``scan_limits``); the project of a
  ``snapshot`` must still be one the principal sees;
  the supervisor checks the rest as for any new job (the store configured,
  offline mode, a conflict, a job it joins).
- ``log`` returns the end of the job's log (its worker's standard error) to
  a principal who sees the whole job: a ``preview`` job that also builds
  files of projects the principal does not see is ``403
  permission_denied``; a job without a log is ``404`` (``job.no_log``).
"""

from collections.abc import Callable
from typing import Any

from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import ConflictError, NotFoundError, PermissionDeniedError
from archiwista.index import IndexQueries
from archiwista.jobs import (
    FINISHED_STATES,
    PROJECT_KINDS,
    JobRecord,
    JobState,
    JobSupervisor,
    LogTail,
)
from archiwista.jobs.supervisor import action_details
from archiwista.messages import label, message
from archiwista.services.owndata import scan_limits
from archiwista.services.pins import check_plan_pin
from archiwista.services.project_jobs import require as require_project_job

# States of a job that a retry runs again: it did not succeed.
RETRY_STATES: tuple[JobState, ...] = ("partial", "failed", "interrupted", "cancelled")
# Kinds of the jobs of a store that only administrators start (``store.scan``).
STORE_SCAN_KINDS = frozenset({"scan", "footprints", "link_check"})


def visible_job(
    jobs: JobSupervisor, job_id: str, visible: ProjectVisibility
) -> JobRecord:
    """Return a job as the principal sees it, else refuse with ``job.not_found``.

    Raises
    ------
    NotFoundError
        No job ``job_id``, or one only of projects the principal does not
        see: both answer alike.
    """
    record = jobs.get(job_id, visible=visible)
    if record is None:
        raise NotFoundError(message("job.not_found", job=job_id))
    return record


def cancel(
    jobs: JobSupervisor,
    authorizer: Authorizer,
    *,
    job_id: str,
    actor: Principal,
    visible: ProjectVisibility,
) -> JobRecord:
    """Cancel a job that waits or runs.

    Parameters
    ----------
    jobs : JobSupervisor
        Started supervisor; it cancels a job of another supervisor through a
        request that one carries out.
    authorizer : Authorizer
        Decides whether ``actor`` may cancel the job (``job.cancel``).
    job_id : str
        The job.
    actor : Principal
        Who asks.
    visible : ProjectVisibility
        The projects ``actor`` sees.

    Returns
    -------
    JobRecord
        The job right after the request, as ``actor`` sees it: ``cancelled``
        when it waited, still ``running`` (or ``queued`` under another
        supervisor) until it is stopped.

    Raises
    ------
    NotFoundError
        No job ``job_id`` that ``actor`` sees.
    PermissionDeniedError
        ``actor`` neither started the job nor is an administrator.
    ConflictError
        The job has ended (reason ``job_finished``, ``details.job``).
    """
    record = visible_job(jobs, job_id, visible)
    authorizer.require(actor, "job.cancel", record.actor, target=job_id)
    if record.state in FINISHED_STATES:
        state = label("job.state", record.state)
        raise ConflictError(
            message("job.cancel_finished", job=job_id, state=state),
            reason="job_finished",
            details={"job": _named(record)},
        )
    jobs.cancel(job_id)
    authorizer.state.record(
        actor,
        "job.cancel",
        job_id,
        details=action_details(record.kind, record.store, record.params),
    )
    return visible_job(jobs, job_id, visible)


def retry(
    jobs: JobSupervisor,
    authorizer: Authorizer,
    queries: IndexQueries,
    settings: AppSettings,
    *,
    job_id: str,
    actor: Principal,
    visible: ProjectVisibility,
) -> JobRecord:
    """Start a job that did not succeed again, as a new job of ``actor``.

    Parameters
    ----------
    jobs : JobSupervisor
        Started supervisor of the new job.
    authorizer : Authorizer
        Decides what the kind of the job needs (``store.write``,
        ``project.write``, ``store.scan``).
    queries : IndexQueries
        The local index: the project of a ``snapshot`` job.
    settings : AppSettings
        The configured stores and project directories: the ``pin`` of a
        ``download``.
    job_id : str
        The job to run again.
    actor : Principal
        Who asks: the new job's actor.
    visible : ProjectVisibility
        The projects ``actor`` sees: a ``preview`` job is run again with the
        refs ``actor`` sees.

    Returns
    -------
    JobRecord
        The new job, ``queued`` or already ``running``, as ``actor`` sees it;
        for a kind that joins (``preview``, ``availability``), the active job
        of the same request it joined.

    Raises
    ------
    NotFoundError
        No job ``job_id`` that ``actor`` sees; the project of a ``snapshot``
        is gone or hidden; the store is no longer configured.
    ConflictError
        The job succeeded (reason ``job_succeeded``) or has not ended
        (``job_active``), with ``details.job``.
    PermissionDeniedError
        A ``download`` without ``store.write`` (and, with ``pin``, without
        ``project.write`` of its project), a ``snapshot`` without
        ``project.write`` of its project, a ``project_repin`` or a
        ``project_restore`` without ``project.write`` or ``store.write``, a
        ``scan``, ``footprints``,
        ``link_check`` or an ``own_scan`` of every project without
        ``store.scan``.
    ConflictError, InvalidChangeError
        The ``pin`` of a ``download`` is refused as ``actions.start`` refuses
        it (``group_exists``, ``other_store``, ``unknown_store``).
    RateLimitedError
        An ``own_scan`` of one project beyond the limits of a person's scans
        (``scan_running``, ``scan_too_soon``).
    OfflineModeError, JobConflictError
        As for any new job of the kind (``JobSupervisor.submit``).
    """
    record = visible_job(jobs, job_id, visible)
    if record.state == "succeeded":
        raise ConflictError(
            message("job.retry_succeeded", job=job_id),
            reason="job_succeeded",
            details={"job": _named(record)},
        )
    if record.state not in RETRY_STATES:
        state = label("job.state", record.state)
        raise ConflictError(
            message("job.retry_active", job=job_id, state=state),
            reason="job_active",
            details={"job": _named(record)},
        )
    if record.kind == "download":
        authorizer.require(actor, "store.write", target=record.store)
        pin = record.params.get("pin")
        if isinstance(pin, dict) and record.store is not None:
            check_plan_pin(
                settings,
                queries,
                authorizer,
                project=str(pin["project"]),
                group=str(pin["group"]),
                producer=str(record.params["producer"]),
                store=record.store,
                actor=actor,
                visible=visible,
            )
    if record.kind in STORE_SCAN_KINDS:
        authorizer.require(actor, "store.scan")
    admit: Callable[[], None] | None = None
    if record.kind == "own_scan":
        scanned = record.params.get("project")
        if scanned is None:
            authorizer.require(actor, "store.scan")
        else:
            admit = scan_limits(jobs, actor, str(scanned))
    if record.kind == "snapshot" or record.kind in PROJECT_KINDS:
        project = str(record.params["project"])
        found = queries.project(project, visible=visible)
        if found is None:
            raise NotFoundError(message("project.not_found", project=project))
        if record.kind == "snapshot":
            authorizer.require(actor, "project.write", found.project.access_key)
        else:
            require_project_job(authorizer, actor, record.kind, found.project)
    submitted = jobs.submit(
        record.kind,
        store=record.store,
        params=record.params,
        actor=actor,
        admit=admit,
        retry_of=record.id,
    )
    return jobs.get(submitted.id, visible=visible) or submitted


def log(jobs: JobSupervisor, *, job_id: str, visible: ProjectVisibility) -> LogTail:
    """Return the end of a job's log to a principal who sees the whole job.

    Raises
    ------
    NotFoundError
        No job ``job_id`` that the principal sees (``job.not_found``), or the
        job has no log (``job.no_log``).
    PermissionDeniedError
        The job also holds files of projects the principal does not see.
    """
    visible_job(jobs, job_id, visible)
    if not jobs.sees_whole(job_id, visible=visible):
        raise PermissionDeniedError(
            message("permission.job_log"), action="project.view", target=job_id
        )
    tail = jobs.log(job_id)
    if tail is None:
        raise NotFoundError(message("job.no_log", job=job_id))
    return tail


def _named(record: JobRecord) -> dict[str, Any]:
    """Return a job as a refusal names it: its id, kind and state."""
    return {"id": record.id, "kind": record.kind, "state": record.state}
