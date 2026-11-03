"""Contract of the series indexes of IMGWTools behind ``SeriesIndexAdapter``.

The IMGW adapter names the dataset whose series a slot is by the producer's
own slot key and reads the index of a series version with
``imgwtools.read_series_index``: what it gives must be what the producer itself
reads in its offline fixture stores (``imgwtools.testing``), with each
station's series file relative to the store, and a version the producer
refuses is its error, never coverage.
"""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from imgwtools import get_dataset, iter_store, read_series_index

from archiwista.adapter.imgw import load
from archiwista.adapter.imgw.adapter import ImgwAdapter
from archiwista.adapter.kartograf import load as load_kartograf
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.sources import SeriesIndexAdapter, SourceContext

type Stores = Callable[[str], Path]

SERIES_SLOTS = (
    "series:pl.imgw.hydro_daily",
    "series:pl.imgw.meteo_precip_daily",
    "series:cz.chmi.hydro_daily",
    "series:cz.chmi.meteo_daily",
)


@pytest.fixture
def adapter(tmp_path: Path) -> ImgwAdapter:
    """Create the adapter with its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "imgw"))
    assert isinstance(created, ImgwAdapter)
    return created


def _series_version(adapter: ImgwAdapter, root: Path, key: str) -> Path:
    """Return the current version of a dataset's series, relative to the store."""
    version = adapter.current_version(root, key)
    assert version is not None
    return version


def test_only_the_imgw_adapter_has_series_indexes(
    adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """The capability is optional: Kartograf keeps no series of stations."""
    kartograf = load_kartograf(SourceContext(cache_dir=tmp_path / "cache" / "k"))

    assert isinstance(adapter, SeriesIndexAdapter)
    assert not isinstance(kartograf, SeriesIndexAdapter)


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_the_series_slots_name_their_datasets_and_no_other_slot_does(
    imgw_store: Stores, adapter: ImgwAdapter, variant: str
) -> None:
    """Every slot of ``iter_store``: a series names its dataset, the others none."""
    root = imgw_store(variant)
    slots = {
        entry.slot: entry.kind
        for entry in iter_store(root)
        if entry.slot is not None and entry.kind != "problem"
    }

    named = {slot: adapter.series_dataset(slot) for slot in slots}

    assert any(kind == "series" for kind in slots.values())
    assert named == {
        slot: slot.partition(":")[2] if kind == "series" else None
        for slot, kind in slots.items()
    }
    assert adapter.series_dataset("series:pl.imgw.no_such_dataset") is None


@pytest.mark.parametrize("key", SERIES_SLOTS)
def test_read_series_index_gives_every_station_the_producer_reads(
    imgw_store: Stores, adapter: ImgwAdapter, key: str
) -> None:
    """Stations, variables, periods and gaps as the producer's; files in the store."""
    root = imgw_store("complete_pl_cz")
    version = _series_version(adapter, root, key)
    index = read_series_index(root / version)
    dataset = get_dataset(index.dataset)

    listing = adapter.read_series_index(root, version)

    assert (listing.dataset, listing.year_type, listing.periods) == (
        key.partition(":")[2],
        index.year_type,
        index.periods,
    )
    assert (listing.provider, listing.kind, listing.time_unit, listing.first_year) == (
        dataset.provider,
        dataset.kind,
        dataset.time_unit,
        dataset.first_year,
    )
    assert [station.code for station in listing.stations] == list(index.stations)
    for station in listing.stations:
        produced = index.stations[station.code]
        assert (root / station.file).is_file()
        assert Path(station.file) == version.parent / produced.file
        assert (station.sha256, station.rows, station.periods) == (
            produced.sha256,
            produced.rows,
            produced.periods,
        )
        assert [
            (v.key, v.variable, v.unit, v.period, v.first, v.last, v.gaps)
            for v in station.variables
        ] == [
            (key, c.variable, c.unit, c.period, c.first, c.last, c.gaps)
            for key, c in produced.variables.items()
        ]
        assert [(v.with_value, v.accumulated) for v in station.variables] == [
            (c.with_value, c.accumulated) for c in produced.variables.values()
        ]


def test_a_station_of_per_station_files_keeps_its_own_periods(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """ČHMÚ: the station's files decide its known periods, the version's do not."""
    root = imgw_store("complete_pl_cz")
    czech = adapter.read_series_index(
        root, _series_version(adapter, root, "series:cz.chmi.hydro_daily")
    )
    polish = adapter.read_series_index(
        root, _series_version(adapter, root, "series:pl.imgw.hydro_daily")
    )

    stations = {station.code: station for station in czech.stations}
    assert [
        (start.year, end.year)
        for start, end in stations["0-203-1-900002"].periods or ()
    ] == [(2004, 2004), (2006, 2006)]
    assert all(station.periods is None for station in polish.stations)


def test_a_version_unlike_its_sidecar_is_the_producers_error(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """Same size, other bytes: IMGWTools refuses it and no coverage comes out."""
    root = tmp_path / "store"
    shutil.copytree(imgw_store("complete"), root)
    version = _series_version(adapter, root, "series:pl.imgw.hydro_daily")
    path = root / version
    data = path.read_bytes()
    assert b"149190310" in data
    path.write_bytes(data.replace(b"149190310", b"149190319", 1))

    with pytest.raises(ProducerError) as raised:
        adapter.read_series_index(root, version)

    assert raised.value.package == "imgwtools"


def test_a_file_that_is_no_series_index_is_the_producers_error(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """A station catalog is not a series index."""
    root = imgw_store("complete")
    catalog = _series_version(adapter, root, "catalog:pl.imgw.stations")

    with pytest.raises(ProducerError):
        adapter.read_series_index(root, catalog)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads any file"
)
def test_a_series_index_the_system_cannot_read_is_an_unavailable_store(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """A file without read permission is no verdict of the producer."""
    root = tmp_path / "store"
    shutil.copytree(imgw_store("complete_pl_cz"), root)
    version = _series_version(adapter, root, "series:cz.chmi.meteo_daily")
    path = root / version
    path.chmod(0)
    try:
        with pytest.raises(SourceUnavailableError):
            adapter.read_series_index(root, version)
    finally:
        path.chmod(0o644)
