"""Local coverage of an area over HTTP (plan step 9c, decision 5, SPEC 4.4).

A generated store is scanned into the index; ``GET /local-coverage`` must
rescan the area's slots before answering, measure the share in EPSG:2180
for Polish files, and answer from the index (``stale``) when the store is
gone, the rescan runs out of time or the area holds too many slots.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import shapely
from fastapi import FastAPI
from pyproj import Transformer
from shapely.geometry import box, mapping, shape

from archiwista.api.areas import read_local_coverage
from archiwista.api.models import CoverageQuery
from archiwista.messages import message
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE, ServedStore, served_store
from tests.fixtures.area_files import gdal_file, upload
from tests.fixtures.make_store import NMT, ExpectedEntry
from tests.fixtures.store_edits import sidecar_path

# Synthetic JPEG sheets of the store carry no geotransform; rasterio says so.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

# Height of the strip north of a file in the planar test, metres.
_STRIP_M = 200_000.0


@pytest.fixture
def served(tmp_path: Path) -> Iterator[ServedStore]:
    """Serve a generated, scanned store with the local owner's session."""
    with served_store(tmp_path) as store:
        yield store


def _sheets(
    served: ServedStore, *, family: str | None = "asc_sheet"
) -> list[tuple[ExpectedEntry, Any]]:
    """NMT files of the store (standard paths) with their WGS84 outline.

    ``family`` narrows them to one kind, e.g. sheets; ``None`` keeps all.
    """
    found = []
    for link in served.store.by_kind("link"):
        if link.segment != NMT or link.case != "regular":
            continue
        if family is not None and link.family != family:
            continue
        card = served.owner.request(
            "GET", f"/stores/{STORE}/versions/{link.version_path}"
        )
        if card.status_code == 200 and card.json()["footprint"] is not None:
            found.append((link, shape(card.json()["footprint"])))
    assert found
    return found


def _area(served: ServedStore, geometry: Any) -> str:
    response = served.owner.request(
        "POST", "/areas", json={"geometry": mapping(geometry)}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _coverage(served: ServedStore, area: str) -> dict[str, Any]:
    response = served.owner.request(
        "GET",
        f"/local-coverage?area_id={area}&product=nmt&store={STORE}&segment={NMT}",
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _remove_link(served: ServedStore, link: ExpectedEntry) -> None:
    """Delete a slot's standard path, as if someone removed the file."""
    (served.store.root / link.path).unlink()
    sidecar_path(served.store.root, link.path).unlink()


def test_local_coverage_refreshes_area_slots_before_answering(
    served: ServedStore,
) -> None:
    """A file removed after the scan is gone from the very next answer."""
    # Arrange
    link, outline = _sheets(served)[0]
    area = _area(served, outline)
    before = _coverage(served, area)
    _remove_link(served, link)

    # Act
    after = _coverage(served, area)

    # Assert
    assert before["results"][0]["percent"] == 100
    assert before["results"][0]["label"] == message(
        "local.coverage_percent", percent=100
    )
    assert (before["stale"], after["stale"], after["stale_reason"]) == (
        False,
        False,
        None,
    )
    assert after["results"][0]["ratio"] < before["results"][0]["ratio"]
    slot = served.owner.request("GET", f"/stores/{STORE}/slots/{link.path}").json()
    assert slot["current"] is None


def test_local_coverage_percent_measured_in_planar_crs(
    served: ServedStore, tmp_path: Path
) -> None:
    """The share is the one in EPSG:2180, not the one in degrees.

    A file downloaded for a request bbox in EPSG:2180 covers exactly that
    rectangle; the area is a 200 km strip north of it, read from a GeoJSON
    file in EPSG:2180, so the planar share is width × height arithmetic.
    """
    # Arrange
    every = _sheets(served, family=None)
    to_wgs84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
    for item in every:
        link, outline = item
        if link.family != "tif_bbox":
            continue
        bounds = [float(value) for value in (link.unit or "").split("_")]
        min_x, min_y, max_x, max_y = bounds
        strip = box(min_x, min_y, max_x, min_y + _STRIP_M)
        moved = shapely.transform(
            shapely.segmentize(strip, 100.0), to_wgs84.transform, interleaved=False
        )
        crossed = [
            other
            for entry, other in every
            if entry is not link
            and shapely.intersects(moved, other)
            and not shapely.touches(moved, other)
        ]
        if not crossed:
            break
    else:
        pytest.fail("every strip holds another file of the segment")
    covered_km2 = (max_x - min_x) * (max_y - min_y) / 1e6
    area_km2 = (max_x - min_x) * _STRIP_M / 1e6
    in_degrees = shapely.intersection(outline, moved).area / moved.area
    content = gdal_file(
        tmp_path, "pas.geojson", driver="GeoJSON", geometries=[strip]
    ).read_bytes()
    created = upload(served.owner, content)
    assert created.status_code == 201, created.text

    # Act
    answer = _coverage(served, created.json()["id"])

    # Assert
    assert created.json()["area_km2"] == pytest.approx(area_km2, rel=1e-6)
    (result,) = answer["results"]
    assert (result["country"], result["crs"]) == ("PL", "EPSG:2180")
    assert result["area_km2"] == pytest.approx(area_km2, rel=1e-6)
    assert result["covered_km2"] == pytest.approx(covered_km2, rel=1e-5)
    assert result["ratio"] == pytest.approx(covered_km2 / area_km2, rel=1e-5)
    assert abs(result["ratio"] - in_degrees) > 0.01 * in_degrees
    assert result["versions_count"] == 1


@pytest.mark.parametrize("how", ["missing", "empty_mount_point"])
def test_local_coverage_stale_when_store_disconnected(
    served: ServedStore, how: str
) -> None:
    """A disconnected store answers from the index, marked stale, not empty."""
    # Arrange
    _, outline = _sheets(served)[0]
    area = _area(served, outline)
    before = _coverage(served, area)
    root = served.store.root
    shutil.move(root, root.with_name("odlaczony"))
    if how == "empty_mount_point":
        root.mkdir()

    # Act
    after = _coverage(served, area)

    # Assert
    assert (after["stale"], after["stale_reason"]) == (True, "store_unavailable")
    assert [item["store"] for item in after["stale_stores"]] == [STORE]
    assert after["results"] == before["results"]


@pytest.mark.parametrize(
    ("limits", "reason"),
    [({"timeout_s": 0.0}, "refresh_timeout"), ({"max_units": 1}, "too_many_slots")],
)
def test_local_coverage_without_rescan_answers_from_index(
    served: ServedStore, limits: dict[str, Any], reason: str
) -> None:
    """Out of time, or over the slot limit: the index answers, marked stale."""
    # Arrange: two neighbouring sheets, one of them removed after the scan.
    sheets = _sheets(served)
    (link, first), second = next(
        (one, two)
        for one in sheets
        for two in sheets
        if one is not two and shapely.touches(one[1], two[1])
    )
    area = _area(served, shapely.union_all([first, second[1]]))
    _remove_link(served, link)
    app = cast(FastAPI, served.api.client.app)
    query = CoverageQuery(area_id=area, product="nmt", store=STORE, segment=NMT)

    # Act
    answer = read_local_coverage(
        app.state.queries,
        app.state.settings.get(),
        served.registry,
        served.api.paths.index_file,
        query,
        **limits,
    )

    # Assert
    assert (answer.stale, answer.stale_reason, answer.stale_stores) == (
        True,
        reason,
        [],
    )
    (result,) = answer.results
    assert result.percent == 100
    slot = served.owner.request("GET", f"/stores/{STORE}/slots/{link.path}").json()
    assert slot["current"] is not None


def test_local_coverage_refuses_unknown_area_store_and_parameters(
    served: ServedStore,
) -> None:
    """Unknown areas, stores and parameters are 400, never an empty answer."""
    # Arrange
    _, outline = _sheets(served)[0]
    area = _area(served, outline)

    # Act
    answers = [
        served.owner.request("GET", path)
        for path in (
            f"/local-coverage?area_id=nieznany&product=nmt&store={STORE}",
            f"/local-coverage?area_id={area}&product=nmt&store=inny",
            f"/local-coverage?area_id={area}&product=nmt",
            f"/local-coverage?area_id={area}&product=nmt&store={STORE}&bbox=1,2,3,4",
        )
    ]

    # Assert
    for response in answers:
        assert_problem(response, 400, "validation_error")
