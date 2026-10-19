"""The API's own documentation: OpenAPI document and local ``/api/docs``.

``/api/v1/openapi.json`` documents every route under ``/api/v1`` with the
models' examples. Error responses are RFC 9457 problems
(``application/problem+json``, schema ``ProblemDetails``): each route lists
the statuses it answers, every route of a session also ``401`` and ``403``
(CSRF). ``/api/docs`` is Swagger UI served from the package
(``archiwista/api/swagger``: swagger-ui-dist 5.33.3, Apache-2.0, see its
``LICENSE`` and ``NOTICE``), without a CDN and without inline scripts, so the
server's CSP holds; both need a session, like the rest of ``/api``.
"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from archiwista.api import API_PREFIX
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_responses
from archiwista.api.models import ProblemDetails

SWAGGER_DIR = Path(__file__).resolve().parent / "swagger"
DOCS_PATH = "/api/docs"
SESSION_EXCHANGE = (f"{API_PREFIX}/session", "post")
_DESCRIPTION = """\
HTTP API of Archiwista, a local browser of Kartograf data stores (read only
in v0.1). The browser interface uses the same API.

**Session.** Exchange a one-time token (`archiwista serve` prints it in the
address fragment; `archiwista token` issues one for an agent) with
`POST /api/v1/session`; keep the `archiwista_session` cookie and the
answer's `csrf_token`, which only this answer holds. Every other request,
reads included, sends the header `X-Archiwista-CSRF` equal to `csrf_token`.
Without a session every route answers `401 session_required`, without the
header (or with another token) `403 csrf_rejected`. `DELETE /api/v1/session`
ends the session.

**Identifiers.** Stores are named by their configured id, slots and versions
by their path in the store, projects by their id; only the file card's
`paths` (copy path) and the settings hold absolute paths.

**Lists.** `GET /slots` pages with `limit` (at most 200) and the opaque
`next_cursor`; filters keep the names of the interface's filters, and
unknown parameters are refused. Answers from the index carry `stale` and
`stale_stores`: an unavailable store (a disconnected share) is answered as of
its last complete pass, never as an empty result.

**Background jobs.** `POST /stores/{store}/scan`, `…/footprints` and
`…/link-check` answer `202` with the job and `Location: /api/v1/jobs/{job}`;
while another job writes the store's index they answer `409 conflict` naming
it in `job`. `GET /jobs/{job}/events` streams the job's `progress`, `notice`
and `state` events as Server-Sent Events (`id` = event number), resumes after
`Last-Event-ID` and ends after the final state. The stream needs the CSRF
header too, so read it with an HTTP client or `fetch`, not `EventSource`.

**Areas.** `POST /areas` keeps an area: GeoJSON in WGS84 as
`application/json`, or a GeoJSON, GeoPackage or zipped Shapefile as the raw
body (at most 50 MB, an archive at most 200 MB unpacked, 100 000 vertices,
read in a process killed after 30 s); its `id` is used by `GET /slots` and
`GET /local-coverage`, which rescans the area's slots first and measures the
share in the planar CRS of each country.

**Errors** are RFC 9457 problems (`application/problem+json`) with a stable
`code` and a Polish `detail`; see the `ProblemDetails` schema.
"""
_TAGS = [
    {"name": "health", "description": "Versions, producer plugins, index state."},
    {"name": "stores", "description": "Configured stores and their state."},
    {"name": "catalog", "description": "Products, search, file cards, versions."},
    {"name": "map", "description": "Footprints in a map view and sheet grids."},
    {"name": "areas", "description": "Areas of interest and local coverage."},
    {"name": "jobs", "description": "Background jobs and their events (SSE)."},
    {"name": "projects", "description": "Projects, their pins and status (read)."},
    {"name": "settings", "description": "Settings (changes: administrators)."},
    {"name": "session", "description": "One-time tokens and the session."},
    {"name": "permissions", "description": "Accounts, groups, project access."},
]
_PAGE = """\
<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Archiwista — API</title>
<link rel="stylesheet" href="/api/docs/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="/api/docs/swagger-ui-bundle.js"></script>
<script src="/api/docs/archiwista-docs.js"></script>
</body>
</html>
"""


def operation_id(route: APIRoute) -> str:
    """Name an operation after its route function, e.g. ``list_slots``."""
    return route.name


def install_docs(app: FastAPI) -> None:
    """Serve ``/api/docs`` and document problems in the OpenAPI document."""

    def document() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = openapi_document(app)
        return app.openapi_schema

    app.openapi = document  # type: ignore[method-assign]
    app.add_api_route(DOCS_PATH, _docs_page, include_in_schema=False)
    app.mount(DOCS_PATH, StaticFiles(directory=SWAGGER_DIR), name="api-docs")


def openapi_document(app: FastAPI) -> dict[str, Any]:
    """Return the application's OpenAPI document with problems as errors.

    Responses of ``4xx`` and ``5xx`` are ``application/problem+json``
    (``ProblemDetails``) instead of FastAPI's validation schema; each route
    of a session documents ``401`` and ``403``.
    """
    document = get_openapi(
        title=app.title,
        version=app.version,
        description=_DESCRIPTION,
        routes=app.routes,
        tags=_TAGS,
    )
    schemas: dict[str, Any] = document.setdefault("components", {}).setdefault(
        "schemas", {}
    )
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)
    schemas["ProblemDetails"] = ProblemDetails.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    for path, operations in document.get("paths", {}).items():
        for method, operation in operations.items():
            responses: dict[str, Any] = operation.setdefault("responses", {})
            wanted = [
                int(status)
                for status, response in responses.items()
                if status.isdigit()
                and int(status) >= 400
                and PROBLEM_MEDIA_TYPE not in response.get("content", {})
            ]
            if (path, method) != SESSION_EXCHANGE:
                wanted.extend((401, 403))
            documented = problem_responses(*wanted)
            for status, response in documented.items():
                key = str(status)
                if PROBLEM_MEDIA_TYPE not in responses.get(key, {}).get("content", {}):
                    responses[key] = response
    return document


def _docs_page() -> HTMLResponse:
    return HTMLResponse(_PAGE)
