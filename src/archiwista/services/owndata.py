"""Projects' own data for people: the data folder and its problems (decision 8).

``set_data_dir`` is the one way to give a project another data folder
(``PUT /projects/{project}/data-dir``, step 9): an administrator's
``settings.write``, the same rules as every scan (``check_own_folder``) and
then the settings' own checks. ``folder_check`` checks a project's folder
now against the rules, as the ``snapshot`` job does before it writes.
``own_problems``, ``file_problems`` and ``folder_problems`` explain the
problems a scan recorded (or a folder's state now), in Polish, without paths
of other projects.
"""

from collections.abc import Iterable
from pathlib import Path

from archiwista.auth import ALL_PROJECTS, Principal
from archiwista.auth.authorize import Authorizer
from archiwista.config import (
    AppPaths,
    AppSettings,
    SettingsProblem,
    SettingsService,
    SettingsValidationError,
    own_folder_conflict,
)
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries, OwnFileDetail, OwnFolderRecord, OwnProblem
from archiwista.messages import lookup, message
from archiwista.owndata.scan import OwnFolderCheck, check_own_folder, folder_rules
from archiwista.services.problems import Problem, explain


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

    Parameters
    ----------
    authorizer : Authorizer
        Decides ``settings.write`` (administrators; the folder is where
        snapshots are written) and which projects the principal sees.
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
    PermissionDeniedError
        Not an administrator.
    NotFoundError
        Unknown project, or one the principal does not see.
    SettingsValidationError
        The folder breaks a rule of decision 8 or is not a readable
        directory; nothing changes.
    """
    authorizer.require(principal, "settings.write")
    record = queries.project(project, visible=authorizer.visible_projects(principal))
    if record is None:
        raise NotFoundError(message("project.not_found", project=project))
    key = record.project.access_key
    current = settings.get()
    folders = dict(current.own_data_dirs)
    if path is None:
        folders.pop(key, None)
    else:
        folders[key] = path
    changed = current.model_copy(update={"own_data_dirs": folders})
    known = queries.projects(visible=ALL_PROJECTS)
    stores, others = folder_rules(changed, known)
    others.pop(key, None)
    folders_of_others = list(others.values())
    if path is not None:
        conflict = own_folder_conflict(
            Path(path), stores=stores, app_data=paths.data_dir, others=folders_of_others
        )
        if conflict is not None:
            reason, directory = conflict
            code = f"own_data_dir_{reason}"
            text = message(
                f"own.data_dir_{reason}", path=path, project=key, other=directory
            )
            field = f"own_data_dirs.{key}"
            raise SettingsValidationError([SettingsProblem(code, field, text)])
    settings.update(changed)
    return check_own_folder(
        changed, key, stores=stores, app_data=paths.data_dir, others=folders_of_others
    )


def folder_check(
    settings: AppSettings, queries: IndexQueries, paths: AppPaths, project: str
) -> OwnFolderCheck:
    """Check a project's data folder now against the rules of decision 8.

    Parameters
    ----------
    settings : AppSettings
        Settings in effect (``own_data_dirs``, the stores).
    queries : IndexQueries
        The indexed projects: their folders and stores take part in the rules.
    paths : AppPaths
        Archiwista's data directory, which no folder may overlap.
    project : str
        The project's access key (``ProjectRef.access_key``).
    """
    known = queries.projects(visible=ALL_PROJECTS)
    stores, folders = folder_rules(settings, known)
    others = [path for key, path in folders.items() if key != project]
    return check_own_folder(
        settings, project, stores=stores, app_data=paths.data_dir, others=others
    )


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
    """Return problems of a project's folder in Polish, with their fixes."""
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
