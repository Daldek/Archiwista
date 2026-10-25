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
supervisor is gone; the worker then interrupts itself the same way.
"""

import _thread
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
from typing import IO, cast

from archiwista.auth import ALL_PROJECTS
from archiwista.config import AppPaths, StoreConfig
from archiwista.errors import (
    OwnReaderError,
    PathOutsideRootError,
    ProducerError,
    SnapshotBlockedError,
    SnapshotFailedError,
    SourceIncompatibleError,
    SourceStateError,
    SourceUnavailableError,
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
from archiwista.jobs.availability import unreachable_detail
from archiwista.jobs.protocol import (
    CODE_INTERNAL_ERROR,
    CODE_PROTOCOL_ERROR,
    CODE_UNSUPPORTED,
    INTERRUPTED_EXIT,
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
from archiwista.messages import MESSAGES
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


class JobFailure(Exception):
    """The job cannot be done; ``code`` and the Polish ``detail`` explain why.

    ``reason`` tells some codes apart (``snapshot_blocked``: why).
    """

    def __init__(
        self,
        code: str,
        detail: str,
        exception: str | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.exception = exception or type(self).__name__
        self.reason = reason


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
        """Report something the person should know."""
        self.send(
            WorkerMessage("notice", {"level": level, "code": code, "message": message})
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

    Returns
    -------
    int
        ``0`` with a ``result`` message, ``1`` with an ``error`` message,
        ``2`` for an unreadable job, ``130`` when interrupted.
    """
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
        return _report(emit, CODE_PROTOCOL_ERROR, str(error), "ProtocolError", status=2)
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
        code, detail, exception = _failure(error)
        reason = error.reason if isinstance(error, JobFailure) else None
        if code == CODE_INTERNAL_ERROR:
            logger.exception("Job %s failed", spec.job_id)
        else:
            logger.error("Job %s failed (%s): %s", spec.job_id, code, detail)
        return _report(emit, code, detail, exception, status=1, reason=reason)
    try:
        emit.send(WorkerMessage("result", summary))
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
                    _adapter(registry, producer),
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
        raise JobFailure("offline_mode", MESSAGES["job_offline_mode"])
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
            adapter = _adapter(registry, producer)
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
        message = MESSAGES["job_footprints_failed"].format(count=failed, detail=failure)
        emit.notice("warning", "footprints_failed", message)
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
    it, SPEC 10.1) fails the job with ``path_outside_root`` before the
    producer reads it.
    """
    config = _store(spec)
    slot = str(spec.params["slot"])
    with IndexQueries(spec.index_path) as queries:
        detail = queries.slot(config.id, slot, visible=ALL_PROJECTS)
    if detail is None:
        message = MESSAGES["job_slot_not_found"].format(slot=slot, store=config.id)
        raise JobFailure("not_found", message)
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
        message = MESSAGES["job_slot_not_found"].format(slot=slot, store=config.id)
        raise JobFailure("not_found", message)
    adapter = _adapter(load_registry(cache_dir=spec.cache_dir), producer)
    if not isinstance(adapter, LinkCheckAdapter):
        message = MESSAGES["job_link_check_unsupported"].format(producer=producer)
        raise JobFailure(CODE_UNSUPPORTED, message)
    with IndexWriter(spec.index_path) as writer:
        _require_reachable(adapter, root, writer, config.id)
        try:
            resolve_indexed_path(root, slot)
        except (FileNotFoundError, NotADirectoryError):
            return {**result, "status": "missing"}
        except PathOutsideRootError as error:
            raise JobFailure(
                "path_outside_root", str(error), type(error).__name__
            ) from error
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
            message = MESSAGES["job_link_mismatch"].format(problem=problem, fix=fix)
            emit.notice("warning", "link_mismatch", message)
            return {**result, "status": "mismatch"}
        writer.clear_issue(config.id, path=slot, code="link_mismatch")
    holds = confirmed.as_posix()
    if holds != expected:
        message = MESSAGES["job_link_index_outdated"].format(slot=slot, version=holds)
        emit.notice("info", "index_outdated", message)
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
            message = MESSAGES["project_not_found"].format(project=project)
            raise JobFailure("not_found", message)
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
            message = MESSAGES["own_scan_reader_failed"].format(detail=error)
            raise JobFailure(
                "own_reader_failed", message, type(error).__name__
            ) from error
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
            message = MESSAGES["project_not_found"].format(project=key)
            raise JobFailure("not_found", message)
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
            raise JobFailure(
                "snapshot_blocked",
                block.message,
                "SnapshotBlockedError",
                reason=block.reason,
            )
        file = queries.own_file(key, file_id, visible=ALL_PROJECTS)
    if file is None:
        message = MESSAGES["own_file_not_found"].format(project=key, file_id=file_id)
        raise JobFailure("not_found", message)
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
    except SnapshotBlockedError as error:
        raise JobFailure(
            "snapshot_blocked", str(error), type(error).__name__, reason=error.reason
        ) from error
    except SnapshotFailedError as error:
        raise JobFailure(error.job_code, str(error), type(error).__name__) from error
    except PathOutsideRootError as error:
        raise JobFailure(
            "path_outside_root", str(error), type(error).__name__
        ) from error
    except OwnReaderError as error:
        message = MESSAGES["own_scan_reader_failed"].format(detail=error)
        raise JobFailure("own_reader_failed", message, type(error).__name__) from error
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
        message = MESSAGES["snapshot_not_indexed"].format(label=result.label)
        emit.notice("warning", "snapshot_not_indexed", message)


def _store(spec: JobSpec) -> StoreConfig:
    config = None if spec.store is None else spec.settings.store(spec.store)
    if config is None:
        raise JobFailure(
            "not_found", MESSAGES["job_store_unknown"].format(store=spec.store)
        )
    return config


def _adapter(registry: SourceRegistry, producer: str) -> SourceAdapter:
    """Return the producer's adapter; an unusable plugin fails the job."""
    try:
        return registry.adapter(producer)
    except SourceStateError as error:
        code = (
            "source_incompatible"
            if isinstance(error, SourceIncompatibleError)
            else "source_unavailable"
        )
        raise JobFailure(code, str(error), type(error).__name__) from error


def _require_reachable(
    adapter: SourceAdapter, root: Path, writer: IndexWriter, store: str
) -> None:
    """Stop the job when the store cannot be read (probe, empty mount point).

    The job works on versions the index holds, so an empty store directory
    is a share that is not mounted. The store is recorded ``unavailable``.
    """
    detail = unreachable_detail(adapter.probe(root), root, indexed=True)
    if detail is not None:
        writer.set_store_status(store, "unavailable", detail=detail)
        raise JobFailure("store_unavailable", detail, "SourceUnavailableError")


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


def _failure(error: Exception) -> tuple[str, str, str]:
    """``(code, detail, exception)`` of an error that ended a job."""
    if isinstance(error, JobFailure):
        return error.code, error.detail, error.exception
    if isinstance(error, SourceUnavailableError):
        return "store_unavailable", str(error), type(error).__name__
    if isinstance(error, SourceIncompatibleError):
        return "source_incompatible", str(error), type(error).__name__
    if isinstance(error, ProducerError):
        return f"{error.package}_error", error.message, error.exception
    detail = MESSAGES["job_internal_error"].format(
        detail=f"{type(error).__name__}: {error}"
    )
    return CODE_INTERNAL_ERROR, detail, type(error).__name__


def _report(
    emit: Emitter,
    code: str,
    detail: str,
    exception: str,
    *,
    status: int,
    reason: str | None = None,
) -> int:
    data: JsonObject = {"code": code, "detail": detail, "exception": exception}
    if reason is not None:
        data["reason"] = reason
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


def _handle_interrupts() -> None:
    """Turn the supervisor's interrupt into ``KeyboardInterrupt``.

    The default handler may be missing when the parent ignores SIGINT.
    """
    signal.signal(signal.SIGINT, signal.default_int_handler)
    if sys.platform == "win32":  # pragma: no cover - Windows
        signal.signal(signal.SIGBREAK, signal.default_int_handler)


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
