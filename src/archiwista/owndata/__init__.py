"""Own data of projects: reading, content identity, file sets (decision 8).

Files of a project's data folder are read without a single write next to
them: the reader process (``archiwista.owndata.reader``, imported on its
own, since it runs as ``python -m``) reads them with GDAL in the sandbox,
``consistent_sqlite_read`` gives a consistent view of a SQLite file in each
of its three states, and ``content_identity`` tells whether a file changed
since its last snapshot.
"""

from archiwista.owndata.content import (
    CONTENT_METHODS,
    DERIVED_COLUMNS,
    DERIVED_TABLES,
    SHADOW_SUFFIXES,
    SQLITE_READ_ATTEMPTS,
    ContentIdentity,
    ContentMethod,
    FileStamp,
    SqliteRead,
    SqliteState,
    TableKind,
    consistent_sqlite_read,
    content_identity,
    content_method,
    file_sha256,
    fileset_sha256,
    read_sqlite,
    sqlite_content_sha256,
    table_kinds,
)
from archiwista.owndata.formats import (
    FILESET_SUFFIXES,
    SQLITE_COMPANION_SUFFIXES,
    SQLITE_MAGIC,
    fileset_members,
    is_fileset,
    is_sqlite,
)

__all__ = [
    "CONTENT_METHODS",
    "DERIVED_COLUMNS",
    "DERIVED_TABLES",
    "FILESET_SUFFIXES",
    "SHADOW_SUFFIXES",
    "SQLITE_COMPANION_SUFFIXES",
    "SQLITE_MAGIC",
    "SQLITE_READ_ATTEMPTS",
    "ContentIdentity",
    "ContentMethod",
    "FileStamp",
    "SqliteRead",
    "SqliteState",
    "TableKind",
    "consistent_sqlite_read",
    "content_identity",
    "content_method",
    "file_sha256",
    "fileset_sha256",
    "fileset_members",
    "is_fileset",
    "is_sqlite",
    "read_sqlite",
    "sqlite_content_sha256",
    "table_kinds",
]
