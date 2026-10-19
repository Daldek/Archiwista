"""Local COG of a raster for its map tiles (plan v0.2, decision 6, step 5a2).

A file whose tiles cannot be read from it directly — an ASC or XYZ grid, a
JPEG sheet georeferenced by its header outline, a GeoTIFF in strips or
without overviews larger than 4096 pixels a side (``PreviewProbe.needs_cog``)
— gets a Cloud Optimized GeoTIFF in the preview cache, built by the
``preview`` job in a process of its own (``RasterRenderer.build``). The COG
is never a data product: it lives in the preview cache only, with no path
to copy (A-ADR-018: a light preview).

- read decimated to at most ``MAX_SIDE_PX`` pixels a side: averaging for
  values and colours, the nearest value for classes and palettes;
- the georeference the preview uses: the file's, else the index's (an ASC
  grid's CRS, a JPEG sheet's header outline), written into the COG;
- internal overviews (averaged, nearest for classes), 512-pixel tiles;
  DEFLATE with a predictor (horizontal for integers, floating point for
  floats), or JPEG for an 8-bit colour image, its mask kept beside;
- nodata as the file has it, else NaN for floats and a value the data do
  not use for integers; a palette is kept.

Render processes only (rasterio).
"""

from pathlib import Path
from typing import Any

import numpy as np
import rasterio.shutil
from rasterio.enums import ColorInterp, Resampling
from rasterio.io import MemoryFile
from rasterio.transform import Affine, from_bounds

from archiwista.errors import PreviewUnavailableError
from archiwista.formats import open_raster
from archiwista.previews.tiles import raster_view
from archiwista.previews.types import PreviewProbe, PreviewSource

# Longest side of a local COG (decision 6).
MAX_SIDE_PX = 8192
BLOCK_SIZE_PX = 512
JPEG_QUALITY = 90


def build_cog(source: PreviewSource, probe: PreviewProbe, out_path: Path) -> None:
    """Write the local COG of a raster file (``Renderer.build``).

    Parameters
    ----------
    source : PreviewSource
        The file (its main path, its georeference from the index).
    probe : PreviewProbe
        Its probe: the georeference used, nodata, palette, class table.
    out_path : Path
        Where to write the COG (the job's ``.incoming`` directory).

    Raises
    ------
    PreviewUnavailableError
        ``no_georeference`` / ``no_crs``: nothing to put on the map.
    """
    with open_raster(source.paths[0], source.format) as dataset:
        transform = (
            None
            if probe.bbox_native is None
            else from_bounds(*probe.bbox_native, dataset.width, dataset.height)
        )
        view = raster_view(
            dataset, transform=transform, crs=probe.crs, nodata=probe.nodata
        )
        if view.transform is None or view.crs is None:
            raise PreviewUnavailableError(probe.reason or "no_georeference")
        classes = bool(probe.palette) or probe.class_table is not None
        rows, columns = fitted(dataset.height, dataset.width, MAX_SIDE_PX)
        data = dataset.read(
            list(view.data_bands),
            out_shape=(len(view.data_bands), rows, columns),
            resampling=Resampling["nearest" if classes else "average"],
            masked=True,
        )
        if view.nodata is not None:
            data = np.ma.masked_equal(data, view.nodata, copy=False)
        colormap = _colormap(dataset) if classes else None
        nodata = dataset.nodata
        grid = view.transform @ Affine.scale(
            dataset.width / columns, dataset.height / rows
        )
    write_cog(
        out_path,
        data,
        crs=view.crs,
        transform=grid,
        classes=classes,
        nodata=nodata,
        colormap=colormap,
    )


def write_cog(
    out_path: Path,
    data: np.ma.MaskedArray[Any, Any],
    *,
    crs: str,
    transform: Affine,
    classes: bool,
    nodata: float | None = None,
    colormap: dict[int, tuple[int, ...]] | None = None,
) -> None:
    """Write values (bands, rows, columns) as a COG with internal overviews.

    Parameters
    ----------
    out_path : Path
        The COG to write.
    data : numpy.ma.MaskedArray
        Values of the bands; masked where there is no value.
    crs : str
        Their CRS.
    transform : Affine
        Their grid.
    classes : bool
        Class values: overviews by the nearest value, never averaged.
    nodata : float or None, optional
        Value for masked pixels; by default NaN for floats and a value the
        data do not use for integers (none for an 8-bit colour image, which
        keeps a mask).
    colormap : dict or None, optional
        Palette of the first band.
    """
    count, rows, columns = data.shape
    dtype = np.dtype(data.dtype)
    masked = np.ma.getmaskarray(data).any(axis=0)
    colour = dtype == np.uint8 and count >= 3 and not classes
    value = None
    if masked.any() and not colour:
        value = nodata if nodata is not None else _free_value(data)
    filled = np.asarray(data.filled(value if value is not None else 0), dtype=dtype)
    options: dict[str, Any] = {
        "BLOCKSIZE": BLOCK_SIZE_PX,
        "OVERVIEW_RESAMPLING": "NEAREST" if classes else "AVERAGE",
        "BIGTIFF": "IF_SAFER",
        "NUM_THREADS": 1,
    }
    if colour:
        options.update(COMPRESS="JPEG", QUALITY=JPEG_QUALITY)
    else:
        options.update(COMPRESS="DEFLATE", PREDICTOR=3 if dtype.kind == "f" else 2)
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=columns,
            height=rows,
            count=count,
            dtype=dtype.name,
            crs=crs,
            transform=transform,
            nodata=value,
        ) as staged:
            staged.write(filled)
            if colour:
                interpretation = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]
                staged.colorinterp = interpretation + [ColorInterp.undefined] * (
                    count - 3
                )
                if masked.any():
                    staged.write_mask(np.where(masked, 0, 255).astype(np.uint8))
            if colormap:
                staged.write_colormap(1, colormap)
        with memory.open() as staged:
            rasterio.shutil.copy(staged, out_path, driver="COG", **options)


def fitted(rows: int, columns: int, side: int) -> tuple[int, int]:
    """Return ``(rows, columns)`` scaled down to at most ``side`` a side."""
    longest = max(rows, columns)
    if longest <= side:
        return rows, columns
    scale = side / longest
    return max(1, round(rows * scale)), max(1, round(columns * scale))


def _colormap(dataset: Any) -> dict[int, tuple[int, ...]] | None:
    try:
        found: dict[int, tuple[int, ...]] = dataset.colormap(1)
    except ValueError:  # no palette
        return None
    return found


def _free_value(data: np.ma.MaskedArray[Any, Any]) -> float:
    """Return a nodata value for masked pixels the data do not use."""
    dtype = np.dtype(data.dtype)
    if dtype.kind == "f":
        return float("nan")
    limits = np.iinfo(dtype)
    used = np.unique(data.compressed())
    for candidate in (limits.min, limits.max, 0):
        if not np.isin(candidate, used):
            return float(candidate)
    free = np.setdiff1d(
        np.arange(limits.min, min(limits.max, limits.min + 65536)), used
    )
    if free.size == 0:
        raise PreviewUnavailableError("unsupported_format", "no value left for nodata")
    return float(free[0])
