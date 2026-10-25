"""IMGWTools store reads behind Archiwista's producer-neutral source interface.

Only names of ``imgwtools.__all__`` are used. A scan maps the entries of
``iter_store`` to ``SourceEntry`` values: archives, series, station catalogs
and PMAXTP cells are ``version`` entries, a version or an observation the
producer cannot read is a ``problem`` with the producer's own problem code,
and the observation register of an archive slot (a source that republished
the same content under a new signal) is ``observation`` entries, never
versions. The producer's own record rides along as the entry's handle.

IMGWTools has no links and cannot scan one segment alone: a slot is the
directory that holds its versions (``<slot>/<label>_<sha8>/<file>``), named
by the producer's own slot (``slot_key``, e.g.
``archive:pl.imgw.hydro_daily:2024/codz_2024.zip``), and an entry's
``segment`` is its dataset, so the files of IMGW-PIB and ČHMÚ never mix.
``describe_segment`` names each dataset for people and gives it the family the
producer declares for it as a product (``hydro``, ``meteo``), which only groups
the datasets. The versions the index knows (``ScanScope.known_versions``) are
the ``skip_versions`` of ``iter_store``: they come back ``skipped``, with no
sidecar read. A slot has no link, so ``current_version`` asks IMGWTools which
version of a slot is the current one. Exceptions of the producer surface as
``ProducerError`` with the message unchanged.
"""

import os
import shlex
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePosixPath

from imgwtools import (
    IMGWError,
    Meta,
    Project,
    StoreEntry,
    StoreInfo,
    __version__,
    get_dataset,
    get_project_status,
    get_provider,
    iter_store,
    open_project,
    providers,
    store_info,
)
from imgwtools import current_version as current_of_slot
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
    SourceObservation,
    SourceSegment,
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
# The codes of ``StoreInfo.problem_codes`` of a marker the producer refuses: a
# file that is no JSON object with a schema, or one of another schema.
_MARKER_REFUSED = frozenset({"invalid_marker", "unsupported_store"})
# A directory beside the versions of an archive slot: its observation register.
_REGISTER = "observations"
# Kinds of a slot ``<kind>:<dataset>[:<selector>]`` (IMGWTools spec 13.7).
_SLOT_KINDS = frozenset({"archive", "series", "catalog", "pmaxtp"})
# The last part of the key of a provider's station catalog (``pl.imgw.stations``):
# a slot of the store that is no dataset of the registry.
_CATALOG = "stations"
# Trees whose files cover a whole country; the others have no place.
_COUNTRY_TREES = frozenset({"archives", "series"})
# The codes of an IMGWTools error that say a slot has no current version, not that
# the store is unusable: a version of the slot is broken (``data_error``) or the
# producer cannot read the slot (``validation_error``: a link in its path, a key it
# does not know). ``io_error`` is a file the system cannot read and
# ``store_unavailable`` a root that is no store anymore.
_SLOT_UNREADABLE = frozenset({"data_error", "validation_error"})
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
    Implements the source interface, ``SegmentDescriptionAdapter`` (a
    dataset is a segment that cannot be read alone) and
    ``CurrentVersionAdapter`` (a slot has no link); no other optional
    capability. All methods may run in several threads at once; one iterator
    of ``iter_entries`` belongs to one thread.
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
            is valid; ``known_versions`` becomes ``skip_versions``: the named
            versions come back ``skipped`` without ``meta``, and their
            directories are neither listed nor read.

        Yields
        ------
        SourceEntry
            Versions with their metadata (or ``skipped``), problems and
            observations; the ``handle`` is the producer's ``StoreEntry``.

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
        return self._entries(root, {} if scope is None else scope.known_versions)

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

    def describe_segment(self, segment: str) -> SourceSegment:
        """Describe a dataset for people, from the producer's registry.

        No disk access. A dataset of the registry has its Polish title for a
        name, its provider's country and the family the registry declares for
        it as a product; a station catalog (``pl.imgw.stations``,
        ``cz.chmi.stations``: slots of the store that are no datasets of the
        registry) is named after its provider and is of the family
        ``stations``; any other key is not recognised and is its own name.

        Parameters
        ----------
        segment : str
            A dataset key, the ``segment`` of an entry.

        Returns
        -------
        SourceSegment
            ``dataset_key`` is the current key of the dataset. ``product`` is
            its family: the ``kind`` of the registry (``hydro``, ``meteo``),
            for the dataset that has none (PMAXTP) its short name, ``pmaxtp``,
            and ``stations`` for a catalog; ``None`` for a key that is not
            recognised. IMGWTools has no products, so it only groups the
            datasets, and the key itself is not read (SPEC 4.2.1).
        """
        return _describe(segment)

    def current_version(self, root: Path, slot_key: str) -> Path | None:
        """Return the current version of a slot, as IMGWTools chooses it.

        IMGWTools reads every sidecar of the slot: the newest ``Last-Modified``
        of an archive and the newest download of a series, a catalog or a PMAXTP
        cell win. A version directory without its sidecar is an interrupted
        publication and is skipped.

        Parameters
        ----------
        root : Path
            The store root.
        slot_key : str
            The producer's own key of the slot (``SourceEntry.slot_key``), e.g.
            ``archive:pl.imgw.hydro_daily:2024/codz_2024.zip``.

        Returns
        -------
        Path or None
            The version's file relative to ``root``. ``None`` when the slot has
            no version, when one of its versions is broken (an invalid
            sidecar, another schema, a size that differs from the sidecar's;
            a stray file; IMGWTools never chooses an older version in its
            place, and ``iter_entries`` reports the broken one) and when the
            producer cannot read the slot at all (a link in its path, a key it
            no longer knows): a slot the index still holds from an earlier
            pass must not fail the scan that finds it gone.

        Raises
        ------
        SourceUnavailableError
            The system cannot read a file of the slot.
        ProducerError
            IMGWTools refused the store itself (it is no longer a store).
        """
        try:
            found = current_of_slot(root, slot=slot_key)
        except OSError as error:
            raise _unavailable(str(root), str(error)) from error
        except IMGWError as error:
            if error.code in _SLOT_UNREADABLE:
                return None
            raise _failure(str(root), error) from error
        if found is None or found.version is None:
            return None
        return found.version.relative_to(root.expanduser().absolute())

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
        """Judge a directory IMGWTools does not read, by the codes of ``store_info``.

        ``invalid_marker`` and ``unsupported_store`` are a marker the producer
        refuses. ``missing_marker`` is one code for the layout of a store
        without its marker and for a directory that is no store, and
        ``imgw-store.json`` of another producer is a marker it does not know,
        so the names in the directory tell those apart.
        """
        codes = frozenset(info.problem_codes)
        if "missing_store" in codes:
            return self._state("error", root, detail="; ".join(info.problems))
        if codes & _MARKER_REFUSED:
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

    def _entries(
        self, root: Path, known: Mapping[str, tuple[str, ...]]
    ) -> Iterator[SourceEntry]:
        store = str(root)
        base = root.expanduser().absolute()
        try:
            os.listdir(root)
            for entry in iter_store(root, skip_versions=known or None):
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
    slot_path = _slot_path(kind, relative, entry.slot)
    meta = None
    if kind == "version" and entry.meta is not None:
        meta = _entry_meta(store, relative, entry.meta)
    return SourceEntry(
        producer=PRODUCER,
        store=store,
        relative_path=relative,
        kind=kind,
        segment=_dataset(entry.slot),
        slot_path=slot_path,
        version_path=_version_path(kind, relative, slot_path, entry),
        problem=(entry.problem_code or "unknown") if kind == "problem" else None,
        skipped=entry.skipped,
        meta=meta,
        slot_key=entry.slot,
        slot_name=_slot_name(entry.slot),
        observation=_observation(entry),
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


def _slot_name(slot: str | None) -> str | None:
    """Name a slot for people where the name of its directory is none.

    An archive is named by its file (its directory has no extension) and a
    station catalog by its key (the first one lies in a directory called
    ``versions``); a series and a PMAXTP cell keep the name of their
    directory (``None``).
    """
    kind, _, rest = (slot or "").partition(":")
    if kind == "archive":
        return PurePosixPath(rest.partition(":")[2]).name or None
    if kind == "catalog":
        return rest or None
    return None


def _version_path(
    kind: str, relative: Path, slot_path: Path | None, entry: StoreEntry
) -> Path | None:
    """Return the version an entry is, or an observation repeats the content of.

    A version is its own. An observation names the directory of the version
    with the same content, whose file is the slot's (``None`` when the slot
    has no file name).
    """
    if kind == "version":
        return relative
    record = entry.observation
    name = _slot_name(entry.slot)
    if kind != "observation" or record is None or slot_path is None or name is None:
        return None
    return slot_path / record.same_content_as / name


def _observation(entry: StoreEntry) -> SourceObservation | None:
    """Return the record of an observation as the producer-neutral one."""
    record = entry.observation
    if entry.kind != "observation" or record is None:
        return None
    return SourceObservation(
        seen_at=datetime.fromisoformat(record.seen_at),
        url=record.url,
        etag=record.etag,
        last_modified=record.last_modified,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
    )


def _describe(segment: str) -> SourceSegment:
    """Describe a dataset key: a registry dataset, a station catalog, or none."""
    try:
        dataset = get_dataset(segment)
    except IMGWError:
        pass
    else:
        country = get_provider(dataset.provider).country
        title = _polish(dataset.title)
        family = dataset.kind or dataset.slug
        return SourceSegment(segment, family, country, dataset.key, title, True)
    for provider in providers():
        if segment == f"{provider.key_prefix}.{_CATALOG}":
            name = message("source.imgw_catalog", "pl", provider=provider.short_name)
            return SourceSegment(
                segment, _CATALOG, provider.country, segment, str(name), True
            )
    return SourceSegment(segment, None, None, None, segment, False)


def _polish(text: str) -> str:
    """Return a text of the producer's catalog in Polish.

    The registry's titles are catalog messages that render again in another
    language (a ``str`` subclass with ``localized``); the producer's type
    says ``str``, and anything else stays as it is.
    """
    localized = getattr(text, "localized", None)
    return str(localized("pl")) if callable(localized) else str(text)


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
        written_by=meta.producer,
        producer_version=meta.producer_version,
        content_sha256=meta.content_sha256,
        content_form=meta.content_form,
    )


def _raw_sidecar(meta: Meta) -> dict[str, object]:
    """Return the sidecar as IMGWTools parsed it, for display.

    ``Meta`` does not keep the text of the file, so this is the document of
    its fields, not the file.
    """
    raw: dict[str, object] = {
        "schema": meta.schema,
        "producer": meta.producer,
        "producer_version": meta.producer_version,
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
