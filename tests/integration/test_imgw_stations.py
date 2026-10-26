"""Stations of the IMGWTools station catalogs in the local index (plan I4).

Every test scans a copy of a fixture store of the producer's own builder
(``imgwtools.testing``) through the real adapter, offline. The index holds the
stations of the current version of each provider's catalog: every station of
it, those without a location with the catalog's reason, a point for the
others, and a new current version replaces them.
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

import pytest
from imgwtools import current_version, read_catalog

from archiwista.config import AppSettings, StoreConfig
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.index import IndexQueries, IndexWriter, ScanEvent, ScanNotice
from archiwista.index.scanner import ScanMode, ScanSummary, scan_store
from archiwista.sources import SourceAdapter, Station, StationCatalogAdapter
from archiwista.sources.registry import load_registry

STORE = "dane"
PL_KEY = "catalog:pl.imgw.stations"
CZ_KEY = "catalog:cz.chmi.stations"
PL_SLOT = "stations/versions"
CATALOG = "stations.geojson"
META = ".meta.json"
_ROWS = (
    "SELECT provider, code, kind, name, river, hydrographic_code, location,"
    " location_reason, lon, lat FROM stations ORDER BY provider, code"
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

    def catalogs_adapter(self) -> StationCatalogAdapter:
        assert isinstance(self.adapter, StationCatalogAdapter)
        return self.adapter

    def sql(self, statement: str, *params: object) -> list[Row]:
        with closing(sqlite3.connect(self.index)) as connection:
            return [tuple(row) for row in connection.execute(statement, params)]

    def stations(self, provider: str) -> dict[str, Row]:
        """Return ``code -> (location, reason, lon, lat)`` of a provider's rows."""
        return {
            str(code): (location, reason, lon, lat)
            for code, location, reason, lon, lat in self.sql(
                "SELECT code, location, location_reason, lon, lat FROM stations"
                " WHERE provider = ?",
                provider,
            )
        }

    def point_count(self) -> int:
        (count,) = self.sql(
            "SELECT count(*) FROM station_points p JOIN stations s ON s.id = p.id"
            " WHERE s.location = 'point' AND p.min_lon <= s.lon AND s.lon <= p.max_lon"
            " AND p.min_lat <= s.lat AND s.lat <= p.max_lat"
        )[0]
        assert isinstance(count, int)
        return count

    def located_count(self) -> int:
        (count,) = self.sql("SELECT count(*) FROM stations WHERE location = 'point'")[0]
        assert isinstance(count, int)
        return count

    def catalogs(self) -> dict[str, str]:
        """Return the catalog version each provider's rows were read from."""
        return {
            str(provider): str(version)
            for provider, version in self.sql(
                "SELECT provider, version_path FROM station_catalogs"
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


def _catalog(root: Path, key: str) -> dict[str, Row]:
    """Return what ``read_catalog`` reads in the current version of a catalog."""
    found = current_version(root, slot=key)
    assert found is not None and found.version is not None
    return {
        feature.station_code: (
            "none" if feature.geometry is None else "point",
            feature.properties.get("location_missing_reason"),
            None if feature.geometry is None else feature.geometry[0],
            None if feature.geometry is None else feature.geometry[1],
        )
        for feature in read_catalog(found.version)
    }


def _publish(
    root: Path, slot: str, edit: Callable[[list[dict[str, object]]], None]
) -> str:
    """Write a newer version of a catalog with edited stations, as a download does.

    The version directory is ``<label>_<sha8>`` with the edited GeoJSON and its
    sidecar (SHA-256, size, label, a later download), so IMGWTools takes it as
    the current version. Returns its file relative to the store.
    """
    directory = root / slot
    source = max(
        path
        for path in directory.iterdir()
        if path.is_dir() and (path / CATALOG).is_file()
    )
    document = json.loads((source / CATALOG).read_text(encoding="utf-8"))
    edit(document["features"])
    data = json.dumps(document, ensure_ascii=False).encode()
    sha256 = hashlib.sha256(data).hexdigest()
    sidecar = json.loads((source / (CATALOG + META)).read_text(encoding="utf-8"))
    downloaded = datetime.fromisoformat(sidecar["downloaded_at"]) + timedelta(days=1)
    label = downloaded.date().isoformat()
    sidecar.update(
        sha256=sha256,
        size_bytes=len(data),
        downloaded_at=downloaded.isoformat().replace("+00:00", "Z"),
    )
    sidecar["extra"]["version"]["label"] = label
    target = directory / f"{label}_{sha256[:8]}"
    target.mkdir()
    (target / CATALOG).write_bytes(data)
    (target / (CATALOG + META)).write_text(json.dumps(sidecar), encoding="utf-8")
    return f"{slot}/{target.name}/{CATALOG}"


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_the_index_holds_every_station_of_each_current_catalog(
    open_env: Callable[[str], _Env], variant: str
) -> None:
    """Row count and locations equal the catalog's; a point for each located one."""
    # Arrange
    env = open_env(variant)
    keys = {"IMGW-PIB": PL_KEY}
    if variant == "complete_pl_cz":
        keys["CHMI"] = CZ_KEY

    # Act
    env.scan("full")

    # Assert
    for provider, key in keys.items():
        assert env.stations(provider) == _catalog(env.root, key)
    assert set(env.catalogs()) == set(keys)
    assert env.point_count() == env.located_count() > 0
    assert env.notices() == []


def test_stations_without_a_location_are_kept_with_the_catalogs_reason(
    open_env: Callable[[str], _Env],
) -> None:
    """P13, A-ADR-022: none, zero and outside_country stay, never as a point."""
    # Arrange
    env = open_env("complete_pl_cz")

    # Act
    env.scan("full")

    # Assert
    unlocated = {
        str(code): reason
        for code, reason, lon, lat in env.sql(
            "SELECT code, location_reason, lon, lat FROM stations"
            " WHERE location = 'none'"
        )
        if lon is None and lat is None
    }
    assert unlocated == {
        "123760000": "none",
        "149190311": "zero",
        "149190312": "none",
        "149190313": "outside_country",
        "0-20000-0-99903": "outside_country",
    }
    assert env.sql(
        "SELECT count(*) FROM station_points p JOIN stations s ON s.id = p.id"
        " WHERE s.location = 'none'"
    ) == [(0,)]


def test_a_new_catalog_version_replaces_the_providers_rows(
    open_env: Callable[[str], _Env],
) -> None:
    """A newer current version is read again and its stations replace the old."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    czech = env.stations("CHMI")

    def edit(features: list[dict[str, object]]) -> None:
        features[:] = [f for f in features if f["id"] != "149190313"]
        moved = next(f for f in features if f["id"] == "123760000")
        moved["geometry"] = {"type": "Point", "coordinates": [21.5, 52.5]}
        properties = moved["properties"]
        assert isinstance(properties, dict)
        properties.update(location_missing_reason=None, location_source="user")

    published = _publish(env.root, PL_SLOT, edit)

    # Act
    env.scan()

    # Assert
    assert env.catalogs()["IMGW-PIB"] == published
    polish = env.stations("IMGW-PIB")
    assert polish == _catalog(env.root, PL_KEY)
    assert "149190313" not in polish
    assert polish["123760000"] == ("point", None, 21.5, 52.5)
    assert env.point_count() == env.located_count()
    assert env.stations("CHMI") == czech


def test_an_unchanged_catalog_is_read_again_only_by_a_full_scan(
    open_env: Callable[[str], _Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The version its rows came from is current: an incremental scan reads none."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    catalogs = env.catalogs_adapter()
    read: list[str] = []
    original = catalogs.read_stations

    def counted(root: Path, version: Path) -> tuple[Station, ...]:
        read.append(version.as_posix())
        return original(root, version)

    monkeypatch.setattr(catalogs, "read_stations", counted)
    before = env.sql(_ROWS)

    # Act
    env.scan()
    incremental = list(read)
    env.scan("full")

    # Assert
    assert incremental == []
    assert sorted(read) == sorted(env.catalogs().values())
    assert env.sql(_ROWS) == before
    assert env.point_count() == env.located_count()


def test_a_catalog_without_a_current_version_leaves_its_provider_no_stations(
    open_env: Callable[[str], _Env],
) -> None:
    """The catalog's only version is gone: its stations go, the others stay."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    czech = env.stations("CHMI")
    shutil.rmtree((env.root / env.catalogs()["IMGW-PIB"]).parent)

    # Act
    env.scan("full")

    # Assert
    assert env.stations("IMGW-PIB") == {}
    assert set(env.catalogs()) == {"CHMI"}
    assert env.stations("CHMI") == czech
    assert env.point_count() == env.located_count()


def test_a_catalog_the_producer_refuses_is_said_and_holds_no_stations(
    open_env: Callable[[str], _Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ProducerError of one catalog: a notice, its rows gone, the scan goes on."""
    # Arrange
    env = open_env("complete_pl_cz")
    env.scan("full")
    czech = env.stations("CHMI")
    refused = env.catalogs()["IMGW-PIB"]
    catalogs = env.catalogs_adapter()
    original = catalogs.read_stations

    def refusing(root: Path, version: Path) -> tuple[Station, ...]:
        if version.as_posix() == refused:
            raise ProducerError("imgwtools", "IMGWDataError", "catalog broken")
        return original(root, version)

    monkeypatch.setattr(catalogs, "read_stations", refusing)

    # Act
    env.scan("full")

    # Assert
    (notice,) = env.notices()
    assert (notice.level, notice.code) == ("warning", "stations_unreadable")
    assert "IMGW-PIB" in notice.message and "catalog broken" in notice.message
    assert refused in notice.message
    assert env.stations("IMGW-PIB") == {}
    assert set(env.catalogs()) == {"CHMI"}
    assert env.stations("CHMI") == czech


def test_a_catalog_the_system_cannot_read_makes_the_store_unavailable(
    open_env: Callable[[str], _Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SourceUnavailableError ends the scan and keeps the rows the index had."""
    # Arrange
    env = open_env("complete")
    env.scan("full")
    before = env.stations("IMGW-PIB")

    def unreadable(root: Path, version: Path) -> tuple[Station, ...]:
        raise SourceUnavailableError("share gone")

    monkeypatch.setattr(env.catalogs_adapter(), "read_stations", unreadable)

    # Act
    with pytest.raises(SourceUnavailableError):
        env.scan("full")

    # Assert
    with IndexQueries(env.index) as queries:
        (state,) = queries.status().stores
    assert state.status == "unavailable"
    assert env.stations("IMGW-PIB") == before


def test_two_providers_never_collide_on_a_code(open_env: Callable[[str], _Env]) -> None:
    """Identity is store, provider and code: one code in both catalogs is two rows."""
    # Arrange
    env = open_env("complete")
    env.scan("full")
    same = "149190310"

    # Act
    written = env.writer.replace_stations(
        STORE,
        "imgw",
        "CHMI",
        slot="stations/versions/chmi_stations",
        version="stations/versions/chmi_stations/x_00000000/stations.geojson",
        stations=[
            Station(provider="CHMI", code=same, kind="hydro", point=(15.0, 50.0)),
            Station(provider="CHMI", code="0-203-1-1", location_reason="none"),
            Station(provider="CHMI", code="0-203-1-1", point=(16.0, 49.0)),
        ],
    )

    # Assert
    assert written == 2
    rows = env.sql(
        "SELECT provider, lon, lat FROM stations WHERE code = ? ORDER BY provider",
        same,
    )
    assert rows == [("CHMI", 15.0, 50.0), ("IMGW-PIB", 20.1, 49.7)]
    assert env.stations("CHMI")["0-203-1-1"] == ("none", "none", None, None)
    assert env.point_count() == env.located_count()
    assert env.writer.drop_stations(STORE, "CHMI") == 2
    assert env.sql("SELECT provider FROM stations WHERE code = ?", same) == [
        ("IMGW-PIB",)
    ]
    assert env.point_count() == env.located_count()
