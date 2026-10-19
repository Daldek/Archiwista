"""Outlines on the map where the data is on the ground (decision 4, criterion 2).

A raster in EPSG:5514 whose top-left corner is trigonometric point 3722
(``POINT_3722``, ČÚZK) goes through a real scan into the index. The vertex of
its outline that ``/map/footprints`` serves lies within 2 m of the point's
ETRS89 coordinates measured by GNSS, never computed by the transformation
under test. The WGS84 bounding box of 0.1.0 misses that corner by about
200 m. A GeoPackage point at 3722 comes back from a render process's
``features`` (step 5b) within the same 2 m.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pyproj

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.previews.cache import PreviewCache
from archiwista.previews.pool import RenderPool
from archiwista.previews.types import PreviewSource
from archiwista.sources.registry import load_registry
from tests.fixtures import store_files
from tests.fixtures.api_session import running_api
from tests.fixtures.control_points import POINT_3722
from tests.fixtures.index_data import CZ_NMT
from tests.fixtures.local_server import local_paths
from tests.fixtures.own_data import make_own_folder

STORE = "cz"
# An SM5-sized raster: 2.5 km east and 2 km south of its top-left corner.
WIDTH_M, HEIGHT_M = 2500.0, 2000.0
TOLERANCE_M = 2.0
GEOD = pyproj.Geod(ellps="WGS84")


def _write_raster(root: Path, bounds: tuple[float, float, float, float]) -> str:
    """Write a ČÚZK DEM raster of ``bounds`` (EPSG:5514) as Kartograf stores it.

    One version under ``versions/bbox/`` and the standard path linked to it;
    the sidecar names no request bbox, so the outline comes from the
    GeoTIFF's header. Returns the version's path in the store.
    """
    code = "_".join(format(value, ".10g") for value in bounds)
    data = store_files.geotiff(bounds, 5514, 3722)
    sha256 = hashlib.sha256(data).hexdigest()
    segment = root.joinpath(*CZ_NMT.split("/"))
    version = segment / "versions" / "bbox" / f"2026-10-16_{sha256[:8]}" / f"{code}.tif"
    version.parent.mkdir(parents=True)
    version.write_bytes(data)
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
        "sha256": sha256,
        "size_bytes": len(data),
    }
    _write_json(version, meta)
    link = segment / "bbox" / f"{code}.tif"
    link.parent.mkdir(parents=True)
    os.link(version, link)
    target = Path(os.path.relpath(version, link.parent)).as_posix()
    extra = {**meta["extra"], "link": "hardlink", "link_target": target}
    _write_json(link, {**meta, "extra": extra})
    return version.relative_to(root).as_posix()


def _write_json(path: Path, content: dict[str, Any]) -> None:
    sidecar = path.with_name(path.name + ".meta.json")
    sidecar.write_text(json.dumps(content, indent=2), encoding="utf-8")


def test_cz_outline_vertex_within_2_m(tmp_path: Path) -> None:
    """The outline's corner at point 3722 is within 2 m of its ETRS89 position.

    The version card serves the same polygon as the map.
    """
    # Arrange
    x, y = POINT_3722.epsg5514
    lon, lat = POINT_3722.etrs89
    root = tmp_path / "store" / "data"
    version = _write_raster(root, (x, y - HEIGHT_M, x + WIDTH_M, y))
    paths = local_paths(tmp_path)
    config = StoreConfig(id=STORE, name="ČÚZK", kartograf=root, kind="local")
    settings = AppSettings(stores=(config,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {"kartograf": root}})
        scanned = scan_store(registry.adapter("kartograf"), writer, settings, STORE)
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
