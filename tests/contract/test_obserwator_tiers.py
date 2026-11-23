"""Contract of what Obserwator 3.2.0 writes beside the verified archive (A-ADR-059).

On the store of ``tests/fixtures/obserwator_tiers.py``, built offline by the
producer's public writers: a slot per month of a sub-daily series names its
dataset, and its series index gives the month and the starts of UTC hours; a
weekly series gives the dates of its readings; each version carries the tier
and the publication state its sidecar records (none: the verified, public
archive); a groundwater station keeps its kind and its location source; and
the characteristics of ČHMÚ's groundwater are archives with no series.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from obserwator import read_series_index

from archiwista.adapter.obserwator import load
from archiwista.adapter.obserwator.adapter import ObserwatorAdapter
from archiwista.sources import EntryMeta, SourceContext, VariableCoverage
from tests.fixtures.obserwator_roots import data_root, raw_root
from tests.fixtures.obserwator_tiers import (
    BORE,
    CHARACTERISTIC,
    HOURLY_GAP,
    OPERATIONAL,
    RABA,
    RECENT,
    SPRING,
    SUBDAILY,
    TELEMETRY,
    WEEKLY,
)

CZ_CATALOG = "catalog:cz.chmu.stations"


@pytest.fixture
def adapter(tmp_path: Path) -> ObserwatorAdapter:
    """Create the adapter with its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "obserwator"))
    assert isinstance(created, ObserwatorAdapter)
    return created


def _current(adapter: ObserwatorAdapter, root: Path, slot: str) -> Path:
    """Return the current version of a slot, relative to its root."""
    version = adapter.current_version(root, slot)
    assert version is not None
    return version


def _metas(adapter: ObserwatorAdapter, store: Path) -> list[tuple[str, EntryMeta]]:
    """Return the slot and the metadata of every version of both roots."""
    return [
        (str(entry.slot_key), entry.meta)
        for root in (raw_root(store), data_root(store))
        for entry in adapter.iter_entries(root)
        if entry.kind == "version" and entry.meta is not None
    ]


def _variables(
    adapter: ObserwatorAdapter, root: Path, slot: str, code: str
) -> dict[str, VariableCoverage]:
    """Return a station's variables in the current version of a series slot."""
    listing = adapter.read_series_index(root, _current(adapter, root, slot))
    (station,) = (item for item in listing.stations if item.code == code)
    return {coverage.key: coverage for coverage in station.variables}


def _hour(month: int, day: int, hour: int = 0) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def test_a_month_slot_names_the_dataset_of_its_series(
    adapter: ObserwatorAdapter, tiers_store: Path
) -> None:
    """Every series slot names its dataset, a month's slot too; others none."""
    slots = {slot for slot, _ in _metas(adapter, tiers_store)}

    named = {slot: adapter.series_dataset(slot) for slot in slots}

    assert named[f"series:{SUBDAILY}:2026-09"] == SUBDAILY
    assert named[f"series:{SUBDAILY}:2026-10"] == SUBDAILY
    assert named[f"series:{WEEKLY}"] == WEEKLY
    assert {slot for slot, dataset in named.items() if dataset is None} == {
        slot for slot in slots if not slot.startswith("series:")
    }
    assert adapter.series_dataset("series:pl.imgw.no_such_dataset:2026-09") is None


def test_read_series_index_of_a_month_gives_its_month_and_utc_hours(
    adapter: ObserwatorAdapter, tiers_store: Path
) -> None:
    """September of the hourly series: its month, H with the gap, Q of one day."""
    root = data_root(tiers_store)
    version = _current(adapter, root, f"series:{SUBDAILY}:2026-09")

    listing = adapter.read_series_index(root, version)
    variables = _variables(adapter, root, f"series:{SUBDAILY}:2026-09", RABA)

    assert (listing.dataset, listing.time_unit, listing.month) == (
        SUBDAILY,
        "hour",
        "2026-09",
    )
    assert listing.month == read_series_index(root / version).month
    h, q = variables["H"], variables["Q"]
    assert (h.first, h.last, h.gaps) == (_hour(9, 1), _hour(9, 30, 23), (HOURLY_GAP,))
    assert h.with_value == 30 * 24 - 6
    assert (q.first, q.last, q.gaps, q.with_value) == (
        _hour(9, 1),
        _hour(9, 1, 23),
        (),
        24,
    )
    assert isinstance(h.first, datetime)
    assert h.first.utcoffset() == timedelta(0)


def test_read_series_index_of_october_holds_the_captured_hours(
    adapter: ObserwatorAdapter, tiers_store: Path
) -> None:
    """October's H runs to the last hour of 11 October, the captured answer's."""
    root = data_root(tiers_store)

    variables = _variables(adapter, root, f"series:{SUBDAILY}:2026-10", RABA)

    assert (variables["H"].first, variables["H"].last) == (
        _hour(10, 1),
        _hour(10, 11, 23),
    )
    assert variables["H"].gaps == ()


def test_read_series_index_of_a_weekly_series_gives_the_dates_of_its_readings(
    adapter: ObserwatorAdapter, tiers_store: Path
) -> None:
    """ČHMÚ's weekly groundwater: unit ``week``, one version, readings as dates."""
    root = data_root(tiers_store)

    listing = adapter.read_series_index(
        root, _current(adapter, root, f"series:{WEEKLY}")
    )
    variables = _variables(adapter, root, f"series:{WEEKLY}", BORE)

    assert (listing.time_unit, listing.month, listing.kind) == (
        "week",
        None,
        "groundwater",
    )
    assert {station.code for station in listing.stations} == {BORE, SPRING}
    h = variables["H_asl"]
    assert (h.first, h.last) == (date(2012, 1, 1), date(2012, 12, 23))
    assert not isinstance(h.first, datetime)


def test_each_version_carries_the_tier_and_publication_of_its_sidecar(
    adapter: ObserwatorAdapter, tiers_store: Path
) -> None:
    """Telemetry, operational data public and private; the archive records none."""
    found: dict[str, set[tuple[str | None, str | None]]] = {}
    for _, meta in _metas(adapter, tiers_store):
        found.setdefault(str(meta.dataset_key), set()).add(
            (meta.tier, meta.publication)
        )

    marked = {key: states for key, states in found.items() if states != {(None, None)}}

    assert marked == {
        TELEMETRY: {("telemetry", "public")},
        RECENT: {("operational", "public")},
        OPERATIONAL: {("operational", "private")},
        SUBDAILY: {("operational", "private")},
    }
    months = [
        meta
        for slot, meta in _metas(adapter, tiers_store)
        if slot.startswith(f"series:{SUBDAILY}:")
    ]
    assert [meta.data_year for meta in months] == [2026, 2026]


def test_a_groundwater_station_keeps_its_kind_and_location_source(
    adapter: ObserwatorAdapter, tiers_store: Path
) -> None:
    """The bore and the spring: kind ``groundwater``, their object and source."""
    root = data_root(tiers_store)

    stations = adapter.read_stations(root, _current(adapter, root, CZ_CATALOG))

    groundwater = {
        station.code: (station.kind, station.groundwater_kind, station.location_source)
        for station in stations
        if station.groundwater_kind is not None or station.kind == "groundwater"
    }
    assert groundwater == {
        BORE: ("groundwater", "bore", "cz.chmu.groundwater_now"),
        SPRING: ("groundwater", "spring", "cz.chmu.groundwater_now"),
    }


def test_the_groundwater_characteristics_are_archives_without_a_series(
    adapter: ObserwatorAdapter, tiers_store: Path
) -> None:
    """One archive version per object, and no slot of a series names them."""
    metas = _metas(adapter, tiers_store)

    slots = sorted(slot for slot, meta in metas if meta.dataset_key == CHARACTERISTIC)

    assert slots == [
        f"archive:{CHARACTERISTIC}:GCHAR_{SPRING}.json",
        f"archive:{CHARACTERISTIC}:GCHAR_{BORE}.json",
    ]
    assert all(adapter.series_dataset(slot) is None for slot in slots)
    assert CHARACTERISTIC not in {adapter.series_dataset(slot) for slot, _ in metas}
