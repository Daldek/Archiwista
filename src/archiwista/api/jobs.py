"""Background jobs over HTTP: start them, list them, follow their events.

``POST /stores/{store}/scan``, ``/footprints`` and ``/link-check`` (SPEC 9.2,
5.6) record a job of the session's principal (its ``actor``, with the kind
and the session label) and answer
``202`` with it at once, with ``Location: /api/v1/jobs/{job}``; a worker
process runs it (``archiwista.jobs``). While another job writes the store's
index (``scan``, ``footprints``) a second one answers ``409 conflict`` naming
that job in ``job``; unit outlines in offline mode answer ``409
offline_mode``. ``GET /jobs`` and ``GET /jobs/{job}`` read the jobs of every
process, ``archiwista reindex`` too. ``GET /jobs/{job}/events`` streams a
job's ``progress``, ``notice`` and ``state`` events as Server-Sent Events:
the ``id`` of each is its number, a client resumes after ``Last-Event-ID``
from the events kept in the index, and the stream ends after the final state
(or when the server stops). ``POST /jobs/{job}/cancel`` stops a job that
waits or runs (whoever started it or an administrator; ``409`` once it has
ended), ``POST /jobs/{job}/retry`` starts one that did not succeed again as a
new job of the session (``409`` for one that succeeded or is active), and
``GET /jobs/{job}/log`` returns the end of its log (ADR-038,
``archiwista.services.jobs``). What a session sees of the jobs follows their
scope (plan v0.2 "Zadania", ``JobSupervisor``): a job of a store or of
versions (``version:`` refs), or of no project at all, everyone sees; one of
projects only (an ``own_scan`` of a project, a ``snapshot``, a ``preview`` of
own files) only whoever sees one of them, the others find it neither in
``GET /jobs`` nor at its address (``404 not_found``, as an unknown job). A
``preview`` job shows only the refs and failures of visible projects, with
whole counts (A-ADR-029); ``GET /jobs?project=`` keeps the jobs with data of
one project.
"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from archiwista.api import API_PREFIX
from archiwista.api.dependencies import (
    authorizer,
    index_queries,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import (
    PROBLEM_MEDIA_TYPE,
    problem_example,
    problem_responses,
)
from archiwista.api.models import (
    JobDetail,
    JobFilters,
    JobList,
    JobLog,
    LinkCheckRequest,
    ScanRequest,
)
from archiwista.api.slots import checked_project
from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import SettingsService
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries
from archiwista.jobs import (
    FINISHED_STATES,
    JobError,
    JobEvent,
    JobRecord,
    JobSupervisor,
)
from archiwista.messages import current_language, label, message
from archiwista.security import current_principal
from archiwista.services import jobs as job_controls

router = APIRouter(tags=["jobs"])

EVENT_STREAM = "text/event-stream"
# Seconds a stream waits for news of an event before it reads the index anyway
# (another process's job, e.g. ``archiwista reindex``, sends none), and
# seconds of silence after which it sends a comment keeping the connection.
POLL_INTERVAL_S = 1.0
KEEPALIVE_INTERVAL_S = 15.0
KEEPALIVE = ": keepalive\n\n"


class JobStreams:
    """The application's open event streams; ``close`` ends them all.

    The server closes them as it starts to stop, before it waits for open
    connections: a stream would otherwise keep it running until its job
    ends. A stream opened afterwards ends at once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wakers: list[Callable[[], None]] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether the streams were closed."""
        return self._closed

    def watch(self, wake: Callable[[], None]) -> Callable[[], None]:
        """Call ``wake`` when the streams close; return the call forgetting it."""
        with self._lock:
            self._wakers.append(wake)

        def unwatch() -> None:
            with self._lock, suppress(ValueError):
                self._wakers.remove(wake)

        return unwatch

    def close(self) -> None:
        """End every open stream (thread-safe; later calls do nothing new)."""
        with self._lock:
            self._closed = True
            wakers = tuple(self._wakers)
        for wake in wakers:
            wake()


class EventStreamResponse(StreamingResponse):
    """Server-Sent Events (``text/event-stream``)."""

    media_type = EVENT_STREAM


def job_supervisor(request: Request) -> JobSupervisor:
    """Return the server's supervisor of background jobs."""
    value: JobSupervisor = request.app.state.jobs
    return value


def job_streams(request: Request) -> JobStreams:
    """Return the application's open event streams."""
    value: JobStreams = request.app.state.job_streams
    return value


def sse_message(seq: int, event: str, data: Mapping[str, object]) -> str:
    """Return one Server-Sent Events message: ``id``, ``event`` and JSON ``data``.

    JSON escapes line breaks inside strings, so ``data`` is a single line.
    """
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {event}\ndata: {text}\n\n"


def _event_data(event: JobEvent) -> Mapping[str, object]:
    """Return an event's data as it is sent.

    The stored error of a final ``state`` becomes the error of the API: its
    texts in the language of the request, without the keys and values.
    """
    error = event.data.get("error")
    if event.type != "state" or not isinstance(error, Mapping):
        return event.data
    shown = JobError.from_json(error).public_json(current_language())
    return {**event.data, "error": shown}


def _messages(events: Sequence[JobEvent]) -> str:
    # One write per read: a client gone mid-replay costs one failed write.
    return "".join(
        sse_message(event.seq, event.type, _event_data(event)) for event in events
    )


def _final(events: Sequence[JobEvent]) -> bool:
    return any(
        event.type == "state" and event.data.get("state") in FINISHED_STATES
        for event in events
    )


async def job_event_stream(
    jobs: JobSupervisor,
    streams: JobStreams,
    job: str,
    *,
    visible: ProjectVisibility,
    after: int = 0,
) -> AsyncIterator[str]:
    """Yield a job's events after ``after`` as SSE messages until it ends.

    The index is the source: the supervisor's listener only announces new
    events, and a quiet second reads the index anyway, so jobs of other
    processes stream too; the events of each read go out in one write. It
    ends after the final ``state`` event, when the job has ended past
    ``after`` or disappears (or is no longer seen), or when ``streams`` close.

    Parameters
    ----------
    jobs : JobSupervisor
        The started supervisor.
    streams : JobStreams
        The application's streams; closing them ends this one.
    job : str
        Job id.
    visible : ProjectVisibility
        Projects the session sees: a job it does not see has no events, and a
        ``preview`` job's final state lists the failures of visible refs only
        (``JobSupervisor.events``).
    after : int, optional
        Number of the last event the client has (``Last-Event-ID``).
    """
    loop = asyncio.get_running_loop()
    wake = asyncio.Event()

    def announce(*_: object) -> None:
        # Runs in a supervisor thread (a new event) or where the server stops.
        with suppress(RuntimeError):  # the event loop is closed
            loop.call_soon_threadsafe(wake.set)

    unsubscribe = jobs.subscribe(announce, job_id=job)
    unwatch = streams.watch(announce)
    try:
        last = after
        quiet_s = 0.0
        while not streams.closed:
            wake.clear()
            events = await asyncio.to_thread(
                jobs.events, job, after=last, visible=visible
            )
            if events:
                yield _messages(events)
                if _final(events):
                    return
                last = events[-1].seq
                quiet_s = 0.0
            try:
                await asyncio.wait_for(wake.wait(), POLL_INTERVAL_S)
                continue
            except TimeoutError:
                quiet_s += POLL_INTERVAL_S
            record = await asyncio.to_thread(jobs.get, job, visible=visible)
            if record is None or record.state in FINISHED_STATES:
                # Events written before the state was read come last.
                rest = await asyncio.to_thread(
                    jobs.events, job, after=last, visible=visible
                )
                if rest:
                    yield _messages(rest)
                return
            if quiet_s >= KEEPALIVE_INTERVAL_S:
                quiet_s = 0.0
                yield KEEPALIVE
    finally:
        unsubscribe()
        unwatch()


def _accepted(job: JobRecord, response: Response) -> JobDetail:
    """Return a started job, naming where it can be followed."""
    response.headers["Location"] = f"{API_PREFIX}/jobs/{job.id}"
    return JobDetail.of(job)


def _conflicts(*codes: str) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI ``409`` of a route answering these problem codes."""
    running = {"id": "3f9c1a7e5b2d4c60", "kind": "scan", "state": "running"}
    examples = {
        "conflict": problem_example(
            "conflict",
            message(
                "job.conflict",
                store="zespol",
                kind=label("job.kind", running["kind"]),
                state=label("job.state", running["state"]),
                job=running["id"],
            ),
            details={"job": running},
        ),
        "offline_mode": problem_example(
            "conflict", message("job.offline_mode"), reason="offline_mode"
        ),
    }
    return {
        409: {
            "description": (
                "Another job already writes the store's index (`conflict`, that"
                " job in `details.job`) or offline mode is on (`offline_mode`:"
                " `details.reason`)."
            ),
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                    "examples": {code: {"value": examples[code]} for code in codes},
                }
            },
        }
    }


_CANCEL_CONFLICT = (
    "The job has ended (`details.reason` `job_finished`, the job in `details.job`)."
)
_RETRY_CONFLICT = (
    "The job succeeded (`details.reason` `job_succeeded`) or has not ended"
    " (`job_active`), the job in `details.job`; or the new job is refused as"
    " any job of its kind: another job writes the store's index (`conflict`)"
    " or offline mode is on (`offline_mode`)."
)


def _state_conflicts(
    description: str, *reasons: str
) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI ``409`` of a job control refusing a job in its state."""
    ended = {"id": "3f9c1a7e5b2d4c60", "kind": "download", "state": "succeeded"}
    running = {**ended, "state": "running"}
    examples = {
        "job_finished": problem_example(
            "conflict",
            message(
                "job.cancel_finished",
                job=ended["id"],
                state=label("job.state", ended["state"]),
            ),
            reason="job_finished",
            details={"job": ended},
        ),
        "job_succeeded": problem_example(
            "conflict",
            message("job.retry_succeeded", job=ended["id"]),
            reason="job_succeeded",
            details={"job": ended},
        ),
        "job_active": problem_example(
            "conflict",
            message(
                "job.retry_active",
                job=running["id"],
                state=label("job.state", running["state"]),
            ),
            reason="job_active",
            details={"job": running},
        ),
    }
    return {
        409: {
            "description": description,
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                    "examples": {
                        reason: {"value": examples[reason]} for reason in reasons
                    },
                }
            },
        }
    }


_SSE_EXAMPLE = "".join(
    (
        sse_message(1, "state", {"state": "queued"}),
        sse_message(2, "state", {"state": "running"}),
        sse_message(
            3,
            "progress",
            {
                "current": 1,
                "total": 15,
                "segment": "nmt/pl_1992_1m_evrf2007",
                "entries": 5200,
            },
        ),
        sse_message(
            4,
            "notice",
            {
                "level": "warning",
                "code": "project_dir_unreadable",
                "message": message(
                    "project.dir_unreadable", "en", path="/mnt/nas/projekty/archiwum"
                ),
            },
        ),
        sse_message(18, "state", {"state": "succeeded", "result": {"entries": 80000}}),
    )
)

_Principal = Annotated[Principal, Depends(current_principal)]
_Jobs = Annotated[JobSupervisor, Depends(job_supervisor)]
_Streams = Annotated[JobStreams, Depends(job_streams)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_Store = Annotated[str, Path(description="Store id.", examples=["zespol"])]
_JobId = Annotated[str, Path(description="Job id.", examples=["3f9c1a7e5b2d4c60"])]


@router.post(
    "/stores/{store}/scan",
    response_model=JobDetail,
    status_code=202,
    responses={**problem_responses(404, 400), **_conflicts("conflict")},
)
def start_scan(
    store: _Store,
    principal: _Principal,
    jobs: _Jobs,
    response: Response,
    body: Annotated[ScanRequest | None, Body()] = None,
) -> JobDetail:
    """Scan a store into the index in the background; answer `202` with the job.

    Without a body the scan is incremental over the whole store. Follow it
    with `GET /jobs/{job}/events`.
    """
    params = (body or ScanRequest()).model_dump()
    job = jobs.submit("scan", store=store, params=params, actor=principal)
    return _accepted(job, response)


@router.post(
    "/stores/{store}/footprints",
    response_model=JobDetail,
    status_code=202,
    responses={**problem_responses(404), **_conflicts("conflict", "offline_mode")},
)
def start_footprints(
    store: _Store, principal: _Principal, jobs: _Jobs, response: Response
) -> JobDetail:
    """Outline the units of versions still without one, over the network.

    Takes no body. In offline mode it answers `409 offline_mode` and records
    nothing.
    """
    job = jobs.submit("footprints", store=store, actor=principal)
    return _accepted(job, response)


@router.post(
    "/stores/{store}/link-check",
    response_model=JobDetail,
    status_code=202,
    responses=problem_responses(404, 400),
)
def start_link_check(
    store: _Store,
    body: LinkCheckRequest,
    principal: _Principal,
    visible: _Visible,
    jobs: _Jobs,
    settings: Annotated[SettingsService, Depends(settings_service)],
    queries: _Queries,
    response: Response,
) -> JobDetail:
    """Confirm by its content which version a slot's link holds (KA-5).

    Only a slot the index knows is checked (`404` otherwise). The job's
    `result.status` is `confirmed`, `index_outdated`, `mismatch` (recorded as
    the problem `link_mismatch`), `missing` or `not_a_link`.
    """
    configured = settings.get().store(store) is not None
    if configured and queries.slot(store, body.slot, visible=visible) is None:
        text = message("api.slot_unknown", slot=body.slot, store=store)
        raise NotFoundError(text)
    job = jobs.submit(
        "link_check", store=store, params={"slot": body.slot}, actor=principal
    )
    return _accepted(job, response)


@router.get("/jobs", response_model=JobList, responses=problem_responses(404, 400))
def list_jobs(
    filters: Annotated[JobFilters, Query()],
    principal: _Principal,
    visible: _Visible,
    jobs: _Jobs,
    queries: _Queries,
) -> JobList:
    """List background jobs newest first, with who started each (`actor`).

    Jobs only of projects the session does not see are left out, and a
    `preview` job lists only the refs (and failures) of visible projects.
    `project` keeps the jobs with that project's data (`404` for a project
    the session does not see).
    """
    checked_project(queries, filters.project, visible)
    page = jobs.list(
        kind=filters.kind,
        store=filters.store,
        state=filters.state,
        project=filters.project,
        limit=filters.limit,
        cursor=filters.cursor,
        visible=visible,
    )
    return JobList.of(page)


@router.get("/jobs/{job}", response_model=JobDetail, responses=problem_responses(404))
def get_job(
    job: _JobId, principal: _Principal, visible: _Visible, jobs: _Jobs
) -> JobDetail:
    """Return a job: who started it, its state, progress, and result or error.

    A job only of projects the session does not see answers `404`, as an
    unknown one; a `preview` job lists only the refs of visible projects.
    """
    return JobDetail.of(job_controls.visible_job(jobs, job, visible))


@router.get(
    "/jobs/{job}/events",
    response_class=EventStreamResponse,
    responses={
        200: {
            "description": (
                "Events as Server-Sent Events, from the first or after"
                " `Last-Event-ID`; the stream ends after the final `state`."
            ),
            "content": {
                EVENT_STREAM: {"schema": {"type": "string"}, "example": _SSE_EXAMPLE}
            },
        },
        204: {
            "description": (
                "The job has ended and no event follows `Last-Event-ID`;"
                " a client stops reconnecting."
            )
        },
        **problem_responses(404, 400),
    },
)
def get_job_events(
    job: _JobId,
    principal: _Principal,
    visible: _Visible,
    jobs: _Jobs,
    streams: _Streams,
    last_event_id: Annotated[
        int | None,
        Header(
            alias="Last-Event-ID",
            ge=0,
            description="Number (`id`) of the last event received; resume after it.",
        ),
    ] = None,
) -> Response:
    """Stream a job's events: `progress`, `notice` and `state` (SSE).

    Each message's `id` is the event's number (from 1), `event` its type and
    `data` one line of JSON: `progress` has `current` and `total` (a scan
    adds `segment` and `entries`, footprints `written` and `failed`),
    `notice` has `level` (`info`, `warning`), `code` and a `message` (Polish: a
    notice is written as the job runs), `state` has `state` and, at the end,
    `result` (succeeded) or `error` (`code`, `detail`, `hint` and `details`
    with the `reason`; the texts in the language of the request). The stream
    ends after the
    final state; stop reconnecting then. A `: keepalive` comment comes after
    15 s of silence. A job only of projects the session does not see answers
    `404`; a `preview` job's final state lists the failures of visible refs.
    """
    after = last_event_id or 0
    record = job_controls.visible_job(jobs, job, visible)
    finished = record.state in FINISHED_STATES
    if finished and not jobs.events(job, after=after, visible=visible):
        return Response(status_code=204)
    return EventStreamResponse(
        job_event_stream(jobs, streams, job, visible=visible, after=after),
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/jobs/{job}/cancel",
    response_model=JobDetail,
    status_code=202,
    responses={
        **problem_responses(403, 404),
        **_state_conflicts(_CANCEL_CONFLICT, "job_finished"),
    },
)
def cancel_job(
    job: _JobId,
    principal: _Principal,
    visible: _Visible,
    decisions: _Authorizer,
    jobs: _Jobs,
    response: Response,
) -> JobDetail:
    """Cancel a job that waits or runs; answer `202` with the job as it is then.

    A waiting job is `cancelled` at once, without a worker. A running one is
    interrupted as Ctrl+C would and ends `cancelled` when its worker has
    stopped, within 30 s (then it is killed); a download publishes no half
    version and its finished files are read into the index. A job another
    process runs (`archiwista jobs start` at the terminal) is stopped by
    that process within a second. Follow the end with `GET
    /jobs/{job}/events`. Only whoever started the job (`actor`) or an
    administrator cancels it (`403 permission_denied`); a job that has ended
    is `409` (`job_finished`); a job only of projects the session does not
    see is `404`.
    """
    record = job_controls.cancel(
        jobs, decisions, job_id=job, actor=principal, visible=visible
    )
    return _accepted(record, response)


@router.post(
    "/jobs/{job}/retry",
    response_model=JobDetail,
    status_code=202,
    responses={
        **problem_responses(403, 404),
        **_state_conflicts(_RETRY_CONFLICT, "job_succeeded", "job_active"),
    },
)
def retry_job(
    job: _JobId,
    principal: _Principal,
    visible: _Visible,
    decisions: _Authorizer,
    jobs: _Jobs,
    queries: _Queries,
    response: Response,
) -> JobDetail:
    """Start a job that did not succeed again; answer `202` with the new job.

    A job that ended `partial`, `failed`, `interrupted` (the server stopped
    meanwhile) or `cancelled` is submitted again with its kind, store and
    `params` as the session sees them, as a new job of the session (its
    `actor`), with `Location: /api/v1/jobs/{new job}`. A download fetches
    only what its store still lacks: units it finished are not fetched
    again. What the kind needs at its start is asked again: a download needs
    the role `store_writer` or the setting `store_write_for_all`, a snapshot
    the project's owner or an administrator (`403 permission_denied`). A job
    that succeeded or has not ended is `409` (`job_succeeded`,
    `job_active`); the new job is refused as any job of its kind (another
    job writing the store's index, offline mode: `409`; a store no longer
    configured: `404`). A job only of projects the session does not see is
    `404`.
    """
    record = job_controls.retry(
        jobs, decisions, queries, job_id=job, actor=principal, visible=visible
    )
    return _accepted(record, response)


@router.get(
    "/jobs/{job}/log", response_model=JobLog, responses=problem_responses(403, 404)
)
def get_job_log(
    job: _JobId, principal: _Principal, visible: _Visible, jobs: _Jobs
) -> JobLog:
    """Return the end of a job's log: its worker's standard error, in English.

    The last MiB at most (`truncated`), read as the job runs. A job that never
    started its worker, or whose log went with the old logs (90 days, 1 GB),
    is `404`, as is a job only of projects the session does not see; a
    `preview` job that also builds files of projects the session does not
    see is `403 permission_denied`.
    """
    tail = job_controls.log(jobs, job_id=job, visible=visible)
    return JobLog.of(job, tail)
