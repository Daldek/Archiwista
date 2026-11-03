"""Scan the data folders of projects: files, content, snapshots (decision 8).

``scan_own_data`` takes each project's data folder (``AppSettings.own_data_dir``)
and first checks it (``check_own_folder``): a folder whose path lies inside
the project's directory (the default ``dane/`` and every folder an owner who
is no administrator sets) must still lie there after ``realpath``, so a
folder replaced by a symbolic link out of the project is ``invalid``; and,
by the rules of decision 8 (``own_folder_conflict``), a folder in a store,
overlapping Archiwista's data or another project's folder is ``invalid``.
An ``invalid`` folder is never read. A valid folder is
walked in the order of its paths (relative, in NFC), skipping hidden files
and directories (``.wersje/`` too), SQLite companions (``-wal``, ``-shm``,
``-journal``), the members of a file set and symbolic links leading out of
the folder (``path_outside_root``). Scans exceeding the file, entry,
directory, depth or snapshot limits report ``own_folder_too_large``.

A file whose size, modification time, inode and change time (with its set's
members and SQLite ``-wal`` or ``-journal``) equal the index costs one ``stat``.
A new or changed one is read by the reader process (``OwnReader``: driver,
layers, CRS, extent) and its content identity is computed here
(``content_identity``); its extent gets a WGS84 polygon (``outline_wgs84``)
with the producer's pinned operation. A file that changed while it was read
is unreadable until the next scan reads it again. Snapshots come from
``.wersje/**/migawka.json`` (``SnapshotDocument``), also those published
without an index entry; leftovers of interrupted snapshots older than 24
hours in ``.wersje/.incoming/`` are problems. Nothing in a folder is ever
written.
"""

import json
import logging
import os
import sqlite3
import stat
import time
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from archiwista.auth import ALL_PROJECTS, access_key
from archiwista.config import (
    AppPaths,
    AppSettings,
    OwnFolderReason,
    OwnFolderSource,
    own_folder_conflict,
)
from archiwista.errors import InconsistentReadError, ProducerError
from archiwista.formats import file_format
from archiwista.index import (
    MAX_OWN_FILES,
    BBox,
    IndexQueries,
    IndexWriter,
    KnownOwnFile,
    OwnFileWrite,
    OwnFolderState,
    OwnProblem,
    OwnReadState,
    ProjectRef,
    SnapshotState,
    SnapshotWrite,
    TransformerFactory,
)
from archiwista.index.geometry import WGS84, is_wgs84, outline_wgs84
from archiwista.owndata.content import (
    ContentIdentity,
    content_identity,
    content_method,
)
from archiwista.owndata.document import (
    INCOMING_DIR,
    SNAPSHOT_FILE,
    SNAPSHOTS_DIR,
    InvalidSnapshotError,
    UnknownSnapshotSchemaError,
    read_snapshot_document,
    snapshot_files_match,
)
from archiwista.owndata.formats import (
    FILESET_SUFFIXES,
    SQLITE_COMPANION_SUFFIXES,
    fileset_members,
)
from archiwista.owndata.reader import OwnFileInfo, OwnReader
from archiwista.sandbox import process_work_dir
from archiwista.sources import CoordinateTransformer, GeoJSONGeometry

logger = logging.getLogger(__name__)

# Leftovers of interrupted snapshots older than this are a problem.
STALE_INCOMING = timedelta(hours=24)
# Files written to the index in one transaction (and one progress event).
WRITE_BATCH = 50
# Per-project bounds across the working tree, snapshots and incoming leftovers.
# They include skipped/hidden entries, before any directory is sorted.
MAX_SCAN_ENTRIES = 50_000
MAX_SCAN_DIRECTORIES = 25_000
MAX_SCAN_DEPTH = 64
MAX_SCAN_SNAPSHOTS = 10_000
# The companions that change while a SQLite file is edited (``-shm`` is the
# editor's shared memory: SQLite may change its content, never its data).
_STAMPED_COMPANIONS = ("-wal", "-journal")
# Half a metre (or about as much of a degree) around an extent without
# area, e.g. of a single point, so the file still has a place on the map.
_POINT_PAD = 0.5
_POINT_PAD_DEGREES = 0.5 / 111_320

type _Entry = tuple[str, os.DirEntry[str] | None, "_Found | None"]


@dataclass(frozen=True, slots=True)
class OwnScanProgress:
    """How far a scan got: folders done of all, files listed and read so far."""

    current: int
    total: int
    files: int
    read: int


type OwnScanListener = Callable[[OwnScanProgress], None]


@dataclass(slots=True)
class OwnScanSummary:
    """What one ``own_scan`` found and changed (the job's result).

    Attributes
    ----------
    projects : int
        Data folders scanned (also those ``invalid`` or missing).
    files : int
        Files listed in the folders.
    new, changed : int
        Files read for the first time, and files read again after a change.
    missing : int
        Files newly gone.
    unreadable : int
        Files read in this scan that could not be read.
    snapshots : int
        Snapshots newly recorded, or whose state changed.
    problems : int
        Problems found for the first time.
    seconds : float
        Duration of the scan.
    """

    projects: int = 0
    files: int = 0
    new: int = 0
    changed: int = 0
    missing: int = 0
    unreadable: int = 0
    snapshots: int = 0
    problems: int = 0
    seconds: float = 0.0

    def result(self) -> dict[str, int | float]:
        """Return the summary as the ``own_scan`` job's result (numbers only)."""
        return {
            "projects": self.projects,
            "files": self.files,
            "new": self.new,
            "changed": self.changed,
            "missing": self.missing,
            "unreadable": self.unreadable,
            "snapshots": self.snapshots,
            "problems": self.problems,
            "seconds": round(self.seconds, 3),
        }


def scan_own_data(
    writer: IndexWriter,
    projects: Sequence[ProjectRef],
    *,
    known_projects: Sequence[ProjectRef],
    settings: AppSettings,
    paths: AppPaths,
    transformer: TransformerFactory | None,
    prune: bool = False,
    now: datetime | None = None,
    on_progress: OwnScanListener | None = None,
    reader: OwnReader | None = None,
) -> OwnScanSummary:
    """Scan the data folders of ``projects`` into the index.

    Parameters
    ----------
    writer : IndexWriter
        Writer of the local index.
    projects : Sequence[ProjectRef]
        Projects whose folders to scan: all of them, or one.
    known_projects : Sequence[ProjectRef]
        Every indexed project: their folders and stores take part in the
        rules of each folder, and with ``prune`` the folders of other
        projects leave the index.
    settings : AppSettings
        Stores (their producer directories) and ``own_data_dirs``.
    paths : AppPaths
        Archiwista's data directory (no folder may overlap it) and the work
        directory of the reader and of SQLite copies.
    transformer : TransformerFactory or None
        The producer's pinned operations to WGS84 (``GeoAdapter.transformer``);
        ``None``: only files in WGS84 get an outline.
    prune : bool, default False
        Forget the folders of projects that are no longer indexed.
    now : datetime or None, optional
        Time of the scan; the current time when omitted.
    on_progress : OwnScanListener or None, optional
        Called after each folder and each batch of files.
    reader : OwnReader or None, optional
        The reader process to use; one is started (and ended) when omitted.

    Returns
    -------
    OwnScanSummary
        Counts for the job's result.

    Raises
    ------
    OwnReaderError
        The reader process cannot be started.
    """
    started = time.perf_counter()
    moment = now or datetime.now(UTC)
    summary = OwnScanSummary()
    stores, folders = folder_rules(settings, known_projects)
    transformers = Wgs84Outlines(transformer)
    active = reader or OwnReader(paths)
    try:
        for position, project in enumerate(projects):
            others = [
                folder for key, folder in folders.items() if key != project.access_key
            ]
            _FolderScan(
                writer=writer,
                project=project,
                settings=settings,
                paths=paths,
                transformers=transformers,
                reader=active,
                now=moment,
                summary=summary,
                progress=(on_progress, position, len(projects)),
            ).run(stores=stores, others=others)
            summary.projects += 1
            _report(on_progress, position + 1, len(projects), summary)
    finally:
        if reader is None:
            active.close()
    if prune:
        writer.remove_own_folders(
            keep={project.access_key for project in known_projects}
        )
    summary.seconds = time.perf_counter() - started
    return summary


def _stat_stamp(found: os.stat_result) -> tuple[int, int, int | None, int | None]:
    """Record file identity beyond timestamp and length where supported."""
    return (
        found.st_size,
        found.st_mtime_ns,
        getattr(found, "st_ino", None),
        getattr(found, "st_ctime_ns", None),
    )


def snapshot_stamp(directory: Path) -> tuple[str, int]:
    """Return the stamp of a snapshot directory and the bytes of its copy.

    The stamp (names, sizes, modification times and available inode/change
    times of its files) tells a scan whether to check a snapshot again; the
    ``snapshot`` job records it with a snapshot it published. The byte count
    leaves ``migawka.json`` out, like the document's ``size_bytes``.

    Raises
    ------
    OSError
        The directory cannot be listed.
    """
    rows = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_file(follow_symlinks=False):
                found = entry.stat(follow_symlinks=False)
                rows.append((entry.name, *_stat_stamp(found)))
    rows.sort()
    size = sum(row[1] for row in rows if row[0] != SNAPSHOT_FILE)
    return _dump(rows), size


def stamp_holds(main: Path, stamp: str) -> bool:
    """Whether a file is still as a scan stamped it (``OwnFileWrite.stamp``).

    Every file the stamp names (the main file, the members of its set and a
    SQLite ``-wal`` or ``-journal``, all next to ``main``) must retain its
    stamped size, modification time, inode and change time where available.
    Old two-field stamps are rejected so the scan can refresh their identity.
    No ``-wal`` or ``-journal`` may have appeared next to ``main`` since.
    These checks need only ``stat`` calls; a member added to a set since the
    scan goes unnoticed until the next scan.

    Parameters
    ----------
    main : Path
        The main file as the scan listed it: below the folder's real path,
        by its name on the disk (``OwnFileDetail.disk_path``).
    stamp : str
        The stamp the scan recorded.

    Returns
    -------
    bool
        ``False`` also for a stamp that cannot be read or a file gone.
    """
    try:
        rows = json.loads(stamp)
        stamped = {
            str(name): (int(size), int(mtime), inode, changed_ns)
            for name, size, mtime, inode, changed_ns in rows
        }
    except (TypeError, ValueError):
        return False
    for name, expected in stamped.items():
        try:
            found = os.stat(main.parent / name)
        except OSError:
            return False
        if _stat_stamp(found) != expected:
            return False
    return not any(
        f"{main.name}{suffix}" not in stamped
        and os.path.lexists(main.with_name(f"{main.name}{suffix}"))
        for suffix in _STAMPED_COMPANIONS
    )


@dataclass(slots=True)
class _Found:
    """A file of a folder as listed: where it is and its stamp."""

    path: str
    disk_path: str
    absolute: Path
    stamped: tuple[Path, ...]
    stamp: str
    size_bytes: int
    modified_ns: int


@dataclass(slots=True)
class _Listing:
    """What a walk over a folder found."""

    files: list[_Found] = field(default_factory=list)
    outside: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    invalid_names: list[str] = field(default_factory=list)
    too_large: bool = False


@dataclass(slots=True)
class _ScanBudget:
    """Bound one project's traversal, including snapshots and hidden entries."""

    entries: int = 0
    directories: int = 0
    snapshots: int = 0

    def enter_directory(self, depth: int) -> None:
        if depth > MAX_SCAN_DEPTH or self.directories >= MAX_SCAN_DIRECTORIES:
            raise _ScanLimitError
        self.directories += 1

    def add_entry(self) -> None:
        if self.entries >= MAX_SCAN_ENTRIES:
            raise _ScanLimitError
        self.entries += 1

    def add_snapshot(self) -> None:
        if self.snapshots >= MAX_SCAN_SNAPSHOTS:
            raise _ScanLimitError
        self.snapshots += 1


class _ScanLimitError(Exception):
    """The per-project scan cannot safely list the entire folder."""


class _FolderUnreadableError(OSError):
    """The folder itself cannot be listed."""


class Wgs84Outlines:
    """WGS84 outlines of extents with the producer's operations, one per CRS.

    An operation is made once per CRS and kept, also one that failed. An
    extent without area (a single point, an axis-parallel line) gets a
    margin of half a metre (or about as much of a degree) first, so the
    file still has a place on the map. Used by the scan and by snapshots
    (``migawka.json``).

    Parameters
    ----------
    factory : TransformerFactory or None
        The producer's pinned operations to WGS84 (``GeoAdapter.transformer``);
        ``None``: only extents in WGS84 get an outline.
    """

    def __init__(self, factory: TransformerFactory | None) -> None:
        self._factory = factory
        self._made: dict[str, CoordinateTransformer | Exception] = {}

    def outline(self, bbox: BBox, crs: str) -> GeoJSONGeometry:
        """Return the WGS84 polygon of a rectangle in ``crs``, with its margin.

        Raises
        ------
        ValueError, ProducerError
            No operation for ``crs``, or one that failed.
        """
        bbox = _padded(bbox, crs)
        if is_wgs84(crs):
            return outline_wgs84(bbox, crs, None)
        if self._factory is None:
            raise ValueError("no producer with coordinate operations")
        made = self._made.get(crs)
        if made is None:
            try:
                made = self._factory(crs, WGS84)
            except (ProducerError, ValueError) as error:
                made = error
            self._made[crs] = made
        if isinstance(made, Exception):
            raise made
        return outline_wgs84(bbox, crs, made)


@dataclass(frozen=True, slots=True)
class OwnFolderCheck:
    """A project's data folder and its state now, before any file is read."""

    path: Path
    source: OwnFolderSource
    state: OwnFolderState
    reason: OwnFolderReason | None = None


def check_own_folder(
    settings: AppSettings,
    project: str,
    *,
    stores: Sequence[Path],
    app_data: Path,
    others: Sequence[Path],
) -> OwnFolderCheck:
    """Check a project's data folder against its rules now, then on the disk.

    The one check of a folder before anything in it is read or written (a
    scan, a snapshot). A folder whose path lies inside the project's
    directory must lie there after ``realpath`` too (``outside_project``):
    the default ``dane/`` and every folder an owner who is no administrator
    sets (``set_data_dir`` saves it as its real path), so a folder replaced
    later by a symbolic link out of the project is not read. Only an
    administrator's folder elsewhere lies outside the project. Then the
    rules of decision 8 (``own_folder_conflict``).

    Parameters
    ----------
    settings : AppSettings
        ``own_data_dirs`` (the folder, or ``<project>/dane``).
    project : str
        The project directory after ``realpath`` (``access_key``).
    stores : Sequence[Path]
        Producer directories of the stores (also of projects' own stores).
    app_data : Path
        Archiwista's data directory.
    others : Sequence[Path]
        Data folders of the other projects.

    Returns
    -------
    OwnFolderCheck
        ``invalid`` with its reason, else ``missing``, ``unreadable`` or
        ``ok`` as the folder is on the disk.
    """
    folder, source = settings.own_data_dir(project)
    if _written_inside(folder, project) and not inside_project(folder, project):
        return OwnFolderCheck(folder, source, "invalid", "outside_project")
    conflict = own_folder_conflict(
        folder, stores=stores, app_data=app_data, others=others
    )
    if conflict is not None:
        return OwnFolderCheck(folder, source, "invalid", conflict[0])
    return OwnFolderCheck(folder, source, _folder_state(folder))


def inside_project(folder: str | os.PathLike[str], project: str) -> bool:
    """Whether a folder lies inside a project's directory after ``realpath``.

    The directory itself is not inside it, and a relative path lies nowhere
    (it is refused, as a symbolic link out).

    Parameters
    ----------
    folder : str or os.PathLike[str]
        The folder.
    project : str
        The project directory after ``realpath`` (``access_key``).
    """
    if not os.path.isabs(folder):
        return False
    real = Path(access_key(folder))
    return real != Path(project) and real.is_relative_to(project)


def _written_inside(folder: Path, project: str) -> bool:
    """Whether a folder's path, as written, names a place inside the project."""
    written = Path(os.path.normcase(os.path.normpath(folder)))
    return written != Path(project) and written.is_relative_to(project)


def folder_rules(
    settings: AppSettings, known_projects: Sequence[ProjectRef]
) -> tuple[list[Path], dict[str, Path]]:
    """Return the stores' directories and every project's folder, by access key.

    The stores are the configured producer directories and the absolute
    store directories the projects' files name.
    """
    folders = {
        project.access_key: settings.own_data_dir(project.access_key)[0]
        for project in known_projects
    }
    stores = [root for store in settings.stores for root in store.roots().values()]
    stores += [
        Path(entry.root)
        for project in known_projects
        for entry in project.stores
        if os.path.isabs(entry.root)
    ]
    return stores, folders


def folder_check(
    settings: AppSettings, queries: IndexQueries, paths: AppPaths, project: str
) -> OwnFolderCheck:
    """Check a project's data folder now against the rules of every scan.

    ``check_own_folder`` with the stores and the folders of every indexed
    project (``folder_rules``): inside the project's directory after
    ``realpath`` unless an administrator set it elsewhere, and outside the
    stores, Archiwista's data and other projects' folders. What reads or
    writes a folder outside a scan checks it so first (a preview, a
    download, a snapshot's plan); only an ``ok`` folder is read.

    Parameters
    ----------
    settings : AppSettings
        Settings in effect (``own_data_dirs``, the stores).
    queries : IndexQueries
        The indexed projects: their folders and stores take part in the rules.
    paths : AppPaths
        Archiwista's data directory, which no folder may overlap.
    project : str
        The project's access key (``ProjectRef.access_key``).
    """
    known = queries.projects(visible=ALL_PROJECTS)
    stores, folders = folder_rules(settings, known)
    others = [path for key, path in folders.items() if key != project]
    return check_own_folder(
        settings, project, stores=stores, app_data=paths.data_dir, others=others
    )


@dataclass(slots=True)
class _FolderScan:
    """One project's folder in one scan."""

    writer: IndexWriter
    project: ProjectRef
    settings: AppSettings
    paths: AppPaths
    transformers: Wgs84Outlines
    reader: OwnReader
    now: datetime
    summary: OwnScanSummary
    progress: tuple[OwnScanListener | None, int, int]
    problems: list[OwnProblem] = field(default_factory=list)

    def run(self, *, stores: Sequence[Path], others: Sequence[Path]) -> None:
        """Check the folder, then scan its files and snapshots when it is valid."""
        key = self.project.access_key
        check = check_own_folder(
            self.settings,
            key,
            stores=stores,
            app_data=self.paths.data_dir,
            others=others,
        )
        folder, source, state = check.path, check.source, check.state
        self.writer.write_own_folder(
            key,
            path=str(folder),
            source=source,
            state=state,
            reason=check.reason,
            now=self.now,
        )
        if state == "invalid":
            self.problems.append(OwnProblem("own_folder_invalid", reason=check.reason))
        if state == "unreadable":
            self.problems.append(OwnProblem("own_folder_unreadable"))
        if state == "ok":
            root = Path(os.path.realpath(folder))
            budget = _ScanBudget()
            try:
                self._scan_files(root, budget)
                self._scan_snapshots(root, budget)
            except _ScanLimitError:
                self.problems.append(OwnProblem("own_folder_too_large"))
            except _FolderUnreadableError:
                self.writer.write_own_folder(
                    key,
                    path=str(folder),
                    source=source,
                    state="unreadable",
                    now=self.now,
                )
                self.problems = [OwnProblem("own_folder_unreadable")]
        self._finish()

    def _finish(self) -> None:
        self.summary.problems += self.writer.finish_own_folder(
            self.project.access_key, problems=self.problems, now=self.now
        )

    def _scan_files(self, root: Path, budget: _ScanBudget) -> None:
        key = self.project.access_key
        known = self.writer.known_own_files(key)
        listing = _walk(root, MAX_OWN_FILES, budget)
        if listing.too_large:
            self.problems.append(OwnProblem("own_folder_too_large"))
        self.problems.extend(
            OwnProblem("path_outside_root", path=path) for path in listing.outside
        )
        self.problems.extend(
            OwnProblem("own_folder_unreadable", path=path)
            for path in listing.unreadable
        )
        self.problems.extend(
            OwnProblem("own_file_unreadable", path=path, reason="invalid_name")
            for path in listing.invalid_names
        )
        present = {found.path for found in listing.files}
        # Files below a directory that could not be listed stay as they were.
        kept = {
            path
            for path in known
            if any(path.startswith(f"{folder}/") for folder in listing.unreadable)
        }
        drop: set[str] = set()
        if listing.too_large and listing.files:
            last = listing.files[-1].path
            drop = {path for path in known if path > last and path not in kept}
        batch: list[OwnFileWrite] = []
        for found in listing.files:
            item = known.get(found.path)
            if item is not None and item.stamp == found.stamp and not item.retry:
                self._known_problem(found.path, item)
                continue
            written = self._read(root, found)
            if written.state == "unreadable":
                self.summary.unreadable += 1
                self.problems.append(_file_problem(found.path, written.read_error))
            batch.append(written)
            if len(batch) >= WRITE_BATCH:
                self._write(batch)
                batch = []
        self._write(batch)
        for path in kept:
            self._known_problem(path, known[path])
        result = self.writer.mark_own_missing(
            key, present=present | kept, drop=drop, now=self.now
        )
        self.summary.missing += result.missing
        self.summary.files += len(listing.files)

    def _known_problem(self, path: str, item: KnownOwnFile) -> None:
        """Report again the problem of a file that was not read again."""
        if item.read_error is not None and not item.missing:
            self.problems.append(_file_problem(path, item.read_error))

    def _write(self, batch: list[OwnFileWrite]) -> None:
        if not batch:
            return
        written = self.writer.write_own_files(
            self.project.access_key, batch, now=self.now
        )
        self.summary.new += written.new
        self.summary.changed += written.changed
        listener, position, total = self.progress
        _report(listener, position, total, self.summary)

    def _read(self, root: Path, found: _Found) -> OwnFileWrite:
        """Read a new or changed file: the reader, its content and its outline.

        A file without a GDAL driver in the format table goes to no reader:
        the reader would answer it unrecognised without opening it.
        """
        real = Path(os.path.realpath(found.absolute))
        listed = _members(real)
        reals = tuple(Path(os.path.realpath(member)) for member in listed)
        path = found.path
        stamp = found.stamp
        size_bytes, modified_ns = found.size_bytes, found.modified_ns
        fmt = file_format(real)
        if not all(member.is_relative_to(root) for member in reals):
            return OwnFileWrite(
                path=path,
                disk_path=found.disk_path,
                stamp=stamp,
                size_bytes=size_bytes,
                modified_ns=modified_ns,
                kind=fmt.kind,
                driver=None,
                members=tuple(member.name for member in listed),
                state="unreadable",
                read_error="path_outside_root",
                location_reason="unreadable",
            )
        names = tuple(_nfc(member.relative_to(root).as_posix()) for member in reals)
        if fmt.driver is None:
            info = OwnFileInfo(fmt.kind, None, (real.name,))
        else:
            info = self.reader.read(real)
        content: ContentIdentity | None = None
        error: str | None = info.error
        retry = False
        try:
            method = content_method(real)
            content = content_identity(
                listed if method == "fileset" else (real,),
                method=method,
                work_dir=process_work_dir(self.paths),
            )
        except InconsistentReadError:
            error, retry = "inconsistent", True
        except (OSError, sqlite3.Error, ValueError) as failure:
            logger.warning("Content of %s not read: %s", path, failure)
            error = error or "unreadable"
        if _stamp(found.stamped) != stamp:
            error, retry, content = "inconsistent", True, None
        state: OwnReadState = "ok" if info.driver else "unrecognized"
        if error is not None:
            state = "unreadable"
        wgs84, reason = self._outline(info, state)
        return OwnFileWrite(
            path=path,
            disk_path=found.disk_path,
            stamp=stamp,
            size_bytes=size_bytes,
            modified_ns=modified_ns,
            kind=info.kind,
            driver=info.driver,
            members=names,
            state=state,
            read_error=error,
            read_detail=info.detail if error == info.error else None,
            content_method=None if content is None else content.method,
            content_sha256=None if content is None else content.sha256,
            layers=info.layers,
            raster=info.raster,
            feature_count=info.feature_count,
            native_crs=info.native_crs,
            native_bbox=info.native_bbox,
            wgs84=wgs84,
            location_reason=reason,
            retry=retry,
        )

    def _outline(
        self, info: OwnFileInfo, state: OwnReadState
    ) -> tuple[GeoJSONGeometry | None, str | None]:
        """Return the WGS84 polygon of a file's extent, or why it has none."""
        if state != "ok":
            return None, state
        if info.raster is not None and not info.raster.georeferenced:
            return None, "no_georeference"
        if info.native_crs is None:
            return None, "no_crs"
        if info.native_bbox is None:
            return None, "no_extent"
        try:
            return self.transformers.outline(info.native_bbox, info.native_crs), None
        except (ProducerError, ValueError) as error:
            logger.info("No WGS84 outline for %s: %s", info.native_crs[:80], error)
            return None, "transform_unavailable"

    def _scan_snapshots(self, root: Path, budget: _ScanBudget) -> None:
        key = self.project.access_key
        known = self.writer.known_own_snapshots(key)
        versions = root / SNAPSHOTS_DIR
        found: list[SnapshotWrite] = []
        keep: set[tuple[str, str]] = set()
        start_problems = len(self.problems)
        try:
            listed = versions.is_dir() and not versions.is_symlink()
        except OSError:
            listed = False
        try:
            if listed:
                try:
                    for directory, path, label in _snapshot_dirs(versions, budget):
                        keep.add((path, label))
                        snapshot = self._snapshot(
                            directory, path, label, known.get((path, label))
                        )
                        if snapshot is not None:
                            found.append(snapshot)
                except OSError as error:
                    logger.warning("Snapshots of %s not listed: %s", root, error)
                    keep.update(known)
                self._stale_incoming(versions / INCOMING_DIR, budget)
        except _ScanLimitError:
            del self.problems[start_problems:]
            raise
        self.summary.snapshots += self.writer.write_own_snapshots(key, found, keep=keep)

    def _snapshot(
        self,
        directory: Path,
        path: str,
        label: str,
        known: tuple[str, str] | None,
    ) -> SnapshotWrite | None:
        """Check a snapshot directory; ``None``: indexed, valid and unchanged.

        A snapshot is checked once, and again after its files change: its
        document (``SnapshotDocument``, also its label and file path) and
        the size and SHA-256 of each file it names. One that is not valid
        is checked at every scan (and reported again).
        """
        place = f"{SNAPSHOTS_DIR}/{path}/{label}"
        stamp, size = snapshot_stamp(directory)
        if known == (stamp, "ok"):
            return None
        try:
            raw, document = read_snapshot_document(directory)
        except UnknownSnapshotSchemaError as error:
            self.problems.append(
                OwnProblem("unknown_snapshot_schema", path=place, reason=error.schema)
            )
            return SnapshotWrite(path, label, "invalid", stamp, size)
        except (InvalidSnapshotError, OSError):
            self.problems.append(OwnProblem("invalid_snapshot", path=place))
            return SnapshotWrite(path, label, "invalid", stamp, size)
        if document.label != label or _nfc(document.source.path) != path:
            self.problems.append(OwnProblem("invalid_snapshot", path=place))
            return SnapshotWrite(path, label, "invalid", stamp, size, document=raw)
        state: SnapshotState = "ok"
        if not snapshot_files_match(directory, document.files):
            state = "modified"
            self.problems.append(OwnProblem("snapshot_modified", path=place))
        return SnapshotWrite(
            path,
            label,
            state,
            stamp,
            size,
            document=raw,
            created_at=document.created_at,
            content_method=document.content.method,
            content_sha256=document.content.sha256,
        )

    def _stale_incoming(self, incoming: Path, budget: _ScanBudget) -> None:
        """Report working directories of snapshots left for more than 24 hours."""
        oldest = (self.now - STALE_INCOMING).timestamp()
        try:
            with os.scandir(incoming) as entries:
                budget.enter_directory(2)
                stale = []
                for entry in entries:
                    budget.add_entry()
                    if (
                        entry.is_dir(follow_symlinks=False)
                        and entry.stat(follow_symlinks=False).st_mtime < oldest
                    ):
                        stale.append(entry.name)
        except OSError:
            return
        self.problems.extend(
            OwnProblem(
                "stale_snapshot_incoming",
                path=f"{SNAPSHOTS_DIR}/{INCOMING_DIR}/{name}",
            )
            for name in sorted(stale)
        )


def _folder_state(folder: Path) -> OwnFolderState:
    """``missing`` without the folder, ``unreadable`` unless a readable directory."""
    try:
        found = folder.stat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if not stat.S_ISDIR(found.st_mode) or not os.access(folder, os.R_OK | os.X_OK):
        return "unreadable"
    return "ok"


def _walk(root: Path, limit: int, budget: _ScanBudget) -> _Listing:
    """List a folder's files in the order of their paths, at most ``limit``.

    Directories are entered depth-first with their entries sorted by name in
    NFC (a directory's name followed by ``/``), which is the order of the
    relative paths. A symbolic link counts by its target when it stays in
    the folder; a directory reached twice is listed once. A budget failure
    discards the incomplete listing without marking existing files missing.

    Raises
    ------
    _FolderUnreadableError
        ``root`` itself cannot be listed.
    _ScanLimitError
        Too many entries or directories, or too deep a directory.
    """
    listing = _Listing()
    visited = {str(root)}
    try:
        stack = [iter(_directory(root, root, "", "", listing, budget, 1))]
    except OSError as error:
        raise _FolderUnreadableError(str(error)) from error
    while stack:
        item = next(stack[-1], None)
        if item is None:
            stack.pop()
            continue
        relative, entry, found = item
        if found is not None:
            if len(listing.files) == limit:
                listing.too_large = True
                return listing
            listing.files.append(found)
            continue
        assert entry is not None
        real = os.path.realpath(entry.path)
        if real in visited:
            continue
        visited.add(real)
        directory = Path(entry.path)
        disk = directory.relative_to(root).as_posix()
        try:
            stack.append(
                iter(
                    _directory(
                        directory, root, relative, disk, listing, budget, len(stack) + 1
                    )
                )
            )
        except OSError:
            listing.unreadable.append(relative)
    return listing


def _directory(
    directory: Path,
    root: Path,
    prefix: str,
    disk_prefix: str,
    listing: _Listing,
    budget: _ScanBudget,
    depth: int,
) -> list[_Entry]:
    """List one directory in path order: files found, directories to enter.

    Raises
    ------
    OSError
        The directory cannot be listed.
    _ScanLimitError
        Listing this directory would exceed the per-project budget.
    """
    budget.enter_directory(depth)
    entries: list[os.DirEntry[str]] = []
    with os.scandir(directory) as scanned:
        for entry in scanned:
            budget.add_entry()
            entries.append(entry)
    names = {entry.name.lower(): entry for entry in entries}
    members_of: dict[str, list[os.DirEntry[str]]] = {}
    member_names: set[str] = set()
    for entry in entries:
        suffixes = FILESET_SUFFIXES.get(Path(entry.name).suffix.lower())
        if suffixes is None or entry.name.startswith("."):
            continue
        stem = Path(entry.name).stem.lower()
        found = [
            names[f"{stem}{suffix}"]
            for suffix in suffixes[1:]
            if f"{stem}{suffix}" in names
        ]
        members_of[entry.name] = found
        member_names.update(member.name for member in found)
    items: list[tuple[str, _Entry]] = []
    for entry in entries:
        name = entry.name
        if name.startswith(".") or name in member_names:
            continue
        if name.endswith(SQLITE_COMPANION_SUFFIXES):
            continue
        try:
            name.encode("utf-8")
        except UnicodeEncodeError:
            shown = name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
            listing.invalid_names.append(_join(prefix, shown))
            continue
        nfc = _nfc(name)
        relative = _join(prefix, nfc)
        try:
            if entry.is_symlink() and not Path(
                os.path.realpath(entry.path)
            ).is_relative_to(root):
                listing.outside.append(relative)
                continue
            if entry.is_dir():
                items.append((f"{nfc}/", (relative, entry, None)))
                continue
            if not entry.is_file():
                continue
            companions = [
                names[f"{name.lower()}{suffix}"]
                for suffix in _STAMPED_COMPANIONS
                if f"{name.lower()}{suffix}" in names
            ]
            found_file = _found(
                relative,
                _join(disk_prefix, name),
                (entry, *members_of.get(name, ())),
                companions,
            )
        except OSError:  # gone since the listing
            continue
        items.append((nfc, (relative, None, found_file)))
    items.sort(key=lambda item: item[0])
    return [item for _, item in items]


def _found(
    relative: str,
    disk: str,
    members: Sequence[os.DirEntry[str]],
    companions: Sequence[os.DirEntry[str]],
) -> _Found:
    """Return a listed file with the stamp of its members and companions."""
    stats = [(entry, entry.stat()) for entry in (*members, *companions)]
    return _Found(
        path=relative,
        disk_path=disk,
        absolute=Path(members[0].path),
        stamped=tuple(Path(entry.path) for entry, _ in stats),
        stamp=_dump(
            sorted((entry.name, *_stat_stamp(found)) for entry, found in stats)
        ),
        size_bytes=sum(found.st_size for _, found in stats[: len(members)]),
        modified_ns=stats[0][1].st_mtime_ns,
    )


def _stamp(stamped: Sequence[Path]) -> str:
    """Return the stamp of a file again, after it was read (as ``_found``)."""
    rows = []
    for path in stamped:
        try:
            found = path.stat()
        except OSError:
            return ""
        rows.append((path.name, *_stat_stamp(found)))
    return _dump(sorted(rows))


def _snapshot_dirs(
    versions: Path, budget: _ScanBudget
) -> Iterator[tuple[Path, str, str]]:
    """Yield ``(directory, file path, label)`` of each snapshot in ``.wersje/``.

    A snapshot is a directory holding ``migawka.json``; its parent below
    ``.wersje/`` is the working file's path. Hidden directories
    (``.incoming/``) and symbolic links are not entered.

    Raises
    ------
    OSError
        A directory cannot be listed.
    _ScanLimitError
        Too many entries, directories or snapshots, or too deep a directory.
    """
    pending = [(versions, 1)]
    while pending:
        directory, depth = pending.pop()
        budget.enter_directory(depth)
        entries: list[os.DirEntry[str]] = []
        with os.scandir(directory) as scanned:
            for entry in scanned:
                budget.add_entry()
                entries.append(entry)
        entries.sort(key=lambda entry: entry.name)
        if directory != versions and any(
            entry.name == SNAPSHOT_FILE and entry.is_file(follow_symlinks=False)
            for entry in entries
        ):
            parts = directory.relative_to(versions).parts
            if len(parts) >= 2:
                budget.add_snapshot()
                yield directory, _nfc("/".join(parts[:-1])), parts[-1]
            continue
        pending.extend(
            (Path(entry.path), depth + 1)
            for entry in reversed(entries)
            if not entry.name.startswith(".") and entry.is_dir(follow_symlinks=False)
        )


def _members(real: Path) -> tuple[Path, ...]:
    """Return the files of a set at its real place, or the file alone."""
    try:
        return fileset_members(real)
    except OSError:
        return (real,)


def _file_problem(path: str, error: str | None) -> OwnProblem:
    """Return the problem of a file not read: a link out of the folder or other."""
    if error == "path_outside_root":
        return OwnProblem("path_outside_root", path=path, reason=error)
    return OwnProblem("own_file_unreadable", path=path, reason=error)


def _padded(bbox: BBox, crs: str) -> BBox:
    """Give an extent an area: a point or an axis-parallel line gets a margin."""
    min_x, min_y, max_x, max_y = bbox
    pad = _POINT_PAD_DEGREES if is_wgs84(crs) else _POINT_PAD
    if min_x == max_x:
        min_x, max_x = min_x - pad, max_x + pad
    if min_y == max_y:
        min_y, max_y = min_y - pad, max_y + pad
    return (min_x, min_y, max_x, max_y)


def _report(
    listener: OwnScanListener | None, current: int, total: int, summary: OwnScanSummary
) -> None:
    if listener is not None:
        read = summary.new + summary.changed
        listener(OwnScanProgress(current, total, summary.files, read))


def _join(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
