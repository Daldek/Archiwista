"""Projects as people see them: tasks, pinned versions and problems.

A project is its directory, holding the manifest of one producer or of both
(SPEC 4.7): its tasks and pins carry the producer of their manifest, and an
invalid manifest of one producer hides nothing of the other's.
``project_detail`` answers from the index (``GET /projects/{id}``);
``project_status`` asks a manifest's producer now (``GET
/projects/{id}/status``, no network, no hashing). Both take the principal's
``ProjectVisibility`` (A-ADR-029): a project they do not see is unknown to
them (``None``, ``404``).

``create_project``, ``add_project_task`` and ``remove_project_task`` change a
manifest through its producer (``ProjectActionAdapter``, ADR-039) for whoever
may change the project (``project.write``), then record the project in the
index at once, as a scan reads it. A change acts on one manifest: the one of
the producer it names, or the project's only one (``project_manifest``). A
new project lies where a scan finds it, below a configured project
directory, and names a configured store, never the producer's default root.
None of them uses the network or writes a store. ``project_directory`` and
``project_store`` give the jobs of a project (ADR-040) its directory and the
configured store a manifest names.
"""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

from archiwista.auth import Principal, ProjectVisibility, access_key
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import (
    CommandRequestError,
    ConflictError,
    NotFoundError,
    PathOutsideRootError,
    UnsupportedError,
)
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    ProjectManifestRef,
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
    ProjectTaskRef,
)
from archiwista.index.projects import (
    MAX_PROJECT_DEPTH,
    PROJECT_MANIFESTS,
    record_project,
)
from archiwista.jobs.availability import store_unreachable
from archiwista.messages import message
from archiwista.paths import resolve_indexed_path
from archiwista.services.commands import actions, command_info, refuse_path_options
from archiwista.services.problems import Problem, explain
from archiwista.sources import CommandCall, ProjectActionAdapter, ProjectInfo
from archiwista.sources.registry import PluginRegistry


@dataclass(frozen=True, slots=True)
class ProjectDetail:
    """A project with its tasks, pinned versions and visible problems.

    Attributes
    ----------
    project : ProjectRef
        The project as listed, with each manifest's store and state.
    tasks : tuple[ProjectTaskRef, ...]
        Tasks of each manifest in its order, with their producer, existing
        commands and options.
    pins : tuple[ProjectPinRef, ...]
        Pinned versions (older ones included) with their index state.
    problems : tuple[Problem, ...]
        Invalid manifest, unknown store, a task name of several producers,
        missing or other pinned files.
    """

    project: ProjectRef
    tasks: tuple[ProjectTaskRef, ...]
    pins: tuple[ProjectPinRef, ...]
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
        tasks=record.tasks,
        pins=record.pins,
        problems=project_problems(record),
    )


def project_problems(record: ProjectRecord) -> tuple[Problem, ...]:
    """Return a project's problems with their fix instructions.

    Each manifest's own (invalid, or naming no configured store), then each
    task name that the manifests of several producers use (SPEC 14), then
    the pins whose version is missing or holds other content.
    """
    project = record.project
    problems: list[Problem] = []
    for manifest in project.manifests:
        common = {"producer": manifest.producer, "project": project.name}
        if manifest.problem is not None:
            message, instruction = explain(
                "invalid_manifest",
                detail=manifest.problem,
                path=project.path,
                **common,
            )
            problems.append(
                Problem("invalid_manifest", message, instruction, project=project.key)
            )
        elif manifest.store is None:
            message, instruction = explain(
                "unknown_store", store_dir=manifest.store_dir, **common
            )
            problems.append(
                Problem("unknown_store", message, instruction, project=project.key)
            )
    producers: dict[str, list[str]] = {}
    for task in record.tasks:
        producers.setdefault(task.task_id, []).append(task.producer)
    for name, used in producers.items():
        if len(set(used)) < 2:
            continue
        message, instruction = explain(
            "duplicate_task",
            task=name,
            producers=", ".join(dict.fromkeys(used)),
            project=project.name,
        )
        problems.append(
            Problem(
                "duplicate_task", message, instruction, project=project.key, task=name
            )
        )
    for pin in record.pins:
        if pin.state not in ("missing", "sha256_mismatch"):
            continue
        code = "missing_pin" if pin.state == "missing" else "pin_sha256_mismatch"
        message, instruction = explain(
            code,
            version=pin.version,
            task=pin.task,
            producer=pin.producer,
            project=project.name,
        )
        problems.append(
            Problem(
                code,
                message,
                instruction,
                path=pin.version,
                slot=pin.slot,
                project=project.key,
                task=pin.task,
            )
        )
    return tuple(problems)


def project_status(
    queries: IndexQueries,
    registry: PluginRegistry,
    key: str,
    *,
    producer: str | None = None,
    visible: ProjectVisibility,
    project_dirs: Sequence[Path],
) -> ProjectInfo | None:
    """Ask a manifest's producer for its current status (no network, no hashing).

    The project's directory and the manifest are first resolved inside the
    configured project directories (SPEC 10.1): one that leaves them, e.g.
    through a symbolic link planted after the scan, is refused without
    asking the producer.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index (finds the project's directory).
    registry : PluginRegistry
        Producer plugins.
    key : str
        Project key.
    producer : str or None, optional
        The producer whose manifest is checked; ``None``: the project's only
        manifest (``project_manifest``).
    visible : ProjectVisibility
        Projects the principal sees (``Authorizer.visible_projects``).
    project_dirs : Sequence[Path]
        Configured project directories (``AppSettings.project_dirs``).

    Returns
    -------
    ProjectInfo or None
        Tasks with ``ok``, ``not_downloaded``, ``missing`` or ``corrupt``
        and the manifest's worst state; ``None`` for an unknown project or
        one the principal does not see.

    Raises
    ------
    CommandRequestError
        ``producer`` is not one of the project's (``other_producer``) or is
        left out for a project of several (``producer_required``).
    PathOutsideRootError
        The project's directory or manifest resolves outside every
        configured project directory, or no longer lies below one of them.
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin cannot be used.
    ProducerError
        The producer rejected the manifest or cannot reach the store.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        return None
    manifest = project_manifest(record.project, producer)
    adapter = registry.adapter(manifest.producer)
    directory = Path(record.project.path)
    _require_inside(directory, PROJECT_MANIFESTS.get(manifest.producer), project_dirs)
    return adapter.project_status(directory)


def project_manifest(project: ProjectRef, producer: str | None) -> ProjectManifestRef:
    """Return the manifest of ``project`` that an action acts on.

    Parameters
    ----------
    project : ProjectRef
        The project as the index holds it.
    producer : str or None
        The producer the request names; ``None``: the project's only one.

    Raises
    ------
    CommandRequestError
        The project holds no manifest of ``producer`` (reason
        ``other_producer``), or ``producer`` is left out while it holds the
        manifests of several producers (``producer_required``); both with
        ``details.option`` ``producer``.
    """
    producers = ", ".join(project.producers)
    if producer is None:
        if len(project.manifests) == 1:
            return project.manifests[0]
        raise CommandRequestError(
            message(
                "project.producer_required", project=project.key, producers=producers
            ),
            reason="producer_required",
            details={"option": "producer"},
        )
    found = project.manifest(producer)
    if found is None:
        raise CommandRequestError(
            message(
                "project.other_producer",
                project=project.key,
                producers=producers,
                producer=producer,
            ),
            reason="other_producer",
            details={"option": "producer"},
        )
    return found


def _require_inside(
    directory: Path, manifest: str | None, project_dirs: Sequence[Path]
) -> None:
    """Refuse a project directory or manifest resolving outside ``project_dirs``.

    A directory or manifest that no longer exists is left to the producer,
    which reports it in its own words.
    """
    refused: PathOutsideRootError | None = None
    for top in project_dirs:
        base = Path(os.path.abspath(top))
        if not directory.is_relative_to(base):
            continue
        relative = directory.relative_to(base).as_posix()
        try:
            resolve_indexed_path(base, relative)
            if manifest is not None:
                resolve_indexed_path(base, f"{relative}/{manifest}")
        except PathOutsideRootError as error:
            refused = error
            continue
        except FileNotFoundError:
            return
        return
    raise refused or PathOutsideRootError(
        message("ref.path_outside_root", path=directory)
    )


def create_project(
    registry: PluginRegistry,
    settings: AppSettings,
    index_path: Path,
    authorizer: Authorizer,
    *,
    producer: str,
    path: str,
    store: str,
    actor: Principal,
) -> str:
    """Create a manifest of ``producer`` bound to a configured store; return its key.

    A directory that is a project already, through another producer's
    manifest, gets the second manifest and stays one project with its key.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins: the producer writes its own manifest.
    settings : AppSettings
        The configured stores and project directories.
    index_path : Path
        The local index, which holds the new project at once.
    authorizer : Authorizer
        Decides whether ``actor`` may change a project in that directory.
    producer : str
        The producer of the manifest, e.g. ``kartograf``.
    path : str
        Absolute path of the project directory, created when missing: a
        configured project directory or a directory at most
        ``MAX_PROJECT_DEPTH`` levels below one, in no hidden directory and no
        store directory, where a scan finds it.
    store : str
        Id of the configured store whose directory of ``producer`` the
        manifest names: relative to the project directory when the store has
        path aliases (SPEC 4.6 point 7), else absolute; never the producer's
        default root.
    actor : Principal
        Who asks.

    Returns
    -------
    str
        The project's key (``/projects/{project}``).

    Raises
    ------
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available, or the store's directory of
        the producer cannot be read now (``store_unavailable``).
    UnsupportedError
        The producer changes no projects (reason ``no_project_actions``).
    PathOutsideRootError
        ``path`` is not absolute, lies below no configured project directory,
        or leaves it through a symbolic link.
    PermissionDeniedError
        ``actor`` may not change a project in that directory
        (``project.write``).
    NotFoundError
        ``store`` is not configured.
    CommandRequestError
        The store has no directory of the producer (reason
        ``store_without_producer``), the project directory below which
        ``path`` lies does not exist (``project_dir_missing``), or a scan
        would not find the project (``project_not_discoverable``).
    ProducerError
        The producer refused, e.g. a project exists there already.
    """
    adapter = project_actions(registry, producer)
    base, directory = _project_place(path, settings.project_dirs)
    authorizer.require(actor, "project.write", access_key(directory))
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
    _require_discoverable(base, directory, settings)
    refused = store_unreachable(registry.probe(producer, root), root, indexed=False)
    if refused is not None:
        raise refused
    adapter.create_project(directory, root=root, relative=bool(config.path_aliases))
    return _record(registry, settings, index_path, producer, directory)


def add_project_task(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    name: str,
    command: str,
    options: Mapping[str, object],
    producer: str | None,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Add a task to a project's manifest through its producer; return the key.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins: the producer's catalog and its manifest.
    settings : AppSettings
        The configured stores and project directories.
    queries : IndexQueries
        Reader of the local index (finds the project).
    index_path : Path
        The local index, which holds the changed project at once.
    authorizer : Authorizer
        Decides whether ``actor`` may change the project (``project.write``).
    key : str
        Project key.
    name : str
        Name of the new task; the producer's rules apply.
    command : str
        A data command of the producer's catalog.
    options : Mapping[str, object]
        Its options in the JSON form of the catalog, no file path.
    producer : str or None
        The producer the call names; ``None``: the producer of the project's
        only manifest.
    actor : Principal
        Who asks.
    visible : ProjectVisibility
        Projects ``actor`` sees.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees.
    PermissionDeniedError
        ``actor`` may not change the project: neither its owner nor an
        administrator.
    CommandRequestError
        The project holds no manifest of ``producer`` (reason
        ``other_producer``) or holds several and ``producer`` is left out
        (``producer_required``), or the command is not in its catalog
        (``unknown_command``).
    UnsupportedError
        The producer changes no projects (``no_project_actions``) or offers
        no commands (``no_commands``).
    PathOutsideRootError
        An option that is a file path is given (``details.option``), or the
        project's directory now leaves the project directories.
    ProducerError
        The producer refused: its text, ``details.option`` (an invalid or
        taken name, an invalid option), an invalid manifest, a missing store.
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    """
    project = _changed_project(queries, authorizer, key, actor=actor, visible=visible)
    manifest = project_manifest(project, producer)
    adapter = project_actions(registry, manifest.producer)
    call = CommandCall(manifest.producer, command, options)
    refuse_path_options(
        command_info(actions(registry, manifest.producer), call), options
    )
    directory = project_directory(project, settings, manifest.producer)
    adapter.add_project_task(directory, name=name, command=command, options=options)
    return _record(registry, settings, index_path, manifest.producer, directory)


def remove_project_task(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    name: str,
    producer: str | None = None,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Remove a task and its pins through its producer; return the project's key.

    The task is the one of the manifest of ``producer``, or of the project's
    only manifest when ``producer`` is ``None``. The store's files of the
    task stay: other projects may pin them.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees.
    PermissionDeniedError
        ``actor`` may not change the project.
    CommandRequestError
        The project holds no manifest of ``producer`` (``other_producer``)
        or holds several and ``producer`` is left out (``producer_required``).
    UnsupportedError
        The producer changes no projects (``no_project_actions``).
    PathOutsideRootError
        The project's directory now leaves the project directories.
    ProducerError
        The producer refused: an unknown task (``details.option`` ``name``),
        an invalid manifest, a missing store directory.
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    """
    project = _changed_project(queries, authorizer, key, actor=actor, visible=visible)
    manifest = project_manifest(project, producer)
    adapter = project_actions(registry, manifest.producer)
    directory = project_directory(project, settings, manifest.producer)
    adapter.remove_project_task(directory, name=name)
    return _record(registry, settings, index_path, manifest.producer, directory)


def project_actions(registry: PluginRegistry, producer: str) -> ProjectActionAdapter:
    """Return the adapter of a producer that changes its projects' manifests.

    Raises
    ------
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    UnsupportedError
        It changes no projects (reason ``no_project_actions``).
    """
    adapter = registry.adapter(producer)
    if not isinstance(adapter, ProjectActionAdapter):
        raise UnsupportedError(
            message("project.no_actions", producer=producer),
            reason="no_project_actions",
        )
    return adapter


def _changed_project(
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


def project_directory(
    project: ProjectRef, settings: AppSettings, producer: str
) -> Path:
    """Return a project's directory, refused when it left the project directories.

    Parameters
    ----------
    project : ProjectRef
        The project as the index holds it.
    settings : AppSettings
        The configured project directories.
    producer : str
        The producer whose manifest the caller acts on: that manifest must
        resolve inside them too.

    Raises
    ------
    PathOutsideRootError
        The directory or the manifest resolves outside every configured
        project directory (e.g. through a symbolic link planted after the
        scan), or no longer lies below one.
    """
    directory = Path(project.path)
    _require_inside(directory, PROJECT_MANIFESTS.get(producer), settings.project_dirs)
    return directory


def project_store(manifest: ProjectManifestRef, settings: AppSettings) -> Path:
    """Return the producer's directory of the configured store a manifest names.

    Archiwista writes only configured stores (plan of 2026-10-25, rule 1): a
    manifest that names another store is refused before its producer writes
    there.

    Raises
    ------
    ConflictError
        The manifest names no configured store with a directory of its
        producer (reason ``unknown_store``).
    """
    config = None if manifest.store is None else settings.store(manifest.store)
    root = None if config is None else config.roots().get(manifest.producer)
    if root is None:
        raise ConflictError(
            message("problem.unknown_store", store_dir=manifest.store_dir),
            reason="unknown_store",
            hint=message("fix.unknown_store", store_dir=manifest.store_dir),
        )
    return root


def _record(
    registry: PluginRegistry,
    settings: AppSettings,
    index_path: Path,
    producer: str,
    directory: Path,
) -> str:
    """Record a changed project in the index as a scan reads it; return its key."""
    with IndexWriter(index_path) as writer:
        return record_project(
            registry.adapter(producer), writer, directory, stores=settings.stores
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

    A dangling symbolic link counts as leaving: the producer would follow it.
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
