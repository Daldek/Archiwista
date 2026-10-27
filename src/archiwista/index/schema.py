"""Local SQLite index: schema, connection settings and rebuild on change.

The index (A-ADR-002) lives only on the local disk (``index.sqlite`` in the
user data directory), never on a share. It is a cache rebuilt from the
producers' files, so a different ``SCHEMA_VERSION`` (``PRAGMA
user_version``) means an atomic rebuild instead of a migration (SPEC 4.4):
every object is dropped and the current schema created in one transaction,
which readers in other processes see either before or after.

Tables (v0.1): ``stores``, ``segments``, ``slots``, ``versions`` with the
1:1 ``version_sidecars`` (raw sidecar) and ``version_shapes`` (outlines
that are not plain boxes, native outlines), ``footprints`` (R*Tree of WGS84
boxes, versions with a footprint only), ``search`` (FTS5, one row per
slot), ``issues``, ``projects`` with ``manifests``, ``project_tasks`` and
``pins``, ``areas``, ``jobs`` with ``job_events``, ``session_tokens`` and
``index_info``.
Public keys are a store's configured id (``stores.key``) and paths relative
to the store's producer directory; integer ids never leave the index.

Version 5 (v0.2): a WGS84 outline is the polygon of the native rectangle
(``outline_footprints``), so an index of bounding boxes is rebuilt.

Version 6 (v0.2): own data of projects (decision 8). ``own_folders`` (one
per project, keyed by the project directory after ``realpath``: the access
key), ``own_files`` (a folder's files by path, with what the reader found
and the content identity), ``own_file_states`` (observed states, at most
200 per file), ``snapshots`` (``.wersje/`` of a folder, with the full
``migawka.json``) and ``own_problems``.

Version 7 (v0.5, IMGW slots): ``slots.slot_key`` (the producer's own name of a
slot), ``versions.provider`` (the organisation that publishes the data) and
``observations`` (the publication history of a slot: a source served other
bytes with the content of a version, so no version was written).

Version 8 (v0.3, plan of 2026-10-25 A2): ``availability``, the last report of
the availability at the source of each area, producer and product (the
producer-neutral ``AvailabilityReport`` as JSON, with the time the source was
asked and the job that asked it).

Version 9 (v0.3, A4): a job may end ``partial``, and ``plans`` keeps the plan
of each ``check`` job (the producer-neutral ``ActionPlan`` as JSON, with the
store it is of and the producer's command line of the run it plans); a plan
goes with its job.

Version 10 (v0.5, plan I4): ``stations``, the stations of the current version
of each provider's station catalog in a store (identity: store, provider and
code as text), with the R*Tree ``station_points`` of the located ones (a
station without a location keeps the catalog's reason), and
``station_catalogs``, the catalog version each provider's rows were read from:
a new current version replaces the provider's rows.

Version 11 (v0.5, plan I5): ``series_catalogs``, the series version each
dataset's coverage in a store was read from (with its unit, year numbering,
first year and known periods), ``station_series``, each variable of each
station's series in that version (first and last date with a value, gaps,
accumulated sums, the station's own periods, its file), and ``series_years``,
each year of a variable in both year types (units, known units, units with a
value), computed when the index is written: a new current version replaces
the dataset's rows.

Version 12 (v0.3, ADR-044): a ``check`` job plans every call of its
``calls``, so ``plans`` keeps one plan per call (``call``, its place in the
job's ``calls``); a call whose check failed has none.

Version 13 (v0.5, plan I7): a project is its directory (``projects``, one
row and one key per directory), which holds the manifest of one producer or
of both (SPEC 4.7). ``manifests`` keeps each producer's manifest as it was
read (the store it names, its status or the producer's problem, its stamp),
and ``project_tasks`` and ``pins`` carry the producer of the manifest they
come from; they go with it.

Version 14 (v0.4, ADR-047): ``job_claims``, the positions an active
``download`` with a plan fetches (one claimant per store and path), so a
download of another person leaves them out; a claim goes with its job.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from archiwista.errors import ArchiwistaError
from archiwista.paths import private_directory
from archiwista.wal import use_wal

SCHEMA_VERSION = 14
# RETURNING, UPDATE FROM, row values, upserts and json_each.
MIN_SQLITE_VERSION = (3, 35, 0)

type SchemaState = Literal["created", "current", "rebuilt"]

BUSY_TIMEOUT_MS = 10_000
_CACHE_KIB = 32_768
_READER_CACHE_KIB = 4_096
_MMAP_BYTES = 256 * 1024 * 1024

_TABLES = """
CREATE TABLE index_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE stores (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    roots TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('unknown', 'available', 'unavailable')),
    status_at TEXT,
    detail TEXT,
    indexed_at TEXT
);

CREATE TABLE segments (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    producer TEXT NOT NULL,
    segment TEXT NOT NULL,
    product TEXT,
    country TEXT,
    dataset_key TEXT,
    name TEXT NOT NULL,
    known INTEGER NOT NULL DEFAULT 1,
    UNIQUE (store_id, producer, segment)
);

CREATE TABLE slots (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    -- The producer's own name of the slot (opaque to the index); NULL where the
    -- slot is the standard path.
    slot_key TEXT,
    unit TEXT,
    product TEXT,
    country TEXT,
    status TEXT NOT NULL DEFAULT 'missing'
        CHECK (status IN ('ok', 'missing', 'no_sidecar', 'unreadable')),
    current_path TEXT,
    current_version_id INTEGER REFERENCES versions(id) ON DELETE SET NULL,
    full_sheet_path TEXT,
    full_sheet_version_id INTEGER REFERENCES versions(id) ON DELETE SET NULL,
    UNIQUE (store_id, path)
);
CREATE INDEX slots_order ON slots (name, path, store_id);
CREATE INDEX slots_segment ON slots (segment_id);
CREATE INDEX slots_unit ON slots (unit);
CREATE INDEX slots_product ON slots (product, country);
CREATE INDEX slots_current ON slots (current_version_id);
CREATE INDEX slots_full_sheet ON slots (full_sheet_version_id)
    WHERE full_sheet_version_id IS NOT NULL;

CREATE TABLE versions (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    slot_id INTEGER NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    has_meta INTEGER NOT NULL DEFAULT 0,
    digest INTEGER,
    label TEXT,
    label_source TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    data_year INTEGER,
    data_date TEXT,
    downloaded_at TEXT,
    dataset TEXT,
    dataset_key TEXT,
    provider TEXT,
    product TEXT,
    country TEXT,
    unit TEXT,
    campaign TEXT,
    survey_work_id TEXT,
    edition TEXT,
    full_sheet INTEGER,
    coverage REAL,
    parent_request TEXT,
    license TEXT,
    attribution TEXT,
    source_files TEXT,
    horizontal_crs TEXT,
    vertical_crs TEXT,
    resolution TEXT,
    nodata REAL,
    location TEXT NOT NULL DEFAULT 'none'
        CHECK (location IN ('footprint', 'country', 'none')),
    location_reason TEXT DEFAULT 'pending',
    location_source TEXT,
    native_crs TEXT,
    min_lon REAL,
    min_lat REAL,
    max_lon REAL,
    max_lat REAL,
    is_box INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'present' CHECK (state IN ('present', 'missing')),
    missing_since TEXT,
    indexed_at TEXT NOT NULL,
    UNIQUE (store_id, path)
);
CREATE INDEX versions_slot ON versions (slot_id, path);
CREATE INDEX versions_segment ON versions (segment_id);
CREATE INDEX versions_year ON versions (data_year);
-- SHA-256 prefix search; also covers disk usage (each content once).
CREATE INDEX versions_sha256
    ON versions (sha256, store_id, state, segment_id, size_bytes);
CREATE INDEX versions_group ON versions (parent_request)
    WHERE parent_request IS NOT NULL;
CREATE INDEX versions_missing ON versions (store_id) WHERE state = 'missing';
CREATE INDEX versions_unlocated ON versions (store_id) WHERE location = 'none';

-- The publication history of a slot: a source served other bytes with the
-- content of the version ``version_path``, so the producer wrote no version.
-- Never a version: no count, no current version and no usage follows from it.
CREATE TABLE observations (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    slot_id INTEGER NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    version_path TEXT,
    seen_at TEXT NOT NULL,
    url TEXT,
    etag TEXT,
    last_modified TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    UNIQUE (store_id, path)
);
CREATE INDEX observations_slot ON observations (slot_id, seen_at);
CREATE INDEX observations_segment ON observations (segment_id);

CREATE TABLE version_sidecars (
    version_id INTEGER PRIMARY KEY REFERENCES versions(id) ON DELETE CASCADE,
    raw TEXT NOT NULL
);

CREATE TABLE version_shapes (
    version_id INTEGER PRIMARY KEY REFERENCES versions(id) ON DELETE CASCADE,
    wgs84 TEXT,
    native TEXT
);

CREATE VIRTUAL TABLE footprints USING rtree (
    id, min_lon, max_lon, min_lat, max_lat
);

CREATE VIRTUAL TABLE search USING fts5 (
    unit, name, segment, labels, tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE issues (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    slot_id INTEGER REFERENCES slots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    code TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'scan' CHECK (origin IN ('scan', 'check')),
    first_seen_at TEXT NOT NULL,
    UNIQUE (store_id, path, code)
);
CREATE INDEX issues_segment ON issues (segment_id);
CREATE INDEX issues_slot ON issues (slot_id);

-- A project is its directory: one key whatever manifests it holds.
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,
    -- Key of the project's access entry in the state database (realpath).
    access_key TEXT NOT NULL,
    name TEXT NOT NULL
);
CREATE INDEX projects_access ON projects (access_key);

-- One producer's manifest in a project directory, as it was last read.
CREATE TABLE manifests (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    producer TEXT NOT NULL,
    store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    store_dir TEXT NOT NULL,
    status TEXT,
    problem TEXT,
    manifest_mtime_ns INTEGER,
    manifest_size INTEGER,
    scanned_at TEXT NOT NULL,
    PRIMARY KEY (project_id, producer)
) WITHOUT ROWID;
CREATE INDEX manifests_store ON manifests (store_id);

CREATE TABLE project_tasks (
    project_id INTEGER NOT NULL,
    producer TEXT NOT NULL,
    task_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    command TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '{}',
    status TEXT,
    PRIMARY KEY (project_id, producer, task_id),
    FOREIGN KEY (project_id, producer)
        REFERENCES manifests (project_id, producer) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE pins (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    producer TEXT NOT NULL,
    task_id TEXT,
    store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    store_dir TEXT NOT NULL,
    version_path TEXT NOT NULL,
    sha256 TEXT,
    FOREIGN KEY (project_id, producer)
        REFERENCES manifests (project_id, producer) ON DELETE CASCADE
);
CREATE INDEX pins_version ON pins (store_id, version_path);
CREATE INDEX pins_project ON pins (project_id, producer);

CREATE TABLE areas (
    id TEXT PRIMARY KEY,
    name TEXT,
    source TEXT NOT NULL,
    geometry TEXT NOT NULL,
    area_km2 REAL,
    countries TEXT NOT NULL DEFAULT '[]',
    min_lon REAL NOT NULL,
    min_lat REAL NOT NULL,
    max_lon REAL NOT NULL,
    max_lat REAL NOT NULL,
    created_at TEXT NOT NULL
);

-- The last report of each area, producer and product; the job is kept by id
-- only, as jobs are pruned.
CREATE TABLE availability (
    area_id TEXT NOT NULL REFERENCES areas(id) ON DELETE CASCADE,
    producer TEXT NOT NULL,
    product TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    report TEXT NOT NULL,
    job_id TEXT,
    PRIMARY KEY (area_id, producer, product)
) WITHOUT ROWID;

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK (
        actor_kind IN ('local_owner', 'user', 'agent', 'scheduler')
    ),
    session TEXT,
    store TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL CHECK (
        state IN (
            'queued', 'running', 'succeeded', 'partial', 'failed', 'interrupted',
            'cancelled'
        )
    ),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    pid INTEGER,
    summary TEXT,
    error TEXT
);
CREATE INDEX jobs_store ON jobs (store, kind, created_at);
CREATE INDEX jobs_state ON jobs (state);
-- GET /jobs pages newest first.
CREATE INDEX jobs_created ON jobs (created_at, id);

CREATE TABLE job_events (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    at TEXT NOT NULL,
    PRIMARY KEY (job_id, seq)
) WITHOUT ROWID;

-- The plan of each call of a ``check`` job: what a run of the call would do in a
-- store (``call`` is its place in the job's ``calls``).
CREATE TABLE plans (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    call INTEGER NOT NULL,
    store TEXT NOT NULL,
    line TEXT NOT NULL,
    plan TEXT NOT NULL,
    PRIMARY KEY (job_id, call)
) WITHOUT ROWID;

-- The positions to download a running ``download`` with a plan fetches (ADR-047):
-- one claimant per store and path, so another download of the store leaves
-- the position out. Claims end with their job.
CREATE TABLE job_claims (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    store TEXT NOT NULL,
    path TEXT NOT NULL,
    unit TEXT NOT NULL,
    PRIMARY KEY (store, path)
) WITHOUT ROWID;
CREATE INDEX job_claims_job ON job_claims (job_id);

-- The catalog version each provider's stations were read from (SPEC 4.4): the
-- rows are replaced when the current version of the catalog's slot changes.
CREATE TABLE station_catalogs (
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    producer TEXT NOT NULL,
    slot_path TEXT NOT NULL,
    version_path TEXT NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (store_id, provider)
) WITHOUT ROWID;

-- The stations of the current catalog of each provider (SPEC 4.3, 4.8.1). A
-- code is text and belongs to its provider; a station without a point keeps
-- the catalog's reason (P13, A-ADR-022).
CREATE TABLE stations (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    code TEXT NOT NULL,
    kind TEXT,
    meteo_kind TEXT,
    name TEXT,
    river TEXT,
    hydrographic_code TEXT,
    river_order INTEGER,
    location TEXT NOT NULL CHECK (location IN ('point', 'none')),
    location_reason TEXT,
    location_source TEXT,
    location_uncertainty_m REAL,
    lon REAL,
    lat REAL,
    active INTEGER,
    established_year INTEGER,
    gauge_zero_m REAL,
    river_km REAL,
    elevation_m REAL,
    UNIQUE (store_id, provider, code)
);
CREATE INDEX stations_code ON stations (code);
-- "The river with its tributaries" (P19) is a prefix of the code: a range scan.
CREATE INDEX stations_hydrographic ON stations (hydrographic_code);
CREATE INDEX stations_unlocated ON stations (store_id) WHERE location = 'none';

CREATE VIRTUAL TABLE station_points USING rtree (
    id, min_lon, max_lon, min_lat, max_lat
);

-- The series version each dataset's coverage was read from (SPEC 4.4, 4.8.4),
-- with what the labels need of it: the unit, the numbering of its archives,
-- the first year the source publishes and the known periods (JSON
-- [[from, to], ...], ISO dates). The rows are replaced when the current
-- version of the series' slot changes.
CREATE TABLE series_catalogs (
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    dataset TEXT NOT NULL,
    producer TEXT NOT NULL,
    provider TEXT NOT NULL,
    kind TEXT,
    time_unit TEXT NOT NULL CHECK (time_unit IN ('day', 'month', 'half_year')),
    year_type TEXT NOT NULL CHECK (year_type IN ('hydrological', 'calendar')),
    first_year INTEGER,
    periods TEXT NOT NULL,
    slot_path TEXT NOT NULL,
    version_path TEXT NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (store_id, dataset)
) WITHOUT ROWID;

-- A variable of a station's series in the current version of a dataset's
-- series (IMGW-8): ``variable_key`` names it in the series index (``Q``,
-- ``Q_max@winter``); the first and last date with a value, the gaps between
-- them and the station's own known periods (JSON, NULL: the version's) as the
-- index gives them, and the station's series file relative to the store.
CREATE TABLE station_series (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    dataset TEXT NOT NULL,
    provider TEXT NOT NULL,
    code TEXT NOT NULL,
    variable_key TEXT NOT NULL,
    variable TEXT NOT NULL,
    unit TEXT NOT NULL,
    period TEXT,
    first_date TEXT,
    last_date TEXT,
    with_value INTEGER NOT NULL,
    accumulated INTEGER NOT NULL,
    gaps TEXT NOT NULL,
    periods TEXT,
    file TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    UNIQUE (store_id, dataset, code, variable_key)
);
CREATE INDEX station_series_station ON station_series (provider, code);

-- Each year of a variable in both year types (one for half-year
-- characteristics): its units, the known ones and those with a value, from the
-- first year with a known unit to the last (SPEC 4.8.4).
CREATE TABLE series_years (
    series_id INTEGER NOT NULL REFERENCES station_series(id) ON DELETE CASCADE,
    year_type TEXT NOT NULL CHECK (year_type IN ('hydrological', 'calendar')),
    year INTEGER NOT NULL,
    units INTEGER NOT NULL,
    known INTEGER NOT NULL,
    with_value INTEGER NOT NULL,
    PRIMARY KEY (series_id, year_type, year)
) WITHOUT ROWID;

-- One-time session tokens (SHA-256 only) with who minted each (JSON: id and
-- kind; roles and groups are read for every request) and the label of the
-- session each opens; ``index_info`` holds the agent-session generation.
CREATE TABLE session_tokens (
    hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('startup', 'agent')),
    principal TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
) WITHOUT ROWID;

CREATE TABLE own_folders (
    id INTEGER PRIMARY KEY,
    -- The project directory after realpath (projects.access_key).
    project TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('default', 'setting')),
    state TEXT NOT NULL CHECK (state IN ('ok', 'missing', 'unreadable', 'invalid')),
    reason TEXT,
    scanned_at TEXT NOT NULL,
    files INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    snapshots INTEGER NOT NULL DEFAULT 0,
    snapshots_bytes INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE own_files (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL REFERENCES own_folders(id) ON DELETE CASCADE,
    -- Relative to the folder, '/' separated, NFC; disk_path as named on disk.
    path TEXT NOT NULL,
    file_id TEXT NOT NULL,
    disk_path TEXT NOT NULL,
    -- Sizes and times of the file's files when it was read (JSON).
    stamp TEXT NOT NULL,
    kind TEXT NOT NULL,
    driver TEXT,
    members TEXT NOT NULL DEFAULT '[]',
    size_bytes INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    read_state TEXT NOT NULL
        CHECK (read_state IN ('ok', 'unrecognized', 'unreadable')),
    read_error TEXT,
    read_detail TEXT,
    retry INTEGER NOT NULL DEFAULT 0,
    content_method TEXT,
    content_sha256 TEXT,
    layers TEXT NOT NULL DEFAULT '[]',
    raster TEXT,
    feature_count INTEGER,
    native_crs TEXT,
    native_bbox TEXT,
    wgs84 TEXT,
    location_reason TEXT,
    change TEXT NOT NULL DEFAULT 'unsnapshotted'
        CHECK (change IN ('unsnapshotted', 'unchanged', 'changed')),
    last_snapshot TEXT,
    first_seen_at TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    missing_since TEXT,
    UNIQUE (folder_id, path)
);
CREATE UNIQUE INDEX own_files_id ON own_files (folder_id, file_id);

CREATE TABLE own_file_states (
    own_file_id INTEGER NOT NULL REFERENCES own_files(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    content_sha256 TEXT,
    feature_count INTEGER,
    PRIMARY KEY (own_file_id, seq)
) WITHOUT ROWID;

CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL REFERENCES own_folders(id) ON DELETE CASCADE,
    -- The working file it copies (own_files.path; the file may be gone).
    path TEXT NOT NULL,
    file_id TEXT NOT NULL,
    label TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ok', 'invalid', 'modified')),
    created_at TEXT,
    content_method TEXT,
    content_sha256 TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    stamp TEXT NOT NULL,
    document TEXT,
    UNIQUE (folder_id, path, label)
);
CREATE INDEX snapshots_file ON snapshots (folder_id, file_id, created_at);

-- Problems of a folder ('' path), its files and snapshots.
CREATE TABLE own_problems (
    folder_id INTEGER NOT NULL REFERENCES own_folders(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    reason TEXT,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (folder_id, code, path)
) WITHOUT ROWID;

CREATE TRIGGER versions_footprint_delete AFTER DELETE ON versions BEGIN
    DELETE FROM footprints WHERE id = OLD.id;
END;

CREATE TRIGGER slots_search_delete AFTER DELETE ON slots BEGIN
    DELETE FROM search WHERE rowid = OLD.id;
END;

CREATE TRIGGER stations_point_delete AFTER DELETE ON stations BEGIN
    DELETE FROM station_points WHERE id = OLD.id;
END;
"""


class IndexUnsupportedError(ArchiwistaError, RuntimeError):
    """The Python SQLite library lacks a feature the index needs.

    A ``store_unavailable`` (reason ``index_unsupported``).
    """

    default_code = "store_unavailable"
    default_reason = "index_unsupported"


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open the index with Archiwista's connection settings.

    Parameters
    ----------
    path : Path
        The index file; ``initialize`` must have created it.
    readonly : bool, default False
        Refuse changes to the index (``query_only``); used by queries. A
        reader keeps a small private page cache and maps nothing: a server
        holds one reader per thread, and each memory map would count the
        same index pages again in its resident memory (SPEC 4.5: ≤ 500 MB);
        pages come from the operating system's file cache instead.

    Returns
    -------
    sqlite3.Connection
        In autocommit mode (``isolation_level=None``): callers open their
        transactions explicitly. It may be passed between threads but must
        be used by one thread at a time. The SQL function ``casefold(text)``
        folds the case of a text as Python does (SQLite's ``lower`` folds
        ASCII letters only); station searches compare names with it.
    """
    connection = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    cache_kib = _READER_CACHE_KIB if readonly else _CACHE_KIB
    connection.execute(f"PRAGMA cache_size = -{cache_kib}")
    connection.execute(f"PRAGMA mmap_size = {0 if readonly else _MMAP_BYTES}")
    connection.create_function("casefold", 1, _casefold, deterministic=True)
    if readonly:
        connection.execute("PRAGMA query_only = ON")
    return connection


def _casefold(text: str | None) -> str | None:
    """Return the case-folded text (``NULL`` stays ``NULL``): ``casefold`` of SQL."""
    return None if text is None else text.casefold()


def initialize(path: Path) -> SchemaState:
    """Create the index, keep a current one, or rebuild one of another version.

    Parameters
    ----------
    path : Path
        Index file; its directory is created when missing, and on POSIX
        closed to other accounts (``0700``, ``private_directory``).

    Returns
    -------
    SchemaState
        ``created`` for a new file, ``current`` when the schema already
        matches ``SCHEMA_VERSION``, ``rebuilt`` when an index of another
        version (older or newer) was emptied and recreated. A rebuilt index
        is empty: the next full scan fills it again.

    Raises
    ------
    IndexUnsupportedError
        SQLite older than ``MIN_SQLITE_VERSION`` or built without FTS5,
        R*Tree or JSON functions.
    """
    _require_sqlite_features()
    private_directory(path.parent)
    connection = connect(path)
    try:
        use_wal(connection, timeout_ms=BUSY_TIMEOUT_MS)
        if _user_version(connection) == SCHEMA_VERSION:
            return "current"
        # Dropping tables with foreign keys enabled runs checked deletes; a
        # rebuild removes everything anyway.
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            version = _user_version(connection)
            if version == SCHEMA_VERSION:
                connection.execute("COMMIT")
                return "current"
            existing = _drop_all(connection)
            _create(connection, rebuilt_from=version if existing else None)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        if existing:
            # The rebuilt index is empty: give the dropped pages back.
            connection.execute("VACUUM")
        return "rebuilt" if existing else "created"
    finally:
        connection.close()


def _require_sqlite_features() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        minimum = ".".join(str(part) for part in MIN_SQLITE_VERSION)
        raise IndexUnsupportedError(
            f"SQLite {sqlite3.sqlite_version} is older than {minimum}"
        )
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE f USING fts5 (a)")
        probe.execute("CREATE VIRTUAL TABLE r USING rtree (id, x0, x1, y0, y1)")
        probe.execute("SELECT value FROM json_each('[1]')")
    except sqlite3.OperationalError as error:
        raise IndexUnsupportedError(f"SQLite lacks a feature: {error}") from error
    finally:
        probe.close()


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _drop_all(connection: sqlite3.Connection) -> bool:
    """Drop every schema object; return whether there was any."""
    objects = connection.execute(
        "SELECT type, name, sql FROM sqlite_schema"
        " WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    # A virtual table drops its own shadow tables, so it goes first.
    for kind, name, sql in objects:
        if kind == "table" and str(sql or "").upper().startswith("CREATE VIRTUAL"):
            connection.execute(f'DROP TABLE IF EXISTS "{name}"')
    for kind, name in connection.execute(
        "SELECT type, name FROM sqlite_schema"
        " WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
    ).fetchall():
        connection.execute(f'DROP {str(kind).upper()} IF EXISTS "{name}"')
    # Planner statistics of the old schema would mislead the new one.
    stats = connection.execute(
        "SELECT name FROM sqlite_schema WHERE name = 'sqlite_stat1'"
    ).fetchone()
    if stats is not None:
        connection.execute("DELETE FROM sqlite_stat1")
    return bool(objects)


def _create(connection: sqlite3.Connection, *, rebuilt_from: int | None) -> None:
    for statement in _statements(_TABLES):
        connection.execute(statement)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    info = [("created_at", now)]
    if rebuilt_from is not None:
        info.append(("rebuilt_from", str(rebuilt_from)))
    connection.executemany("INSERT INTO index_info (key, value) VALUES (?, ?)", info)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _statements(script: str) -> list[str]:
    """Split the DDL script into statements (triggers contain semicolons)."""
    statements: list[str] = []
    current: list[str] = []
    for line in script.strip().splitlines():
        current.append(line)
        text = "\n".join(current).strip()
        if text and sqlite3.complete_statement(text):
            statements.append(text)
            current = []
    return statements
