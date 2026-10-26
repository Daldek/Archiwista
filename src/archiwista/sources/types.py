"""Producer-neutral values exchanged between adapters and the index.

Every ``store`` field holds the producer directory of a store as text: the
``root`` given to the adapter (Kartograf's store root, the directory that holds
``kartograf-store.json``) or, for a project, the store directory its manifest
names. Adapters resolve relative paths against it, so ``read_meta``,
``footprint`` and ``confirm_link`` locate an entry from the entry alone. The
index keys rows by the configured store id instead and maps the id to this
directory through the store configuration.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

type SourceStatus = Literal["available", "not_installed", "incompatible", "error"]
type EntryKind = Literal["version", "link", "full_sheet", "problem", "observation"]
type LocationKind = Literal["footprint", "country", "none"]
type GeoJSONGeometry = dict[str, object]
type DefaultRootSource = Literal["default", "env", "dotenv", "file"]
type OptionType = Literal["string", "integer", "number", "boolean", "array", "object"]
type PathRole = Literal["input", "output"]
type CommandWrites = Literal["none", "add", "replace", "delete"]
type PlanStatus = Literal["current", "newer", "missing", "unverifiable", "check_failed"]
type FileStatus = Literal["new", "unchanged", "relabeled"]
type ItemStatus = Literal["ok", "failed"]
type RunStatus = Literal["ok", "partial", "failed"]
type ProjectFileStatus = Literal[
    "ok",
    "missing",
    "corrupt",
    "current",
    "newer",
    "added",
    "removed",
    "unverifiable",
    "check_failed",
    "conflict",
]
type TaskOutcome = Literal["pinned", "unchanged", "restored", "updated", "failed"]
# The year numbering of a series: hydrological (1 XI to 31 X) or calendar.
type YearType = Literal["hydrological", "calendar"]
# The unit of a series: a day, a month, or a half-year characteristic (one
# value of each key in a hydrological year).
type TimeUnit = Literal["day", "month", "half_year"]
# A statistic of a half-year characteristic that is an extreme of its variable.
type Extreme = Literal["min", "max"]
type DateRange = tuple[date, date]

# The statuses of a plan's positions in the order the producers define them.
PLAN_STATUSES: tuple[PlanStatus, ...] = (
    "current",
    "newer",
    "missing",
    "unverifiable",
    "check_failed",
)
# The positions a run of a plan downloads (Kartograf's ``TODO_STATUSES``).
PLAN_TODO: tuple[PlanStatus, ...] = ("newer", "missing")
# The statuses of a file a run left in a store (DEV §19 Z6). A plain file
# (``written``, ``replaced``) is no file of a store.
FILE_STATUSES: tuple[FileStatus, ...] = ("new", "unchanged", "relabeled")
# The states of a project's file in the order the producers define them: of a
# pin in the store (``ok``, ``missing``, ``corrupt``), and of a pin or a
# position compared with the source (the others).
PROJECT_FILE_STATUSES: tuple[ProjectFileStatus, ...] = (
    "ok",
    "missing",
    "corrupt",
    "current",
    "newer",
    "added",
    "removed",
    "unverifiable",
    "check_failed",
    "conflict",
)
# The outcomes of a task of a project's download.
TASK_OUTCOMES: tuple[TaskOutcome, ...] = (
    "pinned",
    "unchanged",
    "restored",
    "updated",
    "failed",
)


@dataclass(frozen=True, slots=True)
class SourceContext:
    """Local resources Archiwista hands to a plugin factory.

    Parameters
    ----------
    cache_dir : Path
        Local cache directory owned by the plugin
        (``<user_data_dir>/cache/<producer>/``), never on a share. It may not
        exist yet; the plugin creates it when it first writes.
    """

    cache_dir: Path


@dataclass(frozen=True, slots=True)
class ScanScope:
    """Restrict a scan to a segment, its units or one part of it.

    Parameters
    ----------
    segment : str or None
        Producer segment (``SegmentedAdapter.segments``); ``None`` scans all.
    units : tuple[str, ...] or None
        Unit identifiers of ``segment`` (sheet codes, TERYT...) whose slots
        alone are read; ``None`` reads the whole segment.
    partition : str or None
        One part of ``segment`` (``PartitionedAdapter.partitions``); the
        parts of a segment together read all of it. Not with ``units``.
    known_versions : Mapping[str, tuple[str, ...]]
        Versions the index knows, by directory: a directory's path relative
        to the store (with ``/``) maps to the names of its files. Only
        directories whose every file was a valid version at the last read
        are named. These versions come back with ``skipped=True`` and
        without their metadata being read again; a producer whose version
        directories never change reports them without listing their
        directory, so only a scan without ``known_versions`` (a full scan)
        notices a file removed from or added to such a directory.
    """

    segment: str | None = None
    units: tuple[str, ...] | None = None
    partition: str | None = None
    known_versions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourcePartition:
    """A part of a segment read on its own (``ScanScope.partition``).

    ``weight`` estimates the cost of reading it from what the index knows
    (e.g. its known versions), 0 when nothing is known; a scan reads the
    heaviest parts first.
    """

    key: str
    weight: int = 0


@dataclass(frozen=True, slots=True)
class SourceState:
    """Report a producer's availability and supported version information.

    ``store`` is the probed producer directory as text, ``None`` for the
    state of the plugin itself. For a store the producer refuses, ``detail``
    says what is wrong, ``reason`` is the machine code of the cause
    (``no_marker``, ``unsupported_marker``, ``foreign_store`` or
    ``not_a_store``) and ``hint`` one line that tells how to fix it, the
    command where one exists (e.g. ``imgw store init --root <path>``,
    DEV-19.13); ``detail`` and ``hint`` are catalog messages, and the three
    stay ``None`` for a state that has nothing to add.
    """

    producer: str
    status: SourceStatus
    store: str | None = None
    package_version: str | None = None
    supported_versions: str | None = None
    schemas: tuple[str, ...] = ()
    detail: str | None = None
    reason: str | None = None
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class DefaultRoot:
    """The directory a producer uses for a store when a call names none.

    Archiwista names the store in every call it makes (Decision 1 of the plan of
    2026-10-25), so it never uses this directory for a call; it only reports it,
    so that the wizard can offer it and ``archiwista doctor`` can show it.

    Parameters
    ----------
    path : Path
        The directory; it need not exist.
    source : {"default", "env", "dotenv", "file"}
        Where the producer's settings found it: its own default (``<data_dir>``
        and the producer's name), an environment variable, the same variable in
        a ``.env`` file (IMGWTools) or the settings file.
    name : str or None
        The variable (``KARTOGRAF_ROOT``, ``IMGW_ROOT``) or the table
        (``[kartograf]``, ``[imgw]``) that gave it; ``None`` for the default.
    exists : bool
        Whether ``path`` is a directory.
    marked : bool
        Whether it holds the producer's store marker: a store the producer has
        written to or initialised.
    """

    path: Path
    source: DefaultRootSource
    name: str | None
    exists: bool
    marked: bool


@dataclass(frozen=True, slots=True)
class SourceSegment:
    """Describe a producer segment for people and for planar computations.

    Parameters
    ----------
    segment : str
        Segment as listed by ``SegmentedAdapter.segments``.
    product, country, dataset_key : str or None
        Product, country code (e.g. ``"PL"``) and source key the producer
        recognises; ``None`` for an unknown segment.
    name : str
        Human-readable name; the segment itself when it is unknown.
    known : bool
        Whether the producer recognises the segment.
    """

    segment: str
    product: str | None
    country: str | None
    dataset_key: str | None
    name: str
    known: bool


@dataclass(frozen=True, slots=True)
class EntryMeta:
    """Describe a version without coupling consumers to producer sidecars.

    ``data_year``/``data_date`` say when the data were acquired or
    published, never when they were downloaded (``downloaded_at``).
    ``parent_request`` is a stable text key shared by the files of one
    producer request (e.g. both sides of a border). ``raw_sidecar`` keeps
    the producer's metadata unchanged for display only.

    ``provider``, ``written_by`` and ``producer_version`` are the fields of
    the sidecar core every Nogat tool writes (DEV-19.16): the organisation
    that publishes the data (``IMGW-PIB``, ``CHMI``), the package that wrote
    the file (the sidecar's ``producer``, e.g. ``kartograf``, ``imgwtools``;
    not the Archiwista producer id in ``producer``) and its version. A
    producer that does not know one leaves it ``None``.

    ``content_sha256`` and ``content_form`` identify the content of a file
    apart from its bytes, when the producer defines a canonical form of it
    (a file republished with other bytes but the same content): the digest
    of that form and its name. Both are ``None`` when the producer has none;
    they are never computed here.
    """

    producer: str
    store: str
    relative_path: Path
    dataset: str | None = None
    dataset_key: str | None = None
    product: str | None = None
    label: str | None = None
    label_source: str | None = None
    data_year: int | None = None
    data_date: date | None = None
    downloaded_at: datetime | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    license: str | None = None
    attribution: str | None = None
    source_files: tuple[str, ...] = ()
    raw_sidecar: dict[str, object] | None = None
    country: str | None = None
    unit: str | None = None
    survey_work_id: str | None = None
    campaign: str | None = None
    edition: str | None = None
    full_sheet: bool | None = None
    coverage: float | None = None
    parent_request: str | None = None
    horizontal_crs: str | None = None
    vertical_crs: str | None = None
    resolution: str | None = None
    nodata: float | None = None
    provider: str | None = None
    written_by: str | None = None
    producer_version: str | None = None
    content_sha256: str | None = None
    content_form: str | None = None


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """The record of a source that republished the content of a version.

    A source served other bytes (a new ``seen_at``, perhaps another ``etag``)
    with the content of a version the producer already has, so no new
    version was written (an ``observation`` entry). The fields are what the
    producer kept of that publication; ``None`` is what it did not record.
    """

    seen_at: datetime
    url: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class Station:
    """A station of a producer's station catalog (SPEC 4.8.1; IMGWTools IMGW-9).

    A station is ``provider`` and ``code``: the codes of two providers never
    meet (IMGW-PIB has nine digits, ČHMÚ WIGOS identifiers), and a code is
    text, never a number. ``point`` is ``(lon, lat)`` in WGS84 as the catalog
    gives it; without one, ``location_reason`` says why (``none``: no source
    has coordinates, ``zero``: the source said ``0,0``, ``outside_country``),
    and the station is kept (P13, A-ADR-022): a location is never guessed.
    ``hydrographic_code`` is the river's code on the provider's list (IMGW:
    Raba ``2138``; its tributaries' codes begin with it, P19) and
    ``river_order`` the station's place on that list. ``None`` is what the
    catalog does not say.
    """

    provider: str
    code: str
    kind: str | None = None
    name: str | None = None
    meteo_kind: str | None = None
    river: str | None = None
    hydrographic_code: str | None = None
    river_order: int | None = None
    point: tuple[float, float] | None = None
    location_reason: str | None = None
    location_source: str | None = None
    location_uncertainty_m: float | None = None
    active: bool | None = None
    established_year: int | None = None
    gauge_zero_m: float | None = None
    river_km: float | None = None
    elevation_m: float | None = None


@dataclass(frozen=True, slots=True)
class VariableCoverage:
    """Coverage of one variable of a station's series (SPEC 4.8.4; IMGW-8).

    ``key`` names it in the producer's series index: the variable (``Q``,
    ``Tmax``) and, for half-year characteristics, its ``period`` (``winter``,
    ``summer``, ``annual``; ``Q_max@winter``). ``first`` and ``last`` are the
    first and last unit with a value (``None``: no value at all), ``gaps`` the
    maximal closed ranges of units without a value between them, a unit given
    by a date in it. ``with_value`` counts the units with a value and
    ``accumulated`` those holding an accumulated sum of the days before them.
    """

    key: str
    variable: str
    unit: str
    period: str | None
    first: date | None
    last: date | None
    with_value: int
    accumulated: int
    gaps: tuple[DateRange, ...] = ()


@dataclass(frozen=True, slots=True)
class StationSeries:
    """A station's series in a version of a dataset's series.

    ``file`` is the station's series file relative to the store, with its
    ``sha256`` and ``rows``. ``periods`` are the station's own known periods
    (a dataset of per-station files, ČHMÚ); ``None`` when the periods of the
    version are the station's.
    """

    code: str
    file: str
    sha256: str
    rows: int
    variables: tuple[VariableCoverage, ...]
    periods: tuple[DateRange, ...] | None = None


@dataclass(frozen=True, slots=True)
class SeriesListing:
    """The index of a version of a dataset's series, without its series files.

    ``provider`` and ``kind`` (``hydro``, ``meteo``) are the dataset's;
    ``time_unit`` its unit and ``year_type`` the numbering of its archives;
    ``first_year`` the first year the source publishes (``None``: not
    declared). ``periods`` are the known periods of the version: the union of
    its inputs' periods (SPEC 4.8.4).
    """

    dataset: str
    provider: str
    kind: str | None
    time_unit: TimeUnit
    year_type: YearType
    first_year: int | None
    periods: tuple[DateRange, ...]
    stations: tuple[StationSeries, ...]


@dataclass(frozen=True, slots=True)
class SeriesValues:
    """A station's values in one unit of a series version (SPEC 4.8.3; IMGW-10).

    ``start`` is the first day of the unit (the day, the first day of the
    month or of the half-year period) and ``period`` the half-year period of
    a characteristic (``winter``, ``summer``, ``annual``; ``None`` for days
    and months). ``values`` holds each variable read: its value, or ``None``
    where the producer flags the unit missing, a gap and a unit that is not
    known alike (the gap lists of the series index tell them apart, SPEC
    4.8.4); a phenomenon that did not occur is ``0``. ``accumulated`` names
    the variables whose value is an accumulated sum of the days before it,
    and ``extremes`` the first and last time of each extreme of a half-year
    characteristic the producer dates, by variable (``None``: a bound it does
    not publish).
    """

    start: date
    period: str | None
    values: Mapping[str, float | None]
    accumulated: frozenset[str] = frozenset()
    extremes: Mapping[str, tuple[datetime | None, datetime | None]] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """Identify an indexed item by producer, store, and relative path.

    ``slot_path`` is the file's place independent of its version and
    ``version_path`` the version a link points to (a version's own path).
    ``slot_key`` is the producer's own name of the slot (the index keeps it with
    the slot), opaque to Archiwista; ``slot_name`` is what people call the
    slot when the last part of ``slot_path`` is not a name (e.g. a directory
    called ``versions``). ``skipped`` marks a version listed in
    ``ScanScope.known_versions`` whose metadata was not read; ``meta`` carries
    metadata read in the same pass. ``handle`` is the producer's own record of
    the entry: opaque to Archiwista and passed back to the same adapter
    unchanged.

    An ``observation`` is a record of the producer's publication history:
    the source published other bytes with the content of a version it
    already had. It belongs to a slot (``observation`` holds the record,
    ``version_path`` the version whose content it repeats) and is never a
    version, a link or a full sheet: it changes no version, no current
    version and no count.
    """

    producer: str
    store: str
    relative_path: Path
    kind: EntryKind
    segment: str | None = None
    slot_path: Path | None = None
    version_path: Path | None = None
    problem: str | None = None
    skipped: bool = False
    meta: EntryMeta | None = None
    slot_key: str | None = None
    slot_name: str | None = None
    observation: SourceObservation | None = None
    handle: object | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class Footprint:
    """Carry WGS84 geometry or explicitly explain missing location.

    ``native`` is the same outline in ``native_crs``, the CRS of the file
    or of the source that gave the outline.
    """

    location: LocationKind
    wgs84: GeoJSONGeometry | None = None
    native: GeoJSONGeometry | None = None
    source: str | None = None
    reason: str | None = None
    native_crs: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectPin:
    """Identify one exact project input version, including older versions.

    ``version_path`` is relative to ``store``.
    """

    store: str
    version_path: Path
    sha256: str | None = None
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectTask:
    """Describe an existing producer project task without running it.

    ``status`` is ``None`` until checked (``project_status``): ``ok``,
    ``not_downloaded``, ``missing`` or ``corrupt`` (the worst pinned file).
    """

    task_id: str
    command: str
    options: dict[str, object] = field(default_factory=dict)
    status: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    """Describe an existing producer project and its pinned inputs.

    ``status`` is ``None`` until checked; otherwise the worst task status.
    """

    producer: str
    store: str
    path: Path
    name: str
    tasks: tuple[ProjectTask, ...] = ()
    pins: tuple[ProjectPin, ...] = ()
    status: str | None = None
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class SheetGrid:
    """Report an optional grid capability or its unsupported state.

    In the order of ``sheets``: ``outlines`` holds the WGS84 polygon a map
    draws of each sheet, ``zones`` its zone (Kartograf: the PL-2000 zone 5-8,
    ``None`` in PL-1992) and ``extents`` the WGS84 envelope
    ``(min_lon, min_lat, max_lon, max_lat)`` of the whole sheet. A sheet that a
    zone boundary cuts is outlined inside its zone only, so the sheets of two
    zones never overlap; its extent stays the whole sheet's.
    """

    status: Literal["available", "unsupported"]
    sheets: tuple[str, ...] = ()
    outlines: tuple[GeoJSONGeometry, ...] = ()
    zones: tuple[int | None, ...] = ()
    extents: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class CommandChoice:
    """A value an option of a producer command allows, with what it means.

    Parameters
    ----------
    value : str or int
        The value in the JSON form of a call.
    meaning : str
        What it stands for, in the producer's words.
    """

    value: str | int
    meaning: str


@dataclass(frozen=True, slots=True)
class CommandOption:
    """One option of a producer command, as a call gives it (``CommandCall.options``).

    Parameters
    ----------
    name : str
        The key of the option in a call, ``snake_case`` (``vertical_crs``).
    type : {"string", "integer", "number", "boolean", "array", "object"}
        The JSON type of its value.
    required : bool
        A call without it is refused.
    description : str
        What it is, in the producer's words: in the language of the call when the
        producer has that language, else in English.
    choices : tuple[CommandChoice, ...]
        The values it allows; empty when it takes any.
    default : object
        The JSON value the producer uses when a call leaves it out; ``None`` for
        none.
    minimum, maximum : int or float or None
        Bounds of a number.
    items : {"string", "integer", "number", "boolean", "array", "object"} or None
        The type of the items of an ``array``.
    group : str or None
        The group of mutually exclusive options it belongs to (``area``: a sheet, a
        box or a geometry file); the description says whether one is required.
    path_role : {"input", "output"} or None
        Its value is a path the command reads (``input``) or writes (``output``).
        Archiwista accepts no such path from a request (SPEC 10.1).
    """

    name: str
    type: OptionType
    required: bool
    description: str
    choices: tuple[CommandChoice, ...] = ()
    default: object = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    items: OptionType | None = None
    group: str | None = None
    path_role: PathRole | None = None


@dataclass(frozen=True, slots=True)
class CommandInfo:
    """One command of a producer's catalog (SPEC 12.2 KB-1, IMGW-11).

    Parameters
    ----------
    producer : str
        Producer id.
    command : str
        The producer's name of the command, ``<group> <verb>`` (``elevation
        download``).
    group : str
        Its group (``elevation``).
    summary : str
        One sentence on what it does: in the language of the call when the
        producer has that language, else in English.
    description : str
        When to use it, when not and its main limit; in the same language.
    options : tuple[CommandOption, ...]
        The options of a call, in the producer's order. The store root and the
        flags of a run are none of them: Archiwista names the store itself
        (``store``), and a command line gives the flags beside the options
        (``CommandCall.run``).
    read_only : bool
        A run changes nothing outside the process: no store, project or cache.
    writes : {"none", "add", "replace", "delete"}
        What a run does to files.
    network : bool
        A run uses the network.
    check : bool
        The producer plans a run without effects (its ``check_command``).
    store : bool
        The command works on a store, so every call names the store root;
        Archiwista takes it from the configured store, never from a request
        (Decision 1 of the plan of 2026-10-25).
    examples : tuple[str, ...]
        Complete command lines of the producer, as ``parse`` reads them.
    """

    producer: str
    command: str
    group: str
    summary: str
    description: str
    options: tuple[CommandOption, ...]
    read_only: bool
    writes: CommandWrites
    network: bool
    check: bool
    store: bool
    examples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandCall:
    """A producer command with the options of one call (SPEC 12.2 KB-2).

    Parameters
    ----------
    producer : str
        Producer id.
    command : str
        The producer's name of the command (``CommandInfo.command``).
    options : Mapping[str, object]
        The options in the JSON form of the producer's catalog
        (``CommandInfo.options``): Kartograf's ``bbox`` as four numbers with
        ``bbox_crs``, a list as a list.
    run : Mapping[str, object]
        What a command line gives beside the options: the store root and the
        flags of a run, by the names of the data-output convention where it has
        them (DEV §19: ``root``, ``output_dir``, ``check``, ``force``,
        ``upgrade``, ``plan``) and by the producer's otherwise (``workers``,
        ``details``); a text, a number or ``True``.
    """

    producer: str
    command: str
    options: Mapping[str, object] = field(default_factory=dict)
    run: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AvailabilityArea:
    """The part of a checked area in one country, as the producer measured it.

    Parameters
    ----------
    country : str
        Country code (``PL``, ``CZ``).
    crs : str
        CRS of ``bounds`` and of the measures.
    bounds : tuple[float, float, float, float]
        Envelope of the part in ``crs``.
    area_m2 : float
        Area of the part.
    land_m2 : float
        Its land: what every combination is measured against (SPEC 6.4).
    """

    country: str
    crs: str
    bounds: tuple[float, float, float, float]
    area_m2: float
    land_m2: float


@dataclass(frozen=True, slots=True)
class AvailabilitySheet:
    """A record of the source a download of a combination takes (SPEC 12.4 KD-1).

    Parameters
    ----------
    sheet : str
        Sheet or tile code.
    campaign : str or None
        The survey work it comes from.
    full_sheet : bool or None
        Whether the record fills its sheet; ``None`` when the source does not say.
    acquisition_date, published : str or None
        Date of the survey and of the publication (ISO dates).
    """

    sheet: str
    campaign: str | None
    full_sheet: bool | None
    acquisition_date: str | None = None
    published: str | None = None


@dataclass(frozen=True, slots=True)
class AvailabilityCampaign:
    """One campaign of a combination on its own (SPEC 12.4 KD-1).

    Parameters
    ----------
    campaign : str
        The survey work.
    complete : bool
        Its full records alone cover the land of the area.
    full_m2 : float
        The land in their frames.
    """

    campaign: str
    complete: bool
    full_m2: float


@dataclass(frozen=True, slots=True)
class AvailabilityCombination:
    """One downloadable combination of an area: a year, a variant and a format.

    Parameters
    ----------
    country : str
        Country code of the area part it covers (``AvailabilityArea.country``).
    product : str
        Product id (``nmt``).
    source : str
        The producer's dataset.
    year : int or None
        Year of the data; ``None`` where the source publishes none (CZ).
    horizontal : str
        Sheet system or horizontal CRS (``PL-1992``).
    resolution : str or None
        Resolution label (``1m``); ``None`` for point clouds.
    vertical_crs : str
        Height system (``EVRF2007``).
    format : str
        File format (``ASC``).
    campaigns : tuple[str, ...]
        Every survey work among its records, complete or not.
    complete : bool
        The land of the area lies entirely in its full sheets.
    sheets_full, sheets_partial, sheets_missing : tuple[str, ...]
        Sheets with a full record, with partial records only, and without a file.
    uncovered_m2 : float
        Land outside every sheet of the combination.
    full_m2 : float
        Land in the frames of its full records (SPEC 12.4 KD-2).
    size_bytes : int or None
        Size of its files when the source tells it; ``None`` otherwise.
    published : tuple[str, str] or None
        First and last publication date of its files.
    sheet_records : tuple[AvailabilitySheet, ...]
        The records a download takes, by sheet (KD-1).
    campaign_coverage : tuple[AvailabilityCampaign, ...]
        Each campaign of ``campaigns`` on its own (KD-1).
    commands : tuple[str, ...]
        The producer's command lines that download it, without the program
        name and the store (Kartograf: ``download_hint``); the adapter's
        ``parse`` reads each into a call. Empty when the producer names none.
    """

    country: str
    product: str
    source: str
    year: int | None
    horizontal: str
    resolution: str | None
    vertical_crs: str
    format: str
    campaigns: tuple[str, ...]
    complete: bool
    sheets_full: tuple[str, ...]
    sheets_partial: tuple[str, ...]
    sheets_missing: tuple[str, ...]
    uncovered_m2: float
    full_m2: float
    size_bytes: int | None = None
    published: tuple[str, str] | None = None
    sheet_records: tuple[AvailabilitySheet, ...] = ()
    campaign_coverage: tuple[AvailabilityCampaign, ...] = ()
    commands: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AvailabilityFailure:
    """A part of the request the producer could not check (``ok`` is ``False``).

    Parameters
    ----------
    part : str
        What failed, e.g. a country code.
    detail : str
        The producer's text.
    kind : str
        The producer's kind of failure (``country``, ``download``).
    """

    part: str
    detail: str
    kind: str


@dataclass(frozen=True, slots=True)
class AvailabilityNotice:
    """Something the producer said while it checked: ``level``, ``code``, text.

    Parameters
    ----------
    level : {"info", "warning"}
        How much it matters.
    code : str
        The producer's stable code (``index_unsupported``).
    message : str
        The producer's text, in the language of the call when the producer has it.
    """

    level: Literal["info", "warning"]
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class AvailabilityReport:
    """What the source has for an area and a product (SPEC 6.3, 6.4).

    The producer's report (Kartograf: ``kartograf-availability/1``) without its
    classes, so the index and the services read every producer's report alike.

    Parameters
    ----------
    producer : str
        Producer id.
    schema : str
        Schema of the producer's own report.
    checked_at : datetime
        When the source was asked (UTC).
    request : Mapping[str, object]
        The request as the producer read it (product, country, area, years).
    areas : tuple[AvailabilityArea, ...]
        The parts of the area, one per country.
    combinations : tuple[AvailabilityCombination, ...]
        What can be downloaded, in the producer's order.
    failed : tuple[AvailabilityFailure, ...]
        Parts of the request that could not be checked.
    notices : tuple[AvailabilityNotice, ...]
        What the producer said meanwhile.
    ok : bool
        Every part of the request was checked.
    """

    producer: str
    schema: str
    checked_at: datetime
    request: Mapping[str, object]
    areas: tuple[AvailabilityArea, ...]
    combinations: tuple[AvailabilityCombination, ...]
    failed: tuple[AvailabilityFailure, ...] = ()
    notices: tuple[AvailabilityNotice, ...] = ()
    ok: bool = True

    def to_json(self) -> dict[str, object]:
        """Return the report as a JSON object (what the index keeps)."""
        data = asdict(self)
        data["checked_at"] = self.checked_at.isoformat()
        data["request"] = dict(self.request)
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "AvailabilityReport":
        """Read a report back from ``to_json``.

        Raises
        ------
        KeyError, TypeError, ValueError
            Not a report of ``to_json``.
        """
        return cls(
            producer=str(data["producer"]),
            schema=str(data["schema"]),
            checked_at=datetime.fromisoformat(str(data["checked_at"])),
            request=dict(data["request"]),
            areas=tuple(
                AvailabilityArea(
                    country=str(area["country"]),
                    crs=str(area["crs"]),
                    bounds=_bounds(area["bounds"]),
                    area_m2=float(area["area_m2"]),
                    land_m2=float(area["land_m2"]),
                )
                for area in data["areas"]
            ),
            combinations=tuple(_combination(item) for item in data["combinations"]),
            failed=tuple(AvailabilityFailure(**item) for item in data["failed"]),
            notices=tuple(AvailabilityNotice(**item) for item in data["notices"]),
            ok=bool(data["ok"]),
        )


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """One position of a plan: a file of a run, local and at the source (SPEC 6.5).

    Parameters
    ----------
    path : str
        Its place below the store root, ``/``-separated
        (``nmt/pl_1992_1m_evrf2007/N-34-130-D-d-1-1.asc``): the subject of the
        producer's own status lines.
    unit : str
        The producer's unit of the position (a sheet, a tile, a country).
    status : {"current", "newer", "missing", "unverifiable", "check_failed"}
        ``current``: the store holds the newest version; ``newer``: the source
        has a newer one; ``missing``: the store holds none; ``unverifiable``:
        the source gives no cheap sign of its version; ``check_failed``: the
        source could not be asked (``error``).
    local_label, available_label : str or None
        The label of the version the store holds and of the one at the source.
    size_bytes : int or None
        Size of the file at the source when the producer tells it; ``None``
        when it does not, never 0 for an unknown size.
    error : str or None
        The producer's text of a failed check or of a refused write.
    conflict : str or None
        Why a run would refuse to write the position, the producer's reason
        (``nested_store``, ``not_empty``); ``None`` for one a run may write.
    """

    path: str
    unit: str
    status: PlanStatus
    local_label: str | None = None
    available_label: str | None = None
    size_bytes: int | None = None
    error: str | None = None
    conflict: str | None = None


@dataclass(frozen=True, slots=True)
class ActionPlan:
    """What a run of a command would do in a store, checked without effects.

    The producer's plan (Kartograf: ``kartograf-plan/1`` of ``check_command``)
    without its classes, so the jobs, the index and the interfaces read every
    producer's plan alike (SPEC 6.5, 12.2 KB-5).

    Parameters
    ----------
    producer : str
        Producer id.
    command : str
        The producer's name of the command planned (``CommandInfo.command``).
    schema : str
        Schema of the producer's own plan.
    root : str
        The store root the plan is of, as the producer resolved it.
    checked_at : datetime
        When the source was asked.
    entries : tuple[PlanEntry, ...]
        Its positions, in the producer's order.
    notices : tuple[AvailabilityNotice, ...]
        What the producer said meanwhile.
    document : Mapping[str, object]
        The producer's plan itself, as JSON: a run of the plan takes it back
        (Kartograf's ``update="upgrade", plan=…``).
    """

    producer: str
    command: str
    schema: str
    root: str
    checked_at: datetime
    entries: tuple[PlanEntry, ...]
    notices: tuple[AvailabilityNotice, ...] = ()
    document: Mapping[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Every position was checked: none is ``check_failed``."""
        return all(entry.status != "check_failed" for entry in self.entries)

    @property
    def todo(self) -> tuple[PlanEntry, ...]:
        """The positions a run of the plan downloads (``PLAN_TODO``)."""
        return tuple(entry for entry in self.entries if entry.status in PLAN_TODO)

    @property
    def size_bytes(self) -> int | None:
        """Bytes a run downloads as far as the producer tells their sizes.

        The sum of the known sizes of ``todo``; ``None`` when the plan has
        positions to download and the producer tells none of their sizes, so
        an unknown size is never 0. ``size_complete`` says whether the sum is
        the whole.
        """
        known = [
            entry.size_bytes for entry in self.todo if entry.size_bytes is not None
        ]
        if self.todo and not known:
            return None
        return sum(known)

    @property
    def size_complete(self) -> bool:
        """Every position a run downloads has its size (``size_bytes`` is whole)."""
        return all(entry.size_bytes is not None for entry in self.todo)

    def counts(self) -> dict[PlanStatus, int]:
        """Return the number of positions of each status, every status named."""
        counted = dict.fromkeys(PLAN_STATUSES, 0)
        for entry in self.entries:
            counted[entry.status] += 1
        return counted

    def to_json(self) -> dict[str, object]:
        """Return the plan as a JSON object (what the index keeps)."""
        data = asdict(self)
        data["checked_at"] = self.checked_at.isoformat()
        data["document"] = dict(self.document)
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ActionPlan":
        """Read a plan back from ``to_json``.

        Raises
        ------
        KeyError, TypeError, ValueError
            Not a plan of ``to_json``.
        """
        return cls(
            producer=str(data["producer"]),
            command=str(data["command"]),
            schema=str(data["schema"]),
            root=str(data["root"]),
            checked_at=datetime.fromisoformat(str(data["checked_at"])),
            entries=tuple(PlanEntry(**entry) for entry in data["entries"]),
            notices=tuple(AvailabilityNotice(**item) for item in data["notices"]),
            document=dict(data["document"]),
        )


@dataclass(frozen=True, slots=True)
class ActionProgress:
    """How far a run of a command is (Kartograf: ``DownloadProgress``).

    Parameters
    ----------
    current, total : int
        Units of the run done so far, of the units it knows of; 0 of 0 before
        the producer counts them. An event about a part of a unit (a flight
        of a sheet) keeps the counts of the units.
    unit : str or None
        The producer's unit the event is about (a sheet, a station);
        ``None`` for an event about no one unit.
    status : str
        The producer's word for what happens (``downloading``, ``completed``).
    message : str
        The producer's text; empty when it says nothing more.
    """

    current: int
    total: int
    unit: str | None
    status: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class ActionFile:
    """One file a run left in the store (``files[]`` of DEV §19 Z6).

    Parameters
    ----------
    path : str
        Its standard path below the store root, ``/``-separated: where a
        reader finds the current version.
    unit : str
        The producer's unit of the request the file belongs to.
    status : {"new", "unchanged", "relabeled"}
        ``new``: a new version; ``unchanged``: a version the store had (used
        without a transfer, or a transfer of the same content);
        ``relabeled``: the content of a version the store had, under a new
        label.
    size_bytes : int
        Its size.
    sha256 : str
        SHA-256 of its bytes, lower-case hex, computed while it streamed.
    label : str or None
        The label of its version.
    version_path : str or None
        The immutable file of its version below the store root,
        ``/``-separated.
    """

    path: str
    unit: str
    status: FileStatus
    size_bytes: int
    sha256: str
    label: str | None = None
    version_path: str | None = None


@dataclass(frozen=True, slots=True)
class ActionItem:
    """The outcome of one unit of a run (``items[]``, AGI-4.2).

    Parameters
    ----------
    id : str
        The unit: a sheet, a station, a path below the store root.
    status : {"ok", "failed"}
        Whether the unit succeeded.
    code : str or None
        Registry code of a failure (``source_unavailable``, ``no_data``,
        ``conflict``).
    reason : str or None
        Its finer cause when the code does not say enough (``stale_plan``:
        the source changed the position since the plan).
    message : str or None
        The producer's text of the failure.
    """

    id: str
    status: ItemStatus
    code: str | None = None
    reason: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    """What a run of a command did in a store (SPEC 12.2 KB-5).

    The producer's result (Kartograf: the envelope ``kartograf-result/1`` of
    ``run_command`` with ``kartograf-download/1``) without its classes, so
    the jobs read every producer's run alike.

    Parameters
    ----------
    producer : str
        Producer id.
    command : str
        The producer's name of the command run (``CommandInfo.command``).
    root : str
        The store root the run wrote to.
    status : {"ok", "partial", "failed"}
        ``ok``: every unit succeeded; ``partial``: some failed; ``failed``:
        none succeeded.
    files : tuple[ActionFile, ...]
        The files it left in the store, in the producer's order.
    items : tuple[ActionItem, ...]
        The outcome of each unit; empty for a command without units.
    notices : tuple[AvailabilityNotice, ...]
        What the producer said meanwhile.
    schema : str or None
        Schema of the producer's own result (``kartograf-download/1``);
        ``None`` when the command gave none.
    """

    producer: str
    command: str
    root: str
    status: RunStatus
    files: tuple[ActionFile, ...] = ()
    items: tuple[ActionItem, ...] = ()
    notices: tuple[AvailabilityNotice, ...] = ()
    schema: str | None = None

    @property
    def failed(self) -> tuple[ActionItem, ...]:
        """The units that failed, in the producer's order."""
        return tuple(item for item in self.items if item.status == "failed")


@dataclass(frozen=True, slots=True)
class PinnedVersion:
    """One version a task of a project pinned (a pin of its manifest).

    Parameters
    ----------
    path : str
        The file's standard path below the store root, ``/``-separated: which
        file.
    version_path : str
        The pinned version's file below the store root, ``/``-separated:
        which bytes.
    unit : str
        The producer's unit of the file (a sheet, a tile, a TERYT).
    label : str
        The label of the version.
    sha256 : str
        SHA-256 of its bytes, lower-case hex.
    size_bytes : int
        Its size.
    """

    path: str
    version_path: str
    unit: str
    label: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ProjectTaskRun:
    """What a download of a project did with one of its tasks.

    Parameters
    ----------
    name : str
        The task's name in the manifest.
    outcome : {"pinned", "unchanged", "restored", "updated", "failed"}
        ``pinned``: downloaded and pinned for the first time; ``unchanged``:
        its pins kept, nothing to do; ``restored``: missing pinned versions
        back with the same SHA-256; ``updated``: pinned anew (a repin);
        ``failed``: its pins as they were (``errors``).
    pinned, unpinned : tuple[PinnedVersion, ...]
        The new pins, and the pins they replaced or dropped.
    errors : tuple[str, ...]
        The producer's texts of a failure.
    code, reason : str or None
        Registry code of a failure and its finer cause where the code does not
        say enough; ``None`` otherwise.
    """

    name: str
    outcome: TaskOutcome
    pinned: tuple[PinnedVersion, ...] = ()
    unpinned: tuple[PinnedVersion, ...] = ()
    errors: tuple[str, ...] = ()
    code: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectRun:
    """What a download of a project's tasks did (SPEC 4.7, 5.6).

    The producer's report (Kartograf: ``kartograf-project-report/1`` of
    ``download_project``) without its classes, so the jobs read every
    producer's project alike.

    Parameters
    ----------
    producer : str
        Producer id.
    root : str
        The store the manifest names, as the producer resolved it.
    tasks : tuple[ProjectTaskRun, ...]
        One result per task of the run, in the manifest's order.
    notices : tuple[AvailabilityNotice, ...]
        What the producer said meanwhile (its texts name the task).
    """

    producer: str
    root: str
    tasks: tuple[ProjectTaskRun, ...]
    notices: tuple[AvailabilityNotice, ...] = ()

    @property
    def ok(self) -> bool:
        """No task failed."""
        return all(task.outcome != "failed" for task in self.tasks)

    @property
    def failed(self) -> tuple[ProjectTaskRun, ...]:
        """The tasks that failed, in the manifest's order."""
        return tuple(task for task in self.tasks if task.outcome == "failed")

    def counts(self) -> dict[TaskOutcome, int]:
        """Return the number of tasks of each outcome, every outcome named."""
        counted = dict.fromkeys(TASK_OUTCOMES, 0)
        for task in self.tasks:
            counted[task.outcome] += 1
        return counted


@dataclass(frozen=True, slots=True)
class ProjectFileState:
    """The state of one pinned file of a project, or of a position without a pin.

    Parameters
    ----------
    task : str
        The task the file belongs to.
    unit : str
        The producer's unit of the file; empty for ``conflict``.
    path : str
        The file's standard path below the store root, ``/``-separated; empty
        for ``conflict``.
    status : ProjectFileStatus
        A verification: ``ok``, ``missing`` or ``corrupt``. A check against the
        source: ``current`` (the pin is the newest), ``newer`` (the source has
        a newer version), ``added`` (a position the source has and the task
        did not pin), ``removed`` (a pin the source no longer has),
        ``missing`` (a pin the store lost), ``unverifiable`` (the source gives
        no cheap sign of its version), ``check_failed`` (the source could not
        be asked) or ``conflict`` (a write to the store would be refused, so
        nothing of the task was checked).
    pinned_label, available_label : str or None
        The label of the pinned version and of the one at the source.
    detail : str or None
        The producer's text of the reason with its remedy; ``None`` when
        there is nothing to do.
    """

    task: str
    unit: str
    path: str
    status: ProjectFileStatus
    pinned_label: str | None = None
    available_label: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectCheck:
    """A check of a project's pins: in its store, or against the source.

    The producer's check (Kartograf: ``kartograf-project-check/1`` of
    ``verify_project`` and ``check_project``) without its classes.

    Parameters
    ----------
    producer : str
        Producer id.
    root : str
        The store the manifest names, as the producer resolved it.
    files : tuple[ProjectFileState, ...]
        The state of each file checked, in the producer's order.
    not_downloaded : tuple[str, ...]
        The tasks checked that have no pins yet.
    notices : tuple[AvailabilityNotice, ...]
        What the producer said meanwhile.
    ok : bool
        A verification: every task checked is pinned and every file ``ok``;
        a check against the source: no file is ``check_failed``.
    """

    producer: str
    root: str
    files: tuple[ProjectFileState, ...]
    not_downloaded: tuple[str, ...] = ()
    notices: tuple[AvailabilityNotice, ...] = ()
    ok: bool = True

    def counts(self) -> dict[ProjectFileStatus, int]:
        """Return the number of files of each state, every state named."""
        counted = dict.fromkeys(PROJECT_FILE_STATUSES, 0)
        for item in self.files:
            counted[item.status] += 1
        return counted


def _combination(data: Mapping[str, Any]) -> AvailabilityCombination:
    """Read one combination of ``AvailabilityReport.to_json``.

    A report kept before combinations had ``commands`` reads with none.
    """
    published = data["published"]
    return AvailabilityCombination(
        **{
            **data,
            "campaigns": tuple(data["campaigns"]),
            "sheets_full": tuple(data["sheets_full"]),
            "sheets_partial": tuple(data["sheets_partial"]),
            "sheets_missing": tuple(data["sheets_missing"]),
            "published": None if published is None else tuple(published),
            "sheet_records": tuple(
                AvailabilitySheet(**item) for item in data["sheet_records"]
            ),
            "campaign_coverage": tuple(
                AvailabilityCampaign(**item) for item in data["campaign_coverage"]
            ),
            "commands": tuple(str(line) for line in data.get("commands", ())),
        }
    )


def _bounds(value: object) -> tuple[float, float, float, float]:
    """Read four numbers of an envelope."""
    if not isinstance(value, list | tuple) or len(value) != 4:
        raise ValueError(f"an envelope has four numbers, not {value!r}")
    min_x, min_y, max_x, max_y = (float(number) for number in value)
    return (min_x, min_y, max_x, max_y)
