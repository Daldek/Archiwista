"""Styles of raster previews: values on a grid to RGBA (plan v0.2, steps 5a1, 5a3).

``STYLES`` registers each style under its name (``StyleName``), one line per
style. A render process reads the bands a style asks for (``bands``) onto
the grid of a tile or thumbnail — warped with ``resampling``, read
decimated with ``decimation`` — with ``margin_px`` pixels of the
neighbouring grid around it, and the style turns them into RGBA without
that margin (``apply``). Masked values (nodata, alpha, outside the file) are
transparent. What its colours mean is the style's legend
(``archiwista.previews.legends``).

- ``rgb``: three bands, or a palette's colours; ``gray``: one band, or the
  luminance of three. Both stretch the values between the 2nd and 98th
  percentile of the file (``PreviewProbe.stats``, from a decimated read) or
  a ``rescale`` asked for; an 8-bit colour image (orthophoto, scanned map)
  stays as it is in ``rgb``, already made to be seen.
- ``hypsometry`` (rasters) and ``elevation`` (point clouds' 2D image): the
  colour ramp ``legends.RAMP`` over the same range.
- ``hillshade``: Horn's slopes lit from the north-west (azimuth 315°,
  altitude 45°), with horizontal distances in metres and a vertical
  exaggeration growing with the pixel's size in metres (its square root,
  1–25: relief stays visible at small scales); it looks at the pixels
  around, so a tile is read with a margin of 1 pixel and neighbouring tiles
  meet without a seam.
- ``classes``: the palette's colour of each value, else the colour of its
  class table (``probe.class_table``: CORINE, HSG), else grey.

numpy only: no GDAL here.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from archiwista.previews.classes import class_entry
from archiwista.previews.legends import LEGEND_KINDS, RAMP, LegendKind
from archiwista.previews.types import PreviewProbe, StyleName

type Values = np.ma.MaskedArray[Any, np.dtype[np.floating[Any]]]
type Rgba = npt.NDArray[np.uint8]
type Metres = npt.NDArray[np.float64] | float
type Resampling = Literal["nearest", "bilinear", "average"]

# Light of the hillshade: from the north-west, 45° above the horizon.
AZIMUTH_DEG = 315.0
ALTITUDE_DEG = 45.0
# Vertical exaggeration of the hillshade: the square root of the pixel's size
# in metres, within these bounds.
EXAGGERATION_RANGE = (1.0, 25.0)
# Colour of a class value without a colour of its own.
UNKNOWN_CLASS = (128, 128, 128, 255)
# Weights of red, green and blue in a luminance (ITU-R BT.601).
LUMA = (0.299, 0.587, 0.114)


@dataclass(frozen=True, slots=True)
class StyleContext:
    """What a style knows besides the values.

    Attributes
    ----------
    probe : PreviewProbe
        The file's probe: statistics, palette, class table, data type.
    rescale : tuple of float or None
        Range of the values asked for instead of the file's 2–98%.
    pixel_x_m, pixel_y_m : ndarray or float
        Size of a grid pixel on the ground in metres, across and down: one
        number, or one per row of the grid with its margin (rows, 1) where
        it changes with the latitude (EPSG:3857, geographic CRSs).
    """

    probe: PreviewProbe
    rescale: tuple[float, float] | None = None
    pixel_x_m: Metres = 1.0
    pixel_y_m: Metres = 1.0


@dataclass(frozen=True, slots=True)
class Style:
    """A style of raster previews.

    Attributes
    ----------
    name : StyleName
        Its name in ``STYLES`` and in requests.
    paint : callable
        ``(values, context) -> RGBA``: values (bands, rows, columns) with the
        margin, RGBA ``uint8`` (4, rows, columns) without it.
    pick : callable
        ``(data_bands) -> bands``: the bands it reads among the file's
        bands without alpha (1-based).
    margin_px : int
        Pixels of the neighbouring grid it looks at, on every side.
    resampling : Resampling
        How values are warped onto a grid.
    decimation : Resampling
        How values are read at a lower resolution.
    """

    name: StyleName
    paint: Callable[[Values, StyleContext], Rgba]
    pick: Callable[[Sequence[int]], tuple[int, ...]]
    margin_px: int = 0
    resampling: Resampling = "bilinear"
    decimation: Resampling = "average"

    @property
    def legend(self) -> LegendKind | None:
        """What the style's legend shows, if it has one."""
        return LEGEND_KINDS.get(self.name)

    def warping(self, probe: PreviewProbe) -> Resampling:
        """Return how a file's values are warped: palette indexes never blend."""
        return "nearest" if probe.palette else self.resampling

    def reading(self, probe: PreviewProbe) -> Resampling:
        """Return how a file's values are read decimated: palette indexes as such."""
        return "nearest" if probe.palette else self.decimation

    def bands(self, data_bands: Sequence[int]) -> tuple[int, ...]:
        """Return the bands the style reads among the file's data bands."""
        if not data_bands:
            raise ValueError("a raster without bands")
        return self.pick(data_bands)

    def apply(self, values: Values, context: StyleContext) -> Rgba:
        """Return RGBA (4, rows, columns) of values read with the margin.

        Raises
        ------
        ValueError
            Values without the margin around them.
        """
        margin = self.margin_px
        if values.ndim != 3 or min(values.shape[1:]) <= 2 * margin:
            raise ValueError(f"style {self.name} needs a margin of {margin} pixels")
        return self.paint(values, context)


def _color_bands(data_bands: Sequence[int]) -> tuple[int, ...]:
    return tuple(data_bands[:3]) if len(data_bands) >= 3 else (data_bands[0],)


def _first_band(data_bands: Sequence[int]) -> tuple[int, ...]:
    return (data_bands[0],)


def _rgb(values: Values, context: StyleContext) -> Rgba:
    probe = context.probe
    if values.shape[0] < 3 and probe.palette:
        return _classes(values, context, table=False)
    bands = [values[min(index, values.shape[0] - 1)] for index in range(3)]
    stretch = context.rescale is not None or probe.dtype != "uint8"
    channels = []
    for index, band in enumerate(bands):
        if stretch:
            low, high = _limits(probe, index, context.rescale, band)
            channels.append(_scaled(band, low, high))
        else:
            channels.append(np.clip(band.filled(0), 0, 255).astype(np.uint8))
    return _rgba(channels, _opaque(values))


def _gray(values: Values, context: StyleContext) -> Rgba:
    probe = context.probe
    if values.shape[0] >= 3:
        luma = sum(weight * values[index] for index, weight in enumerate(LUMA))
        band = np.ma.MaskedArray(luma)
        if context.rescale is not None:
            low, high = context.rescale
        else:
            limits = [_limits(probe, index, None, values[index]) for index in range(3)]
            low = sum(
                weight * limit[0] for weight, limit in zip(LUMA, limits, strict=True)
            )
            high = sum(
                weight * limit[1] for weight, limit in zip(LUMA, limits, strict=True)
            )
    else:
        band = values[0]
        low, high = _limits(probe, 0, context.rescale, band)
    gray = _scaled(band, low, high)
    return _rgba([gray, gray, gray], _opaque(values))


def _ramp(values: Values, context: StyleContext) -> Rgba:
    band = values[0]
    low, high = _limits(context.probe, 0, context.rescale, band)
    position = _fraction(band, low, high)
    stops = np.array([stop for stop, _ in RAMP])
    channels = [
        np.interp(position, stops, np.array([color[index] for _, color in RAMP]))
        .round()
        .astype(np.uint8)
        for index in range(3)
    ]
    return _rgba(channels, _opaque(values))


def _hillshade(values: Values, context: StyleContext) -> Rgba:
    heights = np.ma.filled(values[0].astype(np.float64), np.nan)
    rows, columns = heights.shape
    centre = heights[1:-1, 1:-1]

    def around(down: int, right: int) -> npt.NDArray[np.float64]:
        found = heights[1 + down : rows - 1 + down, 1 + right : columns - 1 + right]
        return np.where(np.isnan(found), centre, found)

    a, b, c = around(-1, -1), around(-1, 0), around(-1, 1)
    d, f = around(0, -1), around(0, 1)
    g, h, i = around(1, -1), around(1, 0), around(1, 1)
    pixel_x = _inner_rows(context.pixel_x_m)
    pixel_y = _inner_rows(context.pixel_y_m)
    dz_dx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * pixel_x)
    dz_dy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * pixel_y)
    exaggeration = np.clip(np.sqrt(np.sqrt(pixel_x * pixel_y)), *EXAGGERATION_RANGE)
    slope = np.arctan(exaggeration * np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(dz_dy, -dz_dx)
    zenith = math.radians(90.0 - ALTITUDE_DEG)
    azimuth = math.radians((360.0 - AZIMUTH_DEG + 90.0) % 360.0)
    light = math.cos(zenith) * np.cos(slope) + math.sin(zenith) * np.sin(
        slope
    ) * np.cos(azimuth - aspect)
    shade = np.nan_to_num(np.clip(light, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    opaque = ~np.isnan(centre)
    return _rgba([shade, shade, shade], opaque)


def _classes(values: Values, context: StyleContext, *, table: bool = True) -> Rgba:
    probe = context.probe
    band = values[0]
    valid = _opaque(values)
    codes = np.rint(np.ma.filled(band.astype(np.float64), 0.0)).astype(np.int64)
    rgba = np.zeros((4, *band.shape), dtype=np.uint8)
    if not valid.any():
        return rgba
    palette = {entry.value: entry.color for entry in probe.palette}
    found, inverse = np.unique(codes[valid], return_inverse=True)
    colors = np.array(
        [
            _class_color(int(code), palette, probe.class_table if table else None)
            for code in found
        ],
        dtype=np.uint8,
    )
    for channel in range(4):
        rgba[channel][valid] = colors[inverse, channel]
    return rgba


def _class_color(
    code: int, palette: Mapping[int, tuple[int, int, int, int]], table: str | None
) -> tuple[int, int, int, int]:
    color = palette.get(code)
    if color is not None:
        return color
    entry = class_entry(table, code)
    return UNKNOWN_CLASS if entry is None else (*entry.color, 255)


def _limits(
    probe: PreviewProbe,
    index: int,
    rescale: tuple[float, float] | None,
    band: Values,
) -> tuple[float, float]:
    """Return the range of a band's values shown: asked, the file's, the grid's."""
    if rescale is not None:
        return rescale
    if index < len(probe.stats):
        found = probe.stats[index]
        return found.p2, found.p98
    valid = band.compressed()
    if valid.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(valid, (2, 98))
    return float(low), float(high)


def _fraction(band: Values, low: float, high: float) -> npt.NDArray[np.float64]:
    """Return each value's position between ``low`` (0) and ``high`` (1)."""
    data = np.ma.filled(band.astype(np.float64), low)
    span = high - low
    if not math.isfinite(span) or span <= 0:
        return np.full(data.shape, 0.5)
    return np.clip((data - low) / span, 0.0, 1.0)


def _scaled(band: Values, low: float, high: float) -> npt.NDArray[np.uint8]:
    return (_fraction(band, low, high) * 255.0).round().astype(np.uint8)


def _opaque(values: Values) -> npt.NDArray[np.bool_]:
    """Pixels where every band has a value."""
    mask = np.ma.getmaskarray(values)
    finite = np.isfinite(np.ma.filled(values.astype(np.float64), 0.0))
    return np.asarray(~mask.any(axis=0) & finite.all(axis=0))


def _rgba(
    channels: Sequence[npt.NDArray[np.uint8]], opaque: npt.NDArray[np.bool_]
) -> Rgba:
    alpha = np.where(opaque, 255, 0).astype(np.uint8)
    rgba = np.stack([*channels, alpha]).astype(np.uint8)
    rgba[:3, ~opaque] = 0
    return rgba


def _inner_rows(metres: Metres) -> Metres:
    """Drop the hillshade's margin rows of a per-row pixel size."""
    if isinstance(metres, np.ndarray) and metres.ndim == 2 and metres.shape[0] > 2:
        return metres[1:-1]
    return metres


STYLES: Mapping[str, Style] = MappingProxyType(
    {
        "rgb": Style("rgb", _rgb, _color_bands),
        "gray": Style("gray", _gray, _color_bands),
        "hypsometry": Style("hypsometry", _ramp, _first_band),
        "elevation": Style("elevation", _ramp, _first_band),
        "hillshade": Style("hillshade", _hillshade, _first_band, margin_px=1),
        "classes": Style(
            "classes", _classes, _first_band, resampling="nearest", decimation="nearest"
        ),
    }
)
