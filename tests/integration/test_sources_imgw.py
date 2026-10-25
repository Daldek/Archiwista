"""The IMGWTools source is registered beside Kartograf (plan 2026-10-25, step I2).

``GET /sources`` lists it with its versions and schemas when the extra
``archiwista[imgw]`` is installed. Without the package it is ``not_installed``
with the extra as its fix, a state of this source only (A-ADR-024, SPEC 5.8).
"""

import importlib.metadata
from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import running_api
from tests.fixtures.local_server import local_paths


def _sources(tmp_path: Path) -> dict[str, dict[str, object]]:
    """Return the sources that ``GET /sources`` lists, by producer."""
    paths = local_paths(tmp_path)
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        response = api.session(LOCAL_OWNER).request("GET", "/sources")
    assert response.status_code == 200, response.text
    return {item["producer"]: item for item in response.json()["items"]}


def test_sources_lists_imgw_with_its_versions_and_schemas(tmp_path: Path) -> None:
    """With IMGWTools installed the source is available and names what it reads."""
    pytest.importorskip("imgwtools")
    from archiwista.adapter.imgw import SCHEMAS, SUPPORTED_VERSIONS

    sources = _sources(tmp_path)

    assert sources["imgw"] == {
        "producer": "imgw",
        "status": "available",
        "package_version": importlib.metadata.version("imgwtools"),
        "supported_versions": SUPPORTED_VERSIONS,
        "schemas": list(SCHEMAS),
        "detail": None,
        "message": sources["imgw"]["message"],
        "fix": None,
    }
    assert sources["imgw"]["message"] and sources["kartograf"]["status"] == "available"


def test_sources_imgw_without_its_package_is_not_installed_and_kartograf_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The extra is the fix; no other source changes."""
    installed = importlib.metadata.version

    def version(name: str) -> str:
        if name == "imgwtools":
            raise importlib.metadata.PackageNotFoundError(name)
        return installed(name)

    monkeypatch.setattr(importlib.metadata, "version", version)

    sources = _sources(tmp_path)

    imgw = sources["imgw"]
    assert (imgw["status"], imgw["package_version"]) == ("not_installed", None)
    assert (
        isinstance(imgw["fix"], str) and 'pip install "archiwista[imgw]"' in imgw["fix"]
    )
    assert isinstance(imgw["detail"], str) and "imgwtools" in imgw["detail"]
    kartograf = sources["kartograf"]
    assert (kartograf["status"], kartograf["fix"]) == ("available", None)
