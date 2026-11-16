"""A person's sessions: the list and ending one (SPEC 9.2, ADR-046).

``GET /api/v1/sessions`` lists the live sessions of the session's person,
those of its agents too, and with ``?user=`` an administrator reads another
account's. ``DELETE /api/v1/sessions/{label}`` ends one of the person's
sessions, an administrator's any session, and lands in the action log as
``session.ended``; ``DELETE /api/v1/users/{user_id}/sessions``
(``api/admin.py``) ends all of an account's. A session that may no longer
act (its account disabled, its sessions revoked) is not listed.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.dependencies import authorizer
from archiwista.api.errors import problem_responses
from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.errors import NotFoundError
from archiwista.messages import message
from archiwista.security import (
    Session,
    SessionMethod,
    SessionStore,
    current_principal,
    require_session,
)

router = APIRouter(prefix="/sessions", tags=["session"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]

_ITEM_EXAMPLE: dict[str, Any] = {
    "label": "3f9c1a7e",
    "kind": "browser",
    "method": "password",
    "client": "10.0.0.5",
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0",
    "created_at": "2026-10-19T08:00:00Z",
    "last_seen_at": "2026-10-19T11:42:00Z",
    "expires_at": "2026-10-19T19:42:00Z",
    "current": True,
}


class SessionItem(BaseModel):
    """A live session of a person or of an agent acting for them."""

    model_config = ConfigDict(json_schema_extra={"examples": [_ITEM_EXAMPLE]})

    label: str = Field(description="Label of the session (DELETE /sessions/{label}).")
    kind: Literal["browser", "agent"] = Field(
        description="A person's own session, or an agent's acting for them."
    )
    method: SessionMethod = Field(
        description="How it started: `startup`, `token`, `password`, `proxy`."
    )
    client: str | None = Field(description="Client address of its first request.")
    user_agent: str | None = Field(
        description="Its browser or program (`User-Agent`, at most 200 characters)."
    )
    created_at: datetime
    last_seen_at: datetime = Field(description="Its last request.")
    expires_at: datetime = Field(description="Its end unless used again.")
    current: bool = Field(description="The session of this request.")

    @classmethod
    def of(cls, session: Session, *, current: bool) -> Self:
        """Return the item of a session."""
        return cls(
            label=session.label,
            kind="agent" if session.kind == "agent" else "browser",
            method=session.method,
            client=session.client,
            user_agent=session.user_agent,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at or session.created_at,
            expires_at=session.expires_at,
            current=current,
        )


class SessionList(BaseModel):
    """Live sessions, oldest first."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_ITEM_EXAMPLE]}]}
    )

    items: list[SessionItem]


@router.get("", response_model=SessionList, responses=problem_responses(403, 404))
def list_sessions(
    request: Request,
    session: Annotated[Session, Depends(require_session)],
    principal: _Principal,
    decisions: _Authorizer,
    user: Annotated[
        str | None,
        Query(description="Another account's sessions (an administrator)."),
    ] = None,
) -> SessionList:
    """List the live sessions of the person, their agents' too, oldest first.

    `?user=` lists another account's (`admin`; `403 permission_denied`
    otherwise, `404` for an unknown account). `current` marks the session of
    this request.
    """
    owner = principal.id if user is None else user
    if owner != principal.id:
        decisions.require(principal, "users.manage")
        if decisions.state.user(owner) is None:
            raise NotFoundError(message("state.user_not_found", id=owner))
    sessions: SessionStore = request.app.state.sessions
    acting: Callable[[Session], Principal | None] = request.app.state.principals
    return SessionList(
        items=[
            SessionItem.of(item, current=item.csrf_token == session.csrf_token)
            for item in sessions.live(owner)
            if acting(item) is not None
        ]
    )


@router.delete(
    "/{label}",
    status_code=204,
    response_class=Response,
    responses=problem_responses(404),
)
def end_session_label(
    label: Annotated[str, Path(description="Label of the session.")],
    request: Request,
    principal: _Principal,
    decisions: _Authorizer,
) -> Response:
    """End one session at once: one of the person's, any for an administrator.

    The session's next request answers `401 session_required`. An unknown
    label, or one of another person's session, answers `404`.
    """
    sessions: SessionStore = request.app.state.sessions
    owner = None if decisions.can(principal, "users.manage") else principal.id
    ended = sessions.end_label(label, owner=owner)
    if ended is None:
        raise NotFoundError(message("auth.session_unknown", label=label))
    decisions.state.record(
        principal, "session.ended", ended.principal_id, details={"label": label}
    )
    return Response(status_code=204)
