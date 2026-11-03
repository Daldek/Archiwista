"""Vector features drawn into RGBA thumbnails and map tiles (plan v0.2, step 5b).

The vector renderer (``archiwista.previews.renderers.vector``) draws what it
read on a ``Canvas`` over a ``Grid`` of pixels: polygons filled
half-transparent with an opaque outline, lines one pixel wide (every pixel
they touch), points as round markers of ``MARKER_RADIUS_PX``; a polygon or
a line within one pixel is that pixel. Each layer has its colour
(``LAYER_COLORS``), later layers lie over earlier ones, and where nothing is
drawn the image is transparent, so thumbnails and tiles of several files
compose over each other (step 5a3). Pixels come from GDAL
(``rasterio.features.rasterize``) and numpy, the PNG from rio-tiler
(``archiwista.previews.tiles.encode_png``).

Only render processes import this module.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import shapely
from rasterio.features import rasterize
from rasterio.transform import Affine

from archiwista.previews.tiles import encode_png, grid_transform
from archiwista.previews.types import BBox

type Color = tuple[int, int, int]
type Geometries = npt.NDArray[np.object_]
type Covered = npt.NDArray[np.bool_]

# Colours of the layers drawn together, in their order.
LAYER_COLORS: tuple[Color, ...] = ((31, 119, 180), (214, 39, 40), (44, 160, 44))
# Opacity of a polygon's fill; outlines, lines and markers are opaque.
FILL_ALPHA = 0.35
# Radius of a point's marker in pixels (a disc 2 r + 1 pixels across).
MARKER_RADIUS_PX = 3
# Pixels a feature outside a grid may still reach into it (a marker).
REACH_PX = MARKER_RADIUS_PX + 1

_POINT = shapely.GeometryType.POINT
_POLYGON = shapely.GeometryType.POLYGON
_LINES = (shapely.GeometryType.LINESTRING, shapely.GeometryType.LINEARRING)
_COMPOUND = (
    shapely.GeometryType.MULTIPOINT,
    shapely.GeometryType.MULTILINESTRING,
    shapely.GeometryType.MULTIPOLYGON,
    shapely.GeometryType.GEOMETRYCOLLECTION,
)


@dataclass(frozen=True, slots=True)
class Grid:
    """Pixels covering a rectangle of a CRS, the first row at its north.

    Parameters
    ----------
    bounds : BBox
        ``(min_x, min_y, max_x, max_y)`` in the drawing CRS.
    width, height : int
        Pixels across and down.

    Raises
    ------
    ValueError
        No pixels, or a rectangle without area.
    """

    bounds: BBox
    width: int
    height: int

    def __post_init__(self) -> None:
        """Refuse a grid without pixels or area."""
        min_x, min_y, max_x, max_y = self.bounds
        if self.width < 1 or self.height < 1:
            raise ValueError("a grid has at least one pixel")
        if not (min_x < max_x and min_y < max_y):
            raise ValueError(f"a grid covers a rectangle, not {self.bounds}")

    @property
    def transform(self) -> Affine:
        """Return the affine transform from pixels to the drawing CRS."""
        return grid_transform(self.bounds, self.width, self.height)

    @property
    def pixel_width(self) -> float:
        """Return a pixel's width in units of the drawing CRS."""
        return (self.bounds[2] - self.bounds[0]) / self.width

    @property
    def pixel_height(self) -> float:
        """Return a pixel's height in units of the drawing CRS."""
        return (self.bounds[3] - self.bounds[1]) / self.height


class Canvas:
    """An RGBA image drawn layer by layer, transparent where nothing is drawn.

    Parameters
    ----------
    grid : Grid
        The pixels; geometries come in its CRS.
    """

    def __init__(self, grid: Grid) -> None:
        self.grid = grid
        shape = (grid.height, grid.width)
        # Colour premultiplied by alpha: painting over is two products.
        self._color = np.zeros((3, *shape), dtype=np.float32)
        self._alpha = np.zeros(shape, dtype=np.float32)

    def draw(self, geometries: Geometries, color: Color) -> None:
        """Draw geometries in one colour over what is drawn already.

        Parameters
        ----------
        geometries : ndarray of shapely geometries
            In the grid's CRS; missing and empty ones are skipped.
        color : Color
            ``(r, g, b)``.
        """
        parts = _simple_parts(geometries)
        kinds = shapely.get_type_id(parts)
        points = kinds == _POINT
        dots = ~points & self._within_a_pixel(parts)
        polygons = parts[(kinds == _POLYGON) & ~dots]
        lines = parts[np.isin(kinds, _LINES) & ~dots]
        if polygons.size:
            self._paint(self._burn(polygons, all_touched=False), color, FILL_ALPHA)
            outlines = shapely.boundary(polygons)
            self._paint(self._burn(outlines, all_touched=True), color, 1.0)
        if lines.size:
            self._paint(self._burn(lines, all_touched=True), color, 1.0)
        if dots.any():
            self._paint(self._dots(parts[dots]), color, 1.0)
        if points.any():
            self._paint(self._markers(parts[points]), color, 1.0)

    def png(self) -> bytes:
        """Return the image as an RGBA PNG."""
        alpha = self._alpha
        color = np.divide(
            self._color, alpha, out=np.zeros_like(self._color), where=alpha > 0
        )
        rgba = np.empty((4, self.grid.height, self.grid.width), dtype=np.uint8)
        rgba[:3] = np.clip(np.rint(color), 0, 255)
        rgba[3] = np.clip(np.rint(alpha * 255.0), 0, 255)
        return encode_png(rgba)

    def _within_a_pixel(self, parts: Geometries) -> Covered:
        """Which parts fit in one pixel's width and height (drawn as dots)."""
        bounds = np.asarray(shapely.bounds(parts), dtype=np.float64)
        narrow = bounds[:, 2] - bounds[:, 0] < self.grid.pixel_width
        return narrow & (bounds[:, 3] - bounds[:, 1] < self.grid.pixel_height)

    def _burn(self, geometries: Geometries, *, all_touched: bool) -> Covered:
        """Return the pixels the geometries cover (``all_touched``: every one met)."""
        grid = self.grid
        burnt = rasterize(
            geometries,
            out_shape=(grid.height, grid.width),
            transform=grid.transform,
            fill=0,
            default_value=1,
            all_touched=all_touched,
            dtype="uint8",
        )
        return np.asarray(burnt, dtype=bool)

    def _dots(self, parts: Geometries) -> Covered:
        """Return the pixel at the centre of every part."""
        bounds = shapely.bounds(parts)
        xs = (bounds[:, 0] + bounds[:, 2]) / 2.0
        ys = (bounds[:, 1] + bounds[:, 3]) / 2.0
        return self._discs(xs, ys, radius=0)

    def _markers(self, points: Geometries) -> Covered:
        """Return a disc of ``MARKER_RADIUS_PX`` around every point."""
        xs, ys = shapely.get_coordinates(points).T
        return self._discs(xs, ys, radius=MARKER_RADIUS_PX)

    def _discs(
        self, xs: npt.NDArray[np.float64], ys: npt.NDArray[np.float64], *, radius: int
    ) -> Covered:
        """Return the pixels of a disc of ``radius`` around every position."""
        grid = self.grid
        columns, rows = ~grid.transform * (xs, ys)
        centre_columns = np.floor(columns).astype(np.int64)
        centre_rows = np.floor(rows).astype(np.int64)
        covered = np.zeros((grid.height, grid.width), dtype=bool)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy > radius * radius:
                    continue
                row, column = centre_rows + dy, centre_columns + dx
                inside = (row >= 0) & (row < grid.height)
                inside &= (column >= 0) & (column < grid.width)
                covered[row[inside], column[inside]] = True
        return covered

    def _paint(self, covered: Covered, color: Color, opacity: float) -> None:
        """Paint ``color`` at ``opacity`` over the covered pixels."""
        source = covered.astype(np.float32) * np.float32(opacity)
        kept = 1.0 - source
        for band, value in enumerate(color):
            self._color[band] = np.float32(value) * source + self._color[band] * kept
        self._alpha = source + self._alpha * kept


def draw_png(grid: Grid, layers: Sequence[Geometries]) -> bytes:
    """Draw layers on a transparent grid and return the RGBA PNG.

    Parameters
    ----------
    grid : Grid
        The pixels.
    layers : sequence of ndarray of shapely geometries
        Geometries of each layer in the grid's CRS, the first drawn first,
        in the colours of ``LAYER_COLORS`` (repeated past their number).

    Returns
    -------
    bytes
        The PNG.
    """
    canvas = Canvas(grid)
    for index, geometries in enumerate(layers):
        canvas.draw(geometries, LAYER_COLORS[index % len(LAYER_COLORS)])
    return canvas.png()


def _simple_parts(geometries: Geometries) -> Geometries:
    """Split multi-part geometries and collections into simple non-empty parts."""
    parts: Geometries = np.asarray(geometries, dtype=object)
    parts = parts[~shapely.is_missing(parts)]
    while parts.size and np.isin(shapely.get_type_id(parts), _COMPOUND).any():
        parts = np.asarray(shapely.get_parts(parts), dtype=object)
    simple: Geometries = parts[~shapely.is_empty(parts)]
    return simple
