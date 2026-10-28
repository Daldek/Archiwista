"""Access protection of local and team mode (SPEC 10.1 and 10.2, A-ADR-012, ADR-046).

Local mode: the server listens on ``127.0.0.1`` only and answers requests
whose ``Host`` is ``127.0.0.1:<port>`` or ``localhost:<port>`` (DNS
rebinding). Team mode (``Transport.team``): every request comes over TLS,
directly or from a trusted reverse proxy whose last ``X-Forwarded-Proto`` is
``https`` (``403 tls_required``), and without TLS in the server only from a
trusted proxy (``403 proxy_required``); ``Host`` and a present ``Origin``
compare with the team's ``origin``; every response carries HSTS. The client
address of a request is its peer, or behind trusted proxies the right-most
``X-Forwarded-For`` address that is no trusted proxy (``client_address``).
A one-time token, of which the local index keeps only the SHA-256 hash
together with who minted it (id and kind), or in team mode a sign-in with an
account's password or through a trusted reverse proxy that names the person
in ``proxy_user_header`` (``api/session.py``), starts a session: an
``HttpOnly`` session cookie (``__Host-archiwista_session`` with ``Secure`` in
team mode) and a separate secret, the session's CSRF token, which the client
keeps (the interface in ``sessionStorage``, bound to the server's origin) and
sends as ``X-Archiwista-CSRF`` with every ``/api`` request, reads included.
Browsers send cookies to every port of a host, so the cookie never acts
alone. ``/api/*`` requires both, except the exchange itself, the sign-ins,
the ways to sign in and the static files of ``/api/docs`` (local mode only).
Every request of a session signed in through the proxy must come from a
trusted proxy naming the same person, and the proxy's header from any other
peer is ignored and logged (``ProxyHeaderLog``). The session acts as a
``Principal`` whose roles and groups are read for every request
(``current_principal`` for routers), and a session of a
temporary password may only change it. An agent's session ends 12 hours
after its start at the latest, and at once when the owner revokes agent
sessions (``revoke_agent_sessions``); every session ends when its account's
sessions are revoked after it started. A browser (``Sec-Fetch-Site``) may
change state only from the same origin and read only from the same origin
or by a direct navigation (``none``). Request bodies are capped before a
route reads them: 4 KiB for the token exchange, 16 KiB for a sign-in, 1 MiB
otherwise (area files keep their own 50 MB limit). Every response carries a
CSP computed from the current settings,
``Referrer-Policy: no-referrer`` and ``X-Content-Type-Options: nosniff``;
there is no CORS. Files are opened only through ``archiwista.paths``.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import sqlite3
import ssl
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie, APIKeyHeader
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from archiwista.api import API_PREFIX, DOCS_PATH
from archiwista.api.errors import ApiError, DenialLog, problem_response
from archiwista.auth import Principal, PrincipalKind
from archiwista.auth.authorize import session_principal
from archiwista.config import HTTPS_PORT, AppSettings, IPNetwork
from archiwista.error_document import Problem
from archiwista.index.schema import connect
from archiwista.messages import message
from archiwista.state import StateStore

type TokenKind = Literal["startup", "agent"]
# How a session started: a startup token, an agent's token, a password, the proxy.
type SessionMethod = Literal["startup", "token", "password", "proxy"]
type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

LOOPBACK_HOST = "127.0.0.1"
SESSION_COOKIE = "archiwista_session"
# The cookie of team mode: the prefix makes browsers require Secure, Path=/ and
# no Domain, so no other host of the network can set it (ASVS 3.3.1).
TEAM_SESSION_COOKIE = "__Host-archiwista_session"
# HSTS of team mode: a year, without includeSubDomains, which could break other
# services of the network's domain (ADR-046).
HSTS = "max-age=31536000"
CSRF_HEADER = "X-Archiwista-CSRF"
SESSION_PATH = f"{API_PREFIX}/session"
LOGIN_PATH = f"{SESSION_PATH}/login"
METHODS_PATH = f"{SESSION_PATH}/methods"
PASSWORD_PATH = f"{SESSION_PATH}/password"
PROXY_PATH = f"{SESSION_PATH}/proxy"
# What a session signed in with a temporary password may do until it changes
# it: read itself, change the password, sign out (ASVS 6.4.1).
PASSWORD_CHANGE_ROUTES = frozenset(
    {
        ("GET", SESSION_PATH),
        ("GET", METHODS_PATH),
        ("PUT", PASSWORD_PATH),
        ("DELETE", SESSION_PATH),
    }
)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Each request of a session moves its end by the idle timeout: a day in local
# mode, 8 hours in team mode, where a session also ends 7 days after its start
# (ADR-046 decision 7, ASVS 7.3.1 and 7.3.2).
SESSION_IDLE_TIMEOUT = timedelta(hours=24)
TEAM_IDLE_TIMEOUT = timedelta(hours=8)
TEAM_MAX_AGE = timedelta(days=7)
# An agent's session ends this long after its start, used or not, in both modes.
AGENT_SESSION_MAX_AGE = timedelta(hours=12)
# The proxy's header from a peer that is no trusted proxy is logged at most once
# per client address in this time, so a client repeating it fills no log.
PROXY_HEADER_LOG_INTERVAL = timedelta(hours=1)
# The browser a session shows in its list (``User-Agent``), cut to this length.
USER_AGENT_MAX_LENGTH = 200
TOKEN_TTL: Mapping[TokenKind, timedelta] = MappingProxyType(
    {"startup": timedelta(minutes=10), "agent": timedelta(minutes=5)}
)
# Request bodies read before a route: the token exchange, a sign-in,
# everything else.
SESSION_BODY_LIMIT_BYTES = 4 * 1024
LOGIN_BODY_LIMIT_BYTES = 16 * 1024
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
# The file downloads (plan v0.4 C11): a version's, an own file's or a snapshot's.
_FILE_PATH = re.compile(
    rf"{API_PREFIX}/(?:stores/[^/]+/versions/.+"
    r"|projects/[^/]+/files/[0-9a-f]{16}(?:/snapshots/[^/]+)?)/file"
)
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
    # The issue time to the microsecond: a token issued before its account's
    # sessions were revoked opens no session (``session_principals``).
    moment = (now or _utc_now()).astimezone(UTC)
    issued_at = _whole_seconds(moment)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    label = new_label()
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
                    moment.isoformat(),
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
    issued_at : datetime
        When the token was issued (UTC, to the microsecond): the session ends
        when its account's sessions are revoked after it.
    """

    principal_id: str
    kind: PrincipalKind
    label: str
    token_kind: TokenKind
    generation: int
    issued_at: datetime


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
                " RETURNING kind, principal, label, created_at",
                (used_at, _digest(token), used_at),
            ).fetchall()
            generation = _agent_generation(connection)
    finally:
        connection.close()
    if not rows:
        return None
    token_kind, carried, label, created_at = rows[0]
    minter = json.loads(carried)
    return SessionGrant(
        principal_id=minter["id"],
        kind=minter["kind"] if token_kind == "startup" else "agent",
        label=label,
        token_kind=token_kind,
        generation=generation,
        issued_at=datetime.fromisoformat(created_at),
    )


def new_label() -> str:
    """Return a new session label: 8 random hexadecimal digits."""
    return secrets.token_hex(_LABEL_BYTES)


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


def fragment_url(origin: str, token: str) -> str:
    """Return the one-time address ``<origin>/#token=<token>``.

    ``origin`` is ``http://127.0.0.1:<port>`` in local mode and the team's
    ``origin`` in team mode (``Transport.origin``). The token travels in the
    fragment, which browsers send neither to the server (nor its access log)
    nor in ``Referer``.
    """
    return f"{origin}/#token={token}"


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
        Label recorded with the session's jobs and the action log.
    csrf_token : str
        128-bit secret that every ``/api`` request of the session carries in
        ``X-Archiwista-CSRF``.
    created_at : datetime
        Start of the session (UTC, whole seconds).
    expires_at : datetime
        End of the session unless used again: every request moves it by the
        idle timeout of the mode, never past the mode's longest life
        (``TEAM_MAX_AGE``; ``AGENT_SESSION_MAX_AGE`` for an agent) after its
        start.
    issued_at : datetime
        When the credential that opened it was issued (UTC, to the
        microsecond): the sign-in, or the one-time token. The session ends
        when its account's sessions are revoked after this time.
    method : {"startup", "token", "password", "proxy"}
        How it started: a startup token, an agent's token, a password, the
        reverse proxy.
    generation : int, optional
        The index's agent-session generation at the start; an agent session
        ends when it changes.
    client : str or None, optional
        The client address of the request that started it.
    user_agent : str or None, optional
        Its browser (``User-Agent``, at most ``USER_AGENT_MAX_LENGTH``
        characters).
    last_seen_at : datetime or None, optional
        Its last request; its start until then.
    password_change_required : bool, optional
        Signed in with a temporary password: until the change it may only
        read itself, change the password and sign out.
    proxy_user : str or None, optional
        The value of the proxy's header that started it (``method`` ``proxy``).
    """

    principal_id: str
    kind: PrincipalKind
    label: str
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    issued_at: datetime
    method: SessionMethod
    generation: int = 0
    client: str | None = None
    user_agent: str | None = None
    last_seen_at: datetime | None = None
    password_change_required: bool = False
    proxy_user: str | None = None


class SessionStore:
    """Sessions of the running server, kept in memory only.

    A server restart ends every session. Only SHA-256 hashes of session ids
    are held. Thread-safe. Local mode: a session ends after
    ``SESSION_IDLE_TIMEOUT`` without requests. Team mode: after
    ``TEAM_IDLE_TIMEOUT`` without requests and ``TEAM_MAX_AGE`` after its
    start. An agent's session ends ``AGENT_SESSION_MAX_AGE`` after its start
    in both.

    Parameters
    ----------
    team : bool, optional
        The limits of team mode.
    clock : Callable[[], datetime], optional
        Source of the current time (aware).
    """

    def __init__(
        self, *, team: bool = False, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._idle_timeout = TEAM_IDLE_TIMEOUT if team else SESSION_IDLE_TIMEOUT
        self._max_age = TEAM_MAX_AGE if team else None
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(
        self,
        principal_id: str,
        kind: PrincipalKind,
        *,
        method: SessionMethod,
        label: str | None = None,
        issued_at: datetime | None = None,
        generation: int = 0,
        client: str | None = None,
        user_agent: str | None = None,
        password_change_required: bool = False,
        proxy_user: str | None = None,
        replaces: str | None = None,
    ) -> tuple[str, Session]:
        """Start a session, ending the one whose cookie the request carried.

        Parameters
        ----------
        principal_id : str
            Who it belongs to.
        kind : {"local_owner", "user", "agent"}
            How it acts.
        method : {"startup", "token", "password", "proxy"}
            How it starts.
        label : str or None, optional
            Its label: the token's; a new one when omitted.
        issued_at : datetime or None, optional
            When its credential was issued (a token); now when omitted.
        generation : int, optional
            The index's agent-session generation (an agent's token).
        client, user_agent : str or None, optional
            The request's client address and ``User-Agent``.
        password_change_required : bool, optional
            Signed in with a temporary password.
        proxy_user : str or None, optional
            The value of the proxy's header.
        replaces : str or None, optional
            The session id of the request's cookie: that session ends, so no
            session id is used before and after a sign-in (ASVS 7.2.4).

        Returns
        -------
        tuple[str, Session]
            The secret session id for the ``HttpOnly`` cookie and the session.
        """
        moment = self._clock().astimezone(UTC)
        now = _whole_seconds(moment)
        session_id = secrets.token_urlsafe(_SESSION_ID_BYTES)
        session = Session(
            principal_id=principal_id,
            kind=kind,
            label=label or new_label(),
            csrf_token=secrets.token_urlsafe(_TOKEN_BYTES),
            created_at=now,
            expires_at=self._end(kind, now, now),
            issued_at=moment if issued_at is None else issued_at,
            method=method,
            generation=generation,
            client=client,
            user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
            last_seen_at=now,
            password_change_required=password_change_required,
            proxy_user=proxy_user,
        )
        with self._lock:
            if replaces:
                self._sessions.pop(_digest(replaces), None)
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
            session = replace(session, expires_at=expires_at, last_seen_at=now)
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

    def live(self, principal_id: str) -> tuple[Session, ...]:
        """Return the live sessions of a principal, its agents' too, oldest first.

        Whether each may still act (its account, a revocation) is
        ``session_principals``' to say.
        """
        now = _whole_seconds(self._clock())
        with self._lock:
            found = [
                session
                for session in self._sessions.values()
                if session.principal_id == principal_id and session.expires_at > now
            ]
        return tuple(sorted(found, key=lambda session: session.created_at))

    def end_label(self, label: str, *, owner: str | None = None) -> Session | None:
        """End the live session with ``label``, if ``owner`` (when given) owns it.

        Returns
        -------
        Session or None
            The ended session; ``None`` when no live session of ``owner``
            has the label.
        """
        now = _whole_seconds(self._clock())
        with self._lock:
            for key, session in self._sessions.items():
                if (
                    session.label == label
                    and session.expires_at > now
                    and owner in (None, session.principal_id)
                ):
                    del self._sessions[key]
                    return session
        return None

    def _end(
        self, kind: PrincipalKind, created_at: datetime, now: datetime
    ) -> datetime:
        end = now + self._idle_timeout
        if kind == "agent":
            return min(end, created_at + AGENT_SESSION_MAX_AGE)
        if self._max_age is not None:
            return min(end, created_at + self._max_age)
        return end


def session_principals(
    state: StateStore, index_path: Path
) -> Callable[[Session], Principal | None]:
    """Return who sessions act as now, for ``SecurityMiddleware``.

    An agent session has ended once the index's agent-session generation is
    not the one it started under (``revoke_agent_sessions``). Otherwise the
    roles and groups come from the state database at each request
    (``session_principal``): a disabled or removed account ends its sessions,
    and so does a revocation of the account's sessions after the session's
    credential was issued (``StateStore.revoke_sessions``, also from another
    process).

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
            state,
            session.principal_id,
            session.kind,
            session=session.label,
            issued_at=session.issued_at,
        )

    return principal


def session_cookie_name(transport: "Transport") -> str:
    """Return the name of the session cookie: ``__Host-`` prefixed in team mode."""
    return TEAM_SESSION_COOKIE if transport.team else SESSION_COOKIE


def set_session_cookie(
    response: Response, session_id: str, transport: "Transport"
) -> None:
    """Set the ``HttpOnly`` session cookie (``SameSite=Strict``, ``Path=/``).

    It ends with the browser session. Browsers send it to every port of the
    host, so it never acts alone: requests also carry the CSRF token. In team
    mode it is ``__Host-archiwista_session`` with ``Secure``.
    """
    response.set_cookie(
        session_cookie_name(transport),
        session_id,
        secure=transport.team,
        httponly=True,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response, transport: "Transport") -> None:
    """Remove the session cookie from the browser (logout)."""
    response.delete_cookie(
        session_cookie_name(transport),
        secure=transport.team,
        httponly=True,
        samesite="strict",
        path="/",
    )


# Transport -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transport:
    """How requests reach the server: local mode, or team mode over TLS.

    Built once from the settings the server started with (``Transport.of``):
    the table ``[team]`` is read only then (ADR-046).

    Parameters
    ----------
    team : bool
        Team mode: TLS, trusted proxies, the team's origin, HSTS.
    origin : str
        The address people open: ``http://127.0.0.1:<port>`` in local mode,
        the team's ``origin`` in team mode.
    hosts : frozenset[str]
        The ``Host`` values the server answers, lower-case.
    trusted : tuple[IPNetwork, ...], optional
        Networks of the trusted reverse proxies (team mode).
    tls_in_server : bool, optional
        Archiwista itself serves TLS (``tls_cert`` and ``tls_key``).
    proxy_header : str or None, optional
        The header in which a trusted proxy names the person
        (``proxy_user_header``, lower-case); ``None`` without one.
    proxy_autocreate : bool, optional
        A missing account the proxy names is created without roles.
    """

    team: bool
    origin: str
    hosts: frozenset[str]
    trusted: tuple[IPNetwork, ...] = ()
    tls_in_server: bool = False
    proxy_header: str | None = None
    proxy_autocreate: bool = False

    @classmethod
    def of(cls, settings: AppSettings, port: int) -> Self:
        """Return the transport of the settings for a server on ``port``."""
        team = settings.team
        if not team.enabled or team.origin is None:
            origin = f"http://{LOOPBACK_HOST}:{port}"
            return cls(team=False, origin=origin, hosts=allowed_hosts(port))
        header = team.proxy_user_header
        return cls(
            team=True,
            origin=team.origin,
            hosts=origin_hosts(team.origin),
            trusted=team.trusted_networks(),
            tls_in_server=team.tls_cert is not None,
            proxy_header=None if header is None else header.lower(),
            proxy_autocreate=team.proxy_autocreate,
        )

    def trusts(self, address: IPAddress | None) -> bool:
        """Return whether ``address`` is a trusted reverse proxy."""
        return address is not None and any(
            address in network for network in self.trusted
        )


def origin_hosts(origin: str) -> frozenset[str]:
    """Return the ``Host`` values of a team's origin (with ``:443`` or without)."""
    parts = urlsplit(origin)
    if parts.port is None:
        return frozenset({parts.netloc, f"{parts.netloc}:{HTTPS_PORT}"})
    return frozenset({parts.netloc})


def _address(text: str) -> IPAddress | None:
    """Return an IP address, an IPv4-mapped IPv6 one as IPv4; ``None`` if none."""
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _peer(scope: Scope) -> IPAddress | None:
    client = scope.get("client")
    return _address(str(client[0])) if client else None


def _header_items(headers: Headers, name: str) -> list[str]:
    """Return the comma-separated items of every ``name`` header, in order."""
    return [
        item.strip()
        for value in headers.getlist(name)
        for item in value.split(",")
        if item.strip()
    ]


def client_address(scope: Scope, transport: Transport) -> str | None:
    """Return the address of the client of a request (ADR-046).

    The peer, or for a trusted proxy the right-most ``X-Forwarded-For``
    address that is no trusted proxy: each trusted proxy names the one it
    heard from, and anything left of the first address that is not a trusted
    proxy came from the client. A request from a trusted proxy itself, or one
    whose chain names only trusted proxies, is the last of them. It is kept
    in ``scope["state"]["client"]`` and ``Principal.client``.

    Parameters
    ----------
    scope : Scope
        The request.
    transport : Transport
        The trusted proxies; none in local mode.

    Returns
    -------
    str or None
        The address; ``None`` without a peer.
    """
    client = scope.get("client")
    if not client:
        return None
    peer = _address(str(client[0]))
    if peer is None:
        return str(client[0])
    if not transport.trusts(peer):
        return str(peer)
    nearest = peer
    for item in reversed(_header_items(Headers(scope=scope), "x-forwarded-for")):
        address = _address(item)
        if address is None:
            break
        if not transport.trusts(address):
            return str(address)
        nearest = address
    return str(nearest)


def named_by_proxy(scope: Scope, transport: Transport) -> str | None:
    """Return the person a trusted reverse proxy names in a request (ADR-046).

    Returns
    -------
    str or None
        The value of ``proxy_user_header``, trimmed and lower-cased, when
        the request's peer is a trusted proxy and carries the header exactly
        once with a value; ``None`` otherwise, always in local mode and
        without the header configured. The proxy replaces any such header a
        client sent, so only its own value arrives.
    """
    if transport.proxy_header is None or not transport.trusts(_peer(scope)):
        return None
    values = Headers(scope=scope).getlist(transport.proxy_header)
    if len(values) != 1:
        return None
    return values[0].strip().lower() or None


def _proxy_header_ignored(scope: Scope, transport: Transport) -> bool:
    """Return whether a peer that is no trusted proxy sent the proxy's header."""
    return (
        transport.proxy_header is not None
        and transport.proxy_header in Headers(scope=scope)
        and not transport.trusts(_peer(scope))
    )


class ProxyHeaderLog:
    """The proxy's header from peers that are no trusted proxies (ADR-046).

    Such a header is ignored; the action log gets one
    ``session.proxy_header_ignored`` entry (outcome ``denied``) per client
    address and ``PROXY_HEADER_LOG_INTERVAL``. Kept in memory; thread-safe.

    Parameters
    ----------
    state : StateStore
        The state database with the action log.
    clock : Callable[[], datetime], optional
        Source of the current time (aware).
    """

    def __init__(
        self, state: StateStore, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._state = state
        self._clock = clock
        self._logged: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def ignored(self, address: str | None) -> None:
        """Log the header ignored from ``address`` unless logged lately."""
        key = address or "-"
        now = self._clock()
        with self._lock:
            last = self._logged.get(key)
            if last is not None and now - last < PROXY_HEADER_LOG_INTERVAL:
                return
            self._logged = {
                other: at
                for other, at in self._logged.items()
                if now - at < PROXY_HEADER_LOG_INTERVAL
            }
            self._logged[key] = now
        self._state.record(
            None, "session.proxy_header_ignored", key, outcome="denied", client=address
        )


def transport_rejection(scope: Scope, transport: Transport) -> "_Rejection | None":
    """Return why team mode refuses how a request came, or ``None``.

    Without TLS in the server only a trusted proxy may connect
    (``proxy_required``); a request is over TLS when the connection is, or
    when a trusted proxy's last ``X-Forwarded-Proto`` says ``https``
    (``tls_required``). Local mode refuses nothing here.
    """
    if not transport.team:
        return None
    trusted = transport.trusts(_peer(scope))
    if not transport.tls_in_server and not trusted:
        detail = message("api.proxy_required")
        return _Rejection("forbidden", "proxy_required", detail)
    if scope.get("scheme") == "https":
        return None
    forwarded = _header_items(Headers(scope=scope), "x-forwarded-proto")
    if trusted and forwarded and forwarded[-1].lower() == "https":
        return None
    detail = message("api.tls_required", origin=transport.origin)
    return _Rejection("forbidden", "tls_required", detail)


# Request rules -------------------------------------------------------------


def allowed_hosts(port: int) -> frozenset[str]:
    """Return the ``Host`` values of local mode (DNS rebinding guard)."""
    return frozenset({f"{LOOPBACK_HOST}:{port}", f"localhost:{port}"})


def origin_rejection(method: str, headers: Headers, origin: str) -> str | None:
    """Return why the ``Origin`` and ``Sec-Fetch-Site`` rule refuses a request.

    Parameters
    ----------
    method : str
        HTTP method; anything but GET, HEAD and OPTIONS changes state.
    headers : Headers
        Request headers.
    origin : str
        The server's own origin: ``http://<Host>`` of the request in local
        mode, the team's ``origin`` in team mode.

    Returns
    -------
    str or None
        The reason, or ``None`` when the rule lets the request through.
        A client without ``Origin`` and ``Sec-Fetch-Site`` (curl, an agent's
        script) passes here; the session and its CSRF token still apply.
    """
    sent = headers.get("origin")
    if sent is not None and sent.lower() != origin:
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
    if sent is None:
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
        The reason, or ``None`` when the request carries the token.
    """
    header = headers.get(CSRF_HEADER)
    if not header:
        return message("api.csrf_missing")
    if _same(header, session.csrf_token):
        return None
    return message("api.csrf_mismatch")


def file_link(method: str, path: str, headers: Headers) -> bool:
    """Return whether a request is a link to a file download (A-ADR-047 decision 5).

    A link cannot send ``X-Archiwista-CSRF``: a ``GET`` or ``HEAD`` of a
    file download (``…/file``) without it passes with the session cookie
    when ``Sec-Fetch-Site`` is ``same-origin`` (a link of the interface) or
    ``none`` (an address typed in). A page of another origin or port sends
    ``same-site`` or ``cross-site`` (``origin_rejection`` refuses it), and a
    client without fetch metadata keeps the header rule.
    """
    if method not in ("GET", "HEAD") or headers.get(CSRF_HEADER):
        return False
    site = (headers.get("sec-fetch-site") or "").lower()
    return site in ("same-origin", "none") and _FILE_PATH.fullmatch(path) is not None


def body_limit(method: str, path: str) -> int | None:
    """Return how many bytes a request body may have before a route reads it.

    4 KiB for ``/api/v1/session`` (the token exchange needs no session), 16
    KiB for ``/api/v1/session/login`` (a sign-in needs none either), 1 MiB
    otherwise; ``None`` for ``POST /api/v1/areas``, which reads an area file
    itself up to its own limit.
    """
    if path == SESSION_PATH:
        return SESSION_BODY_LIMIT_BYTES
    if path == LOGIN_PATH:
        return LOGIN_BODY_LIMIT_BYTES
    if method == "POST" and path == _AREAS_PATH:
        return None
    return BODY_LIMIT_BYTES


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _is_session_path(path: str) -> bool:
    return path == SESSION_PATH or path.startswith(f"{SESSION_PATH}/")


def _is_public(method: str, path: str) -> bool:
    """Return whether a request needs no session.

    The token exchange, the sign-ins, the ways to sign in and the files of
    ``/api/docs``.
    """
    if method == "POST" and path in (SESSION_PATH, LOGIN_PATH, PROXY_PATH):
        return True
    if method in ("GET", "HEAD") and path == METHODS_PATH:
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
    audit: bool = True

    def problem(self) -> Problem:
        return Problem(
            self.code, self.detail, self.hint, details={"reason": self.reason}
        )


@dataclass(frozen=True, slots=True)
class _Authorized:
    session: Session
    principal: Principal


class SecurityMiddleware:
    """Apply the rules of local or team mode to every HTTP request and response.

    Order: in team mode first how the request came (``403 forbidden``,
    reason ``proxy_required`` or ``tls_required``, ``transport_rejection``);
    then ``Host`` (``403 forbidden``, reason ``invalid_host``), ``Origin`` and
    ``Sec-Fetch-Site`` (``403 forbidden``, reason ``csrf_rejected``); then for
    ``/api/*``, except the public requests (``POST /api/v1/session``, ``POST
    /api/v1/session/login``, ``POST /api/v1/session/proxy``, ``GET
    /api/v1/session/methods`` and the files of ``/api/docs``), the session
    cookie (``401 unauthorized``, reason ``session_required``), for a session
    signed in through the proxy a trusted proxy naming the same person
    (``named_by_proxy``; otherwise the session ends, ``401 session_required``),
    the session's CSRF token in every request (``403 csrf_rejected``; a link to
    a file download goes without it, ``file_link``), who the session acts as
    now (``401 session_required`` once its account is disabled or removed, its
    sessions revoked, or its agent session revoked) and, for a session of a
    temporary password, the routes of ``PASSWORD_CHANGE_ROUTES`` only (``403
    forbidden``, reason ``password_change_required``); last the size of the
    body (``400 validation_error``, reason ``request_too_large``). The proxy's
    header from a peer that is no trusted proxy is ignored and logged
    (``ProxyHeaderLog``).
    Only a request passing all of them extends its session. The client
    address (``client_address``), the session and its principal (with that
    address) are left in ``request.state`` for ``require_session`` and
    ``current_principal``. Every response, including these problems, gets
    the CSP of the current settings, ``Referrer-Policy: no-referrer`` and
    ``X-Content-Type-Options: nosniff``, in team mode
    ``Strict-Transport-Security``; ``/api/v1/session*`` also
    ``Cache-Control: no-store``. ``X-Forwarded-Host`` is never read.

    Parameters
    ----------
    app : ASGIApp
        The wrapped application.
    transport : Transport
        Local or team mode: the origin, the ``Host`` values, trusted proxies.
    sessions : SessionStore
        Live sessions.
    settings : Callable[[], AppSettings]
        Current settings (for the CSP of each response).
    principals : Callable[[Session], Principal or None]
        Who a session acts as now (``session_principals``); ``None`` ends
        the session.
    proxy_log : ProxyHeaderLog
        Where the proxy's header from other peers is logged.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        transport: Transport,
        sessions: SessionStore,
        settings: Callable[[], AppSettings],
        principals: Callable[[Session], Principal | None],
        proxy_log: ProxyHeaderLog,
        denials: DenialLog,
    ) -> None:
        self.app = app
        self._transport = transport
        self._cookie = session_cookie_name(transport)
        self._sessions = sessions
        self._settings = settings
        self._principals = principals
        self._proxy_log = proxy_log
        self._denials = denials

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
        if self._transport.team:
            security_headers.append(("strict-transport-security", HSTS))
        if _is_session_path(path):
            security_headers.append(("cache-control", "no-store"))

        async def send_secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in security_headers:
                    headers[name] = value
            await send(message)

        if _proxy_header_ignored(scope, self._transport):
            self._proxy_log.ignored(client_address(scope, self._transport))
        connection = HTTPConnection(scope)
        outcome = transport_rejection(scope, self._transport) or self._check(
            connection, method, path
        )
        limit = body_limit(method, path)
        if not isinstance(outcome, _Rejection) and limit is not None:
            body = await _read_body(connection.headers, receive, limit)
            if body is None:
                detail = message("api.request_too_large", limit=_size(limit))
                outcome = _Rejection("validation_error", "request_too_large", detail)
            else:
                receive = _replay(body, receive)
        if isinstance(outcome, _Rejection):
            await run_in_threadpool(
                self._log_refusal, connection, outcome, method, path
            )
            response = problem_response(outcome.problem(), Request(scope))
            await response(scope, receive, send_secured)
            return
        state = scope.setdefault("state", {})
        state["client"] = client_address(scope, self._transport)
        if outcome is not None:
            state["session"] = outcome.session
            state["principal"] = replace(outcome.principal, client=state["client"])
        await self.app(scope, receive, send_secured)

    def _log_refusal(
        self, connection: HTTPConnection, refusal: _Rejection, method: str, path: str
    ) -> None:
        if not refusal.audit or refusal.reason == "request_too_large":
            return
        cookie = connection.cookies.get(self._cookie)
        if refusal.reason == "session_required" and cookie is None:
            return
        session = self._sessions.get(cookie)
        principal = None if session is None else self._principals(session)
        if session is not None and principal is None:
            return  # Revocation/disablement already has its own audit entry.
        self._denials.refused(
            principal,
            refusal.reason,
            # Routing has not run; never persist raw paths, query or headers.
            route=f"{method} {'/api/*' if _is_api(path) else '/'}",
            client=client_address(connection.scope, self._transport),
        )

    def _check(
        self, connection: HTTPConnection, method: str, path: str
    ) -> _Rejection | _Authorized | None:
        host = connection.headers.get("host", "").lower()
        if host not in self._transport.hosts:
            return _Rejection("forbidden", "invalid_host", self._invalid_host())
        origin = self._transport.origin if self._transport.team else f"http://{host}"
        reason = origin_rejection(method, connection.headers, origin)
        if reason is not None:
            return _Rejection("forbidden", "csrf_rejected", reason)
        if not _is_api(path) or _is_public(method, path):
            return None
        session_id = connection.cookies.get(self._cookie)
        session = self._sessions.get(session_id)
        hint = message("api.hint_session_required")
        if session_id is None or session is None:
            detail = message("api.session_required")
            return _Rejection("unauthorized", "session_required", detail, hint)
        if session.method == "proxy" and session.proxy_user != named_by_proxy(
            connection.scope, self._transport
        ):
            self._sessions.end(session_id)
            ended = message("api.session_ended")
            return _Rejection("unauthorized", "session_required", ended, hint)
        reason = csrf_rejection(connection.headers, session)
        if reason is not None and not file_link(method, path, connection.headers):
            return _Rejection("forbidden", "csrf_rejected", reason)
        principal = self._principals(session)
        if (
            principal is not None
            and session.password_change_required
            and (method, path) not in PASSWORD_CHANGE_ROUTES
        ):
            detail = message("auth.password_change_required")
            return _Rejection("forbidden", "password_change_required", detail)
        extended = None if principal is None else self._sessions.extend(session_id)
        if principal is None or extended is None:
            self._sessions.end(session_id)
            ended = message("api.session_ended")
            # Account/session revocation already has its own audit event.
            return _Rejection(
                "unauthorized", "session_required", ended, hint, audit=False
            )
        return _Authorized(extended, principal)

    def _invalid_host(self) -> str:
        if self._transport.team:
            return message("api.invalid_host_team", origin=self._transport.origin)
        port = urlsplit(self._transport.origin).port
        return message("api.invalid_host", port=port)


# Route dependencies --------------------------------------------------------

_SESSION_SCHEME = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description=(
        "Session cookie set by POST /api/v1/session; never enough alone, see"
        f" the csrf scheme. In team mode it is {TEAM_SESSION_COOKIE} (Secure)."
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


# TLS -----------------------------------------------------------------------

# TLS in the server (ADR-046 decision 3, ASVS 12.1.1): TLS 1.2 or newer, and
# in TLS 1.2 key exchange with ECDHE (forward secrecy) and AEAD ciphers only.
TLS_MINIMUM_VERSION = ssl.TLSVersion.TLSv1_2
TLS_CIPHERS = "ECDHE+AESGCM:ECDHE+CHACHA20"


class _EncryptedKeyError(OSError):
    """The private key asks for a passphrase, which the server never has."""


def _no_passphrase() -> bytes:
    raise _EncryptedKeyError(message("serve.tls_key_encrypted"))


def tls_context(cert: Path, key: Path) -> ssl.SSLContext:
    """Return the context of TLS in the server, its certificate chain loaded.

    TLS 1.2 or newer, and in TLS 1.2 only the AEAD ciphers with ECDHE
    (``TLS_CIPHERS``; TLS 1.3 has no others), set here rather than left to
    the defaults of Python and Uvicorn (an older Uvicorn widened them to
    every TLS 1.0 cipher). The key must need no passphrase: the server never
    asks for one at the terminal.

    Parameters
    ----------
    cert, key : Path
        ``tls_cert`` and ``tls_key`` of the table ``[team]``.

    Raises
    ------
    OSError
        A file cannot be read, or the two do not load as a pair
        (``ssl.SSLError``), or the key is encrypted.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = TLS_MINIMUM_VERSION
    context.set_ciphers(TLS_CIPHERS)
    context.load_cert_chain(cert, key, password=_no_passphrase)
    return context


def tls_problem(cert: Path, key: Path) -> str | None:
    """Return why a certificate chain and its key cannot serve TLS, or ``None``.

    The files are loaded as the server loads them (``tls_context``):
    readable PEM files, a key that matches the certificate and needs no
    passphrase (an encrypted key would make the server ask for one at the
    terminal).

    Parameters
    ----------
    cert, key : Path
        ``tls_cert`` and ``tls_key`` of the table ``[team]``.

    Returns
    -------
    str or None
        What loading them said, or ``None`` when they load as a pair.
    """
    try:
        tls_context(cert, key)
    except OSError as error:  # ssl.SSLError and an encrypted key too
        return error.strerror or str(error)
    return None


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
