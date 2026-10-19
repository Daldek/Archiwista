"""Styles and legends of raster previews (plan v0.2, step 5a3; decision 5).

Hillshade tiles meet without a seam, the hypsometric ramp follows the
file's 2–98% or a ``rescale``, gray stretches 2–98%, and class rasters
(CORINE with its palette, HSG by its table) are coloured as their legend
says, with Polish class names.
"""

import hashlib
import warnings
from pathlib import Path
from typing import Any

import morecantile
import numpy as np
import pytest
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from archiwista.previews import tiles
from archiwista.previews.legends import RAMP, legend
from archiwista.previews.renderers.raster import RasterRenderer
from archiwista.previews.types import Extent, PreviewProbe, PreviewSource
from tests.fixtures import store_files
from tests.fixtures.store_files import CLC_CLASSES

BOUNDS_2180 = (566_100.0, 241_050.0, 569_800.0, 246_200.0)
RENDERER = RasterRenderer()
# West and north edge of the test rasters in EPSG:2180, 1 m pixels.
ORIGIN = (566_100.0, 246_200.0)


def _source(path: Path, **known: Any) -> PreviewSource:
    content = hashlib.sha256(path.read_bytes()).hexdigest()
    return PreviewSource(f"version:test:{path.name}", content, (path,), **known)


def _raster(path: Path, values: np.ndarray[Any, Any], *, nodata: float | None) -> Path:
    rows, columns = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=columns,
        height=rows,
        count=1,
        dtype=values.dtype.name,
        crs="EPSG:2180",
        transform=from_origin(*ORIGIN, 1.0, 1.0),
        nodata=nodata,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dataset:
        dataset.write(values, 1)
    return path


def _relief(size: int) -> np.ndarray[Any, Any]:
    """Hills of 30 m on a slope: heights in metres, float32."""
    rows, columns = np.indices((size, size), dtype=np.float64)
    hills = 30.0 * np.sin(columns / 40.0) * np.cos(rows / 55.0)
    return (120.0 + hills + 0.02 * columns).astype(np.float32)


def _decoded(png: bytes) -> np.ndarray[Any, Any]:
    with warnings.catch_warnings(), MemoryFile(png) as memory:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with memory.open(driver="PNG") as image:
            return np.asarray(image.read())


def _tile_at(probe: PreviewProbe, zoom: int) -> tuple[int, int, int]:
    assert probe.bbox_wgs84 is not None
    west, south, east, north = probe.bbox_wgs84
    found = morecantile.tms.get("WebMercatorQuad").tile(
        (west + east) / 2, (south + north) / 2, zoom
    )
    return found.z, found.x, found.y


def _colors(image: np.ndarray[Any, Any]) -> set[str]:
    """Colours ``#rrggbb`` of the opaque pixels of an RGBA image."""
    opaque = image[3] == 255
    found = {tuple(pixel) for pixel in image[:3, opaque].T.tolist()}
    return {f"#{r:02x}{g:02x}{b:02x}" for r, g, b in found}


@pytest.fixture(scope="module")
def relief(tmp_path_factory: pytest.TempPathFactory) -> PreviewSource:
    """Write a 1200 m square DEM (1 m pixels) of the product ``nmt``."""
    path = tmp_path_factory.mktemp("nmt") / "nmt.tif"
    return _source(_raster(path, _relief(1200), nodata=-9999.0), product="nmt")


def test_hillshade_tiles_meet_without_seam(relief: PreviewSource) -> None:
    """Four hillshade tiles side by side equal one rendering of their square.

    Each tile is warped with a margin of 1 pixel of its neighbours, so the
    slopes at its edges see the pixels across them; without the margin the
    edge rows and columns would be shaded as flat land (a seam).
    """
    # Arrange
    probe = RENDERER.probe(relief)
    assert probe.default_style == "hillshade" and probe.maxzoom is not None
    z, x, y = _tile_at(probe, probe.maxzoom - 2)
    west, _, _, north = tiles.tile_bounds(z, x, y)
    _, south, east, _ = tiles.tile_bounds(z, x + 1, y + 1)
    square = Extent((west, south, east, north), tiles.WEB_MERCATOR)

    # Act
    def shade(column: int, row: int) -> np.ndarray[Any, Any]:
        image = _decoded(RENDERER.tile(relief, probe, "hillshade", z, column, row, {}))
        assert (image[3] == 255).all()
        return np.asarray(image[0], dtype=np.float64)

    mosaic = np.block(
        [[shade(x, y), shade(x + 1, y)], [shade(x, y + 1), shade(x + 1, y + 1)]]
    )
    whole = _decoded(RENDERER.thumbnail(relief, probe, "hillshade", 512, square))

    # Assert
    difference = np.abs(mosaic - whole[0].astype(np.float64))
    assert whole.shape == (4, 512, 512)
    assert difference[:, 254:258].max() <= 2 and difference[254:258, :].max() <= 2
    assert difference.mean() < 0.1
    assert mosaic.std() > 5  # the relief shows


def test_hypsometry_legend_from_percentiles_and_rescale(relief: PreviewSource) -> None:
    """The ramp spans the file's 2–98% (metres), or exactly the ``rescale``."""
    # Arrange
    probe = RENDERER.probe(relief)
    z, x, y = _tile_at(probe, (probe.maxzoom or 18) - 2)
    first, last = RAMP[0][1], RAMP[-1][1]

    # Act
    own = legend(probe, "hypsometry")
    asked = legend(probe, "hypsometry", rescale=(1000.0, 2000.0))
    below = _decoded(
        RENDERER.tile(relief, probe, "hypsometry", z, x, y, {"rescale": [1000, 2000]})
    )
    above = _decoded(
        RENDERER.tile(relief, probe, "hypsometry", z, x, y, {"rescale": [-20, -10]})
    )

    # Assert
    assert own is not None and asked is not None
    assert (own["kind"], own["unit"]) == ("gradient", "m")
    assert (own["min"], own["max"]) == (probe.stats[0].p2, probe.stats[0].p98)
    assert 90.0 < own["min"] < own["max"] < 175.0
    assert (asked["min"], asked["max"]) == (1000.0, 2000.0)
    assert own["colors"][0] == "#{:02x}{:02x}{:02x}".format(*first)
    assert _colors(below) == {"#{:02x}{:02x}{:02x}".format(*first)}
    assert _colors(above) == {"#{:02x}{:02x}{:02x}".format(*last)}


def test_gray_stretches_2_to_98_percent(tmp_path: Path) -> None:
    """Gray maps the file's 2nd percentile to black and its 98th to white."""
    # Arrange
    columns = np.tile(np.arange(1000, 2000, dtype=np.uint16), (100, 1))
    source = _source(_raster(tmp_path / "skan.tif", columns, nodata=None))
    probe = RENDERER.probe(source)

    # Act
    image = _decoded(RENDERER.thumbnail(source, probe, "gray", 1000, None))

    # Assert
    assert probe.styles == ("hypsometry", "hillshade", "gray")
    gray = image[0]
    assert (gray[:, :15] == 0).all() and (gray[:, -15:] == 255).all()
    assert 120 <= int(gray[0, 500]) <= 136


def test_classes_corine_palette_and_legend(tmp_path: Path) -> None:
    """CORINE: the file's palette colours the classes; the legend names them."""
    # Arrange
    path = tmp_path / "clc.tif"
    path.write_bytes(
        store_files.geotiff_classes(
            store_files.reprojected_bounds(BOUNDS_2180, 2180, 3035), 3035, 5
        )
    )
    source = _source(path, product="corine")
    probe = RENDERER.probe(source)

    # Act
    found = legend(probe, "classes")
    image = _decoded(RENDERER.thumbnail(source, probe, "classes", 512, None))

    # Assert
    assert found is not None and found["kind"] == "classes"
    items = {item["value"]: item for item in found["items"]}
    assert sorted(items) == sorted(CLC_CLASSES)
    assert items[1]["label"] == "111 Zabudowa miejska zwarta"
    assert items[23]["label"] == "311 Lasy liściaste"
    for value, (_, rgb) in CLC_CLASSES.items():
        assert items[value]["color"] == "#{:02x}{:02x}{:02x}".format(*rgb)
    assert _colors(image) == {item["color"] for item in items.values()}


def test_classes_hsg_table_and_legend(tmp_path: Path) -> None:
    """HSG without a palette: colours and names of groups A–D from the table."""
    # Arrange
    rows, columns = np.indices((400, 400))
    values = (1 + (columns // 100)).astype(np.uint8)
    values[rows < 20] = 0
    source = _source(_raster(tmp_path / "hsg.tif", values, nodata=0), product="hsg")
    probe = RENDERER.probe(source)
    z, x, y = _tile_at(probe, (probe.maxzoom or 18) - 4)

    # Act
    found = legend(probe, "classes")
    tile = _decoded(RENDERER.tile(source, probe, "classes", z, x, y, {}))

    # Assert
    assert probe.styles == ("classes",) and probe.class_table == "hsg"
    assert found is not None
    labels = [item["label"] for item in found["items"]]
    assert [item["value"] for item in found["items"]] == [1, 2, 3, 4]
    assert labels[0].startswith("Grupa A: duża infiltracja")
    assert labels[3].startswith("Grupa D: bardzo mała infiltracja")
    assert _colors(tile) <= {item["color"] for item in found["items"]}
    assert (tile[3] == 0).any()  # nodata and the world around: transparent
