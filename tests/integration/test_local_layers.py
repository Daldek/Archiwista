"""Local layers of a product over HTTP (plan v0.2, step 11; decision 7).

The hand-written store of ``tests.fixtures.layer_store`` (NMT sheets by
flight, one sheet also as ASCII-NMT, a cutout labelled by its download date,
a sheet with a sparse sidecar, BDOT10k editions) is scanned and served with
real render processes and jobs. ``GET /local-layers`` groups the versions of
an area by variant — never by file format — and data year (never the
download's), else edition or label, splits a year by campaign on request,
measures each layer's share of the area in the area's planar CRS and draws
its thumbnail and map tiles from the ready previews of its versions. The
tests that only read share one server; the ones that build previews or
disconnect the store have their own.

The last test serves a project's data folder instead (``own_data_api``): the
layers of an own file, its working file and then its snapshots.
"""

import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import morecantile
import numpy as np
import numpy.typing as npt
import pyogrio
import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import box, mapping, shape

from archiwista.api.owndata import OWN_CACHE_CONTROL
from archiwista.api.previews import VERSION_CACHE_CONTROL
from archiwista.messages import message
from archiwista.owndata.content import content_identity
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE
from tests.fixtures.layer_store import (
    AREA_SHEET,
    CUTOUT_BOUNDS,
    CUTOUT_LABEL,
    EDITIONS,
    PRODUCT,
    SHEET_FAR,
    SHEET_NE,
    SHEET_NW,
    SHEET_SW,
    LayerStore,
    ServedLayers,
    StoredVersion,
    add_campaign,
    served_layer_store,
    sheet_bounds,
    sheet_polygon,
)
from tests.fixtures.make_store import NMT, NMT_ASCII
from tests.fixtures.own_data import SnapshotFixture, write_snapshot_fixture
from tests.fixtures.own_data_api import own_data_api
from tests.fixtures.permissions import share
from tests.fixtures.preview_api import PreviewApi, decoded_png, version_url
from tests.fixtures.store_files import Bounds

# The meridian along which SHEET_NW and SHEET_NE meet, and a zoom at which
# a map tile on it holds parts of both sheets.
EDGE_LONGITUDE = 22.96875
TILE_ZOOM = 13
# Pixels this close to a raster's edge (one ASC cell is ~35 m) are not judged.
MARGIN_M = 50.0
TO_PLANAR = Transformer.from_crs("EPSG:3857", "EPSG:2180", always_xy=True)
TILES = morecantile.tms.get("WebMercatorQuad")

type Mask = npt.NDArray[np.bool_]
type Grid = npt.NDArray[np.float64]


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServedLayers]:
    """Serve the layer store for the tests that only read."""
    with served_layer_store(tmp_path_factory.mktemp("layers")) as found:
        yield found


@pytest.fixture(scope="module")
def area(served: ServedLayers) -> str:
    """Return the area of the four 1:10 000 sheets of ``AREA_SHEET``."""
    return _area(served.api, sheet_polygon(AREA_SHEET))


def _area(api: PreviewApi, geometry: dict[str, Any]) -> str:
    response = api.owner.request("POST", "/areas", json={"geometry": geometry})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _layers(api: PreviewApi, area: str | None = None, **params: str) -> dict[str, Any]:
    """Return ``GET /local-layers`` of the store's NMT (or ``product``)."""
    query = {"store": STORE, "product": PRODUCT, **params}
    if area is not None:
        query["area_id"] = area
    response = api.owner.request("GET", "/local-layers?" + urlencode(query))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _layer(answer: dict[str, Any], part: str, *, by_segment: bool = False) -> Any:
    """Return the layer keyed ``<variant>:<part>``.

    The variant is the digest of the full variant, or with ``by_segment``
    the NMT segment (a version without ``resolution``).
    """
    (found,) = (
        layer
        for layer in answer["layers"]
        if layer["key"].split(":", 1)[1] == part
        and layer["key"].startswith(f"{NMT}:") == by_segment
    )
    return found


def _campaign_title(campaign: str) -> str:
    """Return the title of the layer of a campaign of 2023."""
    return message("layer.title_campaign", title="2023", campaign=campaign)


def _path(ref: str) -> str:
    """Return the store path a version's ``ref`` names."""
    return ref.split(":", 2)[2]


def _paths(layer: dict[str, Any]) -> list[str]:
    return [_path(version["ref"]) for version in layer["versions"]]


def _cutout(store: LayerStore) -> StoredVersion:
    return next(
        item for item in store.versions if item.data_year is None and not item.edition
    )


def _preview_jobs(api: PreviewApi) -> int:
    response = api.owner.request("GET", "/jobs?kind=preview&limit=200")
    assert response.status_code == 200, response.text
    return len(response.json()["items"])


def _wait_for_builds(api: PreviewApi, answer: dict[str, Any]) -> None:
    for layer in answer["layers"]:
        job = layer["preview"]["job"]
        if job is not None:
            api.wait(job["id"])


def test_layers_by_data_year_never_download_year(
    served: ServedLayers, area: str
) -> None:
    """A layer is a data year; a version without one is in its label's layer.

    Every file was downloaded in 2025 or 2026: no layer is of those years.
    The cutout labelled by its download date has no data year.
    """
    # Act
    answer = _layers(served.api, area)

    # Assert
    layers = answer["layers"]
    assert [(layer["kind"], layer["year"]) for layer in layers] == [
        ("year", 2023),
        ("year", 2023),
        ("year", 2019),
        ("label", None),
    ]
    for layer in layers[:3]:
        stored = [served.store.by_path(path) for path in _paths(layer)]
        assert {item.data_year for item in stored} == {layer["year"]}
        assert layer["title"] == str(layer["year"])
        assert {day[:4] for day in layer["data_dates"]} == {str(layer["year"])}
    label = layers[3]
    assert (label["title"], label["data_dates"]) == (CUTOUT_LABEL, [])
    assert _paths(label) == [_cutout(served.store).path]
    listed = sorted(path for layer in layers for path in _paths(layer))
    assert listed == sorted(
        item.path
        for item in served.store.versions
        if item.segment in (NMT, NMT_ASCII) and item.unit != SHEET_FAR
    )


def test_layers_by_edition_without_year(served: ServedLayers, area: str) -> None:
    """Versions without a data year group by their edition."""
    # Act
    answer = _layers(served.api, area, product="bdot10k")

    # Assert
    layers = {layer["title"]: layer for layer in answer["layers"]}
    titles = {
        edition: message("layer.title_edition", edition=edition) for edition in EDITIONS
    }
    assert layers.keys() == set(titles.values())
    for edition in EDITIONS:
        layer = layers[titles[edition]]
        assert (layer["kind"], layer["year"], layer["data_dates"]) == (
            "edition",
            None,
            [],
        )
        assert layer["key"].endswith(f":{edition}")
        (path,) = _paths(layer)
        assert served.store.by_path(path).edition == edition


def test_group_by_campaign(served: ServedLayers, area: str) -> None:
    """``group=campaign`` splits a year by campaign; a version without one stays."""
    # Act
    by_year = _layers(served.api, area)
    by_campaign = _layers(served.api, area, group="campaign")

    # Assert
    split = [_layer(by_campaign, f"2023:{flight}") for flight in ("83501", "82710")]
    assert [(layer["kind"], layer["title"], layer["campaigns"]) for layer in split] == [
        ("campaign", _campaign_title("83501"), ["83501"]),
        ("campaign", _campaign_title("82710"), ["82710"]),
    ]
    for layer in split:
        flights = {served.store.by_path(path).campaign for path in _paths(layer)}
        assert flights == set(layer["campaigns"])
    whole = _layer(by_year, "2023")
    assert sorted(path for layer in split for path in _paths(layer)) == sorted(
        _paths(whole)
    )
    assert _layer(by_campaign, "2019:41022")["kind"] == "campaign"
    assert _layer(by_campaign, CUTOUT_LABEL)["kind"] == "label"
    assert by_campaign["group"] == "campaign"


def test_two_formats_of_one_variant_make_one_layer(
    served: ServedLayers, area: str
) -> None:
    """ASC and ASCII-NMT of one product, CRSs and resolution: one layer, two badges.

    The sheet in both formats counts once; the archive has no map preview,
    so the layer's previews do not count it either.
    """
    # Act
    answer = _layers(served.api, area)

    # Assert
    layer = _layer(answer, "2023")
    assert layer["variant"] == {
        "product": "nmt",
        "horizontal_crs": "EPSG:2180",
        "resolution": "1m",
        "vertical_crs": "EPSG:9651",
        "segments": [NMT, NMT_ASCII],
        "formats": ["ASCII Grid", "ZIP"],
    }
    assert (layer["versions_count"], layer["units_count"]) == (4, 2)
    assert layer["preview"]["total"] == 3
    archive = served.store.version(SHEET_NW, "82710", NMT_ASCII).path
    states = {
        _path(item["ref"]): item["preview"]["state"] for item in layer["versions"]
    }
    assert states[archive] == "unavailable"
    assert [
        other["key"]
        for other in answer["layers"]
        if NMT_ASCII in other["variant"]["segments"]
    ] == [layer["key"]]


def test_variant_falls_back_to_segment_without_metadata(
    served: ServedLayers, area: str
) -> None:
    """Without ``resolution`` or ``vertical_crs`` a version's variant is its segment."""
    # Act
    answer = _layers(served.api, area)

    # Assert
    sparse = _layer(answer, "2023", by_segment=True)
    full = _layer(answer, "2023")
    assert sparse["key"] == f"{NMT}:2023"
    assert re.fullmatch(r"[0-9a-f]{12}:2023", full["key"])
    assert sparse["variant"] == {
        "product": "nmt",
        "horizontal_crs": "EPSG:2180",
        "resolution": None,
        "vertical_crs": None,
        "segments": [NMT],
        "formats": ["ASCII Grid"],
    }
    assert [version["unit"] for version in sparse["versions"]] == [SHEET_SW]
    assert SHEET_SW not in {version["unit"] for version in full["versions"]}


def test_layer_coverage_planar(served: ServedLayers) -> None:
    """A layer's share of the area is measured in EPSG:2180, not in degrees.

    The area is a strip 1.6° tall from ``AREA_SHEET`` north; the 2019 layer
    is the box of ``SHEET_NW`` in EPSG:2180 (its footprint). Both are moved
    and measured here with pyproj and shapely. A degree of longitude has
    fewer metres the further north, so the share in degrees is another one.
    """
    # Arrange
    west, south, east, _ = shape(sheet_polygon(AREA_SHEET)).bounds
    strip = box(west, south, east, south + 1.6)
    to_planar = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)
    region = shapely.transform(
        shapely.segmentize(strip, 0.001), to_planar.transform, interleaved=False
    )
    footprint = box(*sheet_bounds(SHEET_NW))
    share = footprint.intersection(region).area / region.area
    to_degrees = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
    outline = shapely.transform(
        shapely.segmentize(footprint, 10.0), to_degrees.transform, interleaved=False
    )
    in_degrees = outline.intersection(strip).area / strip.area
    strip_area = _area(served.api, mapping(strip))

    # Act
    answer = _layers(served.api, strip_area)

    # Assert
    assert answer["frame"]["crs"] == "EPSG:2180"
    assert answer["frame"]["bbox"] == pytest.approx(list(region.bounds), abs=0.01)
    coverage = _layer(answer, "2019")["coverage"]
    assert coverage["ratio"] == pytest.approx(share, rel=1e-5)
    assert abs(coverage["ratio"] - in_degrees) > 0.01 * in_degrees
    assert (coverage["percent"], coverage["label"]) == (
        0,
        message("local.coverage_below_one"),
    )


def test_outlines_in_frame_crs(served: ServedLayers, area: str) -> None:
    """Outlines come in the frame's CRS: every sheet's box in EPSG:2180, to the cm."""
    # Act
    answer = _layers(served.api, area)

    # Assert
    frame = answer["frame"]
    assert frame["crs"] == "EPSG:2180"
    assert frame["bbox"] == pytest.approx(list(sheet_bounds(AREA_SHEET)), abs=0.01)
    cutout = _cutout(served.store)
    for layer in answer["layers"]:
        features = layer["outlines"]["features"]
        refs = [feature["properties"]["ref"] for feature in features]
        assert refs == [version["ref"] for version in layer["versions"]]
        for feature in features:
            stored = served.store.by_path(_path(feature["properties"]["ref"]))
            expected = CUTOUT_BOUNDS if stored == cutout else sheet_bounds(stored.unit)
            outline = shape(feature["geometry"])
            assert outline.bounds == pytest.approx(expected, abs=0.01)
            assert outline.area == pytest.approx(box(*expected).area, rel=1e-5)


@pytest.mark.parametrize("how", ["missing", "empty_mount_point"])
def test_refresh_before_answer_and_stale_when_disconnected(
    tmp_path: Path, how: str
) -> None:
    """A flight added after the scan is in the first answer; a gone store: the index.

    The area's slots are rescanned before the answer, so the 2024 flight over
    ``SHEET_FAR`` written after the scan is a layer at once. With the store
    disconnected the layers come from the index, marked stale, and nothing
    is built: an area never shown before keeps its previews to build.
    """
    with served_layer_store(tmp_path) as served:
        # Arrange
        api = served.api
        area = _area(api, sheet_polygon(SHEET_FAR))
        unseen_area = _area(api, sheet_polygon(SHEET_NW))
        added = add_campaign(
            served.store.root, SHEET_FAR, "2024-07-01", "90417", downloaded="2026-10-18"
        )
        scanned = _layers(api)

        # Act
        refreshed = _layers(api, area)
        _wait_for_builds(api, refreshed)
        root = served.store.root
        shutil.move(root, root.with_name("odlaczony"))
        if how == "empty_mount_point":
            root.mkdir()
        jobs = _preview_jobs(api)
        stale = _layers(api, area)
        unseen = _layers(api, unseen_area)
        jobs_after = _preview_jobs(api)

    # Assert
    assert "2024" not in {layer["title"] for layer in scanned["layers"]}
    assert [layer["title"] for layer in refreshed["layers"]] == ["2024", "2019"]
    assert _paths(_layer(refreshed, "2024")) == [added.path]
    assert (refreshed["stale"], refreshed["stale_reason"]) == (False, None)
    for answer in (stale, unseen):
        assert (answer["stale"], answer["stale_reason"]) == (True, "store_unavailable")
        assert [item["store"] for item in answer["stale_stores"]] == [STORE]
    assert _summary(stale) == _summary(refreshed)
    assert unseen["layers"]
    for layer in unseen["layers"]:
        assert (layer["preview"]["state"], layer["preview"]["job"]) == (
            "needs_build",
            None,
        )
    assert jobs_after == jobs


def _summary(answer: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (layer["key"], layer["versions_count"], layer["units_count"], layer["coverage"])
        for layer in answer["layers"]
    ]


@dataclass(frozen=True)
class LayerBuild:
    """The 2023 layer of two adjacent sheets with one ready version, then all.

    ``before`` and ``after`` are the layer in the answers around the build of
    its missing previews; ``thumbnails`` and ``tiles`` the images of their
    addresses (``v``), fetched at once; ``tile`` is ``(z, x, y)`` of a map
    tile across the sheets' common edge; ``frame`` the frame of the answers.
    """

    served: ServedLayers
    before: dict[str, Any]
    after: dict[str, Any]
    frame: list[float]
    thumbnails: tuple[httpx.Response, httpx.Response]
    tiles: tuple[httpx.Response, httpx.Response]
    tile: tuple[int, int, int]


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LayerBuild]:
    """Build the north-west flight of 2023, then let the layer build the rest.

    The answer with one ready version names the layer's ``preview`` job,
    which builds the north-east sheet's two flights of 2023. The images of
    each answer's addresses are fetched right after it, while its layer is
    kept for them (``LayerMemo``, a minute).
    """
    with served_layer_store(tmp_path_factory.mktemp("layer-build")) as served:
        api = served.api
        first = served.store.version(SHEET_NW, "82710")
        posted = api.post(version_url(first.path), {"force": False})
        assert posted.status_code == 202, posted.text
        api.wait(posted.json()["id"])
        sheets = [shape(sheet_polygon(sheet)) for sheet in (SHEET_NW, SHEET_NE)]
        area = _area(api, mapping(shapely.union_all(sheets)))
        north = shape(sheet_polygon(SHEET_NW)).bounds
        found = TILES.tile(EDGE_LONGITUDE, (north[1] + north[3]) / 2, TILE_ZOOM)
        tile = (found.z, found.x, found.y)
        answer = _layers(api, area, segment=NMT)
        before = _layer(answer, "2023")
        images_before = _images(api, before, tile)
        api.wait(before["preview"]["job"]["id"])
        after = _layer(_layers(api, area, segment=NMT), "2023")
        images_after = _images(api, after, tile)
        yield LayerBuild(
            served=served,
            before=before,
            after=after,
            frame=answer["frame"]["bbox"],
            thumbnails=(images_before[0], images_after[0]),
            tiles=(images_before[1], images_after[1]),
            tile=tile,
        )


def _images(
    api: PreviewApi, layer: dict[str, Any], tile: tuple[int, int, int]
) -> tuple[httpx.Response, httpx.Response]:
    preview = layer["preview"]
    z, x, y = tile
    return (
        api.get(f"{preview['thumbnail_url']}&size=512"),
        api.get(preview["tiles_url"].format(z=z, x=x, y=y)),
    )


def _raster(sheet: str) -> Bounds:
    """Return the box an ASC grid of the store covers (square cells, sheet's width)."""
    min_x, min_y, max_x, _ = sheet_bounds(sheet)
    return (min_x, min_y, max_x, min_y + max_x - min_x)


def _only(x: Grid, y: Grid, inside: str, outside: str) -> Mask:
    """Pixels on one sheet's raster, ``MARGIN_M`` away from the other's."""
    return _within(x, y, _raster(inside), -MARGIN_M) & ~_within(
        x, y, _raster(outside), MARGIN_M
    )


def _within(x: Grid, y: Grid, bounds: Bounds, grow: float) -> Mask:
    min_x, min_y, max_x, max_y = bounds
    inside: Mask = (
        (x > min_x - grow)
        & (x < max_x + grow)
        & (y > min_y - grow)
        & (y < max_y + grow)
    )
    return inside


def _frame_pixels(frame: list[float], rows: int, columns: int) -> tuple[Grid, Grid]:
    """Return the EPSG:2180 centres of a thumbnail's pixels."""
    min_x, min_y, max_x, max_y = frame
    across = min_x + (np.arange(columns) + 0.5) * (max_x - min_x) / columns
    down = max_y - (np.arange(rows) + 0.5) * (max_y - min_y) / rows
    x, y = np.meshgrid(across, down)
    return x, y


def _tile_pixels(z: int, x: int, y: int) -> tuple[Grid, Grid]:
    """Return the EPSG:2180 centres of a 256-pixel map tile's pixels."""
    left, bottom, right, top = TILES.xy_bounds(morecantile.Tile(x, y, z))
    across = left + (np.arange(256) + 0.5) * (right - left) / 256
    down = top - (np.arange(256) + 0.5) * (top - bottom) / 256
    mercator_x, mercator_y = np.meshgrid(across, down)
    planar_x, planar_y = TO_PLANAR.transform(mercator_x, mercator_y)
    return np.asarray(planar_x), np.asarray(planar_y)


def test_layer_thumbnail_partial_then_full_after_build(build: LayerBuild) -> None:
    """The thumbnail shows the ready versions; after the layer's job, all of them.

    Each address (``v``) names exactly what its image was drawn from, so
    both images are immutable; a client holding one gets ``304``.
    """
    # Act
    partial, full = (decoded_png(response.content) for response in build.thumbnails)
    again = build.served.api.get(
        f"{build.after['preview']['thumbnail_url']}&size=512",
        etag=build.thumbnails[1].headers["etag"],
    )

    # Assert
    before, after = build.before["preview"], build.after["preview"]
    assert (before["state"], before["ready"], before["total"]) == ("building", 1, 3)
    assert before["job"] is not None
    assert (after["state"], after["ready"], after["total"], after["job"]) == (
        "ready",
        3,
        3,
        None,
    )
    assert before["thumbnail_url"] != after["thumbnail_url"]
    for response in build.thumbnails:
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == VERSION_CACHE_CONTROL
    assert build.thumbnails[0].headers["etag"] != build.thumbnails[1].headers["etag"]
    x, y = _frame_pixels(build.frame, *partial.shape[1:])
    west, east = _only(x, y, SHEET_NW, SHEET_NE), _only(x, y, SHEET_NE, SHEET_NW)
    assert west.any() and east.any()
    assert (partial[3][west] == 255).all() and (partial[3][east] == 0).all()
    assert (full[3][west] == 255).all() and (full[3][east] == 255).all()
    assert again.status_code == 304


def test_layer_tile_composes_version_tiles(build: LayerBuild) -> None:
    """A tile across two sheets has pixels of both; one without a preview is clear.

    Where only one sheet lies, the layer's tile is that sheet's own tile (the
    north-east sheet's newest flight on top). Below the layer's ``minzoom``
    and away from it: ``404``.
    """
    # Arrange
    api, store = build.served.api, build.served.store
    z, x, y = build.tile
    after = build.after["preview"]
    centre = TILES.tile(EDGE_LONGITUDE, 52.4, after["minzoom"] - 1)

    # Act
    partial, full = (decoded_png(response.content) for response in build.tiles)
    own = [
        decoded_png(
            api.get(
                version_url(store.version(sheet, flight).path, f"tiles/{z}/{x}/{y}.png")
            ).content
        )
        for sheet, flight in ((SHEET_NW, "82710"), (SHEET_NE, "83501"))
    ]
    below = api.get(after["tiles_url"].format(z=centre.z, x=centre.x, y=centre.y))
    away = api.get(after["tiles_url"].format(z=after["minzoom"], x=0, y=0))

    # Assert
    for response in build.tiles:
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == VERSION_CACHE_CONTROL
    planar_x, planar_y = _tile_pixels(z, x, y)
    west = _only(planar_x, planar_y, SHEET_NW, SHEET_NE)
    east = _only(planar_x, planar_y, SHEET_NE, SHEET_NW)
    assert west.any() and east.any()
    assert (partial[3][west] == 255).all() and (partial[3][east] == 0).all()
    assert (full[3][west] == 255).all() and (full[3][east] == 255).all()
    assert np.array_equal(full[:, west], own[0][:, west])
    assert np.array_equal(full[:, east], own[1][:, east])
    assert_problem(below, 404, "not_found")
    assert_problem(away, 404, "not_found")


def test_without_area_counts_only(served: ServedLayers, area: str) -> None:
    """Without an area: the whole store's versions counted, nothing drawn or built."""
    # Arrange
    inside = _layers(served.api, area)
    jobs = _preview_jobs(served.api)

    # Act
    whole = _layers(served.api)

    # Assert
    assert (whole["area"], whole["frame"], whole["stale"]) == (None, None, False)
    for layer in whole["layers"]:
        drawn = (layer["coverage"], layer["outlines"], layer["preview"])
        assert drawn == (None, None, None)
        assert layer["versions"] is None
    assert [layer["key"] for layer in whole["layers"]] == [
        layer["key"] for layer in inside["layers"]
    ]
    counts = {
        layer["key"]: (layer["versions_count"], layer["units_count"])
        for layer in whole["layers"]
    }
    assert counts[_layer(inside, "2019")["key"]] == (2, 2)
    assert _layer(inside, "2019")["versions_count"] == 1
    assert counts[_layer(inside, "2023")["key"]] == (4, 2)
    assert _preview_jobs(served.api) == jobs


def _bounds(values: list[float]) -> Bounds:
    return values[0], values[1], values[2], values[3]


def _rewrite(
    path: Path, work: Path, start: tuple[float, float], end: tuple[float, float]
) -> Bounds:
    """Save another version of a GeoPackage, one pipe; return its extent."""
    pipe = shapely.LineString([start, end])
    fresh = work / path.name
    pyogrio.raw.write(
        fresh,
        np.array([shapely.to_wkb(pipe)], dtype=object),
        [np.array([110], dtype=np.int32)],
        ["srednica_mm"],
        layer="przewody",
        driver="GPKG",
        geometry_type="LineString",
        crs="EPSG:2180",
    )
    os.replace(fresh, path)
    return _bounds(list(pipe.bounds))


def _snapshot(
    folder: Path, path: str, work: Path, created_at: datetime, extent: Bounds
) -> SnapshotFixture:
    """Snapshot a GeoPackage as published: its content identity and extent."""
    identity = content_identity([folder / path], method="sqlite", work_dir=work)
    return write_snapshot_fixture(
        folder,
        path,
        created_at=created_at,
        content=(identity.method, identity.sha256),
        extent={"crs": "EPSG:2180", "bbox": list(extent), "wgs84": None},
    )


def test_own_file_layers_current_first(tmp_path: Path) -> None:
    """An own file's layers: the working file on top, then its snapshots, newest first.

    Each layer is one object with its ``ref``. The frame holds every
    object's extent (none holds the others) in EPSG:2180, and each
    thumbnail draws its object there, revalidated as own data; a project
    the caller does not see is ``404``.
    """
    with own_data_api(tmp_path, first=("gpkg_layers",), second=()) as served:
        # Arrange
        project, owner = served.first, served.owner
        path = project.folder.file("gpkg_layers").path
        working, work = project.root / path, tmp_path / "edycje"
        work.mkdir()
        first = _bounds(
            owner.request("GET", project.url(path)).json()["extent"]["bbox"]
        )
        older = _snapshot(
            project.root, path, work, datetime(2026, 9, 1, 9, tzinfo=UTC), first
        )
        east = _rewrite(working, work, (569_000.0, 243_000.0), (571_500.0, 243_500.0))
        newer = _snapshot(
            project.root, path, work, datetime(2026, 10, 1, 9, tzinfo=UTC), east
        )
        north = _rewrite(working, work, (567_000.0, 246_000.0), (568_000.0, 247_800.0))
        served.scan()

        # Act
        answer = owner.request("GET", project.url(path, "layers"))
        thumbnails = [
            served.get(owner, layer["preview"]["thumbnail_url"])
            for layer in answer.json()["layers"]
        ]
        share(served.api.state, project.access_key, "private")
        hidden = served.caller("other").request("GET", project.url(path, "layers"))

    # Assert
    assert answer.status_code == 200, answer.text
    body = answer.json()
    layers = body["layers"]
    assert [(layer["key"], layer["kind"], layer["title"]) for layer in layers] == [
        ("file", "file", message("layer.title_working")),
        (
            f"snapshot:{newer.label}",
            "snapshot",
            message("layer.title_snapshot", label=newer.label),
        ),
        (
            f"snapshot:{older.label}",
            "snapshot",
            message("layer.title_snapshot", label=older.label),
        ),
    ]
    assert [[version["ref"] for version in layer["versions"]] for layer in layers] == [
        [project.ref(path)],
        [f"snapshot:{project.key}:{newer.label}:{path}"],
        [f"snapshot:{project.key}:{older.label}:{path}"],
    ]
    assert (body["area"], body["store"], body["product"], body["group"]) == (
        None,
        None,
        None,
        None,
    )
    extents = (north, east, first)
    union = (
        min(extent[0] for extent in extents),
        min(extent[1] for extent in extents),
        max(extent[2] for extent in extents),
        max(extent[3] for extent in extents),
    )
    frame = body["frame"]["bbox"]
    longer = max(union[2] - union[0], union[3] - union[1])
    assert body["frame"]["crs"] == "EPSG:2180"
    assert frame[0] <= union[0] and frame[1] <= union[1]
    assert frame[2] >= union[2] and frame[3] >= union[3]
    assert all(abs(frame[i] - union[i]) <= longer / 20 for i in range(4))
    for layer, extent, response in zip(layers, extents, thumbnails, strict=True):
        assert layer["preview"]["state"] == "ready"
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == OWN_CACHE_CONTROL
        image = decoded_png(response.content)
        x, y = _frame_pixels(frame, *image.shape[1:])
        pixel = (frame[2] - frame[0]) / image.shape[2]
        drawn = image[3] > 0
        assert drawn.any()
        assert not (drawn & ~_within(x, y, extent, 2 * pixel)).any()
    assert_problem(hidden, 404, "not_found")
