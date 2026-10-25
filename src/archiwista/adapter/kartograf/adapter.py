"""Kartograf store reads behind Archiwista's producer-neutral source interface.

Only names of ``kartograf.__all__`` are used. A scan maps ``iter_store``
entries to ``SourceEntry`` values carrying the metadata of the same pass. The
index's known version directories go to ``iter_store`` as a ``skip_versions``
mapping (directory → file names), so Kartograf neither reads their sidecars
nor lists them again; a segment splits into ``list_partitions`` parts read
in parallel. A scan never calls ``link_target``: that is the on-demand
``confirm_link``. Kartograf's exceptions surface as ``ProducerError`` with
the message unchanged.
"""

import json
import os
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from kartograf import (
    BBox,
    InvalidSidecarError,
    KartografError,
    SheetParser,
    StoreEntry,
    __version__,
    countries_for_bbox,
    describe_segment,
    file_footprint,
    find_sheets_for_bbox,
    get_project_status,
    iter_store,
    link_target,
    list_partitions,
    list_segments,
    open_project,
    pinned_transform,
    read_sidecar,
)

from archiwista.adapter.kartograf import PACKAGE, PRODUCER, SCHEMAS
from archiwista.adapter.kartograf.marker import refusal
from archiwista.adapter.kartograf.unit_cache import UnitBBoxCache
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.messages import message, with_detail
from archiwista.sources import (
    CoordinateTransformer,
    EntryMeta,
    FloatArray,
    Footprint,
    GeoJSONGeometry,
    ProjectInfo,
    ProjectPin,
    ProjectTask,
    ScanScope,
    SheetGrid,
    SourceContext,
    SourceEntry,
    SourcePartition,
    SourceSegment,
    SourceState,
    SourceStatus,
)

UNIT_CACHE_FILE = "unit_bboxes.sqlite"

_WGS84 = "EPSG:4326"
# Problems of a whole segment: they have no slot.
_SEGMENT_PROBLEMS = frozenset({"unknown_segment", "legacy_campaigns", "stale_incoming"})
# Project and task states by increasing severity.
_STATUS_ORDER = ("ok", "not_downloaded", "missing", "corrupt")


class KartografAdapter:
    """Read a Kartograf store (its ``--output`` directory) for Archiwista.

    Parameters
    ----------
    context : SourceContext
        ``cache_dir`` holds the local memory of unit outlines
        (``unit_bboxes.sqlite``), created when the first outline is stored.
    supported_versions : str
        Kartograf versions Archiwista supports, e.g. ``"<0.9,>=0.8.0"``.

    Notes
    -----
    Besides ``SourceAdapter`` it implements every optional capability:
    ``SegmentedAdapter``, ``PartitionedAdapter``, ``GeoAdapter``,
    ``LinkCheckAdapter`` and ``SheetGridAdapter``. All methods may run in
    several threads at once; one iterator of ``iter_entries`` belongs to one
    thread.
    """

    producer = PRODUCER
    package = PACKAGE
    schemas: tuple[str, ...] = SCHEMAS

    def __init__(self, context: SourceContext, *, supported_versions: str) -> None:
        self.supported_versions = supported_versions
        self._unit_bboxes = UnitBBoxCache(context.cache_dir / UNIT_CACHE_FILE)

    def probe(self, root: Path) -> SourceState:
        """Report whether ``root`` is a Kartograf store Archiwista reads.

        Parameters
        ----------
        root : Path
            The store root: the directory that holds ``kartograf-store.json``
            and the product directories.

        Returns
        -------
        SourceState
            ``available`` for a store with its marker, for a directory with no
            segment yet (a new store) and for known segments with no file
            below them (no layout yet). ``incompatible`` with a ``reason``
            when Kartograf's own writer would not use the directory:
            ``no_marker`` (known segments with a file and no marker; the hint
            is ``kartograf store init``), ``unsupported_marker`` (a marker that
            is not ``kartograf-store/1``), ``foreign_store`` (the marker of
            another tool) or ``not_a_store`` (segments but none known, e.g.
            the parent of the store). ``error`` when the directory or a marker
            cannot be read.
        """
        try:
            segments = list_segments(root)
            known = [name for name in segments if describe_segment(name).known]
            refused = refusal(root, segments, known)
        except OSError as error:
            return self._state("error", root, detail=str(error))
        if refused is None:
            return self._state("available", root)
        return self._state(
            "incompatible",
            root,
            detail=refused.detail,
            reason=refused.reason,
            hint=refused.hint,
        )

    def iter_entries(
        self, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        """Yield the entries of ``iter_store`` with the metadata of the pass.

        Parameters
        ----------
        root : Path
            Kartograf's ``--output`` directory.
        scope : ScanScope or None, optional
            ``segment`` and ``units`` or ``partition`` narrow the scan;
            ``known_versions`` becomes the ``skip_versions`` mapping: the
            named files of those version directories come back ``skipped``
            without ``meta`` and the directories are not listed.

        Yields
        ------
        SourceEntry
            Links carry the version their sidecar names (``version_path``),
            without ``link_target``; new versions and links carry ``meta``.

        Raises
        ------
        SourceUnavailableError
            The store cannot be listed or becomes unreadable during the scan
            (e.g. a disconnected share).
        ProducerError
            Kartograf rejected the scope (a malformed segment, unit or part).
        """
        return self._entries(root, scope or ScanScope())

    def partitions(
        self, root: Path, segment: str, known_versions: Mapping[str, tuple[str, ...]]
    ) -> tuple[SourcePartition, ...]:
        """Split a segment into the parts of ``list_partitions``.

        Parameters
        ----------
        root : Path
            Kartograf's ``--output`` directory.
        segment : str
            ``<product>/<variant>`` of ``segments``.
        known_versions : Mapping[str, tuple[str, ...]]
            Known version directories (``ScanScope.known_versions``): a
            part's weight is the number of their files below it.

        Returns
        -------
        tuple[SourcePartition, ...]
            Disjoint parts whose ``iter_entries`` together give the
            segment's entries once; none for a segment that is gone.

        Raises
        ------
        SourceUnavailableError
            The store cannot be listed.
        ProducerError
            Kartograf rejected the segment.
        """
        try:
            keys = list_partitions(root, segment)
        except OSError as error:
            raise _unavailable(root, error) from error
        except KartografError as error:
            raise _producer_error(error) from error
        weights = _partition_weights(segment, keys, known_versions)
        return tuple(SourcePartition(key, weights[key]) for key in keys)

    def read_meta(self, entry: SourceEntry) -> EntryMeta:
        """Read the metadata of one entry again, on demand.

        Raises
        ------
        ProducerError
            The sidecar is missing, unreadable or of another schema.
        """
        try:
            sidecar = read_sidecar(Path(entry.store) / entry.relative_path)
        except KartografError as error:
            raise _producer_error(error) from error
        return _entry_meta(
            entry.store, entry.relative_path, sidecar, entry.segment, label=None
        )

    def footprint(self, entry: SourceEntry, *, network: bool = False) -> Footprint:
        """Outline a file with ``file_footprint`` and the local unit memory.

        Parameters
        ----------
        entry : SourceEntry
            An entry of ``iter_entries`` (its sidecar is reused) or one
            rebuilt from the index (its sidecar is read once).
        network : bool, default False
            Allow queries of the unit indexes (PRG, RUIAN, CUZK SM5) for
            outlines missing from the local memory; found ones are kept.

        Returns
        -------
        Footprint
            ``footprint`` with the WGS84 and native outlines; ``country``
            for a file of a whole country; otherwise ``none`` with reason
            ``no_source`` or ``unreadable`` (no readable sidecar).

        Raises
        ------
        ProducerError
            No pinned operation to WGS84 exists, or a unit index failed.
        """
        if entry.kind == "problem":
            return Footprint(location="none", reason="unreadable")
        handle = entry.handle
        store_entry = handle if isinstance(handle, StoreEntry) else _rebuilt(entry)
        if store_entry is None:
            return Footprint(location="none", reason="unreadable")
        try:
            found = file_footprint(
                store_entry, network=network, cache=self._unit_bboxes
            )
        except KartografError as error:
            raise _producer_error(error) from error
        if found is not None:
            return Footprint(
                location="footprint",
                wgs84=_polygon(found.wgs84),
                native=_polygon(found.native),
                source=str(found.source),
                native_crs=str(found.native.crs),
            )
        sidecar = store_entry.sidecar or _readable_sidecar(store_entry.path)
        if sidecar is None:
            return Footprint(location="none", reason="unreadable")
        if _mapping(sidecar.request).get("whole_country") is True:
            return Footprint(location="country", source="country")
        return Footprint(location="none", reason="no_source")

    def read_project(self, path: Path) -> ProjectInfo:
        """Read a project manifest strictly with ``open_project``.

        Raises
        ------
        ProducerError
            No manifest or an invalid one; Kartograf's message names the
            place.
        """
        try:
            project = open_project(path)
        except KartografError as error:
            raise _producer_error(error) from error
        return _project_info(project)

    def project_status(self, path: Path) -> ProjectInfo:
        """Check pinned versions with ``get_project_status`` (no hashing).

        Returns
        -------
        ProjectInfo
            Each task ``ok``, ``not_downloaded``, ``missing`` or ``corrupt``
            (its worst pinned file); the project the worst task status.

        Raises
        ------
        ProducerError
            No manifest or an invalid one.
        """
        try:
            check = get_project_status(path)
        except KartografError as error:
            raise _producer_error(error) from error
        info = _project_info(check.project)
        worst = {str(name): "not_downloaded" for name in check.not_downloaded}
        for file in check.files:
            worst[file.task] = max(
                worst.get(file.task, "ok"), str(file.status), key=_severity
            )
        tasks = tuple(
            replace(task, status=worst.get(task.task_id, "ok")) for task in info.tasks
        )
        status = max((str(task.status) for task in tasks), key=_severity, default="ok")
        return replace(info, tasks=tasks, status=status)

    def segments(self, root: Path) -> tuple[str, ...]:
        """List the store's segments (``list_segments``), unknown ones included.

        Raises
        ------
        SourceUnavailableError
            The store cannot be listed.
        """
        try:
            return tuple(list_segments(root))
        except OSError as error:
            raise _unavailable(root, error) from error

    def describe_segment(self, segment: str) -> SourceSegment:
        """Describe a segment with ``describe_segment`` (no disk access)."""
        info = describe_segment(segment)
        return SourceSegment(
            segment=info.segment,
            product=info.product,
            country=info.country,
            dataset_key=info.dataset_key,
            name=info.name,
            known=info.known,
        )

    def transformer(self, src_crs: str, dst_crs: str) -> CoordinateTransformer:
        """Return Kartograf's pinned operation between two CRSs.

        Raises
        ------
        ProducerError
            No operation satisfies Kartograf's policy (never approximated).
        """
        try:
            return _PinnedTransformer(src_crs, dst_crs)
        except KartografError as error:
            raise _producer_error(error) from error

    def countries(
        self, bbox_wgs84: tuple[float, float, float, float]
    ) -> tuple[str, ...]:
        """Return Kartograf's countries whose extent meets a WGS84 box."""
        try:
            return tuple(countries_for_bbox(BBox(*bbox_wgs84, _WGS84)))
        except KartografError as error:
            raise _producer_error(error) from error

    def confirm_link(self, entry: SourceEntry) -> Path | None:
        """Confirm on demand which version a link holds (``link_target``).

        It may read the whole file on a share without stable inode numbers,
        so a scan never calls it.

        Returns
        -------
        Path or None
            The confirmed version relative to the store; ``None`` when the
            link does not hold the version its sidecar names.

        Raises
        ------
        SourceUnavailableError
            The store became unreadable.
        """
        base = Path(os.path.normpath(entry.store))
        try:
            target = link_target(base / entry.relative_path)
        except OSError as error:
            raise _unavailable(base, error) from error
        except KartografError as error:
            raise _producer_error(error) from error
        return None if target is None else Path(target).relative_to(base)

    def sheet_grid(
        self, area: tuple[float, float, float, float], system: str, scale: str
    ) -> SheetGrid:
        """Find the sheets of a WGS84 area with their WGS84 outlines.

        Parameters
        ----------
        area : tuple[float, float, float, float]
            ``(min_lon, min_lat, max_lon, max_lat)``.
        system : str
            ``"1992"`` or ``"2000"`` (Polish sheet systems).
        scale : str
            Sheet scale, e.g. ``"1:10000"``.

        Raises
        ------
        ProducerError
            Kartograf does not support the system or scale.
        """
        try:
            codes = tuple(find_sheets_for_bbox(BBox(*area, _WGS84), scale, system))
            outlines = tuple(_sheet_outline(code, system) for code in codes)
        except KartografError as error:
            raise _producer_error(error) from error
        return SheetGrid(status="available", sheets=codes, outlines=outlines)

    def _state(
        self,
        status: SourceStatus,
        root: Path,
        *,
        detail: str | None = None,
        reason: str | None = None,
        hint: str | None = None,
    ) -> SourceState:
        return SourceState(
            producer=self.producer,
            status=status,
            store=str(root),
            package_version=str(__version__),
            supported_versions=self.supported_versions,
            schemas=self.schemas,
            detail=detail,
            reason=reason,
            hint=hint,
        )

    def _entries(self, root: Path, scope: ScanScope) -> Iterator[SourceEntry]:
        store = str(root)
        prefix = os.path.join(os.path.normpath(root), "")
        try:
            for entry in iter_store(
                root,
                segment=scope.segment,
                units=scope.units,
                partition=scope.partition,
                skip_versions=scope.known_versions or None,
            ):
                yield _source_entry(store, prefix, entry)
        except OSError as error:
            raise _unavailable(root, error) from error
        except KartografError as error:
            raise _producer_error(error) from error


class _PinnedTransformer:
    """Kartograf's pinned operation for one CRS pair, usable from any thread.

    ``pinned_transform`` keeps one operation object per thread (pyproj
    operations are not thread-safe), so each call takes the calling thread's.
    """

    def __init__(self, src_crs: str, dst_crs: str) -> None:
        pinned = pinned_transform(src_crs, dst_crs)
        self._src_crs = src_crs
        self._dst_crs = dst_crs
        self.description = str(pinned.description)
        self.accuracy_m = float(pinned.accuracy_m)

    def transform(
        self, xs: FloatArray, ys: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Transform coordinates in x (east), y (north) order."""
        try:
            x, y = pinned_transform(self._src_crs, self._dst_crs).transform(xs, ys)
        except KartografError as error:
            raise _producer_error(error) from error
        return x, y

    def gdal_operation(self) -> str:
        """Return the operation as a PROJ pipeline for GDAL.

        Kartograf's ``PinnedTransform.gdal_operation``: the pipeline of the
        same pinned operation for ``COORDINATE_OPERATION``, with
        ``axisswap`` for a northing-first CRS.

        Raises
        ------
        ProducerError
            Kartograf cannot express the operation for GDAL.
        """
        try:
            pinned = pinned_transform(self._src_crs, self._dst_crs)
            return str(pinned.gdal_operation())
        except KartografError as error:
            raise _producer_error(error) from error


def _source_entry(store: str, prefix: str, entry: Any) -> SourceEntry:
    """Kartograf's entry as a producer-neutral one, paths relative to the store.

    ``prefix`` is the normalised store directory with a trailing separator,
    the start of every path ``iter_store`` yields.
    """
    version = entry.version_path
    meta = None
    relative = _relative(entry.path, prefix)
    if version is entry.path:
        # A version names itself: one path object serves both fields.
        version = relative
    elif version is not None:
        version = _relative(version, prefix)
    if entry.sidecar is not None and entry.kind != "problem":
        meta = _entry_meta(store, relative, entry.sidecar, entry.segment, entry.label)
    return SourceEntry(
        producer=PRODUCER,
        store=store,
        relative_path=relative,
        kind=entry.kind,
        segment=entry.segment,
        slot_path=_slot_path(entry),
        version_path=version,
        problem=entry.problem,
        skipped=bool(entry.skipped),
        meta=meta,
        handle=entry,
    )


def _relative(path: Any, prefix: str) -> Path:
    """Return a path below the store relative to it.

    The prefix is cut as text: ``Path.relative_to`` walks the parents and
    cost a scan more than everything else done per entry.
    """
    text = os.fspath(path)
    if not text.startswith(prefix):
        raise ValueError(f"{text!r} is not inside the store {prefix!r}")
    return Path(text[len(prefix) :])


def _slot_path(entry: Any) -> Path | None:
    """``<segment>/<hierarchy>/<name>``: the file's place in every version."""
    if entry.kind == "problem" and entry.problem in _SEGMENT_PROBLEMS:
        return None
    parts = (entry.segment, entry.hierarchy, entry.name)
    return Path("/".join(part for part in parts if part))


def _partition_weights(
    segment: str, keys: list[str], known: Mapping[str, tuple[str, ...]]
) -> Counter[str]:
    """Known version files of a segment's ``list_partitions`` parts.

    A part covers a hierarchy: ``"."`` the segment's own level, ``"A/."``
    exactly the directory ``A``, any other key every directory below it.
    A known version directory is ``<segment>/versions/<hierarchy>/<name>``.
    """
    exact: dict[tuple[str, ...], str] = {}
    below: dict[tuple[str, ...], str] = {}
    for key in keys:
        if key == ".":
            exact[()] = key
        elif key.endswith("/."):
            exact[tuple(key[:-2].split("/"))] = key
        else:
            below[tuple(key.split("/"))] = key
    depth = max(map(len, below), default=0)
    versions = f"{segment}/versions/"
    weights: Counter[str] = Counter(dict.fromkeys(keys, 0))
    for directory, names in known.items():
        if not directory.startswith(versions):
            continue
        hierarchy = tuple(directory[len(versions) :].split("/")[:-1])
        found = exact.get(hierarchy)
        size = min(depth, len(hierarchy))
        while found is None and size > 0:
            found = below.get(hierarchy[:size])
            size -= 1
        if found is not None:
            weights[found] += len(names)
    return weights


def _entry_meta(
    store: str, relative: Path, sidecar: Any, segment: str | None, label: str | None
) -> EntryMeta:
    """Producer-neutral metadata from a sidecar and its segment's descriptor."""
    info = describe_segment(segment) if segment else None
    extra = _mapping(sidecar.extra)
    version = _mapping(extra.get("version"))
    licence = _mapping(sidecar.license)
    return EntryMeta(
        producer=PRODUCER,
        store=store,
        relative_path=relative,
        dataset=sidecar.dataset,
        dataset_key=sidecar.dataset_key or (info.dataset_key if info else None),
        product=sidecar.product or (info.product if info else None),
        label=label or _text(version.get("label")),
        label_source=_text(version.get("label_source")),
        data_year=sidecar.data_year,
        data_date=_date(sidecar.data_date),
        downloaded_at=_datetime(sidecar.downloaded_at),
        sha256=sidecar.sha256,
        size_bytes=sidecar.size_bytes,
        license=_text(licence.get("id")),
        attribution=_text(licence.get("attribution")),
        source_files=_source_files(extra.get("source_files")),
        raw_sidecar=sidecar.raw,
        country=sidecar.country or (info.country if info else None),
        unit=sidecar.unit,
        survey_work_id=sidecar.survey_work_id,
        campaign=_text(_mapping(sidecar.campaign).get("id")),
        edition=sidecar.edition,
        full_sheet=sidecar.full_sheet,
        coverage=sidecar.coverage,
        parent_request=_group_key(extra.get("parent_request")),
        horizontal_crs=sidecar.horizontal_crs,
        vertical_crs=sidecar.vertical_crs,
        resolution=sidecar.resolution,
        nodata=sidecar.nodata,
    )


def _rebuilt(entry: SourceEntry) -> Any | None:
    """Kartograf's entry for one rebuilt from the index; ``None`` if unreadable."""
    path = Path(entry.store) / entry.relative_path
    sidecar = _readable_sidecar(path)
    if sidecar is None:
        return None
    hierarchy = ""
    if entry.slot_path is not None and entry.segment is not None:
        depth = len(Path(entry.segment).parts)
        hierarchy = "/".join(entry.slot_path.parent.parts[depth:])
    version = None
    if entry.version_path is not None:
        version = Path(entry.store) / entry.version_path
    label = _text(_mapping(_mapping(sidecar.extra).get("version")).get("label"))
    return StoreEntry(
        kind=entry.kind,
        segment=entry.segment or "",
        hierarchy=hierarchy,
        name=path.name,
        path=path,
        version_path=version,
        label=label,
        sha8=sidecar.sha256[:8] if sidecar.sha256 else None,
        sidecar=sidecar,
        problem=None,
    )


def _readable_sidecar(path: Path) -> Any | None:
    try:
        return read_sidecar(path)
    except InvalidSidecarError:
        return None


def _project_info(project: Any) -> ProjectInfo:
    """Convert a Kartograf project; its pins are relative to its store."""
    store = str(project.root)
    directory = Path(project.directory)
    tasks = tuple(
        ProjectTask(task_id=task.name, command=task.command, options=dict(task.options))
        for task in project.tasks
    )
    pins = tuple(
        ProjectPin(
            store=store,
            version_path=Path(file.version),
            sha256=file.sha256,
            task_id=task.name,
        )
        for task in project.tasks
        for file in task.files
    )
    return ProjectInfo(
        producer=PRODUCER,
        store=store,
        path=directory,
        name=directory.name,
        tasks=tasks,
        pins=pins,
    )


def _severity(status: str) -> int:
    """Rank of a state; an unexpected one ranks above all known ones."""
    if status in _STATUS_ORDER:
        return _STATUS_ORDER.index(status)
    return len(_STATUS_ORDER)


def _sheet_outline(code: str, system: str) -> GeoJSONGeometry:
    """WGS84 polygon of a sheet: exact for PL-1992, pinned corners for PL-2000."""
    parser = SheetParser(code)
    if system == "1992":
        return _polygon(parser.get_bbox(_WGS84))
    native = parser.get_bbox()
    corners = [
        (native.min_x, native.min_y),
        (native.max_x, native.min_y),
        (native.max_x, native.max_y),
        (native.min_x, native.max_y),
    ]
    pinned = pinned_transform(native.crs, _WGS84)
    ring = [[float(value) for value in pinned.transform(x, y)] for x, y in corners]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def _polygon(bbox: Any) -> GeoJSONGeometry:
    """Counter-clockwise GeoJSON polygon of a bounding box."""
    min_x, min_y = float(bbox.min_x), float(bbox.min_y)
    max_x, max_y = float(bbox.max_x), float(bbox.max_y)
    ring = [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def _producer_error(error: Exception) -> ProducerError:
    return ProducerError(PACKAGE, type(error).__name__, str(error))


def _unavailable(root: Path | str, error: OSError) -> SourceUnavailableError:
    text = message("store.unreadable", path=root)
    return SourceUnavailableError(with_detail(text, str(error)))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _datetime(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _source_files(value: object) -> tuple[str, ...]:
    """Store paths of the input versions of a derived file."""
    if not isinstance(value, list):
        return ()
    return tuple(
        item["file"]
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("file"), str)
    )


def _group_key(value: object) -> str | None:
    """Canonical JSON of ``extra.parent_request``: equal for one request."""
    if not isinstance(value, Mapping) or not value:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
