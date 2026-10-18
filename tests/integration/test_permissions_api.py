"""Permissions over HTTP with several identities (A-ADR-029, SPEC 9.2, 10.2).

Each session comes from a one-time token minted by the identity under test
(``current_principal`` then acts as it), so the routes see owners, listed
people, other people, administrators and their agents exactly as the
server would.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.index import IndexWriter, ManifestStamp
from archiwista.sources import ProjectInfo
from archiwista.state import Visibility
from tests.fixtures.api_session import Api, assert_problem, running_api
from tests.fixtures.index_data import PRODUCER, ROOT, STORE
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import (
    GROUP,
    LISTED,
    MANAGES,
    OTHER,
    OWNER,
    SEES,
    VISIBILITY_VALUES,
    WHO,
    Who,
    add_people,
    principal,
    share,
)

PROJECT_DIR = Path("/projekty/raba")
KEY = access_key(PROJECT_DIR)
ACCESS = "/projects/raba/access"
ADMIN_ROUTES = [
    ("GET", "/users", None),
    ("POST", "/users", {"id": "nowy"}),
    ("PATCH", f"/users/{OTHER}", {"roles": ["admin"]}),
    ("DELETE", f"/users/{OTHER}", None),
    ("GET", "/groups", None),
    ("POST", "/groups", {"id": "geodezja"}),
    ("PUT", f"/groups/{GROUP}/members", {"members": [OTHER]}),
    ("DELETE", f"/groups/{GROUP}", None),
]
CHANGES = [route for route in ADMIN_ROUTES if route[0] != "GET"] + [
    ("PUT", ACCESS, {"visibility": "private"})
]


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """Serve an index with the project ``raba`` and a state with four people."""
    paths = local_paths(tmp_path)
    with running_api(paths) as served:
        with IndexWriter(paths.index_file) as writer:
            writer.sync_stores({STORE: {PRODUCER: ROOT}})
            project = ProjectInfo(PRODUCER, ROOT, PROJECT_DIR, "Raba")
            writer.write_project(project, store=STORE, stamp=ManifestStamp(1, 1))
        add_people(served.state)
        yield served


@pytest.mark.parametrize("token", ["startup", "agent"])
@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize("visibility", VISIBILITY_VALUES)
def test_project_access_follows_visibility_matrix(
    api: Api,
    visibility: Visibility,
    who: Who,
    token: Literal["startup", "agent"],
) -> None:
    """Hidden → 404, visible but not managed → 403, owner and admin → 200."""
    # Arrange
    share(api.state, KEY, visibility)
    caller = api.session(principal(api.state, who), token=token)

    # Act
    response = caller.request("GET", ACCESS)

    # Assert
    if who not in SEES[visibility]:
        assert_problem(response, 404, "not_found")
    elif who not in MANAGES:
        assert_problem(response, 403, "permission_denied")
    else:
        assert response.status_code == 200
        assert response.json() == {
            "project": "raba",
            "owner": OWNER,
            "visibility": visibility,
            "users": [LISTED] if visibility == "users" else [],
            "groups": [GROUP] if visibility == "group" else [],
            "explicit": True,
        }


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize("visibility", VISIBILITY_VALUES)
def test_project_routes_follow_visibility_matrix(
    api: Api, visibility: Visibility, who: Who
) -> None:
    """/projects lists, and its detail and status show, only visible projects."""
    # Arrange
    share(api.state, KEY, visibility)
    caller = api.session(principal(api.state, who))

    # Act
    listed = caller.request("GET", "/projects").json()["items"]
    detail = caller.request("GET", "/projects/raba")
    status = caller.request("GET", "/projects/raba/status")

    # Assert
    if who in SEES[visibility]:
        assert [item["project"] for item in listed] == ["raba"]
        assert detail.status_code == 200 and detail.json()["name"] == "Raba"
        # Visible: the producer is asked, and this server has none.
        assert_problem(status, 503, "source_unavailable")
    else:
        assert listed == []
        assert_problem(detail, 404, "not_found")
        assert_problem(status, 404, "not_found")


def test_settings_change_needs_administrator(api: Api) -> None:
    """Everyone reads the settings; only an administrator changes them."""
    # Arrange
    owner = api.session(principal(api.state, "owner"))
    admin = api.session(principal(api.state, "admin"))
    current = owner.request("GET", "/settings").json()

    # Act
    refused = owner.request("PUT", "/settings", json={**current, "offline": True})
    accepted = admin.request("PUT", "/settings", json={**current, "offline": True})

    # Assert
    assert_problem(refused, 403, "permission_denied")
    assert accepted.status_code == 200 and accepted.json()["offline"] is True


def test_unknown_and_hidden_projects_answer_alike(api: Api) -> None:
    """A private project is as unknown to another person as a missing one."""
    # Arrange
    share(api.state, KEY, "private")
    caller = api.session(principal(api.state, "other"))

    # Act
    hidden = caller.request("GET", ACCESS)
    missing = caller.request("GET", "/projects/nie-ma/access")

    # Assert
    assert_problem(hidden, 404, "not_found")
    assert_problem(missing, 404, "not_found")


def test_other_person_cannot_change_access(api: Api) -> None:
    """Seeing a public project does not allow sharing it; nothing changes."""
    # Arrange
    share(api.state, KEY, "public")
    before = api.state.snapshot()
    caller = api.session(principal(api.state, "other"))

    # Act
    response = caller.request("PUT", ACCESS, json={"visibility": "private"})

    # Assert
    assert_problem(response, 403, "permission_denied")
    assert api.state.snapshot() == before


def test_owner_shares_project_and_change_is_logged(api: Api) -> None:
    """The owner opens a private project to a person; the log keeps both states."""
    # Arrange
    share(api.state, KEY, "private")
    owner = api.session(principal(api.state, "owner"))
    listed = api.session(principal(api.state, "listed"))
    hidden = listed.request("GET", ACCESS)

    # Act
    response = owner.request(
        "PUT", ACCESS, json={"visibility": "users", "users": [LISTED]}
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["users"] == [LISTED]
    change = api.state.changes()[-1]
    assert (change.actor, change.action, change.target) == (
        OWNER,
        "project.access",
        KEY,
    )
    assert change.before is not None and change.before["visibility"] == "private"
    assert change.after is not None and change.after["users"] == [LISTED]
    # Lena now sees the project, without managing it.
    assert_problem(hidden, 404, "not_found")
    assert_problem(listed.request("GET", ACCESS), 403, "permission_denied")


def test_admin_transfers_ownership_of_scanned_project(api: Api) -> None:
    """A project nobody shared has no owner until an administrator names one."""
    # Arrange
    admin = api.session(principal(api.state, "admin"))
    owner = api.session(principal(api.state, "owner"))
    before = admin.request("GET", ACCESS)

    # Act
    moved = admin.request("PUT", ACCESS, json={"visibility": "private", "owner": OWNER})
    kept = owner.request("PUT", ACCESS, json={"visibility": "group", "groups": [GROUP]})

    # Assert
    assert before.json() == {
        "project": "raba",
        "owner": None,
        "visibility": "public",
        "users": [],
        "groups": [],
        "explicit": False,
    }
    assert moved.status_code == 200 and moved.json()["owner"] == OWNER
    # Omitting the owner keeps it.
    assert kept.status_code == 200 and kept.json()["owner"] == OWNER


@pytest.mark.parametrize(
    "body",
    [
        {"visibility": "users"},
        {"visibility": "users", "users": ["nikt"]},
        {"visibility": "group", "users": [LISTED], "groups": [GROUP]},
        {"visibility": "public", "groups": [GROUP]},
        {"visibility": "private", "owner": "nikt"},
        {"visibility": "wszyscy"},
    ],
)
def test_share_rejects_entries_that_do_not_fit(
    api: Api, body: dict[str, object]
) -> None:
    """Unknown people or groups and lists not fitting the visibility → 422."""
    # Arrange
    admin = api.session(principal(api.state, "admin"))

    # Act
    response = admin.request("PUT", ACCESS, json=body)

    # Assert
    assert_problem(response, 422, "validation_error")
    assert api.state.project_access(KEY) is None


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_admin_routes_refuse_people_without_admin(
    api: Api, method: str, path: str, body: dict[str, object] | None
) -> None:
    """Accounts and groups are an administrator's: others get 403, nothing changes."""
    # Arrange
    before = api.state.snapshot()
    caller = api.session(principal(api.state, "owner"))

    # Act
    response = caller.request(method, path, json=body)

    # Assert
    assert_problem(response, 403, "permission_denied")
    assert api.state.snapshot() == before


@pytest.mark.parametrize(("method", "path", "body"), CHANGES)
def test_changes_need_csrf_token(
    api: Api, method: str, path: str, body: dict[str, object] | None
) -> None:
    """Every change of accounts, groups or access needs the session's CSRF token."""
    # Arrange
    before = api.state.snapshot()
    caller = api.session(principal(api.state, "admin"))

    # Act
    response = caller.request(method, path, json=body, csrf=False)

    # Assert
    assert_problem(response, 403, "csrf_rejected")
    assert api.state.snapshot() == before


def test_admin_manages_accounts_and_groups(api: Api) -> None:
    """Create, change and remove accounts and groups; each change is logged."""
    # Arrange
    admin = api.session(principal(api.state, "admin"))
    logged = len(api.state.changes())

    # Act
    created = admin.request(
        "POST", "/users", json={"id": "jan", "name": "Jan", "roles": ["store_writer"]}
    )
    taken = admin.request("POST", "/users", json={"id": "jan"})
    reserved = admin.request("POST", "/users", json={"id": "local"})
    promoted = admin.request("PATCH", "/users/jan", json={"roles": ["admin"]})
    grouped = admin.request(
        "POST", "/groups", json={"id": "geodezja", "members": ["jan", OTHER]}
    )
    unknown = admin.request("PUT", "/groups/geodezja/members", json={"members": ["x"]})
    regrouped = admin.request(
        "PUT", "/groups/geodezja/members", json={"members": ["jan"]}
    )
    removed = admin.request("DELETE", "/users/jan")
    gone = admin.request("PATCH", "/users/jan", json={"disabled": True})
    dropped = admin.request("DELETE", "/groups/geodezja")
    users = admin.request("GET", "/users").json()["items"]
    groups = admin.request("GET", "/groups").json()["items"]

    # Assert
    assert created.status_code == 201
    assert created.json()["roles"] == ["store_writer"]
    assert_problem(taken, 409, "conflict")
    assert_problem(reserved, 422, "validation_error")
    assert promoted.json()["roles"] == ["admin"]
    assert grouped.status_code == 201
    assert grouped.json()["members"] == [OTHER, "jan"]
    assert_problem(unknown, 422, "validation_error")
    assert regrouped.json()["members"] == ["jan"]
    assert removed.status_code == 204 and not removed.content
    assert_problem(gone, 404, "not_found")
    assert dropped.status_code == 204
    assert "jan" not in {user["id"] for user in users}
    assert "geodezja" not in {group["id"] for group in groups}
    actions = [change.action for change in api.state.changes()[logged:]]
    assert actions == [
        "user.add",
        "user.update",
        "group.add",
        "group.members",
        "user.remove",
        "group.members",
        "group.remove",
    ]
    assert {change.actor for change in api.state.changes()[logged:]} == {"ada"}


def test_local_owner_sees_and_manages_everything(api: Api) -> None:
    """Local mode: the owner of the computer manages a private project and accounts."""
    # Arrange
    share(api.state, KEY, "private")
    local = api.session(LOCAL_OWNER)

    # Act
    access = local.request("GET", ACCESS)
    changed = local.request("PUT", ACCESS, json={"visibility": "public"})
    users = local.request("GET", "/users")

    # Assert
    assert access.status_code == 200
    assert changed.json()["visibility"] == "public"
    assert api.state.changes()[-1].actor == "local"
    assert [user["id"] for user in users.json()["items"]] == sorted(
        ["ada", "igor", "lena", "olga"]
    )
