"""Team mode over HTTP: TLS, trusted proxies, Host, HSTS and the cookie (ADR-046).

Every request goes through the real ``SecurityMiddleware`` of an application
built from a configuration file with the table ``[team]``; the test client sets
the scheme and the peer address of each request (``team_client``).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI

from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER, Principal
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    TeamSettings,
)
from archiwista.index.schema import initialize
from archiwista.security import (
    CSRF_HEADER,
    HSTS,
    SESSION_COOKIE,
    TEAM_SESSION_COOKIE,
    issue_one_time_token,
)
from archiwista.state import StateStore
from tests.fixtures.api_session import assert_problem, running_api
from tests.fixtures.local_server import NoSources, local_paths
from tests.fixtures.team_server import team_client

ORIGIN = "https://archiwista.firma.local"
PLAIN = "http://archiwista.firma.local"
PROXY = "10.0.0.2"
PERSON = "10.0.0.5"
# Named only: the transport rules do not open them (serve_main does).
TLS = {
    "tls_cert": "/etc/archiwista/tls/fullchain.pem",
    "tls_key": "/etc/archiwista/tls/privkey.pem",
}
PROXIES = {"trusted_proxies": [PROXY]}


@contextmanager
def team_app(tmp_path: Path, **team: object) -> Iterator[tuple[FastAPI, AppPaths]]:
    """Build the application of a team at ``ORIGIN`` with ``team`` in ``[team]``."""
    paths = local_paths(tmp_path)
    table = {"enabled": True, "origin": ORIGIN, **team}
    settings = AppSettings(team=TeamSettings.model_validate(table))
    ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    state = StateStore(paths.state_file)
    state.add_user("anna", roles=["admin"], actor=LOCAL_OWNER)
    yield (
        create_app(
            port=8443,
            settings=SettingsService(ConfigStore(paths.config_file), NoSources()),
            index_path=paths.index_file,
            state=state,
            registry=NoSources(),
            areas_dir=paths.areas_dir,
        ),
        paths,
    )


def anna_token(paths: AppPaths) -> str:
    """Return a one-time token of a session acting as the account ``anna``."""
    anna = Principal(id="anna", kind="user", roles=frozenset(), groups=frozenset())
    return issue_one_time_token(paths.index_file, "startup", minted_by=anna).token


def test_team_transport_plain_http_is_refused_with_tls_required(
    tmp_path: Path,
) -> None:
    """With TLS in the server, a request that is not over TLS gets nothing."""
    with (
        team_app(tmp_path, **TLS) as (app, _),
        team_client(app, peer=PERSON, base_url=PLAIN) as client,
    ):
        page = client.get("/")
        api = client.get("/api/v1/health")

    assert_problem(page, 403, "forbidden", "tls_required")
    assert_problem(api, 403, "forbidden", "tls_required")
    assert ORIGIN in page.json()["detail"]


def test_team_transport_untrusted_peer_without_tls_in_server_needs_the_proxy(
    tmp_path: Path,
) -> None:
    """Behind a proxy only the proxy may connect, whatever the request says."""
    with (
        team_app(tmp_path, **PROXIES) as (app, _),
        team_client(app, peer=PERSON) as over_https,
        team_client(app, peer=PERSON, base_url=PLAIN) as forwarded,
    ):
        direct = over_https.get("/")
        forged = forwarded.get("/", headers={"x-forwarded-proto": "https"})

    assert_problem(direct, 403, "forbidden", "proxy_required")
    assert_problem(forged, 403, "forbidden", "proxy_required")


def test_team_transport_trusted_proxy_passes_only_when_it_says_https(
    tmp_path: Path,
) -> None:
    """The last X-Forwarded-Proto of a trusted proxy decides; nothing else does."""
    with (
        team_app(tmp_path, **PROXIES) as (app, _),
        team_client(app, peer=PROXY, base_url=PLAIN) as proxy,
    ):
        https = proxy.get("/", headers={"x-forwarded-proto": "https"})
        chained = proxy.get("/", headers={"x-forwarded-proto": "http, https"})
        downgraded = proxy.get("/", headers={"x-forwarded-proto": "https, http"})
        missing = proxy.get("/")

    assert https.status_code == 200
    assert chained.status_code == 200
    assert_problem(downgraded, 403, "forbidden", "tls_required")
    assert_problem(missing, 403, "forbidden", "tls_required")


def test_team_transport_every_answer_carries_hsts(tmp_path: Path) -> None:
    """Pages, problems of the API and refusals of the transport get HSTS."""
    with (
        team_app(tmp_path, **TLS) as (app, _),
        team_client(app, peer=PERSON) as client,
        team_client(app, peer=PERSON, base_url=PLAIN) as plain,
    ):
        page = client.get("/")
        problem = client.get("/api/v1/health")
        refused = plain.get("/")

    assert page.status_code == 200
    assert_problem(problem, 401, "unauthorized", "session_required")
    for response in (page, problem, refused):
        assert response.headers["strict-transport-security"] == HSTS


@pytest.mark.parametrize(
    "base_url",
    [
        "https://evil.example",
        "https://127.0.0.1:8443",
        "https://localhost:8443",
        "https://archiwista.firma.local:8443",
    ],
)
def test_team_transport_host_other_than_the_origin_is_refused(
    tmp_path: Path, base_url: str
) -> None:
    """Only the origin's host is answered: DNS rebinding and a local Host fail."""
    with (
        team_app(tmp_path, **TLS) as (app, _),
        team_client(app, peer=PERSON, base_url=base_url) as client,
    ):
        response = client.get("/")

    assert_problem(response, 403, "forbidden", "invalid_host")
    assert ORIGIN in response.json()["detail"]


def test_team_transport_serves_no_api_docs(tmp_path: Path) -> None:
    """Swagger UI is a feature of local mode; the OpenAPI document needs a session."""
    with (
        team_app(tmp_path, **TLS) as (app, _),
        team_client(app, peer=PERSON) as client,
    ):
        docs = client.get("/api/docs")
        files = client.get("/api/docs/swagger-ui.css")
        document = client.get("/api/v1/openapi.json")

    assert docs.status_code == 404
    assert files.status_code == 404
    assert_problem(document, 401, "unauthorized", "session_required")


def test_team_transport_session_cookie_is_host_prefixed_and_secure(
    tmp_path: Path,
) -> None:
    """The session lives in __Host-archiwista_session; the local name opens nothing."""
    with (
        team_app(tmp_path, **TLS) as (app, paths),
        team_client(app, peer=PERSON) as client,
    ):
        exchanged = client.post("/api/v1/session", json={"token": anna_token(paths)})
        session_id = exchanged.cookies[TEAM_SESSION_COOKIE]
        client.cookies.clear()
        csrf = {CSRF_HEADER: exchanged.json()["csrf_token"]}
        team = client.get(
            "/api/v1/session",
            headers={**csrf, "cookie": f"{TEAM_SESSION_COOKIE}={session_id}"},
        )
        local = client.get(
            "/api/v1/session",
            headers={**csrf, "cookie": f"{SESSION_COOKIE}={session_id}"},
        )
        ended = client.delete(
            "/api/v1/session",
            headers={**csrf, "cookie": f"{TEAM_SESSION_COOKIE}={session_id}"},
        )

    cookie = exchanged.headers["set-cookie"]
    assert cookie.startswith(f"{TEAM_SESSION_COOKIE}=")
    assert {"HttpOnly", "Path=/", "SameSite=strict", "Secure"} <= {
        part.strip() for part in cookie.split(";")
    }
    assert "Domain" not in cookie
    assert team.status_code == 200 and team.json()["actor"] == "anna"
    assert_problem(local, 401, "unauthorized", "session_required")
    assert ended.status_code == 204
    removed = ended.headers["set-cookie"]
    assert removed.startswith(f'{TEAM_SESSION_COOKIE}=""') or removed.startswith(
        f"{TEAM_SESSION_COOKIE}=;"
    )
    assert "Secure" in removed


def test_team_transport_local_mode_is_unchanged_and_without_hsts(
    tmp_path: Path,
) -> None:
    """Local mode keeps its Host rule, cookie name and docs, and sends no HSTS."""
    with running_api(local_paths(tmp_path)) as api:
        page = api.client.get("/")
        docs = api.client.get("/api/docs")
        exchanged = api.client.post(
            "/api/v1/session",
            json={
                "token": issue_one_time_token(
                    api.paths.index_file, "startup", minted_by=LOCAL_OWNER
                ).token
            },
        )
        api.client.cookies.clear()

    assert page.status_code == 200 and docs.status_code == 200
    assert "strict-transport-security" not in page.headers
    cookie = exchanged.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "Secure" not in cookie
