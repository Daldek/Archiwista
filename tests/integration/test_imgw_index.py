"""Archives, series and catalogs of an IMGWTools store in the local index (plan I3).

Every test scans a fixture store of the producer's own builder
(``imgwtools.testing``) through the real adapter, offline, and asks the index
with ``IndexQueries``: what it holds must be what ``imgwtools.iter_store``
yields, with the datasets named from the producer's registry.
"""

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest
from imgwtools import StoreEntry, iter_store

from archiwista.auth import ALL_PROJECTS
from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexQueries, IndexWriter, SlotQuery
from archiwista.index.scanner import ScanMode, ScanSummary, scan_store
from archiwista.sources import SourceAdapter
from archiwista.sources.registry import load_registry

STORE = "dane"
HYDRO_SLOT = "archives/versions/dane_hydrologiczne/dobowe/2024/codz_2024"

type Stores = Callable[[str], Path]


@dataclass
class _Env:
    """A store of IMGWTools with an index that knows it."""

    root: Path
    index: Path
    adapter: SourceAdapter
    writer: IndexWriter
    queries: IndexQueries
    settings: AppSettings

    def scan(self, mode: ScanMode = "incremental") -> ScanSummary:
        return scan_store(self.adapter, self.writer, self.settings, STORE, mode=mode)

    def versions(self) -> set[str]:
        """Return the path of every version the catalog lists."""
        found: set[str] = set()
        cursor = None
        while True:
            page = self.queries.slots(
                SlotQuery(versions="all", limit=200, cursor=cursor),
                visible=ALL_PROJECTS,
            )
            found.update(row.version.path for row in page.items if row.version)
            cursor = page.next_cursor
            if cursor is None:
                return found

    def issues(self) -> set[tuple[str, str]]:
        """Return ``(code, path)`` of every problem of the store."""
        return {(issue.code, issue.path) for issue in self.queries.issues(STORE)}

    def sql(self, statement: str) -> list[tuple[object, ...]]:
        """Return the rows of a statement on the index file."""
        with closing(sqlite3.connect(self.index)) as connection:
            return [tuple(row) for row in connection.execute(statement)]


@pytest.fixture
def open_env(imgw_store: Stores, tmp_path: Path) -> Iterator[Callable[[str], _Env]]:
    """Return ``open(variant)``: a private copy of a fixture store with its index."""
    writers: list[IndexWriter] = []
    readers: list[IndexQueries] = []

    def open_(variant: str) -> _Env:
        root = tmp_path / f"store-{variant}"
        shutil.copytree(imgw_store(variant), root)
        index = tmp_path / f"index-{variant}.sqlite"
        writer = IndexWriter(index)
        writers.append(writer)
        reader = IndexQueries(index)
        readers.append(reader)
        config = StoreConfig(id=STORE, name="Dane", imgw=root, kind="local")
        writer.sync_stores({STORE: config.roots()})
        registry = load_registry(cache_dir=tmp_path / "cache")
        return _Env(
            root,
            index,
            registry.adapter("imgw"),
            writer,
            reader,
            AppSettings(stores=(config,)),
        )

    yield open_
    for reader in readers:
        reader.close()
    for writer in writers:
        writer.close()


def _produced(root: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """Return the versions and the problems ``iter_store`` finds in a store."""
    versions: set[str] = set()
    problems: set[tuple[str, str]] = set()
    for entry in iter_store(root):
        if entry.version is None:
            continue
        path = entry.version.relative_to(root).as_posix()
        if entry.kind == "problem":
            problems.add((entry.problem_code or "unknown", path))
        elif entry.kind != "observation":
            versions.add(path)
    return versions, problems


@pytest.mark.parametrize(
    "variant", ["complete", "complete_pl_cz", "corrupt", "unknown_schema"]
)
def test_the_index_agrees_with_iter_store_in_versions_and_problems(
    open_env: Callable[[str], _Env], variant: str
) -> None:
    """SPEC 13 v0.5, criterion 1: every version and problem, and nothing else."""
    # Arrange
    env = open_env(variant)
    versions, problems = _produced(env.root)

    # Act
    first = env.scan("full")
    again = env.scan()

    # Assert
    assert versions and env.versions() == versions
    assert env.issues() == problems
    assert first.versions_written == len(versions)
    assert (again.versions_written, again.links_changed, again.issues_added) == (
        0,
        0,
        0,
    )
    assert env.versions() == versions and env.issues() == problems


def test_a_segment_is_a_dataset_named_by_the_registry_with_its_country(
    open_env: Callable[[str], _Env],
) -> None:
    """The scan describes each dataset its entries named: a producer lists none."""
    # Arrange
    env = open_env("complete_pl_cz")

    # Act
    env.scan("full")
    segments = {
        found.segment: found
        for product in env.queries.products(store=STORE)
        for found in (summary.segment for summary in product.segments)
    }

    # Assert
    datasets = {
        entry.slot.split(":")[1] for entry in iter_store(env.root) if entry.slot
    }
    assert set(segments) == datasets and datasets
    hydro = segments["pl.imgw.hydro_daily"]
    assert (hydro.name, hydro.country, hydro.dataset_key, hydro.known) == (
        "Dane hydrologiczne dobowe",
        "PL",
        "pl.imgw.hydro_daily",
        True,
    )
    czech_catalog = segments["cz.chmi.stations"]
    assert (czech_catalog.name, czech_catalog.country) == (
        "Katalog stacji ČHMÚ",
        "CZ",
    )
    assert all(found.known and found.product is None for found in segments.values())
    assert {found.country for found in segments.values()} == {"PL", "CZ"}


def test_a_slot_keeps_its_key_a_name_for_people_and_its_versions_a_provider(
    open_env: Callable[[str], _Env],
) -> None:
    """The index keeps what the producer calls a slot, and who publishes the data."""
    # Arrange
    env = open_env("complete_pl_cz")

    # Act
    env.scan("full")
    keys = {
        path: (name, key)
        for path, name, key in env.sql("SELECT path, name, slot_key FROM slots")
    }
    providers = {
        str(path): provider
        for path, provider in env.sql("SELECT path, provider FROM versions")
    }

    # Assert
    assert keys[HYDRO_SLOT] == (
        "codz_2024.zip",
        "archive:pl.imgw.hydro_daily:2024/codz_2024.zip",
    )
    assert keys["series/versions/hydro_daily"] == (
        "hydro_daily",
        "series:pl.imgw.hydro_daily",
    )
    assert keys["stations/versions"] == ("pl.imgw.stations", "catalog:pl.imgw.stations")
    assert keys["stations/versions/chmi_stations"] == (
        "cz.chmi.stations",
        "catalog:cz.chmi.stations",
    )
    assert {key for _, key in keys.values()} == {
        entry.slot for entry in iter_store(env.root) if entry.slot
    }
    by_producer = {
        entry.version.relative_to(env.root).as_posix(): entry.provider
        for entry in iter_store(env.root)
        if entry.version and entry.kind not in ("problem", "observation")
    }
    assert providers == by_producer
    assert set(providers.values()) == {"IMGW-PIB", "CHMI"}


def _register(root: Path) -> tuple[StoreEntry, StoreEntry]:
    """Return the producer's observation and the version whose content it repeats."""
    entries = list(iter_store(root))
    (observed,) = [e for e in entries if e.kind == "observation"]
    assert observed.observation is not None
    (repeated,) = [
        e
        for e in entries
        if e.kind == "archive"
        and e.slot == observed.slot
        and e.version is not None
        and e.version.parent.name == observed.observation.same_content_as
    ]
    return observed, repeated


def _relative(root: Path, entry: StoreEntry) -> str:
    assert entry.version is not None
    return entry.version.relative_to(root).as_posix()


def test_an_observation_is_the_history_of_its_slot_and_changes_no_count(
    open_env: Callable[[str], _Env],
) -> None:
    """A register file is kept with its record; no version, count or issue follows."""
    # Arrange
    env = open_env("complete_pl_cz")
    produced, _ = _produced(env.root)
    observed, repeated = _register(env.root)
    slot = Path(_relative(env.root, repeated)).parent.parent.as_posix()

    # Act
    first = env.scan("full")
    history = env.queries.observations(STORE, slot)
    detail = env.queries.slot(STORE, slot, visible=ALL_PROJECTS)
    again = env.scan()

    # Assert
    (record,) = history
    kept = observed.observation
    assert kept is not None
    assert record.path == _relative(env.root, observed)
    assert record.version == _relative(env.root, repeated)
    assert record.seen_at.isoformat() == kept.seen_at.replace("Z", "+00:00")
    assert (record.url, record.etag, record.last_modified) == (
        kept.url,
        kept.etag,
        kept.last_modified,
    )
    assert (record.size_bytes, record.sha256) == (kept.size_bytes, kept.sha256)
    assert detail is not None
    assert [v.path for v in detail.versions] == [_relative(env.root, repeated)]
    assert first.versions_written == len(produced)
    assert env.versions() == produced
    assert sum(p.versions for p in env.queries.products()) == len(produced)
    assert env.queries.issues(STORE) == ()
    assert env.queries.observations(STORE, "series/versions/hydro_daily") == ()
    assert env.queries.observations(STORE, "no/such/slot") == ()
    assert env.queries.observations(STORE, slot) == history
    assert again.versions_written == 0


def test_an_observation_the_producer_no_longer_lists_is_forgotten(
    open_env: Callable[[str], _Env],
) -> None:
    """The history is the register as the last pass saw it, not what the index kept."""
    # Arrange
    env = open_env("complete_pl_cz")
    observed, repeated = _register(env.root)
    slot = Path(_relative(env.root, repeated)).parent.parent.as_posix()
    env.scan("full")
    assert env.queries.observations(STORE, slot)
    assert observed.version is not None
    observed.version.unlink()

    # Act
    env.scan()

    # Assert
    assert env.queries.observations(STORE, slot) == ()
    detail = env.queries.slot(STORE, slot, visible=ALL_PROJECTS)
    assert detail is not None
    assert [v.path for v in detail.versions] == [_relative(env.root, repeated)]
