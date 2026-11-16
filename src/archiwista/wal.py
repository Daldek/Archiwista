"""The switch of a local SQLite database to WAL while other processes open it.

The index, the state database and the preview cache are opened by the
server, the job workers, the build processes and the command line, often at
the same moment for a new file.
"""

import sqlite3
import time

# Pause before the switch to WAL is tried again after SQLite refused it at once.
_RETRY_S = 0.01


def use_wal(connection: sqlite3.Connection, *, timeout_ms: int) -> None:
    """Switch the database of ``connection`` to WAL, also while others open it.

    The switch reads the header and then writes it. SQLite answers a process
    that read the header while another one writes it with ``SQLITE_BUSY`` at
    once, without the busy timeout, because waiting could deadlock. Processes
    that open a new database together therefore try again until
    ``timeout_ms``; after one has switched, the others only read.

    Parameters
    ----------
    connection : sqlite3.Connection
        Outside a transaction.
    timeout_ms : int
        How long a busy database is tried again: the connection's busy
        timeout.

    Raises
    ------
    sqlite3.OperationalError
        The database stayed busy for ``timeout_ms``, or another error.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as error:
            busy = error.sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY
            if not busy or time.monotonic() >= deadline:
                raise
            time.sleep(_RETRY_S)
        else:
            return
