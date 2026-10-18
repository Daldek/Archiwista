"""Projects as people see them: tasks, pinned versions and problems.

``project_detail`` answers from the index (``GET /projects/{id}``);
``project_status`` asks the producer now (``GET /projects/{id}/status``,
no network, no hashing). Neither runs or changes a project. Both take the
principal's ``ProjectVisibility`` (A-ADR-029): a project they do not see is
unknown to them (``None``, ``404``).
"""

from dataclasses import dataclass
from pathlib import Path

from archiwista.auth import ProjectVisibility
from archiwista.index import (
    IndexQueries,
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
    ProjectTaskRef,
)
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
) -> ProjectInfo | None:
    """Ask the project's producer for its current status (no network, no hashing).

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

    Returns
    -------
    ProjectInfo or None
        Tasks with ``ok``, ``not_downloaded``, ``missing`` or ``corrupt``
        and the project's worst state; ``None`` for an unknown project or
        one the principal does not see.

    Raises
    ------
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin cannot be used.
    ProducerError
        The producer rejected the manifest or cannot reach the store.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        return None
    adapter = registry.adapter(record.project.producer)
    return adapter.project_status(Path(record.project.path))
