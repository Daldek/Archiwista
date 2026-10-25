"""Areas over HTTP: GeoJSON, files and their limits (plan step 9c, SPEC 10.1).

Every test runs the application with the real Kartograf plugin (pinned
operations and countries) and the real reader process, except where a slow
stand-in shows the time limit.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import shapely
from fastapi import FastAPI
from pyproj import Geod, Transformer
from shapely.geometry import mapping, shape

from archiwista.area_reader import MAX_VERTICES, UNPACKED_LIMIT_BYTES
from archiwista.areas import AREA_BODY_LIMIT_BYTES, AreaFiles
from archiwista.auth import LOCAL_OWNER
from archiwista.messages import message
from archiwista.sources.registry import load_registry
from tests.fixtures import fetching_area_reader
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.area_files import (
    SLOW_READER_COMMAND,
    SQUARE_KM2,
    circle,
    declared_size_zip,
    escaping_zip,
    gdal_file,
    geojson_file,
    gpkg_file,
    shapefile_zip,
    square,
    square_wgs84,
    upload,
    zip_bomb,
)
from tests.fixtures.http_listener import listening
from tests.fixtures.local_server import local_paths
from tests.fixtures.slow_area_reader import PID_FILE_ENV

_RECTANGLE: dict[str, object] = {
    "type": "Polygon",
    "coordinates": [
        [[19.0, 50.0], [19.1, 50.0], [19.1, 50.1], [19.0, 50.1], [19.0, 50.0]]
    ],
}
_FETCHING_READER = (sys.executable, str(Path(fetching_area_reader.__file__)))


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """Serve the application over local data with the producer plugins."""
    paths = local_paths(tmp_path)
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as served:
        yield served


@pytest.fixture
def owner(api: Api) -> Caller:
    """Return the local owner's session."""
    return api.session(LOCAL_OWNER)


def _files(api: Api) -> AreaFiles:
    files: AreaFiles = cast(FastAPI, api.client.app).state.area_files
    return files


def _copies(api: Api) -> list[str]:
    """Names of the kept copies and of the uploads not cleaned up."""
    directory = _files(api).directory
    found = sorted(
        path.relative_to(directory).as_posix()
        for path in (*directory.glob("*"), *directory.glob(".incoming/*"))
        if path.name != ".incoming"
    )
    return found


def _geodesic_km2(geometry: dict[str, Any]) -> float:
    area, _ = Geod(ellps="GRS80").geometry_area_perimeter(shape(geometry))
    return abs(area) / 1e6


def _square_with_crs(where: str, crs: object, *, wgs84: bool = True) -> bytes:
    """Return the square as GeoJSON with ``crs`` on one of its objects."""
    polygon = square_wgs84() if wgs84 else square()
    geometry: dict[str, object] = dict(mapping(polygon))
    feature: dict[str, object] = {"type": "Feature", "properties": {}}
    if where == "collection_member":
        feature["geometry"] = {"type": "GeometryCollection", "geometries": [geometry]}
    else:
        feature["geometry"] = geometry
    document: dict[str, object] = {"type": "FeatureCollection", "features": [feature]}
    holders = {"document": document, "feature": feature}
    holder = holders.get(where, geometry)
    holder["crs"] = crs
    return json.dumps(document).encode("utf-8")


def _point_proxies(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Send every proxied request to ``url`` and let 127.0.0.1 skip proxies."""
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    for name in ("http_proxy", "HTTPS_PROXY", "ALL_PROXY", "GDAL_HTTP_PROXY"):
        monkeypatch.setenv(name, url)


def test_areas_geojson_body_kept_with_planar_area_and_countries(
    api: Api, owner: Caller
) -> None:
    """A drawn rectangle gets an id from its geometry, km² in EPSG:2180 and PL.

    Posting the same geometry again keeps the id and the creation time; the
    name and source become the latest ones.
    """
    # Act
    created = owner.request(
        "POST", "/areas", json={"geometry": _RECTANGLE, "name": "Kraków"}
    )
    again = owner.request(
        "POST",
        "/areas",
        json={"geometry": _RECTANGLE, "name": "Widok", "source": "view"},
    )
    body = created.json()
    found = owner.request("GET", f"/areas/{body['id']}")

    # Assert
    assert created.status_code == 201, created.text
    assert created.headers["location"] == f"/api/v1/areas/{body['id']}"
    assert (body["name"], body["source"]) == ("Kraków", "drawn")
    assert found.status_code == 200
    kept = found.json()
    assert kept == again.json()
    assert (kept["id"], kept["created_at"]) == (body["id"], body["created_at"])
    assert (kept["name"], kept["source"]) == ("Widok", "view")
    assert kept["geometry"] == _RECTANGLE
    assert kept["bbox"] == [19.0, 50.0, 19.1, 50.1]
    assert (kept["countries"], kept["area_crs"]) == (["PL"], "EPSG:2180")
    # Poland CS92 shrinks areas by up to about 0.15% near 19°E (scale 0.9993).
    assert kept["area_km2"] == pytest.approx(_geodesic_km2(_RECTANGLE), rel=2e-3)
    assert _copies(api) == []


@pytest.mark.parametrize(
    ("kind", "copy"),
    [
        ("geojson_2180", ["area.geojson"]),
        ("geojson_wgs84", ["area.geojson"]),
        ("gpkg", ["area.gpkg"]),
        ("shapefile_zip", ["area.dbf", "area.prj", "area.shp", "area.shx"]),
    ],
)
def test_areas_file_read_converted_to_wgs84_and_copied(
    api: Api, owner: Caller, tmp_path: Path, kind: str, copy: list[str]
) -> None:
    """GeoJSON, GeoPackage and a zipped Shapefile give the same 100 km² area."""
    # Arrange
    content = {
        "geojson_2180": lambda: gdal_file(
            tmp_path, "obszar.geojson", driver="GeoJSON"
        ).read_bytes(),
        "geojson_wgs84": lambda: geojson_file(mapping(square_wgs84())),
        "gpkg": lambda: gpkg_file(tmp_path),
        "shapefile_zip": lambda: shapefile_zip(tmp_path, prefix="granice/"),
    }[kind]()

    # Act
    response = upload(owner, content, query="?name=obszar")

    # Assert
    assert response.status_code == 201, response.text
    area = response.json()
    assert (area["source"], area["name"], area["countries"]) == (
        "file",
        "obszar",
        ["PL"],
    )
    assert area["area_km2"] == pytest.approx(SQUARE_KM2, rel=1e-4)
    to_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)
    back = shapely.transform(
        shape(area["geometry"]), to_2180.transform, interleaved=False
    )
    assert shapely.hausdorff_distance(back, square()) < 1.0  # metres
    assert _copies(api) == [area["id"]]
    assert (
        sorted(p.name for p in (_files(api).directory / area["id"]).iterdir()) == copy
    )
    assert owner.request("GET", f"/areas/{area['id']}").json() == area


def test_areas_body_over_50_mb_refused(api: Api, owner: Caller) -> None:
    """50 MB is read; one byte more is refused without reading it (413)."""
    # Act
    at_limit = upload(owner, b"x" * AREA_BODY_LIMIT_BYTES)
    over = upload(owner, b"x" * (AREA_BODY_LIMIT_BYTES + 1))
    json_over = upload(
        owner, b" " * (AREA_BODY_LIMIT_BYTES + 1), content_type="application/json"
    )

    # Assert
    assert_problem(at_limit, 500, "data_error", "area_unreadable")
    assert_problem(over, 400, "validation_error", "area_too_large")
    assert_problem(json_over, 400, "validation_error", "area_too_large")
    assert "50 MB" in over.json()["detail"]
    assert _copies(api) == []


@pytest.mark.parametrize("archive", ["declared", "bomb"])
def test_areas_archive_over_200_mb_unpacked_refused_before_unpacking(
    api: Api, owner: Caller, archive: str
) -> None:
    """An archive declaring more than 200 MB unpacked is refused unopened."""
    # Arrange: the declared size is a lie a reader would trip on; the bomb is real.
    content = (
        declared_size_zip(UNPACKED_LIMIT_BYTES + 1)
        if archive == "declared"
        else zip_bomb(UNPACKED_LIMIT_BYTES // 1024**2 + 1)
    )

    # Act
    response = upload(owner, content)

    # Assert
    assert len(content) < 1024**2
    assert_problem(response, 400, "validation_error", "area_too_large")
    assert "200 MB" in response.json()["detail"]
    assert _copies(api) == []


@pytest.mark.parametrize(
    "member", ["../obszar.cpg", "granice/../../obszar.txt", "/etc/obszar", "C:\\x.prj"]
)
def test_areas_archive_member_leaving_its_directory_refused(
    api: Api, owner: Caller, member: str
) -> None:
    """One member outside the directory refuses the whole archive, unpacked."""
    # Act
    response = upload(owner, escaping_zip(member))

    # Assert
    assert_problem(response, 500, "data_error", "area_unreadable")
    assert member in response.json()["detail"]
    assert _copies(api) == []
    data_dir = _files(api).directory.parent
    assert not list(data_dir.rglob("obszar.*"))


def test_areas_slow_reader_killed_at_time_limit(
    api: Api, owner: Caller, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader still busy at the limit is killed and the file is refused."""
    # Arrange
    pid_file = tmp_path / "reader.pid"
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))
    app = cast(FastAPI, api.client.app)
    app.state.area_files = replace(
        _files(api), command=SLOW_READER_COMMAND, timeout_s=1.0
    )

    # Act
    started = time.monotonic()
    response = upload(owner, geojson_file(_RECTANGLE))
    elapsed = time.monotonic() - started

    # Assert
    assert_problem(response, 500, "data_error", "area_unreadable")
    assert "1 s" in response.json()["detail"]
    assert 1.0 <= elapsed < 10.0
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert _copies(api) == []


@pytest.mark.parametrize(
    ("where", "kind"),
    [
        ("document", "link"),
        ("document", "url"),
        ("feature", "link"),
        ("geometry", "url"),
        ("collection_member", "link"),
    ],
)
def test_areas_geojson_crs_link_refused_without_fetching(
    api: Api, owner: Caller, monkeypatch: pytest.MonkeyPatch, where: str, kind: str
) -> None:
    """A CRS given as a link anywhere in GeoJSON is refused; nothing is fetched."""
    # Arrange
    with listening() as listener:
        _point_proxies(monkeypatch, listener.url)
        key = "href" if kind == "link" else "url"
        crs = {"type": kind, "properties": {key: f"{listener.url}/crs"}}

        # Act
        response = upload(owner, _square_with_crs(where, crs))

    # Assert
    assert_problem(response, 500, "data_error", "area_unreadable")
    assert response.json()["detail"] == message("area.crs_not_named")
    assert listener.received == []
    assert _copies(api) == []


def test_areas_geojson_crs_named_read_with_crs_attributes(
    owner: Caller, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CRS by name still reads; attributes named ``crs`` are no CRS to GDAL."""
    # Arrange
    with listening() as listener:
        _point_proxies(monkeypatch, listener.url)
        named = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2180"}}
        document = json.loads(_square_with_crs("document", named, wgs84=False))
        link = {"type": "link", "properties": {"href": f"{listener.url}/crs"}}
        document["features"][0]["properties"] = {
            "crs": "EPSG:2180",
            "meta": {"crs": link},
        }

        # Act
        response = upload(owner, json.dumps(document).encode("utf-8"))

    # Assert
    assert response.status_code == 201, response.text
    assert response.json()["area_km2"] == pytest.approx(SQUARE_KM2, rel=1e-4)
    assert listener.received == []


def test_areas_reader_environment_keeps_gdal_offline(
    api: Api, owner: Caller, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GDAL fetching a link CRS in the reader reaches nothing, whatever the proxies.

    The stand-in reader lets GDAL open the file unchecked: started with the
    server's own environment (NO_PROXY naming 127.0.0.1), it does fetch.
    """
    # Arrange
    app = cast(FastAPI, api.client.app)
    app.state.area_files = replace(_files(api), command=_FETCHING_READER)
    unchecked_dir = tmp_path / "unchecked"
    unchecked_dir.mkdir()

    # Act
    with listening() as unchecked:
        _point_proxies(monkeypatch, unchecked.url)
        crs = {"type": "link", "properties": {"href": f"{unchecked.url}/crs"}}
        (unchecked_dir / "upload").write_bytes(_square_with_crs("document", crs))
        subprocess.run([*_FETCHING_READER, str(unchecked_dir)], check=True, timeout=60)
    with listening() as listener:
        _point_proxies(monkeypatch, listener.url)
        crs = {"type": "link", "properties": {"href": f"{listener.url}/crs"}}
        response = upload(owner, _square_with_crs("document", crs))

    # Assert
    assert unchecked.received, "GDAL no longer fetches a link CRS: probe is moot"
    assert_problem(response, 500, "data_error", "area_unreadable")
    assert response.json()["detail"] == "crs: EPSG:4326"  # GDAL ran, gave up
    assert listener.received == []


@pytest.mark.parametrize("sent", ["json", "file"])
def test_areas_more_than_100000_vertices_refused_never_simplified(
    api: Api, owner: Caller, sent: str
) -> None:
    """100 000 positions are kept as they are; 100 001 are refused."""

    def post(geometry: dict[str, object]) -> httpx.Response:
        if sent == "json":
            return owner.request("POST", "/areas", json={"geometry": geometry})
        return upload(owner, geojson_file(geometry))

    # Act
    kept = post(circle(MAX_VERTICES))
    refused = post(circle(MAX_VERTICES + 1))

    # Assert
    assert kept.status_code == 201, kept.text
    ring = kept.json()["geometry"]["coordinates"][0]
    assert len(ring) == MAX_VERTICES
    assert_problem(refused, 400, "validation_error", "area_too_complex")
    assert "100001" in refused.json()["detail"]


def test_areas_copies_older_than_7_days_pruned_at_start_up(tmp_path: Path) -> None:
    """Old copies go at start-up; the areas stay in the index."""
    # Arrange
    paths = local_paths(tmp_path)
    registry = load_registry(cache_dir=paths.cache_dir)
    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        old = upload(owner, gpkg_file(tmp_path)).json()
        recent = upload(owner, geojson_file(_RECTANGLE)).json()
    now = datetime.now(UTC)
    leftover = paths.areas_dir / ".incoming" / "crashed"
    leftover.mkdir(parents=True)
    for path, age in (
        (paths.areas_dir / old["id"], timedelta(days=7, minutes=1)),
        (paths.areas_dir / recent["id"], timedelta(days=6)),
        (leftover, timedelta(days=8)),
    ):
        stamp = (now - age).timestamp()
        os.utime(path, (stamp, stamp))

    # Act
    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        kept_old = owner.request("GET", f"/areas/{old['id']}")

        # Assert
        assert _copies(api) == [recent["id"]]
        assert kept_old.status_code == 200
        assert kept_old.json()["geometry"] == old["geometry"]


@pytest.mark.parametrize(
    ("make", "query", "fragment"),
    [
        (lambda d: b"\x89PNG\r\n\x1a\n not an area", "", "Nieznany format"),
        (lambda d: b"SQLite format 3\x00" + bytes(4000), "", "Nie można odczytać"),
        (lambda d: b'{"type": "FeatureCollection", "features": [', "", "odczytać"),
        (
            lambda d: geojson_file({"type": "Point", "coordinates": [19, 50]}),
            "",
            "Point",
        ),
        (lambda d: shapefile_zip(d, without=(".prj",)), "", ".prj"),
        (lambda d: shapefile_zip(d, without=(".shx", ".dbf")), "", ".shx, .dbf"),
        (lambda d: escaping_zip("README.txt")[:-10], "", "ZIP"),
        (lambda d: gpkg_file(d, layers=("gminy", "powiaty")), "", "gminy, powiaty"),
        (lambda d: gpkg_file(d), "?layer=rzeki", "rzeki"),
        (lambda d: shapefile_zip(d, names=("a", "b")), "", "a, b"),
        (lambda d: b"", "", "Nieznany format"),
    ],
    ids=[
        "unknown_format",
        "broken_gpkg",
        "broken_geojson",
        "points",
        "no_prj",
        "no_shx_dbf",
        "broken_zip",
        "two_layers",
        "unknown_layer",
        "two_shapefiles",
        "empty",
    ],
)
def test_areas_malformed_file_refused_with_reason(
    api: Api, owner: Caller, tmp_path: Path, make: Any, query: str, fragment: str
) -> None:
    """A file that cannot be an area says why, in Polish, and leaves no copy."""
    # Act
    response = upload(owner, make(tmp_path), query=query)

    # Assert
    assert_problem(response, 500, "data_error", "area_unreadable")
    assert fragment in response.json()["detail"]
    assert _copies(api) == []


@pytest.mark.parametrize("kind", ["gpkg", "shapefile_zip"])
def test_areas_file_with_several_layers_lists_them_then_reads_one(
    api: Api, owner: Caller, tmp_path: Path, kind: str
) -> None:
    """Without `layer` the problem names the layers; with it, that one is read."""
    # Arrange
    content = (
        gpkg_file(tmp_path, layers=("gminy", "powiaty"))
        if kind == "gpkg"
        else shapefile_zip(tmp_path, names=("gminy", "powiaty"))
    )

    # Act
    refused = upload(owner, content)
    chosen = upload(owner, content, query="?layer=powiaty")

    # Assert
    assert_problem(refused, 500, "data_error", "area_unreadable")
    assert refused.json()["details"]["layers"] == ["gminy", "powiaty"]
    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["area_km2"] == pytest.approx(SQUARE_KM2, rel=1e-4)


def test_areas_invalid_requests_refused(
    api: Api, owner: Caller, tmp_path: Path
) -> None:
    """Bad GeoJSON is 400, a missing CSRF token 403, no producer plugin 503."""
    # Arrange
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [[19.0, 50.0], [19.1, 50.1], [19.1, 50.0], [19.0, 50.1], [19.0, 50.0]]
        ],
    }
    outside = {
        "type": "Polygon",
        "coordinates": [[[179.0, 50.0], [181.0, 50.0], [181.0, 51.0], [179.0, 50.0]]],
    }

    # Act
    point = owner.request(
        "POST", "/areas", json={"geometry": {"type": "Point", "coordinates": [19, 50]}}
    )
    beyond = owner.request("POST", "/areas", json={"geometry": outside})
    unknown_field = owner.request(
        "POST", "/areas", json={"geometry": _RECTANGLE, "colour": "red"}
    )
    file_source = owner.request(
        "POST", "/areas", json={"geometry": _RECTANGLE, "source": "file"}
    )
    not_json = upload(owner, b"{", content_type="application/json")
    no_csrf = upload(owner, geojson_file(_RECTANGLE), csrf=False)
    repaired = owner.request("POST", "/areas", json={"geometry": bowtie})
    unknown = owner.request("GET", "/areas/0000000000000000")
    with running_api(local_paths(tmp_path / "bare")) as bare:
        no_plugin = bare.session(LOCAL_OWNER).request(
            "POST", "/areas", json={"geometry": _RECTANGLE}
        )

    # Assert
    for response in (point, beyond, unknown_field, file_source, not_json):
        assert_problem(response, 400, "validation_error")
    assert unknown_field.json()["errors"][0]["pointer"] == "/body/colour"
    assert_problem(no_csrf, 403, "forbidden", "csrf_rejected")
    assert repaired.status_code == 201, repaired.text
    fixed = shape(repaired.json()["geometry"])
    assert shapely.is_valid(fixed) and fixed.area == pytest.approx(0.005)
    assert_problem(unknown, 404, "not_found")
    assert_problem(no_plugin, 503, "missing_dependency", "source_unavailable")


def test_areas_openapi_documents_both_bodies(owner: Caller) -> None:
    """Agents learn from the OpenAPI document how to send GeoJSON or a file."""
    # Act
    document = owner.request("GET", "/openapi.json").json()

    # Assert
    operation = document["paths"]["/api/v1/areas"]["post"]
    assert operation["operationId"] == "create_area"
    content = operation["requestBody"]["content"]
    assert content["application/json"]["schema"]["properties"]["geometry"]
    assert content["application/octet-stream"]["schema"]["format"] == "binary"
    assert {"201", "400", "500", "503"} <= set(operation["responses"])
    get = document["paths"]["/api/v1/areas/{area_id}"]["get"]
    coverage = document["paths"]["/api/v1/local-coverage"]["get"]
    assert (get["operationId"], coverage["operationId"]) == (
        "get_area",
        "get_local_coverage",
    )
