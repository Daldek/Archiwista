"""Session routes: one-time token exchange, session state and next tokens.

``POST /api/v1/session`` needs no session and no CSRF token, but passes the
``Host`` and ``Origin`` rules; the other routes require the session, and
``POST /api/v1/session/tokens`` also the CSRF token (SPEC 10.1).
"""

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.errors import ApiError
from archiwista.auth import Principal
from archiwista.messages import MESSAGES
from archiwista.security import (
    Session,
    SessionStore,
    current_principal,
    fragment_url,
    issue_one_time_token,
    redeem_one_time_token,
    require_csrf,
    require_session,
    set_session_cookies,
)

router = APIRouter(prefix="/session", tags=["session"])


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "actor": "local",
                    "csrf_token": "Yc1hR8kq0sV3nL5tW7xZ9A",
                    "expires_at": "2026-10-19T12:00:00Z",
                }
            ]
        }
    )

    actor: str = Field(description="Who acts; `local` in local mode.")
    csrf_token: str = Field(
        description="Send as X-Archiwista-CSRF with POST, PUT and DELETE."
    )
    expires_at: datetime = Field(
        description="End of the session unless used again (each request extends it)."
    )


class OneTimeToken(BaseModel):
    """A one-time token for a next session, e.g. an agent's."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "token": "pT0Vf1mWQ3uX9aZbC2dE4g",
                    "url": "http://127.0.0.1:8090/#token=pT0Vf1mWQ3uX9aZbC2dE4g",
                    "expires_at": "2026-10-18T12:05:00Z",
                }
            ]
        }
    )

    token: str = Field(description="Value for POST /api/v1/session (single use).")
    url: str = Field(description="Address that opens a browser session.")
    expires_at: datetime = Field(description="End of validity (5 minutes).")


def _state(session: Session) -> SessionState:
    return SessionState(
        actor=session.principal.id,
        csrf_token=session.csrf_token,
        expires_at=session.expires_at,
    )


@router.post("", response_model=SessionState)
def exchange_token(
    body: SessionExchange, request: Request, response: Response
) -> SessionState:
    """Exchange a one-time token for a session and its CSRF token.

    Sets the ``HttpOnly`` cookie ``archiwista_session`` and the cookie
    ``archiwista_csrf``. An unknown, used or expired token answers ``401
    session_required``.
    """
    index_path: Path = request.app.state.index_path
    principal = redeem_one_time_token(index_path, body.token)
    if principal is None:
        raise ApiError(401, "session_required", MESSAGES["api_token_rejected"])
    sessions: SessionStore = request.app.state.sessions
    session_id, session = sessions.create(principal)
    set_session_cookies(response, session, session_id=session_id)
    return _state(session)


@router.get("", response_model=SessionState)
async def read_session(
    session: Annotated[Session, Depends(require_session)], response: Response
) -> SessionState:
    """Return the session's actor, CSRF token and expiry.

    Also renews the ``archiwista_csrf`` cookie, e.g. after a reload.
    """
    set_session_cookies(response, session)
    return _state(session)


@router.post(
    "/tokens",
    response_model=OneTimeToken,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def issue_token(
    principal: Annotated[Principal, Depends(current_principal)], request: Request
) -> OneTimeToken:
    """Issue a one-time token, valid 5 minutes, for an agent's session.

    The user hands it over outside the API, e.g. to an agent, which
    exchanges it with ``POST /api/v1/session`` and then acts for the
    session's principal.
    """
    issued = issue_one_time_token(
        request.app.state.index_path, "agent", minted_by=principal
    )
    port: int = request.app.state.port
    return OneTimeToken(
        token=issued.token,
        url=fragment_url(port, issued.token),
        expires_at=issued.expires_at,
    )
