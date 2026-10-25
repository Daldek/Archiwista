"""RFC 9457 problem responses of the HTTP API (SPEC 9.1, AGI-6.3).

Every error is ``application/problem+json`` with ``type`` (the entry of its
code on the registry page), ``title`` (the registry title), ``status`` (the
registry's HTTP status), a ``detail``, ``instance`` (the request path), the
registry ``code``, a ``hint`` when a fix is known and ``details``. The texts
(``title``, ``detail``, ``hint``, the texts in ``details`` and ``errors``) are in
the language of the request's ``Accept-Language``, English without it
(AGI-6.4); the response says so with ``Content-Language`` and ``Vary``.
``details.reason`` is the
project's own cause (ERR-1): the codes of earlier versions, such as
``session_required``, ``preview_busy`` or ``area_too_large``, are reasons
now. Other members of ``details`` give the context: ``source`` for an
unavailable or incompatible producer plugin (with the pip requirement that
fixes it), ``kartograf`` or ``imgwtools`` for a producer's own error (its
exception and unchanged message), ``problems`` for invalid settings, ``job``
for the job in the way of a ``409 conflict`` (or building the preview of a
``preview_not_ready``, else ``building`` or ``build_required``),
``preview_reason`` for an ``unsupported`` preview (its code, description and
fix), ``blocked_by`` for a ``snapshot_blocked`` (why the
snapshot cannot be made now) and ``layers`` for an area file with several
layers to choose from. Invalid request data adds ``errors``: a JSON Pointer,
the type and the message of each value. ``rate_limited`` carries
``Retry-After``. Unknown routes answer ``404 not_found``, other methods
``405 method_not_allowed`` (with ``Allow``) and unexpected failures ``500
internal_error``. Errors of the services map to codes in the services
themselves (``archiwista.errors``), which the command line shares
(``archiwista.error_document``).
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from archiwista.api import API_PREFIX
from archiwista.config import SettingsValidationError
from archiwista.error_document import (
    REGISTRY_PAGE,
    Language,
    Problem,
    describe,
    language_of,
    title_of,
    validation_problem,
)
from archiwista.errors import (
    ArchiwistaError,
    AreaTooComplexError,
    AreaTooLargeError,
    AreaUnreadableError,
    ConflictError,
    IndexQueryError,
    InvalidChangeError,
    InvalidRefError,
    NotFoundError,
    OfflineModeError,
    OwnFileChangedError,
    PathOutsideRootError,
    PermissionDeniedError,
    PreviewBusyError,
    PreviewNotReadyError,
    PreviewParameterError,
    PreviewTimeoutError,
    PreviewUnavailableError,
    ProducerError,
    SnapshotBlockedError,
    SourceIncompatibleError,
    SourceUnavailableError,
)
from archiwista.messages import message

PROBLEM_MEDIA_TYPE = "application/problem+json"
# Service errors answered with a problem, each by its own code (the other
# errors of ``archiwista.errors`` are not part of the API: 500).
ANSWERED: tuple[type[ArchiwistaError], ...] = (
    PermissionDeniedError,
    PathOutsideRootError,
    NotFoundError,
    ConflictError,
    OfflineModeError,
    OwnFileChangedError,
    SnapshotBlockedError,
    AreaTooLargeError,
    AreaUnreadableError,
    AreaTooComplexError,
    InvalidChangeError,
    IndexQueryError,
    SettingsValidationError,
    ProducerError,
    InvalidRefError,
    PreviewParameterError,
    PreviewUnavailableError,
    PreviewNotReadyError,
    PreviewBusyError,
    PreviewTimeoutError,
    SourceIncompatibleError,
    SourceUnavailableError,
)
# Statuses of the framework's own errors and their codes; other 4xx are
# ``validation_error``, 5xx ``internal_error``.
_HTTP_CODES = MappingProxyType(
    {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        429: "rate_limited",
    }
)
# Statuses routes document: the example's code and reason, the catalog key of
# its detail and what the status means.
_DOCUMENTED: Mapping[int, tuple[str, str | None, str, str]] = MappingProxyType(
    {
        400: (
            "validation_error",
            "invalid_request",
            "api.validation_error",
            "Invalid parameters or body (`errors`: the JSON Pointer, type and"
            " message of each value), or a value over a limit (`details.reason`:"
            " `area_too_large` over 50 MB or 200 MB unpacked, `area_too_complex`,"
            " `invalid_ref`, `request_too_large`).",
        ),
        401: (
            "unauthorized",
            "session_required",
            "api.session_required",
            "No valid session: exchange a one-time token (POST /api/v1/session).",
        ),
        403: (
            "forbidden",
            "csrf_rejected",
            "api.csrf_missing",
            "Refused (`details.reason`): `csrf_rejected` (no or another"
            " X-Archiwista-CSRF, a foreign `Origin` or a cross-site request),"
            " `invalid_host`, `permission_denied` (A-ADR-029) or"
            " `path_outside_root`.",
        ),
        404: (
            "not_found",
            None,
            "api.route_not_found",
            "Unknown, or not visible to the session's principal.",
        ),
        409: (
            "conflict",
            "offline_mode",
            "job.offline_mode",
            "Conflicts with the current state (`details.reason`): none (another"
            " job already writes the store's index; `details.job` names it),"
            " `offline_mode` (the job needs the network), `own_file_changed` (an"
            " own-data file changed since its scan: refresh the project's own"
            " data) or `snapshot_blocked` (`details.blocked_by`).",
        ),
        500: (
            "data_error",
            "area_unreadable",
            "area.format_unknown",
            "Data the server read is malformed (`details.reason`):"
            " `area_unreadable` (an area file; `details.layers` lists the layers"
            " to choose from) or `kartograf_error` (the producer refused, with"
            " its own message in `details.kartograf`).",
        ),
        503: (
            "missing_dependency",
            "source_unavailable",
            "source.unavailable",
            "A producer plugin is missing (`source_unavailable`) or incompatible"
            " (`source_incompatible`), with `details.source` and the fix; or"
            " (`store_unavailable`) the store cannot be read and the index has"
            " no answer.",
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
        code, reason, key, description = _DOCUMENTED[status]
        detail = message(key, "en", path=f"{API_PREFIX}/…", fields="query.limit")
        responses[status] = {
            "description": description,
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                    "example": problem_example(code, detail, reason=reason),
                }
            },
        }
    return responses


class ApiError(ArchiwistaError):
    """A request failure answered with an RFC 9457 problem.

    Parameters
    ----------
    code : str
        Registry code, e.g. ``unauthorized``.
    message : str
        Description for the user, a catalog text.
    reason : str or None, optional
        The project's cause, e.g. ``session_required`` (``details.reason``).
    hint : str or None, optional
        Line telling how to fix it, a catalog text.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        reason: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, code=code, reason=reason, hint=hint)


def problem_body(
    problem: Problem, *, instance: str | None = None, lang: Language = "en"
) -> dict[str, object]:
    """Return the members of a problem (RFC 9457, AGI-6.3).

    Parameters
    ----------
    problem : Problem
        What went wrong.
    instance : str or None, optional
        The request path that failed.
    lang : {"en", "pl"}, optional
        Language of the texts: the ``title``, the ``detail``, the ``hint`` and
        the catalog messages in ``details`` and ``errors``.

    Returns
    -------
    dict[str, object]
        ``type`` (the registry page and ``#<code>``), ``title``, ``status``,
        ``detail``, ``instance`` when known, ``code``, ``hint`` when known,
        ``details`` when not empty and ``errors`` for invalid values.
    """
    shown = problem.localized(lang)
    body: dict[str, object] = {
        "type": f"{REGISTRY_PAGE}#{shown.code}",
        "title": title_of(shown.code, lang),
        "status": shown.status,
        "detail": shown.detail,
    }
    if instance is not None:
        body["instance"] = instance
    body["code"] = shown.code
    if shown.hint:
        body["hint"] = shown.hint
    if shown.details:
        body["details"] = dict(shown.details)
    if shown.errors:
        body["errors"] = list(shown.errors)
    return body


def problem_example(
    code: str,
    detail: str,
    *,
    reason: str | None = None,
    details: Mapping[str, object] | None = None,
    hint: str | None = None,
) -> dict[str, object]:
    """Return a problem for an OpenAPI example (English title).

    Parameters
    ----------
    code : str
        Registry code.
    detail : str
        Description, a catalog text.
    reason : str or None, optional
        ``details.reason``.
    details : Mapping[str, object] or None, optional
        Further members of ``details``.
    hint : str or None, optional
        Line telling how to fix it, a catalog text.
    """
    members = {**({"reason": reason} if reason else {}), **(details or {})}
    return problem_body(
        Problem(code, detail, hint, members), instance=f"{API_PREFIX}/…"
    )


def problem_response(
    problem: Problem,
    request: Request,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Return the ``application/problem+json`` response of ``problem``.

    Its texts follow the request's ``Accept-Language`` (English without it)
    whatever language the running context is in: the answer to an unexpected
    failure is made outside the middleware that sets it. ``Content-Language``
    and ``Vary`` say so (AGI-6.4).
    """
    lang = language_of(request.headers.get("accept-language"))
    sent = {**(headers or {}), "Content-Language": lang, "Vary": "Accept-Language"}
    return JSONResponse(
        problem_body(problem, instance=request.url.path, lang=lang),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=sent,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Answer every failure of a request with a problem (see the module)."""
    app.exception_handler(ApiError)(_service_error)
    for kind in ANSWERED:
        app.exception_handler(kind)(_service_error)
    app.exception_handler(RequestValidationError)(_validation_error)
    app.exception_handler(HTTPException)(_http_error)
    app.exception_handler(Exception)(_internal_error)


async def _service_error(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ArchiwistaError):  # pragma: no cover - by registration
        raise error
    headers = None
    if isinstance(error, PreviewBusyError):
        headers = {"Retry-After": str(error.retry_after_s)}
    return problem_response(describe(error), request, headers=headers)


async def _validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    return problem_response(validation_problem(error.errors()), request)


async def _http_error(request: Request, error: HTTPException) -> JSONResponse:
    status = error.status_code
    code = _HTTP_CODES.get(
        status, "internal_error" if status >= 500 else "validation_error"
    )
    if code == "not_found":
        detail: str = message("api.route_not_found")
    elif code == "method_not_allowed":
        detail = message(
            "api.method_not_allowed", method=request.method, path=request.url.path
        )
    else:
        detail = str(error.detail)
    problem = Problem(code, detail, details={"http_status": status})
    return problem_response(problem, request, headers=error.headers)


async def _internal_error(request: Request, error: Exception) -> JSONResponse:
    # Starlette re-raises the error afterwards, so the server logs it.
    problem = Problem("internal_error", message("api.internal_error"))
    return problem_response(problem, request)
