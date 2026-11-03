"""Stations compared over one range, the route of the comparison (plan I8.6).

``GET /stations/compare`` reads one variable of 2 to 5 stations' current
series of one dataset through the producer over the index of a scanned copy
of ``complete_pl_cz`` (``imgwtools.testing``: ``complete`` and the ČHMÚ
gauges): one range for all, by default the variable's known spans together
(ADR-045 erratum 1), one interval, each station's chart its own over that
range and its facts those of its card; a station without the series or the
variable stays, without them. ``archiwista stations compare`` prints the same.
"""

import json
import shutil
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.local_server import local_paths

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"
CZ_DAILY = "cz.chmi.hydro_daily"
RABA = "149190310"
NO_Q = "149190311"  # no position, Q without a value
UNSERIED = "149190312"  # no series at all
RAINFALL = "123750000"  # a precipitation series only
SPINDLER = "0-203-1-900001"  # values 2023-01-01 to 2024-12-31
ZAPADLA = "0-203-1-900002"  # values 2004 to 2006, no known year
# The facts of a compared station that its card gives too.
_CARD_FIELDS = (
    "store", "provider", "code", "name", "kind", "river", "hydrographic_code",
    "location",
)  # fmt: skip
_SERIES_FIELDS = (
    "series",
    "series_version",
    "file",
    "sha256",
    "license",
    "attribution",
)

type Stores = Callable[[str], Path]
type Params = dict[str, str | list[str]]


def imgw(code: str) -> str:
    """Return the address of an IMGW-PIB station of the store."""
    return f"{STORE}/IMGW-PIB/{code}"


def chmi(code: str) -> str:
    """Return the address of a ČHMÚ station of the store."""
    return f"{STORE}/CHMI/{code}"


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
    base = tmp_path_factory.mktemp("station-compare")
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


def _compare(served: Served, stations: Sequence[str], **params: str) -> Any:
    return served.json("/stations/compare", {"station": list(stations), **params})


def _chart(served: Served, station: str, **params: str) -> Any:
    """Return the chart of one variable of a station (``/stations/{code}/series``)."""
    store, provider, code = station.split("/")
    return served.json(
        f"/stations/{code}/series", {"store": store, "provider": provider, **params}
    )


@pytest.mark.parametrize(
    ("stations", "dataset", "variable", "year_type", "span", "interval"),
    [
        pytest.param(
            [imgw(RABA), imgw(NO_Q)],
            DAILY,
            "H",
            "hydrological",
            ("2023-11-01", "2024-10-31"),
            1,
            id="imgw-H",
        ),
        pytest.param(
            [chmi(SPINDLER), chmi(ZAPADLA)],
            CZ_DAILY,
            "H",
            "hydrological",
            ("2004-01-01", "2024-12-31"),
            4,
            id="chmi-H-two-spans",
        ),
        pytest.param(
            [chmi(ZAPADLA), chmi(SPINDLER)],
            CZ_DAILY,
            "T",
            "calendar",
            ("2004-01-01", "2024-12-31"),
            4,
            id="chmi-T-calendar",
        ),
    ],
)
def test_the_stations_share_one_range_and_interval(
    served: Served,
    stations: list[str],
    dataset: str,
    variable: str,
    year_type: str,
    span: tuple[str, str],
    interval: int,
) -> None:
    """The range joins the charts' default ranges; each chart is its own in it."""
    # Arrange
    asked = {"dataset": dataset, "variable": variable, "year_type": year_type}
    own = [_chart(served, station, **asked) for station in stations]

    # Act
    answer = _compare(served, stations, **asked)

    # Assert
    assert (answer["from"], answer["to"], answer["interval"]) == (*span, interval)
    assert span == (
        min(chart["from"] for chart in own if chart["from"] is not None),
        max(chart["to"] for chart in own if chart["to"] is not None),
    )
    assert answer["year_type"] == year_type
    assert [item["code"] for item in answer["stations"]] == [
        station.rsplit("/", 1)[1] for station in stations
    ]
    for station, item in zip(stations, answer["stations"], strict=True):
        ranged = _chart(served, station, **asked, **{"from": span[0], "to": span[1]})
        assert (ranged["from"], ranged["to"], ranged["interval"]) == (*span, interval)
        assert item["chart"] == ranged["variables"][0], station


@pytest.mark.parametrize(
    ("stations", "dataset", "variable", "year_type"),
    [
        ([imgw(RABA), imgw(NO_Q)], DAILY, "Q", None),
        ([chmi(SPINDLER), chmi(ZAPADLA)], CZ_DAILY, "T", "calendar"),
    ],
)
def test_the_facts_of_each_station_are_those_of_its_card(
    served: Served,
    stations: list[str],
    dataset: str,
    variable: str,
    year_type: str | None,
) -> None:
    """Label, years, gaps, location and series version as the card gives them."""
    # Arrange
    asked = {"dataset": dataset} | (
        {} if year_type is None else {"year_type": year_type}
    )

    # Act
    answer = _compare(served, stations, variable=variable, **asked)

    # Assert
    for station, item in zip(stations, answer["stations"], strict=True):
        store, provider, code = station.split("/")
        card = served.json(
            f"/stations/{code}", {"store": store, "provider": provider, **asked}
        )["station"]
        (series,) = card["series"]
        assert answer["year_type"] == series["year_type"]
        assert item["coverage"] == series["coverage"][variable], station
        assert item["years"] == series["years"]
        assert {key: item[key] for key in _CARD_FIELDS} == {
            key: card[key] for key in _CARD_FIELDS
        }
        assert {key: item[key] for key in _SERIES_FIELDS} == {
            key: series[key] for key in _SERIES_FIELDS
        }


def test_a_station_without_the_series_stays_without_data(served: Served) -> None:
    """A station without a series of the dataset keeps its place, with ``null``."""
    # Act
    answer = _compare(
        served,
        [imgw(UNSERIED), imgw(RABA), imgw(RAINFALL)],
        dataset=DAILY,
        variable="H",
    )

    # Assert
    unseried, raba, rainfall = answer["stations"]
    assert raba["coverage"]["state"] == "gaps"
    assert len(raba["chart"]["gaps"]) == 4
    for item, name in ((unseried, "Stacja Bez Miejsca"), (rainfall, "Warszawa")):
        assert item["name"] == name
        assert [item[key] for key in ("years", "series", "coverage", "chart")] == [
            None
        ] * 4
    assert (answer["from"], answer["to"]) == ("2023-11-01", "2024-10-31")


def test_a_bound_beyond_the_others_default_leaves_an_empty_comparison(
    served: Served,
) -> None:
    """``from`` after the last known day: no unit, no series read, facts kept."""
    # Act
    answer = _compare(
        served,
        [imgw(RABA), imgw(NO_Q)],
        dataset=DAILY,
        variable="H",
        **{"from": "2030-01-01"},
    )

    # Assert
    assert (answer["from"], answer["to"], answer["units"]) == (None, None, 0)
    for item in answer["stations"]:
        assert item["coverage"]["state"] == "gaps"
        chart = item["chart"]
        assert (chart["points"], chart["gaps"], chart["markers"]) == ([], [], [])


@pytest.mark.parametrize(
    ("params", "status", "code", "reason"),
    [
        ({"station": [imgw(RABA)]}, 400, "validation_error", None),
        (
            {"station": [imgw(f"14919031{n}") for n in range(6)]},
            400,
            "validation_error",
            None,
        ),
        ({"station": [RABA, imgw(NO_Q)]}, 400, "validation_error", None),
        ({"station": [imgw(RABA), imgw(RABA)]}, 400, "validation_error", None),
        (
            {"station": [imgw(RABA), imgw(NO_Q)], "variable": "P"},
            400,
            "validation_error",
            "unknown_variable",
        ),
        (
            {
                "station": [imgw(RABA), imgw(NO_Q)],
                "from": "2024-02-01",
                "to": "2024-01-01",
            },
            400,
            "validation_error",
            None,
        ),
        (
            {"station": [imgw(RABA), imgw(NO_Q)], "max_points": "2001"},
            400,
            "validation_error",
            None,
        ),
        ({"station": [imgw(UNSERIED), imgw(RAINFALL)]}, 404, "not_found", None),
        ({"station": [imgw(RABA), imgw("000000000")]}, 404, "not_found", None),
    ],
)
def test_refusals(
    served: Served, params: Params, status: int, code: str, reason: str | None
) -> None:
    """One or six stations, a bad or repeated address, a variable none has."""
    # Act
    response = served.get(
        "/stations/compare", {"dataset": DAILY, "variable": "H", **params}
    )

    # Assert
    assert_problem(response, status, code, reason)


@pytest.mark.parametrize(
    "argv",
    [
        [f"--station={imgw(RABA)}", f"--station={imgw(NO_Q)}", "--variable=H"],
        [
            f"--station={chmi(SPINDLER)}",
            f"--station={chmi(ZAPADLA)}",
            "--variable=T",
            "--year-type=calendar",
            "--max-points=30",
            "--from=2023-06-01",
        ],
    ],
)
def test_the_route_and_the_command_line_give_the_same_comparison(
    served: Served, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    """``archiwista stations compare --json`` prints the route's answer."""
    # Arrange
    dataset = CZ_DAILY if "CHMI" in argv[0] else DAILY
    params: dict[str, list[str]] = {"dataset": [dataset]}
    for option in argv:
        name, _, value = option.removeprefix("--").partition("=")
        params.setdefault(name.replace("-", "_"), []).append(value)

    # Act
    capsys.readouterr()
    status = main(
        ["stations", "compare", f"--dataset={dataset}", *argv, "--json"],
        paths=served.paths,
    )
    from_cli = json.loads(capsys.readouterr().out)

    # Assert
    assert status == 0
    assert from_cli == served.json("/stations/compare", dict(params))


def test_the_command_line_refuses_as_the_route_does(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """A variable no station has: the same problem and the exit code 2."""
    # Arrange
    stations = [imgw(RABA), imgw(NO_Q)]

    # Act
    problem = served.get(
        "/stations/compare", {"station": stations, "dataset": DAILY, "variable": "P"}
    ).json()
    capsys.readouterr()
    status = main(
        [
            "stations",
            "compare",
            *(f"--station={station}" for station in stations),
            f"--dataset={DAILY}",
            "--variable=P",
        ],
        paths=served.paths,
    )
    captured = capsys.readouterr()

    # Assert
    document = refusal(captured.out, captured.err, status)
    assert_same_error(document, problem)
    assert document["exit_code"] == 2


def test_the_command_line_writes_the_comparison_for_a_person(
    served: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """The range once, each station with its label, chart and gaps, the licence."""
    # Act
    capsys.readouterr()
    status = main(
        [
            "stations",
            "compare",
            f"--station={imgw(RABA)}",
            f"--station={imgw(UNSERIED)}",
            f"--station={imgw(NO_Q)}",
            f"--dataset={DAILY}",
            "--variable=H",
        ],
        paths=served.paths,
    )
    lines = capsys.readouterr().out.splitlines()

    # Assert
    assert status == 0
    assert lines[:2] == [
        f"Porównanie H z {DAILY}, lata hydrologiczne",
        "Zakres 2023-11-01 – 2024-10-31 (366 dni): wartość każdej jednostki",
    ]
    assert lines[2].startswith(f"{RABA}  Raba Górna · hydro · IMGW-PIB")
    assert lines[3].startswith("  H (cm): luki 91% · najdł. 2024.03.01–2024.10.31")
    assert lines[4] == "  H (cm): 2 z 366 punktów z wartością, luki: 4, znaczniki: 0"
    assert lines[9].startswith(f"{UNSERIED}  Stacja Bez Miejsca")
    assert lines[10] == f"  brak danych: brak zmiennej H w szeregu {DAILY}"
    assert lines[11].startswith(f"{NO_Q}  Stacja Bez Q")
    assert lines[14] == "    luka 2023-11-02 – 2024-10-31 (365 dni)"
    (licence,) = [line for line in lines if line.startswith("  Licencja")]
    assert licence == lines[-1]
