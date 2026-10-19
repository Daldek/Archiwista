"""Previews of store versions over HTTP (plan v0.2, step 6; decisions 3 and 13).

The application serves a generated store with real render processes and a
job supervisor with the real worker (``tests.fixtures.preview_api``), so
every answer comes from the renderers of step 5. The module's store is
shared by the tests that only read; a test that builds or disconnects the
store has one of its own.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from archiwista.api.previews import VERSION_CACHE_CONTROL
from archiwista.messages import MESSAGES
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE
from tests.fixtures.preview_api import (
    PreviewApi,
    center_tile_url,
    decoded_png,
    entry_of,
    preview_api,
    version_url,
)

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PreviewApi]:
    """Serve one generated store with previews for the reading tests."""
    with preview_api(tmp_path_factory.mktemp("previews")) as found:
        yield found


def _info(served: PreviewApi, path: str) -> dict[str, Any]:
    response = served.get(version_url(path))
    assert response.status_code == 200, response.text
    info: dict[str, Any] = response.json()
    return info


def test_routes_answer_each_kind_of_file(served: PreviewApi) -> None:
    """Description, thumbnail, tile, features, members and a build of nothing."""
    # Arrange
    raster = entry_of(served.store, "tif_sheet", "regular").path
    vector = entry_of(served.store, "gpkg_teryt").path
    archive = entry_of(served.store, "zip_teryt", "regular").path
    info = _info(served, raster)
    vector_info = _info(served, vector)
    features_url = vector_info["features_url"].format(
        bbox=",".join(str(value) for value in vector_info["bounds"]), zoom=14
    )
    archive_info = _info(served, archive)

    # Act
    thumbnail = served.get(f"{info['thumbnail_url']}?size=256")
    tile = served.get(center_tile_url(info))
    features = served.get(features_url)
    members = served.get(archive_info["members_url"])
    built = served.post(version_url(raster), {"force": False})

    # Assert
    assert (info["ref"], info["state"], info["kind"]) == (
        f"version:{STORE}:{raster}",
        "ready",
        "raster",
    )
    for image in (thumbnail, tile):
        assert image.status_code == 200, image.text
        assert image.headers["content-type"] == "image/png"
        assert image.headers["cache-control"] == VERSION_CACHE_CONTROL
        assert image.headers["etag"].startswith('"')
    assert 0 < max(decoded_png(thumbnail.content).shape[1:]) <= 256
    assert decoded_png(tile.content).shape[1:] == (256, 256)
    assert features.status_code == 200, features.text
    assert features.headers["content-type"] == "application/geo+json"
    collection = features.json()
    assert collection["type"] == "FeatureCollection" and collection["features"]
    assert {"number_matched", "truncated", "simplified"} <= set(collection)
    assert (archive_info["state"], archive_info["kind"]) == ("ready", "archive")
    assert members.status_code == 200, members.text
    listing = members.json()
    assert listing["ref"] == archive_info["ref"]
    assert listing["total"] == len(listing["members"]) > 0
    assert built.status_code == 200 and built.json() == info


@pytest.mark.parametrize(
    ("route", "field"),
    [
        ("preview.png?size=77", "query.size"),
        ("preview.png?style=nieznany", "query.style"),
        ("preview.png?bbox=1,2,3", "query.bbox"),
        ("preview.png?bbox_crs=WGS84", "query.bbox_crs"),
        ("tiles/23/0/0.png", "path.z"),
        ("tiles/3/8/0.png", "path.x"),
        ("tiles/3/0/8.png", "path.y"),
        ("tiles/12/0/0.png?rescale=450,200", "query.rescale"),
        ("features?zoom=14", "query.bbox"),
        ("features?bbox=19,50,20,51&zoom=23", "query.zoom"),
    ],
)
def test_invalid_parameters_are_422(served: PreviewApi, route: str, field: str) -> None:
    """Sizes, styles, frames, tile numbers, ranges and zooms are validated."""
    path = entry_of(served.store, "tif_sheet", "regular").path

    response = served.get(version_url(path, route))

    assert_problem(response, 422, "validation_error")
    assert field in [item["field"] for item in response.json()["errors"]]


def test_invalid_ref_is_422(served: PreviewApi) -> None:
    """A store id no store can have makes no reference (``invalid_ref``)."""
    response = served.get("/api/v1/stores/Zespol/versions/nmt/plik.asc/preview")

    assert_problem(response, 422, "invalid_ref")


def test_tiles_outside_zoom_range_or_extent_are_404(served: PreviewApi) -> None:
    """Past ``maxzoom``, before ``minzoom`` or away from the file: ``404``."""
    # Arrange
    info = _info(served, entry_of(served.store, "tif_sheet", "regular").path)
    minzoom, maxzoom = info["minzoom"], info["maxzoom"]

    # Act
    above = served.get(center_tile_url(info, maxzoom + 1))
    below = served.get(center_tile_url(info, minzoom - 1))
    away = served.get(info["tiles_url"].format(z=minzoom, x=0, y=0))

    # Assert
    for response in (above, below, away):
        assert_problem(response, 404, "not_found")


def test_tiles_not_ready_until_build_then_ready(tmp_path: Path) -> None:
    """An ASC sheet's tiles: ``409 preview_not_ready``, ``POST`` ``202``, ready."""
    with preview_api(tmp_path) as served:
        # Arrange
        path = entry_of(served.store, "asc_sheet", "regular").path
        before = _info(served, path)
        tile = center_tile_url(before)

        # Act
        refused = served.get(tile)
        posted = served.post(version_url(path), {"force": False})
        record = served.wait(posted.json()["id"])
        after = _info(served, path)
        shown = served.get(tile)

    # Assert
    assert (before["state"], before["auto_build"], before["job"]) == (
        "needs_build",
        True,
        None,
    )
    assert_problem(refused, 409, "preview_not_ready")
    assert refused.json()["build_required"] is True
    assert posted.status_code == 202, posted.text
    job = posted.json()
    assert job["kind"] == "preview" and job["params"]["refs"] == [before["ref"]]
    assert posted.headers["location"] == f"/api/v1/jobs/{job['id']}"
    assert record.state == "succeeded" and record.result is not None
    assert record.result["built"] == 1
    assert (after["state"], after["job"]) == ("ready", None)
    assert shown.status_code == 200, shown.text
    assert decoded_png(shown.content).shape[1:] == (256, 256)


def test_etag_answers_304_without_rendering(served: PreviewApi) -> None:
    """``If-None-Match`` naming the ``ETag`` is ``304``; nothing is rendered."""
    # Arrange
    raster = _info(served, entry_of(served.store, "tif_oblique").path)
    archive = _info(served, entry_of(served.store, "zip_ku").path)
    image_url = f"{raster['thumbnail_url']}?size=128"
    members_url = archive["members_url"]
    first_image = served.get(image_url)
    first_members = served.get(members_url)
    rendered = served.pool.stats().rendered

    # Act
    image = served.get(image_url, etag=first_image.headers["etag"])
    members = served.get(members_url, etag=first_members.headers["etag"])
    other = served.get(image_url, etag='"inny"')

    # Assert
    for response, first in ((image, first_image), (members, first_members)):
        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["etag"] == first.headers["etag"]
        assert response.headers["cache-control"] == VERSION_CACHE_CONTROL
    assert other.status_code == 200 and other.content == first_image.content
    assert served.pool.stats().rendered == rendered


def test_preview_unavailable_carries_reason(served: PreviewApi) -> None:
    """A PDF has no preview, a PNG without georeference no map: each says why."""
    # Arrange
    document = entry_of(served.store, "pdf_map").path
    image = entry_of(served.store, "png_preview").path
    picture = _info(served, image)

    # Act
    info = _info(served, document)
    thumbnail = served.get(version_url(document, "preview.png"))
    tile = served.get(version_url(image, "tiles/12/2275/1388.png"))

    # Assert
    assert (info["state"], info["thumbnail_url"], info["tiles_url"]) == (
        "unavailable",
        None,
        None,
    )
    assert info["reason"] == {
        "code": "document_no_preview",
        "message": MESSAGES["preview_reason_document_no_preview"],
        "fix": MESSAGES["preview_fix_document_no_preview"],
        "detail": None,
    }
    assert_problem(thumbnail, 409, "preview_unavailable")
    assert thumbnail.json()["reason"] == info["reason"]
    assert (picture["state"], picture["tiles_url"]) == ("ready", None)
    assert picture["reason"]["code"] == "no_georeference"
    assert_problem(tile, 409, "preview_unavailable")
    assert tile.json()["reason"]["code"] == "no_georeference"


@pytest.mark.parametrize("mount_point", [False, True], ids=["gone", "empty_mount"])
def test_disconnected_store_answers_from_cache_or_503(
    tmp_path: Path, mount_point: bool
) -> None:
    """With the store gone, what was rendered comes from the cache; nothing else.

    A share that is not mounted may leave its empty mount point: the store is
    indexed, so an empty directory is unavailable too, not a missing file.
    """
    with preview_api(tmp_path) as served:
        # Arrange
        seen = entry_of(served.store, "tif_sheet", "regular").path
        unseen = entry_of(served.store, "tif_bbox").path
        thumbnail = version_url(seen, "preview.png")
        rendered = served.get(thumbnail)
        known = _info(served, seen)
        root = served.store.root
        root.rename(root.with_name("odlaczony"))
        if mount_point:
            root.mkdir()
        try:
            # Act
            cached = served.get(thumbnail)
            described = _info(served, seen)
            unknown = _info(served, unseen)
            refused = served.get(version_url(unseen, "preview.png"))
        finally:
            if mount_point:
                root.rmdir()
            root.with_name("odlaczony").rename(root)

    # Assert
    assert cached.status_code == 200 and cached.content == rendered.content
    assert described == known
    assert unknown["state"] == "unavailable"
    assert unknown["reason"]["code"] == "store_unavailable"
    assert_problem(refused, 503, "store_unavailable")


def test_preview_routes_need_csrf(served: PreviewApi) -> None:
    """Every preview route, reads included, refuses a request without CSRF."""
    path = entry_of(served.store, "tif_sheet", "regular").path

    answers = [
        served.get(version_url(path), csrf=False),
        served.get(version_url(path, "preview.png"), csrf=False),
        served.get(version_url(path, "tiles/12/2275/1388.png"), csrf=False),
        served.post(version_url(path), {"force": False}, csrf=False),
    ]

    for response in answers:
        assert_problem(response, 403, "csrf_rejected")
