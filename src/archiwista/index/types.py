"""Typed inputs and results of the local index (queries, writer, coverage).

Public keys are the configured store id (``store``) and paths relative to
the store's producer directory (``slot``, ``path``) — never integer row ids
or absolute paths. Times are timezone-aware UTC ``datetime`` values.
"""

import hashlib
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from archiwista.config import (
    DEFAULT_YEAR_TYPES,
    OwnFolderReason,
    OwnFolderSource,
    YearTypes,
)
from archiwista.index.series import SeriesLabel, SeriesState, SeriesYear, YearRange
from archiwista.owndata.reader import LayerInfo, RasterInfo
from archiwista.sources import (
    PLAN_STATUSES,
    ActionPlan,
    AvailabilityReport,
    CoordinateTransformer,
    DateRange,
    GeoJSONGeometry,
    LocationKind,
    PlanStatus,
    SourceEntry,
    TimeUnit,
    YearType,
)

type VersionsMode = Literal[
    "current", "all", "full_sheet", "pinned", "noncurrent_unpinned"
]
type LocationFilter = Literal["any", "with", "none"]
type RowStatus = Literal["ok", "missing", "no_sidecar", "unreadable", "unrecognized"]
type StoreStatus = Literal["unknown", "available", "unavailable"]
type PinState = Literal["ok", "missing", "sha256_mismatch", "unknown"]
type VersionState = Literal["present", "missing"]
type IssueOrigin = Literal["scan", "check"]
type BBox = tuple[float, float, float, float]
# "Exactly this river" or "with its tributaries" (P19): a station's hydrographic
# code equal to the river's, or beginning with it.
type RiverScope = Literal["exact", "tributaries"]
type StationLocation = Literal["point", "none"]
# The kind of a meteo station in its catalog (a station type of the map, 6.7).
type MeteoKind = Literal["synoptic", "climate", "precipitation"]
# The order of a list of stations (SPEC 6.8): along rivers, or by name.
type StationSort = Literal["river", "name"]
type TransformerFactory = Callable[[str, str], CoordinateTransformer]
# A producer's current version of a slot, asked by the slot's key at the end of
# a pass: a path relative to the store, ``None`` without one
# (``CurrentVersionAdapter.current_version``).
type CurrentVersionLookup = Callable[[str], Path | None]
# Own data of projects (plan v0.2, decision 8).
type OwnFolderState = Literal["ok", "missing", "unreadable", "invalid"]
type OwnReadState = Literal["ok", "unrecognized", "unreadable"]
type OwnFileState = Literal["ok", "unrecognized", "unreadable", "missing"]
type OwnChange = Literal["unsnapshotted", "unchanged", "changed"]
type SnapshotState = Literal["ok", "invalid", "modified"]
type OwnProblemCode = Literal[
    "own_folder_unreadable",
    "own_folder_invalid",
    "own_folder_too_large",
    "own_file_unreadable",
    "invalid_snapshot",
    "unknown_snapshot_schema",
    "snapshot_modified",
    "stale_snapshot_incoming",
    "path_outside_root",
]

VERSIONS_MODES: tuple[VersionsMode, ...] = (
    "current",
    "all",
    "full_sheet",
    "pinned",
    "noncurrent_unpinned",
)
LOCATION_FILTERS: tuple[LocationFilter, ...] = ("any", "with", "none")
RIVER_SCOPES: tuple[RiverScope, ...] = ("exact", "tributaries")
METEO_KINDS: tuple[MeteoKind, ...] = ("synoptic", "climate", "precipitation")
STATION_SORTS: tuple[StationSort, ...] = ("river", "name")
ROW_STATUSES: tuple[RowStatus, ...] = (
    "ok",
    "missing",
    "no_sidecar",
    "unreadable",
    "unrecognized",
)
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200
MAP_FOOTPRINT_LIMIT = 5000
DEFAULT_GRID_COLUMNS = 64
MAX_GRID_COLUMNS = 512
OWN_FOLDER_STATES: tuple[OwnFolderState, ...] = (
    "ok",
    "missing",
    "unreadable",
    "invalid",
)
OWN_FILE_STATES: tuple[OwnFileState, ...] = (
    "ok",
    "unrecognized",
    "unreadable",
    "missing",
)
OWN_CHANGES: tuple[OwnChange, ...] = ("unsnapshotted", "unchanged", "changed")
OWN_PROBLEM_CODES: tuple[OwnProblemCode, ...] = (
    "own_folder_unreadable",
    "own_folder_invalid",
    "own_folder_too_large",
    "own_file_unreadable",
    "invalid_snapshot",
    "unknown_snapshot_schema",
    "snapshot_modified",
    "stale_snapshot_incoming",
    "path_outside_root",
)
# Files of a data folder in the index: of a larger folder the first ones in
# the order of their paths.
MAX_OWN_FILES = 10_000
# Observed states kept per file, newest first.
MAX_OWN_FILE_STATES = 200


@dataclass(frozen=True, slots=True)
class AreaFilter:
    """An area of interest for the catalog and local coverage.

    Parameters
    ----------
    geometry : GeoJSONGeometry
        ``Polygon`` or ``MultiPolygon`` in WGS84 (longitude, latitude).
    countries : tuple[str, ...]
        Countries the area lies in (``GeoAdapter.countries``); files of a
        whole country join the ``country`` group only for these.
    """

    geometry: GeoJSONGeometry
    countries: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SlotQuery:
    """Filters, area and page of a catalog query (``GET /slots``).

    Parameters
    ----------
    q : str or None
        Search text; every word must match. A word matches the unit (sheet,
        TERYT, KU), the file name, the segment and its product, or a label,
        survey work number, campaign or edition of any version of the slot
        (word prefix, diacritics ignored). A word of 8 to 64 hex digits also
        matches the beginning of a version's SHA-256.
    store, product, country : str or None
        Exact store id, product (e.g. ``"nmt"``) and country (``"PL"``).
    years : tuple[int | None, int | None] or None
        Inclusive range of the data year (never the download year); an open
        end is ``None``. Rows without a data year never match.
    unit : str or None
        Exact unit code (sheet, TERYT, KU) of the slot.
    location : {"any", "with", "none"}
        Location group: everything, rows with a footprint (in the area when
        one is given) or a whole country, or rows without location.
    versions : {"current", "all", "full_sheet", "pinned", "noncurrent_unpinned"}
        Which versions are rows: the current one of each slot (slots
        without a current version too), every version, versions held by a
        ``full_sheet`` link, versions pinned in projects, or versions held
        by no link and pinned by no project.
    status : {"ok", "missing", "no_sidecar", "unreadable", "unrecognized"} or None
        Row state.
    project : str or None
        Project key (``ProjectRef.key``): only rows of versions pinned in
        this project, on top of what ``versions`` picks (``current`` keeps
        the pinned current versions; ``pinned`` or ``all`` lists every
        pinned version, non-current ones too). A project the principal does
        not see, or an unknown one, matches nothing (the API answers 404
        first).
    area : AreaFilter or None
        Rows whose footprint shares interior with the area, files of the
        area's countries and rows without location (never dropped).
    limit : int
        Page size, 1 to ``MAX_PAGE_LIMIT``.
    cursor : str or None
        ``next_cursor`` of the previous page of the same query.
    """

    q: str | None = None
    store: str | None = None
    product: str | None = None
    country: str | None = None
    years: tuple[int | None, int | None] | None = None
    unit: str | None = None
    location: LocationFilter = "any"
    versions: VersionsMode = "current"
    status: RowStatus | None = None
    project: str | None = None
    area: AreaFilter | None = None
    limit: int = DEFAULT_PAGE_LIMIT
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class MapQuery:
    """Footprints in a map view (``GET /map/footprints``).

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)`` in WGS84; the
    other filters mean the same as in ``SlotQuery``. More than ``limit``
    footprints are aggregated into a grid of ``grid_columns`` columns.
    """

    bbox: BBox
    q: str | None = None
    store: str | None = None
    product: str | None = None
    country: str | None = None
    years: tuple[int | None, int | None] | None = None
    unit: str | None = None
    versions: VersionsMode = "current"
    status: RowStatus | None = None
    project: str | None = None
    limit: int = MAP_FOOTPRINT_LIMIT
    grid_columns: int = DEFAULT_GRID_COLUMNS


@dataclass(frozen=True, slots=True)
class WarmQuery:
    """What the ``preview_warm`` job prepares previews of (SPEC 5.7).

    The current versions of the stores, narrowed by every filter given; with
    ``project`` the current versions the project pins and the working files
    of its own data. ``AND`` of all of them.

    Parameters
    ----------
    store, product, segment : str or None
        Exact store id, product of the slots (e.g. ``"nmt"``) and segment.
    project : str or None
        Project key (``ProjectRef.key``).
    area : AreaFilter or None
        As the catalog's area: versions and files whose outline shares
        interior with it, files of its countries, and those without location.
    since : datetime or None
        Only versions indexed since then (a warm-up after a scan); a
        project's working files are not chosen by time.
    """

    store: str | None = None
    product: str | None = None
    segment: str | None = None
    project: str | None = None
    area: AreaFilter | None = None
    since: datetime | None = None


@dataclass(frozen=True, slots=True)
class WarmSelection:
    """The objects a warm-up of previews prepares, in the order it takes them.

    ``versions`` are ``(store, version path)`` of current versions, by store
    and slot path; ``own_files`` the paths in the project's data folder of its
    working files that were read (not missing), by path.
    """

    versions: tuple[tuple[str, str], ...]
    own_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SegmentRef:
    """A segment of a store with the producer's human-readable name.

    ``segment`` is ``None`` for a producer that does not split its store. For
    Kartograf it is a directory of the store (``<product>/<variant>``), which a
    scan can take alone; for IMGWTools it is the key of a dataset
    (``pl.imgw.hydro_daily``), a label the entries carry: that producer reads
    only its whole directory.
    """

    segment: str | None
    name: str
    producer: str
    product: str | None
    country: str | None
    dataset_key: str | None
    known: bool


@dataclass(frozen=True, slots=True)
class LocationRef:
    """Where a version is (A-ADR-022).

    ``kind`` is ``footprint``, ``country`` or ``none``. ``reason`` explains
    ``none``: ``no_source`` (no source of an outline), ``unreadable`` (no
    readable sidecar), ``pending`` (not computed yet) or ``no_current``
    (a slot row without a current version). ``source`` names the origin of
    a footprint (``request``, ``sheet``, ``header``, ``unit``).
    """

    kind: LocationKind
    reason: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class PinRef:
    """A project task pinning a version (``Przypięta w: Raba (teren)``).

    ``state`` is ``missing`` when the version is not in the index or no
    longer on disk, ``sha256_mismatch`` when the index holds other content.
    ``producer`` is the producer of the project's manifest.
    """

    project: str
    project_key: str
    producer: str
    task: str | None
    version: str
    sha256: str | None
    state: PinState


@dataclass(frozen=True, slots=True)
class VersionSummary:
    """A version as listed in the catalog and on the file card."""

    path: str
    label: str | None
    label_source: str | None
    data_year: int | None
    data_date: date | None
    downloaded_at: datetime | None
    sha256: str | None
    size_bytes: int | None
    full_sheet: bool | None
    horizontal_crs: str | None
    vertical_crs: str | None
    is_current: bool
    is_full_sheet: bool
    state: VersionState
    missing_since: datetime | None
    location: LocationRef
    pinned_by: tuple[PinRef, ...] = ()


@dataclass(frozen=True, slots=True)
class SlotRow:
    """One catalog row: a slot with the version the query selected.

    ``version`` is ``None`` for a slot without a current version in the
    ``current`` mode (e.g. a standard file without a sidecar).
    """

    store: str
    slot: str
    name: str
    segment: SegmentRef
    unit: str | None
    product: str | None
    country: str | None
    status: RowStatus
    location: LocationRef
    version: VersionSummary | None
    versions_count: int


@dataclass(frozen=True, slots=True)
class LocationCounts:
    """Rows per location group over the whole result (``location=any``).

    With an area, ``footprint`` counts rows intersecting it and
    ``country`` files of the area's countries.
    """

    footprint: int = 0
    country: int = 0
    none: int = 0


@dataclass(frozen=True, slots=True)
class SlotPage:
    """A page of catalog rows; ``next_cursor`` is ``None`` on the last page."""

    items: tuple[SlotRow, ...]
    next_cursor: str | None
    groups: LocationCounts


@dataclass(frozen=True, slots=True)
class IssueRef:
    """A store problem with its place.

    ``code`` is the producer's problem code (``missing_sidecar``,
    ``invalid_sidecar``, ``unknown_segment``, ``legacy_campaigns``,
    ``stale_incoming``) or one found by a check job (``link_mismatch``).
    ``producer`` is the producer of the segment the problem belongs to.
    """

    code: str
    path: str
    segment: str | None
    producer: str
    slot: str | None
    origin: IssueOrigin
    first_seen_at: datetime


@dataclass(frozen=True, slots=True)
class ObservationRef:
    """A source republished the content of a version: a record of a slot's history.

    ``path`` is the producer's record in the store; ``version`` the version
    (path relative to the store) whose content the source served again, under
    a signal (``etag``, ``last_modified``) the producer did not have before.
    It is never a version: no count and no current version follows from it.
    """

    path: str
    version: str | None
    seen_at: datetime
    url: str | None
    etag: str | None
    last_modified: str | None
    size_bytes: int | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class SlotDetail:
    """File card: every version of a slot, links, pins and problems."""

    store: str
    slot: str
    name: str
    segment: SegmentRef
    unit: str | None
    product: str | None
    country: str | None
    status: RowStatus
    current: str | None
    full_sheet: str | None
    versions: tuple[VersionSummary, ...]
    issues: tuple[IssueRef, ...]


@dataclass(frozen=True, slots=True)
class VersionDetail:
    """Every indexed value of one version, for the card and the API."""

    store: str
    slot: str
    segment: SegmentRef
    summary: VersionSummary
    dataset: str | None
    dataset_key: str | None
    product: str | None
    country: str | None
    unit: str | None
    campaign: str | None
    survey_work_id: str | None
    edition: str | None
    coverage: float | None
    parent_request: str | None
    license: str | None
    attribution: str | None
    source_files: tuple[str, ...]
    resolution: str | None
    nodata: float | None
    native_crs: str | None
    footprint: GeoJSONGeometry | None
    has_meta: bool


@dataclass(frozen=True, slots=True)
class GroupMember:
    """A file of one producer request (``parent_request``)."""

    store: str
    slot: str
    path: str
    segment: str | None
    country: str | None
    label: str | None
    is_current: bool


@dataclass(frozen=True, slots=True)
class MapFootprint:
    """One footprint drawn on the map, in WGS84."""

    store: str
    slot: str
    version: str
    segment: str | None
    product: str | None
    label: str | None
    data_year: int | None
    source: str | None
    geometry: GeoJSONGeometry


@dataclass(frozen=True, slots=True)
class GridCell:
    """Number of footprints (by their centre) or stations in one grid cell."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    count: int


@dataclass(frozen=True, slots=True)
class FootprintPage:
    """Footprints of a map view or, above the limit, their grid.

    ``total`` counts the footprints in the view. ``groups`` are the catalog
    counts of the same filters without the view: ``groups.none`` is the
    "files without outline" counter that leads to the catalog.
    """

    total: int
    aggregated: bool
    items: tuple[MapFootprint, ...]
    cells: tuple[GridCell, ...]
    groups: LocationCounts


@dataclass(frozen=True, slots=True)
class SegmentSummary:
    """An indexed segment with its counts."""

    store: str
    segment: SegmentRef
    slots: int
    versions: int


@dataclass(frozen=True, slots=True)
class ProductSummary:
    """An indexed product: its segments (variants) and countries.

    ``product`` is ``None`` for segments the producer does not recognise.
    """

    product: str | None
    countries: tuple[str, ...]
    segments: tuple[SegmentSummary, ...]
    slots: int
    versions: int


@dataclass(frozen=True, slots=True)
class LocalCoverage:
    """Local coverage of an area by one product in one country (decision 5).

    ``ratio`` is the area of the union of the current versions' footprints
    within the area divided by the area, both measured in the planar CRS of
    the country (``crs``). ``reason`` replaces the numbers when they cannot
    be computed: ``no_planar_crs`` (no country, or a country without a
    planar CRS) or ``empty_area``.
    """

    country: str | None
    crs: str | None
    ratio: float | None
    area_km2: float | None
    covered_km2: float | None
    versions_count: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class LocalCoverageReport:
    """Local state of a product for an area: one result per country.

    ``results`` is empty when the store holds no version of the product for
    the area. ``stale`` marks an answer from an index that could not be
    refreshed first (``stale_reason``, e.g. ``store_unavailable``); the
    caller sets it.
    """

    store: str
    product: str
    results: tuple[LocalCoverage, ...]
    stale: bool = False
    stale_reason: str | None = None


@dataclass(frozen=True, slots=True)
class JobRef:
    """A background job as shown next to a store's index state.

    ``progress`` is ``(current, total)`` of the job's last progress event.
    """

    id: str
    kind: str
    state: str
    actor: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class StoreIndexState:
    """Index state of one store ("Indeks z 14:02, skan trwa: 63%").

    ``indexed_at`` is the end of the last complete pass over the store.
    ``full_scan_at`` is the end of the last successful full scan of the
    whole store: incremental scans trust known version directories, so it
    is the last check of their contents. ``stale`` is true while the store
    is unavailable: answers come from the index as it was at ``indexed_at``.
    """

    store: str
    status: StoreStatus
    status_at: datetime | None
    detail: str | None
    indexed_at: datetime | None
    full_scan_at: datetime | None
    slots: int
    versions: int
    missing_versions: int
    unlocated_versions: int
    issues: int
    last_scan: JobRef | None
    running_job: JobRef | None
    stale: bool


@dataclass(frozen=True, slots=True)
class StoreFreshness:
    """How current the index is for one store, without its counts.

    ``stale`` is true while the store is unavailable: answers about it come
    from the index as it was at ``indexed_at``.
    """

    store: str
    status: StoreStatus
    status_at: datetime | None
    detail: str | None
    indexed_at: datetime | None
    stale: bool


@dataclass(frozen=True, slots=True)
class IndexStatus:
    """The local index and its stores."""

    schema_version: int
    created_at: datetime | None
    size_bytes: int
    stores: tuple[StoreIndexState, ...]


@dataclass(frozen=True, slots=True)
class ProductUsage:
    """Disk usage of one product's present versions, each content once."""

    product: str | None
    versions: int
    unique_bytes: int


@dataclass(frozen=True, slots=True)
class StoreUsage:
    """Disk usage of a store's present versions; links add nothing.

    A content (``sha256``) held by several versions (relabelled hard links)
    counts once; a version without ``sha256`` counts by itself.
    """

    store: str
    products: tuple[ProductUsage, ...]
    versions: int
    unique_bytes: int


@dataclass(frozen=True, slots=True)
class AreaRecord:
    """An area kept in the index (drawn, a sheet, or read from a file)."""

    id: str
    source: str
    geometry: GeoJSONGeometry
    created_at: datetime
    area_km2: float | None = None
    countries: tuple[str, ...] = ()
    name: str | None = None


@dataclass(frozen=True, slots=True)
class StoredAvailability:
    """The last report of the availability at the source of an area and product.

    ``checked_at`` is when the source was asked (``report.checked_at``) and
    ``job_id`` the ``availability`` job that asked it; the job itself may be
    pruned since.
    """

    area_id: str
    producer: str
    product: str
    checked_at: datetime
    job_id: str | None
    report: AvailabilityReport


@dataclass(frozen=True, slots=True)
class StoredPlan:
    """The plan of one call of a ``check`` job, kept as long as the job (ADR-044).

    ``call`` is the call's place in the job's ``calls`` (from 0), ``store``
    the configured store the plan is of and ``line`` the producer's command
    line of the run it plans, with the store's root.
    """

    job_id: str
    call: int
    store: str
    line: str
    plan: ActionPlan


@dataclass(frozen=True, slots=True)
class PlanTotals:
    """The plans of a ``check`` job's calls together (ADR-044), as one plan reads.

    ``counts`` holds the positions of each status (every status named),
    ``positions`` all of them and ``todo`` those the runs download;
    ``size_bytes`` sums the sizes the producer tells of those, ``None`` when
    it tells none (never 0 for an unknown size), and ``size_complete`` says
    whether it told every one; ``ok`` is whether every position was checked
    and ``checked_at`` the time of the oldest plan.
    """

    counts: dict[PlanStatus, int]
    positions: int
    todo: int
    size_bytes: int | None
    size_complete: bool
    ok: bool
    checked_at: datetime

    @classmethod
    def of(cls, plans: Sequence[ActionPlan]) -> "PlanTotals":
        """Return the totals of one or more plans."""
        counts = dict.fromkeys(PLAN_STATUSES, 0)
        for plan in plans:
            for status, count in plan.counts().items():
                counts[status] += count
        sized = [plan for plan in plans if plan.todo]
        told = [plan.size_bytes for plan in sized if plan.size_bytes is not None]
        return cls(
            counts=counts,
            positions=sum(len(plan.entries) for plan in plans),
            todo=sum(len(plan.todo) for plan in plans),
            size_bytes=None if sized and not told else sum(told),
            size_complete=all(plan.size_complete for plan in plans),
            ok=all(plan.ok for plan in plans),
            checked_at=min(plan.checked_at for plan in plans),
        )


@dataclass(frozen=True, slots=True)
class SlotUnit:
    """A slot with a footprint in a view: what a view refresh rescans."""

    slot: str
    segment: str | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class ProductVersion:
    """A present version of a store's product, as its layer needs it.

    What ``IndexQueries.product_versions`` gives the local layers (plan
    v0.2, decision 7): the variant fields (``product``, ``horizontal_crs``,
    ``resolution``, ``vertical_crs``; ``segment`` without one of them), the
    data year, edition, label and campaign, the content and the georeference
    of its preview. ``bounds`` (WGS84) is ``None`` for a version without a
    footprint; ``outline`` (WGS84) and ``native`` (its rectangle in
    ``native_crs``) are read only for the versions of a view.
    """

    path: str
    slot: str
    unit: str | None
    segment: str | None
    segment_name: str
    producer: str
    data_year: int | None
    data_date: date | None
    downloaded_at: datetime | None
    edition: str | None
    label: str | None
    campaign: str | None
    sha256: str | None
    size_bytes: int | None
    product: str | None
    dataset_key: str | None
    horizontal_crs: str | None
    vertical_crs: str | None
    resolution: str | None
    nodata: float | None
    location_source: str | None
    native_crs: str | None
    bounds: BBox | None
    outline: GeoJSONGeometry | None = None
    native: GeoJSONGeometry | None = None


@dataclass(frozen=True, slots=True)
class ScanPass:
    """One pass of a scan over a store, a segment or chosen slots.

    ``slots`` (paths) limits a partial pass, e.g. a view refresh; ``None``
    covers the whole store of the producer or the whole ``segment``. Only
    ``IndexWriter.finish_pass`` turns what the pass has not seen into
    missing versions; abandoning a pass changes nothing else.
    """

    store: str
    producer: str
    segment: str | None
    slots: frozenset[str] | None
    full: bool
    started_at: datetime


@dataclass(frozen=True, slots=True)
class BatchResult:
    """What one ``write_entries`` batch changed.

    ``needs_footprint`` are the version entries (and plain files at a
    standard path) whose location is still to be computed: new ones, ones
    still pending, and in a full pass ones without a footprint.
    """

    needs_footprint: tuple[SourceEntry, ...] = ()
    versions_written: int = 0
    links_changed: int = 0
    issues_added: int = 0


@dataclass(frozen=True, slots=True)
class PassSummary:
    """What finishing a pass changed.

    ``missing``: versions newly marked missing; ``reappeared``: missing
    versions seen again; ``removed``: versions dropped after a second full
    pass without them; ``unlinked``: links (standard or ``full_sheet``)
    gone; ``issues_resolved``: problems no longer reported; ``current``: slots
    whose current version the producer's answer changed.
    """

    missing: int = 0
    reappeared: int = 0
    removed: int = 0
    slots_removed: int = 0
    unlinked: int = 0
    issues_resolved: int = 0
    current: int = 0


@dataclass(frozen=True, slots=True)
class KeyedSlot:
    """A slot with the producer's own key and its current version.

    What a scan needs to find a producer's station catalogs: ``key`` is the
    producer's name of the slot (``SourceEntry.slot_key``), ``path`` the slot
    and ``current`` the file of its current version, both relative to the
    store; ``None`` without a current version.
    """

    key: str
    path: str
    current: str | None


@dataclass(frozen=True, slots=True)
class StationCatalogRecord:
    """The catalog version a provider's stations in the index were read from.

    ``slot`` is the catalog's slot and ``version`` the file of the version
    read, relative to the store; ``read_at`` is when it was read (UTC).
    """

    provider: str
    producer: str
    slot: str
    version: str
    read_at: datetime


@dataclass(frozen=True, slots=True)
class SeriesCatalogRecord:
    """The series version a dataset's coverage in the index was read from.

    ``slot`` is the series' slot and ``version`` the ``series.json`` of the
    version read, relative to the store; ``read_at`` is when it was read
    (UTC).
    """

    dataset: str
    producer: str
    provider: str
    slot: str
    version: str
    read_at: datetime


@dataclass(frozen=True, slots=True)
class StationQuery:
    """Filters and page of a station query (``GET /stations``, ``/map/stations``).

    Parameters
    ----------
    store, provider : str or None
        Exact store id and provider (``IMGW-PIB``, ``CHMI``).
    code : str or None
        Exact station code.
    kind : str or None
        Exact kind (``hydro``, ``meteo``).
    meteo_kinds : tuple[MeteoKind, ...]
        Meteo stations of any of these kinds only (``synoptic``, ``climate``,
        ``precipitation``; the type chips of the map); empty: no such filter.
    active : bool or None
        Active (``True``) or historical (``False``) stations only.
    river_code, river_scope : str or None, {"exact", "tributaries"}
        The river's hydrographic code (P19): ``exact`` takes the stations of
        that code, ``tributaries`` also those whose code begins with it (IMGW
        ``2138`` takes ``21382``, never ``2139``); a code with ``-`` between
        its parts (ČHMÚ ``1-05-03-0110``) begins with whole parts only
        (``1-05`` takes it, ``1-0`` does not).
    q : str or None
        Search text: stations whose name or river contains it, case-folded,
        or whose code begins with it; no character is a wildcard. Blank: no
        search.
    bbox : BBox or None
        ``(min_lon, min_lat, max_lon, max_lat)`` in WGS84: located stations
        inside it, edges included (a map view). A station without a location
        is never in a box (SPEC 4.3 point 3): with a box, ``location="any"``
        lists located stations only.
    location : {"any", "with", "none"}
        Which stations are rows: every one, located ones, or those without a
        location (the box and the area do not apply to them).
    limit : int
        Page size, 1 to ``MAX_PAGE_LIMIT``.
    cursor : str or None
        ``next_cursor`` of the previous page of the same query.
    sort : {"river", "name"}
        The order of the rows of a page (SPEC 6.8): along rivers (the
        hydrographic code as text, so a tributary follows its river, then
        the order of the provider's list on the river, then the name;
        stations without a code or an order after those with one), or by
        name; then the code, provider and store. A map draws its stations by
        name.
    area : GeoJSONGeometry or None
        A ``Polygon`` or ``MultiPolygon`` in WGS84: the located stations in
        it, edges included, and those on its boundary (SPEC 6.7): closer to
        the boundary, on either side, than their location uncertainty. Like
        a box, it never takes a station without a location.
    boundary : bool
        Whether the stations on the area's boundary are rows; they are
        counted either way (``StationCounts.boundary``).
    dataset : str or None
        The dataset (``pl.imgw.hydro_daily``): only stations with a series
        of it, and its coverage only.
    variables : tuple[str, ...]
        Stations with a value of each of these variables (``Q``), or
        variable keys (``Q_max@winter``), in a series (of ``dataset``).
    coverage : tuple[tuple[str, SeriesState], ...]
        ``(variable, state)``: the variable's label in the range of years has
        one of the states given for it (``Q:continuous``, ``Q:gaps``);
        different variables must all match. Needs ``dataset``.
    min_complete_years : tuple[tuple[str, int], ...]
        ``(variable, years)``: the variable's label has at least this many
        full years (``Q:30``). Needs ``dataset``. A variable of several
        half-year periods passes a coverage filter when each period does; a
        station without the variable never passes a filter of it.
    year_type, years : YearType or None, YearRange or None
        The numbering and the range R of the labels (and of the coverage
        filters); ``None``: the type of ``year_types`` and the dataset's R by
        default (SPEC 4.8.4).
    year_types : YearTypes
        The year type remembered for each family: the numbering of a
        dataset's labels when ``year_type`` is ``None`` (P15).
    labels : bool
        Whether the result holds the coverage of its stations' series
        (``StationPage.coverage``), labelled in ``years`` and ``year_type``.
    """

    store: str | None = None
    provider: str | None = None
    code: str | None = None
    kind: str | None = None
    meteo_kinds: tuple[MeteoKind, ...] = ()
    active: bool | None = None
    river_code: str | None = None
    river_scope: RiverScope = "exact"
    q: str | None = None
    bbox: BBox | None = None
    location: LocationFilter = "any"
    limit: int = DEFAULT_PAGE_LIMIT
    cursor: str | None = None
    sort: StationSort = "river"
    area: GeoJSONGeometry | None = None
    boundary: bool = True
    dataset: str | None = None
    variables: tuple[str, ...] = ()
    coverage: tuple[tuple[str, SeriesState], ...] = ()
    min_complete_years: tuple[tuple[str, int], ...] = ()
    year_type: YearType | None = None
    years: YearRange | None = None
    year_types: YearTypes = DEFAULT_YEAR_TYPES
    labels: bool = False


@dataclass(frozen=True, slots=True)
class StationRow:
    """A station of a provider's current catalog, as the index keeps it.

    ``point`` is ``(lon, lat)`` in WGS84 for ``location="point"``; a station
    without one has ``location="none"`` and the catalog's ``location_reason``
    (``none``, ``zero``, ``outside_country``). ``catalog`` is the label of the
    catalog version the station was read from (its download date) and
    ``catalog_version`` its file, relative to the store. ``on_boundary``:
    the station lies on the boundary of the query's area (closer to it than
    its location uncertainty); ``False`` without an area.
    """

    store: str
    provider: str
    code: str
    kind: str | None
    meteo_kind: str | None
    name: str | None
    river: str | None
    hydrographic_code: str | None
    river_order: int | None
    location: StationLocation
    point: tuple[float, float] | None
    location_reason: str | None
    location_source: str | None
    location_uncertainty_m: float | None
    active: bool | None
    established_year: int | None
    gauge_zero_m: float | None
    river_km: float | None
    elevation_m: float | None
    catalog: str | None
    catalog_version: str | None
    on_boundary: bool = False


@dataclass(frozen=True, slots=True)
class StationCounts:
    """Stations of a query by location, whatever its ``location`` selects.

    ``located`` counts the located stations that match the filters (inside
    the box or the area when there is one, with the stations on the area's
    boundary when ``StationQuery.boundary`` takes them); ``boundary`` those
    on the area's boundary, whether taken or not; ``unlocated`` the stations
    without a location that match the attribute and coverage filters, which
    a box or an area never narrows (SPEC 4.3); ``hidden`` the stations of
    ``located`` and ``unlocated`` that the coverage filters hid ("ukryte
    filtrem: 4", SPEC 4.8.4).
    """

    located: int = 0
    unlocated: int = 0
    boundary: int = 0
    hidden: int = 0


@dataclass(frozen=True, slots=True)
class CoverageVariable:
    """A variable of a station's series with its label in a range of years.

    ``key`` names it in the series index (``Q``, ``Q_max@winter``), with its
    ``variable``, ``unit`` and half-year ``period``; ``first`` and ``last``
    are its first and last date with a value and ``accumulated`` its
    accumulated sums. ``years`` are its years of the range in the label's
    year type (a year the index knows nothing of is left out) and ``label``
    its label (SPEC 4.8.4); ``known`` are the periods whose units the label
    counts as known (the station's own, else the version's: A-ADR-021
    erratum 3), each the dates of its first and last day.
    """

    key: str
    variable: str
    unit: str
    period: str | None
    first: date | None
    last: date | None
    accumulated: int
    years: tuple[SeriesYear, ...]
    label: SeriesLabel
    known: tuple[DateRange, ...] = ()


@dataclass(frozen=True, slots=True)
class StationCoverage:
    """The coverage of a station's series in one dataset, read from the index.

    ``kind`` (``hydro``, ``meteo``) and ``time_unit`` are the dataset's;
    ``year_type`` numbers the years of ``span``, the range R of the labels
    (``None`` when the version knows no period). ``file`` is the station's
    series file in the version ``series_version`` (its ``series.json``,
    relative to the store), with its ``sha256``; ``series`` is the label of
    that version and ``license`` and ``attribution`` its licence and the
    formula the source requires (``None`` when the index has no such
    version). Each variable keeps the order of the series index.
    """

    store: str
    provider: str
    code: str
    dataset: str
    kind: str | None
    time_unit: TimeUnit
    year_type: YearType
    span: YearRange | None
    file: str
    series: str | None
    series_version: str
    variables: tuple[CoverageVariable, ...]
    sha256: str | None = None
    license: str | None = None
    attribution: str | None = None


@dataclass(frozen=True, slots=True)
class StationPage:
    """A page of stations in the order of the query's ``sort``.

    ``next_cursor`` is ``None`` on the last page. ``coverage`` holds the
    coverage of the series of the page's stations when the query asked for
    labels (``StationQuery.labels``), by station and dataset; empty otherwise.
    """

    items: tuple[StationRow, ...]
    next_cursor: str | None
    counts: StationCounts
    coverage: tuple[StationCoverage, ...] = ()


@dataclass(frozen=True, slots=True)
class StationMap:
    """The located stations of a map view, or their grid above the limit.

    ``total`` counts the stations of the view that match the filters;
    ``aggregated`` replaces ``items`` by ``cells`` (each a count of
    stations). ``counts`` are those of the same query as a list, and
    ``coverage`` that of ``items`` when the query asked for labels.
    """

    total: int
    aggregated: bool
    items: tuple[StationRow, ...]
    cells: tuple[GridCell, ...]
    counts: StationCounts
    coverage: tuple[StationCoverage, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetVariable:
    """A variable of a dataset's station series, as the series index names it.

    ``key`` names it in the series index (``Q``, ``Q_max@winter``), with its
    ``variable``, ``unit`` and half-year ``period`` (``None`` for daily and
    monthly data).
    """

    key: str
    variable: str
    unit: str
    period: str | None


@dataclass(frozen=True, slots=True)
class StationDataset:
    """A dataset with station series in a store's index (the dataset chip, 6.7).

    ``name`` is the producer's name of the dataset's segment; ``kind`` its
    family (``hydro``, ``meteo``) and ``time_unit`` its unit. ``span`` is R
    by default (SPEC 4.8.4; ``None`` when the version knows no period) in
    ``year_type``, the default year type of its labels.
    ``series`` is the label of the current series version and
    ``series_version`` its ``series.json``, relative to the store.
    ``variables`` are the distinct keys of its stations' series, in the order
    of the series index.
    """

    store: str
    dataset: str
    name: str | None
    provider: str
    kind: str | None
    time_unit: TimeUnit
    year_type: YearType
    span: YearRange | None
    series: str | None
    series_version: str
    variables: tuple[DatasetVariable, ...]


@dataclass(frozen=True, slots=True)
class ManifestStamp:
    """Size and modification time of a project manifest when it was read."""

    mtime_ns: int | None
    size: int | None


@dataclass(frozen=True, slots=True)
class ProjectManifestRef:
    """One producer's manifest of a project as it was last read.

    ``store`` is the configured store the manifest names, ``None`` when no
    configured store matches ``store_dir`` (the manifest's own store path).
    ``status`` is the producer's project status when the manifest was last
    read (``None``: not checked); ``problem`` is the producer's message for
    an invalid manifest, whose tasks and pins are not used.
    """

    producer: str
    store: str | None
    store_dir: str
    status: str | None
    problem: str | None
    scanned_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectRef:
    """A discovered project as listed (``GET /projects``).

    A project is its directory, holding the manifest of one producer or of
    several (SPEC 4.7): ``manifests`` in the order of the producers'
    manifests (``PROJECT_MANIFESTS``: Kartograf's first), each with its own
    store, status and problem, so an invalid manifest hides nothing of
    another. ``tasks``, ``pins`` and ``missing_pins`` count those of every
    manifest; ``missing_pins`` counts pins whose version is not present in
    the index or holds other content. ``access_key`` is the key of the
    project's access entry in the state database: its directory after
    ``realpath`` when it was scanned (``archiwista.auth.access_key``).
    """

    key: str
    name: str
    path: str
    access_key: str
    manifests: tuple[ProjectManifestRef, ...]
    tasks: int
    pins: int
    missing_pins: int

    @property
    def producers(self) -> tuple[str, ...]:
        """Return the producers whose manifests the project holds, in order."""
        return tuple(manifest.producer for manifest in self.manifests)

    def manifest(self, producer: str) -> ProjectManifestRef | None:
        """Return the project's manifest of ``producer``, ``None`` without one."""
        return next(
            (item for item in self.manifests if item.producer == producer), None
        )


@dataclass(frozen=True, slots=True)
class ProjectTaskRef:
    """A task of a project's manifest with its existing command and options."""

    producer: str
    task_id: str
    command: str
    options: dict[str, object]
    status: str | None


@dataclass(frozen=True, slots=True)
class ProjectPinRef:
    """A version a project task pinned, joined with the index by path and SHA-256.

    ``producer`` is the producer of the manifest that pins it; ``state`` is
    ``unknown`` when that manifest's store is not configured; ``slot``,
    ``label`` and ``size_bytes`` come from the indexed version.
    """

    producer: str
    task: str | None
    version: str
    sha256: str | None
    state: PinState
    slot: str | None
    label: str | None
    size_bytes: int | None
    is_current: bool


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """A project with its tasks and pinned versions, manifest after manifest.

    Within a manifest the tasks keep the manifest's order.
    """

    project: ProjectRef
    tasks: tuple[ProjectTaskRef, ...]
    pins: tuple[ProjectPinRef, ...]


@dataclass(frozen=True, slots=True)
class UnusedVersions:
    """Present versions that are not current, not a full sheet, not pinned.

    A report for a person deciding about cleanup (Archiwista deletes
    nothing). ``unique_bytes`` counts each content once;
    ``reclaimable_bytes`` only contents no other present version holds.
    """

    store: str
    products: tuple[ProductUsage, ...]
    versions: int
    unique_bytes: int
    reclaimable_bytes: int


@dataclass(frozen=True, slots=True)
class OrphanLink:
    """A link whose sidecar names a version that is not present.

    ``kind`` is ``link`` (the standard path) or ``full_sheet``;
    ``producer`` is the producer of the slot's segment.
    """

    slot: str
    segment: str | None
    producer: str
    kind: Literal["link", "full_sheet"]
    version: str


# Own data of projects (plan v0.2, decision 8).


@dataclass(frozen=True, slots=True)
class OwnProblem:
    """A problem of a project's data folder, one of its files or snapshots.

    Attributes
    ----------
    code : OwnProblemCode
        ``own_folder_unreadable``, ``own_folder_invalid``,
        ``own_folder_too_large``, ``own_file_unreadable``,
        ``invalid_snapshot``, ``unknown_snapshot_schema``,
        ``snapshot_modified``, ``stale_snapshot_incoming`` or
        ``path_outside_root``.
    path : str or None
        Place in the folder (``/`` separated, e.g. ``.wersje/a.gpkg/<label>``
        for a snapshot); ``None`` for the folder itself.
    reason : str or None
        What exactly: the reason of ``own_folder_invalid``
        (``OwnFolderReason``), the read error of ``own_file_unreadable``, the
        schema of ``unknown_snapshot_schema``.
    first_seen_at : datetime or None
        When a scan first found it; ``None`` before it is recorded.
    """

    code: OwnProblemCode
    path: str | None = None
    reason: str | None = None
    first_seen_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OwnFolderRecord:
    """A project's data folder as its last ``own_scan`` found it.

    Attributes
    ----------
    project : str
        Project key (``ProjectRef.key``).
    path : str
        The folder: the setting (``AppSettings.own_data_dirs``) or the
        project directory's ``dane/``.
    source : {"default", "setting"}
        Where ``path`` comes from.
    state : {"ok", "missing", "unreadable", "invalid"}
        ``invalid``: refused by the rules of decision 8 (``reason``) and not
        read; ``missing`` and ``unreadable`` keep the files found before.
    reason : OwnFolderReason or None
        Why an ``invalid`` folder is refused.
    scanned_at : datetime
        When the folder was last scanned.
    files, size_bytes : int
        Files present in the index and their bytes.
    snapshots, snapshots_bytes : int
        Snapshots in ``.wersje/`` and their bytes.
    problems : tuple[OwnProblem, ...]
        Problems of the folder, its files and snapshots, by path.
    """

    project: str
    path: str
    source: OwnFolderSource
    state: OwnFolderState
    reason: OwnFolderReason | None
    scanned_at: datetime
    files: int
    size_bytes: int
    snapshots: int
    snapshots_bytes: int
    problems: tuple[OwnProblem, ...]


@dataclass(frozen=True, slots=True)
class OwnSnapshotRef:
    """The snapshot a file's change is measured against."""

    label: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OwnFileRow:
    """A file of a data folder as listed (``IndexQueries.own_files``).

    Attributes
    ----------
    file_id : str
        16 characters of the SHA-256 of ``path`` (``own_file_id``).
    path : str
        Main file relative to the folder, ``/`` separated, in NFC.
    kind : str
        Kind of its format by extension (``archiwista.formats.FormatKind``).
    driver : str or None
        GDAL driver that read it; ``None``: not read by GDAL.
    size_bytes : int
        Bytes of the file with every member of its set.
    modified_at : datetime
        Modification time of the main file.
    state : {"ok", "unrecognized", "unreadable", "missing"}
        ``unrecognized``: no GDAL format; ``missing``: gone since
        ``missing_since``.
    change : {"unsnapshotted", "unchanged", "changed"}
        Its content against its last valid snapshot (``last_snapshot``).
    last_snapshot : OwnSnapshotRef or None
        The newest valid snapshot of the file.
    snapshots : int
        Its snapshots in ``.wersje/`` (valid or not).
    location : LocationRef
        ``footprint`` with a WGS84 outline, or ``none`` with its reason
        (``no_crs``, ``no_georeference``, ``no_extent``,
        ``transform_unavailable``, ``unreadable``, ``unrecognized``).
    outline : GeoJSONGeometry or None
        The WGS84 polygon of its extent (``outline_wgs84``) with
        ``footprint``; ``None`` without one.
    """

    file_id: str
    path: str
    kind: str
    driver: str | None
    size_bytes: int
    modified_at: datetime
    state: OwnFileState
    change: OwnChange
    last_snapshot: OwnSnapshotRef | None
    snapshots: int
    location: LocationRef
    outline: GeoJSONGeometry | None


@dataclass(frozen=True, slots=True)
class OwnFilePage:
    """Files of a data folder by path; ``next_cursor`` continues the list."""

    folder: OwnFolderRecord
    items: tuple[OwnFileRow, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class OwnFileObservation:
    """One observed state of a file (its history, without content)."""

    observed_at: datetime
    size_bytes: int
    modified_at: datetime
    content_sha256: str | None
    feature_count: int | None


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    """A snapshot of a file in ``<folder>/.wersje/<path>/<label>/``.

    Attributes
    ----------
    path : str
        The working file it copies, relative to the folder.
    label : str
        Its directory's name.
    state : {"ok", "invalid", "modified"}
        ``invalid``: no valid ``migawka.json`` (or an unknown schema);
        ``modified``: its files differ from the document.
    created_at : datetime or None
        When it was published (from the document).
    content_method, content_sha256 : str or None
        Content identity of the copy (decision 8).
    size_bytes : int
        Bytes of its files.
    document : dict or None
        ``migawka.json`` as read, with fields of newer versions; ``None``
        when it cannot be read.
    """

    path: str
    label: str
    state: SnapshotState
    created_at: datetime | None
    content_method: str | None
    content_sha256: str | None
    size_bytes: int
    document: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class OwnFileDetail:
    """Everything the index knows of one file of a data folder (its card).

    Attributes
    ----------
    file : OwnFileRow
        The file as listed.
    folder : OwnFolderRecord
        Its data folder.
    disk_path : str
        The main file's path below the folder as named on the disk
        (``path`` in NFC may differ).
    stamp : str
        Sizes and modification times of its files (and of a SQLite ``-wal``
        or ``-journal``) when it was read: a preview checks the file has not
        changed since (``archiwista.owndata.scan.stamp_holds``).
    members : tuple[str, ...]
        Every file of its set, the main file first, relative to the folder.
    read_error : str or None
        Why it was not read (``unsupported_format``, ``unreadable``,
        ``timeout``, ``memory_limit``, ``inconsistent``,
        ``path_outside_root``).
    read_detail : str or None
        The library's English message behind ``read_error``.
    content_method, content_sha256 : str or None
        Content identity of the working file (decision 8).
    layers : tuple[LayerInfo, ...]
        Vector layers.
    raster : RasterInfo or None
        Raster parameters.
    feature_count : int or None
        Features of all layers.
    native_crs : str or None
        ``EPSG:<code>`` or WKT.
    native_bbox : BBox or None
        Extent in ``native_crs``.
    wgs84 : GeoJSONGeometry or None
        WGS84 polygon of the extent (``outline_wgs84``).
    first_seen_at, changed_at : datetime
        When the file was first seen and its content last changed.
    missing_since : datetime or None
        When a scan found it gone.
    history : tuple[OwnFileObservation, ...]
        Observed states, newest first (at most ``MAX_OWN_FILE_STATES``).
    snapshots : tuple[SnapshotRecord, ...]
        Its snapshots, newest first.
    problems : tuple[OwnProblem, ...]
        Problems of the file and of its snapshots.
    """

    file: OwnFileRow
    folder: OwnFolderRecord
    disk_path: str
    stamp: str
    members: tuple[str, ...]
    read_error: str | None
    read_detail: str | None
    content_method: str | None
    content_sha256: str | None
    layers: tuple[LayerInfo, ...]
    raster: RasterInfo | None
    feature_count: int | None
    native_crs: str | None
    native_bbox: BBox | None
    wgs84: GeoJSONGeometry | None
    first_seen_at: datetime
    changed_at: datetime
    missing_since: datetime | None
    history: tuple[OwnFileObservation, ...]
    snapshots: tuple[SnapshotRecord, ...]
    problems: tuple[OwnProblem, ...]


@dataclass(frozen=True, slots=True)
class KnownOwnFile:
    """What a scan needs of an indexed file to skip it (``stat`` only).

    ``stamp`` is the sizes and times of its files when it was read;
    ``retry``: it changed while it was read, so the next scan reads it again;
    ``read_error``: why it was not read, a problem reported at every scan.
    """

    stamp: str
    missing: bool
    retry: bool
    read_error: str | None = None


@dataclass(frozen=True, slots=True)
class OwnFileWrite:
    """A file of a data folder as a scan read it (``IndexWriter.write_own_files``).

    Attributes
    ----------
    path : str
        Main file relative to the folder, ``/`` separated, in NFC.
    disk_path : str
        The same path as named on the disk.
    stamp : str
        Sizes and modification times of its files (and of a SQLite
        ``-wal`` or ``-journal``) before it was read.
    size_bytes : int
        Bytes of all its files.
    modified_ns : int
        Modification time of the main file, ns since the epoch.
    kind : str
        ``archiwista.formats.FormatKind`` by extension.
    driver : str or None
        GDAL driver that read it.
    members : tuple[str, ...]
        Its files relative to the folder, the main file first.
    state : {"ok", "unrecognized", "unreadable"}
        How the read went.
    read_error, read_detail : str or None
        Why it was not read, and the library's message.
    content_method, content_sha256 : str or None
        Content identity (decision 8); ``None`` when it was not computed.
    layers : tuple[LayerInfo, ...]
        Vector layers.
    raster : RasterInfo or None
        Raster parameters.
    feature_count : int or None
        Features of all layers.
    native_crs : str or None
        CRS of the file.
    native_bbox : BBox or None
        Extent in ``native_crs``.
    wgs84 : GeoJSONGeometry or None
        WGS84 polygon of the extent; ``None`` with ``location_reason``.
    location_reason : str or None
        Why the file has no WGS84 outline.
    retry : bool
        It changed while read: the next scan reads it again.
    """

    path: str
    disk_path: str
    stamp: str
    size_bytes: int
    modified_ns: int
    kind: str
    driver: str | None
    members: tuple[str, ...]
    state: OwnReadState
    read_error: str | None = None
    read_detail: str | None = None
    content_method: str | None = None
    content_sha256: str | None = None
    layers: tuple[LayerInfo, ...] = ()
    raster: RasterInfo | None = None
    feature_count: int | None = None
    native_crs: str | None = None
    native_bbox: BBox | None = None
    wgs84: GeoJSONGeometry | None = None
    location_reason: str | None = None
    retry: bool = False


@dataclass(frozen=True, slots=True)
class OwnFilesWritten:
    """What ``IndexWriter.write_own_files`` changed: files new and rewritten."""

    new: int = 0
    changed: int = 0


@dataclass(frozen=True, slots=True)
class OwnMissingResult:
    """What ``IndexWriter.mark_own_missing`` changed.

    ``missing``: files newly gone; ``reappeared``: missing files seen again;
    ``dropped``: files beyond ``MAX_OWN_FILES`` taken out of the index.
    """

    missing: int = 0
    reappeared: int = 0
    dropped: int = 0


@dataclass(frozen=True, slots=True)
class SnapshotWrite:
    """A snapshot as a scan or the ``snapshot`` job found it.

    Attributes
    ----------
    path : str
        The working file, relative to the folder (``/``, NFC).
    label : str
        The snapshot directory's name.
    state : {"ok", "invalid", "modified"}
        Validity of the snapshot.
    stamp : str
        Sizes and times of the snapshot directory's files: a scan checks
        them again only after a change.
    size_bytes : int
        Bytes of its files.
    document : Mapping or None
        ``migawka.json`` as read; ``None`` when it cannot be read.
    created_at : datetime or None
        The document's publication time.
    content_method, content_sha256 : str or None
        The document's content identity.
    """

    path: str
    label: str
    state: SnapshotState
    stamp: str
    size_bytes: int
    document: Mapping[str, object] | None = None
    created_at: datetime | None = None
    content_method: str | None = None
    content_sha256: str | None = None


def own_file_id(path: str) -> str:
    """Return a file's id in its data folder (``file_id`` of the API).

    16 characters of the SHA-256 of the path relative to the folder, ``/``
    separated, in NFC (plan v0.2, decision 10): one URL segment, the same
    after an index rebuild.
    """
    text = unicodedata.normalize("NFC", path)
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:16]
