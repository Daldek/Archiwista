"""Snapshots of own-data files: the plan and the snapshot (plan v0.2, decision 9).

``check_snapshot`` is the plan (``SnapshotPlan``) without a single write: the
data folder valid (decision 8), the file there, the folder writable, free
space of at least 1.1 times the file, and whether the content the last scan
saw is that of the last snapshot. ``make_snapshot`` makes the snapshot, in
the worker of the ``snapshot`` job:

1. the plan's checks again (``SnapshotBlockedError``);
2. a consistent copy: a SQLite file by ``Connection.backup`` from the view of
   ``consistent_sqlite_read`` (states a, b, c of decision 8) into a file of
   the process's local work directory, made one file without a journal; any
   other file, and every member of a set, with the size and modification
   time of each before and after the copy (at most three attempts, else
   ``inconsistent_copy``);
3. the content identity of the copy (decision 8) and, for SQLite,
   ``PRAGMA integrity_check``; the content of the last snapshot is the result
   ``unchanged`` with its label, and nothing new stays in ``.wersje/``;
4. the copy in the working directory ``.wersje/.incoming/<host>_<pid>_<token>/``
   (a SQLite copy goes there as bytes), described by the reader process,
   the sums of its files read again, ``migawka.json``, every file ``0444``
   and synced, the directory synced;
5. publication: the first free label ``<YYYY-MM-DD>_<sha8>[_<n>]`` of the
   listing and one rename of the working directory that never replaces its
   target (``target_exists``);
6. the snapshot directory ``0555``.

A ``chmod`` or a directory sync the file system refuses (CIFS, ACLs) is a
warning, not an error. An error or an interrupt before the rename removes
the working directory; a killed process leaves it in ``.incoming/`` (a scan
reports it after 24 hours), never a label. Archiwista never replaces or
removes a snapshot. New directories of ``.wersje/`` get the permissions of
the data folder, so whoever reads the folder reads its snapshots.
"""

import contextlib
import ctypes
import errno
import hashlib
import json
import logging
import math
import os
import secrets
import shutil
import sqlite3
import stat
import sys
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import BinaryIO, Literal, cast, get_args

from archiwista.errors import (
    InconsistentReadError,
    PathOutsideRootError,
    ProducerError,
    SnapshotBlockedError,
    SnapshotFailedError,
)
from archiwista.formats import file_format
from archiwista.index import OwnFileDetail, OwnSnapshotRef, TransformerFactory
from archiwista.index.geometry import polygon_bounds
from archiwista.messages import MESSAGES
from archiwista.owndata.content import (
    CONTENT_METHODS,
    ContentIdentity,
    ContentMethod,
    FileStamp,
    SqliteRead,
    content_identity,
    content_method,
    fileset_sha256,
    read_sqlite,
)
from archiwista.owndata.document import (
    INCOMING_DIR,
    LABEL_PATTERN,
    MAX_NOTE_CHARS,
    SNAPSHOT_FILE,
    SNAPSHOTS_DIR,
    CopyMethod,
    InvalidSnapshotError,
    SnapshotAuthor,
    SnapshotContent,
    SnapshotCopy,
    SnapshotDocument,
    SnapshotExtent,
    SnapshotField,
    SnapshotFile,
    SnapshotLayer,
    SnapshotRaster,
    SnapshotSource,
    UnknownSnapshotSchemaError,
    read_snapshot_document,
    snapshot_files_match,
)
from archiwista.owndata.formats import fileset_members
from archiwista.owndata.reader import OwnFileInfo, OwnReader
from archiwista.owndata.scan import OwnFolderCheck, Wgs84Outlines
from archiwista.sandbox import process_owner
from archiwista.sources.registry import APP_DISTRIBUTION

logger = logging.getLogger(__name__)

type SnapshotStatus = Literal["created", "unchanged"]
type SnapshotBlockReason = Literal[
    "folder_invalid", "read_only_folder", "insufficient_space", "file_missing"
]
type SnapshotPhase = Literal["copy", "checksums", "document", "rename", "published"]

SNAPSHOT_PHASES: tuple[SnapshotPhase, ...] = get_args(SnapshotPhase.__value__)
# Free space a snapshot needs where its copies go, per byte of the file.
SPACE_FACTOR = 1.1
# Copies of a file or a set tried while its files keep changing.
COPY_ATTEMPTS = 3
# A published snapshot: its files and its directory read-only for everyone.
SNAPSHOT_FILE_MODE = 0o444
SNAPSHOT_DIRECTORY_MODE = 0o555

_CHUNK_BYTES = 1024**2
_SCRATCH_PREFIX = "snapshot-"
_O_BINARY = getattr(os, "O_BINARY", 0)
# What a file system refusing ``chmod`` or the sync of a directory answers
# (CIFS, ACLs): a warning, not an error.
_REFUSED = frozenset(
    {errno.EPERM, errno.EACCES, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}
)
_NO_SPACE = frozenset({errno.ENOSPC, errno.EDQUOT})
_RENAME_NOREPLACE = 1


@dataclass(frozen=True, slots=True)
class SnapshotBlock:
    """Why a snapshot cannot be made now: the reason and a Polish message."""

    reason: SnapshotBlockReason
    message: str


@dataclass(frozen=True, slots=True)
class SnapshotWarning:
    """What the person should know of a snapshot, not an error.

    ``code`` is ``editing_detected`` (the file is open in an editor, or one
    left it so: only committed changes are copied), ``chmod_refused`` (the
    file system keeps the snapshot writable) or ``directory_sync_refused``
    (it does not sync directories); ``message`` is Polish.
    """

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SnapshotPlan:
    """What a snapshot of a file would do (``check_snapshot``); nothing written.

    Attributes
    ----------
    path : str
        The working file relative to the data folder (``/`` separated, NFC).
    size_bytes : int
        Bytes to copy now: the file with its set's members, a SQLite file with
        its ``-wal``; the indexed size when the file cannot be reached.
    destination : Path
        Directory of the file's snapshots, ``<folder>/.wersje/<file>/``.
    copy_method : {"sqlite_backup", "files"}
        How the copy is made.
    content_method : {"sqlite", "fileset", "bytes"}
        How its content identity is computed (decision 8).
    unchanged_since : OwnSnapshotRef or None
        The last snapshot, when the last scan found its content in the file.
    blocked : SnapshotBlock or None
        Why the snapshot cannot be made now.
    free_bytes : int or None
        Free bytes where the snapshot goes; ``None`` when the folder or the
        file cannot be reached.
    warnings : tuple[SnapshotWarning, ...]
        ``editing_detected`` next to a SQLite ``-wal`` or hot ``-journal``.
    """

    path: str
    size_bytes: int
    destination: Path
    copy_method: CopyMethod
    content_method: ContentMethod
    unchanged_since: OwnSnapshotRef | None
    blocked: SnapshotBlock | None
    free_bytes: int | None
    warnings: tuple[SnapshotWarning, ...]


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """What ``make_snapshot`` did.

    Attributes
    ----------
    status : {"created", "unchanged"}
        A new snapshot, or the content of the last one.
    label : str
        The new snapshot's label, or the last one's.
    directory : Path
        Its directory, ``<folder>/.wersje/<file>/<label>/``.
    document : SnapshotDocument
        Its ``migawka.json``.
    warnings : tuple[SnapshotWarning, ...]
        Refused ``chmod`` and directory syncs, a file open in an editor.
    """

    status: SnapshotStatus
    label: str
    directory: Path
    document: SnapshotDocument
    warnings: tuple[SnapshotWarning, ...]


def folder_block(folder: OwnFolderCheck) -> SnapshotBlock | None:
    """Return why a data folder takes no snapshot now; ``None`` when it does.

    A folder breaking the rules of decision 8 is ``folder_invalid``; one that
    is missing or cannot be read holds no file to copy (``file_missing``).
    """
    if folder.state == "invalid":
        reason = MESSAGES.get(f"own_folder_reason_{folder.reason}", str(folder.reason))
        message = MESSAGES["snapshot_blocked_folder_invalid"].format(
            path=folder.path, reason=reason
        )
        return SnapshotBlock("folder_invalid", message)
    if folder.state != "ok":
        message = MESSAGES["snapshot_blocked_folder_unavailable"].format(
            path=folder.path
        )
        return SnapshotBlock("file_missing", message)
    return None


def check_snapshot(
    folder: OwnFolderCheck, file: OwnFileDetail, *, work_dir: Path
) -> SnapshotPlan:
    """Plan a snapshot of an own-data file without writing anything.

    Parameters
    ----------
    folder : OwnFolderCheck
        The project's data folder checked now (``check_own_folder``).
    file : OwnFileDetail
        The file as the index knows it; its change against the last
        snapshot is the last scan's.
    work_dir : Path
        The local work directory where the copy of a SQLite file is made.

    Returns
    -------
    SnapshotPlan
        The plan, ``blocked`` with the reason a snapshot would be refused.

    Raises
    ------
    PathOutsideRootError
        The file, a member of its set or ``.wersje/`` is a symbolic link
        leading out of the data folder.
    """
    inspection = _inspect(folder, file, work_dir)
    working = inspection.working
    method = _indexed_method(file) if working is None else working.method
    return SnapshotPlan(
        path=file.file.path,
        size_bytes=file.file.size_bytes if working is None else working.size_bytes,
        destination=folder.path / SNAPSHOTS_DIR / file.disk_path,
        copy_method=_copy_method(method),
        content_method=method,
        unchanged_since=file.file.last_snapshot
        if file.file.change == "unchanged"
        else None,
        blocked=inspection.block,
        free_bytes=inspection.free_bytes,
        warnings=inspection.warnings,
    )


def make_snapshot(
    folder: OwnFolderCheck,
    file: OwnFileDetail,
    *,
    author: SnapshotAuthor,
    note: str,
    work_dir: Path,
    reader: OwnReader,
    transformer: TransformerFactory | None,
    on_phase: Callable[[SnapshotPhase], None] | None = None,
) -> SnapshotResult:
    """Make a snapshot of an own-data file in ``<folder>/.wersje/`` (see the module).

    Parameters
    ----------
    folder : OwnFolderCheck
        The project's data folder checked now (``check_own_folder``).
    file : OwnFileDetail
        The file as the index knows it (its path and its name on the disk).
    author : SnapshotAuthor
        Who asked for the snapshot.
    note : str
        The person's description, at most ``MAX_NOTE_CHARS`` characters.
    work_dir : Path
        This process's local work directory (``process_work_dir``): the
        copy of a SQLite file is made there, never on a share.
    reader : OwnReader
        The reader process describing the copy (layers, raster, extent).
    transformer : TransformerFactory or None
        The producer's pinned operations to WGS84 for the extent.
    on_phase : Callable[[SnapshotPhase], None] or None, optional
        Called as each phase is done: ``copy`` (the copy is in the working
        directory), ``checksums`` (its files read again and equal),
        ``document`` (``migawka.json`` written), ``rename`` (every file
        read-only and synced; the rename comes next) and ``published``
        (renamed to its label). The job reports progress with it; tests
        interrupt the snapshot there.

    Returns
    -------
    SnapshotResult
        ``created``, or ``unchanged`` with the last snapshot when the copy
        has its content (nothing new in ``.wersje/``).

    Raises
    ------
    SnapshotBlockedError
        The folder is invalid, missing or read-only, the file is missing, or
        there is not enough space.
    SnapshotFailedError
        ``inconsistent_copy``, ``checksum_mismatch``, ``integrity_failed`` or
        ``target_exists``; nothing was published.
    PathOutsideRootError
        The file, a member of its set or ``.wersje/`` leads out of the folder.
    OwnReaderError
        The reader process cannot be started.
    ValueError
        A note longer than ``MAX_NOTE_CHARS``.
    """
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"a note has at most {MAX_NOTE_CHARS} characters")
    inspection = _inspect(folder, file, work_dir)
    if inspection.block is not None:
        raise SnapshotBlockedError(inspection.block.reason, inspection.block.message)
    assert inspection.working is not None
    scratch = work_dir / f"{_SCRATCH_PREFIX}{secrets.token_hex(8)}"
    scratch.mkdir(mode=0o700)
    try:
        return _Snapshot(
            working=inspection.working,
            file=file,
            author=author,
            note=note,
            scratch=scratch,
            reader=reader,
            outlines=Wgs84Outlines(transformer),
            on_phase=on_phase,
        ).make()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@dataclass(frozen=True, slots=True)
class _Working:
    """The working file of a snapshot as it is on the disk now.

    ``root`` and ``real`` are the data folder and the file after
    ``realpath``; ``members`` the files to copy (the file, or every member
    of its set); ``size_bytes`` their bytes with a SQLite ``-wal``;
    ``editing``: a SQLite ``-wal`` or hot ``-journal`` lies next to it.
    """

    root: Path
    real: Path
    members: tuple[Path, ...]
    method: ContentMethod
    size_bytes: int
    editing: bool


@dataclass(frozen=True, slots=True)
class _Inspection:
    """The checks of a plan: the file, why it is blocked, space and warnings."""

    working: _Working | None
    block: SnapshotBlock | None = None
    free_bytes: int | None = None
    warnings: tuple[SnapshotWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class _Copy:
    """A consistent copy: its files, the working file before it, its content."""

    files: tuple[SnapshotFile, ...]
    source: FileStamp
    identity: ContentIdentity


@dataclass(frozen=True, slots=True)
class _Backup:
    """The checked backup of a SQLite file in the scratch directory."""

    path: Path
    source: FileStamp
    identity: ContentIdentity


def _inspect(
    folder: OwnFolderCheck, file: OwnFileDetail, work_dir: Path
) -> _Inspection:
    """Check the folder, the file, write access and space, in this order."""
    block = folder_block(folder)
    if block is not None:
        return _Inspection(None, block)
    working = _working(folder, file)
    if working is None:
        message = MESSAGES["snapshot_blocked_file_missing"].format(
            file=file.file.path, path=folder.path
        )
        return _Inspection(None, SnapshotBlock("file_missing", message))
    warnings: tuple[SnapshotWarning, ...] = ()
    if working.editing:
        message = MESSAGES["snapshot_editing_detected"].format(file=file.file.path)
        warnings = (SnapshotWarning("editing_detected", message),)
    free = shutil.disk_usage(working.root).free
    versions = working.root / SNAPSHOTS_DIR
    for directory in (versions / file.disk_path, versions / INCOMING_DIR):
        refused = _not_writable(working.root, directory)
        if refused is not None:
            message = MESSAGES["snapshot_blocked_read_only_folder"].format(path=refused)
            block = SnapshotBlock("read_only_folder", message)
            return _Inspection(working, block, free, warnings)
    needed = math.ceil(SPACE_FACTOR * working.size_bytes)
    if free < needed:
        message = MESSAGES["snapshot_blocked_insufficient_space"].format(
            path=folder.path, needed=_megabytes(needed), free=_megabytes(free)
        )
        block = SnapshotBlock("insufficient_space", message)
        return _Inspection(working, block, free, warnings)
    if working.method == "sqlite":
        # In states (b) and (c) the view's copy and the backup coexist.
        local_needed = needed * (2 if working.editing else 1)
        local_free = shutil.disk_usage(work_dir).free
        if local_free < local_needed:
            message = MESSAGES["snapshot_blocked_insufficient_work_space"].format(
                path=work_dir,
                needed=_megabytes(local_needed),
                free=_megabytes(local_free),
            )
            block = SnapshotBlock("insufficient_space", message)
            return _Inspection(working, block, free, warnings)
    return _Inspection(working, None, free, warnings)


def _working(folder: OwnFolderCheck, file: OwnFileDetail) -> _Working | None:
    """Find the working file and its members now; ``None``: no such file.

    Raises
    ------
    PathOutsideRootError
        The file or a member leads out of the folder.
    """
    root = Path(os.path.realpath(folder.path))
    real = Path(os.path.realpath(root / file.disk_path))
    if not real.is_relative_to(root):
        raise _outside(file.file.path)
    try:
        if not stat.S_ISREG(os.stat(real).st_mode):
            return None
        method = content_method(real)
        members = fileset_members(real) if method == "fileset" else (real,)
        sizes = [os.stat(member).st_size for member in members]
        wal = _companion_size(real, "-wal") if method == "sqlite" else None
        journal = _companion_size(real, "-journal") if method == "sqlite" else None
    except OSError:
        return None
    for member in members[1:]:
        if not Path(os.path.realpath(member)).is_relative_to(root):
            raise _outside(file.file.path)
    return _Working(
        root=root,
        real=real,
        members=members,
        method=method,
        size_bytes=sum(sizes) + (wal or 0),
        editing=wal is not None or bool(journal),
    )


def _companion_size(path: Path, suffix: str) -> int | None:
    """Bytes of a SQLite companion next to ``path``; ``None`` without one."""
    try:
        return os.stat(path.with_name(f"{path.name}{suffix}")).st_size
    except FileNotFoundError:
        return None


def _not_writable(root: Path, directory: Path) -> Path | None:
    """Return the directory keeping new entries out of ``directory``, if any.

    The nearest existing directory on the way from ``root`` must be one this
    process may write and enter.

    Raises
    ------
    PathOutsideRootError
        A symbolic link on the way.
    """
    current = root
    for part in directory.relative_to(root).parts:
        step = current / part
        try:
            found = os.lstat(step)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(found.st_mode):
            raise _outside(step.relative_to(root).as_posix())
        if not stat.S_ISDIR(found.st_mode):
            return step
        current = step
    if os.access(current, os.W_OK | os.X_OK):
        return None
    return current


@dataclass(frozen=True, slots=True)
class _Destination:
    """Opened project and incoming directories for one snapshot's writes."""

    root_fd: int
    incoming_fd: int
    work_fd: int
    path: Path



@dataclass(slots=True)
class _Snapshot:
    """One snapshot being made (``make_snapshot``)."""

    working: _Working
    file: OwnFileDetail
    author: SnapshotAuthor
    note: str
    scratch: Path
    reader: OwnReader
    outlines: Wgs84Outlines
    on_phase: Callable[[SnapshotPhase], None] | None
    warnings: dict[str, SnapshotWarning] = field(default_factory=dict)

    @property
    def parent(self) -> Path:
        """``<folder>/.wersje/<file>/``: the file's snapshots."""
        return self.working.root / SNAPSHOTS_DIR / self.file.disk_path

    def make(self) -> SnapshotResult:
        """Copy, compare with the last snapshot, describe, write and publish."""
        backup: _Backup | None = None
        if self.working.method == "sqlite":
            backup = self._sqlite_backup()
            unchanged = self._unchanged(backup.identity)
            if unchanged is not None:
                return unchanged
        with self._incoming() as destination:
            work = destination.path
            published = False
            try:
                with self._writes():
                    if backup is None:
                        copy = self._files_copy(work, destination.work_fd)
                    else:
                        copied = _copy_hashed(
                            backup.path, work / backup.path.name,
                            dir_fd=destination.work_fd,
                        )
                        copy = _Copy((copied,), backup.source, backup.identity)
                if backup is None:
                    unchanged = self._unchanged(copy.identity)
                    if unchanged is not None:
                        return unchanged
                self._reached("copy")
                described = work / self.working.real.name if backup is None else backup.path
                info = self._describe(described)
                self._verify(destination.work_fd, copy.files)
                self._reached("checksums")
                document = self._document(copy, info)
                with self._writes():
                    _write_new(
                        work / SNAPSHOT_FILE, _document_bytes(document),
                        dir_fd=destination.work_fd,
                    )
                self._reached("document")
                for name in (*(item.name for item in copy.files), SNAPSHOT_FILE):
                    descriptor = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | _O_BINARY,
                        dir_fd=destination.work_fd,
                    )
                    try:
                        self._chmod(descriptor, SNAPSHOT_FILE_MODE)
                    finally:
                        os.close(descriptor)
                self._sync_directory(destination.work_fd)
                self._reached("rename")
                with self._writes(access=True):
                    with self._directories(self.parent, destination.root_fd) as parent_fd:
                        target = self._publish(destination, document.label, parent_fd)
                        published = True
                        self._reached("published")
                        self._chmod(
                            destination.work_fd, SNAPSHOT_DIRECTORY_MODE,
                            published=True,
                        )
                        self._sync_directory(parent_fd, published=True)
                return SnapshotResult(
                    "created", document.label, target, document, self._warnings()
                )
            finally:
                if not published:
                    shutil.rmtree(
                        work.name, dir_fd=destination.incoming_fd, ignore_errors=True
                    )

    def _sqlite_backup(self) -> _Backup:
        """Back a SQLite file up into the scratch directory, one file, checked."""
        local = self.scratch / self.working.real.name

        def backup(view: SqliteRead) -> SqliteRead:
            local.unlink(missing_ok=True)
            _backup(view, local)
            return view

        try:
            view = read_sqlite(self.working.real, backup, work_dir=self.scratch)
            problems = _integrity_problems(local)
        except InconsistentReadError as error:
            raise self._inconsistent() from error
        except sqlite3.OperationalError:
            raise
        except sqlite3.DatabaseError as error:  # not a database, malformed
            raise self._damaged([str(error)]) from error
        if problems:
            raise self._damaged(problems)
        identity = content_identity([local], method="sqlite", work_dir=self.scratch)
        if view.state != "in_place":
            message = MESSAGES["snapshot_editing_detected"].format(
                file=self.file.file.path
            )
            self._warn("editing_detected", message)
        return _Backup(local, view.source, identity)

    def _files_copy(self, work: Path, work_fd: int) -> _Copy:
        """Copy the file, or every member of its set, while none of them changes."""
        members = self.working.members
        for _ in range(COPY_ATTEMPTS):
            before = _stamps(members)
            try:
                files = tuple(
                    _copy_hashed(member, work / member.name, dir_fd=work_fd)
                    for member in members
                )
            except FileNotFoundError:  # a member went away: the set changed
                files = ()
            if files and before is not None and _stamps(members) == before:
                if self.working.method == "fileset":
                    pairs = ((item.name, item.sha256) for item in files)
                    identity = ContentIdentity("fileset", fileset_sha256(pairs))
                else:
                    identity = ContentIdentity("bytes", files[0].sha256)
                size = sum(stamp.size_bytes for stamp in before)
                return _Copy(files, FileStamp(size, before[0].modified_ns), identity)
            for member in members:
                try:
                    os.unlink(member.name, dir_fd=work_fd)
                except FileNotFoundError:
                    pass
        raise self._inconsistent()

    def _unchanged(self, identity: ContentIdentity) -> SnapshotResult | None:
        """Return the last snapshot if it holds this content and is intact."""
        last = self._last()
        if last is None:
            return None
        directory, document = last
        content = (document.content.method, document.content.sha256)
        if content != (identity.method, identity.sha256):
            return None
        if not snapshot_files_match(directory, document.files):
            return None  # damaged: a new snapshot keeps the content
        return SnapshotResult(
            "unchanged", document.label, directory, document, self._warnings()
        )

    def _last(self) -> tuple[Path, SnapshotDocument] | None:
        """Return the newest snapshot of the file with a valid document.

        Newest by ``created_at``, then by label; the directory on the disk is
        the source of truth, whatever the index knows.
        """
        try:
            with os.scandir(self.parent) as scanned:
                entries = [
                    Path(entry.path)
                    for entry in scanned
                    if LABEL_PATTERN.fullmatch(entry.name)
                    and entry.is_dir(follow_symlinks=False)
                ]
        except (FileNotFoundError, NotADirectoryError):
            return None
        found: list[tuple[datetime, str, Path, SnapshotDocument]] = []
        for directory in entries:
            try:
                _, document = read_snapshot_document(directory)
            except (InvalidSnapshotError, UnknownSnapshotSchemaError, OSError):
                continue
            path = unicodedata.normalize("NFC", document.source.path)
            if document.label == directory.name and path == self.file.file.path:
                found.append((document.created_at, directory.name, directory, document))
        if not found:
            return None
        _, _, directory, document = max(found, key=lambda item: (item[0], item[1]))
        return directory, document

    @contextlib.contextmanager
    def _incoming(self) -> Iterator[_Destination]:
        """Open the project's snapshot directories and create one working directory."""
        with contextlib.ExitStack() as stack:
            with self._writes(access=True):
                root_fd = os.open(
                    self.working.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
                stack.callback(os.close, root_fd)
                incoming = self.working.root / SNAPSHOTS_DIR / INCOMING_DIR
                incoming_fd = stack.enter_context(self._directories(incoming, root_fd))
                work = incoming / f"{process_owner()}_{secrets.token_hex(8)}"
                os.mkdir(work.name, mode=0o700, dir_fd=incoming_fd)
                try:
                    work_fd = os.open(
                        work.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=incoming_fd,
                    )
                except BaseException:
                    shutil.rmtree(work.name, dir_fd=incoming_fd, ignore_errors=True)
                    raise
                stack.callback(os.close, work_fd)
            yield _Destination(root_fd, incoming_fd, work_fd, work)

    @contextlib.contextmanager
    def _directories(self, directory: Path, root_fd: int) -> Iterator[int]:
        """Create and open each child relative to its verified parent, without links.

        New directories get the data folder's permissions (subject to the umask).
        Every descriptor remains open until the caller has finished using it.
        """
        root = self.working.root
        permissions = stat.S_IMODE(os.fstat(root_fd).st_mode) & 0o777
        current_fd = root_fd
        current = root
        with contextlib.ExitStack() as opened:
            for part in directory.relative_to(root).parts:
                current /= part
                try:
                    os.mkdir(part, permissions, dir_fd=current_fd)
                    created = True
                except FileExistsError:
                    created = False
                try:
                    child_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current_fd,
                    )
                except OSError as error:
                    if error.errno in (errno.ELOOP, errno.ENOTDIR):
                        found = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
                        if stat.S_ISLNK(found.st_mode):
                            raise _outside(current.relative_to(root).as_posix()) from error
                        if not stat.S_ISDIR(found.st_mode):
                            raise FileExistsError(
                                errno.EEXIST, os.strerror(errno.EEXIST), str(current)
                            ) from error
                    raise
                opened.callback(os.close, child_fd)
                current_fd = child_fd
                if created:
                    mode = stat.S_IMODE(os.fstat(child_fd).st_mode)
                    if mode & 0o777 != permissions:
                        self._chmod(child_fd, (mode & ~0o777) | permissions)
            yield current_fd

    def _describe(self, path: Path) -> OwnFileInfo:
        """Read the copy in the reader process; a non-GDAL file is not read."""
        fmt = file_format(path)
        if fmt.driver is None:
            return OwnFileInfo(fmt.kind, None, (path.name,))
        return self.reader.read(path)

    def _verify(self, work_fd: int, files: tuple[SnapshotFile, ...]) -> None:
        """Read the written files again: exactly these names, sizes and sums."""
        expected = {item.name: item for item in files}
        stray = sorted(set(os.listdir(work_fd)) ^ expected.keys())
        if stray:
            raise self._mismatch(stray[0])
        for name, item in expected.items():
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | _O_BINARY, dir_fd=work_fd
            )
            with os.fdopen(descriptor, "rb") as reading:
                if os.fstat(reading.fileno()).st_size != item.size_bytes:
                    raise self._mismatch(name)
                digest = hashlib.sha256()
                while chunk := reading.read(_CHUNK_BYTES):
                    digest.update(chunk)
                if digest.hexdigest() != item.sha256:
                    raise self._mismatch(name)

    def _document(self, copy: _Copy, info: OwnFileInfo) -> SnapshotDocument:
        """``migawka.json`` of the copy, labelled from the listing of ``.wersje``."""
        created_at = datetime.now().astimezone().replace(microsecond=0)
        modified_at = datetime.fromtimestamp(
            copy.source.modified_ns / 1_000_000_000
        ).astimezone()
        method = self.working.method
        return SnapshotDocument(
            label=self._free_label(created_at, copy.identity),
            created_at=created_at,
            author=self.author,
            note=self.note,
            source=SnapshotSource(
                path=self.file.file.path,
                format=info.driver,
                size_bytes=copy.source.size_bytes,
                modified_at=modified_at.replace(microsecond=0),
            ),
            content=SnapshotContent(
                method=copy.identity.method, sha256=copy.identity.sha256
            ),
            copy=SnapshotCopy(method=_copy_method(method)),
            files=list(copy.files),
            size_bytes=sum(item.size_bytes for item in copy.files),
            layers=_layers(info),
            raster=_raster(info),
            feature_count=info.feature_count,
            extent=self._extent(info),
            archiwista=version(APP_DISTRIBUTION),
        )

    def _free_label(self, created_at: datetime, identity: ContentIdentity) -> str:
        """``<YYYY-MM-DD>_<sha8>``, or with ``_<n>`` the first one not listed."""
        base = f"{created_at:%Y-%m-%d}_{identity.sha256[:8]}"
        try:
            taken = set(os.listdir(self.parent))
        except (FileNotFoundError, NotADirectoryError):
            taken = set()
        label, number = base, 2
        while label in taken:
            label, number = f"{base}_{number}", number + 1
        return label

    def _extent(self, info: OwnFileInfo) -> SnapshotExtent | None:
        """Return the copy's extent in its CRS and in WGS84 (the pinned operation)."""
        if info.native_bbox is None:
            return None
        wgs84 = None
        if info.native_crs is not None:
            try:
                outline = self.outlines.outline(info.native_bbox, info.native_crs)
                wgs84 = polygon_bounds(outline)
            except (ProducerError, ValueError) as error:
                logger.info("No WGS84 extent for %s: %s", info.native_crs[:80], error)
        return SnapshotExtent(crs=info.native_crs, bbox=info.native_bbox, wgs84=wgs84)

    def _publish(self, destination: _Destination, label: str, parent_fd: int) -> Path:
        """Rename the working directory under the opened snapshot parent."""
        target = self.parent / label
        try:
            _rename_exclusive(
                destination.path.name, label,
                src_dir_fd=destination.incoming_fd, dst_dir_fd=parent_fd,
            )
        except FileExistsError as error:
            message = MESSAGES["snapshot_target_exists"].format(
                label=label, file=self.file.file.path
            )
            raise SnapshotFailedError("target_exists", message) from error
        return target

    def _chmod(self, descriptor: int, mode: int, *, published: bool = False) -> None:
        """Change a mode; a refusal of the file system is a warning.

        After publication any failure is one: the snapshot exists already.
        """
        try:
            os.fchmod(descriptor, mode)
        except OSError as error:
            if not published and error.errno not in _REFUSED:
                raise
            detail = error.strerror or type(error).__name__
            message = MESSAGES["snapshot_chmod_refused"].format(detail=detail)
            self._warn("chmod_refused", message)

    def _sync_directory(self, descriptor: int, *, published: bool = False) -> None:
        """Sync a directory's entries; a refusal of the file system is a warning."""
        try:
            os.fsync(descriptor)
        except OSError as error:
            if not published and error.errno not in _REFUSED:
                raise
            detail = error.strerror or type(error).__name__
            message = MESSAGES["snapshot_directory_sync_refused"].format(detail=detail)
            self._warn("directory_sync_refused", message)

    @contextlib.contextmanager
    def _writes(self, *, access: bool = False) -> Iterator[None]:
        """Turn a full disk or a read-only file system into a block.

        With ``access`` (directories made in ``.wersje``) a refused write is
        a read-only folder too; elsewhere such an error may come from reading.
        """
        try:
            yield
        except OSError as error:
            if error.errno in _NO_SPACE:
                needed = math.ceil(SPACE_FACTOR * self.working.size_bytes)
                message = MESSAGES["snapshot_blocked_insufficient_space"].format(
                    path=self.working.root,
                    needed=_megabytes(needed),
                    free=_megabytes(shutil.disk_usage(self.working.root).free),
                )
                raise SnapshotBlockedError("insufficient_space", message) from error
            refused = {errno.EROFS, errno.EACCES, errno.EPERM} if access else set()
            if error.errno == errno.EROFS or error.errno in refused:
                message = MESSAGES["snapshot_blocked_read_only_folder"].format(
                    path=error.filename or self.working.root
                )
                raise SnapshotBlockedError("read_only_folder", message) from error
            raise

    def _reached(self, phase: SnapshotPhase) -> None:
        if self.on_phase is not None:
            self.on_phase(phase)

    def _warn(self, code: str, message: str) -> None:
        self.warnings.setdefault(code, SnapshotWarning(code, message))

    def _warnings(self) -> tuple[SnapshotWarning, ...]:
        return tuple(self.warnings.values())

    def _inconsistent(self) -> SnapshotFailedError:
        message = MESSAGES["snapshot_inconsistent_copy"].format(
            file=self.file.file.path
        )
        return SnapshotFailedError("inconsistent_copy", message)

    def _mismatch(self, name: str) -> SnapshotFailedError:
        message = MESSAGES["snapshot_checksum_mismatch"].format(name=name)
        return SnapshotFailedError("checksum_mismatch", message)

    def _damaged(self, problems: list[str]) -> SnapshotFailedError:
        message = MESSAGES["snapshot_integrity_failed"].format(
            file=self.file.file.path, detail="; ".join(problems[:3])[:300]
        )
        return SnapshotFailedError("integrity_failed", message)


def _backup(view: SqliteRead, target: Path) -> None:
    """Back up the view into ``target``: one file without a journal (DELETE mode).

    A backup keeps the source's header, so a database in WAL mode would
    stay one and need ``-wal`` and ``-shm`` to be opened read-only.
    """
    source = view.connect()
    try:
        copy = sqlite3.connect(target)
        try:
            source.backup(copy)
            copy.execute("PRAGMA journal_mode=DELETE").fetchone()
        finally:
            copy.close()
    finally:
        source.close()


def _integrity_problems(path: Path) -> list[str]:
    """``PRAGMA integrity_check`` of a local copy: ``[]`` when it is ``ok``."""
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
    finally:
        connection.close()
    return [] if rows == ["ok"] else rows


def _copy_hashed(source: Path, target: Path, *, dir_fd: int) -> SnapshotFile:
    """Copy a file into the opened directory, synced; return its SHA-256."""
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reading, _new_file(target, dir_fd=dir_fd) as writing:
        while chunk := reading.read(_CHUNK_BYTES):
            digest.update(chunk)
            writing.write(chunk)
            size += len(chunk)
    return SnapshotFile(name=target.name, size_bytes=size, sha256=digest.hexdigest())


def _write_new(path: Path, data: bytes, *, dir_fd: int) -> None:
    """Write a new file into the opened directory and sync it."""
    with _new_file(path, dir_fd=dir_fd) as stream:
        stream.write(data)


@contextlib.contextmanager
def _new_file(path: Path, *, dir_fd: int) -> Iterator[BinaryIO]:
    """Create a file that must not exist; sync and close it after the block."""
    descriptor = os.open(
        path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _O_BINARY,
        0o600, dir_fd=dir_fd,
    )
    with os.fdopen(descriptor, "wb") as stream:
        yield stream
        stream.flush()
        os.fsync(stream.fileno())


def _document_bytes(document: SnapshotDocument) -> bytes:
    """``migawka.json``: exactly the schema's fields, UTF-8, indented for people."""
    data = document.model_dump(mode="json", by_alias=True)
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _stamps(paths: tuple[Path, ...]) -> list[FileStamp] | None:
    """Size and modification time of each file; ``None`` when one is gone."""
    try:
        found = [os.stat(path) for path in paths]
    except FileNotFoundError:
        return None
    return [FileStamp(item.st_size, item.st_mtime_ns) for item in found]


def _layers(info: OwnFileInfo) -> list[SnapshotLayer] | None:
    """Return the vector layers the reader read; ``None`` for no vector read."""
    if info.kind != "vector" or info.driver is None or info.error is not None:
        return None
    return [
        SnapshotLayer(
            name=layer.name,
            geometry_type=layer.geometry_type,
            feature_count=layer.feature_count,
            crs=layer.crs,
            fields=[
                SnapshotField(name=item.name, type=item.type) for item in layer.fields
            ],
        )
        for layer in info.layers
    ]


def _raster(info: OwnFileInfo) -> SnapshotRaster | None:
    raster = info.raster
    if raster is None:
        return None
    return SnapshotRaster(
        width=raster.width,
        height=raster.height,
        bands=raster.bands,
        dtype=raster.dtype,
        crs=info.native_crs,
        resolution=raster.pixel_size,
        nodata=raster.nodata,
    )


def _indexed_method(file: OwnFileDetail) -> ContentMethod:
    """Return the content method the index knows, else by the set's members."""
    for method in CONTENT_METHODS:
        if file.content_method == method:
            return method
    return "fileset" if len(file.members) > 1 else "bytes"


def _copy_method(method: ContentMethod) -> CopyMethod:
    return "sqlite_backup" if method == "sqlite" else "files"


def _outside(path: str) -> PathOutsideRootError:
    return PathOutsideRootError(MESSAGES["problem_path_outside_root"].format(path=path))


def _megabytes(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB".replace(".", ",")


def _load_renameat2() -> Callable[..., int] | None:
    """Linux's ``renameat2``, which can refuse to replace its target."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError):
        return None
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    return cast(Callable[..., int], function)


_RENAMEAT2 = _load_renameat2()


def _rename_exclusive(
    source: str, target: str, *, src_dir_fd: int, dst_dir_fd: int
) -> None:
    """Rename a directory by its parent descriptors; never replace the target.

    ``renameat2`` with ``RENAME_NOREPLACE`` where Linux and the file system
    have it; else a look at ``target`` and ``rename``, which refuses a
    directory that is not empty (a published snapshot never is).

    Raises
    ------
    FileExistsError
        ``target`` exists.
    """
    if _RENAMEAT2 is not None:
        old, new = os.fsencode(source), os.fsencode(target)
        if _RENAMEAT2(src_dir_fd, old, dst_dir_fd, new, _RENAME_NOREPLACE) == 0:
            return
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(code, os.strerror(code), target)
        if code not in (errno.EINVAL, errno.ENOSYS):
            raise OSError(code, os.strerror(code), source)
    try:
        os.stat(target, dir_fd=dst_dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), target)
    try:
        os.rename(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    except OSError as error:
        if error.errno in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(error.errno, error.strerror, target) from error
        raise
