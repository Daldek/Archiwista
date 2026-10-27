"""The year type each person remembers for hydro and meteo data (P15, SPEC 6.7).

Plan I8.2 and v0.4 T11: ``PUT /preferences`` keeps the two types among the
session's own preferences; the station routes and ``archiwista stations``
(as the local owner) number the years by the type the person remembers for
the data's family when ``year_type`` is absent, a list of both families by
hydro's, and a given ``year_type`` wins without changing the preference.
Half-year characteristics stay hydrological, and one person's choice is not
another's. The index is a scanned copy of ``complete``
(``imgwtools.testing``) with a synthetic half-year series of Raba Górna,
which the fixture stores lack.
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

from archiwista.auth import LOCAL_OWNER, LOCAL_PRINCIPAL_ID
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources import SeriesListing, StationSeries, VariableCoverage
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import add_people, principal

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

    def json(self, path: str, *, caller: Caller | None = None) -> Any:
        """Return the body of the ``200`` answer of ``GET path`` (the owner's)."""
        response = (caller or self.owner).request("GET", path)
        assert response.status_code == 200, response.text
        return response.json()

    def remember(
        self, *, caller: Caller | None = None, **year_types: str
    ) -> httpx.Response:
        """Send the year types in ``PUT /preferences`` as ``caller`` (the owner)."""
        return (caller or self.owner).request(
            "PUT", "/preferences", json={"year_types": year_types}
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
    """Return the served API; both people choose the defaults again afterwards."""
    yield served
    for caller in (served.owner, served.other):
        reset = caller.request("PUT", "/preferences", json={})
        assert reset.status_code == 200, reset.text


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
    assert api.json("/preferences")["year_types"] == {
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


def test_the_owner_s_choice_is_kept_and_read_by_the_command_line(
    api: Served, capsys: pytest.CaptureFixture[str]
) -> None:
    """The state database keeps the owner's choice; ``stations`` reads it as GET."""
    # Act
    api.remember(meteo="hydrological")
    stored = StateStore(api.paths.state_file).preferences(LOCAL_PRINCIPAL_ID)
    capsys.readouterr()
    status = main(
        ["stations", "list", f"--dataset={PRECIPITATION}", "--json"], paths=api.paths
    )
    printed = json.loads(capsys.readouterr().out)

    # Assert
    assert stored is not None
    assert stored.document["year_types"] == {
        "hydro": "hydrological",
        "meteo": "hydrological",
    }
    assert status == 0
    assert printed == api.json(f"/stations?dataset={PRECIPITATION}")
    assert _year_types(printed) == {"hydrological"}


def test_each_person_numbers_the_years_as_they_chose(api: Served) -> None:
    """A person without any role keeps a choice of their own; a wrong one is 400."""
    # Arrange
    listed = f"/stations?dataset={PRECIPITATION}"

    # Act
    chosen = api.remember(caller=api.other, meteo="hydrological")
    theirs = api.json(listed, caller=api.other)
    owners = api.json(listed)
    wrong = api.remember(caller=api.other, meteo="lunar")

    # Assert
    assert chosen.status_code == 200, chosen.text
    assert _year_types(theirs) == {"hydrological"}
    assert _year_types(owners) == {"calendar"}
    assert api.json("/preferences")["year_types"] == DEFAULTS
    assert_problem(wrong, 400, "validation_error")
    assert api.json("/preferences", caller=api.other)["year_types"] == {
        "hydro": "hydrological",
        "meteo": "hydrological",
    }
