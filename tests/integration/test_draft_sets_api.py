"""Sets in the making: open, close, reopen, uncall (A-ADR-049 erratum 6, plan A2).

The store ``zespol`` holds Kartograf's sheets ``A`` (a current and an older
version) and ``B`` and an IMGW station series; a supervisor starts no job, so
a job submitted waits. Olga owns the public project ``raba``. ``POST
…/groups`` with ``open`` writes a set in the making, ``…/close`` freezes it
with ``pins_sha256`` (refused, in order, ``set_closed``, ``set_job_active``,
``set_empty``, ``set_pins_not_ok``), ``…/reopen`` opens it again and
``DELETE …/calls/{call}`` removes a call with the pins only it pinned; the
commands ``project-draft``, ``project-close`` and ``project-reopen`` do the
same.
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter, initialize
from archiwista.jobs import JobSupervisor
from archiwista.projects import PROJECT_FILE, change_project_file
from archiwista.projects.document import pins_digest
from archiwista.services.projects import record_changed
from archiwista.sources import SourceEntry, SourceSegment
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.index_data import (
    NMT,
    PRODUCER,
    STORE,
    link,
    slot_path,
    version,
    write_pass,
)
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import add_people, log_entries, principal, share

SHEET_A = slot_path(NMT, "M-34-1-A")
SHEET_B = slot_path(NMT, "M-34-1-B")
A_CURRENT = version(SHEET_A, "2024-05-01_1", 1)
A_OLDER = version(SHEET_A, "2016-06-01_1", 2)
B_CURRENT = version(SHEET_B, "2023-04-01_1", 3)
GONE = "nmt/pl_1992_1m_evrf2007/versions/M-34-1-Z/2020-01-01_1_00000000/Z.asc"
HYDRO = "hydro/imgw_daily"
CALL_A = {
    "command": "elevation download",
    "options": {"product": "nmt", "sheet": ["M-34-1-A"], "year": 2016},
}
CALL_B = {
    "command": "elevation download",
    "options": {"product": "nmt", "sheet": ["M-34-1-B"], "year": 2023},
}
CALL_C = {
    "command": "elevation download",
    "options": {"product": "nmt", "sheet": ["M-34-1-A"], "year": 2024},
}


def _path(entry: SourceEntry) -> str:
    return entry.relative_path.as_posix()


def _station() -> SourceEntry:
    station = version(slot_path(HYDRO, "150160180", ".csv"), "2024-12-31_1", 9)
    assert station.meta is not None
    return replace(
        station,
        producer="obserwator",
        meta=replace(station.meta, producer="obserwator"),
    )


STATION = _station()


@dataclass(frozen=True)
class Place:
    """A served installation with Olga's project and a supervisor that waits."""

    api: Api
    jobs: JobSupervisor
    paths: AppPaths
    directory: Path
    project: str
    owner: Caller

    @property
    def groups(self) -> str:
        """Return the route of the project's groups."""
        return f"/projects/{self.project}/groups"


@pytest.fixture
def place(tmp_path: Path) -> Iterator[Place]:
    """Serve the index above; Olga owns the public project ``raba``."""
    kartograf, obserwator = (
        tmp_path / "nas" / "kartograf",
        tmp_path / "nas" / "obserwator",
    )
    projects = tmp_path / "nas" / "projekty"
    for directory in (kartograf, obserwator, projects):
        directory.mkdir(parents=True)
    paths = local_paths(tmp_path)
    store = StoreConfig(
        id=STORE,
        name="Zespół",
        kartograf=kartograf,
        obserwator=obserwator,
        kind="local",
    )
    ConfigStore(paths.config_file).save(
        AppSettings(stores=(store,), project_dirs=(projects,), store_write_for_all=True)
    )
    segment = SourceSegment(HYDRO, "hydro", "PL", "pl.imgw.daily", "Dobowe", True)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: store.roots()})
        write_pass(
            writer,
            [
                A_CURRENT,
                A_OLDER,
                B_CURRENT,
                link(SHEET_A, A_CURRENT),
                link(SHEET_B, B_CURRENT),
            ],
        )
        writer.write_segments(STORE, "obserwator", [segment])
        writer.begin_pass(STORE, "obserwator", segment=None, slots=None, full=False)
        writer.write_entries([STATION])
        writer.finish_pass()
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    state = StateStore(paths.state_file)
    with (
        JobSupervisor(paths, settings, max_jobs=0, record=state.record) as jobs,
        running_api(paths, registry, jobs=jobs) as api,
    ):
        add_people(api.state)
        owner = api.session(principal(api.state, "owner"))
        directory = projects / "raba"
        created = owner.request("POST", "/projects", json={"path": str(directory)})
        assert created.status_code == 201, created.text
        share(api.state, access_key(directory), "public")
        yield Place(api, jobs, paths, directory, created.json()["project"], owner)


def _file(place: Place) -> Any:
    return json.loads((place.directory / PROJECT_FILE).read_text(encoding="utf-8"))


def _group(place: Place, name: str) -> dict[str, Any]:
    return next(item for item in _file(place)["groups"] if item["name"] == name)


def _card_group(card: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in card["groups"] if item["name"] == name)


def _versions(*entries: SourceEntry) -> list[dict[str, str]]:
    return [{"store": STORE, "version": _path(entry)} for entry in entries]


def _draft(place: Place, name: str, *entries: SourceEntry) -> dict[str, Any]:
    """Write an open set ``name``, empty or pinning ``entries``."""
    body: dict[str, Any] = {"name": name, "open": True}
    if entries:
        body.update({"from": "file", "versions": _versions(*entries)})
    made = place.owner.request("POST", place.groups, json=body)
    assert made.status_code == 201, made.text
    return dict(made.json())


def _change(place: Place, change: Callable[[dict[str, Any]], None]) -> None:
    """Change the project file outside the routes and record it in the index."""
    change_project_file(place.directory, change)
    record_changed(
        load_registry(cache_dir=place.paths.cache_dir),
        ConfigStore(place.paths.config_file).load(),
        place.paths.index_file,
        place.directory,
    )


def _as_plan(name: str, calls: list[dict[str, Any]], places: dict[str, Any]) -> Any:
    """Return a change making group ``name`` a plan group of ``calls``.

    ``places`` maps a pin's version to its ``calls`` (``None``: no member).
    """

    def change(data: dict[str, Any]) -> None:
        group = next(item for item in data["groups"] if item["name"] == name)
        group["origin"] = {
            "kind": "plan",
            "producer": PRODUCER,
            "calls": calls,
            "selections": group["origin"]["selections"],
        }
        for pin in group["pins"]:
            held = places[pin["version"]]
            if held is None:
                pin.pop("calls", None)
            else:
                pin["calls"] = held

    return change


def _waiting_download(place: Place, group: str) -> Any:
    """Submit a download adding to ``group``; no job starts, so it waits."""
    return place.jobs.submit(
        "download",
        store=STORE,
        params={
            "producer": PRODUCER,
            "calls": [CALL_A],
            "pin": {"project": place.project, "group": group, "add": True},
        },
        actor=LOCAL_OWNER,
    )


def _cli(capsys: pytest.CaptureFixture[str], place: Place, *argv: str) -> Any:
    """Run ``archiwista … --json``; a refusal gives its error document."""
    capsys.readouterr()
    status = main(
        [*argv, "--json"],
        registry=load_registry(cache_dir=place.paths.cache_dir),
        paths=place.paths,
    )
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def test_a_draft_takes_pins_and_closes_with_the_digest_of_its_pins(
    place: Place,
) -> None:
    """Empty open draft → pins added → closed by Olga with ``pins_sha256``."""
    # Arrange
    drafted = _draft(place, "Szkic")
    written_draft = _group(place, "Szkic")
    added = place.owner.request(
        "POST",
        f"{place.groups}/Szkic/pins",
        json={"from": "file", "versions": _versions(B_CURRENT, A_CURRENT)},
    )
    assert added.status_code == 200, added.text

    # Act
    closed = place.owner.request("POST", f"{place.groups}/szkic/close")

    # Assert
    assert (drafted["group"], drafted["pinned"]) == ("Szkic", 0)
    assert written_draft["state"] == "open"
    assert written_draft["pins"] == []
    assert closed.status_code == 200, closed.text
    written = _group(place, "Szkic")
    expected = pins_digest(
        (pin["producer"], pin["version"], pin["sha256"]) for pin in written["pins"]
    )
    assert (written["state"], written["closed_by"], written["pins_sha256"]) == (
        "closed",
        "olga",
        expected,
    )
    card = _card_group(closed.json(), "Szkic")
    assert (card["state"], card["closed_by"], card["pins_sha256"]) == (
        "closed",
        "olga",
        expected,
    )
    assert card["digest_state"] == "ok"
    assert card["closed_at"] is not None
    (entry,) = [
        item
        for item in log_entries(place.api.state)
        if item.action == "project.set_close"
    ]
    assert entry.details == {"group": "Szkic", "pins": 2, "pins_sha256": expected}
    assert entry.target == access_key(place.directory)


def test_closing_refuses_in_order_and_leaves_the_file_as_it_was(
    place: Place,
) -> None:
    """``set_closed`` before the job, the job before ``set_empty``, then pins."""
    # Arrange
    made = place.owner.request(
        "POST",
        place.groups,
        json={"name": "Gotowy", "from": "file", "versions": _versions(A_OLDER)},
    )
    assert made.status_code == 201, made.text
    _draft(place, "Szkic")
    _draft(place, "Pusty")
    _draft(place, "Zły", A_CURRENT, B_CURRENT)

    def spoil(data: dict[str, Any]) -> None:
        group = next(item for item in data["groups"] if item["name"] == "Zły")
        group["pins"][1]["sha256"] = "f" * 64
        group["pins"].append({**group["pins"][0], "version": GONE})

    _change(place, spoil)
    _waiting_download(place, "gotowy")
    job = _waiting_download(place, "SZKIC")
    before = (place.directory / PROJECT_FILE).read_bytes()

    # Act
    answers = {
        name: place.owner.request("POST", f"{place.groups}/{name}/close")
        for name in ("Gotowy", "Szkic", "Pusty", "Zły", "Brak")
    }

    # Assert
    assert_problem(answers["Gotowy"], 409, "conflict", "set_closed")
    assert_problem(answers["Szkic"], 409, "conflict", "set_job_active")
    assert answers["Szkic"].json()["details"] == {
        "reason": "set_job_active",
        "group": "Szkic",
        "job": {"id": job.id, "kind": "download", "state": "queued"},
    }
    assert_problem(answers["Pusty"], 409, "conflict", "set_empty")
    assert_problem(answers["Zły"], 409, "conflict", "set_pins_not_ok")
    details = answers["Zły"].json()["details"]
    assert details["counts"] == {"missing": 1, "sha256_mismatch": 1, "unknown": 0}
    assert sorted((pin["version"], pin["state"]) for pin in details["pins"]) == [
        (_path(B_CURRENT), "sha256_mismatch"),
        (GONE, "missing"),
    ]
    assert_problem(answers["Brak"], 404, "not_found", "group_not_found")
    assert (place.directory / PROJECT_FILE).read_bytes() == before


def test_a_closed_set_refuses_changes_until_it_is_reopened(place: Place) -> None:
    """Pins, unpins and a re-pin are refused; reopening drops the closing."""
    # Arrange
    _draft(place, "Zestaw", A_CURRENT, B_CURRENT)
    closed = place.owner.request("POST", f"{place.groups}/Zestaw/close")
    assert closed.status_code == 200, closed.text
    sealed = _group(place, "Zestaw")
    pin = {"producer": PRODUCER, "version": _path(B_CURRENT)}

    # Act
    add = place.owner.request(
        "POST",
        f"{place.groups}/Zestaw/pins",
        json={"from": "file", "versions": _versions(A_OLDER)},
    )
    unpin = place.owner.request(
        "POST", f"{place.groups}/Zestaw/unpin", json={"pins": [pin]}
    )
    repin = place.owner.request(
        "POST",
        f"/projects/{place.project}/jobs",
        json={"kind": "repin", "groups": ["Zestaw"]},
    )
    refused = _file(place)
    reopened = place.owner.request("POST", f"{place.groups}/zestaw/reopen")
    again = place.owner.request("POST", f"{place.groups}/Zestaw/reopen")
    unpinned = place.owner.request(
        "POST", f"{place.groups}/Zestaw/unpin", json={"pins": [pin]}
    )

    # Assert
    assert_problem(add, 409, "conflict", "set_closed")
    assert_problem(unpin, 409, "conflict", "set_closed")
    assert_problem(repin, 409, "conflict", "set_closed")
    assert _group_of(refused, "Zestaw") == sealed
    assert reopened.status_code == 200, reopened.text
    card = _card_group(reopened.json(), "Zestaw")
    assert (card["state"], card["closed_at"], card["closed_by"]) == ("open", None, None)
    assert (card["pins_sha256"], card["digest_state"]) == (None, None)
    assert_problem(again, 409, "conflict", "set_open")
    assert unpinned.status_code == 200, unpinned.text
    written = _group(place, "Zestaw")
    assert written["state"] == "open"
    assert not {"closed_at", "closed_by", "pins_sha256"} & set(written)
    assert [item["version"] for item in written["pins"]] == [_path(A_CURRENT)]
    (entry,) = [
        item
        for item in log_entries(place.api.state)
        if item.action == "project.set_open"
    ]
    assert entry.details == {
        "group": "Zestaw",
        "closed_at": sealed["closed_at"],
        "closed_by": "olga",
        "pins_sha256": sealed["pins_sha256"],
    }


def _group_of(data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in data["groups"] if item["name"] == name)


def test_an_open_set_holds_the_data_of_one_producer(place: Place) -> None:
    """A draft of two producers, or another producer's pin, is ``set_producer``."""
    # Arrange
    _draft(place, "NMT", A_CURRENT)
    before = (place.directory / PROJECT_FILE).read_bytes()

    # Act
    both = place.owner.request(
        "POST",
        place.groups,
        json={
            "name": "Oba",
            "open": True,
            "from": "file",
            "versions": _versions(A_OLDER, STATION),
        },
    )
    other = place.owner.request(
        "POST",
        f"{place.groups}/NMT/pins",
        json={"from": "file", "versions": _versions(STATION)},
    )

    # Assert
    assert_problem(both, 409, "conflict", "set_producer")
    assert_problem(other, 409, "conflict", "set_producer")
    assert other.json()["details"] == {
        "reason": "set_producer",
        "group": "NMT",
        "producers": [PRODUCER],
        "producer": "obserwator",
    }
    assert (place.directory / PROJECT_FILE).read_bytes() == before


def test_uncall_removes_a_call_with_the_pins_only_it_pinned(place: Place) -> None:
    """Places shift down, hand pins stay; the last call makes the set local."""
    # Arrange
    _draft(place, "Plan", A_OLDER, A_CURRENT, B_CURRENT)
    _change(
        place,
        _as_plan(
            "Plan",
            [CALL_A, CALL_B, CALL_C],
            {_path(A_OLDER): [0], _path(A_CURRENT): [0, 2], _path(B_CURRENT): []},
        ),
    )
    _draft(place, "Stary", A_OLDER)
    _change(place, _as_plan("Stary", [CALL_A], {_path(A_OLDER): None}))
    url = f"{place.groups}/Plan/calls"

    # Act
    beyond = place.owner.request("DELETE", f"{url}/3")
    first = place.owner.request("DELETE", f"{url}/0")
    after_first = _group(place, "Plan")
    second = place.owner.request("DELETE", f"{url}/1")
    after_second = _group(place, "Plan")
    last = place.owner.request("DELETE", f"{url}/0")
    old = place.owner.request("DELETE", f"{place.groups}/Stary/calls/0")

    # Assert
    assert_problem(beyond, 404, "not_found", "call_not_found")
    assert first.status_code == 200, first.text
    assert after_first["origin"]["calls"] == [CALL_B, CALL_C]
    assert {pin["version"]: pin["calls"] for pin in after_first["pins"]} == {
        _path(A_CURRENT): [1],
        _path(B_CURRENT): [],
    }
    assert second.status_code == 200, second.text
    assert after_second["origin"]["calls"] == [CALL_B]
    assert {pin["version"]: pin["calls"] for pin in after_second["pins"]} == {
        _path(B_CURRENT): []
    }
    assert last.status_code == 200, last.text
    final = _group(place, "Plan")
    assert final["origin"] == {"kind": "local", "selections": [{"from": "file"}]}
    assert [pin["version"] for pin in final["pins"]] == [_path(B_CURRENT)]
    assert "calls" not in final["pins"][0]
    card = _card_group(last.json(), "Plan")
    assert (card["origin"]["kind"], card["origin"]["calls"]) == ("local", None)
    assert_problem(old, 409, "conflict", "pins_without_calls")
    unpins = [
        item.details
        for item in log_entries(place.api.state)
        if item.action == "project.unpin"
    ]
    assert unpins[0] == {
        "group": "Plan",
        "call": {**CALL_A, "call": 0},
        "pins": [{"producer": PRODUCER, "version": _path(A_OLDER)}],
    }


def test_a_call_s_year_stays_through_close_and_reopen(place: Place) -> None:
    """The calls of a plan set, ``year`` and all, are not touched by the states."""
    # Arrange
    _draft(place, "Lata", A_OLDER, B_CURRENT)
    _change(
        place,
        _as_plan(
            "Lata", [CALL_A, CALL_B], {_path(A_OLDER): [0], _path(B_CURRENT): [1]}
        ),
    )
    origin = _group(place, "Lata")["origin"]

    # Act
    closed = place.owner.request("POST", f"{place.groups}/Lata/close")
    closed_origin = _group(place, "Lata")["origin"]
    reopened = place.owner.request("POST", f"{place.groups}/Lata/reopen")
    card = place.owner.request("GET", f"/projects/{place.project}")

    # Assert
    assert closed.status_code == 200, closed.text
    assert reopened.status_code == 200, reopened.text
    assert closed_origin == origin
    assert _group(place, "Lata")["origin"] == origin
    assert [call["options"]["year"] for call in origin["calls"]] == [2016, 2023]
    for answer in (closed.json(), reopened.json(), card.json()):
        calls = _card_group(answer, "Lata")["origin"]["calls"]
        assert calls == [CALL_A, CALL_B]


def test_commands_draft_close_and_reopen_as_the_routes_do(
    place: Place, capsys: pytest.CaptureFixture[str]
) -> None:
    """``project-draft`` → ``project-pin --add`` → ``project-close`` → reopen."""
    # Act
    drafted = _cli(capsys, place, "project-draft", place.project, "Z CLI")
    empty = _cli(capsys, place, "project-close", place.project, "Z CLI")
    api_empty = place.owner.request("POST", f"{place.groups}/Z CLI/close")
    added = _cli(
        capsys,
        place,
        "project-pin",
        place.project,
        "z cli",
        "--add",
        "--version",
        f"{STORE}:{_path(A_CURRENT)}",
    )
    closed = _cli(capsys, place, "project-close", place.project, "z cli")
    sealed = _group(place, "Z CLI")
    twice = _cli(capsys, place, "project-close", place.project, "Z CLI")
    reopened = _cli(capsys, place, "project-reopen", place.project, "Z CLI")
    job = _waiting_download(place, "Z CLI")
    busy = _cli(capsys, place, "project-close", place.project, "Z CLI")

    # Assert
    assert (drafted["group"], drafted["pinned"]) == ("Z CLI", 0)
    assert _card_group(drafted["project"], "Z CLI")["state"] == "open"
    assert_same_error(empty, api_empty.json())
    assert added["pinned"] == 1
    card = _card_group(closed, "Z CLI")
    assert (card["state"], card["closed_by"], card["digest_state"]) == (
        "closed",
        LOCAL_OWNER.id,
        "ok",
    )
    assert (
        card["pins_sha256"]
        == sealed["pins_sha256"]
        == pins_digest([(PRODUCER, _path(A_CURRENT), sealed["pins"][0]["sha256"])])
    )
    assert twice["code"] == "conflict"
    assert twice["details"] == {"reason": "set_closed", "group": "Z CLI"}
    reopened_card = _card_group(reopened, "Z CLI")
    assert (reopened_card["state"], reopened_card["pins_sha256"]) == ("open", None)
    assert _group(place, "Z CLI")["state"] == "open"
    assert busy["details"]["reason"] == "set_job_active"
    assert busy["details"]["job"]["id"] == job.id
    waiting = place.jobs.get(job.id)
    assert waiting is not None
    assert waiting.state == "queued"
