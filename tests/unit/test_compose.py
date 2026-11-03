"""Layers composed from their versions (plan v0.2, step 5a3; decisions 4 and 7).

Real render processes (``RenderPool`` with the production renderers) draw
a layer's thumbnail in a planar frame and its map tiles from the versions'
own previews, which stay in the preview cache under the versions' content.
Expected positions come from Kartograf's pinned operation itself.
"""

import hashlib
import json
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import kartograf
import morecantile
import numpy as np
import pytest
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from archiwista.previews.cache import (
    PreviewCache,
    cache_key,
    thumbnail_name,
    tile_name,
)
from archiwista.previews.compose import layer_tile_target
from archiwista.previews.pool import RenderPool
from archiwista.previews.types import JsonObject, PreviewSource
from tests.fixtures import store_files

RED, GREEN, BLUE = (200, 0, 0), (0, 160, 0), (0, 0, 200)
# Two sheets side by side in EPSG:2180 and one far to the east.
WEST_SHEET = (566_000.0, 245_000.0, 567_000.0, 246_000.0)
EAST_SHEET = (567_000.0, 245_000.0, 568_000.0, 246_000.0)
FAR_SHEET = (580_000.0, 245_000.0, 581_000.0, 246_000.0)


def _sheet(
    path: Path, bounds: tuple[float, ...], epsg: int, rgb: tuple[int, ...]
) -> Path:
    """Write a uniform RGB GeoTIFF sheet of 500 x 500 pixels."""
    size = 500
    bands = np.stack([np.full((size, size), value, dtype=np.uint8) for value in rgb])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=3,
        dtype="uint8",
        crs=f"EPSG:{epsg}",
        transform=from_bounds(*bounds, size, size),
        tiled=True,
        blockxsize=256,
        blockysize=256,
        photometric="RGB",
    ) as dataset:
        dataset.write(bands)
    return path


def _source(path: Path) -> PreviewSource:
    content = hashlib.sha256(path.read_bytes()).hexdigest()
    return PreviewSource(f"version:test:{path.name}", content, (path,), product="orto")


def _decoded(png: bytes) -> np.ndarray[Any, Any]:
    with warnings.catch_warnings(), MemoryFile(png) as memory:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with memory.open(driver="PNG") as image:
            return np.asarray(image.read())


def _versions(pool: RenderPool, sources: list[PreviewSource]) -> list[JsonObject]:
    """Return the layer's versions as the index gives them: source, WGS84 bounds."""
    versions = []
    for source in sources:
        bounds = pool.request("probe", source).probe().bbox_wgs84
        assert bounds is not None
        versions.append({"source": source.to_json(), "bounds": list(bounds)})
    return versions


def _moved(x: float, y: float, src: str, dst: str) -> tuple[float, float]:
    moved_x, moved_y = kartograf.pinned_transform(src, dst).transform(x, y)
    return float(moved_x), float(moved_y)


@pytest.fixture
def pool(tmp_path: Path) -> Iterator[RenderPool]:
    """Yield a render pool of one production render process and its cache."""
    with (
        PreviewCache(tmp_path / "previews", limit_bytes=10**9) as cache,
        RenderPool(workers=1, cache=cache, work_dir=tmp_path / "work") as found,
    ):
        yield found


def test_layer_thumbnail_in_planar_frame(tmp_path: Path, pool: RenderPool) -> None:
    """Sheets in EPSG:2180 and EPSG:2177 lie where they are in a 2180 frame.

    The 2177 sheet is warped into the frame with the pinned operation; its
    centre lands where Kartograf's operation puts it. Around the sheets the
    thumbnail is transparent, and each sheet's own framed thumbnail stays
    in the cache under its content.
    """
    # Arrange
    south = (566_000.0, 244_000.0, 567_000.0, 245_000.0)
    sheet_2177 = store_files.reprojected_bounds(south, 2180, 2177)
    west = _source(_sheet(tmp_path / "zachod.tif", WEST_SHEET, 2180, RED))
    other = _source(_sheet(tmp_path / "poludnie.tif", sheet_2177, 2177, GREEN))
    frame = {"bbox": [565_800.0, 243_800.0, 567_200.0, 246_200.0], "crs": "EPSG:2180"}
    params = {
        "versions": _versions(pool, [west, other]),
        "frame": frame,
        "style": "rgb",
        "size": 256,
    }

    # Act
    image = _decoded(pool.request("layer_thumbnail", None, params).data)

    # Assert
    rows, columns = image.shape[1:]
    assert (rows, columns) == (256, 149)

    def pixel(x: float, y: float) -> tuple[int, ...]:
        column = int((x - 565_800.0) / 1400.0 * columns)
        row = int((246_200.0 - y) / 2400.0 * rows)
        return tuple(int(value) for value in image[:, row, column])

    centre_x, centre_y = _moved(
        (sheet_2177[0] + sheet_2177[2]) / 2,
        (sheet_2177[1] + sheet_2177[3]) / 2,
        "EPSG:2177",
        "EPSG:2180",
    )
    assert pixel(566_500.0, 245_500.0) == (*RED, 255)
    assert pixel(centre_x, centre_y) == (*GREEN, 255)
    assert image[3, 0, 0] == 0 and image[3, -1, -1] == 0
    framed = thumbnail_name(
        "rgb", 256, json.dumps(frame, sort_keys=True, separators=(",", ":"))
    )
    assert all(pool.cache.has(cache_key(source), framed) for source in (west, other))


def test_layer_tile_composes_version_tiles(tmp_path: Path, pool: RenderPool) -> None:
    """A tile on the edge of two sheets has pixels of both.

    The versions' own tiles stay in the cache under their content, the
    composite is kept too, and a new ready version changes the composite's
    key only in the tiles it meets.
    """
    # Arrange
    west = _source(_sheet(tmp_path / "zachod.tif", WEST_SHEET, 2180, RED))
    east = _source(_sheet(tmp_path / "wschod.tif", EAST_SHEET, 2180, BLUE))
    far = _source(_sheet(tmp_path / "daleko.tif", FAR_SHEET, 2180, GREEN))
    versions = _versions(pool, [west, east, far])
    grid = morecantile.tms.get("WebMercatorQuad")
    edge = grid.tile(*_moved(567_000.0, 245_500.0, "EPSG:2180", "EPSG:4326"), 15)
    remote = grid.tile(*_moved(580_500.0, 245_500.0, "EPSG:2180", "EPSG:4326"), 15)
    tile = {"z": edge.z, "x": edge.x, "y": edge.y, "style": "rgb"}

    # Act
    found = pool.request("layer_tile", None, {"versions": versions[:2], **tile})
    again = pool.request("layer_tile", None, {"versions": versions[:2], **tile})

    # Assert
    image = _decoded(found.data)
    opaque = image[3] == 255
    colours = {tuple(pixel) for pixel in image[:3, opaque].T.tolist()}
    assert colours == {RED, BLUE}
    assert (image[3] == 0).any()  # the world beyond both sheets
    assert not found.cached and again.cached
    name = tile_name("rgb", edge.z, edge.x, edge.y)
    assert all(pool.cache.has(cache_key(source), name) for source in (west, east))

    def key(chosen: list[JsonObject], at: Any) -> str:
        params = {"versions": chosen, "z": at.z, "x": at.x, "y": at.y, "style": "rgb"}
        return layer_tile_target(None, params)[0].content_key

    assert key(versions, edge) == key(versions[:2], edge)
    assert key(versions, remote) != key(versions[:2], remote)
