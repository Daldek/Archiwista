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
sees the object first (store versions: everyone), finds it in the index and
returns its ``PreviewSource``: ``resolve`` resolves the file inside its root
(``resolve_indexed_path``: a symbolic link leaving it is
``PathOutsideRootError``), ``locate`` answers from the index alone, so that
the preview cache answers for a version with a ``sha256`` while its store is
disconnected. A version without a ``sha256`` is keyed by its path, size and
modification time (``path_key``), so it needs its file either way. Own-data
kinds (``file``, ``snapshot``) are resolved from step 9 on; until then they
are refused like an unknown kind (``InvalidRefError``).

The ``preview`` job resolves its refs with ``job_resolver`` (registered in
``archiwista.previews.build.RESOLVERS``).
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from archiwista.auth import LOCAL_OWNER, Principal, ProjectVisibility
from archiwista.config import AppSettings
from archiwista.errors import (
    InvalidRefError,
    NotFoundError,
    PreviewUnavailableError,
    SourceUnavailableError,
)
from archiwista.index import IndexQueries, ProductVersion
from archiwista.jobs.protocol import JobSpec
from archiwista.messages import MESSAGES
from archiwista.paths import indexed_path, resolve_indexed_path
from archiwista.previews.cache import path_key
from archiwista.previews.types import CONTENT_KEY, Extent, PreviewSource
from archiwista.sources import GeoJSONGeometry

REF_KINDS = ("version", "file", "snapshot")
_STORE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_PROJECT = re.compile(r"[a-z0-9-]+")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Only whether a version exists: no project's pins are read.
_NO_PROJECTS = ProjectVisibility()


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
    """

    def __init__(
        self, queries: IndexQueries, settings: Callable[[], AppSettings]
    ) -> None:
        self._queries = queries
        self._settings = settings

    def resolve(self, ref: str | ObjectRef, *, principal: Principal) -> PreviewSource:
        """Return the object's source with its file resolved inside its root.

        Parameters
        ----------
        ref : str or ObjectRef
            The object.
        principal : Principal
            Who asks: store versions are visible to everyone.

        Returns
        -------
        PreviewSource
            Real paths inside the root; the content key is the version's
            ``sha256``, else its path key.

        Raises
        ------
        InvalidRefError
            Not a reference, or one of a kind this resolver does not handle.
        NotFoundError
            The index does not know the object (``404``).
        PathOutsideRootError
            Its file resolves outside its root, e.g. through a link (``403``).
        SourceUnavailableError
            Its store cannot be reached (``503 store_unavailable``).
        PreviewUnavailableError
            ``missing_file``: its store is there, its file is not.
        """
        return self._source(_parsed(ref), on_disk=True)

    def locate(self, ref: str | ObjectRef, *, principal: Principal) -> PreviewSource:
        """Return the object's source from the index, for the preview cache.

        A version with a ``sha256`` is located without touching its store:
        its path is the indexed one, not resolved, and must not be rendered
        (``resolve`` gives the source to render). One without a ``sha256``
        is resolved as by ``resolve``.

        Raises
        ------
        InvalidRefError, NotFoundError, PathOutsideRootError
            As ``resolve``.
        SourceUnavailableError, PreviewUnavailableError
            As ``resolve``, only for a version without a ``sha256``, or one
            of a store no longer configured.
        """
        return self._source(_parsed(ref), on_disk=False)

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

    def _source(self, ref: ObjectRef, *, on_disk: bool) -> PreviewSource:
        if isinstance(ref, VersionRef):
            return self._version(ref, on_disk=on_disk)
        message = MESSAGES["ref_kind_unsupported"].format(ref=format_ref(ref))
        raise InvalidRefError(message)

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


def job_resolver(spec: JobSpec) -> Callable[[str], PreviewSource]:
    """Return how a ``preview`` job resolves its refs (``build.RESOLVERS``).

    The index is opened for each ref and closed again; the refs were checked
    against the principal who asked when the job was submitted, so the job
    resolves them as the owner of the installation.
    """
    settings = spec.settings

    def resolve(ref: str) -> PreviewSource:
        with IndexQueries(spec.index_path) as queries:
            resolver = ObjectResolver(queries, lambda: settings)
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
        The root cannot be reached (a disconnected share).
    PreviewUnavailableError
        ``missing_file``: the root is there, the file is not.
    """
    try:
        real = resolve_indexed_path(root, relative)
        return real, real.stat()
    except FileNotFoundError:
        if _reachable(root):
            raise PreviewUnavailableError("missing_file") from None
        raise SourceUnavailableError(
            MESSAGES["preview_reason_store_unavailable"]
        ) from None
    except OSError as error:  # an unreadable root, a stale share
        if isinstance(error, PermissionError) and _reachable(root):
            raise PreviewUnavailableError("unreadable") from None
        raise SourceUnavailableError(
            MESSAGES["preview_reason_store_unavailable"]
        ) from None


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
