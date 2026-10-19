"""Vector previews: layers, thumbnails, tiles, features (plan v0.2, step 5b).

Files are written by GDAL (pyogrio), as a desktop GIS writes them, or come
from the store and own-data fixtures. A position on the map is checked
against the pinned operation (``tiles.transformer``) applied to the position
written in the file; a simplified geometry's deviation is measured in pixels
of the map (EPSG:3857) at the request's zoom.
"""

import hashlib
import os
import sqlite3
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import morecantile
import numpy as np
import numpy.typing as npt
import pyogrio.raw
import pytest
import rasterio
import shapely
from rasterio.errors import NotGeoreferencedWarning

from archiwista.errors import FormatRefusedError, PreviewUnavailableError
from archiwista.previews import tiles
from archiwista.previews.protocol import RenderRequest, encode_request
from archiwista.previews.rasterize import FILL_ALPHA, LAYER_COLORS
from archiwista.previews.renderers.vector import (
    FEATURES_MAX_VERTICES,
    VectorRenderer,
)
from archiwista.previews.types import (
    SOURCE_GPKG_NAME,
    BBox,
    Extent,
    JsonObject,
    PreviewProbe,
    PreviewSource,
    build_product,
)
from archiwista.previews.worker import answer_line
from tests.fixtures import store_files
from tests.fixtures.control_points import POINT_3722
from tests.fixtures.hostile_files import SECRET_TEXT, hostile_files
from tests.fixtures.own_data import GpkgEditor, OwnFamily, make_own_folder

_STORE_BOUNDS = (566_000.0, 241_000.0, 570_000.0, 245_000.0)  # EPSG:2180, Kraków
_BASIN = shapely.box(566_200, 241_200, 566_300, 241_300)
_WGS84 = "EPSG:4326"
_GRID = morecantile.tms.get("WebMercatorQuad")


@pytest.fixture
def renderer(tmp_path: Path) -> VectorRenderer:
    """Return the renderer with a work directory of its own."""
    work = tmp_path / "work"
    work.mkdir()
    return VectorRenderer(work_dir=work)


def _source(path: Path, *, mutable: bool = False) -> PreviewSource:
    key = hashlib.sha256(str(path).encode()).hexdigest()
    return PreviewSource(f"file:p:{path.name}", key, (path,), mutable=mutable)


def _store_gpkg(tmp_path: Path) -> PreviewSource:
    path = tmp_path / "bdot.gpkg"
    path.write_bytes(store_files.geopackage_layers(_STORE_BOUNDS, 2180, 7))
    return _source(path)


def _write_gpkg(
    path: Path,
    layer: str,
    geometries: Sequence[shapely.Geometry],
    crs: str,
    names: Sequence[str] | None = None,
) -> None:
    """Write one GeoPackage layer through GDAL with a ``nazwa`` per feature."""
    values = list(names) if names else [f"o{index}" for index in range(len(geometries))]
    pyogrio.raw.write(
        path,
        np.array([shapely.to_wkb(geometry) for geometry in geometries], dtype=object),
        [np.array(values, dtype=object)],
        ["nazwa"],
        layer=layer,
        driver="GPKG",
        geometry_type=geometries[0].geom_type,
        crs=crs,
    )


def _rgba(png: bytes) -> npt.NDArray[np.uint8]:
    with (
        warnings.catch_warnings(category=NotGeoreferencedWarning, action="ignore"),
        rasterio.MemoryFile(png) as memory,
        memory.open() as image,
    ):
        assert (image.driver, image.count) == ("PNG", 4)
        data: npt.NDArray[np.uint8] = image.read()
    return data


def _opaque_colours(image: npt.NDArray[np.uint8]) -> set[tuple[int, int, int]]:
    rows, columns = np.nonzero(image[3] == 255)
    return {
        (int(image[0, r, c]), int(image[1, r, c]), int(image[2, r, c]))
        for r, c in zip(rows, columns, strict=True)
    }


def _wgs84(crs: str, x: float, y: float) -> tuple[float, float]:
    """Position in WGS84 by the pinned operation the renderer uses."""
    lons, lats = tiles.transformer(crs, _WGS84).transform(np.array([x]), np.array([y]))
    return float(lons[0]), float(lats[0])


def _around(lon: float, lat: float, half: float) -> BBox:
    return lon - half, lat - half, lon + half, lat + half


def _wider(bbox: Any, margin: float = 0.01) -> BBox:
    west, south, east, north = bbox
    return west - margin, south - margin, east + margin, north + margin


def _names(collection: JsonObject) -> list[str]:
    return sorted(str(item["properties"]["nazwa"]) for item in collection["features"])


def _listing(root: Path) -> dict[str, tuple[int, int] | None]:
    """Every file and directory under ``root`` with its size and time (lstat).

    ``-shm`` is the editor's shared memory: SQLite may change its content.
    """
    found: dict[str, tuple[int, int] | None] = {}
    for directory, names, files in os.walk(root):
        for name in [*names, *files, "."]:
            path = Path(directory, name)
            stat = path.lstat()
            relative = path.relative_to(root).as_posix()
            found[relative] = (
                None if name.endswith("-shm") else (stat.st_size, stat.st_mtime_ns)
            )
    return found


def _probe_answer(source: PreviewSource, renderer: VectorRenderer) -> JsonObject:
    """Run ``probe`` as a render process does: code and detail of a failure."""
    line = encode_request(RenderRequest("1", "probe", source, {}))
    answer = answer_line(line, (renderer,))
    return {"code": answer.code, "detail": answer.detail, "files": answer.files}


def test_vector_gpkg_layers_with_fields_crs_extents_and_sample(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """Two layers of a store GeoPackage as GDAL reads them, in info.json form."""
    # Arrange
    source = _store_gpkg(tmp_path)

    # Act
    probe = renderer.probe(source)

    # Assert
    lines, polygons = probe.layers
    corners = [
        _wgs84("EPSG:2180", x, y)
        for x in (566_000.0, 570_000.0)
        for y in (241_000.0, 245_000.0)
    ]
    assert probe.bbox_wgs84 is not None
    west, south, east, north = probe.bbox_wgs84
    assert (probe.kind, probe.driver, probe.crs, probe.reason) == (
        "vector",
        "GPKG",
        "EPSG:2180",
        None,
    )
    assert [
        (layer["name"], layer["geometry_type"], layer["feature_count"])
        for layer in probe.layers
    ] == [
        ("swrs", "LineString", 3),
        ("ptwp", "Polygon", 2),
    ]
    assert lines["fields"] == [
        {"name": "nazwa", "type": "String"},
        {"name": "szerokosc_m", "type": "Integer64"},
    ]
    assert lines["sample"] == [
        {"nazwa": "7", "szerokosc_m": 12},
        {"nazwa": "Potok", "szerokosc_m": 3},
        {"nazwa": "Rów", "szerokosc_m": 1},
    ]
    assert polygons["bbox"] == [566_800.0, 241_800.0, 569_200.0, 244_200.0]
    assert probe.bbox_native == _STORE_BOUNDS
    assert all(west <= lon <= east and south <= lat <= north for lon, lat in corners)
    assert (probe.needs_copy, build_product(probe)) == (False, None)
    assert (probe.styles, probe.default_style) == (("features",), "features")
    assert PreviewProbe.from_bytes(probe.to_bytes()) == probe


def test_vector_thumbnail_polygons_and_lines_transparent_elsewhere(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """Fills half-transparent, strokes opaque, background clear; one chosen layer."""
    # Arrange
    source = _store_gpkg(tmp_path)
    probe = renderer.probe(source)
    frame = Extent((565_000.0, 240_000.0, 571_000.0, 243_000.0), "EPSG:2180")
    polygon_colour, line_colour = LAYER_COLORS[0], LAYER_COLORS[1]

    # Act
    whole = _rgba(renderer.thumbnail(source, probe, "features", 256, None))
    chosen = _rgba(
        renderer.thumbnail(source, probe, "features", 256, None, layer="ptwp")
    )
    framed = _rgba(renderer.thumbnail(source, probe, "features", 200, frame))

    # Assert
    assert whole.shape == (4, 256, 256)
    assert {0, round(FILL_ALPHA * 255), 255} <= set(np.unique(whole[3]).tolist())
    assert {polygon_colour, line_colour} <= _opaque_colours(whole)
    assert _opaque_colours(chosen) == {polygon_colour}
    assert framed.shape == (4, 100, 200)
    assert (framed[3] == 255).any() and (framed[3] == 0).any()


def test_vector_tile_coloured_over_features_transparent_elsewhere(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """A tile inside a polygon is its fill; a tile away from the data is empty."""
    # Arrange
    source = _store_gpkg(tmp_path)
    probe = renderer.probe(source)
    lon, lat = _wgs84("EPSG:2180", 567_300.0, 242_300.0)  # inside the pond "Staw"
    inside = _GRID.tile(lon, lat, 17)
    away = _GRID.tile(lon + 1.0, lat, 17)

    # Act
    filled = _rgba(renderer.tile(source, probe, "features", 17, inside.x, inside.y, {}))
    empty = _rgba(renderer.tile(source, probe, "features", 17, away.x, away.y, {}))

    # Assert
    assert filled.shape == empty.shape == (4, 256, 256)
    assert int(filled[3, 128, 128]) == round(FILL_ALPHA * 255)
    assert tuple(int(band) for band in filled[:3, 128, 128]) == LAYER_COLORS[0]
    assert not empty[3].any()


def test_vector_shapefile_layer_unnamed_read_with_its_members(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """A Shapefile's layer has no name (the file's) but its ``.dbf`` and ``.prj``."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("shp_full",))
    source = _source(folder.path("shp_full"), mutable=True)

    # Act
    probe = renderer.probe(source)
    found = renderer.features(source, probe, None, _wider(probe.bbox_wgs84), 14, 100)

    # Assert
    (layer,) = probe.layers
    assert layer["name"] is None
    assert "dzialki" not in probe.to_bytes().decode()
    assert (layer["geometry_type"], layer["feature_count"], layer["crs"]) == (
        "Polygon",
        2,
        "EPSG:2180",
    )
    assert sorted(item["properties"]["numer"] for item in found["features"]) == [
        "12/3",
        "12/4",
    ]
    assert (found["number_matched"], found["truncated"]) == (2, False)


def test_vector_shapefile_without_prj_no_crs_thumbnail_only(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """Without ``.prj``: ``no_crs``, a thumbnail in the file's own coordinates."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("shp_no_prj",))
    source = _source(folder.path("shp_no_prj"), mutable=True)
    frame = Extent(_STORE_BOUNDS, "EPSG:2180")

    # Act
    probe = renderer.probe(source)
    thumbnail = _rgba(renderer.thumbnail(source, probe, "features", 128, None))

    # Assert
    assert (probe.reason, probe.crs, probe.bbox_wgs84) == ("no_crs", None, None)
    assert (thumbnail[3] == 255).any()
    with pytest.raises(PreviewUnavailableError) as features:
        renderer.features(source, probe, None, (19.9, 50.0, 20.0, 50.1), 14, 100)
    with pytest.raises(PreviewUnavailableError) as framed:
        renderer.thumbnail(source, probe, "features", 128, frame)
    assert features.value.reason == framed.value.reason == "no_crs"


@pytest.mark.parametrize(
    ("family", "geometry_type", "crs", "field"),
    [
        ("geojson_wgs84", "Point", "EPSG:4326", "opis"),
        ("fgb", "LineString", "EPSG:2180", "klasa"),
    ],
)
def test_vector_geojson_and_flatgeobuf_features_where_written(
    tmp_path: Path,
    renderer: VectorRenderer,
    family: OwnFamily,
    geometry_type: str,
    crs: str,
    field: str,
) -> None:
    """Every feature in WGS84 at the pinned position of what the file holds."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=(family,))
    path = folder.path(family)
    source = _source(path, mutable=True)
    _, _, wkb, fields = pyogrio.raw.read(path, force_2d=True)
    written = [shapely.get_coordinates(shapely.from_wkb(item)) for item in wkb]
    expected = sorted(
        (str(value), [_wgs84(crs, x, y) for x, y in coordinates])
        for value, coordinates in zip(fields[0], written, strict=True)
    )

    # Act
    probe = renderer.probe(source)
    found = renderer.features(source, probe, None, _wider(probe.bbox_wgs84), 16, 100)

    # Assert
    (layer,) = probe.layers
    got = sorted(
        (
            str(item["properties"][field]),
            [
                tuple(position)
                for position in shapely.get_coordinates(
                    shapely.geometry.shape(item["geometry"])
                )
            ],
        )
        for item in found["features"]
    )
    assert (layer["name"], layer["geometry_type"], layer["crs"]) == (
        None,
        geometry_type,
        crs,
    )
    assert [value for value, _ in got] == [value for value, _ in expected]
    for (_, positions), (_, wanted) in zip(got, expected, strict=True):
        assert np.allclose(positions, wanted, atol=1e-7, rtol=0.0)


def test_vector_features_limit_5000_and_truncated(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """``limit + 1`` features read: more than the limit is ``truncated``."""
    # Arrange
    path = tmp_path / "punkty.gpkg"
    xs, ys = np.meshgrid(np.arange(71) * 10.0, np.arange(71) * 10.0)
    points = list(shapely.points(566_000.0 + xs.ravel(), 241_000.0 + ys.ravel()))
    _write_gpkg(path, "punkty", points, "EPSG:2180")
    source = _source(path)
    probe = renderer.probe(source)
    lon, lat = _wgs84("EPSG:2180", 566_000.0, 241_000.0)

    # Act
    everything = renderer.features(
        source, probe, "punkty", _wider(probe.bbox_wgs84), 15, 5000
    )
    corner = renderer.features(
        source, probe, "punkty", _around(lon, lat, 0.00003), 18, 5000
    )

    # Assert
    assert len(points) == 5041
    assert (everything["number_returned"], everything["truncated"]) == (5000, True)
    assert everything["number_matched"] is None
    assert (corner["number_returned"], corner["number_matched"]) == (1, 1)
    assert corner["truncated"] is False


def _toothed(centre: tuple[float, float], radius_m: float) -> shapely.Polygon:
    """Return a star of 50 000 vertices: teeth of 60 m, over a pixel at zoom 12."""
    angles = np.linspace(0.0, 2 * np.pi, 50_000, endpoint=False)
    radii = np.where(np.arange(50_000) % 2 == 0, radius_m, radius_m + 60.0)
    return shapely.Polygon(
        np.column_stack(
            [centre[0] + radii * np.cos(angles), centre[1] + radii * np.sin(angles)]
        )
    )


def _smooth(centre: tuple[float, float], radius_m: float) -> shapely.Polygon:
    """Return a circle of 50 000 vertices with 2 cm of noise: below any pixel."""
    angles = np.linspace(0.0, 2 * np.pi, 50_000, endpoint=False)
    radii = radius_m + np.where(np.arange(50_000) % 2 == 0, 0.0, 0.02)
    return shapely.Polygon(
        np.column_stack(
            [centre[0] + radii * np.cos(angles), centre[1] + radii * np.sin(angles)]
        )
    )


def _deviation_px(original: shapely.Polygon, returned: JsonObject, zoom: int) -> float:
    """Return the farthest vertex of ``original`` from the outline, in map pixels."""
    to_wgs84 = tiles.transformer("EPSG:2180", _WGS84)
    to_map = tiles.transformer(_WGS84, tiles.WEB_MERCATOR)
    xs, ys = shapely.get_coordinates(original).T
    map_xs, map_ys = to_map.transform(*to_wgs84.transform(xs, ys))
    outline = shapely.geometry.shape(returned).exterior
    map_outline = shapely.transform(outline, to_map.transform, interleaved=False)
    distances = shapely.distance(shapely.points(map_xs, map_ys), map_outline)
    return float(np.max(distances)) / tiles.tile_resolution(zoom)


def test_features_simplified_to_zoom(tmp_path: Path, renderer: VectorRenderer) -> None:
    """Simplified to half a pixel: ≤ 500 000 vertices, deviation ≤ 1 pixel.

    Twelve toothed polygons of 50 000 vertices keep their teeth at zoom 12
    and fill the vertex budget (``truncated``); a smooth one loses its
    vertices yet stays within a pixel at zoom 12 and at zoom 19.
    """
    # Arrange
    centres = [
        (470_000.0 + 25_000.0 * (i % 4), 300_000.0 + 25_000.0 * (i // 4))
        for i in range(12)
    ]
    toothed = [_toothed(centre, 8_000.0) for centre in centres]
    smooth = _smooth((520_000.0, 400_000.0), 2_000.0)
    path = tmp_path / "ksztalty.gpkg"
    _write_gpkg(path, "zebate", toothed, "EPSG:2180")
    _write_gpkg(path, "gladkie", [smooth], "EPSG:2180")
    source = _source(path)
    probe = renderer.probe(source)
    edge_lon, edge_lat = _wgs84("EPSG:2180", 522_000.0, 400_000.0)

    # Act
    teeth = renderer.features(
        source, probe, "zebate", _wider(probe.layers[0]["bbox_wgs84"]), 12, 5000
    )
    coarse = renderer.features(
        source, probe, "gladkie", _wider(probe.layers[1]["bbox_wgs84"]), 12, 5000
    )
    fine = renderer.features(
        source, probe, "gladkie", _around(edge_lon, edge_lat, 0.0005), 19, 5000
    )

    # Assert
    vertices = [
        len(shapely.get_coordinates(shapely.geometry.shape(item["geometry"])))
        for item in teeth["features"]
    ]
    (coarse_feature,) = coarse["features"]
    (fine_feature,) = fine["features"]
    coarse_vertices = len(
        shapely.get_coordinates(shapely.geometry.shape(coarse_feature["geometry"]))
    )
    assert sum(vertices) <= FEATURES_MAX_VERTICES
    assert teeth["truncated"] is True and teeth["number_matched"] == 12
    assert 0 < len(vertices) < 12 and min(vertices) > 45_000
    assert coarse["simplified"] is True and coarse_vertices < 1_000
    assert _deviation_px(smooth, coarse_feature["geometry"], 12) <= 1.0
    assert _deviation_px(smooth, fine_feature["geometry"], 19) <= 1.0


@pytest.mark.parametrize(
    ("crs", "centre"),
    [("EPSG:2180", (566_000.0, 241_000.0)), ("EPSG:5514", POINT_3722.epsg5514)],
)
def test_vector_view_rectangle_moved_into_file_crs(
    tmp_path: Path, renderer: VectorRenderer, crs: str, centre: tuple[float, float]
) -> None:
    """A WGS84 view finds the point under it, not its neighbours 1 km away."""
    # Arrange
    x0, y0 = centre
    offsets = [
        (dx, dy) for dx in (-1000.0, 0.0, 1000.0) for dy in (-1000.0, 0.0, 1000.0)
    ]
    points = [shapely.Point(x0 + dx, y0 + dy) for dx, dy in offsets]
    names = [f"{dx:+.0f}{dy:+.0f}" for dx, dy in offsets]
    path = tmp_path / "siatka.gpkg"
    _write_gpkg(path, "siatka", points, crs, names)
    source = _source(path)
    probe = renderer.probe(source)
    lon, lat = _wgs84(crs, x0, y0)

    # Act
    found = renderer.features(source, probe, None, _around(lon, lat, 0.002), 17, 100)

    # Assert
    (item,) = found["features"]
    assert item["properties"]["nazwa"] == "+0+0"
    assert item["geometry"]["coordinates"] == pytest.approx([lon, lat], abs=1e-7)


def test_vector_ogr_vrt_under_vector_names_never_reads_its_target(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """OGR VRT XML named ``.gpkg``, ``.geojson``, ``.shp``, ``.fgb`` is refused."""
    # Arrange
    planted = hostile_files(tmp_path / "dane")

    # Act
    answers = {
        path.name: _probe_answer(_source(path), renderer)
        for path in planted.ogr_vrt_vectors
    }

    # Assert
    assert sorted(answers) == ["vrt.fgb", "vrt.geojson", "vrt.gpkg", "vrt.shp"]
    for name, answer in answers.items():
        assert answer["code"] in ("unsupported_format", "unreadable"), name
        assert answer["files"] == {}, name
        assert SECRET_TEXT not in str(answer["detail"]), name


def test_vector_shapefile_with_linked_member_refused(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """A ``.dbf`` that is a symbolic link would make GDAL read another file."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("shp_full",))
    outside = tmp_path / "poza.dbf"
    dbf = folder.root / "dzialki.dbf"
    dbf.rename(outside)
    dbf.symlink_to(outside)

    # Act
    with pytest.raises(FormatRefusedError):
        renderer.probe(_source(folder.path("shp_full"), mutable=True))


def _edited(path: Path, state: str) -> GpkgEditor:
    """Leave the GeoPackage in a state of decision 8 with a committed row in WAL."""
    editor = GpkgEditor(path)
    editor.begin()
    editor.insert("zlewnie", _BASIN, nazwa="Zlewnia C")
    editor.commit()
    if state == "closed_wal":
        editor.close()
    elif state == "open_in_editor":
        editor.begin()
        editor.insert("zlewnie", _BASIN, nazwa="Zlewnia D")
    else:
        editor.crash_without_shm()
    return editor


@pytest.mark.parametrize(
    ("state", "copied"),
    [("closed_wal", False), ("open_in_editor", True), ("crashed_editor", True)],
)
def test_vector_gpkg_states_read_committed_rows_folder_unchanged(
    tmp_path: Path, renderer: VectorRenderer, state: str, copied: bool
) -> None:
    """Each of the three states: committed rows, no file added or changed.

    State (a) in place; (b) and (c) from a copy, so the probe asks for the
    kept copy (``needs_copy`` → ``source.gpkg``).
    """
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_layers",))
    path = folder.path("gpkg_layers")
    editor = _edited(path, state)
    source = _source(path, mutable=True)
    lon, lat = _wgs84("EPSG:2180", 566_250.0, 241_250.0)
    tile = _GRID.tile(lon, lat, 15)
    before = _listing(folder.root)

    # Act
    try:
        probe = renderer.probe(source)
        view = _wider(probe.bbox_wgs84)
        found = renderer.features(source, probe, "zlewnie", view, 14, 100)
        renderer.thumbnail(source, probe, "features", 256, None)
        renderer.tile(source, probe, "features", 15, tile.x, tile.y, {})
        after = _listing(folder.root)
    finally:
        editor.close()

    # Assert
    basins = probe.layers[1]
    assert (basins["name"], basins["feature_count"]) == ("zlewnie", 3)
    assert _names(found) == ["Zlewnia A", "Zlewnia B", "Zlewnia C"]
    assert after == before
    assert probe.needs_copy is copied
    assert build_product(probe) == (SOURCE_GPKG_NAME if copied else None)


def test_vector_build_copy_of_open_gpkg_holds_committed_rows(
    tmp_path: Path, renderer: VectorRenderer
) -> None:
    """``source.gpkg``: one SQLite file, committed rows only, the folder untouched."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_layers",))
    path = folder.path("gpkg_layers")
    editor = _edited(path, "open_in_editor")
    source = _source(path, mutable=True)
    out = tmp_path / "source.gpkg"
    before = _listing(folder.root)

    # Act
    try:
        probe = renderer.probe(source)
        renderer.build(source, probe, out)
        after = _listing(folder.root)
    finally:
        editor.close()

    # Assert
    with sqlite3.connect(f"{out.as_uri()}?mode=ro&immutable=1", uri=True) as copy:
        rows = [
            row[0] for row in copy.execute("SELECT nazwa FROM zlewnie ORDER BY fid")
        ]
    copy.close()
    assert rows == ["Zlewnia A", "Zlewnia B", "Zlewnia C"]
    assert sorted(
        item.name for item in tmp_path.iterdir() if item.name.startswith("source")
    ) == ["source.gpkg"]
    assert after == before
