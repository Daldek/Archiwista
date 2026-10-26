"""Session routes: token exchange, the session, logging out and agents' tokens.

``POST /api/v1/session`` needs no session but passes the ``Host`` and
``Origin`` rules; it answers the session's CSRF token, which every other
``/api`` request carries in ``X-Archiwista-CSRF`` next to the session cookie
(SPEC 10.1). ``GET`` shows the session without that token, with the roles
its principal has now (the interface offers administrators' actions by them)
and whether it may write the stores (a download), ``DELETE`` ends it, and
``POST /api/v1/session/tokens`` issues a one-time token for an agent, which
an agent's own session may not do.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.dependencies import authorizer
from archiwista.api.errors import ApiError
from archiwista.auth import Principal, PrincipalKind
from archiwista.auth.authorize import Authorizer
from archiwista.errors import PermissionDeniedError
from archiwista.messages import message
from archiwista.security import (
    SESSION_COOKIE,
    Session,
    SessionStore,
    TokenKind,
    clear_session_cookie,
    current_principal,
    fragment_url,
    issue_one_time_token,
    redeem_one_time_token,
    require_session,
    set_session_cookie,
)

router = APIRouter(prefix="/session", tags=["session"])

_STATE_EXAMPLE: dict[str, Any] = {
    "actor": "local",
    "kind": "local_owner",
    "roles": ["admin", "store_writer"],
    "store_write": True,
    "label": "3f9c1a7e",
    "expires_at": "2026-10-19T12:00:00Z",
}


class SessionExchange(BaseModel):
    """One-time token to exchange for a session."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"token": "pT0Vf1mWQ3uX9aZbC2dE4g"}]},
    )

    token: str = Field(
        min_length=1,
        max_length=256,
        description=(
            "Value after #token= of the address printed by `archiwista serve`"
            " or `archiwista token`."
        ),
    )


class SessionState(BaseModel):
    """The current session."""

    model_config = ConfigDict(json_schema_extra={"examples": [_STATE_EXAMPLE]})

    actor: str = Field(
        description="Who acts: the principal's id (`local` for the computer's owner)."
    )
    kind: PrincipalKind = Field(
        description=(
            "How: `local_owner` (the owner), `user` (a signed-in person, team"
            " mode) or `agent` (for `actor`, with a token they issued)."
        )
    )
    roles: list[str] = Field(
        description=(
            "Roles `actor` has now, read again for each request: `admin`"
            " (accounts, settings, every project's data folder), `store_writer`;"
            " an agent has those of `actor`. The owner of a local installation"
            " has both."
        )
    )
    store_write: bool = Field(
        description=(
            "Whether `actor` may write the stores now (a `download` job): the role"
            " `store_writer` or the setting `store_write_for_all`, read again for"
            " each request like `roles`. Without it `POST /jobs` refuses a"
            " download with `403 permission_denied`."
        )
    )
    label: str = Field(
        description=(
            "Label of the session, recorded with its jobs and permission changes."
        )
    )
    expires_at: datetime = Field(
        description=(
            "End of the session unless used again: each request extends it by"
            " 24 h; an agent's session ends 12 h after its start at the latest."
        )
    )


class NewSession(SessionState):
    """A session just started, with its CSRF token (answered only here)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{**_STATE_EXAMPLE, "csrf_token": "Yc1hR8kq0sV3nL5tW7xZ9A"}]
        }
    )

    csrf_token: str = Field(
        description=(
            "Send as X-Archiwista-CSRF with every /api request, reads included,"
            " together with the session cookie; keep it secret."
        )
    )


class OneTimeToken(BaseModel):
    """A one-time token for an agent's session."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "token": "pT0Vf1mWQ3uX9aZbC2dE4g",
                    "url": "http://127.0.0.1:8090/#token=pT0Vf1mWQ3uX9aZbC2dE4g",
                    "label": "5b2d4c60",
                    "expires_at": "2026-10-18T12:05:00Z",
                }
            ]
        }
    )

    token: str = Field(description="Value for POST /api/v1/session (single use).")
    url: str = Field(description="Address that opens a browser session.")
    label: str = Field(
        description="Label of the session it opens, recorded with its jobs."
    )
    expires_at: datetime = Field(description="End of validity (5 minutes).")


def _state(
    session: Session, principal: Principal, decisions: Authorizer
) -> SessionState:
    return SessionState(
        actor=session.principal_id,
        kind=session.kind,
        roles=sorted(principal.roles),
        store_write=decisions.can(principal, "store.write"),
        label=session.label,
        expires_at=session.expires_at,
    )


def on_redeem(request: Request, kind: TokenKind) -> None:
    """Tell the server that a one-time token of ``kind`` started a session.

    ``archiwista serve`` deletes the browser's redirect file once its startup
    token is used (``app.state.on_redeem``; nothing without it).
    """
    hook = getattr(request.app.state, "on_redeem", None)
    if hook is not None:
        hook(kind)


@router.post("", response_model=NewSession)
def exchange_token(
    body: SessionExchange, request: Request, response: Response
) -> NewSession:
    """Exchange a one-time token for a session and its CSRF token.

    Sets the `HttpOnly` cookie `archiwista_session`; every later request also
    sends `csrf_token` as `X-Archiwista-CSRF`, since the cookie alone never
    acts. An unknown, used, expired or revoked token, or one of an account
    disabled since, answers `401 session_required`.
    """
    index_path: Path = request.app.state.index_path
    grant = redeem_one_time_token(index_path, body.token)
    if grant is None:
        raise ApiError(
            "unauthorized", message("api.token_rejected"), reason="session_required"
        )
    sessions: SessionStore = request.app.state.sessions
    session_id, session = sessions.create(grant)
    principals: Callable[[Session], Principal | None] = request.app.state.principals
    principal = principals(session)
    if principal is None:
        sessions.end(session_id)
        raise ApiError(
            "unauthorized", message("api.token_rejected"), reason="session_required"
        )
    set_session_cookie(response, session_id)
    on_redeem(request, grant.token_kind)
    return NewSession(
        **_state(session, principal, authorizer(request)).model_dump(),
        csrf_token=session.csrf_token,
    )


@router.get("", response_model=SessionState)
async def read_session(
    session: Annotated[Session, Depends(require_session)],
    principal: Annotated[Principal, Depends(current_principal)],
    decisions: Annotated[Authorizer, Depends(authorizer)],
) -> SessionState:
    """Return who acts in the session, how, with which roles, its label and end.

    The roles, and whether the session may write the stores, are those of
    this request: a role or a setting changed since the session started
    shows at once. The CSRF token is not repeated: the request already
    carries it.
    """
    return _state(session, principal, decisions)


@router.delete("", status_code=204, response_class=Response)
async def end_session(
    request: Request, session: Annotated[Session, Depends(require_session)]
) -> Response:
    """End the session at once (log out) and remove its cookie."""
    sessions: SessionStore = request.app.state.sessions
    sessions.end(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.post("/tokens", response_model=OneTimeToken, status_code=201)
def issue_token(
    principal: Annotated[Principal, Depends(current_principal)], request: Request
) -> OneTimeToken:
    """Issue a one-time token, valid 5 minutes, for an agent's session.

    The user hands it over outside the API, e.g. to an agent, which
    exchanges it with `POST /api/v1/session` and then acts for the session's
    principal under the token's `label`. An agent's own session answers `403
    permission_denied`: agents do not open further sessions.
    """
    if principal.kind == "agent":
        raise PermissionDeniedError(message("permission.session_tokens"))
    issued = issue_one_time_token(
        request.app.state.index_path, "agent", minted_by=principal
    )
    port: int = request.app.state.port
    return OneTimeToken(
        token=issued.token,
        url=fragment_url(port, issued.token),
        label=issued.label,
        expires_at=issued.expires_at,
    )
