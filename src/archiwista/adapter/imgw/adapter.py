"""IMGWTools store reads behind Archiwista's producer-neutral source interface.

Only names of ``imgwtools.__all__`` are used. A scan maps the entries of
``iter_store`` to ``SourceEntry`` values: archives, series, station catalogs
and PMAXTP cells are ``version`` entries, a version or an observation the
producer cannot read is a ``problem`` with the producer's own problem code,
and the observation register of an archive slot (a source that republished
the same content under a new signal) is ``observation`` entries, never
versions. The producer's own record rides along as the entry's handle.

IMGWTools has no links and no segments: a slot is the directory that holds
its versions (``<slot>/<label>_<sha8>/<file>``) and an entry's ``segment`` is
its dataset key, so the files of IMGW-PIB and ČHMÚ never mix. ``iter_store``
takes no list of known versions: every scan reads every sidecar. Exceptions
of the producer surface as ``ProducerError`` with the message unchanged.
"""

import os
import shlex
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path

from imgwtools import (
    IMGWError,
    Meta,
    Project,
    StoreEntry,
    StoreInfo,
    __version__,
    get_project_status,
    iter_store,
    open_project,
    store_info,
)
from imgwtools import read_meta as read_sidecar

from archiwista.adapter.imgw import PACKAGE, PRODUCER, SCHEMAS
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.messages import message, with_detail
from archiwista.sources import (
    EntryKind,
    EntryMeta,
    Footprint,
    ProjectInfo,
    ProjectPin,
    ProjectTask,
    ScanScope,
    SourceEntry,
    SourceState,
    SourceStatus,
)
from archiwista.sources.markers import STORE_MARKERS, foreign_markers

_MARKER = STORE_MARKERS[PRODUCER]
# The trees whose presence is the layout of a store, and the state file the
# server keeps in a default root: IMGWTools' own rules (``init_store``). A
# contract test compares them with its verdicts.
_LAYOUT = frozenset({"archives", "series", "stations", "pmaxtp"})
_STATE_FILES = frozenset({"api_keys.json"})
# A directory beside the versions of an archive slot: its observation register.
_REGISTER = "observations"
# Kinds of a slot ``<kind>:<dataset>[:<selector>]`` (IMGWTools spec 13.7).
_SLOT_KINDS = frozenset({"archive", "series", "catalog", "pmaxtp"})
# Trees whose files cover a whole country; the others have no place.
_COUNTRY_TREES = frozenset({"archives", "series"})
# Project and task states by increasing severity.
_STATUS_ORDER = ("ok", "not_downloaded", "missing", "corrupt")
# The state IMGWTools gives a task, as one of the states above: a pin whose
# file is gone and an equivalent version stands in (``content_match``) is
# still a pin that is missing.
_TASK_STATUS = {
    "current": "ok",
    "unpinned": "not_downloaded",
    "content_match": "missing",
    "missing": "missing",
    "changed": "corrupt",
}


class ImgwAdapter:
    """Read an IMGWTools store (its ``--root`` directory) for Archiwista.

    Parameters
    ----------
    supported_versions : str
        IMGWTools versions Archiwista supports, e.g. ``">=3.0.0,<4"``.

    Notes
    -----
    Implements the source interface and no optional capability. All methods
    may run in several threads at once; one iterator of ``iter_entries``
    belongs to one thread.
    """

    producer = PRODUCER
    package = PACKAGE
    schemas: tuple[str, ...] = SCHEMAS

    def __init__(self, *, supported_versions: str) -> None:
        self.supported_versions = supported_versions

    def probe(self, root: Path) -> SourceState:
        """Report whether ``root`` is a readable IMGWTools store.

        The marker is judged by its file name and schema (DEV-19.12), the
        other states by the names in the directory.

        Parameters
        ----------
        root : Path
            The store root: the directory that holds ``imgw-store.json``.

        Returns
        -------
        SourceState
            ``available`` for a store with a supported marker and for a new
            one (an empty directory, or one holding only the server's
            ``api_keys.json``: its first write creates the marker);
            ``incompatible`` with ``reason`` ``no_marker`` (the layout of a
            store without its marker: the ``hint`` is the command that
            writes it), ``unsupported_marker`` (another schema or no usable
            marker), ``foreign_store`` (the marker of another producer) or
            ``not_a_store`` (anything else, e.g. the parent of a store);
            ``error`` when the directory cannot be listed or IMGWTools
            refuses the path.
        """
        try:
            names = frozenset(os.listdir(root))
            info = store_info(root)
        except (OSError, IMGWError) as error:
            return self._state("error", root, detail=str(error))
        if info.supported:
            return self._state("available", root)
        return self._unsupported(root, info, names)

    def iter_entries(
        self, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        """Yield the entries of ``iter_store`` with the metadata of the pass.

        Parameters
        ----------
        root : Path
            The store root.
        scope : ScanScope or None, optional
            The store has no segments, units or parts, so only an empty scope
            is valid; ``known_versions`` is ignored (``iter_store`` reads
            every sidecar).

        Yields
        ------
        SourceEntry
            Versions with their metadata, problems and observations; the
            ``handle`` is the producer's ``StoreEntry``.

        Raises
        ------
        SourceUnavailableError
            The store cannot be listed or becomes unreadable during the scan
            (e.g. a disconnected share).
        ProducerError
            IMGWTools refused the path (a link in it, or ``..``).
        ValueError
            A scan of a segment, units or a part was asked for.
        """
        if scope is not None and (
            scope.segment is not None
            or scope.units is not None
            or scope.partition is not None
        ):
            raise ValueError(f"producer {self.producer!r} has no segments")
        return self._entries(root)

    def read_meta(self, entry: SourceEntry) -> EntryMeta:
        """Read the metadata of one entry again, on demand.

        Raises
        ------
        ProducerError
            The sidecar is missing, unreadable or of another schema.
        SourceUnavailableError
            The system cannot read it.
        """
        try:
            meta = read_sidecar(Path(entry.store) / entry.relative_path)
        except IMGWError as error:
            raise _failure(entry.store, error) from error
        return _entry_meta(entry.store, entry.relative_path, meta)

    def footprint(self, entry: SourceEntry, *, network: bool = False) -> Footprint:
        """Place a file: its country for an archive or a series, else nowhere.

        Parameters
        ----------
        entry : SourceEntry
            An entry of ``iter_entries`` or one rebuilt from the index.
        network : bool, default False
            Ignored: IMGWTools needs no request to place a file.

        Returns
        -------
        Footprint
            ``country`` for an archive or a series (its metadata name the
            country), ``none`` with reason ``no_source`` for a station catalog
            or a PMAXTP cell and ``unreadable`` for a problem.
        """
        tree = entry.relative_path.parts[:1]
        if entry.kind == "version" and tree and tree[0] in _COUNTRY_TREES:
            return Footprint(location="country", source="country")
        reason = "unreadable" if entry.kind == "problem" else "no_source"
        return Footprint(location="none", reason=reason)

    def read_project(self, path: Path) -> ProjectInfo:
        """Read a project manifest strictly with ``open_project``.

        Raises
        ------
        ProducerError
            No manifest or an invalid one; IMGWTools' message names the place.
        """
        try:
            project = open_project(path)
        except IMGWError as error:
            raise _failure(str(path), error) from error
        return _project_info(project)

    def project_status(self, path: Path) -> ProjectInfo:
        """Check the pinned files with ``get_project_status`` (no hashing).

        Returns
        -------
        ProjectInfo
            Each task ``ok``, ``not_downloaded``, ``missing`` or ``corrupt``
            and the project its worst task.

        Raises
        ------
        ProducerError
            No manifest or an invalid one.
        """
        try:
            report = get_project_status(path)
            project = open_project(path)
        except IMGWError as error:
            raise _failure(str(path), error) from error
        info = _project_info(project)
        found = {
            name: _TASK_STATUS.get(state, state) for name, state in report.tasks.items()
        }
        tasks = tuple(replace(task, status=found[task.task_id]) for task in info.tasks)
        status = max((str(task.status) for task in tasks), key=_severity, default="ok")
        return replace(info, tasks=tasks, status=status)

    def _state(
        self,
        status: SourceStatus,
        root: Path,
        *,
        detail: str | None = None,
        reason: str | None = None,
        hint: str | None = None,
    ) -> SourceState:
        return SourceState(
            producer=self.producer,
            status=status,
            store=str(root),
            package_version=str(__version__),
            supported_versions=self.supported_versions,
            schemas=self.schemas,
            detail=detail,
            reason=reason,
            hint=hint,
        )

    def _unsupported(
        self, root: Path, info: StoreInfo, names: frozenset[str]
    ) -> SourceState:
        """Judge a directory whose marker IMGWTools does not accept."""
        marker = root / _MARKER
        if marker.is_file() and not marker.is_symlink():
            text = message(
                "source.imgw_unsupported_marker",
                found=info.schema or message("source.schema_unknown"),
                expected=SCHEMAS[0],
            )
            detail = with_detail(text, "; ".join(info.problems))
            return self._state(
                "incompatible", root, detail=detail, reason="unsupported_marker"
            )
        foreign = next(
            (name for name in foreign_markers(PRODUCER) if name in names), None
        )
        if foreign is not None:
            detail = message("source.imgw_foreign_store", marker=foreign)
            return self._state(
                "incompatible", root, detail=detail, reason="foreign_store"
            )
        if names & _LAYOUT:
            hint = f"imgw store init --root {shlex.quote(str(root))}"
            detail = message("source.imgw_no_marker", hint=hint)
            return self._state(
                "incompatible", root, detail=detail, reason="no_marker", hint=hint
            )
        if names - _STATE_FILES:
            detail = message("source.imgw_not_store")
            return self._state(
                "incompatible", root, detail=detail, reason="not_a_store"
            )
        return self._state("available", root)

    def _entries(self, root: Path) -> Iterator[SourceEntry]:
        store = str(root)
        base = root.expanduser().absolute()
        try:
            os.listdir(root)
            for entry in iter_store(root):
                yield _source_entry(store, base, entry)
        except OSError as error:
            raise _unavailable(store, str(error)) from error
        except IMGWError as error:
            raise _failure(store, error) from error


def _source_entry(store: str, base: Path, entry: StoreEntry) -> SourceEntry:
    """IMGWTools' entry as a producer-neutral one, paths relative to the root."""
    path = base if entry.version is None else entry.version
    relative = path.relative_to(base)
    kind = _kind(entry)
    meta = None
    if kind == "version" and entry.meta is not None:
        meta = _entry_meta(store, relative, entry.meta)
    return SourceEntry(
        producer=PRODUCER,
        store=store,
        relative_path=relative,
        kind=kind,
        segment=_dataset(entry.slot),
        slot_path=_slot_path(kind, relative, entry.slot),
        version_path=relative if kind == "version" else None,
        problem=(entry.problem_code or "unknown") if kind == "problem" else None,
        meta=meta,
        handle=entry,
    )


def _kind(entry: StoreEntry) -> EntryKind:
    """Return the kind of an entry (archives, series and catalogs are versions)."""
    if entry.kind == "problem":
        return "problem"
    if entry.kind == "observation":
        return "observation"
    return "version"


def _dataset(slot: str | None) -> str | None:
    """Dataset key of a slot ``<kind>:<dataset>[:<selector>]``; ``None`` without one."""
    kind, _, rest = (slot or "").partition(":")
    if kind not in _SLOT_KINDS or not rest:
        return None
    return rest.partition(":")[0]


def _slot_path(kind: str, relative: Path, slot: str | None) -> Path | None:
    """Return the directory that holds a slot's versions.

    It is the file's place in every version.

    A version's file and an observation lie two levels below it; a problem is
    a version directory, or an observation file, or has no slot.
    """
    if kind != "problem":
        return relative.parent.parent
    if _dataset(slot) is None:
        return None
    parent = relative.parent
    return parent.parent if parent.name == _REGISTER else parent


def _entry_meta(store: str, relative: Path, meta: Meta) -> EntryMeta:
    """Producer-neutral metadata from a parsed ``imgw-meta/1`` sidecar."""
    version = _mapping(meta.extra.get("version"))
    period = _mapping(meta.extra.get("period"))
    return EntryMeta(
        producer=PRODUCER,
        store=store,
        relative_path=relative,
        dataset=meta.dataset,
        dataset_key=meta.dataset_key,
        label=_text(version.get("label")),
        label_source=_text(version.get("label_source")),
        data_year=_year(period.get("year")),
        downloaded_at=meta.downloaded_at,
        sha256=meta.sha256,
        size_bytes=meta.size_bytes,
        license=_text(meta.license.id),
        attribution=_text(meta.license.attribution),
        source_files=_source_files(meta.extra.get("source_files")),
        raw_sidecar=_raw_sidecar(meta),
        country=meta.country,
        provider=meta.provider,
        written_by=PACKAGE,
        content_sha256=meta.content_sha256,
        content_form=meta.content_form,
    )


def _raw_sidecar(meta: Meta) -> dict[str, object]:
    """Return the sidecar as IMGWTools parsed it, for display.

    ``Meta`` has neither the sidecar's ``producer_version`` nor its text, so
    this is the document of its fields, not the file.
    """
    raw: dict[str, object] = {
        "schema": meta.schema,
        "producer": PACKAGE,
        "dataset": meta.dataset,
        "provider": meta.provider,
        "country": meta.country,
        "sha256": meta.sha256,
        "size_bytes": meta.size_bytes,
        "downloaded_at": meta.downloaded_at.isoformat(),
        "license": {
            "id": meta.license.id,
            "attribution": meta.license.attribution,
            "url": meta.license.url,
            "terms_url": meta.license.terms_url,
        },
        "request": dict(meta.request),
        "extra": dict(meta.extra),
    }
    if meta.content_sha256 is not None:
        raw["content_sha256"] = meta.content_sha256
        raw["content_form"] = meta.content_form
    return raw


def _project_info(project: Project) -> ProjectInfo:
    """Convert a project; its pins are relative to its store."""
    store = str(project.store_dir)
    directory = Path(project.path)
    tasks = tuple(
        ProjectTask(task_id=task.name, command=task.command, options=dict(task.options))
        for task in project.tasks
    )
    pins = tuple(
        ProjectPin(
            store=store,
            version_path=Path(file.path),
            sha256=file.sha256,
            task_id=task.name,
        )
        for task in project.tasks
        for file in task.files
    )
    return ProjectInfo(
        producer=PRODUCER,
        store=store,
        path=directory,
        name=directory.name,
        tasks=tasks,
        pins=pins,
    )


def _severity(status: str) -> int:
    """Rank of a state; an unexpected one ranks above all known ones."""
    if status in _STATUS_ORDER:
        return _STATUS_ORDER.index(status)
    return len(_STATUS_ORDER)


def _failure(where: str, error: IMGWError) -> ProducerError | SourceUnavailableError:
    """Return the Archiwista error for a producer's own.

    A file the system cannot read (``io_error``) is an unavailable store;
    anything else is the producer's error with its message unchanged.
    """
    if error.code == "io_error":
        return _unavailable(where, str(error))
    return ProducerError(PACKAGE, type(error).__name__, str(error))


def _unavailable(where: str, detail: str) -> SourceUnavailableError:
    text = message("store.unreadable", path=where)
    return SourceUnavailableError(with_detail(text, detail))


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _year(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _source_files(value: object) -> tuple[str, ...]:
    """Store paths of the input versions of a derived file."""
    if not isinstance(value, list):
        return ()
    return tuple(
        item["file"]
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("file"), str)
    )
