"""Producer-neutral values exchanged between adapters and the index."""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

type SourceStatus = Literal["available", "not_installed", "incompatible", "error"]
type EntryKind = Literal["version", "link", "full_sheet", "problem"]
type LocationKind = Literal["footprint", "country", "none"]
type GeoJSONGeometry = dict[str, object]


@dataclass(frozen=True, slots=True)
class ScanScope:
    """Restrict a scan to a segment and optionally its unit identifiers."""

    segment: str | None = None
    units: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class SourceState:
    """Report a producer's availability and supported version information."""

    producer: str
    status: SourceStatus
    store: str | None = None
    package_version: str | None = None
    supported_versions: str | None = None
    schemas: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """Identify an indexed item by producer, store, and relative path."""

    producer: str
    store: str
    relative_path: Path
    kind: EntryKind
    segment: str | None = None
    slot_path: Path | None = None
    version_path: Path | None = None
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class EntryMeta:
    """Describe a version without coupling consumers to producer sidecars."""

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


@dataclass(frozen=True, slots=True)
class Footprint:
    """Carry WGS84 geometry or explicitly explain missing location."""

    location: LocationKind
    wgs84: GeoJSONGeometry | None = None
    native: GeoJSONGeometry | None = None
    source: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectPin:
    """Identify one exact project input version, including older versions."""

    store: str
    version_path: Path
    sha256: str | None = None
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectTask:
    """Describe an existing producer project task without running it."""

    task_id: str
    command: str
    options: dict[str, object] = field(default_factory=dict)
    status: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    """Describe an existing producer project and its pinned inputs."""

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
    """Report an optional grid capability or its unsupported state."""

    status: Literal["available", "unsupported"]
    sheets: tuple[str, ...] = ()
