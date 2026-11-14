"""Feedback reports over HTTP: ``POST /feedback`` and ``/admin/feedback`` (SPEC 9.2).

Any session sends a report ("Zgłoś uwagę" in the top bar; ``201`` with its
number). An administrator (``feedback.manage``; the local owner is one)
reads them newest first with the counts of all and of the unread ones
(``GET /admin/feedback``), marks one read or unread (``PATCH``, answering the
report) and deletes one (``DELETE``, answering ``{"status": "deleted"}``): the
core API of Nogat DEV-15.13 behind Archiwista's own role check, which the
kit's ``<nogat-admin-feedback>`` of the view „Zgłoszenia” reads. Anyone else
is refused ``403 permission_denied``, which the action log records, and an
unknown number is ``404 not_found`` (reason ``feedback_not_found``).
Hydrograf's mechanism and limits; the routes only translate:
``archiwista.services.feedback`` decides and keeps the reports in the state
database.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from archiwista.api.dependencies import authorizer
from archiwista.api.errors import problem_responses
from archiwista.api.models_feedback import (
    FeedbackChange,
    FeedbackCreated,
    FeedbackDeleted,
    FeedbackItem,
    FeedbackList,
    FeedbackListQuery,
    NewFeedback,
)
from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.security import current_principal
from archiwista.services import feedback as feedback_service

router = APIRouter(tags=["feedback"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_FeedbackId = Annotated[int, Path(description="The report's number.")]


@router.post(
    "/feedback",
    response_model=FeedbackCreated,
    status_code=201,
    responses=problem_responses(400),
)
def submit_feedback(
    body: NewFeedback, request: Request, principal: _Principal, decisions: _Authorizer
) -> FeedbackCreated:
    """Keep a report of the session's person: "Zgłoś uwagę" (any session).

    The account that sends it (an agent's person's; none for the owner of a
    local installation) and the request's `User-Agent` are kept with it.
    """
    record = feedback_service.submit(
        decisions.state,
        principal,
        message=body.message,
        contact=body.contact,
        page_url=body.page_url,
        diagnostics=body.diagnostics,
        user_agent=request.headers.get("user-agent"),
    )
    return FeedbackCreated(id=record.id)


@router.get(
    "/admin/feedback", response_model=FeedbackList, responses=problem_responses(400)
)
def list_feedback(
    page: Annotated[FeedbackListQuery, Query()],
    principal: _Principal,
    decisions: _Authorizer,
) -> FeedbackList:
    """Return a page of the reports, newest first (administrators).

    `total` counts every report, `unread_count` those nobody marked read.
    """
    found = feedback_service.read(
        decisions, principal, limit=page.limit, offset=page.offset
    )
    return FeedbackList.of(found)


@router.patch(
    "/admin/feedback/{feedback_id}",
    response_model=FeedbackItem,
    responses=problem_responses(400, 404),
)
def update_feedback(
    feedback_id: _FeedbackId,
    body: FeedbackChange,
    principal: _Principal,
    decisions: _Authorizer,
) -> FeedbackItem:
    """Mark a report read or unread (administrators); answer it."""
    record = feedback_service.mark(
        decisions, principal, feedback_id, is_read=body.is_read
    )
    return FeedbackItem.of(record)


@router.delete(
    "/admin/feedback/{feedback_id}",
    response_model=FeedbackDeleted,
    responses=problem_responses(404),
)
def delete_feedback(
    feedback_id: _FeedbackId, principal: _Principal, decisions: _Authorizer
) -> FeedbackDeleted:
    """Delete a report for good (administrators)."""
    feedback_service.delete(decisions, principal, feedback_id)
    return FeedbackDeleted()
