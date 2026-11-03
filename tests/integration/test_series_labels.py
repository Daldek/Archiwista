"""Coverage labels of the fixture series from the index alone (plan I5, SPEC 4.8.4).

The table of edge cases worked out by hand from the series of the producer's
own fixture store (``imgwtools.testing``): continuous, with gaps, without a
value, a year unknown because a ČHMÚ station has no file for it (not a gap),
a variable with an accumulated sum, hydro and meteo in both year types. Every
test makes IMGWTools refuse to read a series, so a label that needed one would
fail: they come from ``station_series`` and ``series_years`` only.
"""

import shutil
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import imgwtools
import imgwtools.store.reader
import pytest

from archiwista.api.models_stations import series_label_text
from archiwista.config import AppSettings, StoreConfig
from archiwista.errors import IndexQueryError
from archiwista.index import IndexQueries, IndexWriter, StationCoverage, YearRange
from archiwista.index.scanner import scan_store
from archiwista.messages import language
from archiwista.sources import YearType
from archiwista.sources.registry import load_registry

STORE = "dane"
PL_HYDRO = "pl.imgw.hydro_daily"
PL_PRECIP = "pl.imgw.meteo_precip_daily"
CZ_HYDRO = "cz.chmi.hydro_daily"
CZ_METEO = "cz.chmi.meteo_daily"

type Stores = Callable[[str], Path]
type Coverage = Callable[..., StationCoverage]


@pytest.fixture(scope="module")
def index(
    imgw_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Path]:
    """Return the index of a copy of ``complete_pl_cz`` after a full scan."""
    base = tmp_path_factory.mktemp("labels")
    root = base / "store"
    shutil.copytree(imgw_store("complete_pl_cz"), root)
    config = StoreConfig(id=STORE, name="Dane", imgw=root, kind="local")
    path = base / "index.sqlite"
    with IndexWriter(path) as writer:
        writer.sync_stores({STORE: config.roots()})
        adapter = load_registry(cache_dir=base / "cache").adapter("imgw")
        scan_store(adapter, writer, AppSettings(stores=(config,)), STORE, mode="full")
    yield path


@pytest.fixture
def coverage(index: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Coverage]:
    """Return ``coverage(provider, code, dataset, ...)`` with no series readable."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a label must not read a series")

    monkeypatch.setattr(imgwtools, "read_series", refuse)
    monkeypatch.setattr(imgwtools.store.reader, "read_series", refuse)
    with IndexQueries(index) as queries:

        def coverage_(
            provider: str,
            code: str,
            dataset: str,
            *,
            year_type: YearType | None = None,
            years: YearRange | None = None,
        ) -> StationCoverage:
            (found,) = queries.station_coverage(
                STORE, provider, code, dataset=dataset, year_type=year_type, years=years
            )
            return found

        yield coverage_


def _text(found: StationCoverage, key: str) -> str:
    (variable,) = (item for item in found.variables if item.key == key)
    with language("pl"):
        return series_label_text(variable.label, time_unit=found.time_unit)


@pytest.mark.parametrize(
    ("provider", "code", "dataset", "key", "year_type", "years", "expected"),
    [
        pytest.param(
            "IMGW-PIB",
            "149190310",
            PL_HYDRO,
            "H",
            None,
            None,
            "luki 91% · najdł. 2024.03.01–2024.10.31 · nieznane: 1951–2023",
            id="hydro-gaps-hydrological",
        ),
        pytest.param(
            "IMGW-PIB",
            "149190310",
            PL_HYDRO,
            "H",
            "calendar",
            None,
            "nieznane",
            id="hydro-calendar-years-unknown-without-xi-xii",
        ),
        pytest.param(
            "IMGW-PIB",
            "149190311",
            PL_HYDRO,
            "Q",
            None,
            None,
            "brak danych (tylko H, T) · nieznane: 1951–2023",
            id="hydro-no-q-with-h",
        ),
        pytest.param(
            "IMGW-PIB",
            "123750000",
            PL_PRECIP,
            "P",
            None,
            None,
            "nieznane",
            id="meteo-calendar-month-only",
        ),
        pytest.param(
            "IMGW-PIB",
            "123750000",
            PL_PRECIP,
            "P",
            "hydrological",
            None,
            "nieznane",
            id="meteo-hydrological-month-only",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900001",
            CZ_HYDRO,
            "H",
            "calendar",
            (2023, 2023),
            "ciągły · 2023",
            id="chmi-continuous",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900001",
            CZ_HYDRO,
            "H",
            "calendar",
            (2023, 2024),
            "luki <1% · najdł. 2024.06.15",
            id="chmi-one-day",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900001",
            CZ_HYDRO,
            "T",
            "calendar",
            (2023, 2024),
            "częściowy · do 2023 · luki 84%",
            id="chmi-ends-within",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900001",
            CZ_HYDRO,
            "H",
            None,
            None,
            "luki <1% · najdł. 2024.06.15 · nieznane: 1887–2023, 2025",
            id="chmi-hydrological-two-unknown-ranges",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900002",
            CZ_HYDRO,
            "H",
            "calendar",
            (2004, 2006),
            "luki 42% · najdł. 2004.01.01–2004.10.31 · nieznane: 2005",
            id="chmi-no-file-is-unknown-not-a-gap",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900002",
            CZ_HYDRO,
            "Q",
            "calendar",
            (2004, 2006),
            "ciągły · 2004–2006 · nieznane: 2005",
            id="chmi-continuous-around-an-unknown-year",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900002",
            CZ_HYDRO,
            "T",
            "calendar",
            (2004, 2006),
            "brak danych (tylko H, Q) · nieznane: 2005",
            id="chmi-no-t",
        ),
        pytest.param(
            "CHMI",
            "0-203-1-900002",
            CZ_HYDRO,
            "H",
            "calendar",
            None,
            "luki 42% · najdł. 2004.01.01–2004.10.31 · nieznane: 136 lat",
            id="chmi-unknown-years-counted",
        ),
        pytest.param(
            "CHMI",
            "0-203-0-90001",
            CZ_METEO,
            "P",
            None,
            None,
            "nieznane",
            id="chmi-meteo-a-month-only",
        ),
    ],
)
def test_the_labels_of_the_fixture_series(
    coverage: Coverage,
    provider: str,
    code: str,
    dataset: str,
    key: str,
    year_type: YearType | None,
    years: YearRange | None,
    expected: str,
) -> None:
    """Each edge case of SPEC 11, from the index without reading a series."""
    found = coverage(provider, code, dataset, year_type=year_type, years=years)

    assert _text(found, key) == expected


def test_the_range_and_the_year_type_follow_the_dataset_by_default(
    coverage: Coverage,
) -> None:
    """Hydro by hydrological years from 1951, meteo by calendar ones from 1950."""
    hydro = coverage("IMGW-PIB", "149190310", PL_HYDRO)
    meteo = coverage("IMGW-PIB", "123750000", PL_PRECIP)
    czech = coverage("CHMI", "0-203-0-90001", CZ_METEO)

    assert (hydro.year_type, hydro.span) == ("hydrological", (1951, 2024))
    assert (meteo.year_type, meteo.span) == ("calendar", (1950, 2001))
    # No first year declared: the first known year begins the range.
    assert (czech.year_type, czech.span) == ("calendar", (2023, 2023))
    assert hydro.series == "2026-10-19"
    assert hydro.file.startswith(hydro.series_version.rpartition("/")[0] + "/")


def test_the_row_details_come_with_the_label(coverage: Coverage) -> None:
    """Full years, the longest gap, unknown years and accumulated sums."""
    czech = coverage(
        "CHMI", "0-203-1-900002", CZ_HYDRO, year_type="calendar", years=(2004, 2006)
    )
    precip = coverage("IMGW-PIB", "123750000", PL_PRECIP)

    variables = {item.key: item for item in czech.variables}
    water = variables["H"].label
    assert (water.known, water.valued, water.complete_years) == (
        (2004, 2006),
        (2004, 2006),
        1,
    )
    assert (water.units, water.with_value) == (366 + 365, 61 + 365)
    assert water.longest_gap is not None and water.longest_gap.units == 305
    assert water.unknown_years == ((2005, 2005),)
    assert [(y.year, y.known) for y in variables["H"].years] == [
        (2004, 366),
        (2005, 0),
        (2006, 365),
    ]
    (rain,) = (item for item in precip.variables if item.key == "P")
    assert (rain.accumulated, rain.first, rain.last) == (
        1,
        date(2001, 1, 2),
        date(2001, 1, 31),
    )


def test_a_station_without_a_series_has_no_coverage_and_a_reversed_range_is_refused(
    index: Path,
) -> None:
    """Nothing comes out for an unknown station; 2025-2020 is no range."""
    with IndexQueries(index) as queries:
        assert queries.station_coverage(STORE, "IMGW-PIB", "999999999") == ()
        with pytest.raises(IndexQueryError):
            queries.station_coverage(
                STORE, "CHMI", "0-203-1-900002", years=(2025, 2020)
            )
