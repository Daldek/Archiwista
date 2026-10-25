"""The default store root of Kartograf in ``GET /sources`` and the command line (M5).

The producer reports the directory it uses when a call names no store (D7); the
first-run wizard offers it and Archiwista never uses it. ``/health`` is polled and
the producer sizes the directory while it reports it, so ``/health`` leaves it out.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from archiwista.cli import main
from tests.fixtures.api_store import ServedStore, served_store

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServedStore]:
    """Serve one scanned store; the tests point the default root at places."""
    with served_store(tmp_path_factory.mktemp("root")) as found:
        yield found


def _sources(served: ServedStore, *, accept_language: str | None = None) -> Any:
    response = served.owner.request("GET", "/sources", accept_language=accept_language)
    assert response.status_code == 200, response.text
    return response.json()


def _kartograf(listing: Any) -> dict[str, Any]:
    [item] = [item for item in listing["items"] if item["producer"] == "kartograf"]
    return dict(item)


def test_default_root_sources_offers_the_store_of_the_variable(
    served: ServedStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``KARTOGRAF_ROOT`` on a store with its marker: path, layer, state, text."""
    # Arrange
    root = served.store.root
    monkeypatch.setenv("KARTOGRAF_ROOT", str(root))

    # Act
    english = _kartograf(_sources(served))["default_root"]
    polish = _kartograf(_sources(served, accept_language="pl"))["default_root"]

    # Assert
    assert english == {
        "path": str(root),
        "source": "env",
        "name": "KARTOGRAF_ROOT",
        "exists": True,
        "marked": True,
        "message": (
            f"Plugin kartograf: default store root {root}"
            " (variable KARTOGRAF_ROOT; a store with its marker)"
        ),
    }
    assert polish["message"] == (
        f"Wtyczka kartograf: domyślny katalog główny magazynu {root}"
        " (zmienna KARTOGRAF_ROOT; magazyn ze znacznikiem)"
    )


@pytest.mark.parametrize(
    ("exists", "state"),
    [(True, "exists, without a store marker"), (False, "does not exist")],
)
def test_default_root_sources_tells_a_directory_without_marker_from_a_missing_one(
    served: ServedStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exists: bool,
    state: str,
) -> None:
    """Neither is a store to offer, and the two are told apart."""
    # Arrange
    root = tmp_path / "kartograf"
    if exists:
        root.mkdir()
    monkeypatch.setenv("KARTOGRAF_ROOT", str(root))

    # Act
    found = _kartograf(_sources(served))["default_root"]

    # Assert
    assert (found["path"], found["exists"], found["marked"]) == (
        str(root),
        exists,
        False,
    )
    assert found["message"].endswith(f"{state})")
    assert exists == root.exists()  # reading it created nothing


def test_default_root_without_settings_is_under_the_data_directory(
    served: ServedStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only ``NOGAT_DATA_DIR`` is set: ``<data_dir>/kartograf`` is the default."""
    # Arrange
    monkeypatch.delenv("KARTOGRAF_ROOT")
    monkeypatch.delenv("KARTOGRAF_DATA_DIR")
    monkeypatch.setenv("NOGAT_DATA_DIR", str(tmp_path / "nogat"))

    # Act
    found = _kartograf(_sources(served))["default_root"]

    # Assert
    assert (found["path"], found["source"], found["name"]) == (
        str(tmp_path / "nogat" / "kartograf"),
        "default",
        None,
    )
    assert not (tmp_path / "nogat").exists()


def test_default_root_health_leaves_it_out(served: ServedStore) -> None:
    """``/health`` is polled; the root is sized by the producer, so it is not there."""
    # Act
    response = served.owner.request("GET", "/health")

    # Assert
    assert response.status_code == 200, response.text
    sources = response.json()["sources"]
    assert [source["producer"] for source in sources] == ["kartograf"]
    assert all("default_root" not in source for source in sources)


def test_default_root_command_line_prints_what_the_route_answers(
    served: ServedStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sources --json`` is ``GET /sources``; the text gives the root its own line."""
    # Arrange
    root = served.store.root
    monkeypatch.setenv("KARTOGRAF_ROOT", str(root))
    registry, paths = served.registry, served.api.paths
    capsys.readouterr()

    # Act
    assert main(["sources", "--json"], registry=registry, paths=paths) == 0
    as_json = json.loads(capsys.readouterr().out)
    assert main(["sources"], registry=registry, paths=paths) == 0
    text = capsys.readouterr().out.splitlines()

    # Assert
    assert as_json == _sources(served)
    assert len(text) == 2
    assert text[0].startswith("Źródło kartograf (")
    assert text[1] == (
        f"  Wtyczka kartograf: domyślny katalog główny magazynu {root}"
        " (zmienna KARTOGRAF_ROOT; magazyn ze znacznikiem)"
    )
