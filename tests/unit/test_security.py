"""Local-mode access protection: Host, tokens, session, CSRF, paths (SPEC 10.1)."""

import hashlib
import logging
import os
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

from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER, LOCAL_ROLES, Principal
from archiwista.config import AppSettings, BasemapConfig, ConfigStore, SettingsService
from archiwista.errors import PathOutsideRootError
from archiwista.index.schema import initialize
from archiwista.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    TOKEN_TTL,
    SessionStore,
    TokenKind,
    csp_header,
    current_principal,
    issue_one_time_token,
    redeem_one_time_token,
    resolve_indexed_path,
)
from archiwista.state import StateStore
from tests.fixtures.local_server import NoSources, local_paths, serving

PORT = 8090
BASE_URL = f"http://127.0.0.1:{PORT}"
OSM = "https://tile.openstreetmap.org"
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
    """Return a Cookie header with the session and, optionally, CSRF cookie."""
    value = f"{SESSION_COOKIE}={session_id}"
    if csrf is not None:
        value += f"; {CSRF_COOKIE}={csrf}"
    return {"cookie": value}


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


def assert_problem(response: httpx.Response, status: int, code: str) -> None:
    """Check an RFC 9457 problem with a Polish detail."""
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["detail"]


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

    assert_problem(page, 400, "invalid_host")
    assert_problem(data, 400, "invalid_host")


@pytest.mark.parametrize("host", ["127.0.0.1:8090", "localhost:8090"])
def test_security_loopback_host_served(api: Api, host: str) -> None:
    """Both loopback names of the server's own port are answered."""
    response = api.client.get("/", headers={"host": host})

    assert response.status_code == 200


# One-time tokens and sessions ---------------------------------------------


def test_security_token_exchange_starts_session(api: Api) -> None:
    """The exchange sets an HttpOnly session cookie and a separate CSRF token."""
    issued = issue_one_time_token(api.index_path, "startup", minted_by=LOCAL_OWNER)

    response = api.client.post("/api/v1/session", json={"token": issued.token})

    assert response.status_code == 200
    body = response.json()
    assert body["actor"] == "local"
    assert response.headers["cache-control"] == "no-store"
    set_cookies = {
        header.split("=", 1)[0]: header.lower()
        for header in response.headers.get_list("set-cookie")
    }
    assert "httponly" in set_cookies[SESSION_COOKIE]
    assert "httponly" not in set_cookies[CSRF_COOKIE]
    for header in set_cookies.values():
        assert "samesite=strict" in header
        assert "path=/" in header
    assert response.cookies[CSRF_COOKIE] == body["csrf_token"]
    assert response.cookies[SESSION_COOKIE] not in (issued.token, body["csrf_token"])
    state = api.client.get("/api/v1/session")
    assert state.status_code == 200
    assert state.json()["csrf_token"] == body["csrf_token"]
    assert state.headers["cache-control"] == "no-store"


def test_security_token_used_twice_rejected(api: Api) -> None:
    """A one-time token starts one session only."""
    issued = issue_one_time_token(api.index_path, "startup", minted_by=LOCAL_OWNER)
    first = api.client.post("/api/v1/session", json={"token": issued.token})
    api.client.cookies.clear()

    second = api.client.post("/api/v1/session", json={"token": issued.token})

    assert first.status_code == 200
    assert_problem(second, 401, "session_required")
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


def test_security_tokens_carry_minting_principal(tmp_path: Path) -> None:
    """A startup session is its minter; an agent session acts for the minter."""
    index_path = tmp_path / "index.sqlite"
    initialize(index_path)
    minter = Principal(
        id="kasia",
        kind="user",
        roles=frozenset({"reader"}),
        groups=frozenset({"gis", "hydro"}),
    )
    startup = issue_one_time_token(index_path, "startup", minted_by=minter)
    agent = issue_one_time_token(index_path, "agent", minted_by=minter)

    own = redeem_one_time_token(index_path, startup.token)
    delegated = redeem_one_time_token(index_path, agent.token)

    assert own == minter
    assert delegated == Principal(
        id="kasia", kind="agent", roles=minter.roles, groups=minter.groups
    )


def test_security_current_principal_owner_then_agent(api: Api) -> None:
    """The owner's session acts as ``local``; a token it issues starts an agent."""
    session_id, csrf = api.login()
    owner = api.client.get("/api/v1/principal", headers=cookies(session_id))
    issued = api.client.post(
        "/api/v1/session/tokens",
        headers={**cookies(session_id, csrf), CSRF_HEADER: csrf},
    )
    exchanged = api.client.post(
        "/api/v1/session", json={"token": issued.json()["token"]}
    )
    agent_id = exchanged.cookies[SESSION_COOKIE]
    api.client.cookies.clear()

    agent = api.client.get("/api/v1/principal", headers=cookies(agent_id))

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

    assert_problem(response, 401, "session_required")


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

    assert_problem(missing, 401, "session_required")
    assert_problem(unknown, 401, "session_required")


def test_security_session_ends_after_idle_timeout(api: Api) -> None:
    """Each request extends the session; a day without requests ends it."""
    session_id, _ = api.login()
    api.clock.now = START + timedelta(hours=23)
    kept = api.client.get("/api/v1/session", headers=cookies(session_id))

    api.clock.now = START + timedelta(hours=23 + 24)
    ended = api.client.get("/api/v1/session", headers=cookies(session_id))

    assert kept.status_code == 200
    assert kept.json()["expires_at"] == "2026-10-20T11:00:00Z"
    assert_problem(ended, 401, "session_required")


# CSRF, Origin and Sec-Fetch-Site ------------------------------------------


@pytest.mark.parametrize(
    ("header", "cookie"),
    [(None, "valid"), ("wrong", "valid"), ("valid", None), ("valid", "wrong")],
)
def test_security_state_change_without_csrf_token_rejected(
    api: Api, header: str | None, cookie: str | None
) -> None:
    """The CSRF header and cookie must both carry the session's token."""
    session_id, csrf = api.login()
    headers = cookies(session_id, None if cookie is None else csrf)
    if cookie == "wrong":
        headers = cookies(session_id, "wrong")
    if header is not None:
        headers[CSRF_HEADER] = csrf if header == "valid" else "wrong"

    response = api.client.post("/api/v1/session/tokens", headers=headers)

    assert_problem(response, 403, "csrf_rejected")


def test_security_client_without_origin_passes_with_session_and_csrf(
    api: Api,
) -> None:
    """A script without Origin and Sec-Fetch-* changes state with session+CSRF."""
    session_id, csrf = api.login()
    headers = {**cookies(session_id, csrf), CSRF_HEADER: csrf}

    response = api.client.post("/api/v1/session/tokens", headers=headers)

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

    assert_problem(read, 403, "csrf_rejected")
    assert_problem(exchange, 403, "csrf_rejected")
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

    assert_problem(page, 403, "csrf_rejected")
    assert_problem(data, 403, "csrf_rejected")


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
    headers = {**cookies(session_id, csrf), CSRF_HEADER: csrf, "sec-fetch-site": site}
    if origin is not None:
        headers["origin"] = origin

    response = api.client.post("/api/v1/session/tokens", headers=headers)

    assert response.status_code == status


def test_security_navigation_with_fetch_site_none_passes(api: Api) -> None:
    """An address typed or opened from the terminal (``none``) is served."""
    session_id, _ = api.login()
    navigation = {"sec-fetch-site": "none", "sec-fetch-mode": "navigate"}

    page = api.client.get("/", headers=navigation)
    data = api.client.get(
        "/api/v1/session", headers={**navigation, **cookies(session_id)}
    )

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert data.status_code == 200


def test_security_no_cors_headers(api: Api) -> None:
    """Neither a preflight nor a same-origin request gets CORS headers."""
    session_id, _ = api.login()

    preflight = api.client.options(
        "/api/v1/session",
        headers={
            "origin": BASE_URL,
            "access-control-request-method": "POST",
            "access-control-request-headers": CSRF_HEADER,
        },
    )
    read = api.client.get(
        "/api/v1/session", headers={"origin": BASE_URL, **cookies(session_id)}
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


def test_security_interface_files_stay_in_web_dir(api: Api, tmp_path: Path) -> None:
    """Neither ``..`` nor a symbolic link serves a file outside the interface."""
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", "utf-8")
    (tmp_path / "web" / "link.txt").symlink_to(secret)

    linked = api.client.get("/static/link.txt")
    climbed = api.client.get("/static/%2E%2E/secret.txt")

    assert linked.status_code == 404
    assert climbed.status_code == 404
    assert "secret" not in linked.text + climbed.text


def test_security_csp_lists_basemaps_only_online() -> None:
    """Basemap origins are allowed for images and fetches, and only online."""
    basemaps = (
        BasemapConfig(name="OSM", url=f"{OSM}/{{z}}/{{x}}/{{y}}.png"),
        BasemapConfig(name="OSM 2", url=f"{OSM}/a/{{z}}/{{x}}/{{y}}.png"),
        BasemapConfig(
            name="Orto", kind="wms", url="https://mapy.geoportal.gov.pl:443/wms"
        ),
    )
    online = AppSettings(basemaps=basemaps)

    directives = dict(item.split(" ", 1) for item in csp_header(online).split("; "))
    offline = csp_header(online.model_copy(update={"offline": True}))

    sources = f"{OSM} https://mapy.geoportal.gov.pl:443"
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

    assert OSM in before.headers["content-security-policy"]
    assert OSM not in after.headers["content-security-policy"]


# Paths ---------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """Create a store root with one version file and a file outside it."""
    root = tmp_path / "store"
    version = root / "nmt" / "versions" / "a_2023_f3015407"
    version.mkdir(parents=True)
    (version / "a.asc").write_text("data", "utf-8")
    (tmp_path / "outside.txt").write_text("outside", "utf-8")
    return root


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.txt",
        "nmt/../../outside.txt",
        "nmt\\..\\..\\outside.txt",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "nmt/a\x00.asc",
        "",
    ],
)
def test_security_resolve_indexed_path_rejects_escape(
    store: Path, relative: str
) -> None:
    """Absolute paths, ``..`` and NUL never reach the file system."""
    with pytest.raises(PathOutsideRootError):
        resolve_indexed_path(store, relative)


def test_security_resolve_indexed_path_rejects_symlink_leaving_root(
    store: Path, tmp_path: Path
) -> None:
    """A link inside the store that points outside it is refused."""
    os.symlink(tmp_path / "outside.txt", store / "nmt" / "a.asc")
    os.symlink(tmp_path, store / "nmt" / "parent")

    with pytest.raises(PathOutsideRootError):
        resolve_indexed_path(store, "nmt/a.asc")
    with pytest.raises(PathOutsideRootError):
        resolve_indexed_path(store, "nmt/parent/outside.txt")


def test_security_resolve_indexed_path_follows_link_inside_root(store: Path) -> None:
    """A standard path linked to a version resolves to the version's file."""
    target = store / "nmt" / "versions" / "a_2023_f3015407" / "a.asc"
    os.symlink(target, store / "nmt" / "a.asc")

    resolved = resolve_indexed_path(store, "nmt/a.asc")

    assert resolved == target.resolve()


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
                queried = client.get("/api/v1/session", params={"token": token})
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
