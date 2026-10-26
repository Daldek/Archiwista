"""Run background jobs in worker processes and keep them in the local index.

``JobSupervisor`` lives in the server and in the commands running a job in
the foreground (``archiwista.jobs.foreground``: ``reindex``, ``preview
--build``). It records every job in the index (``jobs``, with its
``actor``: the principal's id, kind and session label), starts one worker
process per job (``python -P -m archiwista.jobs.worker``, A-ADR-007),
reads the worker's JSON Lines (``archiwista.jobs.protocol``) and keeps them as
numbered job events (``job_events``), which it also hands to subscribers
(SSE, SPEC 9.2): ``progress``, ``notice`` and ``state``. A job is
``queued``, then ``running``, then ``succeeded``, ``partial`` (part of its
units failed; its summary names them), ``failed``, ``interrupted`` or
``cancelled``; one that ended without a summary has an ``error``
(``JobError``: a registry ``code``, ``detail``, ``details`` with the
``reason``).

Each kind has its rule (``JOB_RULES``; SPEC 5.6, plan v0.2 "Zadania"):
whether it works on a configured store, needs the network (refused in
offline mode, at most two network jobs run), runs alone (one ``preview``
at a time, one ``preview_warm``; the next ones wait in the queue), conflicts
with active jobs (one job writing a store's index at a time, ``scan`` or
``footprints``; one job of a project at a time, of the ``project_*`` kinds;
another one is a ``JobConflictError``), joins one (a ``preview`` of contents
an active build already has adds its refs to that job; an ``availability``
check of an area and product that an active check already asks returns that
job; a ``preview_warm`` of the filters of a waiting one returns it) or
overlaps one (a ``download`` of a call an active download of the
store runs too starts with a warning notice naming that job). At most half
the processors' worth of workers run, the rest wait in
the queue. Cancelling interrupts the worker as Ctrl+C would (SIGINT;
CTRL_BREAK_EVENT to its process group on Windows) and kills it after 30 s.
A job that another supervisor waits for or runs, in this process or in
another one (a server's job cancelled at the terminal, or the reverse), is
cancelled through a request file ``<jobs>/<id>.cancel``: each supervisor
looks for the requests of its own jobs every ``CANCEL_POLL_S`` and carries
them out, and the file goes when the job ends. ``log`` reads the end of a
job's log (``LogTail``).

A job whose supervising process is gone (a server stopped or crashed) becomes
``interrupted`` as soon as a supervisor meets it: every supervising process
locks ``<jobs>/owner-<pid>.lock``, which the system releases when the
process ends, and records its pid with each of its jobs. A worker whose
supervisor is gone interrupts itself. Each worker's standard error is its
job's log, ``<jobs>/<id>.log``; logs and finished jobs are kept 90 days (the
last finished job of each store and kind stays) and logs while under 1 GB.
Routine scans, the scheduler's incremental scans that succeeded without
changing anything, go after 48 hours with their events and logs (the newest
of each store stays); ``prune`` runs at the start and from the scheduler.

What a principal sees of the jobs follows their scope (plan v0.2 "Zadania"),
read from ``store`` and ``params``: a store or versions (``version:`` refs)
everyone sees, and so a job of no project (the ``own_scan`` of every
project); a job of projects only (``params.project``, ``file:`` and
``snapshot:`` refs; the ``project_*`` kinds) is seen by whoever sees one of
them. ``list``, ``get`` and ``events`` take the principal's ``visible``
projects (every project by default); a ``preview`` job then shows only the
refs and failures of visible projects, its counts staying whole (A-ADR-029).
"""

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal, Self, cast, get_args

from archiwista.auth import ALL_PROJECTS, Principal, PrincipalKind, ProjectVisibility
from archiwista.config import AppPaths, AppSettings, SettingsService
from archiwista.errors import (
    IndexQueryError,
    JobConflictError,
    NotFoundError,
    OfflineModeError,
)
from archiwista.index import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, IndexWriter
from archiwista.index.schema import connect, initialize
from archiwista.jobs.error import JobError
from archiwista.jobs.protocol import (
    CODE_CANCELLED,
    CODE_INTERNAL_ERROR,
    INTERRUPTED_EXIT,
    JOB_KINDS,
    PROJECT_KINDS,
    REASON_INTERRUPTED,
    REASON_WORKER_CRASHED,
    STOP_TIMEOUT_S,
    WARM_FILTERS,
    JobKind,
    JobSpec,
    JsonObject,
    ProtocolError,
    WorkerMessage,
    decode_message,
    encode_spec,
)
from archiwista.messages import STORED_LANG, label, localize, message
from archiwista.owndata.document import MAX_NOTE_CHARS
from archiwista.paths import private_directory
from archiwista.previews.types import CONTENT_KEY

if sys.platform == "win32":  # pragma: no cover - Windows
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)

type JobState = Literal[
    "queued", "running", "succeeded", "partial", "failed", "interrupted", "cancelled"
]
type EventType = Literal["progress", "notice", "state"]

JOB_STATES: tuple[JobState, ...] = get_args(JobState.__value__)
ACTIVE_STATES: tuple[JobState, ...] = ("queued", "running")
FINISHED_STATES: tuple[JobState, ...] = (
    "succeeded",
    "partial",
    "failed",
    "interrupted",
    "cancelled",
)
# States of a job that ended with its summary (``result``).
SUMMARY_STATES: tuple[JobState, ...] = ("succeeded", "partial")
# Network jobs (``JobRule.network``) running at once.
MAX_NETWORK_JOBS = 2
# Refs of one ``preview`` job, also once others joined it.
MAX_PREVIEW_REFS = 500
# Calls of one ``check`` or ``download`` job: the lines of a report's row or of
# a pasted list (ADR-044).
MAX_JOB_CALLS = 1000
# ``file_id`` of a ``snapshot`` job (``archiwista.index.own_file_id``).
_FILE_ID = re.compile(r"[0-9a-f]{16}")
# Refs of a project's own data (``file:<project>:…``, ``snapshot:<project>:…``)
# and of a store's version: what a job's scope is made of (``_Scope``).
_PROJECT_REFS = ("file", "snapshot")
_VERSION_REF = "version:"
LOG_MAX_AGE = timedelta(days=90)
LOG_MAX_BYTES = 1024**3
# Bytes of the end of a job's log that ``log`` reads.
LOG_TAIL_BYTES = 1024**2
# Seconds between two looks of a supervisor for cancel requests of its jobs.
CANCEL_POLL_S = 0.5
# Routine scans (scheduled, incremental, nothing changed) older than this go.
ROUTINE_SCAN_MAX_AGE = timedelta(hours=48)
# ``-P``: the working directory (the jobs directory) is not on ``sys.path``.
WORKER_COMMAND: tuple[str, ...] = (
    sys.executable,
    "-P",
    "-m",
    "archiwista.jobs.worker",
)
SCAN_MODES: tuple[str, ...] = ("incremental", "full")

_ACTIVE_SQL = "('queued', 'running')"
_FINISHED_SQL = "('succeeded', 'partial', 'failed', 'interrupted', 'cancelled')"
_JOB_COLUMNS = (
    "id, kind, state, actor, actor_kind, session, store, params, created_at,"
    " started_at, finished_at, summary, error"
)
# Counts of a scan's summary that are all zero when it changed nothing.
_SCAN_CHANGES = (
    "versions_written",
    "links_changed",
    "issues_added",
    "footprints_written",
    "missing",
    "reappeared",
    "removed",
    "slots_removed",
    "unlinked",
    "issues_resolved",
)
_CURSOR_VERSION = 1

# Jobs waiting or running under a supervisor of this process, and the owner
# locks this process holds (with the number of supervisors using each).
_PROCESS_LOCK = threading.Lock()
_ACTIVE_JOBS: set[str] = set()
_OWNER_LOCKS: dict[Path, tuple[IO[bytes], int]] = {}


@dataclass(frozen=True, slots=True)
class JobRecord:
    """A background job (``GET /jobs/{id}``).

    Attributes
    ----------
    id : str
        Opaque job id.
    kind : JobKind
        What the job does, one of ``JOB_KINDS``.
    state : JobState
        Where the job is in its life: ``queued``, ``running``, ``succeeded``,
        ``partial`` (part of its units failed), ``failed``, ``interrupted`` or
        ``cancelled``.
    actor : str
        Who asked for it (``Principal.id``; ``local`` in local mode).
    actor_kind : {"local_owner", "user", "agent", "scheduler"}
        How: the owner, a person, an agent acting for ``actor``, or the
        scan scheduler.
    session : str or None
        Label of the session it was asked in; ``None`` at the terminal and
        for the scheduler.
    store : str or None
        Configured id of the store it works on; ``None`` for a kind working
        on no store (``preview``, ``own_scan``, ``snapshot``,
        ``availability``).
    params : dict
        Its parameters (``scan``: ``mode``, ``segment``; ``link_check``:
        ``slot``; ``preview``: ``refs``, their ``contents`` and ``force``,
        with the refs of the requests that joined it; ``own_scan``: optional
        ``project``; ``snapshot``: ``project``, ``file_id``, ``note``;
        ``availability``: ``area_id``, ``producer``, ``product``, ``force``;
        ``check``: ``producer``, ``calls`` (each ``command``, ``options``);
        ``download``: those and ``plan_job``).
    created_at, started_at, finished_at : datetime or None
        When it was submitted, started and finished (UTC).
    progress : dict or None
        Data of its last ``progress`` event (``current``, ``total``…).
    result : dict or None
        Summary of a job that succeeded or ended ``partial``.
    error : JobError or None
        Why a job did not succeed (a registry code and the reason).
    """

    id: str
    kind: JobKind
    state: JobState
    actor: str
    actor_kind: PrincipalKind
    session: str | None
    store: str | None
    params: JsonObject
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: JsonObject | None = None
    result: JsonObject | None = None
    error: JobError | None = None


@dataclass(frozen=True, slots=True)
class JobEvent:
    """A job event, as kept in the index and sent over SSE.

    ``seq`` numbers a job's events from 1 (the SSE ``id``; resume after it
    with ``JobSupervisor.events``). ``type`` is ``progress``, ``notice`` or
    ``state``; a ``state`` event has ``data["state"]`` and, at the end,
    ``result`` (succeeded) or ``error`` (``code``, ``detail``, maybe ``hint``,
    and ``details`` with the ``reason``: ``JobError.to_json``).
    """

    job_id: str
    seq: int
    type: EventType
    data: JsonObject
    at: datetime


@dataclass(frozen=True, slots=True)
class JobPage:
    """Jobs, newest first; ``next_cursor`` is ``None`` on the last page."""

    items: tuple[JobRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class LogTail:
    """The end of a job's log (``JobSupervisor.log``).

    Attributes
    ----------
    text : str
        The log read as UTF-8 (a byte that is none is replaced): all of it,
        or its last ``LOG_TAIL_BYTES`` from the first line that starts in
        them.
    size_bytes : int
        Size of the whole log when it was read; it grows while the job runs.
    truncated : bool
        Whether ``text`` leaves the start of the log out.
    """

    text: str
    size_bytes: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class ScanHistory:
    """When a store was scanned, for the scheduler.

    ``finished_at`` is the end of the store's last scan whatever its outcome,
    ``full_at`` the end of its last successful full scan of the whole store
    and ``busy`` whether a job writing its index waits or runs.
    """

    finished_at: datetime | None = None
    full_at: datetime | None = None
    busy: bool = False


type JobListener = Callable[[JobEvent], None]


@dataclass(frozen=True, slots=True)
class JobConflict:
    """Active jobs in the way of a new one: the same ``domain`` and key.

    Attributes
    ----------
    domain : str
        Kinds whose rules name the same domain refuse each other's jobs
        (``index``: ``scan`` and ``footprints`` write a store's index).
    key : Callable[[str or None, dict], object]
        Key of a job in the domain from its store and parameters (``index``:
        the store); the kinds of a domain share it.
    message : str
        Catalog key of the ``JobConflictError`` message, rendered with the
        new job's ``store`` and the active job's ``job`` (id), ``kind`` and
        ``state``.
    """

    domain: str
    key: Callable[[str | None, JsonObject], object]
    message: str


@dataclass(frozen=True, slots=True)
class JobJoin:
    """How a new job joins an active job of its kind and store.

    Attributes
    ----------
    merge : Callable[[dict, dict], dict or None]
        ``merge(active, new)`` returns the active job's parameters with the
        new job's added, or ``None`` when the new job cannot join it.
    states : tuple of {"queued", "running"}
        States of the jobs it may join; a running worker keeps the
        parameters it started with.
    """

    merge: Callable[[JsonObject, JsonObject], JsonObject | None]
    states: tuple[JobState, ...]


@dataclass(frozen=True, slots=True)
class JobOverlap:
    """Active jobs a new one repeats: a warning, not a refusal (SPEC 5.6).

    Attributes
    ----------
    keys : Callable[[str or None, dict], frozenset]
        ``keys(store, params)``: the parts of a job's work; a job of the kind
        sharing one with the new job does some of the same work, and the
        producer writes each version once, so the later one mostly finds
        what the earlier wrote.
    message : str
        Catalog key of the notice, with ``job`` and ``state`` of the oldest
        such job.
    """

    keys: Callable[[str | None, JsonObject], frozenset[object]]
    message: str


@dataclass(frozen=True, slots=True)
class JobRule:
    """How the supervisor treats the jobs of one kind (``JOB_RULES``).

    Attributes
    ----------
    store : bool
        Whether a job works on a configured store (``submit`` requires
        ``store``) or on none (``submit`` refuses one).
    network : bool, default False
        Whether it needs the network: refused in offline mode, and at most
        ``max_network_jobs`` such jobs run at once.
    exclusive : bool, default False
        Whether at most one job of the kind runs at once in a supervisor;
        the next ones wait in the queue, oldest first (each takes one of
        ``max_jobs`` when it runs).
    conflict : JobConflict or None, default None
        Active jobs that refuse a new one (``JobConflictError``).
    join : JobJoin or None, default None
        Active jobs a new one joins instead of being recorded.
    overlap : JobOverlap or None, default None
        Active jobs that the new one starts with a warning notice about.
    """

    store: bool
    network: bool = False
    exclusive: bool = False
    conflict: JobConflict | None = None
    join: JobJoin | None = None
    overlap: JobOverlap | None = None


def _store_key(store: str | None, params: JsonObject) -> object:
    """Return the key of a job writing a store's index: the store."""
    return store


def _snapshot_key(store: str | None, params: JsonObject) -> object:
    """Return the key of a ``snapshot`` job: its project and file."""
    return (params["project"], params["file_id"])


def _call_keys(store: str | None, params: JsonObject) -> frozenset[object]:
    """Return the keys of a job of a producer's calls: its store with each call."""
    return frozenset(
        (
            store,
            params["producer"],
            call["command"],
            json.dumps(call["options"], sort_keys=True, ensure_ascii=False),
        )
        for call in params["calls"]
    )


def _project_key(store: str | None, params: JsonObject) -> object:
    """Return the key of a job of a project's manifest: the project."""
    return params["project"]


def _join_preview(active: JsonObject, new: JsonObject) -> JsonObject | None:
    """Add a ``preview`` request's refs to an active build of all its contents.

    The build must hold every content of the request, and build past the
    auto-build limits (``force``) when the request does. A ref it holds with
    another content, or more than ``MAX_PREVIEW_REFS`` refs together, keep
    the request apart.
    """
    if new["force"] and not active["force"]:
        return None
    if not set(new["contents"]) <= set(active["contents"]):
        return None
    contents = dict(zip(active["refs"], active["contents"], strict=True))
    for ref, content in zip(new["refs"], new["contents"], strict=True):
        if contents.setdefault(ref, content) != content:
            return None
    if len(contents) > MAX_PREVIEW_REFS:
        return None
    return {
        "refs": list(contents),
        "contents": list(contents.values()),
        "force": active["force"],
    }


def _join_own_scan(active: JsonObject, new: JsonObject) -> JsonObject | None:
    """Join an ``own_scan`` request to a waiting run that covers its folder.

    A waiting run of every project (no ``project``) takes any request; a
    waiting run of one project takes a request of the same project. The
    run starts after the request, so a change made before it is found.
    """
    if "project" not in active or active == new:
        return active
    return None


def _join_availability(active: JsonObject, new: JsonObject) -> JsonObject | None:
    """Answer a check of availability with an active check of the same question.

    The same area, producer and product; a check that asks the source again
    (``force``) does not wait for one that may answer from the cache.
    """
    same = all(active[key] == new[key] for key in ("area_id", "producer", "product"))
    if not same or (new["force"] and not active["force"]):
        return None
    return active


def _join_warm(active: JsonObject, new: JsonObject) -> JsonObject | None:
    """Join a warm-up of previews to a waiting one of the same filters.

    It selects what to prepare when it starts, so a request finds in it
    whatever the index holds until then.
    """
    return active if active == new else None


# Jobs writing a store's index: one of them per store at a time.
_INDEX_CONFLICT = JobConflict("index", _store_key, "job.conflict")
_PREVIEW_JOIN = JobJoin(_join_preview, ACTIVE_STATES)
# Only a waiting run takes a request: a running one may have passed the change.
_OWN_SCAN_JOIN = JobJoin(_join_own_scan, ("queued",))
# A running check answers the same question as a waiting one.
_AVAILABILITY_JOIN = JobJoin(_join_availability, ACTIVE_STATES)
# Only a waiting warm-up takes a request: a running one has chosen its files.
_WARM_JOIN = JobJoin(_join_warm, ("queued",))
# One snapshot of a file at a time; those of other files run side by side.
_SNAPSHOT_CONFLICT = JobConflict("snapshot", _snapshot_key, "job.conflict_snapshot")
# One job of a project at a time (SPEC 5.6): its producer writes the manifest
# under a lock that a second one would wait for.
_PROJECT_CONFLICT = JobConflict("project", _project_key, "job.conflict_project")
# A download of a call an active download of the store runs (SPEC 5.6).
_DOWNLOAD_OVERLAP = JobOverlap(_call_keys, "job.overlapping")
# The rule of each kind, one line per kind of ``JobKind``.
JOB_RULES: Mapping[JobKind, JobRule] = {
    "scan": JobRule(store=True, conflict=_INDEX_CONFLICT),
    "footprints": JobRule(store=True, network=True, conflict=_INDEX_CONFLICT),
    "link_check": JobRule(store=True),
    "preview": JobRule(store=False, exclusive=True, join=_PREVIEW_JOIN),
    "own_scan": JobRule(store=False, exclusive=True, join=_OWN_SCAN_JOIN),
    "snapshot": JobRule(store=False, conflict=_SNAPSHOT_CONFLICT),
    "availability": JobRule(store=False, network=True, join=_AVAILABILITY_JOIN),
    "check": JobRule(store=True, network=True),
    "download": JobRule(store=True, network=True, overlap=_DOWNLOAD_OVERLAP),
    "project_download": JobRule(store=False, network=True, conflict=_PROJECT_CONFLICT),
    "project_repin": JobRule(store=False, network=True, conflict=_PROJECT_CONFLICT),
    "project_check": JobRule(store=False, network=True, conflict=_PROJECT_CONFLICT),
    "project_verify": JobRule(store=False, conflict=_PROJECT_CONFLICT),
    "preview_warm": JobRule(store=False, exclusive=True, join=_WARM_JOIN),
}


def _domain_kinds(domain: str) -> tuple[JobKind, ...]:
    """Return the kinds whose jobs conflict in ``domain``."""
    return tuple(
        kind
        for kind, rule in JOB_RULES.items()
        if rule.conflict is not None and rule.conflict.domain == domain
    )


# Kinds writing a store's index: the scheduler leaves a store with one alone.
_INDEX_KINDS = _domain_kinds(_INDEX_CONFLICT.domain)


@dataclass(slots=True)
class _Waiting:
    job_id: str
    kind: JobKind
    store: str | None


@dataclass(slots=True)
class _Run:
    """A running worker and what it reported so far."""

    job_id: str
    kind: JobKind
    store: str | None
    process: subprocess.Popen[bytes]
    log: IO[bytes]
    seq: int
    result: JsonObject | None = None
    partial: bool = False
    error: JsonObject | None = None
    cancel: bool = False
    stop: bool = False
    reader: threading.Thread | None = None
    killer: threading.Timer | None = None


def default_max_jobs() -> int:
    """Workers running at once: half the processors, at least two."""
    return max(2, (os.cpu_count() or 2) // 2)


class JobSupervisor:
    """Start, follow and record background jobs.

    Parameters
    ----------
    paths : AppPaths
        The local index and the jobs directory (logs, owner locks); workers
        get the index and the cache, preview and scratch directories.
    settings : SettingsService
        Settings in effect: stores, offline mode. The index's stores follow
        them (``IndexWriter.sync_stores``) before every job starts and after
        every change; jobs of a removed store are cancelled.
    worker_command : Sequence[str], optional
        Command of a worker process, ``python -m archiwista.jobs.worker`` by
        default.
    max_jobs : int or None, optional
        Workers running at once; half the processors (at least two) by
        default.
    max_network_jobs : int, default 2
        Network jobs running at once.
    stop_timeout_s : float, default 30.0
        Seconds an interrupted worker has before it is killed.

    Notes
    -----
    ``start`` must come first and ``close`` last (or use ``with``). All
    methods are thread-safe. Listeners run in a supervisor thread while it
    holds its lock, in the order of each job's events: they must return
    quickly (e.g. hand the event to an event loop) and must not wait for a
    job.
    """

    def __init__(
        self,
        paths: AppPaths,
        settings: SettingsService,
        *,
        worker_command: Sequence[str] = WORKER_COMMAND,
        max_jobs: int | None = None,
        max_network_jobs: int = MAX_NETWORK_JOBS,
        stop_timeout_s: float = STOP_TIMEOUT_S,
    ) -> None:
        self._paths = paths
        self._settings = settings
        self._command = tuple(worker_command)
        self._max_jobs = default_max_jobs() if max_jobs is None else max_jobs
        self._max_network_jobs = max_network_jobs
        self._stop_timeout_s = stop_timeout_s
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._queue: deque[_Waiting] = deque()
        self._running: dict[str, _Run] = {}
        self._listeners: list[tuple[str | None, JobListener]] = []
        self._db: sqlite3.Connection | None = None
        self._local = threading.local()
        self._readers: list[sqlite3.Connection] = []
        self._owner: Path | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._synced: AppSettings | None = None
        self._phase: Literal["new", "open", "closing", "closed"] = "new"
        self._stopping = threading.Event()
        self._watcher: threading.Thread | None = None

    def __enter__(self) -> Self:
        """Start the supervisor for a ``with`` block."""
        self.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the supervisor."""
        self.close()

    def start(self) -> int:
        """Claim this process's jobs, follow the settings and recover jobs.

        Old jobs and logs are pruned first (``prune``); then a thread looks
        for the cancel requests of this supervisor's jobs (``cancel``).

        Returns
        -------
        int
            Jobs found without a live supervising process, now
            ``interrupted``.
        """
        with self._lock:
            if self._phase != "new":
                raise RuntimeError("a supervisor starts once")
            initialize(self._paths.index_file)
            jobs_dir = private_directory(self._paths.jobs_dir)
            self._owner = _hold_owner_lock(jobs_dir)
            self._db = _connect(self._paths.index_file)
            self._phase = "open"
            self.prune()
            self._sync(self._settings.get())
            self._unsubscribe = self._settings.subscribe(self._settings_changed)
            self._watcher = threading.Thread(
                target=self._watch_cancels, name="archiwista-job-cancels", daemon=True
            )
            self._watcher.start()
        return self.recover()

    def prune(self, now: datetime | None = None) -> int:
        """Forget old jobs with their events and logs.

        Routine scans, incremental scans the scheduler started that
        succeeded without changing the index, go after 48 hours, except the
        newest of each store. Other finished jobs and logs go after 90 days
        (the last finished job of each store and kind stays), and the oldest
        logs beyond 1 GB. The scheduler calls it every hour. Cancel requests
        of jobs that are not active go too.

        Parameters
        ----------
        now : datetime or None, optional
            The time of the pruning; the current time when omitted.

        Returns
        -------
        int
            Routine scans forgotten.
        """
        moment = now or _now()
        with self._lock:
            db = self._open_db()
            routine = _prune_routine_scans(db, self._paths.jobs_dir, now=moment)
            routine += _prune_routine_own_scans(db, self._paths.jobs_dir, now=moment)
            _prune_logs(self._paths.jobs_dir, now=moment)
            _prune_jobs(db, now=moment)
            _prune_cancel_requests(db, self._paths.jobs_dir)
        return routine

    def close(self) -> None:
        """Stop: waiting jobs and running workers end ``interrupted``.

        Running workers are interrupted and waited for (killed after
        ``stop_timeout_s``), so a scan abandons its pass.
        """
        with self._lock:
            if self._phase == "new":
                self._phase = "closed"
            if self._phase != "open":
                return
            self._phase = "closing"
            self._stopping.set()
            if self._unsubscribe is not None:
                self._unsubscribe()
            stopped = _interrupted(message("job.interrupted_stop"))
            while self._queue:
                self._end_waiting(self._queue.popleft(), "interrupted", stopped)
            runs = tuple(self._running.values())
            for run in runs:
                run.stop = True
                self._interrupt(run)
        if self._watcher is not None:
            self._watcher.join()
        for run in runs:
            if run.reader is not None:
                run.reader.join(self._stop_timeout_s + 10)
        with self._lock:
            self._phase = "closed"
            for connection in (self._db, *self._readers):
                if connection is not None:
                    connection.close()
            self._db = None
            self._readers.clear()
            if self._owner is not None:
                _release_owner_lock(self._owner)
                self._owner = None

    def submit(
        self,
        kind: str,
        *,
        store: str | None = None,
        params: Mapping[str, object] | None = None,
        actor: Principal,
        admit: Callable[[], None] | None = None,
    ) -> JobRecord:
        """Record a job and start it when there is room, or join an active one.

        Parameters
        ----------
        kind : str
            What to run, one of ``JOB_KINDS``.
        store : str or None, optional
            Configured store id: required by a kind working on a store
            (``scan``, ``footprints``, ``link_check``, ``check``,
            ``download``), refused by one working on none (``preview``,
            ``own_scan``, ``snapshot``, ``availability``, ``project_*``,
            ``preview_warm``).
        params : Mapping or None, optional
            ``scan``: ``mode`` (``incremental``, the default, or ``full``)
            and optional ``segment``; ``link_check``: ``slot`` (its path);
            ``footprints``: none; ``preview``: ``refs`` (1 to 500 non-empty
            strings), ``contents`` (the content key of each ref, SHA-256 in
            lower-case hex) and ``force`` (build past the auto-build limits,
            ``False`` by default); a ref given twice with the same content
            counts once; ``own_scan``: optional ``project`` (its key);
            ``snapshot``: ``project`` (its key), ``file_id`` (16 lower-case
            hex characters) and ``note`` (at most 2000 characters, ``""`` by
            default); ``availability``: ``area_id``, ``producer`` and
            ``product`` (non-empty texts) and ``force`` (ask the source
            again, ``False`` by default); ``check``: ``producer`` (a
            non-empty text) and ``calls`` (1 to ``MAX_JOB_CALLS`` calls, each
            a JSON object of ``command``, a non-empty text, and ``options``,
            a JSON object, ``{}`` by default); ``download``: those of
            ``check`` and ``plan_job`` (the ``check`` job whose kept plans
            the run runs, ``None`` by default); ``project_download``,
            ``project_check``, ``project_verify``: ``project`` (its key),
            ``tasks`` (a list of task names, ``None`` for every task, the
            default) and, when given, ``producer`` (the manifest whose tasks
            run; left out: the project's only one); ``project_repin``: those
            with one task; ``preview_warm``: ``store``, ``product``, ``segment``,
            ``project``, ``area_id`` and ``since`` (``WARM_FILTERS``: each a
            non-empty text or ``None``, the default; ``since`` an ISO 8601
            time with its offset).
        actor : Principal
            Who asks; the job keeps its id, kind and session label.
        admit : Callable[[], None] or None, optional
            Called under the supervisor's lock when the request would become
            a new job (nothing in its way and no active job taking it): it
            refuses the job by raising, and nothing is recorded then (the
            limits of a person's scans, ``archiwista.services.owndata``).

        Returns
        -------
        JobRecord
            The job, ``queued`` or already ``running``. A kind that joins
            (``preview``, ``availability``, ``preview_warm``) returns the
            oldest active job of the kind that takes the request instead:
            that job's ``params`` gain the request's (a running worker keeps
            those it started with), and no job is recorded. A job of a kind
            that overlaps (``download``) gets a warning notice
            ``overlapping_job`` naming the oldest active job it repeats a
            call of, ``job`` its id.

        Raises
        ------
        NotFoundError
            The store is not configured.
        OfflineModeError
            A network job while offline mode is on; nothing is recorded.
        JobConflictError
            Another job writes the store's index (``scan``, ``footprints``),
            or the project has an active job (``project_*``); it names that
            job.
        ValueError
            An unknown kind, a store missing or given against the kind's
            rule, or invalid parameters.
        Exception
            Whatever ``admit`` raises.
        """
        job_kind = _job_kind(kind)
        rule = JOB_RULES[job_kind]
        if rule.store and store is None:
            raise ValueError(f"a {job_kind} job needs a store")
        if not rule.store and store is not None:
            raise ValueError(f"a {job_kind} job takes no store, got {store!r}")
        settings = self._settings.get()
        if store is not None and settings.store(store) is None:
            raise NotFoundError(message("job.store_unknown", store=store))
        values = _job_params(job_kind, params or {})
        if rule.network and settings.offline:
            raise OfflineModeError(message("job.offline_mode"))
        job_id = secrets.token_hex(8)
        now = _now()
        with self._lock:
            db = self._open_db()
            joined: str | None = None
            events: list[JobEvent] = []
            # Claimed first: a recovery meeting the new row sees a live owner.
            _set_active(job_id, active=True)
            try:
                with _transaction(db):
                    conflict, stale = self._conflict(db, job_kind, store, values, now)
                    events.extend(stale)
                    if conflict is None:
                        joined, stale = self._join(db, job_kind, store, values, now)
                        events.extend(stale)
                    if conflict is None and joined is None:
                        if admit is not None:
                            admit()
                        db.execute(
                            "INSERT INTO jobs (id, kind, actor, actor_kind, session,"
                            " store, params, state, created_at, pid)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                            (
                                job_id,
                                job_kind,
                                actor.id,
                                actor.kind,
                                actor.session,
                                store,
                                _json(values),
                                _iso(now),
                                os.getpid(),
                            ),
                        )
                        events.append(
                            _insert_event(
                                db, job_id, 1, "state", {"state": "queued"}, now
                            )
                        )
                        overlap = self._overlap(db, job_kind, store, values, job_id)
                        if overlap is not None:
                            events.append(
                                _insert_event(db, job_id, 2, "notice", overlap, now)
                            )
            except BaseException:
                _set_active(job_id, active=False)
                raise
            for event in events:
                self._publish(event)
            if conflict is not None or joined is not None:
                _set_active(job_id, active=False)
            if conflict is not None:
                raise conflict
            if joined is None:
                self._queue.append(_Waiting(job_id, job_kind, store))
                self._dispatch()
        return self._record(joined or job_id)

    def cancel(self, job_id: str) -> JobRecord:
        """Cancel a job.

        A job waiting under this supervisor ends at once; a running worker of
        this supervisor is interrupted (and killed after ``stop_timeout_s``)
        and its job ends ``cancelled`` when the worker is gone. A job that
        another live supervisor waits for or runs, of this process or of
        another one, gets a cancel request (``<jobs>/<id>.cancel``) that its
        supervisor carries out the same way within ``CANCEL_POLL_S``. A job
        whose supervising process is gone ends ``interrupted`` first
        (``recover``); a finished job is returned unchanged.

        Returns
        -------
        JobRecord
            The job right after the request: ``cancelled`` when it waited
            here, otherwise as it is until its worker or supervisor stops it.

        Raises
        ------
        NotFoundError
            No job has this id.
        """
        with self._lock:
            if self._owns(job_id):
                self._cancel_own(job_id)
                return self._record(job_id)
        self.recover()
        record = self._record(job_id)
        if record.state not in ACTIVE_STATES:
            return record
        request = _cancel_path(self._paths.jobs_dir, job_id)
        request.touch()
        current = self._record(job_id)
        if current.state not in ACTIVE_STATES:  # it ended meanwhile
            request.unlink(missing_ok=True)
        return current

    def log(self, job_id: str) -> LogTail | None:
        """Return the end of a job's log: its worker's standard error.

        Returns
        -------
        LogTail or None
            The log, its last ``LOG_TAIL_BYTES`` at most; ``None`` when the
            job has none: it never started a worker, or its log was pruned.

        Raises
        ------
        NotFoundError
            No job has this id.
        """
        self._record(job_id)
        return _read_log(_log_path(self._paths.jobs_dir, job_id))

    def wait(self, job_id: str, timeout: float | None = None) -> JobRecord:
        """Wait until a job of this supervisor ends (or ``timeout`` passes).

        Raises
        ------
        NotFoundError
            No job has this id.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._changed:
            while self._owns(job_id):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._changed.wait(remaining)
        return self._record(job_id)

    def supervises(self, job_id: str) -> bool:
        """Whether a job waits or runs under this supervisor (``wait`` follows it).

        ``False`` for a finished job and for one another supervisor runs,
        e.g. a server's job a ``preview`` request joined: such a job is
        followed through ``get`` and ``events``.
        """
        with self._lock:
            return self._owns(job_id)

    def recover(self) -> int:
        """Mark jobs whose supervising process is gone as ``interrupted``.

        Returns
        -------
        int
            Jobs marked.
        """
        with self._lock:
            db = self._open_db()
            now = _now()
            with _transaction(db):
                rows = db.execute(
                    f"SELECT id, pid FROM jobs WHERE state IN {_ACTIVE_SQL}"
                ).fetchall()
                events = [
                    self._mark_stale(db, row["id"], now)
                    for row in rows
                    if not self._owner_alive(row["id"], row["pid"])
                ]
            for event in events:
                self._publish(event)
        return len(events)

    def subscribe(
        self, listener: JobListener, *, job_id: str | None = None
    ) -> Callable[[], None]:
        """Call ``listener(event)`` for each new event of one job or of all.

        Returns
        -------
        Callable[[], None]
            Ends the subscription.
        """
        entry = (job_id, listener)
        with self._lock:
            self._listeners.append(entry)

        def unsubscribe() -> None:
            with self._lock:
                if entry in self._listeners:
                    self._listeners.remove(entry)

        return unsubscribe

    def get(
        self, job_id: str, *, visible: ProjectVisibility = ALL_PROJECTS
    ) -> JobRecord | None:
        """Return a job, or ``None`` when no job has this id.

        Parameters
        ----------
        job_id : str
            Job id.
        visible : ProjectVisibility, default ALL_PROJECTS
            Projects the principal sees: a job it does not see is ``None``
            too, and a ``preview`` job shows only the refs (with their
            contents) and failures of visible projects; counts stay whole.
        """
        with self._reading() as connection:
            row = connection.execute(
                f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            seen = _seen_projects(connection, visible)
            record = _job_record(connection, row)
        if not _Scope.of(record.store, record.params).seen_by(seen):
            return None
        return _redacted(record, seen)

    def sees_whole(self, job_id: str, *, visible: ProjectVisibility) -> bool:
        """Whether one seeing the projects ``visible`` sees all of a job's data.

        A job of a store, of versions or of one project is seen whole by
        whoever sees it; a ``preview`` job only when every project of its
        refs is seen (``get`` shows it without the others). ``False`` for an
        unknown job.
        """
        with self._reading() as connection:
            row = connection.execute(
                "SELECT store, params FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return False
            seen = _seen_projects(connection, visible)
        scope = _Scope.of(row["store"], json.loads(row["params"]))
        return seen is None or scope.projects <= seen

    def events(
        self,
        job_id: str,
        *,
        after: int = 0,
        visible: ProjectVisibility = ALL_PROJECTS,
    ) -> tuple[JobEvent, ...]:
        """Return a job's events after ``seq`` ``after`` (SSE ``Last-Event-ID``).

        ``visible`` (every project by default) are the projects the principal
        sees: a job it does not see has no events, and the final ``state`` of
        a ``preview`` job lists the failures of visible refs only (``get``).
        """
        with self._reading() as connection:
            seen = _seen_projects(connection, visible)
            # Projects whose refs a ``preview`` job's failures keep.
            redact: frozenset[str] | None = None
            if seen is not None:
                job = connection.execute(
                    "SELECT kind, store, params FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if job is None:
                    return ()
                scope = _Scope.of(job["store"], json.loads(job["params"]))
                if not scope.seen_by(seen):
                    return ()
                if job["kind"] == "preview":
                    redact = seen
            rows = connection.execute(
                "SELECT seq, type, data, at FROM job_events"
                " WHERE job_id = ? AND seq > ? ORDER BY seq",
                (job_id, after),
            ).fetchall()
        events = tuple(
            JobEvent(
                job_id=job_id,
                seq=int(row["seq"]),
                type=row["type"],
                data=_event_data(row["type"], row["data"]),
                at=datetime.fromisoformat(row["at"]),
            )
            for row in rows
        )
        if redact is None:
            return events
        return tuple(_redacted_event(event, redact) for event in events)

    def scan_history(self, store: str) -> ScanHistory:
        """Return when a store was last scanned and whether it is busy."""
        with self._reading() as connection:
            finished = connection.execute(
                "SELECT max(coalesce(finished_at, created_at)) FROM jobs"
                f" WHERE store = ? AND kind = 'scan' AND state IN {_FINISHED_SQL}",
                (store,),
            ).fetchone()[0]
            full = connection.execute(
                "SELECT max(finished_at) FROM jobs WHERE store = ? AND kind = 'scan'"
                " AND state = 'succeeded' AND json_extract(params, '$.mode') = 'full'"
                " AND json_extract(params, '$.segment') IS NULL",
                (store,),
            ).fetchone()[0]
            busy = connection.execute(
                "SELECT 1 FROM jobs WHERE store = ?"
                f" AND kind IN ({_placeholders(_INDEX_KINDS)})"
                f" AND state IN {_ACTIVE_SQL} LIMIT 1",
                (store, *_INDEX_KINDS),
            ).fetchone()
        return ScanHistory(
            finished_at=_datetime(finished),
            full_at=_datetime(full),
            busy=busy is not None,
        )

    def own_scan_history(self) -> ScanHistory:
        """Return when an ``own_scan`` of every project last ended and if one is on.

        ``finished_at`` is the end of the last run of every project, whatever
        its outcome; ``busy``: such a run waits or runs (the scheduler then
        submits none).
        """
        with self._reading() as connection:
            finished = connection.execute(
                "SELECT max(coalesce(finished_at, created_at)) FROM jobs"
                f" WHERE kind = 'own_scan' AND state IN {_FINISHED_SQL}"
                " AND json_extract(params, '$.project') IS NULL"
            ).fetchone()[0]
            busy = connection.execute(
                f"SELECT 1 FROM jobs WHERE kind = 'own_scan' AND state IN {_ACTIVE_SQL}"
                " AND json_extract(params, '$.project') IS NULL LIMIT 1"
            ).fetchone()
        return ScanHistory(finished_at=_datetime(finished), busy=busy is not None)

    def active_of(self, actor: str, kind: str) -> JobRecord | None:
        """Return the oldest job of ``kind`` that ``actor`` asked for, still active.

        ``actor`` is a principal's id, so a person's agents count as the
        person; ``None`` when no such job is active.
        """
        with self._reading() as connection:
            row = connection.execute(
                f"SELECT {_JOB_COLUMNS} FROM jobs WHERE kind = ? AND actor = ?"
                f" AND state IN {_ACTIVE_SQL} ORDER BY created_at, id LIMIT 1",
                (kind, actor),
            ).fetchone()
            return None if row is None else _job_record(connection, row)

    def last_started(self, kind: str, project: str) -> datetime | None:
        """Return when the newest job of ``kind`` of one project was asked for.

        A job of the project names it in ``params.project`` (an ``own_scan``
        of every project names none); ``None`` without such a job.
        """
        with self._reading() as connection:
            started = connection.execute(
                "SELECT max(created_at) FROM jobs WHERE kind = ?"
                " AND json_extract(params, '$.project') = ?",
                (kind, project),
            ).fetchone()[0]
        return _datetime(started)

    def list(
        self,
        *,
        kind: str | None = None,
        store: str | None = None,
        state: str | None = None,
        project: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
        visible: ProjectVisibility = ALL_PROJECTS,
    ) -> JobPage:
        """Return jobs newest first (``GET /jobs``).

        Parameters
        ----------
        kind, store, state : str or None, optional
            Only jobs of this kind, store or state.
        project : str or None, optional
            Only jobs with data of this project (its key): its ``own_scan``,
            its snapshots, previews of its files.
        limit : int, default 50
            Page size, 1 to 200.
        cursor : str or None, optional
            ``next_cursor`` of the previous page of the same filters.
        visible : ProjectVisibility, default ALL_PROJECTS
            Projects the principal sees: only the jobs it sees, shown as
            ``get`` shows them. The query leaves the others out, so a page
            keeps its size.

        Raises
        ------
        IndexQueryError
            Limit out of range, or a cursor of other filters.
        """
        if not 1 <= limit <= MAX_PAGE_LIMIT:
            raise IndexQueryError(message("index.invalid_limit", limit=MAX_PAGE_LIMIT))
        fingerprint = hashlib.sha256(
            json.dumps([kind, store, state, project]).encode()
        ).hexdigest()[:16]
        after = _decode_cursor(cursor, fingerprint)
        conditions: list[str] = []
        values: list[object] = []
        for column, value in (("kind", kind), ("store", store), ("state", state)):
            if value is not None:
                conditions.append(f"{column} = ?")
                values.append(value)
        if after is not None:
            conditions.append("(created_at, id) < (?, ?)")
            values.extend(after)
        with self._reading() as connection:
            seen = _seen_projects(connection, visible)
            if seen is not None or project is not None:
                # The scope rule of ``get`` filters in the query, so a page
                # keeps its size; registered on this thread's connection, the
                # function is this call's alone.
                connection.create_function("job_listed", 2, _listed(seen, project))
                conditions.append("job_listed(store, params)")
            where = " AND ".join(conditions) or "1"
            rows = connection.execute(
                f"SELECT {_JOB_COLUMNS} FROM jobs WHERE {where}"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*values, limit + 1),
            ).fetchall()
            items = tuple(
                _redacted(_job_record(connection, row), seen) for row in rows[:limit]
            )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = _encode_cursor(fingerprint, [last["created_at"], last["id"]])
        return JobPage(items=items, next_cursor=next_cursor)

    # Internals; methods named ``_…`` that change state run with the lock.

    def _record(self, job_id: str) -> JobRecord:
        record = self.get(job_id)
        if record is None:
            raise NotFoundError(message("job.not_found", job=job_id))
        return record

    def _owns(self, job_id: str) -> bool:
        return job_id in self._running or any(
            item.job_id == job_id for item in self._queue
        )

    def _cancel_own(self, job_id: str) -> None:
        """Cancel a job waiting or running under this supervisor (lock held)."""
        waiting = next((item for item in self._queue if item.job_id == job_id), None)
        if waiting is not None:
            self._queue.remove(waiting)
            error = JobError(CODE_CANCELLED, message("job.cancelled"))
            self._end_waiting(waiting, "cancelled", error)
        run = self._running.get(job_id)
        if run is not None and not run.cancel:
            run.cancel = True
            self._interrupt(run)

    def _watch_cancels(self) -> None:
        """Carry out the cancel requests of this supervisor's jobs (``cancel``)."""
        while not self._stopping.wait(CANCEL_POLL_S):
            with self._lock:
                if self._phase != "open":
                    return
                owned = [item.job_id for item in self._queue]
                owned += [key for key, run in self._running.items() if not run.cancel]
                for job_id in owned:
                    if not _cancel_path(self._paths.jobs_dir, job_id).exists():
                        continue
                    try:
                        self._cancel_own(job_id)
                    except Exception:  # the next look tries again
                        logger.exception("Cancelling job %s failed", job_id)

    def _dispatch(self) -> None:
        """Start waiting jobs, oldest first, while there is room."""
        if self._phase != "open":
            return
        for waiting in tuple(self._queue):
            if not self._room(waiting.kind):
                continue
            self._queue.remove(waiting)
            try:
                self._start(waiting)
            except Exception as error:  # the job must not stay waiting
                logger.exception("Starting job %s failed", waiting.job_id)
                detail = message(
                    "job.internal_error", detail=f"{type(error).__name__}: {error}"
                )
                self._end_waiting(
                    waiting, "failed", JobError(CODE_INTERNAL_ERROR, detail)
                )

    def _room(self, kind: JobKind) -> bool:
        if len(self._running) >= self._max_jobs:
            return False
        rule = JOB_RULES[kind]
        running = [run.kind for run in self._running.values()]
        if rule.exclusive and kind in running:
            return False
        if rule.network:
            network = sum(JOB_RULES[other].network for other in running)
            return network < self._max_network_jobs
        return True

    def _start(self, waiting: _Waiting) -> None:
        """Mark a job running and start its worker with the current settings."""
        settings = self._settings.get()
        if waiting.store is not None and settings.store(waiting.store) is None:
            error = JobError(
                CODE_CANCELLED,
                message("job.store_unknown", store=waiting.store),
            )
            self._end_waiting(waiting, "cancelled", error)
            return
        if JOB_RULES[waiting.kind].network and settings.offline:
            error = JobError.of(OfflineModeError(message("job.offline_mode")))
            self._end_waiting(waiting, "failed", error)
            return
        self._sync(settings)
        db = self._open_db()
        now = _now()
        with _transaction(db):
            row = db.execute(
                "SELECT params, actor, actor_kind, session, (SELECT max(seq)"
                " FROM job_events e WHERE e.job_id = jobs.id) AS seq FROM jobs"
                " WHERE id = ?",
                (waiting.job_id,),
            ).fetchone()
            db.execute(
                "UPDATE jobs SET state = 'running', started_at = ? WHERE id = ?",
                (_iso(now), waiting.job_id),
            )
            seq = int(row["seq"] or 0) + 1
            event = _insert_event(
                db, waiting.job_id, seq, "state", {"state": "running"}, now
            )
        self._publish(event)
        spec = JobSpec(
            job_id=waiting.job_id,
            kind=waiting.kind,
            store=waiting.store,
            params=json.loads(row["params"]),
            actor=row["actor"],
            actor_kind=row["actor_kind"],
            session=row["session"],
            index_path=self._paths.index_file,
            cache_dir=self._paths.cache_dir,
            previews_dir=self._paths.previews_dir,
            work_dir=self._paths.work_dir,
            settings=settings,
        )
        log = _log_path(self._paths.jobs_dir, waiting.job_id).open("ab")
        try:
            process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                cwd=self._paths.jobs_dir,
                **_process_group(),
            )
        except OSError as error:
            log.close()
            failed = JobError(
                CODE_INTERNAL_ERROR,
                message("job.worker_not_started", detail=error),
                {"reason": REASON_WORKER_CRASHED},
            )
            self._end_waiting(waiting, "failed", failed)
            return
        run = _Run(
            job_id=waiting.job_id,
            kind=waiting.kind,
            store=waiting.store,
            process=process,
            log=log,
            seq=seq,
        )
        self._running[run.job_id] = run
        stdin = cast(IO[bytes], process.stdin)
        try:
            # The input stays open: its end tells the worker we are gone.
            stdin.write((encode_spec(spec) + "\n").encode("utf-8"))
            stdin.flush()
        except OSError:  # the worker ended at once; its reader finishes the job
            pass
        run.reader = threading.Thread(
            target=self._read,
            args=(run,),
            name=f"archiwista-job-{run.job_id}",
            daemon=True,
        )
        run.reader.start()

    def _read(self, run: _Run) -> None:
        """Follow a worker's output until it ends, then finish its job."""
        stdout = cast(IO[bytes], run.process.stdout)
        try:
            for raw in stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    message = decode_message(line)
                except ProtocolError as error:
                    logger.warning("Job %s: %s", run.job_id, error)
                    continue
                self._receive(run, message)
        except Exception:  # the job must not stay running
            logger.exception("Following job %s failed", run.job_id)
        finally:
            self._finish(run, run.process.wait())

    def _receive(self, run: _Run, message: WorkerMessage) -> None:
        if message.type == "result" or message.type == "partial":
            run.result = message.data
            run.partial = message.type == "partial"
            return
        if message.type == "error":
            run.error = message.data
            return
        with self._lock:
            db = self._open_db()
            now = _now()
            with _transaction(db):
                event = _insert_event(
                    db, run.job_id, run.seq + 1, message.type, message.data, now
                )
            run.seq += 1
            self._publish(event)

    def _finish(self, run: _Run, status: int) -> None:
        with self._lock:
            state, error = _outcome(
                run, status, _log_path(self._paths.jobs_dir, run.job_id)
            )
            try:
                if run.killer is not None:
                    run.killer.cancel()
                data: JsonObject = {"state": state}
                if run.result is not None and state in SUMMARY_STATES:
                    data["result"] = run.result
                if error is not None:
                    data["error"] = error.to_json()
                db = self._open_db()
                now = _now()
                with _transaction(db):
                    db.execute(
                        "UPDATE jobs SET state = ?, finished_at = ?, summary = ?,"
                        " error = ? WHERE id = ?",
                        (
                            state,
                            _iso(now),
                            _json(run.result) if state in SUMMARY_STATES else None,
                            None if error is None else _json(data["error"]),
                            run.job_id,
                        ),
                    )
                    event = _insert_event(
                        db, run.job_id, run.seq + 1, "state", data, now
                    )
                run.seq += 1
                self._publish(event)
            finally:
                self._running.pop(run.job_id, None)
                _set_active(run.job_id, active=False)
                _drop_cancel_request(self._paths.jobs_dir, run.job_id)
                for stream in (run.process.stdin, run.process.stdout, run.log):
                    if stream is not None:
                        _close_quietly(stream)
                self._changed.notify_all()
                self._dispatch()

    def _end_waiting(self, waiting: _Waiting, state: JobState, error: JobError) -> None:
        """Finish a job that never started."""
        db = self._open_db()
        now = _now()
        with _transaction(db):
            event = _finish_row(db, waiting.job_id, state, error, now)
        _set_active(waiting.job_id, active=False)
        _drop_cancel_request(self._paths.jobs_dir, waiting.job_id)
        self._publish(event)
        self._changed.notify_all()

    def _conflict(
        self,
        db: sqlite3.Connection,
        kind: JobKind,
        store: str | None,
        params: JsonObject,
        now: datetime,
    ) -> tuple[JobConflictError | None, tuple[JobEvent, ...]]:
        """Find the oldest live active job in the way of a new one.

        Looks at the active jobs of the kind's conflict domain with the new
        job's key; those whose supervisor is gone become ``interrupted``.

        Returns
        -------
        tuple
            The error naming the job in the way, or ``None``, and the state
            events of the jobs interrupted.
        """
        rule = JOB_RULES[kind].conflict
        if rule is None:
            return None, ()
        key = rule.key(store, params)
        kinds = _domain_kinds(rule.domain)
        rows = db.execute(
            "SELECT id, kind, state, pid, store, params FROM jobs"
            f" WHERE kind IN ({_placeholders(kinds)}) AND state IN {_ACTIVE_SQL}"
            " ORDER BY created_at",
            kinds,
        ).fetchall()
        busy: sqlite3.Row | None = None
        events: list[JobEvent] = []
        for row in rows:
            if rule.key(row["store"], json.loads(row["params"])) != key:
                continue
            if not self._owner_alive(row["id"], row["pid"]):
                events.append(self._mark_stale(db, row["id"], now))
            elif busy is None:
                busy = row
        if busy is None:
            return None, tuple(events)
        text = message(
            rule.message,
            store=store,
            job=busy["id"],
            kind=label("job.kind", busy["kind"]),
            state=label("job.state", busy["state"]),
        )
        error = JobConflictError(
            text,
            job_id=busy["id"],
            kind=busy["kind"],
            state=busy["state"],
        )
        return error, tuple(events)

    def _join(
        self,
        db: sqlite3.Connection,
        kind: JobKind,
        store: str | None,
        params: JsonObject,
        now: datetime,
    ) -> tuple[str | None, tuple[JobEvent, ...]]:
        """Add a new job to the oldest live job of its kind and store taking it.

        Looks at the jobs of the kind and store in the states its rule may
        join, oldest first; those whose supervisor is gone become
        ``interrupted``. The job joined keeps the merged parameters.

        Returns
        -------
        tuple
            The id of the job joined, or ``None``, and the state events of
            the jobs interrupted.
        """
        rule = JOB_RULES[kind].join
        if rule is None:
            return None, ()
        rows = db.execute(
            "SELECT id, pid, params FROM jobs WHERE kind = ? AND store IS ?"
            f" AND state IN ({_placeholders(rule.states)}) ORDER BY created_at, id",
            (kind, store, *rule.states),
        ).fetchall()
        joined: str | None = None
        events: list[JobEvent] = []
        for row in rows:
            if not self._owner_alive(row["id"], row["pid"]):
                events.append(self._mark_stale(db, row["id"], now))
            elif joined is None:
                active = json.loads(row["params"])
                merged = rule.merge(active, params)
                if merged is not None:
                    joined = row["id"]
                    if merged != active:
                        db.execute(
                            "UPDATE jobs SET params = ? WHERE id = ?",
                            (_json(merged), joined),
                        )
        return joined, tuple(events)

    def _overlap(
        self,
        db: sqlite3.Connection,
        kind: JobKind,
        store: str | None,
        params: JsonObject,
        job_id: str,
    ) -> JsonObject | None:
        """Return the notice of a new job about the oldest live job it repeats.

        Looks at the other active jobs of the kind that share an overlap key
        with the new job (``JobOverlap.keys``); a job whose supervisor is
        gone is no one's work any more. ``None`` without such a job.
        """
        rule = JOB_RULES[kind].overlap
        if rule is None:
            return None
        keys = rule.keys(store, params)
        rows = db.execute(
            "SELECT id, state, pid, store, params FROM jobs"
            f" WHERE kind = ? AND id != ? AND state IN {_ACTIVE_SQL}"
            " ORDER BY created_at, id",
            (kind, job_id),
        ).fetchall()
        for row in rows:
            if keys.isdisjoint(rule.keys(row["store"], json.loads(row["params"]))):
                continue
            if self._owner_alive(row["id"], row["pid"]):
                text = message(
                    rule.message, job=row["id"], state=label("job.state", row["state"])
                )
                return {
                    "level": "warning",
                    "code": "overlapping_job",
                    "message": localize(text, STORED_LANG),
                    "job": row["id"],
                }
        return None

    def _mark_stale(
        self, db: sqlite3.Connection, job_id: str, now: datetime
    ) -> JobEvent:
        error = _interrupted(message("job.interrupted_restart"))
        return _finish_row(db, job_id, "interrupted", error, now)

    def _interrupt(self, run: _Run) -> None:
        try:
            run.process.send_signal(_interrupt_signal())
        except OSError:  # already gone
            return
        if run.killer is None:
            run.killer = threading.Timer(
                self._stop_timeout_s, _kill, args=(run.process,)
            )
            run.killer.daemon = True
            run.killer.start()

    def _owner_alive(self, job_id: str, pid: int | None) -> bool:
        """Whether a waiting or running job still has its supervisor."""
        if pid is None:
            return False
        if pid == os.getpid():
            with _PROCESS_LOCK:
                return job_id in _ACTIVE_JOBS
        return _owner_lock_held(self._paths.jobs_dir, pid)

    def _publish(self, event: JobEvent) -> None:
        for job_id, listener in tuple(self._listeners):
            if job_id is not None and job_id != event.job_id:
                continue
            try:
                listener(event)
            except Exception:
                logger.exception("Job listener %r failed", listener)

    def _settings_changed(self, previous: AppSettings, current: AppSettings) -> None:
        """Cancel the jobs of removed stores and follow the new stores."""
        removed = {store.id for store in previous.stores} - {
            store.id for store in current.stores
        }
        with self._lock:
            if self._phase != "open":
                return
            doomed = [item.job_id for item in self._queue if item.store in removed]
            doomed += [
                run.job_id for run in self._running.values() if run.store in removed
            ]
            for job_id in doomed:
                self.cancel(job_id)
            self._sync(current)

    def _sync(self, settings: AppSettings) -> None:
        """Make the index's stores those of the settings (once per change)."""
        if settings is self._synced:
            return
        with IndexWriter(self._paths.index_file) as writer:
            writer.sync_stores({store.id: store.roots() for store in settings.stores})
        self._synced = settings

    def _open_db(self) -> sqlite3.Connection:
        if self._db is None or self._phase == "closed":
            raise RuntimeError("the job supervisor is not running")
        return self._db

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        """Yield this thread's read-only connection, in one snapshot."""
        if self._phase in ("new", "closed"):
            raise RuntimeError("the job supervisor is not running")
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            connection = _connect(self._paths.index_file, readonly=True)
            self._local.connection = connection
            with self._lock:
                self._readers.append(connection)
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.execute("COMMIT")


def _job_kind(kind: str) -> JobKind:
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    return kind


def _job_params(kind: JobKind, params: Mapping[str, object]) -> JsonObject:
    """Check a kind's parameters and return them with defaults."""
    if kind == "scan":
        mode = params.get("mode", "incremental")
        segment = params.get("segment")
        unknown = set(params) - {"mode", "segment"}
        if mode not in SCAN_MODES or not (segment is None or isinstance(segment, str)):
            raise ValueError(f"invalid scan parameters {dict(params)!r}")
        if unknown:
            raise ValueError(f"unknown scan parameters {sorted(unknown)}")
        return {"mode": mode, "segment": segment or None}
    if kind == "preview":
        return _preview_params(params)
    if kind == "snapshot":
        return _snapshot_params(params)
    if kind == "own_scan":
        project = params.get("project")
        if set(params) - {"project"} or not (
            project is None or (isinstance(project, str) and project)
        ):
            raise ValueError(f"invalid own scan parameters {dict(params)!r}")
        return {} if project is None else {"project": project}
    if kind == "link_check":
        slot = params.get("slot")
        if not isinstance(slot, str) or not slot or set(params) != {"slot"}:
            raise ValueError(f"invalid link check parameters {dict(params)!r}")
        return {"slot": slot}
    if kind == "availability":
        return _availability_params(params)
    if kind == "check":
        return _check_params(params)
    if kind == "download":
        return _download_params(params)
    if kind in PROJECT_KINDS:
        return _project_params(kind, params)
    if kind == "preview_warm":
        return _warm_params(params)
    if params:
        raise ValueError(f"{kind} takes no parameters, got {dict(params)!r}")
    return {}


def _availability_params(params: Mapping[str, object]) -> JsonObject:
    """Check an ``availability`` job's area, producer, product and ``force``."""
    names = ("area_id", "producer", "product")
    force = params.get("force", False)
    if (
        set(params) - {*names, "force"}
        or not all(isinstance(params.get(name), str) and params[name] for name in names)
        or not isinstance(force, bool)
    ):
        raise ValueError(f"invalid availability parameters {dict(params)!r}"[:300])
    return {**{name: params[name] for name in names}, "force": force}


def _warm_params(params: Mapping[str, object]) -> JsonObject:
    """Check a ``preview_warm`` job's filters: each a non-empty text or ``None``.

    ``since`` is an ISO 8601 time with its offset. Every filter is kept,
    ``None`` when not given, so equal requests have equal parameters.
    """
    unknown = set(params) - set(WARM_FILTERS)
    if unknown:
        raise ValueError(f"unknown preview_warm parameters {sorted(unknown)}")
    checked: JsonObject = {}
    for name in WARM_FILTERS:
        value = params.get(name)
        if value is not None and not (isinstance(value, str) and value):
            raise ValueError(f"invalid preview_warm {name} {value!r}"[:300])
        checked[name] = value
    since = checked["since"]
    if since is not None and datetime.fromisoformat(since).tzinfo is None:
        raise ValueError(f"preview_warm since {since!r} has no offset")
    return checked


def _project_params(kind: JobKind, params: Mapping[str, object]) -> JsonObject:
    """Check a project job's project, tasks and producer; a repin takes one task.

    ``tasks`` is a list of task names, a name given twice kept once, or
    ``None``, every task of the project. ``producer``, when given, names the
    manifest whose tasks the job runs; left out, the project's only one.
    """
    project = params.get("project")
    tasks = params.get("tasks")
    producer = params.get("producer")
    if (
        set(params) - {"project", "tasks", "producer"}
        or not (isinstance(project, str) and project)
        or ("producer" in params and not (isinstance(producer, str) and producer))
        or not (
            (tasks is None and kind != "project_repin")
            or (
                isinstance(tasks, list | tuple)
                and tasks
                and all(isinstance(name, str) and name for name in tasks)
            )
        )
    ):
        raise ValueError(f"invalid {kind} parameters {dict(params)!r}"[:300])
    names = None if tasks is None else list(dict.fromkeys(cast(list[str], tasks)))
    if kind == "project_repin" and (names is None or len(names) != 1):
        raise ValueError(f"a project_repin job takes one task, got {tasks!r}"[:300])
    checked: JsonObject = {"project": project, "tasks": names}
    if "producer" in params:
        checked["producer"] = producer
    return checked


def _check_params(params: Mapping[str, object]) -> JsonObject:
    """Check a ``check`` job's producer and its calls, in their order.

    Each call is a ``command`` and the call's ``options`` (``{}`` when not
    given); a job has 1 to ``MAX_JOB_CALLS`` of them.
    """
    producer = params.get("producer")
    calls = params.get("calls")
    if (
        set(params) - {"producer", "calls"}
        or not (isinstance(producer, str) and producer)
        or not (isinstance(calls, list | tuple) and 0 < len(calls) <= MAX_JOB_CALLS)
    ):
        raise ValueError(f"invalid check parameters {dict(params)!r}"[:300])
    checked: list[JsonObject] = []
    for call in calls:
        if not isinstance(call, Mapping):
            raise ValueError(f"invalid call {call!r}"[:300])
        command = call.get("command")
        options = call.get("options", {})
        if (
            set(call) - {"command", "options"}
            or not (isinstance(command, str) and command)
            or not isinstance(options, Mapping)
        ):
            raise ValueError(f"invalid call {dict(call)!r}"[:300])
        checked.append({"command": command, "options": dict(options)})
    return {"producer": producer, "calls": checked}


def _download_params(params: Mapping[str, object]) -> JsonObject:
    """Check a ``download`` job's calls (as of ``check``) and its ``plan_job``."""
    plan_job = params.get("plan_job")
    if not (plan_job is None or (isinstance(plan_job, str) and plan_job)):
        raise ValueError(f"invalid download plan job {plan_job!r}"[:300])
    calls = {name: value for name, value in params.items() if name != "plan_job"}
    return {**_check_params(calls), "plan_job": plan_job}


def _snapshot_params(params: Mapping[str, object]) -> JsonObject:
    """Check a ``snapshot`` job's project, file and note."""
    unknown = set(params) - {"project", "file_id", "note"}
    project = params.get("project")
    file_id = params.get("file_id")
    note = params.get("note", "")
    if (
        unknown
        or not (isinstance(project, str) and project)
        or not (isinstance(file_id, str) and _FILE_ID.fullmatch(file_id))
        or not isinstance(note, str)
        or len(note) > MAX_NOTE_CHARS
    ):
        raise ValueError(f"invalid snapshot parameters {dict(params)!r}"[:300])
    return {"project": project, "file_id": file_id, "note": note}


def _preview_params(params: Mapping[str, object]) -> JsonObject:
    """Check a ``preview`` job's refs, the content of each and ``force``.

    A ref given twice with the same content is kept once; with two contents
    it is refused.
    """
    unknown = set(params) - {"refs", "contents", "force"}
    if unknown:
        raise ValueError(f"unknown preview parameters {sorted(unknown)}")
    refs = params.get("refs")
    contents = params.get("contents")
    force = params.get("force", False)
    if not isinstance(refs, list | tuple) or not 1 <= len(refs) <= MAX_PREVIEW_REFS:
        raise ValueError(f"a preview job takes 1 to {MAX_PREVIEW_REFS} refs")
    if not isinstance(contents, list | tuple) or len(contents) != len(refs):
        raise ValueError("a preview job takes the content key of each ref")
    if not isinstance(force, bool):
        raise ValueError(f"invalid preview force {force!r}")
    known: dict[str, str] = {}
    for ref, content in zip(refs, contents, strict=True):
        if not isinstance(ref, str) or not ref:
            raise ValueError(f"invalid preview ref {ref!r}")
        if not isinstance(content, str) or CONTENT_KEY.fullmatch(content) is None:
            raise ValueError(f"invalid content key {content!r} of ref {ref!r}")
        if known.setdefault(ref, content) != content:
            raise ValueError(f"ref {ref!r} given with two contents")
    return {"refs": list(known), "contents": list(known.values()), "force": force}


def _interrupted(detail: str) -> JobError:
    """Return the error of an interrupted job: ``cancelled``, reason ``interrupted``."""
    return JobError(CODE_CANCELLED, detail, {"reason": REASON_INTERRUPTED})


def _outcome(run: _Run, status: int, log: Path) -> tuple[JobState, JobError | None]:
    """Return the final state of a job whose worker ended with ``status``."""
    if run.result is not None:
        return ("partial" if run.partial else "succeeded"), None
    if run.cancel:
        return "cancelled", JobError(CODE_CANCELLED, message("job.cancelled"))
    if run.stop:
        return "interrupted", _interrupted(message("job.interrupted_stop"))
    if run.error is not None:
        return "failed", JobError.from_message(run.error)
    if status in (INTERRUPTED_EXIT, -signal.SIGINT):
        return "interrupted", _interrupted(message("job.interrupted_signal"))
    if status < 0:
        ending = message("job.status_signal", signal=signal.Signals(-status).name)
    else:
        ending = message("job.status_code", code=status)
    detail = message("job.worker_crashed", status=ending, log=log)
    return "failed", JobError(
        CODE_INTERNAL_ERROR, detail, {"reason": REASON_WORKER_CRASHED}
    )


def _finish_row(
    db: sqlite3.Connection,
    job_id: str,
    state: JobState,
    error: JobError,
    now: datetime,
) -> JobEvent:
    """End a job that has no worker (any more) and record its state event."""
    payload = error.to_json()
    db.execute(
        "UPDATE jobs SET state = ?, finished_at = ?, error = ? WHERE id = ?",
        (state, _iso(now), _json(payload), job_id),
    )
    seq = db.execute(
        "SELECT coalesce(max(seq), 0) FROM job_events WHERE job_id = ?", (job_id,)
    ).fetchone()[0]
    return _insert_event(
        db, job_id, int(seq) + 1, "state", {"state": state, "error": payload}, now
    )


def _insert_event(
    db: sqlite3.Connection,
    job_id: str,
    seq: int,
    kind: EventType,
    data: JsonObject,
    at: datetime,
) -> JobEvent:
    db.execute(
        "INSERT INTO job_events (job_id, seq, type, data, at) VALUES (?, ?, ?, ?, ?)",
        (job_id, seq, kind, _json(data), _iso(at)),
    )
    return JobEvent(job_id=job_id, seq=seq, type=kind, data=data, at=at)


def _event_data(kind: str, raw: str) -> JsonObject:
    """Return the data of a stored event; the error of a 0.2.x job is made current."""
    data: JsonObject = json.loads(raw)
    if kind == "state" and isinstance(data.get("error"), dict):
        data["error"] = JobError.from_json(data["error"]).to_json()
    return data


def _job_record(connection: sqlite3.Connection, row: sqlite3.Row) -> JobRecord:
    progress = connection.execute(
        "SELECT data FROM job_events WHERE job_id = ? AND type = 'progress'"
        " ORDER BY seq DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    error = None if row["error"] is None else json.loads(row["error"])
    return JobRecord(
        id=row["id"],
        kind=row["kind"],
        state=row["state"],
        actor=row["actor"],
        actor_kind=row["actor_kind"],
        session=row["session"],
        store=row["store"],
        params=json.loads(row["params"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        started_at=_datetime(row["started_at"]),
        finished_at=_datetime(row["finished_at"]),
        progress=None if progress is None else json.loads(progress["data"]),
        result=None if row["summary"] is None else json.loads(row["summary"]),
        error=None if error is None else JobError.from_json(error),
    )


@dataclass(frozen=True, slots=True)
class _Scope:
    """Whose data a job holds, read from its ``store`` and ``params``.

    Attributes
    ----------
    stores : bool
        It works on a store or on versions (``version:`` refs): data everyone
        sees (A-ADR-029).
    projects : frozenset[str]
        Keys of the projects whose data it holds: ``params.project`` and the
        project of each ``file:`` and ``snapshot:`` ref.
    """

    stores: bool
    projects: frozenset[str]

    @classmethod
    def of(cls, store: str | None, params: Mapping[str, Any]) -> Self:
        """Return the scope of a job of ``store`` with ``params``."""
        refs = params.get("refs")
        refs = refs if isinstance(refs, list) else []
        projects = {key for ref in refs if (key := _ref_project(ref)) is not None}
        named = params.get("project")
        if isinstance(named, str):
            projects.add(named)
        stores = store is not None or any(
            isinstance(ref, str) and ref.startswith(_VERSION_REF) for ref in refs
        )
        return cls(stores, frozenset(projects))

    def seen_by(self, projects: frozenset[str] | None) -> bool:
        """Whether one seeing the projects ``projects`` (``None``: all) sees it.

        A job with a store part, or of no project at all (the ``own_scan``
        of every project), everyone sees; one of projects only, whoever sees
        one of them.
        """
        return (
            projects is None
            or self.stores
            or not self.projects
            or not self.projects.isdisjoint(projects)
        )


def _ref_project(ref: object) -> str | None:
    """Return the project of a ``file:`` or ``snapshot:`` ref, else ``None``.

    Project keys (``[a-z0-9-]+``) hold no ``:``, so the project is the text
    between the first two; ``archiwista.refs`` imports this package, so its
    ``parse_ref`` is out of reach here.
    """
    if not isinstance(ref, str):
        return None
    kind, _, rest = ref.partition(":")
    return rest.partition(":")[0] if kind in _PROJECT_REFS else None


def _ref_seen(ref: object, projects: frozenset[str]) -> bool:
    """Whether a ref is shown: one of no project always, a project's if seen."""
    project = _ref_project(ref)
    return project is None or project in projects


def _seen_projects(
    connection: sqlite3.Connection, visible: ProjectVisibility
) -> frozenset[str] | None:
    """Return the keys of the indexed projects ``visible`` sees; ``None``: all.

    Jobs name projects by key, visibility goes by access key (the index's
    ``projects``); a key the index does not have is seen only by one who sees
    everything.
    """
    if visible.everything:
        return None
    rows = connection.execute("SELECT key, access_key FROM projects").fetchall()
    return frozenset(row["key"] for row in rows if visible.sees(row["access_key"]))


def _listed(
    seen: frozenset[str] | None, project: str | None
) -> Callable[[str | None, str], bool]:
    """Return the SQL function keeping the jobs ``list`` gives (``job_listed``).

    It takes a job's ``store`` and ``params`` (JSON) and keeps a job that one
    seeing the projects ``seen`` (``None``: all) sees and that, given a
    ``project``, has data of that project.
    """

    def listed(store: str | None, params: str) -> bool:
        scope = _Scope.of(store, json.loads(params))
        return scope.seen_by(seen) and (project is None or project in scope.projects)

    return listed


def _redacted(record: JobRecord, seen: frozenset[str] | None) -> JobRecord:
    """Return a seen job as one seeing the projects ``seen`` (``None``: all) sees it.

    A ``preview`` job keeps the refs of visible projects with their contents,
    and their failures; its counts (``built``, ``cached``, progress) stay
    whole (A-ADR-029: counts in aggregate, names of visible ones only). The
    other kinds have one scope and are shown whole.
    """
    if seen is None or record.kind != "preview":
        return record
    params = record.params
    refs, contents = params.get("refs"), params.get("contents")
    if isinstance(refs, list) and isinstance(contents, list):
        kept = [
            (ref, content)
            for ref, content in zip(refs, contents, strict=True)
            if _ref_seen(ref, seen)
        ]
        params = {
            **params,
            "refs": [ref for ref, _ in kept],
            "contents": [content for _, content in kept],
        }
    result = None if record.result is None else _shown_result(record.result, seen)
    return replace(record, params=params, result=result)


def _redacted_event(event: JobEvent, seen: frozenset[str]) -> JobEvent:
    """Return an event of a ``preview`` job as ``_redacted`` shows the job."""
    result = event.data.get("result")
    if event.type != "state" or not isinstance(result, dict):
        return event
    return replace(event, data={**event.data, "result": _shown_result(result, seen)})


def _shown_result(result: JsonObject, seen: frozenset[str]) -> JsonObject:
    """Return a ``preview`` summary listing the failures of visible refs only."""
    failed = result.get("failed")
    if not isinstance(failed, list):
        return result
    shown = [
        entry
        for entry in failed
        if isinstance(entry, dict) and _ref_seen(entry.get("ref"), seen)
    ]
    return {**result, "failed": shown}


@contextmanager
def _transaction(db: sqlite3.Connection) -> Iterator[None]:
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    connection = connect(path, readonly=readonly)
    connection.row_factory = sqlite3.Row
    return connection


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    # Microseconds: jobs of one second still sort by time.
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _datetime(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _placeholders(values: Sequence[object]) -> str:
    """Return one SQL parameter mark per value: ``?, ?, ?``."""
    return ", ".join("?" * len(values))


def _encode_cursor(fingerprint: str, values: Sequence[object]) -> str:
    data = json.dumps([_CURSOR_VERSION, fingerprint, *values])
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None, fingerprint: str) -> tuple[str, str] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise IndexQueryError(message("index.invalid_cursor")) from None
    if (
        not isinstance(data, list)
        or len(data) != 4
        or data[:2] != [_CURSOR_VERSION, fingerprint]
        or not all(isinstance(value, str) for value in data[2:])
    ):
        raise IndexQueryError(message("index.invalid_cursor"))
    return data[2], data[3]


def _log_path(jobs_dir: Path, job_id: str) -> Path:
    return jobs_dir / f"{job_id}.log"


def _read_log(path: Path, max_bytes: int = LOG_TAIL_BYTES) -> LogTail | None:
    """Return the end of a log from the first line starting in it; ``None``: none."""
    try:
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read(size - start)
    except FileNotFoundError:
        return None
    if start:
        _, newline, rest = data.partition(b"\n")
        if newline:
            data = rest
    return LogTail(data.decode("utf-8", "replace"), size, start > 0)


def _cancel_path(jobs_dir: Path, job_id: str) -> Path:
    return jobs_dir / f"{job_id}.cancel"


def _drop_cancel_request(jobs_dir: Path, job_id: str) -> None:
    """Remove the cancel request of a job that ended, if it has one."""
    with suppress(OSError):
        _cancel_path(jobs_dir, job_id).unlink(missing_ok=True)


def _prune_cancel_requests(db: sqlite3.Connection, jobs_dir: Path) -> None:
    """Remove the cancel requests of jobs that are not active (any more)."""
    active = {
        row["id"]
        for row in db.execute(f"SELECT id FROM jobs WHERE state IN {_ACTIVE_SQL}")
    }
    for path in jobs_dir.glob("*.cancel"):
        if path.stem not in active:
            _drop_cancel_request(jobs_dir, path.stem)


def _prune_logs(jobs_dir: Path, *, now: datetime) -> None:
    """Delete job logs older than 90 days, then the oldest beyond 1 GB."""
    logs: list[tuple[float, int, Path]] = []
    for path in jobs_dir.glob("*.log"):
        try:
            stat = path.stat()
        except OSError:
            continue
        logs.append((stat.st_mtime, stat.st_size, path))
    oldest = (now - LOG_MAX_AGE).timestamp()
    kept = 0
    for modified, size, path in sorted(logs, reverse=True):
        if modified < oldest or kept + size > LOG_MAX_BYTES:
            path.unlink(missing_ok=True)
        else:
            kept += size


def _prune_jobs(db: sqlite3.Connection, *, now: datetime) -> None:
    """Forget finished jobs older than their logs, but each store's last ones.

    The newest finished job of every store and kind stays, so a store still
    shows its last scan; the events go with their job.
    """
    with _transaction(db):
        db.execute(
            f"DELETE FROM jobs WHERE state IN {_FINISHED_SQL}"
            " AND coalesce(finished_at, created_at) < ? AND id NOT IN ("
            " SELECT id FROM (SELECT id, row_number() OVER (PARTITION BY store, kind"
            " ORDER BY coalesce(finished_at, created_at) DESC) AS place"
            f" FROM jobs WHERE state IN {_FINISHED_SQL}) WHERE place = 1)",
            (_iso(now - LOG_MAX_AGE),),
        )


# A scan's summary recording nothing changed: every count zero, no project
# manifest read but those without a store (read again at every scan, see
# ``IndexWriter.project_stamps``), none removed, no project directory
# unreadable.
_UNCHANGED_SQL = " AND ".join(
    [
        *(f"json_extract(summary, '$.{name}') = 0" for name in _SCAN_CHANGES),
        "coalesce(json_extract(summary, '$.projects.read'), 0)"
        " = coalesce(json_extract(summary, '$.projects.invalid'), 0)"
        " + coalesce(json_extract(summary, '$.projects.unknown_store'), 0)",
        "coalesce(json_extract(summary, '$.projects.removed'), 0) = 0",
        "coalesce(json_array_length(summary, '$.projects.unreadable_dirs'), 0) = 0",
    ]
)


def _prune_routine_scans(
    db: sqlite3.Connection, jobs_dir: Path, *, now: datetime
) -> int:
    """Forget routine scans older than 48 hours with their events and logs.

    A routine scan is an incremental scan of a whole store that the
    scheduler started and that succeeded without changing the index
    (``_UNCHANGED_SQL``; a summary lacking a count is kept) and without a
    notice but ``footprints_failed`` (outlines every scan tries again) and
    ``source_skipped`` (every scan says so while a source stays unavailable).
    The newest routine scan of each store stays.

    Returns
    -------
    int
        Jobs forgotten.
    """
    with _transaction(db):
        rows = db.execute(
            "SELECT id FROM (SELECT id, finished_at, row_number() OVER ("
            " PARTITION BY store ORDER BY finished_at DESC, id DESC) AS place"
            " FROM jobs WHERE kind = 'scan' AND actor_kind = 'scheduler'"
            " AND state = 'succeeded'"
            " AND json_extract(params, '$.mode') = 'incremental'"
            " AND json_extract(params, '$.segment') IS NULL"
            f" AND {_UNCHANGED_SQL} AND NOT EXISTS (SELECT 1 FROM job_events e"
            " WHERE e.job_id = jobs.id AND e.type = 'notice'"
            " AND json_extract(e.data, '$.code') IS NOT 'footprints_failed'"
            " AND json_extract(e.data, '$.code') IS NOT 'source_skipped'))"
            " WHERE place > 1 AND finished_at < ?",
            (_iso(now - ROUTINE_SCAN_MAX_AGE),),
        ).fetchall()
        db.executemany("DELETE FROM jobs WHERE id = ?", [(row["id"],) for row in rows])
    for row in rows:
        _log_path(jobs_dir, row["id"]).unlink(missing_ok=True)
    return len(rows)


# An ``own_scan`` result that changed nothing (``OwnScanSummary.result``).
_OWN_SCAN_UNCHANGED = " AND ".join(
    f"json_extract(summary, '$.{name}') = 0"
    for name in ("new", "changed", "missing", "snapshots", "problems")
)


def _prune_routine_own_scans(
    db: sqlite3.Connection, jobs_dir: Path, *, now: datetime
) -> int:
    """Forget routine ``own_scan`` runs older than 48 hours, like routine scans.

    A routine run is one of every project that the scheduler started and
    that succeeded without changing anything; the newest one stays.
    """
    with _transaction(db):
        rows = db.execute(
            "SELECT id FROM (SELECT id, finished_at, row_number() OVER ("
            " ORDER BY finished_at DESC, id DESC) AS place FROM jobs"
            " WHERE kind = 'own_scan' AND actor_kind = 'scheduler'"
            " AND state = 'succeeded' AND json_extract(params, '$.project') IS NULL"
            f" AND {_OWN_SCAN_UNCHANGED}) WHERE place > 1 AND finished_at < ?",
            (_iso(now - ROUTINE_SCAN_MAX_AGE),),
        ).fetchall()
        db.executemany("DELETE FROM jobs WHERE id = ?", [(row["id"],) for row in rows])
    for row in rows:
        _log_path(jobs_dir, row["id"]).unlink(missing_ok=True)
    return len(rows)


def _set_active(job_id: str, *, active: bool) -> None:
    with _PROCESS_LOCK:
        if active:
            _ACTIVE_JOBS.add(job_id)
        else:
            _ACTIVE_JOBS.discard(job_id)


def _owner_lock_path(jobs_dir: Path, pid: int) -> Path:
    return jobs_dir / f"owner-{pid}.lock"


def _hold_owner_lock(jobs_dir: Path) -> Path:
    """Lock this process's owner file (shared by its supervisors)."""
    path = _owner_lock_path(jobs_dir, os.getpid())
    with _PROCESS_LOCK:
        held = _OWNER_LOCKS.get(path)
        if held is not None:
            _OWNER_LOCKS[path] = (held[0], held[1] + 1)
            return path
        handle = path.open("a+b")
        if not _try_lock(handle):  # pragma: no cover - pids are unique
            handle.close()
            raise OSError(f"{path} is locked by another process")
        _OWNER_LOCKS[path] = (handle, 1)
    return path


def _release_owner_lock(path: Path) -> None:
    with _PROCESS_LOCK:
        held = _OWNER_LOCKS.get(path)
        if held is None:
            return
        handle, users = held
        if users > 1:
            _OWNER_LOCKS[path] = (handle, users - 1)
            return
        del _OWNER_LOCKS[path]
        handle.close()
    path.unlink(missing_ok=True)


def _owner_lock_held(jobs_dir: Path, pid: int) -> bool:
    """Whether a live process holds the owner lock of ``pid``."""
    try:
        handle = _owner_lock_path(jobs_dir, pid).open("r+b")
    except FileNotFoundError:
        return False
    except OSError:  # cannot tell: do not interrupt another process's job
        return True
    with handle:
        return not _try_lock(handle)


def _try_lock(handle: IO[bytes]) -> bool:
    """Lock a file without waiting; the lock ends when the handle closes."""
    if sys.platform == "win32":  # pragma: no cover - Windows
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _process_group() -> dict[str, Any]:
    """Start a worker in its own process group, out of reach of the terminal."""
    if sys.platform == "win32":  # pragma: no cover - Windows
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _interrupt_signal() -> int:
    if sys.platform == "win32":  # pragma: no cover - Windows
        return signal.CTRL_BREAK_EVENT
    return signal.SIGINT


def _kill(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()


def _close_quietly(stream: IO[bytes]) -> None:
    with suppress(OSError):
        stream.close()
