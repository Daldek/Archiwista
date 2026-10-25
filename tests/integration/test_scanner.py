"""Scans of a generated Kartograf store into the local index (plan step 6a).

Every test scans a fresh synthetic store through the real Kartograf adapter
(offline) and checks the index with ``IndexQueries``.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kartograf
import pytest

import archiwista.adapter.kartograf.adapter as kartograf_adapter
from archiwista.auth import ALL_PROJECTS
from archiwista.config import AppSettings, StoreConfig, StoreKind
from archiwista.errors import SourceUnavailableError
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    LocationRef,
    SlotDetail,
    SlotQuery,
    StoreIndexState,
    VersionSummary,
)
from archiwista.index.scanner import (
    REFRESH_VIEW_MAX_UNITS,
    ScanEvent,
    ScanMode,
    ScanProgress,
    ScanSummary,
    refresh_view,
    scan_store,
)
from archiwista.messages import localize
from archiwista.sources import (
    Footprint,
    GeoJSONGeometry,
    ScanScope,
    SourceAdapter,
    SourceEntry,
)
from archiwista.sources.registry import load_registry
from tests.fixtures.make_store import (
    LAZ,
    NMT,
    ExpectedEntry,
    StoreManifest,
    make_store,
)
from tests.fixtures.store_edits import (
    META_SUFFIX,
    add_version,
    remove_version,
    sidecar_path,
)

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

STORE = "zespol"
SLOTS = 24
SEED = 7

type _Dump = tuple[list[tuple[object, ...]], list[tuple[object, ...]]]


@dataclass
class _Env:
    """A generated store with its adapter, index and settings."""

    store: StoreManifest
    adapter: SourceAdapter
    writer: IndexWriter
    queries: IndexQueries
    settings: AppSettings

    def scan(self, mode: ScanMode = "incremental", **options: Any) -> ScanSummary:
        return scan_store(
            self.adapter, self.writer, self.settings, STORE, mode=mode, **options
        )

    def slot(self, slot: str) -> SlotDetail:
        detail = self.queries.slot(STORE, slot, visible=ALL_PROJECTS)
        assert detail is not None, slot
        return detail

    def version(self, slot: str, path: str) -> VersionSummary:
        return next(item for item in self.slot(slot).versions if item.path == path)

    def state(self) -> StoreIndexState:
        return next(s for s in self.queries.status().stores if s.store == STORE)


def _settings(
    store: StoreManifest, *, threads: int = 4, kind: StoreKind = "share"
) -> AppSettings:
    """Return settings with the store; a share is read by ``threads`` threads."""
    config = StoreConfig(id=STORE, name="Zespół", kartograf=store.root, kind=kind)
    return AppSettings(
        stores=(config,), project_dirs=(store.projects_dir,), scan_threads=threads
    )


def _adapter(tmp_path: Path) -> SourceAdapter:
    return load_registry(cache_dir=tmp_path / "cache").adapter("kartograf")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[_Env]:
    """Yield a fresh store with an empty index that knows it."""
    store = make_store(tmp_path / "store", slots=SLOTS, seed=SEED)
    path = tmp_path / "index.sqlite"
    with IndexWriter(path) as writer, IndexQueries(path) as queries:
        writer.sync_stores({STORE: {"kartograf": store.root}})
        yield _Env(store, _adapter(tmp_path), writer, queries, _settings(store))


def _versions(store: StoreManifest, link: ExpectedEntry) -> list[ExpectedEntry]:
    """Return the versions of a link's slot, oldest first."""
    name = Path(link.path).name
    return [
        entry
        for entry in store.by_kind("version")
        if entry.segment == link.segment
        and entry.hierarchy == link.hierarchy
        and Path(entry.path).name == name
    ]


def _removable(store: StoreManifest) -> dict[str, tuple[ExpectedEntry, ExpectedEntry]]:
    """Return regular slots by path with an old version nothing else needs.

    The old version is not current, not held by ``full_sheet/`` and pinned
    by no project.
    """
    held = {entry.version_path for entry in store.by_kind("full_sheet")}
    held |= {
        pin.version
        for project in store.projects
        for task in project.tasks
        for pin in task.pins
    }
    found = {}
    for link in store.by_kind("link"):
        if link.case != "regular":
            continue
        old = [
            entry
            for entry in _versions(store, link)
            if not entry.current and entry.path not in held
        ]
        if old:
            found[link.path] = (link, old[0])
    return found


def _rows(queries: IndexQueries) -> list[tuple[object, ...]]:
    """Return every version row of the catalog as a person sees it."""
    rows: list[tuple[object, ...]] = []
    cursor = None
    while True:
        page = queries.slots(
            SlotQuery(versions="all", limit=200, cursor=cursor), visible=ALL_PROJECTS
        )
        for row in page.items:
            version = row.version
            rows.append(
                (
                    row.slot,
                    row.status,
                    row.unit,
                    row.location,
                    None
                    if version is None
                    else (
                        version.path,
                        version.sha256,
                        version.label,
                        version.is_current,
                        version.is_full_sheet,
                        version.state,
                    ),
                )
            )
        cursor = page.next_cursor
        if cursor is None:
            return rows


def _issues(queries: IndexQueries) -> list[tuple[object, ...]]:
    return sorted(
        (issue.code, issue.path, issue.segment, issue.slot)
        for issue in queries.issues(STORE)
    )


def _dump(queries: IndexQueries) -> _Dump:
    """Return the catalog rows and problems of the index."""
    return _rows(queries), _issues(queries)


def _tree(directory: Path) -> dict[str, tuple[int, int, int]]:
    """Return every file and directory below ``directory``: size, mtime, inode."""
    found = {}
    for top, dirnames, filenames in os.walk(directory):
        for name in [*dirnames, *filenames]:
            path = os.path.join(top, name)
            info = os.lstat(path)
            found[os.path.relpath(path, directory)] = (
                info.st_size,
                info.st_mtime_ns,
                info.st_ino,
            )
    return found


def _make_tree_read_only(directory: Path, *, read_only: bool) -> None:
    for top, _, filenames in os.walk(directory):
        os.chmod(top, 0o555 if read_only else 0o755)
        for name in filenames:
            os.chmod(os.path.join(top, name), 0o444 if read_only else 0o644)


def _box(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> GeoJSONGeometry:
    ring = [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def test_full_then_incremental_detects_new_version_and_relinked_current(
    env: _Env,
) -> None:
    """A download after a full scan: new version indexed, standard path moved."""
    # Arrange
    link, old = next(iter(_removable(env.store).values()))
    env.scan("full")
    before = env.slot(link.path)

    # Act
    new = add_version(env.store.root, link.path, label="2026-05-01_99999")
    summary = env.scan("incremental")
    after = env.slot(link.path)

    # Assert
    assert before.current == link.version_path
    assert after.current == new
    assert (summary.versions_written, summary.links_changed) == (1, 1)
    assert summary.finished.missing == 0
    assert {item.path for item in after.versions} == {
        *(item.path for item in before.versions),
        new,
    }
    added = env.version(link.path, new)
    assert (added.label, added.is_current, added.state) == (
        "2026-05-01_99999",
        True,
        "present",
    )
    assert added.location.kind == "footprint"
    assert env.version(link.path, old.path).is_current is False


def test_incremental_does_not_reread_known_versions(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known versions are neither read again nor listed; link sidecars always are."""
    # Arrange
    root = env.store.root
    version_sidecars = {
        os.path.normpath(root / entry.path) + META_SUFFIX
        for entry in env.store.by_kind("version")
    }
    link_sidecars = {
        os.path.normpath(root / entry.path) + META_SUFFIX
        for entry in [*env.store.by_kind("link"), *env.store.by_kind("full_sheet")]
    }
    env.scan("full")
    opened: list[str] = []
    real_open = os.open

    def counting_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        name = os.fsdecode(path)
        if name.endswith(META_SUFFIX):
            opened.append(os.path.normpath(name))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", counting_open)

    # Act
    incremental = env.scan("incremental")
    read_incrementally = set(opened)
    opened.clear()
    env.scan("full")
    read_fully = set(opened)

    # Assert
    assert incremental.versions_written == 0
    assert read_incrementally & version_sidecars == set()
    assert link_sidecars <= read_incrementally
    assert version_sidecars <= read_fully


def test_missing_version_marked_then_removed_after_next_full_scan(
    env: _Env,
) -> None:
    """A vanished version is marked with its date; only a later full scan drops it."""
    # Arrange
    link, old = next(iter(_removable(env.store).values()))
    env.scan("full")
    remove_version(env.store.root, old.path)

    # Act
    marked = env.scan("full")
    missing = env.version(link.path, old.path)
    kept = env.scan("incremental")
    still_missing = env.version(link.path, old.path)
    removed = env.scan("full")

    # Assert
    assert (marked.finished.missing, marked.finished.removed) == (1, 0)
    assert missing.state == "missing" and missing.missing_since is not None
    assert (kept.finished.missing, kept.finished.removed) == (0, 0)
    assert still_missing.state == "missing"
    assert still_missing.missing_since == missing.missing_since
    assert removed.finished.removed == 1
    assert env.queries.version(STORE, old.path, visible=ALL_PROJECTS) is None
    assert env.slot(link.path).current == link.version_path


def test_file_removed_inside_known_version_dir_found_by_full_scan(
    env: _Env,
) -> None:
    """Incremental scans trust known version directories; a full scan checks them.

    A file deleted by hand from a version directory that stays is not seen
    by an incremental scan, which does not list the directory again; the
    next full scan marks it missing, and once back it is listed again.
    """
    # Arrange
    link, old = next(iter(_removable(env.store).values()))
    env.scan("full")
    data = env.store.root / old.path
    sidecar = sidecar_path(env.store.root, old.path)
    content, described = data.read_bytes(), sidecar.read_bytes()
    data.unlink()
    sidecar.unlink()

    # Act
    incremental = env.scan("incremental")
    trusted = env.version(link.path, old.path)
    full = env.scan("full")
    checked = env.version(link.path, old.path)
    data.write_bytes(content)
    sidecar.write_bytes(described)
    back = env.scan("incremental")

    # Assert
    assert data.parent.is_dir()
    assert (incremental.finished.missing, trusted.state) == (0, "present")
    assert (full.finished.missing, checked.state) == (1, "missing")
    assert checked.missing_since is not None
    assert back.finished.reappeared == 1
    assert env.version(link.path, old.path).state == "present"


def test_pins_survive_rescan(env: _Env) -> None:
    """Pins stay through rescans and show a pinned version that disappears."""
    # Arrange
    project = env.store.project("projekt-01")
    pin = next(
        pin
        for task in project.tasks
        for pin in task.pins
        if not pin.current and pin.present
    )
    env.scan("full")
    key = next(
        ref.key
        for ref in env.queries.projects(visible=ALL_PROJECTS)
        if ref.name == project.name
    )
    record = env.queries.project(key, visible=ALL_PROJECTS)
    assert record is not None
    slot = next(item.slot for item in record.pins if item.version == pin.version)
    assert slot is not None

    # Act
    env.scan("incremental")
    env.scan("full")
    rescanned = env.queries.project(key, visible=ALL_PROJECTS)
    pinned_by = env.version(slot, pin.version).pinned_by
    remove_version(env.store.root, pin.version)
    env.scan("incremental")
    marked = env.queries.project(key, visible=ALL_PROJECTS)
    env.scan("full")
    dropped = env.queries.project(key, visible=ALL_PROJECTS)

    # Assert
    assert rescanned == record
    assert {item.state for item in record.pins} == {"ok"}
    assert [(ref.project, ref.state) for ref in pinned_by] == [(project.name, "ok")]
    assert marked is not None and dropped is not None
    for later in (marked, dropped):
        states = {item.version: item.state for item in later.pins}
        assert states.pop(pin.version) == "missing"
        assert set(states.values()) == {"ok"}
    assert env.queries.version(STORE, pin.version, visible=ALL_PROJECTS) is None


def test_empty_mount_point_keeps_index(env: _Env) -> None:
    """An empty store directory over a full index changes no entry."""
    # Arrange
    root = env.store.root
    env.scan("full")
    before = env.state()
    rows = _rows(env.queries)
    away = root.with_name("data-away")
    root.rename(away)
    root.mkdir()

    # Act
    errors = []
    for mode in ("incremental", "full"):
        with pytest.raises(SourceUnavailableError) as raised:
            env.scan(mode)
        errors.append(str(raised.value))
    view = refresh_view(
        env.adapter,
        env.writer,
        env.queries,
        env.settings,
        STORE,
        NMT,
        ["N-33-44-C-b-3-3"],
    )
    unavailable = env.state()
    unchanged = _rows(env.queries)
    root.rmdir()
    away.rename(root)
    back = env.scan("incremental")

    # Assert
    assert all(str(root) in message for message in errors)
    assert (unavailable.status, unavailable.stale) == ("unavailable", True)
    # The status is stored in Polish, whatever language the caller works in.
    assert unavailable.detail == localize(errors[-1], "pl")
    assert unavailable.status_at is not None
    assert next(s for s in view.stores if s.store == STORE).stale is True
    assert unchanged == rows
    assert (unavailable.slots, unavailable.versions) == (before.slots, before.versions)
    assert unavailable.missing_versions == 0
    assert back.finished.missing == 0
    assert (env.state().status, env.state().stale) == ("available", False)
    assert _rows(env.queries) == rows


@pytest.mark.parametrize("failure", ["io_error", "unmounted"])
def test_store_lost_during_scan_marks_nothing(
    env: _Env, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A share lost in the middle of a scan leaves every version present."""
    # Arrange
    root = env.store.root
    env.scan("full")
    rows = _rows(env.queries)
    real = env.adapter.iter_entries

    def losing(path: Path, *, scope: ScanScope | None = None) -> Iterator[SourceEntry]:
        for index, entry in enumerate(real(path, scope=scope)):
            if scope is not None and scope.segment == NMT and index == 3:
                if failure == "io_error":
                    raise SourceUnavailableError("udział odłączony")
                root.rename(root.with_name("data-away"))
                root.mkdir()
            yield entry

    monkeypatch.setattr(env.adapter, "iter_entries", losing)

    # Act
    with pytest.raises(SourceUnavailableError):
        env.scan("incremental")
    state = env.state()

    # Assert
    assert (state.status, state.stale) == ("unavailable", True)
    assert state.missing_versions == 0
    assert _rows(env.queries) == rows


def test_parallel_scan_equals_sequential(tmp_path: Path) -> None:
    """Eight threads reading a share give the index one local thread gives."""
    # Arrange
    store = make_store(tmp_path / "store", slots=SLOTS + 40, seed=SEED + 1)
    adapter = _adapter(tmp_path)
    link, old = next(iter(_removable(store).values()))
    variants: dict[StoreKind, AppSettings] = {
        "local": _settings(store, threads=8, kind="local"),
        "share": _settings(store, threads=8, kind="share"),
    }
    results: dict[StoreKind, list[_Dump]] = {}

    # Act
    for kind, settings in variants.items():
        path = tmp_path / f"index-{kind}.sqlite"
        with IndexWriter(path) as writer, IndexQueries(path) as queries:
            writer.sync_stores({STORE: {"kartograf": store.root}})
            scan_store(adapter, writer, settings, STORE, mode="full")
            results[kind] = [_dump(queries)]
    add_version(store.root, link.path, label="2026-05-01_99999")
    remove_version(store.root, old.path)
    for kind, settings in variants.items():
        path = tmp_path / f"index-{kind}.sqlite"
        with IndexWriter(path) as writer, IndexQueries(path) as queries:
            scan_store(adapter, writer, settings, STORE, mode="incremental")
            results[kind].append(_dump(queries))

    # Assert
    assert results["share"] == results["local"]
    (rows, issues), changed = results["local"]
    assert len(rows) > len(store.by_kind("link")) and issues
    assert changed != (rows, issues)


def test_full_scan_keeps_unit_footprint(env: _Env) -> None:
    """A unit outline from the footprints job outlives later scans."""
    # Arrange
    env.scan("full")
    entry = next(
        item
        for item in env.queries.entries_without_footprint(STORE)
        if item.relative_path.suffix == ".zip"
        and "/teryt/" in item.relative_path.as_posix()
    )
    slot = entry.slot_path.as_posix() if entry.slot_path else ""
    path = entry.relative_path.as_posix()
    before = env.version(slot, path).location
    outline = _box(18.0, 50.0, 18.5, 50.3)
    unit = Footprint(
        location="footprint",
        wgs84=outline,
        native=outline,
        source="unit",
        native_crs="EPSG:4326",
    )
    assert env.writer.write_footprints(STORE, [(entry, unit)]) == 1

    # Act
    env.scan("full")
    after_full = env.version(slot, path).location
    env.scan("incremental")
    after_incremental = env.version(slot, path).location

    # Assert
    assert before == LocationRef("none", "no_source")
    assert after_full == LocationRef("footprint", None, "unit")
    assert after_incremental == after_full


def test_refresh_view_updates_only_requested_units(env: _Env) -> None:
    """A view refresh changes the slots of its units and nothing else."""
    # Arrange
    sheets = [
        (link, old)
        for link, old in _removable(env.store).values()
        if link.segment == NMT and link.family == "asc_sheet"
    ]
    (inside, inside_old), (outside, outside_old) = sheets[:2]
    env.scan("full")
    other_before = env.slot(outside.path)
    root = env.store.root
    inside_new = add_version(root, inside.path, label="2026-05-01_99999")
    add_version(root, outside.path, label="2026-05-02_99998")
    remove_version(root, inside_old.path)
    remove_version(root, outside_old.path)

    # Act
    status = refresh_view(
        env.adapter,
        env.writer,
        env.queries,
        env.settings,
        STORE,
        NMT,
        [inside.unit or ""],
        known_slots=[inside.path],
    )
    refreshed = env.slot(inside.path)

    # Assert
    assert refreshed.current == inside_new
    assert env.version(inside.path, inside_new).location.kind == "footprint"
    assert env.version(inside.path, inside_old.path).state == "missing"
    assert env.slot(outside.path) == other_before
    state = next(s for s in status.stores if s.store == STORE)
    assert (state.status, state.stale, state.missing_versions) == (
        "available",
        False,
        1,
    )


def test_refresh_view_unit_missing_its_slot_marks_nothing(env: _Env) -> None:
    """A unit that does not name its slot leaves the slot as it was.

    The unit is the tile's requested area, which Kartograf 0.8.0-dev gave
    as a LAZ tile's unit: the tile is not under it.
    """
    # Arrange
    tile = next(entry for entry in env.store.by_kind("link") if entry.segment == LAZ)
    env.scan("full")
    before = env.slot(tile.path)
    request = kartograf.read_sidecar(env.store.root / tile.path).request
    assert request is not None
    area = request["bbox"]
    unit = "_".join(format(value, ".10g") for value in area)

    # Act
    refresh_view(
        env.adapter,
        env.writer,
        env.queries,
        env.settings,
        STORE,
        LAZ,
        [unit],
        known_slots=[tile.path],
    )

    # Assert
    assert unit != tile.unit
    assert env.slot(tile.path) == before
    assert env.state().missing_versions == 0


def test_refresh_view_out_of_time_writes_nothing(env: _Env) -> None:
    """A refresh that runs out of time leaves the index as it was."""
    # Arrange
    link = next(iter(_removable(env.store).values()))[0]
    env.scan("full")
    new = add_version(env.store.root, link.path, label="2026-05-01_99999")

    def refresh(timeout_s: float | None) -> object:
        return refresh_view(
            env.adapter,
            env.writer,
            env.queries,
            env.settings,
            STORE,
            link.segment,
            [link.unit or ""],
            known_slots=[link.path],
            timeout_s=timeout_s,
        )

    # Act
    with pytest.raises(TimeoutError):
        refresh(0.0)
    stale = env.slot(link.path).current
    refresh(None)

    # Assert
    assert stale == link.version_path
    assert env.slot(link.path).current == new


def test_refresh_view_takes_at_most_500_units(env: _Env) -> None:
    """More units than a view of 500 slots are refused before any read."""
    units = [f"N-34-{number}-A-a-1-1" for number in range(REFRESH_VIEW_MAX_UNITS + 1)]

    with pytest.raises(ValueError, match="500"):
        refresh_view(
            env.adapter, env.writer, env.queries, env.settings, STORE, NMT, units
        )


def test_segment_scan_marks_only_its_segment(env: _Env) -> None:
    """A scan of one segment acts only on that segment, without projects."""
    # Arrange
    by_segment: dict[str, tuple[ExpectedEntry, ExpectedEntry]] = {}
    for link, old in _removable(env.store).values():
        by_segment.setdefault(link.segment, (link, old))
    other = next(segment for segment in by_segment if segment != NMT)
    env.scan("full")
    for _, old in (by_segment[NMT], by_segment[other]):
        remove_version(env.store.root, old.path)

    # Act
    summary = env.scan("incremental", segment=NMT)

    # Assert
    nmt_link, nmt_old = by_segment[NMT]
    other_link, other_old = by_segment[other]
    assert (summary.segment, summary.projects) == (NMT, None)
    assert [item.segment for item in summary.segments] == [NMT]
    assert summary.finished.missing == 1
    assert env.version(nmt_link.path, nmt_old.path).state == "missing"
    assert env.version(other_link.path, other_old.path).state == "present"


def test_scan_reports_progress_per_segment(env: _Env) -> None:
    """Progress counts segments; the summary times each one."""
    # Arrange
    events: list[ScanEvent] = []

    # Act
    summary = env.scan("full", on_event=events.append)

    # Assert
    progress = [event for event in events if isinstance(event, ScanProgress)]
    segments = env.store.segments()
    assert progress[0] == ScanProgress(None, 0, len(segments), 0)
    assert [event.current for event in progress] == list(range(len(segments) + 1))
    assert {event.total for event in progress} == {len(segments)}
    assert {event.segment for event in progress[1:]} == set(segments)
    assert progress[-1].entries == summary.entries == len(env.store.entries)
    assert [item.segment for item in summary.segments] == list(segments)
    assert sum(item.entries for item in summary.segments) == summary.entries
    assert summary.projects is not None and summary.projects.found == len(
        env.store.projects
    )


def test_scans_never_confirm_links(env: _Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """No scan or view refresh asks the producer to confirm a link (KA-5)."""
    # Arrange
    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> Any:
        calls.append(args)
        raise AssertionError("a scan confirmed a link")

    monkeypatch.setattr(kartograf_adapter, "link_target", forbidden)
    monkeypatch.setattr(kartograf, "link_target", forbidden)
    monkeypatch.setattr(env.adapter, "confirm_link", forbidden)
    link = next(iter(_removable(env.store).values()))[0]

    # Act
    env.scan("full")
    add_version(env.store.root, link.path, label="2026-05-01_99999")
    env.scan("incremental")
    env.scan("full", segment=NMT)
    refresh_view(
        env.adapter,
        env.writer,
        env.queries,
        env.settings,
        STORE,
        link.segment,
        [link.unit or ""],
        known_slots=[link.path],
    )

    # Assert
    assert calls == []
    assert env.slot(link.path).current != link.version_path


def test_read_only_store_scan_leaves_store_unchanged(env: _Env) -> None:
    """Scans read a store without write permission and change nothing in it."""
    # Arrange
    output = env.store.output_dir
    before = _tree(output)
    _make_tree_read_only(output, read_only=True)

    # Act
    try:
        full = env.scan("full")
        incremental = env.scan("incremental")
        env.scan("incremental", segment=NMT)
        after = _tree(output)
    finally:
        _make_tree_read_only(output, read_only=False)

    # Assert
    assert after == before
    assert full.entries == incremental.entries == len(env.store.entries)
    assert env.state().missing_versions == 0
