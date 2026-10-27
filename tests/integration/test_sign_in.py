"""Signing in over HTTP in team mode: sessions, the password, the wait (ADR-046).

A team server in a test client over https (``running_api`` with ``[team]``):
people sign in with real Argon2id at the lowest cost, counted by a spy of
``HASHER.verify``; the cookie is ``__Host-archiwista_session``; the wait after
failures follows a test clock. Requests come from ``PERSON_PEER`` unless a
test names another computer of the network.
"""

import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import argon2
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archiwista.auth import LOCAL_OWNER, passwords
from archiwista.auth.passwords import HASH_SLOTS, TEMPORARY_TTL
from archiwista.auth.throttle import FREE_FAILURES, LoginThrottle
from archiwista.cli import main
from archiwista.config import AppPaths
from archiwista.security import TEAM_SESSION_COOKIE
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import last_entry, log_entries
from tests.fixtures.team_server import PERSON_PEER, save_team, team_client

ADMIN = "anna"
PERSON = "kasia"
ADMIN_PASSWORD = "kajak-po-Rabie-o-swicie"
PERSON_PASSWORD = "wiosla-w-szuwarach-Wisly"
NEW_PASSWORD = "most-na-Sanie-w-Przemyslu"
WRONG = "to-nie-jest-to-haslo"
# Another computer of the team's network.
OTHER_PEER = "10.0.0.9"
LOGIN = "/api/v1/session/login"


class Clock:
    """Settable time source of the wait after failures."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        """Return the current test time."""
        return self.now


class CountingHasher(argon2.PasswordHasher):
    """Argon2id at the lowest cost that counts verifications and their overlap."""

    def __init__(self) -> None:
        super().__init__(time_cost=1, memory_cost=8, parallelism=1)
        self.verified = 0
        self.most_at_once = 0
        self.pause_s = 0.0
        self._running = 0
        self._lock = threading.Lock()

    def verify(self, hash: str | bytes, password: str | bytes) -> Literal[True]:
        """Verify as argon2-cffi does, counting the call and the calls at once."""
        with self._lock:
            self.verified += 1
            self._running += 1
            self.most_at_once = max(self.most_at_once, self._running)
        try:
            time.sleep(self.pause_s)
            return super().verify(hash, password)
        finally:
            with self._lock:
                self._running -= 1


@dataclass
class Team:
    """A team server under a test client, its wait's clock and the hash spy."""

    api: Api
    clock: Clock
    hasher: CountingHasher

    @property
    def client(self) -> TestClient:
        """The client of a person at ``PERSON_PEER``."""
        return self.api.client

    def other_client(self) -> TestClient:
        """Return a client of the same server on another computer."""
        app = self.api.client.app
        assert isinstance(app, FastAPI)
        return team_client(app, peer=OTHER_PEER)


def team_paths(tmp_path: Path) -> AppPaths:
    """Return the paths a fresh installation uses under ``tmp_path`` (XDG)."""
    return AppPaths(
        config_file=tmp_path / "config" / "archiwista" / "config.toml",
        data_dir=tmp_path / "data" / "archiwista",
    )


@pytest.fixture
def team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Team]:
    """Serve team mode: anna, an administrator, and kasia, both with passwords."""
    hasher = CountingHasher()
    monkeypatch.setattr(passwords, "HASHER", hasher)
    paths = team_paths(tmp_path)
    save_team(paths)
    clock = Clock()
    with running_api(paths, login_throttle=LoginThrottle(clock=clock)) as api:
        state = api.state
        state.add_user(ADMIN, name="Anna Admin", roles=["admin"], actor=LOCAL_OWNER)
        state.add_user(PERSON, name="Kasia Kowalska", actor=LOCAL_OWNER)
        for account, password in ((ADMIN, ADMIN_PASSWORD), (PERSON, PERSON_PASSWORD)):
            passwords.set_password(
                state, account, password, temporary=False, actor=LOCAL_OWNER
            )
        yield Team(api, clock, hasher)


def sign_in(
    client: TestClient,
    account: str,
    password: str,
    *,
    cookie: str | None = None,
    user_agent: str | None = None,
) -> httpx.Response:
    """Send ``POST /session/login``; the client keeps no cookie afterwards."""
    headers = {} if cookie is None else {"cookie": f"{TEAM_SESSION_COOKIE}={cookie}"}
    if user_agent is not None:
        headers["user-agent"] = user_agent
    body = {"account": account, "password": password}
    response: httpx.Response = client.post(LOGIN, json=body, headers=headers)
    client.cookies.clear()
    return response


def caller(client: TestClient, answer: httpx.Response) -> Caller:
    """Return the session a sign-in or a password change answered."""
    assert answer.status_code == 200, answer.text
    session_id = answer.cookies[TEAM_SESSION_COOKIE]
    return Caller(client, session_id, answer.json()["csrf_token"], TEAM_SESSION_COOKIE)


def signed_in(client: TestClient, account: str, password: str) -> Caller:
    """Sign in and return the session."""
    return caller(client, sign_in(client, account, password))


def agent_of(person: Caller) -> Caller:
    """Open an agent's session with a token the person's session issues."""
    issued = person.request("POST", "/session/tokens")
    assert issued.status_code == 201, issued.text
    client = person.client
    exchanged = client.post("/api/v1/session", json={"token": issued.json()["token"]})
    client.cookies.clear()
    return caller(client, exchanged)


def change(session: Caller, current: str, new: str) -> httpx.Response:
    """Send ``PUT /session/password``; the client keeps no cookie afterwards."""
    body = {"current_password": current, "new_password": new}
    response = session.request("PUT", "/session/password", json=body)
    session.client.cookies.clear()
    return response


def test_sign_in_answers_a_session_with_the_team_cookie(team: Team) -> None:
    """A correct password starts a session: a CSRF token and a __Host- cookie."""
    # Act
    response = sign_in(team.client, f"  {PERSON.upper()} ", PERSON_PASSWORD)
    session = caller(team.client, response)
    state = session.request("GET", "/session")
    methods = team.client.get("/api/v1/session/methods")

    # Assert
    body = response.json()
    (cookie,) = response.headers.get_list("set-cookie")
    name, _, rest = cookie.partition("=")
    attributes = {part.strip().lower() for part in rest.split(";")[1:]}
    assert name == TEAM_SESSION_COOKIE
    assert {"secure", "httponly", "samesite=strict", "path=/"} <= attributes
    assert not any(part.startswith("domain") for part in attributes)
    assert response.headers["cache-control"] == "no-store"
    assert (body["actor"], body["name"], body["kind"], body["method"]) == (
        PERSON,
        "Kasia Kowalska",
        "user",
        "password",
    )
    assert (body["team"], body["password_change_required"]) == (True, False)
    assert session.session_id not in (body["csrf_token"], body["label"])
    assert state.status_code == 200, state.text
    assert state.json() == {key: body[key] for key in state.json()}
    assert methods.json() == {"mode": "team", "password": True, "proxy": False}
    assert team.hasher.verified == 1


def test_every_refused_account_answers_alike_after_one_verification(
    team: Team,
) -> None:
    """An unknown account, a wrong password, a disabled account, no password."""
    # Arrange
    state = team.api.state
    state.add_user("jan", actor=LOCAL_OWNER)
    state.add_user("ola", actor=LOCAL_OWNER)
    passwords.set_password(
        state, "ola", NEW_PASSWORD, temporary=False, actor=LOCAL_OWNER
    )
    state.update_user("ola", disabled=True, actor=LOCAL_OWNER)
    attempts = [
        ("nikt", PERSON_PASSWORD),
        (PERSON, WRONG),
        ("ola", NEW_PASSWORD),
        ("jan", PERSON_PASSWORD),
    ]
    logged = last_entry(state)

    # Act
    answers, verified = [], []
    for account, password in attempts:
        before = team.hasher.verified
        answers.append(sign_in(team.client, account, password))
        verified.append(team.hasher.verified - before)

    # Assert
    for answer in answers:
        assert_problem(answer, 401, "unauthorized", "login_failed")
        assert "set-cookie" not in answer.headers
    assert len({answer.json()["detail"] for answer in answers}) == 1
    assert verified == [1, 1, 1, 1]
    entries = log_entries(state, after=logged)
    assert [(entry.action, entry.actor, entry.target) for entry in entries] == [
        ("session.login_failed", "-", account) for account, _ in attempts
    ]
    assert [entry.details and entry.details["reason"] for entry in entries] == [
        "login_failed",
        "login_failed",
        "disabled",
        "login_failed",
    ]
    assert {(entry.outcome, entry.client) for entry in entries} == {
        ("failed", PERSON_PEER)
    }


def test_a_correct_expired_temporary_password_is_password_expired(
    team: Team,
) -> None:
    """Only the right temporary password past its end says that it expired."""
    # Arrange
    issued_at = datetime.now(UTC) - TEMPORARY_TTL - timedelta(minutes=1)
    expired = passwords.set_temporary_password(
        team.api.state, PERSON, actor=LOCAL_OWNER, now=issued_at
    )

    # Act
    right = sign_in(team.client, PERSON, expired.password)
    wrong = sign_in(team.client, PERSON, WRONG)

    # Assert
    assert_problem(right, 401, "unauthorized", "password_expired")
    assert_problem(wrong, 401, "unauthorized", "login_failed")


def test_a_sign_in_ends_the_session_whose_cookie_it_carried(team: Team) -> None:
    """No session id lives on across a sign-in (ASVS 7.2.4)."""
    # Arrange
    first = signed_in(team.client, PERSON, PERSON_PASSWORD)

    # Act
    again = sign_in(team.client, PERSON, PERSON_PASSWORD, cookie=first.session_id)
    planted = sign_in(team.client, PERSON, PERSON_PASSWORD, cookie="chosen-by-someone")

    # Assert
    assert again.cookies[TEAM_SESSION_COOKIE] != first.session_id
    assert_problem(first.request("GET", "/session"), 401, "unauthorized")
    assert planted.cookies[TEAM_SESSION_COOKIE] != "chosen-by-someone"


def test_a_temporary_password_lets_the_session_only_change_it(team: Team) -> None:
    """Until the change: read the session, its ways in, the change, signing out."""
    # Arrange
    temporary = passwords.set_temporary_password(
        team.api.state, PERSON, actor=LOCAL_OWNER
    ).password
    leaving = signed_in(team.client, PERSON, temporary)
    staying = signed_in(team.client, PERSON, temporary)
    others = [
        ("GET", "/projects"),
        ("GET", "/sessions"),
        ("GET", "/users"),
        ("POST", "/session/tokens"),
    ]

    # Act
    refused = [leaving.request(method, path) for method, path in others]
    read = leaving.request("GET", "/session")
    methods = leaving.request("GET", "/session/methods")
    signed_out = leaving.request("DELETE", "/session")
    changed = change(staying, temporary, NEW_PASSWORD)
    after = caller(team.client, changed).request("GET", "/sessions")

    # Assert
    for answer in refused:
        assert_problem(answer, 403, "forbidden", "password_change_required")
    assert read.status_code == 200 and read.json()["password_change_required"]
    assert methods.status_code == 200
    assert signed_out.status_code == 204
    assert changed.json()["password_change_required"] is False
    assert after.status_code == 200, after.text


def test_a_temporary_password_cannot_become_the_password_that_stays(
    team: Team,
) -> None:
    """A change to the same temporary password is refused; it must still be changed.

    The administrator who issued it still knows it (ASVS 6.4.1); the change
    used to accept it as the long-term password (review of v0.4, D3).
    """
    # Arrange
    admin = signed_in(team.client, ADMIN, ADMIN_PASSWORD)
    issued = admin.request("POST", f"/users/{PERSON}/password")
    temporary = issued.json()["password"]
    session = signed_in(team.client, PERSON, temporary)

    # Act
    kept = change(session, temporary, temporary)
    case_changed = change(session, temporary, temporary.swapcase())
    again = sign_in(team.client, PERSON, temporary)

    # Assert
    for refused in (kept, case_changed):
        assert_problem(refused, 400, "validation_error", "password_policy")
        assert refused.json()["details"]["rule"] == "same_as_current"
    assert again.status_code == 200, again.text
    assert again.json()["password_change_required"] is True


def test_a_password_change_ends_the_other_sessions_and_answers_a_new_one(
    team: Team,
) -> None:
    """Other computers, the agent and the old session end; a new session answers."""
    # Arrange
    here = signed_in(team.client, PERSON, PERSON_PASSWORD)
    there = signed_in(team.other_client(), PERSON, PERSON_PASSWORD)
    agent = agent_of(here)

    # Act
    changed = change(here, PERSON_PASSWORD, NEW_PASSWORD)
    new = caller(team.client, changed)
    old_password = sign_in(team.client, PERSON, PERSON_PASSWORD)
    new_password = sign_in(team.client, PERSON, NEW_PASSWORD)

    # Assert
    assert new.session_id != here.session_id and new.csrf != here.csrf
    for ended in (here, there, agent):
        assert_problem(ended.request("GET", "/session"), 401, "unauthorized")
    assert new.request("GET", "/session").status_code == 200
    assert_problem(old_password, 401, "unauthorized", "login_failed")
    assert new_password.status_code == 200


def test_a_password_change_checks_the_current_password_and_the_policy(
    team: Team,
) -> None:
    """A wrong current password is 403 wrong_password, a weak new one 400."""
    # Arrange
    session = signed_in(team.client, PERSON, PERSON_PASSWORD)

    # Act
    wrong = change(session, WRONG, NEW_PASSWORD)
    weak = change(session, PERSON_PASSWORD, "krotkie")
    common = change(session, PERSON_PASSWORD, "Password1234")
    still = session.request("GET", "/session")

    # Assert
    assert_problem(wrong, 403, "forbidden", "wrong_password")
    assert_problem(weak, 400, "validation_error", "password_policy")
    assert weak.json()["details"]["rule"] == "too_short"
    assert common.json()["details"]["rule"] == "common"
    assert still.status_code == 200
    assert signed_in(team.client, PERSON, PERSON_PASSWORD)


def test_a_person_lists_their_sessions_and_ends_one(team: Team) -> None:
    """GET /sessions shows both sessions, the current one marked; DELETE ends one."""
    # Arrange
    here = caller(team.client, sign_in(team.client, PERSON, PERSON_PASSWORD))
    elsewhere = team.other_client()
    there = caller(
        elsewhere,
        sign_in(elsewhere, PERSON, PERSON_PASSWORD, user_agent="Firefox/140.0"),
    )
    agent = agent_of(here)
    anna = signed_in(team.client, ADMIN, ADMIN_PASSWORD)

    # Act
    listed = here.request("GET", "/sessions").json()["items"]
    label = listed[1]["label"]
    foreign = anna.request("GET", "/sessions").json()["items"]
    ended = here.request("DELETE", f"/sessions/{label}")
    again = here.request("DELETE", f"/sessions/{label}")

    # Assert
    assert [
        (item["kind"], item["method"], item["client"], item["current"])
        for item in listed
    ] == [
        ("browser", "password", PERSON_PEER, True),
        ("browser", "password", OTHER_PEER, False),
        ("agent", "token", PERSON_PEER, False),
    ]
    assert listed[1]["user_agent"] == "Firefox/140.0"
    assert [item["current"] for item in foreign] == [True]
    assert ended.status_code == 204
    assert_problem(there.request("GET", "/session"), 401, "unauthorized")
    assert agent.request("GET", "/session").status_code == 200
    assert_problem(again, 404, "not_found")


def test_only_an_administrator_reads_and_ends_another_persons_sessions(
    team: Team,
) -> None:
    """A person neither lists nor ends anna's sessions; anna ends all of kasia's."""
    # Arrange
    kasia = signed_in(team.client, PERSON, PERSON_PASSWORD)
    agent = agent_of(kasia)
    anna = signed_in(team.client, ADMIN, ADMIN_PASSWORD)
    anna_label = anna.request("GET", "/session").json()["label"]

    # Act
    peek = kasia.request("GET", f"/sessions?user={ADMIN}")
    end_foreign = kasia.request("DELETE", f"/sessions/{anna_label}")
    listed = anna.request("GET", f"/sessions?user={PERSON}").json()["items"]
    unknown = anna.request("GET", "/sessions?user=nikt")
    ended = anna.request("DELETE", f"/users/{PERSON}/sessions")

    # Assert
    assert_problem(peek, 403, "forbidden", "permission_denied")
    assert_problem(end_foreign, 404, "not_found")
    assert [item["kind"] for item in listed] == ["browser", "agent"]
    assert_problem(unknown, 404, "not_found")
    assert ended.status_code == 204
    for gone in (kasia, agent):
        assert_problem(gone.request("GET", "/session"), 401, "unauthorized")
    assert anna.request("GET", "/session").status_code == 200
    assert signed_in(team.client, PERSON, PERSON_PASSWORD)


def test_the_command_line_ends_the_sessions_of_a_running_server(
    team: Team, tmp_path: Path
) -> None:
    """``archiwista users end-sessions`` in another process; the server obeys."""
    # Arrange
    kasia = signed_in(team.client, PERSON, PERSON_PASSWORD)
    anna = signed_in(team.client, ADMIN, ADMIN_PASSWORD)
    environment = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }

    # Act
    ended = subprocess.run(
        [
            sys.executable,
            "-c",
            "from archiwista.cli import main; raise SystemExit(main())",
            "users",
            "end-sessions",
            PERSON,
        ],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        timeout=60,
    )

    # Assert
    assert ended.returncode == 0, ended.stderr
    assert_problem(kasia.request("GET", "/session"), 401, "unauthorized")
    assert anna.request("GET", "/session").status_code == 200
    entry = log_entries(team.api.state)[-1]
    assert (entry.action, entry.actor, entry.target) == (
        "user.sessions_ended",
        "local",
        PERSON,
    )


def test_a_disabled_account_loses_its_session(team: Team) -> None:
    """An administrator disables kasia: her session ends at its next request."""
    # Arrange
    kasia = signed_in(team.client, PERSON, PERSON_PASSWORD)
    anna = signed_in(team.client, ADMIN, ADMIN_PASSWORD)

    # Act
    disabled = anna.request("PATCH", f"/users/{PERSON}", json={"disabled": True})

    # Assert
    assert disabled.status_code == 200, disabled.text
    assert_problem(kasia.request("GET", "/session"), 401, "unauthorized")
    assert_problem(sign_in(team.client, PERSON, PERSON_PASSWORD), 401, "unauthorized")


def test_failures_of_an_account_make_it_wait_from_every_address(team: Team) -> None:
    """Five failures, then 429 with a Retry-After that doubles; a success clears."""
    # Arrange
    elsewhere = team.other_client()
    failures = [sign_in(team.client, PERSON, WRONG) for _ in range(5)]
    verified = team.hasher.verified

    # Act
    blocked = sign_in(elsewhere, PERSON, PERSON_PASSWORD)
    refused_without_a_hash = team.hasher.verified == verified
    team.clock.now += timedelta(seconds=1)
    sixth = sign_in(team.client, PERSON, WRONG)
    doubled = sign_in(elsewhere, PERSON, PERSON_PASSWORD)
    team.clock.now += timedelta(seconds=2)
    success = sign_in(team.client, PERSON, PERSON_PASSWORD)
    cleared = [sign_in(team.client, PERSON, WRONG) for _ in range(4)]

    # Assert
    for failure in [*failures, sixth, *cleared]:
        assert_problem(failure, 401, "unauthorized", "login_failed")
    assert_problem(blocked, 429, "rate_limited", "login_blocked")
    assert refused_without_a_hash
    assert (blocked.headers["retry-after"], doubled.headers["retry-after"]) == (
        "1",
        "2",
    )
    assert blocked.json()["details"]["retry_after_s"] == 1
    assert_problem(doubled, 429, "rate_limited", "login_blocked")
    assert success.status_code == 200, success.text


def test_failures_from_an_address_make_it_wait_for_every_account(
    team: Team,
) -> None:
    """Five failures from one computer stop its next sign-in, not another's."""
    # Arrange
    for account in ("ala", "ola", "ela", "ula", "iza"):
        assert_problem(sign_in(team.client, account, WRONG), 401, "unauthorized")

    # Act
    here = sign_in(team.client, ADMIN, ADMIN_PASSWORD)
    elsewhere = sign_in(team.other_client(), ADMIN, ADMIN_PASSWORD)

    # Assert
    assert_problem(here, 429, "rate_limited", "login_blocked")
    assert elsewhere.status_code == 200, elsewhere.text


def test_wrong_passwords_sent_at_once_wait_like_one_after_another(team: Team) -> None:
    """Twenty failures at once verify at most five passwords; the rest wait.

    The wait used to be checked before a verification and counted after it,
    so attempts arriving together all passed the check (review of v0.4, D1).
    """
    # Arrange
    team.hasher.pause_s = 0.2
    together = threading.Barrier(20)

    def attempt(_: int) -> httpx.Response:
        together.wait()
        response: httpx.Response = team.client.post(
            LOGIN, json={"account": PERSON, "password": WRONG}
        )
        return response

    # Act
    with ThreadPoolExecutor(max_workers=20) as pool:
        answers = list(pool.map(attempt, range(20)))

    # Assert
    refused = [answer for answer in answers if answer.status_code == 401]
    waiting = [answer for answer in answers if answer.status_code != 401]
    assert team.hasher.verified == len(refused) <= FREE_FAILURES
    for answer in waiting:
        assert_problem(answer, 429, "rate_limited", "login_blocked")
        assert int(answer.headers["retry-after"]) >= 1


def test_at_most_two_passwords_are_verified_at_once(team: Team) -> None:
    """Five sign-ins at once verify all five passwords, never more than two together."""
    # Arrange
    team.hasher.pause_s = 0.05

    # Act
    with ThreadPoolExecutor(max_workers=FREE_FAILURES) as pool:
        answers = list(
            pool.map(
                lambda _: team.client.post(
                    LOGIN, json={"account": PERSON, "password": PERSON_PASSWORD}
                ),
                range(FREE_FAILURES),
            )
        )

    # Assert
    assert [answer.status_code for answer in answers] == [200] * FREE_FAILURES
    assert team.hasher.verified == FREE_FAILURES
    assert team.hasher.most_at_once == HASH_SLOTS


def test_every_action_of_signing_in_has_its_entry(
    team: Team, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sign-ins, failures, tokens, the password, ended sessions, signing out."""
    # Arrange
    state = team.api.state
    logged = last_entry(state)

    # Act
    for _ in range(5):
        sign_in(team.client, PERSON, WRONG)
    team.clock.now += timedelta(minutes=1)
    kasia = signed_in(team.client, PERSON, PERSON_PASSWORD)
    agent_label = agent_of(kasia).request("GET", "/session").json()["label"]
    change(kasia, WRONG, NEW_PASSWORD)
    kasia = caller(team.client, change(kasia, PERSON_PASSWORD, NEW_PASSWORD))
    second = signed_in(team.other_client(), PERSON, NEW_PASSWORD)
    label = second.request("GET", "/session").json()["label"]
    kasia.request("DELETE", f"/sessions/{label}")
    anna = signed_in(team.client, ADMIN, ADMIN_PASSWORD)
    anna.request("DELETE", f"/users/{PERSON}/sessions")
    anna.request("DELETE", "/session")
    assert main(["token", "--revoke-all"], paths=team.api.paths) == 0
    capsys.readouterr()

    # Assert
    entries = log_entries(state, after=logged)
    assert [(entry.action, entry.actor, entry.outcome) for entry in entries] == [
        *[("session.login_failed", "-", "failed")] * 5,
        ("session.login", PERSON, "ok"),
        ("token.issue", PERSON, "ok"),
        ("session.login", PERSON, "ok"),
        ("session.password", PERSON, "failed"),
        ("session.password", PERSON, "ok"),
        ("session.login", PERSON, "ok"),
        ("session.ended", PERSON, "ok"),
        ("session.login", ADMIN, "ok"),
        ("user.sessions_ended", ADMIN, "ok"),
        ("session.logout", ADMIN, "ok"),
        ("token.revoke_all", "local", "ok"),
    ]
    failures, blocking = entries[:4], entries[4]
    assert all("blocked_until" not in (entry.details or {}) for entry in failures)
    assert blocking.details is not None and "blocked_until" in blocking.details
    assert [entry.details for entry in (entries[5], entries[7], entries[10])] == [
        {"method": "password"},
        {"method": "token"},
        {"method": "password"},
    ]
    assert (entries[7].actor_kind, entries[6].details) == (
        "agent",
        {"label": agent_label},
    )
    assert entries[8].details == {
        "reason": "wrong_password",
        "method": "password",
    }
    assert entries[11].details == {"label": label}
    assert entries[-1].target == "*" and entries[-1].details == {"count": 0}


def test_local_mode_has_no_sign_in(tmp_path: Path) -> None:
    """Local mode answers the ways in, and a sign-in is 409 local_mode."""
    # Arrange
    with running_api(local_paths(tmp_path)) as api:
        # Act
        methods = api.client.get("/api/v1/session/methods")
        refused = sign_in(api.client, PERSON, PERSON_PASSWORD)

    # Assert
    assert methods.json() == {"mode": "local", "password": False, "proxy": False}
    assert_problem(refused, 409, "conflict", "local_mode")
