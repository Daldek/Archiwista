"""Point clouds: header, ASPRS classes from a bounded sample, 2D image (decision 5).

The class counts are checked against laspy reading the whole file, an
independent reader of the same records.
"""

import io
import struct
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import pytest
import rasterio

from archiwista.messages import MESSAGES
from archiwista.previews.renderers import points
from archiwista.previews.renderers.points import PointsRenderer, read_cloud
from archiwista.previews.types import PreviewSource
from tests.fixtures.store_files import LAZ_CLASSES, LAZ_POINTS, las_points, laz_points

_KEY = "c" * 64
_BOUNDS = (500_000.0, 300_000.0, 501_000.0, 301_000.0)  # EPSG:2180


def _source(path: Path, crs: str | None = None) -> PreviewSource:
    return PreviewSource(f"file:p:{path.name}", _KEY, (path,), crs=crs)


def _counts(data: bytes, first: int | None = None) -> dict[int, int]:
    classes = np.asarray(laspy.read(io.BytesIO(data)).classification)[:first]
    values, counts = np.unique(classes, return_counts=True)
    return {int(v): int(n) for v, n in zip(values, counts, strict=True)}


def _classes(probe_points: dict[str, Any]) -> dict[int, int]:
    return {item["value"]: item["count"] for item in probe_points["classes"]}


@pytest.fixture(scope="module")
def laz_bytes() -> bytes:
    """Return the store fixture's compressed LAZ (three chunks, classes 2, 3, 6)."""
    return laz_points(_BOUNDS, 7)


def test_points_probe_laz_counts_classes_2_3_6(
    tmp_path: Path, laz_bytes: bytes
) -> None:
    """The compressed LAZ: header, CRS from its VLR, every point's class counted."""
    # Arrange
    path = tmp_path / "chmura.laz"
    path.write_bytes(laz_bytes)

    # Act
    probe = PointsRenderer().probe(_source(path))

    # Assert
    found = probe.points
    assert found is not None
    assert (probe.driver, probe.crs, probe.reason) == ("LAZ", "EPSG:2180", None)
    assert found["point_count"] == LAZ_POINTS
    assert (found["version"], found["point_format"]) == ("1.4", 6)
    assert (found["sampled_from"], found["sample_points"]) == ("all", LAZ_POINTS)
    assert sorted(_classes(found)) == list(LAZ_CLASSES)
    assert _classes(found) == _counts(laz_bytes)
    assert [item["label"] for item in found["classes"]] == [
        "Grunt",
        "Niska roślinność",
        "Budynki",
    ]
    assert probe.bbox_wgs84 is not None and probe.needs_cog
    assert probe.styles == ("elevation",)


def test_points_sample_spread_over_chunks(
    tmp_path: Path, laz_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sample smaller than the cloud takes the start of every chunk."""
    # Arrange
    monkeypatch.setattr(points, "SAMPLE_MAX_POINTS", 30_000)
    path = tmp_path / "chmura.laz"
    path.write_bytes(laz_bytes)
    with path.open("rb") as stream:
        cloud = read_cloud(stream)

    # Act
    windows, sampled_from = points.sample_windows(cloud)
    probe = PointsRenderer().probe(_source(path))

    # Assert
    assert sampled_from == "spread"
    assert [(w.start, w.count, w.chunk) for w in windows] == [
        (0, 10_000, 0),
        (50_000, 10_000, 1),
        (100_000, 10_000, 2),
    ]
    assert probe.points is not None
    assert probe.points["sample_points"] == 30_000
    assert probe.points["sampled_from"] == "spread"


def test_points_laz_without_chunk_table_sampled_from_start(
    tmp_path: Path, laz_bytes: bytes
) -> None:
    """A LAZ written as a stream (no chunk table): its first chunk, marked."""
    # Arrange
    with laspy.open(io.BytesIO(laz_bytes)) as reader:
        start = reader.header.offset_to_point_data
    (table_at,) = struct.unpack_from("<q", laz_bytes, start)
    stream_laz = bytearray(laz_bytes[:table_at])
    stream_laz[start : start + 8] = struct.pack("<q", -1)
    path = tmp_path / "strumien.laz"
    path.write_bytes(bytes(stream_laz))

    # Act
    probe = PointsRenderer().probe(_source(path))

    # Assert
    assert probe.points is not None
    assert probe.points["chunk_table"] is False
    assert probe.points["sampled_from"] == "start"
    assert probe.points["sample_points"] == 50_000
    assert _classes(probe.points) == _counts(laz_bytes, first=50_000)


def test_points_uncompressed_las_named_laz(tmp_path: Path) -> None:
    """A v0.1 store's LAS under a ``.laz`` name: plain records, CRS from the index."""
    # Arrange
    path = tmp_path / "v01.laz"
    path.write_bytes(las_points(_BOUNDS, 3, points=9))
    renderer = PointsRenderer()

    # Act
    without_crs = renderer.probe(_source(path))
    with_crs = renderer.probe(_source(path, crs="EPSG:2180"))

    # Assert
    assert without_crs.driver == "LAS"
    assert without_crs.points is not None
    assert _classes(without_crs.points) == {2: 9}
    assert (without_crs.reason, without_crs.needs_cog) == ("no_crs", False)
    assert MESSAGES["preview_reason_no_crs"]
    assert (with_crs.crs, with_crs.reason, with_crs.needs_cog) == (
        "EPSG:2180",
        None,
        True,
    )


def test_points_large_extra_bytes_sample_bounded_by_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Records with ~7 KB of extra bytes: the sample stops at the byte limit."""
    # Arrange
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.add_extra_dims(
        [
            laspy.ExtraBytesParams(name=f"pole{index}", type="3f8")
            for index in range(300)
        ]
    )
    cloud = laspy.LasData(header)
    count = 400
    cloud.x = np.linspace(_BOUNDS[0], _BOUNDS[2], count)
    cloud.y = np.linspace(_BOUNDS[1], _BOUNDS[3], count)
    cloud.z = np.full(count, 150.0)
    cloud.classification = np.full(count, 5, dtype=np.uint8)
    buffer = io.BytesIO()
    cloud.write(buffer)
    path = tmp_path / "dodatkowe.las"
    path.write_bytes(buffer.getvalue())
    record_bytes = header.point_format.size
    monkeypatch.setattr(points, "SAMPLE_MAX_BYTES", 1024**2)

    # Act
    probe = PointsRenderer().probe(_source(path, crs="EPSG:2180"))

    # Assert
    assert probe.points is not None
    assert record_bytes > 7_000
    limit = 1024**2 // record_bytes
    assert probe.points["sampled_from"] == "spread"
    assert probe.points["sample_points"] <= limit
    assert probe.points["sample_points"] >= limit - points.SAMPLE_WINDOWS
    assert _classes(probe.points) == {5: probe.points["sample_points"]}


def test_points_build_writes_max_z_cog(tmp_path: Path, laz_bytes: bytes) -> None:
    """The 2D image: highest Z per cell ≥ 1 m, as a georeferenced COG."""
    # Arrange
    path = tmp_path / "chmura.laz"
    path.write_bytes(laz_bytes)
    renderer = PointsRenderer()
    probe = renderer.probe(_source(path))
    out = tmp_path / "cog.tif"

    # Act
    renderer.build(_source(path), probe, out)

    # Assert
    with laspy.open(io.BytesIO(laz_bytes)) as reader:
        top = float(reader.header.maxs[2])
    with rasterio.open(out) as dataset:
        image = dataset.read(1, masked=True)
        assert dataset.crs.to_epsg() == 2180
        assert dataset.res[0] >= points.GRID_MIN_CELL_M
        assert (dataset.width, dataset.height) == (probe.width, probe.height)
        assert dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"
    assert image.max() == pytest.approx(top, abs=0.01)
    assert image.count() > 0


def test_points_thumbnail_is_png_of_sample(tmp_path: Path, laz_bytes: bytes) -> None:
    """The thumbnail needs no build: the sample's heights as an image."""
    path = tmp_path / "chmura.laz"
    path.write_bytes(laz_bytes)
    renderer = PointsRenderer()
    probe = renderer.probe(_source(path))

    png = renderer.thumbnail(_source(path), probe, "elevation", 256, None)

    width, height = struct.unpack(">II", png[16:24])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert max(width, height) == 256
