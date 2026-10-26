"""Access protection: Host, tokens, session, CSRF, paths; team transport (SPEC 10)."""

import hashlib
import logging
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.types import Scope

from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER, LOCAL_ROLES, Principal
from archiwista.config import (
    AppSettings,
    BasemapConfig,
    ConfigStore,
    SettingsService,
    TeamSettings,
)
from archiwista.index.schema import initialize
from archiwista.security import (
    CSRF_HEADER,
    SESSION_COOKIE,
    TOKEN_TTL,
    SessionStore,
    TokenKind,
    Transport,
    client_address,
    csp_header,
    current_principal,
    issue_one_time_token,
    origin_rejection,
    redeem_one_time_token,
    revoke_agent_sessions,
    transport_rejection,
)
from archiwista.state import StateStore
from tests.fixtures.local_server import NoSources, local_paths, serving

PORT = 8090
BASE_URL = f"http://127.0.0.1:{PORT}"
OPENFREEMAP = "https://tiles.openfreemap.org"
START = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


class Clock:
    """Settable time source for sessions."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        """Return the current test time."""
        return self.now


@dataclass
class Api:
    """Application under test with its index, settings and session clock."""

    client: TestClient
    index_path: Path
    settings: SettingsService
    clock: Clock

    def login(self) -> tuple[str, str]:
        """Start a session from a fresh token; return its id and CSRF token.

        The client forgets the cookies, so each request states its own.
        """
        issued = issue_one_time_token(self.index_path, "startup", minted_by=LOCAL_OWNER)
        response = self.client.post("/api/v1/session", json={"token": issued.token})
        assert response.status_code == 200
        session_id = response.cookies[SESSION_COOKIE]
        csrf = str(response.json()["csrf_token"])
        self.client.cookies.clear()
        return session_id, csrf


def cookies(session_id: str, csrf: str | None = None) -> dict[str, str]:
    """Return the session cookie and, optionally, the session's CSRF header."""
    headers = {"cookie": f"{SESSION_COOKIE}={session_id}"}
    if csrf is not None:
        headers[CSRF_HEADER] = csrf
    return headers


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """Serve the application with an empty index and two interface files."""
    index_path = tmp_path / "data" / "index.sqlite"
    initialize(index_path)
    config = ConfigStore(tmp_path / "config" / "config.toml")
    settings = SettingsService(config, NoSources())
    web_dir = tmp_path / "web"
    (web_dir / "src").mkdir(parents=True)
    (web_dir / "index.html").write_text("<!doctype html><title>A</title>", "utf-8")
    (web_dir / "src" / "main.js").write_text("export {};\n", "utf-8")
    clock = Clock(START)
    app = create_app(
        port=PORT,
        settings=settings,
        index_path=index_path,
        state=StateStore(tmp_path / "data" / "state.sqlite"),
        registry=NoSources(),
        areas_dir=tmp_path / "data" / "areas",
        sessions=SessionStore(clock=clock),
        web_dir=web_dir,
    )

    @app.get("/api/v1/principal")
    async def principal(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> dict[str, object]:
        """Show who acts, as a router passing it to services would see it."""
        return {
            "id": principal.id,
            "kind": principal.kind,
            "roles": sorted(principal.roles),
            "groups": sorted(principal.groups),
        }

    with TestClient(app, base_url=BASE_URL) as client:
        yield Api(client, index_path, settings, clock)


def assert_problem(
    response: httpx.Response, status: int, code: str, reason: str | None = None
) -> None:
    """Check an RFC 9457 problem: registry code and status, reason, Polish detail."""
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["detail"]
    if reason is not None:
        assert body["details"]["reason"] == reason


# Host ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "evil.example:8090",
        "127.0.0.1:9999",
        "localhost",
        "127.0.0.1",
        "[::1]:8090",
        "127.0.0.1.nip.io:8090",
    ],
)
def test_security_foreign_host_rejected(api: Api, host: str) -> None:
    """A request naming another host or port is refused (DNS rebinding)."""
    session_id, _ = api.login()

    page = api.client.get("/", headers={"host": host})
    data = api.client.get(
        "/api/v1/session", headers={"host": host, **cookies(session_id)}
    )

    assert_problem(page, 403, "forbidden", "invalid_host")
    assert_problem(data, 403, "forbidden", "invalid_host")


@pytest.mark.parametrize("host", ["127.0.0.1:8090", "localhost:8090"])
def test_security_loopback_host_served(api: Api, host: str) -> None:
    """Both loopback names of the server's own port are answered."""
    response = api.client.get("/", headers={"host": host})

    assert response.status_code == 200


# One-time tokens and sessions ---------------------------------------------


def test_security_token_exchange_starts_session(api: Api) -> None:
    """The exchange sets only an HttpOnly session cookie and answers the token.

    Both answers name the principal's roles; ``GET`` repeats all but the token.
    """
    issued = issue_one_time_token(api.index_path, "startup", minted_by=LOCAL_OWNER)

    response = api.client.post("/api/v1/session", json={"token": issued.token})
    session_id = response.cookies[SESSION_COOKIE]
    csrf = response.json()["csrf_token"]
    api.client.cookies.clear()
    cookie_only = api.client.get("/api/v1/session", headers=cookies(session_id))
    state = api.client.get("/api/v1/session", headers=cookies(session_id, csrf))

    assert response.status_code == 200
    body = response.json()
    assert (body["actor"], body["kind"], body["roles"], body["label"]) == (
        "local",
        "local_owner",
        sorted(LOCAL_ROLES),
        issued.label,
    )
    assert response.headers["cache-control"] == "no-store"
    (set_cookie,) = response.headers.get_list("set-cookie")
    assert set_cookie.startswith(f"{SESSION_COOKIE}=")
    for attribute in ("httponly", "samesite=strict", "path=/"):
        assert attribute in set_cookie.lower()
    assert session_id not in (issued.token, csrf)
    assert_problem(cookie_only, 403, "forbidden", "csrf_rejected")
    assert state.status_code == 200
    assert state.json() == {key: body[key] for key in state.json()}
    assert "csrf_token" not in state.json()
    assert state.headers["cache-control"] == "no-store"


def test_security_token_used_twice_rejected(api: Api) -> None:
    """A one-time token starts one session only."""
    issued = issue_one_time_token(api.index_path, "startup", minted_by=LOCAL_OWNER)
    first = api.client.post("/api/v1/session", json={"token": issued.token})
    api.client.cookies.clear()

    second = api.client.post("/api/v1/session", json={"token": issued.token})

    assert first.status_code == 200
    assert_problem(second, 401, "unauthorized", "session_required")
    assert "set-cookie" not in second.headers


@pytest.mark.parametrize("kind", ["startup", "agent"])
def test_security_token_valid_until_expiry(tmp_path: Path, kind: TokenKind) -> None:
    """Startup tokens live 10 minutes, next-session tokens 5, not a second more."""
    index_path = tmp_path / "index.sqlite"
    initialize(index_path)
    on_time = issue_one_time_token(index_path, kind, minted_by=LOCAL_OWNER, now=START)
    late = issue_one_time_token(index_path, kind, minted_by=LOCAL_OWNER, now=START)
    ttl = TOKEN_TTL[kind]

    accepted = redeem_one_time_token(
        index_path, on_time.token, now=START + ttl - timedelta(seconds=1)
    )
    expired = redeem_one_time_token(index_path, late.token, now=START + ttl)

    assert on_time.expires_at == START + ttl
    assert accepted is not None
    assert expired is None


def test_security_tokens_carry_minter_id_and_kind_only(tmp_path: Path) -> None:
    """A token keeps who minted it, never their roles: those are read per request."""
    index_path = tmp_path / "index.sqlite"
    initialize(index_path)
    minter = Principal(
        id="kasia",
        kind="user",
        roles=frozenset({"admin"}),
        groups=frozenset({"gis", "hydro"}),
    )
    startup = issue_one_time_token(index_path, "startup", minted_by=minter)
    agent = issue_one_time_token(index_path, "agent", minted_by=minter)
    connection = sqlite3.connect(index_path)
    try:
        kept = [
            row[0] for row in connection.execute("SELECT principal FROM session_tokens")
        ]
    finally:
        connection.close()

    own = redeem_one_time_token(index_path, startup.token)
    delegated = redeem_one_time_token(index_path, agent.token)

    assert kept == ['{"id": "kasia", "kind": "user"}'] * 2
    assert own is not None and delegated is not None
    assert (own.principal_id, own.kind, own.label) == ("kasia", "user", startup.label)
    assert (delegated.principal_id, delegated.kind) == ("kasia", "agent")
    assert delegated.label == agent.label != startup.label


def test_security_current_principal_owner_then_agent(api: Api) -> None:
    """The owner's session acts as ``local``; a token it issues starts an agent."""
    session_id, csrf = api.login()
    owner = api.client.get("/api/v1/principal", headers=cookies(session_id, csrf))
    issued = api.client.post(
        "/api/v1/session/tokens",
        headers=cookies(session_id, csrf),
    )
    exchanged = api.client.post(
        "/api/v1/session", json={"token": issued.json()["token"]}
    )
    agent_id = exchanged.cookies[SESSION_COOKIE]
    api.client.cookies.clear()

    agent_csrf = exchanged.json()["csrf_token"]
    agent = api.client.get("/api/v1/principal", headers=cookies(agent_id, agent_csrf))

    roles = sorted(LOCAL_ROLES)
    assert owner.json() == {
        "id": "local",
        "kind": "local_owner",
        "roles": roles,
        "groups": [],
    }
    assert agent.json() == {
        "id": "local",
        "kind": "agent",
        "roles": roles,
        "groups": [],
    }
    assert exchanged.json()["actor"] == "local"


def test_security_expired_token_rejected_over_http(api: Api) -> None:
    """An exchange after the token's expiry gets no session."""
    issued_at = datetime.now(UTC) - TOKEN_TTL["startup"]
    issued = issue_one_time_token(
        api.index_path, "startup", minted_by=LOCAL_OWNER, now=issued_at
    )

    response = api.client.post("/api/v1/session", json={"token": issued.token})

    assert_problem(response, 401, "unauthorized", "session_required")


def test_security_index_keeps_only_token_hash(tmp_path: Path) -> None:
    """The index stores the SHA-256 of a token, never the token itself."""
    index_path = tmp_path / "index.sqlite"
    initialize(index_path)

    issued = issue_one_time_token(index_path, "agent", minted_by=LOCAL_OWNER)

    connection = sqlite3.connect(index_path)
    try:
        rows = connection.execute("SELECT * FROM session_tokens").fetchall()
    finally:
        connection.close()
    assert len(rows) == 1
    assert hashlib.sha256(issued.token.encode()).hexdigest() in rows[0]
    assert all(issued.token not in str(value) for value in rows[0])


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/session"),
        ("POST", "/api/v1/session/tokens"),
        ("GET", "/api/v1/openapi.json"),
        ("GET", "/api/v1/not-a-route"),
    ],
)
def test_security_api_without_session_rejected(
    api: Api, method: str, path: str
) -> None:
    """Every API route but the exchange answers 401 without a session."""
    missing = api.client.request(method, path)
    unknown = api.client.request(method, path, headers=cookies("forged-session"))

    assert_problem(missing, 401, "unauthorized", "session_required")
    assert_problem(unknown, 401, "unauthorized", "session_required")


def test_security_session_ends_after_idle_timeout(api: Api) -> None:
    """Each request extends the session; a day without requests ends it."""
    session_id, csrf = api.login()
    api.clock.now = START + timedelta(hours=23)
    kept = api.client.get("/api/v1/session", headers=cookies(session_id, csrf))

    api.clock.now = START + timedelta(hours=23 + 24)
    ended = api.client.get("/api/v1/session", headers=cookies(session_id, csrf))

    assert kept.status_code == 200
    assert kept.json()["expires_at"] == "2026-10-20T11:00:00Z"
    assert_problem(ended, 401, "unauthorized", "session_required")


# CSRF, Origin and Sec-Fetch-Site ------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("header", [None, "wrong"])
def test_security_every_request_needs_csrf_token(
    api: Api, method: str, header: str | None
) -> None:
    """The cookie alone, which other ports of the host also get, never acts."""
    session_id, csrf = api.login()
    path = "/api/v1/session" if method == "GET" else "/api/v1/session/tokens"
    api.clock.now = START + timedelta(hours=20)

    response = api.client.request(method, path, headers=cookies(session_id, header))
    api.clock.now = START + timedelta(hours=25)
    later = api.client.get("/api/v1/session", headers=cookies(session_id, csrf))

    assert_problem(response, 403, "forbidden", "csrf_rejected")
    # A refused request does not keep the session alive.
    assert_problem(later, 401, "unauthorized", "session_required")


def test_security_logout_ends_session(api: Api) -> None:
    """DELETE /session ends the session at once and removes its cookie."""
    session_id, csrf = api.login()

    ended = api.client.delete("/api/v1/session", headers=cookies(session_id, csrf))
    after = api.client.get("/api/v1/session", headers=cookies(session_id, csrf))

    assert ended.status_code == 204
    assert "max-age=0" in ended.headers["set-cookie"].lower()
    assert_problem(after, 401, "unauthorized", "session_required")


def _agent(api: Api, session_id: str, csrf: str) -> tuple[str, str]:
    """Open an agent session with a token the given session issues."""
    issued = api.client.post(
        "/api/v1/session/tokens", headers=cookies(session_id, csrf)
    )
    exchanged = api.client.post(
        "/api/v1/session", json={"token": issued.json()["token"]}
    )
    agent = exchanged.cookies[SESSION_COOKIE], exchanged.json()["csrf_token"]
    api.client.cookies.clear()
    return agent


def test_security_agent_cannot_issue_tokens(api: Api) -> None:
    """An agent's session opens no further sessions: 403 permission_denied."""
    agent_id, agent_csrf = _agent(api, *api.login())

    refused = api.client.post(
        "/api/v1/session/tokens", headers=cookies(agent_id, agent_csrf)
    )

    assert_problem(refused, 403, "forbidden", "permission_denied")


def test_security_agent_session_ends_after_max_age(api: Api) -> None:
    """An agent's session used every hour still ends 12 hours after its start."""
    agent_id, agent_csrf = _agent(api, *api.login())
    answers = []
    for hour in range(1, 13):
        api.clock.now = START + timedelta(hours=hour)
        answers.append(
            api.client.get("/api/v1/session", headers=cookies(agent_id, agent_csrf))
        )

    assert [answer.status_code for answer in answers[:-1]] == [200] * 11
    assert answers[0].json()["expires_at"] == "2026-10-19T00:00:00Z"
    assert_problem(answers[-1], 401, "unauthorized", "session_required")


def test_security_revoke_agent_sessions(api: Api) -> None:
    """Revoking ends live agent sessions and unused agent tokens, not the owner's."""
    owner = api.login()
    agent_id, agent_csrf = _agent(api, *owner)
    unused = issue_one_time_token(api.index_path, "agent", minted_by=LOCAL_OWNER)

    refused = revoke_agent_sessions(api.index_path)
    agent = api.client.get("/api/v1/session", headers=cookies(agent_id, agent_csrf))
    kept = api.client.get("/api/v1/session", headers=cookies(*owner))
    late = api.client.post("/api/v1/session", json={"token": unused.token})
    next_agent = _agent(api, *owner)
    fresh = api.client.get("/api/v1/session", headers=cookies(*next_agent))

    assert refused == 1
    assert_problem(agent, 401, "unauthorized", "session_required")
    assert kept.status_code == 200
    assert_problem(late, 401, "unauthorized", "session_required")
    assert fresh.status_code == 200 and fresh.json()["kind"] == "agent"


def test_security_body_over_limit_refused_before_reading(api: Api) -> None:
    """Bodies over 4 KiB (exchange) or 1 MiB (other routes) answer 413."""
    session_id, csrf = api.login()

    declared = api.client.post(
        "/api/v1/session", content=b"{}", headers={"content-length": "5000"}
    )
    chunked = api.client.post(
        "/api/v1/session",
        content=(b"x" * 1024 for _ in range(5)),
        headers={"content-type": "application/json"},
    )
    settings = api.client.put(
        "/api/v1/settings",
        content=(b" " * 65536 for _ in range(17)),
        headers={**cookies(session_id, csrf), "content-type": "application/json"},
    )

    for response in (declared, chunked, settings):
        assert_problem(response, 400, "validation_error", "request_too_large")


def test_security_docs_files_need_no_session(api: Api) -> None:
    """/api/docs serves its files to a tab; the OpenAPI document needs the session."""
    page = api.client.get("/api/docs")
    document = api.client.get("/api/v1/openapi.json")

    assert page.status_code == 200
    assert_problem(document, 401, "unauthorized", "session_required")


def test_security_client_without_origin_passes_with_session_and_csrf(
    api: Api,
) -> None:
    """A script without Origin and Sec-Fetch-* changes state with session+CSRF."""
    session_id, csrf = api.login()
    response = api.client.post(
        "/api/v1/session/tokens", headers=cookies(session_id, csrf)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == f"http://127.0.0.1:{PORT}/#token={body['token']}"
    assert response.headers["cache-control"] == "no-store"
    agent = api.client.post("/api/v1/session", json={"token": body["token"]})
    assert agent.status_code == 200


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://127.0.0.1"])
def test_security_foreign_origin_rejected(api: Api, origin: str) -> None:
    """A present Origin other than the server is refused, even for the exchange."""
    session_id, _ = api.login()
    issued = issue_one_time_token(api.index_path, "startup", minted_by=LOCAL_OWNER)

    read = api.client.get(
        "/api/v1/session", headers={"origin": origin, **cookies(session_id)}
    )
    exchange = api.client.post(
        "/api/v1/session", json={"token": issued.token}, headers={"origin": origin}
    )

    assert_problem(read, 403, "forbidden", "csrf_rejected")
    assert_problem(exchange, 403, "forbidden", "csrf_rejected")
    later = api.client.post("/api/v1/session", json={"token": issued.token})
    assert later.status_code == 200


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_security_cross_site_read_rejected(api: Api, site: str) -> None:
    """A browser read started by another site is refused, page or API."""
    session_id, _ = api.login()

    page = api.client.get("/", headers={"sec-fetch-site": site})
    data = api.client.get(
        "/api/v1/session", headers={"sec-fetch-site": site, **cookies(session_id)}
    )

    assert_problem(page, 403, "forbidden", "csrf_rejected")
    assert_problem(data, 403, "forbidden", "csrf_rejected")


@pytest.mark.parametrize(
    ("site", "origin", "status"),
    [
        ("same-origin", None, 403),
        ("none", BASE_URL, 403),
        ("same-origin", BASE_URL, 201),
    ],
)
def test_security_browser_state_change_needs_same_origin(
    api: Api, site: str, origin: str | None, status: int
) -> None:
    """A browser changes state only same-origin and with an Origin header."""
    session_id, csrf = api.login()
    headers = {**cookies(session_id, csrf), "sec-fetch-site": site}
    if origin is not None:
        headers["origin"] = origin

    response = api.client.post("/api/v1/session/tokens", headers=headers)

    assert response.status_code == status


def test_security_navigation_with_fetch_site_none_passes(api: Api) -> None:
    """An address typed or opened from the terminal (``none``) is served."""
    session_id, csrf = api.login()
    navigation = {"sec-fetch-site": "none", "sec-fetch-mode": "navigate"}

    page = api.client.get("/", headers=navigation)
    data = api.client.get(
        "/api/v1/session", headers={**navigation, **cookies(session_id, csrf)}
    )

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert data.status_code == 200


def test_security_no_cors_headers(api: Api) -> None:
    """Neither a preflight nor a same-origin request gets CORS headers."""
    session_id, csrf = api.login()

    preflight = api.client.options(
        "/api/v1/session",
        headers={
            "origin": BASE_URL,
            "access-control-request-method": "POST",
            "access-control-request-headers": CSRF_HEADER,
        },
    )
    read = api.client.get(
        "/api/v1/session", headers={"origin": BASE_URL, **cookies(session_id, csrf)}
    )

    assert read.status_code == 200
    for response in (preflight, read):
        assert not [
            name for name in response.headers if name.startswith("access-control-")
        ]


# Interface files and response headers -------------------------------------


def test_security_interface_files_need_no_session(api: Api) -> None:
    """The page and its modules load without a session, with security headers."""
    page = api.client.get("/")
    module = api.client.get("/static/src/main.js")

    assert page.status_code == 200
    assert module.status_code == 200
    assert "javascript" in module.headers["content-type"]
    for response in (page, module):
        assert response.headers["content-security-policy"] == csp_header(AppSettings())
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_security_interface_files_are_revalidated(api: Api) -> None:
    """Page and modules say ``no-cache``; a request naming the ``ETag`` gets ``304``.

    A browser reusing them by heuristic freshness kept the interface of the
    previous version after an upgrade.
    """
    for path in ("/", "/static/src/main.js"):
        first = api.client.get(path)
        again = api.client.get(path, headers={"if-none-match": first.headers["etag"]})

        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-cache"
        assert again.status_code == 304
        assert again.content == b""
        assert again.headers["cache-control"] == "no-cache"
        assert again.headers["content-security-policy"] == csp_header(AppSettings())


def test_security_interface_files_stay_in_web_dir(api: Api, tmp_path: Path) -> None:
    """Neither ``..`` nor a symbolic link serves a file outside the interface."""
    secret = tmp_path / "secret.txt"
    secret.write_text("classified", "utf-8")
    (tmp_path / "web" / "link.txt").symlink_to(secret)

    linked = api.client.get("/static/link.txt")
    climbed = api.client.get("/static/%2E%2E/secret.txt")

    assert linked.status_code == 404
    assert climbed.status_code == 404
    assert "classified" not in linked.text + climbed.text


def test_security_csp_lists_basemaps_only_online() -> None:
    """Basemap origins are allowed for images and fetches, and only online."""
    basemaps = (
        BasemapConfig(name="OpenFreeMap", kind="vector", url=f"{OPENFREEMAP}/planet"),
        BasemapConfig(name="Kafle", url=f"{OPENFREEMAP}/a/{{z}}/{{x}}/{{y}}.png"),
        BasemapConfig(
            name="Orto", kind="wms", url="https://mapy.geoportal.gov.pl:443/wms"
        ),
    )
    online = AppSettings(basemaps=basemaps)

    directives = dict(item.split(" ", 1) for item in csp_header(online).split("; "))
    offline = csp_header(online.model_copy(update={"offline": True}))

    sources = f"{OPENFREEMAP} https://mapy.geoportal.gov.pl:443"
    assert directives["img-src"] == f"'self' data: blob: {sources}"
    assert directives["connect-src"] == f"'self' {sources}"
    for name in ("default-src", "script-src", "style-src", "worker-src", "font-src"):
        assert directives[name] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert "http" not in offline
    assert "img-src 'self' data: blob:;" in offline


def test_security_csp_follows_settings_changes(api: Api) -> None:
    """Switching to offline mode changes the CSP of the next response."""
    before = api.client.get("/")

    api.settings.update(AppSettings(offline=True))
    after = api.client.get("/")

    assert OPENFREEMAP in before.headers["content-security-policy"]
    assert OPENFREEMAP not in after.headers["content-security-policy"]


# Logs ----------------------------------------------------------------------


class RecordingHandler(logging.Handler):
    """Keep every log line, as formatted text."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Remember the record's logger and message."""
        self.lines.append(f"{record.name}: {record.getMessage()}")


def test_token_not_logged(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The exchange and a ``?token=`` request leave no token in any server log."""
    caplog.set_level(logging.DEBUG)
    handler = RecordingHandler()
    loggers = [logging.getLogger(name) for name in ("uvicorn", "uvicorn.access")]
    with serving(local_paths(tmp_path), access_log=True) as (server, output):
        match = re.search(r"#token=([\w-]+)", output)
        assert match is not None
        token = match[1]
        for logger in loggers:
            logger.addHandler(handler)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{server.port}") as client:
                exchanged = client.post("/api/v1/session", json={"token": token})
                csrf = {CSRF_HEADER: exchanged.json()["csrf_token"]}
                queried = client.get(
                    "/api/v1/session", params={"token": token}, headers=csrf
                )
                client.get("/", params={"token": token})
        finally:
            for logger in loggers:
                logger.removeHandler(handler)
    captured = capfd.readouterr()
    server_records = [
        f"{record.name}: {record.getMessage()}"
        for record in caplog.records
        if not record.name.startswith(("httpx", "httpcore"))
    ]
    logs = "\n".join([*handler.lines, *server_records, captured.out, captured.err])

    assert exchanged.status_code == 200
    assert queried.status_code == 200
    assert "/api/v1/session?token=***" in logs
    assert token not in logs


# Team mode -----------------------------------------------------------------

TEAM_ORIGIN = "https://archiwista.firma.local"


def team_transport(**team: object) -> Transport:
    """Return the transport of team mode at ``TEAM_ORIGIN`` with ``team``."""
    table = {"enabled": True, "origin": TEAM_ORIGIN, **team}
    return Transport.of(AppSettings(team=TeamSettings.model_validate(table)), PORT)


def request_scope(
    peer: str, *, scheme: str = "http", headers: tuple[tuple[str, str], ...] = ()
) -> Scope:
    """Return the ASGI scope of a request from ``peer`` with ``headers``."""
    return {
        "type": "http",
        "scheme": scheme,
        "client": (peer, 50_000),
        "headers": [(name.encode(), value.encode()) for name, value in headers],
    }


@pytest.mark.parametrize(
    ("peer", "forwarded", "client"),
    [
        ("10.0.0.5", ("6.6.6.6",), "10.0.0.5"),
        ("10.0.0.2", (), "10.0.0.2"),
        ("10.0.0.2", ("10.0.0.5",), "10.0.0.5"),
        ("10.0.0.2", ("6.6.6.6, 10.0.0.5",), "10.0.0.5"),
        ("10.0.0.2", ("6.6.6.6", "10.0.0.5"), "10.0.0.5"),
        ("10.0.0.2", ("10.0.0.5, 192.168.7.3",), "10.0.0.5"),
        ("10.0.0.2", ("192.168.7.3",), "192.168.7.3"),
        ("10.0.0.2", ("unknown",), "10.0.0.2"),
        ("::ffff:10.0.0.2", ("10.0.0.5",), "10.0.0.5"),
        ("fd00::7", ("10.0.0.5",), "fd00::7"),
    ],
)
def test_security_client_address_follows_only_trusted_proxies(
    peer: str, forwarded: tuple[str, ...], client: str
) -> None:
    """The client is the right-most forwarded address that is no trusted proxy."""
    transport = team_transport(trusted_proxies=["10.0.0.2", "192.168.7.0/24"])
    headers = tuple(("x-forwarded-for", value) for value in forwarded)

    assert client_address(request_scope(peer, headers=headers), transport) == client


def test_security_client_address_of_local_mode_is_the_peer() -> None:
    """Local mode trusts no proxy, so a forwarded address is never believed."""
    scope = request_scope("127.0.0.1", headers=(("x-forwarded-for", "6.6.6.6"),))

    assert client_address(scope, Transport.of(AppSettings(), PORT)) == "127.0.0.1"


@pytest.mark.parametrize(
    ("peer", "scheme", "proto", "reason"),
    [
        ("10.0.0.2", "http", "https", None),
        ("10.0.0.2", "http", "http", "tls_required"),
        ("10.0.0.2", "http", None, "tls_required"),
        ("10.0.0.5", "http", "https", "tls_required"),
        ("10.0.0.5", "https", None, None),
    ],
)
def test_security_forwarded_https_believed_only_from_a_trusted_peer(
    peer: str, scheme: str, proto: str | None, reason: str | None
) -> None:
    """A request is over TLS by its connection, or by what a trusted proxy says."""
    transport = team_transport(
        tls_cert="/etc/tls/cert.pem",
        tls_key="/etc/tls/key.pem",
        trusted_proxies=["10.0.0.2"],
    )
    headers = () if proto is None else (("x-forwarded-proto", proto),)

    rejection = transport_rejection(
        request_scope(peer, scheme=scheme, headers=headers), transport
    )

    assert (None if rejection is None else rejection.reason) == reason


def test_security_team_host_and_origin_compare_with_the_origin() -> None:
    """Host is the origin's host, with :443 or without; Origin must be the origin."""
    transport = team_transport()
    other_port = team_transport(origin="https://archiwista.firma.local:8443")

    def refused(origin: str) -> bool:
        headers = Headers({"origin": origin, "sec-fetch-site": "same-origin"})
        return origin_rejection("POST", headers, transport.origin) is not None

    assert transport.hosts == {"archiwista.firma.local", "archiwista.firma.local:443"}
    assert other_port.hosts == {"archiwista.firma.local:8443"}
    assert not refused(TEAM_ORIGIN)
    assert refused("http://archiwista.firma.local")
    assert refused("https://archiwista.firma.local:8443")
    assert refused(f"http://127.0.0.1:{PORT}")
    assert refused("null")
