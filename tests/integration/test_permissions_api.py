"""Permissions over HTTP with several identities (A-ADR-029, SPEC 9.2, 10.2).

Each session comes from a one-time token minted by the identity under test
(``current_principal`` then acts as it), so the routes see owners, listed
people, other people, administrators and their agents exactly as the
server would. The own-data matrix (plan v0.2, step 9) serves a generated
store whose project has a data folder, with render processes and the real
job worker (``tests.fixtures.own_data_api``).
"""

import json
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.index import MAX_PAGE_LIMIT, IndexWriter, ManifestStamp
from archiwista.refs import version_ref
from archiwista.security import issue_one_time_token
from archiwista.sources import ProjectInfo
from archiwista.state import ActionEntry, StateSnapshot, Visibility
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.api_store import STORE as GENERATED_STORE
from tests.fixtures.index_data import PRODUCER, ROOT, STORE
from tests.fixtures.local_server import local_paths
from tests.fixtures.own_data_api import OwnDataApi, own_data_api
from tests.fixtures.permissions import (
    ADMIN,
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
    last_entry,
    log_entries,
    principal,
    share,
)
from tests.fixtures.preview_api import center_tile_url, entry_of

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

# The own-data matrix: the project ``projekt-01`` of a generated store, its
# data folder, its snapshots and the jobs holding its data (plan v0.2, step 9).
GPKG = "kanalizacja.gpkg"
TIF = "nmt.tif"
STRIP = "pas.tif"
"""A GeoTIFF in strips wider than direct tiles allow: its map needs a local COG."""
DAMAGED = "uszkodzony.tif"
ARCHIVE = "archiwum.zip"
NOTE = "Stan przed przebudową kolektora"
POLAND = "14.0,49.0,24.2,55.0"
FEATURES_ZOOM = 14
HIDDEN = "404 not_found"
# Jobs made once by the owner; ``mixed`` previews a store version with a file.
PROBE_JOBS = ("mixed", "own_scan", "preview", "snapshot")


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
        assert_problem(response, 403, "forbidden", "permission_denied")
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
        assert_problem(status, 503, "missing_dependency", "source_unavailable")
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
    assert_problem(refused, 403, "forbidden", "permission_denied")
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
    """Seeing a public project does not allow sharing it; only the refusal is logged."""
    # Arrange
    share(api.state, KEY, "public")
    before = api.state.snapshot()
    caller = api.session(principal(api.state, "other"))

    # Act
    response = caller.request("PUT", ACCESS, json={"visibility": "private"})

    # Assert
    assert_problem(response, 403, "forbidden", "permission_denied")
    refused = only_refusals(api, before)
    assert [(item.actor, item.target) for item in refused] == [(OTHER, KEY)]
    assert refused[0].details == {
        "action": "project.share",
        "route": "PUT /projects/{project}/access",
    }


def only_refusals(api: Api, before: StateSnapshot) -> list[ActionEntry]:
    """Return the entries a refused request added; nothing else may change."""
    after = api.state.snapshot()
    assert replace(after, actions=before.actions) == before
    added = list(after.actions[len(before.actions) :])
    assert {(item.action, item.outcome) for item in added} == {
        ("permission.denied", "denied")
    }
    return added


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
    change = api.state.actions().entries[0]
    assert (change.actor, change.action, change.target) == (
        OWNER,
        "project.access",
        KEY,
    )
    assert change.before is not None and change.before["visibility"] == "private"
    assert change.after is not None and change.after["users"] == [LISTED]
    # Lena now sees the project, without managing it.
    assert_problem(hidden, 404, "not_found")
    assert_problem(listed.request("GET", ACCESS), 403, "forbidden", "permission_denied")


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
    assert_problem(response, 400, "validation_error")
    assert api.state.project_access(KEY) is None


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_admin_routes_refuse_people_without_admin(
    api: Api, method: str, path: str, body: dict[str, object] | None
) -> None:
    """Accounts and groups are an administrator's: others get 403, nothing changes.

    Only the refusal is logged, about the accounts or the groups.
    """
    # Arrange
    before = api.state.snapshot()
    caller = api.session(principal(api.state, "owner"))

    # Act
    response = caller.request(method, path, json=body)

    # Assert
    assert_problem(response, 403, "forbidden", "permission_denied")
    refused = only_refusals(api, before)
    assert [(item.actor, item.target) for item in refused] == [
        (OWNER, path.split("/")[1])
    ]


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
    assert_problem(response, 403, "forbidden", "csrf_rejected")
    assert api.state.snapshot() == before


def test_admin_manages_accounts_and_groups(api: Api) -> None:
    """Create, change and remove accounts and groups; each change is logged."""
    # Arrange
    admin = api.session(principal(api.state, "admin"))
    logged = last_entry(api.state)

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
    assert_problem(reserved, 400, "validation_error")
    assert promoted.json()["roles"] == ["admin"]
    assert grouped.status_code == 201
    assert grouped.json()["members"] == [OTHER, "jan"]
    assert_problem(unknown, 400, "validation_error")
    assert regrouped.json()["members"] == ["jan"]
    assert removed.status_code == 204 and not removed.content
    assert_problem(gone, 404, "not_found")
    assert dropped.status_code == 204
    assert "jan" not in {user["id"] for user in users}
    assert "geodezja" not in {group["id"] for group in groups}
    actions = [entry.action for entry in log_entries(api.state, after=logged)]
    assert actions == [
        "user.add",
        "user.update",
        "group.add",
        "group.members",
        "user.remove",
        "group.members",
        "group.remove",
    ]
    assert {entry.actor for entry in log_entries(api.state, after=logged)} == {"ada"}


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
    assert api.state.actions().entries[0].actor == "local"
    assert [user["id"] for user in users.json()["items"]] == sorted(
        ["ada", "igor", "lena", "olga"]
    )


@pytest.mark.parametrize("token", ["startup", "agent"])
def test_revoked_admin_role_holds_for_live_session(
    api: Api, token: Literal["startup", "agent"]
) -> None:
    """A session opened as administrator loses admin routes once the role goes.

    ``GET /session`` names the roles of each request, so the interface stops
    offering administrators' actions at its next start.
    """
    # Arrange
    admin = api.session(principal(api.state, "admin"), token=token)
    local = api.session(LOCAL_OWNER)
    before = admin.request("GET", "/users")
    signed_in = admin.request("GET", "/session")

    # Act
    revoked = local.request("PATCH", f"/users/{ADMIN}", json={"roles": []})
    after = admin.request("GET", "/users")
    still_signed_in = admin.request("GET", "/session")

    # Assert
    assert before.status_code == 200
    assert signed_in.json()["roles"] == ["admin"]
    assert revoked.status_code == 200 and revoked.json()["roles"] == []
    assert_problem(after, 403, "forbidden", "permission_denied")
    assert still_signed_in.status_code == 200
    assert still_signed_in.json()["roles"] == []


@pytest.mark.parametrize("change", ["disable", "remove"])
@pytest.mark.parametrize("token", ["startup", "agent"])
def test_disabled_or_removed_account_ends_its_sessions(
    api: Api, token: Literal["startup", "agent"], change: str
) -> None:
    """The next request of a disabled or removed account's session gets 401."""
    # Arrange
    owner = api.session(principal(api.state, "owner"), token=token)
    local = api.session(LOCAL_OWNER)
    before = owner.request("GET", "/session")

    # Act
    if change == "disable":
        done = local.request("PATCH", f"/users/{OWNER}", json={"disabled": True})
    else:
        done = local.request("DELETE", f"/users/{OWNER}")
    ended = owner.request("GET", "/session")
    again = owner.request("GET", "/session")

    # Assert
    assert before.status_code == 200
    assert done.status_code in (200, 204)
    assert_problem(ended, 401, "unauthorized", "session_required")
    assert_problem(again, 401, "unauthorized", "session_required")


@pytest.mark.parametrize("token", ["startup", "agent"])
def test_token_of_disabled_account_starts_no_session(
    api: Api, token: Literal["startup", "agent"]
) -> None:
    """A token minted before its account was disabled opens no session (401)."""
    # Arrange
    issued = issue_one_time_token(
        api.paths.index_file, token, minted_by=principal(api.state, "owner")
    )
    local = api.session(LOCAL_OWNER)
    disabled = local.request("PATCH", f"/users/{OWNER}", json={"disabled": True})

    # Act
    exchanged = api.client.post("/api/v1/session", json={"token": issued.token})

    # Assert
    assert disabled.status_code == 200
    assert_problem(exchanged, 401, "unauthorized", "session_required")
    assert "set-cookie" not in exchanged.headers


def test_action_log_records_how_and_in_which_session(api: Api) -> None:
    """A logged change keeps who acted, how, the session and the client address."""
    # Arrange
    local = api.session(LOCAL_OWNER)
    owner = api.session(principal(api.state, "owner"))
    agent = api.session(principal(api.state, "admin"), token="agent")
    share(api.state, KEY, "private")
    logged = last_entry(api.state)
    labels = [
        caller.request("GET", "/session").json()["label"]
        for caller in (local, owner, agent)
    ]

    # Act
    local.request("PATCH", f"/users/{OTHER}", json={"name": "Igor Nowy"})
    owner.request("PUT", ACCESS, json={"visibility": "public"})
    agent.request("POST", "/groups", json={"id": "geodezja"})

    # Assert
    changes = log_entries(api.state, after=logged)
    assert [
        (change.actor, change.actor_kind, change.session, change.action)
        for change in changes
    ] == [
        ("local", "local_owner", labels[0], "user.update"),
        (OWNER, "user", labels[1], "project.access"),
        (ADMIN, "agent", labels[2], "group.add"),
    ]
    # The peer of TestClient, as the transport names it (ADR-046).
    assert {change.client for change in changes} == {"testclient"}
    assert {change.outcome for change in changes} == {"ok"}
    assert len(set(labels)) == 3


# Headers of the generated store's JPEG sheets carry no geotransform (their
# outline comes from the world file); rasterio says so while reading them.
@pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
def test_own_data_visibility_matrix(tmp_path: Path) -> None:
    """Own data, its snapshots and its jobs follow the visibility of the project.

    Under each visibility, for each person and for the computer's owner:
    every route of the project's own data, its ``file:`` and ``snapshot:``
    refs in ``/compare``, its ``project`` filter and its jobs (a snapshot with
    a note, the preview of a file, the scan of its folder) are ``404`` or left
    out for one who does not see the project; a ``preview`` job of a store
    version and a file of the project shows such a person only the version,
    with whole counts. A snapshot needs ``project.write`` (``403``), another
    data folder an administrator, every change the session's CSRF token;
    local mode may do everything.
    """
    with own_data_api(tmp_path, first=("gpkg_layers", "tif_2180"), second=()) as served:
        # Arrange
        routes = _own_routes(served)
        callers = {who: served.caller(who) for who in WHO}
        observed: dict[tuple[str, str], dict[str, object]] = {}

        # Act
        for visibility in VISIBILITY_VALUES:
            share(served.api.state, served.first.access_key, visibility)
            for who in WHO:
                observed[visibility, who] = _own_answers(served, callers[who], routes)
        observed["private", "local"] = _own_answers(served, served.owner, routes)
        _settle(served)

    # Assert
    expected: dict[tuple[str, str], dict[str, object]] = {
        (visibility, who): _own_expected(
            routes,
            sees=who in SEES[visibility],
            manages=who in MANAGES,
            admin=who == "admin",
        )
        for visibility in VISIBILITY_VALUES
        for who in WHO
    }
    expected["private", "local"] = _own_expected(
        routes, sees=True, manages=True, admin=True
    )
    assert [
        (visibility, who, route, observed[visibility, who].get(route), answer)
        for (visibility, who), answers in expected.items()
        for route, answer in answers.items()
        if observed[visibility, who].get(route) != answer
    ] == []
    assert {key: sorted(answers) for key, answers in observed.items()} == {
        key: sorted(answers) for key, answers in expected.items()
    }


type _Event = tuple[int, str, dict[str, Any]]


@dataclass(frozen=True)
class _OwnRoutes:
    """What the matrix asks of the project's own data, prepared by its owner.

    ``ids`` names the project's jobs (``PROBE_JOBS``); ``jobs`` and
    ``streams`` are their details and events as the owner sees them, and
    ``hidden_mixed`` and ``hidden_mixed_events`` the ``mixed`` job as one who
    does not see the project must see it.
    """

    key: str
    reads: dict[str, str]
    """``GET`` routes by name: their addresses."""
    changes: dict[str, tuple[str, str, dict[str, object] | None]]
    """Routes changing something by name: method, address and body."""
    thumbnail: str
    etag: str
    ids: dict[str, str]
    jobs: dict[str, dict[str, Any]]
    streams: dict[str, list[_Event]]
    hidden_mixed: dict[str, Any]
    hidden_mixed_events: list[_Event]


def _own_routes(served: OwnDataApi) -> _OwnRoutes:
    """Add files to the project's data folder, make its jobs, find what to ask.

    As the owner: the ``preview`` job building the local COG of a file,
    snapshots of a GeoPackage, a GeoTIFF and a ZIP (with a note), the scan of
    the folder, and one ``preview`` job of a store version and of a damaged
    file of the project, submitted together as a batch is.
    """
    project = served.first
    owner = served.owner
    _strip_geotiff(project.root / STRIP)
    (project.root / DAMAGED).write_bytes(b"II*\x00")  # a TIFF cut after its signature
    with zipfile.ZipFile(project.root / ARCHIVE, "w") as archive:
        archive.writestr("opis.txt", "Opis danych projektu.\n")
    served.scan()
    built = owner.request("POST", project.url(STRIP, "preview"), json={"force": False})
    assert built.status_code == 202, built.text
    snapshots = {
        path: owner.request("POST", project.url(path, "snapshots"), json={"note": NOTE})
        for path in (GPKG, TIF, ARCHIVE)
    }
    scanned = owner.request("POST", f"/projects/{project.key}/scan")
    assert scanned.status_code == 202, scanned.text
    sheet = entry_of(served.previews.store, "asc_sheet", "regular")
    assert sheet.sha256 is not None
    version = version_ref(GENERATED_STORE, sheet.path)
    damaged = owner.request("GET", project.url(DAMAGED)).json()["content"]["sha256"]
    mixed = served.jobs.submit(
        "preview",
        params={
            "refs": [version, project.ref(DAMAGED)],
            "contents": [sheet.sha256, damaged],
            "force": False,
        },
        actor=LOCAL_OWNER,
    )
    ids = {
        "mixed": mixed.id,
        "own_scan": str(scanned.json()["id"]),
        "preview": str(built.json()["id"]),
        "snapshot": str(snapshots[GPKG].json()["id"]),
    }
    labels: dict[str, str] = {}
    for path, answer in snapshots.items():
        assert answer.status_code == 202, answer.text
        record = served.wait(answer.json()["id"])
        assert record.state == "succeeded" and record.result is not None, record
        labels[path] = str(record.result["label"])
    for job in ids.values():
        assert served.wait(job).state == "succeeded"
    jobs = {
        name: owner.request("GET", f"/jobs/{job}").json() for name, job in ids.items()
    }
    streams = {
        name: _events(owner.request("GET", f"/jobs/{job}/events"))
        for name, job in ids.items()
    }
    # Only the project's damaged file failed: what one not seeing it loses.
    failed = jobs["mixed"]["result"]["failed"]
    assert [entry["ref"] for entry in failed] == [project.ref(DAMAGED)]
    assert jobs["mixed"]["progress"]["failed"] == 1
    raster = _info(served, project.url(TIF, "preview"))
    vector = _info(served, project.url(GPKG, "preview"))
    archive_info = _info(served, project.url(ARCHIVE, "preview"))
    raster_snapshot = _info(served, project.snapshot_url(TIF, labels[TIF]))
    vector_snapshot = _info(served, project.snapshot_url(GPKG, labels[GPKG]))
    archive_snapshot = _info(served, project.snapshot_url(ARCHIVE, labels[ARCHIVE]))
    snapshot_ref = owner.request("GET", project.url(GPKG)).json()["snapshots"][0]["ref"]
    thumbnail = served.get(owner, raster["thumbnail_url"])
    assert thumbnail.status_code == 200, thumbnail.text
    files = f"/projects/{project.key}"
    pair = urlencode({"a": project.ref(GPKG), "b": snapshot_ref})
    mixed_pair = urlencode({"a": version, "b": project.ref(GPKG)})
    return _OwnRoutes(
        key=project.key,
        reads={
            "files": f"{files}/files",
            "card": project.url(GPKG),
            "preview": project.url(TIF, "preview"),
            "preview.png": raster["thumbnail_url"],
            "tile": center_tile_url(raster),
            "features": _features_url(vector),
            "members": archive_info["members_url"],
            "snapshot-plan": project.url(GPKG, "snapshot-plan"),
            "snapshot preview": project.snapshot_url(TIF, labels[TIF]),
            "snapshot preview.png": raster_snapshot["thumbnail_url"],
            "snapshot tile": center_tile_url(raster_snapshot),
            "snapshot features": _features_url(vector_snapshot),
            "snapshot members": archive_snapshot["members_url"],
            "compare file and snapshot": f"/compare?{pair}",
            "compare version and file": f"/compare?{mixed_pair}",
            "slots of project": f"/slots?project={project.key}",
            "footprints of project": (
                f"/map/footprints?bbox={POLAND}&project={project.key}"
            ),
        },
        changes={
            "POST preview": ("POST", project.url(TIF, "preview"), {"force": False}),
            "POST snapshot preview": (
                "POST",
                project.snapshot_url(TIF, labels[TIF]),
                {"force": False},
            ),
            "POST scan": ("POST", f"{files}/scan", None),
            "POST snapshots": ("POST", project.url(GPKG, "snapshots"), {"note": NOTE}),
            "PUT data-dir": ("PUT", f"{files}/data-dir", {"path": None}),
        },
        thumbnail=raster["thumbnail_url"],
        etag=thumbnail.headers["etag"],
        ids=ids,
        jobs=jobs,
        streams=streams,
        hidden_mixed={
            **jobs["mixed"],
            "params": {"refs": [version], "contents": [sheet.sha256], "force": False},
            "result": {**jobs["mixed"]["result"], "failed": []},
        },
        hidden_mixed_events=_without_failures(streams["mixed"]),
    )


def _own_answers(
    served: OwnDataApi, caller: Caller, routes: _OwnRoutes
) -> dict[str, object]:
    """Ask every route of the project's own data and its jobs as ``caller``."""
    answers: dict[str, object] = {
        route: _answer(served.get(caller, url)) for route, url in routes.reads.items()
    }
    again = served.get(caller, routes.thumbnail, etag=routes.etag)
    answers["preview.png again"] = _answer(again)
    for route, (method, path, body) in routes.changes.items():
        unsigned = caller.request(method, path, json=body, csrf=False)
        answers[f"{route} without CSRF"] = _answer(unsigned)
        answer = caller.request(method, path, json=body)
        answers[route] = _answer(answer)
        if route == "POST snapshots" and answer.status_code == 202:
            served.wait(answer.json()["id"])  # one snapshot of a file at a time
    for name, job in routes.ids.items():
        detail = caller.request("GET", f"/jobs/{job}")
        events = caller.request("GET", f"/jobs/{job}/events")
        answers[f"job {name}"] = (
            detail.json() if detail.status_code == 200 else _answer(detail)
        )
        answers[f"job {name} events"] = (
            _events(events) if events.status_code == 200 else _answer(events)
        )
    listed = caller.request("GET", f"/jobs?limit={MAX_PAGE_LIMIT}")
    answers["jobs"] = (_probes(listed, routes), routes.key in listed.text)
    filtered = caller.request(
        "GET", f"/jobs?project={routes.key}&limit={MAX_PAGE_LIMIT}"
    )
    answers["jobs of project"] = (
        _probes(filtered, routes) if filtered.status_code == 200 else _answer(filtered)
    )
    return answers


def _own_expected(
    routes: _OwnRoutes, *, sees: bool, manages: bool, admin: bool
) -> dict[str, object]:
    """Return what one seeing the project, managing it or administering gets."""

    def shown(answer: object) -> object:
        return answer if sees else HIDDEN

    expected: dict[str, object] = {route: shown("200") for route in routes.reads}
    expected["preview.png again"] = shown("304")
    expected.update(
        {f"{route} without CSRF": "403 csrf_rejected" for route in routes.changes}
    )
    expected.update(
        {
            "POST preview": shown("200"),
            "POST snapshot preview": shown("200"),
            "POST scan": shown("202"),
            "POST snapshots": shown("202" if manages else "403 permission_denied"),
            "PUT data-dir": "200" if admin else "403 permission_denied",
        }
    )
    for name in PROBE_JOBS:
        expected[f"job {name}"] = shown(routes.jobs[name])
        expected[f"job {name} events"] = shown(routes.streams[name])
    if not sees:  # its store part stays, with whole counts
        expected["job mixed"] = routes.hidden_mixed
        expected["job mixed events"] = routes.hidden_mixed_events
    # Everyone sees every job of the queue; a job only of the project is
    # listed hidden for one not seeing it (ADR-047 decision 3).
    expected["jobs"] = (
        tuple((name, not sees and name != "mixed") for name in PROBE_JOBS),
        sees,
    )
    expected["jobs of project"] = shown(tuple((name, False) for name in PROBE_JOBS))
    return expected


def _answer(response: httpx.Response) -> str:
    """Return a status, with the problem's reason or code (``403 csrf_rejected``)."""
    if response.headers.get("content-type") == "application/problem+json":
        body = response.json()
        cause = body.get("details", {}).get("reason", body["code"])
        return f"{response.status_code} {cause}"
    return str(response.status_code)


def _events(response: httpx.Response) -> list[_Event]:
    """Parse a job's event stream into ``(id, event, data)``."""
    assert response.headers["content-type"].startswith("text/event-stream")
    events: list[_Event] = []
    for block in response.text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line[:1] != ":"
        )
        if fields:
            data = json.loads(fields["data"])
            events.append((int(fields["id"]), fields["event"], data))
    return events


def _without_failures(events: list[_Event]) -> list[_Event]:
    """Return a ``preview`` job's events with no failure in its result."""
    return [
        (seq, event, {**data, "result": {**data["result"], "failed": []}})
        if "result" in data
        else (seq, event, data)
        for seq, event, data in events
    ]


def _probes(listed: httpx.Response, routes: _OwnRoutes) -> tuple[tuple[str, bool], ...]:
    """Return the names of the project's jobs a page of ``GET /jobs`` holds.

    Each name comes with whether the page marks that job ``hidden``.
    """
    assert listed.status_code == 200, listed.text
    shown = {item["id"]: item["hidden"] for item in listed.json()["items"]}
    return tuple(
        sorted((name, shown[job]) for name, job in routes.ids.items() if job in shown)
    )


def _info(served: OwnDataApi, url: str) -> dict[str, Any]:
    """Return a ``PreviewInfo`` as the owner gets it."""
    answer = served.owner.request("GET", url)
    assert answer.status_code == 200, answer.text
    info: dict[str, Any] = answer.json()
    return info


def _features_url(info: dict[str, Any]) -> str:
    """Return the address of the features of a ``PreviewInfo``'s whole extent."""
    bbox = ",".join(str(value) for value in info["bounds"])
    return str(info["features_url"]).format(bbox=bbox, zoom=FEATURES_ZOOM)


def _strip_geotiff(target: Path) -> None:
    """Write a GeoTIFF in strips, 4100 px wide: its map tiles need a local COG."""
    width, height = 4100, 4
    west, south = 566_100.0, 241_050.0
    transform = from_bounds(west, south, west + width, south + height, width, height)
    with (
        rasterio.Env(GDAL_PAM_ENABLED="NO"),
        rasterio.open(
            target,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="uint8",
            crs="EPSG:2180",
            transform=transform,
        ) as dst,
    ):
        dst.write(np.full((height, width), 100, dtype=np.uint8), 1)


def _settle(served: OwnDataApi) -> None:
    """Wait for the scans the matrix started that still wait or run.

    Waiting ones are listed first: a job only goes from waiting to running.
    """
    active = [
        job.id
        for state in ("queued", "running")
        for job in served.jobs.list(state=state, limit=MAX_PAGE_LIMIT).items
    ]
    for job in active:
        served.wait(job)
