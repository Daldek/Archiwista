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
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

type SourceStatus = Literal["available", "not_installed", "incompatible", "error"]
type EntryKind = Literal["version", "link", "full_sheet", "problem", "observation"]
type LocationKind = Literal["footprint", "country", "none"]
type GeoJSONGeometry = dict[str, object]
type DefaultRootSource = Literal["default", "env", "dotenv", "file"]
type OptionType = Literal["string", "integer", "number", "boolean", "array", "object"]
type PathRole = Literal["input", "output"]
type CommandWrites = Literal["none", "add", "replace", "delete"]


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

    ``outlines`` holds the WGS84 polygon of each sheet, in the order of
    ``sheets``.
    """

    status: Literal["available", "unsupported"]
    sheets: tuple[str, ...] = ()
    outlines: tuple[GeoJSONGeometry, ...] = ()


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
