"""Renderer of point clouds: LAS and LAZ (plan v0.2, decisions 3, 5 and 6).

The probe reads the public header (version, point format, count, extent,
scales), the CRS from the VLRs (WKT or GeoTIFF keys; the horizontal part
of a compound CRS) or ``PreviewSource.crs`` for a file without one, and the
density. Its histogram of ASPRS classes comes from a sample of at most
``SAMPLE_MAX_POINTS`` points and ``SAMPLE_MAX_BYTES`` bytes of unpacked
records, spread over the file:

- an uncompressed LAS (also one under a ``.laz`` name, as v0.1 stores
  have) is read in ``SAMPLE_WINDOWS`` windows spaced along the file;
- a LAZ with a chunk table is read in whole or partial chunks spaced along
  the table, each decompressed on its own (``lazrs``);
- a LAZ without a chunk table (written as a stream) only from its first
  chunk: the sample says ``sampled_from: "start"``.

Only the sample's records are ever unpacked (laspy's reader would read the
chunk table and refuse such a file). The map image is the highest Z in a
grid of cells of at least ``GRID_MIN_CELL_M`` (``GRID_MAX_SIDE_PX`` pixels
the longest side at most), built by the ``preview`` job as the file's local
COG (``build``, every point read in batches); its tiles are then those of a
raster. The thumbnail is the same image of the sample, so it needs no build.
"""

import math
import struct
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal, cast

import laspy
import lazrs
import numpy as np
import numpy.typing as npt
from affine import Affine
from rasterio.io import DatasetReader, MemoryFile
from rasterio.transform import from_origin

from archiwista.errors import PreviewUnavailableError
from archiwista.previews.cog import write_cog
from archiwista.previews.renderers.raster import open_cog, render_thumbnail, render_tile
from archiwista.previews.tiles import map_placement
from archiwista.previews.types import (
    BandStats,
    BBox,
    Extent,
    JsonObject,
    PreviewKind,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
    StyleName,
)

if TYPE_CHECKING:
    from pyproj import CRS

# Styles of a cloud's 2D image: its heights.
STYLES: tuple[StyleName, ...] = ("elevation",)

# The sample of the probe and the thumbnail (decision 5).
SAMPLE_MAX_POINTS = 2_000_000
SAMPLE_MAX_BYTES = 256 * 1024**2
# Windows of an uncompressed file's sample, spaced along the file.
SAMPLE_WINDOWS = 64
# The 2D image: cells of at least 1 m (in a geographic CRS the same in
# degrees of latitude), at most 8192 pixels the longest side (decision 6).
GRID_MIN_CELL_M = 1.0
GRID_MAX_SIDE_PX = 8192
# Points read at once while building the 2D image.
BUILD_BATCH_POINTS = 1_000_000
# Value of an empty cell of the 2D image.
NODATA = -9999.0

type SampledFrom = Literal["all", "spread", "start"]
type FloatArray = npt.NDArray[np.float64]

# Classes of the ASPRS LAS 1.4 specification (R15), in Polish. Codes 23–63
# are reserved, 64–255 the user's own.
ASPRS_CLASSES: Mapping[int, str] = {
    0: "Utworzone, nigdy niesklasyfikowane",
    1: "Niesklasyfikowane",
    2: "Grunt",
    3: "Niska roślinność",
    4: "Średnia roślinność",
    5: "Wysoka roślinność",
    6: "Budynki",
    7: "Szum niski",
    8: "Punkt kluczowy modelu",
    9: "Woda",
    10: "Kolej",
    11: "Nawierzchnia drogi",
    12: "Nakładanie się pasów",
    13: "Przewód — linka odgromowa",
    14: "Przewód — przewodnik",
    15: "Słup przesyłowy",
    16: "Złącze przewodu",
    17: "Pomost mostu",
    18: "Szum wysoki",
    19: "Konstrukcja napowietrzna",
    20: "Grunt pominięty",
    21: "Śnieg",
    22: "Wykluczenie czasowe",
}
_RESERVED_LABEL = "Klasa zarezerwowana"
_USER_LABEL = "Klasa użytkownika"
_FIRST_USER_CLASS = 64
# Chunk size of a LAZ whose chunks have variable sizes.
_VARIABLE_CHUNKS = 0xFFFFFFFF
# Bytes read past a window's records for LASzip overhead (a compressed
# chunk may be a little larger than its records).
_COMPRESSED_SLACK_BYTES = 64 * 1024
_LAZ_SELECTION = (
    laspy.DecompressionSelection.XY_RETURNS_CHANNEL
    | laspy.DecompressionSelection.Z
    | laspy.DecompressionSelection.CLASSIFICATION
)


def asprs_label(value: int) -> str:
    """Return the Polish name of an ASPRS class."""
    if value >= _FIRST_USER_CLASS:
        return _USER_LABEL
    return ASPRS_CLASSES.get(value, _RESERVED_LABEL)


@dataclass(frozen=True, slots=True)
class Window:
    """Consecutive points of a sample: ``count`` from point ``start``.

    In a LAZ ``chunk`` is the chunk they start (from its first point).
    """

    start: int
    count: int
    chunk: int | None = None


@dataclass(frozen=True, slots=True)
class Cloud:
    """What reading a point cloud's records needs, from its header.

    Parameters
    ----------
    header : laspy.LasHeader
        Public header with its VLRs.
    file_size : int
        Size of the file.
    chunks : tuple[tuple[int, int], ...] or None
        A LAZ's chunk table, ``(points, bytes)`` per chunk; ``None``
        without one, and for an uncompressed file.
    """

    header: laspy.LasHeader
    file_size: int
    chunks: tuple[tuple[int, int], ...] | None

    @property
    def compressed(self) -> bool:
        """Whether the records are LASzip-compressed."""
        return bool(self.header.are_points_compressed)

    @property
    def point_count(self) -> int:
        """Points the header declares."""
        return int(self.header.point_count)

    @property
    def record_bytes(self) -> int:
        """Bytes of one unpacked point record (extra bytes included)."""
        return int(self.header.point_format.size)

    @property
    def chunk_size(self) -> int | None:
        """Points of a LAZ's (fixed) chunks; ``None`` when variable or LAS."""
        if not self.compressed:
            return None
        size = int(lazrs.LazVlr(self.laszip_vlr).chunk_size())
        return None if size == _VARIABLE_CHUNKS else size

    @property
    def laszip_vlr(self) -> bytes:
        """The LASzip VLR's data of a LAZ (its compressor's settings)."""
        vlrs = self.header.vlrs
        return bytes(vlrs[vlrs.index("LasZipVlr")].record_data)


@dataclass(frozen=True, slots=True)
class Sample:
    """Points of a sample: scaled coordinates and ASPRS classes."""

    x: FloatArray
    y: FloatArray
    z: FloatArray
    classes: npt.NDArray[np.uint8]
    sampled_from: SampledFrom


class PointsRenderer:
    """LAS and LAZ: header, classes, 2D image of the highest Z."""

    @property
    def kinds(self) -> frozenset[PreviewKind]:
        """Point clouds."""
        return frozenset({"points"})

    def probe(self, source: PreviewSource) -> PreviewProbe:
        """Read the header and a sample's classes; place the 2D image on the map.

        Raises
        ------
        laspy.LaspyException, lazrs.LazrsError, ValueError
            Not a LAS/LAZ file, or a damaged one (``unreadable``).
        """
        with source.paths[0].open("rb") as stream:
            cloud = read_cloud(stream)
            sample = read_sample(stream, cloud, sample_windows(cloud))
        header = cloud.header
        crs = _crs_name(header) or source.crs
        bbox = _bbox(header)
        points = _points_json(cloud, sample, bbox, crs)
        grid = (
            None
            if bbox is None or crs is None
            else Grid.of(bbox, _cell_size(bbox, crs))
        )
        placement = None
        reason: PreviewReason | None = "no_crs" if crs is None else None
        if grid is not None and bbox is not None and crs is not None:
            try:
                placement = map_placement(bbox, crs, grid.width, grid.height)
            except PreviewUnavailableError as error:
                reason = cast(PreviewReason, error.reason)
        return PreviewProbe(
            kind="points",
            driver="LAZ" if cloud.compressed else "LAS",
            width=None if grid is None else grid.width,
            height=None if grid is None else grid.height,
            bands=1,
            dtype="float32",
            crs=crs,
            bbox_native=bbox,
            bbox_wgs84=None if placement is None else placement.bbox_wgs84,
            minzoom=None if placement is None else placement.minzoom,
            maxzoom=None if placement is None else placement.maxzoom,
            nodata=NODATA,
            stats=_stats(sample.z),
            points=points,
            needs_cog=placement is not None,
            pixels=None if grid is None else grid.width * grid.height,
            reason=reason,
            styles=STYLES,
            default_style=STYLES[0],
            unit="m",
        )

    def thumbnail(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        size: int,
        frame: Extent | None,
    ) -> bytes:
        """Return the highest Z of the sample, rendered as a raster's thumbnail.

        No build needed: the sample's grid (``size`` cells the longest side)
        is an in-memory raster for ``render_thumbnail``.

        Raises
        ------
        PreviewUnavailableError
            ``unreadable``: a cloud without points.
        """
        with source.paths[0].open("rb") as stream:
            cloud = read_cloud(stream)
            sample = read_sample(stream, cloud, sample_windows(cloud))
        bbox = _bbox(cloud.header)
        if bbox is None or sample.z.size == 0:
            raise PreviewUnavailableError("unreadable", "a point cloud without points")
        grid = Grid.of(bbox, max(bbox[2] - bbox[0], bbox[3] - bbox[1]) / size)
        image = grid.empty()
        grid.add(image, sample.x, sample.y, sample.z)
        with _in_memory(image, grid, probe.crs) as dataset:
            return render_thumbnail(dataset, probe, style, size, frame)

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
        """Return a map tile of the 2D image from its local COG, as a raster's.

        Raises
        ------
        PreviewUnavailableError
            The probe's reason (``no_crs``, ``transform_unavailable``), or
            ``unsupported_format`` before the COG is built.
        """
        if probe.reason is not None:
            raise PreviewUnavailableError(probe.reason)
        with open_cog(source) as dataset:
            if dataset is None:
                raise PreviewUnavailableError(
                    "unsupported_format", "the 2D image of the cloud is not built"
                )
            return render_tile(dataset, probe, style, z, x, y, params)

    def build(self, source: PreviewSource, probe: PreviewProbe, out_path: Path) -> None:
        """Write the 2D image of every point's highest Z as a COG at ``out_path``.

        A LAZ without a chunk table gives the image of its first chunk only
        (``sampled_from: "start"`` in its probe).

        Raises
        ------
        PreviewUnavailableError
            ``no_crs``: a file without a CRS has no map image.
        """
        if probe.crs is None:
            raise PreviewUnavailableError("no_crs")
        with source.paths[0].open("rb") as stream:
            cloud = read_cloud(stream)
            bbox = _bbox(cloud.header)
            if bbox is None:
                raise PreviewUnavailableError(
                    "unreadable", "a point cloud without points"
                )
            grid = Grid.of(bbox, _cell_size(bbox, probe.crs))
            image = grid.empty()
            for batch in read_all(stream, cloud):
                grid.add(image, batch.x, batch.y, batch.z)
        data = np.ma.masked_equal(image, NODATA)[np.newaxis]
        write_cog(
            out_path,
            data,
            crs=probe.crs,
            transform=grid.transform,
            classes=False,
            nodata=NODATA,
        )


@dataclass(frozen=True, slots=True)
class Grid:
    """A north-up grid over a rectangle: ``width`` x ``height`` cells of ``cell``."""

    min_x: float
    max_y: float
    cell: float
    width: int
    height: int

    @classmethod
    def of(cls, bbox: BBox, cell: float) -> "Grid":
        """Cover ``bbox`` with cells of ``cell`` (≥ 1 cell a side)."""
        min_x, min_y, max_x, max_y = bbox
        cell = cell if cell > 0 else 1.0
        width = max(1, math.ceil((max_x - min_x) / cell))
        height = max(1, math.ceil((max_y - min_y) / cell))
        return cls(min_x, max_y, cell, width, height)

    def empty(self) -> npt.NDArray[np.float32]:
        """Return an image of ``NODATA`` cells."""
        return np.full((self.height, self.width), NODATA, dtype=np.float32)

    @property
    def transform(self) -> Affine:
        """Return the grid's affine transform (north up)."""
        return cast(Affine, from_origin(self.min_x, self.max_y, self.cell, self.cell))

    def add(
        self,
        image: npt.NDArray[np.float32],
        x: FloatArray,
        y: FloatArray,
        z: FloatArray,
    ) -> None:
        """Raise each cell of ``image`` to the highest ``z`` of its points."""
        col = np.clip(
            ((x - self.min_x) / self.cell).astype(np.int64), 0, self.width - 1
        )
        row = np.clip(
            ((self.max_y - y) / self.cell).astype(np.int64), 0, self.height - 1
        )
        flat = image.reshape(-1)
        np.maximum.at(flat, row * self.width + col, z.astype(np.float32))


def read_cloud(stream: BinaryIO) -> Cloud:
    """Read a point cloud's header, VLRs and (LAZ) chunk table.

    Raises
    ------
    laspy.LaspyException
        Not a LAS/LAZ file.
    """
    file_size = stream.seek(0, 2)
    stream.seek(0)
    header = laspy.LasHeader.read_from(stream)
    chunks = None
    if header.are_points_compressed:
        chunks = _chunk_table(stream, header, file_size)
    return Cloud(header=header, file_size=file_size, chunks=chunks)


def sample_windows(cloud: Cloud) -> tuple[tuple[Window, ...], SampledFrom]:
    """Choose the windows of a sample: at most the points and bytes allowed.

    Returns
    -------
    tuple
        The windows in file order and where the sample comes from.
    """
    total = cloud.point_count
    budget = min(
        total, SAMPLE_MAX_POINTS, max(1, SAMPLE_MAX_BYTES // cloud.record_bytes)
    )
    if total == 0:
        return (), "all"
    if cloud.compressed and cloud.chunks is None:
        size = cloud.chunk_size
        count = budget if size is None else min(budget, size)
        return (Window(0, count, 0),), "start"
    if cloud.chunks is not None:
        return _chunk_windows(cloud.chunks, total, budget)
    if budget >= total:
        return (Window(0, total),), "all"
    windows = min(SAMPLE_WINDOWS, budget)
    each = budget // windows
    starts = np.linspace(0, total - each, windows).round().astype(np.int64)
    return tuple(Window(int(start), each) for start in starts), "spread"


def read_sample(
    stream: BinaryIO,
    cloud: Cloud,
    chosen: tuple[tuple[Window, ...], SampledFrom],
) -> Sample:
    """Read the windows of a sample."""
    windows, sampled_from = chosen
    parts = [_read_window(stream, cloud, window) for window in windows]
    return _joined(parts, sampled_from)


def read_all(stream: BinaryIO, cloud: Cloud) -> Iterator[Sample]:
    """Read every point, in batches of at most ``BUILD_BATCH_POINTS``."""
    if cloud.compressed and cloud.chunks is None:
        # Without a chunk table only the first chunk can be found.
        yield read_sample(stream, cloud, sample_windows(cloud))
        return
    if cloud.chunks is not None:
        start = 0
        for index, (points, _) in enumerate(cloud.chunks):
            count = min(points, cloud.point_count - start)
            if count <= 0:
                return
            yield _read_window(stream, cloud, Window(start, count, index))
            start += points
        return
    for start in range(0, cloud.point_count, BUILD_BATCH_POINTS):
        count = min(BUILD_BATCH_POINTS, cloud.point_count - start)
        yield _read_window(stream, cloud, Window(start, count))


@contextmanager
def _in_memory(
    image: npt.NDArray[np.float32], grid: Grid, crs: str | None
) -> Iterator[DatasetReader]:
    """Open the image as an in-memory GeoTIFF (no file): a raster's input."""
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=grid.width,
            height=grid.height,
            count=1,
            dtype="float32",
            crs=crs,
            transform=grid.transform,
            nodata=NODATA,
        ) as written:
            written.write(image, 1)
        with memory.open(driver="GTiff") as dataset:
            yield dataset


def _points_json(
    cloud: Cloud, sample: Sample, bbox: BBox | None, crs: str | None
) -> JsonObject:
    """Return the header and the sample's classes (``PreviewProbe.points``)."""
    header = cloud.header
    values, counts = np.unique(sample.classes, return_counts=True)
    created = header.creation_date
    return {
        "version": str(header.version),
        "point_format": int(header.point_format.id),
        "point_count": cloud.point_count,
        "compressed": cloud.compressed,
        "record_bytes": cloud.record_bytes,
        "chunk_table": cloud.chunks is not None,
        "min": [float(v) for v in header.mins],
        "max": [float(v) for v in header.maxs],
        "scales": [float(v) for v in header.scales],
        "density_per_m2": _density(cloud.point_count, bbox, crs),
        "creation_date": None if created is None else created.isoformat(),
        "generating_software": str(header.generating_software).strip("\x00 "),
        "classes": [
            {"value": int(value), "label": asprs_label(int(value)), "count": int(n)}
            for value, n in zip(values, counts, strict=True)
        ],
        "sample_points": int(sample.classes.size),
        "sampled_from": sample.sampled_from,
    }


def _stats(z: FloatArray) -> tuple[BandStats, ...]:
    """Heights of the sample: p2, p98, min, max (the elevation style's range)."""
    if z.size == 0:
        return ()
    low, high = np.percentile(z, (2, 98))
    return (BandStats(float(low), float(high), float(z.min()), float(z.max())),)


def _chunk_table(
    stream: BinaryIO, header: laspy.LasHeader, file_size: int
) -> tuple[tuple[int, int], ...] | None:
    """Return a LAZ's chunk table, or ``None`` when it has none (a stream)."""
    start = int(header.offset_to_point_data)
    stream.seek(start)
    raw = stream.read(8)
    if len(raw) != 8:
        raise ValueError("no point records")
    (table_at,) = struct.unpack("<q", raw)
    if not start + 8 <= table_at < file_size:
        return None
    vlrs = header.vlrs
    vlr = lazrs.LazVlr(bytes(vlrs[vlrs.index("LasZipVlr")].record_data))
    stream.seek(start)
    try:
        table = lazrs.read_chunk_table(stream, vlr)
    except lazrs.LazrsError:
        return None
    chunks = tuple((int(points), int(size)) for points, size in table)
    if sum(size for _, size in chunks) > table_at - start - 8:
        return None  # sizes past the table: not a table of this file
    return chunks


def _chunk_windows(
    chunks: tuple[tuple[int, int], ...], total: int, budget: int
) -> tuple[tuple[Window, ...], SampledFrom]:
    starts = np.cumsum([0] + [points for points, _ in chunks[:-1]])
    sizes = [
        min(points, max(0, total - int(start)))
        for (points, _), start in zip(chunks, starts, strict=True)
    ]
    if budget >= total:
        windows = tuple(
            Window(int(start), size, index)
            for index, (start, size) in enumerate(zip(starts, sizes, strict=True))
            if size > 0
        )
        return windows, "all"
    used = [index for index, size in enumerate(sizes) if size > 0]
    count = min(len(used), budget)
    picked = sorted(
        {used[int(i)] for i in np.linspace(0, len(used) - 1, count).round()}
    )
    each = budget // len(picked)
    return (
        tuple(
            Window(int(starts[index]), min(each, sizes[index]), index)
            for index in picked
        ),
        "spread",
    )


def _read_window(stream: BinaryIO, cloud: Cloud, window: Window) -> Sample:
    """Read the points of one window: plain records, or one chunk's start."""
    header = cloud.header
    size = cloud.record_bytes
    data_start = int(header.offset_to_point_data)
    if not cloud.compressed:
        stream.seek(data_start + window.start * size)
        raw = stream.read(window.count * size)
        if len(raw) != window.count * size:
            raise ValueError("fewer point records than the header declares")
        buffer = bytearray(raw)
    else:
        # A layered chunk (point formats 6–10) holds each field for all its
        # points in turn: read whole, at most a little more than its records.
        if cloud.chunks is not None and window.chunk is not None:
            offset = data_start + 8 + sum(b for _, b in cloud.chunks[: window.chunk])
            chunk_points, chunk_bytes = cloud.chunks[window.chunk]
        else:
            offset = data_start + 8
            chunk_points, chunk_bytes = (
                cloud.chunk_size or window.count,
                cloud.file_size,
            )
        raw_bytes = min(chunk_points * size, SAMPLE_MAX_BYTES)
        limit = min(chunk_bytes, raw_bytes + raw_bytes // 8 + _COMPRESSED_SLACK_BYTES)
        stream.seek(offset)
        compressed = stream.read(min(limit, cloud.file_size - offset))
        buffer = bytearray(window.count * size)
        lazrs.decompress_points_with_chunk_table(
            compressed,
            cloud.laszip_vlr,
            buffer,
            [(window.count, len(compressed))],
            _LAZ_SELECTION.to_lazrs(),
        )
    record = laspy.PackedPointRecord.from_buffer(
        buffer, header.point_format, window.count
    )
    scales, offsets = header.scales, header.offsets
    return Sample(
        x=np.asarray(record["X"], dtype=np.float64) * scales[0] + offsets[0],
        y=np.asarray(record["Y"], dtype=np.float64) * scales[1] + offsets[1],
        z=np.asarray(record["Z"], dtype=np.float64) * scales[2] + offsets[2],
        classes=np.asarray(record["classification"], dtype=np.uint8),
        sampled_from="all",
    )


def _joined(parts: list[Sample], sampled_from: SampledFrom) -> Sample:
    if not parts:
        empty = np.zeros(0, dtype=np.float64)
        return Sample(empty, empty, empty, np.zeros(0, dtype=np.uint8), sampled_from)
    return Sample(
        x=np.concatenate([part.x for part in parts]),
        y=np.concatenate([part.y for part in parts]),
        z=np.concatenate([part.z for part in parts]),
        classes=np.concatenate([part.classes for part in parts]),
        sampled_from=sampled_from,
    )


def _crs_name(header: laspy.LasHeader) -> str | None:
    """Return the horizontal CRS of the VLRs: ``EPSG:<code>`` or WKT."""
    try:
        found = header.parse_crs()
    except Exception:  # a damaged CRS VLR: as without one
        return None
    if found is None:
        return None
    horizontal: CRS = found
    if found.is_compound:
        horizontal = found.sub_crs_list[0]
    code = horizontal.to_epsg()
    return f"EPSG:{code}" if code is not None else str(horizontal.to_wkt())


def _bbox(header: laspy.LasHeader) -> BBox | None:
    min_x, min_y = (float(v) for v in header.mins[:2])
    max_x, max_y = (float(v) for v in header.maxs[:2])
    values = (min_x, min_y, max_x, max_y)
    if not all(math.isfinite(v) for v in values) or min_x > max_x or min_y > max_y:
        return None
    return values


def _is_geographic(crs: str | None) -> bool:
    if crs is None:
        return False
    from pyproj import CRS

    try:
        return bool(CRS.from_user_input(crs).is_geographic)
    except Exception:  # an unknown CRS: taken as planar
        return False


def _density(points: int, bbox: BBox | None, crs: str | None) -> float | None:
    """Points per square metre of the extent, in a planar CRS only."""
    if bbox is None or _is_geographic(crs):
        return None
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    return round(points / area, 3) if area > 0 else None


def _cell_size(bbox: BBox, crs: str) -> float:
    """Return the 2D image's cell: ≥ 1 m and ≤ ``GRID_MAX_SIDE_PX`` a side."""
    minimum = GRID_MIN_CELL_M / 111_320.0 if _is_geographic(crs) else GRID_MIN_CELL_M
    longest = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    return max(minimum, longest / GRID_MAX_SIDE_PX)
