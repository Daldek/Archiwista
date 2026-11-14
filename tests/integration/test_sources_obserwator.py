"""The Obserwator source beside Kartograf, and its roots in the settings (plan I2).

``GET /sources`` lists it with its versions, schemas and default raw and data
roots when the extra ``archiwista[obserwator]`` is installed. Without the
package it is ``not_installed`` with the extra as its fix, a state of this
source only (A-ADR-024, SPEC 5.8).
A store takes Obserwator's raw and data roots in ``PUT /settings``, with or
without a Kartograf directory, and refuses a root of the other kind in each
field (``wrong_root``, A-ADR-056); a directory inside a store, found by the
marker file name, is refused at its own field (DEV-19.14).
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
from tests.fixtures.obserwator_roots import data_root, raw_root


def _sources(tmp_path: Path) -> dict[str, dict[str, object]]:
    """Return the sources that ``GET /sources`` lists, by producer."""
    paths = local_paths(tmp_path)
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        response = api.session(LOCAL_OWNER).request("GET", "/sources")
    assert response.status_code == 200, response.text
    return {item["producer"]: item for item in response.json()["items"]}


def test_sources_lists_obserwator_with_its_versions_and_schemas(
    tmp_path: Path, producer_canary: Canary
) -> None:
    """With Obserwator installed the source is available and names what it reads.

    Its default raw and data roots are the canary's ``OBSERWATOR_RAW_ROOT`` and
    ``OBSERWATOR_ROOT`` (``tests/conftest.py``).
    """
    pytest.importorskip("obserwator")
    from archiwista.adapter.obserwator import SCHEMAS, SUPPORTED_VERSIONS

    sources = _sources(tmp_path)

    raw, data = producer_canary.obserwator_raw_root, producer_canary.obserwator_root
    assert sources["obserwator"] == {
        "producer": "obserwator",
        "status": "available",
        "package_version": importlib.metadata.version("obserwator"),
        "supported_versions": SUPPORTED_VERSIONS,
        "schemas": list(SCHEMAS),
        "detail": None,
        "message": sources["obserwator"]["message"],
        "fix": None,
        "default_root": {
            "path": str(raw),
            "source": "env",
            "name": "OBSERWATOR_RAW_ROOT",
            "exists": False,
            "marked": False,
            "message": (
                f"Plugin obserwator: default store root {raw}"
                " (variable OBSERWATOR_RAW_ROOT; does not exist)"
            ),
        },
        "default_data_root": {
            "path": str(data),
            "source": "env",
            "name": "OBSERWATOR_ROOT",
            "exists": False,
            "marked": False,
            "message": (
                f"Plugin obserwator: default data root {data}"
                " (variable OBSERWATOR_ROOT; does not exist)"
            ),
        },
        "availability": [],
    }
    assert (
        sources["obserwator"]["message"]
        and sources["kartograf"]["status"] == "available"
    )


def test_sources_obserwator_without_its_package_is_not_installed_and_kartograf_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The extra is the fix; no other source changes."""
    hide_packages(monkeypatch, "obserwator")

    sources = _sources(tmp_path)

    obserwator = sources["obserwator"]
    assert (obserwator["status"], obserwator["package_version"]) == (
        "not_installed",
        None,
    )
    assert (
        isinstance(obserwator["fix"], str)
        and 'pip install "archiwista[obserwator]"' in obserwator["fix"]
    )
    assert (
        isinstance(obserwator["detail"], str) and "obserwator" in obserwator["detail"]
    )
    kartograf = sources["kartograf"]
    assert (kartograf["status"], kartograf["fix"]) == ("available", None)


def _settings_body(**store: str) -> dict[str, object]:
    """Return a ``PUT /settings`` body with one store (the rest takes defaults)."""
    return {"stores": [{"id": "a", "name": "A", **store}]}


def test_settings_accept_a_store_with_only_obserwators_roots(
    tmp_path: Path, obserwator_store: Callable[[str], Path]
) -> None:
    """No Kartograf directory is needed: the store has only Obserwator's two roots."""
    # Arrange
    pytest.importorskip("obserwator")
    store = obserwator_store("complete")
    raw, data = raw_root(store), data_root(store)
    paths = local_paths(tmp_path)

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        saved = owner.request(
            "PUT",
            "/settings",
            json=_settings_body(obserwator=str(raw), obserwator_data=str(data)),
        )
        read = owner.request("GET", "/settings")
        listed = owner.request("GET", "/stores")

    # Assert
    assert saved.status_code == 200, saved.text
    found = read.json()["stores"][0]
    assert (found["kartograf"], found["obserwator"], found["obserwator_data"]) == (
        None,
        str(raw),
        str(data),
    )
    config = ConfigStore(paths.config_file).load().stores[0]
    assert config.roots() == {"obserwator": raw}
    assert config.directory_paths() == {"obserwator": raw, "obserwator_data": data}
    assert listed.json()["items"][0]["producers"] == ["obserwator"]


def test_settings_refuse_a_root_of_the_other_kind_in_each_field(
    tmp_path: Path, obserwator_store: Callable[[str], Path]
) -> None:
    """The data root as the raw root and the reverse: ``wrong_root`` at each field."""
    # Arrange
    pytest.importorskip("obserwator")
    store = obserwator_store("complete")
    swapped = {
        "obserwator": str(data_root(store)),
        "obserwator_data": str(raw_root(store)),
    }
    paths = local_paths(tmp_path)

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        refused = api.session(LOCAL_OWNER).request(
            "PUT", "/settings", json=_settings_body(**swapped)
        )

    # Assert
    assert_problem(refused, 400, "validation_error", "invalid_settings")
    problems = refused.json()["details"]["problems"]
    assert [(item["code"], item["field"], item["reason"]) for item in problems] == [
        ("source_incompatible", "stores[0].obserwator", "wrong_root"),
        ("source_incompatible", "stores[0].obserwator_data", "wrong_root"),
    ]
    assert not ConfigStore(paths.config_file).exists()


def test_settings_refuse_a_directory_inside_a_store_at_its_own_field(
    tmp_path: Path, obserwator_store: Callable[[str], Path]
) -> None:
    """A Kartograf directory in an Obserwator store, and the reverse."""
    # Arrange
    pytest.importorskip("obserwator")
    store = shutil.copytree(obserwator_store("complete"), tmp_path / "obserwator")
    in_obserwator = raw_root(store) / "kartograf"
    in_obserwator.mkdir()
    kartograf = tmp_path / "kartograf"
    kartograf.mkdir()
    (kartograf / "kartograf-store.json").write_text("{}", encoding="utf-8")
    in_kartograf = kartograf / "obserwator"
    in_kartograf.mkdir()
    paths = local_paths(tmp_path / "app")

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        first = owner.request(
            "PUT", "/settings", json=_settings_body(kartograf=str(in_obserwator))
        )
        second = owner.request(
            "PUT", "/settings", json=_settings_body(obserwator=str(in_kartograf))
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
    assert found[1] == [("root_nested", "stores[0].obserwator")]
    assert not ConfigStore(paths.config_file).exists()


def test_settings_keep_an_obserwator_entry_without_its_source_but_refuse_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry saved earlier is not probed again; a new directory needs the source."""
    # Arrange
    hide_packages(monkeypatch, "obserwator")
    obserwator = tmp_path / "obserwator"
    obserwator.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    paths = local_paths(tmp_path / "app")
    entry = StoreConfig(id="a", name="A", obserwator=obserwator, kind="local")
    ConfigStore(paths.config_file).save(AppSettings(stores=(entry,)))

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        current = owner.request("GET", "/settings").json()
        unchanged = owner.request("PUT", "/settings", json={**current, "offline": True})
        moved = owner.request(
            "PUT",
            "/settings",
            json={
                **current,
                "stores": [{**current["stores"][0], "obserwator": str(other)}],
            },
        )

    # Assert
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["stores"][0]["obserwator"] == str(obserwator)
    assert_problem(moved, 400, "validation_error", "invalid_settings")
    problems = moved.json()["details"]["problems"]
    assert [(item["code"], item["field"]) for item in problems] == [
        ("source_not_installed", "stores[0].obserwator")
    ]
    assert ConfigStore(paths.config_file).load().stores[0].obserwator == obserwator
