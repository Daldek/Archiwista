"""Hand-built source entries for index tests, shaped like Kartograf's.

The index knows producers only through ``archiwista.sources``, so its unit
tests build entries directly: a store directory that never touches the disk,
versions under ``<segment>/versions/…``, links at the standard path and in
``full_sheet/``, problems, and box footprints in WGS84. Coordinate
operations come from pyproj (``PyprojOperation``), not from a producer.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import pyproj

from archiwista.index import CurrentVersionLookup, IndexWriter, PassSummary
from archiwista.sources import (
    EntryKind,
    EntryMeta,
    FloatArray,
    Footprint,
    SourceEntry,
    SourceSegment,
)

PRODUCER = "kartograf"
STORE = "zespol"
ROOT = "/mnt/nas/kartograf/data"
NMT = "nmt/pl_1992_1m_evrf2007"
ORTO = "orto/pl_1992"
BDOT = "landcover/pl_bdot10k_gpkg"
PRG = "boundaries/pl_prg_shp"
CZ_NMT = "nmt/cz_dmr5g_bpv"
SEGMENTS = {
    NMT: SourceSegment(
        NMT, "nmt", "PL", "pl.gugik.nmt_1m", "Numeryczny Model Terenu", True
    ),
    ORTO: SourceSegment(ORTO, "orto", "PL", "pl.gugik.orto", "Ortofotomapa", True),
    BDOT: SourceSegment(
        BDOT, "bdot10k", "PL", "pl.gugik.bdot10k", "BDOT10k · GPKG", True
    ),
    PRG: SourceSegment(PRG, "admin", "PL", "pl.gugik.prg", "PRG — granice", True),
    CZ_NMT: SourceSegment(CZ_NMT, "nmt", "CZ", "cz.cuzk.dmr5g", "DMR 5G", True),
}
DOWNLOADED = datetime(2025, 7, 1, 12, 0, tzinfo=UTC)


def slot_path(segment: str, unit: str, suffix: str = ".asc") -> str:
    """Return the standard path of a sheet slot (``<segment>/<unit>/<file>``)."""
    return f"{segment}/{unit}/{unit}{suffix}"


def version_path(slot: str, label: str, sha256: str) -> str:
    """Return a version path of ``slot`` (``…/versions/…/<label>_<sha8>/``)."""
    pure = PurePosixPath(slot)
    segment = "/".join(pure.parts[:2])
    hierarchy = "/".join(pure.parts[2:-1])
    return f"{segment}/versions/{hierarchy}/{label}_{sha256[:8]}/{pure.name}"


def sha(seed: int) -> str:
    """Return a distinct 64-digit SHA-256-like hex value."""
    return f"{seed:08x}" * 8


def meta(path: str, **fields: object) -> EntryMeta:
    """Return metadata of ``path``: sensible defaults overridden by ``fields``."""
    values: dict[str, object] = {
        "dataset": "pl.gugik.nmt_1m",
        "dataset_key": "pl.gugik.nmt_1m",
        "product": "nmt",
        "country": "PL",
        "downloaded_at": DOWNLOADED,
        "size_bytes": 1000,
        "license": "cc-by-4.0",
        "attribution": "GUGiK",
        "raw_sidecar": {"schema": "kartograf-meta/1", "path": path},
        "horizontal_crs": "EPSG:2180",
    }
    values.update(fields)
    return EntryMeta(
        producer=PRODUCER,
        store=ROOT,
        relative_path=Path(path),
        **values,  # type: ignore[arg-type]
    )


def version(
    slot: str,
    label: str,
    seed: int,
    *,
    unit: str | None = None,
    skipped: bool = False,
    **fields: object,
) -> SourceEntry:
    """Return a version entry of ``slot`` with metadata (``skipped``: without).

    The data year and date come from a label starting with a date, unless
    ``fields`` sets them.
    """
    digest = str(fields.pop("sha256", sha(seed)))
    path = version_path(slot, label, digest)
    values: dict[str, object] = {
        "label": label,
        "label_source": "campaign",
        "sha256": digest,
        "unit": unit if unit is not None else PurePosixPath(slot).stem,
        "data_year": _year(label),
        "data_date": _date(label),
    }
    values.update(fields)
    return SourceEntry(
        producer=PRODUCER,
        store=ROOT,
        relative_path=Path(path),
        kind="version",
        segment="/".join(PurePosixPath(slot).parts[:2]),
        slot_path=Path(slot),
        version_path=Path(path),
        skipped=skipped,
        meta=None if skipped else meta(path, **values),
    )


def skipped(entry: SourceEntry) -> SourceEntry:
    """Return the same version as a known one: listed, metadata not read."""
    return replace(entry, skipped=True, meta=None)


def link(
    slot: str,
    target: SourceEntry | None,
    *,
    kind: EntryKind = "link",
    **fields: object,
) -> SourceEntry:
    """Return a standard (``link``) or ``full_sheet`` link naming ``target``.

    Without ``target`` (a plain file from before ``versions/``) the link's
    own metadata comes from ``fields``.
    """
    pure = PurePosixPath(slot)
    segment = "/".join(pure.parts[:2])
    path = slot
    if kind == "full_sheet":
        path = f"{segment}/full_sheet/{'/'.join(pure.parts[2:])}"
    info = None
    if target is not None and target.meta is not None:
        info = replace(target.meta, relative_path=Path(path))
    elif fields:
        info = meta(path, **fields)
    return SourceEntry(
        producer=PRODUCER,
        store=ROOT,
        relative_path=Path(path),
        kind=kind,
        segment=segment,
        slot_path=Path(slot),
        version_path=None if target is None else target.version_path,
        meta=info,
    )


def problem(path: str, code: str, *, segment: str, slot: str | None) -> SourceEntry:
    """Return a problem the producer found (``missing_sidecar``…)."""
    return SourceEntry(
        producer=PRODUCER,
        store=ROOT,
        relative_path=Path(path),
        kind="problem",
        segment=segment,
        slot_path=None if slot is None else Path(slot),
        problem=code,
    )


def box(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    *,
    source: str = "sheet",
    native: dict[str, object] | None = None,
    native_crs: str | None = None,
) -> Footprint:
    """Return a box footprint in WGS84, optionally with a native outline."""
    return Footprint(
        location="footprint",
        wgs84=polygon(
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
        ),
        native=native,
        source=source,
        native_crs=native_crs,
    )


def polygon(*corners: tuple[float, float]) -> dict[str, object]:
    """Return a closed GeoJSON polygon through ``corners``."""
    ring = [list(corner) for corner in (*corners, corners[0])]
    return {"type": "Polygon", "coordinates": [ring]}


class PyprojOperation:
    """pyproj's operation between two CRSs, a ``CoordinateTransformer``.

    Coordinates in x (east), y (north) order, as the producers' operations.
    """

    def __init__(self, source: str, target: str) -> None:
        self._transformer = pyproj.Transformer.from_crs(source, target, always_xy=True)
        self.description = str(self._transformer.description)
        self.accuracy_m = float(self._transformer.accuracy or 0.0)

    def transform(
        self, xs: FloatArray, ys: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Transform coordinates."""
        x, y = self._transformer.transform(xs, ys)
        return x, y

    def gdal_operation(self) -> str:
        """Return the operation as a PROJ pipeline."""
        return str(self._transformer.definition)


def write_pass(
    writer: IndexWriter,
    entries: Sequence[SourceEntry],
    *,
    footprints: dict[str, Footprint] | None = None,
    full: bool = False,
    segment: str | None = None,
    slots: Iterable[str] | None = None,
    store: str = STORE,
    segments: Iterable[SourceSegment] | None = None,
    current: CurrentVersionLookup | None = None,
) -> PassSummary:
    """Run one complete pass: segments, entries, footprints, finish.

    ``footprints`` maps a version path to its location; versions without
    one get ``none`` (``no_source``) when the writer asks for them.
    ``current`` is the producer's answer for the current version of a slot
    with a key, as ``finish_pass`` takes it.
    """
    described = list(SEGMENTS.values()) if segments is None else list(segments)
    writer.write_segments(store, PRODUCER, described)
    writer.begin_pass(
        store,
        PRODUCER,
        segment=segment,
        slots=None if slots is None else frozenset(slots),
        full=full,
    )
    result = writer.write_entries(entries)
    located = footprints or {}
    writer.write_footprints(
        store,
        [
            (
                entry,
                located.get(
                    entry.relative_path.as_posix(),
                    Footprint(location="none", reason="no_source"),
                ),
            )
            for entry in result.needs_footprint
        ],
    )
    return writer.finish_pass(current=current)


def _year(label: str) -> int | None:
    head = label[:4]
    return int(head) if head.isdigit() else None


def _date(label: str) -> date | None:
    try:
        return date.fromisoformat(label[:10])
    except ValueError:
        return None
