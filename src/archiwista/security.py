"""Local-mode access protection (SPEC 10.1, A-ADR-012 errata 1 and 2).

The server listens on ``127.0.0.1`` only and answers requests whose ``Host``
is ``127.0.0.1:<port>`` or ``localhost:<port>`` (DNS rebinding). A one-time
token, of which the local index keeps only the SHA-256 hash together with
who minted it (id and kind), is exchanged for a session: an ``HttpOnly``
session cookie and a separate secret, the session's CSRF token, which the
client keeps (the interface in ``sessionStorage``, bound to the server's
origin) and sends as ``X-Archiwista-CSRF`` with every ``/api`` request,
reads included. Browsers send cookies to every port of a host, so the cookie
never acts alone. ``/api/*`` requires both, except the exchange itself and
the static files of ``/api/docs``; the session acts as a ``Principal`` whose
roles and groups are read for every request (``current_principal`` for
routers). An agent's session ends 12 hours after its start at the latest,
and at once when the owner revokes agent sessions
(``revoke_agent_sessions``). A present ``Origin`` must be the server itself;
a browser (``Sec-Fetch-Site``) may change state only from the same origin and
read only from the same origin or by a direct navigation (``none``). Request
bodies are capped before a route reads them: 4 KiB for the token exchange,
1 MiB otherwise (area files keep their own 50 MB limit). Every response
carries a CSP computed from the current settings,
``Referrer-Policy: no-referrer`` and ``X-Content-Type-Options: nosniff``;
there is no CORS. Files are opened only through ``archiwista.paths``.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie, APIKeyHeader
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from archiwista.api import API_PREFIX, DOCS_PATH
from archiwista.api.errors import ApiError, problem_response
from archiwista.auth import Principal, PrincipalKind
from archiwista.auth.authorize import session_principal
from archiwista.config import AppSettings
from archiwista.error_document import Problem
from archiwista.index.schema import connect
from archiwista.messages import message
from archiwista.state import StateStore

type TokenKind = Literal["startup", "agent"]

LOOPBACK_HOST = "127.0.0.1"
SESSION_COOKIE = "archiwista_session"
CSRF_HEADER = "X-Archiwista-CSRF"
SESSION_PATH = f"{API_PREFIX}/session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Each request of a session moves its end by the idle timeout.
SESSION_IDLE_TIMEOUT = timedelta(hours=24)
# An agent's session ends this long after its start, used or not.
AGENT_SESSION_MAX_AGE = timedelta(hours=12)
TOKEN_TTL: Mapping[TokenKind, timedelta] = MappingProxyType(
    {"startup": timedelta(minutes=10), "agent": timedelta(minutes=5)}
)
# Request bodies read before a route: the token exchange, everything else.
SESSION_BODY_LIMIT_BYTES = 4 * 1024
BODY_LIMIT_BYTES = 1024**2
REDACTED = "***"

_TOKEN_BYTES = 16  # 128-bit one-time and CSRF tokens
_SESSION_ID_BYTES = 32
_LABEL_BYTES = 4
# ``index_info`` key that ``revoke_agent_sessions`` increments: an agent
# session started under another value has ended.
_AGENT_GENERATION = "agent_session_generation"
# ``POST /api/v1/areas`` reads its body itself, up to its own limit.
_AREAS_PATH = f"{API_PREFIX}/areas"
_TOKEN_VALUE = re.compile(r"(?i)(token=)[^&;#\s\"']*")
# Scheme, host and port only: anything else would break the policy syntax.
_CSP_SOURCE = re.compile(r"https?://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(:[0-9]{1,5})?")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def _same(value: str, expected: str) -> bool:
    return hmac.compare_digest(
        value.encode("utf-8", "surrogatepass"), expected.encode("utf-8")
    )


def _whole_seconds(moment: datetime | None) -> datetime:
    return (moment or _utc_now()).astimezone(UTC).replace(microsecond=0)


@contextmanager
def _immediate(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


# One-time tokens -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A one-time session token, shown once; the index keeps only its hash.

    Parameters
    ----------
    token : str
        128-bit URL-safe value.
    kind : {"startup", "agent"}
        Who asked for it: ``archiwista serve`` or a next session.
    label : str
        Label of the session the token opens (8 hexadecimal digits),
        recorded with that session's jobs and permission changes.
    expires_at : datetime
        End of validity (UTC, whole seconds).
    """

    token: str
    kind: TokenKind
    label: str
    expires_at: datetime


def issue_one_time_token(
    index_path: Path,
    kind: TokenKind,
    *,
    minted_by: Principal,
    now: datetime | None = None,
) -> IssuedToken:
    """Create a one-time session token and store its SHA-256 hash.

    Parameters
    ----------
    index_path : Path
        Local index; ``initialize`` must have created it.
    kind : {"startup", "agent"}
        ``startup`` for ``archiwista serve`` (valid 10 min): the session
        belongs to ``minted_by`` itself. ``agent`` for ``archiwista token``
        and ``POST /api/v1/session/tokens`` (valid 5 min): the session is an
        agent acting for ``minted_by``.
    minted_by : Principal
        Who asked for the token. The index keeps only its id and kind: the
        session's roles and groups are read for each of its requests.
    now : datetime or None, optional
        Time of issue; the current time when omitted.

    Returns
    -------
    IssuedToken
        The value to hand over, the label of its session and its expiry.
        Expired tokens are removed from the index on the way.
    """
    issued_at = _whole_seconds(now)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    label = secrets.token_hex(_LABEL_BYTES)
    expires_at = issued_at + TOKEN_TTL[kind]
    principal = json.dumps({"id": minted_by.id, "kind": minted_by.kind})
    connection = connect(index_path)
    try:
        with _immediate(connection):
            connection.execute(
                "DELETE FROM session_tokens WHERE expires_at <= ?",
                (issued_at.isoformat(),),
            )
            connection.execute(
                "INSERT INTO session_tokens"
                " (hash, kind, principal, label, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _digest(token),
                    kind,
                    principal,
                    label,
                    issued_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )
    finally:
        connection.close()
    return IssuedToken(token=token, kind=kind, label=label, expires_at=expires_at)


@dataclass(frozen=True, slots=True)
class SessionGrant:
    """What a used one-time token grants: who the new session acts as.

    Parameters
    ----------
    principal_id : str
        Who minted the token (``local`` for the owner of the computer).
    kind : {"local_owner", "user", "agent"}
        How the session acts: as the minter (startup token) or as an agent
        for it (agent token).
    label : str
        Label of the session.
    token_kind : {"startup", "agent"}
        Kind of the token used.
    generation : int
        The index's agent-session generation when the token was used.
    """

    principal_id: str
    kind: PrincipalKind
    label: str
    token_kind: TokenKind
    generation: int


def redeem_one_time_token(
    index_path: Path, token: str, *, now: datetime | None = None
) -> SessionGrant | None:
    """Use a one-time token: once, and only before it expires.

    Parameters
    ----------
    index_path : Path
        Local index holding the token's hash.
    token : str
        Value received from the client.
    now : datetime or None, optional
        Time of use; the current time when omitted.

    Returns
    -------
    SessionGrant or None
        Who the new session acts as: the minting principal for a startup
        token, an ``agent`` for it for an agent token. ``None`` for an
        unknown, already used, expired or revoked token; concurrent uses of
        one token succeed at most once.
    """
    used_at = _whole_seconds(now).isoformat()
    connection = connect(index_path)
    try:
        # One transaction with the generation: a revocation comes either
        # before (the token is gone) or after (the session ends).
        with _immediate(connection):
            rows = connection.execute(
                "UPDATE session_tokens SET used_at = ?"
                " WHERE hash = ? AND used_at IS NULL AND expires_at > ?"
                " RETURNING kind, principal, label",
                (used_at, _digest(token), used_at),
            ).fetchall()
            generation = _agent_generation(connection)
    finally:
        connection.close()
    if not rows:
        return None
    token_kind, carried, label = rows[0]
    minter = json.loads(carried)
    return SessionGrant(
        principal_id=minter["id"],
        kind=minter["kind"] if token_kind == "startup" else "agent",
        label=label,
        token_kind=token_kind,
        generation=generation,
    )


def revoke_agent_sessions(index_path: Path) -> int:
    """End every agent session and refuse the agent tokens not used yet.

    The index's agent-session generation goes up by one; a running server
    compares it with each agent session's at every request, so this works
    from another process (``archiwista token --revoke-all``).

    Parameters
    ----------
    index_path : Path
        Local index; ``initialize`` must have created it.

    Returns
    -------
    int
        Agent tokens refused before anyone used them.
    """
    connection = connect(index_path)
    try:
        with _immediate(connection):
            refused = connection.execute(
                "DELETE FROM session_tokens WHERE kind = 'agent' AND used_at IS NULL"
            ).rowcount
            connection.execute(
                "INSERT INTO index_info (key, value) VALUES (?, '1')"
                " ON CONFLICT (key) DO UPDATE SET value = CAST(value AS INTEGER) + 1",
                (_AGENT_GENERATION,),
            )
    finally:
        connection.close()
    return refused


def agent_session_generation(index_path: Path) -> int:
    """Return the index's agent-session generation (``revoke_agent_sessions``)."""
    connection = connect(index_path, readonly=True)
    try:
        return _agent_generation(connection)
    finally:
        connection.close()


def _agent_generation(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM index_info WHERE key = ?", (_AGENT_GENERATION,)
    ).fetchone()
    return 0 if row is None else int(row[0])


def fragment_url(port: int, token: str) -> str:
    """Return the one-time address ``http://127.0.0.1:<port>/#token=<token>``.

    The token travels in the fragment, which browsers send neither to the
    server (nor its access log) nor in ``Referer``.
    """
    return f"http://{LOOPBACK_HOST}:{port}/#token={token}"


# Sessions ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Session:
    """A browser or agent session.

    Parameters
    ----------
    principal_id : str
        Who the session belongs to (``local`` for the owner).
    kind : {"local_owner", "user", "agent"}
        How it acts; the roles and groups are read for each request
        (``archiwista.auth.authorize.session_principal``).
    label : str
        Label recorded with the session's jobs and permission changes.
    csrf_token : str
        128-bit secret that every ``/api`` request of the session carries in
        ``X-Archiwista-CSRF``.
    created_at : datetime
        Start of the session (UTC).
    expires_at : datetime
        End of the session unless used again; every request moves it
        ``SESSION_IDLE_TIMEOUT`` ahead, an agent's session never past
        ``AGENT_SESSION_MAX_AGE`` after its start.
    generation : int, optional
        The index's agent-session generation at the start; an agent session
        ends when it changes.
    """

    principal_id: str
    kind: PrincipalKind
    label: str
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    generation: int = 0


class SessionStore:
    """Sessions of the running server, kept in memory only.

    A server restart ends every session: ``archiwista serve`` prints a new
    one-time address. Only SHA-256 hashes of session ids are held.
    Thread-safe.

    Parameters
    ----------
    idle_timeout : timedelta, optional
        How long a session lives without requests.
    agent_max_age : timedelta, optional
        How long an agent's session lives at most, used or not.
    clock : Callable[[], datetime], optional
        Source of the current time (aware).
    """

    def __init__(
        self,
        *,
        idle_timeout: timedelta = SESSION_IDLE_TIMEOUT,
        agent_max_age: timedelta = AGENT_SESSION_MAX_AGE,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._idle_timeout = idle_timeout
        self._agent_max_age = agent_max_age
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, grant: SessionGrant) -> tuple[str, Session]:
        """Start a session acting as a used token grants.

        Returns
        -------
        tuple[str, Session]
            The secret session id for the ``HttpOnly`` cookie and the session.
        """
        now = _whole_seconds(self._clock())
        session_id = secrets.token_urlsafe(_SESSION_ID_BYTES)
        session = Session(
            principal_id=grant.principal_id,
            kind=grant.kind,
            label=grant.label,
            csrf_token=secrets.token_urlsafe(_TOKEN_BYTES),
            created_at=now,
            expires_at=self._end(grant.kind, now, now),
            generation=grant.generation,
        )
        with self._lock:
            expired = [
                key for key, item in self._sessions.items() if item.expires_at <= now
            ]
            for key in expired:
                del self._sessions[key]
            self._sessions[_digest(session_id)] = session
        return session_id, session

    def get(self, session_id: str | None) -> Session | None:
        """Return the live session of a cookie value, without extending it.

        Returns
        -------
        Session or None
            ``None`` for a missing, unknown or expired session.
        """
        if not session_id:
            return None
        key = _digest(session_id)
        now = _whole_seconds(self._clock())
        with self._lock:
            session = self._sessions.get(key)
            if session is not None and session.expires_at <= now:
                del self._sessions[key]
                return None
        return session

    def extend(self, session_id: str) -> Session | None:
        """Move a live session's end ahead after a request it fully authorized.

        Returns
        -------
        Session or None
            The extended session; ``None`` when it ended meanwhile.
        """
        key = _digest(session_id)
        now = _whole_seconds(self._clock())
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            expires_at = self._end(session.kind, session.created_at, now)
            if expires_at <= now:
                del self._sessions[key]
                return None
            session = replace(session, expires_at=expires_at)
            self._sessions[key] = session
        return session

    def end(self, session_id: str | None) -> bool:
        """End a session at once (logout, a disabled account, a revocation).

        Returns
        -------
        bool
            Whether the session was live.
        """
        if not session_id:
            return False
        with self._lock:
            return self._sessions.pop(_digest(session_id), None) is not None

    def _end(
        self, kind: PrincipalKind, created_at: datetime, now: datetime
    ) -> datetime:
        idle_end = now + self._idle_timeout
        if kind == "agent":
            return min(idle_end, created_at + self._agent_max_age)
        return idle_end


def session_principals(
    state: StateStore, index_path: Path
) -> Callable[[Session], Principal | None]:
    """Return who sessions act as now, for ``SecurityMiddleware``.

    An agent session has ended once the index's agent-session generation is
    not the one it started under (``revoke_agent_sessions``). Otherwise the
    roles and groups come from the state database at each request
    (``session_principal``): a disabled or removed account ends its sessions.

    Parameters
    ----------
    state : StateStore
        Accounts, their roles and groups.
    index_path : Path
        Local index with the agent-session generation.
    """

    def principal(session: Session) -> Principal | None:
        if (
            session.kind == "agent"
            and agent_session_generation(index_path) != session.generation
        ):
            return None
        return session_principal(
            state, session.principal_id, session.kind, session=session.label
        )

    return principal


def set_session_cookie(response: Response, session_id: str) -> None:
    """Set the ``HttpOnly`` session cookie (``SameSite=Strict``, ``Path=/``).

    It ends with the browser session. Browsers send it to every port of the
    host, so it never acts alone: requests also carry the CSRF token.
    """
    response.set_cookie(
        SESSION_COOKIE, session_id, httponly=True, samesite="strict", path="/"
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from the browser (logout)."""
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="strict", path="/")


# Request rules -------------------------------------------------------------


def allowed_hosts(port: int) -> frozenset[str]:
    """Return the ``Host`` values the server answers (DNS rebinding guard)."""
    return frozenset({f"{LOOPBACK_HOST}:{port}", f"localhost:{port}"})


def origin_rejection(method: str, headers: Headers, host: str) -> str | None:
    """Return why the ``Origin`` and ``Sec-Fetch-Site`` rule refuses a request.

    Parameters
    ----------
    method : str
        HTTP method; anything but GET, HEAD and OPTIONS changes state.
    headers : Headers
        Request headers.
    host : str
        The request's ``Host``, already one of ``allowed_hosts``.

    Returns
    -------
    str or None
        Polish reason, or ``None`` when the rule lets the request through.
        A client without ``Origin`` and ``Sec-Fetch-Site`` (curl, an agent's
        script) passes here; the session and its CSRF token still apply.
    """
    origin = headers.get("origin")
    if origin is not None and origin.lower() != f"http://{host}":
        return message("api.cross_site")
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is None:
        return None
    fetch_site = fetch_site.lower()
    if method in SAFE_METHODS:
        if fetch_site in ("same-origin", "none"):
            return None
        return message("api.cross_site")
    if fetch_site != "same-origin":
        return message("api.cross_site")
    if origin is None:
        return message("api.origin_missing")
    return None


def csrf_rejection(headers: Headers, session: Session) -> str | None:
    """Return why a request lacks its session's CSRF token.

    Every ``/api`` request of a session, reads included, carries
    ``X-Archiwista-CSRF`` equal to the session's token. Only a client given
    the token knows it (the interface keeps it in its origin's
    ``sessionStorage``), while browsers send the session cookie to every
    port of the host.

    Returns
    -------
    str or None
        Polish reason, or ``None`` when the request carries the token.
    """
    header = headers.get(CSRF_HEADER)
    if not header:
        return message("api.csrf_missing")
    if _same(header, session.csrf_token):
        return None
    return message("api.csrf_mismatch")


def body_limit(method: str, path: str) -> int | None:
    """Return how many bytes a request body may have before a route reads it.

    4 KiB for ``/api/v1/session`` (the token exchange needs no session),
    1 MiB otherwise; ``None`` for ``POST /api/v1/areas``, which reads an
    area file itself up to its own limit.
    """
    if path == SESSION_PATH:
        return SESSION_BODY_LIMIT_BYTES
    if method == "POST" and path == _AREAS_PATH:
        return None
    return BODY_LIMIT_BYTES


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _is_session_path(path: str) -> bool:
    return path == SESSION_PATH or path.startswith(f"{SESSION_PATH}/")


def _is_public(method: str, path: str) -> bool:
    """Return whether a request needs no session: the exchange, ``/api/docs``."""
    if method == "POST" and path == SESSION_PATH:
        return True
    return method in ("GET", "HEAD") and (
        path == DOCS_PATH or path.startswith(f"{DOCS_PATH}/")
    )


def _size(limit: int) -> str:
    return f"{limit // 1024**2} MiB" if limit >= 1024**2 else f"{limit // 1024} KiB"


async def _read_body(headers: Headers, receive: Receive, limit: int) -> Message | None:
    """Read a request body of at most ``limit`` bytes; ``None`` beyond it.

    A declared ``Content-Length`` over the limit is refused before reading;
    a chunked body is counted as it arrives, so nothing over the limit is
    kept in memory.
    """
    declared = headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return message  # The client left: the route learns it at once.
        chunk: bytes = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            return {"type": "http.request", "body": b"".join(chunks)}


def _replay(first: Message, receive: Receive) -> Receive:
    """Return ``receive`` answering the already read ``first`` message first."""
    pending = [first]

    async def replayed() -> Message:
        if pending:
            return pending.pop()
        return await receive()

    return replayed


@dataclass(frozen=True, slots=True)
class _Rejection:
    code: str
    reason: str
    detail: str
    hint: str | None = None

    def problem(self) -> Problem:
        return Problem(
            self.code, self.detail, self.hint, details={"reason": self.reason}
        )


@dataclass(frozen=True, slots=True)
class _Authorized:
    session: Session
    principal: Principal


class SecurityMiddleware:
    """Apply the local-mode rules to every HTTP request and response.

    Order: ``Host`` (``403 forbidden``, reason ``invalid_host``), ``Origin`` and
    ``Sec-Fetch-Site`` (``403 forbidden``, reason ``csrf_rejected``); then for
    ``/api/*``, except ``POST /api/v1/session`` and the files of ``/api/docs``,
    the session cookie (``401 unauthorized``, reason ``session_required``), the
    session's CSRF token in every request (``403 csrf_rejected``) and who the
    session acts as now (``401 session_required`` once its account is disabled
    or removed, or its agent session revoked); last the size of the body
    (``400 validation_error``, reason ``request_too_large``).
    Only a request passing all of them extends its session. The session and
    its principal are left in ``request.state`` for ``require_session`` and
    ``current_principal``. Every response, including these problems, gets
    the CSP of the current settings, ``Referrer-Policy: no-referrer`` and
    ``X-Content-Type-Options: nosniff``; ``/api/v1/session*`` also
    ``Cache-Control: no-store``.

    Parameters
    ----------
    app : ASGIApp
        The wrapped application.
    port : int
        Port the server listens on.
    sessions : SessionStore
        Live sessions.
    settings : Callable[[], AppSettings]
        Current settings (for the CSP of each response).
    principals : Callable[[Session], Principal or None]
        Who a session acts as now (``session_principals``); ``None`` ends
        the session.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        port: int,
        sessions: SessionStore,
        settings: Callable[[], AppSettings],
        principals: Callable[[Session], Principal | None],
    ) -> None:
        self.app = app
        self._port = port
        self._hosts = allowed_hosts(port)
        self._sessions = sessions
        self._settings = settings
        self._principals = principals

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check an HTTP request; other scopes (lifespan) pass unchanged."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        method: str = scope["method"]
        security_headers = [
            ("content-security-policy", csp_header(self._settings())),
            ("referrer-policy", "no-referrer"),
            ("x-content-type-options", "nosniff"),
        ]
        if _is_session_path(path):
            security_headers.append(("cache-control", "no-store"))

        async def send_secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in security_headers:
                    headers[name] = value
            await send(message)

        connection = HTTPConnection(scope)
        outcome = self._check(connection, method, path)
        limit = body_limit(method, path)
        if not isinstance(outcome, _Rejection) and limit is not None:
            body = await _read_body(connection.headers, receive, limit)
            if body is None:
                detail = message("api.request_too_large", limit=_size(limit))
                outcome = _Rejection("validation_error", "request_too_large", detail)
            else:
                receive = _replay(body, receive)
        if isinstance(outcome, _Rejection):
            response = problem_response(outcome.problem(), Request(scope))
            await response(scope, receive, send_secured)
            return
        if outcome is not None:
            state = scope.setdefault("state", {})
            state["session"] = outcome.session
            state["principal"] = outcome.principal
        await self.app(scope, receive, send_secured)

    def _check(
        self, connection: HTTPConnection, method: str, path: str
    ) -> _Rejection | _Authorized | None:
        host = connection.headers.get("host", "").lower()
        if host not in self._hosts:
            detail = message("api.invalid_host", port=self._port)
            return _Rejection("forbidden", "invalid_host", detail)
        reason = origin_rejection(method, connection.headers, host)
        if reason is not None:
            return _Rejection("forbidden", "csrf_rejected", reason)
        if not _is_api(path) or _is_public(method, path):
            return None
        session_id = connection.cookies.get(SESSION_COOKIE)
        session = self._sessions.get(session_id)
        hint = message("api.hint_session_required")
        if session_id is None or session is None:
            detail = message("api.session_required")
            return _Rejection("unauthorized", "session_required", detail, hint)
        reason = csrf_rejection(connection.headers, session)
        if reason is not None:
            return _Rejection("forbidden", "csrf_rejected", reason)
        principal = self._principals(session)
        extended = None if principal is None else self._sessions.extend(session_id)
        if principal is None or extended is None:
            self._sessions.end(session_id)
            ended = message("api.session_ended")
            return _Rejection("unauthorized", "session_required", ended, hint)
        return _Authorized(extended, principal)


# Route dependencies --------------------------------------------------------

_SESSION_SCHEME = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description=(
        "Session cookie set by POST /api/v1/session; never enough alone, see"
        " the csrf scheme."
    ),
    auto_error=False,
)
_CSRF_SCHEME = APIKeyHeader(
    name=CSRF_HEADER,
    scheme_name="csrf",
    description=(
        "The session's csrf_token, answered only by POST /api/v1/session;"
        " required with every /api request, reads included."
    ),
    auto_error=False,
)


async def require_session(
    request: Request,
    _cookie: Annotated[str | None, Security(_SESSION_SCHEME)],
    _header: Annotated[str | None, Security(_CSRF_SCHEME)],
) -> Session:
    """Return the request's session or answer ``401 unauthorized``.

    ``SecurityMiddleware`` checks the session cookie and the CSRF token of
    every ``/api`` request and leaves the session here; the dependency names
    both on the route (also in OpenAPI). Outside ``/api`` no request has a
    session.
    """
    session = getattr(request.state, "session", None)
    if not isinstance(session, Session):
        raise ApiError(
            "unauthorized",
            message("api.session_required"),
            reason="session_required",
            hint=message("api.hint_session_required"),
        )
    return session


async def current_principal(
    request: Request, _session: Annotated[Session, Depends(require_session)]
) -> Principal:
    """Return who acts in the request's session (``401`` without one).

    Its roles and groups were read for this request. Routers pass it to
    every service and query (A-ADR-029).
    """
    principal: Principal = request.state.principal
    return principal


# Response headers ----------------------------------------------------------


def csp_header(settings: AppSettings) -> str:
    """Return the Content-Security-Policy for the current settings.

    Parameters
    ----------
    settings : AppSettings
        Settings in effect.

    Returns
    -------
    str
        Policy allowing only the server itself, plus the origins of the
        configured basemaps in ``img-src`` and ``connect-src`` (MapLibre
        fetches tiles) when offline mode is off.
    """
    basemaps: list[str] = []
    if not settings.offline:
        for basemap in settings.basemaps:
            origin = basemap.origin
            if _CSP_SOURCE.fullmatch(origin) and origin not in basemaps:
                basemaps.append(origin)
    images = " ".join(["'self'", "data:", "blob:", *basemaps])
    connections = " ".join(["'self'", *basemaps])
    return "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "worker-src 'self'",
            f"img-src {images}",
            f"connect-src {connections}",
            "font-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        )
    )


# Logs ----------------------------------------------------------------------


def redact_tokens(text: str) -> str:
    """Replace the value of every ``token=`` parameter (any name ending in it)."""
    return _TOKEN_VALUE.sub(lambda match: match[1] + REDACTED, text)


class TokenRedactionFilter(logging.Filter):
    """Hide ``token=`` values in log records, e.g. the access log's request line.

    The record is changed in place, so every handler of the logger sees only
    the redacted text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the message and its string arguments; never drop a record."""
        if isinstance(record.msg, str):
            record.msg = redact_tokens(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_tokens(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        elif isinstance(record.args, Mapping):
            record.args = {
                key: redact_tokens(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True
