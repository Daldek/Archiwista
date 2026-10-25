"""Write producer entries, footprints, projects, areas and reports to the index.

One ``IndexWriter`` owns one connection and is used by one thread at a time
(the scanner's write thread, a background job, or the server's view
refresh); writers in other processes or threads use their own instances.

A scan pass (``begin_pass`` … ``finish_pass``) loads what the index knows of
its scope once, so an unchanged entry costs a dictionary lookup and no SQL:
an incremental scan of an unchanged store writes nothing. Each
``write_entries`` batch is one transaction that leaves the index consistent
(current versions, slot states and search rows of the touched slots), so
readers never wait for a pass to end. Only ``finish_pass`` acts on what the
pass has *not* seen; abandoning a pass (e.g. the store became unavailable)
changes nothing else. A producer without links names the current version of
its slots itself: ``finish_pass`` asks it for the slots the pass touched.
"""

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self

from archiwista.auth import access_key
from archiwista.config import OwnFolderReason, OwnFolderSource
from archiwista.index.geometry import is_box, polygon_bounds
from archiwista.index.schema import connect, initialize
from archiwista.index.types import (
    MAX_OWN_FILE_STATES,
    AreaRecord,
    BatchResult,
    CurrentVersionLookup,
    KnownOwnFile,
    ManifestStamp,
    OwnFilesWritten,
    OwnFileWrite,
    OwnFolderState,
    OwnMissingResult,
    OwnProblem,
    PassSummary,
    ScanPass,
    SnapshotWrite,
    StoredPlan,
    StoreStatus,
    own_file_id,
)
from archiwista.messages import STORED_LANG, localize
from archiwista.sources import (
    AvailabilityReport,
    EntryMeta,
    Footprint,
    ProjectInfo,
    SourceEntry,
    SourceObservation,
    SourceSegment,
)

# Columns of a version's metadata, in the order of ``_meta_row``.
_META_COLUMNS = (
    "label",
    "label_source",
    "sha256",
    "size_bytes",
    "data_year",
    "data_date",
    "downloaded_at",
    "dataset",
    "dataset_key",
    "provider",
    "product",
    "country",
    "unit",
    "campaign",
    "survey_work_id",
    "edition",
    "full_sheet",
    "coverage",
    "parent_request",
    "license",
    "attribution",
    "source_files",
    "horizontal_crs",
    "vertical_crs",
    "resolution",
    "nodata",
)
_META_PLACEHOLDERS = ", ".join("?" for _ in _META_COLUMNS)
_META_UPDATES = ", ".join(f"{column} = excluded.{column}" for column in _META_COLUMNS)

_UPSERT_SLOT = """
INSERT INTO slots (store_id, segment_id, path, name, slot_key, unit, product, country)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (store_id, path) DO UPDATE SET
    slot_key = coalesce(excluded.slot_key, slot_key),
    unit = coalesce(excluded.unit, unit),
    product = coalesce(excluded.product, product),
    country = coalesce(excluded.country, country)
"""
_UPSERT_VERSION = f"""
INSERT INTO versions (
    store_id, segment_id, slot_id, path, has_meta, digest,
    {", ".join(_META_COLUMNS)}, indexed_at
)
VALUES (?, ?, ?, ?, 1, ?, {_META_PLACEHOLDERS}, ?)
ON CONFLICT (store_id, path) DO UPDATE SET
    has_meta = 1, digest = excluded.digest, {_META_UPDATES},
    state = 'present', missing_since = NULL
"""
_INSERT_BARE_VERSION = """
INSERT INTO versions (store_id, segment_id, slot_id, path, indexed_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (store_id, path) DO UPDATE SET state = 'present', missing_since = NULL
"""
_UPSERT_SIDECAR = """
INSERT INTO version_sidecars (version_id, raw) VALUES (?, ?)
ON CONFLICT (version_id) DO UPDATE SET raw = excluded.raw
"""
_INSERT_ISSUE = """
INSERT INTO issues (store_id, segment_id, slot_id, path, code, origin, first_seen_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (store_id, path, code) DO NOTHING
"""
_INSERT_OBSERVATION = """
INSERT INTO observations (
    store_id, segment_id, slot_id, path, version_path, seen_at, url, etag,
    last_modified, size_bytes, sha256
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (store_id, path) DO NOTHING
"""
_UPDATE_LOCATION = """
UPDATE versions SET
    location = ?, location_reason = ?, location_source = ?, native_crs = ?,
    min_lon = ?, min_lat = ?, max_lon = ?, max_lat = ?, is_box = ?
WHERE id = ?
"""
_UPSERT_SHAPE = """
INSERT INTO version_shapes (version_id, wgs84, native) VALUES (?, ?, ?)
ON CONFLICT (version_id) DO UPDATE SET wgs84 = excluded.wgs84, native = excluded.native
"""
_IDS = "SELECT value FROM json_each(?)"


def _fold(expression: str) -> str:
    """Fold ``ł`` in SQL as FTS5 folds other diacritics (``Łódź`` ~ lodz)."""
    return f"replace(replace({expression}, 'ł', 'l'), 'Ł', 'L')"


# One search row per slot: unit, file name, segment words and every version's
# label, survey work number, campaign and edition.
_INSERT_SEARCH = f"""
INSERT INTO search (rowid, unit, name, segment, labels)
SELECT
    s.id,
    coalesce(s.unit, ''),
    {_fold("s.name")},
    {
    _fold(
        "g.segment || ' ' || coalesce(s.product, '') || ' '"
        " || coalesce(g.dataset_key, '') || ' ' || g.name"
    )
},
    {
    _fold(
        "coalesce((SELECT group_concat(coalesce(v.label, '') || ' '"
        " || coalesce(v.survey_work_id, '') || ' ' || coalesce(v.campaign, '')"
        " || ' ' || coalesce(v.edition, ''), ' ')"
        " FROM versions v WHERE v.slot_id = s.id), '')"
    )
}
FROM slots s JOIN segments g ON g.id = s.segment_id
WHERE s.id IN ({_IDS})
"""
_RESOLVE_LINKS = f"""
UPDATE slots SET
    current_version_id = (
        SELECT v.id FROM versions v
        WHERE v.store_id = slots.store_id AND v.path = slots.current_path
    ),
    full_sheet_version_id = (
        SELECT v.id FROM versions v
        WHERE v.store_id = slots.store_id AND v.path = slots.full_sheet_path
    )
WHERE id IN ({_IDS})
"""
# A slot without a current version is ``no_sidecar`` while a version of it is an
# interrupted publication, ``unreadable`` while one of its files cannot be read
# (the codes of both producers; ``size_mismatch`` leaves it ``missing``).
_SLOT_STATUS = f"""
UPDATE slots SET status = CASE
    WHEN current_version_id IS NOT NULL THEN 'ok'
    WHEN EXISTS (
        SELECT 1 FROM issues i WHERE i.slot_id = slots.id
        AND i.code = 'missing_sidecar'
    ) THEN 'no_sidecar'
    WHEN EXISTS (
        SELECT 1 FROM issues i WHERE i.slot_id = slots.id
        AND i.code IN (
            'invalid_sidecar', 'invalid_json', 'invalid_meta', 'unknown_schema',
            'unreadable'
        )
    ) THEN 'unreadable'
    ELSE 'missing'
END
WHERE id IN ({_IDS})
"""
_DELETE_EMPTY_SLOTS = f"""
DELETE FROM slots
WHERE id IN ({_IDS})
    AND current_path IS NULL AND full_sheet_path IS NULL
    AND NOT EXISTS (SELECT 1 FROM versions v WHERE v.slot_id = slots.id)
    AND NOT EXISTS (SELECT 1 FROM issues i WHERE i.slot_id = slots.id)
"""
_PROJECT_KEY_FALLBACK = "projekt"
_UPSERT_OWN_FILE = """
INSERT INTO own_files (
    folder_id, path, file_id, disk_path, stamp, kind, driver, members, size_bytes,
    modified_ns, read_state, read_error, read_detail, retry, content_method,
    content_sha256, layers, raster, feature_count, native_crs, native_bbox, wgs84,
    location_reason, first_seen_at, changed_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (folder_id, path) DO UPDATE SET
    disk_path = excluded.disk_path, stamp = excluded.stamp, kind = excluded.kind,
    driver = excluded.driver, members = excluded.members,
    size_bytes = excluded.size_bytes, modified_ns = excluded.modified_ns,
    read_state = excluded.read_state, read_error = excluded.read_error,
    read_detail = excluded.read_detail, retry = excluded.retry,
    content_method = excluded.content_method,
    content_sha256 = excluded.content_sha256, layers = excluded.layers,
    raster = excluded.raster, feature_count = excluded.feature_count,
    native_crs = excluded.native_crs, native_bbox = excluded.native_bbox,
    wgs84 = excluded.wgs84, location_reason = excluded.location_reason,
    changed_at = excluded.changed_at, missing_since = NULL
RETURNING id
"""
_UPSERT_SNAPSHOT = """
INSERT INTO snapshots (
    folder_id, path, file_id, label, state, created_at, content_method,
    content_sha256, size_bytes, stamp, document
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (folder_id, path, label) DO UPDATE SET
    state = excluded.state, created_at = excluded.created_at,
    content_method = excluded.content_method,
    content_sha256 = excluded.content_sha256, size_bytes = excluded.size_bytes,
    stamp = excluded.stamp, document = excluded.document
"""
# A file's change is measured against its newest valid snapshot.
_OWN_LAST_SNAPSHOT = """
UPDATE own_files SET last_snapshot = (
    SELECT s.label FROM snapshots s
    WHERE s.folder_id = own_files.folder_id AND s.path = own_files.path
        AND s.state = 'ok' AND s.created_at IS NOT NULL
    ORDER BY s.created_at DESC, s.label DESC LIMIT 1
)
WHERE folder_id = ?
"""
_OWN_CHANGE = """
UPDATE own_files SET change = CASE
    WHEN last_snapshot IS NULL THEN 'unsnapshotted'
    WHEN content_sha256 IS NOT NULL AND EXISTS (
        SELECT 1 FROM snapshots s
        WHERE s.folder_id = own_files.folder_id AND s.path = own_files.path
            AND s.label = own_files.last_snapshot
            AND s.content_method = own_files.content_method
            AND s.content_sha256 = own_files.content_sha256
    ) THEN 'unchanged'
    ELSE 'changed'
END
WHERE folder_id = ?
"""
_OWN_TOTALS = """
UPDATE own_folders SET
    scanned_at = ?,
    files = (
        SELECT count(*) FROM own_files f
        WHERE f.folder_id = own_folders.id AND f.missing_since IS NULL
    ),
    size_bytes = (
        SELECT coalesce(sum(f.size_bytes), 0) FROM own_files f
        WHERE f.folder_id = own_folders.id AND f.missing_since IS NULL
    ),
    snapshots = (SELECT count(*) FROM snapshots s WHERE s.folder_id = own_folders.id),
    snapshots_bytes = (
        SELECT coalesce(sum(s.size_bytes), 0) FROM snapshots s
        WHERE s.folder_id = own_folders.id
    )
WHERE id = ?
"""


@dataclass(slots=True)
class _Segment:
    id: int
    product: str | None
    country: str | None


@dataclass(slots=True)
class _KnownVersion:
    id: int
    slot_id: int
    segment_id: int
    state: str
    digest: int | None
    location: str
    reason: str | None


@dataclass(slots=True)
class _KnownSlot:
    id: int
    current_path: str | None
    full_sheet_path: str | None
    unit: str | None
    product: str | None
    country: str | None
    key: str | None


@dataclass(slots=True)
class _PassState:
    info: ScanPass
    store_id: int
    segments: dict[str, _Segment]
    versions: dict[str, _KnownVersion]
    slots: dict[str, _KnownSlot]
    issues: dict[tuple[str, str], tuple[int, int | None]]
    seen_versions: set[str] = field(default_factory=set)
    seen_links: set[str] = field(default_factory=set)
    seen_full_sheets: set[str] = field(default_factory=set)
    seen_issues: set[tuple[str, str]] = field(default_factory=set)
    reappeared: int = 0
    # Observations of the scope the index holds, and those the pass has seen.
    observations: set[str] = field(default_factory=set)
    seen_observations: set[str] = field(default_factory=set)
    # Slots (ids) whose versions, links or problems the pass wrote or brought
    # back: the ones a producer is asked the current version of at the end.
    touched: set[int] = field(default_factory=set)
    # Settled version directories by segment id (``known_versions``), taken
    # once per pass before anything is written.
    settled: dict[int, dict[str, tuple[str, ...]]] | None = None


@dataclass(slots=True)
class _SlotWrite:
    segment: str
    unit: str | None
    product: str | None
    country: str | None
    key: str | None
    name: str | None


@dataclass(slots=True)
class _VersionWrite:
    slot: str
    segment: str
    digest: int | None
    row: tuple[object, ...] | None
    raw: str | None


@dataclass(slots=True)
class _ObservationWrite:
    slot: str
    segment: str
    version_path: str | None
    record: SourceObservation


@dataclass(slots=True)
class _Batch:
    slots: dict[str, _SlotWrite] = field(default_factory=dict)
    versions: dict[str, _VersionWrite] = field(default_factory=dict)
    observations: dict[str, _ObservationWrite] = field(default_factory=dict)
    reappeared: set[str] = field(default_factory=set)
    links: dict[str, str | None] = field(default_factory=dict)
    full_sheets: dict[str, str | None] = field(default_factory=dict)
    issues: dict[tuple[str, str], tuple[str | None, str]] = field(default_factory=dict)
    needs_footprint: list[SourceEntry] = field(default_factory=list)

    def empty(self) -> bool:
        return not (
            self.slots
            or self.versions
            or self.observations
            or self.reappeared
            or self.links
            or self.full_sheets
            or self.issues
        )


class IndexWriter:
    """Write the local index from producer entries and project manifests.

    Parameters
    ----------
    path : Path
        The index file; it is created (or rebuilt after a schema change)
        when needed.

    Notes
    -----
    Stores must be known (``sync_stores``) before anything is written for
    them. A pass belongs to one writer; one writer runs one pass at a time.
    """

    def __init__(self, path: Path) -> None:
        initialize(path)
        self._connection = connect(path)
        self._connection.execute("PRAGMA analysis_limit = 1000")
        # Batches commit often: checkpoint every ~32 MB of WAL, not every 4 MB.
        self._connection.execute("PRAGMA wal_autocheckpoint = 8192")
        self._pass: _PassState | None = None

    def close(self) -> None:
        """Close the connection; an unfinished pass is abandoned."""
        self._pass = None
        self._connection.close()

    def __enter__(self) -> Self:
        """Use the writer as a context manager that closes it."""
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the writer."""
        self.close()

    # Stores and segments.

    def sync_stores(self, stores: Mapping[str, Mapping[str, str | Path]]) -> None:
        """Make the index's stores those of the configuration.

        Parameters
        ----------
        stores : Mapping[str, Mapping[str, str | Path]]
            Configured store id → producer → producer directory
            (``StoreConfig.roots()``). Stores missing from it are removed
            with everything indexed for them.
        """
        with self._transaction() as connection:
            existing = {
                str(key)
                for (key,) in connection.execute("SELECT key FROM stores").fetchall()
            }
            connection.executemany(
                "INSERT INTO stores (key, roots) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET roots = excluded.roots",
                [
                    (key, json.dumps({p: str(r) for p, r in sorted(roots.items())}))
                    for key, roots in stores.items()
                ],
            )
            removed = sorted(existing - set(stores))
            connection.execute(
                f"DELETE FROM stores WHERE key IN ({_IDS})", (json.dumps(removed),)
            )

    def set_store_status(
        self, store: str, status: StoreStatus, *, detail: str | None = None
    ) -> None:
        """Record whether a store is reachable, with the time of the finding.

        Parameters
        ----------
        store : str
            Configured store id.
        status : {"unknown", "available", "unavailable"}
            ``unavailable`` keeps every indexed row: answers come from the
            index, marked stale.
        detail : str or None, optional
            Description of the cause, shown with the status; a catalog message
            is written in the language of the stored texts.
        """
        with self._transaction() as connection:
            connection.execute(
                "UPDATE stores SET status = ?, status_at = ?, detail = ? WHERE id = ?",
                (
                    status,
                    _now(),
                    None if detail is None else localize(detail, STORED_LANG),
                    self._store_id(store),
                ),
            )

    def write_segments(
        self, store: str, producer: str, segments: Iterable[SourceSegment]
    ) -> None:
        """Record the producer's description of a store's segments.

        A changed product or country is carried to the segment's slots, and
        a changed name to their search rows.

        Parameters
        ----------
        store : str
            Configured store id.
        producer : str
            The adapter's producer.
        segments : Iterable[SourceSegment]
            ``SegmentedAdapter.describe_segment`` of listed segments.
        """
        store_id = self._store_id(store)
        with self._transaction() as connection:
            before = {
                str(segment): (product, country, name)
                for segment, product, country, name in connection.execute(
                    "SELECT segment, product, country, name FROM segments"
                    " WHERE store_id = ? AND producer = ?",
                    (store_id, producer),
                ).fetchall()
            }
            changed: list[str] = []
            for item in segments:
                connection.execute(
                    "INSERT INTO segments"
                    " (store_id, producer, segment, product, country, dataset_key,"
                    " name, known) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (store_id, producer, segment) DO UPDATE SET"
                    " product = excluded.product, country = excluded.country,"
                    " dataset_key = excluded.dataset_key, name = excluded.name,"
                    " known = excluded.known",
                    (
                        store_id,
                        producer,
                        item.segment,
                        item.product,
                        item.country,
                        item.dataset_key,
                        item.name,
                        int(item.known),
                    ),
                )
                old = before.get(item.segment)
                if old is not None and old != (item.product, item.country, item.name):
                    changed.append(item.segment)
            if changed:
                self._carry_segments(connection, store_id, producer, changed)
        if self._pass is not None and self._pass.store_id == store_id:
            self._pass.segments = self._load_segments(
                store_id, self._pass.info.producer
            )

    # Scan passes.

    def begin_pass(
        self,
        store: str,
        producer: str,
        *,
        segment: str | None = None,
        slots: Collection[str] | None = None,
        full: bool = False,
    ) -> ScanPass:
        """Start a pass and load what the index knows of its scope.

        Parameters
        ----------
        store : str
            Configured store id (``sync_stores``).
        producer : str
            Producer whose entries the pass writes.
        segment : str or None, optional
            Limit the pass to one segment.
        slots : Collection[str] or None, optional
            Limit the pass to these slot paths (a view refresh); slots the
            pass discovers join its scope. Such a pass is never ``full``.
        full : bool, default False
            A full pass re-reads every version: versions it does not see that
            an earlier pass already marked missing are removed.

        Returns
        -------
        ScanPass
            The scope of the pass.

        Raises
        ------
        RuntimeError
            Another pass of this writer is active.
        ValueError
            The store is not in the index.
        """
        if self._pass is not None:
            raise RuntimeError("a scan pass is already active on this writer")
        store_id = self._store_id(store)
        scoped = None if slots is None else frozenset(slots)
        info = ScanPass(
            store=store,
            producer=producer,
            segment=segment,
            slots=scoped,
            full=full and scoped is None,
            started_at=datetime.now(UTC),
        )
        segments = self._load_segments(store_id, producer)
        segment_ids = [
            item.id
            for name, item in segments.items()
            if segment is None or name == segment
        ]
        where = f"s.store_id = ? AND s.segment_id IN ({_IDS})"
        params: list[object] = [store_id, json.dumps(segment_ids)]
        if scoped is not None:
            where += f" AND s.path IN ({_IDS})"
            params.append(json.dumps(sorted(scoped)))
        connection = self._connection
        known_slots = {
            str(path): _KnownSlot(
                int(sid), current, full_sheet, unit, product, country, key
            )
            for path, sid, current, full_sheet, unit, product, country, key in (
                connection.execute(
                    "SELECT s.path, s.id, s.current_path, s.full_sheet_path, s.unit,"
                    f" s.product, s.country, s.slot_key FROM slots s WHERE {where}",
                    params,
                ).fetchall()
            )
        }
        versions = {
            str(path): _KnownVersion(
                int(vid), int(slot_id), int(seg_id), state, digest, location, reason
            )
            for path, vid, slot_id, seg_id, state, digest, location, reason in (
                connection.execute(
                    "SELECT v.path, v.id, v.slot_id, v.segment_id, v.state, v.digest,"
                    " v.location, v.location_reason FROM versions v"
                    f" JOIN slots s ON s.id = v.slot_id WHERE {where}",
                    params,
                ).fetchall()
            )
        }
        issue_where = (
            f"i.store_id = ? AND i.origin = 'scan' AND i.segment_id IN ({_IDS})"
        )
        issue_params: list[object] = [store_id, json.dumps(segment_ids)]
        if scoped is not None:
            issue_where += f" AND i.slot_id IN ({_IDS})"
            ids = [slot.id for slot in known_slots.values()]
            issue_params.append(json.dumps(ids))
        issues = {
            (str(path), str(code)): (int(iid), None if sid is None else int(sid))
            for path, code, iid, sid in connection.execute(
                "SELECT i.path, i.code, i.id, i.slot_id FROM issues i"
                f" WHERE {issue_where}",
                issue_params,
            ).fetchall()
        }
        observations = {
            str(path)
            for (path,) in connection.execute(
                "SELECT o.path FROM observations o JOIN slots s ON s.id = o.slot_id"
                f" WHERE {where}",
                params,
            ).fetchall()
        }
        self._pass = _PassState(
            info,
            store_id,
            segments,
            versions,
            known_slots,
            issues,
            observations=observations,
        )
        return info

    def known_versions(
        self, segment: str | None = None
    ) -> Mapping[str, tuple[str, ...]]:
        """Return the active pass's settled version directories.

        The value of ``ScanScope.known_versions``: each directory (relative
        path with ``/``) maps to the names of its versions. A directory is
        settled when every version the index knows in it is present with
        its metadata read and no problem the index keeps lies in it; a
        version that is its own slot (no version directory) is never named.
        The mapping is computed once per pass, at the first call: take every
        segment's before writing anything.

        Parameters
        ----------
        segment : str or None, optional
            Only the directories of this segment.

        Raises
        ------
        RuntimeError
            No pass is active.
        """
        state = self._active()
        if state.settled is None:
            state.settled = _settled_directories(state)
        if segment is None:
            merged: dict[str, tuple[str, ...]] = {}
            for directories in state.settled.values():
                merged.update(directories)
            return merged
        found = state.segments.get(segment)
        if found is None:
            return {}
        return state.settled.get(found.id, {})

    def holds_entries(self) -> bool:
        """Whether the index holds versions or slots in the active pass's scope.

        Raises
        ------
        RuntimeError
            No pass is active.
        """
        state = self._active()
        return bool(state.versions or state.slots)

    def slots_beside(self, store: str, slots: Collection[str]) -> frozenset[str]:
        """Return the slots and every indexed slot in the same directories.

        A view refresh takes the settled version directories of these
        neighbours too: a producer keeping a directory's versions together
        would otherwise list each neighbour's version directory again.

        Raises
        ------
        ValueError
            The store is not in the index.
        """
        directories = sorted({slot.rpartition("/")[0] for slot in slots})
        rows = self._connection.execute(
            "SELECT s.path FROM json_each(?) d JOIN slots s"
            " ON s.store_id = ? AND s.path > d.value || '/'"
            " AND s.path < d.value || '0'"
            " WHERE instr(substr(s.path, length(d.value) + 2), '/') = 0",
            (json.dumps(directories), self._store_id(store)),
        ).fetchall()
        return frozenset({*slots, *(str(path) for (path,) in rows)})

    def write_entries(self, entries: Iterable[SourceEntry]) -> BatchResult:
        """Write a batch of the active pass's entries in one transaction.

        Parameters
        ----------
        entries : Iterable[SourceEntry]
            Entries of ``SourceAdapter.iter_entries`` for the pass's scope,
            in any order and from any of its segments. Versions bring their
            metadata (``meta``) or come back ``skipped``; a link names its
            version (``version_path``); a plain file at a standard path
            without ``version_path`` is its own version; an observation
            (``SourceEntry.observation``) is kept as the history of its slot
            when the index has the slot or the batch writes it, and is never
            a version, a link or a count.

        Returns
        -------
        BatchResult
            What changed, and the entries whose footprint is still to be
            computed (pass them to ``write_footprints`` with the result of
            ``SourceAdapter.footprint``).

        Raises
        ------
        RuntimeError
            No pass is active.
        ValueError
            An entry of another producer.
        """
        state = self._active()
        batch = _Batch()
        for entry in entries:
            if entry.producer != state.info.producer:
                raise ValueError(
                    f"entry of producer {entry.producer!r} in a pass of"
                    f" {state.info.producer!r}"
                )
            self._plan(state, batch, entry)
        self._settle_observations(state, batch)
        if batch.empty():
            return BatchResult(needs_footprint=tuple(batch.needs_footprint))
        return self._apply(state, batch)

    def finish_pass(self, current: CurrentVersionLookup | None = None) -> PassSummary:
        """End the active pass: act on what it has not seen within its scope.

        Unseen versions become missing (with the date); versions an earlier
        pass already marked missing are removed by a full pass; unseen links
        are cleared, unseen problems resolved and unseen observations
        forgotten; slots left with nothing are removed. A pass over the whole
        store also drops empty segments and records the store as indexed and
        available.

        A producer without links names the current version of a slot itself
        (``current``), asked by the slot's key before anything is written: for
        the slots the pass touched (a version written, back or gone, a problem
        found or resolved) and for the slots that have none while the pass saw a
        version of them (a pass that did not finish leaves such slots), so a
        pass that changed nothing asks for none. A version the pass did not see
        is not taken: the next pass sees it. A slot with a key keeps its current
        version through a pass: no link is seen for it.

        Parameters
        ----------
        current : CurrentVersionLookup or None, optional
            The producer's answer for a slot key
            (``CurrentVersionAdapter.current_version``). Without it the
            current version of a slot with a key stays as it is.

        Returns
        -------
        PassSummary
            Counts of the changes.

        Raises
        ------
        RuntimeError
            No pass is active.

        Notes
        -----
        What ``current`` raises ends the call and leaves the pass active: the
        caller abandons it.
        """
        state = self._active()
        info = state.info
        now = _now()
        missing: list[int] = []
        removed: list[tuple[int, int]] = []
        touched = set(state.touched)
        for path, version in state.versions.items():
            if path in state.seen_versions:
                continue
            if version.state == "present":
                missing.append(version.id)
                touched.add(version.slot_id)
            elif info.full:
                removed.append((version.id, version.slot_id))
                touched.add(version.slot_id)
        unlinked = [
            slot.id
            for path, slot in state.slots.items()
            if slot.current_path is not None
            and slot.key is None
            and path not in state.seen_links
        ]
        unlinked_full = [
            slot.id
            for path, slot in state.slots.items()
            if slot.full_sheet_path is not None and path not in state.seen_full_sheets
        ]
        resolved = [
            (issue_id, slot_id)
            for key, (issue_id, slot_id) in state.issues.items()
            if key not in state.seen_issues
        ]
        gone = sorted(state.observations - state.seen_observations)
        touched.update(slot_id for _, slot_id in resolved if slot_id is not None)
        answers = {} if current is None else _current_versions(state, touched, current)
        affected = {slot_id for _, slot_id in removed}
        affected.update(unlinked, unlinked_full)
        affected.update(slot_id for _, slot_id in resolved if slot_id is not None)
        affected.update(answers)
        whole_store = info.segment is None and info.slots is None
        with self._transaction() as connection:
            connection.execute(
                "UPDATE versions SET state = 'missing', missing_since = ?"
                f" WHERE id IN ({_IDS})",
                (now, json.dumps(missing)),
            )
            connection.execute(
                f"DELETE FROM versions WHERE id IN ({_IDS})",
                (json.dumps([version_id for version_id, _ in removed]),),
            )
            connection.executemany(
                "UPDATE slots SET current_path = ? WHERE id = ?",
                [(target, slot_id) for slot_id, target in answers.items()],
            )
            connection.execute(
                f"UPDATE slots SET current_path = NULL WHERE id IN ({_IDS})",
                (json.dumps(unlinked),),
            )
            connection.execute(
                f"UPDATE slots SET full_sheet_path = NULL WHERE id IN ({_IDS})",
                (json.dumps(unlinked_full),),
            )
            connection.execute(
                f"DELETE FROM observations WHERE store_id = ? AND path IN ({_IDS})",
                (state.store_id, json.dumps(gone)),
            )
            connection.execute(
                f"DELETE FROM issues WHERE id IN ({_IDS})",
                (json.dumps([issue_id for issue_id, _ in resolved]),),
            )
            ids = json.dumps(sorted(affected))
            slots_removed = connection.execute(_DELETE_EMPTY_SLOTS, (ids,)).rowcount
            self._refresh_slots(connection, affected)
            if whole_store:
                connection.execute(
                    "DELETE FROM segments WHERE store_id = ? AND producer = ?"
                    " AND NOT EXISTS"
                    " (SELECT 1 FROM slots s WHERE s.segment_id = segments.id)"
                    " AND NOT EXISTS"
                    " (SELECT 1 FROM issues i WHERE i.segment_id = segments.id)",
                    (state.store_id, info.producer),
                )
                connection.execute(
                    "UPDATE stores SET indexed_at = ?, status = 'available',"
                    " status_at = ?, detail = NULL WHERE id = ?",
                    (now, now, state.store_id),
                )
        self._pass = None
        if whole_store:
            # Keep the planner's statistics close to the data (bounded cost).
            self._connection.execute("ANALYZE")
        return PassSummary(
            missing=len(missing),
            reappeared=state.reappeared,
            removed=len(removed),
            slots_removed=max(slots_removed, 0),
            unlinked=len(unlinked) + len(unlinked_full),
            issues_resolved=len(resolved),
            current=len(answers),
        )

    def abandon_pass(self) -> None:
        """Drop the active pass without acting on what it has not seen."""
        self._pass = None

    # Footprints.

    def write_footprints(
        self, store: str, items: Iterable[tuple[SourceEntry, Footprint]]
    ) -> int:
        """Record computed locations of versions that have none yet.

        An existing footprint or country location is never replaced
        (versions do not change); a ``none`` location is.

        Parameters
        ----------
        store : str
            Configured store id.
        items : Iterable[tuple[SourceEntry, Footprint]]
            Entries (``BatchResult.needs_footprint`` or rebuilt from the
            index) with ``SourceAdapter.footprint``'s result, its WGS84
            outline from ``outline_footprints``; the R*Tree gets the
            outline's bounding box.

        Returns
        -------
        int
            Number of versions whose location was written; an unchanged
            ``none`` (same reason) is not rewritten.
        """
        pairs = [(entry.relative_path.as_posix(), found) for entry, found in items]
        store_id = self._store_id(store)
        state = self._pass if self._pass and self._pass.store_id == store_id else None
        known: dict[str, tuple[int, str, str | None]] = {}
        unknown: list[str] = []
        for path, _ in pairs:
            version = state.versions.get(path) if state else None
            if version is None:
                unknown.append(path)
            else:
                known[path] = (version.id, version.location, version.reason)
        if unknown:
            for path, version_id, location, reason in self._connection.execute(
                "SELECT path, id, location, location_reason FROM versions"
                f" WHERE store_id = ? AND path IN ({_IDS})",
                (store_id, json.dumps(unknown)),
            ).fetchall():
                known[str(path)] = (int(version_id), str(location), reason)
        locations: list[tuple[object, ...]] = []
        shapes: list[tuple[object, ...]] = []
        boxes: list[tuple[object, ...]] = []
        written: dict[str, tuple[str, str | None]] = {}
        for path, found in pairs:
            target = known.get(path)
            if target is None or target[1] != "none" or path in written:
                continue
            if found.location == "none" and (found.reason or "no_source") == target[2]:
                continue
            version_id = target[0]
            location, shape, box = _location_rows(version_id, found)
            locations.append(location)
            if shape is not None:
                shapes.append(shape)
            if box is not None:
                boxes.append(box)
            written[path] = (str(location[0]), _optional_text(location[1]))
        if not locations:
            return 0
        with self._transaction() as connection:
            connection.executemany(_UPDATE_LOCATION, locations)
            connection.executemany(_UPSERT_SHAPE, shapes)
            connection.executemany(
                "INSERT OR REPLACE INTO footprints"
                " (id, min_lon, max_lon, min_lat, max_lat) VALUES (?, ?, ?, ?, ?)",
                boxes,
            )
        if state is not None:
            for path, (location_kind, reason) in written.items():
                version = state.versions.get(path)
                if version is not None:
                    version.location, version.reason = location_kind, reason
        return len(locations)

    # Problems found by check jobs.

    def record_issue(
        self,
        store: str,
        producer: str,
        *,
        path: str,
        code: str,
        segment: str | None = None,
        slot: str | None = None,
    ) -> None:
        """Record a problem found by a check job (e.g. ``link_mismatch``).

        Scan passes do not resolve it; ``clear_issue`` does.

        Parameters
        ----------
        store : str
            Configured store id.
        producer : str
            Producer of the store directory.
        path : str
            Path of the problem relative to the store.
        code : str
            Problem code.
        segment, slot : str or None, optional
            Segment and slot path of the problem.
        """
        store_id = self._store_id(store)
        with self._transaction() as connection:
            segment_id = self._segment_id(connection, store_id, producer, segment or "")
            slot_id = None
            if slot is not None:
                row = connection.execute(
                    "SELECT id FROM slots WHERE store_id = ? AND path = ?",
                    (store_id, slot),
                ).fetchone()
                slot_id = None if row is None else int(row[0])
            connection.execute(
                _INSERT_ISSUE,
                (store_id, segment_id, slot_id, path, code, "check", _now()),
            )

    def clear_issue(self, store: str, *, path: str, code: str) -> bool:
        """Resolve a problem recorded by a check job; return whether it existed."""
        store_id = self._store_id(store)
        with self._transaction() as connection:
            deleted = connection.execute(
                "DELETE FROM issues WHERE store_id = ? AND path = ? AND code = ?"
                " AND origin = 'check'",
                (store_id, path, code),
            ).rowcount
        return deleted > 0

    # Projects.

    def project_stamps(self, producer: str) -> dict[str, ManifestStamp]:
        """Return each indexed project's directory with its manifest stamp.

        A manifest whose size and modification time equal the stamp need
        not be read again. A project without a configured store (an invalid
        manifest, an unknown or removed store) or without a status gets an
        empty stamp, so it is read again until it matches and is checked.
        """
        return {
            str(path): ManifestStamp(mtime_ns, size)
            for path, mtime_ns, size in self._connection.execute(
                "SELECT path,"
                " iif(store_id IS NULL OR status IS NULL, NULL, manifest_mtime_ns),"
                " iif(store_id IS NULL OR status IS NULL, NULL, manifest_size)"
                " FROM projects WHERE producer = ?",
                (producer,),
            ).fetchall()
        }

    def write_project(
        self, info: ProjectInfo, *, store: str | None, stamp: ManifestStamp
    ) -> str:
        """Record a project with its tasks and pinned versions.

        Parameters
        ----------
        info : ProjectInfo
            ``read_project`` or ``project_status`` of the adapter; a project
            with ``problem`` (an invalid manifest) stays visible.
        store : str or None
            Configured id of the store the manifest names (``info.store``)
            and its pins refer to; ``None`` when no configured store matches.
        stamp : ManifestStamp
            Size and modification time of the manifest that was read.

        Returns
        -------
        str
            The project's key: its slugged name, made unique. The project's
            access key (its directory after ``realpath``) is recorded with
            it, so the state database's access entry applies.
        """
        store_id = self._find_store_id(store) if store is not None else None
        path = str(info.path)
        key_of_access = access_key(info.path)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT key FROM projects WHERE producer = ? AND path = ?",
                (info.producer, path),
            ).fetchone()
            key = str(row[0]) if row is not None else _free_key(connection, info.name)
            (project_id,) = connection.execute(
                "INSERT INTO projects (key, producer, path, access_key, name,"
                " store_id, store_dir, status, problem, manifest_mtime_ns,"
                " manifest_size, scanned_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (producer, path) DO UPDATE SET name = excluded.name,"
                " access_key = excluded.access_key,"
                " store_id = excluded.store_id, store_dir = excluded.store_dir,"
                " status = excluded.status, problem = excluded.problem,"
                " manifest_mtime_ns = excluded.manifest_mtime_ns,"
                " manifest_size = excluded.manifest_size,"
                " scanned_at = excluded.scanned_at RETURNING id",
                (
                    key,
                    info.producer,
                    path,
                    key_of_access,
                    info.name,
                    store_id,
                    info.store,
                    info.status,
                    info.problem,
                    stamp.mtime_ns,
                    stamp.size,
                    _now(),
                ),
            ).fetchone()
            connection.execute(
                "DELETE FROM project_tasks WHERE project_id = ?", (project_id,)
            )
            connection.execute("DELETE FROM pins WHERE project_id = ?", (project_id,))
            connection.executemany(
                "INSERT INTO project_tasks"
                " (project_id, task_id, position, command, options, status)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        project_id,
                        task.task_id,
                        position,
                        task.command,
                        json.dumps(task.options, ensure_ascii=False, default=str),
                        task.status,
                    )
                    for position, task in enumerate(info.tasks)
                ],
            )
            connection.executemany(
                "INSERT INTO pins"
                " (project_id, task_id, store_id, store_dir, version_path, sha256)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        project_id,
                        pin.task_id,
                        store_id,
                        pin.store,
                        pin.version_path.as_posix(),
                        pin.sha256.lower() if pin.sha256 else None,
                    )
                    for pin in info.pins
                ],
            )
        return key

    def remove_projects(self, producer: str, *, keep: Collection[str]) -> int:
        """Remove the producer's projects whose directory is not in ``keep``.

        Returns
        -------
        int
            Number of projects removed.
        """
        with self._transaction() as connection:
            return int(
                connection.execute(
                    f"DELETE FROM projects WHERE producer = ? AND path NOT IN ({_IDS})",
                    (producer, json.dumps(sorted(keep))),
                ).rowcount
            )

    # Areas.

    def write_area(self, area: AreaRecord) -> None:
        """Keep an area (its geometry stays after the file copy is deleted).

        Raises
        ------
        ValueError
            The geometry is not a polygon with coordinates.
        """
        bounds = polygon_bounds(area.geometry)
        if bounds is None:
            raise ValueError("an area must be a Polygon or MultiPolygon")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO areas (id, name, source, geometry, area_km2, countries,"
                " min_lon, min_lat, max_lon, max_lat, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET name = excluded.name,"
                " source = excluded.source, geometry = excluded.geometry,"
                " area_km2 = excluded.area_km2, countries = excluded.countries,"
                " min_lon = excluded.min_lon, min_lat = excluded.min_lat,"
                " max_lon = excluded.max_lon, max_lat = excluded.max_lat",
                (
                    area.id,
                    area.name,
                    area.source,
                    json.dumps(area.geometry, separators=(",", ":")),
                    area.area_km2,
                    json.dumps(list(area.countries)),
                    *bounds,
                    area.created_at.astimezone(UTC).isoformat(timespec="seconds"),
                ),
            )

    def write_availability(
        self,
        area_id: str,
        report: AvailabilityReport,
        *,
        product: str,
        job_id: str | None = None,
    ) -> bool:
        """Keep the report of an area and product, unless a newer one is kept.

        One report per area, producer and product: a report replaces the one
        it is not older than (two jobs ending in another order keep the newer).

        Returns
        -------
        bool
            Whether the report was kept.

        Raises
        ------
        sqlite3.IntegrityError
            The index keeps no area ``area_id``.
        """
        checked_at = report.checked_at.astimezone(UTC).isoformat(timespec="seconds")
        with self._transaction() as connection:
            return (
                connection.execute(
                    "INSERT INTO availability (area_id, producer, product, checked_at,"
                    " report, job_id) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (area_id, producer, product) DO UPDATE SET"
                    " checked_at = excluded.checked_at, report = excluded.report,"
                    " job_id = excluded.job_id"
                    " WHERE excluded.checked_at >= availability.checked_at",
                    (
                        area_id,
                        report.producer,
                        product,
                        checked_at,
                        json.dumps(report.to_json(), separators=(",", ":")),
                        job_id,
                    ),
                ).rowcount
                > 0
            )

    def write_plan(self, stored: StoredPlan) -> None:
        """Keep the plan of a ``check`` job; it goes when the job is forgotten.

        Raises
        ------
        sqlite3.IntegrityError
            The index keeps no job ``stored.job_id``.
        """
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO plans (job_id, store, line, plan) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (job_id) DO UPDATE SET store = excluded.store,"
                " line = excluded.line, plan = excluded.plan",
                (
                    stored.job_id,
                    stored.store,
                    stored.line,
                    json.dumps(stored.plan.to_json(), separators=(",", ":")),
                ),
            )

    # Own data of projects (decision 8).

    def write_own_folder(
        self,
        project: str,
        *,
        path: str,
        source: OwnFolderSource,
        state: OwnFolderState,
        reason: OwnFolderReason | None = None,
        now: datetime,
    ) -> bool:
        """Record a project's data folder and the state a scan finds it in.

        The files, snapshots and problems of the folder go when it moved
        (another path holds other files) or is ``invalid`` (it is not read,
        and its files may belong to another project's visibility).
        ``missing`` and ``unreadable`` keep them: a share may come back.

        Parameters
        ----------
        project : str
            The project directory after ``realpath`` (``access_key``).
        path : str
            The folder (the setting or ``<project>/dane``).
        source : {"default", "setting"}
            Where ``path`` comes from.
        state : {"ok", "missing", "unreadable", "invalid"}
            What the scan found.
        reason : OwnFolderReason or None, optional
            Why an ``invalid`` folder is refused.
        now : datetime
            The scan's time.

        Returns
        -------
        bool
            Whether the folder's files were dropped.
        """
        moment = _utc(now)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT id, path FROM own_folders WHERE project = ?", (project,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO own_folders (project, path, source, state, reason,"
                    " scanned_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (project, path, source, state, reason, moment),
                )
                return False
            folder_id = int(row[0])
            dropped = row[1] != path or state == "invalid"
            if dropped:
                for table in ("own_files", "snapshots", "own_problems"):
                    connection.execute(
                        f"DELETE FROM {table} WHERE folder_id = ?", (folder_id,)
                    )
            connection.execute(
                "UPDATE own_folders SET path = ?, source = ?, state = ?, reason = ?,"
                " scanned_at = ? WHERE id = ?",
                (path, source, state, reason, moment, folder_id),
            )
        return dropped

    def known_own_files(self, project: str) -> dict[str, KnownOwnFile]:
        """Return the indexed files of a project's folder by path.

        A file whose ``stamp`` equals what is on the disk now (and that is
        not to be read again, ``retry``) needs nothing but its ``stat``.
        """
        rows = self._connection.execute(
            "SELECT f.path, f.stamp, f.missing_since IS NOT NULL, f.retry,"
            " f.read_error FROM own_files f JOIN own_folders o ON o.id = f.folder_id"
            " WHERE o.project = ?",
            (project,),
        ).fetchall()
        return {
            str(path): KnownOwnFile(str(stamp), bool(missing), bool(retry), error)
            for path, stamp, missing, retry, error in rows
        }

    def write_own_files(
        self, project: str, files: Iterable[OwnFileWrite], *, now: datetime
    ) -> OwnFilesWritten:
        """Record files a scan read, in one transaction.

        A file seen again is present (no longer missing). Its observed state
        (size, modification time, content, features) joins its history when
        it differs from the last one; the newest ``MAX_OWN_FILE_STATES``
        stay. ``changed_at`` moves when the content identity changes, and
        the change against the last snapshot is computed again.

        Raises
        ------
        ValueError
            The project has no folder in the index (``write_own_folder``).
        """
        moment = _utc(now)
        new = changed = 0
        with self._transaction() as connection:
            folder_id = self._own_folder_id(connection, project)
            for item in files:
                row = connection.execute(
                    "SELECT content_method, content_sha256, changed_at FROM own_files"
                    " WHERE folder_id = ? AND path = ?",
                    (folder_id, item.path),
                ).fetchone()
                content = (item.content_method, item.content_sha256)
                if row is None:
                    new += 1
                    changed_at = moment
                else:
                    changed += 1
                    changed_at = moment if tuple(row[:2]) != content else row[2]
                file_row = connection.execute(
                    _UPSERT_OWN_FILE,
                    (
                        folder_id,
                        item.path,
                        own_file_id(item.path),
                        item.disk_path,
                        item.stamp,
                        item.kind,
                        item.driver,
                        json.dumps(list(item.members), ensure_ascii=False),
                        item.size_bytes,
                        item.modified_ns,
                        item.state,
                        item.read_error,
                        item.read_detail,
                        int(item.retry),
                        *content,
                        _json([asdict(layer) for layer in item.layers]),
                        None if item.raster is None else _json(asdict(item.raster)),
                        item.feature_count,
                        item.native_crs,
                        None if item.native_bbox is None else _json(item.native_bbox),
                        None if item.wgs84 is None else _geojson(item.wgs84),
                        item.location_reason,
                        moment,
                        changed_at,
                    ),
                ).fetchone()[0]
                _observe(connection, int(file_row), item, moment)
            connection.execute(_OWN_LAST_SNAPSHOT, (folder_id,))
            connection.execute(_OWN_CHANGE, (folder_id,))
        return OwnFilesWritten(new=new, changed=changed)

    def mark_own_missing(
        self,
        project: str,
        *,
        present: Collection[str],
        drop: Collection[str] = (),
        now: datetime,
    ) -> OwnMissingResult:
        """Act on the files of a project's folder a scan did not list.

        Parameters
        ----------
        project : str
            The project directory after ``realpath``.
        present : Collection[str]
            Paths the scan listed, and those it keeps without listing (in a
            directory it could not list): missing ones among them are back.
        drop : Collection[str], optional
            Paths beyond the first ``MAX_OWN_FILES`` of a folder too large:
            they leave the index (they are not missing).
        now : datetime
            The scan's time, ``missing_since`` of the files gone.

        Returns
        -------
        OwnMissingResult
            Files newly missing, back, and dropped.
        """
        listed = json.dumps(sorted(present), ensure_ascii=False)
        with self._transaction() as connection:
            folder_id = self._own_folder_id(connection, project)
            dropped = connection.execute(
                f"DELETE FROM own_files WHERE folder_id = ? AND path IN ({_IDS})",
                (folder_id, json.dumps(sorted(drop), ensure_ascii=False)),
            ).rowcount
            reappeared = connection.execute(
                "UPDATE own_files SET missing_since = NULL WHERE folder_id = ?"
                f" AND missing_since IS NOT NULL AND path IN ({_IDS})",
                (folder_id, listed),
            ).rowcount
            missing = connection.execute(
                "UPDATE own_files SET missing_since = ? WHERE folder_id = ?"
                f" AND missing_since IS NULL AND path NOT IN ({_IDS})",
                (_utc(now), folder_id, listed),
            ).rowcount
        return OwnMissingResult(
            missing=int(missing), reappeared=int(reappeared), dropped=int(dropped)
        )

    def known_own_snapshots(
        self, project: str
    ) -> dict[tuple[str, str], tuple[str, str]]:
        """Return ``(stamp, state)`` of each indexed snapshot by ``(path, label)``."""
        rows = self._connection.execute(
            "SELECT s.path, s.label, s.stamp, s.state FROM snapshots s"
            " JOIN own_folders o ON o.id = s.folder_id WHERE o.project = ?",
            (project,),
        ).fetchall()
        return {
            (str(path), str(label)): (str(stamp), str(state))
            for path, label, stamp, state in rows
        }

    def record_snapshot(self, project: str, snapshot: SnapshotWrite) -> None:
        """Record one snapshot, e.g. right after the ``snapshot`` job published it.

        The file's change against its last snapshot follows. The snapshot
        directory stays the source of truth: a scan adds what is missing.

        Raises
        ------
        ValueError
            The project has no folder in the index.
        """
        self.write_own_snapshots(project, (snapshot,), keep=None)

    def write_own_snapshots(
        self,
        project: str,
        snapshots: Iterable[SnapshotWrite],
        *,
        keep: Collection[tuple[str, str]] | None,
    ) -> int:
        """Record the snapshots a scan found in ``.wersje/``.

        Parameters
        ----------
        project : str
            The project directory after ``realpath``.
        snapshots : Iterable[SnapshotWrite]
            Snapshots new or changed since the index recorded them.
        keep : Collection[tuple[str, str]] or None
            ``(path, label)`` of every snapshot found: others leave the
            index (their directory is gone); ``None`` removes none.

        Returns
        -------
        int
            Snapshots added or whose state changed.
        """
        changed = 0
        with self._transaction() as connection:
            folder_id = self._own_folder_id(connection, project)
            for item in snapshots:
                before = connection.execute(
                    "SELECT state FROM snapshots WHERE folder_id = ? AND path = ?"
                    " AND label = ?",
                    (folder_id, item.path, item.label),
                ).fetchone()
                changed += before is None or before[0] != item.state
                connection.execute(
                    _UPSERT_SNAPSHOT,
                    (
                        folder_id,
                        item.path,
                        own_file_id(item.path),
                        item.label,
                        item.state,
                        None if item.created_at is None else _utc(item.created_at),
                        item.content_method,
                        item.content_sha256,
                        item.size_bytes,
                        item.stamp,
                        None if item.document is None else _json(item.document),
                    ),
                )
            if keep is not None:
                found = json.dumps(
                    [list(pair) for pair in sorted(keep)], ensure_ascii=False
                )
                connection.execute(
                    "DELETE FROM snapshots WHERE folder_id = ? AND NOT EXISTS ("
                    " SELECT 1 FROM json_each(?) k"
                    " WHERE json_extract(k.value, '$[0]') = snapshots.path"
                    " AND json_extract(k.value, '$[1]') = snapshots.label)",
                    (folder_id, found),
                )
            connection.execute(_OWN_LAST_SNAPSHOT, (folder_id,))
            connection.execute(_OWN_CHANGE, (folder_id,))
        return changed

    def finish_own_folder(
        self, project: str, *, problems: Iterable[OwnProblem], now: datetime
    ) -> int:
        """End a scan of a project's folder: its problems and totals.

        Problems not found again are resolved; one found again keeps its
        ``first_seen_at``. Totals count present files and every snapshot.

        Returns
        -------
        int
            Problems found for the first time.
        """
        moment = _utc(now)
        rows = {
            (problem.code, problem.path or ""): problem.reason for problem in problems
        }
        with self._transaction() as connection:
            folder_id = self._own_folder_id(connection, project)
            known = {
                (str(code), str(path))
                for code, path in connection.execute(
                    "SELECT code, path FROM own_problems WHERE folder_id = ?",
                    (folder_id,),
                ).fetchall()
            }
            connection.executemany(
                "INSERT INTO own_problems (folder_id, code, path, reason,"
                " first_seen_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT"
                " (folder_id, code, path) DO UPDATE SET reason = excluded.reason",
                [
                    (folder_id, code, path, reason, moment)
                    for (code, path), reason in rows.items()
                ],
            )
            for code, path in known - rows.keys():
                connection.execute(
                    "DELETE FROM own_problems WHERE folder_id = ? AND code = ?"
                    " AND path = ?",
                    (folder_id, code, path),
                )
            connection.execute(_OWN_TOTALS, (moment, folder_id))
        return len(rows.keys() - known)

    def remove_own_folders(self, *, keep: Collection[str]) -> int:
        """Forget the folders of projects no longer in the index.

        Parameters
        ----------
        keep : Collection[str]
            Access keys of the projects whose folders stay.

        Returns
        -------
        int
            Folders removed with their files, snapshots and problems.
        """
        with self._transaction() as connection:
            return int(
                connection.execute(
                    f"DELETE FROM own_folders WHERE project NOT IN ({_IDS})",
                    (json.dumps(sorted(keep), ensure_ascii=False),),
                ).rowcount
            )

    # Internals.

    @staticmethod
    def _own_folder_id(connection: sqlite3.Connection, project: str) -> int:
        row = connection.execute(
            "SELECT id FROM own_folders WHERE project = ?", (project,)
        ).fetchone()
        if row is None:
            raise ValueError(f"no data folder of project {project!r} in the index")
        return int(row[0])

    def _active(self) -> _PassState:
        if self._pass is None:
            raise RuntimeError("no scan pass is active on this writer")
        return self._pass

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    def _store_id(self, store: str) -> int:
        found = self._find_store_id(store)
        if found is None:
            raise ValueError(f"store {store!r} is not in the index (sync_stores)")
        return found

    def _find_store_id(self, store: str) -> int | None:
        row = self._connection.execute(
            "SELECT id FROM stores WHERE key = ?", (store,)
        ).fetchone()
        return None if row is None else int(row[0])

    def _load_segments(self, store_id: int, producer: str) -> dict[str, _Segment]:
        return {
            str(segment): _Segment(int(segment_id), product, country)
            for segment, segment_id, product, country in self._connection.execute(
                "SELECT segment, id, product, country FROM segments"
                " WHERE store_id = ? AND producer = ?",
                (store_id, producer),
            ).fetchall()
        }

    def _segment_id(
        self, connection: sqlite3.Connection, store_id: int, producer: str, segment: str
    ) -> int:
        """Id of a segment, created as recognised when the producer never listed it."""
        connection.execute(
            "INSERT INTO segments (store_id, producer, segment, name, known)"
            " VALUES (?, ?, ?, ?, 1)"
            " ON CONFLICT (store_id, producer, segment) DO NOTHING",
            (store_id, producer, segment, segment or producer),
        )
        (segment_id,) = connection.execute(
            "SELECT id FROM segments"
            " WHERE store_id = ? AND producer = ? AND segment = ?",
            (store_id, producer, segment),
        ).fetchone()
        return int(segment_id)

    def _carry_segments(
        self,
        connection: sqlite3.Connection,
        store_id: int,
        producer: str,
        segments: list[str],
    ) -> None:
        """Carry changed segment descriptions to their slots and search rows."""
        rows = connection.execute(
            "SELECT id, product, country FROM segments WHERE store_id = ?"
            f" AND producer = ? AND segment IN ({_IDS})",
            (store_id, producer, json.dumps(segments)),
        ).fetchall()
        slot_ids: set[int] = set()
        for segment_id, product, country in rows:
            connection.execute(
                "UPDATE slots SET product = coalesce(?, product),"
                " country = coalesce(?, country) WHERE segment_id = ?",
                (product, country, segment_id),
            )
            slot_ids.update(
                int(slot_id)
                for (slot_id,) in connection.execute(
                    "SELECT id FROM slots WHERE segment_id = ?", (segment_id,)
                ).fetchall()
            )
        self._refresh_slots(connection, slot_ids)
        if self._pass is not None and self._pass.store_id == store_id:
            for slot in self._pass.slots.values():
                if slot.id in slot_ids:
                    slot.product = slot.country = None

    def _plan(self, state: _PassState, batch: _Batch, entry: SourceEntry) -> None:
        """Decide in memory what an entry changes; unchanged costs no SQL."""
        segment = entry.segment or ""
        kind = entry.kind
        if kind == "problem":
            path = entry.relative_path.as_posix()
            key = (path, entry.problem or "unknown")
            state.seen_issues.add(key)
            slot = None if entry.slot_path is None else entry.slot_path.as_posix()
            if slot is not None:
                self._plan_slot(state, batch, slot, segment, None, entry)
            if key not in state.issues:
                batch.issues[key] = (slot, segment)
            return
        if kind == "version":
            path = entry.relative_path.as_posix()
            slot = path if entry.slot_path is None else entry.slot_path.as_posix()
            self._plan_slot(state, batch, slot, segment, entry.meta, entry)
            self._plan_version(state, batch, entry, path, slot, segment)
            if path == slot:
                # A producer without links: each file is its slot's content.
                self._plan_link(state, batch, "link", slot, path)
            return
        if kind == "observation":
            # The publication history of a slot, never a version or a link.
            self._plan_observation(state, batch, entry, segment)
            return
        # Paths become text only where needed: pathlib's str() is costly.
        slot = (entry.slot_path or entry.relative_path).as_posix()
        self._plan_slot(state, batch, slot, segment, entry.meta, entry)
        target = None if entry.version_path is None else entry.version_path.as_posix()
        if target is None and kind == "link" and entry.meta is not None:
            # A plain file at the standard path (from before versions/) is
            # its own version: the only copy of its content.
            path = entry.relative_path.as_posix()
            self._plan_version(state, batch, entry, path, slot, segment)
            target = path
        self._plan_link(state, batch, kind, slot, target)

    def _plan_observation(
        self, state: _PassState, batch: _Batch, entry: SourceEntry, segment: str
    ) -> None:
        """Plan an observation the index does not know yet.

        A register file never changes, so a known one costs nothing and is
        only seen again; one without its record or its slot is not kept.
        """
        path = entry.relative_path.as_posix()
        if path in state.observations:
            state.seen_observations.add(path)
            return
        if entry.observation is None or entry.slot_path is None:
            return
        version = None if entry.version_path is None else entry.version_path.as_posix()
        batch.observations[path] = _ObservationWrite(
            entry.slot_path.as_posix(), segment, version, entry.observation
        )

    @staticmethod
    def _settle_observations(state: _PassState, batch: _Batch) -> None:
        """Keep the planned observations whose slot the index has or the batch writes.

        An observation is the history of a slot and never makes one: a
        record whose slot is unknown is left for a later pass, which sees it
        again.
        """
        for path, write in list(batch.observations.items()):
            if write.slot in state.slots or write.slot in batch.slots:
                state.seen_observations.add(path)
            else:
                del batch.observations[path]

    def _plan_slot(
        self,
        state: _PassState,
        batch: _Batch,
        slot: str,
        segment: str,
        meta: EntryMeta | None,
        entry: SourceEntry,
    ) -> None:
        known = state.slots.get(slot)
        if meta is None and (known is not None or slot in batch.slots):
            return
        described = state.segments.get(segment)
        unit = meta.unit if meta else None
        product = (described.product if described else None) or (
            meta.product if meta else None
        )
        country = (described.country if described else None) or (
            meta.country if meta else None
        )
        key = entry.slot_key
        pending = batch.slots.get(slot)
        if pending is not None:
            pending.unit = pending.unit or unit
            pending.product = pending.product or product
            pending.country = pending.country or country
            pending.key = pending.key or key
            return
        if (
            known is not None
            and (unit is None or unit == known.unit)
            and (product is None or product == known.product)
            and (country is None or country == known.country)
            and (key is None or key == known.key)
        ):
            return
        batch.slots[slot] = _SlotWrite(
            segment, unit, product, country, key, entry.slot_name
        )

    def _plan_version(
        self,
        state: _PassState,
        batch: _Batch,
        entry: SourceEntry,
        path: str,
        slot: str,
        segment: str,
    ) -> None:
        state.seen_versions.add(path)
        known = state.versions.get(path)
        meta = entry.meta
        if meta is not None and not entry.skipped:
            row = _meta_row(meta)
            digest = _digest(row)
            if known is None or known.digest != digest:
                raw = _raw_json(meta.raw_sidecar)
                batch.versions[path] = _VersionWrite(slot, segment, digest, row, raw)
        elif known is None:
            batch.versions[path] = _VersionWrite(slot, segment, None, None, None)
        if known is not None and known.state == "missing":
            batch.reappeared.add(path)
        if (
            known is None
            or (known.location == "none" and known.reason == "pending")
            or (state.info.full and known.location == "none")
        ):
            batch.needs_footprint.append(entry)

    def _plan_link(
        self,
        state: _PassState,
        batch: _Batch,
        kind: str,
        slot: str,
        target: str | None,
    ) -> None:
        standard = kind == "link"
        (state.seen_links if standard else state.seen_full_sheets).add(slot)
        known = state.slots.get(slot)
        current = None
        if known is not None:
            current = known.current_path if standard else known.full_sheet_path
        if known is None or current != target:
            (batch.links if standard else batch.full_sheets)[slot] = target

    def _apply(self, state: _PassState, batch: _Batch) -> BatchResult:
        """Write a planned batch in one transaction, then update the pass state."""
        now = _now()
        store_id = state.store_id
        producer = state.info.producer
        new_segments: dict[str, int] = {}
        fresh_slots: dict[str, _KnownSlot] = {}
        fresh_versions: dict[str, _KnownVersion] = {}
        fresh_issues: dict[tuple[str, str], tuple[int, int | None]] = {}
        with self._transaction() as connection:

            def segment_id(segment: str) -> int:
                known = state.segments.get(segment)
                if known is not None:
                    return known.id
                if segment not in new_segments:
                    new_segments[segment] = self._segment_id(
                        connection, store_id, producer, segment
                    )
                return new_segments[segment]

            def slot_id(slot: str) -> int:
                found = fresh_slots.get(slot) or state.slots[slot]
                return found.id

            connection.executemany(
                _UPSERT_SLOT,
                [
                    (
                        store_id,
                        segment_id(write.segment),
                        slot,
                        write.name or PurePosixPath(slot).name,
                        write.key,
                        write.unit,
                        write.product,
                        write.country,
                    )
                    for slot, write in batch.slots.items()
                ],
            )
            unknown_slots = [slot for slot in batch.slots if slot not in state.slots]
            if unknown_slots:
                for row in connection.execute(
                    "SELECT path, id, current_path, full_sheet_path, unit, product,"
                    " country, slot_key FROM slots"
                    f" WHERE store_id = ? AND path IN ({_IDS})",
                    (store_id, json.dumps(unknown_slots)),
                ).fetchall():
                    fresh_slots[str(row[0])] = _KnownSlot(int(row[1]), *row[2:])
            meta_rows: list[tuple[object, ...]] = []
            bare_rows: list[tuple[object, ...]] = []
            for path, write in batch.versions.items():
                ids = (store_id, segment_id(write.segment), slot_id(write.slot), path)
                if write.row is None:
                    bare_rows.append((*ids, now))
                else:
                    meta_rows.append((*ids, write.digest, *write.row, now))
            connection.executemany(_UPSERT_VERSION, meta_rows)
            connection.executemany(_INSERT_BARE_VERSION, bare_rows)
            if batch.reappeared:
                connection.execute(
                    "UPDATE versions SET state = 'present', missing_since = NULL"
                    f" WHERE store_id = ? AND path IN ({_IDS}) AND state = 'missing'",
                    (store_id, json.dumps(sorted(batch.reappeared))),
                )
            touched = list(batch.versions) + [
                path for path in batch.reappeared if path not in batch.versions
            ]
            if touched:
                for row in connection.execute(
                    "SELECT path, id, slot_id, segment_id, state, digest, location,"
                    " location_reason FROM versions"
                    f" WHERE store_id = ? AND path IN ({_IDS})",
                    (store_id, json.dumps(touched)),
                ).fetchall():
                    fresh_versions[str(row[0])] = _KnownVersion(
                        int(row[1]), int(row[2]), int(row[3]), *row[4:]
                    )
            connection.executemany(
                _UPSERT_SIDECAR,
                [
                    (fresh_versions[path].id, write.raw)
                    for path, write in batch.versions.items()
                    if write.raw is not None and path in fresh_versions
                ],
            )
            connection.executemany(
                "UPDATE slots SET current_path = ? WHERE id = ?",
                [(target, slot_id(slot)) for slot, target in batch.links.items()],
            )
            connection.executemany(
                "UPDATE slots SET full_sheet_path = ? WHERE id = ?",
                [(target, slot_id(slot)) for slot, target in batch.full_sheets.items()],
            )
            issue_rows = [
                (
                    store_id,
                    segment_id(segment),
                    None if slot is None else slot_id(slot),
                    path,
                    code,
                    "scan",
                    now,
                )
                for (path, code), (slot, segment) in batch.issues.items()
            ]
            connection.executemany(_INSERT_ISSUE, issue_rows)
            if issue_rows:
                paths = sorted({path for path, _ in batch.issues})
                for path, code, issue_id, issue_slot in connection.execute(
                    "SELECT path, code, id, slot_id FROM issues"
                    f" WHERE store_id = ? AND path IN ({_IDS})",
                    (store_id, json.dumps(paths)),
                ).fetchall():
                    key = (str(path), str(code))
                    if key in batch.issues:
                        fresh_issues[key] = (
                            int(issue_id),
                            None if issue_slot is None else int(issue_slot),
                        )
            connection.executemany(
                _INSERT_OBSERVATION,
                [
                    (
                        store_id,
                        segment_id(write.segment),
                        slot_id(write.slot),
                        path,
                        write.version_path,
                        _utc(write.record.seen_at),
                        write.record.url,
                        write.record.etag,
                        write.record.last_modified,
                        write.record.size_bytes,
                        write.record.sha256,
                    )
                    for path, write in batch.observations.items()
                ],
            )
            affected = {slot_id(slot) for slot in batch.slots}
            affected.update(slot_id(write.slot) for write in batch.versions.values())
            affected.update(slot_id(slot) for slot in batch.links)
            affected.update(slot_id(slot) for slot in batch.full_sheets)
            affected.update(
                slot_id(slot) for slot, _ in batch.issues.values() if slot is not None
            )
            self._refresh_slots(connection, affected)
            slots_touched = affected | {
                state.versions[path].slot_id for path in batch.reappeared
            }
        # The transaction is committed: the pass state follows the index.
        for segment, new_id in new_segments.items():
            state.segments[segment] = _Segment(new_id, None, None)
        for slot, pending in batch.slots.items():
            known_slot = fresh_slots.get(slot) or state.slots.get(slot)
            if known_slot is None:
                continue
            known_slot.unit = pending.unit or known_slot.unit
            known_slot.product = pending.product or known_slot.product
            known_slot.country = pending.country or known_slot.country
            known_slot.key = pending.key or known_slot.key
            state.slots[slot] = known_slot
        for slot, target in batch.links.items():
            state.slots[slot].current_path = target
        for slot, target in batch.full_sheets.items():
            state.slots[slot].full_sheet_path = target
        state.versions.update(fresh_versions)
        state.issues.update(fresh_issues)
        state.observations.update(batch.observations)
        state.touched.update(slots_touched)
        state.reappeared += len(batch.reappeared)
        return BatchResult(
            needs_footprint=tuple(batch.needs_footprint),
            versions_written=len(batch.versions),
            links_changed=len(batch.links) + len(batch.full_sheets),
            issues_added=len(fresh_issues),
        )

    @staticmethod
    def _refresh_slots(
        connection: sqlite3.Connection, slot_ids: Collection[int]
    ) -> None:
        """Recompute current versions, state and search rows of slots."""
        if not slot_ids:
            return
        ids = json.dumps(sorted(slot_ids))
        connection.execute(_RESOLVE_LINKS, (ids,))
        connection.execute(_SLOT_STATUS, (ids,))
        connection.execute(f"DELETE FROM search WHERE rowid IN ({_IDS})", (ids,))
        connection.execute(_INSERT_SEARCH, (ids,))


def _settled_directories(state: _PassState) -> dict[int, dict[str, tuple[str, ...]]]:
    """Version directories of a pass whose files were all valid versions.

    A directory is left out when it holds a missing version, a version
    without metadata or a problem the pass knows; a version that is its own
    slot has no version directory.
    """
    unsettled = {path.rpartition("/")[0] for path, _ in state.issues}
    found: dict[int, dict[str, list[str]]] = {}
    for path, version in state.versions.items():
        if path in state.slots:
            continue
        directory, _, name = path.rpartition("/")
        if version.state != "present" or version.digest is None:
            unsettled.add(directory)
            continue
        found.setdefault(version.segment_id, {}).setdefault(directory, []).append(name)
    return {
        segment_id: {
            directory: tuple(names)
            for directory, names in directories.items()
            if directory not in unsettled
        }
        for segment_id, directories in found.items()
    }


def _current_versions(
    state: _PassState, touched: Collection[int], current: CurrentVersionLookup
) -> dict[int, str | None]:
    """Ask the producer for the current version of the slots it keys.

    Asked are the slots with a key that the pass touched, and those with a key
    and no current version of which the pass saw a version: a pass that did
    not finish (its batches are written, ``finish_pass`` is not) leaves such
    slots, and nothing touches them again, so every scan asks for them until
    they have one. A slot the producer cannot name a version of (a broken
    version in it) is asked every scan, and costs the producer a read of its
    few versions. An answer that is not a version this pass saw is left for
    the next pass, which sees it: a version published since the listing is not
    written as a current one the index does not hold.

    Returns
    -------
    dict[int, str | None]
        The new ``current_path`` of each slot (by id) whose answer differs
        from the index's; ``None`` clears it.
    """
    keyed = [(slot, slot.key) for slot in state.slots.values() if slot.key is not None]
    if not keyed:
        return {}
    seen = {
        version.slot_id
        for path in state.seen_versions
        if (version := state.versions.get(path)) is not None
    }
    changes: dict[int, str | None] = {}
    for slot, key in keyed:
        unnamed = slot.current_path is None and slot.id in seen
        if slot.id not in touched and not unnamed:
            continue
        found = current(key)
        target = None if found is None else found.as_posix()
        if target is not None and target not in state.seen_versions:
            continue
        if target != slot.current_path:
            changes[slot.id] = target
    return changes


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _utc(value: datetime) -> str:
    """Return a time as UTC ISO 8601 text: such texts sort in time order."""
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _observe(
    connection: sqlite3.Connection, file_row: int, item: OwnFileWrite, moment: str
) -> None:
    """Add a file's observed state to its history unless it is the last one."""
    observed = (
        item.size_bytes,
        item.modified_ns,
        item.content_sha256,
        item.feature_count,
    )
    last = connection.execute(
        "SELECT seq, size_bytes, modified_ns, content_sha256, feature_count"
        " FROM own_file_states WHERE own_file_id = ? ORDER BY seq DESC LIMIT 1",
        (file_row,),
    ).fetchone()
    if last is not None and tuple(last[1:]) == observed:
        return
    seq = 1 if last is None else int(last[0]) + 1
    connection.execute(
        "INSERT INTO own_file_states (own_file_id, seq, observed_at, size_bytes,"
        " modified_ns, content_sha256, feature_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (file_row, seq, moment, *observed),
    )
    connection.execute(
        "DELETE FROM own_file_states WHERE own_file_id = ? AND seq <= ?",
        (file_row, seq - MAX_OWN_FILE_STATES),
    )


def _meta_row(meta: EntryMeta) -> tuple[object, ...]:
    """Values of ``_META_COLUMNS``; ``data_year`` never from ``downloaded_at``."""
    return (
        meta.label,
        meta.label_source,
        meta.sha256.lower() if meta.sha256 else None,
        meta.size_bytes,
        meta.data_year,
        None if meta.data_date is None else meta.data_date.isoformat(),
        _iso(meta.downloaded_at),
        meta.dataset,
        meta.dataset_key,
        meta.provider,
        meta.product,
        meta.country,
        meta.unit,
        meta.campaign,
        meta.survey_work_id,
        meta.edition,
        None if meta.full_sheet is None else int(meta.full_sheet),
        meta.coverage,
        meta.parent_request,
        meta.license,
        meta.attribution,
        json.dumps(list(meta.source_files)) if meta.source_files else None,
        meta.horizontal_crs,
        meta.vertical_crs,
        meta.resolution,
        meta.nodata,
    )


def _digest(row: tuple[object, ...]) -> int:
    """Signed 64-bit fingerprint of a metadata row: equal rows are not rewritten."""
    value = hashlib.blake2b(repr(row).encode(), digest_size=8).digest()
    return int.from_bytes(value, "big", signed=True)


def _raw_json(raw: Mapping[str, object] | None) -> str | None:
    if raw is None:
        return None
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"), default=str)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _location_rows(
    version_id: int, found: Footprint
) -> tuple[tuple[object, ...], tuple[object, ...] | None, tuple[object, ...] | None]:
    """Rows of ``versions`` location columns, ``version_shapes`` and the R*Tree."""
    if found.location == "footprint":
        bounds = polygon_bounds(found.wgs84)
        if found.wgs84 is not None and bounds is not None:
            box = is_box(found.wgs84, bounds)
            min_lon, min_lat, max_lon, max_lat = bounds
            location = (
                "footprint",
                None,
                found.source,
                found.native_crs,
                min_lon,
                min_lat,
                max_lon,
                max_lat,
                int(box),
                version_id,
            )
            wgs84 = None if box else _geojson(found.wgs84)
            native = None if found.native is None else _geojson(found.native)
            shape = (
                None
                if wgs84 is None and native is None
                else (version_id, wgs84, native)
            )
            return location, shape, (version_id, min_lon, max_lon, min_lat, max_lat)
        # An outline without usable coordinates locates nothing.
        return (
            ("none", "no_source", None, None, None, None, None, None, 0, version_id),
            None,
            None,
        )
    if found.location == "country":
        row = ("country", None, found.source, None, None, None, None, None, 0)
        return (*row, version_id), None, None
    reason = found.reason or "no_source"
    return (
        ("none", reason, None, None, None, None, None, None, 0, version_id),
        None,
        None,
    )


def _geojson(geometry: Mapping[str, object]) -> str:
    return json.dumps(geometry, separators=(",", ":"))


def _free_key(connection: sqlite3.Connection, name: str) -> str:
    """Return a project key from its name that no other project uses."""
    folded = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    ascii_name = folded.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-") or _PROJECT_KEY_FALLBACK
    taken = {
        str(key)
        for (key,) in connection.execute(
            "SELECT key FROM projects WHERE key = ? OR key LIKE ?",
            (base, f"{base}-%"),
        ).fetchall()
    }
    key, number = base, 1
    while key in taken:
        number += 1
        key = f"{base}-{number}"
    return key
