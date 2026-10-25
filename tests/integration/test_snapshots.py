"""Snapshots of own-data files (plan v0.2, step 8; decision 9).

Every test snapshots real folders written by GDAL (``tests.fixtures.own_data``),
scanned into a fresh index with the real reader process: in this process
with ``make_snapshot``, or through the ``snapshot`` job of a supervisor whose
workers carry test hooks (``tests.fixtures.job_worker``).
"""

import errno
import json
import os
import shutil
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pyogrio
import pytest
import shapely
from shapely.geometry import box

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER, Principal
from archiwista.config import AppPaths, AppSettings, ConfigStore, SettingsService
from archiwista.errors import (
    JobConflictError,
    SnapshotBlockedError,
    SnapshotFailedError,
)
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    ManifestStamp,
    OwnFileDetail,
    TransformerFactory,
    own_file_id,
)
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.owndata import snapshots
from archiwista.owndata.content import file_sha256
from archiwista.owndata.document import (
    SnapshotAuthor,
    SnapshotFile,
    parse_snapshot_document,
)
from archiwista.owndata.reader import OwnReader
from archiwista.owndata.scan import (
    OwnFolderCheck,
    check_own_folder,
    folder_rules,
    scan_own_data,
)
from archiwista.owndata.snapshots import (
    SnapshotPhase,
    SnapshotPlan,
    SnapshotResult,
    check_snapshot,
    make_snapshot,
)
from archiwista.sandbox import process_owner, process_work_dir
from archiwista.sources import ProjectInfo
from archiwista.sources.registry import SourceRegistry, load_registry
from tests.fixtures.job_worker import SNAPSHOT_FAULT_ENV
from tests.fixtures.jobs import JOB_TIMEOUT_S, TEST_WORKER, worker_path
from tests.fixtures.own_data import GpkgEditor, make_own_folder, project_inside_store

# make_own_folder writes a TIFF without georeference on purpose.
pytestmark = pytest.mark.filterwarnings(
    "ignore::rasterio.errors.NotGeoreferencedWarning"
)
LOCAL_AUTHOR = SnapshotAuthor(id="local", kind="local_owner", name=None, session=None)
# Kraków: the extent of make_own_folder's files in WGS84, roughly.
_KRAKOW = box(19.8, 49.9, 20.1, 50.2)
_SCHEMA_KEYS = [
    "schema",
    "label",
    "created_at",
    "author",
    "note",
    "source",
    "content",
    "copy",
    "files",
    "size_bytes",
    "layers",
    "raster",
    "feature_count",
    "extent",
    "archiwista",
]
_BEFORE_RENAME: tuple[SnapshotPhase, ...] = ("copy", "checksums", "document", "rename")


@dataclass
class SnapshotEnv:
    """A fresh index with projects, their scanned folders and a reader process."""

    root: Path
    paths: AppPaths
    writer: IndexWriter
    queries: IndexQueries
    registry: SourceRegistry
    transformer: TransformerFactory
    reader: OwnReader
    settings: AppSettings = field(default_factory=AppSettings)

    def project(
        self, name: str = "Raba", directory: Path | None = None
    ) -> tuple[str, Path]:
        """Index a project; return its key and its directory (created)."""
        place = directory or self.root / "projekty" / name.lower()
        place.mkdir(parents=True, exist_ok=True)
        info = ProjectInfo("kartograf", str(self.root / "magazyn"), place, name)
        key = self.writer.write_project(
            info, store=None, stamp=ManifestStamp(None, None)
        )
        return key, place

    def scan(self) -> None:
        """Scan every project's data folder into the index."""
        known = self.queries.projects(visible=ALL_PROJECTS)
        scan_own_data(
            self.writer,
            known,
            known_projects=known,
            settings=self.settings,
            paths=self.paths,
            transformer=self.transformer,
            reader=self.reader,
        )

    def file(self, key: str, path: str) -> OwnFileDetail:
        """Return the card of a file by its path."""
        found = self.queries.own_file(key, own_file_id(path), visible=ALL_PROJECTS)
        assert found is not None, path
        return found

    def folder(self, key: str) -> OwnFolderCheck:
        """Check a project's data folder now, as the ``snapshot`` job does."""
        known = self.queries.projects(visible=ALL_PROJECTS)
        project = next(item for item in known if item.key == key)
        stores, folders = folder_rules(self.settings, known)
        return check_own_folder(
            self.settings,
            project.access_key,
            stores=stores,
            app_data=self.paths.data_dir,
            others=[
                path for name, path in folders.items() if name != project.access_key
            ],
        )

    def plan(self, key: str, path: str) -> SnapshotPlan:
        """Plan a snapshot of a file."""
        return check_snapshot(
            self.folder(key), self.file(key, path), work_dir=self.work_dir
        )

    def make(
        self,
        key: str,
        path: str,
        *,
        note: str = "",
        on_phase: Callable[[SnapshotPhase], None] | None = None,
    ) -> SnapshotResult:
        """Make a snapshot of a file in this process, as the local owner."""
        return make_snapshot(
            self.folder(key),
            self.file(key, path),
            author=LOCAL_AUTHOR,
            note=note,
            work_dir=self.work_dir,
            reader=self.reader,
            transformer=self.transformer,
            on_phase=on_phase,
        )

    @property
    def work_dir(self) -> Path:
        """Return this process's work directory."""
        return process_work_dir(self.paths)

    @contextmanager
    def jobs(self) -> Iterator[JobSupervisor]:
        """Yield a started supervisor of test workers with the env's settings."""
        ConfigStore(self.paths.config_file).save(self.settings)
        settings = SettingsService(ConfigStore(self.paths.config_file), self.registry)
        with JobSupervisor(self.paths, settings, worker_command=TEST_WORKER) as jobs:
            yield jobs


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SnapshotEnv]:
    """Yield an empty index, Kartograf's operations and a reader process."""
    worker_path(monkeypatch)
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    registry = load_registry(cache_dir=paths.cache_dir)
    transformer = registry.adapter("kartograf").transformer  # type: ignore[attr-defined]
    with (
        IndexWriter(paths.index_file) as writer,
        IndexQueries(paths.index_file) as queries,
        OwnReader(paths) as reader,
    ):
        yield SnapshotEnv(
            tmp_path, paths, writer, queries, registry, transformer, reader
        )


def _submit(
    jobs: JobSupervisor,
    key: str,
    path: str,
    *,
    note: str = "",
    actor: Principal = LOCAL_OWNER,
) -> JobRecord:
    params = {"project": key, "file_id": own_file_id(path), "note": note}
    return jobs.submit("snapshot", params=params, actor=actor)


def _run(jobs: JobSupervisor, key: str, path: str, *, note: str = "") -> JobRecord:
    """Run a ``snapshot`` job to its end."""
    return jobs.wait(_submit(jobs, key, path, note=note).id, timeout=JOB_TIMEOUT_S)


def _tree(folder: Path) -> dict[str, tuple[int, int] | None]:
    """Names below a folder with sizes and times, ``.wersje/`` left out.

    A ``-shm`` is an editor's shared memory: SQLite may write it, so only
    its name counts.
    """
    found: dict[str, tuple[int, int] | None] = {}
    for directory, names, files in os.walk(folder):
        names[:] = [name for name in names if name != ".wersje"]
        for name in [*names, *files]:
            path = Path(directory) / name
            status = path.lstat()
            relative = path.relative_to(folder).as_posix()
            found[relative] = (
                None if name.endswith("-shm") else (status.st_size, status.st_mtime_ns)
            )
    return found


def _labels(folder: Path, path: str) -> list[str]:
    """Labels of a file's snapshots in ``.wersje/``."""
    parent = folder / ".wersje" / path
    return sorted(entry.name for entry in parent.iterdir()) if parent.is_dir() else []


def _leftovers(folder: Path) -> list[str]:
    """Working directories left in ``.wersje/.incoming/``."""
    incoming = folder / ".wersje" / ".incoming"
    return (
        sorted(entry.name for entry in incoming.iterdir()) if incoming.is_dir() else []
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _diameters(copy: Path) -> list[int]:
    """``srednica_mm`` of the pipes of a GeoPackage copy, in ``fid`` order."""
    connection = sqlite3.connect(f"{copy.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute("SELECT srednica_mm FROM przewody ORDER BY fid")
        return [int(row[0]) for row in rows]
    finally:
        connection.close()


def _integrity(copy: Path) -> list[str]:
    connection = sqlite3.connect(f"{copy.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        return [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
    finally:
        connection.close()


def _pipe() -> shapely.Geometry:
    return shapely.LineString([(566_500, 241_500), (566_600, 241_600)])


def test_gpkg_open_for_editing_snapshot_is_consistent(env: SnapshotEnv) -> None:
    """A GeoPackage open in an editor: the snapshot job copies committed rows only.

    The editor (WAL, like QGIS) committed one pipe, whose frames wait in
    ``-wal``, and keeps a transaction with another one open. The copy passes
    ``PRAGMA integrity_check``, holds the committed pipe and not the open
    one, and opens in pyogrio straight from the read-only snapshot; the
    folder outside ``.wersje/`` stays as it was; the job warns that the file
    is being edited and records the snapshot in the index.
    """
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("gpkg_layers",)).root
    env.scan()
    gpkg = root / "kanalizacja.gpkg"
    with env.jobs() as jobs, GpkgEditor(gpkg) as editor:
        editor.begin()
        editor.insert("przewody", _pipe(), srednica_mm=999, material="PE")
        editor.commit()
        editor.begin()
        editor.insert("przewody", _pipe(), srednica_mm=777, material="PE")
        before = _tree(root)

        # Act
        record = _run(jobs, key, "kanalizacja.gpkg")
        notices = [e.data for e in jobs.events(record.id) if e.type == "notice"]
        after = _tree(root)
        wal_left = editor.wal.exists() and editor.shm.exists()

    # Assert
    assert record.state == "succeeded", record
    assert record.result is not None and record.result["status"] == "created"
    label = record.result["label"]
    directory = root / ".wersje" / "kanalizacja.gpkg" / label
    copy = directory / "kanalizacja.gpkg"
    assert _integrity(copy) == ["ok"]
    assert _diameters(copy) == [300, 200, 160, 999]
    assert pyogrio.read_info(copy, layer="przewody")["features"] == 4
    assert sorted(os.listdir(directory)) == ["kanalizacja.gpkg", "migawka.json"]
    assert after == before and wal_left
    assert [notice["code"] for notice in notices] == ["editing_detected"]
    assert record.result["size_bytes"] == copy.stat().st_size
    card = env.file(key, "kanalizacja.gpkg")
    assert [(s.label, s.state) for s in card.snapshots] == [(label, "ok")]
    assert card.snapshots[0].content_sha256 == record.result["content_sha256"]


def test_wal_without_shm_snapshot_has_committed_rows(env: SnapshotEnv) -> None:
    """State (c), ``-wal`` without ``-shm``: rows only in the WAL are copied.

    No ``-shm`` appears next to the file, nothing in the folder changes.
    """
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("gpkg_layers",)).root
    env.scan()
    gpkg = root / "kanalizacja.gpkg"
    editor = GpkgEditor(gpkg)
    editor.begin()
    editor.insert("przewody", _pipe(), srednica_mm=999, material="PE")
    editor.commit()
    editor.crash_without_shm()
    before = _tree(root)

    # Act
    result = env.make(key, "kanalizacja.gpkg")

    # Assert
    assert result.status == "created"
    assert _diameters(result.directory / "kanalizacja.gpkg") == [300, 200, 160, 999]
    assert result.document.feature_count == 6
    assert not Path(f"{gpkg}-shm").exists()
    assert _tree(root) == before
    assert [warning.code for warning in result.warnings] == ["editing_detected"]


def test_interrupted_snapshot_leaves_no_partial_version(
    env: SnapshotEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interruption in any phase before the rename leaves no label.

    The phases are the copy, the sums, ``migawka.json`` and the moment
    before the rename; the interruptions an error raised in this process
    (``on_phase``) for a GeoPackage and a Shapefile, and SIGINT and SIGKILL
    of the worker of a ``snapshot`` job. No label appears in ``.wersje/``,
    the index knows no snapshot, and only a killed worker leaves its working
    directory in ``.incoming/``. SIGKILL just after the rename leaves a
    complete snapshot with read-only files, which the next scan indexes.
    """

    # Arrange
    class Fault(Exception):
        pass

    def fail_at(phase: SnapshotPhase) -> Callable[[SnapshotPhase], None]:
        def reached(done: SnapshotPhase) -> None:
            if done == phase:
                raise Fault(phase)

        return reached

    key, project = env.project()
    root = make_own_folder(project / "dane", families=("gpkg_layers", "shp_full")).root
    env.scan()
    outcomes: dict[tuple[str, str, str], tuple[list[str], list[str], int]] = {}
    states: dict[tuple[str, str], str] = {}

    # Act
    for path in ("kanalizacja.gpkg", "dzialki.shp"):
        for phase in _BEFORE_RENAME:
            with pytest.raises(Fault):
                env.make(key, path, on_phase=fail_at(phase))
            snapshots_known = len(env.file(key, path).snapshots)
            outcomes[("fault", path, phase)] = (
                _labels(root, path),
                _leftovers(root),
                snapshots_known,
            )
    killed: list[str] = []
    with env.jobs() as jobs:
        for signal_name in ("SIGINT", "SIGKILL"):
            for phase in _BEFORE_RENAME:
                monkeypatch.setenv(SNAPSHOT_FAULT_ENV, f"{phase}:{signal_name}")
                record = _run(jobs, key, "kanalizacja.gpkg")
                states[(signal_name, phase)] = record.state
                left = _leftovers(root)
                outcomes[(signal_name, "kanalizacja.gpkg", phase)] = (
                    _labels(root, "kanalizacja.gpkg"),
                    [name for name in left if name not in killed],
                    len(env.file(key, "kanalizacja.gpkg").snapshots),
                )
                killed = left
        monkeypatch.setenv(SNAPSHOT_FAULT_ENV, "published:SIGKILL")
        published = _run(jobs, key, "kanalizacja.gpkg")
    labels = _labels(root, "kanalizacja.gpkg")
    indexed_before_scan = len(env.file(key, "kanalizacja.gpkg").snapshots)
    env.scan()
    card = env.file(key, "kanalizacja.gpkg")

    # Assert
    for (how, name, step), (found, left, known) in outcomes.items():
        assert found == [], (how, name, step)
        assert known == 0, (how, name, step)
        if how == "SIGKILL":
            assert len(left) == 1, (how, step, left)
        else:
            assert left == [], (how, name, step)
    for (signal_name, step), state in states.items():
        expected = "interrupted" if signal_name == "SIGINT" else "failed"
        assert state == expected, (signal_name, step)
    assert published.state == "failed"
    assert len(labels) == 1 and indexed_before_scan == 0
    directory = root / ".wersje" / "kanalizacja.gpkg" / labels[0]
    raw, document = parse_snapshot_document((directory / "migawka.json").read_bytes())
    assert raw["label"] == labels[0]
    assert {_mode(path) for path in directory.iterdir()} == {0o444}
    assert [(s.label, s.state) for s in card.snapshots] == [(labels[0], "ok")]
    assert card.file.change == "unchanged"
    assert _integrity(directory / "kanalizacja.gpkg") == ["ok"]
    assert document.files[0].sha256 == file_sha256(directory / "kanalizacja.gpkg")


@pytest.mark.parametrize("swapped", [".incoming", ".wersje"])
def test_snapshot_symlink_swap_before_work_creation_stays_in_project(
    env: SnapshotEnv, monkeypatch: pytest.MonkeyPatch, swapped: str
) -> None:
    """Replacing a checked destination cannot redirect the copied files outside."""
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("csv",)).root
    env.scan()
    outside = env.root / "outside"
    outside.mkdir()
    if swapped == ".wersje":
        (outside / ".incoming").mkdir()
    original_owner = process_owner
    swapped_once = False

    def swap_before_work() -> str:
        nonlocal swapped_once
        if not swapped_once:
            checked = root / ".wersje"
            if swapped == ".incoming":
                checked /= ".incoming"
            checked.rename(checked.with_name(f"{checked.name}-detached"))
            checked.symlink_to(outside, target_is_directory=True)
            swapped_once = True
        return original_owner()

    class StopAfterCopy(Exception):
        pass

    def check_copy(phase: SnapshotPhase) -> None:
        if phase == "copy":
            if swapped == ".wersje":
                assert list((outside / ".incoming").iterdir()) == []
            else:
                assert list(outside.iterdir()) == []
            raise StopAfterCopy

    monkeypatch.setattr(snapshots, "process_owner", swap_before_work)
    with pytest.raises(StopAfterCopy):
        env.make(key, "pomiary.csv", on_phase=check_copy)
    assert swapped_once


def test_snapshot_symlink_swap_before_publish_stays_in_project(
    env: SnapshotEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish must rename under its checked destination, not a new symlink."""
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("csv",)).root
    env.scan()
    outside = env.root / "outside"
    outside.mkdir()
    original_rename = snapshots._rename_exclusive
    detached = root / ".wersje" / "pomiary.csv-detached"
    swapped_once = False

    def swap_before_rename(source: str, target: str, **options: int) -> None:
        nonlocal swapped_once
        parent = root / ".wersje" / "pomiary.csv"
        parent.rename(detached)
        parent.symlink_to(outside, target_is_directory=True)
        swapped_once = True
        original_rename(source, target, **options)

    class StopAfterPublish(Exception):
        pass

    def check_publish(phase: SnapshotPhase) -> None:
        if phase == "published":
            assert list(outside.iterdir()) == []
            assert len(list(detached.iterdir())) == 1
            raise StopAfterPublish

    monkeypatch.setattr(snapshots, "_rename_exclusive", swap_before_rename)
    with pytest.raises(StopAfterPublish):
        env.make(key, "pomiary.csv", on_phase=check_publish)
    assert swapped_once


def test_same_content_makes_no_second_snapshot(env: SnapshotEnv) -> None:
    """The content of the last snapshot is ``unchanged`` with its label.

    Again without changes, a GeoPackage after VACUUM and a WAL checkpoint and
    a Shapefile copied anew: nothing new in ``.wersje/``. After A, B and A
    again, A gets a new snapshot labelled ``_2`` (same day, same content).
    """
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("gpkg_layers", "shp_full")).root
    env.scan()
    gpkg = root / "kanalizacja.gpkg"
    original = gpkg.read_bytes()

    # Act
    first = env.make(key, "kanalizacja.gpkg")
    again = env.make(key, "kanalizacja.gpkg")
    connection = sqlite3.connect(gpkg)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    vacuumed = env.make(key, "kanalizacja.gpkg")
    shp_first = env.make(key, "dzialki.shp")
    for member in sorted(root.glob("dzialki.*")):
        shutil.copyfile(member, root / f"{member.name}.tmp")
        os.replace(root / f"{member.name}.tmp", member)
    shp_again = env.make(key, "dzialki.shp")
    with GpkgEditor(gpkg) as editor:
        editor.begin()
        editor.insert("przewody", _pipe(), srednica_mm=999, material="PE")
        editor.commit()
    changed = env.make(key, "kanalizacja.gpkg")
    gpkg.write_bytes(original)
    back = env.make(key, "kanalizacja.gpkg")

    # Assert
    assert first.status == "created"
    for result in (again, vacuumed):
        assert (result.status, result.label) == ("unchanged", first.label)
        assert result.directory == first.directory
    assert (shp_first.status, shp_again.status) == ("created", "unchanged")
    assert shp_again.label == shp_first.label
    assert changed.status == "created" and changed.label != first.label
    assert back.status == "created" and back.label == f"{first.label}_2"
    assert back.document.content == first.document.content
    assert _labels(root, "kanalizacja.gpkg") == sorted(
        [first.label, changed.label, back.label]
    )
    assert _labels(root, "dzialki.shp") == [shp_first.label]
    assert _leftovers(root) == []


def test_fileset_changing_during_copy_retries_then_fails(
    env: SnapshotEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A set changing during its copy is copied again, at most three times.

    A member changing once costs one more copy and the snapshot is made; one
    changing during every copy fails as ``inconsistent_copy`` after three,
    with no label and nothing left in ``.incoming/``.
    """
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("shp_full",)).root
    env.scan()
    real = snapshots._copy_hashed
    copied: list[str] = []
    changes = [1]

    def changing(source: Path, target: Path, *, dir_fd: int) -> SnapshotFile:
        result = real(source, target, dir_fd=dir_fd)
        copied.append(source.name)
        if source.suffix == ".dbf" and changes[0] > 0:
            changes[0] -= 1
            found = source.stat()
            os.utime(source, ns=(found.st_atime_ns, found.st_mtime_ns + 10**9))
        return result

    monkeypatch.setattr(snapshots, "_copy_hashed", changing)

    # Act
    retried = env.make(key, "dzialki.shp")
    copies_once = copied.count("dzialki.shp")
    copied.clear()
    changes[0] = 100
    with pytest.raises(SnapshotFailedError) as failed:
        env.make(key, "dzialki.shp")

    # Assert
    assert retried.status == "created" and copies_once == 2
    assert (failed.value.code, failed.value.details["reason"]) == (
        "conflict",
        "inconsistent_copy",
    )
    assert "zmieniał się w trakcie kopiowania" in str(failed.value)
    assert copied.count("dzialki.shp") == 3
    assert _labels(root, "dzialki.shp") == [retried.label]
    assert _leftovers(root) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root may write anywhere")
@pytest.mark.parametrize("locked", ["dane", "dane/.wersje"])
def test_read_only_folder_blocked(env: SnapshotEnv, locked: str) -> None:
    """A folder (or ``.wersje/``) without write access blocks the snapshot.

    The plan names the directory, the snapshot raises ``read_only_folder``
    before writing anything.
    """
    # Arrange
    key, project = env.project()
    make_own_folder(project / "dane", families=("tif_2180",))
    env.scan()
    directory = project / locked
    directory.mkdir(exist_ok=True)
    before = _tree(project)
    directory.chmod(0o555)

    # Act
    try:
        plan = env.plan(key, "nmt.tif")
        with pytest.raises(SnapshotBlockedError) as blocked:
            env.make(key, "nmt.tif")
        after = _tree(project)
        wersje = (
            sorted(os.listdir(project / "dane" / ".wersje")) if locked != "dane" else []
        )
    finally:
        directory.chmod(0o755)

    # Assert
    assert plan.blocked is not None and plan.blocked.reason == "read_only_folder"
    assert str(directory) in plan.blocked.message
    assert plan.free_bytes is not None and plan.free_bytes > 0
    assert blocked.value.reason == "read_only_folder"
    assert after == before and wersje == []


@pytest.mark.parametrize("tight", ["folder", "work"])
def test_insufficient_space_blocked(
    env: SnapshotEnv, monkeypatch: pytest.MonkeyPatch, tight: str
) -> None:
    """Less free space than 1.1 times the file blocks the snapshot.

    In the data folder, and for a SQLite file in the local work directory
    its copy is made in.
    """
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("gpkg_layers",)).root
    env.scan()
    size = (root / "kanalizacja.gpkg").stat().st_size
    full = Path(os.path.realpath(root if tight == "folder" else env.work_dir))
    real = shutil.disk_usage

    def usage(path: str | os.PathLike[str]) -> Any:
        found = real(path)
        if Path(os.path.realpath(path)) == full:
            return found._replace(free=size)
        return found

    monkeypatch.setattr(shutil, "disk_usage", usage)

    # Act
    plan = env.plan(key, "kanalizacja.gpkg")
    with pytest.raises(SnapshotBlockedError) as blocked:
        env.make(key, "kanalizacja.gpkg")

    # Assert
    assert plan.blocked is not None and plan.blocked.reason == "insufficient_space"
    assert "Za mało miejsca" in plan.blocked.message
    assert str(full) in plan.blocked.message
    assert blocked.value.reason == "insufficient_space"
    assert not (root / ".wersje").exists()


def test_default_folder_inside_store_is_refused(env: SnapshotEnv) -> None:
    """A project with its manifest in a store: the job is ``snapshot_blocked``.

    Its default ``dane/`` lies in the store (``folder_invalid``), checked
    before the file is looked up; the store stays as it was.
    """
    # Arrange
    store = env.root / "magazyn"
    store.mkdir()
    directory = project_inside_store(store)
    key, _ = env.project("W magazynie", directory)
    make_own_folder(directory / "dane", families=("gpkg_layers",))
    before = _tree(store)

    # Act
    with env.jobs() as jobs:
        record = _run(jobs, key, "kanalizacja.gpkg")

    # Assert
    assert record.state == "failed" and record.error is not None
    assert (record.error.code, record.error.reason) == (
        "conflict",
        "snapshot_blocked",
    )
    assert record.error.details["blocked_by"] == "folder_invalid"
    assert "leży w magazynie" in record.error.detail
    assert _tree(store) == before
    assert not (directory / "dane" / ".wersje").exists()


def test_second_snapshot_of_file_conflicts(env: SnapshotEnv) -> None:
    """One snapshot of a file at a time; another file's snapshot runs alongside.

    The second request for the same file is a ``JobConflictError`` naming the
    first job, a note over 2000 characters is refused, and the job's actor
    is the snapshot's author: an agent with its session label.
    """
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("gpkg_layers", "tif_2180")).root
    env.scan()
    agent = replace(LOCAL_OWNER, kind="agent", session="Agent testowy")

    # Act
    with env.jobs() as jobs:
        first = _submit(jobs, key, "kanalizacja.gpkg", note="pierwsza")
        with pytest.raises(JobConflictError) as conflict:
            _submit(jobs, key, "kanalizacja.gpkg", note="druga")
        other = _submit(jobs, key, "nmt.tif", actor=agent)
        with pytest.raises(ValueError, match="invalid snapshot parameters"):
            _submit(jobs, key, "nmt.tif", note="x" * 2001)
        done = {
            job.id: jobs.wait(job.id, timeout=JOB_TIMEOUT_S) for job in (first, other)
        }

    # Assert
    assert conflict.value.job_id == first.id
    assert "Migawka tego pliku już trwa" in str(conflict.value)
    assert {record.state for record in done.values()} == {"succeeded"}
    gpkg, tif = done[first.id].result, done[other.id].result
    assert gpkg is not None and tif is not None
    assert set(gpkg) == {"status", "label", "content_sha256", "size_bytes", "seconds"}
    assert (gpkg["status"], tif["status"]) == ("created", "created")
    tif_dir = root / ".wersje" / "nmt.tif" / tif["label"]
    raw, document = parse_snapshot_document((tif_dir / "migawka.json").read_bytes())
    assert raw["author"] == {
        "id": "local",
        "kind": "agent",
        "name": None,
        "session": "Agent testowy",
    }
    gpkg_dir = root / ".wersje" / "kanalizacja.gpkg" / gpkg["label"]
    assert json.loads((gpkg_dir / "migawka.json").read_text("utf-8"))["note"] == (
        "pierwsza"
    )
    card = env.file(key, "kanalizacja.gpkg")
    assert [s.label for s in card.snapshots] == [gpkg["label"]]
    assert card.file.change == "unchanged"
    assert document.content.sha256 == tif["content_sha256"]


def test_published_files_read_only(env: SnapshotEnv) -> None:
    """Files are ``0444`` already at the rename, the directory ``0555`` after it."""
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("shp_full",)).root
    env.scan()
    seen: dict[str, dict[str, int]] = {}

    def inspect(phase: SnapshotPhase) -> None:
        if phase == "rename":
            work = next((root / ".wersje" / ".incoming").iterdir())
            seen["rename"] = {path.name: _mode(path) for path in work.iterdir()}
        if phase == "published":
            target = next((root / ".wersje" / "dzialki.shp").iterdir())
            seen["published"] = {path.name: _mode(path) for path in target.iterdir()}
            seen["directory"] = {target.name: _mode(target)}

    # Act
    result = env.make(key, "dzialki.shp", on_phase=inspect)

    # Assert
    names = {"dzialki.shp", "dzialki.shx", "dzialki.dbf", "dzialki.prj", "dzialki.cpg"}
    assert seen["rename"] == dict.fromkeys([*names, "migawka.json"], 0o444)
    assert seen["published"] == seen["rename"]
    assert seen["directory"] == {result.label: 0o700}
    assert _mode(result.directory) == 0o555
    assert {_mode(path) for path in result.directory.iterdir()} == {0o444}
    assert _leftovers(root) == []


def test_chmod_and_directory_fsync_errors_are_notices(
    env: SnapshotEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``chmod`` refused (EPERM) and a directory sync refused (EINVAL) only warn."""
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("tif_2180",)).root
    env.scan()
    real_root = Path(os.path.realpath(root))
    real_chmod, real_fsync = os.fchmod, os.fsync

    def chmod(descriptor: int, mode: int) -> None:
        path = Path(os.path.realpath(f"/proc/self/fd/{descriptor}"))
        if path.is_relative_to(real_root):
            raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), str(path))
        real_chmod(descriptor, mode)

    def fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fchmod", chmod)
    monkeypatch.setattr(os, "fsync", fsync)

    # Act
    result = env.make(key, "nmt.tif")

    # Assert
    assert result.status == "created"
    assert [w.code for w in result.warnings] == [
        "chmod_refused",
        "directory_sync_refused",
    ]
    assert all(w.message for w in result.warnings)
    assert _labels(root, "nmt.tif") == [result.label]
    assert _mode(result.directory / "nmt.tif") == 0o600
    assert file_sha256(result.directory / "nmt.tif") == file_sha256(root / "nmt.tif")


@pytest.mark.parametrize("taken", ["empty", "complete"])
def test_label_taken_before_rename_is_target_exists(
    env: SnapshotEnv, taken: str
) -> None:
    """A label published meanwhile by another process is never replaced.

    Even an empty directory under the label stays; the snapshot fails as
    ``target_exists`` and leaves nothing in ``.incoming/``.
    """
    # Arrange
    key, project = env.project()
    root = make_own_folder(project / "dane", families=("tif_2180",)).root
    env.scan()
    taken_dirs: list[Path] = []

    def publish_first(phase: SnapshotPhase) -> None:
        if phase == "rename":
            work = next((root / ".wersje" / ".incoming").iterdir())
            label = json.loads((work / "migawka.json").read_text("utf-8"))["label"]
            target = root / ".wersje" / "nmt.tif" / label
            target.mkdir(parents=True)
            if taken == "complete":
                (target / "nmt.tif").write_bytes(b"inna")
            taken_dirs.append(target)

    # Act
    with pytest.raises(SnapshotFailedError) as failed:
        env.make(key, "nmt.tif", on_phase=publish_first)

    # Assert
    assert (failed.value.code, failed.value.details["reason"]) == (
        "conflict",
        "target_exists",
    )
    target = taken_dirs[0]
    expected = ["nmt.tif"] if taken == "complete" else []
    assert sorted(os.listdir(target)) == expected
    assert _labels(root, "nmt.tif") == [target.name]
    assert _leftovers(root) == []


def test_document_validates_and_sums_match(env: SnapshotEnv) -> None:
    """``migawka.json`` is a valid ``archiwista-snapshot/1`` of exactly its files.

    Its fields are those of the schema in order; the label is today's date
    and the content's first eight characters; the content identity is the
    one the scan computed of the working file; every file has its size and
    SHA-256; the layers, raster and extent are read from the copy.
    """
    # Arrange
    key, project = env.project()
    families = ("gpkg_layers", "shp_full", "tif_2180", "csv")
    root = make_own_folder(project / "dane", families=families).root
    env.scan()
    cases = [
        ("kanalizacja.gpkg", "sqlite", "sqlite_backup", "GPKG"),
        ("dzialki.shp", "fileset", "files", "ESRI Shapefile"),
        ("nmt.tif", "bytes", "files", "GTiff"),
        ("pomiary.csv", "bytes", "files", None),
    ]
    today = datetime.now().astimezone().date().isoformat()

    # Act
    made = {path: env.make(key, path, note="przed przebudową") for path, *_ in cases}

    # Assert
    for path, method, copy_method, driver in cases:
        result, detail = made[path], env.file(key, path)
        raw, document = parse_snapshot_document(
            (result.directory / "migawka.json").read_bytes()
        )
        assert list(raw) == _SCHEMA_KEYS, path
        assert document == result.document
        assert document.label == result.label == result.directory.name
        assert detail.content_sha256 is not None
        assert document.label == f"{today}_{detail.content_sha256[:8]}"
        assert (document.content.method, document.content.sha256) == (
            method,
            detail.content_sha256,
        )
        assert document.copied.method == copy_method
        assert document.source.path == path and document.source.format == driver
        assert document.source.size_bytes == detail.file.size_bytes
        assert document.created_at.utcoffset() is not None
        assert document.author == LOCAL_AUTHOR and document.note == "przed przebudową"
        on_disk = sorted(p.name for p in result.directory.iterdir())
        assert on_disk == sorted(
            [*(item.name for item in document.files), "migawka.json"]
        )
        for item in document.files:
            copy = result.directory / item.name
            assert item.size_bytes == copy.stat().st_size, item.name
            assert item.sha256 == file_sha256(copy), item.name
        assert document.size_bytes == sum(item.size_bytes for item in document.files)
    gpkg = made["kanalizacja.gpkg"].document
    assert gpkg.layers is not None
    assert [(x.name, x.geometry_type, x.feature_count) for x in gpkg.layers] == [
        ("przewody", "LineString", 3),
        ("zlewnie", "Polygon", 2),
    ]
    assert [f.name for f in gpkg.layers[0].fields] == ["srednica_mm", "material"]
    assert (gpkg.feature_count, gpkg.raster) == (5, None)
    assert gpkg.extent is not None and gpkg.extent.crs == "EPSG:2180"
    assert gpkg.extent.wgs84 is not None and _KRAKOW.contains(box(*gpkg.extent.wgs84))
    shp = made["dzialki.shp"].document
    assert [item.name for item in shp.files] == [
        "dzialki.shp",
        "dzialki.shx",
        "dzialki.dbf",
        "dzialki.prj",
        "dzialki.cpg",
    ]
    tif = made["nmt.tif"].document
    assert tif.raster is not None and tif.layers is None
    assert (tif.raster.width, tif.raster.height, tif.raster.crs) == (
        64,
        64,
        "EPSG:2180",
    )
    assert tif.extent is not None and tif.extent.wgs84 is not None
    assert _KRAKOW.contains(box(*tif.extent.wgs84))
    csv = made["pomiary.csv"].document
    assert (csv.layers, csv.raster, csv.extent, csv.feature_count) == (
        None,
        None,
        None,
        None,
    )
    assert _leftovers(root) == []
