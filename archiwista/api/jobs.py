"""Background jobs over HTTP: start them, list them, follow their events.

``POST /stores/{store}/scan``, ``/footprints`` and ``/link-check`` (SPEC 9.2,
5.6) record a job of the session's principal (its ``actor``) and answer
``202`` with it at once, with ``Location: /api/v1/jobs/{job}``; a worker
process runs it (``archiwista.jobs``). While another job writes the store's
index (``scan``, ``footprints``) a second one answers ``409 conflict`` naming
that job in ``job``; unit outlines in offline mode answer ``409
offline_mode``. ``GET /jobs`` and ``GET /jobs/{job}`` read the jobs of every
process, ``archiwista reindex`` too. ``GET /jobs/{job}/events`` streams a
job's ``progress``, ``notice`` and ``state`` events as Server-Sent Events:
the ``id`` of each is its number, a client resumes after ``Last-Event-ID``
from the events kept in the index, and the stream ends after the final state
(or when the server stops). Jobs concern stores, which everyone sees
(A-ADR-029), so no project visibility applies to them.
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
    index_queries,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_body, problem_responses
from archiwista.api.models import (
    JobDetail,
    JobFilters,
    JobList,
    LinkCheckRequest,
    ScanRequest,
)
from archiwista.auth import Principal, ProjectVisibility
from archiwista.config import SettingsService
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries
from archiwista.jobs import FINISHED_STATES, JobEvent, JobRecord, JobSupervisor, label
from archiwista.messages import MESSAGES
from archiwista.security import current_principal, require_csrf

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


def _messages(events: Sequence[JobEvent]) -> str:
    # One write per read: a client gone mid-replay costs one failed write.
    return "".join(sse_message(event.seq, event.type, event.data) for event in events)


def _final(events: Sequence[JobEvent]) -> bool:
    return any(
        event.type == "state" and event.data.get("state") in FINISHED_STATES
        for event in events
    )


async def job_event_stream(
    jobs: JobSupervisor, streams: JobStreams, job: str, *, after: int = 0
) -> AsyncIterator[str]:
    """Yield a job's events after ``after`` as SSE messages until it ends.

    The index is the source: the supervisor's listener only announces new
    events, and a quiet second reads the index anyway, so jobs of other
    processes stream too; the events of each read go out in one write. It
    ends after the final ``state`` event, when the job has ended past
    ``after`` or disappears, or when ``streams`` close.

    Parameters
    ----------
    jobs : JobSupervisor
        The started supervisor.
    streams : JobStreams
        The application's streams; closing them ends this one.
    job : str
        Job id.
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
            events = await asyncio.to_thread(jobs.events, job, after=last)
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
            record = await asyncio.to_thread(jobs.get, job)
            if record is None or record.state in FINISHED_STATES:
                # Events written before the state was read come last.
                rest = await asyncio.to_thread(jobs.events, job, after=last)
                if rest:
                    yield _messages(rest)
                return
            if quiet_s >= KEEPALIVE_INTERVAL_S:
                quiet_s = 0.0
                yield KEEPALIVE
    finally:
        unsubscribe()
        unwatch()


def _job(jobs: JobSupervisor, job: str) -> JobRecord:
    """Return a job or refuse with ``404 not_found``."""
    record = jobs.get(job)
    if record is None:
        raise NotFoundError(MESSAGES["job_not_found"].format(job=job))
    return record


def _accepted(job: JobRecord, response: Response) -> JobDetail:
    """Return a started job, naming where it can be followed."""
    response.headers["Location"] = f"{API_PREFIX}/jobs/{job.id}"
    return JobDetail.of(job)


def _conflicts(*codes: str) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI ``409`` of a route answering these problem codes."""
    running = {"id": "3f9c1a7e5b2d4c60", "kind": "scan", "state": "running"}
    examples = {
        "conflict": problem_body(
            409,
            "conflict",
            MESSAGES["job_conflict"].format(
                store="zespol",
                kind=label("job_kind", running["kind"]),
                state=label("job_state", running["state"]),
                job=running["id"],
            ),
            {"job": running},
        ),
        "offline_mode": problem_body(409, "offline_mode", MESSAGES["job_offline_mode"]),
    }
    return {
        409: {
            "description": (
                "Another job already writes the store's index (`conflict`, that"
                " job in `job`) or offline mode is on (`offline_mode`)."
            ),
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                    "examples": {code: {"value": examples[code]} for code in codes},
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
                "message": MESSAGES["project_dir_unreadable"].format(
                    path="/mnt/nas/projekty/archiwum"
                ),
            },
        ),
        sse_message(18, "state", {"state": "succeeded", "result": {"entries": 80000}}),
    )
)

_Principal = Annotated[Principal, Depends(current_principal)]
_Jobs = Annotated[JobSupervisor, Depends(job_supervisor)]
_Streams = Annotated[JobStreams, Depends(job_streams)]
_Store = Annotated[str, Path(description="Store id.", examples=["zespol"])]
_JobId = Annotated[str, Path(description="Job id.", examples=["3f9c1a7e5b2d4c60"])]
_CHANGE = [Depends(require_csrf)]


@router.post(
    "/stores/{store}/scan",
    response_model=JobDetail,
    status_code=202,
    dependencies=_CHANGE,
    responses={**problem_responses(404, 422), **_conflicts("conflict")},
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
    job = jobs.submit("scan", store=store, params=params, actor=principal.id)
    return _accepted(job, response)


@router.post(
    "/stores/{store}/footprints",
    response_model=JobDetail,
    status_code=202,
    dependencies=_CHANGE,
    responses={**problem_responses(404), **_conflicts("conflict", "offline_mode")},
)
def start_footprints(
    store: _Store, principal: _Principal, jobs: _Jobs, response: Response
) -> JobDetail:
    """Outline the units of versions still without one, over the network.

    Takes no body. In offline mode it answers `409 offline_mode` and records
    nothing.
    """
    job = jobs.submit("footprints", store=store, actor=principal.id)
    return _accepted(job, response)


@router.post(
    "/stores/{store}/link-check",
    response_model=JobDetail,
    status_code=202,
    dependencies=_CHANGE,
    responses=problem_responses(404, 422),
)
def start_link_check(
    store: _Store,
    body: LinkCheckRequest,
    principal: _Principal,
    visible: Annotated[ProjectVisibility, Depends(visible_projects)],
    jobs: _Jobs,
    settings: Annotated[SettingsService, Depends(settings_service)],
    queries: Annotated[IndexQueries, Depends(index_queries)],
    response: Response,
) -> JobDetail:
    """Confirm by its content which version a slot's link holds (KA-5).

    Only a slot the index knows is checked (`404` otherwise). The job's
    `result.status` is `confirmed`, `index_outdated`, `mismatch` (recorded as
    the problem `link_mismatch`), `missing` or `not_a_link`.
    """
    configured = settings.get().store(store) is not None
    if configured and queries.slot(store, body.slot, visible=visible) is None:
        message = MESSAGES["api_slot_unknown"].format(slot=body.slot, store=store)
        raise NotFoundError(message)
    job = jobs.submit(
        "link_check", store=store, params={"slot": body.slot}, actor=principal.id
    )
    return _accepted(job, response)


@router.get("/jobs", response_model=JobList, responses=problem_responses(422))
def list_jobs(
    filters: Annotated[JobFilters, Query()], principal: _Principal, jobs: _Jobs
) -> JobList:
    """List background jobs newest first, with who started each (`actor`)."""
    page = jobs.list(
        kind=filters.kind,
        store=filters.store,
        state=filters.state,
        limit=filters.limit,
        cursor=filters.cursor,
    )
    return JobList.of(page)


@router.get("/jobs/{job}", response_model=JobDetail, responses=problem_responses(404))
def get_job(job: _JobId, principal: _Principal, jobs: _Jobs) -> JobDetail:
    """Return a job: who started it, its state, progress, and result or error."""
    return JobDetail.of(_job(jobs, job))


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
                " EventSource stops reconnecting."
            )
        },
        **problem_responses(404, 422),
    },
)
def get_job_events(
    job: _JobId,
    principal: _Principal,
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
    `notice` has `level` (`info`, `warning`), `code` and a Polish `message`,
    `state` has `state` and, at the end, `result` (succeeded) or `error`
    (`code`, `detail`). The stream ends after the final state; close the
    EventSource then. A `: keepalive` comment comes after 15 s of silence.
    """
    after = last_event_id or 0
    record = _job(jobs, job)
    if record.state in FINISHED_STATES and not jobs.events(job, after=after):
        return Response(status_code=204)
    return EventStreamResponse(
        job_event_stream(jobs, streams, job, after=after),
        headers={"Cache-Control": "no-store"},
    )
