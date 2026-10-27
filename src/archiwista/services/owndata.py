"""Projects' own data for people: the data folder, its scans and its problems.

``set_data_dir`` is the one way to give a project another data folder
(``PUT /projects/{project}/data-dir``, step 9): the project's owner or an
administrator (``project.write``), for one who is no administrator inside the
project's directory (A-ADR-029 erratum 2), then the same rules as every scan
(``check_own_folder``) and the settings' own checks; the folder is saved as
its real path and a change is logged (``project.data_dir``).
``scan_limits`` keeps each person to one waiting or
running scan of a data folder and each project's folder to one scan started a
minute (ADR-047 decision 4). ``own_problems``, ``file_problems`` and
``folder_problems`` explain the problems a scan recorded (or a folder's state
now, ``archiwista.owndata.scan.folder_check``), without paths of other
projects.
"""

import math
import os
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from archiwista.auth import ALL_PROJECTS, LOCAL_PRINCIPAL_ID, Principal
from archiwista.auth.authorize import Authorizer
from archiwista.config import (
    AppPaths,
    SettingsProblem,
    SettingsService,
    SettingsValidationError,
    own_folder_conflict,
)
from archiwista.errors import NotFoundError, RateLimitedError
from archiwista.index import IndexQueries, OwnFileDetail, OwnFolderRecord, OwnProblem
from archiwista.jobs import JobSupervisor
from archiwista.messages import lookup, message
from archiwista.owndata.scan import (
    OwnFolderCheck,
    check_own_folder,
    folder_rules,
    inside_project,
)
from archiwista.services.problems import Problem, explain

# Seconds between two scans of one project's data folder that people start
# (ADR-047 decision 4); the local owner and the scheduler are not limited.
SCAN_INTERVAL_S = 60
# Seconds after which a person whose scan waits or runs may ask again.
SCAN_RUNNING_RETRY_S = 10


def set_data_dir(
    authorizer: Authorizer,
    principal: Principal,
    settings: SettingsService,
    queries: IndexQueries,
    paths: AppPaths,
    project: str,
    path: str | None,
) -> OwnFolderCheck:
    """Set a project's data folder, or bring back its default ``dane/``.

    The folder is saved as its real path (``realpath``), so the folder a
    later scan checks is the one checked here: one inside the project's
    directory must stay there (``check_own_folder``), even when a symbolic
    link it was given through is changed.

    Parameters
    ----------
    authorizer : Authorizer
        Decides ``project.write`` (the project's owner and administrators;
        the folder is where snapshots are written), whether the folder may
        lie outside the project's directory (``settings.write``: an
        administrator), which projects the principal sees, and logs the
        change.
    principal : Principal
        Who asks.
    settings : SettingsService
        Settings in effect; ``own_data_dirs`` is saved there.
    queries : IndexQueries
        The indexed projects: their folders and stores take part in the rules.
    paths : AppPaths
        Archiwista's data directory, which no folder may overlap.
    project : str
        Project key.
    path : str or None
        Absolute folder; ``None`` removes the setting.

    Returns
    -------
    OwnFolderCheck
        The folder and its state now; its files come with the next
        ``own_scan``.

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    PermissionDeniedError
        Neither the project's owner nor an administrator.
    SettingsValidationError
        The folder lies outside the project's directory after ``realpath``
        and the principal is no administrator (``own_data_dir_outside_project``),
        breaks a rule of decision 8 or is not a readable directory; nothing
        changes.
    """
    record = queries.project(project, visible=authorizer.visible_projects(principal))
    if record is None:
        raise NotFoundError(message("project.not_found", project=project))
    key = record.project.access_key
    authorizer.require(principal, "project.write", key)
    current = settings.get()
    folders = dict(current.own_data_dirs)
    if path is None:
        folders.pop(key, None)
    else:
        folders[key] = os.path.realpath(path) if os.path.isabs(path) else path
    changed = current.model_copy(update={"own_data_dirs": folders})
    known = queries.projects(visible=ALL_PROJECTS)
    stores, others = folder_rules(changed, known)
    others.pop(key, None)
    folders_of_others = list(others.values())
    if path is not None:
        field = f"own_data_dirs.{key}"
        if not authorizer.can(principal, "settings.write") and not inside_project(
            path, key
        ):
            text = message("own.data_dir_outside_project", path=path, project=key)
            problem = SettingsProblem("own_data_dir_outside_project", field, text)
            raise SettingsValidationError([problem])
        conflict = own_folder_conflict(
            Path(path), stores=stores, app_data=paths.data_dir, others=folders_of_others
        )
        if conflict is not None:
            reason, directory = conflict
            code = f"own_data_dir_{reason}"
            text = message(
                f"own.data_dir_{reason}", path=path, project=key, other=directory
            )
            raise SettingsValidationError([SettingsProblem(code, field, text)])
    settings.update(changed)
    before, after = current.own_data_dir(key), changed.own_data_dir(key)
    if before != after:
        authorizer.state.record(
            principal,
            "project.data_dir",
            key,
            before={"path": str(before[0]), "source": before[1]},
            after={"path": str(after[0]), "source": after[1]},
        )
    return check_own_folder(
        changed, key, stores=stores, app_data=paths.data_dir, others=folders_of_others
    )


def scan_limits(
    jobs: JobSupervisor, principal: Principal, project: str
) -> Callable[[], None] | None:
    """Return the limits of a person's new scan of a project's data folder.

    The check is for ``JobSupervisor.submit(admit=…)``, so a request that
    joins a waiting scan is never refused. A person (with the agents of the
    account) has at most one ``own_scan`` waiting or running
    (``scan_running``), and a project's folder is scanned at most once per
    ``SCAN_INTERVAL_S`` (``scan_too_soon``): both ``429 rate_limited`` with
    ``Retry-After``.

    Parameters
    ----------
    jobs : JobSupervisor
        The supervisor of the scan: its jobs tell what waits, runs and ran.
    principal : Principal
        Who asks.
    project : str
        The project's key (``params.project`` of its ``own_scan``).

    Returns
    -------
    Callable[[], None] or None
        The check, which raises ``RateLimitedError``; ``None`` for the local
        owner and the scheduler (the principal ``local``), who are not
        limited.
    """
    if principal.id == LOCAL_PRINCIPAL_ID:
        return None

    def admit() -> None:
        running = jobs.active_of(principal.id, "own_scan")
        if running is not None:
            raise RateLimitedError(
                message("own.scan_running", job=running.id),
                retry_after_s=SCAN_RUNNING_RETRY_S,
                reason="scan_running",
            )
        started = jobs.last_started("own_scan", project)
        if started is None:
            return
        wait = SCAN_INTERVAL_S - (datetime.now(UTC) - started).total_seconds()
        if wait > 0:
            seconds = math.ceil(wait)
            raise RateLimitedError(
                message("own.scan_too_soon", project=project, seconds=seconds),
                retry_after_s=seconds,
                reason="scan_too_soon",
            )

    return admit


def folder_problems(check: OwnFolderCheck, project: str) -> tuple[Problem, ...]:
    """Return the problems of a folder checked now, before its first scan.

    Parameters
    ----------
    check : OwnFolderCheck
        The folder and its state now.
    project : str
        The project's key (``ProjectRef.key``).
    """
    found: list[OwnProblem] = []
    if check.state == "invalid":
        found.append(OwnProblem("own_folder_invalid", reason=check.reason))
    elif check.state == "unreadable":
        found.append(OwnProblem("own_folder_unreadable"))
    return _explained(found, project=project, folder=check.path)


def file_problems(detail: OwnFileDetail) -> tuple[Problem, ...]:
    """Return the problems of one file and its snapshots with their fixes."""
    folder = detail.folder
    return _explained(detail.problems, project=folder.project, folder=Path(folder.path))


def own_problems(record: OwnFolderRecord) -> tuple[Problem, ...]:
    """Return the problems of a project's folder with their fix instructions."""
    return _explained(record.problems, project=record.project, folder=Path(record.path))


def _explained(
    found: Iterable[OwnProblem], *, project: str, folder: Path
) -> tuple[Problem, ...]:
    """Return problems of a project's folder, with their fixes."""
    problems: list[Problem] = []
    for problem in found:
        reason = problem.reason
        if problem.code == "own_folder_invalid" and reason is not None:
            reason = message(f"own.folder_reason_{reason}")
        elif problem.code == "own_file_unreadable" and reason is not None:
            reason = lookup(f"own.read_error_{reason}", reason)
        place = problem.path or str(folder)
        text, instruction = explain(problem.code, path=place, reason=reason)
        problems.append(
            Problem(
                code=problem.code,
                message=text,
                instruction=instruction,
                path=problem.path,
                project=project,
                first_seen_at=problem.first_seen_at,
            )
        )
    return tuple(problems)
