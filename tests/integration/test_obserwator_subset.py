"""A series version of chosen stations and years (Obserwator ADR-026, E3-01).

Obserwator 3.1.0 builds a series version of a subset of a dataset's stations
and years (``build_series(stations=…, years=…)``), recorded as ``subset`` of
its ``series.json``. The raw root of a copy of ``complete`` gets IMGW-PIB's
half-year archives of 2020 to 2024 (``tests/fixtures/obserwator_statistics.py``)
and its data root the half-year series of Poza krajem (``LATE``) in the
hydrological years 2023 and 2024 alone. Archiwista reads that version as any
other: the years not chosen are unknown to the version, not gaps; the stations
not chosen, whose rows the archives hold, have no series of the dataset rather
than a missing one; and the hand-off spans the version's values.
"""

import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import pytest
from obserwator import SeriesSubset, build_series, read_series_index, sync_store

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.obserwator_http import standin_source
from tests.fixtures.obserwator_roots import data_root, raw_root, store_fields
from tests.fixtures.obserwator_statistics import (
    HALF_YEAR,
    HALF_YEARS,
    HALF_YEARS_ONLY,
    LATE,
    RABA,
    archives,
)

STORE = "dane"
CHOSEN_YEARS = (2023, 2024)


@dataclass(frozen=True)
class Served:
    """The API over the index of a scanned store with a subset series version."""

    owner: Caller
    # The subset version's series.json, relative to the data root.
    version: str

    def json(self, path: str, params: dict[str, str] | None = None) -> Any:
        """Return the body of a ``200`` answer of ``GET path`` under ``/api/v1``."""
        query = "" if not params else "?" + urlencode(params)
        response = self.owner.request("GET", path + query)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture(scope="module")
def served(
    obserwator_store: Any, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Build the half-year series of ``LATE`` in 2023 and 2024, scan and serve."""
    base = tmp_path_factory.mktemp("obserwator-subset")
    root = base / "store"
    shutil.copytree(obserwator_store("complete"), root)
    raw = raw_root(root)
    with standin_source() as source:
        source.archives.update(archives())
        sync_store(raw, datasets=[HALF_YEAR], years=HALF_YEARS)
    report = build_series(
        data_root(root),
        raw_root=raw,
        dataset=HALF_YEAR,
        stations=[LATE],
        years=CHOSEN_YEARS,
    )
    assert report.status == "new", report
    assert report.version is not None
    assert read_series_index(report.version).subset == SeriesSubset(
        stations=(LATE,), years=CHOSEN_YEARS
    )
    paths = local_paths(base)
    config = StoreConfig(id=STORE, name="Dane", **store_fields(root), kind="local")
    settings = AppSettings(stores=(config,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.directory_paths()})
        scan_store(registry.adapter("obserwator"), writer, settings, STORE, mode="full")
    version = report.version.relative_to(data_root(root)).as_posix()
    with running_api(paths, registry) as api:
        yield Served(api.session(LOCAL_OWNER), version)


def test_station_datasets_name_the_subset_version_as_the_current_series(
    served: Served,
) -> None:
    """The subset is the dataset's current version, read like a full one."""
    # Act
    body = served.json("/stations/datasets")

    # Assert
    (item,) = [item for item in body["items"] if item["dataset"] == HALF_YEAR]
    assert item["series_version"] == served.version
    assert "Q_max@winter" in [variable["key"] for variable in item["variables"]]


def test_station_coverage_of_a_subset_leaves_the_years_not_chosen_unknown(
    served: Served,
) -> None:
    """2020 to 2022 are in the raw root's archives but not in the version: no gap."""
    # Act
    body = served.json(f"/stations/{LATE}/coverage")

    # Assert
    (series,) = [item for item in body["series"] if item["dataset"] == HALF_YEAR]
    (winter,) = [item for item in series["variables"] if item["key"] == "Q_max@winter"]
    cells = {year["year"]: year["cell"] for year in winter["years"]}
    assert {year: cells[year] for year in HALF_YEARS} == {
        2020: "unknown",
        2021: "unknown",
        2022: "unknown",
        2023: "full",
        2024: "full",
    }
    assert winter["state"] == "continuous"
    assert winter["longest_gap"] is None


@pytest.mark.parametrize("code", [RABA, HALF_YEARS_ONLY])
def test_station_not_chosen_for_a_subset_has_no_series_of_its_dataset(
    served: Served, code: str
) -> None:
    """Its archive rows are not the version's: no series is claimed, none missing."""
    # Act
    card = served.json(f"/stations/{code}")
    listed = served.json("/stations", {"dataset": HALF_YEAR})

    # Assert
    series = card["station"]["series"]
    assert HALF_YEAR not in [item["dataset"] for item in series]
    assert [station["code"] for station in listed["items"]] == [LATE]


def test_map_draws_a_station_not_chosen_for_a_subset_without_coverage(
    served: Served,
) -> None:
    """Raba Górna keeps its point, uncoloured (unknown), not labelled as no data."""
    # Act
    body = served.json("/map/stations", {"bbox": "14,49,25,55", "dataset": HALF_YEAR})

    # Assert
    points = {item["code"]: item["coverage"] for item in body["items"]}
    assert points[RABA] == {}


def test_station_handoff_of_a_subset_spans_the_chosen_years(served: Served) -> None:
    """The maxima of 2023 and 2024, not the earlier years of the archives as null."""
    # Act
    doc = served.json(
        f"/stations/{LATE}/handoff", {"resolution": "annual", "variable": "Q"}
    )

    # Assert
    payload = doc["payload"]
    assert dict(zip(payload["years"], payload["values"], strict=True)) == {
        2023: 38.0,
        2024: 39.0,
    }
    assert doc["provenance"]["series"]["series_version"] == served.version
    assert doc["provenance"]["series"]["left_out"] == []
