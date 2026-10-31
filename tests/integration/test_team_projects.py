"""Projects of every person in team mode (plan v0.4 T7, ADR-039 erratum 3).

A person creates a project where none is and owns it; a directory that was a
project already (an access entry) is changed only by whoever may change
that project, and a producer's own file there makes no project; the owner gives the
project a data folder inside its directory, an administrator anywhere the
rules allow (A-ADR-029 erratum 2); a person's scans of data folders keep to
their limits (ADR-047 decision 4); ``GET /directory`` names whom a project
can be shared with. The server runs in team mode over a marked store with
the real Kartograf plugin, offline, and its jobs wait (``team_api``).
"""

from pathlib import Path

import imgwtools
import pytest

from archiwista.api.owndata import start_own_scan
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER, access_key
from archiwista.config import ConfigStore, DefaultProjectVisibility
from archiwista.index import IndexQueries
from archiwista.projects import PROJECT_FILE
from archiwista.services.owndata import SCAN_INTERVAL_S, SCAN_RUNNING_RETRY_S
from archiwista.state import ActionQuery
from tests.fixtures.api_session import assert_problem
from tests.fixtures.permissions import last_entry, log_entries
from tests.fixtures.team_projects import (
    ADMIN,
    OTHER,
    OWNER,
    TeamApi,
    TeamPlace,
    team_api,
    team_place,
)

DATA_DIR = "/projects/raba/data-dir"


@pytest.fixture
def place(tmp_path: Path) -> TeamPlace:
    """Return a team's store and project directory, the default visibility public."""
    return team_place(tmp_path)


def _created(served: TeamApi, place: TeamPlace, *names: str) -> None:
    """Let kasia create the Kartograf projects ``names``."""
    kasia = served.caller(OWNER)
    for name in names:
        answer = kasia.request("POST", "/projects", json=place.body(name))
        assert answer.status_code == 201, answer.text


@pytest.mark.parametrize("visibility", ["public", "private"])
def test_a_person_creates_a_project_and_owns_it(
    tmp_path: Path, visibility: DefaultProjectVisibility
) -> None:
    """A person's new project is hers, at the default visibility, and logged.

    The answer is its card, which she may change; marek sees it when the
    default is ``public``, an administrator always.
    """
    place = team_place(tmp_path, visibility=visibility)
    with team_api(place) as served:
        # Arrange
        kasia = served.caller(OWNER)

        # Act
        created = kasia.request("POST", "/projects", json=place.body("raba"))
        access = kasia.request("GET", "/projects/raba/access")
        seen = {
            who: served.caller(who).request("GET", "/projects/raba").status_code
            for who in (OTHER, ADMIN)
        }
        entries = served.state.actions(ActionQuery(action="project.create")).entries

    # Assert
    assert created.status_code == 201, created.text
    assert (created.json()["project"], created.json()["project_write"]) == (
        "raba",
        True,
    )
    assert (place.projects / "raba" / PROJECT_FILE).is_file()
    assert access.json() == {
        "project": "raba",
        "owner": OWNER,
        "visibility": visibility,
        "users": [],
        "groups": [],
        "explicit": True,
    }
    assert seen == {OTHER: 200 if visibility == "public" else 404, ADMIN: 200}
    key = access_key(place.projects / "raba")
    (entry,) = entries
    assert (entry.actor, entry.actor_kind, entry.target, entry.outcome) == (
        OWNER,
        "user",
        key,
        "ok",
    )
    assert entry.details == {"name": "raba", "owner": OWNER}
    assert entry.after == {
        "project": key,
        "owner": OWNER,
        "visibility": visibility,
        "users": [],
        "groups": [],
    }


def test_a_directory_with_an_access_entry_is_changed_only_by_who_may(
    place: TeamPlace,
) -> None:
    """A project file where an access entry is needs ``project.write``.

    kasia, refused (``403``), writes nothing; marek, whose entry it is,
    writes the file, and the access entry stays as it was.
    """
    directory = place.projects / "wisla"
    key = access_key(directory)
    with team_api(place) as served:
        # Arrange
        served.state.set_project_access(
            key, owner=OTHER, visibility="public", actor=LOCAL_OWNER
        )
        before = served.state.project_access(key)

        # Act
        denied = served.caller(OWNER).request(
            "POST", "/projects", json=place.body("wisla")
        )
        written_after_denial = (directory / PROJECT_FILE).exists()
        accepted = served.caller(OTHER).request(
            "POST", "/projects", json=place.body("wisla")
        )
        after = served.state.project_access(key)

    # Assert
    assert_problem(denied, 403, "forbidden", "permission_denied")
    assert not written_after_denial
    assert accepted.status_code == 201, accepted.text
    assert (directory / PROJECT_FILE).is_file()
    assert after == before


def test_a_producers_project_file_alone_is_no_project(place: TeamPlace) -> None:
    """A directory holding only ``imgw-project.json`` is new: kasia creates it."""
    directory = place.projects / "wisla"
    imgwtools.init_project(directory, store_dir=place.imgw)
    with team_api(place) as served:
        # Act
        listed = served.caller(OWNER).request("GET", "/projects").json()["items"]
        created = served.caller(OWNER).request(
            "POST", "/projects", json=place.body("wisla")
        )
        access = served.state.project_access(access_key(directory))

    # Assert
    assert listed == []
    assert created.status_code == 201, created.text
    assert (directory / PROJECT_FILE).is_file()
    assert (directory / "imgw-project.json").is_file()
    assert access is not None
    assert access.owner == OWNER


def test_the_owner_sets_a_data_folder_inside_her_project_only(
    place: TeamPlace, tmp_path: Path
) -> None:
    """Outside, through a link out, relative or the project itself: ``400``.

    Each refusal names the problem ``own_data_dir_outside_project`` and
    changes nothing; a folder inside the project's directory, given through
    a link from elsewhere, is saved as its real path (so the link cannot
    lead it out later) and logged with the folder before and after, then the
    scan of the new folder she starts with it (``job.start``).
    """
    project = place.projects / "raba"
    outside = tmp_path / "obce-dane"
    with team_api(place) as served:
        # Arrange
        _created(served, place, "raba")
        kasia = served.caller(OWNER)
        inside = project / "dane-gis"
        inside.mkdir()
        outside.mkdir()
        (project / "na-zewnatrz").symlink_to(outside, target_is_directory=True)
        shortcut = tmp_path / "skrot"
        shortcut.symlink_to(project, target_is_directory=True)
        logged = last_entry(served.state)

        # Act
        refused = {
            name: kasia.request("PUT", DATA_DIR, json={"path": path})
            for name, path in (
                ("outside", str(outside)),
                ("link out", str(project / "na-zewnatrz")),
                ("relative", "raba/dane-gis"),
                ("the project itself", str(project)),
            )
        }
        unchanged = ConfigStore(place.paths.config_file).load()
        changed = kasia.request(
            "PUT", DATA_DIR, json={"path": str(shortcut / "dane-gis")}
        )
        entries = log_entries(served.state, after=logged)
        scan = served.jobs.active_of(OWNER, "own_scan")

    # Assert
    key = access_key(project)
    saved = str(Path(key) / "dane-gis")
    for name, answer in refused.items():
        assert_problem(answer, 400, "validation_error", "invalid_settings")
        problems = answer.json()["details"]["problems"]
        assert [problem["code"] for problem in problems] == [
            "own_data_dir_outside_project"
        ], name
    assert unchanged.own_data_dir(key) == (Path(key) / "dane", "default")
    assert changed.status_code == 200, changed.text
    assert (changed.json()["path"]["local"], changed.json()["source"]) == (
        saved,
        "setting",
    )
    assert scan is not None
    assert [
        (
            entry.actor,
            entry.action,
            entry.target,
            entry.before,
            entry.after,
            entry.details,
        )
        for entry in entries
    ] == [
        (
            OWNER,
            "project.data_dir",
            key,
            {"path": str(Path(key) / "dane"), "source": "default"},
            {"path": saved, "source": "setting"},
            None,
        ),
        (
            OWNER,
            "job.start",
            scan.id,
            None,
            None,
            {"kind": "own_scan", "project": "raba"},
        ),
    ]


def test_a_folder_elsewhere_is_an_administrators_and_others_are_refused(
    place: TeamPlace, tmp_path: Path
) -> None:
    """An administrator sets a folder outside; marek ``403``, hidden ``404``."""
    outside = tmp_path / "obce-dane"
    outside.mkdir()
    with team_api(place) as served:
        # Arrange
        _created(served, place, "raba", "wisla")
        private = served.caller(OWNER).request(
            "PUT", "/projects/wisla/access", json={"visibility": "private"}
        )
        assert private.status_code == 200, private.text
        marek = served.caller(OTHER)

        # Act
        by_admin = served.caller(ADMIN).request(
            "PUT", DATA_DIR, json={"path": str(outside)}
        )
        by_other = marek.request("PUT", DATA_DIR, json={"path": None})
        hidden = marek.request("PUT", "/projects/wisla/data-dir", json={"path": None})
        entries = served.state.actions(ActionQuery(action="project.data_dir")).entries

    # Assert
    assert by_admin.status_code == 200, by_admin.text
    assert by_admin.json()["path"]["local"] == str(outside)
    assert_problem(by_other, 403, "forbidden", "permission_denied")
    assert_problem(hidden, 404, "not_found")
    assert [(entry.actor, entry.after) for entry in entries] == [
        (ADMIN, {"path": str(outside), "source": "setting"})
    ]


def test_scans_of_data_folders_keep_to_the_limits_of_a_person(
    place: TeamPlace,
) -> None:
    """One scan of a person waits or runs, and a folder is asked for once a minute.

    A request joins a waiting scan of the folder (never refused); the
    person's scan of another folder is ``scan_running``; once the scan is
    cancelled, the folder is ``scan_too_soon`` for everyone, by a retry too;
    the computer's owner (``archiwista own-scan``) is not limited.
    """
    with team_api(place) as served:
        # Arrange
        _created(served, place, "raba", "wisla", "san")
        kasia, marek = served.caller(OWNER), served.caller(OTHER)

        # Act
        first = kasia.request("POST", "/projects/raba/scan")
        joined = marek.request("POST", "/projects/raba/scan")
        running = kasia.request("POST", "/projects/wisla/scan")
        served.jobs.cancel(first.json()["id"])
        too_soon = marek.request("POST", "/projects/raba/scan")
        retried = kasia.request("POST", f"/jobs/{first.json()['id']}/retry")
        other = marek.request("POST", "/projects/wisla/scan")
        with IndexQueries(place.paths.index_file) as queries:
            local = [
                start_own_scan(
                    served.jobs,
                    queries,
                    name,
                    principal=LOCAL_OWNER,
                    visible=ALL_PROJECTS,
                )
                for name in ("raba", "san")
            ]
        recorded = served.jobs.list(kind="own_scan").items

    # Assert
    assert first.status_code == 202, first.text
    assert (joined.status_code, joined.json()["id"]) == (202, first.json()["id"])
    assert_problem(running, 429, "rate_limited", "scan_running")
    assert running.headers["retry-after"] == str(SCAN_RUNNING_RETRY_S)
    assert running.json()["details"]["retry_after_s"] == SCAN_RUNNING_RETRY_S
    for refused in (too_soon, retried):
        assert_problem(refused, 429, "rate_limited", "scan_too_soon")
        assert 0 < int(refused.headers["retry-after"]) <= SCAN_INTERVAL_S
    assert other.status_code == 202, other.text
    assert [job.state for job in local] == ["queued", "queued"]
    assert {job.id for job in recorded} == {
        first.json()["id"],
        other.json()["id"],
        *(job.id for job in local),
    }


def test_the_directory_lists_enabled_accounts_and_groups(place: TeamPlace) -> None:
    """Any session, an agent's too: ids and names, no disabled account."""
    with team_api(place) as served:
        # Arrange
        served.state.add_user("jan", name="Jan Nieobecny", actor=LOCAL_OWNER)
        served.state.update_user("jan", disabled=True, actor=LOCAL_OWNER)
        served.state.add_group("gis", name="Dział GIS", actor=LOCAL_OWNER)
        agent = served.caller(OTHER, agent=True)

        # Act
        listed = agent.request("GET", "/directory")

    # Assert
    assert listed.status_code == 200, listed.text
    assert listed.json() == {
        "users": [
            {"id": ADMIN, "name": "Anna Nowak"},
            {"id": OWNER, "name": "Kasia Wrona"},
            {"id": OTHER, "name": "Marek Lis"},
        ],
        "groups": [
            {"id": "gis", "name": "Dział GIS"},
            {"id": "hydro", "name": "Dział hydrologii"},
        ],
    }
