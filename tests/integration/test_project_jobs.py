"""The jobs over a project's groups with real workers (A-ADR-049 decision 11).

The stand-in producer (``tests/fixtures/actions.py``) keeps a station's files
as ``hydro/<station>/<file>``; its source has ``2023.csv`` (label
``2023-12-31``), ``2024.csv`` (``2024-12-31``), ``2025.csv`` (``2025-10-20``)
and ``stations.json``, and its check plans them ``current``, ``newer``,
``missing`` and ``unverifiable``. A file's ``content_sha256`` reads CRLF as LF;
a file of ``derived/`` has no call (D5). Olga owns the public project ``raba``
and every person may write the stores. Each test writes the files it needs,
scans the store and pins them through the API, then runs a job through
``POST /projects/{project}/jobs`` (or ``archiwista project-…``).
"""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.commands import project_jobs as project_job_commands
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.jobs import JobSupervisor
from archiwista.projects import PROJECT_FILE, change_project_file
from archiwista.sources.registry import load_registry
from tests.fixtures.actions import (
    ACTION_WORKER,
    CHECK,
    STORE,
    action_paths,
    action_supervisor,
    standin_in_settings,
    store_root,
)
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import refusal
from tests.fixtures.jobs import worker_path
from tests.fixtures.permissions import add_people, principal, share

JOB_TIMEOUT_S = 90.0
STATION = "150160180"
FOLDER = f"hydro/{STATION}"
DERIVED = f"derived/{STATION}/zlewnia.csv"
LOCAL = "Wodowskaz"
PLAN = "Pobrane"


@dataclass(frozen=True)
class Place:
    """A served installation with Olga's public project and running workers."""

    api: Api
    jobs: JobSupervisor
    paths: AppPaths
    root: Path
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
    """Serve the stand-in's store ``STORE`` and Olga's public project ``raba``."""
    paths = action_paths(tmp_path)
    projects = tmp_path / "projekty"
    projects.mkdir()
    config = ConfigStore(paths.config_file)
    settings = config.load()
    config.save(
        settings.model_copy(
            update={"project_dirs": (projects,), "store_write_for_all": True}
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
            yield Place(
                api,
                jobs,
                paths,
                store_root(tmp_path),
                directory,
                created.json()["project"],
                owner,
            )


def _line(name: str, label: str, end: str = "\n") -> str:
    """Return the content the stand-in gives a station's file of a label."""
    return f"{STATION},{FOLDER}/{name},{label}{end}"


def _write(place: Place, path: str, text: str) -> None:
    target = place.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode())


def _scan(place: Place) -> None:
    """Read the whole store again (and the project file with it)."""
    job = place.jobs.submit(
        "scan", store=STORE, params={"mode": "full"}, actor=LOCAL_OWNER
    )
    ended = place.jobs.wait(job.id, timeout=JOB_TIMEOUT_S)
    assert ended.state == "succeeded", ended.error


def _pin(place: Place, group: str, *versions: str) -> None:
    """Pin the store's versions into a new local group of the project."""
    answer = place.owner.request(
        "POST",
        f"/projects/{place.project}/groups",
        json={
            "name": group,
            "from": "file",
            "versions": [{"store": STORE, "version": v} for v in versions],
        },
    )
    assert answer.status_code in (200, 201), answer.text


def _wait(place: Place, caller: Caller, job_id: str) -> dict[str, Any]:
    place.jobs.wait(job_id, timeout=JOB_TIMEOUT_S)
    detail: dict[str, Any] = caller.request("GET", f"/jobs/{job_id}").json()
    return detail


def _job(place: Place, body: dict[str, Any], caller: Caller | None = None) -> Any:
    """Start a project job, wait for its end; return it as the caller sees it."""
    who = caller or place.owner
    started = who.request("POST", f"/projects/{place.project}/jobs", json=body)
    assert started.status_code == 202, started.text
    assert started.headers["Location"].endswith(f"/jobs/{started.json()['id']}")
    return _wait(place, who, started.json()["id"])


def _states(detail: dict[str, Any]) -> dict[str, str]:
    return {row["version"]: row["status"] for row in detail["result"]["pins"]}


def _file(place: Place) -> Any:
    return json.loads((place.directory / PROJECT_FILE).read_text(encoding="utf-8"))


def test_project_verify_finds_ok_corrupt_missing_content_match_and_no_store(
    place: Place,
) -> None:
    """Pinned files are hashed in the store; another version of the same content.

    ``2025.csv`` was pinned with CRLF line ends; it is gone and the slot holds
    a version kept beside with LF ends: the same content, ``content_match``.
    """
    # Arrange
    _write(place, f"{FOLDER}/2023.csv", _line("2023.csv", "2023-12-31"))
    _write(place, f"{FOLDER}/2024.csv", _line("2024.csv", "2024-06-30"))
    _write(place, f"{FOLDER}/2025.csv", _line("2025.csv", "2025-10-20", "\r\n"))
    _write(place, f"{FOLDER}/stations.json", _line("stations.json", "v3"))
    _scan(place)
    pinned = [f"{FOLDER}/{name}" for name in ("2023.csv", "2024.csv", "2025.csv")]
    _pin(place, LOCAL, *pinned, f"{FOLDER}/stations.json")
    _write(place, f"{FOLDER}/2024.csv", _line("2024.csv", "zmieniony"))
    (place.root / FOLDER / "2025.csv").unlink()
    _write(place, f"{FOLDER}/v2/2025.csv", _line("2025.csv", "2025-10-20"))
    (place.root / FOLDER / "stations.json").unlink()
    _scan(place)
    before = (place.directory / PROJECT_FILE).read_bytes()

    # Act
    detail = _job(
        place,
        {"kind": "verify"},
        place.api.session(principal(place.api.state, "other")),
    )

    # Assert
    assert detail["state"] == "succeeded", detail
    assert (detail["store"], detail["params"]) == (
        None,
        {"project": place.project, "groups": None},
    )
    result = detail["result"]
    assert result["ok"] is False
    assert _states(detail) == {
        f"{FOLDER}/2023.csv": "ok",
        f"{FOLDER}/2024.csv": "corrupt",
        f"{FOLDER}/2025.csv": "content_match",
        f"{FOLDER}/stations.json": "missing",
    }
    found = {row["version"]: row["found"] for row in result["pins"]}
    assert found[f"{FOLDER}/2025.csv"] == f"{FOLDER}/v2/2025.csv"
    assert result["counts"] == {
        "ok": 1,
        "corrupt": 1,
        "missing": 1,
        "content_match": 1,
        "no_store": 0,
    }
    assert (place.directory / PROJECT_FILE).read_bytes() == before

    # Act: the project's store of the stand-in now matches no configured one
    def elsewhere(data: dict[str, Any]) -> None:
        data["stores"][0]["root"] = str(place.root.parent / "gdzie-indziej")

    change_project_file(place.directory, elsewhere)
    _scan(place)
    moved = _job(place, {"kind": "verify", "groups": [LOCAL.upper()]})

    # Assert
    assert moved["params"]["groups"] == [LOCAL]
    assert set(_states(moved).values()) == {"no_store"}


def test_project_check_compares_pins_by_slot_and_reports_added_and_d5(
    place: Place,
) -> None:
    """A plan group by its calls, a local group by each pin's call; D5 refused.

    The plan group of a download lost its ``2025.csv`` pin: that position is
    ``added``. The local ``2019.csv`` is a slot the call no longer selects, and
    the derived file has no call: ``not_checkable`` with the producer's text,
    which the card already knew when it was pinned.
    """
    # Arrange
    started = place.owner.request(
        "POST",
        "/jobs",
        json={
            "kind": "download",
            "store": STORE,
            **CHECK,
            "pin": {"project": place.project, "group": PLAN},
        },
    )
    assert _wait(place, place.owner, started.json()["id"])["state"] == "succeeded"
    unpinned = place.owner.request(
        "POST",
        f"/projects/{place.project}/groups/{PLAN}/unpin",
        json={"pins": [{"producer": "standin", "version": f"{FOLDER}/2025.csv"}]},
    )
    assert unpinned.status_code == 200, unpinned.text
    _write(place, f"{FOLDER}/2019.csv", _line("2019.csv", "2019-12-31"))
    _write(place, DERIVED, "zlewnia\n")
    _scan(place)
    _pin(place, LOCAL, f"{FOLDER}/2019.csv", DERIVED)
    card = place.owner.request("GET", f"/projects/{place.project}").json()

    # Act
    detail = _job(place, {"kind": "check"})

    # Assert
    commands = {
        pin["version"]: pin["command"]
        for group in card["groups"]
        if group["name"] == LOCAL
        for pin in group["pins"]
    }
    assert commands == {f"{FOLDER}/2019.csv": "rebuildable", DERIVED: "not_rebuildable"}
    assert detail["state"] == "partial", detail
    assert _states(detail) == {
        f"{FOLDER}/2023.csv": "current",
        f"{FOLDER}/2024.csv": "newer",
        f"{FOLDER}/stations.json": "unverifiable",
        f"{FOLDER}/2019.csv": "removed",
        DERIVED: "not_checkable",
    }
    rows = {row["version"]: row for row in detail["result"]["pins"]}
    assert rows[f"{FOLDER}/2024.csv"]["available_label"] == "2024-12-31"
    assert "derived" in rows[DERIVED]["detail"]
    assert detail["result"]["added"] == [
        {
            "group": PLAN,
            "unit": STATION,
            "path": f"{FOLDER}/2025.csv",
            "available_label": "2025-10-20",
        }
    ]


def test_project_repin_replaces_pins_and_keeps_those_unchanged(place: Place) -> None:
    """A whole run in update mode pins the newer file; the same one keeps its time."""
    # Arrange
    _write(place, f"{FOLDER}/2023.csv", _line("2023.csv", "2023-12-31"))
    _write(place, f"{FOLDER}/2024.csv", _line("2024.csv", "2024-06-30"))
    _scan(place)
    _pin(place, LOCAL, f"{FOLDER}/2023.csv", f"{FOLDER}/2024.csv")
    (before,) = _file(place)["groups"]
    old = {pin["version"]: pin for pin in before["pins"]}

    # Act
    detail = _job(place, {"kind": "repin", "groups": [LOCAL]})

    # Assert
    assert detail["state"] == "succeeded", detail
    result = detail["result"]
    assert (result["status"], result["written"], result["pins"]) == (
        "replaced",
        True,
        {"kept": 1, "new": 1, "dropped": 0},
    )
    (after,) = _file(place)["groups"]
    new = {pin["version"]: pin for pin in after["pins"]}
    assert new[f"{FOLDER}/2023.csv"] == old[f"{FOLDER}/2023.csv"]
    content = (place.root / FOLDER / "2024.csv").read_bytes()
    assert content.decode() == _line("2024.csv", "2024-12-31")
    assert new[f"{FOLDER}/2024.csv"]["sha256"] != old[f"{FOLDER}/2024.csv"]["sha256"]
    assert new[f"{FOLDER}/2024.csv"]["label"] == "2024-12-31"
    assert new[f"{FOLDER}/2024.csv"]["pinned_by"] == "olga"


def test_project_repin_of_a_partial_run_changes_no_pin(place: Place) -> None:
    """Station ``9…`` fails its ``2025.csv``: the files stay, the pins do not move."""
    # Arrange
    folder = "hydro/950160180"
    _write(place, f"{folder}/2024.csv", f"950160180,{folder}/2024.csv,2024-06-30\n")
    _scan(place)
    _pin(place, LOCAL, f"{folder}/2024.csv")
    before = (place.directory / PROJECT_FILE).read_bytes()

    # Act
    detail = _job(place, {"kind": "repin", "groups": [LOCAL]})

    # Assert
    assert detail["state"] == "partial", detail
    assert (detail["result"]["status"], detail["result"]["written"]) == (
        "unchanged",
        False,
    )
    assert (place.directory / PROJECT_FILE).read_bytes() == before
    assert "2024-12-31" in (place.root / folder / "2024.csv").read_text()


def test_project_repin_of_a_plan_group_pins_files_without_a_version_path(
    place: Place, standin: ModuleType
) -> None:
    """A run naming no version of a file: its pin is the slot's current version.

    The download kept the store's older ``2024.csv``; the run in update mode
    fetches it again from the source and its pin follows.
    """
    # Arrange
    _write(place, f"{FOLDER}/2024.csv", _line("2024.csv", "2024-06-30"))
    started = place.owner.request(
        "POST",
        "/jobs",
        json={
            "kind": "download",
            "store": STORE,
            **CHECK,
            "pin": {"project": place.project, "group": PLAN},
        },
    )
    assert _wait(place, place.owner, started.json()["id"])["state"] == "succeeded"
    (before,) = _file(place)["groups"]
    (place.root / standin.UNVERSIONED).touch()

    # Act
    detail = _job(place, {"kind": "repin", "groups": [PLAN]})

    # Assert
    assert detail["state"] == "succeeded", detail
    assert detail["result"]["pins"] == {"kept": 3, "new": 1, "dropped": 0}
    (after,) = _file(place)["groups"]
    pinned = {pin["version"]: pin["sha256"] for pin in after["pins"]}
    assert sorted(pinned) == sorted(pin["version"] for pin in before["pins"])
    assert pinned == {
        path: hashlib.sha256((place.root / path).read_bytes()).hexdigest()
        for path in pinned
    }


def test_project_restore_gives_restored_content_match_not_restored_and_d5(
    place: Place,
) -> None:
    """Missing pins are fetched again in default mode; the file is never written."""
    # Arrange
    _write(place, f"{FOLDER}/2023.csv", _line("2023.csv", "2023-12-31"))
    _write(place, f"{FOLDER}/2024.csv", _line("2024.csv", "2024-06-30"))
    _write(place, f"{FOLDER}/2025.csv", _line("2025.csv", "2025-10-20", "\r\n"))
    _write(place, f"{FOLDER}/2019.csv", _line("2019.csv", "2019-12-31"))
    _write(place, DERIVED, "zlewnia\n")
    _write(place, "hydro/150160181/2023.csv", "150160181,inna,2023-12-31\n")
    _scan(place)
    names = ("2023.csv", "2024.csv", "2025.csv", "2019.csv")
    _pin(place, LOCAL, *(f"{FOLDER}/{name}" for name in names), DERIVED)
    for path in (*(f"{FOLDER}/{name}" for name in names), DERIVED):
        (place.root / path).unlink()
    _scan(place)
    before = (place.directory / PROJECT_FILE).read_bytes()

    # Act
    detail = _job(place, {"kind": "restore"})

    # Assert
    assert detail["state"] == "partial", detail
    assert _states(detail) == {
        f"{FOLDER}/2023.csv": "restored",
        f"{FOLDER}/2024.csv": "not_restored",
        f"{FOLDER}/2025.csv": "content_match",
        f"{FOLDER}/2019.csv": "not_restored",
        DERIVED: "not_restorable",
    }
    reasons = {row["version"]: row["reason"] for row in detail["result"]["pins"]}
    assert reasons[f"{FOLDER}/2024.csv"] == "other_content"
    assert reasons[f"{FOLDER}/2019.csv"] == "not_returned"
    assert (place.directory / PROJECT_FILE).read_bytes() == before
    card = place.owner.request("GET", f"/projects/{place.project}").json()
    states = {pin["version"]: pin["state"] for pin in card["groups"][0]["pins"]}
    assert states[f"{FOLDER}/2023.csv"] == "ok"


def test_project_jobs_refuse_before_a_job_and_ask_again_on_retry(
    place: Place, tmp_path: Path
) -> None:
    """Permissions, groups, D5, one job per project, offline mode, retries."""
    # Arrange
    _write(place, f"{FOLDER}/2023.csv", _line("2023.csv", "2023-12-31"))
    _write(place, DERIVED, "zlewnia\n")
    _write(place, "hydro/150160181/2023.csv", "150160181,inna,2023-12-31\n")
    _scan(place)
    _pin(place, LOCAL, f"{FOLDER}/2023.csv")
    _pin(place, "Pochodne", DERIVED)
    other = place.api.session(principal(place.api.state, "other"))
    url = f"/projects/{place.project}/jobs"

    # Act
    denied = other.request("POST", url, json={"kind": "restore"})
    no_group = place.owner.request("POST", url, json={"kind": "repin"})
    two = place.owner.request("POST", url, json={"kind": "repin", "groups": ["a", "b"]})
    unknown = place.owner.request("POST", url, json={"kind": "check", "groups": ["x"]})
    derived = place.owner.request(
        "POST", url, json={"kind": "repin", "groups": ["Pochodne"]}
    )
    (place.root / ".standin-hold").touch()
    (place.root / FOLDER / "2023.csv").unlink()
    (place.root / DERIVED).unlink()
    _scan(place)
    held = place.owner.request("POST", url, json={"kind": "restore", "groups": [LOCAL]})
    second = place.owner.request("POST", url, json={"kind": "verify"})
    (place.root / ".standin-hold").unlink()
    ended = _wait(place, place.owner, held.json()["id"])
    failed = _job(place, {"kind": "restore", "groups": ["Pochodne"]})
    retried = other.request("POST", f"/jobs/{failed['id']}/retry")
    share(place.api.state, access_key(place.directory), "private")
    hidden = other.request("POST", url, json={"kind": "verify"})

    # Assert
    assert_problem(denied, 403, "forbidden", "permission_denied")
    assert no_group.status_code == 400
    assert two.status_code == 400
    assert_problem(unknown, 404, "not_found")
    assert_problem(derived, 422, "unsupported", reason="command_not_rebuildable")
    assert held.status_code == 202, held.text
    assert_problem(second, 409, "conflict")
    assert second.json()["details"]["job"]["id"] == held.json()["id"]
    assert ended["state"] == "succeeded", ended
    assert failed["state"] == "failed", failed
    assert failed["error"]["details"]["reason"] == "run_failed"
    assert_problem(retried, 403, "forbidden", "permission_denied")
    assert_problem(hidden, 404, "not_found")


def test_project_verify_from_the_command_line_equals_the_api(
    place: Place, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``project-verify`` prints the job the route starts; offline refuses a check."""
    # Arrange
    _write(place, f"{FOLDER}/2023.csv", _line("2023.csv", "2023-12-31"))
    _scan(place)
    _pin(place, LOCAL, f"{FOLDER}/2023.csv")

    def supervisor(paths: AppPaths, service: SettingsService) -> JobSupervisor:
        return JobSupervisor(paths, service, worker_command=ACTION_WORKER)

    monkeypatch.setattr(project_job_commands, "JobSupervisor", supervisor)
    registry = load_registry(cache_dir=place.paths.cache_dir)

    def cli(*argv: str) -> Any:
        capsys.readouterr()
        status = main([*argv, "--json"], registry=registry, paths=place.paths)
        captured = capsys.readouterr()
        if status == 0:
            return json.loads(captured.out)
        return refusal(captured.out, captured.err, status)

    # Act
    printed = cli("project-verify", place.project, LOCAL)
    served = _job(place, {"kind": "verify", "groups": [LOCAL]})
    config = ConfigStore(place.paths.config_file)
    config.save(config.load().model_copy(update={"offline": True}))
    offline = cli("project-check", place.project)

    # Assert
    assert printed["state"] == "succeeded", printed
    assert printed["result"]["pins"] == served["result"]["pins"]
    assert printed["params"] == served["params"]
    assert offline["details"]["reason"] == "offline_mode"
