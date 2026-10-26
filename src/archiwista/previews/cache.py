"""Preview cache: objects by content with LRU accounting (plan v0.2, decision 3).

``<data_dir>/previews/`` (``AppPaths.previews_dir``, mode ``0700``, never on a
share or in a store) keeps what render processes make, by content::

    objects/<key[:2]>/<key>/<renderer>-r<version>/    one object (CacheKey):
        info.json, cog.tif, source.gpkg, thumb-<style>-<size>[-<frame>].png,
        tiles/<style>[-<params>]/<z>/<x>/<y>.png
    cache.sqlite                     the objects' files, sizes, uses and pins
    .incoming/<host>_<pid>_<token>/  a process's files before they are put

An object's key hashes its content (a ``sha256``; ``path_key`` for a version
without one; ``composite_key`` for a layer) together with the source metadata
used for rendering, its renderer and the renderer's version
(``RENDERER_VERSIONS``). Store versions never change and every change of a
renderer raises its version, so an object is never stale; different indexed
placements or styles of the same bytes never share an object.
``cache.sqlite`` only accounts for the files: without it ``reconcile`` adopts
the objects found on the disk, and an empty directory is an empty cache.

A put over the limit (``preview_cache_limit_gb``) evicts the least recently
used objects down to ``EVICT_TO`` of it, never one pinned by a live process
(being built). A hit writes its use at most once per ``TOUCH_INTERVAL_S`` per
object and process, so serving a tile is normally no SQLite write. ``room``
tells what puts may add before they would evict an object used lately, and
``peek`` reads a file without counting a use: the ``preview_warm`` job keeps
within both.

The server, job workers and the command line share the cache. Every change
under ``objects/`` (a put's rename, an eviction's removal) is made inside one
``BEGIN IMMEDIATE`` transaction of ``cache.sqlite`` together with the rows it
changes, so the changes of different processes never interleave and a
committed row has its file. Readers take no lock: ``get`` reads a file whole
at once and ``open`` holds its descriptor, so an object another process
evicts right after a hit still reads complete (POSIX); a file missing at
opening is a miss. A process killed between a rename and its commit leaves a
file without a row or a row without a file, which ``reconcile`` (at ``serve``
start) settles.

Only the standard library is imported here (no GDAL): the server opens the
cache at its start.
"""

import contextlib
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import sqlite3
import stat
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import BinaryIO, Literal, Self

from archiwista.paths import PRIVATE_DIRECTORY_MODE, private_directory
from archiwista.previews.types import COG_NAME as COG_NAME
from archiwista.previews.types import (
    CONTENT_KEY,
    RENDERER_NAMES,
    PreviewSource,
    RendererName,
)
from archiwista.previews.types import SOURCE_GPKG_NAME as SOURCE_GPKG_NAME
from archiwista.sandbox import (
    owner_alive,
    process_dir,
    process_owner,
    prune_dead_process_dirs,
)
from archiwista.wal import use_wal

CACHE_FILE = "cache.sqlite"
OBJECTS_DIR = "objects"
INCOMING_DIR = ".incoming"
# Files of an object besides its local COG (``COG_NAME``), the consistent
# copy of an own-data SQLite file in state (b) or (c) (``SOURCE_GPKG_NAME``,
# decision 8), thumbnails and tiles (``thumbnail_name``, ``tile_name``): the
# probe.
INFO_NAME = "info.json"
# A hit writes its object's use at most this often per process.
TOUCH_INTERVAL_S = 300.0
# A put over the limit evicts down to this part of it.
EVICT_TO = 0.9
# Version of each renderer's objects, raised with every change of what it
# makes: its older objects become misses, and ``reconcile`` removes them.
# Version 2 partitions identical bytes by their indexed rendering metadata.
RENDERER_VERSIONS: Mapping[RendererName, int] = {
    "raster": 2,
    "vector": 2,
    "points": 2,
    "archive": 2,
    "document": 2,
    "composite": 2,
}
# Version of the tables of cache.sqlite: another one is dropped and rebuilt.
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 10_000

# An object as its rows name it: content key, renderer, renderer version.
type _Columns = tuple[str, str, int]
type _SchemaState = Literal["created", "current", "rebuilt"]

# A file of an object: segments of letters, digits, ".", "_" and "-".
_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
_NAME = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
_STYLE = re.compile(r"[A-Za-z0-9_-]+")
_PREFIX = re.compile(r"[0-9a-f]{2}")
_RENDERER_DIR = re.compile(r"(?P<renderer>[a-z]+)-r(?P<version>[1-9][0-9]*)")
# Objects read at once while evicting.
_EVICT_BATCH = 256
# Uses remembered before those older than TOUCH_INTERVAL_S are forgotten.
_REMEMBERED_USES = 4096
_TOUCH = (
    "UPDATE objects SET used_at = max(used_at, ?)"
    " WHERE content_key = ? AND renderer = ? AND renderer_version = ?"
)
_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE objects (
        id INTEGER PRIMARY KEY,
        content_key TEXT NOT NULL,
        renderer TEXT NOT NULL,
        renderer_version INTEGER NOT NULL,
        used_at REAL NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        UNIQUE (content_key, renderer, renderer_version)
    )
    """,
    "CREATE INDEX objects_by_use ON objects (used_at)",
    """
    CREATE TABLE files (
        object_id INTEGER NOT NULL REFERENCES objects (id),
        name TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        PRIMARY KEY (object_id, name)
    ) WITHOUT ROWID
    """,
    # One row per process (owner, "<host>_<pid>") and PreviewCache (holder).
    """
    CREATE TABLE pins (
        content_key TEXT NOT NULL,
        renderer TEXT NOT NULL,
        renderer_version INTEGER NOT NULL,
        owner TEXT NOT NULL,
        holder TEXT NOT NULL,
        PRIMARY KEY (content_key, renderer, renderer_version, owner, holder)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE totals (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        used_bytes INTEGER NOT NULL,
        objects INTEGER NOT NULL
    )
    """,
    "INSERT INTO totals (id, used_bytes, objects) VALUES (1, 0, 0)",
    # Sizes follow the files: an object's is the sum of its files', the
    # total the sum of the objects'. An object loses its files first.
    """
    CREATE TRIGGER file_added AFTER INSERT ON files BEGIN
        UPDATE objects SET size_bytes = size_bytes + NEW.size_bytes
        WHERE id = NEW.object_id;
    END
    """,
    """
    CREATE TRIGGER file_resized AFTER UPDATE OF size_bytes ON files BEGIN
        UPDATE objects SET size_bytes = size_bytes - OLD.size_bytes + NEW.size_bytes
        WHERE id = NEW.object_id;
    END
    """,
    """
    CREATE TRIGGER file_removed AFTER DELETE ON files BEGIN
        UPDATE objects SET size_bytes = size_bytes - OLD.size_bytes
        WHERE id = OLD.object_id;
    END
    """,
    """
    CREATE TRIGGER object_added AFTER INSERT ON objects BEGIN
        UPDATE totals SET used_bytes = used_bytes + NEW.size_bytes,
            objects = objects + 1;
    END
    """,
    """
    CREATE TRIGGER object_resized AFTER UPDATE OF size_bytes ON objects BEGIN
        UPDATE totals SET used_bytes = used_bytes - OLD.size_bytes + NEW.size_bytes;
    END
    """,
    """
    CREATE TRIGGER object_removed AFTER DELETE ON objects BEGIN
        UPDATE totals SET used_bytes = used_bytes - OLD.size_bytes,
            objects = objects - 1;
    END
    """,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, order=True)
class CacheKey:
    """One object of the preview cache: a content and the renderer that made it.

    Parameters
    ----------
    content_key : str
        The content as lower-case SHA-256 hex: a ``sha256``, a path key
        (``path_key``) or a composite key (``composite_key``).
    renderer : RendererName
        The renderer of the object's files.
    renderer_version : int
        Its version that made them (``RENDERER_VERSIONS`` for new objects).

    Raises
    ------
    ValueError
        Another content key, an unknown renderer or a version below 1.
    """

    content_key: str
    renderer: RendererName
    renderer_version: int

    def __post_init__(self) -> None:
        """Refuse a key that names no object (``ValueError``)."""
        if CONTENT_KEY.fullmatch(self.content_key) is None:
            raise ValueError("a content key is a lower-case SHA-256")
        if self.renderer not in RENDERER_NAMES:
            raise ValueError(f"unknown renderer {self.renderer!r}")
        if self.renderer_version < 1:
            raise ValueError("a renderer version is a positive integer")

    @property
    def directory(self) -> PurePosixPath:
        """Return the object's directory below the cache root.

        ``objects/<key[:2]>/<key>/<renderer>-r<version>``.
        """
        return _object_directory(_columns(self))


@dataclass(frozen=True, slots=True)
class CacheUsage:
    """What the preview cache holds against its limit.

    Parameters
    ----------
    used_bytes : int
        Bytes of the objects' files.
    limit_bytes : int
        The limit a put evicts to keep.
    objects : int
        Objects with at least one file.
    """

    used_bytes: int
    limit_bytes: int
    objects: int


def cache_key(source: PreviewSource) -> CacheKey:
    """Key artifacts by bytes and all inputs that can affect their rendering.

    The main file name can change vector layer labels and auxiliary-file
    recognition; the other names identify files in a file set. A source
    stamp, reference or absolute path is deliberately excluded: identical
    content and rendering metadata can still share the rendered artifacts.
    """
    metadata = {
        "format": source.format.name,
        "format_hint": source.format_hint,
        "kind": source.kind,
        "filename": source.paths[0].name,
        "members": [path.name for path in source.paths[1:]],
        "crs": source.crs,
        "georeference": None
        if source.georeference is None
        else {
            "bbox": source.georeference.bbox,
            "crs": source.georeference.crs,
        },
        "nodata": source.nodata,
        "product": source.product,
        "dataset_key": source.dataset_key,
        "mutable": source.mutable,
    }
    identity = json.dumps(
        [source.content_key, metadata], sort_keys=True, separators=(",", ":")
    )
    content = _sha256("preview-source:" + identity)
    renderer = source.renderer
    return CacheKey(content, renderer, RENDERER_VERSIONS[renderer])


def composite_key(
    op: str,
    contents: Iterable[str],
    frame_or_tile: str,
    style: str,
    size: int | None,
) -> str:
    """Return the content key of a composite object (a layer's thumbnail or tile).

    The ``sha256`` of ``"composite:"`` followed by the operation, the sorted
    contents, the frame or tile, the style and the size (empty without one),
    joined by line feeds. No field holds a line feed and every content is a
    content key, so the text names one set of fields only (decision 3).

    Parameters
    ----------
    op : str
        The operation, e.g. ``layer_thumbnail``.
    contents : iterable of str
        Content keys of the layer's ready versions, in any order.
    frame_or_tile : str
        The frame of a thumbnail or ``<z>/<x>/<y>`` of a tile.
    style : str
        The style.
    size : int or None
        The size of a thumbnail; ``None`` for a tile.

    Returns
    -------
    str
        Lower-case SHA-256 hex.

    Raises
    ------
    ValueError
        A content that is not a content key, or a field with a line feed.
    """
    keys = sorted(contents)
    if any(CONTENT_KEY.fullmatch(key) is None for key in keys):
        raise ValueError("a content key is a lower-case SHA-256")
    if any("\n" in text for text in (op, frame_or_tile, style)):
        raise ValueError("a composite key field holds no line feed")
    fields = [op, *keys, frame_or_tile, style, "" if size is None else str(size)]
    return _sha256("composite:" + "\n".join(fields))


def path_key(store: str, path: str, size_bytes: int, modified_ns: int) -> str:
    """Return the content key of a store version without a ``sha256``.

    ``sha256("path:" + store + ":" + path + ":" + size + ":" + mtime)``:
    store versions never change, so the key is right, only not shared with
    copies of the same bytes (decision 3, A-ADR-008 errata 3).

    Parameters
    ----------
    store : str
        The store's id (without ``:``).
    path : str
        The version's path in the store.
    size_bytes : int
        The version's size.
    modified_ns : int
        Its modification time in nanoseconds.

    Returns
    -------
    str
        Lower-case SHA-256 hex.

    Raises
    ------
    ValueError
        A store id with ``:``.
    """
    if ":" in store:
        raise ValueError("a store id holds no ':'")
    return _sha256(f"path:{store}:{path}:{size_bytes}:{modified_ns}")


def params_digest(text: str) -> str:
    """Return 12 hex characters of the ``sha256`` of a frame or parameters."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def thumbnail_name(style: str, size: int, frame: str | None = None) -> str:
    """Return the name of a thumbnail in its object.

    Parameters
    ----------
    style : str
        The style (letters, digits, ``_``, ``-``).
    size : int
        The size in pixels.
    frame : str or None, optional
        The frame as canonical text; its digest ends the name.

    Returns
    -------
    str
        ``thumb-<style>-<size>[-<params_digest(frame)>].png``.

    Raises
    ------
    ValueError
        Another style name, or a size below 1.
    """
    _require_style(style)
    if size < 1:
        raise ValueError("a thumbnail size is positive")
    suffix = "" if frame is None else f"-{params_digest(frame)}"
    return f"thumb-{style}-{size}{suffix}.png"


def tile_name(style: str, z: int, x: int, y: int, params: str | None = None) -> str:
    """Return the name of a tile in its object.

    Parameters
    ----------
    style : str
        The style (letters, digits, ``_``, ``-``).
    z, x, y : int
        The tile.
    params : str or None, optional
        Further parameters as canonical text (``rescale``); their digest
        follows the style.

    Returns
    -------
    str
        ``tiles/<style>[-<params_digest(params)>]/<z>/<x>/<y>.png``.

    Raises
    ------
    ValueError
        Another style name, or a negative tile number.
    """
    _require_style(style)
    if min(z, x, y) < 0:
        raise ValueError("tile numbers are not negative")
    suffix = "" if params is None else f"-{params_digest(params)}"
    return f"tiles/{style}{suffix}/{z}/{x}/{y}.png"


class PreviewCache:
    """The preview cache of one data directory, shared by its processes.

    One SQLite connection per instance, used by one thread at a time; the
    instance may be shared by threads.

    Parameters
    ----------
    root : Path
        The cache directory (``AppPaths.previews_dir``), created ``0700``.
    limit_bytes : int
        Bytes of the objects' files a put evicts to keep
        (``AppSettings.preview_cache_limit_bytes``).
    clock : callable, optional
        Seconds since the epoch: when an object is used.

    Raises
    ------
    ValueError
        A negative limit.
    sqlite3.Error
        ``cache.sqlite`` cannot be opened.

    Notes
    -----
    Without ``cache.sqlite``, or with one of another schema version (dropped
    and rebuilt), the cache reconciles at once and adopts the objects on the
    disk.
    """

    def __init__(
        self,
        root: Path,
        *,
        limit_bytes: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        _require_limit(limit_bytes)
        self._root = private_directory(root)
        self._limit = limit_bytes
        self._clock = clock
        # Guards the connection and the pins; a hit takes it only to write
        # its use.
        self._lock = threading.Lock()
        self._used_lock = threading.Lock()
        self._used: dict[CacheKey, float] = {}
        self._forget_at = _REMEMBERED_USES
        self._pins: dict[CacheKey, int] = {}
        self._holder = secrets.token_hex(8)
        self._closed = False
        self._db = _connect(root / CACHE_FILE)
        try:
            if _initialize(self._db) != "current":
                self.reconcile()
        except BaseException:
            self._db.close()
            raise

    @property
    def root(self) -> Path:
        """The cache directory."""
        return self._root

    @property
    def limit_bytes(self) -> int:
        """The limit a put evicts to keep."""
        return self._limit

    def set_limit(self, limit_bytes: int) -> None:
        """Change the limit, evicting when the cache is now over it.

        Parameters
        ----------
        limit_bytes : int
            The new limit.

        Raises
        ------
        ValueError
            A negative limit.
        """
        _require_limit(limit_bytes)
        with self._lock:
            self._limit = limit_bytes
            with self._transaction() as db:
                self._evict_over_limit(db)

    def get(self, key: CacheKey, name: str) -> bytes | None:
        """Return a small file of an object, read whole at once.

        For ``info.json``, thumbnails and tiles: removed by another process
        after the hit, the bytes stay complete. A hit writes the object's
        use unless this process did within ``TOUCH_INTERVAL_S``.

        Parameters
        ----------
        key : CacheKey
            The object.
        name : str
            The file (``INFO_NAME``, ``thumbnail_name``, ``tile_name``).

        Returns
        -------
        bytes or None
            The file, or ``None`` (a miss).

        Raises
        ------
        ValueError
            A name that is not a relative path of the object's files.
        """
        path = self._file(key, name)
        try:
            data = path.read_bytes()
        except (FileNotFoundError, NotADirectoryError):
            return None
        self._touch(key)
        return data

    def open(self, key: CacheKey, name: str) -> BinaryIO | None:
        """Open a large file of an object for reading; the caller closes it.

        For ``cog.tif`` and ``source.gpkg``: removed by another process after
        the opening, the file still reads complete (POSIX). Uses count as in
        ``get``.

        Parameters
        ----------
        key : CacheKey
            The object.
        name : str
            The file (``COG_NAME``, ``SOURCE_GPKG_NAME``).

        Returns
        -------
        BinaryIO or None
            The open file, or ``None`` (a miss).

        Raises
        ------
        ValueError
            A name that is not a relative path of the object's files.
        """
        path = self._file(key, name)
        try:
            file = path.open("rb")
        except (FileNotFoundError, NotADirectoryError):
            return None
        try:
            self._touch(key)
        except BaseException:
            file.close()
            raise
        return file

    def has(self, key: CacheKey, name: str) -> bool:
        """Whether an object has a file; not a use.

        Raises
        ------
        ValueError
            A name that is not a relative path of the object's files.
        """
        return self._file(key, name).is_file()

    def peek(self, key: CacheKey, name: str) -> bytes | None:
        """Return a small file of an object as ``get`` does, but not as a use.

        For a look that is no view: the ``preview_warm`` job checks what an
        object holds without making it recently used.

        Raises
        ------
        ValueError
            A name that is not a relative path of the object's files.
        """
        try:
            return self._file(key, name).read_bytes()
        except (FileNotFoundError, NotADirectoryError):
            return None

    def put(self, key: CacheKey, name: str, data: bytes | Path) -> None:
        """Keep a file of an object, replacing one of the same name.

        Bytes are written in this process's ``incoming_dir`` first; a path is
        a finished file, moved into the cache (one on another file system is
        copied, then removed). Then one write transaction records the file
        (an object's use; a replaced file changes the usage by the
        difference only), renames it into the object and, over the limit,
        evicts the least recently used unpinned objects down to ``EVICT_TO``
        of it: this one too when its files alone are too much.

        Parameters
        ----------
        key : CacheKey
            The object.
        name : str
            The file (``INFO_NAME``, ``COG_NAME``, ``thumbnail_name``,
            ``tile_name`` …).
        data : bytes or Path
            The content, or a finished file (normally in ``incoming_dir``).

        Raises
        ------
        ValueError
            A name that is not a relative path of the object's files, or a
            path that is not a regular file.
        OSError, sqlite3.Error
            The file could not be kept. A given path stays where it was,
            unless the failure came after its rename: ``reconcile`` adopts
            it then.
        """
        target = self._file(key, name)
        staged, copied = self._stage(data)
        now = self._clock()
        try:
            size = os.stat(staged).st_size
            # Rename and evictions inside the write transaction: the files
            # of other processes' puts and evictions never change meanwhile.
            with self._lock, self._transaction() as db:
                object_id = _upsert_object(db, _columns(key), now)
                db.execute(
                    "INSERT INTO files (object_id, name, size_bytes) VALUES (?, ?, ?)"
                    " ON CONFLICT (object_id, name)"
                    " DO UPDATE SET size_bytes = excluded.size_bytes",
                    (object_id, name, size),
                )
                _private_directories(target.parent)
                os.replace(staged, target)
                self._evict_over_limit(db)
        except BaseException:
            if copied:
                staged.unlink(missing_ok=True)
            raise
        if copied and isinstance(data, Path):
            data.unlink(missing_ok=True)
        with self._used_lock:
            self._remember_use(key, now)

    def pin(self, key: CacheKey) -> None:
        """Keep an object from eviction while it is built, files or not yet.

        Pins nest; the last ``unpin`` releases the object. A pin of a process
        of this host that ended without releasing it expires.

        Parameters
        ----------
        key : CacheKey
            The object.
        """
        with self._lock:
            count = self._pins.get(key, 0)
            if count == 0:
                self._db.execute(
                    "INSERT OR IGNORE INTO pins"
                    " (content_key, renderer, renderer_version, owner, holder)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (*_columns(key), process_owner(), self._holder),
                )
            self._pins[key] = count + 1

    def unpin(self, key: CacheKey) -> None:
        """Release a pin of ``pin``.

        Parameters
        ----------
        key : CacheKey
            The object.

        Raises
        ------
        ValueError
            The object is not pinned by this cache.
        """
        with self._lock:
            count = self._pins.get(key, 0)
            if count == 0:
                raise ValueError("the preview cache object is not pinned")
            if count == 1:
                self._db.execute(
                    "DELETE FROM pins WHERE content_key = ? AND renderer = ?"
                    " AND renderer_version = ? AND owner = ? AND holder = ?",
                    (*_columns(key), process_owner(), self._holder),
                )
                del self._pins[key]
            else:
                self._pins[key] = count - 1

    def usage(self) -> CacheUsage:
        """Return the bytes and objects in the cache and its limit."""
        with self._lock:
            row = self._db.execute("SELECT used_bytes, objects FROM totals").fetchone()
            return CacheUsage(int(row[0]), self._limit, int(row[1]))

    def room(self, *, used_before: float) -> int:
        """Return the bytes puts may add without evicting an object used lately.

        A put within the limit evicts nothing; one past it evicts the least
        recently used unpinned objects down to ``EVICT_TO`` of the limit, so
        the objects last used before ``used_before`` go first. The room is
        what stays below the limit, or what those objects can make room for,
        whichever is more.

        Parameters
        ----------
        used_before : float
            Seconds since the epoch: an object last used before it may go
            (an object pinned by any process, even one that ended, never).

        Returns
        -------
        int
            Bytes, ``0`` when the cache cannot take more without evicting an
            object used since ``used_before``.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT (SELECT used_bytes FROM totals),"
                " (SELECT coalesce(sum(o.size_bytes), 0) FROM objects o"
                " WHERE o.used_at < ? AND NOT EXISTS (SELECT 1 FROM pins p"
                " WHERE p.content_key = o.content_key AND p.renderer = o.renderer"
                " AND p.renderer_version = o.renderer_version))",
                (used_before,),
            ).fetchone()
        used, cold = int(row[0]), int(row[1])
        return max(0, self._limit - used, int(self._limit * EVICT_TO) - used + cold)

    def evict(self) -> int:
        """Evict down to ``EVICT_TO`` of the limit when over it.

        Returns
        -------
        int
            Bytes freed.
        """
        with self._lock, self._transaction() as db:
            return self._evict_over_limit(db)

    def reconcile(self) -> None:
        """Make ``cache.sqlite`` agree with the files (``serve`` start, new file).

        Files without rows are adopted (their size; their modification time
        as the object's use), rows without files dropped, objects of another
        renderer version and other entries under ``objects/`` removed, the
        pins and ``.incoming`` directories of this host's dead processes
        dropped; then the cache evicts when over its limit. The files are
        listed outside the write transaction; each difference is checked
        again inside it, so a concurrent put is never lost.
        """
        objects = self._root / OBJECTS_DIR
        listing = _scan(objects)
        changes: Counter[str] = Counter()
        with self._lock:
            rows = _file_rows(self._db)
            with self._transaction() as db:
                changes["stale"] += self._remove_stale_objects(db)
                for columns, name in _differences(listing.files, rows):
                    change = self._settle_file(db, columns, name)
                    if change is not None:
                        changes[change] += 1
                for path in listing.stale:
                    if os.path.lexists(path) and _remove_entry(path):
                        changes["stale"] += 1
                        _prune_empty(path.parent, objects)
                for path in listing.empty:
                    _prune_empty(path, objects)
                db.execute(
                    "DELETE FROM objects WHERE NOT EXISTS"
                    " (SELECT 1 FROM files WHERE files.object_id = objects.id)"
                )
                _live_pins(db)
                self._evict_over_limit(db)
        prune_dead_process_dirs(self._root / INCOMING_DIR)
        if changes:
            logger.info(
                "Preview cache reconciled: %d files adopted, %d resized,"
                " %d dropped, %d stale entries removed",
                changes["adopted"],
                changes["resized"],
                changes["dropped"],
                changes["stale"],
            )

    def incoming_dir(self) -> Path:
        """Return this process's directory for files on their way in.

        ``<root>/.incoming/<host>_<pid>_<token>/`` (``0700``), created on the
        first call; the same on every call of the process. A finished file
        written there is put by its path.
        """
        return process_dir(self._root / INCOMING_DIR)

    def close(self) -> None:
        """Release this cache's pins and close its connection; idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._pins:
                    self._pins.clear()
                    self._db.execute(
                        "DELETE FROM pins WHERE owner = ? AND holder = ?",
                        (process_owner(), self._holder),
                    )
            except sqlite3.Error as error:
                logger.warning("Cannot release the preview cache pins: %s", error)
            finally:
                self._db.close()

    def __enter__(self) -> Self:
        """Use the cache as a context manager that closes it."""
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the cache."""
        self.close()

    def _file(self, key: CacheKey, name: str) -> Path:
        """Return where an object's file lies."""
        _require_name(name)
        return self._root.joinpath(*key.directory.parts, *name.split("/"))

    def _stage(self, data: bytes | Path) -> tuple[Path, bool]:
        """Return the file to rename into the cache and whether it is a copy."""
        if isinstance(data, Path):
            found = os.stat(data)
            if not stat.S_ISREG(found.st_mode):
                raise ValueError(f"not a regular file: {data}")
            if found.st_dev == os.stat(self._root).st_dev:
                return data, False
        staged = self.incoming_dir() / f"{secrets.token_hex(8)}.part"
        try:
            if isinstance(data, Path):
                shutil.copyfile(data, staged)
            else:
                with staged.open("xb") as file:
                    file.write(data)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
        return staged, True

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block in one write transaction; the caller holds ``_lock``."""
        db = self._db
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")

    def _touch(self, key: CacheKey) -> None:
        """Write a hit's use, unless this process wrote the object's lately."""
        now = self._clock()
        with self._used_lock:
            last = self._used.get(key)
            if last is not None and 0 <= now - last < TOUCH_INTERVAL_S:
                return
            self._remember_use(key, now)
        try:
            with self._lock:
                self._db.execute(_TOUCH, (now, *_columns(key)))
        except sqlite3.OperationalError as error:
            # The use only orders evictions: a busy database keeps the hit.
            with self._used_lock:
                if self._used.get(key) == now:
                    del self._used[key]
            logger.warning("Cannot write the use of a preview: %s", error)

    def _remember_use(self, key: CacheKey, now: float) -> None:
        """Remember when this process wrote an object's use (``_used_lock`` held)."""
        self._used[key] = now
        if len(self._used) >= self._forget_at:
            self._used = {
                known: when
                for known, when in self._used.items()
                if 0 <= now - when < TOUCH_INTERVAL_S
            }
            self._forget_at = max(_REMEMBERED_USES, 2 * len(self._used))

    def _evict_over_limit(self, db: sqlite3.Connection) -> int:
        """Evict unpinned objects, least recently used first, when over the limit.

        Down to ``EVICT_TO`` of the limit; inside the caller's transaction.
        Returns the bytes freed.
        """
        used = _used_bytes(db)
        if used <= self._limit:
            return 0
        goal = int(self._limit * EVICT_TO)
        pinned = _live_pins(db)
        freed = 0
        after: tuple[float, int] = (-math.inf, 0)
        while used > goal:
            rows = db.execute(
                "SELECT id, used_at, content_key, renderer, renderer_version,"
                " size_bytes FROM objects WHERE (used_at, id) > (?, ?)"
                " ORDER BY used_at, id LIMIT ?",
                (*after, _EVICT_BATCH),
            ).fetchall()
            if not rows:
                break
            for object_id, used_at, content_key, renderer, version, size in rows:
                after = (used_at, object_id)
                columns = (content_key, renderer, version)
                if columns in pinned or not self._remove_object(db, object_id, columns):
                    continue
                used -= size
                freed += size
                if used <= goal:
                    break
        if freed:
            logger.debug("Preview cache evicted %d bytes", freed)
        return freed

    def _remove_object(
        self, db: sqlite3.Connection, object_id: int, columns: _Columns
    ) -> bool:
        """Remove an object's directory, then its rows; whether it is gone."""
        path = self._root / _object_directory(columns)
        if not _remove_entry(path):
            return False
        _prune_empty(path.parent, self._root / OBJECTS_DIR)
        db.execute("DELETE FROM files WHERE object_id = ?", (object_id,))
        db.execute("DELETE FROM objects WHERE id = ?", (object_id,))
        return True

    def _remove_stale_objects(self, db: sqlite3.Connection) -> int:
        """Remove the objects of renderer versions other than the current ones."""
        current = list(RENDERER_VERSIONS.items())
        values = ", ".join("(?, ?)" for _ in current)
        rows = db.execute(
            "SELECT id, content_key, renderer, renderer_version FROM objects"
            f" WHERE (renderer, renderer_version) NOT IN (VALUES {values})",
            [value for pair in current for value in pair],
        ).fetchall()
        return sum(
            self._remove_object(db, object_id, (content_key, renderer, version))
            for object_id, content_key, renderer, version in rows
        )

    def _settle_file(
        self, db: sqlite3.Connection, columns: _Columns, name: str
    ) -> str | None:
        """Make a file's row agree with the disk; return what changed."""
        path = self._root.joinpath(*_object_directory(columns).parts, *name.split("/"))
        try:
            found: os.stat_result | None = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            found = None
        except OSError as error:
            logger.warning("Cannot check the preview cache file %s: %s", path, error)
            return None
        if found is not None and not stat.S_ISREG(found.st_mode):
            found = None
        row = db.execute(
            "SELECT files.object_id, files.size_bytes FROM files"
            " JOIN objects ON objects.id = files.object_id"
            " WHERE objects.content_key = ? AND objects.renderer = ?"
            " AND objects.renderer_version = ? AND files.name = ?",
            (*columns, name),
        ).fetchone()
        if found is None:
            if row is None:
                return None
            db.execute(
                "DELETE FROM files WHERE object_id = ? AND name = ?", (row[0], name)
            )
            return "dropped"
        if row is None:
            object_id = _upsert_object(db, columns, found.st_mtime)
            db.execute(
                "INSERT INTO files (object_id, name, size_bytes) VALUES (?, ?, ?)",
                (object_id, name, found.st_size),
            )
            return "adopted"
        if row[1] == found.st_size:
            return None
        db.execute(
            "UPDATE files SET size_bytes = ? WHERE object_id = ? AND name = ?",
            (found.st_size, row[0], name),
        )
        return "resized"


@dataclass(slots=True)
class _Listing:
    """What ``reconcile`` found under ``objects/`` outside its transaction."""

    # Files of the current renderer versions' objects: name -> size.
    files: dict[_Columns, dict[str, int]] = field(default_factory=dict)
    # Entries to remove: other renderer versions, other names, links.
    stale: list[Path] = field(default_factory=list)
    # Directories without files, removed while still empty.
    empty: list[Path] = field(default_factory=list)


def _scan(objects: Path) -> _Listing:
    """List the objects' files, and what does not belong, under ``objects/``."""
    listing = _Listing()
    current = _current_versions()
    for prefix in _entries(objects):
        prefix_path = objects / prefix.name
        if not (
            _PREFIX.fullmatch(prefix.name) and prefix.is_dir(follow_symlinks=False)
        ):
            listing.stale.append(prefix_path)
            continue
        contents = _entries(prefix_path)
        if not contents:
            listing.empty.append(prefix_path)
        for content in contents:
            content_path = prefix_path / content.name
            if not (
                CONTENT_KEY.fullmatch(content.name)
                and content.name.startswith(prefix.name)
                and content.is_dir(follow_symlinks=False)
            ):
                listing.stale.append(content_path)
                continue
            renderers = _entries(content_path)
            if not renderers:
                listing.empty.append(content_path)
            for renderer in renderers:
                renderer_path = content_path / renderer.name
                columns = _object_of(content.name, renderer.name, current)
                if columns is None or not renderer.is_dir(follow_symlinks=False):
                    listing.stale.append(renderer_path)
                    continue
                files: dict[str, int] = {}
                _scan_files(renderer_path, "", files, listing.stale)
                if files:
                    listing.files[columns] = files
                else:
                    listing.empty.append(renderer_path)
    return listing


def _scan_files(
    directory: Path, prefix: str, files: dict[str, int], stale: list[Path]
) -> None:
    """Add the regular files below an object's directory to ``files``."""
    for entry in _entries(directory):
        path = directory / entry.name
        name = prefix + entry.name
        try:
            if entry.is_dir(follow_symlinks=False):
                if _SEGMENT.fullmatch(entry.name):
                    _scan_files(path, f"{name}/", files, stale)
                else:
                    stale.append(path)
            elif entry.is_file(follow_symlinks=False) and _NAME.fullmatch(name):
                files[name] = entry.stat(follow_symlinks=False).st_size
            else:
                stale.append(path)
        except FileNotFoundError:  # evicted meanwhile
            continue


def _entries(directory: Path) -> list[os.DirEntry[str]]:
    """List a directory; nothing when it is gone or unreadable (logged)."""
    try:
        with os.scandir(directory) as entries:
            return list(entries)
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as error:
        logger.warning(
            "Cannot list the preview cache directory %s: %s", directory, error
        )
        return []


def _current_versions() -> set[tuple[str, int]]:
    """Return each renderer with its current version (``RENDERER_VERSIONS``)."""
    return {(str(renderer), version) for renderer, version in RENDERER_VERSIONS.items()}


def _object_of(
    content_key: str, directory: str, current: set[tuple[str, int]]
) -> _Columns | None:
    """Return the object of a renderer directory of a current version."""
    match = _RENDERER_DIR.fullmatch(directory)
    if match is None:
        return None
    renderer, version = match["renderer"], int(match["version"])
    return (content_key, renderer, version) if (renderer, version) in current else None


def _differences(
    disk: Mapping[_Columns, Mapping[str, int]],
    rows: Mapping[_Columns, Mapping[str, int]],
) -> list[tuple[_Columns, str]]:
    """Return the files of current objects whose row and disk size differ."""
    current = _current_versions()
    found: list[tuple[_Columns, str]] = []
    for columns in disk.keys() | rows.keys():
        if (columns[1], columns[2]) not in current:
            continue
        on_disk = disk.get(columns, {})
        in_rows = rows.get(columns, {})
        found.extend(
            (columns, name)
            for name in on_disk.keys() | in_rows.keys()
            if on_disk.get(name) != in_rows.get(name)
        )
    return found


def _file_rows(db: sqlite3.Connection) -> dict[_Columns, dict[str, int]]:
    """Return every file row: object -> name -> size."""
    rows: dict[_Columns, dict[str, int]] = {}
    for content_key, renderer, version, name, size in db.execute(
        "SELECT objects.content_key, objects.renderer, objects.renderer_version,"
        " files.name, files.size_bytes"
        " FROM objects JOIN files ON files.object_id = objects.id"
    ):
        rows.setdefault((content_key, renderer, version), {})[name] = size
    return rows


def _live_pins(db: sqlite3.Connection) -> set[_Columns]:
    """Drop the pins of this host's dead processes; return the pinned objects."""
    owners = db.execute("SELECT DISTINCT owner FROM pins").fetchall()
    for (owner,) in owners:
        if not owner_alive(owner):
            db.execute("DELETE FROM pins WHERE owner = ?", (owner,))
    return {
        (str(content_key), str(renderer), int(version))
        for content_key, renderer, version in db.execute(
            "SELECT content_key, renderer, renderer_version FROM pins"
        ).fetchall()
    }


def _upsert_object(db: sqlite3.Connection, columns: _Columns, used_at: float) -> int:
    """Insert an object's row or move its use later; return its id."""
    rows = db.execute(
        "INSERT INTO objects (content_key, renderer, renderer_version, used_at)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT (content_key, renderer, renderer_version)"
        " DO UPDATE SET used_at = max(used_at, excluded.used_at)"
        " RETURNING id",
        (*columns, used_at),
    ).fetchall()
    return int(rows[0][0])


def _used_bytes(db: sqlite3.Connection) -> int:
    return int(db.execute("SELECT used_bytes FROM totals").fetchone()[0])


def _connect(path: Path) -> sqlite3.Connection:
    """Open ``cache.sqlite`` in autocommit mode, for any thread."""
    connection = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
        check_same_thread=False,
    )
    try:
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


def _initialize(connection: sqlite3.Connection) -> _SchemaState:
    """Create the tables, keep current ones, or rebuild those of another version."""
    use_wal(connection, timeout_ms=BUSY_TIMEOUT_MS)
    if _user_version(connection) == SCHEMA_VERSION:
        return "current"
    # Dropping tables with foreign keys on runs checked deletes; a rebuild
    # removes everything anyway.
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            if _user_version(connection) == SCHEMA_VERSION:
                connection.execute("COMMIT")
                return "current"
            existed = _drop_all(connection)
            for statement in _SCHEMA:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    return "rebuilt" if existed else "created"


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _drop_all(connection: sqlite3.Connection) -> bool:
    """Drop every table and view (their triggers and indexes go with them)."""
    found = connection.execute(
        "SELECT type, name FROM sqlite_schema"
        " WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for kind, name in found:
        quoted = '"' + str(name).replace('"', '""') + '"'
        connection.execute(f"DROP {'VIEW' if kind == 'view' else 'TABLE'} {quoted}")
    return bool(found)


def _columns(key: CacheKey) -> _Columns:
    return key.content_key, key.renderer, key.renderer_version


def _object_directory(columns: _Columns) -> PurePosixPath:
    content_key, renderer, version = columns
    return PurePosixPath(
        OBJECTS_DIR, content_key[:2], content_key, f"{renderer}-r{version}"
    )


def _private_directories(directory: Path) -> None:
    """Create a directory and its missing parents, each ``0700``."""
    if directory.is_dir():
        return
    _private_directories(directory.parent)
    with contextlib.suppress(FileExistsError):
        directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)


def _remove_entry(path: Path) -> bool:
    """Remove a file or a directory tree; whether it is gone (failures logged)."""
    try:
        if stat.S_ISDIR(os.lstat(path).st_mode):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except FileNotFoundError:
        return True
    except OSError as error:
        logger.warning("Cannot remove %s from the preview cache: %s", path, error)
        return False
    return True


def _prune_empty(directory: Path, stop: Path) -> None:
    """Remove a directory and its parents below ``stop`` while they are empty."""
    while directory != stop and directory.is_relative_to(stop):
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError:  # not empty
            return
        directory = directory.parent


def _require_name(name: str) -> None:
    if _NAME.fullmatch(name) is None or any(
        part in (".", "..") for part in name.split("/")
    ):
        raise ValueError(f"not a preview cache file name: {name!r}")


def _require_style(style: str) -> None:
    if _STYLE.fullmatch(style) is None:
        raise ValueError(f"not a style name: {style!r}")


def _require_limit(limit_bytes: int) -> None:
    if limit_bytes < 0:
        raise ValueError("a preview cache limit is not negative")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
