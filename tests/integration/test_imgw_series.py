"""Coverage of the IMGWTools series of stations in the local index (plan I5).

Every test scans a copy of a fixture store of the producer's own builder
(``imgwtools.testing``) through the real adapter, offline. The index holds the
coverage of the current version of each dataset's series: every variable of
every station as the series index gives it, and each of its years in both year
types computed from the gap lists against the known periods (SPEC 4.8.4); a
new current version replaces them.
"""

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from imgwtools import current_version, read_series_index

from archiwista.config import AppSettings, StoreConfig
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.index import IndexQueries, IndexWriter, ScanEvent, ScanNotice
from archiwista.index.scanner import ScanMode, ScanSummary, scan_store
from archiwista.sources import SeriesIndexAdapter, SeriesListing, SourceAdapter
from archiwista.sources.registry import load_registry

STORE = "dane"
SERIES = "series.json"
META = ".meta.json"
PL_HYDRO = "pl.imgw.hydro_daily"
PL_PRECIP = "pl.imgw.meteo_precip_daily"
CZ_HYDRO = "cz.chmi.hydro_daily"
CZ_METEO = "cz.chmi.meteo_daily"
_ROWS = (
    "SELECT dataset, provider, code, variable_key, variable, unit, first_date,"
    " last_date, with_value, accumulated, gaps, periods, file FROM station_series"
    " ORDER BY dataset, code, variable_key"
)

type Stores = Callable[[str], Path]
type Row = tuple[object, ...]


@dataclass
class _Env:
    """A copy of a fixture store with an index that knows it."""

    root: Path
    index: Path
    adapter: SourceAdapter
    writer: IndexWriter
    settings: AppSettings
    events: list[ScanEvent]

    def scan(self, mode: ScanMode = "incremental") -> ScanSummary:
        return scan_store(
            self.adapter,
            self.writer,
            self.settings,
            STORE,
            mode=mode,
            on_event=self.events.append,
        )

    def series_adapter(self) -> SeriesIndexAdapter:
        assert isinstance(self.adapter, SeriesIndexAdapter)
        return self.adapter

    def sql(self, statement: str, *params: object) -> list[Row]:
        with closing(sqlite3.connect(self.index)) as connection:
            return [tuple(row) for row in connection.execute(statement, params)]

    def series(self, dataset: str) -> list[Row]:
        """Return ``(code, key, first, last, with_value, accumulated, gaps)`` rows."""
        return self.sql(
            "SELECT code, variable_key, first_date, last_date, with_value,"
            " accumulated, gaps FROM station_series WHERE dataset = ?"
            " ORDER BY code, variable_key",
            dataset,
        )

    def years(self, dataset: str, code: str, key: str, year_type: str) -> list[Row]:
        """Return ``(year, units, known, with_value)`` of a variable in a year type."""
        return self.sql(
            "SELECT y.year, y.units, y.known, y.with_value FROM series_years y"
            " JOIN station_series s ON s.id = y.series_id"
            " WHERE s.dataset = ? AND s.code = ? AND s.variable_key = ?"
            " AND y.year_type = ? ORDER BY y.year",
            dataset,
            code,
            key,
            year_type,
        )

    def catalogs(self) -> dict[str, str]:
        """Return the series version each dataset's coverage was read from."""
        return {
            str(dataset): str(version)
            for dataset, version in self.sql(
                "SELECT dataset, version_path FROM series_catalogs"
            )
        }

    def notices(self) -> list[ScanNotice]:
        return [event for event in self.events if isinstance(event, ScanNotice)]


@pytest.fixture
def open_env(imgw_store: Stores, tmp_path: Path) -> Iterator[Callable[[str], _Env]]:
    """Return ``open(variant)``: a private copy of a fixture store with its index."""
    writers: list[IndexWriter] = []

    def open_(variant: str) -> _Env:
        root = tmp_path / f"store-{variant}"
        shutil.copytree(imgw_store(variant), root)
        index = tmp_path / f"index-{variant}.sqlite"
        writer = IndexWriter(index)
        writers.append(writer)
        config = StoreConfig(id=STORE, name="Dane", imgw=root, kind="local")
        writer.sync_stores({STORE: config.roots()})
        adapter = load_registry(cache_dir=tmp_path / "cache").adapter("imgw")
        return _Env(root, index, adapter, writer, AppSettings(stores=(config,)), [])

    yield open_
    for writer in writers:
        writer.close()


def _current(root: Path, dataset: str) -> Path:
    found = current_version(root, slot=f"series:{dataset}")
    assert found is not None and found.version is not None
    return found.version


def _producer_rows(root: Path, dataset: str) -> list[Row]:
    """Return what ``read_series_index`` reads in the current version, as rows."""
    version = _current(root, dataset)
    index = read_series_index(version)
    relative = version.parent.relative_to(root)
    return sorted(
        (
            code,
            key,
            None if coverage.first is None else coverage.first.isoformat(),
            None if coverage.last is None else coverage.last.isoformat(),
            coverage.with_value,
            coverage.accumulated,
            json.dumps(
                [[start.isoformat(), end.isoformat()] for start, end in coverage.gaps],
                separators=(",", ":"),
            ),
            (relative / station.file).as_posix(),
        )
        for code, station in index.stations.items()
        for key, coverage in station.variables.items()
    )


def _publish(root: Path, dataset: str, edit: Callable[[dict[str, Any]], None]) -> str:
    """Write a newer version of a dataset's series with an edited index.

    The version directory is ``<label>_<sha8>`` with the edited ``series.json``,
    the series files of the current version and the sidecar (SHA-256, size,
    label, a later build), so IMGWTools takes it as the current version.
    Returns its ``series.json`` relative to the store.
    """
    source = _current(root, dataset).parent
    document = json.loads((source / SERIES).read_text(encoding="utf-8"))
    edit(document)
    data = json.dumps(document).encode()
    sha256 = hashlib.sha256(data).hexdigest()
    sidecar = json.loads((source / (SERIES + META)).read_text(encoding="utf-8"))
    built = datetime.fromisoformat(sidecar["downloaded_at"]) + timedelta(days=1)
    label = built.date().isoformat()
    sidecar.update(
        sha256=sha256,
        size_bytes=len(data),
        downloaded_at=built.isoformat().replace("+00:00", "Z"),
    )
    sidecar["extra"]["version"]["label"] = label
    target = source.parent / f"{label}_{sha256[:8]}"
    shutil.copytree(source, target)
    (target / SERIES).write_bytes(data)
    (target / (SERIES + META)).write_text(json.dumps(sidecar), encoding="utf-8")
    return (target / SERIES).relative_to(root).as_posix()


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_the_index_holds_every_variable_of_each_current_series(
    open_env: Callable[[str], _Env], variant: str
) -> None:
    """The rows equal the series index of each dataset's current version."""
    # Arrange
    env = open_env(variant)
    datasets = [PL_HYDRO, PL_PRECIP]
    if variant == "complete_pl_cz":
        datasets += [CZ_HYDRO, CZ_METEO]

    # Act
    env.scan("full")

    # Assert
    assert env.catalogs() == {
        dataset: _current(env.root, dataset).relative_to(env.root).as_posix()
        for dataset in datasets
    }
    for dataset in datasets:
        rows = env.sql(
            "SELECT code, variable_key, first_date, last_date, with_value,"
            " accumulated, gaps, file FROM station_series WHERE dataset = ?"
            " ORDER BY code, variable_key",
            dataset,
        )
        assert rows == _producer_rows(env.root, dataset)
    assert env.notices() == []


@pytest.mark.parametrize(
    ("dataset", "code", "key", "year_type", "years"),
    [
        # The producer counts 2 days with a value; its gaps leave 33 of 91.
        (PL_HYDRO, "149190310", "H", "hydrological", [(2024, 366, 366, 33)]),
        (
            PL_HYDRO,
            "149190310",
            "H",
            "calendar",
            [(2023, 365, 61, 1), (2024, 366, 305, 32)],
        ),
        (PL_HYDRO, "149190311", "Q", "hydrological", [(2024, 366, 366, 0)]),
        # The station has files of 2004 and 2006: 2005 is unknown, not a gap.
        (
            CZ_HYDRO,
            "0-203-1-900002",
            "H",
            "calendar",
            [(2004, 366, 366, 61), (2005, 365, 0, 0), (2006, 365, 365, 365)],
        ),
        (
            CZ_HYDRO,
            "0-203-1-900002",
            "T",
            "calendar",
            [(2004, 366, 366, 0), (2005, 365, 0, 0), (2006, 365, 365, 0)],
        ),
        # An accumulated sum is the value of its day.
        (PL_PRECIP, "123750000", "P", "calendar", [(2001, 365, 31, 30)]),
        (PL_PRECIP, "123750000", "P", "hydrological", [(2001, 365, 31, 30)]),
        (
            CZ_METEO,
            "0-203-0-90001",
            "P",
            "hydrological",
            [(2023, 365, 12, 11), (2024, 366, 19, 19)],
        ),
    ],
    ids=[
        "hydro-gaps-hydrological",
        "hydro-gaps-calendar",
        "hydro-empty",
        "chmi-unknown-year",
        "chmi-no-value",
        "meteo-accumulated-calendar",
        "meteo-accumulated-hydrological",
        "chmi-meteo-hydrological",
    ],
)
def test_each_year_counts_its_known_units_and_those_with_a_value(
    open_env: Callable[[str], _Env],
    dataset: str,
    code: str,
    key: str,
    year_type: str,
    years: list[Row],
) -> None:
    """Known periods and gap lists decide; worked out by hand from the fixture."""
    # Arrange
    env = open_env("complete_pl_cz")

    # Act
    env.scan("full")

    # Assert
    assert env.years(dataset, code, key, year_type) == years


def test_the_accumulated_sums_and_the_station_periods_are_kept(
    open_env: Callable[[str], _Env],
) -> None:
    """The row details of SPEC 4.8.4 come from the index, never from a series."""
    # Arrange
    env = open_env("complete_pl_cz")

    # Act
    env.scan("full")

    # Assert
    assert env.sql(
        "SELECT accumulated, periods FROM station_series"
        " WHERE dataset = ? AND code = '123750000' AND variable_key = 'P'",
        PL_PRECIP,
    ) == [(1, None)]
    assert env.sql(
        "SELECT DISTINCT periods FROM station_series"
        " WHERE dataset = ? AND code = '0-203-1-900002'",
        CZ_HYDRO,
    ) == [('[["2004-01-01","2004-12-31"],["2006-01-01","2006-12-31"]]',)]
    assert env.sql(
        "SELECT provider, kind, time_unit, year_type, first_year, periods"
        " FROM series_catalogs WHERE dataset = ?",
        PL_HYDRO,
    ) == [
        (
            "IMGW-PIB",
            "hydro",
            "day",
            "hydrological",
            1951,
            '[["2023-11-01","2024-10-31"]]',
        )
    ]


def test_a_new_series_version_replaces_the_datasets_rows(
    open_env: Callable[[str], _Env],
) -> None:
    """A newer current version is read again and its coverage replaces the old."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    czech = env.series(CZ_HYDRO)

    def edit(document: dict[str, Any]) -> None:
        precip = document["stations"]["123760000"]["variables"]["P"]
        precip.update(gaps=[["2001-01-10", "2001-01-12"]], with_value=28)

    published = _publish(env.root, PL_PRECIP, edit)

    # Act
    env.scan()

    # Assert
    assert env.catalogs()[PL_PRECIP] == published
    assert env.sql(
        "SELECT dataset, code, variable_key, first_date, last_date, with_value,"
        " accumulated, gaps, file FROM station_series WHERE dataset = ?"
        " ORDER BY code, variable_key",
        PL_PRECIP,
    ) == [(PL_PRECIP, *row) for row in _producer_rows(env.root, PL_PRECIP)]
    assert env.years(PL_PRECIP, "123760000", "P", "calendar") == [(2001, 365, 31, 28)]
    assert env.series(CZ_HYDRO) == czech


def test_an_unchanged_series_is_read_again_only_by_a_full_scan(
    open_env: Callable[[str], _Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The version its rows came from is current: an incremental scan reads none."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    series = env.series_adapter()
    read: list[str] = []
    original = series.read_series_index

    def counted(root: Path, version: Path) -> SeriesListing:
        read.append(version.as_posix())
        return original(root, version)

    monkeypatch.setattr(series, "read_series_index", counted)
    before = (env.sql(_ROWS), env.sql("SELECT count(*) FROM series_years"))

    # Act
    env.scan()
    incremental = list(read)
    env.scan("full")

    # Assert
    assert incremental == []
    assert sorted(read) == sorted(env.catalogs().values())
    assert (env.sql(_ROWS), env.sql("SELECT count(*) FROM series_years")) == before


def test_a_series_without_a_current_version_leaves_its_dataset_no_coverage(
    open_env: Callable[[str], _Env],
) -> None:
    """The series' only version is gone: its rows and years go, the others stay."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    czech = env.series(CZ_HYDRO)
    shutil.rmtree((env.root / env.catalogs()[PL_PRECIP]).parent)

    # Act
    env.scan("full")

    # Assert
    assert env.series(PL_PRECIP) == []
    assert PL_PRECIP not in env.catalogs()
    assert env.series(CZ_HYDRO) == czech
    assert env.sql(
        "SELECT count(*) FROM series_years y"
        " LEFT JOIN station_series s ON s.id = y.series_id WHERE s.id IS NULL"
    ) == [(0,)]


def test_a_series_the_producer_refuses_is_said_and_holds_no_coverage(
    open_env: Callable[[str], _Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ProducerError of one series: a notice, its rows gone, the scan goes on."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    czech = env.series(CZ_HYDRO)
    refused = env.catalogs()[PL_HYDRO]
    series = env.series_adapter()
    original = series.read_series_index

    def refusing(root: Path, version: Path) -> SeriesListing:
        if version.as_posix() == refused:
            raise ProducerError("imgwtools", "IMGWDataError", "series broken")
        return original(root, version)

    monkeypatch.setattr(series, "read_series_index", refusing)

    # Act
    env.scan("full")

    # Assert
    (notice,) = env.notices()
    assert (notice.level, notice.code) == ("warning", "series_unreadable")
    assert PL_HYDRO in notice.message and "series broken" in notice.message
    assert refused in notice.message
    assert env.series(PL_HYDRO) == []
    assert PL_HYDRO not in env.catalogs()
    assert env.series(CZ_HYDRO) == czech


def test_a_series_the_system_cannot_read_makes_the_store_unavailable(
    open_env: Callable[[str], _Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SourceUnavailableError ends the scan and keeps the rows the index had."""
    # Arrange
    env = open_env("complete")
    env.scan("full")
    before = env.sql(_ROWS)

    def unreadable(root: Path, version: Path) -> SeriesListing:
        raise SourceUnavailableError("share gone")

    monkeypatch.setattr(env.series_adapter(), "read_series_index", unreadable)

    # Act
    with pytest.raises(SourceUnavailableError):
        env.scan("full")

    # Assert
    with IndexQueries(env.index) as queries:
        (state,) = queries.status().stores
    assert state.status == "unavailable"
    assert env.sql(_ROWS) == before


def test_a_store_removed_from_the_settings_takes_its_coverage_with_it(
    open_env: Callable[[str], _Env],
) -> None:
    """The coverage belongs to its store: every row and year goes with it."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    assert env.sql("SELECT count(*) FROM series_years") != [(0,)]

    # Act
    env.writer.sync_stores({})

    # Assert
    assert env.sql(
        "SELECT (SELECT count(*) FROM series_catalogs),"
        " (SELECT count(*) FROM station_series), (SELECT count(*) FROM series_years)"
    ) == [(0, 0, 0)]
