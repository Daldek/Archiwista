"""Local COG of rasters (plan v0.2, step 5a2; decision 6).

A file whose tiles cannot come from it directly gets a COG in the preview
cache: ASC and XYZ grids, a JPEG sheet georeferenced by its header
outline, a GeoTIFF in strips larger than 4096 px. The COG is read back with
rasterio: its CRS and extent, size, layout, compression and values.
"""

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio

from archiwista.errors import PreviewUnavailableError
from archiwista.previews.cog import MAX_SIDE_PX
from archiwista.previews.renderers.raster import RasterRenderer
from archiwista.previews.types import Extent, PreviewSource, build_product
from tests.fixtures import store_files
from tests.fixtures.store_files import CLC_CLASSES, CLC_NODATA

BOUNDS_2180 = (566_100.0, 241_050.0, 569_800.0, 246_200.0)
RENDERER = RasterRenderer()


def _source(path: Path, data: bytes, **known: Any) -> PreviewSource:
    path.write_bytes(data)
    content = hashlib.sha256(data).hexdigest()
    return PreviewSource(f"version:test:{path.name}", content, (path,), **known)


def _built(source: PreviewSource, out: Path) -> Path:
    probe = RENDERER.probe(source)
    assert probe.needs_cog and build_product(probe) == "cog.tif"
    RENDERER.build(source, probe, out)
    return out


def _wide_asc(columns: int, rows: int) -> bytes:
    min_x, min_y = BOUNDS_2180[:2]
    header = (
        f"ncols {columns}\nnrows {rows}\nxllcorner {min_x}\nyllcorner {min_y}\n"
        "cellsize 0.5\nNODATA_value -9999\n"
    )
    line = " ".join(str(100 + column % 50) for column in range(columns))
    return (header + "\n".join([line] * rows) + "\n").encode("ascii")


def test_asc_cog_at_most_8192_px_with_index_crs(tmp_path: Path) -> None:
    """An ASC grid 9000 px wide: a tiled COG ≤ 8192 px in the index's CRS."""
    # Arrange
    source = _source(
        tmp_path / "nmt.asc", _wide_asc(9000, 4), crs="EPSG:2180", product="nmt"
    )

    # Act
    cog = _built(source, tmp_path / "cog.tif")

    # Assert
    with rasterio.open(cog, driver="GTiff") as dataset:
        assert dataset.crs.to_epsg() == 2180
        assert dataset.width == MAX_SIDE_PX and dataset.height == 4
        assert dataset.bounds.left == pytest.approx(BOUNDS_2180[0])
        assert dataset.bounds.right == pytest.approx(BOUNDS_2180[0] + 4500.0)
        assert dataset.profile["tiled"] and dataset.block_shapes[0] == (512, 512)
        assert dataset.overviews(1)
        assert dataset.profile["compress"] == "deflate"


def test_xyz_grid_cog(tmp_path: Path) -> None:
    """A regular XYZ grid gets a COG over the grid's cells in the index's CRS."""
    # Arrange
    source = _source(
        tmp_path / "nmt.xyz",
        store_files.xyz_grid(BOUNDS_2180, 7),
        crs="EPSG:2180",
        product="nmt",
    )

    # Act
    cog = _built(source, tmp_path / "cog.tif")

    # Assert
    with rasterio.open(cog, driver="GTiff") as dataset:
        assert dataset.crs.to_epsg() == 2180
        assert tuple(dataset.bounds) == pytest.approx(BOUNDS_2180)
        assert int(dataset.read(1)[0, 0]) == 7


def test_ungridded_xyz_unsupported_format(tmp_path: Path) -> None:
    """Points that are no regular grid: ``unsupported_format``, no COG."""
    # Arrange
    points = b"0.0 0.0 1\n1.3 0.2 2\n2.1 5.7 3\n7.0 1.1 4\n"
    source = _source(tmp_path / "punkty.xyz", points, crs="EPSG:2180")

    # Act / Assert
    with pytest.raises(PreviewUnavailableError) as raised:
        RENDERER.probe(source)
    assert raised.value.reason == "unsupported_format"


def test_striped_map_over_4096_px_cog(tmp_path: Path) -> None:
    """A 4160 px RGBA map in strips: a JPEG COG, its transparency as a mask."""
    # Arrange
    source = _source(
        tmp_path / "mapa.tif",
        store_files.geotiff_rgba_strips(BOUNDS_2180, 2180, 1),
        product="topographic",
    )

    # Act
    cog = _built(source, tmp_path / "cog.tif")

    # Assert
    with rasterio.open(cog, driver="GTiff") as dataset:
        assert (dataset.width, dataset.count) == (store_files.STRIPED_SIZE_PX, 3)
        assert dataset.profile["compress"] == "jpeg" and dataset.overviews(1)
        mask = dataset.dataset_mask()
        eighth = store_files.STRIPED_SIZE_PX // 8
        assert (mask[: eighth - 1, : eighth - 1] == 0).all()
        assert (mask[eighth + 1 :, eighth + 1 :] == 255).all()


def test_jpeg_with_header_outline_georeferenced(tmp_path: Path) -> None:
    """A JPEG sheet takes its header outline (S-JTSK) into its COG."""
    # Arrange
    bounds = store_files.reprojected_bounds(BOUNDS_2180, 2180, 5514)
    source = _source(
        tmp_path / "arkusz.jpg",
        store_files.jpeg(3),
        georeference=Extent(bounds, "EPSG:5514"),
    )

    # Act
    probe = RENDERER.probe(source)
    cog = _built(source, tmp_path / "cog.tif")

    # Assert
    assert probe.crs == "EPSG:5514" and probe.bbox_native == pytest.approx(bounds)
    assert probe.bbox_wgs84 is not None
    with rasterio.open(cog, driver="GTiff") as dataset:
        assert dataset.crs.to_epsg() == 5514
        assert tuple(dataset.bounds) == pytest.approx(bounds)


def test_jpeg_without_header_outline_no_georeference(tmp_path: Path) -> None:
    """A JPEG whose outline comes from elsewhere: a thumbnail, no map, no COG."""
    # Arrange
    source = _source(tmp_path / "arkusz.jpg", store_files.jpeg(4), crs="EPSG:5514")

    # Act
    probe = RENDERER.probe(source)

    # Assert
    assert probe.reason == "no_georeference"
    assert not probe.needs_cog and build_product(probe) is None


def _checkerboard_classes(path: Path, size: int) -> bytes:
    """HSG classes 1 and 4 alternating pixel by pixel, nodata 0 in a corner."""
    rows, columns = np.indices((size, size))
    values = np.where((rows + columns) % 2 == 0, 1, 4).astype(np.uint8)
    values[:64, :64] = 0
    transform = rasterio.transform.from_origin(500_000.0, 300_000.0, 1.0, 1.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="uint8",
        crs="EPSG:2180",
        transform=transform,
        nodata=0,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dataset:
        dataset.write(values, 1)
    return path.read_bytes()


def test_classes_cog_nearest_values(tmp_path: Path) -> None:
    """A class raster's COG and every overview hold class values only.

    Classes 1 and 4 alternate pixel by pixel: an averaged overview would
    show 2 and 3, the nearest value keeps 1 and 4.
    """
    # Arrange
    path = tmp_path / "hsg.tif"
    source = _source(path, _checkerboard_classes(path, 2048), product="hsg")
    probe = RENDERER.probe(source)
    out = tmp_path / "cog.tif"

    # Act
    RENDERER.build(source, probe, out)

    # Assert
    assert probe.class_table == "hsg" and probe.styles == ("classes",)
    with rasterio.open(out, driver="GTiff") as dataset:
        assert set(np.unique(dataset.read(1)).tolist()) == {0, 1, 4}
        levels = len(dataset.overviews(1))
    assert levels >= 2
    for level in range(levels):
        with rasterio.open(out, driver="GTiff", OVERVIEW_LEVEL=level) as overview:
            assert set(np.unique(overview.read(1)).tolist()) <= {0, 1, 4}


def test_palette_kept_in_cog(tmp_path: Path) -> None:
    """A CORINE raster's COG keeps its palette."""
    # Arrange
    source = _source(
        tmp_path / "klasy.tif",
        store_files.geotiff_classes(
            store_files.reprojected_bounds(BOUNDS_2180, 2180, 3035), 3035, 2
        ),
        product="corine",
    )
    probe = RENDERER.probe(source)
    out = tmp_path / "cog.tif"

    # Act
    RENDERER.build(source, probe, out)

    # Assert
    with rasterio.open(out, driver="GTiff") as dataset:
        assert set(np.unique(dataset.read(1)).tolist()) <= {*CLC_CLASSES, CLC_NODATA}
        assert dataset.colormap(1)[1][:3] == CLC_CLASSES[1][1]
