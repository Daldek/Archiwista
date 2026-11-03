"""The warm-up of previews for every interface (plan of 2026-10-25, A9; ADR-041).

``start`` takes a request to prepare the first look at current versions
ahead (``POST /previews/warm``, ``archiwista preview-warm``) and refuses
before a job exists a filter that names nothing the principal may warm: a
store that is not configured, a project the principal does not see (as an
unknown one) and an area the index does not keep, each ``404``. Any session
may warm: the job uses no network, only reads the stores and writes the
preview cache. A warm-up of a project is that project's job: only those who
see the project see it (``JobSupervisor`` reads ``params.project``), and a
warm-up without ``project`` never prepares the own data of a project. The
scheduler's warm-up after a scan (``ScanScheduler``) submits its job itself.
"""

from archiwista.auth import Principal, ProjectVisibility
from archiwista.config import AppSettings
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.services.availability import known_store


def start(
    settings: AppSettings,
    jobs: JobSupervisor,
    queries: IndexQueries,
    *,
    store: str | None,
    product: str | None,
    segment: str | None,
    project: str | None,
    area_id: str | None,
    actor: Principal,
    visible: ProjectVisibility,
) -> JobRecord:
    """Check a request for a warm-up of previews, then start the job.

    Parameters
    ----------
    settings : AppSettings
        The configured stores.
    jobs : JobSupervisor
        Started supervisor of the job.
    queries : IndexQueries
        The local index: the project and the area.
    store, product, segment : str or None
        Only the current versions of this configured store, product (its
        id) and segment; ``None``: every one.
    project : str or None
        Only the current versions this project pins and the working files
        of its own data (its key); ``None``: the stores' current versions
        and no own data.
    area_id : str or None
        Only the current versions within this area the index keeps.
    actor : Principal
        Who asks: the job's actor.
    visible : ProjectVisibility
        The projects ``actor`` sees.

    Returns
    -------
    JobRecord
        The job, ``queued`` or already ``running``, with no store; its
        parameters are the filters (``WARM_FILTERS``, ``since`` ``None``).
        A request of the filters of a waiting warm-up returns that job.

    Raises
    ------
    NotFoundError
        ``store`` is not configured, ``project`` is no project ``actor``
        sees, or the index keeps no area ``area_id``.
    """
    known_store(settings, store)
    if project is not None and queries.project(project, visible=visible) is None:
        raise NotFoundError(message("project.not_found", project=project))
    if area_id is not None and queries.area(area_id) is None:
        raise NotFoundError(message("api.area_unknown", area=area_id))
    params = {
        "store": store,
        "product": product,
        "segment": segment,
        "project": project,
        "area_id": area_id,
    }
    return jobs.submit("preview_warm", params=params, actor=actor)
