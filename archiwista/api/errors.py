"""RFC 9457 problem responses of the HTTP API (SPEC 9.1).

Every error is ``application/problem+json`` with ``type``, ``title``,
``status``, a Polish ``detail`` and a stable machine code that does not
depend on the Polish text. ``title`` comes from ``MESSAGES["api_title_<code>"]``.
Errors of the services map to codes in one table (``PROBLEMS``), which the
command line uses too.
"""

from collections.abc import Mapping
from types import MappingProxyType

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from archiwista.api import API_PREFIX
from archiwista.errors import (
    ArchiwistaError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
    PermissionDeniedError,
)
from archiwista.messages import MESSAGES

PROBLEM_MEDIA_TYPE = "application/problem+json"
# Service errors answered with a problem: HTTP status and machine code.
PROBLEMS: Mapping[type[ArchiwistaError], tuple[int, str]] = MappingProxyType(
    {
        PermissionDeniedError: (403, "permission_denied"),
        NotFoundError: (404, "not_found"),
        ConflictError: (409, "conflict"),
        InvalidChangeError: (422, "validation_error"),
    }
)


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


def problem_body(status: int, code: str, detail: str) -> dict[str, object]:
    """Return the members of a problem (also printed by ``--json`` commands).

    Parameters
    ----------
    status : int
        HTTP status code.
    code : str
        Stable machine code; ``MESSAGES`` must hold ``api_title_<code>``.
    detail : str
        Polish description for the user.

    Returns
    -------
    dict[str, object]
        ``type`` (``/api/v1/problems/<code with hyphens>``), ``title``,
        ``status``, ``detail`` and ``code``.
    """
    return {
        "type": f"{API_PREFIX}/problems/{code.replace('_', '-')}",
        "title": MESSAGES[f"api_title_{code}"],
        "status": status,
        "detail": detail,
        "code": code,
    }


def problem_response(status: int, code: str, detail: str) -> JSONResponse:
    """Return an ``application/problem+json`` response (see ``problem_body``)."""
    return JSONResponse(
        problem_body(status, code, detail),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def problem_of(error: ArchiwistaError) -> tuple[int, str] | None:
    """Return the status and code a service error is answered with, if any."""
    return next(
        (problem for kind, problem in PROBLEMS.items() if isinstance(error, kind)),
        None,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Answer ``ApiError``, service errors and invalid request data with problems."""
    app.exception_handler(ApiError)(_api_error)
    for kind in PROBLEMS:
        app.exception_handler(kind)(_service_error)
    app.exception_handler(RequestValidationError)(_validation_error)


async def _api_error(request: Request, error: ApiError) -> JSONResponse:
    return problem_response(error.status, error.code, error.detail)


async def _service_error(request: Request, error: Exception) -> JSONResponse:
    problem = problem_of(error) if isinstance(error, ArchiwistaError) else None
    if problem is None:  # pragma: no cover - only registered for PROBLEMS
        raise error
    status, code = problem
    return problem_response(status, code, str(error))


async def _validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    fields = ", ".join(
        ".".join(str(part) for part in item.get("loc", ())) for item in error.errors()
    )
    detail = MESSAGES["api_validation_error"].format(fields=fields)
    return problem_response(422, "validation_error", detail)
