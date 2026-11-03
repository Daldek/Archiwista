"""The years of a page of stations, the route of the Timeline tab (plan I8.3).

``GET /stations/timeline`` pages the stations of one dataset with the filters,
order and cursor of ``GET /stations`` over the index of a scanned copy of
``complete_pl_cz`` (``imgwtools.testing``), each station with its series year
by year exactly as ``GET /stations/{code}/coverage`` gives it; ``dataset`` is
required. ``archiwista stations timeline`` prints the same. The page's years
are read at once: 200 stations of 75 years each are answered within the
300 ms of SPEC 4.5 (``perf``, on a synthetic index).
"""

import json
import shutil
import statistics
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources import SeriesListing, Station, StationSeries, VariableCoverage
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.local_server import local_paths

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"
RABA = "149190310"
# The fields of a station the Timeline shares with the list.
STATION_FIELDS = (
    "store",
    "provider",
    "code",
    "name",
    "kind",
    "meteo_kind",
    "river",
    "hydrographic_code",
    "active",
    "location",
)

type Stores = Callable[[str], Path]
type Params = dict[str, str | list[str]]


@dataclass(frozen=True)
class Served:
    """The API over the index of a scanned fixture store, and its command line."""

    owner: Caller
    paths: AppPaths

    def get(self, path: str, params: Params | None = None) -> httpx.Response:
        """Return the answer of ``GET path`` under ``/api/v1``."""
        query = "" if not params else "?" + urlencode(params, doseq=True)
        return self.owner.request("GET", path + query)

    def json(self, path: str, params: Params | None = None) -> Any:
        """Return the body of a ``200`` answer of ``GET path``."""
        response = self.get(path, params)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture(scope="module")
def served(
    imgw_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Serve the index of a copy of ``complete_pl_cz`` after a full scan."""
    base = tmp_path_factory.mktemp("station-timeline")
    root = base / "store"
    shutil.copytree(imgw_store("complete_pl_cz"), root)
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
        yield Served(api.session(LOCAL_OWNER), paths)


def _options(params: Params) -> list[str]:
    """Return the options of route parameters, a list as a repeated option."""
    return [
        f"--{name.replace('_', '-')}={item}"
        for name, value in params.items()
        for item in (value if isinstance(value, list) else [value])
    ]


def _pages(served: Served, path: str, params: Params) -> list[dict[str, Any]]:
    """Return every page of a query, each asked with the cursor of the one before."""
    pages = [served.json(path, params)]
    while pages[-1]["next_cursor"] is not None:
        assert len(pages) < 50
        cursor = pages[-1]["next_cursor"]
        pages.append(served.json(path, {**params, "cursor": cursor}))
    return pages


def _station(item: dict[str, Any]) -> dict[str, Any]:
    return {name: item[name] for name in STATION_FIELDS}


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"variable": ["Q"]},
        {"years": "2020-2024", "year_type": "calendar"},
        {"sort": "name", "location": "with"},
    ],
)
def test_each_item_is_the_coverage_of_its_station_and_the_pages_join(
    served: Served, params: Params
) -> None:
    """Every dataset: the stations of the list, each with its coverage route."""
    # Arrange
    datasets = sorted(
        {item["dataset"] for item in served.json("/stations/datasets")["items"]}
    )
    labelled = {
        name: params[name]
        for name in ("variable", "years", "year_type")
        if name in params
    }
    seen = 0

    # Act and Assert
    for dataset in datasets:
        query: Params = {"dataset": dataset, **params}
        pages = _pages(served, "/stations/timeline", {**query, "limit": "2"})
        whole = served.json("/stations/timeline", {**query, "limit": "200"})
        listed = served.json("/stations", {**query, "limit": "200"})
        items = [item for page in pages for item in page["items"]]
        assert items == whole["items"]
        assert [page["counts"] for page in pages] == [listed["counts"]] * len(pages)
        assert [_station(item) for item in items] == [
            _station(item) for item in listed["items"]
        ]
        for item in items:
            coverage = served.json(
                f"/stations/{item['code']}/coverage",
                {
                    "store": item["store"],
                    "provider": item["provider"],
                    "dataset": dataset,
                    **labelled,
                },
            )
            assert item["series"] == coverage["series"], item["code"]
            assert [series["dataset"] for series in item["series"]] == [dataset]
            seen += 1
    assert seen >= 3


def test_variable_keeps_the_stations_with_a_value_and_only_their_years(
    served: Served,
) -> None:
    """``Q`` leaves out the gauge without Q and every other variable's row."""
    # Act
    every = served.json("/stations/timeline", {"dataset": DAILY})
    flows = served.json("/stations/timeline", {"dataset": DAILY, "variable": "Q"})

    # Assert
    raba = next(item for item in every["items"] if item["code"] == RABA)
    (series,) = raba["series"]
    assert [variable["key"] for variable in series["variables"]] == ["H", "Q", "T"]
    years = series["variables"][0]["years"]
    assert [year["year"] for year in years] == list(range(1951, 2025))
    assert 0 < len(flows["items"]) < len(every["items"])
    for item in flows["items"]:
        (only,) = item["series"]
        assert [variable["key"] for variable in only["variables"]] == ["Q"]


def test_dataset_is_required_and_unknown_parameters_are_refused(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without ``dataset`` the route and the command line refuse alike."""
    # Act
    missing = served.get("/stations/timeline")
    misspelt = served.get("/stations/timeline", {"dataset": DAILY, "grid_columns": "4"})
    capsys.readouterr()
    status = main(["stations", "timeline", "--json"], paths=served.paths)
    captured = capsys.readouterr()

    # Assert
    assert_problem(missing, 400, "validation_error")
    assert [item["pointer"] for item in missing.json()["errors"]] == ["/query/dataset"]
    assert_problem(misspelt, 400, "validation_error")
    document = refusal(captured.out, captured.err, status)
    assert_same_error(document, missing.json())
    assert document["exit_code"] == 2


@pytest.mark.parametrize(
    "params",
    [
        {"dataset": DAILY, "limit": "1"},
        {"dataset": DAILY, "variable": ["H", "T"], "year_type": "calendar"},
        {"dataset": "cz.chmi.meteo_daily", "sort": "name"},
    ],
)
def test_the_route_and_the_command_line_give_the_same_pages(
    served: Served, capsys: pytest.CaptureFixture[str], params: Params
) -> None:
    """``archiwista stations timeline --json`` prints each page of the route."""
    # Arrange
    pairs: list[tuple[Any, Any]] = []
    cursor: Params = {}

    # Act
    while len(pairs) < 10:
        query = {**params, **cursor}
        capsys.readouterr()
        argv = ["stations", "timeline", *_options(query), "--json"]
        assert main(argv, paths=served.paths) == 0
        from_cli = json.loads(capsys.readouterr().out)
        pairs.append((from_cli, served.json("/stations/timeline", query)))
        if pairs[-1][1]["next_cursor"] is None:
            break
        cursor = {"cursor": pairs[-1][1]["next_cursor"]}

    # Assert
    assert pairs[-1][1]["next_cursor"] is None
    assert [from_cli for from_cli, _ in pairs] == [route for _, route in pairs]
    assert sum(len(route["items"]) for _, route in pairs) >= 1


def test_the_command_line_draws_a_strip_of_years_for_a_person(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """A line per variable: its years as cells, then its label; a legend."""
    # Arrange
    path = f"/stations/timeline?dataset={DAILY}"
    route = served.owner.request("GET", path, accept_language="pl").json()
    raba = next(item for item in route["items"] if item["code"] == RABA)
    (series,) = raba["series"]
    cells = {"full": "█", "fraction": "▒", "none": "·", "unknown": "?"}

    # Act
    capsys.readouterr()
    assert main(["stations", "timeline", f"--dataset={DAILY}"], paths=served.paths) == 0
    lines = capsys.readouterr().out.splitlines()

    # Assert
    start = lines.index(
        f"{RABA}  Raba Górna · hydro · IMGW-PIB · magazyn {STORE} · Raba (213)"
    )
    assert lines[start + 1] == (
        f"  {DAILY} (szeregi {series['series']}, lata hydrologiczne 1951–2024)"
    )
    strips = lines[start + 2 : start + 5]
    for line, variable in zip(strips, series["variables"], strict=True):
        years = "".join(cells[year["cell"]] for year in variable["years"])
        assert line == f"    {variable['key']} {years}  {variable['label']}"
    assert strips[0].split()[1] == "?" * 73 + "▒"  # 2024 holds the gaps of H
    assert "Lata: █ pełny, ▒ z lukami, · bez wartości, ? nieznany." in lines
    assert lines[-1].startswith("Stacje na stronie: ")


# Performance ------------------------------------------------------------------

PERF_STATIONS = 200
PERF_RUNS = 30
PERF_MS = 300.0
# 75 hydrological years, 1951 to 2025.
PERF_KNOWN = (date(1950, 11, 1), date(2025, 10, 31))


def _perf_variable(key: str, unit: str, shift: int) -> VariableCoverage:
    """Return a variable of 75 years with ten gaps of 20 days, one every 7 years."""
    starts = (
        date(1952 + year, 3, 1) + timedelta(days=shift) for year in range(0, 70, 7)
    )
    return VariableCoverage(
        key=key,
        variable=key,
        unit=unit,
        period=None,
        first=PERF_KNOWN[0],
        last=PERF_KNOWN[1],
        with_value=(PERF_KNOWN[1] - PERF_KNOWN[0]).days + 1 - 200,
        accumulated=0,
        gaps=tuple((start, start + timedelta(days=19)) for start in starts),
    )


def _perf_index(paths: AppPaths, root: Path) -> None:
    """Write 200 water gauges with H, Q and T of 75 years, as a scan writes them."""
    codes = [f"1492{index:05d}" for index in range(PERF_STATIONS)]
    folder = "series/versions/hydro_daily/2026-10-26_00000000"
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {"imgw": root}})
        writer.replace_stations(
            STORE,
            "imgw",
            "IMGW-PIB",
            slot="stations/versions",
            version="stations/versions/2026-10-26_00000000/stations.geojson",
            stations=[
                Station(
                    "IMGW-PIB",
                    code,
                    kind="hydro",
                    name=f"Stacja {index}",
                    river="Raba",
                    hydrographic_code=f"2138{index % 10}",
                    river_order=index,
                    point=(19.0 + index / 100, 50.0),
                    location_source="api_hydro",
                )
                for index, code in enumerate(codes)
            ],
        )
        writer.replace_series(
            STORE,
            "imgw",
            slot="series/versions/hydro_daily",
            version=f"{folder}/series.json",
            listing=SeriesListing(
                dataset=DAILY,
                provider="IMGW-PIB",
                kind="hydro",
                time_unit="day",
                year_type="hydrological",
                first_year=1951,
                periods=(PERF_KNOWN,),
                stations=tuple(
                    StationSeries(
                        code=code,
                        file=f"{folder}/stations/{code}.parquet",
                        sha256="0" * 64,
                        rows=(PERF_KNOWN[1] - PERF_KNOWN[0]).days + 1,
                        variables=(
                            _perf_variable("H", "cm", index % 5),
                            _perf_variable("Q", "m3/s", index % 3),
                            _perf_variable("T", "degC", 0),
                        ),
                    )
                    for index, code in enumerate(codes)
                ),
            ),
        )


@pytest.mark.perf
def test_a_page_of_200_stations_of_75_years_within_300_ms(tmp_path: Path) -> None:
    """The page the Timeline tab asks for (H, Q, T of each), p95 over HTTP."""
    # Arrange
    paths = local_paths(tmp_path)
    ConfigStore(paths.config_file).save(AppSettings())
    _perf_index(paths, tmp_path / "store" / "imgw")
    path = f"/stations/timeline?dataset={DAILY}&limit={PERF_STATIONS}"

    # Act
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        caller = api.session(LOCAL_OWNER)
        page = caller.request("GET", path).json()
        samples = []
        for _ in range(PERF_RUNS):
            started = time.perf_counter()
            response = caller.request("GET", path)
            samples.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
    samples.sort()
    p95 = samples[int(0.95 * (len(samples) - 1))]
    print(
        f"\ntimeline of {PERF_STATIONS} stations: p95 {p95:.1f} ms,"
        f" median {statistics.median(samples):.1f} ms"
    )

    # Assert
    assert len(page["items"]) == PERF_STATIONS
    for item in page["items"]:
        (series,) = item["series"]
        assert [len(variable["years"]) for variable in series["variables"]] == [75] * 3
    assert p95 <= PERF_MS
