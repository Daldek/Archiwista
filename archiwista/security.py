"""Local-mode access protection (SPEC 10.1, A-ADR-012 errata 1).

The server listens on ``127.0.0.1`` only and answers requests whose ``Host``
is ``127.0.0.1:<port>`` or ``localhost:<port>`` (DNS rebinding). A one-time
token, of which the local index keeps only the SHA-256 hash together with
the principal that minted it, is exchanged for a session cookie and a
separate CSRF token; the session acts as that ``Principal``
(``current_principal`` for routers). ``/api/*`` requires the session (except
the exchange itself), and state-changing requests also the
``X-Archiwista-CSRF`` header equal to the session's CSRF token and to its
cookie (double-submit). A present ``Origin`` must be the server itself; a
browser (``Sec-Fetch-Site``) may change state only from the same origin and
read only from the same origin or by a direct navigation (``none``). Every
response carries a CSP computed from the current settings,
``Referrer-Policy: no-referrer`` and ``X-Content-Type-Options: nosniff``;
there is no CORS. Files are opened only through paths taken from the index
and resolved inside their store or project root.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Annotated, Literal

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie, APIKeyHeader
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from archiwista.api import API_PREFIX
from archiwista.api.errors import ApiError, problem_response
from archiwista.auth import Principal
from archiwista.config import AppSettings
from archiwista.errors import PathOutsideRootError
from archiwista.index.schema import connect
from archiwista.messages import MESSAGES

type TokenKind = Literal["startup", "agent"]

LOOPBACK_HOST = "127.0.0.1"
SESSION_COOKIE = "archiwista_session"
CSRF_COOKIE = "archiwista_csrf"
CSRF_HEADER = "X-Archiwista-CSRF"
SESSION_PATH = f"{API_PREFIX}/session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Each request of a session moves its end by the idle timeout.
SESSION_IDLE_TIMEOUT = timedelta(hours=24)
TOKEN_TTL: Mapping[TokenKind, timedelta] = MappingProxyType(
    {"startup": timedelta(minutes=10), "agent": timedelta(minutes=5)}
)
REDACTED = "***"

_TOKEN_BYTES = 16  # 128-bit one-time and CSRF tokens
_SESSION_ID_BYTES = 32
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
    expires_at : datetime
        End of validity (UTC, whole seconds).
    """

    token: str
    kind: TokenKind
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
        Who asked for the token; the token carries this principal.
    now : datetime or None, optional
        Time of issue; the current time when omitted.

    Returns
    -------
    IssuedToken
        The value to hand over and its expiry. Expired tokens are removed
        from the index on the way.
    """
    issued_at = _whole_seconds(now)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = issued_at + TOKEN_TTL[kind]
    principal = json.dumps(
        {
            "id": minted_by.id,
            "kind": minted_by.kind,
            "roles": sorted(minted_by.roles),
            "groups": sorted(minted_by.groups),
        }
    )
    connection = connect(index_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "DELETE FROM session_tokens WHERE expires_at <= ?",
                (issued_at.isoformat(),),
            )
            connection.execute(
                "INSERT INTO session_tokens"
                " (hash, kind, principal, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    _digest(token),
                    kind,
                    principal,
                    issued_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    return IssuedToken(token=token, kind=kind, expires_at=expires_at)


def redeem_one_time_token(
    index_path: Path, token: str, *, now: datetime | None = None
) -> Principal | None:
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
    Principal or None
        Who the new session acts as: the minting principal for a startup
        token, an ``agent`` with the minter's id, roles and groups for an
        agent token. ``None`` for an unknown, already used or expired token;
        concurrent uses of one token succeed at most once.
    """
    used_at = _whole_seconds(now).isoformat()
    connection = connect(index_path)
    try:
        rows = connection.execute(
            "UPDATE session_tokens SET used_at = ?"
            " WHERE hash = ? AND used_at IS NULL AND expires_at > ?"
            " RETURNING kind, principal",
            (used_at, _digest(token), used_at),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        return None
    kind, carried = rows[0]
    minter = json.loads(carried)
    return Principal(
        id=minter["id"],
        kind=minter["kind"] if kind == "startup" else "agent",
        roles=frozenset(minter["roles"]),
        groups=frozenset(minter["groups"]),
    )


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
    principal : Principal
        Who acts; services and background jobs receive it.
    csrf_token : str
        128-bit token that state-changing requests carry in
        ``X-Archiwista-CSRF`` and in the ``archiwista_csrf`` cookie.
    created_at : datetime
        Start of the session (UTC).
    expires_at : datetime
        End of the session unless used again; every request of the session
        moves it ``SESSION_IDLE_TIMEOUT`` ahead.
    """

    principal: Principal
    csrf_token: str
    created_at: datetime
    expires_at: datetime


class SessionStore:
    """Sessions of the running server, kept in memory only.

    A server restart ends every session: ``archiwista serve`` prints a new
    one-time address. Only SHA-256 hashes of session ids are held.
    Thread-safe.

    Parameters
    ----------
    idle_timeout : timedelta, optional
        How long a session lives without requests.
    clock : Callable[[], datetime], optional
        Source of the current time (aware).
    """

    def __init__(
        self,
        *,
        idle_timeout: timedelta = SESSION_IDLE_TIMEOUT,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._idle_timeout = idle_timeout
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, principal: Principal) -> tuple[str, Session]:
        """Start a session acting as ``principal``.

        Returns
        -------
        tuple[str, Session]
            The secret session id for the ``HttpOnly`` cookie and the session.
        """
        now = _whole_seconds(self._clock())
        session_id = secrets.token_urlsafe(_SESSION_ID_BYTES)
        session = Session(
            principal=principal,
            csrf_token=secrets.token_urlsafe(_TOKEN_BYTES),
            created_at=now,
            expires_at=now + self._idle_timeout,
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
        """Return the live session of a cookie value and extend it.

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
            if session is None:
                return None
            if session.expires_at <= now:
                del self._sessions[key]
                return None
            session = replace(session, expires_at=now + self._idle_timeout)
            self._sessions[key] = session
        return session


def set_session_cookies(
    response: Response, session: Session, *, session_id: str | None = None
) -> None:
    """Set the CSRF cookie and, for a new session, the session cookie.

    The session cookie is ``HttpOnly``; the CSRF cookie is readable by the
    interface, which copies it to ``X-Archiwista-CSRF``. Both are
    ``SameSite=Strict`` with ``Path=/`` and end with the browser session.
    """
    if session_id is not None:
        response.set_cookie(
            SESSION_COOKIE, session_id, httponly=True, samesite="strict", path="/"
        )
    response.set_cookie(CSRF_COOKIE, session.csrf_token, samesite="strict", path="/")


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
        script) passes here; the session and CSRF checks still apply.
    """
    origin = headers.get("origin")
    if origin is not None and origin.lower() != f"http://{host}":
        return MESSAGES["api_cross_site"]
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is None:
        return None
    fetch_site = fetch_site.lower()
    if method in SAFE_METHODS:
        if fetch_site in ("same-origin", "none"):
            return None
        return MESSAGES["api_cross_site"]
    if fetch_site != "same-origin":
        return MESSAGES["api_cross_site"]
    if origin is None:
        return MESSAGES["api_origin_missing"]
    return None


def csrf_rejection(
    headers: Headers, cookies: Mapping[str, str], session: Session
) -> str | None:
    """Return why a state-changing request fails the CSRF double-submit check.

    The ``X-Archiwista-CSRF`` header and the ``archiwista_csrf`` cookie must
    both equal the session's CSRF token.

    Returns
    -------
    str or None
        Polish reason, or ``None`` when the request carries the token.
    """
    header = headers.get(CSRF_HEADER)
    if not header:
        return MESSAGES["api_csrf_missing"]
    header_matches = _same(header, session.csrf_token)
    cookie_matches = _same(cookies.get(CSRF_COOKIE, ""), session.csrf_token)
    if header_matches and cookie_matches:
        return None
    return MESSAGES["api_csrf_mismatch"]


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _is_session_path(path: str) -> bool:
    return path == SESSION_PATH or path.startswith(f"{SESSION_PATH}/")


@dataclass(frozen=True, slots=True)
class _Rejection:
    status: int
    code: str
    detail: str


class SecurityMiddleware:
    """Apply the local-mode rules to every HTTP request and response.

    Order: ``Host`` (``400 invalid_host``), ``Origin`` and ``Sec-Fetch-Site``
    (``403 csrf_rejected``), then for ``/api/*`` except ``POST
    /api/v1/session`` the session (``401 session_required``) and, for
    state-changing methods, the CSRF token (``403 csrf_rejected``). The
    session is left in ``request.state.session`` for ``require_session``.
    Every response, including these problems, gets the CSP of the current
    settings, ``Referrer-Policy: no-referrer`` and ``X-Content-Type-Options:
    nosniff``; ``/api/v1/session*`` also ``Cache-Control: no-store``.

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
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        port: int,
        sessions: SessionStore,
        settings: Callable[[], AppSettings],
    ) -> None:
        self.app = app
        self._port = port
        self._hosts = allowed_hosts(port)
        self._sessions = sessions
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check an HTTP request; other scopes (lifespan) pass unchanged."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
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
        outcome = self._check(connection, scope["method"], path)
        if isinstance(outcome, _Rejection):
            response = problem_response(outcome.status, outcome.code, outcome.detail)
            await response(scope, receive, send_secured)
            return
        if outcome is not None:
            scope.setdefault("state", {})["session"] = outcome
        await self.app(scope, receive, send_secured)

    def _check(
        self, connection: HTTPConnection, method: str, path: str
    ) -> _Rejection | Session | None:
        host = connection.headers.get("host", "").lower()
        if host not in self._hosts:
            detail = MESSAGES["api_invalid_host"].format(port=self._port)
            return _Rejection(400, "invalid_host", detail)
        reason = origin_rejection(method, connection.headers, host)
        if reason is not None:
            return _Rejection(403, "csrf_rejected", reason)
        if not _is_api(path) or (method == "POST" and path == SESSION_PATH):
            return None
        session = self._sessions.get(connection.cookies.get(SESSION_COOKIE))
        if session is None:
            detail = MESSAGES["api_session_required"]
            return _Rejection(401, "session_required", detail)
        if method not in SAFE_METHODS:
            reason = csrf_rejection(connection.headers, connection.cookies, session)
            if reason is not None:
                return _Rejection(403, "csrf_rejected", reason)
        return session


# Route dependencies --------------------------------------------------------

_SESSION_SCHEME = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description="Session cookie set by POST /api/v1/session.",
    auto_error=False,
)
_CSRF_SCHEME = APIKeyHeader(
    name=CSRF_HEADER,
    scheme_name="csrf",
    description=(
        "CSRF token of the session (csrf_token of GET /api/v1/session), also"
        " sent in the archiwista_csrf cookie; required by POST, PUT and DELETE."
    ),
    auto_error=False,
)


async def require_session(
    request: Request,
    _cookie: Annotated[str | None, Security(_SESSION_SCHEME)],
) -> Session:
    """Return the request's session or answer ``401 session_required``.

    ``SecurityMiddleware`` has already found it for ``/api/*``; the
    dependency names the requirement on the route (also in OpenAPI) and
    holds for routes mounted elsewhere.
    """
    session = getattr(request.state, "session", None)
    if isinstance(session, Session):
        return session
    store: SessionStore = request.app.state.sessions
    session = store.get(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise ApiError(401, "session_required", MESSAGES["api_session_required"])
    return session


async def require_csrf(
    request: Request,
    session: Annotated[Session, Depends(require_session)],
    _header: Annotated[str | None, Security(_CSRF_SCHEME)],
) -> Session:
    """Return the session of a request with its CSRF token or answer ``403``.

    Declare it on every state-changing route, like ``require_session``.
    """
    reason = csrf_rejection(request.headers, request.cookies, session)
    if reason is not None:
        raise ApiError(403, "csrf_rejected", reason)
    return session


async def current_principal(
    session: Annotated[Session, Depends(require_session)],
) -> Principal:
    """Return who acts in the request's session (``401`` without one).

    Routers pass it to every service and query (A-ADR-029).
    """
    return session.principal


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


# Files ---------------------------------------------------------------------


def resolve_indexed_path(root: Path, relative: str) -> Path:
    """Resolve an indexed path inside its store or project root.

    Parameters
    ----------
    root : Path
        Configured producer directory of a store, or a project directory.
    relative : str
        Slot, version or project path relative to ``root`` as stored in the
        local index (``/`` separators). Never a raw path from a client:
        routes look the identifier up in the index first.

    Returns
    -------
    Path
        The real path (symbolic links resolved) inside the real root.

    Raises
    ------
    PathOutsideRootError
        If the path is absolute, contains ``..`` or a NUL character, or
        resolves outside the root, e.g. through a symbolic link.
    FileNotFoundError
        If the root or the file does not exist (e.g. a disconnected share).
    """
    message = MESSAGES["path_outside_root"].format(path=relative)
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        not relative
        or "\x00" in relative
        or posix.is_absolute()
        or windows.anchor
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise PathOutsideRootError(message)
    real_root = root.resolve(strict=True)
    real = (real_root / relative).resolve(strict=True)
    if not real.is_relative_to(real_root):
        raise PathOutsideRootError(message)
    return real


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
