"""A project's exports: ``eksport/<name>/``, a flat copy of its pinned data.

An export (A-ADR-049 decision 13 and its erratum 1, SPEC 8.4) hands a set of
input data over to another tool (QGIS, a model): one folder per category
(``NMT``, ``BDOT``, ``ORTO``…, named by the producer's adapter) holding each
exported version's file under its original name, copied (never linked: a
recipient may write to a GeoPackage, which must not change the store), with
the companion files the store holds beside it (``.prj``, ``.tfw``,
``.aux.xml``, the parts of a Shapefile; never a ``*.meta.json`` sidecar), and
``README.txt`` (Polish) describing every file and listing each data source's
attribution once. Two files of one name in one folder (the same sheet of two
years) both get their version's label before the extension. With ``zip``
the folder's content is also ``eksport/<name>.zip``.

An export is written in a hidden sibling directory and then swapped with
the one of the same name, so a failed export leaves the old one whole; the
zip of an export written without ``zip`` is removed, it would describe other
data. ``list_exports`` tells which exports are older than the project file.
"""

import hashlib
import os
import re
import secrets
import shutil
import stat
import zipfile
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from archiwista.errors import PathOutsideRootError
from archiwista.messages import message
from archiwista.projects.document import EXPORTS_DIR
from archiwista.projects.files import _write_failed

README = "README.txt"
ZIP_SUFFIX = ".zip"
MAX_EXPORT_NAME_CHARS = 64
# An export's name: 1 to 64 letters, digits, ".", "_" and "-", not starting
# with "." (A-ADR-049 decision 13); the same rule in Python and in the API.
_NAME_RULE = r"[\w-][\w.-]{0,63}"
EXPORT_NAME_PATTERN = f"^{_NAME_RULE}$"
_NAME = re.compile(_NAME_RULE)
# A metadata sidecar of the producers, never exported.
_SIDECAR_SUFFIX = ".meta.json"
# Characters of a folder name or a label put into a file name.
_UNSAFE = re.compile(r"[^\w.-]+")
_CHUNK = 1024**2


@dataclass(frozen=True, slots=True)
class ExportItem:
    """A version to export and what ``README.txt`` says of it.

    ``file`` is the version's file as the server reads it, inside its store;
    ``folder`` its category (``ExportFolderAdapter``, cleaned here);
    ``sets`` the names of the groups that pin it.
    """

    file: Path
    folder: str
    label: str | None
    sha256: str
    sets: tuple[str, ...]
    product: str | None
    year: int | None
    crs: str | None
    vertical_crs: str | None
    attribution: str | None


@dataclass(frozen=True, slots=True)
class ExportResult:
    """An export just written: its directory, files, zip and when."""

    name: str
    path: Path
    files: tuple[str, ...]
    versions: int
    zip: bool
    written_at: datetime


@dataclass(frozen=True, slots=True)
class ExportListing:
    """An export found in a project's ``eksport/``.

    ``changed_since``: the project file changed after the export was
    written, so the export may no longer show the project's pins.
    """

    name: str
    path: Path
    files: tuple[str, ...]
    zip: bool
    written_at: datetime
    changed_since: bool


@dataclass(frozen=True, slots=True)
class _Placed:
    """An item with the names of its file and companions in its folder."""

    item: ExportItem
    companions: tuple[Path, ...]
    name: str
    companion_names: tuple[str, ...]


def is_export_name(name: str) -> bool:
    """Whether ``name`` keeps the rule of an export's name."""
    return _NAME.fullmatch(name) is not None


def folder_name(text: str | None, fallback: str) -> str:
    """Return a category folder's name: upper case, letters, digits, ``_-.``.

    ``fallback`` (upper-cased and cleaned as well) when ``text`` leaves no
    such name.
    """
    for candidate in (text, fallback):
        cleaned = _UNSAFE.sub("_", (candidate or "").upper()).strip("._")
        if cleaned:
            return cleaned
    return "DANE"


def companions(file: Path) -> tuple[Path, ...]:
    """Return the companion files the store holds beside a version's file.

    The regular files of its directory named after its stem (``x.prj`` and
    ``x.asc.aux.xml`` of ``x.asc``, the parts of ``x.shp``), by name; never a
    ``*.meta.json`` sidecar, a link or a directory.
    """
    prefix = f"{file.stem}."
    found = []
    try:
        entries = list(os.scandir(file.parent))
    except OSError:
        return ()
    for entry in entries:
        if (
            entry.name == file.name
            or not entry.name.startswith(prefix)
            or entry.name.endswith(_SIDECAR_SUFFIX)
            or not entry.is_file(follow_symlinks=False)
        ):
            continue
        found.append(Path(entry.path))
    return tuple(sorted(found, key=lambda path: path.name))


def write_export(
    directory: Path,
    name: str,
    items: Sequence[ExportItem],
    *,
    project: str,
    with_zip: bool,
) -> ExportResult:
    """Write ``eksport/<name>/`` of a project, with ``with_zip`` ``eksport/<name>.zip``.

    Parameters
    ----------
    directory : Path
        The project directory.
    name : str
        The export's name (``is_export_name``).
    items : Sequence[ExportItem]
        The exported versions in the order of the groups and their pins,
        each once.
    project : str
        The project's name, for ``README.txt``.
    with_zip : bool
        Also write the folder's content as ``eksport/<name>.zip``.

    Returns
    -------
    ExportResult
        The export's directory, its files (``/``-separated, ``README.txt``
        last), the versions copied and the time ``README.txt`` was written.

    Raises
    ------
    ValueError
        ``name`` breaks the rule of an export's name.
    PathOutsideRootError
        ``eksport/`` leads out of the project directory (a symbolic link).
    ProjectFileWriteError
        A file could not be read or written; the export there stays as it was.
    """
    if not is_export_name(name):
        raise ValueError(f"invalid export name: {name!r}")
    base = _exports_dir(directory)
    target = base / name
    archive = base / f"{name}{ZIP_SUFFIX}"
    token = secrets.token_hex(4)
    temp = base / f".{name}.{token}.tmp"
    temp_zip = base / f".{name}{ZIP_SUFFIX}.{token}.tmp"
    try:
        temp.mkdir()
        files = _write_tree(temp, name, project, _place(items))
        if with_zip:
            _write_zip(temp, files, temp_zip)
        _swap(temp, target)
        if with_zip:
            os.replace(temp_zip, archive)
        else:
            archive.unlink(missing_ok=True)
    except OSError as error:
        raise _write_failed(target, error) from error
    finally:  # nothing is left of a failed export; a written one moved away
        shutil.rmtree(temp, ignore_errors=True)
        with suppress(OSError):
            temp_zip.unlink()
    written = (target / README).stat().st_mtime
    return ExportResult(
        name=name,
        path=target,
        files=files,
        versions=len(items),
        zip=with_zip,
        written_at=datetime.fromtimestamp(written, UTC),
    )


def list_exports(directory: Path, project_mtime: float) -> tuple[ExportListing, ...]:
    """Return a project's exports by name: directories of ``eksport/`` with a README.

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
        ``eksport/`` leads out of the project directory.
    """
    base = directory / EXPORTS_DIR
    if not base.is_dir():
        return ()
    _require_inside(base, directory)
    found = []
    for entry in sorted(os.scandir(base), key=lambda item: item.name):
        if not is_export_name(entry.name) or not entry.is_dir(follow_symlinks=False):
            continue
        try:
            status = os.stat(Path(entry.path, README), follow_symlinks=False)
        except OSError:
            continue
        written = status.st_mtime
        found.append(
            ExportListing(
                name=entry.name,
                path=Path(entry.path),
                files=_tree_files(Path(entry.path)),
                zip=_zip_file(base, entry.name) is not None,
                written_at=datetime.fromtimestamp(written, UTC),
                changed_since=project_mtime > written,
            )
        )
    return tuple(found)


def export_zip(directory: Path, name: str) -> Path | None:
    """Return ``eksport/<name>.zip`` of a project, ``None`` when there is none.

    Raises
    ------
    PathOutsideRootError
        ``eksport/`` leads out of the project directory.
    """
    base = directory / EXPORTS_DIR
    if not is_export_name(name) or not base.is_dir():
        return None
    _require_inside(base, directory)
    return _zip_file(base, name)


def _place(items: Sequence[ExportItem]) -> list[_Placed]:
    """Name each item's file in its folder, the colliding ones with their label.

    A name met twice in a folder (case-folded, as Windows compares names)
    gets ``_<label>`` before its extension in every file of the collision;
    when that still collides, ``_<label>_<sha8>``, then the item's position.
    Its companions follow the file's new stem.
    """
    found = [(item, companions(item.file)) for item in items]
    levels = [0] * len(found)
    while True:
        placed = [
            _named(item, extra, level, position)
            for position, ((item, extra), level) in enumerate(
                zip(found, levels, strict=True)
            )
        ]
        owners: dict[tuple[str, str], set[int]] = {}
        for position, place in enumerate(placed):
            for file_name in (place.name, *place.companion_names):
                key = (place.item.folder, file_name.casefold())
                owners.setdefault(key, set()).add(position)
        clashing = {
            position
            for positions in owners.values()
            if len(positions) > 1
            for position in positions
        }
        if not clashing:
            return placed
        for position in clashing:
            levels[position] += 1


def _named(
    item: ExportItem, extra: tuple[Path, ...], level: int, position: int
) -> _Placed:
    """Return an item's names at a level of ``_place``."""
    stem = item.file.stem
    parts = [stem]
    if level >= 1:
        parts.append(_UNSAFE.sub("_", item.label or "").strip("._") or item.sha256[:8])
    if level >= 2:
        parts.append(item.sha256[:8])
    if level >= 3:
        parts.append(str(position + 1))
    new_stem = "_".join(dict.fromkeys(parts))
    return _Placed(
        item=item,
        companions=extra,
        name=new_stem + item.file.name[len(stem) :],
        companion_names=tuple(new_stem + path.name[len(stem) :] for path in extra),
    )


def _write_tree(
    target: Path, name: str, project: str, placed: Sequence[_Placed]
) -> tuple[str, ...]:
    """Copy the files into their folders, write ``README.txt``; return the files."""
    files: list[str] = []
    sizes: list[tuple[int, str]] = []
    for place in placed:
        folder = target / place.item.folder
        folder.mkdir(exist_ok=True)
        sizes.append(_copy(place.item.file, folder / place.name))
        files.append(f"{place.item.folder}/{place.name}")
        for source, copied in zip(place.companions, place.companion_names, strict=True):
            shutil.copyfile(source, folder / copied)
            files.append(f"{place.item.folder}/{copied}")
    readme = target / README
    readme.write_bytes(_readme(name, project, placed, sizes))
    files.sort()
    files.append(README)
    return tuple(files)


def _copy(source: Path, target: Path) -> tuple[int, str]:
    """Copy a file, never as a link; return its size and SHA-256."""
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, target.open("xb") as writer:
        while chunk := reader.read(_CHUNK):
            digest.update(chunk)
            writer.write(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _readme(
    name: str,
    project: str,
    placed: Sequence[_Placed],
    sizes: Sequence[tuple[int, str]],
) -> bytes:
    """Return ``README.txt``: every file with what is known of it, the sources."""

    def text(key: str, **values: object) -> str:
        return str(message(f"export.{key}", "pl", **values))

    written = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    lines = [text("readme_title", name=name, project=project, written=written), ""]
    lines.append(text("readme_intro") if placed else text("readme_empty"))
    attributions: dict[str, None] = {}
    for place, (size, sha256) in zip(placed, sizes, strict=True):
        item = place.item
        lines += ["", f"{item.folder}/{place.name}"]
        facts: list[tuple[str, str, object]] = [
            ("readme_product", "product", item.product),
            ("readme_year", "year", item.year),
            ("readme_label", "label", item.label),
            ("readme_crs", "crs", item.crs),
            ("readme_vertical", "crs", item.vertical_crs),
        ]
        for key, field, value in facts:
            if value is not None:
                lines.append(f"  {text(key, **{field: value})}")
        lines.append(f"  {text('readme_size', size=size)}")
        lines.append(f"  {text('readme_sha256', sha256=sha256)}")
        lines.append(f"  {text('readme_sets', sets=', '.join(item.sets))}")
        if place.companion_names:
            files = ", ".join(place.companion_names)
            lines.append(f"  {text('readme_companions', files=files)}")
        attribution = (item.attribution or "").strip()
        if attribution:
            attributions.setdefault(attribution)
    lines += ["", text("readme_sources")]
    if attributions:
        lines += [f"- {attribution}" for attribution in attributions]
    else:
        lines.append(text("readme_no_sources"))
    return _text(lines)


def _write_zip(source: Path, files: Iterable[str], target: Path) -> None:
    """Write the files of an export's folder as a ZIP at ``target``."""
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(source / file, file)
    with target.open("rb") as written:
        os.fsync(written.fileno())


def _swap(temp: Path, target: Path) -> None:
    """Put the export written in ``temp`` in place of ``target``.

    The old export moves aside first and comes back when the move fails; it
    is removed once the new one is in place.
    """
    if not os.path.lexists(target):
        os.rename(temp, target)
        return
    old = temp.with_name(f"{temp.name}.old")
    os.rename(target, old)
    try:
        os.rename(temp, target)
    except OSError:
        os.rename(old, target)
        raise
    if old.is_dir() and not old.is_symlink():
        shutil.rmtree(old, ignore_errors=True)
    else:
        old.unlink(missing_ok=True)


def _tree_files(path: Path) -> tuple[str, ...]:
    """Return an export's files as ``write_export`` does: folders' files, README."""
    files = []
    for folder in os.scandir(path):
        if not folder.is_dir(follow_symlinks=False):
            continue
        for entry in os.scandir(folder.path):
            if entry.is_file(follow_symlinks=False):
                files.append(f"{folder.name}/{entry.name}")
    files.sort()
    files.append(README)
    return tuple(files)


def _zip_file(base: Path, name: str) -> Path | None:
    """Return ``<base>/<name>.zip`` when it is a regular file, else ``None``."""
    path = base / f"{name}{ZIP_SUFFIX}"
    try:
        status = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return path if stat.S_ISREG(status.st_mode) else None


def _exports_dir(directory: Path) -> Path:
    """Make ``eksport/`` of a project, refused when it leads out of it."""
    base = directory / EXPORTS_DIR
    try:
        base.mkdir(exist_ok=True)
    except OSError as error:
        raise _write_failed(base, error) from error
    _require_inside(base, directory)
    return base


def _require_inside(path: Path, directory: Path) -> None:
    """Refuse ``path`` when its real path is not inside the project directory."""
    if not path.resolve().is_relative_to(directory.resolve()):
        raise PathOutsideRootError(message("ref.path_outside_root", path=path))


def _text(lines: Iterable[str]) -> bytes:
    """Return lines as a UTF-8 file with LF, each line ended."""
    return "".join(f"{line}\n" for line in lines).encode()
