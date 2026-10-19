"""Previews never read data in the server and never change the store (step 6).

Plan v0.2, decision 3: every data file is opened by a render process (the
sandbox of step 1) or a build process of the ``preview`` job; the server
only resolves paths inside their root and answers from the preview cache.
The tests serve a generated store with real render processes and the real
job worker (``tests.fixtures.preview_api``) and use one version of every
file family: its description, thumbnail, central map tile, features and
members, and the build of an ASC sheet with its tile. The own-data folder
joins these tests with its routes (step 9).
"""

import os
import shutil
import zipfile
from pathlib import Path

import httpx
import laspy
import pyogrio
import pyogrio.raw
import pytest
import rasterio

from tests.fixtures.api_session import assert_problem
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


def _listing(root: Path) -> dict[str, tuple[int, int, int]]:
    """Return every entry below ``root``: its size, modification time and mode."""
    found: dict[str, tuple[int, int, int]] = {}
    for directory, names, files in os.walk(root):
        for name in (*names, *files):
            path = Path(directory) / name
            status = path.lstat()
            found[path.relative_to(root).as_posix()] = (
                status.st_size,
                status.st_mtime_ns,
                status.st_mode,
            )
    return found


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
    assert_problem(described, 403, "path_outside_root")
    assert_problem(thumbnail, 403, "path_outside_root")


def test_store_and_own_folder_unchanged_after_previews(tmp_path: Path) -> None:
    """Names, sizes, times and modes in the writable store stay; no ``.aux.xml``."""
    with preview_api(tmp_path) as served:
        # Arrange
        output = served.store.output_dir
        before = _listing(output)

        # Act
        answers = _previews(served)
        after = _listing(output)

    # Assert
    assert os.access(served.store.root, os.W_OK)
    assert all(answer.status_code in (200, 202) for answer in answers)
    assert after == before
    assert list(output.rglob("*.aux.xml")) == []
