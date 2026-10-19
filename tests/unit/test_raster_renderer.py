"""Raster previews: probe, thumbnail, map tile (plan v0.2, step 5a1; decisions 3–6).

The raster families of the test store (``tests.fixtures.store_files``, step
2) are read where they lie. Thumbnails and tiles are decoded PNGs; tiles
reach the map only through the operation Kartograf pins, compared with
``kartograf.pinned_transform`` itself.
"""

import hashlib
import time
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import kartograf
import morecantile
import numpy as np
import pytest
import rasterio
import rasterio.warp
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning, RasterioIOError
from rasterio.io import DatasetReader, MemoryFile
from rasterio.vrt import WarpedVRT

from archiwista.errors import PreviewUnavailableError
from archiwista.previews import tiles
from archiwista.previews.renderers.raster import RasterRenderer
from archiwista.previews.types import (
    AUTO_BUILD_MAX_PIXELS,
    Extent,
    PreviewProbe,
    PreviewSource,
    auto_build,
)
from tests.fixtures import store_files
from tests.fixtures.hostile_files import HUGE_SIZE_PX, hostile_files

# A 3.7 x 5.15 km rectangle near Kraków in EPSG:2180.
BOUNDS_2180 = (566_100.0, 241_050.0, 569_800.0, 246_200.0)
RENDERER = RasterRenderer()


def _sjtsk_bounds() -> tuple[float, float, float, float]:
    return store_files.reprojected_bounds(BOUNDS_2180, 2180, 5514)


# Family: file name, bytes, what the index knows of the version.
FAMILIES: dict[str, tuple[str, Callable[[], bytes], dict[str, Any]]] = {
    "classes": (
        "klasy.tif",
        lambda: store_files.geotiff_classes(
            store_files.reprojected_bounds(BOUNDS_2180, 2180, 3035), 3035, 1
        ),
        {"product": "corine"},
    ),
    "map": (
        "mapa.tif",
        lambda: store_files.geotiff_rgba_strips(BOUNDS_2180, 2180, 1),
        {"product": "topographic"},
    ),
    "oblique": (
        "ukosne.tif",
        lambda: store_files.geotiff_tiled_overviews(
            store_files.reprojected_bounds(BOUNDS_2180, 2180, 2177), 2177, 1
        ),
        {"product": "oblique-orto"},
    ),
    "soil": (
        "gleba.tif",
        lambda: store_files.geotiff_wgs84(
            store_files.reprojected_bounds(BOUNDS_2180, 2180, 4326), 1
        ),
        {"product": "soil"},
    ),
    "asc": (
        "nmt.asc",
        lambda: store_files.asc_grid(BOUNDS_2180, 1),
        {"crs": "EPSG:2180", "product": "nmt"},
    ),
    "xyz": (
        "nmt.xyz",
        lambda: store_files.xyz_grid(BOUNDS_2180, 1),
        {"crs": "EPSG:2180", "product": "nmt"},
    ),
    "jpeg": (
        "arkusz.jpg",
        lambda: store_files.jpeg(1),
        {"georeference": Extent(_sjtsk_bounds(), "EPSG:5514")},
    ),
    "png": ("podglad.png", lambda: store_files.png_image(1), {"product": "corine"}),
}
ON_MAP = ("classes", "map", "oblique", "soil", "asc", "xyz", "jpeg")


def _source(path: Path, **known: Any) -> PreviewSource:
    content = hashlib.sha256(path.read_bytes()).hexdigest()
    return PreviewSource(f"version:test:{path.name}", content, (path,), **known)


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


def _directory_state(path: Path) -> dict[str, tuple[int, int]]:
    return {
        item.name: (item.stat().st_size, item.stat().st_mtime_ns)
        for item in path.iterdir()
    }


@pytest.fixture(scope="module")
def families(tmp_path_factory: pytest.TempPathFactory) -> dict[str, PreviewSource]:
    """Write each raster family once; return its source as the index gives it."""
    directory = tmp_path_factory.mktemp("rastry")
    sources = {}
    for family, (name, encode, known) in FAMILIES.items():
        path = directory / name
        path.write_bytes(encode())
        sources[family] = _source(path, **known)
    return sources


@pytest.fixture
def read_shapes(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """Record the ``out_shape`` of every raster read (``None``: full resolution)."""
    shapes: list[Any] = []
    original = DatasetReader.read

    def spy(self: DatasetReader, *args: Any, **kwargs: Any) -> Any:
        shapes.append(kwargs.get("out_shape"))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DatasetReader, "read", spy)
    yield shapes


@pytest.mark.parametrize("family", list(FAMILIES))
def test_raster_family_thumbnail_decodes(
    families: dict[str, PreviewSource], family: str
) -> None:
    """Every family has a thumbnail: RGBA PNG at most 256 px a side, drawn."""
    # Arrange
    source = families[family]
    probe = RENDERER.probe(source)
    assert probe.default_style is not None

    # Act
    image = _decoded(RENDERER.thumbnail(source, probe, probe.default_style, 256, None))

    # Assert
    assert image.shape[0] == 4
    expected = min(256, max(probe.width or 0, probe.height or 0))
    assert max(image.shape[1:]) == expected
    assert (image[3] == 255).any()


@pytest.mark.parametrize("family", ON_MAP)
def test_raster_family_tile_has_alpha(
    families: dict[str, PreviewSource], family: str
) -> None:
    """A tile is 256 x 256 RGBA: the raster opaque, the rest of the tile clear."""
    # Arrange
    source = families[family]
    probe = RENDERER.probe(source)
    assert probe.reason is None and probe.minzoom is not None
    assert probe.default_style is not None
    z, x, y = _tile_at(probe, max(0, probe.minzoom - 1))

    # Act
    image = _decoded(RENDERER.tile(source, probe, probe.default_style, z, x, y, {}))

    # Assert
    assert image.shape == (4, 256, 256)
    assert (image[3] == 255).any() and (image[3] == 0).any()


def test_raster_nodata_transparent(families: dict[str, PreviewSource]) -> None:
    """``nodata`` corners (CORINE 48, SoilGrids -32768) are transparent."""
    # Arrange
    classes, soil = families["classes"], families["soil"]
    classes_probe, soil_probe = RENDERER.probe(classes), RENDERER.probe(soil)

    # Act
    corine = _decoded(RENDERER.thumbnail(classes, classes_probe, "classes", 256, None))
    clay = _decoded(RENDERER.thumbnail(soil, soil_probe, "hypsometry", 64, None))

    # Assert: 16 of 512 pixels at 256 px, 8 of 64 pixels at 64 px.
    assert (corine[3, -8:, -8:] == 0).all() and (corine[3, :-8, :-8] == 255).all()
    assert (clay[3, -8:, -8:] == 0).all() and (clay[3, :-8, :-8] == 255).all()


def test_png_without_georeference_thumbnail_only(
    families: dict[str, PreviewSource],
) -> None:
    """A WMS preview PNG: a thumbnail, no map place (``no_georeference``)."""
    # Arrange
    source = families["png"]

    # Act
    probe = RENDERER.probe(source)

    # Assert
    assert probe.reason == "no_georeference"
    assert (probe.bbox_wgs84, probe.minzoom, probe.needs_cog) == (None, None, False)
    assert _decoded(RENDERER.thumbnail(source, probe, "rgb", 128, None)).shape[0] == 4
    with pytest.raises(PreviewUnavailableError) as raised:
        RENDERER.tile(source, probe, "rgb", 10, 568, 347, {})
    assert raised.value.reason == "no_georeference"


def test_tile_forces_pinned_operation(
    families: dict[str, PreviewSource], monkeypatch: pytest.MonkeyPatch
) -> None:
    """EPSG:2177 is warped with Kartograf's pinned operation; EPSG:4326 plainly.

    ``reproject`` gets ``COORDINATE_OPERATION`` equal to
    ``kartograf.pinned_transform(crs, "EPSG:3857").gdal_operation()``; a CRS
    on the WGS84 ellipsoid gets none (Kartograf pins no such conversion).
    """
    # Arrange
    calls: list[dict[str, Any]] = []
    original = rasterio.warp.reproject

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(tiles, "reproject", spy)
    pinned = kartograf.pinned_transform("EPSG:2177", "EPSG:3857").gdal_operation()
    drawn = {}

    # Act
    for family in ("oblique", "soil"):
        source = families[family]
        probe = RENDERER.probe(source)
        assert probe.maxzoom is not None and probe.default_style is not None
        z, x, y = _tile_at(probe, probe.maxzoom - 2)
        drawn[family] = _decoded(
            RENDERER.tile(source, probe, probe.default_style, z, x, y, {})
        )

    # Assert
    oblique, soil = calls
    assert oblique["dst_crs"] == "EPSG:3857"
    assert oblique["COORDINATE_OPERATION"] == pinned
    assert "COORDINATE_OPERATION" not in soil
    assert all((image[3] == 255).any() for image in drawn.values())


def test_raster_without_overviews_read_decimated(
    families: dict[str, PreviewSource], read_shapes: list[Any]
) -> None:
    """A 4160 px map without overviews: statistics and thumbnail decimated.

    Every read asks for at most 1024 pixels a side; the statistics are those
    of the decimated values (numpy), never GDAL's.
    """
    # Arrange
    source = families["map"]

    # Act
    probe = RENDERER.probe(source)
    png = RENDERER.thumbnail(source, probe, "rgb", 256, None)
    shapes = list(read_shapes)

    # Assert
    assert probe.overviews == () and probe.tiled is False
    assert shapes and all(
        shape is not None and max(shape[1:]) <= 1024 for shape in shapes
    )
    with rasterio.open(source.paths[0], driver="GTiff") as dataset:
        red = dataset.read(
            1, out_shape=(1024, 1024), masked=True, resampling=Resampling.nearest
        )
        assert not any("STATISTICS" in tag for tag in dataset.tags(1))
    low, high = np.percentile(red.compressed(), (2, 98))
    assert (probe.stats[0].p2, probe.stats[0].p98) == (float(low), float(high))
    assert _decoded(png).shape == (4, 256, 256)


def test_huge_declared_raster_needs_build(tmp_path: Path) -> None:
    """100 000 x 100 000 px in a few hundred kB: ``needs_build``, never auto-built.

    The probe samples windows instead of reading the whole raster, and a
    thumbnail waits for the local COG ("Zbuduj podgląd").
    """
    # Arrange
    planted = hostile_files(tmp_path / "pliki")
    source = _source(planted.huge_raster)

    # Act
    started = time.perf_counter()
    probe = RENDERER.probe(source)
    seconds = time.perf_counter() - started

    # Assert
    assert seconds < 10
    assert (probe.width, probe.height) == (HUGE_SIZE_PX, HUGE_SIZE_PX)
    assert probe.pixels is not None and probe.pixels > AUTO_BUILD_MAX_PIXELS
    assert probe.needs_cog and probe.reason is None
    assert not auto_build(source, probe)
    with pytest.raises(PreviewUnavailableError) as raised:
        RENDERER.thumbnail(source, probe, "gray", 256, None)
    assert raised.value.reason == "too_large"


def test_vrt_under_raster_names_never_read(tmp_path: Path) -> None:
    """VRT XML named ``.tif`` and ``.asc`` is refused, also after a WarpedVRT.

    A ``WarpedVRT`` registers GDAL's VRT driver again in the process (as
    rio-tiler does); the explicit driver still refuses the file, so the
    target's pixels are never read.
    """
    # Arrange
    planted = hostile_files(tmp_path / "pliki")
    with (
        rasterio.open(planted.ovr_base, driver="GTiff") as dataset,
        WarpedVRT(dataset, crs="EPSG:3857"),
    ):
        pass

    for path in planted.vrt_rasters:
        # Act / Assert
        with pytest.raises(RasterioIOError):
            RENDERER.probe(_source(path, crs="EPSG:2180"))


def test_probe_and_renders_leave_folder_unchanged(
    tmp_path: Path, families: dict[str, PreviewSource]
) -> None:
    """No ``.aux.xml`` or other file appears beside the data (decision 3)."""
    # Arrange
    folder = tmp_path / "dane"
    folder.mkdir()
    sources = {}
    for family in ("classes", "oblique", "soil", "asc"):
        path = folder / families[family].paths[0].name
        path.write_bytes(families[family].paths[0].read_bytes())
        sources[family] = _source(path, **FAMILIES[family][2])
    before = _directory_state(folder)

    # Act
    for source in sources.values():
        probe = RENDERER.probe(source)
        assert probe.default_style is not None
        RENDERER.thumbnail(source, probe, probe.default_style, 256, None)
        z, x, y = _tile_at(probe, probe.maxzoom or 10)
        RENDERER.tile(source, probe, probe.default_style, z, x, y, {})

    # Assert
    assert _directory_state(folder) == before
