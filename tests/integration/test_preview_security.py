"""Previews never read data in the server and never change the store (steps 6, 9).

Plan v0.2, decision 3: every data file is opened by a render process (the
sandbox of step 1) or a build process of the ``preview`` job; the server
only resolves paths inside their root and answers from the preview cache.
The tests serve a generated store with real render processes and the real
job worker (``tests.fixtures.preview_api``) and use one version of every
file family: its description, thumbnail, central map tile, features and
members, and the build of an ASC sheet with its tile. A project's data
folder (``tests.fixtures.own_data_api``) joins them with every own-data
family and GeoPackages in the three states of decision 8; two projects
holding the same damaged bytes share its failure, never a path.
"""

import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import laspy
import pyogrio
import pyogrio.raw
import pytest
import rasterio
import shapely
from starlette.applications import Starlette

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.config import ConfigStore
from archiwista.index import IndexQueries, own_file_id
from archiwista.previews.cache import cache_key
from archiwista.refs import ObjectResolver, VersionRef
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE
from tests.fixtures.own_data import ALL_OWN_FAMILIES, GpkgEditor, write_snapshot_fixture
from tests.fixtures.own_data_api import FIRST, OwnDataApi, OwnProject, own_data_api
from tests.fixtures.permissions import principal, share
from tests.fixtures.preview_api import (
    PreviewApi,
    center_tile_url,
    entry_of,
    preview_api,
    version_url,
)

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

# What reads a data file, each as the server process would call it.
READERS = (
    (rasterio, "open"),
    (pyogrio, "read_info"),
    (pyogrio, "read_dataframe"),
    (pyogrio, "read_arrow"),
    (pyogrio, "open_arrow"),
    (pyogrio, "list_layers"),
    (pyogrio.raw, "read"),
    (laspy, "open"),
    (laspy, "read"),
    (zipfile, "ZipFile"),
)

# The data folder of step 9: GeoPackages in the states of decision 8 and what
# they leave beside them; a basin each makes most of them contents of their own.
BASIN = shapely.box(566_200, 241_200, 566_300, 241_300)
COMPANIONS = (
    "dziennik.gpkg-journal",
    "po_awarii.gpkg-wal",
    "w_edycji.gpkg-shm",
    "w_edycji.gpkg-wal",
)
# A writer of a rollback-mode GeoPackage commits a change, then dies inside its
# next transaction: a cache of one page spills changed pages into the file and
# the journal keeps the old ones (a hot journal, state (c) of decision 8).
CRASHING_WRITER = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("UPDATE gpkg_contents SET description = 'awaria'")
db.execute("PRAGMA cache_size=1")
db.execute("BEGIN IMMEDIATE")
db.execute("CREATE TABLE balast (dane BLOB)")
db.execute(
    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 400)"
    " INSERT INTO balast SELECT zeroblob(1000) FROM n"
)
os._exit(0)
"""
# The same damaged bytes in two projects: a TIFF cut after its signature, and
# a file of zeros (what a copy cut short on a share leaves).
TRUNCATED = "uszkodzony.tif"
ZEROED = "wyzerowany.tif"


def _previews(served: PreviewApi) -> list[httpx.Response]:
    """Ask for every preview of one version of each family; build an ASC sheet."""
    families = sorted(
        {entry.family for entry in served.store.by_kind("version") if entry.family}
    )
    answers: list[httpx.Response] = []
    for family in families:
        described = served.get(version_url(entry_of(served.store, family).path))
        answers.append(described)
        info = described.json()
        if info["thumbnail_url"]:
            answers.append(served.get(info["thumbnail_url"]))
        if info["state"] == "ready" and info["tiles_url"]:
            answers.append(served.get(center_tile_url(info)))
        if info["features_url"]:
            bbox = ",".join(str(value) for value in info["bounds"])
            answers.append(served.get(info["features_url"].format(bbox=bbox, zoom=14)))
        if info["members_url"]:
            answers.append(served.get(info["members_url"]))
    sheet = entry_of(served.store, "asc_sheet", "regular").path
    posted = served.post(version_url(sheet), {"force": False})
    answers.append(posted)
    record = served.wait(posted.json()["id"])
    assert record.state == "succeeded", record
    answers.append(served.get(center_tile_url(served.get(version_url(sheet)).json())))
    return answers


def _own_previews(served: OwnDataApi) -> list[httpx.Response]:
    """Ask for every preview of each file of the first project's data folder.

    A file needing a build (a GeoPackage under edit: its consistent copy) is
    built first, then described again.
    """
    project = served.first
    owner = served.owner
    listed = owner.request("GET", f"/projects/{project.key}/files?limit=200")
    answers: list[httpx.Response] = [listed]
    for item in listed.json()["items"]:
        address = project.url(item["path"], "preview")
        described = owner.request("GET", address)
        answers.append(described)
        info = described.json()
        if info["state"] == "needs_build":
            posted = owner.request("POST", address, json={"force": False})
            answers.append(posted)
            record = served.wait(posted.json()["id"])
            assert record.state == "succeeded", record
            described = owner.request("GET", address)
            answers.append(described)
            info = described.json()
        if info["thumbnail_url"]:
            answers.append(served.get(owner, info["thumbnail_url"]))
        if info["state"] == "ready" and info["tiles_url"]:
            answers.append(served.get(owner, center_tile_url(info)))
        if info["features_url"]:
            # A map view around the file: a single point has no extent.
            west, south, east, north = info["bounds"]
            view = f"{west - 0.01},{south - 0.01},{east + 0.01},{north + 0.01}"
            features = info["features_url"].format(bbox=view, zoom=14)
            answers.append(served.get(owner, features))
        if info["members_url"]:
            answers.append(served.get(owner, info["members_url"]))
    return answers


def _listing(root: Path) -> dict[str, tuple[int | None, int | None, int]]:
    """Return every entry below ``root``: its size, modification time and mode.

    Of a ``-shm`` only the name and mode count: it is the shared memory of
    the editor holding its database open, and SQLite's readers write into it
    (decision 8).
    """
    found: dict[str, tuple[int | None, int | None, int]] = {}
    for directory, names, files in os.walk(root):
        for name in (*names, *files):
            path = Path(directory) / name
            status = path.lstat()
            shared = name.endswith("-shm")
            found[path.relative_to(root).as_posix()] = (
                None if shared else status.st_size,
                None if shared else status.st_mtime_ns,
                status.st_mode,
            )
    return found


@contextmanager
def _geopackages_in_three_states(folder: Path) -> Iterator[None]:
    """Write copies of ``kanalizacja.gpkg`` in the states of decision 8.

    (a) ``zamkniety.gpkg``: a WAL database its editor closed, no ``-wal``;
    (b) ``w_edycji.gpkg``: open in an editor with committed frames in
    ``-wal`` and an open transaction, until the block ends; (c)
    ``po_awarii.gpkg``: ``-wal`` without ``-shm`` after its editor crashed,
    and ``dziennik.gpkg``: a hot rollback journal after its writer crashed.
    Each holds other committed rows, so each is a content of its own.
    """
    source = folder / "kanalizacja.gpkg"
    for name in ("zamkniety", "w_edycji", "po_awarii", "dziennik"):
        shutil.copy2(source, folder / f"{name}.gpkg")
    with GpkgEditor(folder / "zamkniety.gpkg") as closed:
        closed.begin()
        closed.insert("zlewnie", BASIN, nazwa="Zlewnia zamknięta")
        closed.commit()
    with GpkgEditor(folder / "po_awarii.gpkg") as crashed:
        crashed.begin()
        crashed.insert("zlewnie", BASIN, nazwa="Zlewnia po awarii")
        crashed.commit()
        crashed.crash_without_shm()
    subprocess.run(
        [sys.executable, "-c", CRASHING_WRITER, str(folder / "dziennik.gpkg")],
        check=True,
    )
    with GpkgEditor(folder / "w_edycji.gpkg") as editing:
        editing.begin()
        editing.insert("zlewnie", BASIN, nazwa="Zlewnia zatwierdzona")
        editing.commit()
        editing.begin()
        editing.insert("zlewnie", BASIN, nazwa="Zlewnia w edycji")
        yield


def _content(served: OwnDataApi, project: OwnProject, path: str) -> str:
    """Return the content key the last scan gave a working file."""
    with IndexQueries(served.paths.index_file) as queries:
        found = queries.own_file(project.key, own_file_id(path), visible=ALL_PROJECTS)
    assert found is not None and found.content_sha256 is not None
    return found.content_sha256


def test_server_process_never_opens_data_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With every file reader failing in the server, all preview routes work."""
    with preview_api(tmp_path) as served:
        # Arrange
        opened: list[str] = []
        for module, name in READERS:

            def refuse(*args: object, _name: str = name, **kwargs: object) -> None:
                opened.append(_name)
                raise AssertionError(f"{_name} called in the server process")

            monkeypatch.setattr(module, name, refuse)

        # Act
        answers = _previews(served)

    # Assert
    assert opened == []
    assert [
        (answer.request.url.path, answer.status_code)
        for answer in answers
        if answer.status_code not in (200, 202)
    ] == []


def test_link_leaving_root_is_path_outside_root(tmp_path: Path) -> None:
    """A version file linked to a place outside its store is refused (``403``)."""
    with preview_api(tmp_path) as served:
        # Arrange
        path = entry_of(served.store, "tif_bbox").path
        version = served.store.root / path
        outside = tmp_path / "poza-magazynem" / version.name
        outside.parent.mkdir()
        shutil.move(version, outside)
        version.symlink_to(outside)

        # Act
        described = served.get(version_url(path))
        thumbnail = served.get(version_url(path, "preview.png"))

    # Assert
    assert_problem(described, 403, "forbidden", "path_outside_root")
    assert_problem(thumbnail, 403, "forbidden", "path_outside_root")


def test_store_and_own_folder_unchanged_after_previews(tmp_path: Path) -> None:
    """Names, sizes, times and modes in the store and a data folder stay.

    The writable store and the data folder of its project, with every
    own-data family and GeoPackages in the three states of decision 8 (one of
    them open in an editor), are listed before and after every preview of
    both, the builds of an ASC sheet and of the consistent copies of the
    GeoPackages under edit included: no ``.aux.xml``, ``-wal`` or ``-shm`` is
    created, no ``-wal`` or journal goes, no file changes.
    """
    with own_data_api(tmp_path, first=ALL_OWN_FAMILIES, second=()) as served:
        # Arrange
        output = served.previews.store.base
        folder = served.first.root
        with _geopackages_in_three_states(folder):
            served.scan()  # the edits came after the first scan
            before = _listing(output)

            # Act
            answers = _previews(served.previews) + _own_previews(served)
            after = _listing(output)

    # Assert
    own = folder.relative_to(output).as_posix()
    assert os.access(served.previews.store.root, os.W_OK)
    assert os.access(folder, os.W_OK)
    assert [
        (answer.request.url.path, answer.status_code)
        for answer in answers
        if answer.status_code not in (200, 202)
    ] == []
    assert sorted(
        name for name in after if name.startswith(f"{own}/") and ".gpkg-" in name
    ) == [f"{own}/{name}" for name in COMPANIONS]
    assert after == before
    assert list(output.rglob("*.aux.xml")) == []


def test_failure_message_carries_no_other_projects_path(tmp_path: Path) -> None:
    """The same damaged bytes in two projects: the second's failures show no path.

    The failure of the first project's file is kept by its content without
    the library's message, which only the answer that found it gets; a build
    failing on the first project's file gives a ref of the second project of
    the same content the library's message with file names only (decision
    3). Igor sees the second project only.
    """
    with own_data_api(tmp_path, first=(), second=()) as served:
        # Arrange
        first, second = served.first, served.second
        for project in (first, second):
            (project.root / TRUNCATED).write_bytes(b"II*\x00")
            (project.root / ZEROED).write_bytes(bytes(4096))
        served.scan()
        share(served.api.state, first.access_key, "private")
        igor = served.caller("other")
        truncated = _content(served, second, TRUNCATED)
        zeroed = _content(served, second, ZEROED)
        # The same bytes: one content in both projects.
        assert _content(served, first, TRUNCATED) == truncated
        assert _content(served, first, ZEROED) == zeroed

        # Act
        found = served.owner.request("GET", first.url(TRUNCATED, "preview"))
        cached = igor.request("GET", second.url(TRUNCATED, "preview"))
        submitted = served.jobs.submit(
            "preview",
            params={
                "refs": [first.ref(ZEROED), second.ref(ZEROED), second.ref(TRUNCATED)],
                "contents": [zeroed, zeroed, truncated],
                "force": False,
            },
            actor=LOCAL_OWNER,
        )
        record = served.wait(submitted.id)
        built = igor.request("GET", f"/jobs/{submitted.id}")

    # Assert
    assert found.status_code == 200, found.text
    reason = found.json()["reason"]
    assert reason["code"] == "unreadable"
    assert TRUNCATED in reason["detail"] and str(tmp_path) not in reason["detail"]
    assert cached.status_code == 200, cached.text
    assert cached.json()["reason"] == {**reason, "detail": None}
    assert record.result is not None
    every = {entry["ref"]: entry["detail"] for entry in record.result["failed"]}
    assert every[first.ref(ZEROED)] == every[second.ref(ZEROED)]  # one build of both
    assert built.status_code == 200, built.text
    job = built.json()
    assert job["params"]["refs"] == [second.ref(ZEROED), second.ref(TRUNCATED)]
    shown = {entry["ref"]: entry["detail"] for entry in job["result"]["failed"]}
    assert set(shown) == {second.ref(ZEROED), second.ref(TRUNCATED)}
    assert ZEROED in shown[second.ref(ZEROED)]  # the library's message, as built
    leaks = (str(tmp_path), first.key, first.directory.name)
    for answer in (cached, built):
        assert [part for part in leaks if part in answer.text] == [], answer.text


def test_hidden_preview_job_only_reports_generic_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Public tiles cannot disclose the private job ID or its queue state."""
    with own_data_api(tmp_path, first=(), second=()) as served:
        share(served.api.state, served.first.access_key, "private")
        visitor = served.caller("other")
        path = entry_of(served.previews.store, "asc_sheet", "regular").path
        url = version_url(path)
        before = served.get(visitor, url).json()
        assert before["state"] == "needs_build"
        with IndexQueries(served.paths.index_file) as queries:
            settings = ConfigStore(served.paths.config_file).load()
            source = ObjectResolver(queries, lambda: settings).locate(
                VersionRef(STORE, path), principal=LOCAL_OWNER
            )
        # Keep a real job queued so the request observes its stable state.
        monkeypatch.setattr(served.jobs, "_dispatch", lambda: None)
        hidden = served.jobs.submit(
            "preview",
            params={
                "refs": [served.first.ref("private.asc")],
                "contents": [cache_key(source).content_key],
                "force": False,
            },
            actor=LOCAL_OWNER,
        )
        app = cast(Starlette, served.api.client.app)
        visibility = app.state.authorizer.visible_projects(
            principal(served.api.state, "other")
        )
        assert served.jobs.get(hidden.id, visible=visibility) is None
        owner_info = served.get(served.owner, url)
        owner_tile = served.get(served.owner, center_tile_url(before))
        described = served.get(visitor, url)
        refused = served.get(visitor, center_tile_url(before))

    assert described.status_code == 200
    assert owner_info.json()["state"] == "building"
    assert owner_info.json()["job"]["id"] == hidden.id
    assert owner_tile.json()["details"]["job"]["id"] == hidden.id
    assert described.json()["state"] == "building"
    assert described.json()["job"] is None
    assert_problem(refused, 409, "conflict", "preview_not_ready")
    assert refused.json()["details"]["building"] is True
    assert "job" not in refused.json()["details"]
    assert hidden.id not in described.text + refused.text


def _lead_out(served: OwnDataApi, outside: Path) -> None:
    """Put a symbolic link out of the project in place of its data folder.

    The folder's files move to ``outside`` unchanged, so the index still
    describes what the link leads to; only the rules of a scan tell.
    """
    folder = served.first.root
    folder.rename(outside)
    folder.symlink_to(outside, target_is_directory=True)


def test_a_data_folder_led_out_of_its_project_is_not_previewed(tmp_path: Path) -> None:
    """The previews of a data folder replaced by a link out of the project are refused.

    The working file and its snapshot were described and their thumbnails
    rendered after the scan; once the folder leads out of the project, both
    are ``409 own_folder_invalid`` though the cache holds the thumbnails, and
    the file's card and its layers show no preview of them.
    """
    with own_data_api(tmp_path, first=("tif_2180",), second=(), workers=1) as served:
        # Arrange
        project, owner = served.first, served.owner
        raster = project.folder.file("tif_2180").path
        snapshot = write_snapshot_fixture(
            project.root, raster, created_at=datetime(2026, 10, 20, 12, tzinfo=UTC)
        )
        served.scan()
        described = [
            project.url(raster, "preview"),
            project.snapshot_url(raster, snapshot.label),
        ]
        thumbnails = [
            owner.request("GET", address).json()["thumbnail_url"]
            for address in described
        ]
        before = [served.get(owner, address) for address in thumbnails]
        _lead_out(served, tmp_path / "poza-projektu")

        # Act
        refused = [owner.request("GET", address) for address in described]
        refused += [served.get(owner, address) for address in thumbnails]
        card = owner.request("GET", project.url(raster))
        layers = owner.request("GET", project.url(raster, "layers"))

    # Assert
    assert [answer.status_code for answer in before] == [200, 200]
    for answer in refused:
        assert_problem(answer, 409, "conflict", "own_folder_invalid")
    assert card.status_code == 200
    assert card.json()["preview"] is None
    assert layers.status_code == 200
    assert [item["preview"]["state"] for item in layers.json()["layers"]] == [
        "unavailable",
        "unavailable",
    ]


def test_jobs_read_no_file_of_a_data_folder_led_out_of_its_project(
    tmp_path: Path,
) -> None:
    """A ``preview`` build and a project's warm-up fail such a file alone.

    The build was asked for before the folder was led out of the project (a
    job waiting in the queue); both jobs check the folder when they reach
    the file and read nothing of it, while the warm-up prepares the store
    versions the project pins.
    """
    with own_data_api(tmp_path, first=("tif_2180",), second=(), workers=1) as served:
        # Arrange
        project = served.first
        raster = project.folder.file("tif_2180").path
        with IndexQueries(served.paths.index_file) as queries:
            detail = queries.own_file(
                project.key, own_file_id(raster), visible=ALL_PROJECTS
            )
        assert detail is not None and detail.content_sha256 is not None
        _lead_out(served, tmp_path / "poza-projektu")

        # Act
        build = served.jobs.submit(
            "preview",
            params={
                "refs": [project.ref(raster)],
                "contents": [detail.content_sha256.lower()],
                "force": True,
            },
            actor=LOCAL_OWNER,
        )
        built = served.wait(build.id)
        warm = served.owner.request("POST", "/previews/warm", json={"project": FIRST})
        warmed = served.wait(warm.json()["id"])

    # Assert
    ref = project.ref(raster)
    assert built.result is not None and warmed.result is not None
    assert [(item["ref"], item["code"]) for item in built.result["failed"]] == [
        (ref, "own_folder_invalid")
    ]
    assert built.result["built"] == 0
    assert [(item["ref"], item["code"]) for item in warmed.result["failures"]] == [
        (ref, "own_folder_invalid")
    ]
    assert warmed.result["failed"] == 1
