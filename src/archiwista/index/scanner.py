"""Scan a producer's store into the local index (decision 3 of the v0.1 plan).

A scan lists the store's segments (``SegmentedAdapter.segments``) and reads
them with ``SourceAdapter.iter_entries`` in a bounded thread pool, one
iterator per thread. Threads hide the latency of a share
(``AppSettings.scan_threads``): there each segment of a
``PartitionedAdapter`` is read in parts, the heaviest first, so the largest
segment does not keep one thread busy long after the others. On a local
disk the work is CPU under the GIL, where more threads only contend, so one
thread reads a local store, whole segments. Entries go through a bounded
queue to the calling thread, the only one using the ``IndexWriter``: it
writes them in batches (``BATCH_ENTRIES`` entries or ``BATCH_SECONDS``, one
transaction each) and hands the versions still without a location to a
small pool computing ``SourceAdapter.footprint`` without network, with the
WGS84 polygon of each native rectangle (``outline_footprints``). An
incremental scan passes the settled version directories the index knows
(``ScanScope.known_versions``): their metadata is not read again and they
are not listed again, so only the full scan (scheduled daily by default)
notices a file removed from or added to one of them. A link names its
version itself (``SourceEntry.version_path``); the scanner never confirms
links, which is an on-demand job. A producer without links (its slots carry
its own key) names the current version of a slot itself
(``CurrentVersionAdapter``): the pass asks for the slots it touched when it
finishes. After a pass over the whole store, the stations of each provider's
station catalog (``StationCatalogAdapter``) are read again when the current
version of the catalog changed.

Every complete pass without units marks unseen versions missing (with the
date); a full pass removes the versions an earlier pass already marked. A
store found unavailable (its probe fails, it lists no segment while the
index holds its entries, or reading fails) gets no missing marks: the pass
is abandoned and the store recorded ``unavailable`` with the time.

``refresh_view`` rescans the units of a map view before an answer and acts
only on the slots the producer returned for them.
"""

import gc
import queue
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from archiwista.config import AppSettings
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.index.geometry import (
    WGS84,
    BBox,
    box_within,
    is_box,
    is_wgs84,
    outline_wgs84,
    outlines_wgs84,
    polygon_bounds,
)
from archiwista.index.projects import ProjectScanSummary, scan_projects
from archiwista.index.queries import IndexQueries
from archiwista.index.types import (
    BatchResult,
    CurrentVersionLookup,
    IndexStatus,
    KeyedSlot,
    PassSummary,
)
from archiwista.index.writer import IndexWriter
from archiwista.messages import message, with_detail
from archiwista.sources import (
    CurrentVersionAdapter,
    Footprint,
    GeoAdapter,
    GeoJSONGeometry,
    PartitionedAdapter,
    ScanScope,
    SegmentDescriptionAdapter,
    SegmentedAdapter,
    SourceAdapter,
    SourceEntry,
    SourcePartition,
    StationCatalogAdapter,
)

type ScanMode = Literal["incremental", "full"]
type NoticeLevel = Literal["info", "warning"]

SCAN_MODES: tuple[ScanMode, ...] = ("incremental", "full")
# A batch of entries written in one transaction: this many entries, or what
# arrived within this many seconds of its first entry.
BATCH_ENTRIES = 1000
BATCH_SECONDS = 1.0
# Threads computing footprints of a store on a share (CPU and small header
# reads, no network); a local store uses one.
FOOTPRINT_THREADS = 4
# Units one view refresh may name (SPEC 4.5: a view of at most 500 slots).
REFRESH_VIEW_MAX_UNITS = 500

# Entries a reading thread hands over at once, and chunks queued per thread:
# the queue bounds the memory of entries read but not yet written.
_READ_CHUNK = 256
_QUEUE_CHUNKS_PER_THREAD = 2
# Entries per footprint task, and tasks waiting per footprint thread before
# the writing thread waits for the oldest one.
_FOOTPRINT_CHUNK = 128
_FOOTPRINT_BACKLOG = 2
# How often a waiting thread checks for written footprints or a stop.
_POLL_SECONDS = 0.1
# Allocations between young-generation collections while a scan runs.
_GC_YOUNG_THRESHOLD = 50_000


@dataclass(frozen=True, slots=True)
class ScanProgress:
    """Progress of a scan: ``current`` of ``total`` segments are read.

    ``segment`` is the segment just finished: ``None`` in the first event
    (``current`` 0) and for a producer without segments. ``entries`` counts
    the entries read so far by the whole scan.
    """

    segment: str | None
    current: int
    total: int
    entries: int


@dataclass(frozen=True, slots=True)
class ScanNotice:
    """Something the person should know about a scan.

    ``code`` is stable for programs; ``message`` is a catalog message.
    """

    level: NoticeLevel
    code: str
    message: str


type ScanEvent = ScanProgress | ScanNotice
type ScanListener = Callable[[ScanEvent], None]


@dataclass(frozen=True, slots=True)
class SegmentScan:
    """Entries one segment gave and the seconds its reading took.

    A segment read in parts in parallel counts the seconds of every part.
    """

    segment: str | None
    entries: int
    seconds: float


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """The result of one scan of a store, for the job summary.

    Attributes
    ----------
    store, producer : str
        Configured store id and the adapter's producer.
    mode : {"incremental", "full"}
        Kind of the scan.
    segment : str or None
        The only segment scanned; ``None`` for the whole store.
    started_at : datetime
        Start of the scan (UTC).
    seconds : float
        Duration, projects included.
    entries : int
        Entries read from the store.
    versions_written, links_changed, issues_added : int
        Totals of the written batches (``BatchResult``).
    footprints_written : int
        Versions that got a location.
    footprints_failed : int
        Versions whose location the producer could not compute; they stay
        pending and are tried again by the next scan.
    finished : PassSummary
        What finishing the pass changed (missing, removed, unlinked...).
    segments : tuple[SegmentScan, ...]
        Entries and reading time of each segment, by segment.
    projects : ProjectScanSummary or None
        The pass over the project directories after a scan of the whole
        store; ``None`` after a scan of one segment.
    """

    store: str
    producer: str
    mode: ScanMode
    segment: str | None
    started_at: datetime
    seconds: float
    entries: int
    versions_written: int
    links_changed: int
    issues_added: int
    footprints_written: int
    footprints_failed: int
    finished: PassSummary
    segments: tuple[SegmentScan, ...]
    projects: ProjectScanSummary | None = None


def scan_store(
    adapter: SourceAdapter,
    writer: IndexWriter,
    settings: AppSettings,
    store: str,
    *,
    mode: ScanMode = "incremental",
    segment: str | None = None,
    on_event: ScanListener | None = None,
) -> ScanSummary:
    """Scan the adapter's directory of a configured store into the index.

    Segments of a store on a share are read in parallel, in parts where the
    producer splits them (``AppSettings.scan_threads``), those of a local
    store by one thread; batches are written by the calling thread and
    footprints computed without network. After a pass over the whole store,
    the producer's projects are scanned too (``scan_projects``). A producer
    that lists no segments but can describe them (``SegmentDescriptionAdapter``)
    is read whole, and the segments its entries named are described at the
    end of the pass. A producer that names the current version of a slot
    itself (``CurrentVersionAdapter``) is asked for the slots the pass touched
    when it finishes. A producer with station catalogs
    (``StationCatalogAdapter``) has the stations of each provider's current
    catalog read after a pass over the whole store, when that version changed.

    Parameters
    ----------
    adapter : SourceAdapter
        The producer of the scanned directory (``StoreConfig.roots``).
    writer : IndexWriter
        Writer of the local index, used only by the calling thread. The
        store must be in the index (``IndexWriter.sync_stores``).
    settings : AppSettings
        Current settings: the store, ``scan_threads``, ``project_dirs`` and
        all ``stores`` (for the projects).
    store : str
        Configured store id.
    mode : {"incremental", "full"}, default "incremental"
        ``incremental`` neither reads the metadata of the versions in the
        index's settled version directories nor lists those directories
        (``IndexWriter.known_versions``); ``full`` reads everything again
        and removes versions an earlier pass marked missing that are still
        not there.
    segment : str or None, optional
        Scan only this segment of a ``SegmentedAdapter``; nothing outside it
        is marked and no project is scanned.
    on_event : callable, optional
        Receives ``ScanProgress`` and ``ScanNotice`` events in the calling
        thread.

    Returns
    -------
    ScanSummary
        Counts, per-segment times and the projects' pass.

    Raises
    ------
    SourceUnavailableError
        The store is unavailable: its probe fails, it has no segment while
        the index holds entries of it (an empty mount point), or reading
        fails. The pass is abandoned and the store recorded ``unavailable``
        with the message.
    ProducerError
        The producer rejected the scan; the pass is abandoned.
    ValueError
        Unknown mode or store, or a segment for a producer without segments.
    """
    if mode not in SCAN_MODES:
        raise ValueError(f"unknown scan mode {mode!r}")
    target = _target(settings, store, adapter.producer)
    root = target.root
    if segment is not None and not isinstance(adapter, SegmentedAdapter):
        raise ValueError(f"producer {adapter.producer!r} has no segments")
    emit: ScanListener = on_event or _ignore
    started_at = datetime.now(UTC)
    clock = time.perf_counter()
    full = mode == "full"
    try:
        listed = _reachable_segments(adapter, root)
    except SourceUnavailableError as error:
        writer.set_store_status(store, "unavailable", detail=str(error))
        raise
    segments: tuple[str | None, ...] = (None,)
    if listed is not None and isinstance(adapter, SegmentedAdapter):
        segments = listed if segment is None else (segment,)
        writer.write_segments(
            store,
            adapter.producer,
            [adapter.describe_segment(name) for name in listed if name in segments],
        )
    totals = _Totals()
    footprints = _Footprints(adapter, writer, store, target.footprint_threads)
    with _rare_collections():
        writer.begin_pass(store, adapter.producer, segment=segment, full=full)
        try:
            if listed == () and writer.holds_entries():
                raise _empty_store(root)
            known = {name: writer.known_versions(name) for name in segments}
            scopes = _scopes(
                adapter, root, known, full=full, threads=target.reading_threads
            )
            emit(ScanProgress(segment=None, current=0, total=len(segments), entries=0))
            readers = _Readers(adapter, root, scopes, target.reading_threads)
            try:
                _stream(writer, readers, footprints, totals, emit, scopes)
            finally:
                readers.close()
            footprints.finish()
            if listed is None and isinstance(adapter, SegmentDescriptionAdapter):
                # No list of segments to describe first: describe the ones the
                # entries named, for a producer that cannot read one alone.
                writer.write_segments(
                    store,
                    adapter.producer,
                    [
                        adapter.describe_segment(name)
                        for name in sorted(totals.segments_seen)
                    ],
                )
            # Listings of a share unmounted mid-scan end empty without an error.
            if segment is None and totals.entries == 0 and writer.holds_entries():
                raise _empty_store(root)
            if _reachable_segments(adapter, root) == () and writer.holds_entries():
                raise _empty_store(root)
            finished = writer.finish_pass(current=_current_lookup(adapter, root))
            if segment is None and isinstance(adapter, StationCatalogAdapter):
                _index_stations(
                    adapter, adapter.producer, writer, store, root, full=full, emit=emit
                )
        except SourceUnavailableError as error:
            writer.abandon_pass()
            writer.set_store_status(store, "unavailable", detail=str(error))
            raise
        except BaseException:
            writer.abandon_pass()
            raise
        finally:
            footprints.close()
    projects = None
    if segment is None:
        projects = scan_projects(
            adapter,
            writer,
            project_dirs=settings.project_dirs,
            stores=settings.stores,
        )
        for directory in projects.unreadable_dirs:
            text = message("project.dir_unreadable", path=directory)
            emit(ScanNotice("warning", "project_dir_unreadable", text))
    else:
        writer.set_store_status(store, "available")
    if footprints.failed:
        text = message(
            "scan.footprints_failed", count=footprints.failed, detail=footprints.failure
        )
        emit(ScanNotice("warning", "footprints_failed", text))
    return ScanSummary(
        store=store,
        producer=adapter.producer,
        mode=mode,
        segment=segment,
        started_at=started_at,
        seconds=time.perf_counter() - clock,
        entries=totals.entries,
        versions_written=totals.versions_written,
        links_changed=totals.links_changed,
        issues_added=totals.issues_added,
        footprints_written=footprints.written,
        footprints_failed=footprints.failed,
        finished=finished,
        segments=tuple(sorted(totals.segments, key=lambda item: item.segment or "")),
        projects=projects,
    )


def refresh_view(
    adapter: SourceAdapter,
    writer: IndexWriter,
    queries: IndexQueries,
    settings: AppSettings,
    store: str,
    segment: str | None,
    units: Sequence[str],
    *,
    known_slots: Collection[str] = (),
    timeout_s: float | None = None,
) -> IndexStatus:
    """Rescan the units of a map view so the answer about it is current.

    The units are read in disjoint batches, in parallel on a share
    (``AppSettings.scan_threads``), then written in one pass limited to the
    slots the producer returned entries for: their new versions and links
    are added and their unseen versions marked missing. A slot that
    returned nothing (gone, or not reached by the unit) is left to the next
    scan of the store, so a unit that does not name its slot never marks
    anything missing.

    Parameters
    ----------
    adapter : SourceAdapter
        The producer of the store directory.
    writer : IndexWriter
        Writer of the local index, used only by the calling thread.
    queries : IndexQueries
        Queries of the same index (the returned state).
    settings : AppSettings
        Current settings: the store and ``scan_threads``.
    store : str
        Configured store id, in the index (``IndexWriter.sync_stores``).
    segment : str or None
        Segment of the units (``None`` for a producer without segments).
    units : Sequence[str]
        Unit identifiers of the segment (``ScanScope.units``): sheet codes
        of ``SheetGridAdapter.sheet_grid`` or units of indexed slots
        (``SlotUnit.unit``); at most ``REFRESH_VIEW_MAX_UNITS``.
    known_slots : Collection[str], optional
        Indexed slots of these units (``SlotUnit.slot`` of
        ``IndexQueries.slots_in_bbox``): the settled version directories of
        these slots and of the slots beside them
        (``IndexWriter.slots_beside``) are neither read nor listed again.
        Without them every version of the units is read.
    timeout_s : float or None, optional
        Longest time for reading the store; when it runs out nothing is
        written and ``TimeoutError`` is raised.

    Returns
    -------
    IndexStatus
        The index after the refresh. An unavailable store is recorded as
        such, changes no entry and shows ``stale`` in its state.

    Raises
    ------
    TimeoutError
        Reading the units took longer than ``timeout_s``.
    ProducerError
        The producer rejected a unit or the segment.
    ValueError
        Unknown store or more than ``REFRESH_VIEW_MAX_UNITS`` units.
    """
    target = _target(settings, store, adapter.producer)
    root = target.root
    wanted = tuple(dict.fromkeys(units))
    if len(wanted) > REFRESH_VIEW_MAX_UNITS:
        raise ValueError(
            f"a view refresh takes at most {REFRESH_VIEW_MAX_UNITS} units,"
            f" got {len(wanted)}"
        )
    if not wanted:
        return queries.status()
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    try:
        if _reachable_segments(adapter, root) == () and _indexed(queries, store):
            raise _empty_store(root)
        known = _slot_versions(writer, store, adapter.producer, segment, known_slots)
        scopes = [
            ScanScope(segment=segment, units=batch, known_versions=known)
            for batch in _unit_batches(wanted, target.reading_threads)
        ]
        readers = _Readers(adapter, root, scopes, target.reading_threads)
        try:
            entries = _collect(readers, deadline, timeout_s)
        finally:
            readers.close()
        if _reachable_segments(adapter, root) == () and _indexed(queries, store):
            raise _empty_store(root)
    except SourceUnavailableError as error:
        writer.set_store_status(store, "unavailable", detail=str(error))
        return queries.status()
    if entries:
        _write_view(adapter, writer, store, segment, entries, target)
    writer.set_store_status(store, "available")
    return queries.status()


def outline_footprints(
    adapter: SourceAdapter, items: Sequence[tuple[SourceEntry, Footprint]]
) -> tuple[list[tuple[SourceEntry, Footprint]], list[str]]:
    """Give new footprints the WGS84 polygon of their native rectangle.

    For a producer with coordinate operations (``GeoAdapter``), a footprint
    whose native outline is a rectangle gets that rectangle with its edges
    densified and moved by the producer's pinned operation
    (``outline_wgs84``; one ``transform`` call per CRS) as its WGS84
    outline (decision 4 of the v0.2 plan). The producer's own WGS84 outline
    stays when it is not a box, or when it lies within the polygon: then it
    is the tighter one (a PL-1992 sheet is a longitude/latitude rectangle
    whose native outline is its envelope). A producer without coordinate
    operations keeps its own outlines.

    Parameters
    ----------
    adapter : SourceAdapter
        The producer that computed the footprints.
    items : Sequence[tuple[SourceEntry, Footprint]]
        Entries with their ``SourceAdapter.footprint``.

    Returns
    -------
    tuple[list[tuple[SourceEntry, Footprint]], list[str]]
        The entries with their outlines, in order, without those whose
        polygon failed; and the messages of those failures (no pinned
        operation, a position the operation cannot move).
    """
    if not isinstance(adapter, GeoAdapter):
        return list(items), []
    groups: dict[str, list[tuple[int, BBox]]] = {}
    for index, (_, found) in enumerate(items):
        native = _native_rectangle(found)
        if native is not None and found.native_crs is not None:
            groups.setdefault(found.native_crs, []).append((index, native))
    outlined: list[tuple[SourceEntry, Footprint] | None] = list(items)
    failures: list[str] = []
    for crs, members in groups.items():
        polygons = _outline_group(adapter, crs, [native for _, native in members])
        for (index, _), polygon in zip(members, polygons, strict=True):
            entry, found = items[index]
            if isinstance(polygon, str):
                outlined[index] = None
                failures.append(polygon)
                continue
            own = None if found.wgs84 is None else polygon_bounds(found.wgs84)
            if own is None or not box_within(own, polygon):
                outlined[index] = (entry, replace(found, wgs84=polygon))
    return [item for item in outlined if item is not None], failures


@dataclass(frozen=True, slots=True)
class _Target:
    """The scanned directory of a store and the threads that read it."""

    root: Path
    reading_threads: int
    footprint_threads: int


@dataclass(slots=True)
class _Totals:
    """Running totals of the batches the writing thread wrote."""

    entries: int = 0
    versions_written: int = 0
    links_changed: int = 0
    issues_added: int = 0
    segments: list[SegmentScan] = field(default_factory=list)
    # Segments the entries named: for a producer that lists none.
    segments_seen: set[str] = field(default_factory=set)

    def add(self, result: BatchResult) -> None:
        self.versions_written += result.versions_written
        self.links_changed += result.links_changed
        self.issues_added += result.issues_added


@dataclass(frozen=True, slots=True)
class _ReadDone:
    """A reading thread finished its ``iter_entries`` call."""

    segment: str | None
    entries: int
    seconds: float


@dataclass(frozen=True, slots=True)
class _ReadFailed:
    """A reading thread stopped with an error, raised in the writing thread."""

    error: Exception


type _QueueItem = list[SourceEntry] | _ReadDone | _ReadFailed


class _Readers:
    """``iter_entries`` calls in a thread pool feeding one bounded queue.

    Each call runs in one thread, from the first entry to the last. The
    writing thread takes chunks of entries with ``get``; ``close`` stops the
    calls (each at its next entry) and waits for the threads.
    """

    def __init__(
        self,
        adapter: SourceAdapter,
        root: Path,
        scopes: Sequence[ScanScope],
        threads: int,
    ) -> None:
        self._adapter = adapter
        self._root = root
        workers = max(1, min(threads, len(scopes)))
        self._queue: queue.Queue[_QueueItem] = queue.Queue(
            maxsize=_QUEUE_CHUNKS_PER_THREAD * workers
        )
        self._stop = threading.Event()
        self.pending = len(scopes)
        self._pool = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="archiwista-scan"
        )
        for scope in scopes:
            self._pool.submit(self._read, scope)

    def get(self, timeout: float | None) -> list[SourceEntry] | _ReadDone | None:
        """Return the next chunk or finished call; ``None`` after ``timeout``.

        Raises
        ------
        Exception
            The error that stopped a reading thread.
        """
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, _ReadFailed):
            raise item.error
        if isinstance(item, _ReadDone):
            self.pending -= 1
        return item

    def close(self) -> None:
        """Stop the reading threads and wait for them."""
        self._stop.set()
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _read(self, scope: ScanScope) -> None:
        started = time.perf_counter()
        count = 0
        chunk: list[SourceEntry] = []
        entries = None
        try:
            entries = self._adapter.iter_entries(self._root, scope=scope)
            for entry in entries:
                if self._stop.is_set():
                    return
                chunk.append(entry)
                if len(chunk) == _READ_CHUNK:
                    count += len(chunk)
                    if not self._put(chunk):
                        return
                    chunk = []
            count += len(chunk)
            if chunk and not self._put(chunk):
                return
            self._put(_ReadDone(scope.segment, count, time.perf_counter() - started))
        except Exception as error:  # handed to the writing thread
            self._put(_ReadFailed(error))
        finally:
            close = getattr(entries, "close", None)
            if close is not None:
                close()

    def _put(self, item: _QueueItem) -> bool:
        """Queue an item, waiting for room; ``False`` when stopped first."""
        while not self._stop.is_set():
            try:
                self._queue.put(item, timeout=_POLL_SECONDS)
            except queue.Full:
                continue
            return True
        return False


@dataclass(frozen=True, slots=True)
class _Located:
    """Footprints of one task and the messages of entries that failed."""

    items: tuple[tuple[SourceEntry, Footprint], ...]
    failures: tuple[str, ...]


class _Footprints:
    """Footprints computed in a small pool and written by the writing thread.

    ``submit`` and ``harvest`` write finished tasks in submission order;
    ``finish`` waits for the rest. Too many waiting tasks make ``submit``
    wait for the oldest one, which bounds the entries held in memory.
    """

    def __init__(
        self,
        adapter: SourceAdapter,
        writer: IndexWriter,
        store: str,
        threads: int,
    ) -> None:
        self._adapter = adapter
        self._writer = writer
        self._store = store
        self._limit = _FOOTPRINT_BACKLOG * threads
        self._pool = ThreadPoolExecutor(
            max_workers=threads, thread_name_prefix="archiwista-footprint"
        )
        self._pending: deque[Future[_Located]] = deque()
        self.written = 0
        self.failed = 0
        self.failure: str | None = None

    def submit(self, entries: Sequence[SourceEntry]) -> None:
        """Compute the footprints of entries (``BatchResult.needs_footprint``)."""
        for start in range(0, len(entries), _FOOTPRINT_CHUNK):
            chunk = entries[start : start + _FOOTPRINT_CHUNK]
            self._pending.append(self._pool.submit(_locate, self._adapter, chunk))
        while len(self._pending) > self._limit:
            self._write(self._pending.popleft().result())

    def harvest(self) -> None:
        """Write the footprints of the tasks finished so far."""
        while self._pending and self._pending[0].done():
            self._write(self._pending.popleft().result())

    def finish(self) -> None:
        """Wait for every task and write its footprints."""
        while self._pending:
            self._write(self._pending.popleft().result())

    def close(self) -> None:
        """Drop the tasks not started and wait for the running ones."""
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _write(self, located: _Located) -> None:
        if located.items:
            self.written += self._writer.write_footprints(self._store, located.items)
        if located.failures:
            self.failed += len(located.failures)
            self.failure = self.failure or located.failures[0]


def _locate(adapter: SourceAdapter, entries: Sequence[SourceEntry]) -> _Located:
    """Footprints without network, with their outlines; a failure stays pending."""
    items: list[tuple[SourceEntry, Footprint]] = []
    failures: list[str] = []
    for entry in entries:
        try:
            items.append((entry, adapter.footprint(entry)))
        except (ProducerError, OSError) as error:
            # No pinned operation, or a file gone since the listing (SPEC 4.6).
            failures.append(str(error))
    outlined, failed = outline_footprints(adapter, items)
    return _Located(tuple(outlined), (*failures, *failed))


def _native_rectangle(found: Footprint) -> BBox | None:
    """Return the native rectangle to outline a footprint with, if any.

    ``None`` also when the producer's own WGS84 outline is a polygon other
    than a box: it stays as it is.
    """
    if found.location != "footprint" or found.native is None:
        return None
    own = None if found.wgs84 is None else polygon_bounds(found.wgs84)
    if found.wgs84 is not None and own is not None and not is_box(found.wgs84, own):
        return None
    native = polygon_bounds(found.native)
    return native if native is not None and is_box(found.native, native) else None


def _outline_group(
    adapter: GeoAdapter, crs: str, natives: Sequence[BBox]
) -> list[GeoJSONGeometry | str]:
    """WGS84 polygons of rectangles in one CRS; a failure is its message.

    One ``transform`` call for all; when it fails, each rectangle is moved
    alone, so one that cannot be does not fail the others.
    """
    try:
        transformer = None if is_wgs84(crs) else adapter.transformer(crs, WGS84)
    except ProducerError as error:
        return [str(error)] * len(natives)
    try:
        return list(outlines_wgs84(natives, crs, transformer))
    except (ProducerError, ValueError):
        pass
    polygons: list[GeoJSONGeometry | str] = []
    for native in natives:
        try:
            polygons.append(outline_wgs84(native, crs, transformer))
        except (ProducerError, ValueError) as error:
            polygons.append(str(error))
    return polygons


def _stream(
    writer: IndexWriter,
    readers: _Readers,
    footprints: _Footprints,
    totals: _Totals,
    emit: ScanListener,
    scopes: Sequence[ScanScope],
) -> None:
    """Write what the reading threads give, in batches, until they finish.

    A segment read in parts is read when its last part is.
    """
    remaining = Counter(scope.segment for scope in scopes)
    entries: Counter[str | None] = Counter()
    seconds: dict[str | None, float] = dict.fromkeys(remaining, 0.0)
    batch: list[SourceEntry] = []
    deadline = 0.0
    while readers.pending:
        wait = _POLL_SECONDS
        if batch:
            wait = min(wait, max(0.0, deadline - time.monotonic()))
        item = readers.get(wait)
        if isinstance(item, _ReadDone):
            segment = item.segment
            entries[segment] += item.entries
            seconds[segment] += item.seconds
            remaining[segment] -= 1
            if remaining[segment] == 0:
                totals.segments.append(
                    SegmentScan(segment, entries[segment], seconds[segment])
                )
                emit(
                    ScanProgress(
                        segment=segment,
                        current=len(totals.segments),
                        total=len(remaining),
                        entries=totals.entries,
                    )
                )
        elif item is not None:
            if not batch:
                deadline = time.monotonic() + BATCH_SECONDS
            batch.extend(item)
            totals.entries += len(item)
        while len(batch) >= BATCH_ENTRIES:
            _write_batch(writer, batch[:BATCH_ENTRIES], footprints, totals)
            batch = batch[BATCH_ENTRIES:]
            deadline = time.monotonic() + BATCH_SECONDS
        if batch and time.monotonic() >= deadline:
            _write_batch(writer, batch, footprints, totals)
            batch = []
        footprints.harvest()
    if batch:
        _write_batch(writer, batch, footprints, totals)


def _write_batch(
    writer: IndexWriter,
    batch: Sequence[SourceEntry],
    footprints: _Footprints,
    totals: _Totals,
) -> None:
    result = writer.write_entries(batch)
    totals.add(result)
    totals.segments_seen.update(entry.segment for entry in batch if entry.segment)
    footprints.submit(result.needs_footprint)


def _collect(
    readers: _Readers, deadline: float | None, timeout_s: float | None
) -> list[SourceEntry]:
    """Every entry of the reading threads, within the deadline."""
    entries: list[SourceEntry] = []
    while readers.pending:
        wait = None
        if deadline is not None:
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise TimeoutError(
                    message("api.refresh_view_timeout", seconds=timeout_s)
                )
        item = readers.get(wait)
        if isinstance(item, list):
            entries.extend(item)
    return entries


def _write_view(
    adapter: SourceAdapter,
    writer: IndexWriter,
    store: str,
    segment: str | None,
    entries: Sequence[SourceEntry],
    target: _Target,
) -> None:
    """Write a view's entries in a pass over the slots they belong to."""
    slots = {key for entry in entries if (key := _slot_key(entry)) is not None}
    writer.begin_pass(store, adapter.producer, segment=segment, slots=slots)
    totals = _Totals()
    footprints = _Footprints(adapter, writer, store, target.footprint_threads)
    try:
        for start in range(0, len(entries), BATCH_ENTRIES):
            batch = entries[start : start + BATCH_ENTRIES]
            _write_batch(writer, batch, footprints, totals)
        footprints.finish()
        writer.finish_pass(current=_current_lookup(adapter, target.root))
    except BaseException:
        writer.abandon_pass()
        raise
    finally:
        footprints.close()


def _slot_key(entry: SourceEntry) -> str | None:
    """Return the slot an entry belongs to, as the writer keys it.

    ``None`` for a problem of a whole segment (it has no slot).
    """
    if entry.kind == "problem" and entry.slot_path is None:
        return None
    return (entry.slot_path or entry.relative_path).as_posix()


def _slot_versions(
    writer: IndexWriter,
    store: str,
    producer: str,
    segment: str | None,
    slots: Collection[str],
) -> Mapping[str, tuple[str, ...]]:
    """Settled version directories of some slots and of the slots beside them.

    None without slots.
    """
    if not slots:
        return {}
    near = writer.slots_beside(store, slots)
    writer.begin_pass(store, producer, segment=segment, slots=near)
    try:
        return writer.known_versions(segment)
    finally:
        writer.abandon_pass()


def _scopes(
    adapter: SourceAdapter,
    root: Path,
    known: Mapping[str | None, Mapping[str, tuple[str, ...]]],
    *,
    full: bool,
    threads: int,
) -> list[ScanScope]:
    """Return the ``iter_entries`` calls of a scan, the heaviest first.

    With several threads (a share) each segment of a ``PartitionedAdapter``
    is read in parts, split in parallel; one thread reads whole segments.
    Weights come from the index's settled versions (``known``) also for a
    full scan, which passes none to the producer.
    """
    parts: dict[str | None, tuple[SourcePartition, ...]] = {}
    named = [name for name in known if name is not None]
    if threads > 1 and named and isinstance(adapter, PartitionedAdapter):
        partitioned: PartitionedAdapter = adapter

        def split(name: str) -> tuple[SourcePartition, ...]:
            return partitioned.partitions(root, name, known[name])

        with ThreadPoolExecutor(
            max_workers=min(threads, len(named)),
            thread_name_prefix="archiwista-split",
        ) as pool:
            parts.update(zip(named, pool.map(split, named), strict=True))
    work: list[tuple[int, ScanScope]] = []
    for name, versions in known.items():
        skip: Mapping[str, tuple[str, ...]] = {} if full else versions
        found = parts.get(name)
        if found:
            work.extend(
                (
                    part.weight,
                    ScanScope(segment=name, partition=part.key, known_versions=skip),
                )
                for part in found
            )
        else:
            weight = sum(map(len, versions.values()))
            work.append((weight, ScanScope(segment=name, known_versions=skip)))
    # Stable: parts of equal weight keep the producer's order.
    work.sort(key=lambda item: -item[0])
    return [scope for _, scope in work]


def _unit_batches(units: Sequence[str], threads: int) -> list[tuple[str, ...]]:
    """Contiguous, disjoint batches of units, one per thread at most.

    Neighbouring units share directories, which one call lists once.
    """
    count = max(1, min(threads, len(units)))
    size = -(-len(units) // count)
    return [tuple(units[start : start + size]) for start in range(0, len(units), size)]


def _reachable_segments(adapter: SourceAdapter, root: Path) -> tuple[str, ...] | None:
    """Probe the store and list its segments (``None`` without segments).

    Raises
    ------
    SourceUnavailableError
        The probe is not ``available`` (with its reason and hint when the
        producer gave them) or the store cannot be listed.
    """
    state = adapter.probe(root)
    if state.status != "available":
        text = message("store.unreadable", path=root)
        raise SourceUnavailableError(
            with_detail(text, state.detail), reason=state.reason, hint=state.hint
        )
    if isinstance(adapter, SegmentedAdapter):
        return tuple(adapter.segments(root))
    return None


def _current_lookup(adapter: SourceAdapter, root: Path) -> CurrentVersionLookup | None:
    """Return the producer's answer for a slot's current version, if it gives one."""
    if not isinstance(adapter, CurrentVersionAdapter):
        return None
    producer: CurrentVersionAdapter = adapter

    def lookup(key: str) -> Path | None:
        return producer.current_version(root, key)

    return lookup


def _index_stations(
    catalogs: StationCatalogAdapter,
    producer: str,
    writer: IndexWriter,
    store: str,
    root: Path,
    *,
    full: bool,
    emit: ScanListener,
) -> None:
    """Keep each provider's stations those of the current version of its catalog.

    Run after the pass, outside its transaction: a catalog is read only when
    the current version of its slot is not the one its stations were read from
    (a full scan reads every catalog again). A provider whose catalog has no
    slot or no current version anymore has no stations; one whose current
    version the producer refuses has none either, and the scan says so.

    Raises
    ------
    SourceUnavailableError
        The system cannot read a catalog.
    """
    current: dict[str, tuple[KeyedSlot, str]] = {}
    for slot in writer.keyed_slots(store, producer):
        provider = catalogs.station_catalog(slot.key)
        if provider is not None and slot.current is not None:
            current[provider] = (slot, slot.current)
    read = writer.station_catalogs(store, producer)
    for provider in sorted(read.keys() - current.keys()):
        writer.drop_stations(store, provider)
    for provider in sorted(current):
        slot, version = current[provider]
        known = read.get(provider)
        unchanged = known is not None and (known.slot, known.version) == (
            slot.path,
            version,
        )
        if unchanged and not full:
            continue
        try:
            stations = catalogs.read_stations(root, Path(version))
        except ProducerError as error:
            writer.drop_stations(store, provider)
            text = message(
                "scan.stations_unreadable",
                provider=provider,
                path=version,
                detail=str(error),
            )
            emit(ScanNotice("warning", "stations_unreadable", text))
            continue
        writer.replace_stations(
            store,
            producer,
            provider,
            slot=slot.path,
            version=version,
            stations=stations,
        )


def _indexed(queries: IndexQueries, store: str) -> bool:
    """Whether the index holds slots or versions of a store."""
    return any(
        state.store == store and (state.slots or state.versions)
        for state in queries.status().stores
    )


def _empty_store(root: Path) -> SourceUnavailableError:
    return SourceUnavailableError(message("scan.store_empty", path=root))


def _target(settings: AppSettings, store: str, producer: str) -> _Target:
    """Resolve the producer's directory of a store and its threads.

    Threads hide the latency of a share. On a local disk the scan is CPU
    under the GIL and more threads only contend: an unchanged incremental
    scan of the 50 000-slot store took 20 s with one reading thread, 23 s
    with two and 27 s with eight, and a full scan was faster with one
    footprint thread than with four. A local store gets one of each.
    """
    config = settings.store(store)
    if config is None:
        raise ValueError(f"store {store!r} is not configured")
    root = config.roots().get(producer)
    if root is None:
        raise ValueError(f"store {store!r} has no {producer} directory")
    if config.kind == "share":
        return _Target(root, settings.scan_threads, FOOTPRINT_THREADS)
    return _Target(root, 1, 1)


@contextmanager
def _rare_collections() -> Iterator[None]:
    """Run the cyclic garbage collector less often during a scan.

    A scan allocates millions of short-lived objects without cycles; with
    the default thresholds collections took about a second of an unchanged
    incremental scan of the 50 000-slot store. The thresholds are
    process-wide (a scan runs in its own worker process) and restored.
    """
    saved = gc.get_threshold()
    gc.set_threshold(_GC_YOUNG_THRESHOLD, *saved[1:])
    try:
        yield
    finally:
        gc.set_threshold(*saved)


def _ignore(event: ScanEvent) -> None:
    """Drop the events of a scan nobody follows."""
