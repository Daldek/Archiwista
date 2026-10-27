"""Passwords of accounts and the last administrator, over HTTP and at the terminal.

Team mode (ADR-046 decision 4): an administrator gives a temporary password the
server generates (``POST /users/{user_id}/password``), the server's terminal
sets a typed one (``archiwista users password``), and the last administrator
who can sign in cannot be disabled, removed or lose the role. The hashes are
real Argon2id at the lowest cost (``cheap_hasher``).
"""

import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER, passwords
from archiwista.auth.authorize import principal_for
from archiwista.auth.passwords import TEMPORARY_TTL, Verified
from archiwista.cli import main
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import last_entry, log_entries
from tests.fixtures.team_server import cheap_hasher, save_team

ADMIN = "anna"
PERSON = "kasia"
TYPED = "kajak-po-Rabie-o-swicie"
# Each change that would leave the team without an administrator who can sign
# in, at the terminal and over HTTP.
LAST_ADMIN_CHANGES = [
    (("users", "disable", ADMIN), "PATCH", f"/users/{ADMIN}", {"disabled": True}),
    (("users", "roles", ADMIN), "PATCH", f"/users/{ADMIN}", {"roles": []}),
    (("users", "remove", ADMIN), "DELETE", f"/users/{ADMIN}", None),
]


@pytest.fixture
def team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    """Serve team mode: anna, an administrator with a password, and kasia."""
    monkeypatch.setattr(passwords, "HASHER", cheap_hasher())
    paths = local_paths(tmp_path)
    save_team(paths)
    with running_api(paths) as api:
        api.state.add_user(ADMIN, name="Anna Admin", roles=["admin"], actor=LOCAL_OWNER)
        api.state.add_user(PERSON, name="Kasia Kowalska", actor=LOCAL_OWNER)
        passwords.set_password(
            api.state, ADMIN, TYPED, temporary=False, actor=LOCAL_OWNER
        )
        yield api


def administrator(api: Api) -> Caller:
    """Open a session of anna, the team's administrator."""
    anna = principal_for(api.state, ADMIN)
    assert anna is not None
    return api.session(anna)


def command(
    api: Api, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str, str]:
    """Run ``archiwista ARGV --json`` over the served data; status, out, err."""
    capsys.readouterr()
    status = main([*argv, "--json"], paths=api.paths)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def listed(caller: Caller, user_id: str) -> dict[str, Any]:
    """Return the item of ``user_id`` in ``GET /users``."""
    response = caller.request("GET", "/users")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return next(item for item in items if item["id"] == user_id)


def test_temporary_password_is_answered_once_and_ends_the_sessions(
    team: Api,
) -> None:
    """The route answers the password once, valid 72 hours; nothing shows a hash."""
    # Arrange
    admin = administrator(team)
    logged = last_entry(team.state)
    start = datetime.now(UTC).replace(microsecond=0)

    # Act
    response = admin.request("POST", f"/users/{PERSON}/password")
    users = admin.request("GET", "/users")

    # Assert
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    answer = response.json()
    expires = datetime.fromisoformat(answer["expires_at"])
    assert start + TEMPORARY_TTL <= expires <= datetime.now(UTC) + TEMPORARY_TTL
    kept = team.state.password_record(PERSON)
    assert passwords.verify(kept, answer["password"]) == Verified(
        matches=True, temporary=True
    )
    user = team.state.user(PERSON)
    assert user is not None and user.sessions_revoked_at is not None
    assert user.sessions_revoked_at >= start
    item = listed(admin, PERSON)
    assert (item["password"], item["password_expires_at"]) == (
        "temporary",
        answer["expires_at"],
    )
    assert answer["password"] not in users.text and "$argon2" not in users.text
    (entry,) = log_entries(team.state, after=logged)
    assert (entry.actor, entry.action, entry.target) == (
        ADMIN,
        "user.password_reset",
        PERSON,
    )
    assert entry.details is not None and entry.details["temporary"] is True
    assert datetime.fromisoformat(str(entry.details["expires_at"])) == expires
    assert answer["password"] not in repr(entry) and "$argon2" not in repr(entry)


def test_each_temporary_password_replaces_the_one_before(team: Api) -> None:
    """A second temporary password works and the first no longer does."""
    # Arrange
    admin = administrator(team)
    first = admin.request("POST", f"/users/{PERSON}/password").json()["password"]

    # Act
    second = admin.request("POST", f"/users/{PERSON}/password").json()["password"]

    # Assert
    kept = team.state.password_record(PERSON)
    assert second != first
    assert passwords.verify(kept, second).matches
    assert not passwords.verify(kept, first).matches


@pytest.mark.parametrize("temporary", [False, True])
def test_cli_sets_a_password_read_from_standard_input(
    team: Api,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    temporary: bool,
) -> None:
    """``users password --stdin`` keeps the line's hash; it prints what /users lists."""
    # Arrange
    admin = administrator(team)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{TYPED}\n"))
    logged = last_entry(team.state)
    option = ("--temporary",) if temporary else ()

    # Act
    status, out, err = command(
        team, capsys, "users", "password", PERSON, "--stdin", *option
    )

    # Assert
    assert status == 0, err
    printed = json.loads(out)
    assert printed == listed(admin, PERSON)
    assert printed["password"] == ("temporary" if temporary else "set")
    assert (printed["password_expires_at"] is not None) is temporary
    verified = passwords.verify(team.state.password_record(PERSON), TYPED)
    assert verified.matches and verified.temporary is temporary
    (entry,) = log_entries(team.state, after=logged)
    assert (entry.actor, entry.action) == ("local", "user.password_reset")
    assert entry.details is not None and entry.details["temporary"] is temporary
    user = team.state.user(PERSON)
    assert user is not None and user.sessions_revoked_at is not None


@pytest.mark.parametrize(
    ("typed", "reason", "rule"),
    [
        (("Kasia Kowalska",), "password_policy", "account_name"),
        (("krotkie",), "password_policy", "too_short"),
        ((TYPED, f"{TYPED}!"), "password_mismatch", None),
    ],
)
def test_cli_refuses_a_password_the_policy_or_the_repetition_refuses(
    team: Api,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    typed: tuple[str, ...],
    reason: str,
    rule: str | None,
) -> None:
    """A refused password changes nothing; the prompts ask twice without echo."""
    # Arrange
    answers = iter(typed)
    prompts: list[str] = []

    def type_unseen(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("getpass.getpass", type_unseen)
    before = team.state.snapshot()

    # Act
    if len(typed) == 1:
        monkeypatch.setattr("sys.stdin", io.StringIO(f"{typed[0]}\n"))
        status, out, err = command(team, capsys, "users", "password", PERSON, "--stdin")
    else:
        status, out, err = command(team, capsys, "users", "password", PERSON)

    # Assert
    document = refusal(out, err, status)
    assert (document["code"], document["details"]["reason"]) == (
        "validation_error",
        reason,
    )
    assert document["details"].get("rule") == rule
    assert len(prompts) == (0 if len(typed) == 1 else 2)
    assert team.state.password_record(PERSON) is None
    assert team.state.snapshot() == before


def test_unknown_account_is_refused_alike_at_the_terminal_and_over_http(
    team: Api,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``users password nikt`` asks for nothing and says what the route says."""
    # Arrange
    admin = administrator(team)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{TYPED}\n"))

    # Act
    status, out, err = command(team, capsys, "users", "password", "nikt", "--stdin")
    answered = admin.request("POST", "/users/nikt/password")

    # Assert
    assert_problem(answered, 404, "not_found")
    assert_same_error(refusal(out, err, status), answered.json())


@pytest.mark.parametrize(("argv", "method", "path", "body"), LAST_ADMIN_CHANGES)
def test_the_last_administrator_who_can_sign_in_stays(
    team: Api,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    """Disabling, demoting or removing the last one is 409 on both doors.

    An enabled administrator without a password used to count, so anna could
    go and nobody could administer the team from the network (review of v0.4,
    D9).
    """
    # Arrange: a disabled administrator and one without a password do not count.
    admin = administrator(team)
    team.state.add_user("ada", roles=["admin"], actor=LOCAL_OWNER)
    team.state.update_user("ada", disabled=True, actor=LOCAL_OWNER)
    team.state.add_user("bob", roles=["admin"], actor=LOCAL_OWNER)
    before = team.state.snapshot()

    # Act
    answered = admin.request(method, path, json=body)
    status, out, err = command(team, capsys, *argv)

    # Assert
    assert_problem(answered, 409, "conflict", "last_admin")
    assert_same_error(refusal(out, err, status), answered.json())
    assert team.state.snapshot() == before


@pytest.mark.parametrize("way", ["password", "proxy"])
def test_another_administrator_who_can_sign_in_lets_the_first_go(
    team: Api, capsys: pytest.CaptureFixture[str], way: str
) -> None:
    """With ada able to sign in, anna can be disabled; then ada is the last one.

    Ada signs in with a password, or without one through the reverse proxy
    that names people (``proxy_user_header``).
    """
    # Arrange
    team.state.add_user("ada", roles=["admin"], actor=LOCAL_OWNER)
    if way == "password":
        passwords.set_password(
            team.state, "ada", TYPED, temporary=False, actor=LOCAL_OWNER
        )
    else:
        save_team(team.paths, trusted_proxies=["10.0.0.1"], proxy_user_header="X-User")

    # Act
    disabled = command(team, capsys, "users", "disable", ADMIN)
    refused = command(team, capsys, "users", "disable", "ada")

    # Assert
    status, out, err = disabled
    assert status == 0, err
    assert json.loads(out)["disabled"] is True
    assert refusal(refused[1], refused[2], refused[0])["details"]["reason"] == (
        "last_admin"
    )
