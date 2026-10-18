"""FastAPI application: local-mode security, API routers and interface files.

``create_app`` wraps every request in ``SecurityMiddleware`` (``Host``,
``Origin``/``Sec-Fetch-Site``, session and CSRF rules, CSP and other
headers), answers errors with RFC 9457 problems, mounts the routers under
``/api/v1`` (with the OpenAPI document and the local ``/api/docs``) and
serves the build-free interface from ``archiwista/web`` (``/`` and
``/static/…``), which needs no session. Routers reach the shared objects
through ``request.app.state``: ``settings`` (``SettingsService``),
``sessions`` (``SessionStore``), ``index_path``, ``port``, ``authorizer``
(``Authorizer`` over the state database), ``queries`` (``IndexQueries``),
``registry`` (the producer plugins), the last three also as dependencies of
``archiwista.api.dependencies``, ``jobs`` (``JobSupervisor``, ``None``
without background jobs, which leaves out their routes) and ``job_streams``
(open job event streams, which the server ends as it stops).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from archiwista.api import (
    API_PREFIX,
    admin,
    health,
    projects,
    session,
    slots,
    stores,
)
from archiwista.api import jobs as job_routes
from archiwista.api import map as map_routes
from archiwista.api import settings as settings_routes
from archiwista.api.docs import install_docs, operation_id
from archiwista.api.errors import ApiError, install_error_handlers
from archiwista.auth.authorize import Authorizer
from archiwista.config import SettingsService
from archiwista.index import IndexQueries
from archiwista.jobs import JobSupervisor
from archiwista.messages import MESSAGES
from archiwista.security import SecurityMiddleware, SessionStore
from archiwista.sources.registry import APP_DISTRIBUTION, PluginRegistry
from archiwista.state import StateStore

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(
    *,
    port: int,
    settings: SettingsService,
    index_path: Path,
    state: StateStore,
    registry: PluginRegistry,
    sessions: SessionStore | None = None,
    web_dir: Path = WEB_DIR,
    jobs: JobSupervisor | None = None,
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
    sessions : SessionStore or None, optional
        Live sessions; a new, empty store when omitted.
    web_dir : Path, optional
        Interface files: ``index.html`` at ``/`` and every file under
        ``/static/``.
    jobs : JobSupervisor or None, optional
        The started supervisor of background jobs (``app.state.jobs``);
        without it the routes of jobs are left out.

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
        yield
        queries.close()

    app = FastAPI(
        title="Archiwista",
        version=version(APP_DISTRIBUTION),
        openapi_url=f"{API_PREFIX}/openapi.json",
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
    app.state.queries = queries
    app.state.jobs = jobs
    app.state.job_streams = job_routes.JobStreams()
    app.state.registry = registry
    install_error_handlers(app)
    app.include_router(session.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(stores.router, prefix=API_PREFIX)
    app.include_router(slots.router, prefix=API_PREFIX)
    app.include_router(map_routes.router, prefix=API_PREFIX)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(settings_routes.router, prefix=API_PREFIX)
    if jobs is not None:
        app.include_router(job_routes.router, prefix=API_PREFIX)
    install_docs(app)

    index_page = web_dir / "index.html"

    @app.get("/", include_in_schema=False)
    def interface() -> FileResponse:
        if not index_page.is_file():
            raise ApiError(404, "not_found", MESSAGES["api_interface_missing"])
        return FileResponse(index_page)

    app.mount("/static", StaticFiles(directory=web_dir), name="static")
    app.add_middleware(
        SecurityMiddleware, port=port, sessions=sessions, settings=settings.get
    )
    return app
