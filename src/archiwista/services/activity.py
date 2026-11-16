"""A project's activity from the action log (A-ADR-049 decision 14, SPEC 13).

What was done to a project and the jobs that worked on it are entries of
the action log (A-ADR-047): ``project.*`` entries whose target is the
project's access key, and ``job.start``, ``job.retry`` and ``job.cancel``
whose ``details.project`` is its key, done or failed, newest first. Whoever
sees the project reads them (``GET /projects/{project}/activity``,
``archiwista project-activity``); the client address and the session stay
the administrators' (``GET /log``). No file in the project's directory
keeps a history.
"""

from dataclasses import dataclass

from archiwista.auth import ProjectVisibility
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries
from archiwista.messages import message
from archiwista.state import ActionPage, StateStore


@dataclass(frozen=True, slots=True)
class ActivityPage:
    """A page of a project's activity and the names of its actors.

    Attributes
    ----------
    page : ActionPage
        The entries, newest first, and the cursor of the next page.
    names : dict[str, str]
        The name of each account among the page's actors; ``local``, ``-``
        and a removed account have none.
    """

    page: ActionPage
    names: dict[str, str]


def project_activity(
    state: StateStore,
    queries: IndexQueries,
    key: str,
    *,
    visible: ProjectVisibility,
    cursor: int | None = None,
    limit: int = 20,
) -> ActivityPage:
    """Return a page of a project's activity, for whoever sees the project.

    Parameters
    ----------
    state : StateStore
        The state database holding the action log and the accounts.
    queries : IndexQueries
        The index: the project's access key.
    key : str
        The project's key.
    visible : ProjectVisibility
        The projects the principal sees.
    cursor : int or None, optional
        Only the entries older than this one (``next_cursor`` of the page
        before).
    limit : int, default 20
        At most this many entries.

    Raises
    ------
    NotFoundError
        No project ``key`` the principal sees.
    """
    record = queries.project(key, visible=visible)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    page = state.project_activity(
        record.project.access_key, key, before=cursor, limit=limit
    )
    actors = {entry.actor for entry in page.entries}
    names = {user.id: user.name for user in state.users() if user.id in actors}
    return ActivityPage(page, names)
