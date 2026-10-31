"""Discover project files and record them in the local index (A-ADR-049).

Projects live in the configured project directories (SPEC 4.7): a project
is a directory holding ``archiwista-project.json``, written only by
Archiwista (``archiwista.projects``); a directory holding only a file of a
producer is none. Discovery goes at most ``MAX_PROJECT_DEPTH`` levels below
each project directory, never enters hidden directories or a store's
producer directory, and needs no producer: only a new or changed file (other
size or modification time) is read again, and one whose store matches no
configured store, or whose area was not used, on every pass until it does
(``IndexWriter.project_stamps``). An invalid file, or one of a newer format,
stays visible with its problem. A file that is a symbolic link resolving
outside the configured project directory (SPEC 10.1) is never read: it is
an invalid project (``path_outside_root``). Each producer's store is matched
to a configured store by its resolved path or through a store's path
aliases; the area file is read as JSON and kept as an area of the index
(``areas.area_from_geometry``, with the producer's countries and pinned
operations: without a producer that has them the area is not read). A
project directory that cannot be read keeps the projects indexed under it,
so a disconnected share does not empty the list. ``record_project`` reads
one project again the same way after Archiwista changed it.
"""

import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archiwista.config import StoreConfig
from archiwista.errors import (
    AreaTooComplexError,
    IndexQueryError,
    PathOutsideRootError,
    ProducerError,
    ProjectAreaError,
    ProjectFileError,
)
from archiwista.index.types import (
    ProjectAreaState,
    ProjectStamp,
    ProjectWrite,
)
from archiwista.index.writer import IndexWriter
from archiwista.paths import resolve_indexed_path
from archiwista.projects import (
    PROJECT_FILE,
    ProjectDocument,
    parse_document,
    read_name,
    read_project_area,
    read_project_json,
)
from archiwista.sources import GeoAdapter

# Directory levels searched below a configured project directory.
MAX_PROJECT_DEPTH = 4


@dataclass(frozen=True, slots=True)
class ProjectScanSummary:
    """What one pass over the project directories found and changed.

    Attributes
    ----------
    found : int
        Project files discovered.
    read : int
        Files read because they were new, changed or not matched yet.
    unchanged : int
        Files skipped because their size and modification time match the
        index.
    invalid : int
        Files read that are invalid or of a newer format (kept with their
        problem).
    unknown_store : int
        Files read with a store that matches no configured store.
    removed : int
        Indexed projects whose file is gone.
    unreadable_dirs : tuple[str, ...]
        Directories that could not be listed; their projects were kept.
    """

    found: int = 0
    read: int = 0
    unchanged: int = 0
    invalid: int = 0
    unknown_store: int = 0
    removed: int = 0
    unreadable_dirs: tuple[str, ...] = ()


def scan_projects(
    writer: IndexWriter,
    *,
    project_dirs: Sequence[Path],
    stores: Sequence[StoreConfig],
    geo: GeoAdapter | None,
) -> ProjectScanSummary:
    """Index the project files found in the project directories.

    Parameters
    ----------
    writer : IndexWriter
        Writer of the local index, already synchronised with ``stores``.
    project_dirs : Sequence[Path]
        Configured project directories (``AppSettings.project_dirs``).
    stores : Sequence[StoreConfig]
        All configured stores: their producer directories are not searched,
        and a project's store of a producer is matched to one of them.
    geo : GeoAdapter or None
        A producer's countries and pinned operations, to read a project's
        area; ``None``: the areas are not read.

    Returns
    -------
    ProjectScanSummary
        Counts of found, read, unchanged, invalid and removed projects.
    """
    skipped = {
        os.path.normpath(root) for config in stores for root in config.roots().values()
    }
    unreadable: list[str] = []
    outside: set[str] = set()
    found: dict[str, ProjectStamp] = {}
    for directory in project_dirs:
        for path, stamp in _discover(Path(directory), skipped, unreadable, outside):
            found.setdefault(path, stamp)
    known = writer.project_stamps()
    read = invalid = unknown_store = 0
    for path, stamp in sorted(found.items()):
        if path in known and known[path] == stamp:
            continue
        if path in outside:
            project = _invalid(
                Path(path), stamp, {"pointer": "", "rule": "path_outside_root"}
            )
        else:
            project = _read(writer, Path(path), stamp, stores=stores, geo=geo)
        writer.write_project(project)
        read += 1
        invalid += project.state != "ok"
        unknown_store += None in project.stores.values()
    keep = set(found)
    keep.update(
        path for path in known if any(_inside(path, gone) for gone in unreadable)
    )
    removed = writer.remove_projects(keep=keep)
    return ProjectScanSummary(
        found=len(found),
        read=read,
        unchanged=len(found) - read,
        invalid=invalid,
        unknown_store=unknown_store,
        removed=removed,
        unreadable_dirs=tuple(unreadable),
    )


def record_project(
    writer: IndexWriter,
    directory: Path,
    *,
    stores: Sequence[StoreConfig],
    geo: GeoAdapter | None,
) -> str:
    """Read one project file again and record it as a scan would; return its key.

    For a file Archiwista just changed: the project shows the change at
    once, and the next scan finds the stamp of the file it read (taken
    before the read, so a change in between is read again).

    Parameters
    ----------
    writer : IndexWriter
        Writer of the local index.
    directory : Path
        The project directory as discovery names it: below a configured
        project directory, without resolving symbolic links.
    stores : Sequence[StoreConfig]
        All configured stores, which the project's stores are matched to.
    geo : GeoAdapter or None
        A producer's countries and pinned operations, to read the area.

    Returns
    -------
    str
        The project's key (``ProjectRef.key``), kept when it was indexed.
    """
    try:
        status = os.stat(directory / PROJECT_FILE)
        stamp = ProjectStamp(status.st_mtime_ns, status.st_size)
    except OSError:
        stamp = ProjectStamp(0, 0)
    return writer.write_project(_read(writer, directory, stamp, stores=stores, geo=geo))


def _match_store(
    root: str, directory: Path, producer: str, stores: Sequence[StoreConfig]
) -> str | None:
    r"""Return the configured store whose directory of ``producer`` is ``root``.

    ``root`` as the project file writes it: relative to the project
    ``directory`` or absolute. It matches by its resolved path or through a
    store's path aliases (SPEC 4.6); a path written on another system
    (``Z:\dane\kartograf`` read on Linux) is matched by its text.

    Returns
    -------
    str or None
        The store's id; ``None`` when no configured store matches.
    """
    candidates = [root]
    if not os.path.isabs(root):
        candidates.insert(0, os.path.normpath(os.path.join(directory, root)))
    for config in stores:
        configured = config.roots().get(producer)
        if configured is None:
            continue
        for candidate in candidates:
            if _same_directory(candidate, configured) or _same_directory(
                str(config.local_path(candidate)), configured
            ):
                return config.id
    return None


def _read(
    writer: IndexWriter,
    directory: Path,
    stamp: ProjectStamp,
    *,
    stores: Sequence[StoreConfig],
    geo: GeoAdapter | None,
) -> ProjectWrite:
    """Read a project file: what it holds, or why it is not used."""
    data: dict[str, Any] | None = None
    try:
        data = read_project_json(directory)
        document = parse_document(data)
    except ProjectFileError as error:
        detail = dict(error.details)
        reason = detail.pop("reason", None)
        if reason == "unsupported_project_schema":
            name = None if data is None else read_name(data)
            return ProjectWrite(
                path=directory,
                stamp=stamp,
                name=name or directory.name,
                state="unsupported_schema",
                problem="unsupported_project_schema",
                problem_detail=detail,
            )
        return _invalid(directory, stamp, detail)
    area_id, area_state = _area(writer, directory, document, geo)
    return ProjectWrite(
        path=directory,
        stamp=stamp,
        name=document.name,
        document=document,
        stores={
            store.producer: _match_store(store.root, directory, store.producer, stores)
            for store in document.stores
        },
        area_id=area_id,
        area_state=area_state,
    )


def _invalid(
    directory: Path, stamp: ProjectStamp, detail: Mapping[str, object]
) -> ProjectWrite:
    """Return a project whose file is not used, listed by its directory's name."""
    return ProjectWrite(
        path=directory,
        stamp=stamp,
        name=directory.name,
        state="invalid",
        problem="invalid_project_file",
        problem_detail=detail,
    )


def _area(
    writer: IndexWriter,
    directory: Path,
    document: ProjectDocument,
    geo: GeoAdapter | None,
) -> tuple[str | None, ProjectAreaState | None]:
    """Keep a project's area in the index; return its id and state.

    ``(None, None)`` for a project without an area, and while it cannot be
    read: no producer with coordinate operations, or none to the planar CRS.
    """
    # ``archiwista.areas`` imports the index: imported here, where it is used.
    from archiwista.areas import area_from_geometry

    if document.area is None or geo is None:
        return None, None
    try:
        geometry = read_project_area(directory, document.area)
        record = area_from_geometry(
            geometry, adapter=geo, source="file", name=document.name
        )
    except ProjectAreaError as error:
        return None, error.state
    except (IndexQueryError, AreaTooComplexError):
        return None, "invalid"
    except ProducerError:
        return None, None
    writer.write_area(record)
    return record.id, "ok"


def _discover(
    top: Path,
    skipped: set[str],
    unreadable: list[str],
    outside: set[str],
) -> Iterator[tuple[str, ProjectStamp]]:
    """Yield ``(project directory, file stamp)`` below ``top``.

    Symbolic links to directories are not followed (no cycles); a directory
    that cannot be listed is appended to ``unreadable``. A project file that
    is a symbolic link resolving outside ``top`` (SPEC 10.1) is yielded with
    the link's own stamp and its directory added to ``outside``: it must not
    be read.
    """
    base = os.path.abspath(top)
    pending = [(base, 0)]
    while pending:
        directory, depth = pending.pop()
        if os.path.normpath(directory) in skipped:
            continue
        try:
            with os.scandir(directory) as listing:
                items = list(listing)
        except OSError:
            unreadable.append(directory)
            continue
        for item in items:
            if item.name == PROJECT_FILE:
                try:
                    escapes = item.is_symlink() and not _contained(base, item.path)
                    if not escapes and not item.is_file():
                        continue
                    status = item.stat(follow_symlinks=not escapes)
                except OSError:
                    unreadable.append(directory)
                    continue
                if escapes:
                    outside.add(directory)
                yield directory, ProjectStamp(status.st_mtime_ns, status.st_size)
                continue
            if depth >= MAX_PROJECT_DEPTH or item.name.startswith("."):
                continue
            try:
                if item.is_dir(follow_symlinks=False):
                    pending.append((item.path, depth + 1))
            except OSError:
                unreadable.append(item.path)


def _contained(base: str, path: str) -> bool:
    """Whether ``path`` resolves inside ``base``; a dangling link counts as inside.

    A dangling link is not a file, so discovery skips it without reading it.
    """
    relative = Path(os.path.relpath(path, base)).as_posix()
    try:
        resolve_indexed_path(Path(base), relative)
    except PathOutsideRootError:
        return False
    except FileNotFoundError:
        return True
    return True


def _same_directory(path: str, root: Path) -> bool:
    if not os.path.isabs(path):
        return False
    if os.path.normpath(path) == os.path.normpath(root):
        return True
    return os.path.realpath(path) == os.path.realpath(root)


def _inside(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)
