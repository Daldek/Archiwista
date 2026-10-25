"""The IMGWTools source beside Kartograf, and its directory in the settings (plan I2).

``GET /sources`` lists it with its versions, schemas and default store root when
the extra ``archiwista[imgw]`` is installed. Without the package it is
``not_installed`` with the extra as its fix, a state of this source only
(A-ADR-024, SPEC 5.8).
A store takes an IMGW directory in ``PUT /settings``, with or without a
Kartograf one; a directory inside a store, found by the marker file name, is
refused at its own field (DEV-19.14).
"""

import importlib.metadata
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, ConfigStore, StoreConfig
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import assert_problem, running_api
from tests.fixtures.isolation import Canary
from tests.fixtures.local_server import local_paths
from tests.fixtures.missing_package import hide_packages


def _sources(tmp_path: Path) -> dict[str, dict[str, object]]:
    """Return the sources that ``GET /sources`` lists, by producer."""
    paths = local_paths(tmp_path)
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        response = api.session(LOCAL_OWNER).request("GET", "/sources")
    assert response.status_code == 200, response.text
    return {item["producer"]: item for item in response.json()["items"]}


def test_sources_lists_imgw_with_its_versions_and_schemas(
    tmp_path: Path, producer_canary: Canary
) -> None:
    """With IMGWTools installed the source is available and names what it reads.

    Its default store root is the canary's ``IMGW_ROOT`` (``tests/conftest.py``).
    """
    pytest.importorskip("imgwtools")
    from archiwista.adapter.imgw import SCHEMAS, SUPPORTED_VERSIONS

    sources = _sources(tmp_path)

    root = producer_canary.imgw_root
    assert sources["imgw"] == {
        "producer": "imgw",
        "status": "available",
        "package_version": importlib.metadata.version("imgwtools"),
        "supported_versions": SUPPORTED_VERSIONS,
        "schemas": list(SCHEMAS),
        "detail": None,
        "message": sources["imgw"]["message"],
        "fix": None,
        "default_root": {
            "path": str(root),
            "source": "env",
            "name": "IMGW_ROOT",
            "exists": False,
            "marked": False,
            "message": (
                f"Plugin imgw: default store root {root}"
                " (variable IMGW_ROOT; does not exist)"
            ),
        },
    }
    assert sources["imgw"]["message"] and sources["kartograf"]["status"] == "available"


def test_sources_imgw_without_its_package_is_not_installed_and_kartograf_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The extra is the fix; no other source changes."""
    hide_packages(monkeypatch, "imgwtools")

    sources = _sources(tmp_path)

    imgw = sources["imgw"]
    assert (imgw["status"], imgw["package_version"]) == ("not_installed", None)
    assert (
        isinstance(imgw["fix"], str) and 'pip install "archiwista[imgw]"' in imgw["fix"]
    )
    assert isinstance(imgw["detail"], str) and "imgwtools" in imgw["detail"]
    kartograf = sources["kartograf"]
    assert (kartograf["status"], kartograf["fix"]) == ("available", None)


def _settings_body(**store: str) -> dict[str, object]:
    """Return a ``PUT /settings`` body with one store (the rest takes defaults)."""
    return {"stores": [{"id": "a", "name": "A", **store}]}


def test_settings_accept_a_store_with_only_an_imgw_directory(
    tmp_path: Path, imgw_store: Callable[[str], Path]
) -> None:
    """Neither directory is needed beside the other: the store has only IMGW's."""
    # Arrange
    pytest.importorskip("imgwtools")
    root = imgw_store("complete")
    paths = local_paths(tmp_path)

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        saved = owner.request("PUT", "/settings", json=_settings_body(imgw=str(root)))
        read = owner.request("GET", "/settings")
        listed = owner.request("GET", "/stores")

    # Assert
    assert saved.status_code == 200, saved.text
    store = read.json()["stores"][0]
    assert (store["kartograf"], store["imgw"]) == (None, str(root))
    assert ConfigStore(paths.config_file).load().stores[0].roots() == {"imgw": root}
    assert listed.json()["items"][0]["producers"] == ["imgw"]


def test_settings_refuse_a_directory_inside_a_store_at_its_own_field(
    tmp_path: Path, imgw_store: Callable[[str], Path]
) -> None:
    """A Kartograf directory in an IMGW store, and an IMGW one in a Kartograf store."""
    # Arrange
    pytest.importorskip("imgwtools")
    store = shutil.copytree(imgw_store("complete"), tmp_path / "imgw")
    in_imgw = store / "kartograf"
    in_imgw.mkdir()
    kartograf = tmp_path / "kartograf"
    kartograf.mkdir()
    (kartograf / "kartograf-store.json").write_text("{}", encoding="utf-8")
    in_kartograf = kartograf / "imgw"
    in_kartograf.mkdir()
    paths = local_paths(tmp_path / "app")

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        first = owner.request(
            "PUT", "/settings", json=_settings_body(kartograf=str(in_imgw))
        )
        second = owner.request(
            "PUT", "/settings", json=_settings_body(imgw=str(in_kartograf))
        )

    # Assert
    for refused in (first, second):
        assert_problem(refused, 400, "validation_error", "invalid_settings")
    found = [
        [
            (item["code"], item["field"])
            for item in refused.json()["details"]["problems"]
        ]
        for refused in (first, second)
    ]
    assert ("root_nested", "stores[0].kartograf") in found[0]
    assert found[1] == [("root_nested", "stores[0].imgw")]
    assert not ConfigStore(paths.config_file).exists()


def test_settings_keep_an_imgw_entry_without_its_source_but_refuse_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry saved earlier is not probed again; a new directory needs the source."""
    # Arrange
    hide_packages(monkeypatch, "imgwtools")
    imgw = tmp_path / "imgw"
    imgw.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    paths = local_paths(tmp_path / "app")
    entry = StoreConfig(id="a", name="A", imgw=imgw, kind="local")
    ConfigStore(paths.config_file).save(AppSettings(stores=(entry,)))

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        current = owner.request("GET", "/settings").json()
        unchanged = owner.request("PUT", "/settings", json={**current, "offline": True})
        moved = owner.request(
            "PUT",
            "/settings",
            json={**current, "stores": [{**current["stores"][0], "imgw": str(other)}]},
        )

    # Assert
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["stores"][0]["imgw"] == str(imgw)
    assert_problem(moved, 400, "validation_error", "invalid_settings")
    problems = moved.json()["details"]["problems"]
    assert [(item["code"], item["field"]) for item in problems] == [
        ("source_not_installed", "stores[0].imgw")
    ]
    assert ConfigStore(paths.config_file).load().stores[0].imgw == imgw
