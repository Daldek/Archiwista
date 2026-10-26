"""Contract of the station catalogs of IMGWTools behind ``StationCatalogAdapter``.

The IMGW adapter names a provider's station catalog by the producer's own slot
key and reads a catalog version with ``imgwtools.read_catalog``: what it gives
must be what the producer itself reads in its offline fixture stores
(``imgwtools.testing``), stations without a location included with their
reason, and a version the producer refuses is its error, never stations.
"""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from imgwtools import iter_store, providers, read_catalog

from archiwista.adapter.imgw import load
from archiwista.adapter.imgw.adapter import ImgwAdapter
from archiwista.adapter.kartograf import load as load_kartograf
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.sources import SourceContext, Station, StationCatalogAdapter

type Stores = Callable[[str], Path]

PL_CATALOG = "catalog:pl.imgw.stations"
CZ_CATALOG = "catalog:cz.chmi.stations"


@pytest.fixture
def adapter(tmp_path: Path) -> ImgwAdapter:
    """Create the adapter with its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "imgw"))
    assert isinstance(created, ImgwAdapter)
    return created


def _catalog_version(adapter: ImgwAdapter, root: Path, key: str) -> Path:
    """Return the current version of a provider's catalog, relative to the store."""
    version = adapter.current_version(root, key)
    assert version is not None
    return version


def _copy(imgw_store: Stores, root: Path) -> Path:
    shutil.copytree(imgw_store("complete_pl_cz"), root)
    return root


def test_only_the_imgw_adapter_has_station_catalogs(
    adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """The capability is optional: Kartograf keeps no station catalog."""
    kartograf = load_kartograf(SourceContext(cache_dir=tmp_path / "cache" / "k"))

    assert isinstance(adapter, StationCatalogAdapter)
    assert not isinstance(kartograf, StationCatalogAdapter)


def test_each_provider_of_the_registry_has_its_catalog_slot(
    adapter: ImgwAdapter,
) -> None:
    """``catalog:<key prefix>.stations`` is the catalog of the provider it names."""
    named = {
        adapter.station_catalog(f"catalog:{provider.key_prefix}.stations"): str(
            provider.id
        )
        for provider in providers()
    }

    assert named == {"IMGW-PIB": "IMGW-PIB", "CHMI": "CHMI"}
    assert adapter.station_catalog(PL_CATALOG) == "IMGW-PIB"
    assert adapter.station_catalog(CZ_CATALOG) == "CHMI"


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_the_catalog_slots_are_the_producers_catalogs_and_nothing_else(
    imgw_store: Stores, adapter: ImgwAdapter, variant: str
) -> None:
    """Every slot of ``iter_store``: a catalog names its provider, others none."""
    root = imgw_store(variant)
    slots = {
        entry.slot: (entry.kind, entry.provider)
        for entry in iter_store(root)
        if entry.slot is not None and entry.kind != "problem"
    }

    named = {slot: adapter.station_catalog(slot) for slot in slots}

    assert any(kind == "catalog" for kind, _ in slots.values())
    assert named == {
        slot: provider if kind == "catalog" else None
        for slot, (kind, provider) in slots.items()
    }


@pytest.mark.parametrize(
    ("key", "count"), [(PL_CATALOG, 6), (CZ_CATALOG, 7)], ids=["imgw", "chmi"]
)
def test_read_stations_gives_every_station_the_producer_reads(
    imgw_store: Stores, adapter: ImgwAdapter, key: str, count: int
) -> None:
    """Codes as text in the catalog's order, points and reasons as the producer's."""
    root = imgw_store("complete_pl_cz")
    version = _catalog_version(adapter, root, key)
    features = read_catalog(root / version)

    stations = adapter.read_stations(root, version)

    assert len(stations) == count
    assert [(s.provider, s.code, s.point) for s in stations] == [
        (f.provider, f.station_code, f.geometry) for f in features
    ]
    assert [s.location_reason for s in stations] == [
        f.properties.get("location_missing_reason") for f in features
    ]
    assert {s.provider for s in stations} == {adapter.station_catalog(key)}
    assert all((s.point is None) == (s.location_reason is not None) for s in stations)


def test_a_station_keeps_the_fields_of_the_catalog(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """Kind, river, hydrographic code and order, location source and uncertainty."""
    root = imgw_store("complete_pl_cz")

    imgw = {
        s.code: s
        for s in adapter.read_stations(
            root, _catalog_version(adapter, root, PL_CATALOG)
        )
    }
    chmi = {
        s.code: s
        for s in adapter.read_stations(
            root, _catalog_version(adapter, root, CZ_CATALOG)
        )
    }

    assert imgw["149190310"] == Station(
        provider="IMGW-PIB",
        code="149190310",
        kind="hydro",
        name="Raba Górna",
        river="Raba",
        hydrographic_code="213",
        river_order=12,
        point=(20.1, 49.7),
        location_source="api_hydro",
        location_uncertainty_m=5566.0,
        active=True,
    )
    assert (imgw["123760000"].kind, imgw["123760000"].meteo_kind) == (
        "meteo",
        "precipitation",
    )
    assert {code: s.location_reason for code, s in imgw.items() if s.point is None} == {
        "123760000": "none",
        "149190311": "zero",
        "149190312": "none",
        "149190313": "outside_country",
    }
    hydro = chmi["0-203-1-900001"]
    assert (hydro.kind, hydro.river, hydro.hydrographic_code) == (
        "hydro",
        "Labe",
        "1-05-03-0110",
    )
    meteo = chmi["0-203-0-90001"]
    assert (meteo.meteo_kind, meteo.established_year, meteo.elevation_m) == (
        None,
        1961,
        318.5,
    )
    assert chmi["0-203-1-900002"].active is False


def test_a_version_unlike_its_sidecar_is_the_producers_error(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """Same size, other bytes: IMGWTools refuses it and no station comes out."""
    root = _copy(imgw_store, tmp_path / "store")
    version = _catalog_version(adapter, root, PL_CATALOG)
    path = root / version
    data = path.read_bytes()
    assert b"Warszawa" in data
    path.write_bytes(data.replace(b"Warszawa", b"Warszawb"))

    with pytest.raises(ProducerError) as raised:
        adapter.read_stations(root, version)

    assert raised.value.package == "imgwtools"


def test_a_file_that_is_no_catalog_is_the_producers_error(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """A series listing is not a station catalog."""
    root = imgw_store("complete")
    series = adapter.current_version(root, "series:pl.imgw.hydro_daily")
    assert series is not None

    with pytest.raises(ProducerError):
        adapter.read_stations(root, series)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads any file"
)
def test_a_catalog_the_system_cannot_read_is_an_unavailable_store(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """A file without read permission is no verdict of the producer."""
    root = _copy(imgw_store, tmp_path / "store")
    version = _catalog_version(adapter, root, CZ_CATALOG)
    path = root / version
    path.chmod(0)
    try:
        with pytest.raises(SourceUnavailableError):
            adapter.read_stations(root, version)
    finally:
        path.chmod(0o644)
