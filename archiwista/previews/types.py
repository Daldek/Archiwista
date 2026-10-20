"""Types of the previews: sources, probes, reasons, styles (plan v0.2, decision 3).

A ``PreviewSource`` is what a render process may read: the resolved paths of
one file (the main one first, then the rest of its file set) with what the
index knows about it. ``content_key`` names the content, not the file: the
``sha256`` of a store version, a path key for a version without one, the
content identity of an own-data file (decision 8), so the same bytes in two
versions, two stores, or a snapshot and its working file share previews.

A ``PreviewProbe`` is what a renderer recognised in a file: the ``info.json``
of its preview cache object. It never names a file or a path (no ``name`` or
``files`` of a GDAL dataset): two projects with the same bytes share it.

Only the standard library and the format table are imported here, so the
server uses these types without loading GDAL.
"""

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, Protocol, cast, get_args

from archiwista.formats import FORMATS, FileFormat, FormatKind, file_format
from archiwista.owndata.content import CONTENT_METHODS, ContentMethod

type PreviewKind = FormatKind
type PreviewState = Literal["ready", "needs_build", "building", "unavailable", "failed"]
type PreviewReason = Literal[
    "no_georeference",
    "no_crs",
    "auxiliary_file",
    "archive_members_only",
    "document_no_preview",
    "unsupported_format",
    "too_large",
    "missing_file",
    "store_unavailable",
    "transform_unavailable",
    "unreadable",
    "timeout",
    "memory_limit",
    "changed_since_scan",
]
type StyleName = Literal[
    "hillshade", "hypsometry", "rgb", "gray", "classes", "features", "elevation"
]
# Renderers with their own version in the preview cache (decision 3): a fix
# of one never invalidates the previews of another.
type RendererName = Literal[
    "raster", "vector", "points", "archive", "document", "composite"
]
type BBox = tuple[float, float, float, float]
type JsonObject = dict[str, Any]

PREVIEW_KINDS: tuple[PreviewKind, ...] = get_args(FormatKind.__value__)
PREVIEW_STATES: tuple[PreviewState, ...] = get_args(PreviewState.__value__)
PREVIEW_REASONS: tuple[PreviewReason, ...] = get_args(PreviewReason.__value__)
STYLE_NAMES: tuple[StyleName, ...] = get_args(StyleName.__value__)
RENDERER_NAMES: tuple[RendererName, ...] = get_args(RendererName.__value__)
# Reasons that depend on the load or the moment (a busy computer, a share
# gone, a file edited since the scan): never kept in the preview cache.
TRANSIENT_REASONS: frozenset[PreviewReason] = frozenset(
    {
        "timeout",
        "memory_limit",
        "missing_file",
        "store_unavailable",
        "changed_since_scan",
    }
)
# Reasons of a probe after which no other operation can succeed: the pool
# answers them at once, and the ``preview`` job does not build.
UNRENDERABLE_REASONS: frozenset[PreviewReason] = frozenset(
    {"unreadable", "unsupported_format"}
)
# The renderer of each kind of file; ``composite`` renders layers of many.
RENDERER_OF_KIND: Mapping[PreviewKind, RendererName] = {
    "raster": "raster",
    "image": "raster",
    "vector": "vector",
    "points": "points",
    "archive": "archive",
    "document": "document",
    "auxiliary": "document",
    "unknown": "document",
}
# A content key, also a composite and a path key: SHA-256 in lower-case hex.
CONTENT_KEY = re.compile(r"[0-9a-f]{64}")
# Built automatically on the first preview only up to these sizes (decision
# 6): the file, and a raster's pixels and bytes once unpacked (a few MB of
# DEFLATE may declare 100 000 x 100 000 pixels).
AUTO_BUILD_MAX_FILE_BYTES = 2 * 1024**3
AUTO_BUILD_MAX_PIXELS = 1_000_000_000
AUTO_BUILD_MAX_UNPACKED_BYTES = 8 * 1024**3
# Name of the local COG of a file in its preview cache object.
COG_NAME = "cog.tif"
# Name of the consistent copy of an own-data SQLite file in state (b) or (c)
# (decision 8) in its preview cache object.
SOURCE_GPKG_NAME = "source.gpkg"

_FORMAT_BY_NAME = {found.name: found for found in FORMATS}


@dataclass(frozen=True, slots=True)
class FileStat:
    """Size, modification time and available identity of an ``os.stat`` result."""

    size_bytes: int
    modified_ns: int
    inode: int | None = None
    changed_ns: int | None = None

    @classmethod
    def of(cls, found: os.stat_result) -> "FileStat":
        """Keep inode and change time where the filesystem exposes them."""
        return cls(
            found.st_size,
            found.st_mtime_ns,
            getattr(found, "st_ino", None),
            getattr(found, "st_ctime_ns", None),
        )


@dataclass(frozen=True, slots=True)
class SourceStat:
    """State of an own-data file, checked before and after rendering.

    ``wal`` and ``journal`` are SQLite companions next to a GeoPackage.
    """

    main: FileStat
    wal: FileStat | None = None
    journal: FileStat | None = None


@dataclass(frozen=True, slots=True)
class Extent:
    """A rectangle ``(min_x, min_y, max_x, max_y)`` in a CRS (``EPSG:2180``).

    The georeference of a file from its header outline (a JPEG sheet), or
    the frame of a thumbnail.
    """

    bbox: BBox
    crs: str


@dataclass(frozen=True, slots=True)
class PreviewSource:
    """One file a render process may read, with what the index knows about it.

    Parameters
    ----------
    ref : str
        The object's reference (decision 10), e.g.
        ``version:zespol:nmt/…/plik.asc``.
    content_key : str
        Key of the content (lower-case SHA-256): the version's ``sha256``,
        its path key without one (``archiwista.previews.cache.path_key``),
        or the content identity of an own-data file.
    paths : tuple[Path, ...]
        Resolved absolute paths: the main file first, then the rest of its
        file set (a Shapefile's ``.shx .dbf .prj .cpg``).
    format_hint : str or None, optional
        Name of the main file's format in the format table
        (``FileFormat.name``) when the index knows it; by its extension
        otherwise.
    size_bytes : int or None, optional
        Size of the main file.
    crs : str or None, optional
        CRS for a file without its own (``EntryMeta.horizontal_crs``; an ASC
        grid carries none).
    georeference : Extent or None, optional
        Native rectangle and CRS from a header outline, for a file without
        a georeference of its own (a JPEG sheet, decision 5).
    product, dataset_key : str or None, optional
        Product and dataset key of the version: the default style.
    nodata : float or None, optional
        ``nodata`` of the version's metadata.
    mutable : bool, optional
        An own-data file whose state and content must match its indexed key
        before any preview is published.
    stat : SourceStat or None, optional
        Its state when the server resolved the indexed file.
    content_method : ContentMethod or None, optional
        How its indexed content SHA-256 was computed (bytes by default for
        manually constructed sources).
    """

    ref: str
    content_key: str
    paths: tuple[Path, ...]
    format_hint: str | None = None
    size_bytes: int | None = None
    crs: str | None = None
    georeference: Extent | None = None
    product: str | None = None
    dataset_key: str | None = None
    nodata: float | None = None
    mutable: bool = False
    stat: SourceStat | None = None
    content_method: ContentMethod | None = None

    def __post_init__(self) -> None:
        """Refuse a key that is no SHA-256, relative paths, an unknown format."""
        if CONTENT_KEY.fullmatch(self.content_key) is None:
            raise ValueError("a content key is a lower-case SHA-256")
        if not self.paths or not all(path.is_absolute() for path in self.paths):
            raise ValueError("a preview source has absolute paths, the main first")
        if self.format_hint is not None and self.format_hint not in _FORMAT_BY_NAME:
            raise ValueError(f"unknown format {self.format_hint!r}")
        if (
            self.content_method is not None
            and self.content_method not in CONTENT_METHODS
        ):
            raise ValueError("unknown own-data content method")

    @property
    def format(self) -> FileFormat:
        """Return the main file's format (the hint, else by its extension)."""
        if self.format_hint is not None:
            return _FORMAT_BY_NAME[self.format_hint]
        return file_format(self.paths[0])

    @property
    def kind(self) -> PreviewKind:
        """Return what a preview of the file can show."""
        return self.format.kind

    @property
    def renderer(self) -> RendererName:
        """Return the renderer of the file's kind."""
        return RENDERER_OF_KIND[self.kind]

    def to_json(self) -> JsonObject:
        """Return the source as a JSON object (the render protocol)."""
        return {
            "ref": self.ref,
            "content_key": self.content_key,
            "paths": [str(path) for path in self.paths],
            "format_hint": self.format_hint,
            "size_bytes": self.size_bytes,
            "crs": self.crs,
            "georeference": None
            if self.georeference is None
            else {"bbox": list(self.georeference.bbox), "crs": self.georeference.crs},
            "product": self.product,
            "dataset_key": self.dataset_key,
            "nodata": self.nodata,
            "mutable": self.mutable,
            "stat": None if self.stat is None else _stat_json(self.stat),
            "content_method": self.content_method,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "PreviewSource":
        """Read a source written by ``to_json``.

        Raises
        ------
        ValueError
            A member is missing or of the wrong type.
        """
        try:
            georeference = value.get("georeference")
            stat = value.get("stat")
            return cls(
                ref=str(value["ref"]),
                content_key=str(value["content_key"]),
                paths=tuple(Path(str(path)) for path in value["paths"]),
                format_hint=_optional(value.get("format_hint"), str),
                size_bytes=_optional(value.get("size_bytes"), int),
                crs=_optional(value.get("crs"), str),
                georeference=None
                if georeference is None
                else Extent(_bbox(georeference["bbox"]), str(georeference["crs"])),
                product=_optional(value.get("product"), str),
                dataset_key=_optional(value.get("dataset_key"), str),
                nodata=_optional(value.get("nodata"), float),
                mutable=bool(value.get("mutable", False)),
                stat=None if stat is None else _stat_of(stat),
                content_method=cast(
                    ContentMethod | None, _optional(value.get("content_method"), str)
                ),
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"invalid preview source: {error}") from error


@dataclass(frozen=True, slots=True)
class BandStats:
    """Statistics of one band from a decimated read (numpy, never GDAL's)."""

    p2: float
    p98: float
    min: float
    max: float


@dataclass(frozen=True, slots=True)
class PaletteEntry:
    """A value of a raster's palette and its colour ``(r, g, b, a)``."""

    value: int
    color: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class PreviewProbe:
    """What a renderer recognised in a file: ``info.json`` of its cache object.

    Never a file name or a path. Members a renderer does not know stay at
    their defaults.

    Parameters
    ----------
    kind : PreviewKind
        What a preview of the file can show.
    driver : str or None
        GDAL/OGR driver, or the format read without GDAL (``LAZ``, ``ZIP``).
    width, height, bands : int or None
        Raster size in pixels and its number of bands.
    dtype : str or None
        Data type of the bands (numpy name, e.g. ``float32``).
    crs : str or None
        CRS of the file, or ``PreviewSource.crs`` for one without its own.
    bbox_native : BBox or None
        Extent in ``crs``.
    bbox_wgs84 : BBox or None
        Extent in WGS84 (west, south, east, north); ``None`` without a
        pinned operation to the map's CRS or without a georeference.
    minzoom, maxzoom : int or None
        Zoom levels of the map tiles (maximum: the native resolution's
        zoom + 2, at most 22).
    overviews : tuple[int, ...]
        Decimation factors of the overviews.
    tiled : bool or None
        Whether the raster is internally tiled.
    nodata : float or None
        Value shown transparent.
    stats : tuple[BandStats, ...]
        Per band: p2, p98, min, max.
    palette : tuple[PaletteEntry, ...]
        Colour table of a class raster.
    layers : tuple[dict, ...]
        Layers of a vector file (name, geometry type, feature count,
        fields, extent, sample; step 5b).
    points : dict or None
        Header and classes of a point cloud (step 5c).
    members : int or None
        Number of members of an archive.
    needs_cog : bool
        Map tiles need a local COG first (decision 6).
    needs_copy : bool
        A working SQLite file (GeoPackage) an editor has open or left with
        its ``-wal`` or ``-journal`` (state (b) or (c) of decision 8): read
        only from its consistent copy, kept as ``source.gpkg``.
    pixels, unpacked_bytes : int or None
        Pixels of a raster and its bytes once unpacked (auto-build limits).
    reason : PreviewReason or None
        Why the file has no preview (or no map preview); a code only.
    styles : tuple[StyleName, ...]
        Styles the file can be shown in, the renderer's choice; empty for a
        file without an image preview.
    default_style : StyleName or None
        The style shown first: one of ``styles``, chosen by the renderer from
        the product (``PreviewSource.product``, ``dataset_key``).
    unit : str or None
        Unit of the values of a gradient legend, e.g. ``m``.
    class_table : str or None
        Table of the Polish class names a classes legend uses (``clc``,
        ``hsg``); ``None``: the palette's values only.
    """

    kind: PreviewKind
    driver: str | None = None
    width: int | None = None
    height: int | None = None
    bands: int | None = None
    dtype: str | None = None
    crs: str | None = None
    bbox_native: BBox | None = None
    bbox_wgs84: BBox | None = None
    minzoom: int | None = None
    maxzoom: int | None = None
    overviews: tuple[int, ...] = ()
    tiled: bool | None = None
    nodata: float | None = None
    stats: tuple[BandStats, ...] = ()
    palette: tuple[PaletteEntry, ...] = ()
    layers: tuple[JsonObject, ...] = ()
    points: JsonObject | None = None
    members: int | None = None
    needs_cog: bool = False
    needs_copy: bool = False
    pixels: int | None = None
    unpacked_bytes: int | None = None
    reason: PreviewReason | None = None
    styles: tuple[StyleName, ...] = ()
    default_style: StyleName | None = None
    unit: str | None = None
    class_table: str | None = None

    def __post_init__(self) -> None:
        """Refuse an unknown kind, reason or style."""
        if self.kind not in PREVIEW_KINDS:
            raise ValueError(f"unknown preview kind {self.kind!r}")
        if self.reason is not None and self.reason not in PREVIEW_REASONS:
            raise ValueError(f"unknown preview reason {self.reason!r}")
        unknown = [style for style in self.styles if style not in STYLE_NAMES]
        if unknown:
            raise ValueError(f"unknown preview styles {unknown!r}")
        if self.default_style is not None and self.default_style not in self.styles:
            raise ValueError(f"default style {self.default_style!r} not in styles")

    def to_json(self) -> JsonObject:
        """Return the probe as a JSON object (also inside render requests)."""
        value: JsonObject = {}
        for member in fields(self):
            item = getattr(self, member.name)
            if member.name == "stats":
                item = [[s.p2, s.p98, s.min, s.max] for s in self.stats]
            elif member.name == "palette":
                item = [[entry.value, *entry.color] for entry in self.palette]
            elif isinstance(item, tuple):
                item = list(item)
            value[member.name] = item
        return value

    @classmethod
    def from_json(cls, value: object) -> "PreviewProbe":
        """Read a probe written by ``to_json``.

        Raises
        ------
        ValueError
            Not such a JSON object.
        """
        try:
            if not isinstance(value, dict):
                raise TypeError("a probe is a JSON object")
            known = {member.name for member in fields(cls)}
            items = {name: item for name, item in value.items() if name in known}
            for name in ("bbox_native", "bbox_wgs84"):
                if items.get(name) is not None:
                    items[name] = _bbox(items[name])
            items["overviews"] = tuple(int(f) for f in items.get("overviews") or ())
            items["stats"] = tuple(
                BandStats(*(float(number) for number in band))
                for band in items.get("stats") or ()
            )
            items["palette"] = tuple(
                PaletteEntry(int(entry[0]), _color(entry[1:]))
                for entry in items.get("palette") or ()
            )
            items["layers"] = tuple(dict(layer) for layer in items.get("layers") or ())
            items["styles"] = tuple(str(style) for style in items.get("styles") or ())
            return cls(**items)
        except (TypeError, ValueError, IndexError) as error:
            raise ValueError(f"invalid preview probe: {error}") from error

    def to_bytes(self) -> bytes:
        """Return the probe as ``info.json``: compact UTF-8 JSON."""
        return json.dumps(
            self.to_json(), ensure_ascii=False, separators=(",", ":")
        ).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "PreviewProbe":
        """Read an ``info.json`` written by ``to_bytes``.

        Raises
        ------
        ValueError
            Not JSON, or not a probe.
        """
        try:
            value = json.loads(data)
        except ValueError as error:
            raise ValueError(f"invalid info.json: {error}") from error
        return cls.from_json(value)


class Renderer(Protocol):
    """A renderer of some kinds of files, run in a render process only.

    Steps 5a1–5c add one module each to ``archiwista.previews.renderers``.
    Besides these members a renderer may have ``features(source, probe,
    layer, bbox_wgs84, zoom, limit) -> dict`` (vectors), ``members(source)
    -> dict`` (archives) and ``build(source, probe, out_path) -> None``
    (writes what ``build_product`` names: the local COG of a file whose
    probe ``needs_cog``, the copy of one that ``needs_copy``). A vector
    renderer's ``thumbnail`` also takes ``layer`` (one layer drawn; the
    ``thumbnail`` operation passes it only when the request has one). A
    renderer raises ``PreviewUnavailableError`` with the reason a file has
    no such preview; any other error makes the file ``unreadable``.
    """

    @property
    def kinds(self) -> frozenset[PreviewKind]:
        """Kinds of files the renderer handles."""
        ...

    def probe(self, source: PreviewSource) -> PreviewProbe:
        """Recognise the file."""
        ...

    def thumbnail(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        size: int,
        frame: Extent | None,
    ) -> bytes:
        """Return a PNG of at most ``size`` pixels a side, in ``frame`` if given."""
        ...

    def tile(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        z: int,
        x: int,
        y: int,
        params: JsonObject,
    ) -> bytes:
        """Return the PNG map tile ``z/x/y`` (EPSG:3857, 256 pixels)."""
        ...


def build_product(probe: PreviewProbe) -> str | None:
    """Return the name of what the ``preview`` job builds for a file, if anything.

    The consistent copy of a working SQLite file in state (b) or (c), which
    its thumbnails read too (a file without a CRS has one), else the local
    COG of a raster whose map tiles need it.
    """
    if probe.needs_copy:
        return SOURCE_GPKG_NAME
    return COG_NAME if probe.needs_cog and probe.reason is None else None


def auto_build(source: PreviewSource, probe: PreviewProbe | None) -> bool:
    """Whether a file's preview is built at its first view (decision 6).

    A file of at most 2 GB, and a raster of at most 1 Gpx and 8 GB unpacked;
    a larger one waits for "Zbuduj podgląd" (``force``).
    """
    if source.size_bytes is not None and source.size_bytes > AUTO_BUILD_MAX_FILE_BYTES:
        return False
    if probe is None:
        return True
    if probe.pixels is not None and probe.pixels > AUTO_BUILD_MAX_PIXELS:
        return False
    unpacked = probe.unpacked_bytes
    return unpacked is None or unpacked <= AUTO_BUILD_MAX_UNPACKED_BYTES


def _stat_json(stat: SourceStat) -> JsonObject:
    return {
        "main": _file_stat_json(stat.main),
        "wal": None if stat.wal is None else _file_stat_json(stat.wal),
        "journal": None if stat.journal is None else _file_stat_json(stat.journal),
    }


def _file_stat_json(stat: FileStat) -> list[int | None]:
    return [stat.size_bytes, stat.modified_ns, stat.inode, stat.changed_ns]


def _file_stat_of(value: Sequence[Any]) -> FileStat:
    return FileStat(
        int(value[0]),
        int(value[1]),
        None if len(value) < 3 or value[2] is None else int(value[2]),
        None if len(value) < 4 or value[3] is None else int(value[3]),
    )


def _stat_of(value: Mapping[str, Any]) -> SourceStat:
    wal = value.get("wal")
    journal = value.get("journal")
    return SourceStat(
        main=_file_stat_of(value["main"]),
        wal=None if wal is None else _file_stat_of(wal),
        journal=None if journal is None else _file_stat_of(journal),
    )


def _bbox(value: Sequence[Any]) -> BBox:
    numbers = tuple(float(number) for number in value)
    if len(numbers) != 4:
        raise ValueError("a bounding box has four numbers")
    return numbers


def _color(value: Sequence[Any]) -> tuple[int, int, int, int]:
    numbers = tuple(int(number) for number in value)
    if len(numbers) != 4:
        raise ValueError("a colour has four components")
    return numbers


def _optional[T](value: object, kind: type[T]) -> T | None:
    if value is None:
        return None
    if kind is float and isinstance(value, int | float) and not isinstance(value, bool):
        return cast(T, float(value))
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise TypeError(f"{value!r} is not {kind.__name__}")
    return value
