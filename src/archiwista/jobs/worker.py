"""Worker process of one background job: ``python -m archiwista.jobs.worker``.

The worker reads its job (``JobSpec``) from the first line of standard
input, runs it and reports in JSON Lines on standard output
(``archiwista.jobs.protocol``); its log goes to standard error. Kinds:

- ``scan``: ``scan_store`` of each producer directory of the store (6a; the
  projects follow a pass over the whole store); a ``segment`` is scanned only
  by the producers that own it (ADR 0032, decision 9);
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
  then recorded in the index;
- ``availability``: what the source has for an area and a product (the
  producer's ``ActionAdapter.availability``, plan of 2026-10-25 A2), kept in
  the index as the area's last report;
- ``check``: what a run of each of a job's calls of a producer's commands
  would do in the store (the producer's ``ActionAdapter.check``, A4; all the
  lines of a report's row in one job, ADR-044), the plan of each call kept in
  the index with the job; a job some of whose calls or positions could not be
  checked ends ``partial``;
- ``download``: a run of each of a job's calls in the store (the producer's
  ``ActionAdapter.run``, A5), of the plans a ``check`` job kept when one is
  named, narrowed to the positions the job claimed (``ActionAdapter.narrow``,
  ADR-047); the slots of the files it reports are read again into the index
  when it ends, those of the units it named also when it is interrupted;
- ``preview_warm``: the first look at current versions (the pane's
  thumbnail, the map's tiles at the smallest zoom) prepared in the preview
  cache ahead, at the lowest priority and within the room the cache has
  without evicting what people used lately
  (``archiwista.previews.warm.warm_previews``, ADR-041).

A worker imports what every job needs; the previews' modules, which bring the
models of the API and the supervisor, are imported by the runners of
``preview`` and ``preview_warm`` only, so the worker of a producer's job
starts without them (ADR-044, decision C).

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
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import FrameType
from typing import IO, cast

from archiwista._errors import BY_CODE
from archiwista.auth import ALL_PROJECTS
from archiwista.config import AppPaths, StoreConfig
from archiwista.error_document import Problem, describe
from archiwista.errors import (
    ArchiwistaError,
    CheckFailedError,
    NotFoundError,
    OfflineModeError,
    OwnReaderError,
    ProducerError,
    RunFailedError,
    SnapshotBlockedError,
    SourceStateError,
    UnsupportedError,
)
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    PlanTotals,
    SnapshotWrite,
    StoredPlan,
    TransformerFactory,
)
from archiwista.index.scanner import (
    REFRESH_VIEW_MAX_UNITS,
    ScanEvent,
    ScanMode,
    ScanProgress,
    ScanSummary,
    outline_footprints,
    refresh_view,
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
from archiwista.messages import (
    STORED_LANG,
    language,
    localize,
    localize_json,
    message,
    with_detail,
)
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
from archiwista.sandbox import process_work_dir
from archiwista.services.commands import actions, store_root
from archiwista.services.problems import explain
from archiwista.sources import (
    FILE_STATUSES,
    ActionAdapter,
    ActionPlan,
    ActionProgress,
    ActionResult,
    CommandCall,
    GeoAdapter,
    LinkCheckAdapter,
    RunStatus,
    SegmentDescriptionAdapter,
    SegmentedAdapter,
    SourceAdapter,
    SourceEntry,
)
from archiwista.sources.registry import SourceRegistry, load_registry

# Versions whose outlines are written in one transaction and reported in one
# progress event by the ``footprints`` job.
FOOTPRINT_BATCH = 25
# Seconds an interrupted download has to read the slots of its units again
# before the watchdog of ``_handle_interrupts`` ends the process.
RESCAN_STOP_S = STOP_TIMEOUT_S / 2
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


@dataclass(frozen=True, slots=True)
class PartialResult:
    """The summary of a job that did only part of its work (it ends ``partial``)."""

    summary: JsonObject


type Runner = Callable[[JobSpec, Emitter], JsonObject | PartialResult]


def main() -> int:
    """Run the job given on standard input; return the exit status.

    The texts the job makes (its notices and its error) are in `STORED_LANG`,
    the language of what is stored; the log is English.

    Returns
    -------
    int
        ``0`` with a ``result`` or ``partial`` message, ``1`` with an
        ``error`` message, ``2`` for an unreadable job, ``130`` when
        interrupted.
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
        outcome = RUNNERS[spec.kind](spec, emit)
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
    partial = isinstance(outcome, PartialResult)
    summary = outcome.summary if isinstance(outcome, PartialResult) else outcome
    try:
        # Texts made in a thread of the job are in the default language.
        emit.send(
            WorkerMessage(
                "partial" if partial else "result",
                localize_json(summary, STORED_LANG),
            )
        )
    except OSError:  # the supervisor is gone
        return 1
    logger.info("Job %s %s", spec.job_id, "ended partly" if partial else "succeeded")
    return 0


def run_scan(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Scan every producer directory of the store (``mode``, ``segment``).

    A directory whose source is not available (not installed, incompatible,
    failed to load) is skipped with a notice, and its entry stays in the
    settings (SPEC 5.8); the store's other directories are scanned. A
    ``segment`` is scanned by the producers that own it in the index (or by
    those that scan by segment, for a name it does not know); a producer that
    reads only its whole directory (IMGWTools) refuses the job as
    ``unsupported`` before anything is scanned.
    """
    config = _store(spec)
    mode = cast(ScanMode, spec.params["mode"])
    segment = spec.params.get("segment")
    registry = load_registry(cache_dir=spec.cache_dir)
    adapters: dict[str, SourceAdapter] = {}
    for producer in config.roots():
        try:
            adapters[producer] = registry.adapter(producer)
        except SourceStateError as error:
            text = message(
                "job.source_skipped", producer=producer, detail=error.message
            )
            emit.notice("warning", "source_skipped", text)
    if segment is not None:
        with IndexQueries(spec.index_path) as queries:
            owners = queries.segment_producers(config.id, segment)
        adapters = _segment_scanners(adapters, owners, segment)
    summaries: list[ScanSummary] = []
    with IndexWriter(spec.index_path) as writer:
        geo = _geo(registry)
        for adapter in adapters.values():
            summaries.append(
                scan_store(
                    adapter,
                    writer,
                    spec.settings,
                    config.id,
                    mode=mode,
                    segment=segment,
                    on_event=emit.scan_event,
                    geo=geo,
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


def run_availability(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Ask the producer what the source has for an area and keep the report.

    The area is the one the index keeps (``area_id``); the producer's notices
    become the job's. The report replaces the area's last one of the product
    unless that one is newer.
    """
    if spec.settings.offline:
        raise OfflineModeError(message("job.offline_mode"))
    area_id = str(spec.params["area_id"])
    producer = str(spec.params["producer"])
    product = str(spec.params["product"])
    started = time.perf_counter()
    with IndexQueries(spec.index_path) as queries:
        area = queries.area(area_id)
    if area is None:
        raise NotFoundError(message("api.area_unknown", area=area_id))
    adapter = actions(load_registry(cache_dir=spec.cache_dir), producer)
    report = adapter.availability(
        product,
        area=area.geometry,
        countries=area.countries,
        force=bool(spec.params["force"]),
        on_notice=lambda notice: emit.notice(notice.level, notice.code, notice.message),
    )
    with IndexWriter(spec.index_path) as writer:
        kept = writer.write_availability(
            area_id, report, product=product, job_id=spec.job_id
        )
    return {
        "area_id": area_id,
        "producer": producer,
        "product": product,
        "checked_at": report.checked_at.isoformat(),
        "ok": report.ok,
        "combinations": len(report.combinations),
        "kept": kept,
        "seconds": round(time.perf_counter() - started, 3),
    }


def run_check(spec: JobSpec, emit: Emitter) -> JsonObject | PartialResult:
    """Plan a run of each of a job's calls in the store and keep the plans.

    The producer compares the store's root (the configured directory of the
    producer, never its default root) with the source, one call after the
    other in this one process (ADR-044); its notices become the job's, and
    each call planned is a progress event. The plan of each call is kept with
    the job, with the producer's command line of the run it plans. A call the
    producer refuses, or one with none of its positions checked
    (``check_failed``), keeps no plan, and its section of the summary says
    why. A job some of whose calls or positions could not be checked ends
    ``partial``; one with no call planned fails with the error of its first
    call.
    """
    if spec.settings.offline:
        raise OfflineModeError(message("job.offline_mode"))
    config = _store(spec)
    calls = _calls(spec)
    root = store_root(spec.settings, config.id, calls[0])
    started = time.perf_counter()
    adapter = actions(load_registry(cache_dir=spec.cache_dir), calls[0].producer)
    kept: list[StoredPlan] = []
    sections: list[JsonObject] = []
    errors: list[ArchiwistaError] = []
    for place, call in enumerate(calls):
        line = adapter.format(replace(call, run={"root": str(root)}))
        try:
            plan = _checked_plan(adapter, call, root, emit)
        except ArchiwistaError as error:
            errors.append(error)
            sections.append(_plan_section(call, line, error=error))
        else:
            kept.append(StoredPlan(spec.job_id, place, config.id, line, plan))
            sections.append(_plan_section(call, line, plan=plan))
        emit.progress(place + 1, len(calls))
    if not kept:
        raise errors[0]
    with IndexWriter(spec.index_path) as writer:
        writer.write_plans(kept)
    plans = [stored.plan for stored in kept]
    totals = PlanTotals.of(plans)
    ok = not errors and totals.ok
    summary: JsonObject = {
        "producer": calls[0].producer,
        "store": config.id,
        "root": plans[0].root,
        "checked_at": totals.checked_at.isoformat(),
        "ok": ok,
        "positions": totals.positions,
        "counts": totals.counts,
        "size_bytes": totals.size_bytes,
        "size_complete": totals.size_complete,
        "failed": [
            {"call": stored.call, "path": entry.path, "error": entry.error}
            for stored in kept
            for entry in stored.plan.entries
            if entry.status == "check_failed"
        ],
        "calls": sections,
        "seconds": round(time.perf_counter() - started, 3),
    }
    return summary if ok else PartialResult(summary)


def run_download(spec: JobSpec, emit: Emitter) -> JsonObject | PartialResult:
    """Run each of a job's calls in the store, then read their files' slots again.

    The producer writes the store's root (the configured directory of the
    producer, never its default root) itself, one call after the other in
    this one process (ADR-044). With ``plan_job`` each call runs the plan
    that ``check`` job kept of it, so a position whose source changed since
    comes back as a failed item (``conflict``, ``stale_plan``); a call
    without a kept plan (its check failed) or whose plan has nothing to
    download is skipped. A plan runs narrowed to the positions the job
    claimed when it started (``JobSpec.claimed``): those another active
    download of the store fetches (``JobSpec.taken``) are left to it, one
    notice ``taken_by_job`` per such job, and the summary lists them
    (``taken``: ``path``, ``unit``, ``job``, ``actor``); a call all of whose
    positions to download are taken is skipped (``taken``). The progress (with
    the ``call`` and the number of ``calls``) and the notices become the
    job's. When the calls end the index learns their files: the slot of each
    file of ``files[]`` is read again (``scope``, ``refresh_view``), and those
    of the units a call that failed named. When the job is interrupted, the
    slots of what its calls wrote or named are read again within
    ``RESCAN_STOP_S``: those of the plan's positions with a plan, else in
    every segment of the store. A call the producer refuses, or none of whose
    units succeeded, failed; a job some of whose calls or units failed, or
    some of whose positions were taken (a retry fetches what the other job
    failed), ends ``partial``; one none of whose calls run succeeded fails
    with the error of its first (``RunFailedError``, the code of the first
    failed unit, when the producer reported the units).

    With ``pin`` (A-ADR-049 decision 9) a job that succeeded writes, after
    the rescan, the ``plan`` group of the project: its ``files[]`` and the
    positions of its kept plans it did not transfer, at the version the
    index holds at their standard path; the summary's ``pin`` says what was
    written (``written``, ``pins``, ``not_pinned``). A job that is not ``ok``
    pins nothing (``written`` false, ``reason`` ``job_partial``), and a write
    that fails (``error``) ends the job ``partial``; the downloaded files
    stay.
    """
    if spec.settings.offline:
        raise OfflineModeError(message("job.offline_mode"))
    config = _store(spec)
    calls = _calls(spec)
    root = store_root(spec.settings, config.id, calls[0])
    plan_job = spec.params.get("plan_job")
    plans = None if plan_job is None else _kept_plans(spec, str(plan_job))
    started = time.perf_counter()
    registry = load_registry(cache_dir=spec.cache_dir)
    adapter = actions(registry, calls[0].producer)
    reader = registry.adapter(calls[0].producer)
    runs: list[_CallRun] = []
    sections: list[JsonObject] = []
    for (job, actor), count in Counter(
        (str(item["job"]), str(item["actor"])) for item in spec.taken
    ).items():
        text = message("job.taken_by_job", count=count, actor=actor, job=job)
        emit.notice("info", "taken_by_job", text)
    try:
        for place, call in enumerate(calls):
            kept = None if plans is None else plans.get(place)
            plan = (
                kept
                if kept is None or spec.claimed is None
                else adapter.narrow(kept, spec.claimed)
            )
            line = adapter.format(replace(call, run={"root": str(root)}))
            if kept is None and plans is not None:
                sections.append(
                    _run_section(call, line, "skipped", reason="not_planned")
                )
                continue
            if plan is not None and not plan.todo:
                reason = (
                    "taken" if kept is not None and kept.todo else "nothing_to_download"
                )
                sections.append(_run_section(call, line, "skipped", reason=reason))
                continue
            run = _CallRun(place, plan)
            runs.append(run)
            _run_call(adapter, call, root, run, calls=len(calls), emit=emit)
            sections.append(
                _run_section(
                    call, line, run.status(), error=run.error, result=run.result
                )
            )
    except BaseException:
        _rescan(
            spec,
            reader,
            config.id,
            lambda: _run_scopes(adapter, reader, root, runs),
            emit,
            timeout_s=RESCAN_STOP_S,
        )
        raise
    rescanned = _rescan(
        spec,
        reader,
        config.id,
        lambda: _run_scopes(adapter, reader, root, runs),
        emit,
        timeout_s=None,
    )
    errors = [run.error for run in runs if run.error is not None]
    if runs and len(errors) == len(runs):
        raise errors[0]
    results = [(run.place, run.result) for run in runs if run.result is not None]
    counts = dict.fromkeys(FILE_STATUSES, 0)
    for _, result in results:
        for file in result.files:
            counts[file.status] += 1
    # Positions another job fetches are no part of this job's success: a retry
    # fetches what that job failed (ADR-047).
    ok = all(run.status() == "ok" for run in runs) and not spec.taken
    summary: JsonObject = {
        "producer": calls[0].producer,
        "store": config.id,
        "root": results[0][1].root if results else str(root),
        "plan_job": plan_job,
        "status": "ok" if ok else "partial",
        "counts": counts,
        "files": [
            {**asdict(file), "call": place}
            for place, result in results
            for file in result.files
        ],
        "items": [
            {**asdict(item), "call": place}
            for place, result in results
            for item in result.items
        ],
        "failed": sum(len(result.failed) for _, result in results),
        "calls": sections,
        "taken": list(spec.taken),
        "rescanned": rescanned,
        "seconds": round(time.perf_counter() - started, 3),
    }
    if "pin" in spec.params:
        summary["pin"] = _pin_download(
            spec, config.id, calls, summary, plans, ok, geo=_geo(registry)
        )
        ok = ok and "error" not in summary["pin"]
        summary["status"] = "ok" if ok else "partial"
    return summary if ok else PartialResult(summary)


def _pin_download(
    spec: JobSpec,
    store: str,
    calls: Sequence[CommandCall],
    summary: JsonObject,
    plans: Mapping[int, ActionPlan] | None,
    ok: bool,
    *,
    geo: GeoAdapter | None,
) -> JsonObject:
    """Write the project's ``plan`` group of a download; return the ``pin``."""
    # Only a download that pins needs the services: imported here.
    from archiwista.services.pins import pin_download

    pin = cast(Mapping[str, str], spec.params["pin"])
    target: JsonObject = {"project": pin["project"], "group": pin["group"]}
    if not ok:
        return {**target, "written": False, "reason": "job_partial"}
    positions = [
        entry.path for plan in (plans or {}).values() for entry in plan.entries
    ]
    try:
        written = pin_download(
            spec.settings,
            spec.index_path,
            geo,
            pin=pin,
            store=store,
            calls=calls,
            files=cast(Sequence[Mapping[str, object]], summary["files"]),
            positions=positions,
            account=spec.actor,
        )
    except ArchiwistaError as error:
        return {**target, "written": False, "error": _call_error(error)}
    return {**written, "written": True}


def run_preview(spec: JobSpec, emit: Emitter) -> JsonObject:
    """Build the previews of the job's refs (``previews.build.run_preview``).

    The previews' modules are imported here, by the jobs that build them.
    """
    from archiwista.previews.build import run_preview as build_previews

    return build_previews(spec, emit)


def run_preview_warm(spec: JobSpec, emit: Emitter) -> JsonObject | PartialResult:
    """Prepare the first look at current versions ahead (``warm_previews``).

    A warm-up some of whose files failed, or that stopped when the preview
    cache had no more room, ends ``partial``. The previews' modules are
    imported here, by the jobs that warm them.
    """
    from archiwista.previews.warm import warm_previews

    summary = warm_previews(spec, emit)
    if summary["failed"] or summary["skipped"]:
        return PartialResult(summary)
    return summary


RUNNERS: Mapping[JobKind, Runner] = {
    "scan": run_scan,
    "footprints": run_footprints,
    "link_check": run_link_check,
    "preview": run_preview,
    "own_scan": run_own_scan,
    "snapshot": run_snapshot,
    "availability": run_availability,
    "check": run_check,
    "download": run_download,
    "preview_warm": run_preview_warm,
}


def _checked_plan(
    adapter: ActionAdapter, call: CommandCall, root: Path, emit: Emitter
) -> ActionPlan:
    """Return the producer's plan of one call; its notices become the job's.

    Raises
    ------
    CheckFailedError
        None of the plan's positions could be checked (``check_failed``, the
        producer's text of the first).
    ArchiwistaError
        The producer refused the call (``ProducerError``).
    """
    plan = adapter.check(
        call.command,
        call.options,
        root=root,
        on_notice=lambda notice: emit.notice(notice.level, notice.code, notice.message),
    )
    failed = [entry for entry in plan.entries if entry.status == "check_failed"]
    if failed and len(failed) == len(plan.entries):
        text = message("job.check_failed", count=len(failed))
        raise CheckFailedError(with_detail(text, failed[0].error))
    return plan


def _calls(spec: JobSpec) -> tuple[CommandCall, ...]:
    """Return the calls of a ``check`` or ``download`` job, in their order."""
    producer = str(spec.params["producer"])
    return tuple(
        CommandCall(producer, str(call["command"]), dict(call["options"]))
        for call in spec.params["calls"]
    )


def _kept_plans(spec: JobSpec, job_id: str) -> dict[int, ActionPlan]:
    """Return the plans the ``check`` job ``job_id`` kept, by the place of their call.

    Raises
    ------
    NotFoundError
        The index keeps no plan of that job (``job.no_plan``): it was
        forgotten since.
    """
    with IndexQueries(spec.index_path) as queries:
        stored = queries.plans(job_id)
    if not stored:
        raise NotFoundError(message("job.no_plan", job=job_id))
    return {item.call: item.plan for item in stored}


@dataclass(slots=True)
class _CallRun:
    """One call of a ``download`` job as it ran (``_run_call``).

    ``place`` is the call's place in the job's ``calls``, ``plan`` the kept
    plan it runs, ``units`` the units its progress named; ``result`` is what
    the producer reported, ``error`` why the call failed.
    """

    place: int
    plan: ActionPlan | None
    units: set[str] = field(default_factory=set)
    result: ActionResult | None = None
    error: ArchiwistaError | None = None

    def status(self) -> RunStatus:
        """Return ``ok``, ``partial`` (some units failed) or ``failed``."""
        if self.error is not None or self.result is None:
            return "failed"
        return self.result.status


def _run_call(
    adapter: ActionAdapter,
    call: CommandCall,
    root: Path,
    run: _CallRun,
    *,
    calls: int,
    emit: Emitter,
) -> None:
    """Run one call of a ``download`` job; keep its result, or why it failed.

    Its progress events name the call (``call`` of ``calls``) besides the
    producer's ``unit``, ``status`` and ``message``. A call the producer
    refuses, or none of whose units succeeded, keeps its error and the job
    goes on with the next call; any other exception ends the job.
    """

    def progressed(event: ActionProgress) -> None:
        if event.unit is not None:
            run.units.add(event.unit)
        emit.progress(
            event.current,
            event.total,
            call=run.place,
            calls=calls,
            unit=event.unit,
            status=event.status,
            message=event.message,
        )

    try:
        run.result = adapter.run(
            call.command,
            call.options,
            root=root,
            plan=run.plan,
            on_progress=progressed,
            on_notice=lambda notice: emit.notice(
                notice.level, notice.code, notice.message
            ),
        )
    except ArchiwistaError as error:
        run.error = error
        return
    if run.result.status == "failed":
        run.error = _run_failed(run.result)


def _plan_section(
    call: CommandCall,
    line: str,
    *,
    plan: ActionPlan | None = None,
    error: ArchiwistaError | None = None,
) -> JsonObject:
    """Return what the check of one call came to: its plan's size, or why none."""
    return {
        "command": call.command,
        "line": line,
        "status": "failed" if plan is None else "ok" if plan.ok else "partial",
        "positions": 0 if plan is None else len(plan.entries),
        "todo": 0 if plan is None else len(plan.todo),
        "error": _call_error(error),
    }


def _run_section(
    call: CommandCall,
    line: str,
    status: str,
    *,
    reason: str | None = None,
    result: ActionResult | None = None,
    error: ArchiwistaError | None = None,
) -> JsonObject:
    """Return what the run of one call came to: its files, failed units, error."""
    return {
        "command": call.command,
        "line": line,
        "status": status,
        "reason": reason,
        "files": 0 if result is None else len(result.files),
        "failed": 0 if result is None else len(result.failed),
        "error": _call_error(error),
    }


def _call_error(error: ArchiwistaError | None) -> JsonObject | None:
    """Return why a call of a job failed: its problem's code, reason and text."""
    if error is None:
        return None
    problem = describe(error)
    return {
        "code": problem.code,
        "reason": problem.details.get("reason"),
        "detail": problem.detail,
    }


def _scopes(
    adapter: ActionAdapter, paths: Iterable[str]
) -> dict[str | None, tuple[str, ...]]:
    """Return the units of each segment that read the files at ``paths`` again."""
    found: dict[str | None, dict[str, None]] = {}
    for path in paths:
        scope = adapter.scope(path)
        found.setdefault(scope.segment, {}).update(dict.fromkeys(scope.units or ()))
    return {segment: tuple(units) for segment, units in found.items()}


def _unit_scopes(
    adapter: ActionAdapter,
    reader: SourceAdapter,
    root: Path,
    plan: ActionPlan | None,
    units: Collection[str],
) -> dict[str | None, tuple[str, ...]]:
    """Return the scopes of the units a run named before it stopped.

    With a plan, those of the plan's positions to download of these units;
    without one, the units in every segment of the store (a producer's unit
    names no segment), each segment reading only the slots it has of them.
    """
    if not units:
        return {}
    if plan is not None:
        return _scopes(adapter, (e.path for e in plan.todo if e.unit in units))
    named = tuple(sorted(units))
    if isinstance(reader, SegmentedAdapter):
        return dict.fromkeys(reader.segments(root), named)
    return {None: named}


def _run_scopes(
    adapter: ActionAdapter,
    reader: SourceAdapter,
    root: Path,
    runs: Iterable[_CallRun],
) -> dict[str | None, tuple[str, ...]]:
    """Return the scopes that read again what a download's calls wrote or named.

    The files of each call the producer reported; of a call that failed or
    was stopped, the units its progress named (``_unit_scopes``).
    """
    found: dict[str | None, dict[str, None]] = {}
    for run in runs:
        scopes = (
            _unit_scopes(adapter, reader, root, run.plan, run.units)
            if run.result is None
            else _scopes(adapter, (file.path for file in run.result.files))
        )
        for segment, units in scopes.items():
            found.setdefault(segment, {}).update(dict.fromkeys(units))
    return {segment: tuple(units) for segment, units in found.items()}


def _rescan(
    spec: JobSpec,
    reader: SourceAdapter,
    store: str,
    scopes: Callable[[], Mapping[str | None, Sequence[str]]],
    emit: Emitter,
    *,
    timeout_s: float | None,
) -> int:
    """Read the slots of a run's units again into the index; return the units read.

    ``refresh_view`` of the units of each segment, in batches, the segments
    described first (a run may have made one). A store found unavailable, a
    failure or the end of ``timeout_s`` stops it with the notice
    ``rescan_failed``: the next scan of the store reads the rest.
    """
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    read = 0
    try:
        found = scopes()
        if not found:
            return 0
        with IndexWriter(spec.index_path) as writer:
            if isinstance(reader, SegmentDescriptionAdapter):
                named = [segment for segment in found if segment is not None]
                described = [reader.describe_segment(name) for name in named]
                writer.write_segments(store, reader.producer, described)
            with IndexQueries(spec.index_path) as queries:
                for segment, units in found.items():
                    for batch in _batches(units, REFRESH_VIEW_MAX_UNITS):
                        left = None if deadline is None else deadline - time.monotonic()
                        status = refresh_view(
                            reader,
                            writer,
                            queries,
                            spec.settings,
                            store,
                            segment,
                            batch,
                            timeout_s=None if left is None else max(left, 0.0),
                        )
                        if any(
                            item.store == store and item.stale for item in status.stores
                        ):
                            emit.notice(
                                "warning", "rescan_failed", message("job.rescan_failed")
                            )
                            return read
                        read += len(batch)
    except (TimeoutError, ArchiwistaError, OSError, sqlite3.Error, ValueError) as error:
        logger.warning(
            "Job %s: the rescan of its units stopped: %s", spec.job_id, error
        )
        text = with_detail(message("job.rescan_failed"), str(error))
        emit.notice("warning", "rescan_failed", text)
    return read


def _run_failed(result: ActionResult) -> RunFailedError:
    """Return the error of a run no unit of which succeeded."""
    failed = result.failed
    first = failed[0] if failed else None
    text = message("job.run_failed", count=len(result.items))
    code = None if first is None or first.code not in BY_CODE else first.code
    return RunFailedError(
        with_detail(text, None if first is None else first.message),
        code=code,
        details=None if first is None else {"unit": first.id},
    )


def _geo(registry: SourceRegistry) -> GeoAdapter | None:
    """Return the first producer with pinned coordinate operations, if any."""
    for producer in sorted(registry.producers()):
        try:
            adapter = registry.adapter(producer)
        except SourceStateError:
            continue
        if isinstance(adapter, GeoAdapter):
            return adapter
    return None


def _transformer(registry: SourceRegistry) -> TransformerFactory | None:
    """Return the pinned operations of the first producer that has them."""
    geo = _geo(registry)
    return None if geo is None else geo.transformer


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


def _batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _segment_scanners(
    adapters: Mapping[str, SourceAdapter], owners: Collection[str], segment: str
) -> dict[str, SourceAdapter]:
    """Return the producers that scan ``segment``, or refuse the job.

    A segment belongs to the producers that own it in the index. A name the
    index does not know belongs to those that scan by segment
    (``SegmentedAdapter``), so a store of only Kartograf behaves as it always
    did; when none of the store's available producers does, they are all asked
    and refuse.

    Parameters
    ----------
    adapters : Mapping[str, SourceAdapter]
        The available producers of the store's directories, by name.
    owners : Collection[str]
        Producers that own ``segment`` (``IndexQueries.segment_producers``).
    segment : str
        The segment the job names.

    Returns
    -------
    dict[str, SourceAdapter]
        The producers to scan, by name; empty when the ones asked are not
        available.

    Raises
    ------
    UnsupportedError
        A producer asked to scan ``segment`` reads only its whole directory
        (IMGWTools: a segment is a label there).
    """
    if owners:
        asked = {name: found for name, found in adapters.items() if name in owners}
    else:
        asked = {
            name: found
            for name, found in adapters.items()
            if isinstance(found, SegmentedAdapter)
        }
        asked = asked or dict(adapters)
    for name, found in asked.items():
        if not isinstance(found, SegmentedAdapter):
            text = message(
                "job.segment_scan_unsupported", producer=name, segment=segment
            )
            raise UnsupportedError(text)
    return asked


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
