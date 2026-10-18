"""RFC 9457 problem responses of the HTTP API (SPEC 9.1).

Every error is ``application/problem+json`` with ``type``, ``title``,
``status``, a Polish ``detail`` and a stable machine ``code`` that does not
depend on the Polish text. ``title`` comes from ``MESSAGES["api_title_<code>"]``.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from archiwista.api import API_PREFIX
from archiwista.errors import ArchiwistaError
from archiwista.messages import MESSAGES

PROBLEM_MEDIA_TYPE = "application/problem+json"


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


def problem_response(status: int, code: str, detail: str) -> JSONResponse:
    """Return an ``application/problem+json`` response.

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
    JSONResponse
        Problem with ``type`` ``/api/v1/problems/<code with hyphens>``.
    """
    body = {
        "type": f"{API_PREFIX}/problems/{code.replace('_', '-')}",
        "title": MESSAGES[f"api_title_{code}"],
        "status": status,
        "detail": detail,
        "code": code,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


def install_error_handlers(app: FastAPI) -> None:
    """Answer ``ApiError`` and invalid request data with problems."""
    app.exception_handler(ApiError)(_api_error)
    app.exception_handler(RequestValidationError)(_validation_error)


async def _api_error(request: Request, error: ApiError) -> JSONResponse:
    return problem_response(error.status, error.code, error.detail)


async def _validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    fields = ", ".join(
        ".".join(str(part) for part in item.get("loc", ())) for item in error.errors()
    )
    detail = MESSAGES["api_validation_error"].format(fields=fields)
    return problem_response(422, "validation_error", detail)
