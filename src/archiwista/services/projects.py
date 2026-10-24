"""Projects as people see them: tasks, pinned versions and problems.

``project_detail`` answers from the index (``GET /projects/{id}``);
``project_status`` asks the producer now (``GET /projects/{id}/status``,
no network, no hashing). Neither runs or changes a project. Both take the
principal's ``ProjectVisibility`` (A-ADR-029): a project they do not see is
unknown to them (``None``, ``404``).
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from archiwista.auth import ProjectVisibility
from archiwista.errors import PathOutsideRootError
from archiwista.index import (
    IndexQueries,
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
    ProjectTaskRef,
)
from archiwista.index.projects import PROJECT_MANIFESTS
from archiwista.messages import MESSAGES
from archiwista.paths import resolve_indexed_path
from archiwista.services.problems import Problem, explain
from archiwista.sources import ProjectInfo
from archiwista.sources.registry import PluginRegistry


@dataclass(frozen=True, slots=True)
class ProjectDetail:
    """A project with its tasks, pinned versions and visible problems.

    Attributes
    ----------
    project : ProjectRef
        The project as listed, with its store and manifest state.
    tasks : tuple[ProjectTaskRef, ...]
        Tasks in manifest order with their existing commands and options.
    pins : tuple[ProjectPinRef, ...]
        Pinned versions (older ones included) with their index state.
    problems : tuple[Problem, ...]
        Invalid manifest, unknown store, missing or other pinned files.
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
    """Return a project's problems with their fix instructions."""
    project = record.project
    common = {"producer": project.producer, "project": project.name}
    problems: list[Problem] = []
    if project.problem is not None:
        message, instruction = explain(
            "invalid_manifest", detail=project.problem, path=project.path, **common
        )
        problems.append(
            Problem("invalid_manifest", message, instruction, project=project.key)
        )
    elif project.store is None:
        message, instruction = explain(
            "unknown_store", store_dir=project.store_dir, **common
        )
        problems.append(
            Problem("unknown_store", message, instruction, project=project.key)
        )
    for pin in record.pins:
        if pin.state not in ("missing", "sha256_mismatch"):
            continue
        code = "missing_pin" if pin.state == "missing" else "pin_sha256_mismatch"
        message, instruction = explain(
            code, version=pin.version, task=pin.task, **common
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
    visible: ProjectVisibility,
    project_dirs: Sequence[Path],
) -> ProjectInfo | None:
    """Ask the project's producer for its current status (no network, no hashing).

    The project's directory and manifest are first resolved inside the
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
    visible : ProjectVisibility
        Projects the principal sees (``Authorizer.visible_projects``).
    project_dirs : Sequence[Path]
        Configured project directories (``AppSettings.project_dirs``).

    Returns
    -------
    ProjectInfo or None
        Tasks with ``ok``, ``not_downloaded``, ``missing`` or ``corrupt``
        and the project's worst state; ``None`` for an unknown project or
        one the principal does not see.

    Raises
    ------
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
    project = record.project
    adapter = registry.adapter(project.producer)
    directory = Path(project.path)
    _require_inside(directory, PROJECT_MANIFESTS.get(project.producer), project_dirs)
    return adapter.project_status(directory)


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
        MESSAGES["path_outside_root"].format(path=directory)
    )
