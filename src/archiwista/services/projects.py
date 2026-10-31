"""Projects as people see them: groups, pinned versions and problems.

A project is its directory holding ``archiwista-project.json``, Archiwista's
own file (A-ADR-049). ``project_detail`` answers from the index (``GET
/projects/{id}``) with the principal's ``ProjectVisibility`` (A-ADR-029): a
project they do not see is unknown to them (``None``, ``404``).

``create_project``, ``update_project``, ``set_area`` and ``set_store`` write
the file under its lock (``archiwista.projects.change_project_file``), then
record the project in the index at once, as a scan reads it. A change of a
project needs ``project.write`` (its owner or an administrator); a new
project, in a directory where none is yet, ``project.create`` (any person or
their agent), and an account that creates one (a ``user``, or an ``agent``
of one) owns it (A-ADR-049 decision 6). Each change is logged
(``project.create``, ``project.update``, ``project.area``,
``project.store``, A-ADR-047). ``export_project`` writes an export
``zestawy/<name>/`` from the pins, a change of the project too
(``project.export``), and ``project_exports`` lists the exports to whoever
sees the project (A-ADR-049 decision 13). A new project lies where a scan
finds it, below a configured project directory. None of them uses the
network or writes a store. ``project_directory`` gives a project's
directory, refused when it or its file left the project directories.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any

from archiwista.auth import (
    LOCAL_PRINCIPAL_ID,
    Principal,
    ProjectVisibility,
    access_key,
)
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import (
    CommandRequestError,
    NotFoundError,
    PathOutsideRootError,
    ProjectFileError,
    ProjectFileWriteError,
    SourceStateError,
)
from archiwista.index import (
    AreaRecord,
    IndexQueries,
    IndexWriter,
    PinGroupRef,
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
)
from archiwista.index.projects import MAX_PROJECT_DEPTH, record_project
from archiwista.messages import message
from archiwista.paths import indexed_path, resolve_indexed_path
from archiwista.projects import (
    PROJECT_FILE,
    ProjectDocument,
    area_json,
    change_project_file,
    clean_name,
    read_project_file,
    rule_text,
    write_area_file,
)
from archiwista.projects.exports import (
    ExportListing,
    ExportResult,
    ExportRow,
    list_exports,
    write_export,
)
from archiwista.services.problems import Problem, explain
from archiwista.sources import GeoAdapter
from archiwista.sources.registry import PluginRegistry


@dataclass(frozen=True, slots=True)
class ProjectDetail:
    """A project with its groups, pinned versions and visible problems.

    Attributes
    ----------
    project : ProjectRef
        The project as listed, with its stores and area.
    groups : tuple[PinGroupRef, ...]
        Its groups in the file's order, each with its pins and their state
        in the index.
    problems : tuple[Problem, ...]
        An invalid or newer file, a store that matches no configured one, an
        area file that is not used, missing or other pinned versions.
    """

    project: ProjectRef
    groups: tuple[PinGroupRef, ...]
    problems: tuple[Problem, ...]


def project_detail(
    queries: IndexQueries, key: str, *, visible: ProjectVisibility
) -> ProjectDetail | None:
    """Return a project's detail from the index.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index.
    key : str
        Project key (``ProjectRef.key``).
    visible : ProjectVisibility
        Projects the principal sees (``Authorizer.visible_projects``).

    Returns
    -------
    ProjectDetail or None
        ``None`` for an unknown project or one the principal does not see.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        return None
    return ProjectDetail(
        project=record.project,
        groups=record.groups,
        problems=project_problems(record),
    )


def project_problems(record: ProjectRecord) -> tuple[Problem, ...]:
    """Return a project's problems with their fix instructions.

    The file's own (invalid, of a newer format), then each store that
    matches no configured store, the area file when it is not used, then the
    pins whose version is missing or holds other content. The problem of an
    invalid file is rendered in the language of the request.
    """
    project = record.project
    problems: list[Problem] = []
    detail = project.problem_detail or {}
    if project.state == "invalid":
        text = rule_text(
            str(detail.get("pointer", "")),
            str(detail.get("rule", "")),
            None if detail.get("detail") is None else str(detail["detail"]),
        )
        problems.append(
            _problem("invalid_project_file", project, detail=text, path=project.path)
        )
    elif project.state == "unsupported_schema":
        problems.append(
            _problem(
                "unsupported_project_schema",
                project,
                schema=detail.get("schema"),
                path=project.path,
            )
        )
    for store in project.stores:
        if store.store is None:
            problems.append(
                _problem(
                    "unknown_store",
                    project,
                    producer=store.producer,
                    store_dir=store.root,
                )
            )
    area = project.area
    if area is not None and area.state in ("missing", "changed", "invalid"):
        problems.append(
            _problem(
                f"area_{area.state}",
                project,
                path=os.path.join(project.path, area.path),
            )
        )
    for group in record.groups:
        for pin in group.pins:
            if pin.state not in ("missing", "sha256_mismatch"):
                continue
            code = "missing_pin" if pin.state == "missing" else "pin_sha256_mismatch"
            text, instruction = explain(
                code,
                version=pin.version,
                group=group.name,
                producer=pin.producer,
                project=project.name,
            )
            problems.append(
                Problem(
                    code,
                    text,
                    instruction,
                    path=pin.version,
                    slot=pin.slot,
                    project=project.key,
                    group=group.name,
                )
            )
    return tuple(problems)


def _problem(code: str, project: ProjectRef, **values: object) -> Problem:
    """Return a problem of the project itself, its texts naming the project."""
    text, instruction = explain(code, project=project.name, **values)
    return Problem(code, text, instruction, project=project.key)


def create_project(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    *,
    path: str,
    name: str | None,
    description: str,
    area_id: str | None,
    actor: Principal,
) -> str:
    """Write a new project file in ``path``; return the project's key.

    A directory with an access entry needs ``project.write`` (it was a
    project before); anywhere else the project is new (``project.create``):
    an account that creates it (a ``user``, or an ``agent`` of one) becomes
    its owner, with the visibility of ``default_project_visibility``; the
    local owner and their agents, who have no account, leave it without an
    entry. Either way ``project.create`` is logged. A missing directory is
    made; the area, when given, is written into its ``obszary/``. The new
    project names no store: its first pin of a producer adds one.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins: the coordinate operations that read the area into
        the index.
    settings : AppSettings
        The configured stores and project directories.
    queries : IndexQueries
        Reader of the local index: the area ``area_id``.
    index_path : Path
        The local index, which holds the new project at once.
    authorizer : Authorizer
        Decides whether ``actor`` may create a project there, and records a
        new project's owner.
    path : str
        Absolute path of the project directory, created when missing: a
        configured project directory or a directory at most
        ``MAX_PROJECT_DEPTH`` levels below one, in no hidden directory and no
        store directory, where a scan finds it.
    name : str or None
        The project's name; ``None``: the directory's name.
    description : str
        The project's description (``""``: none).
    area_id : str or None
        An area of the index (``POST /areas``), or none.
    actor : Principal
        Who asks.

    Returns
    -------
    str
        The project's key (``/projects/{project}``).

    Raises
    ------
    PathOutsideRootError
        ``path`` is not absolute, lies below no configured project directory,
        or leaves it through a symbolic link.
    PermissionDeniedError
        ``actor`` may not change the project there (``project.write``), or is
        the scheduler (``project.create``).
    CommandRequestError
        The project directory below which ``path`` lies does not exist
        (``project_dir_missing``), or a scan would not find the project
        (``project_not_discoverable``).
    NotFoundError
        The index keeps no area ``area_id``.
    ProjectFileError
        A project file is there already (``project_exists``), or the name or
        description breaks the file's rule (``invalid_project_file``).
    ProjectLockedError
        Another change holds the project's lock.
    ProjectFileWriteError
        The directory, the area file or the project file cannot be written.
    """
    base, directory = _project_place(path, settings.project_dirs)
    key = access_key(directory)
    if authorizer.state.project_access(key) is None:
        authorizer.require(actor, "project.create")
    else:
        authorizer.require(actor, "project.write", key)
    _require_discoverable(base, directory, settings)
    area = None if area_id is None else _area(queries, area_id)
    if os.path.lexists(directory / PROJECT_FILE):
        raise ProjectFileError(
            message("project.exists", path=directory), reason="project_exists"
        )
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ProjectFileWriteError(
            message("project.file_write_failed", path=directory),
            hint=message("fix.project_file_write_failed", path=directory.parent),
        ) from error
    document = change_project_file(
        directory,
        create=ProjectDocument(
            name=clean_name(name if name is not None else directory.name),
            description=description,
            created_at=datetime.now(UTC).replace(microsecond=0),
            created_by=actor.id,
            area=None if area is None else write_area_file(directory, area),
        ),
    )
    project = record_changed(registry, settings, index_path, directory)
    authorizer.state.add_project(
        key,
        owner=None if actor.id == LOCAL_PRINCIPAL_ID else actor.id,
        visibility=authorizer.default_project_visibility,
        name=document.name,
        actor=actor,
    )
    return project


def update_project(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    name: str | None = None,
    description: str | None = None,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Change a project's name or description; return its key.

    Logged as ``project.update`` with the values before and after.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees.
    PermissionDeniedError
        ``actor`` may not change the project.
    PathOutsideRootError
        The project's directory or file now leaves the project directories.
    ProjectFileError
        The file is invalid or of a newer format, or the new value breaks
        its rule.
    ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)

    def change(data: dict[str, Any]) -> None:
        if name is not None:
            data["name"] = clean_name(name)
        if description is not None:
            data["description"] = description

    document = change_project_file(directory, change)
    authorizer.state.record(
        actor,
        "project.update",
        project.access_key,
        before={"name": project.name, "description": project.description},
        after={"name": document.name, "description": document.description},
    )
    return record_changed(registry, settings, index_path, directory)


def set_area(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    area_id: str | None,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Set a project's area (written into its ``obszary/``) or clear it.

    An area file the project held stays on the disk (A-ADR-049 decision 4).
    Logged as ``project.area``.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, or no area ``area_id``.
    PermissionDeniedError
        ``actor`` may not change the project.
    PathOutsideRootError
        The project's directory, file or ``obszary/`` leaves the project
        directories.
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)
    area = None if area_id is None else _area(queries, area_id)
    ref = None if area is None else write_area_file(directory, area)

    def change(data: dict[str, Any]) -> None:
        data["area"] = None if ref is None else area_json(ref)

    change_project_file(directory, change)
    authorizer.state.record(
        actor,
        "project.area",
        project.access_key,
        before={"area": None if project.area is None else project.area.path},
        after={"area": None if ref is None else ref.path},
        details={"area_id": area_id},
    )
    return record_changed(registry, settings, index_path, directory)


def set_store(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    producer: str,
    store: str,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Set the configured store of a producer's pins in a project.

    For a store that moved or is mounted at another path: the pins are
    relative to the store, so they stay (A-ADR-049 decision 7). The root is
    written as ``written_root`` says. Logged as ``project.store``.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, or ``store`` is not configured.
    CommandRequestError
        The store has no directory of ``producer`` (reason
        ``store_without_producer``).
    PermissionDeniedError
        ``actor`` may not change the project.
    PathOutsideRootError
        The project's directory or file leaves the project directories.
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    config = settings.store(store)
    if config is None:
        raise NotFoundError(message("api.store_not_configured", store=store))
    root = config.roots().get(producer)
    if root is None:
        raise CommandRequestError(
            message("command.store_without_producer", store=store, producer=producer),
            reason="store_without_producer",
            details={"option": "store"},
        )
    directory = project_directory(project, settings)
    written = written_root(root, directory, relative=bool(config.path_aliases))
    entry = {"producer": producer, "root": written}

    def change(data: dict[str, Any]) -> None:
        stores = data.setdefault("stores", [])
        for item in stores:
            if isinstance(item, dict) and item.get("producer") == producer:
                item.update(entry)
                return
        stores.append(entry)

    change_project_file(directory, change)
    before = project.store(producer)
    authorizer.state.record(
        actor,
        "project.store",
        project.access_key,
        before=None if before is None else {"producer": producer, "root": before.root},
        after=dict(entry),
        details={"store": store},
    )
    return record_changed(registry, settings, index_path, directory)


@dataclass(frozen=True, slots=True)
class ProjectExportDone:
    """An export just written, and the pins it left out.

    Attributes
    ----------
    export : ExportResult
        Its directory, files, the versions listed and when.
    no_store : int
        Pins whose producer's store in the project matches no configured
        store.
    missing : int
        Pins whose version is not present: not in the index, or not on the
        disk of its store.
    """

    export: ExportResult
    no_store: int
    missing: int


def export_project(
    settings: AppSettings,
    queries: IndexQueries,
    authorizer: Authorizer,
    key: str,
    *,
    name: str,
    groups: Sequence[str] | None,
    actor: Principal,
    visible: ProjectVisibility,
) -> ProjectExportDone:
    """Write the export ``zestawy/<name>/`` of a project from its pins.

    The pins of the chosen groups (every group when ``groups`` is ``None``),
    in the file's order of groups and pins, each version once; each pinned
    file resolved in its configured store (A-ADR-049 decision 13). A pin
    whose store is not configured, or whose version is not present, is left
    out and counted. An export is a change of the project: it needs
    ``project.write`` and is logged as ``project.export`` (its name and the
    versions listed). The project file is not written.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, or it has no group of ``groups``.
    PermissionDeniedError
        ``actor`` may not change the project.
    PathOutsideRootError
        The project's directory, its file or ``zestawy/`` leaves the project
        directories.
    ProjectFileError
        The project file is invalid or of a newer format.
    ProjectFileWriteError
        An export file cannot be written; the one there stays as it was.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    project = record.project
    authorizer.require(actor, "project.write", project.access_key)
    directory = project_directory(project, settings)
    read_project_file(directory)
    chosen = record.groups
    if groups is not None:
        names = {group.name for group in record.groups}
        for group in groups:
            if group not in names:
                raise NotFoundError(
                    message("project.group_not_found", project=key, group=group)
                )
        chosen = tuple(group for group in record.groups if group.name in groups)
    rows, no_store, missing = _export_rows(settings, queries, chosen)
    export = write_export(directory, name, rows)
    authorizer.state.record(
        actor,
        "project.export",
        project.access_key,
        details={"name": name, "pins": export.versions},
    )
    return ProjectExportDone(export, no_store=no_store, missing=missing)


def project_exports(
    settings: AppSettings,
    queries: IndexQueries,
    key: str,
    *,
    visible: ProjectVisibility,
) -> tuple[ExportListing, ...]:
    """Return a project's exports, each saying whether the project changed since.

    For whoever sees the project.

    Raises
    ------
    NotFoundError
        No project ``key`` the principal sees.
    PathOutsideRootError
        The project's directory, its file or ``zestawy/`` leaves the project
        directories.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    directory = project_directory(record.project, settings)
    try:
        changed = (directory / PROJECT_FILE).stat().st_mtime
    except OSError:  # gone since the scan: nothing to compare with
        changed = 0.0
    return list_exports(directory, changed)


def _export_rows(
    settings: AppSettings, queries: IndexQueries, groups: Sequence[PinGroupRef]
) -> tuple[list[ExportRow], int, int]:
    """Return the exported versions of ``groups`` and the pins without store, missing.

    Each version once, in the order of the groups and their pins.
    """
    pins: dict[tuple[str, str | None, str], ProjectPinRef] = {}
    for group in groups:
        for pin in group.pins:
            pins.setdefault((pin.producer, pin.store, pin.version), pin)
    roots: dict[tuple[str, str | None, str], Path] = {}
    no_store = missing = 0
    for identity, pin in pins.items():
        config = None if pin.store is None else settings.store(pin.store)
        root = None if config is None else config.roots().get(pin.producer)
        if pin.state == "unknown" or root is None:
            no_store += 1
        elif pin.state == "missing":
            missing += 1
        else:
            try:
                resolve_indexed_path(root, pin.version)
            except (OSError, PathOutsideRootError):
                missing += 1
            else:
                roots[identity] = root
    stores: dict[str, list[str]] = {}
    for _, store, version in roots:
        stores.setdefault(str(store), []).append(version)
    attributions = {
        store: queries.attributions(store, versions)
        for store, versions in stores.items()
    }
    rows = [
        ExportRow(
            file=indexed_path(root, version),
            attribution=attributions[str(store)].get(version),
        )
        for (_, store, version), root in roots.items()
    ]
    return rows, no_store, missing


def written_root(store_root: Path, directory: Path, *, relative: bool) -> str:
    """Return a store's producer directory as a project file writes it.

    Relative to the project ``directory`` (``/``-separated) when the store
    has path aliases (SPEC 4.6 point 7) and a relative path exists (the same
    drive), else absolute: so a project on a share keeps its store on every
    computer that mounts both at their aliases. Never the producer's default
    root: ``store_root`` is a configured store's.
    """
    if relative:
        try:
            return PurePath(os.path.relpath(store_root, directory)).as_posix()
        except ValueError:
            pass
    return str(store_root)


def project_directory(project: ProjectRef, settings: AppSettings) -> Path:
    """Return a project's directory, refused when it left the project directories.

    Parameters
    ----------
    project : ProjectRef
        The project as the index holds it.
    settings : AppSettings
        The configured project directories.

    Raises
    ------
    PathOutsideRootError
        The directory or its project file resolves outside every configured
        project directory (e.g. through a symbolic link planted after the
        scan), or no longer lies below one.
    """
    directory = Path(project.path)
    _require_inside(directory, PROJECT_FILE, settings.project_dirs)
    return directory


def _area(queries: IndexQueries, area_id: str) -> AreaRecord:
    """Return an area of the index, else refuse it (``404``)."""
    area = queries.area(area_id)
    if area is None:
        raise NotFoundError(message("api.area_unknown", area=area_id))
    return area


def _geo(registry: PluginRegistry) -> GeoAdapter | None:
    """Return a producer with coordinate operations, ``None`` without one."""
    # The API's helper imports the services: imported here, where it is used.
    from archiwista.api.slots import geo_adapter

    try:
        return geo_adapter(registry)
    except SourceStateError:
        return None


def record_changed(
    registry: PluginRegistry,
    settings: AppSettings,
    index_path: Path,
    directory: Path,
) -> str:
    """Record a changed project in the index as a scan reads it; return its key."""
    geo = _geo(registry)
    with IndexWriter(index_path) as writer:
        return record_project(writer, directory, stores=settings.stores, geo=geo)


def changed_project(
    queries: IndexQueries,
    authorizer: Authorizer,
    key: str,
    *,
    actor: Principal,
    visible: ProjectVisibility,
) -> ProjectRef:
    """Return a project ``actor`` sees and may change, else refuse it."""
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    authorizer.require(actor, "project.write", record.project.access_key)
    return record.project


def _require_inside(
    directory: Path, name: str | None, project_dirs: Sequence[Path]
) -> None:
    """Refuse a project directory or its file resolving outside ``project_dirs``.

    A directory or file that no longer exists is left to the change, which
    reports it in its own words.
    """
    refused: PathOutsideRootError | None = None
    for top in project_dirs:
        base = Path(os.path.abspath(top))
        if not directory.is_relative_to(base):
            continue
        relative = directory.relative_to(base).as_posix()
        try:
            resolve_indexed_path(base, relative)
            if name is not None:
                resolve_indexed_path(base, f"{relative}/{name}")
        except PathOutsideRootError as error:
            refused = error
            continue
        except FileNotFoundError:
            return
        return
    raise refused or PathOutsideRootError(
        message("ref.path_outside_root", path=directory)
    )


def _project_place(path: str, project_dirs: Sequence[Path]) -> tuple[Path, Path]:
    """Return the project directory a request names and the one it lies in.

    The directory as discovery names it: the absolute path without ``.`` and
    ``..``, its symbolic links kept, equal to or below a configured project
    directory; the part of it that exists must resolve inside that directory.

    Raises
    ------
    PathOutsideRootError
        ``path`` is not absolute, lies below no configured project directory,
        or leaves it through a symbolic link.
    CommandRequestError
        The configured project directory does not exist (reason
        ``project_dir_missing``).
    """
    if "\x00" not in path and os.path.isabs(path):
        directory = Path(os.path.abspath(path))
        for top in project_dirs:
            base = Path(os.path.abspath(top))
            if not directory.is_relative_to(base):
                continue
            if not base.is_dir():
                raise CommandRequestError(
                    message("project.dir_missing", path=base),
                    reason="project_dir_missing",
                    details={"option": "path"},
                )
            if _stays_inside(base, directory.relative_to(base)):
                return base, directory
    raise PathOutsideRootError(
        message(
            "project.outside_project_dirs",
            path=path,
            dirs=", ".join(str(top) for top in project_dirs) or "-",
        ),
        details={"option": "path"},
    )


def _stays_inside(base: Path, relative: PurePath) -> bool:
    """Whether the deepest existing part of ``base/relative`` resolves inside it.

    A dangling symbolic link counts as leaving: a write would follow it.
    """
    parts = relative.parts
    for count in range(len(parts), 0, -1):
        if os.path.lexists(base.joinpath(*parts[:count])):
            try:
                resolve_indexed_path(base, PurePath(*parts[:count]).as_posix())
            except (PathOutsideRootError, FileNotFoundError):
                return False
            return True
    return True


def _require_discoverable(base: Path, directory: Path, settings: AppSettings) -> None:
    """Refuse a project directory a scan of ``base`` would not find.

    Discovery goes at most ``MAX_PROJECT_DEPTH`` levels down and enters no
    hidden directory and no store's producer directory (``scan_projects``).

    Raises
    ------
    CommandRequestError
        Reason ``project_not_discoverable``.
    """
    parts = directory.relative_to(base).parts
    stores = {
        os.path.normpath(root)
        for config in settings.stores
        for root in config.roots().values()
    }
    places = [base.joinpath(*parts[:count]) for count in range(len(parts) + 1)]
    if (
        len(parts) > MAX_PROJECT_DEPTH
        or any(part.startswith(".") for part in parts)
        or any(os.path.normpath(place) in stores for place in places)
    ):
        raise CommandRequestError(
            message(
                "project.not_discoverable", path=directory, depth=MAX_PROJECT_DEPTH
            ),
            reason="project_not_discoverable",
            details={"option": "path"},
        )
