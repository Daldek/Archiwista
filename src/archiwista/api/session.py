"""Session routes: signing in, the token exchange, the session, its password.

``GET /api/v1/session/methods`` (public) tells how to start a session: in
local mode with one-time tokens only, in team mode also with an account's
password, and through the company's reverse proxy when the request came
from a trusted proxy naming the person. ``POST /api/v1/session/login``
(public, team mode) signs in with an account and its password (ADR-046):
every refusal of an account answers the same ``401 login_failed`` after one
password verification, a correct temporary password past its end ``401
password_expired``, and after five failures of the account or the address
the attempts wait (``archiwista.auth.throttle``: ``429 login_blocked`` with
``Retry-After``, no verification; attempts sent at once are admitted under
one lock, so they pass no more failures than one after another). ``POST
/api/v1/session/proxy`` (public, team mode) signs in as the enabled account a
trusted proxy names in ``proxy_user_header`` (with ``proxy_autocreate`` a
missing one is created without roles); each later request of that session
must come from a trusted proxy naming the same person
(``SecurityMiddleware``). ``POST
/api/v1/session`` (public) exchanges a one-time token. All three pass the
``Host`` and ``Origin`` rules, end the session whose cookie the request
carried (no fixation) and answer the new session's CSRF token, which every
other ``/api`` request carries in ``X-Archiwista-CSRF`` next to the session
cookie (SPEC 10.1). A session signed in with a temporary password may only
read itself, change the password and sign out (``SecurityMiddleware``).
``GET`` shows the session without that token, with the roles and groups its
principal has now and whether it may write the stores; ``PUT
/api/v1/session/password`` changes the person's password, ends every
session of the account and answers a new one; ``DELETE`` signs out; ``POST
/api/v1/session/tokens`` issues a one-time token for an agent, which an
agent's own session may not do. Each sign-in, failure, sign-out, password
change and token lands in the action log.
"""

import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.dependencies import authorizer
from archiwista.api.errors import ApiError, problem_responses
from archiwista.auth import LOCAL_PRINCIPAL_ID, Principal, PrincipalKind, passwords
from archiwista.auth.throttle import (
    LoginAttempt,
    LoginThrottle,
    LoginWaitError,
    throttle_keys,
)
from archiwista.errors import (
    ConflictError,
    InvalidChangeError,
    PermissionDeniedError,
    RateLimitedError,
)
from archiwista.messages import message
from archiwista.security import (
    Session,
    SessionMethod,
    SessionStore,
    TokenKind,
    Transport,
    clear_session_cookie,
    current_principal,
    fragment_url,
    issue_one_time_token,
    named_by_proxy,
    redeem_one_time_token,
    require_session,
    session_cookie_name,
    set_session_cookie,
)
from archiwista.state import StateStore, UserRecord

router = APIRouter(prefix="/session", tags=["session"])

# The longest account name a sign-in takes: the longest account id.
ACCOUNT_MAX_LENGTH = 64

_STATE_EXAMPLE: dict[str, Any] = {
    "actor": "anna.nowak",
    "name": "Anna Nowak",
    "kind": "user",
    "roles": ["store_writer"],
    "groups": ["hydro"],
    "store_write": True,
    "label": "3f9c1a7e",
    "method": "password",
    "password_change_required": False,
    "team": True,
    "expires_at": "2026-10-19T20:00:00Z",
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


class SignIn(BaseModel):
    """An account and its password (team mode)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"account": "anna.nowak", "password": "kajak-po-Rabie"}]
        },
    )

    account: str = Field(
        min_length=1,
        max_length=ACCOUNT_MAX_LENGTH,
        description="Account id; spaces around it and the case do not matter.",
    )
    password: str = Field(
        min_length=1,
        max_length=passwords.MAX_LENGTH,
        description="The password as typed (compared after Unicode NFKC).",
    )


class PasswordChange(BaseModel):
    """A person's current password and the new one."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)
    new_password: str = Field(
        min_length=1,
        max_length=passwords.MAX_LENGTH,
        description=(
            f"{passwords.MIN_LENGTH} to {passwords.MAX_LENGTH} characters of any"
            " kind, not the account's id or name, not a common password."
        ),
    )


class SessionMethods(BaseModel):
    """How a session starts on this server."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"mode": "team", "password": True, "proxy": False}]
        }
    )

    mode: Literal["local", "team"] = Field(
        description=(
            "`local`: one person on this computer, sessions from one-time tokens;"
            " `team`: people sign in with accounts."
        )
    )
    password: bool = Field(
        description="Signing in with an account's password (POST /session/login)."
    )
    proxy: bool = Field(
        description=(
            "Signing in through the company's reverse proxy (POST /session/proxy):"
            " this request came from a trusted proxy that names a person."
        )
    )


class SessionState(BaseModel):
    """The current session."""

    model_config = ConfigDict(json_schema_extra={"examples": [_STATE_EXAMPLE]})

    actor: str = Field(
        description="Who acts: the principal's id (`local` for the computer's owner)."
    )
    name: str = Field(
        description="The account's display name; the id for the computer's owner."
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
    groups: list[str] = Field(description="Groups `actor` belongs to now.")
    store_write: bool = Field(
        description=(
            "Whether `actor` may write the stores now (a `download` job): the role"
            " `store_writer` or the setting `store_write_for_all`, read again for"
            " each request like `roles`. Without it `POST /jobs` refuses a"
            " download with `403 permission_denied`."
        )
    )
    label: str = Field(
        description="Label of the session, recorded with its jobs and the action log."
    )
    method: SessionMethod = Field(
        description=(
            "How it started: `startup` (the address of `archiwista serve`),"
            " `token` (a one-time token for an agent), `password`, `proxy`."
        )
    )
    password_change_required: bool = Field(
        description=(
            "Signed in with a temporary password: until PUT /session/password it"
            " may only read itself and sign out (`403 password_change_required`)."
        )
    )
    team: bool = Field(description="The server runs in team mode.")
    expires_at: datetime = Field(
        description=(
            "End of the session unless used again: each request extends it by"
            " 24 h, in team mode by 8 h and never past 7 days after its start;"
            " an agent's session ends 12 h after its start at the latest."
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
    url: str = Field(
        description="Address that opens a browser session (at the team's origin)."
    )
    label: str = Field(
        description="Label of the session it opens, recorded with its jobs."
    )
    expires_at: datetime = Field(description="End of validity (5 minutes).")


def _client(request: Request) -> str | None:
    client: str | None = getattr(request.state, "client", None)
    return client


def _state_store(request: Request) -> StateStore:
    return authorizer(request).state


def _state(session: Session, principal: Principal, request: Request) -> SessionState:
    decisions = authorizer(request)
    transport: Transport = request.app.state.transport
    user = None
    if session.principal_id != LOCAL_PRINCIPAL_ID:
        user = decisions.state.user(session.principal_id)
    return SessionState(
        actor=session.principal_id,
        name=session.principal_id if user is None else user.name,
        kind=session.kind,
        roles=sorted(principal.roles),
        groups=sorted(principal.groups),
        store_write=decisions.can(principal, "store.write"),
        label=session.label,
        method=session.method,
        password_change_required=session.password_change_required,
        team=transport.team,
        expires_at=session.expires_at,
    )


@dataclass(frozen=True, slots=True)
class _Started:
    """A session ``_new_session`` started: the answer and who acts in it."""

    answer: NewSession
    principal: Principal


def _new_session(
    request: Request,
    response: Response,
    principal_id: str,
    kind: PrincipalKind,
    *,
    method: SessionMethod,
    label: str | None = None,
    issued_at: datetime | None = None,
    generation: int = 0,
    password_change_required: bool = False,
    proxy_user: str | None = None,
) -> _Started | None:
    """Start a session, end the one of the request's cookie, set the cookie.

    Returns
    -------
    _Started or None
        ``None`` when the account cannot act (disabled, or its sessions
        revoked after the credential was issued): no session started.
    """
    sessions: SessionStore = request.app.state.sessions
    transport: Transport = request.app.state.transport
    session_id, session = sessions.create(
        principal_id,
        kind,
        method=method,
        label=label,
        issued_at=issued_at,
        generation=generation,
        client=_client(request),
        user_agent=request.headers.get("user-agent"),
        password_change_required=password_change_required,
        proxy_user=proxy_user,
        replaces=request.cookies.get(session_cookie_name(transport)),
    )
    principal: Principal | None = request.app.state.principals(session)
    if principal is None:
        sessions.end(session_id)
        return None
    set_session_cookie(response, session_id, transport)
    answer = NewSession(
        **_state(session, principal, request).model_dump(),
        csrf_token=session.csrf_token,
    )
    return _Started(answer, replace(principal, client=_client(request)))


def _admitted(throttle: LoginThrottle, keys: tuple[str, str]) -> LoginAttempt:
    """Admit an attempt, or refuse it while its account or address waits.

    A refused attempt verifies no password and counts nothing.
    """
    try:
        return throttle.admit(keys)
    except LoginWaitError as wait:
        raise RateLimitedError(
            message("auth.login_blocked"),
            retry_after_s=wait.seconds,
            reason="login_blocked",
        ) from None


def _failure(reason: str, until: datetime | None) -> dict[str, object]:
    """Return the details of a failed sign-in or password change."""
    details: dict[str, object] = {"reason": reason, "method": "password"}
    if until is not None:
        details["blocked_until"] = until.isoformat(timespec="seconds")
    return details


def _typed(account: str) -> str:
    """Return an account name as typed, its control characters replaced."""
    return "".join(
        "\N{REPLACEMENT CHARACTER}" if unicodedata.category(char) == "Cc" else char
        for char in account
    )


def on_redeem(request: Request, kind: TokenKind) -> None:
    """Tell the server that a one-time token of ``kind`` started a session.

    ``archiwista serve`` deletes the browser's redirect file once its startup
    token is used (``app.state.on_redeem``; nothing without it).
    """
    hook = getattr(request.app.state, "on_redeem", None)
    if hook is not None:
        hook(kind)


def _proxy_refused() -> ApiError:
    """Return the one refusal of a sign-in through the proxy."""
    return ApiError(
        "unauthorized", message("auth.proxy_login_failed"), reason="login_failed"
    )


def _proxy_account(
    state: StateStore, named: str, transport: Transport, client: str | None
) -> UserRecord | None:
    """Return the account the proxy names; with ``proxy_autocreate`` a new one.

    The new account has no roles and its ``user.add`` entry has no actor
    (``-``). A name that is no valid account id creates nothing.
    """
    user = state.user(named)
    if user is not None or not transport.proxy_autocreate:
        return user
    try:
        return state.add_user(named, actor=None, client=client)
    except InvalidChangeError:  # no valid account id, or ``local``
        return None
    except ConflictError:  # created meanwhile by another sign-in
        return state.user(named)


@router.get("/methods", response_model=SessionMethods)
async def session_methods(request: Request) -> SessionMethods:
    """Tell how a session starts here: local mode, or team mode and its ways.

    Needs no session: the interface asks before it shows the sign-in.
    `proxy` is true when this request came from a trusted proxy carrying
    `proxy_user_header`.
    """
    transport: Transport = request.app.state.transport
    return SessionMethods(
        mode="team" if transport.team else "local",
        password=transport.team,
        proxy=named_by_proxy(request.scope, transport) is not None,
    )


@router.post("/proxy", response_model=NewSession, responses=problem_responses(409))
def proxy_sign_in(request: Request, response: Response) -> NewSession:
    """Sign in as the person the company's reverse proxy names (team mode).

    Only a request from a trusted proxy (`trusted_proxies`) carrying
    `proxy_user_header` signs in, as the enabled account the header names
    (trimmed and lower-cased); with `proxy_autocreate` a missing account is
    created without roles. Anything else answers `401 login_failed`: no
    header, another peer, an unknown or a disabled account. Sets the cookie
    and answers the session with its `csrf_token` as POST /session/login;
    every later `/api` request of the session must come from a trusted proxy
    naming the same person, else the session ends (`401 session_required`).
    The proxy has authenticated the person: no password and no wait after
    failures. Local mode: `409 local_mode`.
    """
    transport: Transport = request.app.state.transport
    if not transport.team:
        raise ApiError("conflict", message("auth.local_mode"), reason="local_mode")
    named = named_by_proxy(request.scope, transport)
    if named is None:
        raise _proxy_refused()
    state = _state_store(request)
    client = _client(request)
    user = _proxy_account(state, named, transport, client)
    if user is None or user.disabled:
        state.record(
            None,
            "session.login_failed",
            _typed(named[:ACCOUNT_MAX_LENGTH]),
            outcome="failed",
            details={
                "reason": "unknown_proxy_user" if user is None else "disabled",
                "method": "proxy",
            },
            client=client,
        )
        raise _proxy_refused()
    started = _new_session(
        request, response, user.id, "user", method="proxy", proxy_user=named
    )
    if started is None:  # disabled between the check and the session
        raise _proxy_refused()
    state.record(
        started.principal, "session.login", user.id, details={"method": "proxy"}
    )
    return started.answer


@router.post("/login", response_model=NewSession, responses=problem_responses(409, 429))
def sign_in(body: SignIn, request: Request, response: Response) -> NewSession:
    """Sign in with an account and its password (team mode).

    Sets the cookie `__Host-archiwista_session` (`Secure`, `HttpOnly`,
    `SameSite=Strict`, `Path=/`) and answers the session with its
    `csrf_token`; a session cookie the request carried ends. An unknown
    account, a wrong password, a disabled account and one without a password
    answer the same `401 login_failed`; a correct temporary password past
    its end `401 password_expired`. After five failures of the account (from
    any address) or of the address (for any account) each attempt waits,
    1 s doubling up to 15 min: `429 rate_limited`, reason `login_blocked`,
    with `Retry-After`. A temporary password signs in with
    `password_change_required`: change it with PUT /session/password first.
    Local mode has no sign-in: `409 local_mode`.
    """
    transport: Transport = request.app.state.transport
    if not transport.team:
        raise ApiError("conflict", message("auth.local_mode"), reason="local_mode")
    state = _state_store(request)
    throttle: LoginThrottle = request.app.state.login_throttle
    client = _client(request)
    account = body.account.strip().lower()
    keys = throttle_keys(account, client)
    with _admitted(throttle, keys) as attempt:
        checked = passwords.check_sign_in(state, account, body.password)
        if checked.user is None:
            reason = checked.failure or "login_failed"
            until = attempt.failed()
            state.record(
                None,
                "session.login_failed",
                _typed(body.account),
                outcome="failed",
                details=_failure(reason, until),
                client=client,
            )
            if reason == "password_expired":
                raise ApiError(
                    "unauthorized",
                    message("auth.password_expired"),
                    reason="password_expired",
                )
            raise ApiError(
                "unauthorized", message("auth.login_failed"), reason="login_failed"
            )
        attempt.succeeded()
    started = _new_session(
        request,
        response,
        checked.user.id,
        "user",
        method="password",
        password_change_required=checked.temporary,
    )
    if started is None:  # disabled between the check and the session
        raise ApiError(
            "unauthorized", message("auth.login_failed"), reason="login_failed"
        )
    state.record(
        started.principal,
        "session.login",
        checked.user.id,
        details={"method": "password"},
    )
    return started.answer


@router.post("", response_model=NewSession)
def exchange_token(
    body: SessionExchange, request: Request, response: Response
) -> NewSession:
    """Exchange a one-time token for a session and its CSRF token.

    Sets the `HttpOnly` cookie `archiwista_session` (in team mode
    `__Host-archiwista_session` with `Secure`); every later request also
    sends `csrf_token` as `X-Archiwista-CSRF`, since the cookie alone never
    acts. An unknown, used, expired or revoked token, or one of an account
    disabled since, answers `401 session_required`. A session cookie the
    request carried ends: no session id lives on across a new session.
    """
    index_path: Path = request.app.state.index_path
    grant = redeem_one_time_token(index_path, body.token)
    if grant is None:
        raise ApiError(
            "unauthorized", message("api.token_rejected"), reason="session_required"
        )
    method: SessionMethod = "startup" if grant.token_kind == "startup" else "token"
    started = _new_session(
        request,
        response,
        grant.principal_id,
        grant.kind,
        method=method,
        label=grant.label,
        issued_at=grant.issued_at,
        generation=grant.generation,
    )
    if started is None:
        raise ApiError(
            "unauthorized", message("api.token_rejected"), reason="session_required"
        )
    _state_store(request).record(
        started.principal,
        "session.login",
        grant.principal_id,
        details={"method": method},
    )
    on_redeem(request, grant.token_kind)
    return started.answer


@router.get("", response_model=SessionState)
def read_session(
    request: Request,
    session: Annotated[Session, Depends(require_session)],
    principal: Annotated[Principal, Depends(current_principal)],
) -> SessionState:
    """Return who acts in the session, how, with which roles, its label and end.

    The roles, groups and whether the session may write the stores are those
    of this request: a role or a setting changed since the session started
    shows at once. The CSRF token is not repeated: the request already
    carries it.
    """
    return _state(session, principal, request)


@router.put(
    "/password",
    response_model=NewSession,
    responses=problem_responses(400, 403, 409, 429),
)
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(require_session)],
    principal: Annotated[Principal, Depends(current_principal)],
) -> NewSession:
    """Change the password of the session's account (team mode).

    The new password must have 12 to 1,024 characters and be neither the
    account's id or name nor a common password (`400 validation_error`,
    reason `password_policy`, `details.rule`); a wrong current password is
    `403 forbidden`, reason `wrong_password`, and counts as a failed sign-in
    (`429 login_blocked` after five). Every session of the account and its
    agents' ends; the answer is a new session with a new cookie and CSRF
    token. An agent's session may not change it (`403 permission_denied`),
    nor a session of the reverse proxy (`409 proxy_session`); local mode has
    no passwords (`409 local_mode`).
    """
    transport: Transport = request.app.state.transport
    if not transport.team:
        raise ApiError("conflict", message("auth.local_mode"), reason="local_mode")
    if principal.kind == "agent":
        raise PermissionDeniedError(message("permission.session_password"))
    if session.method == "proxy":
        raise ApiError(
            "conflict", message("auth.proxy_session"), reason="proxy_session"
        )
    state = _state_store(request)
    throttle: LoginThrottle = request.app.state.login_throttle
    keys = throttle_keys(principal.id, principal.client)
    with _admitted(throttle, keys) as attempt:
        changed = passwords.change_password(
            state,
            principal.id,
            body.current_password,
            body.new_password,
            actor=principal,
        )
        if changed is None:
            until = attempt.failed()
            state.record(
                principal,
                "session.password",
                principal.id,
                outcome="failed",
                details=_failure("wrong_password", until),
            )
            raise ApiError(
                "forbidden", message("auth.wrong_password"), reason="wrong_password"
            )
        attempt.succeeded()
    started = _new_session(
        request, response, principal.id, principal.kind, method=session.method
    )
    if started is None:  # disabled since this request began
        raise ApiError(
            "unauthorized", message("api.session_ended"), reason="session_required"
        )
    return started.answer


@router.delete("", status_code=204, response_class=Response)
def end_session(
    request: Request,
    session: Annotated[Session, Depends(require_session)],
    principal: Annotated[Principal, Depends(current_principal)],
) -> Response:
    """End the session at once (sign out) and remove its cookie."""
    sessions: SessionStore = request.app.state.sessions
    transport: Transport = request.app.state.transport
    sessions.end(request.cookies.get(session_cookie_name(transport)))
    _state_store(request).record(principal, "session.logout", session.principal_id)
    response = Response(status_code=204)
    clear_session_cookie(response, transport)
    return response


@router.post("/tokens", response_model=OneTimeToken, status_code=201)
def issue_token(
    principal: Annotated[Principal, Depends(current_principal)], request: Request
) -> OneTimeToken:
    """Issue a one-time token, valid 5 minutes, for an agent's session.

    The user hands it over outside the API, e.g. to an agent, which
    exchanges it with `POST /api/v1/session` and then acts for the session's
    principal, with its roles, under the token's `label`; `url` is an
    address of the team's origin in team mode. An agent's own session
    answers `403 permission_denied`: agents do not open further sessions.
    """
    if principal.kind == "agent":
        raise PermissionDeniedError(message("permission.session_tokens"))
    issued = issue_one_time_token(
        request.app.state.index_path, "agent", minted_by=principal
    )
    _state_store(request).record(
        principal, "token.issue", principal.id, details={"label": issued.label}
    )
    transport: Transport = request.app.state.transport
    return OneTimeToken(
        token=issued.token,
        url=fragment_url(transport.origin, issued.token),
        label=issued.label,
        expires_at=issued.expires_at,
    )
