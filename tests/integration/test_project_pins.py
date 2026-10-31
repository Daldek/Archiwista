"""Pinning what the store holds into a project's groups (A-ADR-049 decisions 7, 8).

An index holds two sheets of the store ``zespol`` (a current and an older
version of ``A``, a current one of ``B``), a version of ``C`` without
metadata and a version of the store ``drugi``. ``POST
/projects/{project}/groups`` and ``…/groups/{group}/pins`` pin them into
Archiwista's project file from the index alone, ``…/unpin`` and ``DELETE
…/groups/{group}`` remove them; ``archiwista project-pin`` and
``project-unpin`` do the same and refuse alike.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize
from archiwista.projects import PROJECT_FILE, change_project_file
from archiwista.projects import document as project_document
from archiwista.sources import SourceEntry, SourceSegment
from archiwista.sources.registry import load_registry
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
from tests.fixtures.network import no_network
from tests.fixtures.permissions import add_people, log_entries, principal, share

OTHER_STORE = "drugi"
SHEET_A = slot_path(NMT, "M-34-1-A")
SHEET_B = slot_path(NMT, "M-34-1-B")
SHEET_C = slot_path(NMT, "M-34-1-C")
A_CURRENT = version(SHEET_A, "2024-05-01_1", 1)
A_OLDER = version(SHEET_A, "2016-06-01_1", 2)
B_CURRENT = version(SHEET_B, "2023-04-01_1", 3)
C_NO_META = version(SHEET_C, "2022-02-01_1", 4, skipped=True)
D_OTHER = version(slot_path(NMT, "M-34-1-D"), "2021-03-01_1", 5)
GONE = "nmt/pl_1992_1m_evrf2007/versions/M-34-1-Z/2020-01-01_1_00000000/Z.asc"


def _path(entry: SourceEntry) -> str:
    return entry.relative_path.as_posix()


@dataclass(frozen=True)
class Place:
    """A served installation with one project of Olga's."""

    api: Api
    paths: AppPaths
    root: Path
    directory: Path
    project: str
    owner: Caller


@pytest.fixture
def place(tmp_path: Path) -> Iterator[Place]:
    """Serve the index above; Olga owns the public project ``raba``."""
    root = tmp_path / "nas" / "kartograf"
    other = tmp_path / "nas" / "drugi"
    projects = tmp_path / "nas" / "projekty"
    for directory in (root, other, projects):
        directory.mkdir(parents=True)
    paths = local_paths(tmp_path)
    stores = (
        StoreConfig(id=STORE, name="Zespół", kartograf=root, kind="local"),
        StoreConfig(id=OTHER_STORE, name="Drugi", kartograf=other, kind="local"),
    )
    ConfigStore(paths.config_file).save(
        AppSettings(stores=stores, project_dirs=(projects,))
    )
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {PRODUCER: root}, OTHER_STORE: {PRODUCER: other}})
        write_pass(
            writer,
            [
                A_CURRENT,
                A_OLDER,
                B_CURRENT,
                C_NO_META,
                link(SHEET_A, A_CURRENT),
                link(SHEET_B, B_CURRENT),
            ],
        )
        write_pass(writer, [D_OTHER], store=OTHER_STORE)
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        add_people(api.state)
        owner = api.session(principal(api.state, "owner"))
        directory = projects / "raba"
        created = owner.request("POST", "/projects", json={"path": str(directory)})
        assert created.status_code == 201, created.text
        share(api.state, access_key(directory), "public")
        yield Place(api, paths, root, directory, created.json()["project"], owner)


def _file(place: Place) -> Any:
    return json.loads((place.directory / PROJECT_FILE).read_text(encoding="utf-8"))


def _group(place: Place, name: str) -> dict[str, Any]:
    return next(item for item in _file(place)["groups"] if item["name"] == name)


def _versions(group: dict[str, Any]) -> list[str]:
    return sorted(pin["version"] for pin in group["pins"])


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


def test_pins_a_catalog_query_offline_and_every_version_with_versions_all(
    place: Place,
) -> None:
    """A query pins exactly the Catalog's rows; the slots and file card show them."""
    # Arrange
    query = {"store": STORE, "product": "nmt"}
    rows = place.owner.request("GET", f"/slots?store={STORE}&product=nmt").json()
    every = place.owner.request(
        "GET", f"/slots?store={STORE}&product=nmt&versions=all"
    ).json()

    # Act
    with no_network() as attempts:
        current = place.owner.request(
            "POST",
            f"/projects/{place.project}/groups",
            json={"name": "NMT", "from": "catalog", "query": query},
        )
        everything = place.owner.request(
            "POST",
            f"/projects/{place.project}/groups",
            json={
                "name": "Wszystko",
                "from": "local_state",
                "query": {**query, "versions": "all"},
            },
        )

    # Assert
    assert attempts == []
    assert current.status_code == 201, current.text
    outcome = current.json()
    assert (outcome["group"], outcome["pinned"], outcome["already"]) == ("NMT", 2, 0)
    assert outcome["skipped"] == []
    shown = [row["version"]["path"] for row in rows["items"] if row["version"]]
    assert _versions(_group(place, "NMT")) == sorted(shown)
    assert everything.status_code == 201, everything.text
    assert everything.json()["skipped"] == [
        {"store": STORE, "version": _path(C_NO_META), "reason": "no_sha256"}
    ]
    listed = [row["version"]["path"] for row in every["items"]]
    assert _versions(_group(place, "Wszystko")) == sorted(
        path for path in listed if path != _path(C_NO_META)
    )
    written = _file(place)
    assert written["stores"] == [{"producer": PRODUCER, "root": str(place.root)}]
    selection = _group(place, "NMT")["origin"]["selections"]
    assert [(item["from"], item["query"]["product"]) for item in selection] == [
        ("catalog", "nmt")
    ]
    pin = next(
        item
        for item in _group(place, "NMT")["pins"]
        if item["version"] == _path(A_CURRENT)
    )
    assert (pin["sha256"], pin["size_bytes"], pin["unit"], pin["label"]) == (
        A_CURRENT.meta.sha256 if A_CURRENT.meta else None,
        1000,
        "M-34-1-A",
        "2024-05-01_1",
    )
    assert pin["pinned_by"] == "olga"
    pinned = place.owner.request(
        "GET", f"/slots?project={place.project}&versions=all"
    ).json()
    groups = {
        row["version"]["path"]: sorted(
            item["group"] for item in row["version"]["pinned_by"]
        )
        for row in pinned["items"]
    }
    assert groups[_path(A_CURRENT)] == ["NMT", "Wszystko"]
    assert groups[_path(A_OLDER)] == ["Wszystko"]
    card = outcome["project"]
    assert [group["name"] for group in card["groups"]] == ["NMT"]


def test_pins_named_versions_counts_the_pinned_and_skips_with_a_reason(
    place: Place,
) -> None:
    """An older version is pinnable; missing ones are skipped, repeated ones counted."""
    # Arrange
    named = [
        {"store": STORE, "version": _path(A_OLDER)},
        {"store": STORE, "version": _path(C_NO_META)},
        {"store": STORE, "version": GONE},
    ]

    # Act
    created = place.owner.request(
        "POST",
        f"/projects/{place.project}/groups",
        json={"name": "Starsze", "from": "file", "versions": named},
    )
    added = place.owner.request(
        "POST",
        f"/projects/{place.project}/groups/starsze/pins",
        json={
            "from": "file",
            "versions": [
                {"store": STORE, "version": _path(A_OLDER)},
                {"store": STORE, "version": _path(B_CURRENT)},
            ],
        },
    )

    # Assert
    assert created.status_code == 201, created.text
    assert (created.json()["pinned"], created.json()["already"]) == (1, 0)
    assert created.json()["skipped"] == [
        {"store": STORE, "version": _path(C_NO_META), "reason": "no_sha256"},
        {"store": STORE, "version": GONE, "reason": "missing"},
    ]
    assert added.status_code == 200, added.text
    assert (added.json()["group"], added.json()["pinned"], added.json()["already"]) == (
        "Starsze",
        1,
        1,
    )
    group = _group(place, "Starsze")
    assert _versions(group) == sorted([_path(A_OLDER), _path(B_CURRENT)])
    assert group["origin"]["selections"] == [{"from": "file"}, {"from": "file"}]


def test_one_request_pins_two_producers_of_a_store_each_at_its_own_root(
    tmp_path: Path,
) -> None:
    """The store ``zespol`` holds both producers; each ``stores[]`` names its own."""
    # Arrange
    kartograf, imgw = tmp_path / "nas" / "kartograf", tmp_path / "nas" / "imgw"
    projects = tmp_path / "nas" / "projekty"
    for directory in (kartograf, imgw, projects):
        directory.mkdir(parents=True)
    paths = local_paths(tmp_path)
    store = StoreConfig(
        id=STORE, name="Zespół", kartograf=kartograf, imgw=imgw, kind="local"
    )
    ConfigStore(paths.config_file).save(
        AppSettings(stores=(store,), project_dirs=(projects,))
    )
    hydro = "hydro/imgw_daily"
    station = version(slot_path(hydro, "150160180", ".csv"), "2024-12-31_1", 9)
    assert station.meta is not None
    station = replace(
        station, producer="imgw", meta=replace(station.meta, producer="imgw")
    )
    segment = SourceSegment(hydro, "hydro", "PL", "pl.imgw.daily", "Dobowe", True)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: store.roots()})
        write_pass(writer, [A_CURRENT])
        writer.write_segments(STORE, "imgw", [segment])
        writer.begin_pass(STORE, "imgw", segment=None, slots=None, full=False)
        writer.write_entries([station])
        writer.finish_pass()
    versions = [
        {"store": STORE, "version": _path(A_CURRENT)},
        {"store": STORE, "version": _path(station)},
    ]
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        made = owner.request("POST", "/projects", json={"path": str(projects / "r")})
        assert made.status_code == 201, made.text
        url = f"/projects/{made.json()['project']}/groups"

        # Act
        both = owner.request(
            "POST", url, json={"name": "Oba", "from": "file", "versions": versions}
        )
        again = owner.request(
            "POST", url, json={"name": "Znowu", "from": "file", "versions": versions}
        )

    # Assert
    assert both.status_code == 201, both.text
    assert again.status_code == 201, again.text
    written = json.loads((projects / "r" / PROJECT_FILE).read_text(encoding="utf-8"))
    assert written["stores"] == [
        {"producer": PRODUCER, "root": str(kartograf)},
        {"producer": "imgw", "root": str(imgw)},
    ]


def test_too_many_versions_are_refused_before_anything_is_written(
    place: Place, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Above ``MAX_GROUP_PINS`` (patched to 3): ``too_many_pins``, file unchanged."""
    # Arrange
    monkeypatch.setattr(project_document, "MAX_GROUP_PINS", 3)
    before = (place.directory / PROJECT_FILE).read_bytes()

    # Act
    refused = place.owner.request(
        "POST",
        f"/projects/{place.project}/groups",
        json={"name": "Za dużo", "from": "catalog", "query": {"versions": "all"}},
    )

    # Assert
    assert_problem(refused, 400, "validation_error", "too_many_pins")
    assert refused.json()["details"]["count"] == 4
    assert (place.directory / PROJECT_FILE).read_bytes() == before


def test_refusals_of_a_pin_leave_the_file_as_it_was(place: Place) -> None:
    """``other_store``, ``unknown_store``, ``group_origin_plan``, names, groups."""
    # Arrange
    url = f"/projects/{place.project}/groups"
    first = place.owner.request(
        "POST",
        url,
        json={
            "name": "NMT",
            "from": "file",
            "versions": [{"store": STORE, "version": _path(A_CURRENT)}],
        },
    )
    assert first.status_code == 201, first.text

    def plan(data: dict[str, Any]) -> None:
        data["groups"].append(
            {
                "name": "Plan",
                "origin": {
                    "kind": "plan",
                    "producer": PRODUCER,
                    "calls": [{"command": "elevation download", "options": {}}],
                },
                "pins": [],
            }
        )

    change_project_file(place.directory, plan)
    other = {"store": OTHER_STORE, "version": _path(D_OTHER)}
    before = (place.directory / PROJECT_FILE).read_bytes()

    # Act
    other_store = place.owner.request(
        "POST", url, json={"name": "Drugi", "from": "file", "versions": [other]}
    )
    into_plan = place.owner.request(
        "POST",
        f"{url}/Plan/pins",
        json={
            "from": "file",
            "versions": [{"store": STORE, "version": _path(A_OLDER)}],
        },
    )
    taken = place.owner.request(
        "POST", url, json={"name": " nmt ", "from": "file", "versions": [other]}
    )
    slash = place.owner.request(
        "POST", url, json={"name": "a/b", "from": "file", "versions": [other]}
    )
    unknown = place.owner.request(
        "POST", f"{url}/brak/pins", json={"from": "file", "versions": [other]}
    )
    unchanged = (place.directory / PROJECT_FILE).read_bytes()

    def elsewhere(data: dict[str, Any]) -> None:
        data["stores"][0]["root"] = str(place.root.parent / "przeniesiony")

    change_project_file(place.directory, elsewhere)
    moved = place.owner.request(
        "POST",
        f"{url}/NMT/pins",
        json={
            "from": "file",
            "versions": [{"store": STORE, "version": _path(A_OLDER)}],
        },
    )

    # Assert
    assert_problem(other_store, 409, "conflict", "other_store")
    assert other_store.json()["details"]["store"] == STORE
    assert_problem(into_plan, 409, "conflict", "group_origin_plan")
    assert_problem(taken, 409, "conflict", "group_exists")
    assert_problem(slash, 400, "validation_error", "invalid_group_name")
    assert_problem(unknown, 404, "not_found")
    assert unchanged == before
    assert_problem(moved, 409, "conflict", "unknown_store")


def test_unpin_removes_pins_and_whole_groups(place: Place) -> None:
    """``…/unpin`` removes named pins, ``DELETE`` a group; both are logged."""
    # Arrange
    url = f"/projects/{place.project}/groups"
    created = place.owner.request(
        "POST",
        url,
        json={
            "name": "NMT",
            "from": "catalog",
            "query": {"store": STORE, "versions": "all"},
        },
    )
    assert created.status_code == 201, created.text
    pin = {"producer": PRODUCER, "version": _path(A_OLDER)}

    # Act
    unpinned = place.owner.request("POST", f"{url}/NMT/unpin", json={"pins": [pin]})
    after_unpin = _versions(_group(place, "NMT"))
    removed = place.owner.request("DELETE", f"{url}/nmt")
    again = place.owner.request("DELETE", f"{url}/nmt")

    # Assert
    assert unpinned.status_code == 200, unpinned.text
    assert _path(A_OLDER) not in after_unpin
    assert len(after_unpin) == 2
    pins = {
        group["name"]: [item["version"] for item in group["pins"]]
        for group in unpinned.json()["groups"]
    }
    assert _path(A_OLDER) not in pins["NMT"]
    assert removed.status_code == 200, removed.text
    assert removed.json()["groups"] == []
    assert _file(place)["groups"] == []
    assert_problem(again, 404, "not_found")
    entries = [
        entry
        for entry in log_entries(place.api.state)
        if entry.action in ("project.pin", "project.unpin")
    ]
    kept = [
        {"producer": PRODUCER, "version": _path(entry)}
        for entry in (A_CURRENT, B_CURRENT)
    ]
    assert [(entry.action, entry.details) for entry in entries] == [
        (
            "project.pin",
            {"group": "NMT", "from": "catalog", "pins": 3, "already": 0, "skipped": 1},
        ),
        ("project.unpin", {"group": "NMT", "pins": [pin]}),
        ("project.unpin", {"group": "NMT", "pins": kept, "group_removed": True}),
    ]
    assert {entry.target for entry in entries} == {access_key(place.directory)}


@pytest.mark.parametrize(
    ("who", "agent", "status"),
    [
        ("owner", False, 201),
        ("owner", True, 201),
        ("admin", False, 201),
        ("other", False, 403),
        ("other", True, 403),
    ],
)
def test_who_may_pin_follows_the_project_s_sharing(
    place: Place, who: str, agent: bool, status: int
) -> None:
    """The owner, their agent and an administrator pin; another person may not."""
    # Arrange
    caller = place.api.session(
        principal(place.api.state, who),  # type: ignore[arg-type]
        token="agent" if agent else "startup",
    )

    # Act
    response = caller.request(
        "POST",
        f"/projects/{place.project}/groups",
        json={
            "name": "NMT",
            "from": "file",
            "versions": [{"store": STORE, "version": _path(A_CURRENT)}],
        },
    )

    # Assert
    assert response.status_code == status, response.text
    if status == 403:
        assert_problem(response, 403, "forbidden", "permission_denied")
        assert _file(place)["groups"] == []


def test_a_private_project_is_unknown_to_another_person(place: Place) -> None:
    """A project the session does not see answers ``404``, as one that is not."""
    # Arrange
    share(place.api.state, access_key(place.directory), "private")
    other = place.api.session(principal(place.api.state, "other"))

    # Act
    response = other.request("DELETE", f"/projects/{place.project}/groups/nmt")

    # Assert
    assert_problem(response, 404, "not_found")


def test_commands_pin_and_unpin_as_the_routes_do(
    place: Place, capsys: pytest.CaptureFixture[str]
) -> None:
    """``project-pin`` prints ``PinOutcome``, ``project-unpin`` the card; alike."""
    # Arrange
    versions = [_path(A_OLDER), _path(C_NO_META)]
    api_outcome = place.owner.request(
        "POST",
        f"/projects/{place.project}/groups",
        json={
            "name": "Z API",
            "from": "file",
            "versions": [{"store": STORE, "version": path} for path in versions],
        },
    ).json()

    # Act
    cli_outcome = _cli(
        capsys,
        place,
        "project-pin",
        place.project,
        "Z CLI",
        *[arg for path in versions for arg in ("--version", f"{STORE}:{path}")],
    )
    added = _cli(
        capsys,
        place,
        "project-pin",
        place.project,
        "z cli",
        "--add",
        "--query",
        json.dumps({"store": STORE}),
    )
    taken = _cli(
        capsys,
        place,
        "project-pin",
        place.project,
        "z api",
        "--version",
        f"{STORE}:{_path(A_OLDER)}",
    )
    api_taken = place.owner.request(
        "POST",
        f"/projects/{place.project}/groups",
        json={
            "name": "z api",
            "from": "file",
            "versions": [{"store": STORE, "version": _path(A_OLDER)}],
        },
    )
    unpinned = _cli(
        capsys,
        place,
        "project-unpin",
        place.project,
        "Z CLI",
        "--pin",
        f"{PRODUCER}:{_path(A_OLDER)}",
    )
    removed = _cli(capsys, place, "project-unpin", place.project, "Z API")

    # Assert
    keys = ("pinned", "already", "skipped")
    assert [cli_outcome[key] for key in keys] == [api_outcome[key] for key in keys]
    assert cli_outcome["group"] == "Z CLI"
    assert (added["pinned"], added["already"]) == (2, 0)
    assert _group(place, "Z CLI")["origin"]["selections"][1] == {
        "from": "catalog",
        "query": {**_group(place, "Z CLI")["origin"]["selections"][1]["query"]},
    }
    assert_same_error(taken, api_taken.json())
    assert [group["name"] for group in unpinned["groups"]] == ["Z API", "Z CLI"]
    assert [group["name"] for group in removed["groups"]] == ["Z CLI"]
    assert _versions(_group(place, "Z CLI")) == sorted(
        [_path(A_CURRENT), _path(B_CURRENT)]
    )
    pinned_by = {pin["pinned_by"] for pin in _group(place, "Z CLI")["pins"]}
    assert pinned_by == {LOCAL_OWNER.id}
