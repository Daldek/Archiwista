"""``archiwista stations`` next to the station routes (plan I6, AGENT_API).

``stations list`` and ``stations show`` with ``--json`` print exactly what
``GET /stations`` and ``GET /stations/{code}`` answer over the same index (a
scanned copy of ``complete_pl_cz``), refusals included: the options are the
routes' parameters by name, a repeatable parameter a repeatable option.
Without ``--json`` a person reads Polish lines.
"""

import argparse
import json
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.commands import stations
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import AreaRecord, IndexWriter, initialize, scan_store
from archiwista.sources.registry import PluginRegistry, load_registry
from tests.fixtures.api_session import Caller, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.local_server import NoSources, local_paths

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"
RABA = "149190310"
AREA = AreaRecord(
    id="zlewnia",
    source="drawn",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [[20.12, 49.6], [20.4, 49.6], [20.4, 49.8], [20.12, 49.8], [20.12, 49.6]]
        ],
    },
    created_at=datetime(2026, 10, 26, tzinfo=UTC),
)

type Stores = Callable[[str], Path]
type Params = dict[str, str | list[str]]


class Doors:
    """The same index through the command line and through HTTP."""

    def __init__(
        self, paths: AppPaths, owner: Caller, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.paths = paths
        self.owner = owner
        self._capsys = capsys

    def cli(self, *argv: str) -> Any:
        """Return what ``archiwista … --json`` printed; it must succeed."""
        self._capsys.readouterr()
        assert main([*argv, "--json"], paths=self.paths) == 0
        return json.loads(self._capsys.readouterr().out)

    def text(self, *argv: str) -> str:
        """Return what ``archiwista …`` printed for a person; it must succeed."""
        self._capsys.readouterr()
        assert main(list(argv), paths=self.paths) == 0
        return self._capsys.readouterr().out

    def refused(
        self, *argv: str, registry: PluginRegistry | None = None
    ) -> dict[str, Any]:
        """Return the error document of a refused ``archiwista … --json``."""
        self._capsys.readouterr()
        status = main([*argv, "--json"], paths=self.paths, registry=registry)
        captured = self._capsys.readouterr()
        return refusal(captured.out, captured.err, status)

    def http(self, path: str) -> Any:
        """Return the body of ``GET path`` under ``/api/v1``."""
        return self.owner.request("GET", path).json()


@pytest.fixture(scope="module")
def served(
    imgw_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[AppPaths, Caller]]:
    """Serve the index of a copy of ``complete_pl_cz`` after a full scan."""
    base = tmp_path_factory.mktemp("stations-cli")
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
        writer.write_area(AREA)
        scan_store(registry.adapter("imgw"), writer, settings, STORE, mode="full")
    with running_api(paths, registry) as api:
        yield paths, api.session(LOCAL_OWNER)


@pytest.fixture
def doors(served: tuple[AppPaths, Caller], capsys: pytest.CaptureFixture[str]) -> Doors:
    """Return the command line and HTTP over the served index."""
    paths, owner = served
    return Doors(paths, owner, capsys)


def _options(params: Params) -> list[str]:
    """Return the options of route parameters, a list as a repeated option."""
    options: list[str] = []
    for name, value in params.items():
        for item in value if isinstance(value, list) else [value]:
            options.append(f"--{name.replace('_', '-')}={item}")
    return options


@pytest.mark.parametrize(
    ("params", "rows"),
    [
        ({}, 13),
        ({"dataset": DAILY}, 2),
        ({"limit": "4"}, 13),
        ({"area_id": AREA.id}, 1),
        ({"area_id": AREA.id, "boundary": "false"}, 0),
        ({"bbox": "20.12,49.6,20.4,49.8", "location": "none"}, 5),
        ({"dataset": DAILY, "coverage": ["Q:gaps", "Q:no_data"]}, 2),
        ({"dataset": DAILY, "min_complete_years": ["H:1"], "years": "2024"}, 0),
        ({"variable": ["Q", "T"], "year_type": "calendar"}, 2),
        ({"provider": "CHMI", "river_code": "1-05", "river_scope": "tributaries"}, 1),
        ({"kind": "meteo", "active": "true", "location": "with"}, 3),
    ],
)
def test_stations_list_json_equals_the_route_page_after_page(
    doors: Doors, params: Params, rows: int
) -> None:
    """Every page of a query, followed by its cursor, is the same on both doors."""
    # Arrange
    pairs: list[tuple[Any, Any]] = []
    cursor: Params = {}

    # Act
    while len(pairs) < 10:
        query = {**params, **cursor}
        pair = (
            doors.cli("stations", "list", *_options(query)),
            doors.http(f"/stations?{urlencode(query, doseq=True)}"),
        )
        pairs.append(pair)
        if pair[1]["next_cursor"] is None:
            break
        cursor = {"cursor": pair[1]["next_cursor"]}

    # Assert
    assert pairs[-1][1]["next_cursor"] is None
    for from_cli, from_http in pairs:
        assert from_cli == from_http
    assert sum(len(page["items"]) for _, page in pairs) == rows


@pytest.mark.parametrize(
    ("code", "params"),
    [
        (RABA, {}),
        (RABA, {"dataset": DAILY, "years": "2020-2024", "year_type": "calendar"}),
        ("0-203-1-900001", {"provider": "CHMI", "store": STORE}),
        ("0-20000-0-99903", {}),
    ],
)
def test_stations_show_json_equals_the_card(
    doors: Doors, code: str, params: Params
) -> None:
    """The card of a station is the same through either door."""
    # Act
    shown = doors.cli("stations", "show", code, *_options(params))
    card = doors.http(f"/stations/{code}?{urlencode(params)}")

    # Assert
    assert shown == card
    assert shown["station"]["code"] == code


def test_stations_options_are_the_parameters_of_the_routes(doors: Doors) -> None:
    """One option per parameter, of its name; the code of ``show`` is positional."""
    # Arrange
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command")
    stations.add_commands(commands)
    (actions,) = (
        action
        for action in commands.choices["stations"]._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    choices: dict[str, argparse.ArgumentParser] = actions.choices
    document = doors.http("/openapi.json")

    def parameters(path: str) -> set[str]:
        operation = document["paths"][f"/api/v1{path}"]["get"]
        return {item["name"] for item in operation["parameters"]}

    def options(name: str) -> dict[str, list[str]]:
        return {
            action.dest: list(action.option_strings)
            for action in choices[name]._actions
            if action.dest not in {"help", "json", "verbose", "quiet"}
        }

    # Act
    listing = options("list")
    shown = options("show")

    # Assert
    assert set(listing) == parameters("/stations")
    assert set(shown) == parameters("/stations/{code}")
    assert shown.pop("code") == []  # the positional KOD
    for name, strings in [*listing.items(), *shown.items()]:
        assert strings == [f"--{name.replace('_', '-')}"]


@pytest.mark.parametrize(
    ("argv", "path", "exit_code"),
    [
        (
            ["stations", "list", "--coverage=Q:gaps"],
            "/stations?coverage=Q:gaps",
            2,
        ),
        (
            ["stations", "list", f"--dataset={DAILY}", "--coverage=Q:bad"],
            f"/stations?dataset={DAILY}&coverage=Q:bad",
            2,
        ),
        (
            ["stations", "list", "--years=2025-1951", f"--dataset={DAILY}"],
            f"/stations?years=2025-1951&dataset={DAILY}",
            2,
        ),
        (["stations", "list", "--limit=0"], "/stations?limit=0", 2),
        (["stations", "list", "--store=brak"], "/stations?store=brak", 2),
        (["stations", "list", "--area-id=brak"], "/stations?area_id=brak", 2),
        (["stations", "show", "000000000"], "/stations/000000000", 3),
        (
            ["stations", "show", RABA, "--years=19"],
            f"/stations/{RABA}?years=19",
            2,
        ),
    ],
)
def test_stations_cli_refuses_as_the_route_does(
    doors: Doors, argv: list[str], path: str, exit_code: int
) -> None:
    """The error document says what the problem says, with the registry's exit."""
    # Act
    document = doors.refused(*argv)
    problem = doors.http(path)

    # Assert
    assert_same_error(document, problem)
    assert document["exit_code"] == exit_code


def test_stations_cli_without_imgwtools_is_a_missing_dependency(
    doors: Doors, tmp_path: Path
) -> None:
    """The stations are not shown without their source, as the routes answer 503."""
    # Act
    listed = doors.refused("stations", "list", registry=NoSources())
    shown = doors.refused("stations", "show", RABA, registry=NoSources())
    with running_api(local_paths(tmp_path), NoSources()) as api:
        problem = api.session(LOCAL_OWNER).request("GET", "/stations").json()

    # Assert
    assert_same_error(listed, problem)
    assert (listed["code"], listed["exit_code"]) == ("missing_dependency", 6)
    assert shown == listed


def test_stations_cli_writes_polish_lines_for_a_person(doors: Doors) -> None:
    """Each station with its series' labels; the card with its facts and terms."""
    # Act
    listed = doors.text("stations", "list", f"--dataset={DAILY}")
    card = doors.text("stations", "show", RABA)
    unlocated = doors.text("stations", "show", "149190311")

    # Assert
    lines = listed.splitlines()
    assert lines[0] == (
        f"{RABA}  Raba Górna · hydro · IMGW-PIB · magazyn {STORE} · Raba (213)"
    )
    assert lines[1].startswith(
        f"  {DAILY} (szeregi 2026-10-19, lata hydrologiczne 1951–2024): H: luki 91%"
    )
    assert "bez położenia (źródło podało 0,0)" in lines[2]
    assert lines[-1] == (
        "Stacje na stronie: 2. Z położeniem: 1 (na granicy obszaru: 0), bez"
        " położenia: 1, ukryte filtrem: 0."
    )
    assert "czynna: tak" in card
    assert "Położenie: 20.1, 49.7 (źródło api_hydro, niepewność 5566.0 m" in card
    assert "  Licencja IMGW-PIB: Źródłem pochodzenia danych jest" in card
    assert "Bez położenia: źródło podało 0,0" in unlocated
