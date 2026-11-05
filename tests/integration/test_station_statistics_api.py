"""Charts of monthly series and of annual extremes, the route of the card (A-ADR-051).

``GET /stations/{code}/series`` over the index of a scanned copy of the
statistics store (``tests/fixtures/obserwator_statistics.py``: ``complete``
with IMGW-PIB's monthly series and half-year characteristics built by
Obserwator). A monthly series is drawn per variable from the minimum, mean
and maximum IMGW-PIB published for each month; ``resolution=annual`` gives
each hydrological year's maximum and minimum found in the half-year
characteristics: the greater of the winter and summer maxima, the lesser of
their minima, an incomplete year marked, a year without either half a gap.
``archiwista stations series`` prints the same, and the station's card names
the charts its series give. ``GET /stations/{code}/handoff`` (A-ADR-052) hands
a series to Hydrolog as ``nogat-handoff/1`` around ``hydrolog-series/1``, both
checked against their owners' schemas: the annual maxima of complete years, or
every day of a daily series as the chart reads it.
"""

import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from jsonschema import Draft202012Validator

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.local_server import local_paths
from tests.fixtures.obserwator_statistics import (
    HALF_YEAR,
    HALF_YEARS_ONLY,
    MONTHLY,
    RABA,
    WITHOUT_Q,
    monthly_value,
)

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"

type Params = dict[str, str | list[str]]


@dataclass(frozen=True)
class Served:
    """The API over the index of a scanned statistics store, and its command line."""

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
    statistics_store: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Serve the index of a copy of the statistics store after a full scan."""
    base = tmp_path_factory.mktemp("station-statistics")
    root = base / "store"
    shutil.copytree(statistics_store, root)
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
        yield Served(api.session(LOCAL_OWNER), paths)


def _extreme(
    value: float,
    start: str,
    end: str,
    occurrences: int,
    halves: list[str],
    partial: str | None = None,
) -> dict[str, Any]:
    return {
        "value": value,
        "start": start,
        "end": end,
        "occurrences": occurrences,
        "halves": halves,
        "partial": partial,
    }


def _months(first: date, count: int) -> list[date]:
    index = first.year * 12 + first.month - 1
    return [date((index + n) // 12, (index + n) % 12 + 1, 1) for n in range(count)]


def _published(code: str, quantity: str, month: date, statistic: int) -> float | None:
    """Return a month's statistic as the archive holds it; ``None`` when missing."""
    year = month.year + 1 if month.month >= 11 else month.year
    hydrological = month.month - 10 if month.month >= 11 else month.month + 2
    text = monthly_value(code, quantity, year, hydrological, statistic)
    return None if text in {"9999", "99999.999", "99.9"} else float(text)


# Annual chart ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "maximum", "minimum"),
    [
        pytest.param(
            2020,
            _extreme(223.0, "2020-03-02", "2020-03-02", 1, ["winter"]),
            _extreme(32.7, "2020-08-18", "2020-08-19", 2, ["summer"]),
            id="greater-winter-maximum-lesser-summer-minimum",
        ),
        pytest.param(2021, None, None, id="neither-half"),
        pytest.param(
            2022,
            _extreme(150.0, "2022-02-10", "2022-06-06", 3, ["winter", "summer"]),
            _extreme(20.0, "2021-12-01", "2021-12-01", 1, ["winter"]),
            id="equal-halves-joined",
        ),
        pytest.param(
            2023,
            _extreme(180.0, "2023-03-01", "2023-03-01", 1, ["winter"], "summer"),
            _extreme(25.0, "2023-01-01", "2023-01-01", 1, ["winter"], "summer"),
            id="summer-missing-day-unpublished",
        ),
        pytest.param(
            2024,
            _extreme(90.0, "2024-07-09", "2024-07-09", 1, ["summer"], "winter"),
            _extreme(10.0, "2024-09-09", "2024-09-09", 1, ["summer"], "winter"),
            id="winter-absent",
        ),
    ],
)
def test_station_chart_annual_finds_each_years_maximum_and_minimum_in_its_halves(
    served: Served,
    year: int,
    maximum: dict[str, Any] | None,
    minimum: dict[str, Any] | None,
) -> None:
    """The greater maximum and lesser minimum of the halves, with their half's facts."""
    # Act
    chart = served.json(
        f"/stations/{RABA}/series", {"resolution": "annual", "variable": "Q"}
    )

    # Assert
    (variable,) = chart["variables"]
    points = {point["year"]: point for point in variable["points"]}
    assert points[year] == {
        "t": f"{year - 1}-11-01",
        "year": year,
        "max": maximum,
        "min": minimum,
    }


def test_station_chart_annual_marks_its_values_derived_in_hydrological_years(
    served: Served,
) -> None:
    """Every known year a point, the year without either half a gap, no marker."""
    # Arrange
    card = served.json(f"/stations/{RABA}", {"dataset": HALF_YEAR})
    (series,) = card["station"]["series"]

    # Act
    chart = served.json(
        f"/stations/{RABA}/series", {"resolution": "annual", "variable": "Q"}
    )

    # Assert
    assert (chart["resolution"], chart["derived"]) == ("annual", "annual_extremes")
    assert (chart["dataset"], chart["time_unit"], chart["year_type"]) == (
        HALF_YEAR,
        "half_year",
        "hydrological",
    )
    assert (chart["from"], chart["to"], chart["units"], chart["interval"]) == (
        "2019-11-01",
        "2024-10-31",
        5,
        1,
    )
    assert (chart["series_version"], chart["file"], chart["sha256"]) == (
        series["series_version"],
        series["file"],
        series["sha256"],
    )
    (variable,) = chart["variables"]
    assert [point["year"] for point in variable["points"]] == [
        2020,
        2021,
        2022,
        2023,
        2024,
    ]
    assert variable["gaps"] == [{"from": "2020-11-01", "to": "2021-10-31", "units": 1}]
    assert (variable["key"], variable["unit"], variable["markers"]) == ("Q", "m3/s", [])


def test_station_chart_annual_takes_by_default_each_variable_with_a_value(
    served: Served,
) -> None:
    """H and Q of Raba Górna; its T has no value, and a range keeps its years."""
    # Act
    chart = served.json(f"/stations/{RABA}/series", {"resolution": "annual"})
    ranged = served.json(
        f"/stations/{RABA}/series",
        {"resolution": "annual", "from": "2021-03-01", "to": "2022-11-15"},
    )

    # Assert
    assert [variable["key"] for variable in chart["variables"]] == ["H", "Q"]
    (height, _) = chart["variables"]
    assert height["points"][0]["max"] == _extreme(
        250.0, "2020-07-01", "2020-07-01", 1, ["summer"]
    )
    assert (ranged["from"], ranged["to"], ranged["units"]) == (
        "2020-11-01",
        "2023-10-31",
        3,
    )
    assert [p["year"] for p in ranged["variables"][1]["points"]] == [2021, 2022, 2023]


@pytest.mark.parametrize(
    ("code", "params", "status", "reason"),
    [
        pytest.param(
            RABA,
            {"resolution": "annual", "year_type": "calendar"},
            400,
            "annual_year_type",
            id="calendar-years",
        ),
        pytest.param(
            WITHOUT_Q,
            {"resolution": "annual"},
            400,
            "no_annual_source",
            id="no-half-years",
        ),
        pytest.param(
            RABA,
            {"resolution": "annual", "dataset": DAILY},
            400,
            "no_annual_source",
            id="daily-dataset",
        ),
        pytest.param(
            RABA,
            {"resolution": "annual", "variable": "P"},
            400,
            "unknown_variable",
            id="unknown-variable",
        ),
        pytest.param(
            RABA,
            {"dataset": HALF_YEAR, "variable": "Q"},
            400,
            "half_year_chart",
            id="half-years-at-their-units",
        ),
        pytest.param(
            RABA,
            {"dataset": MONTHLY, "variable": "Q_max"},
            400,
            "unknown_variable",
            id="monthly-column",
        ),
    ],
)
def test_station_chart_refuses_what_it_does_not_draw(
    served: Served, code: str, params: Params, status: int, reason: str
) -> None:
    """Calendar years, no half-year characteristics, a column instead of a variable."""
    # Act
    response = served.get(f"/stations/{code}/series", params)

    # Assert
    assert_problem(response, status, "validation_error", reason)


def test_station_chart_refusal_of_half_years_names_the_annual_chart(
    served: Served,
) -> None:
    """``half_year_chart`` hints at the annual chart; a column lists the variables."""
    # Act
    refused = served.get(
        f"/stations/{RABA}/series", {"dataset": HALF_YEAR, "variable": "Q"}
    ).json()
    column = served.get(
        f"/stations/{RABA}/series", {"dataset": MONTHLY, "variable": "Q_max"}
    ).json()

    # Assert
    assert "resolution=annual" in refused["hint"]
    assert column["details"]["allowed"] == ["H", "Q", "T"]


# Monthly chart -----------------------------------------------------------------


def test_station_chart_monthly_gives_each_months_published_minimum_mean_and_maximum(
    served: Served,
) -> None:
    """Q of Raba Górna, 24 months; March 2024 has no value and is the label's gap."""
    # Arrange
    months = _months(date(2022, 11, 1), 24)

    # Act
    chart = served.json(
        f"/stations/{RABA}/series", {"dataset": MONTHLY, "variable": "Q"}
    )

    # Assert
    assert (chart["resolution"], chart["derived"], chart["time_unit"]) == (
        "unit",
        None,
        "month",
    )
    assert (chart["from"], chart["to"], chart["units"], chart["interval"]) == (
        "2022-11-01",
        "2024-10-31",
        24,
        1,
    )
    (variable,) = chart["variables"]
    assert (variable["key"], variable["variable"], variable["unit"]) == (
        "Q",
        "Q",
        "m3/s",
    )
    assert variable["points"] == [
        {
            "t": month.isoformat(),
            "min": _published(RABA, "Q", month, 1),
            "mean": _published(RABA, "Q", month, 2),
            "max": _published(RABA, "Q", month, 3),
        }
        for month in months
    ]
    assert variable["gaps"] == [{"from": "2024-03-01", "to": "2024-03-31", "units": 1}]
    assert variable["markers"] == []


def test_station_chart_monthly_simplified_takes_the_least_minimum_and_greatest_maximum(
    served: Served,
) -> None:
    """``max_points=5`` over 24 months: intervals of 5 months, means of the means."""
    # Arrange
    months = _months(date(2022, 11, 1), 24)

    # Act
    chart = served.json(
        f"/stations/{RABA}/series",
        {"dataset": MONTHLY, "variable": "Q", "max_points": "5"},
    )

    # Assert
    assert (chart["units"], chart["interval"]) == (24, 5)
    expected = []
    for start in range(0, 24, 5):
        held = months[start : start + 5]
        least = [v for m in held if (v := _published(RABA, "Q", m, 1)) is not None]
        means = [v for m in held if (v := _published(RABA, "Q", m, 2)) is not None]
        most = [v for m in held if (v := _published(RABA, "Q", m, 3)) is not None]
        expected.append(
            {
                "t": held[0].isoformat(),
                "min": min(least),
                "mean": round(sum(means) / len(means), 6),
                "max": max(most),
            }
        )
    (variable,) = chart["variables"]
    assert variable["points"] == expected
    assert variable["gaps"] == [{"from": "2024-03-01", "to": "2024-03-31", "units": 1}]


def test_station_chart_without_dataset_prefers_the_daily_series(served: Served) -> None:
    """H of Raba Górna is daily and monthly: the daily series is drawn."""
    # Act
    chart = served.json(f"/stations/{RABA}/series", {"variable": "H"})

    # Assert
    assert (chart["dataset"], chart["time_unit"]) == (DAILY, "day")


# The card and the command line ---------------------------------------------------


@pytest.mark.parametrize(
    ("code", "charts"),
    [
        pytest.param(
            RABA,
            [
                (DAILY, "day", "unit", ["H", "Q", "T"]),
                (MONTHLY, "month", "unit", ["H", "Q", "T"]),
                (HALF_YEAR, "half_year", "annual", ["H", "Q"]),
            ],
            id="days-months-and-half-years",
        ),
        pytest.param(
            WITHOUT_Q,
            [
                (DAILY, "day", "unit", ["H", "Q", "T"]),
                (MONTHLY, "month", "unit", ["H", "T"]),
            ],
            id="monthly-without-q",
        ),
        pytest.param(
            HALF_YEARS_ONLY,
            [(HALF_YEAR, "half_year", "annual", ["Q"])],
            id="half-years-only",
        ),
    ],
)
def test_station_card_names_the_charts_of_its_series(
    served: Served, code: str, charts: list[tuple[str, str, str, list[str]]]
) -> None:
    """Days first, then months, then the annual chart; statistics with a value only."""
    # Act
    card = served.json(f"/stations/{code}")

    # Assert
    assert [
        (
            chart["dataset"],
            chart["time_unit"],
            chart["resolution"],
            [variable["key"] for variable in chart["variables"]],
        )
        for chart in card["charts"]
    ] == charts


def test_station_card_gives_the_days_each_chart_variable_spans(served: Served) -> None:
    """Monthly Q: 1 XI 2022 to 31 X 2024; annual Q: its hydrological years 2020-2024."""
    # Act
    card = served.json(f"/stations/{RABA}")

    # Assert
    spans = {
        (chart["dataset"], variable["key"]): (variable["first"], variable["last"])
        for chart in card["charts"]
        for variable in chart["variables"]
    }
    assert spans[(MONTHLY, "Q")] == ("2022-11-01", "2024-10-31")
    assert spans[(HALF_YEAR, "Q")] == ("2019-11-01", "2024-10-31")


@pytest.mark.parametrize(
    "argv",
    [
        ["--resolution=annual"],
        ["--resolution=annual", "--variable=Q", "--from=2021-01-01", "--to=2023-12-31"],
        [f"--dataset={MONTHLY}", "--variable=Q", "--variable=H", "--max-points=5"],
    ],
)
def test_station_chart_route_and_command_line_give_the_same_chart(
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


def test_station_chart_command_line_refuses_calendar_years_as_the_route_does(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """``annual_year_type``: the same problem and the exit code 2."""
    # Act
    params: Params = {"resolution": "annual", "year_type": "calendar"}
    problem = served.get(f"/stations/{RABA}/series", params).json()
    capsys.readouterr()
    status = main(
        ["stations", "series", RABA, "--resolution=annual", "--year-type=calendar"],
        paths=served.paths,
    )
    captured = capsys.readouterr()

    # Assert
    document = refusal(captured.out, captured.err, status)
    assert_same_error(document, problem)
    assert document["exit_code"] == 2


def test_station_chart_command_line_writes_each_year_for_a_person(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each year's maximum and minimum with their days, halves and occurrences."""
    # Act
    capsys.readouterr()
    status = main(
        ["stations", "series", RABA, "--resolution=annual", "--variable=Q"],
        paths=served.paths,
    )
    lines = capsys.readouterr().out.splitlines()

    # Assert
    assert status == 0
    assert lines[0].startswith(f"{RABA}: szereg {HALF_YEAR}, wersja ")
    assert lines[1:10] == [
        "Roczne maksimum i minimum wyznaczone przez Archiwistę z charakterystyk"
        " półrocznych IMGW-PIB: lata hydrologiczne 2020–2024 (5 lat)",
        "  Q (m3/s): 4 z 5 lat z wartością, luki: 1",
        "    2020: maks. 223.0 (2020-03-02, półrocze zimowe); min. 32.7"
        " (2020-08-18 – 2020-08-19, półrocze letnie, 2 wystąpienia)",
        "    2021: brak wartości",
        "    2022: maks. 150.0 (2022-02-10 – 2022-06-06, oba półrocza, 3 wystąpienia);"
        " min. 20.0 (2021-12-01, półrocze zimowe)",
        "    2023: maks. 180.0 (2023-03-01, półrocze zimowe, niepełny rok: brak"
        " półrocza letniego); min. 25.0 (2023-01-01, półrocze zimowe, niepełny"
        " rok: brak półrocza letniego)",
        "    2024: maks. 90.0 (2024-07-09, półrocze letnie, niepełny rok: brak"
        " półrocza zimowego); min. 10.0 (2024-09-09, półrocze letnie, niepełny"
        " rok: brak półrocza zimowego)",
        "    luka 2020-11-01 – 2021-10-31 (1 rok)",
        lines[9],
    ]
    assert lines[9].startswith("  Licencja IMGW-PIB: Źródłem pochodzenia danych")


# Hand-off to Hydrolog (A-ADR-052) ---------------------------------------------------

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
HANDOFF_CHECK = Draft202012Validator(
    json.loads((SCHEMAS / "nogat" / "handoff-1.schema.json").read_text("utf-8"))
)
SERIES_CHECK = Draft202012Validator(
    json.loads(
        (SCHEMAS / "hydrolog" / "hydrolog-series-1.schema.json").read_text("utf-8")
    )
)


def _valid(doc: dict[str, Any]) -> None:
    """Check the envelope against Nogat's schema and the payload against Hydrolog's."""
    assert [error.message for error in HANDOFF_CHECK.iter_errors(doc)] == []
    assert [error.message for error in SERIES_CHECK.iter_errors(doc["payload"])] == []


def test_station_handoff_annual_gives_the_maxima_of_complete_years_only(
    served: Served,
) -> None:
    """A year missing a half is no annual maximum for a flood frequency analysis."""
    # Act
    doc = served.json(
        f"/stations/{RABA}/handoff", {"resolution": "annual", "variable": "Q"}
    )

    # Assert
    _valid(doc)
    payload = doc["payload"]
    assert (payload["step"], payload["statistic"], payload["year_type"]) == (
        "year",
        "max",
        "hydrological",
    )
    assert dict(zip(payload["years"], payload["values"], strict=True)) == {
        2020: 223.0,
        2021: None,
        2022: 150.0,
        2023: None,
        2024: None,
    }
    origin = doc["provenance"]["series"]
    assert (origin["dataset"], origin["station"], origin["left_out"]) == (
        HALF_YEAR,
        RABA,
        [2023, 2024],
    )
    assert doc["subject"].endswith("— Q, maksima roczne")


def test_station_handoff_daily_gives_every_day_of_the_range_as_the_chart_reads_it(
    served: Served,
) -> None:
    """The values of each day, ``null`` without one, the chart's values unsimplified."""
    # Arrange
    whole = served.json(f"/stations/{RABA}/series", {"variable": "Q", "dataset": DAILY})
    (variable,) = whole["variables"]
    valued = next(point for point in variable["points"] if point["mean"] is not None)
    first = date.fromisoformat(valued["t"]) - timedelta(days=5)
    span = {"from": first.isoformat(), "to": (first + timedelta(days=59)).isoformat()}

    # Act
    doc = served.json(
        f"/stations/{RABA}/handoff", {"variable": "Q", "dataset": DAILY, **span}
    )
    chart = served.json(
        f"/stations/{RABA}/series",
        {"variable": "Q", "dataset": DAILY, "max_points": "2000", **span},
    )

    # Assert
    _valid(doc)
    payload = doc["payload"]
    assert payload["dates"] == [
        (first + timedelta(days=offset)).isoformat() for offset in range(60)
    ]
    assert payload["values"] == [
        point["mean"] for point in chart["variables"][0]["points"]
    ]
    assert any(value is not None for value in payload["values"])
    assert doc["provenance"]["series"]["dataset"] == DAILY


def test_station_handoff_refuses_a_monthly_series(served: Served) -> None:
    """Hydrolog takes daily values or annual maxima: ``no_daily_series``."""
    # Act
    response = served.get(
        f"/stations/{RABA}/handoff", {"variable": "Q", "dataset": MONTHLY}
    )

    # Assert
    assert_problem(response, 400, "validation_error")
    assert response.json()["details"]["reason"] == "no_daily_series"


def test_station_handoff_route_and_command_line_give_the_same_document(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista stations handoff CODE`` prints the route's document."""
    # Act
    capsys.readouterr()
    status = main(
        ["stations", "handoff", RABA, "--variable=Q", "--resolution=annual"],
        paths=served.paths,
    )
    from_cli = json.loads(capsys.readouterr().out)
    route = served.json(
        f"/stations/{RABA}/handoff", {"resolution": "annual", "variable": "Q"}
    )

    # Assert
    assert status == 0
    assert {**from_cli, "created_at": None} == {**route, "created_at": None}
