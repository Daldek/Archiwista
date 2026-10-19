"""Renderer of rasters and images (plan v0.2, steps 5a1–5a3; decisions 3–6).

Files of kind ``raster`` (GeoTIFF, ASC, XYZ) and ``image`` (JPEG, PNG),
always opened through the format table with their one driver
(``archiwista.formats.open_raster``, decision 3), never by a path GDAL
could take for another format.

- ``probe``: driver, size, bands, type, the georeference the preview uses
  (the file's own; else the index's: the CRS of an ASC grid, the header
  outline of a JPEG sheet), overviews, tiling, nodata, palette; the place on
  the map through the pinned operation (``tiles.map_placement``);
  statistics (2nd and 98th percentile, minimum, maximum per band) computed
  by numpy from a decimated read — the nearest overview of at most 1024
  pixels a side, or ``out_shape`` of 1024 pixels without overviews; a file
  too large for that and without overviews is sampled in windows spread
  over it — never GDAL's statistics (they write ``.aux.xml`` next to the
  data); the styles of the file with the default one from its product
  (decision 5); ``needs_cog`` and the pixels and bytes of the auto-build
  limits (decision 6). Reasons: ``no_georeference``, ``no_crs``,
  ``transform_unavailable`` (a thumbnail is still made),
  ``unsupported_format`` (an ungridded XYZ file).
- ``thumbnail``: in the file's CRS from a decimated read, or in a frame
  (``Extent``: a layer's planar frame) warped with the pinned operation and
  painted only on the window of the frame the file covers.
- ``tile``: the 256-pixel EPSG:3857 tile warped by ``reproject`` with the
  pinned operation as ``COORDINATE_OPERATION`` from the nearest overview
  (decision 4), with the margin its style looks at.
- ``build``: the local COG (``archiwista.previews.cog``) of a file that
  ``needs_cog``; its thumbnails and tiles then come from it.

``open_cog``, ``render_tile`` and ``render_thumbnail`` also serve other
renderers with a COG of their own (a point cloud's 2D image).
"""

import contextlib
import math
import warnings
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import numpy as np
from rasterio.errors import NotGeoreferencedWarning, RasterioIOError
from rasterio.transform import Affine, from_bounds
from rasterio.windows import Window

from archiwista.errors import PreviewUnavailableError
from archiwista.formats import FORMATS, open_raster
from archiwista.previews import tiles
from archiwista.previews.classes import TABLE_OF_PRODUCT, class_entry
from archiwista.previews.cog import build_cog
from archiwista.previews.styles import (
    STYLES,
    Metres,
    Rgba,
    Style,
    StyleContext,
    Values,
)
from archiwista.previews.types import (
    COG_NAME,
    BandStats,
    Extent,
    JsonObject,
    PaletteEntry,
    PreviewKind,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
    StyleName,
    auto_build,
)
from archiwista.previews.worker import cached_file

if TYPE_CHECKING:
    from rasterio.io import DatasetReader

# Side of the decimated read of a probe's statistics.
SAMPLE_SIDE_PX = 1024
# Pixels a file without overviews may have to be read whole, decimated, for
# its statistics; a larger one is sampled in windows.
SAMPLE_FULL_MAX_PIXELS = 64 * 1024**2
# Windows (per row and column) and their side when sampling such a file.
SAMPLE_WINDOWS = 8
SAMPLE_WINDOW_PX = 128
# Values of a class raster's palette kept in its probe at most.
MAX_PALETTE_ENTRIES = 256
# Side above which a raster in strips or without overviews gets a local COG
# for its tiles (decision 6).
DIRECT_MAX_SIDE_PX = 4096
# Drivers whose files always get a local COG: text grids read line by line.
COG_DRIVERS = frozenset({"AAIGrid", "XYZ"})
# Products of heights: hillshade first, values in metres (decision 5).
ELEVATION_PRODUCTS = frozenset({"nmt", "nmpt"})
# What GDAL's XYZ driver says of points that are no regular grid.
_UNGRIDDED = "ungridded"

_GEOTIFF = next(found for found in FORMATS if found.driver == "GTiff")


class RasterRenderer:
    """Renderer of ``raster`` and ``image`` files (``RENDERERS``)."""

    kinds: frozenset[PreviewKind] = frozenset({"raster", "image"})

    def probe(self, source: PreviewSource) -> PreviewProbe:
        """Recognise a raster or image file (see the module)."""
        return probe_raster(source)

    def thumbnail(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        size: int,
        frame: Extent | None,
    ) -> bytes:
        """Return a PNG of the file at most ``size`` pixels a side."""
        with _opened(source, probe) as dataset:
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
        """Return the PNG map tile ``z/x/y`` of the file."""
        if probe.reason is not None:
            raise PreviewUnavailableError(probe.reason)
        with _opened(source, probe) as dataset:
            return render_tile(dataset, probe, style, z, x, y, params)

    build = staticmethod(build_cog)


def probe_raster(source: PreviewSource) -> PreviewProbe:
    """Recognise a raster or image file.

    Raises
    ------
    PreviewUnavailableError
        ``unsupported_format``: points of an XYZ file that are no grid.
    FormatRefusedError
        The file is not of its format (the format table).
    """
    with _open_source(source) as dataset:
        own = not dataset.transform.is_identity
        georeference = None if own else source.georeference
        view = tiles.raster_view(
            dataset,
            transform=None
            if georeference is None
            else from_bounds(*georeference.bbox, dataset.width, dataset.height),
            crs=source.crs if georeference is None else georeference.crs,
            nodata=_finite(source.nodata),
        )
        width, height = dataset.width, dataset.height
        bands = view.data_bands
        dtype = str(dataset.dtypes[bands[0] - 1])
        overviews = tuple(int(factor) for factor in dataset.overviews(bands[0]))
        tiled = dataset.block_shapes[0][1] != width
        file_palette = _file_palette(dataset)
        class_table = (
            None
            if source.kind == "image"
            else TABLE_OF_PRODUCT.get(source.product or "")
        )
        sample = _sample(view, overviews)
        palette: tuple[PaletteEntry, ...] = ()
        if file_palette is not None or class_table is not None:
            palette = _palette(sample, file_palette, class_table)
        styles, default = _styles(
            source.kind,
            len(bands),
            dtype,
            file_palette is not None,
            class_table,
            source.product,
        )
        reason: PreviewReason | None = None
        bbox_native = None
        placement = None
        if view.transform is None:
            reason = "no_georeference"
        else:
            bbox_native = tiles.raster_bounds(view.transform, width, height)
            if view.crs is None:
                reason = "no_crs"
            else:
                try:
                    placement = tiles.map_placement(
                        bbox_native, view.crs, width, height
                    )
                except PreviewUnavailableError:
                    reason = "transform_unavailable"
        # A georeference or CRS from the index travels in the COG (decision 6).
        needs_cog = reason is None and (
            dataset.driver in COG_DRIVERS
            or georeference is not None
            or dataset.crs is None
            or (
                max(width, height) > DIRECT_MAX_SIDE_PX and (not tiled or not overviews)
            )
        )
        return PreviewProbe(
            kind=source.kind,
            driver=str(dataset.driver),
            width=width,
            height=height,
            bands=dataset.count,
            dtype=dtype,
            crs=view.crs,
            bbox_native=bbox_native,
            bbox_wgs84=None if placement is None else placement.bbox_wgs84,
            minzoom=None if placement is None else placement.minzoom,
            maxzoom=None if placement is None else placement.maxzoom,
            overviews=overviews,
            tiled=tiled,
            nodata=_finite(source.nodata if dataset.nodata is None else dataset.nodata),
            stats=_stats(sample),
            palette=palette,
            needs_cog=needs_cog,
            pixels=width * height,
            unpacked_bytes=width * height * dataset.count * np.dtype(dtype).itemsize,
            reason=reason,
            styles=styles,
            default_style=default,
            unit="m" if source.product in ELEVATION_PRODUCTS else None,
            class_table=class_table,
        )


@contextlib.contextmanager
def open_cog(source: PreviewSource) -> Iterator["DatasetReader | None"]:
    """Open the local COG of a source from the preview cache.

    Yields
    ------
    rasterio.io.DatasetReader or None
        The COG (the cache object of ``source``), or ``None`` when the cache
        has none (not built, or evicted).
    """
    with cached_file(source, COG_NAME) as path:
        if path is None:
            yield None
            return
        try:
            dataset = open_raster(path, _GEOTIFF)
        except RasterioIOError:  # gone between the link and the opening
            yield None
            return
        with dataset:
            yield dataset


def view_of(dataset: "DatasetReader", probe: PreviewProbe) -> tiles.RasterView:
    """Return an open raster with the georeference of its probe.

    The dataset's own georeference first; for a file without one, the
    probe's (``bbox_native`` and ``crs``: the index's).
    """
    transform = (
        None
        if probe.bbox_native is None
        else from_bounds(*probe.bbox_native, dataset.width, dataset.height)
    )
    return tiles.raster_view(
        dataset, transform=transform, crs=probe.crs, nodata=_finite(probe.nodata)
    )


def render_tile(
    dataset: "DatasetReader",
    probe: PreviewProbe,
    style: str,
    z: int,
    x: int,
    y: int,
    params: JsonObject,
) -> bytes:
    """Return the PNG map tile ``z/x/y`` (EPSG:3857, 256 pixels, alpha).

    The raster is warped onto the tile with its margin by ``reproject``
    with the pinned operation (``tiles.warp``), from the nearest overview.

    Parameters
    ----------
    dataset : rasterio.io.DatasetReader
        The raster (a file, its COG, an in-memory image).
    probe : PreviewProbe
        Its probe: georeference of a file without its own, nodata,
        statistics and palette for the style.
    style : str
        A style of ``STYLES`` (one of ``probe.styles`` when it has some).
    z, x, y : int
        The tile.
    params : dict
        ``rescale``: ``[low, high]`` of the values shown, optional.

    Raises
    ------
    PreviewUnavailableError
        ``no_georeference``, ``no_crs`` or ``transform_unavailable``.
    """
    look = _style(probe, style)
    view = view_of(dataset, probe)
    if view.transform is None or view.crs is None:
        raise PreviewUnavailableError(probe.reason or "no_georeference")
    grid, side = tiles.tile_grid(z, x, y, margin=look.margin_px)
    values = tiles.warp(
        view,
        look.bands(view.data_bands),
        grid,
        (side, side),
        tiles.WEB_MERCATOR,
        resampling=look.warping(probe),
        decimation=look.reading(probe),
    )
    across, down = tiles.pixel_metres(grid, side, tiles.WEB_MERCATOR)
    context = StyleContext(probe, _rescale(params), across, down)
    return tiles.encode_png(look.apply(values, context))


def render_thumbnail(
    dataset: "DatasetReader",
    probe: PreviewProbe,
    style: str,
    size: int,
    frame: Extent | None,
) -> bytes:
    """Return a PNG thumbnail at most ``size`` pixels a side.

    Without a frame: the whole raster in its own CRS, read decimated (never
    larger than the raster). With a frame: the frame's rectangle in its CRS
    (a layer's planar frame), the raster warped into it with the pinned
    operation, transparent around it.

    Raises
    ------
    PreviewUnavailableError
        A frame for a raster without georeference or CRS (its reason).
    """
    look = _style(probe, style)
    view = view_of(dataset, probe)
    bands = look.bands(view.data_bands)
    margin = look.margin_px
    if frame is None:
        rows, columns = _fitted(dataset.height, dataset.width, size)
        values = tiles.read_values(
            view, bands, shape=(rows, columns), resampling=look.reading(probe)
        )
        if margin:
            values = _padded(values, margin)
        grid = (
            Affine.scale(dataset.width / columns, dataset.height / rows)
            if view.transform is None
            else view.transform
            @ Affine.scale(dataset.width / columns, dataset.height / rows)
        ) @ Affine.translation(-margin, -margin)
        across, down = tiles.pixel_metres(
            grid, rows + 2 * margin, None if view.transform is None else view.crs
        )
    else:
        if view.transform is None or view.crs is None:
            raise PreviewUnavailableError(probe.reason or "no_crs")
        rows, columns = tiles.frame_shape(frame.bbox, size)
        grid = tiles.grid_transform(frame.bbox, columns, rows) @ Affine.translation(
            -margin, -margin
        )
        shape = (rows + 2 * margin, columns + 2 * margin)
        values = tiles.warp(
            view,
            bands,
            grid,
            shape,
            frame.crs,
            resampling=look.warping(probe),
            decimation=look.reading(probe),
        )
        across, down = tiles.pixel_metres(grid, shape[0], frame.crs)
        context = StyleContext(probe, None, across, down)
        return tiles.encode_png(_paint_within(look, values, context))
    return tiles.encode_png(look.apply(values, StyleContext(probe, None, across, down)))


def _paint_within(look: Style, values: Values, context: StyleContext) -> Rgba:
    """Paint a style only on the window of a grid that has values.

    A version's thumbnail in a layer's frame covers a small part of it (one
    sheet of a year): the style — a hillshade above all — is applied to the
    values' window with the style's margin and laid into a transparent
    frame. The pixels are those of painting the whole grid, whose cells
    without values are transparent anyway (plan v0.2, step 16).
    """
    margin = look.margin_px
    rows, columns = values.shape[1] - 2 * margin, values.shape[2] - 2 * margin
    rgba = np.zeros((4, rows, columns), dtype=np.uint8)
    # Every value a style may look at (its percentiles too) lies in the window.
    present = ~np.ma.getmaskarray(values).all(axis=0)
    found_rows = np.flatnonzero(present.any(axis=1))
    found_columns = np.flatnonzero(present.any(axis=0))
    if found_rows.size == 0:
        return rgba
    # A painted pixel's centre is a value; it looks ``margin`` cells around.
    top = max(int(found_rows[0]) - margin, 0)
    bottom = min(int(found_rows[-1]) + 1 - margin, rows)
    left = max(int(found_columns[0]) - margin, 0)
    right = min(int(found_columns[-1]) + 1 - margin, columns)
    if top >= bottom or left >= right:
        return rgba
    window = values[:, top : bottom + 2 * margin, left : right + 2 * margin]
    context = replace(
        context,
        pixel_x_m=_rows_of(context.pixel_x_m, top, bottom + 2 * margin),
        pixel_y_m=_rows_of(context.pixel_y_m, top, bottom + 2 * margin),
    )
    rgba[:, top:bottom, left:right] = look.apply(window, context)
    return rgba


def _rows_of(metres: Metres, start: int, stop: int) -> Metres:
    """Return the per-row pixel sizes of rows ``start:stop``; one number as is."""
    if isinstance(metres, np.ndarray) and metres.ndim == 2:
        return metres[start:stop]
    return metres


@contextlib.contextmanager
def _opened(source: PreviewSource, probe: PreviewProbe) -> Iterator["DatasetReader"]:
    """Open what a preview of a source reads: its local COG, else the file.

    A file over the auto-build limits without overviews and without its
    COG is not read whole for a preview (``too_large``: "Zbuduj podgląd").
    """
    if probe.needs_cog:
        with open_cog(source) as cog:
            if cog is not None:
                yield cog
                return
        if not probe.overviews and not auto_build(source, probe):
            raise PreviewUnavailableError("too_large", "the local COG is not built")
    with _open_source(source) as dataset:
        yield dataset


@contextlib.contextmanager
def _open_source(source: PreviewSource) -> Iterator["DatasetReader"]:
    """Open a source's main file with its driver; an ungridded XYZ is refused."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            dataset = open_raster(source.paths[0], source.format)
    except RasterioIOError as error:
        if _UNGRIDDED in str(error).lower():
            raise PreviewUnavailableError("unsupported_format", str(error)) from error
        raise
    with dataset:
        yield dataset


def _style(probe: PreviewProbe, style: str) -> Style:
    found = STYLES.get(style)
    if found is None or (probe.styles and style not in probe.styles):
        raise ValueError(f"no style {style!r} for this file")
    return found


def _sample(view: tiles.RasterView, overviews: Sequence[int]) -> Values:
    """Read the values of a probe's statistics: decimated, or windows of a file."""
    dataset = view.dataset
    bands = view.data_bands
    width, height = dataset.width, dataset.height
    if overviews or width * height <= SAMPLE_FULL_MAX_PIXELS:
        shape = _fitted(height, width, SAMPLE_SIDE_PX)
        return tiles.read_values(view, bands, shape=shape, resampling="nearest")
    side = SAMPLE_WINDOW_PX
    pieces = []
    for row in range(SAMPLE_WINDOWS):
        for column in range(SAMPLE_WINDOWS):
            window = Window(
                (width - side) * column // (SAMPLE_WINDOWS - 1),
                (height - side) * row // (SAMPLE_WINDOWS - 1),
                side,
                side,
            )
            pieces.append(
                tiles.read_values(
                    view, bands, shape=(side, side), resampling="nearest", window=window
                )
            )
    return np.ma.concatenate(pieces, axis=2)


def _stats(sample: Values) -> tuple[BandStats, ...]:
    """Return the 2nd and 98th percentile, minimum and maximum of each band."""
    found = []
    for band in sample:
        valid = np.ma.compressed(band)
        if valid.size == 0:
            return ()
        low, high = np.percentile(valid, (2, 98))
        found.append(
            BandStats(float(low), float(high), float(valid.min()), float(valid.max()))
        )
    return tuple(found)


def _file_palette(dataset: "DatasetReader") -> dict[int, tuple[int, ...]] | None:
    try:
        palette: dict[int, tuple[int, ...]] = dataset.colormap(1)
    except ValueError:  # the band has no palette
        return None
    return palette


def _palette(
    sample: Values,
    file_palette: dict[int, tuple[int, ...]] | None,
    class_table: str | None,
) -> tuple[PaletteEntry, ...]:
    """Return the colours of the class values found in the sample."""
    values = np.unique(np.rint(np.ma.compressed(sample[0])).astype(np.int64))
    entries = []
    for value in values[:MAX_PALETTE_ENTRIES].tolist():
        if file_palette is not None and value in file_palette:
            red, green, blue, alpha = (tuple(file_palette[value]) + (255,))[:4]
            entries.append(PaletteEntry(value, (red, green, blue, alpha)))
            continue
        entry = class_entry(class_table, value)
        color = (128, 128, 128) if entry is None else entry.color
        entries.append(PaletteEntry(value, (*color, 255)))
    return tuple(entries)


def _styles(
    kind: PreviewKind,
    bands: int,
    dtype: str,
    palette: bool,
    class_table: str | None,
    product: str | None,
) -> tuple[tuple[StyleName, ...], StyleName]:
    """Return the styles of a file and its default one (decision 5)."""
    if kind == "image":
        if palette:
            return ("rgb",), "rgb"
        if bands >= 3:
            return ("rgb", "gray"), "rgb"
        return ("gray",), "gray"
    if palette or class_table is not None:
        return ("classes",), "classes"
    if bands >= 3:
        return ("rgb", "gray"), "rgb"
    if dtype == "uint8" and product not in ELEVATION_PRODUCTS:
        return ("gray",), "gray"
    if product in ELEVATION_PRODUCTS:
        return ("hillshade", "hypsometry", "gray"), "hillshade"
    return ("hypsometry", "hillshade", "gray"), "hypsometry"


def _rescale(params: JsonObject) -> tuple[float, float] | None:
    """Return the ``rescale`` of a tile request: two numbers, low then high."""
    found = params.get("rescale")
    if found is None:
        return None
    parts = found.split(",") if isinstance(found, str) else list(found)
    low, high = (float(part) for part in parts)
    if not (math.isfinite(low) and math.isfinite(high)) or low >= high:
        raise ValueError("rescale is two finite numbers, the lower first")
    return low, high


def _fitted(rows: int, columns: int, size: int) -> tuple[int, int]:
    """Return ``(rows, columns)`` scaled down to at most ``size`` a side."""
    longest = max(rows, columns)
    if longest <= size:
        return rows, columns
    scale = size / longest
    return max(1, round(rows * scale)), max(1, round(columns * scale))


def _padded(values: Values, margin: int) -> Values:
    """Return values with ``margin`` pixels repeated from their edges."""
    width = ((0, 0), (margin, margin), (margin, margin))
    data = np.pad(np.ma.filled(values, np.nan), width, mode="edge")
    mask = np.pad(np.ma.getmaskarray(values), width, mode="edge")
    return np.ma.MaskedArray(data, mask=mask)


def _finite(value: Any) -> float | None:
    """Return a nodata value as a float, ``None`` for none or NaN."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None
