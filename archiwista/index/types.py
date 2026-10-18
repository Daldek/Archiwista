"""Typed inputs and results of the local index (queries, writer, coverage).

Public keys are the configured store id (``store``) and paths relative to
the store's producer directory (``slot``, ``path``) — never integer row ids
or absolute paths. Times are timezone-aware UTC ``datetime`` values.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from archiwista.sources import (
    CoordinateTransformer,
    GeoJSONGeometry,
    LocationKind,
    SourceEntry,
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
type TransformerFactory = Callable[[str, str], CoordinateTransformer]

VERSIONS_MODES: tuple[VersionsMode, ...] = (
    "current",
    "all",
    "full_sheet",
    "pinned",
    "noncurrent_unpinned",
)
LOCATION_FILTERS: tuple[LocationFilter, ...] = ("any", "with", "none")
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
    limit: int = MAP_FOOTPRINT_LIMIT
    grid_columns: int = DEFAULT_GRID_COLUMNS


@dataclass(frozen=True, slots=True)
class SegmentRef:
    """A segment of a store with the producer's human-readable name.

    ``segment`` is ``None`` for a producer that does not split its store.
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
    """

    project: str
    project_key: str
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
    """

    code: str
    path: str
    segment: str | None
    slot: str | None
    origin: IssueOrigin
    first_seen_at: datetime


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
    """Number of footprints whose centre falls in one grid cell."""

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
    ``stale`` is true while the store is unavailable: answers come from the
    index as it was at ``indexed_at``.
    """

    store: str
    status: StoreStatus
    status_at: datetime | None
    detail: str | None
    indexed_at: datetime | None
    slots: int
    versions: int
    missing_versions: int
    unlocated_versions: int
    issues: int
    last_scan: JobRef | None
    running_job: JobRef | None
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
class SlotUnit:
    """A slot with a footprint in a view: what a view refresh rescans."""

    slot: str
    segment: str | None
    unit: str | None


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
    gone; ``issues_resolved``: problems no longer reported.
    """

    missing: int = 0
    reappeared: int = 0
    removed: int = 0
    slots_removed: int = 0
    unlinked: int = 0
    issues_resolved: int = 0


@dataclass(frozen=True, slots=True)
class ManifestStamp:
    """Size and modification time of a project manifest when it was read."""

    mtime_ns: int | None
    size: int | None


@dataclass(frozen=True, slots=True)
class ProjectRef:
    """A discovered project as listed (``GET /projects``).

    ``store`` is the configured store the manifest names, ``None`` when no
    configured store matches ``store_dir`` (the manifest's own store path).
    ``status`` is the producer's project status when the manifest was last
    read (``None``: not checked); ``problem`` is the producer's message for
    an invalid manifest. ``missing_pins`` counts pins whose version is not
    present in the index or holds other content. ``access_key`` is the key
    of the project's access entry in the state database: its directory after
    ``realpath`` when it was scanned (``archiwista.auth.access_key``).
    """

    key: str
    name: str
    producer: str
    path: str
    access_key: str
    store: str | None
    store_dir: str
    status: str | None
    problem: str | None
    scanned_at: datetime
    tasks: int
    pins: int
    missing_pins: int


@dataclass(frozen=True, slots=True)
class ProjectTaskRef:
    """A task of a project with its existing command and options."""

    task_id: str
    command: str
    options: dict[str, object]
    status: str | None


@dataclass(frozen=True, slots=True)
class ProjectPinRef:
    """A version a project task pinned, joined with the index by path and SHA-256.

    ``state`` is ``unknown`` when the project's store is not configured;
    ``slot``, ``label`` and ``size_bytes`` come from the indexed version.
    """

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
    """A project with its tasks (manifest order) and pinned versions."""

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

    ``kind`` is ``link`` (the standard path) or ``full_sheet``.
    """

    slot: str
    segment: str | None
    kind: Literal["link", "full_sheet"]
    version: str
