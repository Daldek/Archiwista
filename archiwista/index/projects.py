"""Discover producer project manifests and record them in the local index.

Projects live in the configured project directories (SPEC 4.7): a project
is a directory holding its producer's manifest (``kartograf-project.json``).
Discovery goes at most four levels below each project directory and never
enters ``.git``, hidden directories or a store's producer directory. Only a
new or changed manifest (other size or modification time) is read again,
through the producer's adapter; an invalid one stays visible with the
producer's own message. A manifest that is a symbolic link resolving outside
the configured project directory (SPEC 10.1) is never read: the project
stays visible as invalid with ``path_outside_root``'s message. A project
without a configured store or a status (invalid manifest, unknown store,
store unreachable) is read on every pass until it matches and is checked
(``IndexWriter.project_stamps``). A project directory that cannot be read
keeps the projects indexed under it, so a disconnected share does not empty
the list.
"""

import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from archiwista.config import StoreConfig
from archiwista.errors import PathOutsideRootError, ProducerError
from archiwista.index.types import ManifestStamp
from archiwista.index.writer import IndexWriter
from archiwista.messages import MESSAGES
from archiwista.paths import resolve_indexed_path
from archiwista.sources import ProjectInfo, SourceAdapter

# Manifest file of each producer's projects.
PROJECT_MANIFESTS: Mapping[str, str] = {"kartograf": "kartograf-project.json"}
# Directory levels searched below a configured project directory.
MAX_PROJECT_DEPTH = 4


@dataclass(frozen=True, slots=True)
class ProjectScanSummary:
    """What one pass over the project directories found and changed.

    Attributes
    ----------
    found : int
        Manifests discovered.
    read : int
        Manifests read because they were new or changed.
    unchanged : int
        Manifests skipped because their size and modification time match
        the index.
    invalid : int
        Manifests read that the producer rejected (kept with the message).
    unknown_store : int
        Projects read whose store matches no configured store.
    removed : int
        Indexed projects whose manifest is gone.
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
    adapter: SourceAdapter,
    writer: IndexWriter,
    *,
    project_dirs: Sequence[Path],
    stores: Sequence[StoreConfig],
) -> ProjectScanSummary:
    """Index the producer's projects found in the project directories.

    Parameters
    ----------
    adapter : SourceAdapter
        The producer whose manifests are read (``project_status``, falling
        back to ``read_project`` when the status cannot be taken).
    writer : IndexWriter
        Writer of the local index, already synchronised with ``stores``.
    project_dirs : Sequence[Path]
        Configured project directories (``AppSettings.project_dirs``).
    stores : Sequence[StoreConfig]
        All configured stores: their producer directories are not searched,
        and a manifest's store is matched to one of them by path or alias.

    Returns
    -------
    ProjectScanSummary
        Counts of found, read, unchanged, invalid and removed projects.
    """
    manifest = PROJECT_MANIFESTS.get(adapter.producer)
    if manifest is None:
        return ProjectScanSummary()
    roots = {
        config.id: root
        for config in stores
        if (root := config.roots().get(adapter.producer)) is not None
    }
    skipped = {
        os.path.normpath(root) for config in stores for root in config.roots().values()
    }
    unreadable: list[str] = []
    outside: set[str] = set()
    found: dict[str, ManifestStamp] = {}
    for directory in project_dirs:
        for path, stamp in _discover(
            Path(directory), manifest, skipped, unreadable, outside
        ):
            found.setdefault(path, stamp)
    known = writer.project_stamps(adapter.producer)
    read = invalid = unknown_store = 0
    for path, stamp in sorted(found.items()):
        if known.get(path) == stamp:
            continue
        if path in outside:
            refused = MESSAGES["path_outside_root"].format(
                path=os.path.join(path, manifest)
            )
            info = _invalid(adapter, Path(path), refused)
        else:
            info = _read(adapter, Path(path))
        store = _match_store(info, stores, roots) if info.problem is None else None
        writer.write_project(info, store=store, stamp=stamp)
        read += 1
        invalid += info.problem is not None
        unknown_store += info.problem is None and store is None
    keep = set(found)
    keep.update(
        path for path in known if any(_inside(path, gone) for gone in unreadable)
    )
    removed = writer.remove_projects(adapter.producer, keep=keep)
    return ProjectScanSummary(
        found=len(found),
        read=read,
        unchanged=len(found) - read,
        invalid=invalid,
        unknown_store=unknown_store,
        removed=removed,
        unreadable_dirs=tuple(unreadable),
    )


def _discover(
    top: Path,
    manifest: str,
    skipped: set[str],
    unreadable: list[str],
    outside: set[str],
) -> Iterator[tuple[str, ManifestStamp]]:
    """Yield ``(project directory, manifest stamp)`` below ``top``.

    Symbolic links to directories are not followed (no cycles); a directory
    that cannot be listed is appended to ``unreadable``. A manifest that is
    a symbolic link resolving outside ``top`` (SPEC 10.1) is yielded with
    the link's own stamp and its directory added to ``outside``: it must
    not be read.
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
            if item.name == manifest:
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
                yield directory, ManifestStamp(status.st_mtime_ns, status.st_size)
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


def _invalid(adapter: SourceAdapter, directory: Path, problem: str) -> ProjectInfo:
    """Return a project whose manifest is not used, visible with ``problem``."""
    return ProjectInfo(
        producer=adapter.producer,
        store="",
        path=directory,
        name=directory.name,
        problem=problem,
    )


def _read(adapter: SourceAdapter, directory: Path) -> ProjectInfo:
    """Read a project with its status; an invalid manifest keeps its message."""
    try:
        info = adapter.project_status(directory)
    except ProducerError:
        try:
            info = adapter.read_project(directory)
        except ProducerError as error:
            return _invalid(adapter, directory, error.message)
    return replace(info, path=directory)


def _match_store(
    info: ProjectInfo, stores: Sequence[StoreConfig], roots: Mapping[str, Path]
) -> str | None:
    r"""Return the configured store whose producer directory the project names.

    The manifest's store matches by its resolved path or through a store's
    path aliases (SPEC 4.6). A path written on another system that the
    producer resolved against the project directory (``Z:\kartograf`` read
    on Linux) is matched by the text it was written as.
    """
    written = info.store
    project = str(info.path)
    candidates = [written]
    if written.startswith(project + os.sep):
        candidates.append(written[len(project) + 1 :])
    for config in stores:
        root = roots.get(config.id)
        if root is None:
            continue
        for candidate in candidates:
            if _same_directory(candidate, root) or _same_directory(
                str(config.local_path(candidate)), root
            ):
                return config.id
    return None


def _same_directory(path: str, root: Path) -> bool:
    if not os.path.isabs(path):
        return False
    if os.path.normpath(path) == os.path.normpath(root):
        return True
    return os.path.realpath(path) == os.path.realpath(root)


def _inside(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)
