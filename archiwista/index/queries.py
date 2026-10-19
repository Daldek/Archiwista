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
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import shapely
from shapely.geometry import shape

from archiwista.auth import ProjectVisibility
from archiwista.errors import IndexQueryError
from archiwista.index.coverage import CoverageShape, measure_coverage, planar_crs
from archiwista.index.geometry import (
    box_geometry,
    is_box,
    require_wgs84_area,
    require_wgs84_bbox,
)
from archiwista.index.schema import SCHEMA_VERSION, connect, initialize
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
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
    ProjectTaskRef,
    RowStatus,
    SegmentRef,
    SegmentSummary,
    SlotDetail,
    SlotPage,
    SlotQuery,
    SlotRow,
    SlotUnit,
    SnapshotRecord,
    StoreFreshness,
    StoreIndexState,
    StoreUsage,
    TransformerFactory,
    UnusedVersions,
    VersionDetail,
    VersionsMode,
    VersionSummary,
)
from archiwista.messages import MESSAGES
from archiwista.owndata.document import SNAPSHOTS_DIR
from archiwista.owndata.reader import FieldInfo, LayerInfo, RasterInfo
from archiwista.sources import GeoJSONGeometry, SourceEntry

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
SELECT pr.id, pr.key, pr.name, pr.producer, pr.path, pr.access_key,
    st.key AS store, pr.store_dir, pr.status, pr.problem, pr.scanned_at,
    (SELECT count(*) FROM project_tasks t WHERE t.project_id = pr.id) AS tasks,
    (SELECT count(*) FROM pins p WHERE p.project_id = pr.id) AS pins,
    (SELECT count(*) FROM {_PIN_SOURCE}
        WHERE p.project_id = pr.id AND {_PIN_STATE} IN ('missing', 'sha256_mismatch')
    ) AS missing_pins
FROM projects pr LEFT JOIN stores st ON st.id = pr.store_id
"""
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
        FootprintPage
            ``items`` when at most ``query.limit`` footprints are in the
            view, otherwise ``cells`` counting footprint centres.

        Raises
        ------
        IndexQueryError
            An invalid view, limit or grid.
        """
        min_lon, min_lat, max_lon, max_lat = require_wgs84_bbox(query.bbox)
        _require_limit(query.limit, MAP_FOOTPRINT_LIMIT)
        if not 1 <= query.grid_columns <= MAX_GRID_COLUMNS:
            raise IndexQueryError(
                MESSAGES["index_invalid_grid"].format(limit=MAX_GRID_COLUMNS)
            )
        filters = _filters(query)
        columns = query.grid_columns
        cell_width = (max_lon - min_lon) / columns
        middle = math.radians((min_lat + max_lat) / 2)
        rows_count = min(
            MAX_GRID_COLUMNS,
            max(1, math.ceil((max_lat - min_lat) / (cell_width * math.cos(middle)))),
        )
        cell_height = (max_lat - min_lat) / rows_count
        with self._read() as connection:
            stores = _stores(connection)
            where = _where(connection, filters, stores, visible)
            groups = _groups(connection, filters.versions, where)
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
                    columns - 1,
                    min_lon,
                    cell_width,
                    rows_count - 1,
                    min_lat,
                    cell_height,
                    *view.params,
                ],
            ).fetchall()
            total = sum(int(cell["n"]) for cell in cells)
            if total > query.limit:
                grid = tuple(
                    GridCell(
                        min_lon=min_lon + cell["col"] * cell_width,
                        min_lat=min_lat + cell["row"] * cell_height,
                        max_lon=min_lon + (cell["col"] + 1) * cell_width,
                        max_lat=min_lat + (cell["row"] + 1) * cell_height,
                        count=int(cell["n"]),
                    )
                    for cell in sorted(cells, key=lambda c: (c["row"], c["col"]))
                )
                return FootprintPage(total, True, (), grid, groups)
            rows = connection.execute(
                "SELECT s.store_id, s.path, v.path, g.segment, s.product, v.label,"
                " v.data_year, v.location_source, v.is_box, v.min_lon, v.min_lat,"
                f" v.max_lon, v.max_lat, sh.wgs84 FROM {_MAP_SOURCE}"
                " LEFT JOIN version_shapes sh ON sh.version_id = v.id AND v.is_box = 0"
                f" WHERE {view.sql()} ORDER BY v.id",
                view.params,
            ).fetchall()
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
        return FootprintPage(total, False, items, (), groups)

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
                " s.current_path AS version FROM slots s"
                " JOIN segments g ON g.id = s.segment_id"
                " LEFT JOIN versions v ON v.id = s.current_version_id"
                " WHERE s.store_id = ? AND s.current_path IS NOT NULL"
                " AND (v.id IS NULL OR v.state = 'missing')"
                " UNION ALL"
                " SELECT s.path, g.segment, 'full_sheet', s.full_sheet_path"
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
            Only projects of this configured store.
        """
        where = _Where()
        if store is not None:
            where.add("st.key = ?", store)
        condition, params = _visible(visible)
        where.add(condition, *params)
        with self._read() as connection:
            rows = connection.execute(
                f"{_PROJECT_SELECT} WHERE {where.sql()} ORDER BY pr.name, pr.key",
                where.params,
            ).fetchall()
        return tuple(_project_ref(row) for row in rows)

    def project(self, key: str, *, visible: ProjectVisibility) -> ProjectRecord | None:
        """Return a project with its tasks and pins.

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
            tasks = connection.execute(
                "SELECT task_id, command, options, status FROM project_tasks"
                " WHERE project_id = ? ORDER BY position",
                (row["id"],),
            ).fetchall()
            pins = connection.execute(
                "SELECT p.task_id, p.version_path, p.sha256,"
                f" {_PIN_STATE} AS state, s.path AS slot, v.label, v.size_bytes,"
                " coalesce(v.id = s.current_version_id, 0) AS is_current"
                f" FROM {_PIN_SOURCE} LEFT JOIN slots s ON s.id = v.slot_id"
                " WHERE p.project_id = ? ORDER BY p.id",
                (row["id"],),
            ).fetchall()
        return ProjectRecord(
            project=_project_ref(row),
            tasks=tuple(
                ProjectTaskRef(
                    task_id=task["task_id"],
                    command=task["command"],
                    options=json.loads(task["options"]),
                    status=task["status"],
                )
                for task in tasks
            ),
            pins=tuple(
                ProjectPinRef(
                    task=pin["task_id"],
                    version=pin["version_path"],
                    sha256=pin["sha256"],
                    state=pin["state"],
                    slot=pin["slot"],
                    label=pin["label"],
                    size_bytes=pin["size_bytes"],
                    is_current=bool(pin["is_current"]),
                )
                for pin in pins
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
                "SELECT pr.name, pr.key, p.task_id, p.version_path, p.sha256,"
                f" {_PIN_STATE} AS state FROM {_PIN_SOURCE}"
                " JOIN projects pr ON pr.id = p.project_id"
                f" WHERE p.store_id = ? AND {_PIN_STATE} <> 'ok' AND {condition}"
                " ORDER BY pr.key, p.task_id, p.version_path",
                (_store_id(stores, store), *params),
            ).fetchall()
        return tuple(
            PinRef(
                project=row["name"],
                project_key=row["key"],
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
        wanted = set(shapes) | ({country for country in countries} & held)
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
                f"SELECT {_OWN_FILE_COLUMNS}, f.disk_path, f.members, f.read_error,"
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
        raise IndexQueryError(MESSAGES["index_invalid_limit"].format(limit=maximum))


def _filters(query: SlotQuery | MapQuery) -> _Filters:
    years = query.years
    if years is not None:
        start, end = years
        if start is not None and end is not None and start > end:
            raise IndexQueryError(
                MESSAGES["index_invalid_years"].format(start=start, end=end)
            )
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


def _decode_cursor(
    cursor: str | None, fingerprint: str, size: int
) -> list[object] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise IndexQueryError(MESSAGES["index_invalid_cursor"]) from None
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
        raise IndexQueryError(MESSAGES["index_invalid_cursor"])
    return list(data[2:])


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


def _project_ref(row: sqlite3.Row) -> ProjectRef:
    return ProjectRef(
        key=row["key"],
        name=row["name"],
        producer=row["producer"],
        path=row["path"],
        access_key=row["access_key"],
        store=row["store"],
        store_dir=row["store_dir"],
        status=row["status"],
        problem=row["problem"],
        scanned_at=datetime.fromisoformat(row["scanned_at"]),
        tasks=int(row["tasks"]),
        pins=int(row["pins"]),
        missing_pins=int(row["missing_pins"]),
    )


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
        " v.sha256 AS version_sha256, v.state AS version_state FROM pins p"
        " JOIN projects pr ON pr.id = p.project_id"
        " LEFT JOIN versions v ON v.store_id = p.store_id AND v.path = p.version_path"
        f" WHERE p.version_path IN ({_IDS}) AND {seen} ORDER BY pr.key, p.task_id",
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
        "SELECT i.code, i.path, g.segment, s.path AS slot, i.origin, i.first_seen_at"
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
        MESSAGES["index_invalid_own_state"].format(state=state, allowed=allowed)
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
        raise IndexQueryError(MESSAGES["index_invalid_cursor"]) from None
    if (
        not isinstance(data, list)
        or len(data) != 3
        or data[:2] != [_CURSOR_VERSION, fingerprint]
        or not isinstance(data[2], str)
    ):
        raise IndexQueryError(MESSAGES["index_invalid_cursor"])
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
