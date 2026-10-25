"""One description of an error for every interface (AGI-1.2, AGI-6.3, ERR-4).

``describe`` reduces an ``ArchiwistaError`` to a ``Problem``: its registry
``code`` (``archiwista._errors``), a ``detail``, an optional ``hint`` and the
JSON ``details`` whose ``reason`` is the project's own cause (ERR-1). The
HTTP API answers with it as ``application/problem+json``
(``archiwista.api.errors``); the command line prints the ``archiwista-error/1``
document as the last line of standard error and exits with the registry's exit
code (``refuse``). The texts of a problem are catalog messages
(``archiwista.messages``): each interface renders them where they leave the
process, in the language of its reader (``Problem.localized``) - the API in the
``Accept-Language`` of the request, English without one, the document in
English and the line for a person on the command line in Polish. Codes,
reasons and keys are not texts.
"""

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Self, TextIO

from archiwista._errors import BY_CODE
from archiwista.errors import (
    ArchiwistaError,
    PreviewNotReadyError,
    PreviewParameterError,
    PreviewUnavailableError,
    SourceStateError,
)
from archiwista.messages import (
    Lang,
    Message,
    localize,
    localize_json,
    lookup,
    message,
    with_detail,
)
from archiwista.sources.registry import install_requirement, source_fix

ERROR_SCHEMA: Final = "archiwista-error/1"
# A command as the catalog names it: ``<group> <verb>`` (commands-1).
_COMMAND_NAME: Final = re.compile(r"^[a-z][a-z0-9-]* [a-z][a-z0-9-]*$")
# The page of the registry; ``#<code>`` is the anchor of a code (ERR-4).
REGISTRY_PAGE: Final = (
    "https://github.com/Daldek/Nogat/blob/main/standards/ERROR_REGISTRY.md"
)
# The exit status of a code that has no exit code (the REST-only codes).
FALLBACK_EXIT_STATUS: Final = 1

type Language = Lang


@dataclass(frozen=True, slots=True)
class Problem:
    """What an interface reports about one error.

    Attributes
    ----------
    code : str
        Registry code.
    detail : str
        Description of what happened, a catalog message when it has a key.
    hint : str or None
        Line telling how to fix it.
    details : Mapping[str, Any]
        JSON object: ``reason`` and the context of the error; a catalog
        message may be among its values.
    errors : tuple[Mapping[str, object], ...]
        Invalid values of a request: ``pointer`` (JSON Pointer), ``type``,
        ``message``.
    """

    code: str
    detail: str
    hint: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[Mapping[str, object], ...] = ()

    @property
    def status(self) -> int:
        """int: the HTTP status of the code (ERR §2)."""
        return BY_CODE[self.code].http_status or 500

    @property
    def exit_code(self) -> int | None:
        """Int or None: the exit code of the code (``None`` for REST-only codes)."""
        return BY_CODE[self.code].exit_code

    def localized(self, lang: Language) -> Self:
        """Return the problem with every catalog message in it rendered in ``lang``.

        The ``detail``, the ``hint``, the values of the ``details`` and of the
        ``errors`` become plain strings; a text that is no catalog message
        (a library's own, a name) is as it is.
        """
        return type(self)(
            self.code,
            localize(self.detail, lang),
            None if self.hint is None else localize(self.hint, lang),
            localize_json(self.details, lang),
            tuple(localize_json(item, lang) for item in self.errors),
        )


def title_of(code: str, lang: Language = "en") -> str:
    """Return the registry title of ``code`` in ``lang`` (ERR-6)."""
    entry = BY_CODE[code]
    return entry.title_pl if lang == "pl" else entry.title


def language_of(header: str | None) -> Language:
    """Return ``"pl"`` when ``Accept-Language`` prefers Polish, else ``"en"``.

    The tag with the highest quality wins, the first of equals; any other
    language, no header and a malformed one are English (AGI-6.4).
    """
    best: tuple[float, str] | None = None
    for item in (header or "").split(","):
        tag, _, rest = item.strip().partition(";")
        weight = 1.0
        key, _, number = rest.strip().partition("=")
        if key.strip() == "q":
            try:
                weight = float(number)
            except ValueError:
                weight = 0.0
        if tag and weight > 0 and (best is None or weight > best[0]):
            best = (weight, tag.strip().lower())
    return "pl" if best is not None and best[1].split("-")[0] == "pl" else "en"


def pointer(location: str | Iterable[object]) -> str:
    """Return the JSON Pointer (RFC 6901) of a dotted location.

    Parameters
    ----------
    location : str or Iterable[object]
        ``query.limit`` or the parts of FastAPI's ``loc``, e.g.
        ``("body", "areas", 0)``.

    Returns
    -------
    str
        ``/query/limit`` or ``/body/areas/0``.
    """
    parts = location.split(".") if isinstance(location, str) else list(location)
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "".join(f"/{part}" for part in escaped)


def preview_reason(code: str, detail: str | None = None) -> dict[str, Any]:
    """Return why a file has no preview: its code, description and fix.

    Parameters
    ----------
    code : str
        Reason code (``PreviewReason``).
    detail : str or None, optional
        The library's message without paths, when the request found it.
    """
    return {
        "code": code,
        "message": lookup(f"preview.reason_{code}", code),
        "fix": lookup(f"preview.fix_{code}", ""),
        "detail": detail,
    }


def _error_message(item: Mapping[str, Any]) -> object:
    """Return the text of a pydantic error, as a catalog message when it is one.

    A validator that raised ``ValueError(message(…))`` keeps its message,
    which pydantic turns into the text ``Value error, …``; it is rendered
    again in the language of the reader.
    """
    text = item.get("msg")
    context = item.get("ctx")
    error = context.get("error") if isinstance(context, Mapping) else None
    first = error.args[0] if isinstance(error, ValueError) and error.args else None
    if isinstance(first, Message) and isinstance(text, str) and text.endswith(first):
        return message("api.value_error", detail=first)
    return text


def validation_problem(errors: Iterable[Mapping[str, Any]]) -> Problem:
    """Return the ``validation_error`` of invalid request data.

    Parameters
    ----------
    errors : Iterable[Mapping[str, Any]]
        Pydantic errors; ``loc`` starts with where the value came from
        (``query``, ``path``, ``body``), as FastAPI reports it.
    """
    items = tuple(
        {
            "pointer": pointer(item.get("loc", ())),
            "type": item.get("type"),
            "message": _error_message(item),
        }
        for item in errors
    )
    fields = ", ".join(
        str(item["pointer"]).strip("/").replace("/", ".") for item in items
    )
    return Problem(
        "validation_error",
        message("api.validation_error", fields=fields),
        details={"reason": "invalid_request"},
        errors=items,
    )


def describe(error: ArchiwistaError) -> Problem:
    """Return what an interface reports about ``error``.

    The ``detail`` of an unavailable or incompatible plugin ends with its
    fix, which is also the ``hint``; the ``details`` hold the machine-readable
    rest: ``source`` (the plugin and the requirement that fixes it),
    ``preview_reason`` (why a file has no preview), ``job`` (the job in the
    way, or building the preview), ``building`` or ``build_required`` (a
    preview that is not ready), ``problems`` (invalid settings), ``layers``
    (an area file with several layers) and ``<package>`` (a producer's own
    exception and message).
    """
    detail = error.message
    hint = error.hint
    details: dict[str, Any] = dict(error.details)
    errors: tuple[Mapping[str, object], ...] = ()
    if isinstance(error, SourceStateError) and error.state is not None:
        state = error.state
        fix = source_fix(state)
        detail = message("api.source_problem", message=detail, fix=fix)
        hint = hint or fix
        details["source"] = {
            "id": state.producer,
            "state": state.status,
            "package_version": state.package_version,
            "supported_versions": state.supported_versions,
            "requirement": install_requirement(state.producer),
        }
    elif isinstance(error, PreviewUnavailableError):
        reason = preview_reason(error.reason, error.detail)
        # The library's detail explains the reason; the fix closes the text.
        detail = message(
            "preview.unavailable_detail",
            message=with_detail(reason["message"], error.detail),
            fix=reason["fix"],
        )
        hint = hint or reason["fix"] or None
        details["preview_reason"] = reason
    elif isinstance(error, PreviewNotReadyError):
        if error.state == "building":
            details["building"] = True
        elif error.job_id is None:
            details["build_required"] = True
        else:
            details["job"] = {
                "id": error.job_id,
                "kind": error.kind,
                "state": error.state,
            }
    elif isinstance(error, PreviewParameterError):
        errors = (
            {
                "pointer": pointer(error.field),
                "type": "value_error",
                "message": error.message,
            },
        )
    return Problem(error.code, detail, hint, details, errors)


def error_document(
    problem: Problem, *, command: str | None = None, lang: Language = "en"
) -> dict[str, Any]:
    """Return the ``archiwista-error/1`` document of ``problem`` (AGI-4.3).

    Parameters
    ----------
    problem : Problem
        What went wrong.
    command : str or None, optional
        The command line's command as ``<group> <verb>``, e.g. ``preview
        thumbnail``; left out when it has another shape.
    lang : {"en", "pl"}, optional
        Language of the ``title`` and of every catalog message in the
        document; machine output is English (AGI-9.2).

    Returns
    -------
    dict[str, Any]
        ``schema``, ``code``, ``title``, ``message``, ``hint`` when there is
        one, ``details`` (with ``errors`` for invalid values), ``exit_code``
        and ``command`` when known.
    """
    shown = problem.localized(lang)
    details = dict(shown.details)
    if shown.errors:
        details["errors"] = list(shown.errors)
    document: dict[str, Any] = {
        "schema": ERROR_SCHEMA,
        "code": shown.code,
        "title": title_of(shown.code, lang),
        "message": shown.detail,
    }
    if shown.hint:
        document["hint"] = shown.hint
    document["details"] = details
    document["exit_code"] = shown.exit_code
    if command and _COMMAND_NAME.match(command):
        document["command"] = command
    return document


def refuse(problem: Problem, err: TextIO, *, command: str | None = None) -> int:
    """Report a refusal of a command and return its exit status (ERR-4).

    The ``detail`` in Polish goes to ``err`` for the person, then the English
    error document as one compact JSON line, the last one (AGI-3.3). Nothing
    goes to standard output (AGI-3.2), with or without ``--json``.

    Parameters
    ----------
    problem : Problem
        What went wrong.
    err : TextIO
        Standard error.
    command : str or None, optional
        The command, for the document.

    Returns
    -------
    int
        The registry's exit code; ``1`` for a REST-only code.
    """
    err.write(f"{localize(problem.detail, 'pl')}\n")
    document = error_document(problem, command=command)
    err.write(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n")
    exit_code = problem.exit_code
    return FALLBACK_EXIT_STATUS if exit_code is None else exit_code


def exception_problem(error: BaseException, message: str) -> Problem:
    """Return the problem of an exception that stopped a command.

    Parameters
    ----------
    error : BaseException
        What stopped it: an ``ArchiwistaError`` keeps its code, details and
        hint; an ``OSError`` is ``io_error``, an SQLite error
        ``store_unavailable``, anything else ``internal_error``.
    message : str
        The description to show.
    """
    if isinstance(error, ArchiwistaError):
        return Problem(error.code, message, error.hint, error.details)
    if isinstance(error, OSError):
        return Problem("io_error", message, details={"reason": "io_failure"})
    if isinstance(error, sqlite3.Error):
        return Problem(
            "store_unavailable", message, details={"reason": "database_unavailable"}
        )
    return Problem("internal_error", message)


def fail(
    err: TextIO,
    code: str,
    message: str,
    *,
    reason: str | None = None,
    hint: str | None = None,
    command: str | None = None,
) -> int:
    """Report a failure with a registry ``code`` and return the exit status.

    Parameters
    ----------
    err : TextIO
        Standard error.
    code : str
        Registry code.
    message : str
        Description.
    reason : str or None, optional
        The project's cause (``details["reason"]``).
    hint : str or None, optional
        Line telling how to fix it.
    command : str or None, optional
        The command, for the document.
    """
    details = {"reason": reason} if reason else {}
    return refuse(Problem(code, message, hint, details), err, command=command)
