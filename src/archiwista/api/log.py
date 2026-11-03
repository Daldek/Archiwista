"""The action log over HTTP: ``GET /log`` and ``GET /log/export`` (plan v0.4 C9).

Both need ``log.read`` (administrators, A-ADR-047): anyone else is refused
``403 permission_denied``, which the log records. ``GET /log`` answers a page
newest first with ``total``, the number of entries its filters select, and
``next_cursor``. ``GET /log/export`` streams every entry the same filters
select as JSON Lines or CSV, an attachment with ``Cache-Control: private,
no-store``, after logging the export (``log.export``). The routes only
translate: ``archiwista.services.log`` decides, reads and writes the formats;
``archiwista log list|export`` prints the same.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from archiwista.api.dependencies import authorizer
from archiwista.api.errors import problem_responses
from archiwista.api.files import CACHE_CONTROL
from archiwista.api.models import ActionExportQuery, ActionPage, ActionPageQuery
from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.security import current_principal
from archiwista.services import log as log_service

router = APIRouter(prefix="/log", tags=["log"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_EXPORT_ANSWERS: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "Every entry the filters select, newest first, as an attachment"
            " (`archiwista-log-<UTC time>.jsonl` or `.csv`): JSON Lines, or CSV in"
            " UTF-8 with a BOM, a header of the field names and CRLF, a cell that"
            " starts with `=`, `+`, `-`, `@`, a tab, CR or LF prefixed with `'`."
        ),
        "content": {"application/jsonl": {}, "text/csv": {}},
    },
    **problem_responses(403, 400),
}


@router.get("", response_model=ActionPage, responses=problem_responses(403, 400))
def get_log(
    filters: Annotated[ActionPageQuery, Query()],
    principal: _Principal,
    decisions: _Authorizer,
) -> ActionPage:
    """Return a page of the action log, newest entry first (administrators).

    `total` counts every entry the filters select; `next_cursor` is the
    `cursor` of the next page. Reading is not logged; an export is.
    """
    return ActionPage.of(log_service.read(decisions, principal, filters.query()))


@router.get("/export", response_class=StreamingResponse, responses=_EXPORT_ANSWERS)
def export_log(
    query: Annotated[ActionExportQuery, Query()],
    principal: _Principal,
    decisions: _Authorizer,
) -> StreamingResponse:
    """Stream every entry the filters select (administrators).

    The export is logged first (`log.export` with the filters, the format and
    the count) and holds the entries older than that entry.
    """
    export = log_service.export(decisions, principal, query.query(), query.format)
    return StreamingResponse(
        export.chunks(),
        media_type=export.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "Cache-Control": CACHE_CONTROL,
        },
    )
