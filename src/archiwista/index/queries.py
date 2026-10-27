"""Read the local index: catalog pages, cards, map footprints and states.

HTTP and the command line answer from one ``IndexQueries``; nothing here
reads a store. Every method reads one consistent snapshot (a read
transaction in WAL mode), so answers stay coherent while a scan writes.

The catalog orders rows by file name, then slot path, store and version
path; ``next_cursor`` continues after the last row of a page (keyset
pagination), so pages stay cheap however deep the client goes. A cursor
belongs to its query: one from other filters is rejected.

Every method that names projects or follows their pins takes a required
``visible`` (``Authorizer.visible_projects``, A-ADR-029): projects the
principal does not see are left out of lists, pins (``pinned_by``), the
``pinned`` filter and store problems, and ``project`` answers ``None`` for
them. Reports counting all projects (``noncurrent_unpinned``,
``unused_versions``) name none.
"""

import base64
import binascii
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import shapely
from shapely.geometry import shape

from archiwista.auth import ProjectVisibility
from archiwista.errors import IndexQueryError
from archiwista.index.coverage import CoverageShape, measure_coverage, planar_crs
from archiwista.index.geometry import (
    AreaPlace,
    area_places,
    box_geometry,
    is_box,
    require_wgs84_area,
    require_wgs84_bbox,
    widen_bounds,
)
from archiwista.index.projects import PROJECT_MANIFESTS
from archiwista.index.schema import SCHEMA_VERSION, connect, initialize
from archiwista.index.series import (
    DEFAULT_YEAR_TYPES,
    VALUED_STATES,
    SeriesYear,
    YearRange,
    YearTypes,
    default_span,
    label_year_type,
    series_label,
)
from archiwista.index.types import (
    DEFAULT_PAGE_LIMIT,
    MAP_FOOTPRINT_LIMIT,
    MAX_GRID_COLUMNS,
    MAX_PAGE_LIMIT,
    OWN_CHANGES,
    OWN_FILE_STATES,
    AreaFilter,
    AreaRecord,
    BBox,
    CoverageVariable,
    DatasetVariable,
    FootprintPage,
    GridCell,
    GroupMember,
    IndexStatus,
    IssueRef,
    JobRef,
    LocalCoverage,
    LocalCoverageReport,
    LocationCounts,
    LocationRef,
    MapFootprint,
    MapQuery,
    ObservationRef,
    OrphanLink,
    OwnFileDetail,
    OwnFileObservation,
    OwnFilePage,
    OwnFileRow,
    OwnFolderRecord,
    OwnProblem,
    OwnSnapshotRef,
    PinRef,
    PinState,
    ProductSummary,
    ProductUsage,
    ProductVersion,
    ProjectManifestRef,
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
    ProjectTaskRef,
    RiverScope,
    RowStatus,
    SegmentRef,
    SegmentSummary,
    SlotDetail,
    SlotPage,
    SlotQuery,
    SlotRow,
    SlotUnit,
    SnapshotRecord,
    StationCounts,
    StationCoverage,
    StationDataset,
    StationMap,
    StationPage,
    StationQuery,
    StationRow,
    StationSort,
    StoredAvailability,
    StoredPlan,
    StoreFreshness,
    StoreIndexState,
    StoreUsage,
    TransformerFactory,
    UnusedVersions,
    VersionDetail,
    VersionsMode,
    VersionSummary,
    WarmQuery,
    WarmSelection,
)
from archiwista.messages import message
from archiwista.owndata.document import SNAPSHOTS_DIR
from archiwista.owndata.reader import FieldInfo, LayerInfo, RasterInfo
from archiwista.sources import (
    ActionPlan,
    AvailabilityReport,
    DateRange,
    GeoJSONGeometry,
    SourceEntry,
    VariableCoverage,
    YearType,
)

_IDS = "SELECT value FROM json_each(?)"
_CURSOR_VERSION = 1
_SHA_PREFIX = re.compile(r"[0-9a-fA-F]{8,64}")
_WORD = re.compile(r"[^\W_]")
_LOCATION = "coalesce(v.location, 'none')"
_STATUS = (
    "CASE WHEN g.known = 0 THEN 'unrecognized' WHEN v.id IS NULL THEN s.status"
    " WHEN v.state = 'missing' THEN 'missing' ELSE 'ok' END"
)
# Pinned by any project: what clean-up reports count (names never shown).
_PINNED = (
    "EXISTS (SELECT 1 FROM pins p WHERE p.store_id = v.store_id"
    " AND p.version_path = v.path)"
)
# Pinned by a project the principal sees: the ``pinned`` filter (``_where``);
# with ``pr.key = ?`` prepended, the ``project`` filter. Driven by the few
# pins, not tested for each of the store's versions.
_PINNED_VISIBLE = (
    "v.id IN (SELECT pv.id FROM pins p JOIN projects pr ON pr.id = p.project_id"
    " JOIN versions pv ON pv.store_id = p.store_id AND pv.path = p.version_path"
    " WHERE {visible})"
)
_SOURCES: Mapping[VersionsMode, tuple[str, tuple[str, ...]]] = {
    "current": (
        "slots s JOIN segments g ON g.id = s.segment_id"
        " LEFT JOIN versions v ON v.id = s.current_version_id",
        (),
    ),
    "full_sheet": (
        "slots s JOIN segments g ON g.id = s.segment_id"
        " JOIN versions v ON v.id = s.full_sheet_version_id",
        (),
    ),
    "all": (
        "slots s JOIN segments g ON g.id = s.segment_id"
        " JOIN versions v ON v.slot_id = s.id",
        (),
    ),
    "pinned": (
        "slots s JOIN segments g ON g.id = s.segment_id"
        " JOIN versions v ON v.slot_id = s.id",
        (),
    ),
    "noncurrent_unpinned": (
        "slots s JOIN segments g ON g.id = s.segment_id"
        " JOIN versions v ON v.slot_id = s.id",
        (
            "v.id IS NOT s.current_version_id",
            "v.id IS NOT s.full_sheet_version_id",
            f"NOT {_PINNED}",
        ),
    ),
}
# The map's rows come from the footprints: which version each mode draws
# (the catalog conditions of the other modes apply as they are).
_MAP_MODES: Mapping[VersionsMode, tuple[str, ...]] = {
    "current": ("s.current_version_id = v.id",),
    "full_sheet": ("s.full_sheet_version_id = v.id",),
}
_MAP_SOURCE = (
    "footprints f JOIN versions v ON v.id = f.id"
    " JOIN slots s ON s.id = v.slot_id JOIN segments g ON g.id = s.segment_id"
)
_PIN_SOURCE = (
    "pins p LEFT JOIN versions v ON v.store_id = p.store_id AND v.path = p.version_path"
)
# A pin of an unconfigured store is unknown; a version that is not present
# is missing; other indexed content (by SHA-256) is a mismatch.
_PIN_STATE = (
    "CASE WHEN p.store_id IS NULL THEN 'unknown'"
    " WHEN v.id IS NULL OR v.state <> 'present' THEN 'missing'"
    " WHEN p.sha256 IS NOT NULL AND v.sha256 IS NOT NULL AND p.sha256 <> v.sha256"
    " THEN 'sha256_mismatch' ELSE 'ok' END"
)
_PROJECT_SELECT = f"""
SELECT pr.id, pr.key, pr.name, pr.path, pr.access_key,
    (SELECT count(*) FROM project_tasks t WHERE t.project_id = pr.id) AS tasks,
    (SELECT count(*) FROM pins p WHERE p.project_id = pr.id) AS pins,
    (SELECT count(*) FROM {_PIN_SOURCE}
        WHERE p.project_id = pr.id AND {_PIN_STATE} IN ('missing', 'sha256_mismatch')
    ) AS missing_pins
FROM projects pr
"""
_MANIFEST_SELECT = """
SELECT m.project_id, m.producer, st.key AS store, m.store_dir, m.status, m.problem,
    m.scanned_at
FROM manifests m LEFT JOIN stores st ON st.id = m.store_id
"""
# A project of a store: one of its manifests names the store.
_PROJECT_OF_STORE = (
    "EXISTS (SELECT 1 FROM manifests m JOIN stores st ON st.id = m.store_id"
    " WHERE m.project_id = pr.id AND st.key = ?)"
)
_SLOT_COLUMNS = """
    s.id AS slot_id, s.store_id AS store_id, s.path AS slot_path,
    s.name AS slot_name, s.unit AS slot_unit, s.product AS slot_product,
    s.country AS slot_country, s.status AS slot_status,
    s.current_path AS current_path, s.full_sheet_path AS full_sheet_path,
    g.segment AS segment, g.name AS segment_name, g.producer AS producer,
    g.product AS segment_product, g.country AS segment_country,
    g.dataset_key AS segment_dataset_key, g.known AS segment_known
"""
_VERSION_COLUMNS = """
    v.id AS version_id, v.path AS version_path, v.label AS label,
    v.label_source AS label_source, v.data_year AS data_year,
    v.data_date AS data_date, v.downloaded_at AS downloaded_at,
    v.sha256 AS sha256, v.size_bytes AS size_bytes, v.full_sheet AS full_sheet,
    v.horizontal_crs AS horizontal_crs, v.vertical_crs AS vertical_crs,
    v.state AS version_state, v.missing_since AS missing_since,
    v.location AS location, v.location_reason AS location_reason,
    v.location_source AS location_source,
    (v.id = s.current_version_id) AS is_current,
    (v.id = s.full_sheet_version_id) AS is_full_sheet
"""
# A station with the label and file of the catalog version it was read from.
_STATION_COLUMNS = """
    s.id AS id, s.store_id AS store_id, s.provider AS provider, s.code AS code,
    s.kind AS kind,
    s.meteo_kind AS meteo_kind, s.name AS name, s.river AS river,
    s.hydrographic_code AS hydrographic_code, s.river_order AS river_order,
    s.location AS location, s.lon AS lon, s.lat AS lat,
    s.location_reason AS location_reason, s.location_source AS location_source,
    s.location_uncertainty_m AS location_uncertainty_m, s.active AS active,
    s.established_year AS established_year, s.gauge_zero_m AS gauge_zero_m,
    s.river_km AS river_km, s.elevation_m AS elevation_m, cv.label AS catalog,
    c.version_path AS catalog_version
"""
_STATION_SOURCE = (
    "stations s LEFT JOIN station_catalogs c"
    " ON c.store_id = s.store_id AND c.provider = s.provider"
    " LEFT JOIN versions cv ON cv.store_id = c.store_id AND cv.path = c.version_path"
)
# The keys of each order of a list of stations (SPEC 6.8), selected as
# ``order_<i>`` and kept in its cursor: along rivers, the hydrographic code as
# text (a tributary's code begins with its river's, so it follows the river),
# then the provider's order on the river, then the name, stations without a
# code or an order after those with one; or by name. Code, provider and store
# make each key unique.
_STATION_ORDERS: dict[StationSort, tuple[str, ...]] = {
    "river": (
        "s.hydrographic_code IS NULL",
        "coalesce(s.hydrographic_code, '')",
        "s.river_order IS NULL",
        "coalesce(s.river_order, 0)",
        "coalesce(s.name, '')",
        "s.code",
        "s.provider",
        "s.store_id",
    ),
    "name": ("coalesce(s.name, '')", "s.code", "s.provider", "s.store_id"),
}
# A map draws its stations by name.
_NAME_ORDER = ", ".join(_STATION_ORDERS["name"])
# A variable of a station's series with what its labels need of the dataset's
# version, and the label, licence and attribution of that version.
_SERIES_COLUMNS = """
    s.id AS id, s.store_id AS store_id, s.dataset AS dataset, s.provider AS provider,
    s.code AS code, s.variable_key AS variable_key, s.variable AS variable,
    s.unit AS unit, s.period AS period, s.first_date AS first_date,
    s.last_date AS last_date, s.with_value AS with_value,
    s.accumulated AS accumulated, s.gaps AS gaps, s.periods AS periods,
    s.file AS file, s.sha256 AS sha256, c.kind AS kind, c.time_unit AS time_unit,
    c.first_year AS first_year, c.periods AS version_periods,
    c.version_path AS version_path, sv.label AS series, sv.license AS license,
    sv.attribution AS attribution
"""
# The stations whose ids a JSON list gives, as the key of their series.
_SERIES_OF_STATIONS = (
    "(s.store_id, s.provider, s.code) IN (SELECT store_id, provider, code"
    f" FROM stations WHERE id IN ({_IDS}))"
)
# The series ``x`` of the station ``s``, for ``EXISTS`` (``AND …`` follows).
_STATION_SERIES = (
    "station_series x WHERE x.store_id = s.store_id AND x.provider = s.provider"
    " AND x.code = s.code"
)
_SERIES_SOURCE = (
    "station_series s JOIN series_catalogs c"
    " ON c.store_id = s.store_id AND c.dataset = s.dataset"
    " LEFT JOIN versions sv ON sv.store_id = c.store_id AND sv.path = c.version_path"
)


@dataclass(frozen=True, slots=True)
class _Filters:
    """Filters shared by the catalog and the map, normalised."""

    q: str | None
    store: str | None
    product: str | None
    country: str | None
    years: tuple[int | None, int | None] | None
    unit: str | None
    versions: VersionsMode
    status: RowStatus | None
    project: str | None


@dataclass(slots=True)
class _Where:
    conditions: list[str] = field(default_factory=list)
    params: list[object] = field(default_factory=list)

    def add(self, condition: str, *params: object) -> None:
        self.conditions.append(condition)
        self.params.extend(params)

    def sql(self) -> str:
        return " AND ".join(f"({item})" for item in self.conditions) or "1"

    def copy(self) -> Self:
        return type(self)(list(self.conditions), list(self.params))


@dataclass(frozen=True, slots=True)
class _Grid:
    """The aggregation grid of a map view: cells of ``width`` by ``height``°."""

    min_lon: float
    min_lat: float
    columns: int
    rows: int
    width: float
    height: float

    def cell(self, column: int, row: int, count: int) -> GridCell:
        """Return the cell in ``column`` and ``row`` holding ``count`` objects."""
        return GridCell(
            min_lon=self.min_lon + column * self.width,
            min_lat=self.min_lat + row * self.height,
            max_lon=self.min_lon + (column + 1) * self.width,
            max_lat=self.min_lat + (row + 1) * self.height,
            count=count,
        )

    def count(self, points: Iterable[tuple[float, float]]) -> tuple[GridCell, ...]:
        """Count points of the view by cell, row after row."""
        counts: dict[tuple[int, int], int] = {}
        for lon, lat in points:
            column = max(
                0, min(self.columns - 1, int((lon - self.min_lon) / self.width))
            )
            row = max(0, min(self.rows - 1, int((lat - self.min_lat) / self.height)))
            counts[row, column] = counts.get((row, column), 0) + 1
        return tuple(
            self.cell(column, row, count)
            for (row, column), count in sorted(counts.items())
        )


def _grid(view: BBox, columns: int) -> _Grid:
    """Return the grid of a view: ``columns`` across, rows of square cells.

    Raises
    ------
    IndexQueryError
        ``columns`` out of range.
    """
    if not 1 <= columns <= MAX_GRID_COLUMNS:
        raise IndexQueryError(message("index.invalid_grid", limit=MAX_GRID_COLUMNS))
    min_lon, min_lat, max_lon, max_lat = view
    width = (max_lon - min_lon) / columns
    middle = math.radians((min_lat + max_lat) / 2)
    rows = min(
        MAX_GRID_COLUMNS,
        max(1, math.ceil((max_lat - min_lat) / (width * math.cos(middle)))),
    )
    return _Grid(min_lon, min_lat, columns, rows, width, (max_lat - min_lat) / rows)


@dataclass(frozen=True, slots=True)
class _Area:
    """An area turned into SQL: which rows it admits and how they group."""

    admits: str
    params: tuple[object, ...]


class IndexQueries:
    """Answer catalog, card, map, product, usage and state questions.

    Parameters
    ----------
    path : Path
        The index file; created (or rebuilt after a schema change) when
        needed.

    Notes
    -----
    Safe to share between threads: each thread reads through its own
    read-only connection.
    """

    def __init__(self, path: Path) -> None:
        initialize(path)
        self._path = path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: list[sqlite3.Connection] = []

    def close(self) -> None:
        """Close every thread's connection."""
        with self._lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            connection.close()
        self._local = threading.local()

    def __enter__(self) -> Self:
        """Use the queries as a context manager that closes them."""
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the queries."""
        self.close()

    # Catalog.

    def slots(self, query: SlotQuery, *, visible: ProjectVisibility) -> SlotPage:
        """Return a page of catalog rows with the location group counts.

        Parameters
        ----------
        query : SlotQuery
            Filters, area, page size and cursor.
        visible : ProjectVisibility
            Projects the principal sees: only their pins are listed
            (``pinned_by``) and count for ``versions="pinned"`` and for
            ``query.project`` (an invisible project matches nothing).

        Returns
        -------
        SlotPage
            Rows in name order; ``groups`` count the whole result for every
            location group, whatever ``query.location`` selects.

        Raises
        ------
        IndexQueryError
            Limit out of range, reversed years, an invalid area or a cursor
            of another query.
        """
        _require_limit(query.limit, MAX_PAGE_LIMIT)
        filters = _filters(query)
        with self._read() as connection:
            stores = _stores(connection)
            where = _where(connection, filters, stores, visible)
            area = None if query.area is None else _area(connection, query.area)
            if area is not None:
                where.add(area.admits, *area.params)
            groups = _groups(connection, filters.versions, where)
            page = _Where(list(where.conditions), list(where.params))
            if query.location == "with":
                page.add(f"{_LOCATION} <> 'none'")
            elif query.location == "none":
                page.add(f"{_LOCATION} = 'none'")
            fingerprint = _fingerprint(query)
            current = filters.versions == "current"
            keys = ["s.name", "s.path", "s.store_id"] + ([] if current else ["v.path"])
            after = _decode_cursor(query.cursor, fingerprint, len(keys))
            if after is not None:
                marks = ", ".join("?" for _ in keys)
                page.add(f"({', '.join(keys)}) > ({marks})", *after)
            source, _ = _SOURCES[filters.versions]
            rows = connection.execute(
                f"SELECT {_SLOT_COLUMNS}, {_VERSION_COLUMNS},"
                f" {_STATUS} AS row_status,"
                " (SELECT count(*) FROM versions x WHERE x.slot_id = s.id)"
                f" AS versions_count FROM {source} WHERE {page.sql()}"
                f" ORDER BY {', '.join(keys)} LIMIT ?",
                [*page.params, query.limit + 1],
            ).fetchall()
            more = len(rows) > query.limit
            rows = rows[: query.limit]
            pins = _pins(
                connection,
                [
                    (row["store_id"], row["version_path"])
                    for row in rows
                    if row["version_id"] is not None
                ],
                visible,
            )
            items = tuple(_slot_row(row, stores, pins) for row in rows)
        next_cursor = None
        if more and rows:
            last = rows[-1]
            values: list[object] = [
                last["slot_name"],
                last["slot_path"],
                last["store_id"],
            ]
            if not current:
                values.append(last["version_path"])
            next_cursor = _encode_cursor(fingerprint, values)
        return SlotPage(items=items, next_cursor=next_cursor, groups=groups)

    def slot(
        self, store: str, slot: str, *, visible: ProjectVisibility
    ) -> SlotDetail | None:
        """Return the file card of a slot, or ``None`` when it is not indexed.

        Parameters
        ----------
        store : str
            Configured store id.
        slot : str
            Slot path relative to the store.
        visible : ProjectVisibility
            Projects the principal sees: only their pins are listed
            (``Przypięta w:``).
        """
        with self._read() as connection:
            stores = _stores(connection)
            store_id = _store_id(stores, store)
            row = connection.execute(
                f"SELECT {_SLOT_COLUMNS} FROM slots s"
                " JOIN segments g ON g.id = s.segment_id"
                " WHERE s.store_id = ? AND s.path = ?",
                (store_id, slot),
            ).fetchone()
            if row is None:
                return None
            versions = connection.execute(
                f"SELECT s.store_id AS store_id, {_VERSION_COLUMNS} FROM versions v"
                " JOIN slots s ON s.id = v.slot_id WHERE v.slot_id = ? ORDER BY v.path",
                (row["slot_id"],),
            ).fetchall()
            pins = _pins(
                connection,
                [(row["store_id"], item["version_path"]) for item in versions],
                visible,
            )
            issues = _issues(connection, "i.slot_id = ?", (row["slot_id"],))
        summaries = tuple(_summary(item, pins) for item in versions)
        current = next((item for item in summaries if item.is_current), None)
        status: RowStatus = row["slot_status"]
        if not row["segment_known"]:
            status = "unrecognized"
        elif current is not None and current.state == "missing":
            status = "missing"
        return SlotDetail(
            store=store,
            slot=row["slot_path"],
            name=row["slot_name"],
            segment=_segment(row),
            unit=row["slot_unit"],
            product=row["slot_product"],
            country=row["slot_country"],
            status=status,
            current=row["current_path"],
            full_sheet=row["full_sheet_path"],
            versions=summaries,
            issues=issues,
        )

    def version(
        self, store: str, path: str, *, visible: ProjectVisibility
    ) -> VersionDetail | None:
        """Return every indexed value of a version, or ``None`` if unknown.

        Parameters
        ----------
        store : str
            Configured store id.
        path : str
            Version path relative to the store.
        visible : ProjectVisibility
            Projects the principal sees: only their pins are listed.
        """
        with self._read() as connection:
            stores = _stores(connection)
            row = connection.execute(
                f"SELECT {_SLOT_COLUMNS}, {_VERSION_COLUMNS},"
                " v.dataset AS dataset, v.dataset_key AS dataset_key,"
                " v.product AS version_product, v.country AS version_country,"
                " v.unit AS version_unit, v.campaign AS campaign,"
                " v.survey_work_id AS survey_work_id, v.edition AS edition,"
                " v.coverage AS coverage, v.parent_request AS parent_request,"
                " v.license AS license, v.attribution AS attribution,"
                " v.source_files AS source_files, v.resolution AS resolution,"
                " v.nodata AS nodata, v.native_crs AS native_crs,"
                " v.has_meta AS has_meta, v.is_box AS is_box,"
                " v.min_lon AS min_lon, v.min_lat AS min_lat,"
                " v.max_lon AS max_lon, v.max_lat AS max_lat, sh.wgs84 AS wgs84"
                " FROM versions v JOIN slots s ON s.id = v.slot_id"
                " JOIN segments g ON g.id = s.segment_id"
                " LEFT JOIN version_shapes sh ON sh.version_id = v.id"
                " WHERE v.store_id = ? AND v.path = ?",
                (_store_id(stores, store), path),
            ).fetchone()
            if row is None:
                return None
            pins = _pins(connection, [(row["store_id"], row["version_path"])], visible)
        footprint = None
        if row["location"] == "footprint":
            footprint = _outline(row)
        return VersionDetail(
            store=store,
            slot=row["slot_path"],
            segment=_segment(row),
            summary=_summary(row, pins),
            dataset=row["dataset"],
            dataset_key=row["dataset_key"],
            product=row["version_product"],
            country=row["version_country"],
            unit=row["version_unit"],
            campaign=row["campaign"],
            survey_work_id=row["survey_work_id"],
            edition=row["edition"],
            coverage=row["coverage"],
            parent_request=row["parent_request"],
            license=row["license"],
            attribution=row["attribution"],
            source_files=tuple(json.loads(row["source_files"] or "[]")),
            resolution=row["resolution"],
            nodata=row["nodata"],
            native_crs=row["native_crs"],
            footprint=footprint,
            has_meta=bool(row["has_meta"]),
        )

    def sidecar(self, store: str, path: str) -> dict[str, object] | None:
        """Return a version's raw sidecar as read, or ``None`` without one."""
        with self._read() as connection:
            stores = _stores(connection)
            row = connection.execute(
                "SELECT sc.raw FROM versions v"
                " JOIN version_sidecars sc ON sc.version_id = v.id"
                " WHERE v.store_id = ? AND v.path = ?",
                (_store_id(stores, store), path),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(row["raw"])
        return raw if isinstance(raw, dict) else None

    def native_outline(self, store: str, path: str) -> GeoJSONGeometry | None:
        """Return a version's outline in its native CRS, or ``None`` without one.

        The rectangle of the producer's footprint in ``native_crs`` (e.g. a
        JPEG sheet's from its header, ``location.source`` ``header``): the
        georeference of a file that carries none itself (plan v0.2,
        decision 5).
        """
        with self._read() as connection:
            stores = _stores(connection)
            row = connection.execute(
                "SELECT sh.native FROM versions v"
                " JOIN version_shapes sh ON sh.version_id = v.id"
                " WHERE v.store_id = ? AND v.path = ?",
                (_store_id(stores, store), path),
            ).fetchone()
        if row is None or row["native"] is None:
            return None
        outline: GeoJSONGeometry = json.loads(row["native"])
        return outline

    def group(self, parent_request: str) -> tuple[GroupMember, ...]:
        """Return the files of one producer request (``parent_request``)."""
        with self._read() as connection:
            stores = _stores(connection)
            rows = connection.execute(
                "SELECT s.store_id AS store_id, s.path AS slot_path,"
                " v.path AS version_path, g.segment AS segment,"
                " coalesce(v.country, s.country) AS country, v.label AS label,"
                " (v.id = s.current_version_id) AS is_current"
                " FROM versions v JOIN slots s ON s.id = v.slot_id"
                " JOIN segments g ON g.id = s.segment_id"
                " WHERE v.parent_request = ? ORDER BY s.store_id, v.path",
                (parent_request,),
            ).fetchall()
        return tuple(
            GroupMember(
                store=stores[row["store_id"]],
                slot=row["slot_path"],
                path=row["version_path"],
                segment=row["segment"] or None,
                country=row["country"],
                label=row["label"],
                is_current=bool(row["is_current"]),
            )
            for row in rows
        )

    # Map.

    def footprints(
        self, query: MapQuery, *, visible: ProjectVisibility
    ) -> FootprintPage:
        """Return decoded outlines for index consumers, or grid cells."""
        page, _ = self._footprints(query, visible=visible, encoded=False)
        return page

    def footprints_json(
        self, query: MapQuery, *, visible: ProjectVisibility
    ) -> tuple[FootprintPage, str]:
        """Return metadata and JSON items for HTTP, without decoding polygons.

        The page's ``items`` stay empty even for unaggregated views: the JSON
        string supplies them. In aggregated views the JSON string is ``[]``.
        """
        return self._footprints(query, visible=visible, encoded=True)

    def _footprints(
        self, query: MapQuery, *, visible: ProjectVisibility, encoded: bool
    ) -> tuple[FootprintPage, str]:
        """Return the footprints of a map view, or their grid above the limit.

        Parameters
        ----------
        query : MapQuery
            View, filters, limit and grid size.
        visible : ProjectVisibility
            Projects the principal sees: only their pins count for
            ``versions="pinned"`` and ``query.project``, as in the catalog.

        Returns
        -------
        tuple[FootprintPage, str]
            For decoded views the page contains ``items``; for encoded ones
            its items are in the JSON text instead. Above ``query.limit``,
            ``cells`` count footprint centres and the items text is ``[]``.

        Raises
        ------
        IndexQueryError
            An invalid view, limit or grid.
        """
        view_box = require_wgs84_bbox(query.bbox)
        min_lon, min_lat, max_lon, max_lat = view_box
        _require_limit(query.limit, MAP_FOOTPRINT_LIMIT)
        grid_shape = _grid(view_box, query.grid_columns)
        filters = _filters(query)
        with self._read() as connection:
            stores = _stores(connection)
            where = _where(connection, filters, stores, visible)
            groups = self._map_groups(connection, filters.versions, where)
            view = _Where(list(where.conditions), list(where.params))
            for condition in _MAP_MODES.get(filters.versions, ()):
                view.add(condition)
            view.add(
                "f.max_lon >= ? AND f.min_lon <= ?"
                " AND f.max_lat >= ? AND f.min_lat <= ?",
                min_lon,
                max_lon,
                min_lat,
                max_lat,
            )
            cells = connection.execute(
                "SELECT max(0, min(?, CAST(((f.min_lon + f.max_lon) / 2 - ?) / ?"
                " AS INTEGER))) AS col, max(0, min(?, CAST(((f.min_lat + f.max_lat)"
                " / 2 - ?) / ? AS INTEGER))) AS row, count(*) AS n"
                f" FROM {_MAP_SOURCE} WHERE {view.sql()} GROUP BY col, row",
                [
                    grid_shape.columns - 1,
                    min_lon,
                    grid_shape.width,
                    grid_shape.rows - 1,
                    min_lat,
                    grid_shape.height,
                    *view.params,
                ],
            ).fetchall()
            total = sum(int(cell["n"]) for cell in cells)
            if total > query.limit:
                grid = tuple(
                    grid_shape.cell(cell["col"], cell["row"], int(cell["n"]))
                    for cell in sorted(cells, key=lambda c: (c["row"], c["col"]))
                )
                return FootprintPage(total, True, (), grid, groups), "[]"
            rows = connection.execute(
                "SELECT s.store_id, s.path, v.path, g.segment, s.product, v.label,"
                " v.data_year, v.location_source, v.is_box, v.min_lon, v.min_lat,"
                f" v.max_lon, v.max_lat, sh.wgs84 FROM {_MAP_SOURCE}"
                " LEFT JOIN version_shapes sh ON sh.version_id = v.id AND v.is_box = 0"
                f" WHERE {view.sql()} ORDER BY v.id",
                view.params,
            ).fetchall()
        if encoded:
            items_json = (
                "["
                + ",".join(_map_item_json(row, stores[row[0]]) for row in rows)
                + "]"
            )
            return FootprintPage(total, False, (), (), groups), items_json
        items = tuple(
            MapFootprint(
                store=stores[row[0]],
                slot=row[1],
                version=row[2],
                segment=row[3] or None,
                product=row[4],
                label=row[5],
                data_year=row[6],
                source=row[7],
                geometry=box_geometry((row[9], row[10], row[11], row[12]))
                if row[8] or row[13] is None
                else json.loads(row[13]),
            )
            for row in rows
        )
        return FootprintPage(total, False, items, (), groups), "[]"

    def slots_in_bbox(
        self,
        store: str,
        bbox: BBox,
        *,
        segment: str | None = None,
        product: str | None = None,
    ) -> tuple[SlotUnit, ...]:
        """Return the slots whose current footprint shares interior with a box.

        What a view refresh rescans when the producer has no sheet grid.

        Parameters
        ----------
        store : str
            Configured store id.
        bbox : BBox
            ``(min_lon, min_lat, max_lon, max_lat)`` in WGS84.
        segment, product : str or None, optional
            Narrow to one segment or product.
        """
        min_lon, min_lat, max_lon, max_lat = require_wgs84_bbox(bbox)
        with self._read() as connection:
            stores = _stores(connection)
            where = _Where()
            where.add("s.store_id = ?", _store_id(stores, store))
            where.add(
                "f.max_lon > ? AND f.min_lon < ? AND f.max_lat > ? AND f.min_lat < ?",
                min_lon,
                max_lon,
                min_lat,
                max_lat,
            )
            where.add(
                "v.max_lon > ? AND v.min_lon < ? AND v.max_lat > ? AND v.min_lat < ?",
                min_lon,
                max_lon,
                min_lat,
                max_lat,
            )
            if segment is not None:
                where.add("g.segment = ?", segment)
            if product is not None:
                where.add("s.product = ?", product)
            rows = connection.execute(
                "SELECT DISTINCT s.path, g.segment, s.unit FROM footprints f"
                " JOIN versions v ON v.id = f.id"
                " JOIN slots s ON s.current_version_id = v.id"
                f" JOIN segments g ON g.id = s.segment_id WHERE {where.sql()}"
                " ORDER BY s.path",
                where.params,
            ).fetchall()
        return tuple(SlotUnit(row[0], row[1] or None, row[2]) for row in rows)

    def product_versions(
        self,
        store: str,
        product: str,
        *,
        segment: str | None = None,
        bbox: BBox | None = None,
    ) -> tuple[ProductVersion, ...]:
        """Return the present versions of a store's product, for its layers.

        What the local layers group (plan v0.2, decision 7). With ``bbox``
        only the versions whose footprint's box meets it, each with its WGS84
        outline and native rectangle; without it every present version of
        the product, without outlines. Ordered by version path.

        Parameters
        ----------
        store : str
            Configured store id.
        product : str
            Product of the slots (e.g. ``"nmt"``), all its segments.
        segment : str or None, optional
            Only this segment of the product.
        bbox : BBox or None, optional
            ``(min_lon, min_lat, max_lon, max_lat)`` in WGS84.
        """
        with self._read() as connection:
            stores = _stores(connection)
            where = _Where()
            where.add("s.store_id = ?", _store_id(stores, store))
            where.add("s.product = ?", product)
            where.add("v.state = 'present'")
            if segment is not None:
                where.add("g.segment = ?", segment)
            source = "versions v"
            shapes = ", NULL AS wgs84, NULL AS native"
            if bbox is not None:
                min_lon, min_lat, max_lon, max_lat = require_wgs84_bbox(bbox)
                source = "footprints f JOIN versions v ON v.id = f.id"
                where.add(
                    "f.max_lon > ? AND f.min_lon < ?"
                    " AND f.max_lat > ? AND f.min_lat < ?",
                    min_lon,
                    max_lon,
                    min_lat,
                    max_lat,
                )
                shapes = (
                    ", (SELECT sh.wgs84 FROM version_shapes sh"
                    " WHERE sh.version_id = v.id) AS wgs84,"
                    " (SELECT sh.native FROM version_shapes sh"
                    " WHERE sh.version_id = v.id) AS native"
                )
            rows = connection.execute(
                "SELECT v.path AS path, s.path AS slot,"
                " coalesce(v.unit, s.unit) AS unit, g.segment AS segment,"
                " g.name AS segment_name, g.producer AS producer,"
                " v.data_year AS data_year, v.data_date AS data_date,"
                " v.downloaded_at AS downloaded_at, v.edition AS edition,"
                " v.label AS label, v.campaign AS campaign, v.sha256 AS sha256,"
                " v.size_bytes AS size_bytes, v.product AS product,"
                " v.dataset_key AS dataset_key, v.horizontal_crs AS horizontal_crs,"
                " v.vertical_crs AS vertical_crs, v.resolution AS resolution,"
                " v.nodata AS nodata, v.location AS location,"
                " v.location_source AS location_source, v.native_crs AS native_crs,"
                " v.is_box AS is_box, v.min_lon AS min_lon, v.min_lat AS min_lat,"
                f" v.max_lon AS max_lon, v.max_lat AS max_lat{shapes}"
                f" FROM {source} JOIN slots s ON s.id = v.slot_id"
                " JOIN segments g ON g.id = s.segment_id"
                f" WHERE {where.sql()} ORDER BY v.path",
                where.params,
            ).fetchall()
        return tuple(_product_version(row, shapes=bbox is not None) for row in rows)

    def warm_selection(
        self, query: WarmQuery, *, visible: ProjectVisibility
    ) -> WarmSelection:
        """Return what a warm-up of previews prepares (``preview_warm``).

        The present current version of each slot that the filters admit, as
        the catalog's current rows; with ``query.project`` only those the
        project pins, and also the working files of its data folder that its
        last ``own_scan`` read and found (unless ``product``, ``segment`` or
        ``since`` is given: own data has none of them).

        Parameters
        ----------
        query : WarmQuery
            The filters.
        visible : ProjectVisibility
            Projects the principal sees: a project it does not see, or an
            unknown one, adds nothing.

        Returns
        -------
        WarmSelection
            Versions by store and slot path, files by path.
        """
        with self._read() as connection:
            stores = _stores(connection)
            where = _Where()
            where.add("v.state = 'present'")
            if query.store is not None:
                where.add("s.store_id = ?", _store_id(stores, query.store))
            if query.product is not None:
                where.add("s.product = ?", query.product)
            if query.segment is not None:
                where.add("g.segment = ?", query.segment)
            if query.since is not None:
                where.add("v.indexed_at >= ?", _utc_text(query.since))
            if query.project is not None:
                seen, params = _visible(visible)
                where.add(
                    _PINNED_VISIBLE.format(visible=f"pr.key = ? AND {seen}"),
                    query.project,
                    *params,
                )
            if query.area is not None:
                area = _area(connection, query.area)
                where.add(area.admits, *area.params)
            rows = connection.execute(
                "SELECT s.store_id, v.path FROM slots s"
                " JOIN segments g ON g.id = s.segment_id"
                " JOIN versions v ON v.id = s.current_version_id"
                f" WHERE {where.sql()} ORDER BY s.store_id, s.path",
                where.params,
            ).fetchall()
            versions = tuple((stores[row[0]], str(row[1])) for row in rows)
            files: tuple[str, ...] = ()
            own = query.project is not None and all(
                value is None for value in (query.product, query.segment, query.since)
            )
            folder = (
                _own_folder_row(connection, str(query.project), visible)
                if own
                else None
            )
            if folder is not None:
                found = connection.execute(
                    "SELECT path, wgs84 FROM own_files WHERE folder_id = ?"
                    " AND read_state = 'ok' AND missing_since IS NULL ORDER BY path",
                    (folder["id"],),
                ).fetchall()
                files = tuple(
                    str(row["path"])
                    for row in found
                    if query.area is None or _own_in_area(row["wgs84"], query.area)
                )
        return WarmSelection(versions, files)

    def entries_without_footprint(
        self, store: str, *, segment: str | None = None
    ) -> tuple[SourceEntry, ...]:
        """Rebuild entries of present versions still without an outline.

        The ``footprints`` job passes them to ``SourceAdapter.footprint``
        with the network allowed; versions without a readable sidecar are
        left out. Each entry's ``store`` is the producer directory recorded
        by ``IndexWriter.sync_stores``.
        """
        with self._read() as connection:
            stores = _stores(connection)
            store_id = _store_id(stores, store)
            roots_row = connection.execute(
                "SELECT roots FROM stores WHERE id = ?", (store_id,)
            ).fetchone()
            roots = {} if roots_row is None else json.loads(roots_row["roots"])
            where = _Where()
            where.add("v.store_id = ?", store_id)
            where.add("v.location = 'none'")
            where.add("v.location_reason IN ('no_source', 'pending')")
            where.add("v.state = 'present'")
            if segment is not None:
                where.add("g.segment = ?", segment)
            rows = connection.execute(
                "SELECT v.path, s.path, g.segment, g.producer FROM versions v"
                " JOIN slots s ON s.id = v.slot_id"
                f" JOIN segments g ON g.id = s.segment_id WHERE {where.sql()}"
                " ORDER BY v.path",
                where.params,
            ).fetchall()
        return tuple(
            SourceEntry(
                producer=producer,
                store=str(roots.get(producer, "")),
                relative_path=Path(version),
                kind="link" if version == slot else "version",
                segment=segment_name or None,
                slot_path=Path(slot),
                version_path=Path(version),
            )
            for version, slot, segment_name, producer in rows
        )

    # Products, usage, problems and state.

    def products(self, *, store: str | None = None) -> tuple[ProductSummary, ...]:
        """Return indexed products with their segments, countries and counts.

        Parameters
        ----------
        store : str or None, optional
            Only this store's segments.
        """
        with self._read() as connection:
            stores = _stores(connection)
            where = _Where()
            if store is not None:
                where.add("g.store_id = ?", _store_id(stores, store))
            rows = connection.execute(
                f"SELECT g.id, g.store_id AS store_id, {_segment_columns()},"
                " (SELECT count(*) FROM slots s WHERE s.segment_id = g.id) AS slots,"
                " (SELECT count(*) FROM versions v WHERE v.segment_id = g.id)"
                f" AS versions FROM segments g WHERE {where.sql()}"
                " ORDER BY g.product IS NULL, g.product, g.segment, g.store_id",
                where.params,
            ).fetchall()
        products: dict[str | None, list[SegmentSummary]] = {}
        for row in rows:
            summary = SegmentSummary(
                store=stores[row["store_id"]],
                segment=_segment(row),
                slots=int(row["slots"]),
                versions=int(row["versions"]),
            )
            products.setdefault(row["segment_product"], []).append(summary)
        return tuple(
            ProductSummary(
                product=product,
                countries=tuple(
                    sorted(
                        {
                            item.segment.country
                            for item in segments
                            if item.segment.country is not None
                        }
                    )
                ),
                segments=tuple(segments),
                slots=sum(item.slots for item in segments),
                versions=sum(item.versions for item in segments),
            )
            for product, segments in products.items()
        )

    def segment_producers(self, store: str, segment: str) -> tuple[str, ...]:
        """Return the producers that own a segment of a store, by name.

        A segment belongs to the producer whose scan described it
        (``segments.producer``), so a scan of one segment goes to its owner.
        A name the index does not know, and a store it does not know, have
        no owner.

        Parameters
        ----------
        store : str
            Configured store id.
        segment : str
            Segment name, as ``SegmentRef.segment``.
        """
        with self._read() as connection:
            stores = _stores(connection)
            rows = connection.execute(
                "SELECT producer FROM segments WHERE store_id = ? AND segment = ?"
                " ORDER BY producer",
                (_store_id(stores, store), segment),
            ).fetchall()
        return tuple(str(row["producer"]) for row in rows)

    def usage(self, store: str) -> StoreUsage | None:
        """Return the disk usage of a store's present versions, per product.

        Links add nothing and a content held by several versions counts
        once; products are the segments' (``None``: unrecognised segments).
        ``None`` for a store that is not indexed.
        """
        with self._read() as connection:
            stores = _stores(connection)
            if store not in stores.values():
                return None
            store_id = _store_id(stores, store)
            products = {
                int(row[0]): row[1]
                for row in connection.execute(
                    "SELECT id, product FROM segments WHERE store_id = ?", (store_id,)
                ).fetchall()
            }
            cursor = connection.cursor()
            cursor.row_factory = None
            rows = cursor.execute(
                "SELECT segment_id, sha256, size_bytes"
                " FROM versions INDEXED BY versions_sha256"
                " WHERE store_id = ? AND state = 'present'",
                (store_id,),
            ).fetchall()
        counts: dict[str | None, int] = {}
        loose: dict[str | None, int] = {}
        contents: dict[str | None, dict[str, int]] = {}
        everywhere: dict[str, int] = {}
        for segment_id, digest, size in rows:
            product = products.get(segment_id)
            counts[product] = counts.get(product, 0) + 1
            if digest is None:
                loose[product] = loose.get(product, 0) + (size or 0)
            else:
                contents.setdefault(product, {})[digest] = size or 0
                everywhere[digest] = size or 0
        return StoreUsage(
            store=store,
            products=tuple(
                ProductUsage(
                    product,
                    counts[product],
                    loose.get(product, 0) + sum(contents.get(product, {}).values()),
                )
                for product in sorted(
                    counts, key=lambda item: (item is None, item or "")
                )
            ),
            versions=len(rows),
            unique_bytes=sum(loose.values()) + sum(everywhere.values()),
        )

    def issues(self, store: str) -> tuple[IssueRef, ...]:
        """Return a store's problems, ordered by segment and path."""
        with self._read() as connection:
            stores = _stores(connection)
            return _issues(connection, "i.store_id = ?", (_store_id(stores, store),))

    def observations(self, store: str, slot: str) -> tuple[ObservationRef, ...]:
        """Return the publication history of a slot, the newest record first.

        A record is a source that served the content of a version again (it
        is never a version and changes no count). A slot the index does not
        know has none.

        Parameters
        ----------
        store : str
            Configured store id.
        slot : str
            Slot path relative to the store.
        """
        with self._read() as connection:
            stores = _stores(connection)
            rows = connection.execute(
                "SELECT o.path, o.version_path, o.seen_at, o.url, o.etag,"
                " o.last_modified, o.size_bytes, o.sha256 FROM observations o"
                " JOIN slots s ON s.id = o.slot_id"
                " WHERE s.store_id = ? AND s.path = ?"
                " ORDER BY o.seen_at DESC, o.path DESC",
                (_store_id(stores, store), slot),
            ).fetchall()
        return tuple(
            ObservationRef(
                path=row["path"],
                version=row["version_path"],
                seen_at=datetime.fromisoformat(row["seen_at"]),
                url=row["url"],
                etag=row["etag"],
                last_modified=row["last_modified"],
                size_bytes=row["size_bytes"],
                sha256=row["sha256"],
            )
            for row in rows
        )

    # Stations of the station catalogs.

    def stations(self, query: StationQuery) -> StationPage:
        """Return a page of stations in order, with the counts by location.

        Parameters
        ----------
        query : StationQuery
            Attribute, search and coverage filters, the box or the area, the
            location group, the labels, the order, page size and cursor.

        Returns
        -------
        StationPage
            Rows along rivers or by name (``query.sort``), then by code,
            provider and store; ``counts`` count the whole result by
            location, whatever ``query.location`` selects: the stations
            without a location after the attribute and coverage filters only,
            never narrowed or joined by the box or the area. With
            ``query.labels``, ``coverage`` holds the coverage of the page's
            stations.

        Raises
        ------
        IndexQueryError
            Limit out of range, an invalid box or area, an empty river code,
            a coverage filter without a dataset, a reversed range of years or
            a cursor of another query.
        """
        _require_limit(query.limit, MAX_PAGE_LIMIT)
        box = None if query.bbox is None else require_wgs84_bbox(query.bbox)
        _require_station_filters(query)
        with self._read() as connection:
            stores = _stores(connection)
            found = _select_stations(connection, stores, query, box)
            if query.location == "none":
                page = found.unlocated.copy()
            elif query.location == "with" or box is not None or query.area is not None:
                page = found.located.copy()
            else:
                page = found.every.copy()
            order = _STATION_ORDERS[query.sort]
            keys = ", ".join(order)
            fingerprint = _station_fingerprint(query)
            after = _decode_station_cursor(query.cursor, fingerprint, len(order))
            if after is not None:
                page.add(f"({keys}) > ({', '.join('?' * len(order))})", *after)
            rows = connection.execute(
                f"SELECT {_STATION_COLUMNS}, {_order_columns(order)}"
                f" FROM {_STATION_SOURCE}"
                f" WHERE {page.sql()} ORDER BY {keys} LIMIT ?",
                [*page.params, query.limit + 1],
            ).fetchall()
            more = len(rows) > query.limit
            rows = rows[: query.limit]
            coverage = (
                _stations_coverage(connection, stores, rows, query)
                if query.labels
                else ()
            )
        next_cursor = None
        if more and rows:
            last = rows[-1]
            next_cursor = _encode_cursor(
                fingerprint, [last[f"order_{index}"] for index in range(len(order))]
            )
        return StationPage(
            items=tuple(_station(row, stores, found.boundary) for row in rows),
            next_cursor=next_cursor,
            counts=found.counts,
            coverage=coverage,
        )

    def station_map(
        self, query: StationQuery, *, limit: int, grid_columns: int
    ) -> StationMap:
        """Return the located stations of a map view, or their grid above ``limit``.

        Parameters
        ----------
        query : StationQuery
            ``bbox`` is the view (required); the filters, the area and the
            labels apply as in ``stations``. A map holds located stations
            only, so ``location``, ``limit`` and ``cursor`` do not apply.
        limit : int
            Most stations drawn, 1 to ``MAP_FOOTPRINT_LIMIT``; above it the
            view is a grid of counts.
        grid_columns : int
            Columns of the grid, 1 to ``MAX_GRID_COLUMNS`` (rows follow the
            view's shape, as in ``footprints``).

        Returns
        -------
        StationMap
            The stations of the view by name, or the grid; ``counts`` as in
            ``stations`` (the stations without a location are never drawn,
            only counted).

        Raises
        ------
        IndexQueryError
            No view or an invalid one, a limit or grid out of range, or the
            refusals of ``stations``.
        """
        if query.bbox is None:
            raise IndexQueryError(message("index.invalid_bbox"))
        box = require_wgs84_bbox(query.bbox)
        _require_limit(limit, MAP_FOOTPRINT_LIMIT)
        grid = _grid(box, grid_columns)
        _require_station_filters(query)
        with self._read() as connection:
            stores = _stores(connection)
            found = _select_stations(connection, stores, query, box)
            rows = connection.execute(
                f"SELECT {_STATION_COLUMNS} FROM {_STATION_SOURCE}"
                f" WHERE {found.located.sql()} ORDER BY {_NAME_ORDER}",
                found.located.params,
            ).fetchall()
            if len(rows) > limit:
                points = [(row["lon"], row["lat"]) for row in rows]
                cells = grid.count(points)
                return StationMap(len(rows), True, (), cells, found.counts)
            coverage = (
                _stations_coverage(connection, stores, rows, query)
                if query.labels
                else ()
            )
        return StationMap(
            total=len(rows),
            aggregated=False,
            items=tuple(_station(row, stores, found.boundary) for row in rows),
            cells=(),
            counts=found.counts,
            coverage=coverage,
        )

    def station(self, store: str, provider: str, code: str) -> StationRow | None:
        """Return one station of a store, or ``None`` when its catalog lacks it.

        Parameters
        ----------
        store : str
            Configured store id.
        provider : str
            The station's provider (``IMGW-PIB``, ``CHMI``).
        code : str
            The station's code, as text.
        """
        with self._read() as connection:
            stores = _stores(connection)
            row = connection.execute(
                f"SELECT {_STATION_COLUMNS} FROM {_STATION_SOURCE}"
                " WHERE s.store_id = ? AND s.provider = ? AND s.code = ?",
                (_store_id(stores, store), provider, code),
            ).fetchone()
        return None if row is None else _station(row, stores)

    def station_datasets(
        self, store: str | None = None, *, year_types: YearTypes = DEFAULT_YEAR_TYPES
    ) -> tuple[StationDataset, ...]:
        """Return the datasets with station series in the index (the dataset chip).

        Parameters
        ----------
        store : str or None
            One configured store id; ``None``: every store.
        year_types : YearTypes
            The year type remembered for each family: the numbering of each
            dataset's labels and of its R (P15).

        Returns
        -------
        tuple[StationDataset, ...]
            One per store and dataset of the series catalogs (the current
            series version of each), by store and dataset key: the
            producer's name of its segment, R by default in the year type of
            its labels and the distinct variable keys of its stations'
            series, in the order of the series index.
        """
        with self._read() as connection:
            stores = _stores(connection)
            where = _Where()
            if store is not None:
                where.add("c.store_id = ?", _store_id(stores, store))
            rows = connection.execute(
                "SELECT c.store_id, c.dataset, c.provider, c.kind, c.time_unit,"
                " c.first_year, c.periods, c.version_path, sv.label AS series,"
                " g.name AS segment_name FROM series_catalogs c"
                " LEFT JOIN versions sv"
                " ON sv.store_id = c.store_id AND sv.path = c.version_path"
                " LEFT JOIN slots sl"
                " ON sl.store_id = c.store_id AND sl.path = c.slot_path"
                " LEFT JOIN segments g ON g.id = sl.segment_id"
                f" WHERE {where.sql()} ORDER BY c.store_id, c.dataset",
                where.params,
            ).fetchall()
            # SQLite takes the bare columns of a ``min`` group from its row:
            # each key with its first row, so the keys keep the index's order.
            keys: dict[tuple[int, str], list[DatasetVariable]] = {}
            for row in connection.execute(
                "SELECT x.store_id, x.dataset, x.variable_key, x.variable, x.unit,"
                " x.period, min(x.id) AS first FROM station_series x"
                " JOIN series_catalogs c"
                " ON c.store_id = x.store_id AND c.dataset = x.dataset"
                f" WHERE {where.sql()} GROUP BY x.store_id, x.dataset, x.variable_key"
                " ORDER BY x.store_id, x.dataset, first",
                where.params,
            ):
                keys.setdefault((row["store_id"], row["dataset"]), []).append(
                    DatasetVariable(
                        key=row["variable_key"],
                        variable=row["variable"],
                        unit=row["unit"],
                        period=row["period"],
                    )
                )
        found: list[StationDataset] = []
        for row in rows:
            unit = row["time_unit"]
            numbering = label_year_type(row["kind"], unit, None, year_types)
            found.append(
                StationDataset(
                    store=stores[row["store_id"]],
                    dataset=row["dataset"],
                    name=row["segment_name"],
                    provider=row["provider"],
                    kind=row["kind"],
                    time_unit=unit,
                    year_type=numbering,
                    span=default_span(
                        row["first_year"],
                        _date_ranges(row["periods"]),
                        time_unit=unit,
                        year_type=numbering,
                    ),
                    series=row["series"],
                    series_version=row["version_path"],
                    variables=tuple(keys.get((row["store_id"], row["dataset"]), ())),
                )
            )
        return tuple(found)

    # Coverage of the series of stations.

    def station_coverage(
        self,
        store: str,
        provider: str,
        code: str,
        *,
        dataset: str | None = None,
        year_type: YearType | None = None,
        years: YearRange | None = None,
        year_types: YearTypes = DEFAULT_YEAR_TYPES,
    ) -> tuple[StationCoverage, ...]:
        """Return the coverage of a station's series with its labels (SPEC 4.8.4).

        Everything comes from ``station_series`` and ``series_years``: no
        series file is read, and changing the range or the year type reads
        nothing else.

        Parameters
        ----------
        store, provider, code : str
            The station: configured store id, provider and code as text.
        dataset : str or None
            One dataset only; ``None``: every dataset with a series of it.
        year_type : {"hydrological", "calendar"} or None
            The numbering of the years; ``None``: the one ``year_types``
            remembers for each dataset's family. Half-year characteristics
            stay in hydrological years whatever is asked (SPEC 4.8.2).
        years : tuple[int, int] or None
            R, the first and last year; ``None``: from the dataset's first
            year (else the first known one) to the last year of the known
            periods of its version.
        year_types : YearTypes
            The year type remembered for each family (P15).

        Returns
        -------
        tuple[StationCoverage, ...]
            By dataset; empty when the index holds no series of the station.

        Raises
        ------
        IndexQueryError
            A range whose first year comes after its last.
        """
        if years is not None and years[0] > years[1]:
            raise IndexQueryError(
                message("index.invalid_years", start=years[0], end=years[1])
            )
        with self._read() as connection:
            stores = _stores(connection)
            where = _Where()
            where.add("s.store_id = ?", _store_id(stores, store))
            where.add("s.provider = ?", provider)
            where.add("s.code = ?", code)
            if dataset is not None:
                where.add("s.dataset = ?", dataset)
            return _series_coverage(
                connection,
                stores,
                where,
                year_type=year_type,
                year_types=year_types,
                years=years,
            )

    def unused_versions(self, store: str) -> UnusedVersions | None:
        """Report present versions no link names and no project pins.

        Products are the segments' (``None``: unrecognised segments); each
        content counts once. ``None`` for a store that is not indexed.
        """
        with self._read() as connection:
            stores = _stores(connection)
            if store not in stores.values():
                return None
            store_id = _store_id(stores, store)
            products = {
                int(row[0]): row[1]
                for row in connection.execute(
                    "SELECT id, product FROM segments WHERE store_id = ?", (store_id,)
                ).fetchall()
            }
            cursor = connection.cursor()
            cursor.row_factory = None
            rows = cursor.execute(
                "SELECT v.segment_id, v.sha256, v.size_bytes,"
                " v.id IS NOT s.current_version_id"
                " AND v.id IS NOT s.full_sheet_version_id"
                f" AND NOT {_PINNED}"
                " FROM versions v JOIN slots s ON s.id = v.slot_id"
                " WHERE v.store_id = ? AND v.state = 'present'",
                (store_id,),
            ).fetchall()
        held = {digest for _, digest, _, unused in rows if not unused and digest}
        counts: dict[str | None, int] = {}
        loose: dict[str | None, int] = {}
        contents: dict[str | None, dict[str, int]] = {}
        everywhere: dict[str, int] = {}
        for segment_id, digest, size, unused in rows:
            if not unused:
                continue
            product = products.get(segment_id)
            counts[product] = counts.get(product, 0) + 1
            if digest is None:
                loose[product] = loose.get(product, 0) + (size or 0)
            else:
                contents.setdefault(product, {})[digest] = size or 0
                everywhere[digest] = size or 0
        return UnusedVersions(
            store=store,
            products=tuple(
                ProductUsage(
                    product,
                    counts[product],
                    loose.get(product, 0) + sum(contents.get(product, {}).values()),
                )
                for product in sorted(
                    counts, key=lambda item: (item is None, item or "")
                )
            ),
            versions=sum(counts.values()),
            unique_bytes=sum(loose.values()) + sum(everywhere.values()),
            reclaimable_bytes=sum(loose.values())
            + sum(size for digest, size in everywhere.items() if digest not in held),
        )

    def orphan_links(self, store: str) -> tuple[OrphanLink, ...]:
        """Return links whose sidecar names a version that is not present."""
        with self._read() as connection:
            stores = _stores(connection)
            store_id = _store_id(stores, store)
            rows = connection.execute(
                "SELECT s.path AS slot, g.segment, 'link' AS kind,"
                " s.current_path AS version, g.producer FROM slots s"
                " JOIN segments g ON g.id = s.segment_id"
                " LEFT JOIN versions v ON v.id = s.current_version_id"
                " WHERE s.store_id = ? AND s.current_path IS NOT NULL"
                " AND (v.id IS NULL OR v.state = 'missing')"
                " UNION ALL"
                " SELECT s.path, g.segment, 'full_sheet', s.full_sheet_path, g.producer"
                " FROM slots s JOIN segments g ON g.id = s.segment_id"
                " LEFT JOIN versions v ON v.id = s.full_sheet_version_id"
                " WHERE s.store_id = ? AND s.full_sheet_path IS NOT NULL"
                " AND (v.id IS NULL OR v.state = 'missing')"
                " ORDER BY 2, 1, 3",
                (store_id, store_id),
            ).fetchall()
        return tuple(
            OrphanLink(
                slot=row["slot"],
                segment=row["segment"] or None,
                producer=row["producer"],
                kind=row["kind"],
                version=row["version"],
            )
            for row in rows
        )

    # Projects.

    def projects(
        self, *, visible: ProjectVisibility, store: str | None = None
    ) -> tuple[ProjectRef, ...]:
        """Return the discovered projects the principal sees, ordered by name.

        Parameters
        ----------
        visible : ProjectVisibility
            Projects the principal sees.
        store : str or None, optional
            Only projects of this configured store: one of their manifests
            names it.
        """
        where = _Where()
        if store is not None:
            where.add(_PROJECT_OF_STORE, store)
        condition, params = _visible(visible)
        where.add(condition, *params)
        with self._read() as connection:
            rows = connection.execute(
                f"{_PROJECT_SELECT} WHERE {where.sql()} ORDER BY pr.name, pr.key",
                where.params,
            ).fetchall()
            manifests = _manifests(connection, [row["id"] for row in rows])
        return tuple(_project_ref(row, manifests.get(row["id"], ())) for row in rows)

    def project(self, key: str, *, visible: ProjectVisibility) -> ProjectRecord | None:
        """Return a project with the tasks and pins of each of its manifests.

        Parameters
        ----------
        key : str
            Project key (``ProjectRef.key``).
        visible : ProjectVisibility
            Projects the principal sees.

        Returns
        -------
        ProjectRecord or None
            ``None`` for an unknown project and for one the principal does
            not see, alike (``404``).
        """
        condition, params = _visible(visible)
        with self._read() as connection:
            row = connection.execute(
                f"{_PROJECT_SELECT} WHERE pr.key = ? AND {condition}", (key, *params)
            ).fetchone()
            if row is None:
                return None
            manifests = _manifests(connection, [row["id"]])
            tasks = connection.execute(
                "SELECT producer, task_id, command, options, status FROM project_tasks"
                " WHERE project_id = ? ORDER BY producer, position",
                (row["id"],),
            ).fetchall()
            pins = connection.execute(
                "SELECT p.producer, p.task_id, p.version_path, p.sha256,"
                f" {_PIN_STATE} AS state, s.path AS slot, v.label, v.size_bytes,"
                " coalesce(v.id = s.current_version_id, 0) AS is_current"
                f" FROM {_PIN_SOURCE} LEFT JOIN slots s ON s.id = v.slot_id"
                " WHERE p.project_id = ? ORDER BY p.producer, p.id",
                (row["id"],),
            ).fetchall()
        return ProjectRecord(
            project=_project_ref(row, manifests.get(row["id"], ())),
            tasks=tuple(
                ProjectTaskRef(
                    producer=task["producer"],
                    task_id=task["task_id"],
                    command=task["command"],
                    options=json.loads(task["options"]),
                    status=task["status"],
                )
                for task in sorted(tasks, key=_by_producer)
            ),
            pins=tuple(
                ProjectPinRef(
                    producer=pin["producer"],
                    task=pin["task_id"],
                    version=pin["version_path"],
                    sha256=pin["sha256"],
                    state=pin["state"],
                    slot=pin["slot"],
                    label=pin["label"],
                    size_bytes=pin["size_bytes"],
                    is_current=bool(pin["is_current"]),
                )
                for pin in sorted(pins, key=_by_producer)
            ),
        )

    def pin_problems(
        self, store: str, *, visible: ProjectVisibility
    ) -> tuple[PinRef, ...]:
        """Return pins of a store's projects whose version is missing or other.

        Only pins of projects the principal sees (``visible``) are listed.
        """
        condition, params = _visible(visible)
        with self._read() as connection:
            stores = _stores(connection)
            rows = connection.execute(
                "SELECT pr.name, pr.key, p.producer, p.task_id, p.version_path,"
                " p.sha256,"
                f" {_PIN_STATE} AS state FROM {_PIN_SOURCE}"
                " JOIN projects pr ON pr.id = p.project_id"
                f" WHERE p.store_id = ? AND {_PIN_STATE} <> 'ok' AND {condition}"
                " ORDER BY pr.key, p.producer, p.task_id, p.version_path",
                (_store_id(stores, store), *params),
            ).fetchall()
        return tuple(
            PinRef(
                project=row["name"],
                project_key=row["key"],
                producer=row["producer"],
                task=row["task_id"],
                version=row["version_path"],
                sha256=row["sha256"],
                state=row["state"],
            )
            for row in rows
        )

    def status(self) -> IndexStatus:
        """Return the index's state and each store's index state and jobs."""
        with self._read() as connection:
            info = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    "SELECT key, value FROM index_info"
                ).fetchall()
            }
            rows = connection.execute(
                "SELECT st.id, st.key, st.status, st.status_at, st.detail,"
                " st.indexed_at,"
                " (SELECT count(*) FROM slots s WHERE s.store_id = st.id) AS slots,"
                " (SELECT count(*) FROM versions v WHERE v.store_id = st.id)"
                " AS versions,"
                " (SELECT count(*) FROM versions v WHERE v.store_id = st.id"
                " AND v.state = 'missing') AS missing,"
                " (SELECT count(*) FROM versions v WHERE v.store_id = st.id"
                " AND v.location = 'none') AS unlocated,"
                " (SELECT count(*) FROM issues i WHERE i.store_id = st.id) AS issues,"
                # Same rule as JobSupervisor.scan_history's full_at.
                " (SELECT max(j.finished_at) FROM jobs j WHERE j.store = st.key"
                " AND j.kind = 'scan' AND j.state = 'succeeded'"
                " AND json_extract(j.params, '$.mode') = 'full'"
                " AND json_extract(j.params, '$.segment') IS NULL) AS full_scan_at"
                " FROM stores st ORDER BY st.key"
            ).fetchall()
            states = tuple(
                StoreIndexState(
                    store=row["key"],
                    status=row["status"],
                    status_at=_datetime(row["status_at"]),
                    detail=row["detail"],
                    indexed_at=_datetime(row["indexed_at"]),
                    full_scan_at=_datetime(row["full_scan_at"]),
                    slots=int(row["slots"]),
                    versions=int(row["versions"]),
                    missing_versions=int(row["missing"]),
                    unlocated_versions=int(row["unlocated"]),
                    issues=int(row["issues"]),
                    last_scan=_job(
                        connection,
                        "store = ? AND kind = 'scan' AND state IN"
                        " ('succeeded', 'failed', 'interrupted', 'cancelled')",
                        row["key"],
                        order="coalesce(finished_at, created_at) DESC",
                    ),
                    running_job=_job(
                        connection,
                        "store = ? AND state IN ('queued', 'running')",
                        row["key"],
                        order="created_at DESC",
                    ),
                    stale=row["status"] == "unavailable",
                )
                for row in rows
            )
        size = sum(
            os.path.getsize(name)
            for name in (self._path, Path(f"{self._path}-wal"))
            if os.path.exists(name)
        )
        return IndexStatus(
            schema_version=SCHEMA_VERSION,
            created_at=_datetime(info.get("created_at")),
            size_bytes=size,
            stores=states,
        )

    def freshness(self) -> tuple[StoreFreshness, ...]:
        """Return each store's availability and last complete pass, by store id.

        A cheap companion of ``status`` (no counts, no jobs) for marking
        answers of an unavailable store as ``stale``.
        """
        with self._read() as connection:
            rows = connection.execute(
                "SELECT key, status, status_at, detail, indexed_at FROM stores"
                " ORDER BY key"
            ).fetchall()
        return tuple(
            StoreFreshness(
                store=row["key"],
                status=row["status"],
                status_at=_datetime(row["status_at"]),
                detail=row["detail"],
                indexed_at=_datetime(row["indexed_at"]),
                stale=row["status"] == "unavailable",
            )
            for row in rows
        )

    def area(self, area_id: str) -> AreaRecord | None:
        """Return a kept area, or ``None`` when there is none with this id."""
        with self._read() as connection:
            row = connection.execute(
                "SELECT id, source, geometry, created_at, area_km2, countries, name"
                " FROM areas WHERE id = ?",
                (area_id,),
            ).fetchone()
        if row is None:
            return None
        return AreaRecord(
            id=row["id"],
            source=row["source"],
            geometry=json.loads(row["geometry"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            area_km2=row["area_km2"],
            countries=tuple(json.loads(row["countries"])),
            name=row["name"],
        )

    def availability(
        self, area_id: str, product: str, *, producer: str
    ) -> StoredAvailability | None:
        """Return the last report of an area and product, ``None`` without one."""
        with self._read() as connection:
            row = connection.execute(
                "SELECT checked_at, job_id, report FROM availability"
                " WHERE area_id = ? AND producer = ? AND product = ?",
                (area_id, producer, product),
            ).fetchone()
        if row is None:
            return None
        return StoredAvailability(
            area_id=area_id,
            producer=producer,
            product=product,
            checked_at=datetime.fromisoformat(row["checked_at"]),
            job_id=row["job_id"],
            report=AvailabilityReport.from_json(json.loads(row["report"])),
        )

    def plans(self, job_id: str) -> tuple[StoredPlan, ...]:
        """Return the plans of a ``check`` job's calls, in their order; none without.

        A call whose check failed has no plan: the job's result says why.
        """
        with self._read() as connection:
            rows = connection.execute(
                "SELECT call, store, line, plan FROM plans WHERE job_id = ?"
                " ORDER BY call",
                (job_id,),
            ).fetchall()
        return tuple(
            StoredPlan(
                job_id=job_id,
                call=row["call"],
                store=row["store"],
                line=row["line"],
                plan=ActionPlan.from_json(json.loads(row["plan"])),
            )
            for row in rows
        )

    def held_units(
        self,
        store: str,
        *,
        dataset: str,
        units: Sequence[str],
        year: int | None,
        campaigns: Sequence[str],
    ) -> frozenset[str]:
        """Return the units of which a store holds a version of a dataset.

        A present version counts when its dataset is ``dataset``, its slot's
        unit one of ``units``, its data year ``year`` and its campaign one of
        ``campaigns``; ``None`` and an empty ``campaigns`` ask for any (the
        store badge of an availability combination, SPEC 6.4).
        """
        if not units:
            return frozenset()
        with self._read() as connection:
            where = _Where()
            where.add("s.store_id = ?", _store_id(_stores(connection), store))
            where.add(f"s.unit IN ({_IDS})", json.dumps(list(units)))
            where.add("v.state = 'present'")
            where.add("v.dataset = ?", dataset)
            if year is not None:
                where.add("v.data_year = ?", year)
            if campaigns:
                where.add(f"v.campaign IN ({_IDS})", json.dumps(list(campaigns)))
            found = connection.execute(
                "SELECT DISTINCT s.unit FROM slots s"
                f" JOIN versions v ON v.slot_id = s.id WHERE {where.sql()}",
                where.params,
            ).fetchall()
        return frozenset(str(row[0]) for row in found)

    def local_coverage(
        self,
        area: GeoJSONGeometry,
        *,
        store: str,
        product: str,
        transformer: TransformerFactory,
        countries: Sequence[str] = (),
        segment: str | None = None,
    ) -> LocalCoverageReport:
        """Measure how much of an area the store's current versions cover.

        One result per country: each country of the product's current
        footprints in the area, and each of ``countries`` (the area's) in
        which the store holds the product. The share is measured in the
        country's planar CRS (decision 5); a country without one gives
        ``no_planar_crs``.

        Parameters
        ----------
        area : GeoJSONGeometry
            ``Polygon`` or ``MultiPolygon`` in WGS84.
        store : str
            Configured store id.
        product : str
            Product of the slots (e.g. ``"nmt"``), all its segments.
        transformer : TransformerFactory
            The producer's pinned operations (``GeoAdapter.transformer``).
        countries : Sequence[str], optional
            Countries of the area (``GeoAdapter.countries``).
        segment : str or None, optional
            Only this segment of the product.

        Raises
        ------
        IndexQueryError
            The area is not a polygon in WGS84.
        ProducerError
            The producer has no pinned operation for a needed CRS pair.
        """
        min_lon, min_lat, max_lon, max_lat = require_wgs84_area(area)
        with self._read() as connection:
            stores = _stores(connection)
            store_id = _store_id(stores, store)
            where = _Where()
            where.add("s.store_id = ?", store_id)
            where.add("s.product = ?", product)
            if segment is not None:
                where.add("g.segment = ?", segment)
            held = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT s.country FROM slots s"
                    f" JOIN segments g ON g.id = s.segment_id WHERE {where.sql()}"
                    " AND s.current_version_id IS NOT NULL",
                    where.params,
                ).fetchall()
            }
            where.add(
                "f.max_lon > ? AND f.min_lon < ? AND f.max_lat > ? AND f.min_lat < ?",
                min_lon,
                max_lon,
                min_lat,
                max_lat,
            )
            rows = connection.execute(
                "SELECT s.country, v.is_box, v.min_lon, v.min_lat, v.max_lon,"
                " v.max_lat, v.native_crs, sh.wgs84, sh.native FROM footprints f"
                " JOIN versions v ON v.id = f.id"
                " JOIN slots s ON s.current_version_id = v.id"
                " JOIN segments g ON g.id = s.segment_id"
                " LEFT JOIN version_shapes sh ON sh.version_id = v.id"
                f" WHERE {where.sql()} ORDER BY v.id",
                where.params,
            ).fetchall()
        shapes: dict[str | None, list[CoverageShape]] = {}
        for row in rows:
            outline = (
                box_geometry((row[2], row[3], row[4], row[5]))
                if row[1] or row[7] is None
                else json.loads(row[7])
            )
            native = None if row[8] is None else json.loads(row[8])
            shapes.setdefault(row[0], []).append(
                CoverageShape(outline, native, row[6] if native else None)
            )
        wanted = set(shapes) | (set(countries) & held)
        results = []
        for country in sorted(wanted, key=lambda item: (item is None, item or "")):
            results.append(
                _coverage(area, shapes.get(country, []), country, transformer)
            )
        return LocalCoverageReport(store=store, product=product, results=tuple(results))

    # Own data of projects (decision 8).

    def own_folder(
        self, project: str, *, visible: ProjectVisibility
    ) -> OwnFolderRecord | None:
        """Return a project's data folder as its last ``own_scan`` found it.

        Parameters
        ----------
        project : str
            Project key (``ProjectRef.key``).
        visible : ProjectVisibility
            Projects the principal sees.

        Returns
        -------
        OwnFolderRecord or None
            ``None`` for an unknown project, one the principal does not see,
            and one whose folder was never scanned.
        """
        with self._read() as connection:
            row = _own_folder_row(connection, project, visible)
            return None if row is None else _own_folder(connection, row)

    def own_files(
        self,
        project: str,
        *,
        visible: ProjectVisibility,
        q: str | None = None,
        state: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> OwnFilePage | None:
        """Return a page of a project's own files, ordered by path.

        Parameters
        ----------
        project : str
            Project key.
        visible : ProjectVisibility
            Projects the principal sees.
        q : str or None, optional
            Words that must all occur in the path (letter case of ASCII
            ignored).
        state : str or None, optional
            Only files in this state (``ok``, ``unrecognized``,
            ``unreadable``, ``missing``) or present files of this change
            (``unsnapshotted``, ``unchanged``, ``changed``).
        limit : int, default 50
            Page size, 1 to 200.
        cursor : str or None, optional
            ``next_cursor`` of the previous page of the same filters.

        Returns
        -------
        OwnFilePage or None
            ``None`` as for ``own_folder``.

        Raises
        ------
        IndexQueryError
            An unknown state, a limit out of range or a cursor of other
            filters.
        """
        _require_limit(limit, MAX_PAGE_LIMIT)
        where = _Where()
        if state is not None:
            condition, values = _own_state(state)
            where.add(condition, *values)
        words = (q or "").split()
        for word in words:
            escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.add("f.path LIKE ? ESCAPE '\\'", f"%{escaped}%")
        fingerprint = hashlib.sha256(
            json.dumps([project, state, words]).encode()
        ).hexdigest()[:16]
        after = _decode_own_cursor(cursor, fingerprint)
        if after is not None:
            where.add("f.path > ?", after)
        with self._read() as connection:
            row = _own_folder_row(connection, project, visible)
            if row is None:
                return None
            folder = _own_folder(connection, row)
            rows = connection.execute(
                f"SELECT {_OWN_FILE_COLUMNS} FROM own_files f"
                f" WHERE f.folder_id = ? AND {where.sql()} ORDER BY f.path LIMIT ?",
                (row["id"], *where.params, limit + 1),
            ).fetchall()
        items = tuple(_own_file_row(item) for item in rows[:limit])
        next_cursor = None
        if len(rows) > limit:
            next_cursor = _encode_own_cursor(fingerprint, rows[limit - 1]["path"])
        return OwnFilePage(folder=folder, items=items, next_cursor=next_cursor)

    def own_file(
        self, project: str, file_id: str, *, visible: ProjectVisibility
    ) -> OwnFileDetail | None:
        """Return the card of one own file: what was read, history, snapshots.

        Parameters
        ----------
        project : str
            Project key.
        file_id : str
            The file's id (``own_file_id`` of its path).
        visible : ProjectVisibility
            Projects the principal sees.

        Returns
        -------
        OwnFileDetail or None
            ``None`` as for ``own_folder``, and for an unknown file.
        """
        with self._read() as connection:
            row = _own_folder_row(connection, project, visible)
            if row is None:
                return None
            found = connection.execute(
                f"SELECT {_OWN_FILE_COLUMNS}, f.disk_path, f.stamp, f.members,"
                " f.read_error,"
                " f.read_detail, f.content_method, f.content_sha256, f.layers,"
                " f.raster, f.feature_count, f.native_crs, f.native_bbox,"
                " f.first_seen_at, f.changed_at"
                " FROM own_files f WHERE f.folder_id = ? AND f.file_id = ?",
                (row["id"], file_id),
            ).fetchone()
            if found is None:
                return None
            folder = _own_folder(connection, row)
            history = connection.execute(
                "SELECT observed_at, size_bytes, modified_ns, content_sha256,"
                " feature_count FROM own_file_states WHERE own_file_id = ?"
                " ORDER BY seq DESC",
                (found["id"],),
            ).fetchall()
            snapshots = connection.execute(
                "SELECT path, label, state, created_at, content_method,"
                " content_sha256, size_bytes, document FROM snapshots"
                " WHERE folder_id = ? AND path = ?"
                " ORDER BY created_at IS NULL, created_at DESC, label DESC",
                (row["id"], found["path"]),
            ).fetchall()
        prefix = f"{SNAPSHOTS_DIR}/{found['path']}/"
        return OwnFileDetail(
            file=_own_file_row(found),
            folder=folder,
            disk_path=found["disk_path"],
            stamp=found["stamp"],
            members=tuple(json.loads(found["members"])),
            read_error=found["read_error"],
            read_detail=found["read_detail"],
            content_method=found["content_method"],
            content_sha256=found["content_sha256"],
            layers=tuple(_layer(layer) for layer in json.loads(found["layers"])),
            raster=_raster(found["raster"]),
            feature_count=found["feature_count"],
            native_crs=found["native_crs"],
            native_bbox=_own_bbox(found["native_bbox"]),
            wgs84=None if found["wgs84"] is None else json.loads(found["wgs84"]),
            first_seen_at=datetime.fromisoformat(found["first_seen_at"]),
            changed_at=datetime.fromisoformat(found["changed_at"]),
            missing_since=_datetime(found["missing_since"]),
            history=tuple(
                OwnFileObservation(
                    observed_at=datetime.fromisoformat(state["observed_at"]),
                    size_bytes=state["size_bytes"],
                    modified_at=_from_ns(state["modified_ns"]),
                    content_sha256=state["content_sha256"],
                    feature_count=state["feature_count"],
                )
                for state in history
            ),
            snapshots=tuple(_snapshot(item) for item in snapshots),
            problems=tuple(
                problem
                for problem in folder.problems
                if problem.path == found["path"]
                or (problem.path or "").startswith(prefix)
            ),
        )

    # Connections.

    def _connection(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            connection = connect(self._path, readonly=True)
            connection.row_factory = sqlite3.Row
            self._local.connection = connection
            with self._lock:
                self._connections.append(connection)
        return connection

    def _map_groups(
        self, connection: sqlite3.Connection, versions: VersionsMode, where: _Where
    ) -> LocationCounts:
        """Reuse catalog totals until the index changes, per reader connection."""
        revision = connection.execute("PRAGMA data_version").fetchone()[0]
        cached = getattr(self._local, "map_groups", None)
        if cached is None or revision != cached[0]:
            cache: dict[tuple[object, ...], LocationCounts] = {}
            self._local.map_groups = (revision, cache)
        else:
            cache = cached[1]
        key = (versions, where.sql(), tuple(where.params))
        groups = cache.get(key)
        if groups is None:
            groups = _groups(connection, versions, where)
            if len(cache) >= 64:
                cache.pop(next(iter(cache)))
            cache[key] = groups
        return groups

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        """One read snapshot for every statement of a query."""
        connection = self._connection()
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            if connection.in_transaction:
                connection.execute("COMMIT")


def _require_limit(limit: int, maximum: int) -> None:
    if not 1 <= limit <= maximum:
        raise IndexQueryError(message("index.invalid_limit", limit=maximum))


def _filters(query: SlotQuery | MapQuery) -> _Filters:
    years = query.years
    if years is not None:
        start, end = years
        if start is not None and end is not None and start > end:
            raise IndexQueryError(message("index.invalid_years", start=start, end=end))
        if start is None and end is None:
            years = None
    q = query.q.strip() if query.q else None
    return _Filters(
        q=q or None,
        store=query.store,
        product=query.product,
        country=query.country,
        years=years,
        unit=query.unit,
        versions=query.versions,
        status=query.status,
        project=query.project,
    )


def _stores(connection: sqlite3.Connection) -> dict[int, str]:
    return {
        int(row[0]): str(row[1])
        for row in connection.execute("SELECT id, key FROM stores").fetchall()
    }


def _store_id(stores: Mapping[int, str], store: str) -> int:
    """Row id of a store; ``-1`` (matching nothing) for an unknown one."""
    return next((key for key, name in stores.items() if name == store), -1)


def _where(
    connection: sqlite3.Connection,
    filters: _Filters,
    stores: Mapping[int, str],
    visible: ProjectVisibility,
) -> _Where:
    """Conditions of the filters on ``s`` (slot), ``g`` (segment), ``v`` (version)."""
    where = _Where()
    for condition in _SOURCES[filters.versions][1]:
        where.add(condition)
    if filters.versions == "pinned":
        seen, params = _visible(visible)
        where.add(_PINNED_VISIBLE.format(visible=seen), *params)
    if filters.project is not None:
        seen, params = _visible(visible)
        where.add(
            _PINNED_VISIBLE.format(visible=f"pr.key = ? AND {seen}"),
            filters.project,
            *params,
        )
    if filters.store is not None:
        where.add("s.store_id = ?", _store_id(stores, filters.store))
    if filters.product is not None:
        where.add("s.product = ?", filters.product)
    if filters.country is not None:
        where.add("s.country = ?", filters.country)
    if filters.unit is not None:
        where.add("s.unit = ?", filters.unit)
    if filters.years is not None:
        start, end = filters.years
        if start is not None:
            where.add("v.data_year >= ?", start)
        if end is not None:
            where.add("v.data_year <= ?", end)
    if filters.status is not None:
        where.add(f"{_STATUS} = ?", filters.status)
    if filters.q is not None:
        _search(where, filters.q, current=filters.versions == "current")
    return where


def _search(where: _Where, text: str, *, current: bool) -> None:
    """Every word must match the slot's search row (or a SHA-256 prefix)."""
    phrases: list[str] = []
    for word in text.split():
        if not _WORD.search(word):
            continue
        folded = word.replace("ł", "l").replace("Ł", "L")
        phrase = '"' + folded.replace('"', '""') + '"*'
        if _SHA_PREFIX.fullmatch(word) is None:
            phrases.append(phrase)
            continue
        low = word.lower()
        sha = (
            "s.id IN (SELECT slot_id FROM versions WHERE sha256 >= ? AND sha256 < ?)"
            if current
            else "(v.sha256 >= ? AND v.sha256 < ?)"
        )
        where.add(
            f"s.id IN (SELECT rowid FROM search WHERE search MATCH ?) OR {sha}",
            phrase,
            low,
            f"{low}g",
        )
    if phrases:
        where.add(
            "s.id IN (SELECT rowid FROM search WHERE search MATCH ?)", " ".join(phrases)
        )


def _area(connection: sqlite3.Connection, area: AreaFilter) -> _Area:
    """Rows an area admits: footprints sharing interior, its countries, none.

    Box footprints in a box area are decided in SQL by their exact bounds
    (strict comparisons: a neighbour sheet sharing only an edge stays
    out); other outlines are tested with shapely.
    """
    bounds = require_wgs84_area(area.geometry)
    min_lon, min_lat, max_lon, max_lat = bounds
    region = shapely.make_valid(shape(area.geometry))
    box_area = is_box(area.geometry, bounds)
    overlap = (
        "v.id IN (SELECT id FROM footprints WHERE min_lon < ? AND max_lon > ?"
        " AND min_lat < ? AND max_lat > ?)"
        " AND v.min_lon < ? AND v.max_lon > ? AND v.min_lat < ? AND v.max_lat > ?"
    )
    box_params = (max_lon, min_lon, max_lat, min_lat) * 2
    hits = _refine(connection, region, bounds, boxes_too=not box_area)
    if box_area:
        footprint = f"{overlap} AND (v.is_box = 1 OR v.id IN ({_IDS}))"
        params: tuple[object, ...] = (*box_params, json.dumps(hits))
    else:
        footprint = f"v.id IN ({_IDS})"
        params = (json.dumps(hits),)
    admits = (
        f"{_LOCATION} = 'none'"
        " OR (v.location = 'country' AND coalesce(v.country, s.country)"
        f" IN ({_IDS})) OR (v.location = 'footprint' AND {footprint})"
    )
    return _Area(admits, (json.dumps(list(area.countries)), *params))


def _map_item_json(row: sqlite3.Row, store: str) -> str:
    """Serialize one indexed outline, reusing polygon JSON already in SQLite."""
    fields = json.dumps(
        {
            "store": store,
            "slot": row[1],
            "version": row[2],
            "segment": row[3] or None,
            "product": row[4],
            "label": row[5],
            "data_year": row[6],
            "source": row[7],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    geometry = (
        json.dumps(
            box_geometry((row[9], row[10], row[11], row[12])),
            separators=(",", ":"),
        )
        if row[8] or row[13] is None
        else row[13]
    )
    return f'{fields[:-1]},"geometry":{geometry}}}'


def _refine(
    connection: sqlite3.Connection, region: Any, bounds: BBox, *, boxes_too: bool
) -> list[int]:
    """Footprints sharing interior with ``region`` (not just an edge)."""
    min_lon, min_lat, max_lon, max_lat = bounds
    rows = connection.execute(
        "SELECT v.id, v.is_box, v.min_lon, v.min_lat, v.max_lon, v.max_lat,"
        " sh.wgs84 FROM footprints f JOIN versions v ON v.id = f.id"
        " LEFT JOIN version_shapes sh ON sh.version_id = v.id"
        " WHERE f.min_lon < ? AND f.max_lon > ? AND f.min_lat < ? AND f.max_lat > ?"
        + ("" if boxes_too else " AND v.is_box = 0"),
        (max_lon, min_lon, max_lat, min_lat),
    ).fetchall()
    if not rows:
        return []
    geometries = [
        shapely.box(row[2], row[3], row[4], row[5])
        if row[1] or row[6] is None
        else shape(json.loads(row[6]))
        for row in rows
    ]
    shapely.prepare(region)
    inside = shapely.intersects(region, geometries) & ~shapely.touches(
        region, geometries
    )
    return [int(row[0]) for row, hit in zip(rows, inside, strict=True) if hit]


def _groups(
    connection: sqlite3.Connection, versions: VersionsMode, where: _Where
) -> LocationCounts:
    source, _ = _SOURCES[versions]
    counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            f"SELECT CASE WHEN {_LOCATION} = 'none' THEN 'none'"
            " WHEN v.location = 'country' THEN 'country' ELSE 'footprint' END,"
            f" count(*) FROM {source} WHERE {where.sql()} GROUP BY 1",
            where.params,
        ).fetchall()
    }
    return LocationCounts(
        footprint=counts.get("footprint", 0),
        country=counts.get("country", 0),
        none=counts.get("none", 0),
    )


def _fingerprint(query: SlotQuery) -> str:
    """Identity of a query's rows: a cursor is valid only for the same one."""
    area = None
    if query.area is not None:
        area = [
            json.dumps(query.area.geometry, sort_keys=True),
            list(query.area.countries),
        ]
    identity = [
        query.q,
        query.store,
        query.product,
        query.country,
        list(query.years) if query.years else None,
        query.unit,
        query.location,
        query.versions,
        query.status,
        query.project,
        area,
    ]
    data = json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.blake2b(data, digest_size=8).hexdigest()


def _encode_cursor(fingerprint: str, values: list[object]) -> str:
    data = json.dumps([_CURSOR_VERSION, fingerprint, *values], ensure_ascii=False)
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def _parse_cursor(cursor: str) -> Any:
    """Return the JSON a cursor encodes; anything else is an invalid cursor."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise IndexQueryError(message("index.invalid_cursor")) from None


def _decode_cursor(
    cursor: str | None, fingerprint: str, size: int
) -> list[object] | None:
    if cursor is None:
        return None
    data = _parse_cursor(cursor)
    valid = (
        isinstance(data, list)
        and len(data) == size + 2
        and data[0] == _CURSOR_VERSION
        and data[1] == fingerprint
        and isinstance(data[2], str)
        and isinstance(data[3], str)
        and isinstance(data[4], int)
        and all(isinstance(value, str) for value in data[5:])
    )
    if not valid:
        raise IndexQueryError(message("index.invalid_cursor"))
    return list(data[2:])


def _station_where(query: StationQuery, stores: Mapping[int, str]) -> _Where:
    """Attribute filters of a station query on ``s`` (stations); no box."""
    where = _Where()
    if query.store is not None:
        where.add("s.store_id = ?", _store_id(stores, query.store))
    if query.provider is not None:
        where.add("s.provider = ?", query.provider)
    if query.code is not None:
        where.add("s.code = ?", query.code)
    if query.kind is not None:
        where.add("s.kind = ?", query.kind)
    if query.meteo_kinds:
        where.add(f"s.meteo_kind IN ({_IDS})", json.dumps(sorted(query.meteo_kinds)))
    if query.active is not None:
        where.add("s.active = ?", int(query.active))
    if query.river_code is not None:
        _river(where, query.river_code, query.river_scope)
    text = (query.q or "").strip()
    if text:
        _station_search(where, text)
    dataset = () if query.dataset is None else (query.dataset,)
    in_dataset = "" if query.dataset is None else " AND x.dataset = ?"
    if query.dataset is not None:
        where.add(f"EXISTS (SELECT 1 FROM {_STATION_SERIES}{in_dataset})", *dataset)
    for name in query.variables:
        where.add(
            f"EXISTS (SELECT 1 FROM {_STATION_SERIES}{in_dataset}"
            " AND (x.variable = ? OR x.variable_key = ?) AND x.first_date IS NOT NULL)",
            *dataset,
            name,
            name,
        )
    return where


def _station_search(where: _Where, text: str) -> None:
    """Stations whose name or river contains ``text``, or whose code begins with it.

    The name and the river are compared case-folded (``casefold``, the SQL
    function of ``schema.connect``), the code as given; ``instr`` and
    ``substr`` read every character literally, so none is a wildcard (ADR
    0032 decision 11).
    """
    folded = text.casefold()
    where.add(
        "(instr(casefold(s.name), ?) > 0 OR instr(casefold(s.river), ?) > 0"
        " OR substr(s.code, 1, ?) = ?)",
        folded,
        folded,
        len(text),
        text,
    )


def _river(where: _Where, code: str, scope: RiverScope) -> None:
    """Stations of a river, or of the river with its tributaries (P19).

    A tributary's code begins with the river's: a range ``code <= x < next``
    over the index of hydrographic codes, where ``next`` follows every text
    that begins with ``code``. A code with ``-`` between its parts (ČHMÚ
    ``1-05-03-0110``) begins with whole parts only, so the text after the
    river's code starts with ``-``; one without (IMGW ``21382``) with any
    character.
    """
    river = code.strip()
    if not river:
        raise IndexQueryError(message("index.invalid_river_code"))
    if scope == "exact":
        where.add("s.hydrographic_code = ?", river)
        return
    following = river[:-1] + chr(ord(river[-1]) + 1)
    where.add(
        "s.hydrographic_code >= ? AND s.hydrographic_code < ?"
        " AND (s.hydrographic_code = ? OR instr(s.hydrographic_code, '-') = 0"
        " OR substr(s.hydrographic_code, ?, 1) = '-')",
        river,
        following,
        river,
        len(river) + 1,
    )


def _station_box(where: _Where, box: BBox) -> None:
    """Located stations inside a WGS84 box, edges included.

    The R*Tree keeps 32-bit bounds rounded outward, so it only picks the
    candidates; the stored coordinates decide.
    """
    min_lon, min_lat, max_lon, max_lat = box
    where.add(
        "s.id IN (SELECT id FROM station_points WHERE max_lon >= ? AND min_lon <= ?"
        " AND max_lat >= ? AND min_lat <= ?)"
        " AND s.lon BETWEEN ? AND ? AND s.lat BETWEEN ? AND ?",
        min_lon,
        max_lon,
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        min_lat,
        max_lat,
    )


def _count_stations(connection: sqlite3.Connection, where: _Where) -> int:
    return int(
        connection.execute(
            f"SELECT count(*) FROM stations s WHERE {where.sql()}", where.params
        ).fetchone()[0]
    )


def _station_fingerprint(query: StationQuery) -> str:
    """Identity of a station query's rows: a cursor is valid only for the same one."""
    area = None
    if query.area is not None:
        text = json.dumps(query.area, sort_keys=True, separators=(",", ":"))
        area = hashlib.blake2b(text.encode(), digest_size=8).hexdigest()
    identity = [
        query.store,
        query.provider,
        query.code,
        query.kind,
        sorted(query.meteo_kinds),
        query.active,
        query.river_code,
        query.river_scope,
        query.q,
        query.sort,
        None if query.bbox is None else list(query.bbox),
        query.location,
        area,
        query.boundary,
        query.dataset,
        sorted(query.variables),
        sorted([name, state] for name, state in query.coverage),
        sorted([name, years] for name, years in query.min_complete_years),
        query.year_type,
        [query.year_types.hydro, query.year_types.meteo],
        None if query.years is None else list(query.years),
    ]
    data = json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.blake2b(data, digest_size=8).hexdigest()


def _order_columns(order: tuple[str, ...]) -> str:
    """Select the keys of a station order as ``order_<i>``, for the next cursor."""
    return ", ".join(f"{key} AS order_{index}" for index, key in enumerate(order))


def _decode_station_cursor(
    cursor: str | None, fingerprint: str, width: int
) -> list[object] | None:
    """Return the keys of the row after which a page goes on.

    ``width`` is the number of keys of the query's order (``_STATION_ORDERS``);
    each is a text or an integer.
    """
    if cursor is None:
        return None
    data = _parse_cursor(cursor)
    valid = (
        isinstance(data, list)
        and len(data) == width + 2
        and data[0] == _CURSOR_VERSION
        and data[1] == fingerprint
        and all(
            isinstance(value, str | int) and not isinstance(value, bool)
            for value in data[2:]
        )
    )
    if not valid:
        raise IndexQueryError(message("index.invalid_cursor"))
    return list(data[2:])


def _station(
    row: sqlite3.Row, stores: Mapping[int, str], boundary: Collection[int] = ()
) -> StationRow:
    located = row["location"] == "point"
    active = row["active"]
    return StationRow(
        store=stores[row["store_id"]],
        provider=row["provider"],
        code=row["code"],
        kind=row["kind"],
        meteo_kind=row["meteo_kind"],
        name=row["name"],
        river=row["river"],
        hydrographic_code=row["hydrographic_code"],
        river_order=row["river_order"],
        location="point" if located else "none",
        point=(row["lon"], row["lat"]) if located else None,
        location_reason=row["location_reason"],
        location_source=row["location_source"],
        location_uncertainty_m=row["location_uncertainty_m"],
        active=None if active is None else bool(active),
        established_year=row["established_year"],
        gauge_zero_m=row["gauge_zero_m"],
        river_km=row["river_km"],
        elevation_m=row["elevation_m"],
        catalog=row["catalog"],
        catalog_version=row["catalog_version"],
        on_boundary=row["id"] in boundary,
    )


@dataclass(frozen=True, slots=True)
class _Stations:
    """The stations of a query by location group, with their counts.

    ``located`` and ``unlocated`` select the rows of each group on ``s``
    (stations), ``every`` both; ``boundary`` holds the ids of the stations on
    the area's boundary that pass the other filters.
    """

    located: _Where
    unlocated: _Where
    every: _Where
    boundary: frozenset[int]
    counts: StationCounts


def _require_station_filters(query: StationQuery) -> None:
    """Refuse an area, a range of years or coverage filters that cannot apply."""
    if query.area is not None:
        require_wgs84_area(query.area)
    if query.years is not None and query.years[0] > query.years[1]:
        raise IndexQueryError(
            message("index.invalid_years", start=query.years[0], end=query.years[1])
        )
    if (query.coverage or query.min_complete_years) and query.dataset is None:
        raise IndexQueryError(message("index.coverage_without_dataset"))


def _select_stations(
    connection: sqlite3.Connection,
    stores: Mapping[int, str],
    query: StationQuery,
    box: BBox | None,
) -> _Stations:
    """Split a station query's result by location group (SPEC 4.3 point 3).

    The attribute filters are SQL. The area places the located stations it
    may hold (R*Tree candidates) with shapely; the coverage filters label the
    stations the other filters leave, before any page is cut. The stations
    without a location are never placed by a box or an area.
    """
    where = _station_where(query, stores)
    located = where.copy()
    located.add("s.location = 'point'")
    if box is not None:
        _station_box(located, box)
    unlocated = where.copy()
    unlocated.add("s.location = 'none'")
    boundary: set[int] = set()
    located_ids: list[int] | None = None
    if query.area is not None:
        places = _area_places(connection, located, query.area)
        boundary = {key for key, place in places.items() if place == "boundary"}
        located_ids = [
            key
            for key, place in places.items()
            if place == "inside" or (place == "boundary" and query.boundary)
        ]
    hidden = 0
    unlocated_ids: list[int] | None = None
    filtered = bool(query.coverage or query.min_complete_years)
    if filtered:
        if located_ids is None:
            located_ids = _station_ids(connection, located)
        unlocated_ids = _station_ids(connection, unlocated)
        shown = {*located_ids, *unlocated_ids}
        passing = _covered(connection, stores, shown | boundary, query)
        hidden = len(shown - passing)
        located_ids = [key for key in located_ids if key in passing]
        unlocated_ids = [key for key in unlocated_ids if key in passing]
        boundary &= passing
    if located_ids is not None:
        located = _with_ids(located, located_ids)
    if unlocated_ids is not None:
        unlocated = _with_ids(unlocated, unlocated_ids)
    every = (
        _with_ids(where, [*(located_ids or ()), *(unlocated_ids or ())])
        if filtered
        else where
    )
    counts = StationCounts(
        located=(
            _count_stations(connection, located)
            if located_ids is None
            else len(located_ids)
        ),
        unlocated=(
            _count_stations(connection, unlocated)
            if unlocated_ids is None
            else len(unlocated_ids)
        ),
        boundary=len(boundary),
        hidden=hidden,
    )
    return _Stations(located, unlocated, every, frozenset(boundary), counts)


def _area_places(
    connection: sqlite3.Connection, located: _Where, area: GeoJSONGeometry
) -> dict[int, AreaPlace]:
    """Place the located stations near an area: inside it or on its boundary.

    The R*Tree candidates lie in the area's bounds widened by the largest
    location uncertainty among the stations, so a station outside the area
    but closer to it than its uncertainty is among them. Stations outside are
    left out.
    """
    bounds = require_wgs84_area(area)
    widest = connection.execute(
        f"SELECT max(s.location_uncertainty_m) FROM stations s WHERE {located.sql()}",
        located.params,
    ).fetchone()[0]
    candidates = located.copy()
    _station_box(candidates, widen_bounds(bounds, float(widest or 0.0)))
    rows = connection.execute(
        "SELECT s.id, s.lon, s.lat, s.location_uncertainty_m FROM stations s"
        f" WHERE {candidates.sql()}",
        candidates.params,
    ).fetchall()
    places = area_places(
        area,
        [(row[1], row[2]) for row in rows],
        [row[3] for row in rows],
    )
    return {
        row[0]: place
        for row, place in zip(rows, places, strict=True)
        if place != "outside"
    }


def _station_ids(connection: sqlite3.Connection, where: _Where) -> list[int]:
    return [
        int(row[0])
        for row in connection.execute(
            f"SELECT s.id FROM stations s WHERE {where.sql()}", where.params
        )
    ]


def _with_ids(where: _Where, ids: Iterable[int]) -> _Where:
    """Return ``where`` narrowed to the stations of ``ids``."""
    narrowed = where.copy()
    narrowed.add(f"s.id IN ({_IDS})", json.dumps(sorted(ids)))
    return narrowed


def _covered(
    connection: sqlite3.Connection,
    stores: Mapping[int, str],
    ids: Collection[int],
    query: StationQuery,
) -> set[int]:
    """Return the stations of ``ids`` whose labels pass the coverage filters.

    Only the variables the filters name are labelled, in the query's dataset,
    range and year type. A variable passes a filter when each of its entries
    (its half-year periods) does; a station without the variable never does.
    """
    if not ids:
        return set()
    names = sorted(
        {name for name, _ in query.coverage}
        | {name for name, _ in query.min_complete_years}
    )
    keys = {
        (stores[row[1]], row[2], row[3]): int(row[0])
        for row in connection.execute(
            f"SELECT id, store_id, provider, code FROM stations WHERE id IN ({_IDS})",
            (json.dumps(sorted(ids)),),
        )
    }
    where = _Where()
    where.add("s.dataset = ?", query.dataset)
    where.add(_SERIES_OF_STATIONS, json.dumps(sorted(ids)))
    where.add(
        f"(s.variable IN ({_IDS}) OR s.variable_key IN ({_IDS}))",
        json.dumps(names),
        json.dumps(names),
    )
    states: dict[str, set[str]] = {}
    for name, state in query.coverage:
        states.setdefault(name, set()).add(state)
    minimum: dict[str, int] = {}
    for name, years in query.min_complete_years:
        minimum[name] = max(years, minimum.get(name, 0))
    passing: set[int] = set()
    for found in _series_coverage(
        connection,
        stores,
        where,
        year_type=query.year_type,
        year_types=query.year_types,
        years=query.years,
    ):
        entries = {
            name: [
                item for item in found.variables if name in (item.key, item.variable)
            ]
            for name in names
        }
        if all(
            entries[name] and all(item.label.state in allowed for item in entries[name])
            for name, allowed in states.items()
        ) and all(
            entries[name]
            and all(item.label.complete_years >= least for item in entries[name])
            for name, least in minimum.items()
        ):
            passing.add(keys[(found.store, found.provider, found.code)])
    return passing


def _stations_coverage(
    connection: sqlite3.Connection,
    stores: Mapping[int, str],
    rows: Sequence[sqlite3.Row],
    query: StationQuery,
) -> tuple[StationCoverage, ...]:
    """Label the series of the stations of ``rows`` as the query asks."""
    if not rows:
        return ()
    where = _Where()
    where.add(_SERIES_OF_STATIONS, json.dumps([row["id"] for row in rows]))
    if query.dataset is not None:
        where.add("s.dataset = ?", query.dataset)
    return _series_coverage(
        connection,
        stores,
        where,
        year_type=query.year_type,
        year_types=query.year_types,
        years=query.years,
    )


def _series_coverage(
    connection: sqlite3.Connection,
    stores: Mapping[int, str],
    where: _Where,
    *,
    year_type: YearType | None,
    year_types: YearTypes,
    years: YearRange | None,
) -> tuple[StationCoverage, ...]:
    """Read the coverage of the series ``where`` selects on ``s`` (station_series).

    Each dataset's year type (the one asked, else the one ``year_types``
    remembers for its family) and range R are known before its years are
    read, so only the years of R in that numbering are read.
    """
    rows = connection.execute(
        f"SELECT {_SERIES_COLUMNS} FROM {_SERIES_SOURCE} WHERE {where.sql()}"
        " ORDER BY s.store_id, s.provider, s.code, s.dataset, s.id",
        where.params,
    ).fetchall()
    groups: dict[tuple[int, str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["store_id"], row["provider"], row["code"], row["dataset"])
        groups.setdefault(key, []).append(row)
    plans: dict[tuple[int, str, str, str], _LabelPlan] = {}
    wanted: dict[YearType, tuple[list[int], YearRange]] = {}
    for key, group in groups.items():
        first = group[0]
        unit = first["time_unit"]
        numbering = label_year_type(first["kind"], unit, year_type, year_types)
        periods = _date_ranges(first["version_periods"])
        span = years or default_span(
            first["first_year"], periods, time_unit=unit, year_type=numbering
        )
        plans[key] = _LabelPlan(numbering, periods, span)
        if span is None:
            continue
        ids, (low, high) = wanted.get(numbering, ([], span))
        ids.extend(row["id"] for row in group)
        wanted[numbering] = (ids, (min(low, span[0]), max(high, span[1])))
    found: dict[int, list[SeriesYear]] = {}
    # A page of stations reads tens of thousands of years: plain tuples, read
    # by position, cost a fraction of named rows.
    cursor = connection.cursor()
    cursor.row_factory = None
    for numbering, (ids, (low, high)) in wanted.items():
        rows_of_years = cursor.execute(
            "SELECT series_id, year, units, known, with_value"
            f" FROM series_years WHERE series_id IN ({_IDS}) AND year_type = ?"
            " AND year BETWEEN ? AND ?"
            " ORDER BY series_id, year",
            (json.dumps(ids), numbering, low, high),
        )
        for series_id, series in groupby(rows_of_years, key=itemgetter(0)):
            found[series_id] = [
                SeriesYear(numbering, year, units, known, with_value)
                for _, year, units, known, with_value in series
            ]
    return tuple(
        _station_coverage(group, found, stores, plans[key])
        for key, group in groups.items()
    )


@dataclass(frozen=True, slots=True)
class _LabelPlan:
    """How a dataset's labels count: the year type, known periods and range R."""

    numbering: YearType
    periods: tuple[DateRange, ...]
    span: YearRange | None


def _station_coverage(
    rows: Sequence[sqlite3.Row],
    found: Mapping[int, Sequence[SeriesYear]],
    stores: Mapping[int, str],
    plan: _LabelPlan,
) -> StationCoverage:
    """Label a station's variables in one dataset, in one range R."""
    first = rows[0]
    unit = first["time_unit"]
    numbering, periods, span = plan.numbering, plan.periods, plan.span
    variables: list[CoverageVariable] = []
    for row in rows:
        coverage = VariableCoverage(
            key=row["variable_key"],
            variable=row["variable"],
            unit=row["unit"],
            period=row["period"],
            first=_date(row["first_date"]),
            last=_date(row["last_date"]),
            with_value=row["with_value"],
            accumulated=row["accumulated"],
            gaps=_date_ranges(row["gaps"]),
        )
        own = row["periods"]
        known = periods if own is None else _date_ranges(own)
        rows_of_years = found.get(row["id"], ())
        label = series_label(
            coverage,
            rows_of_years,
            known=known,
            time_unit=unit,
            year_type=numbering,
            span=span,
        )
        variables.append(
            CoverageVariable(
                key=coverage.key,
                variable=coverage.variable,
                unit=coverage.unit,
                period=coverage.period,
                first=coverage.first,
                last=coverage.last,
                accumulated=coverage.accumulated,
                years=_years_in(rows_of_years, span),
                label=label,
                known=known,
            )
        )
    if first["kind"] == "hydro":
        variables = _only_with_value(variables)
    return StationCoverage(
        store=stores[first["store_id"]],
        provider=first["provider"],
        code=first["code"],
        dataset=first["dataset"],
        kind=first["kind"],
        time_unit=unit,
        year_type=numbering,
        span=span,
        file=first["file"],
        series=first["series"],
        series_version=first["version_path"],
        variables=tuple(variables),
        sha256=first["sha256"],
        license=first["license"],
        attribution=first["attribution"],
    )


def _years_in(
    years: Sequence[SeriesYear], span: YearRange | None
) -> tuple[SeriesYear, ...]:
    """Return the years of a series within R.

    ``years`` are one year type's, in order, read for the widest R of their
    query: a series whose R is that one keeps them all without a test.
    """
    if span is None or not years:
        return ()
    if span[0] <= years[0].year and years[-1].year <= span[1]:
        return tuple(years)
    return tuple(year for year in years if span[0] <= year.year <= span[1])


def _only_with_value(variables: Sequence[CoverageVariable]) -> list[CoverageVariable]:
    """Name the variables with a value beside each one without ("tylko H")."""
    valued = tuple(
        dict.fromkeys(
            item.variable for item in variables if item.label.state in VALUED_STATES
        )
    )
    return [
        replace(
            item,
            label=replace(
                item.label,
                only=tuple(name for name in valued if name != item.variable),
            ),
        )
        if item.label.state == "no_data"
        else item
        for item in variables
    ]


def _date_ranges(value: str) -> tuple[DateRange, ...]:
    """Ranges of days written as JSON by the writer (``[["2001-01-01", ...]]``)."""
    return tuple(
        (date.fromisoformat(start), date.fromisoformat(end))
        for start, end in json.loads(value)
    )


def _segment_columns() -> str:
    return (
        "g.segment AS segment, g.name AS segment_name, g.producer AS producer,"
        " g.product AS segment_product, g.country AS segment_country,"
        " g.dataset_key AS segment_dataset_key, g.known AS segment_known"
    )


def _segment(row: sqlite3.Row) -> SegmentRef:
    return SegmentRef(
        segment=row["segment"] or None,
        name=row["segment_name"],
        producer=row["producer"],
        product=row["segment_product"],
        country=row["segment_country"],
        dataset_key=row["segment_dataset_key"],
        known=bool(row["segment_known"]),
    )


def _location(kind: str | None, reason: str | None, source: str | None) -> LocationRef:
    if kind == "footprint":
        return LocationRef("footprint", None, source)
    if kind == "country":
        return LocationRef("country", None, source)
    return LocationRef("none", reason or "pending", None)


def _summary(
    row: sqlite3.Row, pins: Mapping[tuple[int, str], tuple[PinRef, ...]]
) -> VersionSummary:
    full_sheet = row["full_sheet"]
    return VersionSummary(
        path=row["version_path"],
        label=row["label"],
        label_source=row["label_source"],
        data_year=row["data_year"],
        data_date=_date(row["data_date"]),
        downloaded_at=_datetime(row["downloaded_at"]),
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        full_sheet=None if full_sheet is None else bool(full_sheet),
        horizontal_crs=row["horizontal_crs"],
        vertical_crs=row["vertical_crs"],
        is_current=bool(row["is_current"]),
        is_full_sheet=bool(row["is_full_sheet"]),
        state=row["version_state"],
        missing_since=_datetime(row["missing_since"]),
        location=_location(
            row["location"], row["location_reason"], row["location_source"]
        ),
        pinned_by=pins.get((row["store_id"], row["version_path"]), ()),
    )


def _slot_row(
    row: sqlite3.Row,
    stores: Mapping[int, str],
    pins: Mapping[tuple[int, str], tuple[PinRef, ...]],
) -> SlotRow:
    version = None if row["version_id"] is None else _summary(row, pins)
    location = (
        LocationRef("none", "no_current") if version is None else version.location
    )
    return SlotRow(
        store=stores[row["store_id"]],
        slot=row["slot_path"],
        name=row["slot_name"],
        segment=_segment(row),
        unit=row["slot_unit"],
        product=row["slot_product"],
        country=row["slot_country"],
        status=row["row_status"],
        location=location,
        version=version,
        versions_count=int(row["versions_count"]),
    )


def _project_ref(
    row: sqlite3.Row, manifests: tuple[ProjectManifestRef, ...]
) -> ProjectRef:
    return ProjectRef(
        key=row["key"],
        name=row["name"],
        path=row["path"],
        access_key=row["access_key"],
        manifests=manifests,
        tasks=int(row["tasks"]),
        pins=int(row["pins"]),
        missing_pins=int(row["missing_pins"]),
    )


def _manifests(
    connection: sqlite3.Connection, projects: Sequence[int]
) -> dict[int, tuple[ProjectManifestRef, ...]]:
    """Return the manifests of the projects by project row id, producer by producer."""
    if not projects:
        return {}
    rows = connection.execute(
        f"{_MANIFEST_SELECT} WHERE m.project_id IN ({_IDS})",
        (json.dumps(list(projects)),),
    ).fetchall()
    found: dict[int, list[ProjectManifestRef]] = {}
    for row in sorted(rows, key=_by_producer):
        found.setdefault(int(row["project_id"]), []).append(
            ProjectManifestRef(
                producer=row["producer"],
                store=row["store"],
                store_dir=row["store_dir"],
                status=row["status"],
                problem=row["problem"],
                scanned_at=datetime.fromisoformat(row["scanned_at"]),
            )
        )
    return {project: tuple(items) for project, items in found.items()}


def _by_producer(row: sqlite3.Row) -> tuple[int, str]:
    """Order of a row of a project's manifest: ``PROJECT_MANIFESTS``, then name.

    Python sorts stably, so the rows of one manifest keep their own order.
    """
    producer = str(row["producer"])
    order = list(PROJECT_MANIFESTS)
    return (order.index(producer) if producer in order else len(order), producer)


def _visible(visible: ProjectVisibility) -> tuple[str, tuple[object, ...]]:
    """Condition on ``pr`` (projects) admitting exactly what ``visible`` sees.

    Only projects with an access entry are named (``granted``, ``denied``);
    the others follow ``unlisted``, so the condition stays short however
    many projects the index holds.
    """
    if visible.everything:
        return "1", ()
    granted = json.dumps(sorted(visible.granted))
    if not visible.unlisted:
        return f"pr.access_key IN ({_IDS})", (granted,)
    denied = json.dumps(sorted(visible.denied))
    return (
        f"(pr.access_key IN ({_IDS}) OR pr.access_key NOT IN ({_IDS}))",
        (granted, denied),
    )


def _pins(
    connection: sqlite3.Connection,
    versions: Iterable[tuple[int, str]],
    visible: ProjectVisibility,
) -> dict[tuple[int, str], tuple[PinRef, ...]]:
    """Pins of the given ``(store row id, version path)`` by visible projects."""
    wanted = set(versions)
    if not wanted:
        return {}
    seen, params = _visible(visible)
    rows = connection.execute(
        "SELECT p.store_id, p.version_path, p.task_id, p.sha256, pr.name, pr.key,"
        " p.producer, v.sha256 AS version_sha256, v.state AS version_state"
        " FROM pins p"
        " JOIN projects pr ON pr.id = p.project_id"
        " LEFT JOIN versions v ON v.store_id = p.store_id AND v.path = p.version_path"
        f" WHERE p.version_path IN ({_IDS}) AND {seen}"
        " ORDER BY pr.key, p.producer, p.task_id",
        (json.dumps(sorted({path for _, path in wanted})), *params),
    ).fetchall()
    found: dict[tuple[int, str], list[PinRef]] = {}
    for row in rows:
        key = (row[0], row[1])
        if key not in wanted:
            continue
        state: PinState = "ok"
        if row["version_state"] != "present":
            state = "missing"
        elif row[3] and row["version_sha256"] and row[3] != row["version_sha256"]:
            state = "sha256_mismatch"
        found.setdefault(key, []).append(
            PinRef(
                project=row[4],
                project_key=row[5],
                producer=row[6],
                task=row[2],
                version=row[1],
                sha256=row[3],
                state=state,
            )
        )
    return {key: tuple(items) for key, items in found.items()}


def _issues(
    connection: sqlite3.Connection, condition: str, params: tuple[object, ...]
) -> tuple[IssueRef, ...]:
    rows = connection.execute(
        "SELECT i.code, i.path, g.segment, g.producer, s.path AS slot, i.origin,"
        " i.first_seen_at"
        " FROM issues i JOIN segments g ON g.id = i.segment_id"
        " LEFT JOIN slots s ON s.id = i.slot_id"
        f" WHERE {condition} ORDER BY g.segment, i.path, i.code",
        params,
    ).fetchall()
    return tuple(
        IssueRef(
            code=row["code"],
            path=row["path"],
            segment=row["segment"] or None,
            producer=row["producer"],
            slot=row["slot"],
            origin=row["origin"],
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        )
        for row in rows
    )


def _job(
    connection: sqlite3.Connection, condition: str, store: str, *, order: str
) -> JobRef | None:
    row = connection.execute(
        "SELECT id, kind, state, actor, created_at, started_at, finished_at"
        f" FROM jobs WHERE {condition} ORDER BY {order} LIMIT 1",
        (store,),
    ).fetchone()
    if row is None:
        return None
    progress = None
    event = connection.execute(
        "SELECT data FROM job_events WHERE job_id = ? AND type = 'progress'"
        " ORDER BY seq DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    if event is not None:
        data = json.loads(event["data"])
        current, total = data.get("current"), data.get("total")
        if isinstance(current, int) and isinstance(total, int):
            progress = (current, total)
    return JobRef(
        id=row["id"],
        kind=row["kind"],
        state=row["state"],
        actor=row["actor"],
        created_at=datetime.fromisoformat(row["created_at"]),
        started_at=_datetime(row["started_at"]),
        finished_at=_datetime(row["finished_at"]),
        progress=progress,
    )


def _outline(row: sqlite3.Row) -> GeoJSONGeometry:
    if row["wgs84"] is not None and not row["is_box"]:
        geometry: GeoJSONGeometry = json.loads(row["wgs84"])
        return geometry
    return box_geometry(
        (row["min_lon"], row["min_lat"], row["max_lon"], row["max_lat"])
    )


def _product_version(row: sqlite3.Row, *, shapes: bool) -> ProductVersion:
    located = row["location"] == "footprint" and row["min_lon"] is not None
    bounds = (
        (row["min_lon"], row["min_lat"], row["max_lon"], row["max_lat"])
        if located
        else None
    )
    outline = _outline(row) if shapes and located else None
    native = json.loads(row["native"]) if shapes and row["native"] is not None else None
    return ProductVersion(
        path=row["path"],
        slot=row["slot"],
        unit=row["unit"],
        segment=row["segment"] or None,
        segment_name=row["segment_name"],
        producer=row["producer"],
        data_year=row["data_year"],
        data_date=_date(row["data_date"]),
        downloaded_at=_datetime(row["downloaded_at"]),
        edition=row["edition"],
        label=row["label"],
        campaign=row["campaign"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        product=row["product"],
        dataset_key=row["dataset_key"],
        horizontal_crs=row["horizontal_crs"],
        vertical_crs=row["vertical_crs"],
        resolution=row["resolution"],
        nodata=row["nodata"],
        location_source=row["location_source"],
        native_crs=row["native_crs"],
        bounds=bounds,
        outline=outline,
        native=native,
    )


def _coverage(
    area: GeoJSONGeometry,
    shapes: list[CoverageShape],
    country: str | None,
    transformer: TransformerFactory,
) -> LocalCoverage:
    crs = planar_crs(country)
    if crs is None:
        return LocalCoverage(
            country=country,
            crs=None,
            ratio=None,
            area_km2=None,
            covered_km2=None,
            versions_count=len(shapes),
            reason="no_planar_crs",
        )
    measure = measure_coverage(area, shapes, crs=crs, transformer=transformer)
    if measure.area_km2 <= 0:
        return LocalCoverage(
            country=country,
            crs=crs,
            ratio=None,
            area_km2=measure.area_km2,
            covered_km2=None,
            versions_count=measure.footprints,
            reason="empty_area",
        )
    return LocalCoverage(
        country=country,
        crs=crs,
        ratio=min(1.0, measure.covered_km2 / measure.area_km2),
        area_km2=measure.area_km2,
        covered_km2=measure.covered_km2,
        versions_count=measure.footprints,
    )


def _datetime(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _date(value: object) -> date | None:
    return None if value is None else date.fromisoformat(str(value))


def _utc_text(value: datetime) -> str:
    """Return a time as the index writes its times: UTC ISO 8601, in seconds.

    Such texts sort in time order; a naive time counts as UTC.
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="seconds")


def _own_in_area(wgs84: str | None, area: AreaFilter) -> bool:
    """Whether an own file belongs to an area as the catalog's rows do.

    Its outline shares interior with the area (an edge alone is not enough);
    a file without an outline always does.
    """
    if wgs84 is None:
        return True
    region = shapely.make_valid(shape(area.geometry))
    outline = shape(json.loads(wgs84))
    return bool(region.intersects(outline) and not region.touches(outline))


# Own data of projects (decision 8).

_OWN_FOLDER_COLUMNS = (
    "o.id, pr.key AS project, o.path, o.source, o.state, o.reason, o.scanned_at,"
    " o.files, o.size_bytes, o.snapshots, o.snapshots_bytes"
)
_OWN_FILE_COLUMNS = (
    "f.id, f.file_id, f.path, f.kind, f.driver, f.size_bytes, f.modified_ns,"
    " f.read_state, f.missing_since, f.change, f.last_snapshot, f.wgs84,"
    " f.location_reason, (SELECT s.created_at FROM snapshots s"
    " WHERE s.folder_id = f.folder_id AND s.path = f.path"
    " AND s.label = f.last_snapshot) AS last_snapshot_at,"
    " (SELECT count(*) FROM snapshots s WHERE s.folder_id = f.folder_id"
    " AND s.path = f.path) AS snapshots"
)


def _own_folder_row(
    connection: sqlite3.Connection, project: str, visible: ProjectVisibility
) -> sqlite3.Row | None:
    """Find the folder of a project the principal sees, by its access key."""
    condition, params = _visible(visible)
    row: sqlite3.Row | None = connection.execute(
        f"SELECT {_OWN_FOLDER_COLUMNS} FROM own_folders o"
        " JOIN projects pr ON pr.access_key = o.project"
        f" WHERE pr.key = ? AND {condition}",
        (project, *params),
    ).fetchone()
    return row


def _own_folder(connection: sqlite3.Connection, row: sqlite3.Row) -> OwnFolderRecord:
    problems = connection.execute(
        "SELECT code, path, reason, first_seen_at FROM own_problems"
        " WHERE folder_id = ? ORDER BY path, code",
        (row["id"],),
    ).fetchall()
    return OwnFolderRecord(
        project=row["project"],
        path=row["path"],
        source=row["source"],
        state=row["state"],
        reason=row["reason"],
        scanned_at=datetime.fromisoformat(row["scanned_at"]),
        files=row["files"],
        size_bytes=row["size_bytes"],
        snapshots=row["snapshots"],
        snapshots_bytes=row["snapshots_bytes"],
        problems=tuple(
            OwnProblem(
                code=problem["code"],
                path=problem["path"] or None,
                reason=problem["reason"],
                first_seen_at=datetime.fromisoformat(problem["first_seen_at"]),
            )
            for problem in problems
        ),
    )


def _own_file_row(row: sqlite3.Row) -> OwnFileRow:
    missing = row["missing_since"] is not None
    if row["wgs84"] is not None:
        location = LocationRef("footprint")
    else:
        location = LocationRef("none", row["location_reason"])
    last = row["last_snapshot"]
    return OwnFileRow(
        file_id=row["file_id"],
        path=row["path"],
        kind=row["kind"],
        driver=row["driver"],
        size_bytes=row["size_bytes"],
        modified_at=_from_ns(row["modified_ns"]),
        state="missing" if missing else row["read_state"],
        change=row["change"],
        last_snapshot=None
        if last is None or row["last_snapshot_at"] is None
        else OwnSnapshotRef(last, datetime.fromisoformat(row["last_snapshot_at"])),
        snapshots=row["snapshots"],
        location=location,
        outline=None if row["wgs84"] is None else json.loads(row["wgs84"]),
    )


def _own_state(state: str) -> tuple[str, tuple[object, ...]]:
    """Return the SQL condition on ``f`` (own_files) of a state or change filter."""
    if state == "missing":
        return "f.missing_since IS NOT NULL", ()
    if state in OWN_FILE_STATES:
        return "f.missing_since IS NULL AND f.read_state = ?", (state,)
    if state in OWN_CHANGES:
        return "f.missing_since IS NULL AND f.change = ?", (state,)
    allowed = ", ".join((*OWN_FILE_STATES, *OWN_CHANGES))
    raise IndexQueryError(
        message("index.invalid_own_state", state=state, allowed=allowed)
    )


def _encode_own_cursor(fingerprint: str, path: str) -> str:
    data = json.dumps([_CURSOR_VERSION, fingerprint, path], ensure_ascii=False)
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def _decode_own_cursor(cursor: str | None, fingerprint: str) -> str | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise IndexQueryError(message("index.invalid_cursor")) from None
    if (
        not isinstance(data, list)
        or len(data) != 3
        or data[:2] != [_CURSOR_VERSION, fingerprint]
        or not isinstance(data[2], str)
    ):
        raise IndexQueryError(message("index.invalid_cursor"))
    return data[2]


def _layer(data: dict[str, Any]) -> LayerInfo:
    return LayerInfo(
        name=data["name"],
        geometry_type=data["geometry_type"],
        feature_count=data["feature_count"],
        fields=tuple(FieldInfo(**field) for field in data["fields"]),
        crs=data["crs"],
        bbox=_own_bbox(data["bbox"]),
    )


def _raster(text: str | None) -> RasterInfo | None:
    if text is None:
        return None
    data = json.loads(text)
    pixel = data["pixel_size"]
    return RasterInfo(
        width=data["width"],
        height=data["height"],
        bands=data["bands"],
        dtype=data["dtype"],
        nodata=data["nodata"],
        pixel_size=None if pixel is None else (pixel[0], pixel[1]),
        georeferenced=data["georeferenced"],
    )


def _own_bbox(value: str | list[float] | None) -> BBox | None:
    if value is None:
        return None
    values = json.loads(value) if isinstance(value, str) else value
    return (values[0], values[1], values[2], values[3])


def _from_ns(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1e9, UTC)


def _snapshot(row: sqlite3.Row) -> SnapshotRecord:
    return SnapshotRecord(
        path=row["path"],
        label=row["label"],
        state=row["state"],
        created_at=_datetime(row["created_at"]),
        content_method=row["content_method"],
        content_sha256=row["content_sha256"],
        size_bytes=row["size_bytes"],
        document=None if row["document"] is None else json.loads(row["document"]),
    )
