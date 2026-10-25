"""Worker process of one background job: ``python -m archiwista.jobs.worker``.

The worker reads its job (``JobSpec``) from the first line of standard
input, runs it and reports in JSON Lines on standard output
(``archiwista.jobs.protocol``); its log goes to standard error. Kinds:

- ``scan``: ``scan_store`` of each producer directory of the store (6a; the
  projects follow a pass over the whole store);
- ``footprints``: unit outlines with the network (``footprint(entry,
  network=True)``) for versions still without an outline, with the
  producer's local memory of unit outlines (decision 4);
- ``link_check``: ``confirm_link`` of a slot's standard path (KA-5); a link
  that does not hold the version its sidecar names is a ``link_mismatch``
  problem until a later check confirms it;
- ``preview``: local previews of files, each built in a render process of
  its own (``archiwista.previews.build.run_preview``, plan v0.2 decision 3);
- ``own_scan``: the data folders of every project, or of one
  (``archiwista.owndata.scan.scan_own_data``, plan v0.2 decision 8);
- ``snapshot``: a snapshot of an own-data file in its folder's ``.wersje/``
  (``archiwista.owndata.snapshots.make_snapshot``, plan v0.2 decision 9),
  then recorded in the index.

An interrupt (SIGINT; CTRL_BREAK_EVENT on Windows) stops the job like Ctrl+C:
a scan abandons its pass, so nothing is marked missing, and the worker ends
with status 130 without a message. The end of standard input means the
supervisor is gone; the worker then interrupts itself the same way. The first
interrupt also starts a watchdog that ends the process after ``STOP_TIMEOUT_S``
whatever it is doing (`_handle_interrupts`).
"""

import _thread
import faulthandler
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import IO, cast

from archiwista.auth import ALL_PROJECTS
from archiwista.config import AppPaths, StoreConfig
from archiwista.error_document import Problem, describe
from archiwista.errors import (
    ArchiwistaError,
    NotFoundError,
    OfflineModeError,
    OwnReaderError,
    ProducerError,
    SnapshotBlockedError,
    SourceStateError,
    UnsupportedError,
)
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    SnapshotWrite,
    TransformerFactory,
)
from archiwista.index.scanner import (
    ScanEvent,
    ScanMode,
    ScanProgress,
    ScanSummary,
    outline_footprints,
    scan_store,
)
from archiwista.jobs.availability import store_unreachable
from archiwista.jobs.error import JobError
from archiwista.jobs.protocol import (
    CODE_INTERNAL_ERROR,
    INTERRUPTED_EXIT,
    REASON_PROTOCOL_ERROR,
    STOP_TIMEOUT_S,
    JobKind,
    JobSpec,
    JsonObject,
    NoticeLevel,
    ProtocolError,
    WorkerMessage,
    decode_spec,
    encode_message,
)
from archiwista.logs import process_log_level
from archiwista.messages import STORED_LANG, language, localize, localize_json, message
from archiwista.owndata.document import SnapshotAuthor
from archiwista.owndata.reader import OwnReader
from archiwista.owndata.scan import (
    OwnScanProgress,
    check_own_folder,
    folder_rules,
    scan_own_data,
    snapshot_stamp,
)
from archiwista.owndata.snapshots import (
    SNAPSHOT_PHASES,
    SnapshotPhase,
    SnapshotResult,
    folder_block,
    make_snapshot,
)
from archiwista.paths import resolve_indexed_path
from archiwista.previews.build import run_preview
from archiwista.sandbox import process_work_dir
from archiwista.services.problems import explain
from archiwista.sources import (
    GeoAdapter,
    LinkCheckAdapter,
    SourceAdapter,
    SourceEntry,
)
from archiwista.sources.registry import SourceRegistry, load_registry

# Versions whose outlines are written in one transaction and reported in one
# progress event by the ``footprints`` job.
FOOTPRINT_BATCH = 25
# Standard input: the job line, then silence until the supervisor is gone.
_STDIN = 0

logger = logging.getLogger("archiwista.jobs.worker")


class Emitter:
    """Write the job's messages as JSON Lines to the protocol stream.

    Parameters
    ----------
    stream : IO[str]
        The worker's real standard output.
    """

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, message: WorkerMessage) -> None:
        """Write one message and flush it."""
        with self._lock:
            self._stream.write(encode_message(message) + "\n")
            self._stream.flush()

    def progress(self, current: int, total: int, **counts: object) -> None:
        """Report ``current`` of ``total`` with counts of the job's kind."""
        self.send(
            WorkerMessage("progress", {"current": current, "total": total, **counts})
        )

    def notice(self, level: NoticeLevel, code: str, message: str) -> None:
        """Report something the person should know, in `STORED_LANG`."""
        text = localize(message, STORED_LANG)
        self.send(
            WorkerMessage("notice", {"level": level, "code": code, "message": text})
        )

    def scan_event(self, event: ScanEvent) -> None:
        """Pass on a scanner's ``ScanProgress`` or ``ScanNotice``."""
        if isinstance(event, ScanProgress):
            self.progress(
                event.current,
                event.total,
                segment=event.segment,
                entries=event.entries,
            )
        else:
            self.notice(event.level, event.code, event.message)


type Runner = Callable[[JobSpec, Emitter], JsonObject]


def main() -> int:
    """Run the job given on standard input; return the exit status.

    The texts the job makes (its notices and its error) are in `STORED_LANG`,
    the language of what is stored; the log is English.

    Returns
    -------
    int
        ``0`` with a ``result`` message, ``1`` with an ``error`` message,
        ``2`` for an unreadable job, ``130`` when interrupted.
    """
    with language(STORED_LANG):
        return _run()


def _run() -> int:
    """Run the job of standard input (see `main`)."""
    protocol = _protocol_stream()
    emit = Emitter(protocol)
    _handle_interrupts()
    logging.basicConfig(
        level=process_log_level("info"),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        spec = decode_spec(_read_line(_STDIN).decode("utf-8", "replace"))
    except ProtocolError as error:
        unreadable = Problem(
            CODE_INTERNAL_ERROR, str(error), details={"reason": REASON_PROTOCOL_ERROR}
        )
        return _report(emit, unreadable, "ProtocolError", status=2)
    _watch_supervisor(_STDIN)
    logger.info(
        "Job %s (%s) of store %s for %s, process %d",
        spec.job_id,
        spec.kind,
        spec.store,
        spec.actor,
        os.getpid(),
    )
    try:
        summary = RUNNERS[spec.kind](spec, emit)
    except KeyboardInterrupt:
        logger.warning("Job %s interrupted", spec.job_id)
        return INTERRUPTED_EXIT
    except Exception as error:
        problem, exception = _failure(error)
        if problem.code == CODE_INTERNAL_ERROR:
            logger.exception("Job %s failed", spec.job_id)
        else:
            logger.error(
                "Job %s failed (%s): %s",
                spec.job_id,
                problem.details.get("reason", problem.code),
                localize(problem.detail, "en"),
            )
        return _report(emit, problem, exception, status=1)
    try:
        # Texts made in a thread of the job are in the default language.
        emit.send(WorkerMessage("result", localize_json(summary, STORED_LANG)))
    except OSError:  # the supervisor is gone
        return 1
    logger.info("Job %s succeeded", spec.job_id)
    return 0


def run_scan(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Scan every producer directory of the store (``mode``, ``segment``)."""
    config = _store(spec)
    mode = cast(ScanMode, spec.params["mode"])
    segment = spec.params.get("segment")
    registry = load_registry(cache_dir=spec.cache_dir)
    summaries: list[ScanSummary] = []
    with IndexWriter(spec.index_path) as writer:
        for producer in config.roots():
            summaries.append(
                scan_store(
                    registry.adapter(producer),
                    writer,
                    spec.settings,
                    config.id,
                    mode=mode,
                    segment=segment,
                    on_event=emit.scan_event,
                )
            )
    return _scan_result(config.id, mode, segment, summaries)


def run_footprints(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Outline the store's versions still without one, with the network.

    A version keeps no outline (``no_source``) when no source gives one; one
    whose sidecar cannot be read now keeps its earlier reason, since a share
    may have gone meanwhile. Outlines get the WGS84 polygon of their native
    rectangle, as in a scan (``outline_footprints``).
    """
    if spec.settings.offline:
        raise OfflineModeError(message("job.offline_mode"))
    config = _store(spec)
    registry = load_registry(cache_dir=spec.cache_dir)
    started = time.perf_counter()
    total = written = failed = 0
    failure: str | None = None
    with (
        IndexWriter(spec.index_path) as writer,
        IndexQueries(spec.index_path) as queries,
    ):
        pending = queries.entries_without_footprint(config.id)
        for producer, root in config.roots().items():
            entries = [entry for entry in pending if entry.producer == producer]
            if not entries:
                continue
            adapter = registry.adapter(producer)
            _require_reachable(adapter, root, writer, config.id)
            done = 0
            emit.progress(done, len(entries), written=written, failed=failed)
            for batch in _batches(entries, FOOTPRINT_BATCH):
                items = []
                for entry in batch:
                    try:
                        found = adapter.footprint(entry, network=True)
                    except (ProducerError, OSError) as error:
                        failed += 1
                        failure = failure or str(error)
                        continue
                    if found.location != "none" or found.reason != "unreadable":
                        items.append((entry, found))
                items, failures = outline_footprints(adapter, items)
                failed += len(failures)
                failure = failure or next(iter(failures), None)
                written += writer.write_footprints(config.id, items)
                done += len(batch)
                emit.progress(done, len(entries), written=written, failed=failed)
            total += len(entries)
    if failed:
        text = message("job.footprints_failed", count=failed, detail=failure)
        emit.notice("warning", "footprints_failed", text)
    return {
        "store": config.id,
        "total": total,
        "written": written,
        "failed": failed,
        "seconds": round(time.perf_counter() - started, 3),
    }


def run_link_check(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Confirm on demand which version a slot's standard path holds.

    The result ``status`` is ``confirmed`` (the link holds the version the
    index names), ``index_outdated`` (it holds the version its sidecar names,
    which the index does not know yet), ``mismatch`` (it does not hold the
    version its sidecar names: problem ``link_mismatch``), ``missing`` (no
    file at the standard path) or ``not_a_link`` (no version is linked).
    A standard path resolving outside the store (a symbolic link leaving
    it, SPEC 10.1) fails the job as ``forbidden`` (reason
    ``path_outside_root``) before the producer reads it.
    """
    config = _store(spec)
    slot = str(spec.params["slot"])
    with IndexQueries(spec.index_path) as queries:
        detail = queries.slot(config.id, slot, visible=ALL_PROJECTS)
    if detail is None:
        text = message("job.slot_not_found", slot=slot, store=config.id)
        raise NotFoundError(text)
    producer = detail.segment.producer
    expected = detail.current
    result: JsonObject = {
        "store": config.id,
        "slot": slot,
        "expected": expected,
        "confirmed": None,
    }
    if expected is None or expected == slot:
        return {**result, "status": "not_a_link"}
    root = config.roots().get(producer)
    if root is None:
        text = message("job.slot_not_found", slot=slot, store=config.id)
        raise NotFoundError(text)
    adapter = load_registry(cache_dir=spec.cache_dir).adapter(producer)
    if not isinstance(adapter, LinkCheckAdapter):
        text = message("job.link_check_unsupported", producer=producer)
        raise UnsupportedError(text)
    with IndexWriter(spec.index_path) as writer:
        _require_reachable(adapter, root, writer, config.id)
        try:
            resolve_indexed_path(root, slot)
        except (FileNotFoundError, NotADirectoryError):
            return {**result, "status": "missing"}
        segment = detail.segment.segment
        confirmed = adapter.confirm_link(
            SourceEntry(
                producer=producer,
                store=str(root),
                relative_path=Path(slot),
                kind="link",
                segment=segment,
                slot_path=Path(slot),
                version_path=Path(expected),
            )
        )
        if confirmed is None:
            writer.record_issue(
                config.id,
                producer,
                path=slot,
                code="link_mismatch",
                segment=segment,
                slot=slot,
            )
            problem, fix = explain("link_mismatch", path=slot, producer=producer)
            text = message("job.link_mismatch", problem=problem, fix=fix)
            emit.notice("warning", "link_mismatch", text)
            return {**result, "status": "mismatch"}
        writer.clear_issue(config.id, path=slot, code="link_mismatch")
    holds = confirmed.as_posix()
    if holds != expected:
        text = message("job.link_index_outdated", slot=slot, version=holds)
        emit.notice("info", "index_outdated", text)
        return {**result, "confirmed": holds, "status": "index_outdated"}
    return {**result, "confirmed": holds, "status": "confirmed"}


def run_own_scan(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Scan the data folders of every project, or of ``project`` (decision 8).

    A run of every project also forgets the folders of projects no longer
    indexed. Outlines take the pinned operations of the first producer that
    has them; without one only files in WGS84 get an outline.
    """
    project = spec.params.get("project")
    # The reader process reads no settings: only its work directory, below
    # the data directory (the index's).
    paths = AppPaths(config_file=Path(os.devnull), data_dir=spec.index_path.parent)
    registry = load_registry(cache_dir=spec.cache_dir)
    with (
        IndexWriter(spec.index_path) as writer,
        IndexQueries(spec.index_path) as queries,
    ):
        known = queries.projects(visible=ALL_PROJECTS)
        chosen = [item for item in known if project in (None, item.key)]
        if project is not None and not chosen:
            text = message("project.not_found", project=project)
            raise NotFoundError(text)
        emit.progress(0, len(chosen), files=0, read=0)

        def progress(found: OwnScanProgress) -> None:
            emit.progress(
                found.current, found.total, files=found.files, read=found.read
            )

        try:
            summary = scan_own_data(
                writer,
                chosen,
                known_projects=known,
                settings=spec.settings,
                paths=paths,
                transformer=_transformer(registry),
                prune=project is None,
                on_progress=progress,
            )
        except OwnReaderError as error:
            text = message("own.scan_reader_failed", detail=error)
            raise OwnReaderError(text) from error
    return summary.result()


def run_snapshot(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Make a snapshot of an own-data file (``make_snapshot``, decision 9).

    The project's data folder is checked before the file is looked up, so a
    folder breaking the rules is ``snapshot_blocked`` also for a file the
    index forgot with it. Progress counts the phases of the snapshot; its
    warnings are notices. A published snapshot goes into the index at once,
    as best it can: the index is a cache, and the next ``own_scan`` adds a
    snapshot missing there. The author is the job's actor (the scheduler
    acts for the owner); no account names are known to a worker.
    """
    started = time.perf_counter()
    key = str(spec.params["project"])
    file_id = str(spec.params["file_id"])
    # The reader process reads no settings: only its work directory, below
    # the data directory (the index's), like the snapshot's local copy.
    paths = AppPaths(config_file=Path(os.devnull), data_dir=spec.index_path.parent)
    with IndexQueries(spec.index_path) as queries:
        known = queries.projects(visible=ALL_PROJECTS)
        project = next((item for item in known if item.key == key), None)
        if project is None:
            text = message("project.not_found", project=key)
            raise NotFoundError(text)
        stores, folders = folder_rules(spec.settings, known)
        folder = check_own_folder(
            spec.settings,
            project.access_key,
            stores=stores,
            app_data=paths.data_dir,
            others=[
                path for name, path in folders.items() if name != project.access_key
            ],
        )
        block = folder_block(folder)
        if block is not None:
            raise SnapshotBlockedError(block.reason, block.message)
        file = queries.own_file(key, file_id, visible=ALL_PROJECTS)
    if file is None:
        text = message("own.file_not_found", project=key, file_id=file_id)
        raise NotFoundError(text)
    total = len(SNAPSHOT_PHASES)
    emit.progress(0, total, phase=None)

    def reached(phase: SnapshotPhase) -> None:
        emit.progress(SNAPSHOT_PHASES.index(phase) + 1, total, phase=phase)

    registry = load_registry(cache_dir=spec.cache_dir)
    try:
        with OwnReader(paths) as reader:
            result = make_snapshot(
                folder,
                file,
                author=_author(spec),
                note=str(spec.params.get("note", "")),
                work_dir=process_work_dir(paths),
                reader=reader,
                transformer=_transformer(registry),
                on_phase=reached,
            )
    except OwnReaderError as error:
        text = message("own.scan_reader_failed", detail=error)
        raise OwnReaderError(text) from error
    for warning in result.warnings:
        emit.notice("warning", warning.code, warning.message)
    if result.status == "created":
        _record_snapshot(spec, project.access_key, file.file.path, result, emit)
    return {
        "status": result.status,
        "label": result.label,
        "content_sha256": result.document.content.sha256,
        "size_bytes": result.document.size_bytes,
        "seconds": round(time.perf_counter() - started, 3),
    }


RUNNERS: Mapping[JobKind, Runner] = {
    "scan": run_scan,
    "footprints": run_footprints,
    "link_check": run_link_check,
    "preview": run_preview,
    "own_scan": run_own_scan,
    "snapshot": run_snapshot,
}


def _transformer(registry: SourceRegistry) -> TransformerFactory | None:
    """Return the pinned operations of the first producer that has them."""
    for producer in sorted(registry.producers()):
        try:
            adapter = registry.adapter(producer)
        except SourceStateError:
            continue
        if isinstance(adapter, GeoAdapter):
            return adapter.transformer
    return None


def _author(spec: JobSpec) -> SnapshotAuthor:
    """Return the job's actor as the author; the scheduler acts for the owner."""
    kind = spec.actor_kind
    return SnapshotAuthor(
        id=spec.actor,
        kind="local_owner" if kind == "scheduler" else kind,
        name=None,
        session=spec.session,
    )


def _record_snapshot(
    spec: JobSpec, project: str, path: str, result: SnapshotResult, emit: Emitter
) -> None:
    """Record a published snapshot in the index; a failure is only a notice."""
    document = result.document
    try:
        stamp, size = snapshot_stamp(result.directory)
        with IndexWriter(spec.index_path) as writer:
            writer.record_snapshot(
                project,
                SnapshotWrite(
                    path,
                    result.label,
                    "ok",
                    stamp,
                    size,
                    document=document.model_dump(mode="json", by_alias=True),
                    created_at=document.created_at,
                    content_method=document.content.method,
                    content_sha256=document.content.sha256,
                ),
            )
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Snapshot %s not in the index: %s", result.label, error)
        text = message("snapshot.not_indexed", label=result.label)
        emit.notice("warning", "snapshot_not_indexed", text)


def _store(spec: JobSpec) -> StoreConfig:
    config = None if spec.store is None else spec.settings.store(spec.store)
    if config is None:
        raise NotFoundError(message("job.store_unknown", store=spec.store))
    return config


def _require_reachable(
    adapter: SourceAdapter, root: Path, writer: IndexWriter, store: str
) -> None:
    """Stop the job when the store cannot be read (probe, empty mount point).

    The job works on versions the index holds, so an empty store directory
    is a share that is not mounted. The store is recorded ``unavailable``.
    """
    error = store_unreachable(adapter.probe(root), root, indexed=True)
    if error is not None:
        writer.set_store_status(store, "unavailable", detail=str(error))
        raise error


def _batches(
    entries: Sequence[SourceEntry], size: int
) -> Iterator[Sequence[SourceEntry]]:
    for start in range(0, len(entries), size):
        yield entries[start : start + size]


def _scan_result(
    store: str, mode: ScanMode, segment: str | None, summaries: Sequence[ScanSummary]
) -> JsonObject:
    """Return the job's summary: totals over the store's producer directories."""
    counts = (
        "entries",
        "versions_written",
        "links_changed",
        "issues_added",
        "footprints_written",
        "footprints_failed",
    )
    finished = (
        "missing",
        "reappeared",
        "removed",
        "slots_removed",
        "unlinked",
        "issues_resolved",
    )
    projects = [summary.projects for summary in summaries if summary.projects]
    return {
        "store": store,
        "mode": mode,
        "segment": segment,
        "seconds": round(sum(summary.seconds for summary in summaries), 3),
        **{name: sum(getattr(s, name) for s in summaries) for name in counts},
        **{
            name: sum(getattr(s.finished, name) for s in summaries) for name in finished
        },
        "segments": [
            {
                "producer": summary.producer,
                "segment": scanned.segment,
                "entries": scanned.entries,
                "seconds": round(scanned.seconds, 3),
            }
            for summary in summaries
            for scanned in summary.segments
        ],
        "projects": None
        if not projects
        else {
            "found": sum(p.found for p in projects),
            "read": sum(p.read for p in projects),
            "unchanged": sum(p.unchanged for p in projects),
            "invalid": sum(p.invalid for p in projects),
            "unknown_store": sum(p.unknown_store for p in projects),
            "removed": sum(p.removed for p in projects),
            "unreadable_dirs": [d for p in projects for d in p.unreadable_dirs],
        },
    }


def _failure(error: Exception) -> tuple[Problem, str]:
    """Return the problem of an error that ended a job and its exception's name.

    An ``ArchiwistaError`` is described as a request's problem is, so that a
    job and a request agree on the code and the reason; any other exception is
    an ``internal_error``.
    """
    if isinstance(error, ArchiwistaError):
        exception = (
            error.exception
            if isinstance(error, ProducerError)
            else type(error).__name__
        )
        return describe(error), exception
    detail = message("job.internal_error", detail=f"{type(error).__name__}: {error}")
    return Problem(CODE_INTERNAL_ERROR, detail), type(error).__name__


def _report(emit: Emitter, problem: Problem, exception: str, *, status: int) -> int:
    """Send the ``error`` message of a job that failed; return ``status``.

    The message is the stored form of the error (``JobError.to_json``: texts
    in `STORED_LANG` with their keys and values) and the ``exception``.
    """
    data = JobError.from_problem(problem).to_json()
    data["exception"] = exception
    with suppress(OSError):  # the supervisor is gone
        emit.send(WorkerMessage("error", data))
    return status


def _protocol_stream() -> IO[str]:
    """Keep standard output for the protocol; send all other output to stderr.

    Libraries (and C code) writing to file descriptor 1 then write to the
    job's log instead of breaking the protocol.
    """
    sys.stdout.flush()
    descriptor = os.dup(1)
    os.dup2(2, 1)
    return os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")


def _handle_interrupts(stop_timeout_s: float = STOP_TIMEOUT_S) -> None:
    """Turn the supervisor's interrupt into ``KeyboardInterrupt``, for a limited time.

    The first interrupt also starts the watchdog of ``faulthandler``: after
    ``stop_timeout_s`` it writes the stacks of all threads to the job's log and
    ends the process with status 1, as the supervisor's killer does when the
    supervisor is alive. A process the supervisor cannot kill (it is gone, or
    the interrupt came from the end of standard input) or one that stalls in
    an exit handler thus stops too: the watchdog is a thread in C, so no lock
    that Python code holds for good can stop it. The tracer of ``coverage``
    holds such a lock when the interrupt lands in it at the wrong moment
    (``Collector.unlock_data``). A later interrupt does not extend the limit.

    Parameters
    ----------
    stop_timeout_s : float, default ``STOP_TIMEOUT_S``
        Seconds from the first interrupt to the end of the process.
    """
    armed = False

    def interrupt(signum: int, frame: FrameType | None) -> None:
        nonlocal armed
        if not armed:
            armed = True
            with suppress(OSError, RuntimeError, ValueError):  # no log: no watchdog
                faulthandler.dump_traceback_later(stop_timeout_s, exit=True)
        raise KeyboardInterrupt

    # The default handler may be missing when the parent ignores SIGINT.
    signal.signal(signal.SIGINT, interrupt)
    if sys.platform == "win32":  # pragma: no cover - Windows
        signal.signal(signal.SIGBREAK, interrupt)


def _read_line(descriptor: int) -> bytes:
    """Read one line from a file descriptor, without Python's buffering.

    A buffered reader would hold its lock in the watching thread and stop
    the interpreter at exit.
    """
    data = b""
    while not data.endswith(b"\n"):
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        data += chunk
    return data


def _watch_supervisor(descriptor: int) -> None:
    """Interrupt the job when standard input ends: the supervisor is gone."""

    def watch() -> None:
        try:
            while os.read(descriptor, 4096):
                pass
        except OSError:
            pass
        logger.warning("The supervisor is gone; stopping the job")
        _interrupt_self()

    threading.Thread(target=watch, name="archiwista-supervisor", daemon=True).start()


def _interrupt_self() -> None:
    if sys.platform == "win32":  # pragma: no cover - Windows
        _thread.interrupt_main()
    else:
        os.kill(os.getpid(), signal.SIGINT)


if __name__ == "__main__":
    if os.name == "posix":
        os.umask(0o077)  # What the job writes locally is the user's alone.
    sys.exit(main())
