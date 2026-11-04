"""Feedback reports: "Zgłoś uwagę" and the administrators' list of them.

Hydrograf's mechanism with its limits: any session sends a report
(``submit``: 1 to 5,000 characters, an optional contact of at most 200, the
page's address and the browser's ``User-Agent`` of at most 500 each, and,
when the person attaches them, the interface's diagnostics of at most
100,000 characters of compact JSON); the state database keeps it with the
account that sent it, none for the owner of a local installation. The
administrators read them newest first (``read``), mark each one read or
unread (``mark``) and delete it (``delete``): ``feedback.manage``, which
anyone else is refused with ``403 permission_denied`` (logged as every
refusal). Nothing else is logged: a report changes nothing anyone may do.
``POST /feedback`` and ``/admin/feedback`` call these.
"""

from collections.abc import Mapping

from archiwista.auth import LOCAL_PRINCIPAL_ID, Principal
from archiwista.auth.authorize import Authorizer
from archiwista.state import FeedbackPage, FeedbackRecord, StateStore

MESSAGE_MAX_LENGTH = 5000
CONTACT_MAX_LENGTH = 200
PAGE_URL_MAX_LENGTH = 500
USER_AGENT_MAX_LENGTH = 500
# Characters of the diagnostics as compact JSON (no spaces after separators).
DIAGNOSTICS_MAX_LENGTH = 100_000
DEFAULT_FEEDBACK_LIMIT = 50
MAX_FEEDBACK_LIMIT = 200


def submit(
    state: StateStore,
    principal: Principal,
    *,
    message: str,
    contact: str | None,
    page_url: str | None,
    diagnostics: Mapping[str, object] | None,
    user_agent: str | None,
) -> FeedbackRecord:
    """Keep a report a session sends; any session may.

    Parameters
    ----------
    state : StateStore
        Where the report is kept.
    principal : Principal
        Who sends it: its account (an agent's person's) is kept, none for the
        owner of a local installation.
    message, contact, page_url, diagnostics
        The report, within the limits of this module (the API's model
        checks them).
    user_agent : str or None
        The request's ``User-Agent``, cut to 500 characters.
    """
    return state.add_feedback(
        user_id=None if principal.id == LOCAL_PRINCIPAL_ID else principal.id,
        message=message,
        contact=contact,
        page_url=page_url,
        user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
        diagnostics=diagnostics,
    )


def read(
    authorizer: Authorizer, principal: Principal, *, limit: int, offset: int
) -> FeedbackPage:
    """Return a page of the reports, newest first, with their counts.

    Raises
    ------
    PermissionDeniedError
        The principal is no administrator.
    """
    authorizer.require(principal, "feedback.manage")
    return authorizer.state.feedback(limit=limit, offset=offset)


def mark(
    authorizer: Authorizer, principal: Principal, feedback_id: int, *, is_read: bool
) -> FeedbackRecord:
    """Mark a report read or unread; return it.

    Raises
    ------
    PermissionDeniedError
        The principal is no administrator.
    NotFoundError
        No report has this number (reason ``feedback_not_found``).
    """
    authorizer.require(principal, "feedback.manage", target=str(feedback_id))
    return authorizer.state.set_feedback_read(feedback_id, is_read=is_read)


def delete(authorizer: Authorizer, principal: Principal, feedback_id: int) -> None:
    """Delete a report for good.

    Raises
    ------
    PermissionDeniedError
        The principal is no administrator.
    NotFoundError
        No report has this number (reason ``feedback_not_found``).
    """
    authorizer.require(principal, "feedback.manage", target=str(feedback_id))
    authorizer.state.delete_feedback(feedback_id)
