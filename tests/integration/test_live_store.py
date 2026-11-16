r"""The index of Kartograf's live 0.8.0 store equals ``iter_store`` (SPEC 13 v0.1).

Criterion 1 of v0.1: the store written by Kartograf's live release test
(``<katalog-danych>/data``, Kartograf
``docs/research/2026-10-17-release-0.8.0-live``) gives an index with the same
versions, links, ``full_sheet/`` links and problems as ``kartograf.iter_store``,
segments as ``describe_segment`` names them and the dataset keys of every
sidecar — those written by development releases too. Run deliberately, on
the store itself (several stores separated by ``os.pathsep``)::

    ARCHIWISTA_LIVE_STORE=<katalog-danych>/data \\
        .venv/bin/python -m pytest -m live tests/integration/test_live_store.py \\
        --no-cov

The store is only read: a full and an unchanged incremental scan go into an
index in the test directory, and the store's tree (names, sizes,
modification times) is the same afterwards.
"""

import os
from pathlib import Path

import kartograf
import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.config import AppSettings, StoreConfig
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    SlotQuery,
    initialize,
    scan_store,
)
from archiwista.sources.registry import load_registry

# A JPEG sheet's header has no geotransform (its outline comes from the world
# file); rasterio says so while the footprint is read.
pytestmark = [
    pytest.mark.live,
    pytest.mark.filterwarnings("ignore:Dataset has no geotransform"),
]

STORE = "zywy"

# (kind, segment, path, version path, problem): ``path`` is the slot (the
# standard path) of a link or full sheet, the file of a version or problem;
# a version's own path is its version path, as ``iter_store`` gives it.
type Entry = tuple[str, str | None, str, str | None, str | None]
# Segment → (product, country, dataset key, recognised).
type Segments = dict[str, tuple[str | None, str | None, str | None, bool]]
# Version path → (dataset, dataset key, SHA-256).
type Keys = dict[str, tuple[str | None, str | None, str | None]]


def _stores() -> list[Path]:
    variable = os.environ.get("ARCHIWISTA_LIVE_STORE", "")
    stores = [Path(item) for item in variable.split(os.pathsep) if item]
    if not stores:
        pytest.skip("ARCHIWISTA_LIVE_STORE names the live store's data/ directory")
    return stores


def _tree(directory: Path) -> dict[str, tuple[int, int]]:
    found = {}
    for top, dirnames, filenames in os.walk(directory):
        for name in [*dirnames, *filenames]:
            info = os.lstat(os.path.join(top, name))
            found[os.path.relpath(os.path.join(top, name), directory)] = (
                info.st_size,
                info.st_mtime_ns,
            )
    return found


def _relative(path: str | Path | None, root: Path) -> str | None:
    return None if path is None else Path(path).relative_to(root).as_posix()


def _kartograf_view(root: Path) -> tuple[set[Entry], Segments, Keys]:
    """Return what Kartograf's public reader sees in the store."""
    entries: set[Entry] = set()
    keys: Keys = {}
    for entry in kartograf.iter_store(root):
        path = _relative(entry.path, root)
        assert path is not None
        version = _relative(entry.version_path, root)
        if entry.kind == "full_sheet":
            # The index keeps a full sheet on its slot, the standard path.
            path = Path(entry.segment, entry.hierarchy, entry.name).as_posix()
        entries.add((entry.kind, entry.segment, path, version, entry.problem))
        if entry.kind == "version" and entry.sidecar is not None:
            sidecar = entry.sidecar
            keys[path] = (sidecar.dataset, sidecar.dataset_key, sidecar.sha256)
    segments: Segments = {}
    for name in kartograf.list_segments(root):
        info = kartograf.describe_segment(name)
        segments[name] = (info.product, info.country, info.dataset_key, info.known)
    return entries, segments, keys


def _index_view(queries: IndexQueries) -> tuple[set[Entry], Segments, Keys]:
    """Return what the index holds about the store."""
    slots: dict[str, str | None] = {}
    cursor = None
    while True:
        page = queries.slots(
            SlotQuery(store=STORE, versions="all", limit=200, cursor=cursor),
            visible=ALL_PROJECTS,
        )
        slots.update((row.slot, row.segment.segment) for row in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    entries: set[Entry] = set()
    keys: Keys = {}
    for slot, segment in slots.items():
        card = queries.slot(STORE, slot, visible=ALL_PROJECTS)
        assert card is not None, slot
        if card.current is not None:
            entries.add(("link", segment, slot, card.current, None))
        if card.full_sheet is not None:
            entries.add(("full_sheet", segment, slot, card.full_sheet, None))
        for version in card.versions:
            assert version.state == "present", version
            entries.add(("version", segment, version.path, version.path, None))
            detail = queries.version(STORE, version.path, visible=ALL_PROJECTS)
            assert detail is not None, version.path
            keys[version.path] = (detail.dataset, detail.dataset_key, version.sha256)
    for issue in queries.issues(STORE):
        assert issue.origin == "scan", issue
        entries.add(("problem", issue.segment, issue.path, None, issue.code))
    segments: Segments = {
        item.segment.segment: (
            item.segment.product,
            item.segment.country,
            item.segment.dataset_key,
            item.segment.known,
        )
        for product in queries.products(store=STORE)
        for item in product.segments
        if item.segment.segment is not None
    }
    return entries, segments, keys


def test_index_matches_iter_store_on_live_store(tmp_path: Path) -> None:
    """Versions, links, problems, segments and keys as Kartograf reads them."""
    for number, root in enumerate(_stores()):
        # Arrange
        before = _tree(root)
        index = tmp_path / f"index-{number}.sqlite"
        config = StoreConfig(id=STORE, name="Żywy", kartograf=root, kind="share")
        settings = AppSettings(stores=(config,))
        adapter = load_registry(cache_dir=tmp_path / f"cache-{number}").adapter(
            "kartograf"
        )
        initialize(index)

        # Act
        with IndexWriter(index) as writer:
            writer.sync_stores({STORE: config.roots()})
            full = scan_store(adapter, writer, settings, STORE, mode="full")
            again = scan_store(adapter, writer, settings, STORE)
        with IndexQueries(index) as queries:
            indexed, indexed_segments, indexed_keys = _index_view(queries)
        expected, segments, keys = _kartograf_view(root)

        # Assert
        assert indexed == expected, root
        # Segments without any entry need no row in the index.
        assert indexed_segments == {
            name: info
            for name, info in segments.items()
            if any(entry[1] == name for entry in expected)
        }, root
        assert indexed_keys == keys, root
        assert full.versions_written == len(keys), root
        assert (again.versions_written, again.links_changed) == (0, 0), root
        assert again.finished.missing == 0, root
        assert _tree(root) == before, root
