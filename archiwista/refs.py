"""References to the objects people preview and compare (plan v0.2, decision 10).

Every object that has a preview has a ``ref`` in the models of the API:

- ``version:<store>:<version path>`` — a version in a store;
- ``file:<project>:<path in the data folder>`` — an own-data working file;
- ``snapshot:<project>:<label>:<path in the data folder>`` — its snapshot.

Store ids (``[a-z0-9][a-z0-9_-]{0,31}``), project keys (``[a-z0-9-]+``) and
snapshot labels hold no ``:``, so whatever follows the second colon (of a
snapshot: the third) is the path. An agent copies a ``ref`` from an answer,
it never builds one; ``parse_ref`` and ``format_ref`` are each other's
inverse.

``ObjectResolver`` is the only way from a ``ref`` to a file. It decides who
sees the object first (store versions: everyone; an own-data file and its
snapshots: whoever sees its project, else ``NotFoundError`` as for an
unknown object), finds it in the index and returns its ``PreviewSource``:
``resolve`` resolves the file inside its root (``resolve_indexed_path``: a
symbolic link leaving it is ``PathOutsideRootError``), ``locate`` answers
from the index alone, so that the preview cache answers for a version with
a ``sha256`` (or a snapshot) while its store (folder) is disconnected. A
version without a ``sha256`` is keyed by its path, size and modification
time (``path_key``), so it needs its file either way.

An own-data working file (``file``) changes while people work: it is keyed
by the content identity of its last scan (decision 8), so every use first
checks that its files are still as the scan stamped them
(``stamp_holds``), else ``OwnFileChangedError`` (``409 own_file_changed``:
refresh the project's own data), and its source is ``mutable`` with the
state a render process checks again before and after rendering. A snapshot
(``snapshot``) is read only in ``.wersje/`` of its project's folder and is
keyed by the content identity of its ``migawka.json``.

The ``preview`` job resolves its refs with ``job_resolver`` (registered in
``archiwista.previews.build.RESOLVERS`` for every kind).
"""

import os
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER, Principal, ProjectVisibility
from archiwista.config import AppSettings
from archiwista.errors import (
    InvalidRefError,
    NotFoundError,
    OwnFileChangedError,
    PathOutsideRootError,
    PreviewUnavailableError,
    SourceUnavailableError,
)
from archiwista.index import (
    IndexQueries,
    OwnFileDetail,
    ProductVersion,
    SnapshotRecord,
    own_file_id,
)
from archiwista.jobs.protocol import JobSpec
from archiwista.messages import MESSAGES
from archiwista.owndata.content import CONTENT_METHODS, ContentMethod
from archiwista.owndata.document import SNAPSHOTS_DIR
from archiwista.owndata.formats import fileset_members
from archiwista.owndata.scan import stamp_holds
from archiwista.paths import indexed_path, resolve_indexed_path
from archiwista.previews.cache import path_key
from archiwista.previews.types import (
    CONTENT_KEY,
    Extent,
    FileStat,
    PreviewSource,
    SourceStat,
)
from archiwista.sources import GeoJSONGeometry

REF_KINDS = ("version", "file", "snapshot")
_STORE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_PROJECT = re.compile(r"[a-z0-9-]+")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Only whether a version exists: no project's pins are read. Also what a
# resolver without a visibility rule sees of own data: nothing.
_NO_PROJECTS = ProjectVisibility()

type VisibleProjects = Callable[[Principal], ProjectVisibility]


@dataclass(frozen=True, slots=True)
class VersionRef:
    """A version in a store: ``version:<store>:<path>``."""

    store: str
    path: str


@dataclass(frozen=True, slots=True)
class FileRef:
    """An own-data working file: ``file:<project>:<path>``."""

    project: str
    path: str


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    """A snapshot of an own-data file: ``snapshot:<project>:<label>:<path>``."""

    project: str
    label: str
    path: str


type ObjectRef = VersionRef | FileRef | SnapshotRef


def parse_ref(text: str) -> ObjectRef:
    """Read a reference.

    Parameters
    ----------
    text : str
        ``version:<store>:<path>``, ``file:<project>:<path>`` or
        ``snapshot:<project>:<label>:<path>``.

    Returns
    -------
    ObjectRef
        The reference; its path is not checked against any root here.

    Raises
    ------
    InvalidRefError
        An unknown kind, a malformed store id, project key or label, or an
        empty path (``422 invalid_ref``).
    """
    kind, _, rest = text.partition(":")
    found: ObjectRef | None = None
    if kind == "version":
        store, _, path = rest.partition(":")
        if _STORE.fullmatch(store) and _path(path):
            found = VersionRef(store, path)
    elif kind == "file":
        project, _, path = rest.partition(":")
        if _PROJECT.fullmatch(project) and _path(path):
            found = FileRef(project, path)
    elif kind == "snapshot":
        project, _, rest = rest.partition(":")
        label, _, path = rest.partition(":")
        if _PROJECT.fullmatch(project) and _LABEL.fullmatch(label) and _path(path):
            found = SnapshotRef(project, label, path)
    if found is None:
        raise InvalidRefError(MESSAGES["ref_invalid"].format(ref=text))
    return found


def format_ref(ref: ObjectRef) -> str:
    """Return the text of a reference (the inverse of ``parse_ref``)."""
    match ref:
        case VersionRef(store, path):
            return f"version:{store}:{path}"
        case FileRef(project, path):
            return f"file:{project}:{path}"
        case SnapshotRef(project, label, path):
            return f"snapshot:{project}:{label}:{path}"


def version_ref(store: str, path: str) -> str:
    """Return the ``ref`` of a store version (``version:<store>:<path>``)."""
    return format_ref(VersionRef(store, path))


class ObjectResolver:
    """From a reference to the file a render process may read (see the module).

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index.
    settings : Callable[[], AppSettings]
        The settings in effect (the stores' directories), read per call.
    visible : Callable[[Principal], ProjectVisibility] or None, optional
        The projects a principal sees (``Authorizer.visible_projects``):
        their own data and snapshots. Without it no project's are visible,
        only store versions.
    """

    def __init__(
        self,
        queries: IndexQueries,
        settings: Callable[[], AppSettings],
        *,
        visible: VisibleProjects | None = None,
    ) -> None:
        self._queries = queries
        self._settings = settings
        self._visible = visible

    def visible_projects(self, principal: Principal) -> ProjectVisibility:
        """Use the same project visibility for preview jobs as for own files."""
        return _NO_PROJECTS if self._visible is None else self._visible(principal)

    def resolve(self, ref: str | ObjectRef, *, principal: Principal) -> PreviewSource:
        """Return the object's source with its file resolved inside its root.

        Parameters
        ----------
        ref : str or ObjectRef
            The object.
        principal : Principal
            Who asks: store versions are visible to everyone, own data and
            snapshots to whoever sees their project.

        Returns
        -------
        PreviewSource
            Real paths inside the root; the content key is the version's
            ``sha256`` (else its path key), or the content identity of an
            own-data file or snapshot.

        Raises
        ------
        InvalidRefError
            Not a reference.
        NotFoundError
            The index does not know the object, or the principal does not
            see its project (``404``).
        PathOutsideRootError
            Its file resolves outside its root, e.g. through a link (``403``).
        SourceUnavailableError
            Its store cannot be reached (``503 store_unavailable``).
        OwnFileChangedError
            A working file differs from its last scan (``409``).
        PreviewUnavailableError
            ``missing_file``: its store or folder is there, its file is not
            (or a working file the last scan found gone, or a folder out of
            reach); ``unreadable``: a working file without a content
            identity, or a snapshot that is not valid.
        """
        return self._source(_parsed(ref), principal, on_disk=True)

    def locate(self, ref: str | ObjectRef, *, principal: Principal) -> PreviewSource:
        """Return the object's source from the index, for the preview cache.

        A version with a ``sha256`` and a snapshot are located without
        touching their store or folder: their paths are the indexed ones,
        not resolved, and must not be rendered (``resolve`` gives the source
        to render). A version without a ``sha256`` is resolved as by
        ``resolve``, and a working file too: whether it changed since its
        scan decides its content.

        Raises
        ------
        InvalidRefError, NotFoundError, PathOutsideRootError
            As ``resolve``.
        SourceUnavailableError, OwnFileChangedError, PreviewUnavailableError
            As ``resolve``, only for a version without a ``sha256`` or one of
            a store no longer configured, a working file, or a snapshot that
            is not valid.
        """
        return self._source(_parsed(ref), principal, on_disk=False)

    def version_source(
        self, store: str, version: ProductVersion, *, on_disk: bool
    ) -> PreviewSource:
        """Return the source of a version the index listed, without reading it again.

        As ``locate`` (``on_disk`` false) or ``resolve`` (``on_disk`` true) of
        the version's ``ref``, for many versions of one answer (the local
        layers, plan v0.2 decision 7). Its ``native`` rectangle gives the
        georeference of a header outline, so it comes from a query of a view
        (``IndexQueries.product_versions`` with ``bbox``).

        Raises
        ------
        PathOutsideRootError, SourceUnavailableError, PreviewUnavailableError
            As ``resolve``; without ``on_disk`` only for a version without a
            ``sha256``, or one of a store no longer configured.
        """
        return _version_source(
            store,
            version.path,
            self._root(store, version.producer),
            sha256=version.sha256,
            size_bytes=version.size_bytes,
            crs=version.horizontal_crs,
            georeference=_georeference(
                version.location_source, version.native_crs, version.native
            ),
            product=version.product,
            dataset_key=version.dataset_key,
            nodata=version.nodata,
            on_disk=on_disk,
        )

    def _source(
        self, ref: ObjectRef, principal: Principal, *, on_disk: bool
    ) -> PreviewSource:
        match ref:
            case VersionRef():
                return self._version(ref, on_disk=on_disk)
            case FileRef():
                return self._working(ref, self._own_file(ref, principal))
            case SnapshotRef():
                detail = self._own_file(ref, principal)
                return _snapshot_source(ref, detail, on_disk=on_disk)

    def _version(self, ref: VersionRef, *, on_disk: bool) -> PreviewSource:
        detail = self._queries.version(ref.store, ref.path, visible=_NO_PROJECTS)
        if detail is None:
            message = MESSAGES["api_version_unknown"].format(
                version=ref.path, store=ref.store
            )
            raise NotFoundError(message)
        summary = detail.summary
        root = self._root(ref.store, detail.segment.producer)
        native = None
        if summary.location.source == "header" and detail.native_crs is not None:
            native = self._queries.native_outline(ref.store, ref.path)
        return _version_source(
            ref.store,
            ref.path,
            root,
            sha256=summary.sha256,
            size_bytes=summary.size_bytes,
            crs=summary.horizontal_crs,
            georeference=_georeference(
                summary.location.source, detail.native_crs, native
            ),
            product=detail.product,
            dataset_key=detail.dataset_key,
            nodata=detail.nodata,
            on_disk=on_disk,
        )

    def _root(self, store: str, producer: str) -> Path:
        """Return the directory of a store's producer; refuse an unknown one."""
        config = self._settings().store(store)
        root = None if config is None else config.roots().get(producer)
        if root is None:
            raise SourceUnavailableError(MESSAGES["preview_reason_store_unavailable"])
        return root

    def _own_file(
        self, ref: FileRef | SnapshotRef, principal: Principal
    ) -> OwnFileDetail:
        """Return the indexed working file of a reference its principal sees.

        Raises
        ------
        NotFoundError
            An unknown project, file or folder never scanned, or a project
            the principal does not see.
        """
        visible = self.visible_projects(principal)
        path = unicodedata.normalize("NFC", ref.path)
        detail = self._queries.own_file(ref.project, own_file_id(path), visible=visible)
        if detail is None or detail.file.path != path:
            message = MESSAGES["own_file_not_found"].format(
                project=ref.project, file_id=path
            )
            raise NotFoundError(message)
        return detail

    def _working(self, ref: FileRef, detail: OwnFileDetail) -> PreviewSource:
        """Return a working file's source once it is known unchanged since its scan.

        Its state for the render process (the main file and its ``-wal``) is
        read before the scan's stamp is checked, so a change after the check
        shows to the render process as a change since the scan.
        """
        if detail.file.state == "missing":
            raise PreviewUnavailableError("missing_file")
        root = Path(os.path.realpath(detail.folder.path))
        listed = indexed_path(root, detail.disk_path)
        try:
            real = resolve_indexed_path(root, detail.disk_path)
            stat = _source_stat(real)
            members = fileset_members(real)
        except FileNotFoundError:
            if _reachable(root):
                raise own_file_changed(ref) from None
            raise PreviewUnavailableError("missing_file") from None
        except OSError:  # a folder out of reach, a stale share
            raise PreviewUnavailableError("missing_file") from None
        reals = tuple(Path(os.path.realpath(member)) for member in members)
        if not all(member.is_relative_to(root) for member in reals):
            message = MESSAGES["path_outside_root"].format(path=detail.file.path)
            raise PathOutsideRootError(message)
        if not stamp_holds(listed, detail.stamp):
            raise own_file_changed(ref)
        content = (detail.content_sha256 or "").lower()
        if (
            CONTENT_KEY.fullmatch(content) is None
            or detail.content_method not in CONTENT_METHODS
        ):
            raise PreviewUnavailableError("unreadable")
        return PreviewSource(
            ref=format_ref(FileRef(ref.project, detail.file.path)),
            content_key=content,
            paths=reals,
            size_bytes=stat.main.size_bytes,
            mutable=True,
            stat=stat,
            content_method=cast(ContentMethod, detail.content_method),
        )


def own_file_changed(ref: FileRef) -> OwnFileChangedError:
    """Return the refusal of a working file that changed since its scan."""
    message = MESSAGES["own_file_changed"].format(path=ref.path, project=ref.project)
    return OwnFileChangedError(message)


def job_resolver(spec: JobSpec) -> Callable[[str], PreviewSource]:
    """Return how a ``preview`` job resolves its refs (``build.RESOLVERS``).

    The index is opened for each ref and closed again; the refs were checked
    against the principal who asked when the job was submitted, so the job
    resolves them as the owner of the installation, who sees every project.
    """
    settings = spec.settings

    def resolve(ref: str) -> PreviewSource:
        with IndexQueries(spec.index_path) as queries:
            resolver = ObjectResolver(
                queries, lambda: settings, visible=lambda _: ALL_PROJECTS
            )
            return resolver.resolve(ref, principal=LOCAL_OWNER)

    return resolve


def _parsed(ref: str | ObjectRef) -> ObjectRef:
    return parse_ref(ref) if isinstance(ref, str) else ref


def _path(path: str) -> bool:
    return bool(path) and "\x00" not in path


def _version_source(
    store: str,
    path: str,
    root: Path,
    *,
    sha256: str | None,
    size_bytes: int | None,
    crs: str | None,
    georeference: Extent | None,
    product: str | None,
    dataset_key: str | None,
    nodata: float | None,
    on_disk: bool,
) -> PreviewSource:
    """Return a version's source: on disk, or located by its ``sha256``.

    The content key is the ``sha256``, else the path key of the file's size
    and modification time, which only the file gives.
    """
    content_key = sha256.lower() if sha256 else None
    if content_key is not None and CONTENT_KEY.fullmatch(content_key) is None:
        content_key = None
    found = indexed_path(root, path)
    if on_disk or content_key is None:
        found, status = _on_disk(root, path)
        size_bytes = status.st_size
        if content_key is None:
            content_key = path_key(store, path, status.st_size, status.st_mtime_ns)
    return PreviewSource(
        ref=format_ref(VersionRef(store, path)),
        content_key=content_key,
        paths=(found,),
        size_bytes=size_bytes,
        crs=crs,
        georeference=georeference,
        product=product,
        dataset_key=dataset_key,
        nodata=nodata,
    )


def _snapshot_source(
    ref: SnapshotRef, detail: OwnFileDetail, *, on_disk: bool
) -> PreviewSource:
    """Return a snapshot's source in ``.wersje/`` of its file's data folder.

    Its files are those its ``migawka.json`` names, the main file first, in
    ``<folder>/.wersje/<file>/<label>/``; on the disk each must resolve
    inside that directory. The content key is the document's content
    identity, so a snapshot shares its previews with every file of the same
    content (decision 3).

    Raises
    ------
    NotFoundError
        The file has no snapshot of that label.
    PreviewUnavailableError
        ``unreadable``: the snapshot is not valid (``invalid``, ``modified``);
        ``missing_file``: its directory or a file of it is gone.
    PathOutsideRootError
        A file of it resolves outside its directory.
    """
    snapshot = next(
        (item for item in detail.snapshots if item.label == ref.label), None
    )
    if snapshot is None:
        message = MESSAGES["own_snapshot_not_found"].format(
            project=ref.project, path=detail.file.path, label=ref.label
        )
        raise NotFoundError(message)
    content = (snapshot.content_sha256 or "").lower()
    files = _snapshot_files(snapshot)
    if (
        snapshot.state != "ok"
        or not files
        or CONTENT_KEY.fullmatch(content) is None
        or snapshot.content_method not in CONTENT_METHODS
    ):
        raise PreviewUnavailableError("unreadable")
    root = Path(os.path.realpath(detail.folder.path))
    place = f"{SNAPSHOTS_DIR}/{detail.disk_path}/{snapshot.label}"
    size_bytes = files[0][1]
    state = None
    if on_disk:
        try:
            directory = resolve_indexed_path(root, place)
            paths = tuple(resolve_indexed_path(directory, name) for name, _ in files)
            state = _source_stat(paths[0])
            size_bytes = state.main.size_bytes
        except OSError:  # gone, or a folder out of reach
            raise PreviewUnavailableError("missing_file") from None
    else:
        directory = indexed_path(root, place)
        paths = tuple(indexed_path(directory, name) for name, _ in files)
    return PreviewSource(
        ref=format_ref(SnapshotRef(ref.project, snapshot.label, detail.file.path)),
        content_key=content,
        paths=paths,
        size_bytes=size_bytes,
        mutable=on_disk,
        stat=state if on_disk else None,
        content_method=cast(ContentMethod, snapshot.content_method),
    )


def _snapshot_files(snapshot: SnapshotRecord) -> list[tuple[str, int]]:
    """Return the names and sizes of a snapshot's files from its document."""
    files = (snapshot.document or {}).get("files")
    found: list[tuple[str, int]] = []
    for item in files if isinstance(files, list) else ():
        entry = item if isinstance(item, Mapping) else {}
        name, size = entry.get("name"), entry.get("size_bytes")
        if not isinstance(name, str) or not isinstance(size, int):
            return []
        found.append((name, size))
    return found


def _source_stat(main: Path) -> SourceStat:
    """Return the main file's and SQLite companions' current identity.

    Raises
    ------
    OSError
        The file cannot be read (``FileNotFoundError``: it is gone).
    """
    found = FileStat.of(os.stat(main))
    wal = _companion_stat(main, "-wal")
    journal = _companion_stat(main, "-journal")
    return SourceStat(found, wal, journal)


def _companion_stat(main: Path, suffix: str) -> FileStat | None:
    try:
        return FileStat.of(os.stat(main.with_name(f"{main.name}{suffix}")))
    except FileNotFoundError:
        return None


def _georeference(
    location_source: str | None, native_crs: str | None, native: GeoJSONGeometry | None
) -> Extent | None:
    """Return the georeference of a header outline (a JPEG sheet), if any."""
    if location_source != "header" or native_crs is None or native is None:
        return None
    bounds = _bounds(native)
    return None if bounds is None else Extent(bounds, native_crs)


def _on_disk(root: Path, relative: str) -> tuple[Path, os.stat_result]:
    """Resolve a version's file inside its root and read its size and time.

    Raises
    ------
    PathOutsideRootError
        The file resolves outside the root.
    SourceUnavailableError
        The root cannot be reached (a disconnected share), or it is empty:
        the version is indexed, so its store has entries and an empty
        directory is the mount point of a share that is gone (SPEC 4.4).
    PreviewUnavailableError
        ``missing_file``: the root is there, the file is not.
    """
    try:
        real = resolve_indexed_path(root, relative)
        return real, real.stat()
    except FileNotFoundError:
        if _present(root):
            raise PreviewUnavailableError("missing_file") from None
        raise SourceUnavailableError(
            MESSAGES["preview_reason_store_unavailable"]
        ) from None
    except OSError as error:  # an unreadable root, a stale share
        if isinstance(error, PermissionError) and _present(root):
            raise PreviewUnavailableError("unreadable") from None
        raise SourceUnavailableError(
            MESSAGES["preview_reason_store_unavailable"]
        ) from None


def _present(root: Path) -> bool:
    """Whether a store's directory is there with entries (not an empty mount)."""
    try:
        with os.scandir(root) as entries:
            return next(entries, None) is not None
    except OSError:
        return False


def _reachable(root: Path) -> bool:
    try:
        return root.is_dir()
    except OSError:
        return False


def _bounds(outline: GeoJSONGeometry) -> tuple[float, float, float, float] | None:
    """Return the bounding rectangle of a polygon's coordinates, if any."""
    xs: list[float] = []
    ys: list[float] = []

    def walk(value: object) -> None:
        if (
            isinstance(value, list | tuple)
            and len(value) >= 2
            and all(isinstance(number, int | float) for number in value[:2])
        ):
            xs.append(float(value[0]))
            ys.append(float(value[1]))
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    walk(outline.get("coordinates"))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)
