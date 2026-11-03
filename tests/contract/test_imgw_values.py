"""Contract of the values of IMGWTools series behind ``SeriesValuesAdapter``.

The IMGW adapter reads a station's values of a series version with
``imgwtools.read_series``: what it gives must be what the producer itself reads
in its offline fixture stores (``imgwtools.testing``), a missing unit as
``None``, an accumulated sum flagged; a station outside the series is not
found and a version the producer refuses is its error. The dataset of the
half-year characteristics and their extremes come from the producer's
registry, never from the text of a key.
"""

import shutil
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from imgwtools import get_dataset, read_series, read_series_index

from archiwista.adapter.imgw import load
from archiwista.adapter.imgw.adapter import ImgwAdapter
from archiwista.adapter.kartograf import load as load_kartograf
from archiwista.errors import NotFoundError, ProducerError
from archiwista.sources import SeriesValuesAdapter, SourceContext

type Stores = Callable[[str], Path]

DAILY = "pl.imgw.hydro_daily"
RABA = "149190310"


@pytest.fixture
def adapter(tmp_path: Path) -> ImgwAdapter:
    """Create the adapter with its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "imgw"))
    assert isinstance(created, ImgwAdapter)
    return created


def _version(adapter: ImgwAdapter, root: Path, dataset: str) -> Path:
    """Return the current version of a dataset's series, relative to the store."""
    version = adapter.current_version(root, f"series:{dataset}")
    assert version is not None
    return version


def _days(start: date, end: date) -> set[date]:
    return {start + timedelta(days=n) for n in range((end - start).days + 1)}


def test_only_the_imgw_adapter_reads_series_values(
    adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """The capability is optional: Kartograf keeps no series of stations."""
    kartograf = load_kartograf(SourceContext(cache_dir=tmp_path / "cache" / "k"))

    assert isinstance(adapter, SeriesValuesAdapter)
    assert not isinstance(kartograf, SeriesValuesAdapter)


def test_the_values_of_a_station_are_those_the_producer_reads(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """H of the Raba gauge: the producer's units and values; ``None`` without one."""
    root = imgw_store("complete")
    version = _version(adapter, root, DAILY)
    produced = list(read_series(root / version, station=RABA, variables=["H"]))
    gaps = read_series_index(root / version).stations[RABA].variables["H"].gaps

    values = list(adapter.read_values(root, version, station=RABA, variables=["H"]))

    assert [(item.start, item.period, dict(item.values)) for item in values] == [
        (record.date, None, {"H": record.measurements["H"].value})
        for record in produced
    ]
    assert gaps == (
        (date(2023, 12, 2), date(2023, 12, 31)),
        (date(2024, 2, 1), date(2024, 2, 28)),
    )
    missing = {item.start for item in values if item.values["H"] is None}
    gap_days = set().union(*(_days(start, end) for start, end in gaps))
    # January is not known (no archive holds it): no value, yet no gap either.
    assert missing == gap_days | _days(date(2024, 1, 1), date(2024, 1, 31))
    assert {item.start for item in values} - missing == {
        date(2023, 12, 1),
        date(2024, 2, 29),
    }
    assert all(not item.accumulated and not item.extremes for item in values)


def test_the_range_and_the_variables_select_the_units_and_values(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """Both bounds included; only the variables asked for, in every unit."""
    root = imgw_store("complete")
    version = _version(adapter, root, DAILY)

    values = list(
        adapter.read_values(
            root,
            version,
            station=RABA,
            variables=["Q", "H"],
            start=date(2024, 2, 28),
            end=date(2024, 2, 29),
        )
    )

    assert [(item.start, dict(item.values)) for item in values] == [
        (
            record.date,
            {name: record.measurements[name].value for name in ("Q", "H")},
        )
        for record in read_series(
            root / version,
            station=RABA,
            variables=["Q", "H"],
            start=date(2024, 2, 28),
            end=date(2024, 2, 29),
        )
    ]
    assert [item.start for item in values] == [date(2024, 2, 28), date(2024, 2, 29)]


def test_an_accumulated_sum_is_flagged_and_keeps_its_value(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """Precipitation: the producer's ``accumulated`` units, no other unit."""
    root = imgw_store("complete")
    version = _version(adapter, root, "pl.imgw.meteo_precip_daily")
    station = next(iter(read_series_index(root / version).stations))
    produced = list(read_series(root / version, station=station, variables=["P"]))

    values = list(adapter.read_values(root, version, station=station, variables=["P"]))

    flagged = [r.date for r in produced if r.measurements["P"].flag == "accumulated"]
    assert flagged
    assert [item.start for item in values if item.accumulated] == flagged
    assert all(item.accumulated == {"P"} for item in values if item.accumulated)
    assert [item.values["P"] for item in values] == [
        record.measurements["P"].value for record in produced
    ]


def test_a_station_outside_the_series_is_not_found(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """A code of the catalog without a series in the version."""
    root = imgw_store("complete")
    version = _version(adapter, root, DAILY)

    with pytest.raises(NotFoundError):
        list(adapter.read_values(root, version, station="149190319", variables=["H"]))


def test_a_refused_version_or_variable_is_the_producers_error(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """A Parquet file unlike the index, a catalog, a variable of no dataset."""
    root = tmp_path / "store"
    shutil.copytree(imgw_store("complete"), root)
    version = _version(adapter, root, DAILY)
    catalog = adapter.current_version(root, "catalog:pl.imgw.stations")
    assert catalog is not None

    with pytest.raises(ProducerError):
        list(adapter.read_values(root, catalog, station=RABA, variables=["H"]))
    with pytest.raises(ProducerError):
        list(adapter.read_values(root, version, station=RABA, variables=["P"]))
    parquet = root / version.parent / "stations" / f"{RABA}.parquet"
    data = bytearray(parquet.read_bytes())
    data[-1] ^= 1
    parquet.write_bytes(bytes(data))
    with pytest.raises(ProducerError) as raised:
        list(adapter.read_values(root, version, station=RABA, variables=["H"]))
    assert raised.value.package == "imgwtools"


def test_the_characteristics_dataset_comes_from_the_registry(
    adapter: ImgwAdapter,
) -> None:
    """Same provider and family, unit ``half_year``; none for a meteo dataset."""
    semiannual = get_dataset("pl.imgw.hydro_semiannual")

    named = adapter.characteristics_dataset(DAILY)

    assert named == semiannual.key
    assert (semiannual.provider, semiannual.kind, semiannual.time_unit) == (
        get_dataset(DAILY).provider,
        get_dataset(DAILY).kind,
        "half_year",
    )
    assert adapter.characteristics_dataset("pl.imgw.hydro_monthly") == semiannual.key
    assert adapter.characteristics_dataset("pl.imgw.hydro_semiannual") is None
    assert adapter.characteristics_dataset("pl.imgw.meteo_precip_daily") is None
    assert adapter.characteristics_dataset("pl.imgw.meteo_climate_daily") is None
    assert adapter.characteristics_dataset("cz.chmi.hydro_daily") is None
    assert adapter.characteristics_dataset("pl.imgw.pmaxtp") is None
    assert adapter.characteristics_dataset("pl.imgw.no_such_dataset") is None


def test_the_extremes_of_a_variable_are_its_characteristics_in_its_unit(
    adapter: ImgwAdapter,
) -> None:
    """``Q`` of daily hydro data: ``Q_min`` and ``Q_max``; nothing elsewhere."""
    held = get_dataset("pl.imgw.hydro_semiannual").variables
    daily = get_dataset(DAILY).variables

    extremes = {name: dict(adapter.extremes_of(DAILY, name)) for name in daily}

    assert extremes == {
        "H": {"min": "H_min", "max": "H_max"},
        "Q": {"min": "Q_min", "max": "Q_max"},
        "T": {"min": "T_min", "max": "T_max"},
    }
    assert all(
        held[key] == daily[name]
        for name, found in extremes.items()
        for key in found.values()
    )
    assert adapter.extremes_of(DAILY, "P") == {}
    assert adapter.extremes_of("pl.imgw.meteo_precip_daily", "P") == {}
    assert adapter.extremes_of("cz.chmi.hydro_daily", "Q") == {}
