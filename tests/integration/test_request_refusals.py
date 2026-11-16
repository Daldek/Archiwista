"""Security refusals are audited without credentials and without log flooding."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from archiwista.api.errors import DenialLog
from archiwista.auth import LOCAL_OWNER
from archiwista.security import TEAM_SESSION_COOKIE
from tests.fixtures.api_session import running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import log_entries
from tests.fixtures.team_server import save_team


def test_request_refusals_are_throttled_and_do_not_store_secrets(
    tmp_path: Path,
) -> None:
    """Record distinct refusals once and never copy request secrets."""
    paths = local_paths(tmp_path)
    save_team(paths)
    with running_api(paths) as api:
        for _ in range(2):
            response = api.client.get(
                "/api/v1/settings?token=secret-query",
                headers={"Origin": "https://secret-origin.invalid"},
            )
            assert response.status_code == 403
        api.client.cookies.set(TEAM_SESSION_COOKIE, "secret-cookie")
        assert api.client.get("/api/v1/settings").status_code == 401
        for _ in range(2):
            assert (
                api.client.post(
                    "/api/v1/session", json={"token": "secret-token"}
                ).status_code
                == 401
            )
        assert api.client.post("/api/v1/session/proxy").status_code == 401
        entries = log_entries(api.state)
    assert [(entry.action, (entry.details or {})["reason"]) for entry in entries] == [
        ("request.refused", "csrf_rejected"),
        ("request.refused", "session_required"),
        ("session.login_failed", "token_rejected"),
        ("session.login_failed", "no_proxy_user"),
    ]
    assert "secret-" not in repr(entries)


def test_refusal_limit_expires_and_separates_clients_and_reasons(
    tmp_path: Path,
) -> None:
    """A minute boundary admits a new entry without merging clients or reasons."""
    paths = local_paths(tmp_path)
    with running_api(paths) as api:
        now = datetime(2026, 10, 28, tzinfo=UTC)
        denials = DenialLog(api.state, clock=lambda: now)
        for client, reason in [
            ("a", "csrf_rejected"),
            ("b", "csrf_rejected"),
            ("a", "invalid_host"),
        ]:
            assert denials.refused(None, reason, route="GET /api/*", client=client)
            assert not denials.refused(None, reason, route="POST /api/*", client=client)
        now += timedelta(minutes=1)
        assert denials.refused(None, "csrf_rejected", route="GET /api/*", client="a")
        entries = [e for e in log_entries(api.state) if e.action == "request.refused"]
    assert [(e.client, (e.details or {})["reason"]) for e in entries] == [
        ("a", "csrf_rejected"),
        ("b", "csrf_rejected"),
        ("a", "invalid_host"),
        ("a", "csrf_rejected"),
    ]


@pytest.mark.parametrize(
    ("team", "url", "headers", "reason"),
    [
        (
            {},
            "https://archiwista.firma.local/api/v1/health",
            {"Host": "foreign.invalid"},
            "invalid_host",
        ),
        ({}, "http://archiwista.firma.local/api/v1/health", {}, "tls_required"),
        (
            {"tls_cert": None, "tls_key": None, "trusted_proxies": ["10.0.0.2"]},
            "https://archiwista.firma.local/api/v1/health",
            {},
            "proxy_required",
        ),
    ],
)
def test_transport_refusals_are_audited(
    tmp_path: Path,
    team: dict[str, object],
    url: str,
    headers: dict[str, str],
    reason: str,
) -> None:
    """Transport and Host checks log refusals even before routing."""
    paths = local_paths(tmp_path)
    save_team(paths, **team)
    with running_api(paths) as api:
        for _ in range(2):
            assert api.client.get(url, headers=headers).status_code == 403
        entries = log_entries(api.state)
    assert [(e.action, (e.details or {})["reason"]) for e in entries] == [
        ("request.refused", reason)
    ]


def test_session_csrf_refusal_names_actor_and_concurrent_failures_do_not_flood(
    tmp_path: Path,
) -> None:
    """Keep the known actor and admit only one concurrent failure per key."""
    with running_api(local_paths(tmp_path)) as api:
        caller = api.session(LOCAL_OWNER)
        assert caller.request("GET", "/settings", csrf=False).status_code == 403
        denials = DenialLog(api.state)

        def refuse(_: int) -> bool:
            return denials.login_failed(
                method="token", reason="token_rejected", client="a"
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(refuse, range(20))) == 1
        entries = log_entries(api.state)
    refused = [e for e in entries if e.action == "request.refused"]
    assert [(e.actor, (e.details or {})["reason"]) for e in refused] == [
        ("local", "csrf_rejected")
    ]
    assert [
        (e.client, (e.details or {})["reason"])
        for e in entries
        if e.action == "session.login_failed"
    ] == [("a", "token_rejected")]
