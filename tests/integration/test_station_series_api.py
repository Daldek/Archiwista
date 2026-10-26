"""A station's series as a chart, the route of the station card (plan I8.4).

``GET /stations/{code}/series`` reads the values of one or two variables of a
station's current series through the producer over the index of a scanned
copy of ``complete`` (``imgwtools.testing``): each unit's value up to
``max_points`` units, else the least, mean and greatest value of intervals,
the producer's gaps cut at the range's ends and the accumulated sums as
markers. ``archiwista stations series`` prints the same. Building the chart of
27,393 days takes less than the 500 ms of SPEC 4.5 (``perf``; the read of a
real 75-year file is measured on the author's store).
"""

import json
import shutil
import statistics
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from imgwtools import read_series, read_series_index

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import (
    CoverageVariable,
    IndexWriter,
    StationCoverage,
    initialize,
    scan_store,
)
from archiwista.index.series import SeriesLabel
from archiwista.services.series_chart import station_chart
from archiwista.sources import Extreme, SeriesValues
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.local_server import local_paths

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"
PRECIPITATION = "pl.imgw.meteo_precip_daily"
RABA = "149190310"

type Stores = Callable[[str], Path]
type Params = dict[str, str | list[str]]


@dataclass(frozen=True)
class Served:
    """The API over the index of a scanned fixture store, and its command line."""

    owner: Caller
    paths: AppPaths
    root: Path

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
    """Serve the index of a copy of ``complete`` after a full scan."""
    base = tmp_path_factory.mktemp("station-series")
    root = base / "store"
    shutil.copytree(imgw_store("complete"), root)
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


def _series(served: Served, code: str, variables: Sequence[str]) -> list[Any]:
    """Return the producer's records of a station's current daily series."""
    card = served.json(f"/stations/{code}")
    (series,) = (item for item in card["station"]["series"] if item["coverage"])
    path = served.root / series["series_version"]
    return list(read_series(path, station=code, variables=list(variables)))


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def test_the_daily_values_are_the_producers_with_the_two_gaps(served: Served) -> None:
    """H of the Raba gauge: a point a day, ``null`` without a value, two bands."""
    # Arrange
    records = _series(served, RABA, ["H"])
    card = served.json(f"/stations/{RABA}", {"dataset": DAILY})
    (series,) = card["station"]["series"]
    gaps = read_series_index(served.root / series["series_version"])
    produced = gaps.stations[RABA].variables["H"].gaps

    # Act
    chart = served.json(f"/stations/{RABA}/series", {"variable": "H"})

    # Assert
    assert (chart["from"], chart["to"], chart["units"], chart["interval"]) == (
        "2023-12-01",
        "2024-02-29",
        91,
        1,
    )
    assert (chart["dataset"], chart["file"], chart["sha256"]) == (
        DAILY,
        series["file"],
        series["sha256"],
    )
    assert (chart["license"], chart["attribution"]) == (
        series["license"],
        series["attribution"],
    )
    (variable,) = chart["variables"]
    value = {record.date: record.measurements["H"].value for record in records}
    assert variable["points"] == [
        {"t": day.isoformat(), "min": value[day], "mean": value[day], "max": value[day]}
        for day in _days(date(2023, 12, 1), date(2024, 2, 29))
    ]
    assert variable["gaps"] == [
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "units": (end - start).days + 1,
        }
        for start, end in produced
    ]
    assert [gap["units"] for gap in variable["gaps"]] == [30, 28]
    assert [
        point["t"] for point in variable["points"] if point["mean"] is not None
    ] == [
        "2023-12-01",
        "2024-02-29",
    ]
    assert (variable["key"], variable["unit"], variable["markers"]) == ("H", "cm", [])


def test_more_units_than_points_give_the_least_mean_and_greatest_of_each_interval(
    served: Served,
) -> None:
    """``max_points=30`` over 91 days: intervals of 4 days from the first."""
    # Arrange
    records = _series(served, RABA, ["H", "Q"])

    # Act
    chart = served.json(
        f"/stations/{RABA}/series",
        {"variable": ["H", "Q"], "max_points": "30"},
    )

    # Assert
    assert (chart["units"], chart["interval"]) == (91, 4)
    first = date(2023, 12, 1)
    for variable in chart["variables"]:
        name = variable["key"]
        expected = []
        for index in range(23):
            start = first + timedelta(days=4 * index)
            values = [
                record.measurements[name].value
                for record in records
                if start <= record.date < start + timedelta(days=4)
                and record.measurements[name].value is not None
            ]
            expected.append(
                {
                    "t": start.isoformat(),
                    "min": min(values) if values else None,
                    "mean": round(sum(values) / len(values), 6) if values else None,
                    "max": max(values) if values else None,
                }
            )
        assert variable["points"] == expected, name
    assert [variable["key"] for variable in chart["variables"]] == ["H", "Q"]
    assert [len(variable["gaps"]) for variable in chart["variables"]] == [2, 0]


def test_a_range_cuts_the_gaps_and_its_units_without_a_row_have_no_value(
    served: Served,
) -> None:
    """Days before the station's file are units without a value, not a gap."""
    # Act
    chart = served.json(
        f"/stations/{RABA}/series",
        {"variable": "H", "from": "2023-11-28", "to": "2023-12-05"},
    )

    # Assert
    (variable,) = chart["variables"]
    assert [point["mean"] is not None for point in variable["points"]] == [
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
    ]
    assert variable["gaps"] == [{"from": "2023-12-02", "to": "2023-12-05", "units": 4}]


def test_an_accumulated_sum_is_a_marker_and_no_value_of_its_day(
    served: Served,
) -> None:
    """Precipitation: the producer's accumulated unit is a marker with its sum."""
    # Arrange
    card = served.json("/stations/123750000", {"dataset": PRECIPITATION})
    (series,) = card["station"]["series"]
    records = list(
        read_series(
            served.root / series["series_version"], station="123750000", variables=["P"]
        )
    )
    (summed,) = [r for r in records if r.measurements["P"].flag == "accumulated"]

    # Act
    chart = served.json("/stations/123750000/series", {"variable": "P"})

    # Assert
    (variable,) = chart["variables"]
    assert variable["markers"] == [
        {
            "t": summed.date.isoformat(),
            "kind": "accumulated",
            "value": summed.measurements["P"].value,
            "period": None,
            "end": None,
        }
    ]
    (point,) = [p for p in variable["points"] if p["t"] == summed.date.isoformat()]
    assert point == {"t": point["t"], "min": None, "mean": None, "max": None}


@pytest.mark.parametrize(
    ("params", "status", "code", "reason"),
    [
        ({"variable": "P"}, 400, "validation_error", "unknown_variable"),
        ({"variable": ["H", "Q", "T"]}, 400, "validation_error", None),
        ({}, 400, "validation_error", None),
        (
            {"variable": "H", "from": "2024-02-01", "to": "2024-01-01"},
            400,
            "validation_error",
            None,
        ),
        ({"variable": "H", "max_points": "2001"}, 400, "validation_error", None),
        ({"variable": "H", "dataset": PRECIPITATION}, 404, "not_found", None),
        (
            {"variable": "H", "version": "series/versions/hydro_daily/x/series.json"},
            409,
            "conflict",
            "series_version_not_current",
        ),
    ],
)
def test_refusals(
    served: Served, params: Params, status: int, code: str, reason: str | None
) -> None:
    """Unknown or too many variables, a reversed range, another series version."""
    # Act
    response = served.get(f"/stations/{RABA}/series", params)

    # Assert
    assert_problem(response, status, code, reason)


def test_the_current_version_may_be_named(served: Served) -> None:
    """``version`` equal to the index's current one changes nothing."""
    # Arrange
    card = served.json(f"/stations/{RABA}", {"dataset": DAILY})
    (series,) = card["station"]["series"]

    # Act
    named = served.json(
        f"/stations/{RABA}/series",
        {"variable": "H", "version": series["series_version"]},
    )

    # Assert
    assert named == served.json(f"/stations/{RABA}/series", {"variable": "H"})


@pytest.mark.parametrize(
    "argv",
    [
        ["--variable=H"],
        ["--variable=H", "--variable=Q", "--max-points=30", f"--dataset={DAILY}"],
        ["--variable=T", "--from=2024-02-01", "--to=2024-02-29"],
    ],
)
def test_the_route_and_the_command_line_give_the_same_chart(
    served: Served, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    """``archiwista stations series CODE --json`` prints the route's answer."""
    # Arrange
    params: dict[str, list[str]] = {}
    for option in argv:
        name, _, value = option.removeprefix("--").partition("=")
        params.setdefault(name.replace("-", "_"), []).append(value)

    # Act
    capsys.readouterr()
    status = main(["stations", "series", RABA, *argv, "--json"], paths=served.paths)
    from_cli = json.loads(capsys.readouterr().out)

    # Assert
    assert status == 0
    assert from_cli == served.json(f"/stations/{RABA}/series", dict(params))


def test_the_command_line_refuses_as_the_route_does(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """A variable the series lacks: the same problem and the exit code 2."""
    # Act
    problem = served.get(f"/stations/{RABA}/series", {"variable": "P"}).json()
    capsys.readouterr()
    status = main(["stations", "series", RABA, "--variable=P"], paths=served.paths)
    captured = capsys.readouterr()

    # Assert
    document = refusal(captured.out, captured.err, status)
    assert_same_error(document, problem)
    assert document["exit_code"] == 2


def test_the_command_line_writes_the_chart_for_a_person(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """The series, the range and each variable's points, gaps and markers."""
    # Act
    capsys.readouterr()
    status = main(
        ["stations", "series", RABA, "--variable=H", "--max-points=30"],
        paths=served.paths,
    )
    lines = capsys.readouterr().out.splitlines()

    # Assert
    assert status == 0
    assert lines[1] == (
        "Zakres 2023-12-01 – 2024-02-29 (91 dni): uproszczony, min./śr./maks. z 4 dni"
    )
    assert lines[2] == "  H (cm): 2 z 23 punktów z wartością, luki: 2, znaczniki: 0"
    assert lines[3:5] == [
        "    luka 2023-12-02 – 2023-12-31 (30 dni)",
        "    luka 2024-02-01 – 2024-02-28 (28 dni)",
    ]
    assert lines[5].startswith("  Licencja IMGW-PIB: Źródłem pochodzenia danych")


# Performance ------------------------------------------------------------------

PERF_DAYS = 27393
PERF_RUNS = 30
PERF_MS = 500.0


class _Values:
    """A stand-in producer with a long daily series of one station."""

    def __init__(self, values: list[SeriesValues]) -> None:
        self.values = values

    def read_values(self, *args: object, **kwargs: object) -> Iterator[SeriesValues]:
        return iter(self.values)

    def characteristics_dataset(self, dataset: str) -> str | None:
        return None

    def extremes_of(self, dataset: str, variable: str) -> dict[Extreme, str]:
        return {}


@pytest.mark.perf
def test_a_chart_of_27393_days_within_500_ms() -> None:
    """75 hydrological years of Q at 2,000 points, from the values to the answer."""
    # Arrange
    first = date(1950, 11, 1)
    values = [
        SeriesValues(
            start=first + timedelta(days=n),
            period=None,
            values={"Q": None if n % 97 == 0 else float(n % 400)},
        )
        for n in range(PERF_DAYS)
    ]
    gaps = tuple(
        (first + timedelta(days=n), first + timedelta(days=n))
        for n in range(0, PERF_DAYS, 97)
    )
    label = SeriesLabel(state="gaps", year_type="hydrological", span=None)
    variable = CoverageVariable(
        key="Q", variable="Q", unit="m3/s", period=None, first=first,
        last=first + timedelta(days=PERF_DAYS - 1), accumulated=0, years=(),
        label=label, gaps=gaps,
    )  # fmt: skip
    series = StationCoverage(
        store=STORE, provider="IMGW-PIB", code=RABA, dataset=DAILY, kind="hydro",
        time_unit="day", year_type="hydrological", span=None, file="f.parquet",
        series="2026-08-31", series_version="series.json", variables=(variable,),
    )  # fmt: skip
    adapter = _Values(values)
    times: list[float] = []

    # Act
    for _ in range(PERF_RUNS):
        started = time.perf_counter()
        chart = station_chart(
            adapter,
            Path("store"),
            series,
            [variable],
            start=None,
            end=None,
            max_points=2000,
            characteristics=None,
            freshness={"stale": False, "stale_stores": []},
        )
        chart.model_dump_json()
        times.append((time.perf_counter() - started) * 1000)

    # Assert
    assert (chart.units, chart.interval, len(chart.variables[0].points)) == (
        PERF_DAYS,
        14,
        1957,
    )
    p95 = statistics.quantiles(times, n=20)[-1]
    median = statistics.median(times)
    print(f"chart of {PERF_DAYS} days: median {median:.1f} ms, p95 {p95:.1f} ms")
    assert p95 <= PERF_MS
