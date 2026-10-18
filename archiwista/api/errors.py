"""RFC 9457 problem responses of the HTTP API (SPEC 9.1).

Every error is ``application/problem+json`` with ``type``, ``title``,
``status``, a Polish ``detail`` and a stable machine code that does not
depend on the Polish text. ``title`` comes from ``MESSAGES["api_title_<code>"]``.
Errors of the services map to codes in one table (``PROBLEMS``), which the
command line uses too (``problem_of``, ``service_problem``). Some problems
add members: ``source`` for an unavailable or incompatible producer plugin
(with the pip requirement that fixes it), ``kartograf`` or ``imgwtools`` for
a producer's own error (its exception and unchanged message), ``problems``
for invalid settings, ``errors`` for invalid request data, ``job`` for
the job in the way of a ``409 conflict`` and ``layers`` for an area file
with several layers to choose from. Unknown routes
answer ``404 not_found``, other methods ``405 method_not_allowed`` (with
``Allow``) and unexpected failures ``500 internal_error``.
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from archiwista.api import API_PREFIX
from archiwista.config import SettingsValidationError
from archiwista.errors import (
    ArchiwistaError,
    AreaTooComplexError,
    AreaTooLargeError,
    AreaUnreadableError,
    ConflictError,
    IndexQueryError,
    InvalidChangeError,
    JobConflictError,
    NotFoundError,
    OfflineModeError,
    PathOutsideRootError,
    PermissionDeniedError,
    ProducerError,
    SourceIncompatibleError,
    SourceStateError,
    SourceUnavailableError,
)
from archiwista.messages import MESSAGES
from archiwista.sources.registry import install_requirement, source_fix

PROBLEM_MEDIA_TYPE = "application/problem+json"
# Service errors answered with a problem: HTTP status and machine code. A
# source error without a plugin state is a store that cannot be read
# (``store_unavailable``); a producer's error is ``<producer>_error``.
PROBLEMS: Mapping[type[ArchiwistaError], tuple[int, str]] = MappingProxyType(
    {
        PermissionDeniedError: (403, "permission_denied"),
        PathOutsideRootError: (403, "path_outside_root"),
        NotFoundError: (404, "not_found"),
        ConflictError: (409, "conflict"),
        OfflineModeError: (409, "offline_mode"),
        AreaTooLargeError: (413, "area_too_large"),
        AreaUnreadableError: (422, "area_unreadable"),
        AreaTooComplexError: (422, "area_too_complex"),
        InvalidChangeError: (422, "validation_error"),
        IndexQueryError: (422, "validation_error"),
        SettingsValidationError: (422, "validation_error"),
        ProducerError: (422, "producer_error"),
        SourceIncompatibleError: (503, "source_incompatible"),
        SourceUnavailableError: (503, "source_unavailable"),
    }
)
# Codes of the producers' own errors (SPEC 9.1); other packages share one.
PRODUCER_CODES: Mapping[str, str] = MappingProxyType(
    {"kartograf": "kartograf_error", "imgwtools": "imgwtools_error"}
)
_HTTP_CODES = MappingProxyType({404: "not_found", 405: "method_not_allowed"})
# Statuses routes document: the example's code and what the status means.
_DOCUMENTED: Mapping[int, tuple[str, str, str]] = MappingProxyType(
    {
        401: (
            "session_required",
            "api_session_required",
            "No valid session: exchange a one-time token (POST /api/v1/session).",
        ),
        403: (
            "permission_denied",
            "permission_settings_write",
            "Refused: `permission_denied` (A-ADR-029), `csrf_rejected` (no"
            " X-Archiwista-CSRF on a change) or `path_outside_root`.",
        ),
        404: (
            "not_found",
            "api_route_not_found",
            "Unknown, or not visible to the session's principal.",
        ),
        409: (
            "conflict",
            "api_title_conflict",
            "Conflicts with the current state: `conflict` (e.g. another job"
            " already writes the store's index; `job` names it) or"
            " `offline_mode` (the job needs the network).",
        ),
        413: (
            "area_too_large",
            "api_title_area_too_large",
            "The body is over 50 MB, or an archive declares more than 200 MB"
            " unpacked (`area_too_large`).",
        ),
        422: (
            "validation_error",
            "api_validation_error",
            "Invalid parameters or body (`errors`, `problems`), or the producer"
            " refused (`kartograf_error`, with the producer's own message).",
        ),
        503: (
            "source_unavailable",
            "source_unavailable",
            "A producer plugin is missing (`source_unavailable`) or incompatible"
            " (`source_incompatible`), with `source` and the fix; or the store"
            " cannot be read and the index has no answer (`store_unavailable`).",
        ),
    }
)


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI responses of a route's problems (``401`` always).

    Parameters
    ----------
    *statuses : int
        Further statuses the route answers with a problem, e.g. ``404``.
    """
    responses: dict[int | str, dict[str, Any]] = {}
    for status in sorted({401, *statuses}):
        code, message, description = _DOCUMENTED[status]
        detail = MESSAGES[message].format(path=f"{API_PREFIX}/…", fields="query.limit")
        responses[status] = {
            "description": description,
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                    "example": problem_body(status, code, detail),
                }
            },
        }
    return responses


class ApiError(ArchiwistaError):
    """A request failure answered with an RFC 9457 problem.

    Parameters
    ----------
    status : int
        HTTP status code.
    code : str
        Stable machine code, e.g. ``session_required``.
    detail : str
        Polish description for the user.
    """

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def problem_body(
    status: int,
    code: str,
    detail: str,
    members: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return the members of a problem (also printed by ``--json`` commands).

    Parameters
    ----------
    status : int
        HTTP status code.
    code : str
        Stable machine code; ``MESSAGES`` must hold ``api_title_<code>``.
    detail : str
        Polish description for the user.
    members : Mapping[str, object] or None, optional
        Further members of the problem, e.g. ``source``.

    Returns
    -------
    dict[str, object]
        ``type`` (``/api/v1/problems/<code with hyphens>``), ``title``,
        ``status``, ``detail``, ``code`` and ``members``.
    """
    return {
        "type": f"{API_PREFIX}/problems/{code.replace('_', '-')}",
        "title": MESSAGES[f"api_title_{code}"],
        "status": status,
        "detail": detail,
        "code": code,
        **(members or {}),
    }


def problem_response(
    status: int,
    code: str,
    detail: str,
    members: Mapping[str, object] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Return an ``application/problem+json`` response (see ``problem_body``)."""
    return JSONResponse(
        problem_body(status, code, detail, members),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def problem_of(error: ArchiwistaError) -> tuple[int, str] | None:
    """Return the status and code a service error is answered with, if any."""
    found = next(
        (problem for kind, problem in PROBLEMS.items() if isinstance(error, kind)),
        None,
    )
    if found is None:
        return None
    status, code = found
    if isinstance(error, SourceUnavailableError) and error.state is None:
        return status, "store_unavailable"
    if isinstance(error, ProducerError):
        return status, PRODUCER_CODES.get(error.package, code)
    return status, code


def service_problem(error: ArchiwistaError) -> dict[str, object] | None:
    """Return the whole problem a service error is answered with, if any.

    The ``detail`` of an unavailable or incompatible plugin ends with its
    fix; members carry the machine-readable rest (see the module).
    """
    found = problem_of(error)
    if found is None:
        return None
    status, code = found
    detail = str(error)
    members: dict[str, object] = {}
    if isinstance(error, SourceStateError) and error.state is not None:
        state = error.state
        detail = MESSAGES["api_source_problem"].format(
            message=detail, fix=source_fix(state)
        )
        members["source"] = {
            "id": state.producer,
            "state": state.status,
            "package_version": state.package_version,
            "supported_versions": state.supported_versions,
            "requirement": install_requirement(state.producer),
        }
    elif isinstance(error, ProducerError):
        members[error.package] = {
            "exception": error.exception,
            "message": error.message,
        }
    elif isinstance(error, SettingsValidationError):
        members["problems"] = [
            {"code": problem.code, "field": problem.field, "message": problem.message}
            for problem in error.problems
        ]
    elif isinstance(error, JobConflictError):
        members["job"] = {"id": error.job_id, "kind": error.kind, "state": error.state}
    elif isinstance(error, AreaUnreadableError) and error.layers:
        members["layers"] = list(error.layers)
    return problem_body(status, code, detail, members)


def install_error_handlers(app: FastAPI) -> None:
    """Answer every failure of a request with a problem (see the module)."""
    app.exception_handler(ApiError)(_api_error)
    for kind in PROBLEMS:
        app.exception_handler(kind)(_service_error)
    app.exception_handler(RequestValidationError)(_validation_error)
    app.exception_handler(HTTPException)(_http_error)
    app.exception_handler(Exception)(_internal_error)


async def _api_error(request: Request, error: ApiError) -> JSONResponse:
    return problem_response(error.status, error.code, error.detail)


async def _service_error(request: Request, error: Exception) -> JSONResponse:
    body = service_problem(error) if isinstance(error, ArchiwistaError) else None
    if body is None:  # pragma: no cover - only registered for PROBLEMS
        raise error
    status = body["status"]
    assert isinstance(status, int)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


def validation_problem(errors: Iterable[Mapping[str, Any]]) -> dict[str, object]:
    """Return the ``422 validation_error`` problem of invalid request data.

    Parameters
    ----------
    errors : Iterable[Mapping[str, Any]]
        Pydantic errors; ``loc`` starts with where the value came from
        (``query``, ``path``, ``body``), as FastAPI reports it.
    """
    items = [
        {
            "field": ".".join(str(part) for part in item.get("loc", ())),
            "type": item.get("type"),
            "message": item.get("msg"),
        }
        for item in errors
    ]
    fields = ", ".join(str(item["field"]) for item in items)
    detail = MESSAGES["api_validation_error"].format(fields=fields)
    return problem_body(422, "validation_error", detail, {"errors": items})


async def _validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        validation_problem(error.errors()),
        status_code=422,
        media_type=PROBLEM_MEDIA_TYPE,
    )


async def _http_error(request: Request, error: HTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(error.status_code, "http_error")
    if code == "not_found":
        detail = MESSAGES["api_route_not_found"].format(path=request.url.path)
    elif code == "method_not_allowed":
        detail = MESSAGES["api_method_not_allowed"].format(
            method=request.method, path=request.url.path
        )
    else:
        detail = str(error.detail)
    return problem_response(error.status_code, code, detail, headers=error.headers)


async def _internal_error(request: Request, error: Exception) -> JSONResponse:
    # Starlette re-raises the error afterwards, so the server logs it.
    return problem_response(500, "internal_error", MESSAGES["api_internal_error"])
