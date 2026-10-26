"""The action log for administrators: pages and exports (A-ADR-047, plan v0.4 T8).

``read`` returns a page of the log, newest entry first, with the number of
entries its filters select; ``export`` streams every entry they select as
JSON Lines or CSV, for ``GET /log``, ``GET /log/export`` and ``archiwista log
list|export`` alike. Both need ``log.read`` (administrators; the local owner
is one), else ``403 permission_denied``, which the log records too. An
export is an entry of its own, ``log.export`` (target ``log``) with its
filters, format and count, written before the first byte: it holds the
entries older than that entry, so it never lists itself.

An entry is exported as ``entry_document`` gives it, which is also the
model of ``GET /log`` (``ActionEntryModel``): one line of compact JSON per
entry, or a CSV row (RFC 4180: comma, CRLF; UTF-8 with a BOM, which
spreadsheets need) under a header of the field names, with the objects
``before``, ``after`` and ``details`` as JSON text and an absent value empty.
A CSV cell starting with ``=``, ``+``, ``-``, ``@``, a tab, a carriage return
or a line feed gets a leading ``'``, so a spreadsheet shows it as text and
never runs it as a formula (OWASP "CSV injection").
"""

import csv
import io
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.state import ActionEntry, ActionPage, ActionQuery, StateStore

type ExportFormat = Literal["jsonl", "csv"]

EXPORT_FORMATS: tuple[ExportFormat, ...] = ("jsonl", "csv")
# The fields of an entry, in the order of a JSON object and of the CSV columns.
FIELDS = (
    "id",
    "at",
    "actor",
    "actor_kind",
    "session",
    "client",
    "action",
    "target",
    "outcome",
    "before",
    "after",
    "details",
)
# Entries read from the database at a time while an export streams.
EXPORT_BATCH = 500
_MEDIA_TYPES: dict[ExportFormat, str] = {
    "jsonl": "application/jsonl",
    "csv": "text/csv; charset=utf-8",
}
# What a spreadsheet may take for the start of a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\n")
_BOM = "\ufeff"


@dataclass(frozen=True, slots=True)
class LogPage:
    """A page of the action log and how many entries its filters select."""

    page: ActionPage
    total: int


@dataclass(frozen=True, slots=True)
class LogExport:
    """An export, logged and ready to stream.

    Attributes
    ----------
    format : ExportFormat
        ``jsonl`` or ``csv``.
    count : int
        How many entries it holds (``log.export`` says so too).
    filename : str
        The name of its file, ``archiwista-log-<UTC time>.<format>``.
    """

    state: StateStore
    query: ActionQuery
    format: ExportFormat
    count: int
    filename: str

    @property
    def media_type(self) -> str:
        """Return the media type of the format."""
        return _MEDIA_TYPES[self.format]

    def chunks(self) -> Iterator[str]:
        """Yield the export's text, ``EXPORT_BATCH`` entries at a time."""
        query = self.query
        if self.format == "csv":
            yield _BOM + _csv_rows([FIELDS])
        while True:
            page = self.state.actions(query)
            documents = [entry_document(entry) for entry in page.entries]
            if self.format == "csv":
                yield _csv_rows(
                    [_cell(document[name]) for name in FIELDS] for document in documents
                )
            else:
                yield "".join(_json_line(document) for document in documents)
            if page.next_cursor is None:
                return
            query = replace(query, cursor=page.next_cursor)


def read(authorizer: Authorizer, principal: Principal, query: ActionQuery) -> LogPage:
    """Return a page of the action log (``log.read``) and its filters' count.

    Raises
    ------
    PermissionDeniedError
        The principal is no administrator.
    """
    authorizer.require(principal, "log.read")
    state = authorizer.state
    return LogPage(
        state.actions(query), state.count_actions(replace(query, cursor=None))
    )


def export(
    authorizer: Authorizer,
    principal: Principal,
    query: ActionQuery,
    format: ExportFormat,
    *,
    now: datetime | None = None,
) -> LogExport:
    """Log an export of the entries the filters of ``query`` select (``log.read``).

    Parameters
    ----------
    authorizer : Authorizer
        Decides, and holds the state database with the log.
    principal : Principal
        Who exports.
    query : ActionQuery
        The filters; its ``limit`` and ``cursor`` are not used.
    format : ExportFormat
        ``jsonl`` or ``csv``.
    now : datetime or None, optional
        The time of the file's name; now when omitted.

    Returns
    -------
    LogExport
        The entries up to the newest one now, logged as ``log.export`` with
        the filters given, the format and the count.

    Raises
    ------
    PermissionDeniedError
        The principal is no administrator.
    """
    authorizer.require(principal, "log.read")
    state = authorizer.state
    newest = state.actions(ActionQuery(limit=1)).entries
    # ``cursor`` keeps the entries older than it: those up to the newest now.
    selected = replace(
        query, cursor=newest[0].id + 1 if newest else 1, limit=EXPORT_BATCH
    )
    count = state.count_actions(selected)
    state.record(
        principal,
        "log.export",
        "log",
        details={"filters": _filters(query), "format": format, "count": count},
    )
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    name = f"archiwista-log-{moment:%Y%m%dT%H%M%SZ}.{format}"
    return LogExport(state, selected, format, count, name)


def entry_document(entry: ActionEntry) -> dict[str, object]:
    """Return an entry as JSON values, the fields of ``FIELDS``; ``at`` in UTC."""
    return {
        "id": entry.id,
        "at": _utc(entry.at),
        "actor": entry.actor,
        "actor_kind": entry.actor_kind,
        "session": entry.session,
        "client": entry.client,
        "action": entry.action,
        "target": entry.target,
        "outcome": entry.outcome,
        "before": entry.before,
        "after": entry.after,
        "details": entry.details,
    }


def _filters(query: ActionQuery) -> dict[str, str]:
    """Return the filters a query gives, as ``log.export`` names them."""
    given = {
        "actor": query.actor,
        "action": query.action,
        "outcome": query.outcome,
        "target": query.target,
        "since": None if query.since is None else _utc(query.since),
        "until": None if query.until is None else _utc(query.until),
    }
    return {name: value for name, value in given.items() if value is not None}


def _utc(moment: datetime) -> str:
    """Return a time in UTC as ISO 8601 with ``Z``, as the API writes it."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_line(document: dict[str, object]) -> str:
    return _json(document) + "\n"


def _cell(value: object) -> str:
    """Return a CSV cell: empty for none, JSON for a number or an object."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else _json(value)
    return f"'{text}" if text.startswith(_FORMULA_STARTS) else text


def _csv_rows(rows: Iterable[Iterable[str]]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue()
