"""Obserwator 3.2.0's tiers, hourly and weekly series in the index and the API.

A scan of a copy of the store of ``tests/fixtures/obserwator_tiers.py`` (built
offline by the producer's public writers, A-ADR-059) indexes the hourly series
of Raba's gauge, kept as one version per month, as one series of UTC hours
over both months, and ČHMÚ's weekly groundwater by the weeks of their Mondays;
each version keeps its tier and publication state, which the API shows in the
catalog's rows and on the slot and version cards. Archiwista draws no chart of
an hour or a week. A series of a unit Archiwista does not know is skipped with
one warning and a record, its versions still listed; the stores of Obserwator
3.1.0's layout scan as before, and ``archiwista doctor`` finds no error.
"""

import dataclasses
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import httpx
import pytest
from obserwator import DatasetDescriptor, get_dataset

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, ScanEvent, ScanNotice, initialize
from archiwista.index.scanner import ScanMode, ScanSummary, scan_store
from archiwista.sources import SourceAdapter
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.obserwator_roots import store_fields
from tests.fixtures.obserwator_tiers import (
    BORE,
    CHARACTERISTIC,
    OPERATIONAL,
    RABA,
    RECENT,
    SUBDAILY,
    TELEMETRY,
    WEEKLY,
)

STORE = "dane"
DAILY = "pl.imgw.hydro_daily"

type Stores = Callable[[str], Path]
type Row = tuple[object, ...]


@dataclass
class _Env:
    """A copy of a store with an index that knows it."""

    index: Path
    adapter: SourceAdapter
    writer: IndexWriter
    settings: AppSettings
    events: list[ScanEvent]

    def scan(self, mode: ScanMode = "incremental") -> ScanSummary:
        self.events.clear()
        return scan_store(
            self.adapter,
            self.writer,
            self.settings,
            STORE,
            mode=mode,
            on_event=self.events.append,
        )

    def sql(self, statement: str, *params: object) -> list[Row]:
        with closing(sqlite3.connect(self.index)) as connection:
            return [tuple(row) for row in connection.execute(statement, params)]

    def units(self) -> dict[str, str]:
        """Return the unit of each dataset whose series the index holds."""
        return {
            str(dataset): str(unit)
            for dataset, unit in self.sql(
                "SELECT dataset, time_unit FROM series_catalogs"
            )
        }

    def notices(self) -> list[tuple[str, str]]:
        return [
            (event.level, event.code)
            for event in self.events
            if isinstance(event, ScanNotice)
        ]


@pytest.fixture
def open_env(tmp_path: Path) -> Iterator[Callable[[Path], _Env]]:
    """Return ``open(store)``: a private copy of a store with its index."""
    writers: list[IndexWriter] = []

    def open_(store: Path) -> _Env:
        root = tmp_path / f"store-{len(writers)}"
        shutil.copytree(store, root)
        index = tmp_path / f"index-{len(writers)}.sqlite"
        writer = IndexWriter(index)
        writers.append(writer)
        config = StoreConfig(id=STORE, name="Dane", **store_fields(root), kind="local")
        writer.sync_stores({STORE: config.directory_paths()})
        adapter = load_registry(cache_dir=tmp_path / "cache").adapter("obserwator")
        return _Env(index, adapter, writer, AppSettings(stores=(config,)), [])

    yield open_
    for writer in writers:
        writer.close()


def test_scan_indexes_the_hourly_months_as_one_series_of_utc_hours(
    open_env: Callable[[Path], _Env], tiers_store: Path
) -> None:
    """Both months joined: H with its six-hour gap, Q's gap across the months."""
    env = open_env(tiers_store)

    env.scan("full")
    full = env.notices()
    env.scan()

    assert (full, env.notices()) == ([], [])
    assert env.sql("SELECT slot_path FROM skipped_series") == []
    ((unit, slot, version, months),) = env.sql(
        "SELECT time_unit, slot_path, version_path, months FROM series_catalogs"
        " WHERE dataset = ?",
        SUBDAILY,
    )
    assert unit == "hour"
    assert [(month, slot_) for month, slot_, _ in json.loads(str(months))] == [
        ("2026-09", "series/versions/imgw_hydro_subdaily/2026-09"),
        ("2026-10", "series/versions/imgw_hydro_subdaily/2026-10"),
    ]
    assert (slot, version) == tuple(json.loads(str(months))[-1][1:])
    rows = env.sql(
        "SELECT variable_key, first_date, last_date, with_value, gaps"
        " FROM station_series WHERE dataset = ? AND code = ? ORDER BY variable_key",
        SUBDAILY,
        RABA,
    )
    assert [
        (key, first, last, count, json.loads(str(gaps)))
        for key, first, last, count, gaps in rows
    ] == [
        (
            "H",
            "2026-09-01T00:00:00Z",
            "2026-10-11T23:00:00Z",
            978,
            [["2026-09-15T06:00:00Z", "2026-09-15T11:00:00Z"]],
        ),
        (
            "Q",
            "2026-09-01T00:00:00Z",
            "2026-10-01T23:00:00Z",
            48,
            [["2026-09-02T00:00:00Z", "2026-09-30T23:00:00Z"]],
        ),
        ("T", None, None, 0, []),
    ]
    years = env.sql(
        "SELECT s.variable_key, y.units, y.known, y.with_value FROM series_years y"
        " JOIN station_series s ON s.id = y.series_id WHERE s.dataset = ?"
        " AND s.code = ? AND y.year_type = 'calendar' AND y.year = 2026"
        " ORDER BY s.variable_key",
        SUBDAILY,
        RABA,
    )
    assert years == [("H", 8760, 984, 978), ("Q", 8760, 984, 48), ("T", 8760, 984, 0)]


def test_scan_indexes_weekly_groundwater_and_keeps_tiers_and_characteristics(
    open_env: Callable[[Path], _Env], tiers_store: Path
) -> None:
    """Weeks, the tiers of the versions, and the characteristics as archives."""
    env = open_env(tiers_store)

    env.scan("full")

    units = env.units()
    assert units[WEEKLY] == "week"
    assert CHARACTERISTIC not in units
    assert env.sql(
        "SELECT first_date, last_date, with_value FROM station_series"
        " WHERE dataset = ? AND code = ? AND variable_key = 'H_asl'",
        WEEKLY,
        BORE,
    ) == [("2012-01-01", "2012-12-23", 52)]
    tiers = {
        (str(dataset), tier, publication)
        for dataset, tier, publication in env.sql(
            "SELECT dataset_key, tier, publication FROM versions"
        )
    }
    assert {row for row in tiers if row[1:] != (None, None)} == {
        (TELEMETRY, "telemetry", "public"),
        (RECENT, "operational", "public"),
        (OPERATIONAL, "operational", "private"),
        (SUBDAILY, "operational", "private"),
    }
    assert (CHARACTERISTIC, None, None) in tiers
    assert env.sql(
        "SELECT groundwater_kind FROM stations WHERE kind = 'groundwater'"
        " ORDER BY groundwater_kind"
    ) == [("bore",), ("spring",)]


def _fortnights(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the registry keep the weekly groundwater by a unit Archiwista lacks."""
    real = get_dataset

    def patched(key: str) -> DatasetDescriptor:
        found = real(key)
        if found.key == WEEKLY:
            return dataclasses.replace(found, time_unit=cast("Any", "fortnight"))
        return found

    monkeypatch.setattr("archiwista.adapter.obserwator.adapter.get_dataset", patched)


def test_scan_skips_a_series_of_an_unknown_unit_with_one_warning(
    open_env: Callable[[Path], _Env],
    tiers_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit Obserwator may add later: recorded, warned of once, versions kept."""
    env = open_env(tiers_store)
    _fortnights(monkeypatch)

    env.scan("full")
    full = env.notices()
    env.scan()
    incremental = env.notices()

    assert full == [("warning", "series_skipped")]
    assert incremental == []
    ((slot, dataset, version),) = env.sql(
        "SELECT slot_path, dataset, version_path FROM skipped_series"
    )
    assert (slot, dataset) == ("series/versions/chmu_groundwater_weekly", WEEKLY)
    assert str(version).startswith("series/versions/chmu_groundwater_weekly/")
    assert WEEKLY not in env.units()
    assert env.sql("SELECT count(*) FROM station_series WHERE dataset = ?", WEEKLY) == [
        (0,)
    ]
    assert env.sql(
        "SELECT path FROM versions WHERE path = ? AND state = 'present'", version
    ) == [(version,)]
    assert {str(row[0]) for row in env.sql("SELECT dataset FROM series_catalogs")} >= {
        SUBDAILY,
        DAILY,
    }


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_scan_of_a_store_of_obserwator_3_1_layout_skips_no_series(
    open_env: Callable[[Path], _Env], obserwator_store: Stores, variant: str
) -> None:
    """The stores without tiers: no warning, no skipped series, no months."""
    env = open_env(obserwator_store(variant))

    env.scan("full")
    full = env.notices()
    env.scan()

    assert (full, env.notices()) == ([], [])
    assert env.sql("SELECT slot_path FROM skipped_series") == []
    assert (
        env.sql(
            "SELECT dataset FROM series_catalogs"
            " WHERE months IS NOT NULL OR time_unit IN ('hour', 'week')"
        )
        == []
    )
    tiered = (
        "SELECT path FROM versions WHERE tier IS NOT NULL OR publication IS NOT NULL"
    )
    assert env.sql(tiered) == []


@dataclass(frozen=True)
class Served:
    """The API over the index of a scanned copy of the tiers store."""

    owner: Caller
    paths: AppPaths

    def get(self, path: str) -> httpx.Response:
        """Return the answer of ``GET path`` under ``/api/v1``."""
        return self.owner.request("GET", path)

    def json(self, path: str) -> Any:
        """Return the body of a ``200`` answer of ``GET path``."""
        response = self.get(path)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture(scope="module")
def served(
    tiers_store: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Serve the index of a copy of the tiers store after a full scan."""
    base = tmp_path_factory.mktemp("tiers-api")
    root = base / "store"
    shutil.copytree(tiers_store, root)
    paths = local_paths(base)
    config = StoreConfig(id=STORE, name="Dane", **store_fields(root), kind="local")
    settings = AppSettings(stores=(config,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.directory_paths()})
        scan_store(registry.adapter("obserwator"), writer, settings, STORE, mode="full")
    with running_api(paths, registry) as api:
        yield Served(api.session(LOCAL_OWNER), paths)


def test_station_card_gives_the_hourly_series_its_months_and_utc_hours(
    served: Served,
) -> None:
    """Raba's card: the months joined, the first and last hours in UTC."""
    card = served.json(f"/stations/{RABA}")

    (hourly,) = (
        item for item in card["station"]["series"] if item["dataset"] == SUBDAILY
    )
    h = hourly["coverage"]["H"]
    assert (hourly["time_unit"], hourly["months"]) == ("hour", ["2026-09", "2026-10"])
    assert hourly["series_version"].startswith(
        "series/versions/imgw_hydro_subdaily/2026-10/"
    )
    assert (h["first"], h["last"]) == ("2026-09-01T00:00:00Z", "2026-10-11T23:00:00Z")
    # 2026 is not known whole, so the year is unknown (SPEC 4.8.4).
    assert (h["state"], h["label"]) == ("unknown", "unknown")
    assert SUBDAILY not in {chart["dataset"] for chart in card["charts"]}
    (daily,) = (item for item in card["station"]["series"] if item["dataset"] == DAILY)
    assert daily["months"] == []


def test_station_card_labels_a_weekly_series_by_its_weeks(served: Served) -> None:
    """The bore's H_asl: the weeks of 24 and 31 XII 2012, Mondays of 2012, a gap."""
    card = served.json(f"/stations/{BORE}")

    (weekly,) = (
        item for item in card["station"]["series"] if item["dataset"] == WEEKLY
    )
    h = weekly["coverage"]["H_asl"]
    assert (weekly["time_unit"], weekly["months"]) == ("week", [])
    assert (h["first"], h["last"], h["state"]) == ("2012-01-01", "2012-12-23", "gaps")
    assert h["longest_gap"] == {"from": "2012-12-24", "to": "2013-01-06", "units": 2}
    assert h["label"] == (
        "gaps 4% · longest 2012.12.24–2013.01.06 · unknown: 1933–2011, 2013–2014"
    )
    assert WEEKLY not in {chart["dataset"] for chart in card["charts"]}


@pytest.mark.parametrize(
    ("code", "dataset", "unit"), [(RABA, SUBDAILY, "hour"), (BORE, WEEKLY, "week")]
)
def test_station_series_of_an_hourly_or_weekly_dataset_is_no_chart(
    served: Served, code: str, dataset: str, unit: str
) -> None:
    """``/stations/{code}/series`` of an hour or a week: ``400 no_chart``."""
    variable = "H" if unit == "hour" else "H_asl"
    response = served.get(
        f"/stations/{code}/series?dataset={dataset}&variable={variable}"
    )

    assert_problem(response, 400, "validation_error", "no_chart")
    assert response.json()["details"]["unit"] == unit


def test_versions_carry_their_tier_and_publication_in_rows_and_cards(
    served: Served,
) -> None:
    """The catalog's rows, the slot card and the version card say the same."""
    marks: dict[str, set[tuple[str | None, str | None]]] = {}
    for dataset in (TELEMETRY, OPERATIONAL, SUBDAILY, DAILY):
        page = served.json(f"/slots?segment={quote(dataset)}&versions=all&limit=200")
        marks[dataset] = {
            (row["version"]["tier"], row["version"]["publication"])
            for row in page["items"]
        }
    rows = served.json(f"/slots?segment={quote(SUBDAILY)}&limit=200")["items"]
    (hourly,) = (row for row in rows if row["slot"].endswith("/2026-10"))
    slot = served.json(f"/stores/{STORE}/slots/{hourly['slot']}")
    version = served.json(f"/stores/{STORE}/versions/{hourly['version']['path']}")

    assert marks == {
        TELEMETRY: {("telemetry", "public")},
        OPERATIONAL: {("operational", "private")},
        SUBDAILY: {("operational", "private")},
        DAILY: {(None, None)},
    }
    assert [(item["tier"], item["publication"]) for item in slot["versions"]] == [
        ("operational", "private")
    ]
    assert (version["version"]["tier"], version["version"]["publication"]) == (
        "operational",
        "private",
    )


def test_doctor_finds_no_error_with_the_tiers_store(
    tiers_store: Path, tmp_path: Path
) -> None:
    """``archiwista doctor`` with settings naming the store: both roots OK."""
    config = ConfigStore(tmp_path / "config" / "archiwista" / "config.toml")
    config.save(
        AppSettings(
            stores=(
                StoreConfig(
                    id=STORE, name="Dane", **store_fields(tiers_store), kind="local"
                ),
            )
        )
    )
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from archiwista.cli import main; raise SystemExit(main())",
            "doctor",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert "[BŁĄD]" not in result.stdout
    assert any(line.startswith("Wynik: błędy 0,") for line in lines), lines
    assert (
        f"[OK] Magazyn „{STORE}” (obserwator, dysk lokalny):"
        f" {store_fields(tiers_store)['obserwator']}"
    ) in lines
    assert (
        f"[OK] Magazyn „{STORE}” (obserwator_data, dysk lokalny):"
        f" {store_fields(tiers_store)['obserwator_data']}"
    ) in lines
