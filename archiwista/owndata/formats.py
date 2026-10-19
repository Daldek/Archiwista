"""Which own-data files form one set and which are SQLite databases (decision 8).

A Shapefile and a native MapInfo table are a set of files sharing the name
stem: the main file (``.shp``, ``.tab``) and its members next to it, found by
extension in any letter case. Every other file stands alone; a SQLite
database keeps its ``-wal``, ``-shm`` and ``-journal`` next to it while it is
edited or after a crash, and those are not files of their own. A ``.tab``
other than a native table (a view, a seamless or raster table) names other
files, so it is no set: the reader refuses it (``unsupported_format``).

Only the standard library and the format table (``archiwista.formats``):
nothing here opens a file with GDAL.
"""

import os
from pathlib import Path

from archiwista.errors import FormatRefusedError
from archiwista.formats import file_format, vector_source

# Members of a set by the main file's extension: the main file first, then
# the members in the order GDAL lists them (spatial indexes last).
FILESET_SUFFIXES: dict[str, tuple[str, ...]] = {
    ".shp": (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx"),
    ".tab": (".tab", ".dat", ".map", ".id", ".ind"),
}
# Files SQLite keeps next to a database: the WAL with its shared memory
# while a connection writes, the rollback journal during a transaction.
SQLITE_COMPANION_SUFFIXES: tuple[str, ...] = ("-wal", "-shm", "-journal")
SQLITE_MAGIC = b"SQLite format 3\x00"


def is_sqlite(path: Path) -> bool:
    """Whether a file starts with the SQLite header (GeoPackage or another database).

    Raises
    ------
    OSError
        The file cannot be read.
    """
    with path.open("rb") as stream:
        return stream.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def is_fileset(path: Path) -> bool:
    """Whether a file is the main file of a set: a ``.shp`` or a native ``.tab``.

    A ``.tab`` is read (at most 1 MiB of its header) to tell a native table
    from a view, a seamless or a raster table; one that cannot be read is
    no set.
    """
    suffix = path.suffix.lower()
    if suffix not in FILESET_SUFFIXES:
        return False
    if suffix != ".tab":
        return True
    try:
        vector_source(path.absolute(), file_format(path))
    except (FormatRefusedError, OSError):
        return False
    return True


def fileset_members(path: Path) -> tuple[Path, ...]:
    """Return the files of the set ``path`` is the main file of, or ``path`` alone.

    Members are the regular files (a link counts by its target) next to
    ``path`` whose name is its stem with a member extension, compared without
    letter case; GDAL opens them by name, so a caller keeping the reading
    inside a folder checks them as it checks ``path``.

    Parameters
    ----------
    path : Path
        A file; for a ``.shp`` or a native ``.tab`` its directory is listed.

    Returns
    -------
    tuple[Path, ...]
        ``path`` first, then the members by extension in the order of
        ``FILESET_SUFFIXES`` (names of one extension sorted); ``(path,)``
        for a file that is no set.

    Raises
    ------
    OSError
        The directory cannot be listed.
    """
    if not is_fileset(path):
        return (path,)
    stem = path.stem.lower()
    ranks = {
        f"{stem}{suffix}": rank
        for rank, suffix in enumerate(FILESET_SUFFIXES[path.suffix.lower()])
    }
    found: list[tuple[int, str]] = []
    with os.scandir(path.parent) as entries:
        for entry in entries:
            rank = ranks.get(entry.name.lower())
            if rank is not None and entry.name != path.name and entry.is_file():
                found.append((rank, entry.name))
    return (path, *(path.parent / name for _, name in sorted(found)))
