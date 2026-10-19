"""The ``archiwista-snapshot/1`` document of a snapshot (plan v0.2, decision 9).

A snapshot of a working file is a directory
``<data folder>/.wersje/<file path>/<label>/`` with the copy of the file (the
whole set of a multi-file format) and ``migawka.json``: this module's
``SnapshotDocument``. Writing gives exactly the fields of the schema; reading
ignores fields it does not know (``extra="ignore"``), so a snapshot written
by a newer Archiwista with a new optional field stays valid. Another
``schema`` is ``UnknownSnapshotSchemaError``; a document that is not valid
JSON or misses a field is ``InvalidSnapshotError``.
"""

import json
import re
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from archiwista.owndata.content import ContentMethod

type SnapshotFormat = Literal["archiwista-snapshot/1"]
type AuthorKind = Literal["local_owner", "user", "agent"]
type CopyMethod = Literal["sqlite_backup", "files"]

SNAPSHOT_SCHEMA: SnapshotFormat = "archiwista-snapshot/1"
# The snapshots of a data folder and the working directories of snapshots
# being made, on the same file system as their target (SPEC 4.7.1).
SNAPSHOTS_DIR = ".wersje"
INCOMING_DIR = ".incoming"
SNAPSHOT_FILE = "migawka.json"
MAX_NOTE_CHARS = 2000
# ``<YYYY-MM-DD>_<sha8>``, then ``_<n>`` for the same content the same day.
LABEL_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9a-f]{8}(?:_[0-9]+)?")
_SHA256 = r"^[0-9a-f]{64}$"
_BBOX = tuple[float, float, float, float]


class SnapshotError(ValueError):
    """``migawka.json`` cannot be used as a snapshot document."""


class InvalidSnapshotError(SnapshotError):
    """Not JSON, not an object, or a field missing or of the wrong type."""


class UnknownSnapshotSchemaError(SnapshotError):
    """A ``schema`` other than ``archiwista-snapshot/1`` (a newer Archiwista)."""

    def __init__(self, schema: str) -> None:
        super().__init__(f"unknown snapshot schema {schema!r}")
        self.schema = schema


class _Part(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SnapshotAuthor(_Part):
    """Who made the snapshot: an account, ``local``, and how they acted."""

    id: str
    kind: AuthorKind
    name: str | None
    session: str | None


class SnapshotSource(_Part):
    """The working file at the moment of the copy."""

    path: str = Field(description="Relative to the data folder, ``/`` separated.")
    format: str | None = Field(description="GDAL driver; ``None``: unrecognised.")
    size_bytes: int = Field(ge=0)
    modified_at: AwareDatetime


class SnapshotContent(_Part):
    """Content identity of the copy (decision 8); its first 8 characters label it."""

    method: ContentMethod
    sha256: str = Field(pattern=_SHA256)


class SnapshotCopy(_Part):
    """How the copy was made: SQLite's backup or a copy of the files."""

    method: CopyMethod


class SnapshotFile(_Part):
    """One file of the snapshot directory with its size and SHA-256."""

    name: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=_SHA256)


class SnapshotField(_Part):
    """A field of a vector layer."""

    name: str
    type: str


class SnapshotLayer(_Part):
    """A vector layer of the copy."""

    name: str
    geometry_type: str | None
    feature_count: int | None
    crs: str | None
    fields: list[SnapshotField]


class SnapshotRaster(_Part):
    """Raster parameters of the copy."""

    width: int
    height: int
    bands: int
    dtype: str
    crs: str | None
    resolution: tuple[float, float] | None
    nodata: float | None


class SnapshotExtent(_Part):
    """Extent of the copy in its CRS and in WGS84 (the pinned operation)."""

    crs: str | None
    bbox: _BBOX
    wgs84: _BBOX | None


class SnapshotDocument(_Part):
    """``migawka.json``: the ``archiwista-snapshot/1`` document of a snapshot.

    Field names follow the schema of decision 9; ``schema`` and ``copy`` are
    the aliases of ``format`` and ``copied`` (names Pydantic keeps for
    itself). Dump with ``by_alias=True``.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    format: SnapshotFormat = Field(default=SNAPSHOT_SCHEMA, alias="schema")
    label: str = Field(pattern=LABEL_PATTERN.pattern)
    created_at: AwareDatetime
    author: SnapshotAuthor
    note: str = Field(max_length=MAX_NOTE_CHARS)
    source: SnapshotSource
    content: SnapshotContent
    copied: SnapshotCopy = Field(alias="copy")
    files: list[SnapshotFile]
    size_bytes: int = Field(ge=0)
    layers: list[SnapshotLayer] | None
    raster: SnapshotRaster | None
    feature_count: int | None
    extent: SnapshotExtent | None
    archiwista: str


def parse_snapshot_document(data: bytes) -> tuple[dict[str, object], SnapshotDocument]:
    """Read ``migawka.json``.

    Parameters
    ----------
    data : bytes
        The file's bytes (UTF-8 JSON).

    Returns
    -------
    tuple[dict, SnapshotDocument]
        The document as written, with fields this version does not know,
        and its validated model.

    Raises
    ------
    UnknownSnapshotSchemaError
        Another ``schema`` (a format of a newer Archiwista).
    InvalidSnapshotError
        Not a JSON object, or not a valid ``archiwista-snapshot/1``.
    """
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise InvalidSnapshotError(f"not JSON: {error}") from error
    if not isinstance(raw, dict):
        raise InvalidSnapshotError("not a JSON object")
    schema = raw.get("schema")
    if not isinstance(schema, str):
        raise InvalidSnapshotError("no schema")
    if schema != SNAPSHOT_SCHEMA:
        raise UnknownSnapshotSchemaError(schema)
    try:
        document = SnapshotDocument.model_validate(raw)
    except ValidationError as error:
        raise InvalidSnapshotError(str(error)) from error
    return raw, document
