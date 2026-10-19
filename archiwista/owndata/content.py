r"""Content identity of own-data files and consistent reading of SQLite (decision 8).

The identity (``ContentIdentity``: method and SHA-256) tells whether a file
changed since its last snapshot and keys its previews:

- ``bytes``: SHA-256 of the file;
- ``fileset``: SHA-256 of the sorted lines ``<member name in lower
  case>\t<member SHA-256>\n`` of a Shapefile or native MapInfo table;
- ``sqlite`` (GeoPackage and other SQLite databases): a logical hash that
  ignores the page layout, the WAL, the header counters and the data OGR and
  QGIS rewrite on an open for update without edits (``sqlite_content_sha256``).

A SQLite file of a data folder is opened only through
``consistent_sqlite_read``, by the state of the files next to it (checked
2026-10-19 with SQLite 3.46.1 and GDAL 3.12), and the folder stays as it was:

- (a) no ``-wal`` (nor a hot ``-journal``): read in place with ``immutable=1``
  (GDAL ``IMMUTABLE=YES``); ``mode=ro`` would create ``-wal`` and ``-shm``
  next to a WAL database. The file's size, modification time and header
  change counter and the files next to it must be the same after the read;
- (b) ``-wal`` and ``-shm`` (open in an editor): ``mode=ro``, which creates
  nothing then, and ``Connection.backup`` of the committed rows into a copy
  in the process's work directory;
- (c) ``-wal`` without ``-shm`` (a crashed editor, a copied folder) or a hot
  rollback ``-journal``: never in place (``mode=ro`` creates ``-shm``,
  ``immutable=1`` misses the WAL, GDAL writes the WAL into the file); a byte
  copy of the file and its ``-wal`` or ``-journal``, stable before and after,
  in the work directory.

A copy is turned into a single file without a journal (WAL recovered and
checkpointed, a hot journal rolled back) in the work directory, so every
state is read the same way, with ``immutable=1``.
"""

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from archiwista.errors import InconsistentReadError
from archiwista.owndata.formats import is_fileset, is_sqlite

type ContentMethod = Literal["bytes", "fileset", "sqlite"]
type SqliteState = Literal["in_place", "backup", "copy"]
type TableKind = Literal["table", "virtual", "shadow"]

CONTENT_METHODS: tuple[ContentMethod, ...] = ("bytes", "fileset", "sqlite")
# Shadow tables of the virtual table modules SQLite builds in, by the
# suffixes of their ``xShadowName``: the storage of an index (R*Tree,
# full-text search) derived from the data, outside the identity. Tables of
# another module's virtual table count as data: a change is never missed.
SHADOW_SUFFIXES: dict[str, tuple[str, ...]] = {
    "rtree": ("_node", "_parent", "_rowid"),
    "rtree_i32": ("_node", "_parent", "_rowid"),
    "geopoly": ("_node", "_parent", "_rowid"),
    "fts3": ("_content", "_segments", "_segdir", "_docsize", "_stat"),
    "fts4": ("_content", "_segments", "_segdir", "_docsize", "_stat"),
    "fts5": ("_data", "_idx", "_content", "_docsize", "_config"),
}
# What OGR and QGIS rewrite on an open for update without edits: OGR's
# feature counts and the write timestamps (lower-case names).
DERIVED_TABLES = frozenset({"gpkg_ogr_contents"})
DERIVED_COLUMNS: dict[str, frozenset[str]] = {
    "gpkg_contents": frozenset({"last_change"}),
    "gpkg_metadata_reference": frozenset({"timestamp"}),
}
SQLITE_READ_ATTEMPTS = 3

_CHUNK_BYTES = 1024**2
_FETCH_ROWS = 10_000
# Version of the logical hash: a change of the stream below is a new one.
_SQLITE_SCHEME = "archiwista-sqlite-content/1"
_COPY_PREFIX = "sqlite-"
# The database header's file change counter: bytes 24-27.
_COUNTER_START, _COUNTER_END = 24, 28
# One identifier of SQL as SQLite stores it: quoted ("", [], ``, '') or bare.
_NAME = r"""(?:"(?:[^"]|"")*"|\[[^\]]*\]|`(?:[^`]|``)*`|'(?:[^']|'')*'|[^\s.(]+)"""
_VIRTUAL = re.compile(r"\s*create\s+virtual\s+table\s", re.IGNORECASE)
_MODULE = re.compile(
    rf"\s*create\s+virtual\s+table\s+(?:if\s+not\s+exists\s+)?"
    rf"(?:{_NAME}\s*\.\s*)?{_NAME}\s+using\s+(?P<module>{_NAME})",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """Identity of a file's content (decision 8).

    Parameters
    ----------
    method : {"bytes", "fileset", "sqlite"}
        How ``sha256`` was computed; two identities are equal only with
        the same method.
    sha256 : str
        Lower-case hexadecimal SHA-256.
    """

    method: ContentMethod
    sha256: str


@dataclass(frozen=True, slots=True)
class FileStamp:
    """Size and modification time of a file, compared before and after a read."""

    size_bytes: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class SqliteRead:
    """A consistent view of a SQLite file of a data folder.

    Parameters
    ----------
    path : Path
        What to open: the file itself (``in_place``) or its copy in the
        work directory (``backup``, ``copy``), a single file without a
        journal. Open it only with ``sqlite_uri`` or ``gdal_options``.
    state : {"in_place", "backup", "copy"}
        State (a), (b) or (c) of decision 8; ``backup`` and ``copy`` mean an
        editor has the file open or left it so.
    source : FileStamp
        The file in the folder before it was read.
    wal : FileStamp or None
        Its ``-wal`` before it was read; ``None`` without one.
    journal : FileStamp or None
        Its hot ``-journal`` before it was read; ``None`` without one.
    """

    path: Path
    state: SqliteState
    source: FileStamp
    wal: FileStamp | None = None
    journal: FileStamp | None = None

    @property
    def sqlite_uri(self) -> str:
        """URI for ``sqlite3.connect(..., uri=True)``: read-only, immutable."""
        return f"{self.path.as_uri()}?mode=ro&immutable=1"

    @property
    def gdal_options(self) -> dict[str, str]:
        """GDAL open options of the GeoPackage driver for ``path``."""
        return {"IMMUTABLE": "YES"}

    def connect(self) -> sqlite3.Connection:
        """Open ``path`` with ``sqlite3``; the caller closes the connection.

        The connection is read-only and runs no function a schema names
        that is not innocuous (``trusted_schema=OFF``).
        """
        connection = sqlite3.connect(self.sqlite_uri, uri=True)
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA query_only=ON")
        except BaseException:
            connection.close()
            raise
        return connection


def content_method(path: Path) -> ContentMethod:
    """Return how the identity of a file is computed.

    ``fileset`` for the main file of a set (``.shp``, native ``.tab``),
    ``sqlite`` for a file with the SQLite header, ``bytes`` for any other.

    Raises
    ------
    OSError
        The file cannot be read.
    """
    if is_fileset(path):
        return "fileset"
    if is_sqlite(path):
        return "sqlite"
    return "bytes"


def content_identity(
    paths: Sequence[Path], *, method: ContentMethod, work_dir: Path | None = None
) -> ContentIdentity:
    """Return the identity of a file or a set of files.

    Parameters
    ----------
    paths : Sequence[Path]
        One file for ``bytes`` and ``sqlite``; every member of a set for
        ``fileset`` (``fileset_members``), in any order.
    method : {"bytes", "fileset", "sqlite"}
        The method (``content_method``).
    work_dir : Path or None, optional
        This process's work directory (``process_work_dir``), required by
        ``sqlite`` for the copies of states (b) and (c).

    Returns
    -------
    ContentIdentity
        The method and the SHA-256.

    Raises
    ------
    ValueError
        A wrong number of paths, or ``sqlite`` without ``work_dir``.
    InconsistentReadError
        A SQLite file kept changing while it was read.
    OSError
        A file cannot be read.
    sqlite3.Error
        A SQLite file is not a readable database.
    """
    if method == "fileset":
        if not paths:
            raise ValueError("a file set needs its members")
        lines = sorted(f"{path.name.lower()}\t{file_sha256(path)}\n" for path in paths)
        text = "".join(lines).encode("utf-8", "surrogateescape")
        return ContentIdentity("fileset", hashlib.sha256(text).hexdigest())
    if len(paths) != 1:
        raise ValueError(f"the {method} method takes one file")
    if method == "bytes":
        return ContentIdentity("bytes", file_sha256(paths[0]))
    if work_dir is None:
        raise ValueError("the sqlite method needs a work directory")
    return ContentIdentity(
        "sqlite", read_sqlite(paths[0], _logical_sha256, work_dir=work_dir)
    )


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of a file's bytes, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_content_sha256(connection: sqlite3.Connection) -> str:
    """Return the logical SHA-256 of a SQLite database (decision 8).

    The hash covers ``application_id``, ``user_version``, the sorted schema
    entries and the rows of every table, so it does not depend on the page
    layout, the WAL or the header counters (``VACUUM``, a checkpoint and a
    write without changes keep it). Left out: SQLite's internal ``sqlite_*``
    objects, virtual tables with the shadow tables of their modules
    (``SHADOW_SUFFIXES``; told from ``sqlite_master``, not from ``PRAGMA
    table_list``, which needs SQLite 3.37), indexes and triggers on those,
    the table ``gpkg_ogr_contents`` and the columns
    ``gpkg_contents.last_change`` and ``gpkg_metadata_reference.timestamp``.

    A row is the Python ``repr`` of its tuple of values, in the order of
    ``PRAGMA table_info``, with text and blob values as ``"T"`` or ``"X"``
    followed by the upper-case hexadecimal of their bytes, so the type of
    every value counts. Rows are ordered by the primary key (an ``INTEGER
    PRIMARY KEY`` table by its key, as stored), then by every column with
    the binary collation and its type: the rows of a table without a key
    are a sorted multiset.

    Parameters
    ----------
    connection : sqlite3.Connection
        An open database (``SqliteRead.connect``); its reads run in one read
        transaction unless one is already open.

    Returns
    -------
    str
        Lower-case hexadecimal SHA-256.

    Raises
    ------
    sqlite3.Error
        The database cannot be read.
    """
    with _read_transaction(connection):
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        kinds = table_kinds(connection)
        excluded = {
            name.lower() for name, kind in kinds.items() if kind != "table"
        } | DERIVED_TABLES
        schema: list[str] = []
        tables: list[str] = []
        for kind, name, table, sql in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
        ):
            if _internal(name) or table.lower() in excluded or _internal(table):
                continue
            schema.append(json.dumps([kind, name, table, sql]))
            if kind == "table":
                tables.append(name)
        lines = [
            _SQLITE_SCHEME,
            f"application_id\t{application_id}",
            f"user_version\t{user_version}",
            *(f"schema\t{entry}" for entry in sorted(schema)),
            *(
                f"rows\t{json.dumps([name, _rows_sha256(connection, name)])}"
                for name in sorted(tables)
            ),
        ]
    text = "".join(f"{line}\n" for line in lines)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def table_kinds(connection: sqlite3.Connection) -> dict[str, TableKind]:
    """Tell the tables of ``sqlite_master`` apart: data, virtual, shadow.

    A virtual table is an entry whose SQL starts with ``CREATE VIRTUAL
    TABLE``; its shadow tables are named ``<virtual table><suffix>`` with the
    suffixes of its module (``SHADOW_SUFFIXES``, without letter case). The
    same as ``PRAGMA table_list`` of SQLite 3.37 and later, from what SQLite
    3.35 has.

    Returns
    -------
    dict[str, TableKind]
        Every table of ``sqlite_master`` by name (SQLite's own ``sqlite_*``
        ones included): ``"table"``, ``"virtual"`` or ``"shadow"``.
    """
    entries: list[tuple[str, str | None]] = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    modules = {
        name: _virtual_module(sql)
        for name, sql in entries
        if sql is not None and _VIRTUAL.match(sql)
    }
    shadows = {
        f"{name}{suffix}".lower()
        for name, module in modules.items()
        for suffix in SHADOW_SUFFIXES.get(module, ())
    }
    return {
        name: "virtual"
        if name in modules
        else "shadow"
        if name.lower() in shadows
        else "table"
        for name, _ in entries
    }


@contextlib.contextmanager
def consistent_sqlite_read(
    path: Path, *, work_dir: Path, attempts: int = SQLITE_READ_ATTEMPTS
) -> Iterator[SqliteRead]:
    """Give a consistent view of a SQLite file without writing next to it.

    The state of the files next to ``path`` decides the way (see the
    module): (a) in place, (b) ``Connection.backup`` with ``mode=ro``, (c) a
    byte copy with its ``-wal`` or ``-journal``. Copies go to a directory of
    their own in ``work_dir``, removed when the block ends.

    Parameters
    ----------
    path : Path
        The SQLite file in its data folder.
    work_dir : Path
        This process's work directory (``process_work_dir``).
    attempts : int, optional
        Copies of state (c) tried before giving up.

    Yields
    ------
    SqliteRead
        What to open and the stamps of the file before the read.

    Raises
    ------
    InconsistentReadError
        In place: the file changed during the block (raised when it ends).
        State (c): the file or its companion changed during every copy.
    OSError
        The file cannot be read or copied.
    sqlite3.Error
        The file is not a readable database.
    """
    path = path.absolute()
    before = _files(path)
    if before.wal is None and before.journal is None:
        try:
            yield SqliteRead(path, "in_place", before.source)
        except Exception as error:
            if _files_or_none(path) != before:
                changed = InconsistentReadError("the file changed during the read")
                raise changed from error
            raise
        if _files_or_none(path) != before:
            raise InconsistentReadError("the file changed during the read")
        return
    directory = work_dir / f"{_COPY_PREFIX}{secrets.token_hex(8)}"
    directory.mkdir(mode=0o700)
    try:
        copy = directory / path.name
        if before.wal is not None and before.shm:
            _backup(path, copy)
            state: SqliteState = "backup"
        else:
            before = _copy_with_journal(path, copy, attempts)
            state = "copy"
        _single_file(copy)
        yield SqliteRead(copy, state, before.source, before.wal, before.journal)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def read_sqlite[T](
    path: Path,
    read: Callable[[SqliteRead], T],
    *,
    work_dir: Path,
    attempts: int = SQLITE_READ_ATTEMPTS,
) -> T:
    """Run ``read`` on a consistent view of a SQLite file, again if it changed.

    Parameters
    ----------
    path : Path
        The SQLite file in its data folder.
    read : Callable[[SqliteRead], T]
        What to do with the view (``consistent_sqlite_read``).
    work_dir : Path
        This process's work directory.
    attempts : int, optional
        Views tried in all, each with one copy in state (c).

    Returns
    -------
    T
        What ``read`` returned on a view that held.

    Raises
    ------
    InconsistentReadError
        The file changed during every attempt.
    """
    for attempt in range(1, attempts + 1):
        try:
            with consistent_sqlite_read(path, work_dir=work_dir, attempts=1) as view:
                return read(view)
        except InconsistentReadError:
            if attempt == attempts:
                raise
    raise ValueError("at least one attempt is needed")


def _logical_sha256(read: SqliteRead) -> str:
    with contextlib.closing(read.connect()) as connection:
        return sqlite_content_sha256(connection)


def _rows_sha256(connection: sqlite3.Connection, table: str) -> str:
    """SHA-256 of a table's rows, one ``repr`` line per row (see the caller)."""
    derived = DERIVED_COLUMNS.get(table.lower(), frozenset())
    columns: list[tuple[str, int]] = [
        (name, key)
        for name, key in connection.execute(
            "SELECT name, pk FROM pragma_table_info(?, 'main') ORDER BY cid", (table,)
        )
        if name.lower() not in derived
    ]
    digest = hashlib.sha256()
    if not columns:
        return digest.hexdigest()
    names = [_quoted(name) for name, _ in columns]
    values = ", ".join(
        f"CASE typeof({name}) WHEN 'text' THEN 'T' || hex({name})"
        f" WHEN 'blob' THEN 'X' || hex({name}) ELSE {name} END"
        for name in names
    )
    keys = [_quoted(name) for name, key in sorted(columns, key=lambda c: c[1]) if key]
    order = ", ".join(
        [
            *(f"{name} COLLATE BINARY" for name in keys),
            *(f"{name} COLLATE BINARY, typeof({name})" for name in names),
        ]
    )
    cursor = connection.execute(
        f"SELECT {values} FROM main.{_quoted(table)} ORDER BY {order}"
    )
    try:
        while rows := cursor.fetchmany(_FETCH_ROWS):
            digest.update("".join(f"{row!r}\n" for row in rows).encode("ascii"))
    finally:
        cursor.close()
    return digest.hexdigest()


@contextlib.contextmanager
def _read_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Keep the reads of the block in one read transaction of ``connection``."""
    if connection.in_transaction:
        yield
        return
    connection.execute("BEGIN")
    try:
        yield
    finally:
        connection.execute("ROLLBACK")


def _virtual_module(sql: str) -> str:
    """Return the module of a ``CREATE VIRTUAL TABLE``, lower case; ``""``: unknown."""
    found = _MODULE.match(sql)
    if found is None:
        return ""
    module = found["module"]
    if module[:1] in "\"'`[":
        module = module[1:-1]
    return module.lower()


def _internal(name: str) -> bool:
    """Whether a name is reserved by SQLite (``sqlite_`` in any letter case)."""
    return name.lower().startswith("sqlite_")


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _companion(path: Path, suffix: str) -> Path:
    return path.with_name(f"{path.name}{suffix}")


@dataclass(frozen=True, slots=True)
class _Files:
    """A SQLite file and its companions at one moment, compared later.

    ``counter`` is the header's file change counter: a commit in rollback
    mode changes it even when the size stays and the clock behind the
    modification time has not moved on.
    """

    source: FileStamp
    counter: bytes
    wal: FileStamp | None
    journal: FileStamp | None
    shm: bool


def _files(path: Path) -> _Files:
    source = _stamp(path)
    with path.open("rb") as stream:
        counter = stream.read(_COUNTER_END)[_COUNTER_START:]
    journal = _stamp_or_none(_companion(path, "-journal"))
    if journal is not None and journal.size_bytes == 0:
        journal = None  # TRUNCATE mode between transactions: nothing to undo
    return _Files(
        source,
        counter,
        _stamp_or_none(_companion(path, "-wal")),
        journal,
        _companion(path, "-shm").exists(),
    )


def _files_or_none(path: Path) -> _Files | None:
    try:
        return _files(path)
    except FileNotFoundError:
        return None


def _stamp(path: Path) -> FileStamp:
    found = os.stat(path)
    return FileStamp(found.st_size, found.st_mtime_ns)


def _stamp_or_none(path: Path) -> FileStamp | None:
    try:
        return _stamp(path)
    except FileNotFoundError:
        return None


def _backup(path: Path, copy: Path) -> None:
    """State (b): the committed rows through SQLite's own locks, nothing created."""
    source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _copy_with_journal(path: Path, copy: Path, attempts: int) -> _Files:
    """State (c): copy the file and its ``-wal`` or ``-journal`` while they hold."""
    for _ in range(attempts):
        before = _files(path)
        companions = {"-wal": before.wal, "-journal": before.journal}
        try:
            shutil.copyfile(path, copy)
            for suffix, stamp in companions.items():
                if stamp is not None:
                    shutil.copyfile(_companion(path, suffix), _companion(copy, suffix))
        except FileNotFoundError:
            pass  # a companion went away: the file changed
        else:
            if _files_or_none(path) == before:
                return before
        for suffix in ("", *companions):
            _companion(copy, suffix).unlink(missing_ok=True)
    raise InconsistentReadError("the file kept changing while it was copied")


def _single_file(copy: Path) -> None:
    """Make a copy one file: recover and checkpoint its WAL, roll back its journal."""
    connection = sqlite3.connect(copy)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        connection.execute("PRAGMA journal_mode=DELETE").fetchone()
    finally:
        connection.close()
