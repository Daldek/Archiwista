"""FastAPI application: local-mode security, API routers and interface files.

``create_app`` wraps every request in ``LanguageMiddleware`` (the language of
its texts from ``Accept-Language``), outermost, and ``SecurityMiddleware``
(``Host``, ``Origin``/``Sec-Fetch-Site``, session cookie and CSRF token rules,
body limits, CSP and other
headers), answers errors with RFC 9457 problems, mounts the routers under
``/api/v1`` (with the OpenAPI document and the local ``/api/docs``) and
serves the build-free interface from ``archiwista/web`` (``/`` and
``/static/…``, revalidated on every use: ``InterfaceFiles``), which needs no
session. Routers reach the shared objects
through ``request.app.state``: ``settings`` (``SettingsService``),
``sessions`` (``SessionStore``), ``index_path``, ``port``, ``authorizer``
(``Authorizer`` over the state database), ``queries`` (``IndexQueries``),
``registry`` (the producer plugins), the last three also as dependencies of
``archiwista.api.dependencies``, ``jobs`` (``JobSupervisor``, ``None``
without background jobs, which leaves out their routes), ``job_streams``
(open job event streams, which the server ends as it stops), ``previews``
(``RenderPool`` with its preview cache, ``None`` without one),
``area_files`` (``AreaFiles``: copies of area files and their reader),
``area_refreshes`` (``AreaRefreshes``: the areas' slots rescanned in the
last minute), ``layer_memo`` (``LayerMemo``: the local layers of the last
answers, for their images) and ``on_redeem`` (told when a one-time token
starts a session).
"""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from archiwista.api import (
    API_PREFIX,
    OPENAPI_PATH,
    admin,
    health,
    projects,
    session,
    slots,
    stores,
)
from archiwista.api import actions as action_routes
from archiwista.api import areas as area_routes
from archiwista.api import availability as availability_routes
from archiwista.api import commands as command_routes
from archiwista.api import compare as compare_routes
from archiwista.api import jobs as job_routes
from archiwista.api import layers as layer_routes
from archiwista.api import map as map_routes
from archiwista.api import owndata as owndata_routes
from archiwista.api import previews as preview_routes
from archiwista.api import settings as settings_routes
from archiwista.api import stations as station_routes
from archiwista.api.docs import install_docs, operation_id
from archiwista.api.errors import ApiError, install_error_handlers
from archiwista.api.language import LanguageMiddleware
from archiwista.areas import AreaFiles, prune_area_copies
from archiwista.auth.authorize import Authorizer
from archiwista.config import SettingsService
from archiwista.index import IndexQueries
from archiwista.jobs import JobSupervisor
from archiwista.messages import message
from archiwista.previews.pool import RenderPool
from archiwista.security import (
    SecurityMiddleware,
    SessionStore,
    TokenKind,
    session_principals,
)
from archiwista.services.layers import LayerMemo
from archiwista.sources.registry import APP_DISTRIBUTION, PluginRegistry
from archiwista.state import StateStore

WEB_DIR = Path(__file__).resolve().parent / "web"


class InterfaceFiles(StaticFiles):
    """Interface files the browser revalidates on every use.

    Every answer, ``304`` included, carries ``Cache-Control: no-cache``: a
    browser asks again with the ``ETag`` before reusing a file (``304`` when
    unchanged), so after an upgrade it never keeps the ES modules or page of
    the previous version by heuristic freshness.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        """Answer a file (or ``304``) that must be revalidated before reuse."""
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["cache-control"] = "no-cache"
        return response


def create_app(
    *,
    port: int,
    settings: SettingsService,
    index_path: Path,
    state: StateStore,
    registry: PluginRegistry,
    areas_dir: Path,
    sessions: SessionStore | None = None,
    web_dir: Path = WEB_DIR,
    jobs: JobSupervisor | None = None,
    previews: RenderPool | None = None,
    on_redeem: Callable[[TokenKind], None] | None = None,
) -> FastAPI:
    """Build the Archiwista application for one server.

    Parameters
    ----------
    port : int
        Port the server listens on; ``Host`` must name it.
    settings : SettingsService
        Settings in effect; each response's CSP follows their current value.
    index_path : Path
        Local index (catalog, projects, hashes of one-time session tokens).
    state : StateStore
        State database: accounts, groups and project access (A-ADR-029).
    registry : PluginRegistry
        Producer plugins: their states, and adapters for requests needing a
        producer (project status, sheet grids, areas in another CRS).
    areas_dir : Path
        Copies of uploaded area files (``AppPaths.areas_dir``); those older
        than 7 days are deleted at start-up (``app.state.area_files``).
    sessions : SessionStore or None, optional
        Live sessions; a new, empty store when omitted.
    web_dir : Path, optional
        Interface files: ``index.html`` at ``/`` and every file under
        ``/static/``.
    jobs : JobSupervisor or None, optional
        The started supervisor of background jobs (``app.state.jobs``);
        without it the routes of jobs are left out.
    previews : RenderPool or None, optional
        The started render pool with its preview cache
        (``app.state.previews``); the server closes both.
    on_redeem : Callable[[TokenKind], None] or None, optional
        Called with the token's kind after a one-time token starts a session,
        e.g. ``archiwista serve`` deleting the browser's launch file.

    Returns
    -------
    FastAPI
        The application, ready for Uvicorn or a test client.
    """
    if sessions is None:
        sessions = SessionStore()
    queries = IndexQueries(index_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        prune_area_copies(areas_dir)
        yield
        queries.close()

    app = FastAPI(
        title="Archiwista",
        version=version(APP_DISTRIBUTION),
        openapi_url=OPENAPI_PATH,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.index_path = index_path
    app.state.port = port
    app.state.authorizer = Authorizer(state, settings.get)
    # Who sessions act as now: the middleware's check and the session routes.
    app.state.principals = session_principals(state, index_path)
    app.state.queries = queries
    app.state.jobs = jobs
    app.state.previews = previews
    app.state.job_streams = job_routes.JobStreams()
    app.state.registry = registry
    app.state.area_files = AreaFiles(areas_dir)
    app.state.on_redeem = on_redeem
    app.state.area_refreshes = area_routes.AreaRefreshes()
    app.state.layer_memo = LayerMemo()
    install_error_handlers(app)
    app.include_router(session.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(stores.router, prefix=API_PREFIX)
    app.include_router(preview_routes.router, prefix=API_PREFIX)
    app.include_router(slots.router, prefix=API_PREFIX)
    app.include_router(map_routes.router, prefix=API_PREFIX)
    app.include_router(station_routes.router, prefix=API_PREFIX)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(settings_routes.router, prefix=API_PREFIX)
    app.include_router(area_routes.router, prefix=API_PREFIX)
    app.include_router(availability_routes.router, prefix=API_PREFIX)
    app.include_router(compare_routes.router, prefix=API_PREFIX)
    app.include_router(command_routes.router, prefix=API_PREFIX)
    app.include_router(layer_routes.router, prefix=API_PREFIX)
    app.include_router(owndata_routes.router, prefix=API_PREFIX)
    if jobs is not None:
        app.include_router(job_routes.router, prefix=API_PREFIX)
        app.include_router(owndata_routes.job_router, prefix=API_PREFIX)
        app.include_router(availability_routes.job_router, prefix=API_PREFIX)
        app.include_router(action_routes.router, prefix=API_PREFIX)
        app.include_router(projects.job_router, prefix=API_PREFIX)
        app.include_router(preview_routes.job_router, prefix=API_PREFIX)
    install_docs(app)

    index_page = web_dir / "index.html"
    interface_files = InterfaceFiles(directory=web_dir)

    @app.get("/", include_in_schema=False)
    def interface(request: Request) -> Response:
        if not index_page.is_file():
            raise ApiError("not_found", message("api.interface_missing"))
        return interface_files.file_response(
            index_page, index_page.stat(), request.scope
        )

    app.mount("/static", interface_files, name="static")
    app.add_middleware(
        SecurityMiddleware,
        port=port,
        sessions=sessions,
        settings=settings.get,
        principals=app.state.principals,
    )
    app.add_middleware(LanguageMiddleware)
    return app
