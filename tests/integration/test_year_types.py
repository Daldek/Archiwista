"""The year type remembered for hydro and meteo data (plan I8.2, P15, SPEC 6.7).

``PUT /settings/year-types`` changes only the two remembered types, logged as
``settings.update`` like a change of ``PUT /settings``; the
station routes and ``archiwista stations`` number the years by the type
remembered for the data's family when ``year_type`` is absent, a list of both
families by hydro's, and a given ``year_type`` wins without changing the
settings. Half-year characteristics stay hydrological. The index is a
scanned copy of ``complete`` (``imgwtools.testing``) with a synthetic
half-year series of Raba Górna, which the fixture stores lack.
"""

import json
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig, YearTypes
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources import SeriesListing, StationSeries, VariableCoverage
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import add_people, last_entry, log_entries, principal

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"
PRECIPITATION = "pl.imgw.meteo_precip_daily"
HALF_YEAR = "pl.imgw.hydro_semiannual"
RABA = "149190310"
DEFAULTS = {"hydro": "hydrological", "meteo": "calendar"}

type Stores = Callable[[str], Path]


@dataclass(frozen=True)
class Served:
    """The API over the scanned index: the owner, a person, and the paths."""

    owner: Caller
    other: Caller
    paths: AppPaths

    def json(self, path: str) -> Any:
        """Return the body of the owner's ``200`` answer of ``GET path``."""
        response = self.owner.request("GET", path)
        assert response.status_code == 200, response.text
        return response.json()

    def remember(
        self, *, caller: Caller | None = None, **year_types: str
    ) -> httpx.Response:
        """Send ``PUT /settings/year-types`` as ``caller`` (the owner by default)."""
        return (caller or self.owner).request(
            "PUT", "/settings/year-types", json=year_types
        )


def _half_years(writer: IndexWriter) -> None:
    """Write Raba Górna's winter Q_max of the hydrological years 2001 to 2004."""
    known = (date(2000, 11, 1), date(2004, 10, 31))
    winter = VariableCoverage(
        key="Q_max@winter",
        variable="Q_max",
        unit="m3/s",
        period="winter",
        first=known[0],
        last=known[1],
        with_value=0,
        accumulated=0,
        gaps=(),
    )
    folder = "series/versions/hydro_semiannual"
    writer.replace_series(
        STORE,
        "imgw",
        slot=folder,
        version=f"{folder}/2026-10-26_00000000/series.json",
        listing=SeriesListing(
            dataset=HALF_YEAR,
            provider="IMGW-PIB",
            kind="hydro",
            time_unit="half_year",
            year_type="hydrological",
            first_year=2001,
            periods=(known,),
            stations=(
                StationSeries(
                    code=RABA,
                    file=f"{folder}/2026-10-26_00000000/stations/{RABA}.parquet",
                    sha256="0" * 64,
                    rows=4,
                    variables=(winter,),
                ),
            ),
        ),
    )


@pytest.fixture(scope="module")
def served(
    imgw_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Serve the index of a copy of ``complete`` with the half-year series."""
    base = tmp_path_factory.mktemp("year-types")
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
        _half_years(writer)
    with running_api(paths, registry) as api:
        add_people(api.state)
        owner = api.session(LOCAL_OWNER)
        other = api.session(principal(api.state, "other"))
        yield Served(owner, other, paths)


@pytest.fixture
def api(served: Served) -> Iterator[Served]:
    """Return the served API; the defaults are remembered again after the test."""
    yield served
    assert served.remember(hydro="hydrological", meteo="calendar").status_code == 200


def _year_types(body: dict[str, Any]) -> set[str]:
    """Return the year types of every series of a page of stations."""
    return {series["year_type"] for item in body["items"] for series in item["series"]}


def test_the_remembered_meteo_type_numbers_a_meteo_dataset(api: Served) -> None:
    """Meteo in hydrological years until a request asks for calendar ones."""
    # Arrange
    listed = f"/stations?dataset={PRECIPITATION}"
    calendar = api.json(listed)

    # Act
    saved = api.remember(hydro="hydrological", meteo="hydrological")
    remembered = api.json(listed)
    asked = api.json(f"{listed}&year_type=calendar")
    hydrological = api.json(f"{listed}&year_type=hydrological")

    # Assert
    assert saved.status_code == 200, saved.text
    assert saved.json()["year_types"] == {
        "hydro": "hydrological",
        "meteo": "hydrological",
    }
    assert _year_types(calendar) == {"calendar"}
    assert remembered["items"] and remembered["items"] == hydrological["items"]
    assert _year_types(remembered) == {"hydrological"}
    assert asked["items"] == calendar["items"]
    assert api.json("/settings")["year_types"] == {
        "hydro": "hydrological",
        "meteo": "hydrological",
    }


def test_half_year_characteristics_stay_hydrological(api: Served) -> None:
    """Hydro data follow the calendar choice, their half-years do not."""
    # Act
    api.remember(hydro="calendar")
    daily = api.json(f"/stations?dataset={DAILY}")
    half_years = api.json(f"/stations?dataset={HALF_YEAR}")
    asked = api.json(f"/stations?dataset={HALF_YEAR}&year_type=calendar")
    card = api.json(f"/stations/{RABA}")["station"]
    datasets = {
        item["dataset"]: item for item in api.json("/stations/datasets")["items"]
    }

    # Assert
    assert _year_types(daily) == {"calendar"}
    assert _year_types(half_years) == _year_types(asked) == {"hydrological"}
    assert {series["dataset"]: series["year_type"] for series in card["series"]} == {
        DAILY: "calendar",
        HALF_YEAR: "hydrological",
    }
    assert datasets[DAILY]["year_type"] == "calendar"
    assert datasets[HALF_YEAR]["year_type"] == "hydrological"
    assert datasets[PRECIPITATION]["year_type"] == "calendar"


def test_a_list_of_both_families_takes_the_type_remembered_for_hydro(
    api: Served,
) -> None:
    """Without a dataset or kind meteo is numbered as hydro; with ``kind`` its own."""
    # Act
    api.remember(hydro="calendar", meteo="hydrological")
    mixed = api.json("/stations")
    meteo = api.json("/stations?kind=meteo")

    # Assert
    datasets = {
        series["dataset"]: series["year_type"]
        for item in mixed["items"]
        for series in item["series"]
        if series["dataset"] != HALF_YEAR
    }
    assert datasets == {DAILY: "calendar", PRECIPITATION: "calendar"}
    assert _year_types(meteo) == {"hydrological"}


def test_the_choice_is_kept_in_the_file_and_read_by_the_command_line(
    api: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """The file holds the choice; ``archiwista stations`` reads it like the route."""
    # Act
    api.remember(meteo="hydrological")
    stored = ConfigStore(api.paths.config_file).load()
    capsys.readouterr()
    status = main(
        ["stations", "list", f"--dataset={PRECIPITATION}", "--json"], paths=api.paths
    )
    printed = json.loads(capsys.readouterr().out)
    replaced = api.owner.request("PUT", "/settings", json=api.json("/settings"))

    # Assert
    assert stored.year_types == YearTypes(meteo="hydrological")
    assert status == 0
    assert printed == api.json(f"/stations?dataset={PRECIPITATION}")
    assert _year_types(printed) == {"hydrological"}
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["year_types"] == {
        "hydro": "hydrological",
        "meteo": "hydrological",
    }


def test_only_a_settings_writer_changes_the_choice(api: Served) -> None:
    """A person without ``settings.write`` gets ``403``; a wrong value ``400``."""
    # Act
    refused = api.remember(caller=api.other, meteo="hydrological")
    wrong = api.remember(meteo="lunar")

    # Assert
    assert_problem(refused, 403, "forbidden", "permission_denied")
    assert_problem(wrong, 400, "validation_error")
    assert api.json("/settings")["year_types"] == DEFAULTS


def test_a_change_of_the_choice_is_in_the_action_log(api: Served) -> None:
    """``settings.update`` with the types before and after; no change, no entry."""
    # Arrange
    state = StateStore(api.paths.state_file)
    after = last_entry(state)

    # Act
    changed = api.remember(hydro="calendar", meteo="calendar")
    again = api.remember(hydro="calendar", meteo="calendar")

    # Assert
    assert changed.status_code == again.status_code == 200
    (entry,) = log_entries(state, after=after)
    assert (entry.action, entry.actor, entry.target, entry.outcome) == (
        "settings.update",
        LOCAL_OWNER.id,
        "settings",
        "ok",
    )
    assert entry.before == {"year_types": DEFAULTS}
    assert entry.after == {"year_types": {"hydro": "calendar", "meteo": "calendar"}}
