"""Signing in through the company's reverse proxy (ADR-046, plan v0.4 C6).

A team server with TLS in the server trusts the proxy at ``PROXY_PEER``, which
names the person in ``X-Remote-User`` and the person's computer in
``X-Forwarded-For``; ``OTHER_PEER`` reaches the server directly. Every request
goes through the real ``SecurityMiddleware``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, ConfigStore, TeamSettings
from archiwista.security import TEAM_SESSION_COOKIE
from tests.fixtures.api_session import (
    BASE_URL,
    Api,
    Caller,
    assert_problem,
    running_api,
)
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import last_entry, log_entries
from tests.fixtures.team_server import PEER_PORT, PERSON_PEER, save_team, team_client

HEADER = "X-Remote-User"
PROXY_PEER = "10.0.0.2"
OTHER_PEER = "10.0.0.9"
PROXY = "/api/v1/session/proxy"
METHODS = "/api/v1/session/methods"
PERSON = "kasia"


@contextmanager
def proxied(tmp_path: Path, **team: object) -> Iterator[Api]:
    """Serve team mode behind the proxy at ``PROXY_PEER``; kasia has an account."""
    paths = local_paths(tmp_path)
    save_team(paths, trusted_proxies=[PROXY_PEER], proxy_user_header=HEADER, **team)
    with running_api(paths) as api:
        api.state.add_user(PERSON, name="Kasia Kowalska", actor=LOCAL_OWNER)
        yield api


def app_of(api: Api) -> FastAPI:
    """Return the application a running API serves."""
    app = api.client.app
    assert isinstance(app, FastAPI)
    return app


def through_proxy(api: Api, person: str) -> TestClient:
    """Return a client whose requests come through the proxy, naming ``person``."""
    client = team_client(app_of(api), peer=PROXY_PEER)
    client.headers[HEADER] = person
    client.headers["x-forwarded-for"] = PERSON_PEER
    return client


def signed_in(client: TestClient) -> Caller:
    """Sign in through the proxy and return the session."""
    answer = client.post(PROXY)
    assert answer.status_code == 200, answer.text
    client.cookies.clear()
    session_id = answer.cookies[TEAM_SESSION_COOKIE]
    return Caller(client, session_id, answer.json()["csrf_token"], TEAM_SESSION_COOKIE)


def test_a_trusted_proxy_signs_in_the_person_it_names(tmp_path: Path) -> None:
    """The header of a trusted proxy names an account: a session as that person."""
    with proxied(tmp_path) as api:
        proxy = through_proxy(api, "KASIA")
        logged = last_entry(api.state)

        # Act
        methods = proxy.get(METHODS)
        answer = proxy.post(PROXY)
        proxy.cookies.clear()
        session = Caller(
            proxy,
            answer.cookies[TEAM_SESSION_COOKIE],
            answer.json()["csrf_token"],
            TEAM_SESSION_COOKIE,
        )
        state = session.request("GET", "/session")
        sessions = session.request("GET", "/sessions")
        entries = log_entries(api.state, after=logged)

    # Assert
    assert methods.json() == {"mode": "team", "password": True, "proxy": True}
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["actor"], body["name"], body["kind"], body["method"]) == (
        PERSON,
        "Kasia Kowalska",
        "user",
        "proxy",
    )
    assert body["password_change_required"] is False
    assert state.status_code == 200, state.text
    (item,) = sessions.json()["items"]
    assert (item["method"], item["client"], item["current"]) == (
        "proxy",
        PERSON_PEER,
        True,
    )
    assert [
        (entry.action, entry.actor, entry.target, entry.details, entry.client)
        for entry in entries
    ] == [("session.login", PERSON, PERSON, {"method": "proxy"}, PERSON_PEER)]


def test_the_header_from_another_computer_is_ignored_and_logged(
    tmp_path: Path,
) -> None:
    """Only a trusted proxy names people; another peer's header is logged once."""
    with proxied(tmp_path) as api:
        stranger = team_client(app_of(api), peer=OTHER_PEER)
        stranger.headers[HEADER] = PERSON
        logged = last_entry(api.state)

        # Act
        methods = stranger.get(METHODS)
        refused = stranger.post(PROXY)
        again = stranger.post(PROXY)
        entries = log_entries(api.state, after=logged)

    # Assert
    assert methods.json()["proxy"] is False
    for answer in (refused, again):
        assert_problem(answer, 401, "unauthorized", "login_failed")
        assert "set-cookie" not in answer.headers
    assert [
        (entry.action, entry.actor_kind, entry.target, entry.outcome, entry.client)
        for entry in entries
    ] == [
        ("session.proxy_header_ignored", "anonymous", OTHER_PEER, "denied", OTHER_PEER)
    ]


def test_a_proxy_session_ends_unless_the_proxy_names_the_same_person(
    tmp_path: Path,
) -> None:
    """Another name mid-session, or a request around the proxy, ends the session."""
    with proxied(tmp_path) as api:
        api.state.add_user("marek", actor=LOCAL_OWNER)
        proxy = through_proxy(api, PERSON)
        first, second = signed_in(proxy), signed_in(proxy)
        around = team_client(app_of(api), peer=OTHER_PEER)
        direct = Caller(around, second.session_id, second.csrf, TEAM_SESSION_COOKIE)

        # Act
        before = first.request("GET", "/session")
        proxy.headers[HEADER] = "marek"
        switched = first.request("GET", "/session")
        proxy.headers[HEADER] = PERSON
        after = first.request("GET", "/session")
        bypassed = direct.request("GET", "/session")
        after_bypass = second.request("GET", "/session")

    # Assert
    assert before.status_code == 200, before.text
    for answer in (switched, after, bypassed, after_bypass):
        assert_problem(answer, 401, "unauthorized", "session_required")


def test_an_unknown_or_disabled_account_is_refused_alike(tmp_path: Path) -> None:
    """Both answer 401 login_failed with one text; the log keeps the reasons."""
    with proxied(tmp_path) as api:
        api.state.add_user("ola", actor=LOCAL_OWNER)
        api.state.update_user("ola", disabled=True, actor=LOCAL_OWNER)
        logged = last_entry(api.state)

        # Act
        unknown = through_proxy(api, "nowy.pracownik").post(PROXY)
        disabled = through_proxy(api, "ola").post(PROXY)
        entries = log_entries(api.state, after=logged)
        created = api.state.user("nowy.pracownik")

    # Assert
    for answer in (unknown, disabled):
        assert_problem(answer, 401, "unauthorized", "login_failed")
        assert "set-cookie" not in answer.headers
    assert unknown.json()["detail"] == disabled.json()["detail"]
    assert [
        (entry.action, entry.actor, entry.target, entry.outcome, entry.client)
        for entry in entries
    ] == [
        ("session.login_failed", "-", "nowy.pracownik", "failed", PERSON_PEER),
        ("session.login_failed", "-", "ola", "failed", PERSON_PEER),
    ]
    assert [entry.details for entry in entries] == [
        {"reason": "unknown_proxy_user", "method": "proxy"},
        {"reason": "disabled", "method": "proxy"},
    ]
    assert created is None


def test_proxy_autocreate_makes_an_account_without_roles(tmp_path: Path) -> None:
    """A missing account becomes one without roles; a name that is no id does not."""
    with proxied(tmp_path, proxy_autocreate=True) as api:
        logged = last_entry(api.state)

        # Act
        answer = through_proxy(api, "Nowy.Pracownik").post(PROXY)
        invalid = through_proxy(api, "nowy@firma.local").post(PROXY)
        entries = log_entries(api.state, after=logged)
        created = api.state.user("nowy.pracownik")

    # Assert
    assert answer.status_code == 200, answer.text
    assert (answer.json()["actor"], answer.json()["roles"]) == ("nowy.pracownik", [])
    assert created is not None
    assert (created.roles, created.disabled) == ((), False)
    assert_problem(invalid, 401, "unauthorized", "login_failed")
    assert [
        (entry.action, entry.actor, entry.target, entry.client) for entry in entries
    ] == [
        ("user.add", "-", "nowy.pracownik", PERSON_PEER),
        ("session.login", "nowy.pracownik", "nowy.pracownik", PERSON_PEER),
        ("session.login_failed", "-", "nowy@firma.local", PERSON_PEER),
    ]
    assert entries[-1].details == {"reason": "unknown_proxy_user", "method": "proxy"}


def test_a_proxy_session_changes_no_password(tmp_path: Path) -> None:
    """The proxy's people change their password there: 409 proxy_session."""
    with proxied(tmp_path) as api:
        session = signed_in(through_proxy(api, PERSON))
        body = {
            "current_password": "jakiekolwiek-haslo",
            "new_password": "most-na-Sanie-w-Przemyslu",
        }

        # Act
        refused = session.request("PUT", "/session/password", json=body)
        still = session.request("GET", "/session")

    # Assert
    assert_problem(refused, 409, "conflict", "proxy_session")
    assert still.status_code == 200, still.text


def test_the_proxy_header_never_matters_in_local_mode(tmp_path: Path) -> None:
    """A local server neither signs in through a proxy nor logs its header."""
    # Arrange
    paths = local_paths(tmp_path)
    team = TeamSettings.model_validate(
        {"trusted_proxies": ["127.0.0.1"], "proxy_user_header": HEADER}
    )
    ConfigStore(paths.config_file).save(AppSettings(team=team))
    with running_api(paths) as api:
        api.state.add_user(PERSON, actor=LOCAL_OWNER)
        local = TestClient(
            app_of(api), base_url=BASE_URL, client=("127.0.0.1", PEER_PORT)
        )
        local.headers[HEADER] = PERSON
        logged = last_entry(api.state)

        # Act
        methods = local.get(METHODS)
        refused = local.post(PROXY)
        entries = log_entries(api.state, after=logged)

    # Assert
    assert methods.json() == {"mode": "local", "password": False, "proxy": False}
    assert_problem(refused, 409, "conflict", "local_mode")
    assert entries == []
