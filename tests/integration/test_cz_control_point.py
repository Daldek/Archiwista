"""Outlines and previews where the data is on the ground (decision 4, criterion 2).

A raster in EPSG:5514 whose top-left corner is trigonometric point 3722
(``POINT_3722``, ČÚZK) goes through a real scan into the index. The vertex of
its outline that ``/map/footprints`` serves lies within 2 m of the point's
ETRS89 coordinates measured by GNSS, never computed by the transformation
under test. The WGS84 bounding box of 0.1.0 misses that corner by about
200 m. A GeoPackage point at 3722 comes back from a render process's
``features`` (step 5b) within the same 2 m, and so does a bright mark at 3722
on the z = 19 map tiles of a GeoTIFF and of an SM5 JPEG sheet placed by its
world file, through its local COG (steps 5a1 and 5a2).
"""

import hashlib
import json
import os
import warnings
from pathlib import Path
from typing import Any

import morecantile
import numpy as np
import pyproj
import pytest
from kartograf import FileStorage
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, ScanSummary, initialize, scan_store
from archiwista.previews.cache import PreviewCache
from archiwista.previews.pool import RenderPool
from archiwista.previews.types import PreviewSource
from archiwista.sources.registry import SourceRegistry, load_registry
from tests.fixtures import store_files
from tests.fixtures.api_session import running_api
from tests.fixtures.control_points import POINT_3722
from tests.fixtures.index_data import CZ_NMT
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import CZ_ORTO, StoreManifest
from tests.fixtures.own_data import make_own_folder
from tests.fixtures.preview_api import PreviewApi, decoded_png, serve_previews
from tests.fixtures.store_files import Bounds
from tests.fixtures.store_marker import mark_store

STORE = "cz"
# An SM5-sized raster: 2.5 km east and 2 km south of its top-left corner.
WIDTH_M, HEIGHT_M = 2500.0, 2000.0
TOLERANCE_M = 2.0
GEOD = pyproj.Geod(ellps="WGS84")
# The SM5 sheet of 3722 (Český Těšín 7-5, north-west of Kartograf's CTES86)
# and its north-west corner in EPSG:5514.
SM5_SHEET = "CTES75"
SM5_CORNER = (-450_000.0, -1_110_000.0)
PIXEL_M = 0.5
TILE_ZOOM = 19
TILES = morecantile.tms.get("WebMercatorQuad")
TO_LONLAT = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def _write_raster(root: Path, bounds: Bounds, data: bytes) -> str:
    """Write a ČÚZK DEM raster of ``bounds`` (EPSG:5514) as Kartograf stores it.

    One version under ``versions/bbox/`` and the standard path linked to it;
    the sidecar names no request bbox, so the outline comes from the
    GeoTIFF's header. Returns the version's path in the store.
    """
    code = "_".join(format(value, ".10g") for value in bounds)
    segment = root.joinpath(*CZ_NMT.split("/"))
    meta: dict[str, Any] = {
        "schema": "kartograf-meta/1",
        "dataset": "cz.cuzk.dmr5g",
        "country": "CZ",
        "product": "nmt",
        "provider": "CUZK",
        "horizontal_crs": "EPSG:5514",
        "vertical_crs": "EPSG:8357",
        "vertical_source": "server",
        "resolution": "2m",
        "request": {},
        "downloaded_at": "2026-10-16T12:00:00+00:00",
        "extra": {"version": {"label": "2026-10-16", "label_source": "downloaded"}},
    }
    link = segment / "bbox" / f"{code}.tif"
    version = _write_version(segment / "versions" / "bbox", link, data, meta)
    return version.relative_to(root).as_posix()


def _write_sm5_sheet(root: Path, x: float, y: float) -> str:
    """Write an SM5 orthophoto: a JPEG marked at ``(x, y)`` and its world file.

    As Kartograf stores ČÚZK's sheets: the JPEG and the ``.jgw`` are two
    slots of one edition, and the JPEG has no georeference of its own, so
    its header outline comes from the world file. The image covers the
    sheet's 2.5 × 2 km with 0.5 m pixels, moved by under 2 m so that a
    white 16 × 16 pixel mark on black fills whole JPEG blocks and is centred
    on ``(x, y)``. Returns the JPEG version's path in the store.
    """
    columns, rows = int(WIDTH_M / PIXEL_M), int(HEIGHT_M / PIXEL_M)
    column = round((x - SM5_CORNER[0]) / PIXEL_M / 8) * 8
    row = round((SM5_CORNER[1] - y) / PIXEL_M / 8) * 8
    west, north = x - column * PIXEL_M, y + row * PIXEL_M
    pixels = np.zeros((3, rows, columns), dtype="uint8")
    pixels[:, row - 8 : row + 8, column - 8 : column + 8] = 255
    world = (PIXEL_M, 0.0, 0.0, -PIXEL_M, west + PIXEL_M / 2, north - PIXEL_M / 2)
    label = "2024_2025-03-31"
    meta: dict[str, Any] = {
        "schema": "kartograf-meta/1",
        "dataset": "cz.cuzk.orto",
        "country": "CZ",
        "product": "orto",
        "provider": "CUZK",
        "horizontal_crs": "EPSG:5514",
        "request": {"sheet": SM5_SHEET},
        "downloaded_at": "2026-10-16T12:00:00+00:00",
        "extra": {
            "version": {"label": label, "label_source": "edition"},
            "source": {"edition": label, "year": 2024, "updated": "2025-03-31"},
        },
    }
    storage = FileStorage(root, resolution=None, vertical_crs=None, subdir=CZ_ORTO)
    versions = storage.get_raw_versions_root(SM5_SHEET)
    _write_version(
        versions,
        storage.get_raw_path(SM5_SHEET, f"{SM5_SHEET}.jgw"),
        "".join(f"{value:.6f}\n" for value in world).encode("ascii"),
        meta,
    )
    image = _write_version(
        versions,
        storage.get_raw_path(SM5_SHEET, f"{SM5_SHEET}.jpg"),
        _jpeg(pixels),
        meta,
    )
    return image.relative_to(root).as_posix()


def _marked_geotiff(x: float, y: float) -> tuple[Bounds, bytes]:
    """Return the box and bytes of a 0.5 m DEM GeoTIFF marked at ``(x, y)``.

    200 × 200 m around the point in EPSG:5514, without data but an 8 × 8
    pixel block (4 × 4 m) centred on it.
    """
    size = 400
    half = size * PIXEL_M / 2
    bounds = (x - half, y - half, x + half, y + half)
    pixels = np.zeros((1, size, size), dtype="uint8")
    middle = size // 2
    pixels[0, middle - 4 : middle + 4, middle - 4 : middle + 4] = 255
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=size,
            height=size,
            count=1,
            dtype="uint8",
            crs="EPSG:5514",
            transform=from_bounds(*bounds, size, size),
            nodata=0,
        ) as dataset:
            dataset.write(pixels)
        return bounds, bytes(memory.read())


def _jpeg(pixels: np.ndarray[Any, Any]) -> bytes:
    """Encode RGB bands as a JPEG without georeference (quality 95)."""
    count, height, width = pixels.shape
    with warnings.catch_warnings(), MemoryFile() as memory:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with memory.open(
            driver="JPEG",
            width=width,
            height=height,
            count=count,
            dtype="uint8",
            QUALITY=95,
        ) as dataset:
            dataset.write(pixels)
        return bytes(memory.read())


def _write_version(
    versions: Path, link: Path, data: bytes, meta: dict[str, Any]
) -> Path:
    """Write a version with its sidecar and link the standard path to it."""
    sha256 = hashlib.sha256(data).hexdigest()
    label = meta["extra"]["version"]["label"]
    version = versions / f"{label}_{sha256[:8]}" / link.name
    version.parent.mkdir(parents=True)
    version.write_bytes(data)
    meta = {**meta, "sha256": sha256, "size_bytes": len(data)}
    _write_json(version, meta)
    link.parent.mkdir(parents=True, exist_ok=True)
    os.link(version, link)
    target = Path(os.path.relpath(version, link.parent)).as_posix()
    extra = {**meta["extra"], "link": "hardlink", "link_target": target}
    _write_json(link, {**meta, "extra": extra})
    return version


def _write_json(path: Path, content: dict[str, Any]) -> None:
    sidecar = path.with_name(path.name + ".meta.json")
    sidecar.write_text(json.dumps(content, indent=2), encoding="utf-8")


def _scan(tmp_path: Path, root: Path) -> tuple[AppPaths, SourceRegistry, ScanSummary]:
    """Configure the store at ``root`` and scan it into a fresh index."""
    paths = local_paths(tmp_path)
    config = StoreConfig(id=STORE, name="ČÚZK", kartograf=root, kind="local")
    settings = AppSettings(stores=(config,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {"kartograf": root}})
        scanned = scan_store(registry.adapter("kartograf"), writer, settings, STORE)
    return paths, registry, scanned


def _marked_centre(served: PreviewApi, path: str) -> tuple[float, float]:
    """Return the WGS84 centre of the bright pixels of a version's tiles at 3722.

    The 3 × 3 tiles (z = 19) around the point make one image, so a mark
    across a tile's edge is whole; tile pixels go to WGS84 by the spherical
    Mercator formulas, not by the operation under test.
    """
    lon, lat = POINT_3722.etrs89
    centre = TILES.tile(lon, lat, TILE_ZOOM)
    mosaic = np.zeros((4, 768, 768), dtype=np.uint8)
    for row in range(3):
        for column in range(3):
            x, y = centre.x + column - 1, centre.y + row - 1
            response = served.get(
                f"/api/v1/stores/{STORE}/versions/{path}/tiles/{TILE_ZOOM}/{x}/{y}.png"
            )
            assert response.status_code == 200, response.text
            mosaic[
                :, row * 256 : (row + 1) * 256, column * 256 : (column + 1) * 256
            ] = decoded_png(response.content)
    marked = (mosaic[3] > 0) & (mosaic[:3].mean(axis=0) > 127)
    rows, columns = np.nonzero(marked)
    assert rows.size, f"no bright pixel around 3722 on the tiles of {path}"
    corner = morecantile.Tile(centre.x - 1, centre.y - 1, TILE_ZOOM)
    left, _, right, top = TILES.xy_bounds(corner)
    pixel = (right - left) / 256
    found: tuple[float, float] = TO_LONLAT.transform(
        left + (columns.mean() + 0.5) * pixel, top - (rows.mean() + 0.5) * pixel
    )
    return found


def test_cz_outline_vertex_within_2_m(tmp_path: Path) -> None:
    """The outline's corner at point 3722 is within 2 m of its ETRS89 position.

    The version card serves the same polygon as the map.
    """
    # Arrange
    x, y = POINT_3722.epsg5514
    lon, lat = POINT_3722.etrs89
    root = tmp_path / "store" / "data"
    mark_store(root)
    bounds = (x, y - HEIGHT_M, x + WIDTH_M, y)
    version = _write_raster(root, bounds, store_files.geotiff(bounds, 5514, 3722))
    paths, registry, scanned = _scan(tmp_path, root)
    view = f"{lon - 0.05},{lat - 0.05},{lon + 0.05},{lat + 0.05}"

    # Act
    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        footprints = owner.request("GET", f"/map/footprints?bbox={view}")
        card = owner.request("GET", f"/stores/{STORE}/versions/{version}")

    # Assert
    assert scanned.footprints_written == 1 and scanned.footprints_failed == 0
    assert footprints.status_code == 200, footprints.text
    (item,) = footprints.json()["items"]
    ring = item["geometry"]["coordinates"][0]
    nearest = min(float(GEOD.inv(lon, lat, *vertex)[2]) for vertex in ring)
    assert (item["version"], item["source"]) == (version, "header")
    assert nearest <= TOLERANCE_M
    assert card.status_code == 200, card.text
    assert card.json()["footprint"] == item["geometry"]


def test_cz_features_within_2_m(tmp_path: Path) -> None:
    """A GeoPackage point at 3722 comes back from ``features`` within 2 m.

    A real render process (the application's renderers in the sandbox)
    reads the own-data GeoPackage in EPSG:5514 and moves its point to WGS84
    with the pinned operation.
    """
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_5514_control",))
    path = folder.path("gpkg_5514_control")
    content = hashlib.sha256(path.read_bytes()).hexdigest()
    source = PreviewSource(f"file:cz:{path.name}", content, (path,), mutable=True)
    lon, lat = POINT_3722.etrs89
    view = [lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01]
    params = {"layer": None, "bbox": view, "zoom": 19, "limit": 100}

    # Act
    with (
        PreviewCache(tmp_path / "previews", limit_bytes=100 * 1024**2) as cache,
        RenderPool(workers=1, cache=cache, work_dir=tmp_path / "work") as pool,
    ):
        found = pool.request("features", source, params).json()

    # Assert
    (item,) = found["features"]
    point_lon, point_lat = item["geometry"]["coordinates"]
    assert item["properties"]["numer"] == POINT_3722.number
    assert float(GEOD.inv(lon, lat, point_lon, point_lat)[2]) <= TOLERANCE_M


# The JPEG sheet carries no geotransform (its world file places it); the scan
# reads its header with rasterio, which says so.
@pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
def test_cz_preview_tile_within_2_m(tmp_path: Path) -> None:
    """A mark at 3722 shows on z = 19 map tiles within 2 m of its ETRS89 place.

    Both rasters are scanned and served with real render processes: the
    GeoTIFF (its own georeference) is tiled straight from the file; the SM5
    JPEG has its header outline from the world file in the index, which the
    local COG built by a ``preview`` job carries. Tiles are drawn with the
    pinned operation; the centre of the bright pixels is compared with the
    point's GNSS coordinates.
    """
    # Arrange
    x, y = POINT_3722.epsg5514
    lon, lat = POINT_3722.etrs89
    root = tmp_path / "store" / "data"
    mark_store(root)
    raster = _write_raster(root, *_marked_geotiff(x, y))
    sheet = _write_sm5_sheet(root, x, y)
    paths, _, scanned = _scan(tmp_path, root)
    store = StoreManifest(root.parent, 0, 0, (), ())

    # Act
    with serve_previews(store, paths) as served:
        address = f"/api/v1/stores/{STORE}/versions/{sheet}/preview"
        before = served.get(address).json()
        posted = served.post(address, {"force": False})
        job = served.wait(posted.json()["id"])
        centres = {path: _marked_centre(served, path) for path in (raster, sheet)}

    # Assert
    assert scanned.footprints_written == 3 and scanned.footprints_failed == 0
    assert (before["state"], before["reason"]) == ("needs_build", None)
    assert posted.status_code == 202, posted.text
    assert job.state == "succeeded" and job.result is not None
    assert job.result["built"] == 1
    for path, (centre_lon, centre_lat) in centres.items():
        distance = float(GEOD.inv(lon, lat, centre_lon, centre_lat)[2])
        assert distance <= TOLERANCE_M, (path, distance)
