"""The lines the providers' terms require with a stored version (A-ADR-055).

A version of Obserwator's store is a provider's file as published (an
archive: S, or C, alone) or a form Obserwator processed (a series: S and P,
or C and CP; the IMGW-PIB station catalog adds the hydrological service's
H and RH). The version's card (``GET /stores/{store}/versions/{path}``), the
Katalog's page (``GET /slots``) and a comparison (``GET /compare``) carry
the lines of that origin, which the producer's adapter names, never the
attribution a sidecar holds. Offline, over the index of a scanned copy of
``complete_pl_cz``.
"""

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.provider_lines import (
    CHMI_PROCESSED,
    CHMI_SOURCE,
    IMGW_HYDRO,
    IMGW_PROCESSED,
    IMGW_SOURCE,
    IMGW_TERMS,
    IMGW_TERMS_HYDRO,
    IMGW_TERMS_PUBLIC_DATA,
)

STORE = "dane"
IMGW_ARCHIVE = "archives/versions/dane_hydrologiczne/dobowe/2024/codz_2024"
IMGW_SERIES = "series/versions/hydro_daily"
IMGW_CATALOG = "stations/versions"
CZ_ARCHIVE = (
    "archives/versions/hydrology/historical/data/daily/H_0-203-1-900001_DQ_2023"
)
CZ_SERIES = "series/versions/chmi_hydro_daily"
CZ_CATALOG = "stations/versions/chmi_stations"
PUBLIC_DATA_TERMS = [IMGW_TERMS, IMGW_TERMS_PUBLIC_DATA]

type Stores = Callable[[str], Path]


@pytest.fixture(scope="module")
def owner(
    obserwator_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Caller]:
    """Serve the index of a copy of ``complete_pl_cz`` after a full scan."""
    base = tmp_path_factory.mktemp("version-lines")
    root = base / "store"
    shutil.copytree(obserwator_store("complete_pl_cz"), root)
    paths = local_paths(base)
    config = StoreConfig(id=STORE, name="Dane", obserwator=root, kind="local")
    settings = AppSettings(stores=(config,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        scan_store(registry.adapter("obserwator"), writer, settings, STORE, mode="full")
    with running_api(paths, registry) as api:
        yield api.session(LOCAL_OWNER)


def _get(owner: Caller, path: str) -> Any:
    """Return the body of a ``200`` answer of ``GET path``."""
    response = owner.request("GET", path)
    assert response.status_code == 200, response.text
    return response.json()


def _current(owner: Caller, slot: str) -> str:
    """Return the path of a slot's current version."""
    path: str = _get(owner, f"/stores/{STORE}/slots/{slot}")["current"]
    return path


@pytest.mark.parametrize(
    ("slot", "attribution", "terms_notice"),
    [
        pytest.param(IMGW_ARCHIVE, [IMGW_SOURCE], PUBLIC_DATA_TERMS, id="imgw-archive"),
        pytest.param(
            IMGW_SERIES,
            [IMGW_SOURCE, IMGW_PROCESSED],
            PUBLIC_DATA_TERMS,
            id="imgw-series",
        ),
        pytest.param(
            IMGW_CATALOG,
            [IMGW_SOURCE, IMGW_PROCESSED, IMGW_HYDRO],
            [*PUBLIC_DATA_TERMS, IMGW_TERMS_HYDRO],
            id="imgw-catalog",
        ),
        pytest.param(CZ_ARCHIVE, [CHMI_SOURCE], [], id="chmi-archive"),
        pytest.param(CZ_SERIES, [CHMI_SOURCE, CHMI_PROCESSED], [], id="chmi-series"),
        pytest.param(CZ_CATALOG, [CHMI_SOURCE, CHMI_PROCESSED], [], id="chmi-catalog"),
    ],
)
def test_a_versions_card_carries_the_lines_of_its_datas_origin(
    owner: Caller, slot: str, attribution: list[str], terms_notice: list[str]
) -> None:
    """A file as published: S or C alone; Obserwator's forms: processed."""
    # Act
    card = _get(owner, f"/stores/{STORE}/versions/{_current(owner, slot)}")

    # Assert
    assert (card["attribution"], card["terms_notice"]) == (attribution, terms_notice)


def test_the_catalog_page_carries_the_lines_of_its_rows_once_each(
    owner: Caller,
) -> None:
    """Every provider and form of the page, in the standard's order."""
    # Act
    page = _get(owner, "/slots?limit=200")

    # Assert
    assert page["next_cursor"] is None
    assert (page["attribution"], page["terms_notice"]) == (
        [IMGW_SOURCE, IMGW_PROCESSED, IMGW_HYDRO, CHMI_SOURCE, CHMI_PROCESSED],
        [*PUBLIC_DATA_TERMS, IMGW_TERMS_HYDRO],
    )


def test_a_comparison_carries_the_lines_of_both_sides(owner: Caller) -> None:
    """A ČHMÚ file beside an IMGW-PIB series: S and P before C, whatever the side."""
    # Arrange
    czech = f"version:{STORE}:{_current(owner, CZ_ARCHIVE)}"
    polish = f"version:{STORE}:{_current(owner, IMGW_SERIES)}"

    # Act
    comparison = _get(owner, "/compare?" + urlencode({"a": czech, "b": polish}))

    # Assert
    assert (comparison["attribution"], comparison["terms_notice"]) == (
        [IMGW_SOURCE, IMGW_PROCESSED, CHMI_SOURCE],
        PUBLIC_DATA_TERMS,
    )
