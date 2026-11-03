"""Local memory of unit outlines (TERYT, KU, SM5) for Kartograf's footprints.

``file_footprint`` reads a unit outline from the caller's mapping even
without network and adds the outlines it fetches with network. This mapping
keeps them in a local SQLite file (never on a share), so a scan without
network outlines new versions of units seen before.
"""

import json
import sqlite3
import threading
import weakref
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

from kartograf import BBox

from archiwista.wal import use_wal

type UnitKey = tuple[str, str]

_BUSY_TIMEOUT_MS = 30_000
_SCHEMA = """
CREATE TABLE IF NOT EXISTS unit_bboxes (
    kind TEXT NOT NULL,
    code TEXT NOT NULL,
    bbox TEXT NOT NULL,
    PRIMARY KEY (kind, code)
)
"""


class UnitBBoxCache(MutableMapping[UnitKey, BBox]):
    """Persistent ``(kind, code) -> BBox`` mapping for ``file_footprint``.

    Parameters
    ----------
    path : Path
        SQLite file in the plugin's local cache directory. Nothing is created
        until the first outline is stored; a missing file reads as empty.

    Notes
    -----
    A ``BBox`` is stored as the JSON list of its five values
    ``[min_x, min_y, max_x, max_y, crs]``. One connection serves all threads
    under a lock; other processes share the file through SQLite locking.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None
        self._finalizer: weakref.finalize[[], UnitBBoxCache] | None = None

    def __getitem__(self, key: UnitKey) -> BBox:
        """Return the stored outline of a unit."""
        rows = self._read(
            "SELECT bbox FROM unit_bboxes WHERE kind = ? AND code = ?", key
        )
        if not rows:
            raise KeyError(key)
        min_x, min_y, max_x, max_y, crs = json.loads(rows[0][0])
        return BBox(min_x, min_y, max_x, max_y, crs)

    def __setitem__(self, key: UnitKey, value: BBox) -> None:
        """Store or replace the outline of a unit."""
        bbox = [
            float(value.min_x),
            float(value.min_y),
            float(value.max_x),
            float(value.max_y),
            str(value.crs),
        ]
        with self._lock, self._open() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO unit_bboxes (kind, code, bbox)"
                " VALUES (?, ?, ?)",
                (*key, json.dumps(bbox)),
            )

    def __delitem__(self, key: UnitKey) -> None:
        """Forget the outline of a unit."""
        rows = self._read(
            "DELETE FROM unit_bboxes WHERE kind = ? AND code = ? RETURNING code", key
        )
        if not rows:
            raise KeyError(key)

    def __iter__(self) -> Iterator[UnitKey]:
        """Iterate over the stored unit keys."""
        rows = self._read("SELECT kind, code FROM unit_bboxes ORDER BY kind, code")
        return iter([(str(kind), str(code)) for kind, code in rows])

    def __len__(self) -> int:
        """Return the number of stored outlines."""
        rows = self._read("SELECT COUNT(*) FROM unit_bboxes")
        return int(rows[0][0]) if rows else 0

    def close(self) -> None:
        """Close the connection; a later access opens it again."""
        with self._lock:
            if self._finalizer is not None:
                self._finalizer()
            self._connection = self._finalizer = None

    def _read(self, sql: str, parameters: tuple[str, ...] = ()) -> list[Any]:
        """Run one statement on an existing file; nothing when it is missing."""
        with self._lock:
            if self._connection is None and not self.path.exists():
                return []
            with self._open() as connection:
                return connection.execute(sql, parameters).fetchall()

    def _open(self) -> sqlite3.Connection:
        """Return the shared connection, creating the file and table if needed."""
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.path, timeout=_BUSY_TIMEOUT_MS / 1000, check_same_thread=False
            )
            try:
                use_wal(connection, timeout_ms=_BUSY_TIMEOUT_MS)
                connection.execute(_SCHEMA)
            except BaseException:
                connection.close()
                raise
            # Closed with the mapping, or at exit, never left to the collector.
            self._finalizer = weakref.finalize(self, connection.close)
            self._connection = connection
        return self._connection
