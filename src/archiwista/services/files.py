"""Files people download over HTTP (plan v0.4 C11, A-ADR-047 decision 5).

``version_file``, ``own_file`` and ``snapshot_file`` find the file of a store
version, of an own-data working file (or one file of its set, ``member``) and
of a snapshot as ``refs.ObjectResolver.resolve`` resolves it: only what the
index knows and the principal sees (else ``404``), its real path inside its
root (a symbolic link leaving it is ``403 path_outside_root``), a working file
unchanged since its scan (else ``409 own_file_changed``). A file the index
lists but the disk has no more is ``404`` (reason ``missing_file``); a working
file its scan could not read and a snapshot that is not valid are ``409``
(reason ``file_unreadable``). The media type is the registered type of the
file's format (``archiwista.formats``), else that of Python's own table (the
system's tables call an ASCII grid a PGP key), else
``application/octet-stream``.

``FileStreams`` counts the downloads each person streams: at most
``FILE_DOWNLOADS_PER_PERSON`` at once (an agent counts as its account), a
further one is ``429 rate_limited`` (reason ``too_many_downloads``) with
``Retry-After`` of ``RETRY_AFTER_S``.
"""

import mimetypes
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from archiwista.auth import Principal
from archiwista.errors import (
    ConflictError,
    NotFoundError,
    PreviewUnavailableError,
    RateLimitedError,
)
from archiwista.formats import file_format
from archiwista.index import OwnFileDetail
from archiwista.messages import message
from archiwista.previews.types import PreviewSource
from archiwista.refs import (
    FileRef,
    ObjectResolver,
    SnapshotRef,
    format_ref,
    own_file_changed,
    snapshot_files,
    version_ref,
)

FILE_DOWNLOADS_PER_PERSON = 2
RETRY_AFTER_S = 10
OCTET_STREAM = "application/octet-stream"
# Python's own table only: no system file is read.
_TYPES = mimetypes.MimeTypes()


@dataclass(frozen=True, slots=True)
class FileDownload:
    """A file to send.

    Attributes
    ----------
    path : Path
        Its real path, inside its root.
    name : str
        The name it is saved under.
    media_type : str
        Its ``Content-Type``.
    ref : str
        The object it belongs to (``version:…``, ``file:…``, ``snapshot:…``),
        the target of its entry in the action log.
    """

    path: Path
    name: str
    media_type: str
    ref: str


def media_type(name: str) -> str:
    """Return the media type of a file by its name (see the module)."""
    found = file_format(name).media_type or _TYPES.guess_type(name)[0]
    return found or OCTET_STREAM


def version_file(
    resolver: ObjectResolver, store: str, version: str, *, principal: Principal
) -> FileDownload:
    """Return the file of a store version.

    Raises
    ------
    NotFoundError
        A version the index does not know, or its file gone from the store.
    PathOutsideRootError
        Its file resolves outside the store.
    SourceUnavailableError
        The store is not configured or cannot be reached.
    """
    ref = version_ref(store, version)
    source = _resolved(resolver, ref, principal)
    name = PurePosixPath(version).name
    return FileDownload(source.paths[0], name, media_type(name), ref)


def own_file(
    resolver: ObjectResolver,
    project: str,
    detail: OwnFileDetail,
    *,
    principal: Principal,
    member: str | None = None,
) -> FileDownload:
    """Return an own-data working file, or the file ``member`` of its set.

    Parameters
    ----------
    detail : OwnFileDetail
        The file as the index lists it for a principal who sees its project.
    member : str or None, optional
        The name of one file of its set (``OwnFileCard.members``); the main
        file when omitted.

    Raises
    ------
    NotFoundError
        A ``member`` the index does not list for it, or its file gone.
    OwnFileChangedError
        It changed since its scan.
    PathOutsideRootError, SourceUnavailableError, ConflictError
        As the module says.
    """
    ref = FileRef(project, detail.file.path)
    source = _resolved(resolver, format_ref(ref), principal)
    if member is None:
        return _download(source.paths[0], PurePosixPath(detail.file.path).name, ref)
    listed = {_nfc(PurePosixPath(item).name) for item in detail.members}
    on_disk = {_nfc(path.name): path for path in source.paths}
    wanted = _nfc(member)
    if wanted not in listed:
        raise _no_member(format_ref(ref), member)
    if wanted not in on_disk:
        raise own_file_changed(ref)
    return _download(on_disk[wanted], wanted, ref)


def snapshot_file(
    resolver: ObjectResolver,
    project: str,
    detail: OwnFileDetail,
    label: str,
    *,
    principal: Principal,
    member: str | None = None,
) -> FileDownload:
    """Return the main file of a snapshot, or its file ``member``.

    Parameters
    ----------
    detail : OwnFileDetail
        The working file as the index lists it for a principal who sees its
        project.
    label : str
        The snapshot.
    member : str or None, optional
        The name of one of its files (``SnapshotItem.members``); the main file
        when omitted.

    Raises
    ------
    NotFoundError
        No snapshot ``label`` of the file, or no file ``member`` in it.
    PathOutsideRootError, ConflictError
        As the module says.
    """
    ref = SnapshotRef(project, label, detail.file.path)
    source = _resolved(resolver, format_ref(ref), principal)
    record = next(item for item in detail.snapshots if item.label == label)
    names = [name for name, _ in snapshot_files(record)]
    place = 0 if member is None else _place(names, member, format_ref(ref))
    return _download(source.paths[place], names[place], ref)


class FileStreams:
    """The downloads each person streams now (``app.state.file_streams``).

    Parameters
    ----------
    limit : int, optional
        How many one person may stream at once.
    """

    def __init__(self, limit: int = FILE_DOWNLOADS_PER_PERSON) -> None:
        self._limit = limit
        self._open: Counter[str] = Counter()
        self._lock = threading.Lock()

    def start(self, person: str) -> Callable[[], None]:
        """Count a download of ``person``; return what ends it (once).

        Raises
        ------
        RateLimitedError
            The person streams ``limit`` downloads already (reason
            ``too_many_downloads``).
        """
        with self._lock:
            if self._open[person] >= self._limit:
                raise RateLimitedError(
                    message("api.too_many_downloads", limit=self._limit),
                    retry_after_s=RETRY_AFTER_S,
                    reason="too_many_downloads",
                )
            self._open[person] += 1
        ended = threading.Event()

        def end() -> None:
            with self._lock:
                if ended.is_set():
                    return
                ended.set()
                self._open[person] -= 1
                if self._open[person] <= 0:
                    del self._open[person]

        return end


def _resolved(
    resolver: ObjectResolver, ref: str, principal: Principal
) -> PreviewSource:
    """Resolve a ``ref`` on the disk; a file it cannot give is no preview's concern."""
    try:
        return resolver.resolve(ref, principal=principal)
    except PreviewUnavailableError as error:
        if error.reason == "missing_file":
            text = message("api.file_missing", ref=ref)
            raise NotFoundError(text, reason="missing_file") from None
        text = message("api.file_unreadable", ref=ref)
        raise ConflictError(text, reason="file_unreadable") from None


def _download(path: Path, name: str, ref: FileRef | SnapshotRef) -> FileDownload:
    return FileDownload(path, name, media_type(name), format_ref(ref))


def _place(names: list[str], member: str, ref: str) -> int:
    """Return where ``member`` is among a snapshot's files."""
    wanted = _nfc(member)
    for place, name in enumerate(names):
        if _nfc(name) == wanted:
            return place
    raise _no_member(ref, member)


def _no_member(ref: str, member: str) -> NotFoundError:
    return NotFoundError(message("api.file_member_unknown", ref=ref, member=member))


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)
