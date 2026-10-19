"""Projects' own data over HTTP: files, previews, snapshots, data folder (step 9).

Plan v0.2, step 9 (criterion 6 over HTTP): a project's data folder is listed
with extents, every indexed file answers its preview or the reason it has
none, a snapshot is planned without writing, made by a ``snapshot`` job and
shown on the file's card, a file changed since its scan is refused until the
next scan, and only an administrator gives a project another data folder.
Every test serves a generated store whose project ``projekt-01`` has a data
folder of the families it needs (``tests.fixtures.own_data_api``).
"""

import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from archiwista.jobs import supervisor
from tests.fixtures.api_session import assert_problem
from tests.fixtures.own_data import ALL_OWN_FAMILIES, SNAPSHOT_FILE, SNAPSHOTS_DIR
from tests.fixtures.own_data_api import OwnDataApi, OwnProject, own_data_api
from tests.fixtures.permissions import share
from tests.fixtures.preview_api import PNG_SIGNATURE, center_tile_url, decoded_png

# The world-file TIFF and the store's JPEG sheets carry no geotransform;
# rasterio says so while writing and reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
OWN_CACHE_CONTROL = "private, no-cache"
VIEW_ZOOM = 14


def _info(served: OwnDataApi, project: OwnProject, path: str) -> dict[str, Any]:
    """Return the ``PreviewInfo`` of a working file, as the owner asks for it."""
    answer = served.owner.request("GET", project.url(path, "preview"))
    assert answer.status_code == 200, answer.text
    info: dict[str, Any] = answer.json()
    return info


def _features_url(info: dict[str, Any], layer: str | None = None) -> str:
    """Return the features of a ``PreviewInfo``'s whole extent (one layer)."""
    bbox = ",".join(str(value) for value in info["bounds"])
    url = str(info["features_url"]).format(bbox=bbox, zoom=VIEW_ZOOM)
    return url if layer is None else f"{url}&layer={layer}"


def _listing(root: Path) -> dict[str, tuple[int, int]]:
    """Return every entry below ``root`` with its size and modification time."""
    found: dict[str, tuple[int, int]] = {}
    for directory, names, files in os.walk(root):
        for name in (*names, *files):
            status = (Path(directory) / name).lstat()
            relative = (Path(directory) / name).relative_to(root).as_posix()
            found[relative] = (status.st_size, status.st_mtime_ns)
    return found


def _snapshot(
    served: OwnDataApi, project: OwnProject, path: str, note: str
) -> httpx.Response:
    """Ask for a snapshot of a file as the owner (``202`` with the job)."""
    return served.owner.request(
        "POST", project.url(path, "snapshots"), json={"note": note}
    )


def test_folder_with_gpkg_shp_geotiff_indexed_with_extent_and_preview(
    tmp_path: Path,
) -> None:
    """GeoPackage, Shapefile and GeoTIFF: listed, cards, thumbnails, tiles, features."""
    with own_data_api(
        tmp_path, first=("gpkg_layers", "shp_full", "tif_2180"), second=()
    ) as served:
        # Arrange
        project = served.first
        gpkg = project.folder.file("gpkg_layers")
        shp = project.folder.file("shp_full")
        tif = project.folder.file("tif_2180")
        owner = served.owner

        # Act
        listed = owner.request("GET", f"/projects/{project.key}/files")
        cards = {
            entry.path: owner.request("GET", project.url(entry.path)).json()
            for entry in project.folder.files
        }
        infos = {
            entry.path: _info(served, project, entry.path)
            for entry in project.folder.files
        }
        thumbnails = {
            path: served.get(owner, info["thumbnail_url"])
            for path, info in infos.items()
        }
        revalidated = served.get(
            owner,
            infos[tif.path]["thumbnail_url"],
            etag=thumbnails[tif.path].headers["etag"],
        )
        raster = infos[tif.path]
        if raster["state"] == "needs_build":
            posted = owner.request(
                "POST", project.url(tif.path, "preview"), json={"force": False}
            )
            assert posted.status_code == 202, posted.text
            assert served.wait(posted.json()["id"]).state == "succeeded"
            raster = _info(served, project, tif.path)
        tile = served.get(owner, center_tile_url(raster))
        gpkg_features = {
            layer.name: served.get(
                owner, _features_url(infos[gpkg.path], layer.name)
            ).json()
            for layer in gpkg.layers
        }
        shp_features = served.get(owner, _features_url(infos[shp.path])).json()

    # Assert
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["folder"]["state"] == "ok"
    assert page["folder"]["path"]["local"] == str(project.root)
    assert {
        item["path"]: (item["state"], item["location"]["kind"], item["ref"])
        for item in page["items"]
    } == {
        entry.path: ("ok", "footprint", project.ref(entry.path))
        for entry in (gpkg, shp, tif)
    }
    for entry in (gpkg, shp, tif):
        card = cards[entry.path]
        assert (card["format"], card["crs"]) == (entry.driver, entry.crs)
        assert len(card["extent"]["bbox"]) == 4
        assert card["extent"]["wgs84"]["type"] == "Polygon"
        assert card["preview"]["state"] in ("ready", "needs_build")
        assert card["paths"]["local"] == str(project.root / entry.path)
    assert [layer["name"] for layer in cards[gpkg.path]["layers"]] == [
        layer.name for layer in gpkg.layers
    ]
    described_raster = cards[tif.path]["raster"]
    assert (
        described_raster["width"],
        described_raster["height"],
        described_raster["bands"],
    ) == tif.raster
    for path, thumbnail in thumbnails.items():
        assert thumbnail.status_code == 200, (path, thumbnail.text)
        assert thumbnail.headers["content-type"] == "image/png"
        assert thumbnail.headers["cache-control"] == OWN_CACHE_CONTROL
        assert decoded_png(thumbnail.content).shape[0] >= 1
    assert revalidated.status_code == 304
    assert tile.status_code == 200, tile.text
    assert tile.content.startswith(PNG_SIGNATURE)
    pixels = decoded_png(tile.content)
    assert pixels.shape == (4, 256, 256)
    assert pixels[-1].max() > 0  # the raster shows in its central tile
    assert {
        name: (answer["type"], answer["number_matched"], len(answer["features"]))
        for name, answer in gpkg_features.items()
    } == {
        layer.name: ("FeatureCollection", layer.feature_count, layer.feature_count)
        for layer in gpkg.layers
    }
    assert shp_features["number_matched"] == shp.feature_count
    assert {feature["geometry"]["type"] for feature in shp_features["features"]} == {
        "Polygon"
    }


def test_own_file_types_have_preview_or_reason(tmp_path: Path) -> None:
    """Every listed file of every family answers its preview, or why it has none."""
    with own_data_api(tmp_path, first=ALL_OWN_FAMILIES, second=()) as served:
        # Arrange
        project = served.first
        files = f"/projects/{project.key}/files"

        # Act
        listed = served.owner.request("GET", f"{files}?limit=200").json()["items"]
        described = {
            item["path"]: served.owner.request(
                "GET", f"{files}/{item['file_id']}/preview"
            )
            for item in listed
        }
        thumbnails = {
            path: served.get(served.owner, answer.json()["thumbnail_url"])
            for path, answer in described.items()
            if answer.status_code == 200 and answer.json()["thumbnail_url"]
        }

    # Assert
    # A world file is listed apart from its image; hidden and linked-out are not.
    paths = set(described)
    assert {entry.path for entry in project.folder.indexed} <= paths
    assert paths.isdisjoint(
        entry.path for entry in project.folder.files if not entry.indexed
    )
    assert [
        (path, answer.status_code)
        for path, answer in described.items()
        if answer.status_code != 200
    ] == []
    for path, answer in described.items():
        info = answer.json()
        assert info["state"] in ("ready", "needs_build", "unavailable"), path
        if info["state"] == "unavailable":
            reason = info["reason"]
            assert reason["code"] and reason["message"] and reason["fix"], path
    assert described["skan.tfw"].json()["reason"]["code"] == "auxiliary_file"
    assert [
        (path, answer.status_code)
        for path, answer in thumbnails.items()
        if answer.status_code != 200
    ] == []


def test_snapshot_plan_job_and_card(tmp_path: Path) -> None:
    """Plan writes nothing; a snapshot job shows on the card; the same content again."""
    with own_data_api(tmp_path, first=("tif_2180",), second=()) as served:
        # Arrange
        project = served.first
        path = project.folder.file("tif_2180").path
        before = _listing(project.root)

        # Act
        plan = served.owner.request("GET", project.url(path, "snapshot-plan"))
        after_plan = _listing(project.root)
        started = _snapshot(served, project, path, "Przed zmianą trasy")
        first = served.wait(started.json()["id"])
        job = served.owner.request("GET", f"/jobs/{first.id}").json()
        card = served.owner.request("GET", project.url(path)).json()
        label = str(job["result"]["label"])
        snapshot_info = served.owner.request(
            "GET", project.snapshot_url(path, label)
        ).json()
        snapshot_thumbnail = served.get(served.owner, snapshot_info["thumbnail_url"])
        again = _snapshot(served, project, path, "Drugi raz")
        second = served.wait(again.json()["id"])
        card_again = served.owner.request("GET", project.url(path)).json()

    # Assert
    assert plan.status_code == 200, plan.text
    planned = plan.json()
    assert (planned["file"], planned["blocked"], planned["content_method"]) == (
        path,
        None,
        "bytes",
    )
    assert planned["destination"]["local"] == str(project.root / SNAPSHOTS_DIR / path)
    assert after_plan == before
    assert started.status_code == 202, started.text
    assert started.headers["location"] == f"/api/v1/jobs/{first.id}"
    assert started.json()["kind"] == "snapshot"
    assert started.json()["params"]["note"] == "Przed zmianą trasy"
    assert (job["state"], job["result"]["status"]) == ("succeeded", "created")
    assert (project.root / SNAPSHOTS_DIR / path / label / SNAPSHOT_FILE).is_file()
    assert [
        (item["label"], item["note"], item["ref"], item["state"])
        for item in card["snapshots"]
    ] == [(label, "Przed zmianą trasy", f"snapshot:{project.key}:{label}:{path}", "ok")]
    assert (card["change"], card["last_snapshot"]["label"]) == ("unchanged", label)
    assert snapshot_info["ref"] == f"snapshot:{project.key}:{label}:{path}"
    assert snapshot_info["state"] in ("ready", "needs_build")
    assert snapshot_thumbnail.status_code == 200, snapshot_thumbnail.text
    assert snapshot_thumbnail.content.startswith(PNG_SIGNATURE)
    assert second.state == "succeeded", second
    assert second.result is not None
    assert (second.result["status"], second.result["label"]) == ("unchanged", label)
    assert [item["label"] for item in card_again["snapshots"]] == [label]


def test_changed_file_is_own_file_changed_until_rescanned(tmp_path: Path) -> None:
    """A file changed after its scan: ``409 own_file_changed``, then new previews."""
    with own_data_api(tmp_path, first=("geojson_wgs84",), second=()) as served:
        # Arrange
        project = served.first
        path = project.folder.file("geojson_wgs84").path
        info = _info(served, project, path)
        working = project.root / path
        working.write_text(
            working.read_text(encoding="utf-8").replace("studnia", "zdroj"),
            encoding="utf-8",
        )
        status = working.stat()
        os.utime(working, ns=(status.st_atime_ns, status.st_mtime_ns + 5_000_000_000))

        # Act
        changed_thumbnail = served.get(served.owner, info["thumbnail_url"])
        changed_features = served.get(served.owner, _features_url(info))
        changed_info = _info(served, project, path)
        scan = served.owner.request("POST", f"/projects/{project.key}/scan")
        scanned = served.wait(scan.json()["id"])
        rescanned_info = _info(served, project, path)
        thumbnail = served.get(served.owner, rescanned_info["thumbnail_url"])
        features = served.get(served.owner, _features_url(rescanned_info))

    # Assert
    assert_problem(changed_thumbnail, 409, "own_file_changed")
    assert_problem(changed_features, 409, "own_file_changed")
    assert changed_info["state"] == "unavailable"
    assert changed_info["reason"]["code"] == "changed_since_scan"
    assert changed_info["reason"]["fix"]
    assert scan.status_code == 202, scan.text
    assert (scan.json()["kind"], scanned.state) == ("own_scan", "succeeded")
    assert rescanned_info["state"] == "ready"
    assert thumbnail.status_code == 200, thumbnail.text
    assert features.status_code == 200, features.text
    assert sorted(
        feature["properties"]["opis"] for feature in features.json()["features"]
    ) == ["hydrant", "zdroj"]


def test_data_dir_set_by_admin_only_and_checked(tmp_path: Path) -> None:
    """Non-admin ``403``; admin sets a folder and scans it; bad folders ``422``."""
    with own_data_api(tmp_path, first=("txt",), second=()) as served:
        # Arrange
        project = served.first
        share(served.api.state, project.access_key, "public")
        owner = served.caller("owner")
        admin = served.caller("admin")
        folder = tmp_path / "dane-projektu"
        folder.mkdir()
        (folder / "opis.txt").write_text("Nowy folder danych.\n", encoding="utf-8")
        address = f"/projects/{project.key}/data-dir"

        # Act
        refused = owner.request("PUT", address, json={"path": str(folder)})
        changed = admin.request("PUT", address, json={"path": str(folder)})
        jobs = admin.request("GET", f"/jobs?project={project.key}").json()["items"]
        scans = [job for job in jobs if job["kind"] == "own_scan"]
        finished = [served.wait(job["id"]).state for job in scans]
        in_store = admin.request(
            "PUT", address, json={"path": str(served.previews.store.root)}
        )
        missing = admin.request(
            "PUT", address, json={"path": str(tmp_path / "brak-folderu")}
        )
        listed = admin.request("GET", f"/projects/{project.key}/files").json()

    # Assert
    assert_problem(refused, 403, "permission_denied")
    assert changed.status_code == 200, changed.text
    assert (changed.json()["path"]["local"], changed.json()["source"]) == (
        str(folder),
        "setting",
    )
    assert changed.json()["state"] == "ok"
    assert finished == ["succeeded"]
    for answer, code in (
        (in_store, "own_data_dir_inside_store"),
        (missing, "own_data_dir_missing"),
    ):
        assert_problem(answer, 422, "validation_error")
        assert [problem["code"] for problem in answer.json()["problems"]] == [code]
    assert listed["folder"]["path"]["local"] == str(folder)
    assert [item["path"] for item in listed["items"]] == ["opis.txt"]


def test_snapshot_refused_while_blocked_or_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing file: ``409 snapshot_blocked``; a waiting snapshot: ``409 conflict``."""
    # Arrange: no free worker, so a snapshot waits in the queue.
    monkeypatch.setattr(supervisor, "default_max_jobs", lambda: 0)
    with own_data_api(
        tmp_path, first=("tif_2180", "geojson_wgs84"), second=()
    ) as served:
        project = served.first
        gone = project.folder.file("tif_2180").path
        waiting = project.folder.file("geojson_wgs84").path
        (project.root / gone).unlink()

        # Act
        plan = served.owner.request("GET", project.url(gone, "snapshot-plan"))
        blocked = _snapshot(served, project, gone, "")
        queued = _snapshot(served, project, waiting, "")
        conflict = _snapshot(served, project, waiting, "")

    # Assert
    assert plan.status_code == 200, plan.text
    assert plan.json()["blocked"]["code"] == "file_missing"
    assert plan.json()["blocked"]["message"]
    assert_problem(blocked, 409, "snapshot_blocked")
    assert blocked.json()["reason"] == "file_missing"
    assert queued.status_code == 202, queued.text
    assert queued.json()["state"] == "queued"
    assert_problem(conflict, 409, "conflict")
    assert conflict.json()["job"] == {
        "id": queued.json()["id"],
        "kind": "snapshot",
        "state": "queued",
    }
