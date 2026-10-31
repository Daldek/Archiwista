"""A download of the plan window that pins into a project (A-ADR-049 decision 9).

The stand-in producer (``tests/fixtures/actions.py``) fetches a station's files
in real workers of ``ACTION_WORKER``; its check plans ``2023.csv`` current,
``2024.csv`` newer, ``2025.csv`` missing and ``stations.json`` unverifiable.
Olga owns the public project ``raba`` and every person may write the stores.
``POST /jobs`` with ``pin`` checks the project before a job exists; the worker
writes the group (origin ``plan``) only when the download succeeded, from the
files it fetched and the positions of the plan the index holds after the
rescan. ``archiwista jobs start … --pin … --pin-group …`` refuses alike.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from archiwista.auth import access_key
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore, StoreConfig
from archiwista.jobs import JobSupervisor
from archiwista.projects import PROJECT_FILE, change_project_file
from archiwista.sources.registry import load_registry
from tests.fixtures.actions import (
    CHECK,
    STATION,
    STORE,
    action_paths,
    action_supervisor,
    standin_in_settings,
    station_calls,
    store_root,
)
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.jobs import worker_path
from tests.fixtures.permissions import add_people, log_entries, principal, share

JOB_TIMEOUT_S = 90.0
OTHER_STORE = "zapas"
FOLDER = "hydro/150160180"
GROUP = "Wodowskaz 150160180"
CHECK_BODY: dict[str, Any] = {"kind": "check", "store": STORE, **CHECK}
DOWNLOAD_BODY: dict[str, Any] = {**CHECK_BODY, "kind": "download"}


@dataclass(frozen=True)
class Place:
    """A served installation with Olga's public project and running workers."""

    api: Api
    jobs: JobSupervisor
    paths: AppPaths
    directory: Path
    project: str
    owner: Caller


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers, in every store's settings."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    return module


@pytest.fixture
def place(tmp_path: Path, standin: ModuleType) -> Iterator[Place]:
    """Serve the stand-in's stores ``STORE`` and ``OTHER_STORE`` and ``raba``."""
    paths = action_paths(tmp_path)
    projects = tmp_path / "projekty"
    projects.mkdir()
    (tmp_path / OTHER_STORE).mkdir()
    config = ConfigStore(paths.config_file)
    settings = config.load()
    other = StoreConfig(
        id=OTHER_STORE, name="Zapas", kartograf=tmp_path / OTHER_STORE, kind="local"
    )
    config.save(
        settings.model_copy(
            update={
                "stores": (*settings.stores, other),
                "project_dirs": (projects,),
                "store_write_for_all": True,
            }
        )
    )
    with action_supervisor(paths) as jobs:
        registry = load_registry(cache_dir=paths.cache_dir)
        with running_api(paths, registry, jobs=jobs) as api:
            add_people(api.state)
            owner = api.session(principal(api.state, "owner"))
            directory = projects / "raba"
            created = owner.request("POST", "/projects", json={"path": str(directory)})
            assert created.status_code == 201, created.text
            share(api.state, access_key(directory), "public")
            yield Place(api, jobs, paths, directory, created.json()["project"], owner)


def _file(place: Place) -> Any:
    return json.loads((place.directory / PROJECT_FILE).read_text(encoding="utf-8"))


def _pinned(place: Place, body: dict[str, Any], group: str = GROUP) -> dict[str, Any]:
    """Return ``body`` pinning into ``group`` of the project."""
    return {**body, "pin": {"project": place.project, "group": group}}


def _run(place: Place, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    """Start a job, wait for its end; return it as ``caller`` sees it."""
    started = caller.request("POST", "/jobs", json=body)
    assert started.status_code == 202, started.text
    place.jobs.wait(started.json()["id"], timeout=JOB_TIMEOUT_S)
    detail: dict[str, Any] = caller.request(
        "GET", f"/jobs/{started.json()['id']}"
    ).json()
    return detail


def _cli(capsys: pytest.CaptureFixture[str], place: Place, *argv: str) -> Any:
    """Run ``archiwista jobs … --json``; a refusal gives its error document."""
    capsys.readouterr()
    status = main(
        ["jobs", *argv, "--json"],
        registry=load_registry(cache_dir=place.paths.cache_dir),
        paths=place.paths,
    )
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def _start_argv(body: dict[str, Any]) -> list[str]:
    """Return the arguments of ``jobs start`` that ask what ``body`` asks."""
    argv = ["start", body["kind"], body["producer"], "--store", body["store"]]
    for call in body["calls"]:
        argv += ["--call", json.dumps(call)]
    pin = body["pin"]
    return [*argv, "--pin", pin["project"], "--pin-group", pin["group"]]


def test_a_planned_download_pins_its_files_and_the_plans_held_positions(
    place: Place, tmp_path: Path
) -> None:
    """The group, origin `plan`, pins the run's files and what the store holds.

    The store already holds the current ``2023.csv``: the run leaves it and
    the index holds it after the rescan, so it is pinned; the unverifiable
    ``stations.json`` lies nowhere and is reported ``not_in_store``.
    """
    # Arrange
    held = store_root(tmp_path) / FOLDER / "2023.csv"
    held.parent.mkdir(parents=True)
    held.write_text(f"150160180,{FOLDER}/2023.csv,2023-12-31\n", encoding="utf-8")
    checked = _run(place, place.owner, CHECK_BODY)

    # Act
    detail = _run(
        place, place.owner, _pinned(place, {**DOWNLOAD_BODY, "plan_job": checked["id"]})
    )
    listed = place.owner.request("GET", f"/jobs?project={place.project}")
    card = place.owner.request("GET", f"/projects/{place.project}")

    # Assert
    assert detail["state"] == "succeeded", detail
    assert detail["params"]["pin"] == {"project": place.project, "group": GROUP}
    assert detail["result"]["pin"] == {
        "project": place.project,
        "group": GROUP,
        "pins": 3,
        "not_pinned": [{"path": f"{FOLDER}/stations.json", "reason": "not_in_store"}],
        "written": True,
    }
    data = _file(place)
    assert data["stores"] == [
        {"producer": "standin", "root": str(store_root(tmp_path))}
    ]
    (group,) = data["groups"]
    assert (group["name"], group["origin"]) == (
        GROUP,
        {
            "kind": "plan",
            "producer": "standin",
            "calls": [{"command": "series fetch", "options": STATION}],
        },
    )
    assert sorted(pin["version"] for pin in group["pins"]) == [
        f"{FOLDER}/2023.csv",
        f"{FOLDER}/2024.csv",
        f"{FOLDER}/2025.csv",
    ]
    files = {item["path"]: item for item in detail["result"]["files"]}
    for pin in group["pins"]:
        content = (store_root(tmp_path) / pin["version"]).read_bytes()
        assert (pin["producer"], pin["size_bytes"], pin["unit"]) == (
            "standin",
            len(content),
            "150160180",
        )
        assert pin["pinned_by"] == "olga"
        if pin["version"] in files:
            assert pin["sha256"] == files[pin["version"]]["sha256"]
    assert [job["id"] for job in listed.json()["items"]] == [detail["id"]]
    assert [item["name"] for item in card.json()["groups"]] == [GROUP]
    (started,) = [
        entry
        for entry in log_entries(place.api.state)
        if entry.action == "job.start" and entry.target == detail["id"]
    ]
    assert started.details is not None
    assert (started.details["project"], started.details["group"]) == (
        place.project,
        GROUP,
    )


def test_a_partial_download_pins_nothing_and_says_so(place: Place) -> None:
    """A failed unit leaves the project unchanged; the summary's `pin` tells why."""
    # Act
    detail = _run(
        place,
        place.owner,
        _pinned(place, {**DOWNLOAD_BODY, "calls": station_calls("999", "150160180")}),
    )

    # Assert
    assert detail["state"] == "partial", detail
    assert detail["result"]["files"]
    assert detail["result"]["pin"] == {
        "project": place.project,
        "group": GROUP,
        "written": False,
        "reason": "job_partial",
    }
    assert _file(place).get("groups", []) == []


def _taken(data: dict[str, Any]) -> None:
    data.setdefault("groups", []).append(
        {
            "name": GROUP.upper(),
            "origin": {"kind": "local", "selections": [{"from": "file"}]},
            "pins": [],
        }
    )


@pytest.mark.parametrize(
    ("case", "status", "code", "reason"),
    [
        ("group_exists", 409, "conflict", "group_exists"),
        ("other_store", 409, "conflict", "other_store"),
        ("invalid_group_name", 400, "validation_error", "invalid_group_name"),
        ("unknown_project", 404, "not_found", None),
    ],
)
def test_a_pin_the_project_refuses_is_refused_before_a_job(
    place: Place,
    standin: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    status: int,
    code: str,
    reason: str | None,
) -> None:
    """A taken name, another store, a bad name, no project: no job, the CLI agrees."""
    # Arrange
    body = _pinned(place, DOWNLOAD_BODY)
    if case == "group_exists":
        change_project_file(place.directory, _taken)
    elif case == "other_store":
        root = str(tmp_path / OTHER_STORE)
        change_project_file(
            place.directory,
            lambda data: data.setdefault("stores", []).append(
                {"producer": "standin", "root": root}
            ),
        )
    elif case == "invalid_group_name":
        body = _pinned(place, DOWNLOAD_BODY, group="NMT/2023")
    else:
        body = {**body, "pin": {"project": "nieznany", "group": GROUP}}

    # Act
    refused = place.owner.request("POST", "/jobs", json=body)
    printed = _cli(capsys, place, *_start_argv(body))

    # Assert
    assert_problem(refused, status, code, reason)
    assert_same_error(printed, refused.json())
    assert place.jobs.list().items == ()
    assert [call for call in standin.CALLS if call[0] == "run_command"] == []


def test_a_pin_needs_the_permission_to_change_the_project(place: Place) -> None:
    """Igor sees the public project and may write the stores, not change it.

    Neither a download that pins nor a retry of Olga's pinned download that
    ended partial starts a job for him; Olga's retry does.
    """
    # Arrange
    other = place.api.session(principal(place.api.state, "other"))
    failed = _run(
        place,
        place.owner,
        _pinned(place, {**DOWNLOAD_BODY, "calls": station_calls("999")}),
    )

    # Act
    started = other.request("POST", "/jobs", json=_pinned(place, DOWNLOAD_BODY))
    retried = other.request("POST", f"/jobs/{failed['id']}/retry")
    again = place.owner.request("POST", f"/jobs/{failed['id']}/retry")

    # Assert
    assert failed["state"] in ("failed", "partial"), failed
    assert_problem(started, 403, "forbidden", "permission_denied")
    assert_problem(retried, 403, "forbidden", "permission_denied")
    assert again.status_code == 202, again.text
    assert again.json()["params"]["pin"] == {"project": place.project, "group": GROUP}
