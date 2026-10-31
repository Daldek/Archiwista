"""A project's exports: ``zestawy/<name>/`` generated from its pins.

An export (a "zestaw", A-ADR-049 decision 13, SPEC 8.4) is rebuildable, not
data: ``pliki.txt`` lists each exported version's file once, one per line,
in the order of the groups and their pins (for Hydrograf), and
``ATRYBUCJE.txt`` each attribution text the sources require once, in the
order of first use; both UTF-8 with LF. A file's line is relative to the
export directory when the two share a directory below the file system's
root or drive (the same share), else absolute as the server reads it.
Regenerating writes each file under a name of its own and replaces it with
``os.replace``, so a failed write leaves the old file whole; Archiwista never
removes an export. ``list_exports`` tells which exports are older than the
project file. The QGIS project and the rest of SPEC 8.4 are v1.1.
"""

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath

from archiwista.errors import PathOutsideRootError
from archiwista.messages import message
from archiwista.projects.document import EXPORTS_DIR
from archiwista.projects.files import _write_atomic, _write_failed

FILES_LIST = "pliki.txt"
ATTRIBUTIONS = "ATRYBUCJE.txt"
EXPORT_FILES = (FILES_LIST, ATTRIBUTIONS)
MAX_EXPORT_NAME_CHARS = 64
# An export's name: 1 to 64 letters, digits, ".", "_" and "-", not starting
# with "." (A-ADR-049 decision 13); the same rule in Python and in the API.
_NAME_RULE = r"[\w-][\w.-]{0,63}"
EXPORT_NAME_PATTERN = f"^{_NAME_RULE}$"
_NAME = re.compile(_NAME_RULE)


@dataclass(frozen=True, slots=True)
class ExportRow:
    """A version of an export: its file as the server reads it, its attribution."""

    file: Path
    attribution: str | None


@dataclass(frozen=True, slots=True)
class ExportResult:
    """An export just written: its directory, files and when."""

    name: str
    path: Path
    files: tuple[str, ...]
    versions: int
    written_at: datetime


@dataclass(frozen=True, slots=True)
class ExportListing:
    """An export found in a project's ``zestawy/``.

    ``changed_since``: the project file changed after the export was
    written, so the export may no longer show the project's pins.
    """

    name: str
    path: Path
    files: tuple[str, ...]
    written_at: datetime
    changed_since: bool


def is_export_name(name: str) -> bool:
    """Whether ``name`` keeps the rule of an export's name."""
    return _NAME.fullmatch(name) is not None


def export_path(version_file: Path, export_dir: Path) -> str:
    """Return a version's file as an export's ``pliki.txt`` lists it.

    Relative to ``export_dir`` (``/``-separated) when the real paths of both
    share a directory below the file system's root or drive, else
    ``version_file`` as given (the path the server reads).

    Parameters
    ----------
    version_file : Path
        The version's file below its configured store.
    export_dir : Path
        The export's directory, ``zestawy/<name>/`` of the project.
    """
    real_file = os.path.realpath(version_file)
    real_dir = os.path.realpath(export_dir)
    try:
        common = PurePath(os.path.commonpath([real_file, real_dir]))
    except ValueError:  # other drives
        return str(version_file)
    if common == PurePath(common.anchor):
        return str(version_file)
    return PurePath(os.path.relpath(real_file, real_dir)).as_posix()


def write_export(directory: Path, name: str, rows: Sequence[ExportRow]) -> ExportResult:
    """Write ``zestawy/<name>/pliki.txt`` and ``ATRYBUCJE.txt`` of a project.

    Parameters
    ----------
    directory : Path
        The project directory.
    name : str
        The export's name (``is_export_name``).
    rows : Sequence[ExportRow]
        The exported versions in the order of the groups and their pins; a
        file listed twice is written once.

    Returns
    -------
    ExportResult
        The export's directory, its files, the versions listed and the time
        ``pliki.txt`` was written.

    Raises
    ------
    ValueError
        ``name`` breaks the rule of an export's name.
    PathOutsideRootError
        ``zestawy/`` or the export's directory leads out of the project
        directory (a symbolic link).
    ProjectFileWriteError
        A file could not be written; it stays as it was.
    """
    if not is_export_name(name):
        raise ValueError(f"invalid export name: {name!r}")
    target = _export_dir(directory, name)
    lines: dict[str, None] = {}
    attributions: dict[str, None] = {}
    for row in rows:
        lines.setdefault(export_path(row.file, target))
        text = (row.attribution or "").strip()
        if text:
            attributions.setdefault(text)
    _write_atomic(target / FILES_LIST, _text(lines))
    _write_atomic(target / ATTRIBUTIONS, _text(attributions))
    written = (target / FILES_LIST).stat().st_mtime
    return ExportResult(
        name=name,
        path=target,
        files=EXPORT_FILES,
        versions=len(lines),
        written_at=datetime.fromtimestamp(written, UTC),
    )


def list_exports(directory: Path, project_mtime: float) -> tuple[ExportListing, ...]:
    """Return a project's exports by name: directories of ``zestawy/`` with its files.

    Parameters
    ----------
    directory : Path
        The project directory.
    project_mtime : float
        The modification time of the project file (``st_mtime``): an export
        written before it is ``changed_since``.

    Raises
    ------
    PathOutsideRootError
        ``zestawy/`` leads out of the project directory.
    """
    base = directory / EXPORTS_DIR
    if not base.is_dir():
        return ()
    _require_inside(base, directory)
    found = []
    for entry in sorted(os.scandir(base), key=lambda item: item.name):
        if not is_export_name(entry.name) or not entry.is_dir(follow_symlinks=False):
            continue
        times = {}
        for name in EXPORT_FILES:
            try:
                status = os.stat(Path(entry.path, name), follow_symlinks=False)
            except OSError:
                continue
            times[name] = status.st_mtime
        if not times:
            continue
        written = max(times.values())
        found.append(
            ExportListing(
                name=entry.name,
                path=Path(entry.path),
                files=tuple(name for name in EXPORT_FILES if name in times),
                written_at=datetime.fromtimestamp(written, UTC),
                changed_since=project_mtime > written,
            )
        )
    return tuple(found)


def _export_dir(directory: Path, name: str) -> Path:
    """Make ``zestawy/<name>/`` of a project, refused when it leads out of it."""
    base = directory / EXPORTS_DIR
    target = base / name
    try:
        base.mkdir(exist_ok=True)
        _require_inside(base, directory)
        target.mkdir(exist_ok=True)
    except OSError as error:
        raise _write_failed(target, error) from error
    _require_inside(target, directory)
    return target


def _require_inside(path: Path, directory: Path) -> None:
    """Refuse ``path`` when its real path is not inside the project directory."""
    if not path.resolve().is_relative_to(directory.resolve()):
        raise PathOutsideRootError(message("ref.path_outside_root", path=path))


def _text(lines: Iterable[str]) -> bytes:
    """Return lines as a UTF-8 file with LF, each line ended."""
    return "".join(f"{line}\n" for line in lines).encode()
