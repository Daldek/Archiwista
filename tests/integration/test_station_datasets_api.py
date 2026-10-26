"""The datasets with station series and the type of a meteo station (plan I8.1).

``GET /stations/datasets`` names the datasets of the series slots of a scanned
copy of ``complete`` and ``complete_pl_cz`` (``imgwtools.testing``): the
producer's name of each segment, its family, unit, default year type and R,
the label of its current series version and the variables of its stations'
series, which are those ``imgwtools.summarize_series`` gives. ``archiwista
stations datasets`` prints the same, both answer ``503`` without IMGWTools,
and the repeatable ``meteo_kind`` keeps the stations of the type chips of the
map, with the counts.
"""

import json
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import imgwtools
import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import PluginRegistry, load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.cli_errors import refusal
from tests.fixtures.local_server import NoSources, local_paths
from tests.fixtures.missing_package import hide_packages

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"
PRECIPITATION = "pl.imgw.meteo_precip_daily"
SERIES_UNITS = ("day", "month", "half_year")

type Stores = Callable[[str], Path]


@dataclass(frozen=True)
class Served:
    """The API over the index of a scanned fixture store, and its command line."""

    owner: Caller
    paths: AppPaths
    root: Path

    def get(self, path: str) -> httpx.Response:
        """Return the answer of ``GET path`` under ``/api/v1``."""
        return self.owner.request("GET", path)

    def json(self, path: str) -> Any:
        """Return the body of a ``200`` answer of ``GET path``."""
        response = self.get(path)
        assert response.status_code == 200, response.text
        return response.json()


def _serve(imgw_store: Stores, base: Path, variant: str) -> Iterator[Served]:
    root = base / "store"
    shutil.copytree(imgw_store(variant), root)
    paths = local_paths(base)
    config = StoreConfig(id=STORE, name="Dane", imgw=root, kind="local")
    settings = AppSettings(stores=(config,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        scan_store(registry.adapter("imgw"), writer, settings, STORE, mode="full")
    with running_api(paths, registry) as api:
        yield Served(api.session(LOCAL_OWNER), paths, root)


@pytest.fixture(scope="module", params=["complete", "complete_pl_cz"])
def served(
    request: pytest.FixtureRequest,
    imgw_store: Stores,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Served]:
    """Serve the index of a copy of each fixture variant after a full scan."""
    base = tmp_path_factory.mktemp(f"datasets-{request.param}")
    yield from _serve(imgw_store, base, request.param)


@pytest.fixture(scope="module")
def mixed(
    imgw_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Serve the index of ``complete_pl_cz``: stations of both providers."""
    yield from _serve(
        imgw_store, tmp_path_factory.mktemp("meteo-kinds"), "complete_pl_cz"
    )


def _series_datasets(root: Path) -> list[str]:
    """Return the datasets whose series slot has a current version, by key."""
    return sorted(
        item.key
        for item in imgwtools.datasets()
        if item.in_store
        and item.time_unit in SERIES_UNITS
        and imgwtools.current_version(root, slot=f"series:{item.key}") is not None
    )


def _variables(root: Path, dataset: str) -> set[tuple[str, str]]:
    """Return a dataset's variable keys with their units, as IMGWTools reads them."""
    return {
        (
            row.variable if row.period is None else f"{row.variable}@{row.period}",
            row.unit,
        )
        for row in imgwtools.summarize_series(root=root, dataset=dataset)
    }


def test_datasets_are_those_of_the_series_slots_with_their_variables(
    served: Served,
) -> None:
    """Each dataset with a series version, its version and its variables."""
    # Act
    body = served.json("/stations/datasets")

    # Assert
    items = body["items"]
    assert [item["dataset"] for item in items] == _series_datasets(served.root)
    assert body["stale"] is False
    for item in items:
        descriptor = imgwtools.get_dataset(item["dataset"])
        entry = imgwtools.current_version(served.root, slot=f"series:{item['dataset']}")
        assert entry is not None and entry.version is not None
        assert item["store"] == STORE
        assert item["provider"] == descriptor.provider
        assert item["kind"] == descriptor.kind
        assert item["time_unit"] == descriptor.time_unit
        version = entry.version
        assert item["series_version"] == version.relative_to(served.root).as_posix()
        assert item["series"] == version.parent.name.split("_")[0]
        keys = [variable["key"] for variable in item["variables"]]
        assert len(keys) == len(set(keys))
        assert {
            (variable["key"], variable["unit"]) for variable in item["variables"]
        } == _variables(served.root, item["dataset"])
    daily = next(item for item in items if item["dataset"] == DAILY)
    assert (daily["name"], daily["year_type"], daily["years"]) == (
        "Dane hydrologiczne dobowe",
        "hydrological",
        {"from": 1951, "to": 2024},
    )
    assert daily["variables"] == [
        {"key": "H", "variable": "H", "unit": "cm", "period": None},
        {"key": "Q", "variable": "Q", "unit": "m3/s", "period": None},
        {"key": "T", "variable": "T", "unit": "degC", "period": None},
    ]
    rain = next(item for item in items if item["dataset"] == PRECIPITATION)
    assert (rain["kind"], rain["year_type"], rain["years"]) == (
        "meteo",
        "calendar",
        {"from": 1950, "to": 2001},
    )


def test_the_route_and_the_command_line_give_the_same_datasets(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista stations datasets --json`` prints the route's answer."""
    # Act
    answers = []
    for options in ([], [f"--store={STORE}"]):
        capsys.readouterr()
        assert (
            main(["stations", "datasets", *options, "--json"], paths=served.paths) == 0
        )
        answers.append(capsys.readouterr().out)
    capsys.readouterr()
    assert main(["stations", "datasets"], paths=served.paths) == 0
    text = capsys.readouterr().out

    # Assert
    route = served.json("/stations/datasets")
    chosen = served.json(f"/stations/datasets?store={STORE}")
    assert [json.loads(out) for out in answers] == [route, chosen]
    assert f"{DAILY} · Dane hydrologiczne dobowe · IMGW-PIB · hydro" in text
    assert "H (cm), Q (m3/s), T (degC)" in text


def test_an_unknown_store_or_parameter_is_refused(served: Served) -> None:
    """A store that is not configured and a misspelt parameter are problems."""
    # Act
    unknown = served.get("/stations/datasets?store=brak")
    misspelt = served.get("/stations/datasets?dataset=pl.imgw.hydro_daily")

    # Assert
    assert_problem(unknown, 400, "validation_error")
    assert_problem(misspelt, 400, "validation_error")


@pytest.mark.parametrize("missing", ["registry", "package"])
def test_the_datasets_answer_503_while_the_source_is_not_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    """Without IMGWTools neither the route nor the command line names a dataset."""
    # Arrange
    paths = local_paths(tmp_path)
    registry: PluginRegistry = NoSources()
    if missing == "package":
        hide_packages(monkeypatch, "imgwtools")
        registry = load_registry(cache_dir=paths.cache_dir)

    # Act
    with running_api(paths, registry) as api:
        response = api.session(LOCAL_OWNER).request("GET", "/stations/datasets")
    capsys.readouterr()
    status = main(["stations", "datasets", "--json"], paths=paths, registry=registry)
    captured = capsys.readouterr()

    # Assert
    assert_problem(response, 503, "missing_dependency", "source_unavailable")
    document = refusal(captured.out, captured.err, status)
    assert document["code"] == "missing_dependency"
    assert document["details"]["reason"] == "source_unavailable"


def test_openapi_documents_the_datasets_route(served: Served) -> None:
    """Agents find the route, its one parameter, its example and its problems."""
    # Act
    document = served.json("/openapi.json")

    # Assert
    operation = document["paths"]["/api/v1/stations/datasets"]["get"]
    assert {item["name"] for item in operation["parameters"]} == {"store"}
    assert {"400", "401", "503"} <= set(operation["responses"])
    reference = operation["responses"]["200"]["content"]["application/json"]
    name = reference["schema"]["$ref"].rsplit("/", 1)[1]
    assert document["components"]["schemas"][name]["examples"]
    names = {
        item["name"]
        for item in document["paths"]["/api/v1/stations"]["get"]["parameters"]
    }
    assert "meteo_kind" in names


def test_meteo_kind_keeps_the_stations_of_a_type_with_their_counts(
    mixed: Served,
) -> None:
    """``precipitation`` keeps the two IMGW precipitation posts, one unlocated."""
    # Act
    rain = mixed.json("/stations?meteo_kind=precipitation")
    both = mixed.json("/stations?meteo_kind=precipitation&meteo_kind=climate")
    climate = mixed.json("/stations?meteo_kind=climate")
    drawn = mixed.json("/map/stations?bbox=14,48,24,55&meteo_kind=precipitation")
    everything = mixed.json("/map/stations?bbox=14,48,24,55")
    refused = mixed.get("/stations?meteo_kind=hydro")

    # Assert
    assert sorted(item["code"] for item in rain["items"]) == ["123750000", "123760000"]
    assert {item["meteo_kind"] for item in rain["items"]} == {"precipitation"}
    assert rain["counts"] == {"located": 1, "boundary": 0, "unlocated": 1, "hidden": 0}
    assert both["items"] == rain["items"]
    assert (climate["items"], climate["counts"]["unlocated"]) == ([], 0)
    assert [item["code"] for item in drawn["items"]] == ["123750000"]
    assert drawn["counts"] == rain["counts"]
    assert everything["total"] > drawn["total"]
    assert_problem(refused, 400, "validation_error")
