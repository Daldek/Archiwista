"""The lines the providers' terms require with the data a project pins (A-ADR-055).

``GET /projects/{project}`` carries in ``attribution`` and ``terms_notice``
the lines of every version its pins name, each line once in the standard's
order: of Obserwator's versions the lines of their data's origin, of a
producer that names no origin (Kartograf) its sidecar's attribution, as the
project's export writes them in ``ATTRIBUTION.txt``. ``GET /projects`` merges
those of the listed projects; a project without such data has none. The
command ``archiwista project`` ends its text with them. Offline, over the
index of a scanned copy of ``complete_pl_cz`` and a generated Kartograf store.
"""

import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import SourceRegistry, load_registry
from tests.fixtures.api_session import Caller, running_api
from tests.fixtures.api_store import served_store
from tests.fixtures.local_server import local_paths
from tests.fixtures.obserwator_roots import store_fields
from tests.fixtures.provider_lines import (
    CHMU_PROCESSED,
    CHMU_SOURCE,
    IMGW_PROCESSED,
    IMGW_SOURCE,
    IMGW_TERMS_PUBLIC_DATA,
)

STORE = "dane"
IMGW_ARCHIVE = "archives/versions/dane_hydrologiczne/dobowe/2024/codz_2024"
IMGW_SERIES = "series/versions/hydro_daily"
CZ_ARCHIVE = (
    "archives/versions/hydrology/historical/data/daily/H_0-203-1-900001_DQ_2023"
)
CZ_SERIES = "series/versions/chmu_hydro_daily"

type Stores = Callable[[str], Path]


@dataclass(frozen=True)
class Served:
    """The API over the scanned store, with its projects by name."""

    owner: Caller
    paths: AppPaths
    registry: SourceRegistry
    projects: dict[str, str]


def _get(owner: Caller, path: str) -> Any:
    """Return the body of a ``200`` answer of ``GET path``."""
    response = owner.request("GET", path)
    assert response.status_code == 200, response.text
    return response.json()


def _project(owner: Caller, directory: Path, slots: tuple[str, ...]) -> str:
    """Create a project pinning the current versions of ``slots``; return its key."""
    created = owner.request("POST", "/projects", json={"path": str(directory)})
    assert created.status_code == 201, created.text
    key: str = created.json()["project"]
    if slots:
        versions = [
            {
                "store": STORE,
                "version": _get(owner, f"/stores/{STORE}/slots/{slot}")["current"],
            }
            for slot in slots
        ]
        grouped = owner.request(
            "POST",
            f"/projects/{key}/groups",
            json={"name": "Dane", "from": "file", "versions": versions},
        )
        assert grouped.status_code == 201, grouped.text
    return key


@pytest.fixture(scope="module")
def served(
    obserwator_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Serve the index of a copy of ``complete_pl_cz`` with three projects.

    ``polskie`` pins an IMGW-PIB archive and series and a ČHMÚ archive,
    ``czeskie`` a ČHMÚ series and ``pusty`` nothing.
    """
    base = tmp_path_factory.mktemp("project-lines")
    root = base / "store"
    shutil.copytree(obserwator_store("complete_pl_cz"), root)
    paths = local_paths(base)
    directory = base / "projekty"
    directory.mkdir()
    config = StoreConfig(id=STORE, name="Dane", **store_fields(root), kind="local")
    settings = AppSettings(stores=(config,), project_dirs=(directory,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.directory_paths()})
        scan_store(registry.adapter("obserwator"), writer, settings, STORE, mode="full")
    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        projects = {
            "polskie": _project(
                owner, directory / "polskie", (IMGW_ARCHIVE, IMGW_SERIES, CZ_ARCHIVE)
            ),
            "czeskie": _project(owner, directory / "czeskie", (CZ_SERIES,)),
            "pusty": _project(owner, directory / "pusty", ()),
        }
        yield Served(owner, paths, registry, projects)


def test_a_projects_card_carries_the_lines_of_its_pinned_data_once_each(
    served: Served,
) -> None:
    """An IMGW-PIB archive and series and a ČHMÚ archive: S, P, C; RD once."""
    # Act
    card = _get(served.owner, f"/projects/{served.projects['polskie']}")

    # Assert
    assert (card["attribution"], card["terms_notice"]) == (
        [IMGW_SOURCE, IMGW_PROCESSED, CHMU_SOURCE],
        [IMGW_TERMS_PUBLIC_DATA],
    )


def test_a_project_without_data_has_no_lines(served: Served) -> None:
    """No pins: both arrays empty."""
    # Act
    card = _get(served.owner, f"/projects/{served.projects['pusty']}")

    # Assert
    assert (card["attribution"], card["terms_notice"]) == ([], [])


def test_the_list_merges_the_lines_of_its_projects(served: Served) -> None:
    """Every listed project's lines, each once, in the standard's order."""
    # Act
    listed = _get(served.owner, "/projects")

    # Assert
    assert len(listed["items"]) == len(served.projects)
    assert (listed["attribution"], listed["terms_notice"]) == (
        [IMGW_SOURCE, IMGW_PROCESSED, CHMU_SOURCE, CHMU_PROCESSED],
        [IMGW_TERMS_PUBLIC_DATA],
    )


def test_the_project_command_ends_its_text_with_the_lines(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista project``: the card, then the lines, indented, last."""
    # Arrange
    key = served.projects["czeskie"]
    capsys.readouterr()

    # Act
    status = main(["project", key], registry=served.registry, paths=served.paths)

    # Assert
    assert status == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [
        f"  {CHMU_SOURCE}",
        f"  {CHMU_PROCESSED}",
    ]


def test_a_kartograf_projects_card_carries_its_sidecars_attribution(
    tmp_path: Path,
) -> None:
    """A producer that names no origin: its sidecar's attribution, no terms."""
    with served_store(tmp_path) as kartograf:
        # Act
        card = _get(kartograf.owner, "/projects/projekt-01")

    # Assert
    assert (card["attribution"], card["terms_notice"]) == (
        ["Archiwista synthetic test store"],
        [],
    )
