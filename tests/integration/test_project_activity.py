"""A project's activity over HTTP and by command (A-ADR-049 decision 14, plan P5).

The project's entries of the action log: its ``project.*`` entries (created,
changed, pinned, unpinned, exported, shared) and the ``job.*`` entries of its
jobs, done or failed, newest first, paged by a cursor. Another project's
entries and refusals never show; a project the person does not see is
``404``; the client address and the session are not given.
``archiwista project-activity`` prints the route's model. Offline.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import access_key
from archiwista.cli import main
from archiwista.config import AppPaths
from archiwista.jobs.supervisor import action_details
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE, ServedStore, served_store
from tests.fixtures.cli_errors import refusal
from tests.fixtures.permissions import Who, add_people, principal, share

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

PROJECT = "projekt-01"
OTHER_PROJECT = "brak-wersji"
CLIENT = "10.0.0.31"


@contextmanager
def _served(tmp_path: Path) -> Iterator[ServedStore]:
    with served_store(tmp_path) as served:
        add_people(served.api.state)
        yield served


def _access(served: ServedStore, name: str) -> str:
    return access_key(served.store.base / served.store.project(name).path)


def _activity(served: ServedStore, project: str, query: str = "") -> Any:
    response = served.owner.request("GET", f"/projects/{project}/activity{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _job(served: ServedStore, project: str, **changes: Any) -> None:
    """Log the start of a download pinning into ``project``, as the supervisor does."""
    state = served.api.state
    actor = principal(state, "owner")
    details = action_details(
        "download", STORE, {"pin": {"project": project, "group": "NMT"}}
    )
    state.record(actor, "job.start", f"job-{project}", details=details, **changes)


def _cli(capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str) -> Any:
    """Run ``archiwista … --json``; a refusal gives its error document."""
    capsys.readouterr()
    registry = load_registry(cache_dir=paths.cache_dir)
    status = main([*argv, "--json"], registry=registry, paths=paths)
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def test_project_activity_lists_its_changes_and_jobs_newest_first(
    tmp_path: Path,
) -> None:
    """A new project, pins, unpins, an export and a job; nothing of another project."""
    with _served(tmp_path) as served:
        owner = served.owner
        state = served.api.state
        pinned = served.store.project(PROJECT).groups[0].pins[0]
        created = owner.request(
            "POST",
            "/projects",
            json={"path": str(served.store.projects_dir / "nowy"), "name": "Nowy"},
        )
        assert created.status_code == 201, created.text
        new = created.json()["project"]
        steps = [
            owner.request(
                "POST",
                f"/projects/{new}/groups",
                json={
                    "name": "NMT",
                    "from": "file",
                    "versions": [{"store": STORE, "version": pinned.version}],
                },
            ),
            owner.request("PATCH", f"/projects/{new}", json={"description": "Raba"}),
            owner.request("DELETE", f"/projects/{new}/groups/nmt"),
            owner.request("POST", f"/projects/{new}/exports", json={"name": "z"}),
            owner.request(
                "PATCH", f"/projects/{OTHER_PROJECT}", json={"description": "inny"}
            ),
        ]
        _job(served, new, client=CLIENT)
        _job(served, new, outcome="failed")
        _job(served, OTHER_PROJECT)
        state.record(
            principal(state, "other"),
            "permission.denied",
            access_key(served.store.projects_dir / "nowy"),
            outcome="denied",
            details={"action": "project.write"},
        )

        # Act
        answer = _activity(served, new)

    # Assert
    assert [step.status_code for step in steps] == [201, 200, 200, 201, 200]
    assert [(item["action"], item["outcome"]) for item in answer["items"]] == [
        ("job.start", "failed"),
        ("job.start", "ok"),
        ("project.export", "ok"),
        ("project.unpin", "ok"),
        ("project.update", "ok"),
        ("project.pin", "ok"),
        ("project.create", "ok"),
    ]
    assert answer["next_cursor"] is None
    job = answer["items"][1]
    assert job["actor"] == "olga"
    assert job["actor_name"] == "Olga Owczarek"
    assert job["actor_kind"] == "user"
    assert job["details"] == {
        "kind": "download",
        "store": STORE,
        "project": new,
        "group": "NMT",
    }
    created_entry = answer["items"][-1]
    assert (created_entry["actor"], created_entry["actor_name"]) == ("local", None)
    for item in answer["items"]:
        assert set(item) == {
            "id",
            "at",
            "actor",
            "actor_name",
            "actor_kind",
            "action",
            "outcome",
            "details",
        }


@pytest.mark.parametrize(
    ("who", "status"),
    [("owner", 200), ("listed", 200), ("admin", 200), ("other", 404)],
)
def test_project_activity_is_read_by_whoever_sees_the_project(
    tmp_path: Path, who: Who, status: int
) -> None:
    """Shared with listed people: they read it; a person it is hidden from gets 404."""
    with _served(tmp_path) as served:
        state = served.api.state
        share(state, _access(served, PROJECT), "users")
        _job(served, PROJECT)
        person = served.api.session(principal(state, who))

        # Act
        response = person.request("GET", f"/projects/{PROJECT}/activity")
        unknown = person.request("GET", "/projects/brak/activity")

    # Assert
    assert response.status_code == status, response.text
    assert_problem(unknown, 404, "not_found")
    if status == 404:
        assert_problem(response, 404, "not_found")
    else:
        assert [item["action"] for item in response.json()["items"]] == [
            "job.start",
            "project.access",
        ]


def test_project_activity_pages_by_its_cursor(tmp_path: Path) -> None:
    """Every entry once across the pages; a page too large or unknown is refused."""
    with _served(tmp_path) as served:
        for _ in range(5):
            _job(served, PROJECT)
            _job(served, OTHER_PROJECT)
        everything = _activity(served, PROJECT, "?limit=100")

        # Act
        pages = [_activity(served, PROJECT, "?limit=2")]
        while pages[-1]["next_cursor"] is not None:
            pages.append(
                _activity(
                    served, PROJECT, f"?limit=2&cursor={pages[-1]['next_cursor']}"
                )
            )
        too_large = served.owner.request(
            "GET", f"/projects/{PROJECT}/activity?limit=101"
        )
        unknown = served.owner.request("GET", f"/projects/{PROJECT}/activity?actor=x")

    # Assert
    assert [len(page["items"]) for page in pages] == [2, 2, 1]
    assert [item["id"] for page in pages for item in page["items"]] == [
        item["id"] for item in everything["items"]
    ]
    assert len(everything["items"]) == 5
    assert_problem(too_large, 400, "validation_error")
    assert_problem(unknown, 400, "validation_error")


def test_project_activity_command_prints_what_the_route_answers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` is the route's model, with the cursor; a refusal is the route's."""
    with _served(tmp_path) as served:
        paths = served.api.paths
        for _ in range(3):
            _job(served, PROJECT)
        first = _activity(served, PROJECT, "?limit=2")
        second = _activity(served, PROJECT, f"?limit=2&cursor={first['next_cursor']}")

        # Act
        by_cli = _cli(capsys, paths, "project-activity", PROJECT, "--limit", "2")
        next_cli = _cli(
            capsys,
            paths,
            "project-activity",
            PROJECT,
            "--limit",
            "2",
            "--cursor",
            str(by_cli["next_cursor"]),
        )
        unknown = _cli(capsys, paths, "project-activity", "brak")
        invalid = _cli(capsys, paths, "project-activity", PROJECT, "--limit", "0")

    # Assert
    assert (by_cli, next_cli) == (first, second)
    assert unknown["code"] == "not_found"
    assert invalid["code"] == "validation_error"


def test_openapi_documents_the_activity(tmp_path: Path) -> None:
    """The route, its model with an example, and the problems it answers."""
    with _served(tmp_path) as served:
        document = served.owner.request("GET", "/openapi.json").json()

    route = document["paths"]["/api/v1/projects/{project}/activity"]["get"]
    assert route["operationId"] == "get_project_activity"
    assert route["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProjectActivity"
    }
    assert {"400", "404"} <= set(route["responses"])
    assert document["components"]["schemas"]["ProjectActivity"]["examples"]
