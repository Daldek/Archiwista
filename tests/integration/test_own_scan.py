"""Scan of the projects' data folders (plan v0.2, step 7b; decision 8).

Every test scans real folders written by GDAL (``tests.fixtures.own_data``)
with the real reader process and Kartograf's pinned operations, into a
fresh index holding the test's projects.
"""

import json
import os
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import pyogrio.raw
import pytest
import rasterio
import shapely
from rasterio.windows import Window
from shapely.geometry import shape

from archiwista.auth import ALL_PROJECTS, access_key
from archiwista.config import AppPaths, AppSettings, StoreConfig
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    ManifestStamp,
    OwnFileDetail,
    OwnFolderRecord,
    TransformerFactory,
    own_file_id,
)
from archiwista.owndata.content import content_identity
from archiwista.owndata.formats import fileset_members
from archiwista.owndata.reader import OwnFileInfo, OwnReader
from archiwista.owndata.scan import OwnScanSummary, scan_own_data
from archiwista.sources import ProjectInfo
from archiwista.sources.registry import load_registry
from tests.fixtures.own_data import (
    GpkgEditor,
    SnapshotFixture,
    make_own_folder,
    project_inside_store,
    write_snapshot_fixture,
)

# make_own_folder writes a TIFF without georeference on purpose.
pytestmark = pytest.mark.filterwarnings(
    "ignore::rasterio.errors.NotGeoreferencedWarning"
)
# Kraków: the extent of make_own_folder's files in WGS84, roughly.
_KRAKOW = shapely.box(19.8, 49.9, 20.1, 50.2)
_MONDAY = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


@dataclass
class OwnEnv:
    """A fresh index with projects, and how to scan their data folders."""

    root: Path
    paths: AppPaths
    writer: IndexWriter
    queries: IndexQueries
    transformer: TransformerFactory
    settings: AppSettings = field(default_factory=AppSettings)

    def project(self, name: str, directory: Path | None = None) -> tuple[str, Path]:
        """Index a project; return its key and its directory (created)."""
        place = directory or self.root / "projekty" / name.lower()
        place.mkdir(parents=True, exist_ok=True)
        info = ProjectInfo("kartograf", str(self.root / "magazyn"), place, name)
        key = self.writer.write_project(
            info, store=None, stamp=ManifestStamp(None, None)
        )
        return key, place

    def scan(self, project: str | None = None, **options: object) -> OwnScanSummary:
        """Scan every project's folder, or one project's."""
        known = self.queries.projects(visible=ALL_PROJECTS)
        chosen = [item for item in known if project in (None, item.key)]
        return scan_own_data(
            self.writer,
            chosen,
            known_projects=known,
            settings=self.settings,
            paths=self.paths,
            transformer=self.transformer,
            prune=project is None,
            **options,  # type: ignore[arg-type]
        )

    def folder(self, project: str) -> OwnFolderRecord:
        """Return a project's folder as indexed."""
        found = self.queries.own_folder(project, visible=ALL_PROJECTS)
        assert found is not None
        return found

    def file(self, project: str, path: str) -> OwnFileDetail:
        """Return the card of a file by its path."""
        found = self.queries.own_file(project, own_file_id(path), visible=ALL_PROJECTS)
        assert found is not None, path
        return found

    def paths_listed(self, project: str, **filters: object) -> list[str]:
        """Return the paths of a project's files, every page."""
        listed: list[str] = []
        cursor = None
        while True:
            page = self.queries.own_files(
                project,
                visible=ALL_PROJECTS,
                cursor=cursor,
                **filters,  # type: ignore[arg-type]
            )
            assert page is not None
            listed += [item.path for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                return listed


@pytest.fixture
def env(tmp_path: Path) -> Iterator[OwnEnv]:
    """Yield an empty index, its writer and queries, and Kartograf's operations."""
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")
    adapter = load_registry(cache_dir=paths.cache_dir).adapter("kartograf")
    transformer = adapter.transformer  # type: ignore[attr-defined]
    with (
        IndexWriter(paths.index_file) as writer,
        IndexQueries(paths.index_file) as queries,
    ):
        yield OwnEnv(tmp_path, paths, writer, queries, transformer)


def _tree(folder: Path) -> dict[str, tuple[int, int]]:
    """Every name below a folder with its size and modification time."""
    found: dict[str, tuple[int, int]] = {}
    for directory, names, files in os.walk(folder):
        for name in [*names, *files]:
            path = Path(directory) / name
            status = path.lstat()
            found[path.relative_to(folder).as_posix()] = (
                status.st_size,
                status.st_mtime_ns,
            )
    return found


class _NoReads:
    """A reader that fails the test when a file is read."""

    def read(self, path: Path) -> OwnFileInfo:
        """Refuse to read."""
        raise AssertionError(f"read {path}")

    def close(self) -> None:
        """Nothing to end."""


def _no_reads() -> OwnReader:
    return cast(OwnReader, _NoReads())


def _snapshot(folder: Path, path: str, created_at: datetime) -> SnapshotFixture:
    """Snapshot a working file with its content identity (decision 8)."""
    source = folder / path
    work = folder.parent / "work"
    work.mkdir(exist_ok=True)
    members = fileset_members(source)
    if len(members) > 1:
        identity = content_identity(members, method="fileset")
    elif source.read_bytes()[:16] == b"SQLite format 3\x00":
        identity = content_identity([source], method="sqlite", work_dir=work)
    else:
        identity = content_identity([source], method="bytes")
    return write_snapshot_fixture(
        folder,
        path,
        created_at=created_at,
        content=(identity.method, identity.sha256),
        note="przed zmianą",
    )


def _editable(directory: Path) -> None:
    """Let a test change a snapshot (files ``0444``, directory ``0555``)."""
    directory.chmod(0o755)
    for path in directory.iterdir():
        path.chmod(0o644)


def _codes(record: OwnFolderRecord) -> list[tuple[str, str | None]]:
    return [(problem.code, problem.path) for problem in record.problems]


def test_folder_with_gpkg_shp_geotiff_indexed_with_extent(env: OwnEnv) -> None:
    """Files of a folder are indexed with drivers, layers, CRS, extent and content."""
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(
        project / "dane", families=("gpkg_layers", "shp_full", "tif_2180")
    )
    before = _tree(folder.root)

    # Act
    summary = env.scan()

    # Assert
    assert (summary.projects, summary.files, summary.new) == (1, 3, 3)
    assert (summary.changed, summary.missing, summary.unreadable) == (0, 0, 0)
    assert env.paths_listed(key) == ["dzialki.shp", "kanalizacja.gpkg", "nmt.tif"]
    assert env.paths_listed(key, q="KANAL gpkg") == ["kanalizacja.gpkg"]
    assert env.paths_listed(key, limit=1) == env.paths_listed(key)
    gpkg = env.file(key, "kanalizacja.gpkg")
    assert (gpkg.file.driver, gpkg.file.kind, gpkg.native_crs) == (
        "GPKG",
        "vector",
        "EPSG:2180",
    )
    assert [
        (layer.name, layer.geometry_type, layer.feature_count) for layer in gpkg.layers
    ] == [
        ("przewody", "LineString", 3),
        ("zlewnie", "Polygon", 2),
    ]
    assert [field.name for field in gpkg.layers[0].fields] == [
        "srednica_mm",
        "material",
    ]
    assert gpkg.feature_count == 5
    assert gpkg.content_method == "sqlite"
    assert gpkg.native_bbox is not None and 566_100 <= gpkg.native_bbox[0] < 570_000
    assert gpkg.file.location.kind == "footprint"
    assert gpkg.wgs84 is not None and _KRAKOW.contains(shape(gpkg.wgs84))
    assert (gpkg.file.state, gpkg.file.change) == ("ok", "unsnapshotted")
    shp = env.file(key, "dzialki.shp")
    assert shp.file.driver == "ESRI Shapefile"
    assert shp.members == (
        "dzialki.shp",
        "dzialki.shx",
        "dzialki.dbf",
        "dzialki.prj",
        "dzialki.cpg",
    )
    assert shp.content_method == "fileset"
    assert shp.file.size_bytes == sum(
        (folder.root / name).stat().st_size for name in shp.members
    )
    assert shp.wgs84 is not None and _KRAKOW.contains(shape(shp.wgs84))
    tif = env.file(key, "nmt.tif")
    assert tif.raster is not None and (tif.raster.width, tif.raster.height) == (64, 64)
    assert tif.content_method == "bytes"
    assert tif.wgs84 is not None and _KRAKOW.contains(shape(tif.wgs84))
    assert [state.content_sha256 for state in tif.history] == [tif.content_sha256]
    record = env.folder(key)
    assert (record.state, record.source, record.files) == ("ok", "default", 3)
    assert record.path == str(project / "dane")
    assert record.size_bytes == sum(
        item.size_bytes for item in (gpkg.file, shp.file, tif.file)
    )
    assert record.problems == ()
    assert _tree(folder.root) == before


def test_change_after_snapshot_detected(env: OwnEnv) -> None:
    """Changes against the last snapshot: content counts, not bytes or times.

    A GeoPackage feature, a feature appended to a Shapefile and an
    overwritten GeoTIFF pixel make each file ``changed`` since the
    snapshot; the content brought back makes it ``unchanged`` again, and so
    does opening the GeoPackage for update without changing data (OGR's
    feature count and the write timestamps are rewritten). Every observed
    state stays in the history.
    """
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(
        project / "dane", families=("gpkg_layers", "shp_full", "tif_2180")
    )
    root = folder.root
    originals = env.root / "oryginaly"
    shutil.copytree(root, originals)
    names = ("kanalizacja.gpkg", "dzialki.shp", "nmt.tif")
    labels = {name: _snapshot(root, name, _MONDAY).label for name in names}

    # Act
    first = env.scan()
    snapshotted = {name: env.file(key, name) for name in names}
    with GpkgEditor(root / "kanalizacja.gpkg") as editor:
        editor.begin()
        editor.insert(
            "przewody",
            shapely.LineString([(566_500, 241_500), (566_600, 241_600)]),
            srednica_mm=110,
            material="PE",
        )
        editor.commit()
    pyogrio.raw.write(
        root / "dzialki.shp",
        np.array([shapely.to_wkb(shapely.box(566_200, 241_200, 566_300, 241_300))]),
        [np.array(["12/5"], dtype=object), np.array([100], dtype=np.int32)],
        ["numer", "pow_m2"],
        layer="dzialki",
        driver="ESRI Shapefile",
        geometry_type="Polygon",
        crs="EPSG:2180",
        append=True,
    )
    with rasterio.open(root / "nmt.tif", "r+") as raster:
        raster.write(
            np.full((1, 1), 999.0, dtype=np.float32), 1, window=Window(0, 0, 1, 1)
        )
    second = env.scan()
    changed = {name: env.file(key, name) for name in names}
    for name in os.listdir(originals):
        shutil.copyfile(originals / name, root / name)
    third = env.scan()
    restored = {name: env.file(key, name) for name in names}
    with GpkgEditor(root / "kanalizacja.gpkg") as editor:
        editor.reopen_for_update_unchanged()
    fourth = env.scan()
    reopened = env.file(key, "kanalizacja.gpkg")

    # Assert
    assert first.new == 3
    for name in names:
        assert snapshotted[name].file.change == "unchanged", name
        last = snapshotted[name].file.last_snapshot
        assert last is not None and (last.label, last.created_at) == (
            labels[name],
            _MONDAY,
        )
        assert changed[name].file.change == "changed", name
        assert changed[name].file.last_snapshot == last
        assert changed[name].content_sha256 != snapshotted[name].content_sha256
        assert restored[name].file.change == "unchanged", name
        assert restored[name].content_sha256 == snapshotted[name].content_sha256
    assert (second.changed, second.new) == (3, 0)
    assert (
        changed["kanalizacja.gpkg"].feature_count,
        changed["dzialki.shp"].feature_count,
    ) == (6, 3)
    assert third.changed == 3
    assert fourth.changed == 1
    assert reopened.file.change == "unchanged"
    assert reopened.content_sha256 == snapshotted["kanalizacja.gpkg"].content_sha256
    history = [state.content_sha256 for state in reversed(reopened.history)]
    first_sha = snapshotted["kanalizacja.gpkg"].content_sha256
    assert history[:3] == [
        first_sha,
        changed["kanalizacja.gpkg"].content_sha256,
        first_sha,
    ]
    assert history[-1] == first_sha
    assert [state.feature_count for state in reversed(reopened.history)][:2] == [5, 6]
    assert len(reopened.snapshots) == 1
    snapshot = reopened.snapshots[0]
    assert (snapshot.label, snapshot.state, snapshot.created_at) == (
        labels["kanalizacja.gpkg"],
        "ok",
        _MONDAY,
    )
    assert snapshot.document is not None and snapshot.document["note"] == "przed zmianą"


def test_unchanged_files_cost_only_stat(
    env: OwnEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second scan of an unchanged folder reads no file and hashes nothing."""
    # Arrange
    key, project = env.project("Raba")
    make_own_folder(project / "dane")
    first = env.scan()
    before = env.paths_listed(key)

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("content hashed again")

    monkeypatch.setattr("archiwista.owndata.scan.content_identity", refuse)

    # Act
    second = env.scan(reader=_no_reads())

    # Assert
    assert first.new == len(before) > 0
    assert (second.new, second.changed, second.missing, second.problems) == (0, 0, 0, 0)
    assert second.files == first.files
    assert env.paths_listed(key) == before


def test_hidden_and_versions_skipped(env: OwnEnv) -> None:
    """Hidden files and directories, ``.wersje/`` and SQLite companions are no files."""
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(
        project / "dane", families=("hidden", "gpkg_layers", "subdir")
    )
    _snapshot(folder.root, "kanalizacja.gpkg", _MONDAY)
    (folder.root / "kanalizacja.gpkg-shm").write_bytes(b"")
    (folder.root / "stary.gpkg-journal").write_bytes(b"")

    # Act
    summary = env.scan()

    # Assert
    assert env.paths_listed(key) == [
        "archiwum/2025/punkty.geojson",
        "kanalizacja.gpkg",
    ]
    assert summary.files == 2
    card = env.file(key, "kanalizacja.gpkg")
    assert [snapshot.state for snapshot in card.snapshots] == ["ok"]
    assert env.folder(key).snapshots == 1
    assert env.folder(key).problems == ()


def test_symlink_outside_folder_skipped(env: OwnEnv) -> None:
    """Links out of the folder are not followed; each is a ``path_outside_root``."""
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(
        project / "dane", families=("symlink_outside", "geojson_wgs84")
    )
    assert folder.outside is not None
    (folder.root / "w_srodku.geojson").symlink_to(folder.root / "punkty_wgs84.geojson")

    # Act
    env.scan()

    # Assert
    assert env.paths_listed(key) == ["punkty_wgs84.geojson", "w_srodku.geojson"]
    assert _codes(env.folder(key)) == [
        ("path_outside_root", "katalog_poza"),
        ("path_outside_root", "poza.geojson"),
    ]
    inside = env.file(key, "w_srodku.geojson")
    assert (inside.file.state, inside.file.driver) == ("ok", "GeoJSON")


def test_invalid_snapshot_problem(env: OwnEnv) -> None:
    """A broken document, a newer schema and changed copies are reported."""
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(project / "dane", families=("tif_2180", "geojson_wgs84"))
    root = folder.root
    broken = _snapshot(root, "nmt.tif", _MONDAY)
    newer = _snapshot(root, "punkty_wgs84.geojson", _MONDAY)
    changed = _snapshot(root, "nmt.tif", _MONDAY + timedelta(days=1))
    _editable(broken.directory)
    (broken.directory / "migawka.json").write_text("{nie json", encoding="utf-8")
    _editable(newer.directory)
    document = {**newer.document, "schema": "archiwista-snapshot/2"}
    (newer.directory / "migawka.json").write_text(
        json.dumps(document), encoding="utf-8"
    )
    _editable(changed.directory)
    (changed.directory / "nmt.tif").write_bytes(b"inne bajty")

    # Act
    env.scan()
    again = env.scan()

    # Assert
    base = ".wersje"
    assert _codes(env.folder(key)) == [
        ("invalid_snapshot", f"{base}/nmt.tif/{broken.label}"),
        ("snapshot_modified", f"{base}/nmt.tif/{changed.label}"),
        ("unknown_snapshot_schema", f"{base}/punkty_wgs84.geojson/{newer.label}"),
    ]
    schema = next(
        p for p in env.folder(key).problems if p.code == "unknown_snapshot_schema"
    )
    assert schema.reason == "archiwista-snapshot/2"
    tif = env.file(key, "nmt.tif")
    assert {s.label: s.state for s in tif.snapshots} == {
        broken.label: "invalid",
        changed.label: "modified",
    }
    assert (tif.file.last_snapshot, tif.file.change) == (None, "unsnapshotted")
    assert again.problems == 0


def test_snapshot_with_unknown_optional_field_is_valid(env: OwnEnv) -> None:
    """A field written by a newer Archiwista keeps the snapshot valid and indexed."""
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(project / "dane", families=("tif_2180",))
    snapshot = _snapshot(folder.root, "nmt.tif", _MONDAY)
    _editable(snapshot.directory)
    document = {**snapshot.document, "reviewed_by": {"id": "ola"}}
    (snapshot.directory / "migawka.json").write_text(
        json.dumps(document), encoding="utf-8"
    )

    # Act
    env.scan()

    # Assert
    card = env.file(key, "nmt.tif")
    assert [item.state for item in card.snapshots] == ["ok"]
    assert card.snapshots[0].document == document
    assert card.file.change == "unchanged"
    assert env.folder(key).problems == ()


def test_stale_incoming_problem_after_24h(env: OwnEnv) -> None:
    """A working directory of an interrupted snapshot is a problem after 24 h."""
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(project / "dane", families=("tif_2180",))
    incoming = folder.root / ".wersje" / ".incoming"
    old = incoming / "stacja_4242_0f3a9c1d"
    fresh = incoming / "stacja_4243_77aa01b2"
    for directory in (old, fresh):
        directory.mkdir(parents=True)
        (directory / "nmt.tif").write_bytes(b"kopia w toku")
    day_ago = time.time() - timedelta(hours=25).total_seconds()
    os.utime(old, (day_ago, day_ago))

    # Act
    env.scan()

    # Assert
    assert _codes(env.folder(key)) == [
        ("stale_snapshot_incoming", ".wersje/.incoming/stacja_4242_0f3a9c1d")
    ]
    assert env.paths_listed(key) == ["nmt.tif"]
    assert env.folder(key).snapshots == 0


def test_missing_file_keeps_snapshots(env: OwnEnv) -> None:
    """A working file gone is ``missing``; its snapshots stay on its card."""
    # Arrange
    key, project = env.project("Raba")
    folder = make_own_folder(project / "dane", families=("tif_2180", "geojson_wgs84"))
    snapshot = _snapshot(folder.root, "nmt.tif", _MONDAY)
    env.scan()
    (folder.root / "nmt.tif").unlink()

    # Act
    summary = env.scan()

    # Assert
    card = env.file(key, "nmt.tif")
    assert summary.missing == 1
    assert card.file.state == "missing" and card.missing_since is not None
    assert [item.label for item in card.snapshots] == [snapshot.label]
    assert env.paths_listed(key, state="missing") == ["nmt.tif"]
    assert env.paths_listed(key, state="ok") == ["punkty_wgs84.geojson"]
    assert env.folder(key).files == 1
    assert env.folder(key).snapshots == 1


def test_default_folder_inside_store_is_refused(env: OwnEnv) -> None:
    """A project with its manifest in a store: ``dane/`` is in the store, not read."""
    # Arrange
    store = env.root / "magazyn"
    store.mkdir()
    env.settings = AppSettings(
        stores=(StoreConfig(id="zespol", name="Zespół", kartograf=store, kind="local"),)
    )
    directory = project_inside_store(store)
    key, _ = env.project("W magazynie", directory)
    make_own_folder(directory / "dane", families=("gpkg_layers", "tif_2180"))
    before = _tree(store)

    # Act
    summary = env.scan(reader=_no_reads())

    # Assert
    record = env.folder(key)
    assert (record.state, record.reason, record.files) == ("invalid", "inside_store", 0)
    assert [(p.code, p.reason) for p in record.problems] == [
        ("own_folder_invalid", "inside_store")
    ]
    assert env.paths_listed(key) == []
    assert (summary.projects, summary.files, summary.new) == (1, 0, 0)
    assert _tree(store) == before


def test_overlapping_folders_invalid_for_both(env: OwnEnv) -> None:
    """A folder inside another project's folder makes both invalid; others stay."""
    # Arrange
    shared = env.root / "wspolne"
    first, first_dir = env.project("Raba")
    second, second_dir = env.project("Wisła")
    third, third_dir = env.project("Dunajec")
    make_own_folder(shared, families=("tif_2180",))
    make_own_folder(shared / "wisla", families=("geojson_wgs84",))
    make_own_folder(third_dir / "dane", families=("geojson_wgs84",))
    env.settings = AppSettings(
        own_data_dirs={
            access_key(first_dir): str(shared),
            access_key(second_dir): str(shared / "wisla"),
        }
    )

    # Act
    env.scan()

    # Assert
    for key in (first, second):
        record = env.folder(key)
        assert (record.state, record.reason, record.source) == (
            "invalid",
            "overlaps_project",
            "setting",
        )
        assert env.paths_listed(key) == []
    assert env.folder(third).state == "ok"
    assert env.paths_listed(third) == ["punkty_wgs84.geojson"]


def test_too_large_folder_indexes_first_10000_by_path(env: OwnEnv) -> None:
    """Of more than 10 000 files the first 10 000 by path in NFC are indexed.

    ``a-b.txt`` < ``a.txt`` < ``a/b.txt`` (by character, ``/`` too), and
    ``é.txt`` written decomposed (``e`` + U+0301) sorts as the one character
    U+00E9, after ``eя.txt`` (decomposed it would come first). A file beyond
    the limit after the folder grows leaves the index without being missing.
    """
    # Arrange
    key, project = env.project("Raba")
    root = project / "dane"
    (root / "a").mkdir(parents=True)
    for number in range(9_996):
        (root / f"d_{number:05d}.txt").write_bytes(b"")
    for name in ("a-b.txt", "a.txt", "a/b.txt", "e\u044f.txt", "e\u0301.txt"):
        (root / name).write_bytes(b"")

    # Act
    first = env.scan()
    indexed = env.paths_listed(key)
    (root / "0.txt").write_bytes(b"")
    second = env.scan()
    after = env.paths_listed(key)

    # Assert
    assert first.files == 10_000
    assert indexed[:4] == ["a-b.txt", "a.txt", "a/b.txt", "d_00000.txt"]
    assert indexed[-1] == "e\u044f.txt" and "\u00e9.txt" not in indexed
    record = env.folder(key)
    assert record.files == 10_000
    assert [p.code for p in record.problems] == ["own_folder_too_large"]
    assert (second.new, second.missing) == (1, 0)
    assert (after[0], after[-1], len(after)) == ("0.txt", "d_09995.txt", 10_000)
    assert env.folder(key).files == 10_000
