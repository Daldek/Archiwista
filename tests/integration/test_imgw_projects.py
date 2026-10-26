"""Projects of IMGWTools beside those of Kartograf (plan I7, SPEC 4.7).

A project is its directory, with the manifest of one producer or of both. Each
test builds one directory with both manifests by the producers' own writers
(Kartograf's fixture project of two pinned tasks, then ``imgwtools.init_project``
and ``add_project_task``) over a store with a Kartograf and an IMGW directory,
each built by its producer's fixture builder; scans both directories with the
real adapters, offline; and asks the API and the commands.
"""

import json
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import imgwtools
import pytest
from kartograf.testing import FixtureStore, build_fixture_store, build_project

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter, initialize
from archiwista.index.scanner import scan_store
from archiwista.jobs import JobSupervisor
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Api, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.job_worker import NO_NETWORK_ENV
from tests.fixtures.jobs import TEST_WORKER, worker_path

STORE = "zespol"
KEY = "raba"
PRODUCERS = ("kartograf", "imgw")
KARTOGRAF_TASKS = ["nmt-pl", "nmt-cz"]
FLOWS = "przeplywy"
FLOW_OPTIONS: dict[str, Any] = {
    "dataset": "pl.imgw.hydro_daily",
    "stations": ["000000001"],
    "years": [2024],
}
SERIES = "series:pl.imgw.hydro_daily"
# A Kartograf task checked without the network: 1 km² in PL-1992.
TERRAIN: dict[str, Any] = {
    "name": "teren",
    "command": "elevation download",
    "options": {
        "product": "nmt",
        "country": "pl",
        "bbox": [500000, 250000, 501000, 251000],
        "bbox_crs": "EPSG:2180",
        "sheet_system": "1992",
        "resolution": "1m",
        "vertical_crs": "EVRF2007",
        "year": 2023,
    },
}
JOB_TIMEOUT_S = 90.0

type Stores = Callable[[str], Path]


@dataclass(frozen=True)
class Place:
    """An installation whose project directory holds the manifests of both producers."""

    paths: AppPaths
    settings: AppSettings
    kartograf: FixtureStore
    imgw: Path
    directory: Path
    attempts: Path

    def manifest(self, producer: str) -> Path:
        """Return the manifest file of ``producer`` in the project directory."""
        return self.directory / f"{producer}-project.json"

    def manifests(self) -> dict[str, bytes]:
        """Return the bytes of each manifest the project directory holds."""
        return {
            producer: self.manifest(producer).read_bytes()
            for producer in PRODUCERS
            if self.manifest(producer).exists()
        }

    def scan(self, *producers: str) -> None:
        """Scan the directories of ``producers`` (default both) and their projects."""
        registry = load_registry(cache_dir=self.paths.cache_dir)
        with IndexWriter(self.paths.index_file) as writer:
            for producer in producers or PRODUCERS:
                adapter = registry.adapter(producer)
                scan_store(adapter, writer, self.settings, STORE, mode="full")

    def pin_flows(self) -> str:
        """Pin the IMGW task to the current hydro series as IMGWTools records it.

        Returns the pinned version's path in the IMGW directory.
        """
        current = imgwtools.current_version(self.imgw, slot=SERIES)
        assert current is not None and current.version is not None
        assert current.meta is not None
        version = current.version.relative_to(self.imgw).as_posix()
        document = json.loads(self.manifest("imgw").read_text(encoding="utf-8"))
        document["tasks"][0].update(
            pinned_at="2026-10-25T05:00:00Z",
            imgwtools_version=imgwtools.__version__,
            files=[{"role": "series", "path": version, "sha256": current.meta.sha256}],
        )
        self.manifest("imgw").write_text(json.dumps(document), encoding="utf-8")
        return version


@pytest.fixture
def place(imgw_store: Stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Place:
    """Give the directory of both manifests in a configured store, scanned."""
    worker_path(monkeypatch)
    attempts = tmp_path / "network.log"
    monkeypatch.setenv(NO_NETWORK_ENV, str(attempts))
    built = build_fixture_store(tmp_path / "nas" / "kartograf")
    imgw = tmp_path / "nas" / "imgw"
    shutil.copytree(imgw_store("complete"), imgw)
    projects = tmp_path / "nas" / "projekty"
    directory = build_project(projects / KEY, built)
    imgwtools.init_project(directory, store_dir=imgw)
    imgwtools.add_project_task(
        directory, name=FLOWS, command="series select", options=FLOW_OPTIONS
    )
    config = StoreConfig(
        id=STORE, name="Zespół", kartograf=built.root, imgw=imgw, kind="local"
    )
    settings = AppSettings(stores=(config,), project_dirs=(projects,))
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
    made = Place(paths, settings, built, imgw, directory, attempts)
    made.scan()
    return made


@contextmanager
def _api(paths: AppPaths, **supervisor: Any) -> Iterator[tuple[Api, JobSupervisor]]:
    """Serve the API with the producers' plugins and a supervisor of test workers."""
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    with (
        JobSupervisor(
            paths, settings, worker_command=TEST_WORKER, **supervisor
        ) as jobs,
        running_api(paths, registry, jobs=jobs) as api,
    ):
        yield api, jobs


def _cli(capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str) -> Any:
    """Run ``archiwista … --json``; a refusal gives its error document."""
    capsys.readouterr()
    status = main(
        [*argv, "--json"],
        registry=load_registry(cache_dir=paths.cache_dir),
        paths=paths,
    )
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def _tasks(card: dict[str, Any]) -> list[tuple[str, str]]:
    return [(task["producer"], task["task"]) for task in card["tasks"]]


def test_a_directory_with_both_manifests_is_one_project_with_the_tasks_of_both(
    place: Place,
) -> None:
    """One key; each manifest with its store and state, Kartograf's first.

    The store's own list and the list filtered by the store hold the project
    once, though both its manifests name the store.
    """
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)

        # Act
        listed = owner.request("GET", "/projects").json()["items"]
        of_store = owner.request("GET", f"/projects?store={STORE}").json()["items"]
        store = owner.request("GET", f"/stores/{STORE}").json()
        card = owner.request("GET", f"/projects/{KEY}").json()

    # Assert
    assert listed == of_store == store["projects"]
    (item,) = listed
    assert [
        (m["producer"], m["store"], m["status"], m["problem"])
        for m in item["manifests"]
    ] == [
        ("kartograf", STORE, "ok", None),
        ("imgw", STORE, "not_downloaded", None),
    ]
    assert (item["project"], item["tasks"], item["pins"], item["missing_pins"]) == (
        KEY,
        3,
        2,
        0,
    )
    assert card["manifests"] == item["manifests"]
    assert _tasks(card) == [
        ("kartograf", "nmt-pl"),
        ("kartograf", "nmt-cz"),
        ("imgw", FLOWS),
    ]
    assert card["tasks"][2]["options"]["dataset"] == FLOW_OPTIONS["dataset"]
    assert {pin["producer"] for pin in card["pins"]} == {"kartograf"}
    assert card["problems"] == []


def test_a_pin_of_imgwtools_links_to_its_version_in_the_index(place: Place) -> None:
    """The pin has the state, slot and label of the IMGW version it names.

    The version's card names the project's task among its pins.
    """
    version = place.pin_flows()
    place.scan("imgw")
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)

        # Act
        card = owner.request("GET", f"/projects/{KEY}").json()
        indexed = owner.request("GET", f"/stores/{STORE}/versions/{version}").json()

    # Assert
    (pin,) = [pin for pin in card["pins"] if pin["producer"] == "imgw"]
    assert pin == {
        "producer": "imgw",
        "task": FLOWS,
        "version": version,
        "sha256": indexed["version"]["sha256"],
        "state": "ok",
        "slot": indexed["slot"],
        "label": indexed["version"]["label"],
        "size_bytes": indexed["version"]["size_bytes"],
        "is_current": True,
    }
    assert indexed["version"]["is_current"]
    assert [
        (p["project"], p["task"], p["state"]) for p in indexed["version"]["pinned_by"]
    ] == [(KEY, FLOWS, "ok")]
    assert [m["status"] for m in card["manifests"]] == ["ok", "ok"]


def test_the_status_of_each_manifest_is_its_producers_check_now(place: Place) -> None:
    """IMGWTools follows its pin: not downloaded, ok, corrupt, missing.

    Kartograf's manifest beside it stays as its own pins are; the command
    prints what the route answers.
    """
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)

        def status() -> list[tuple[str, str, bool, list[tuple[str, str]]]]:
            answer = owner.request("GET", f"/projects/{KEY}/status")
            assert answer.status_code == 200, answer.text
            return [
                (
                    manifest["producer"],
                    manifest["status"],
                    manifest["stale"],
                    [(task["task"], task["status"]) for task in manifest["tasks"]],
                )
                for manifest in answer.json()["manifests"]
            ]

        # Act
        unpinned = status()
        series = place.imgw / place.pin_flows()
        pinned = status()
        series.write_bytes(b"{}")
        corrupt = status()
        series.unlink()
        missing = status()

    # Assert
    kartograf = ("kartograf", "ok", False, [(task, "ok") for task in KARTOGRAF_TASKS])
    assert [unpinned, pinned, corrupt, missing] == [
        [kartograf, ("imgw", state, False, [(FLOWS, state)])]
        for state in ("not_downloaded", "ok", "corrupt", "missing")
    ]


@pytest.mark.parametrize("broken", PRODUCERS)
def test_a_broken_manifest_hides_nothing_of_the_other(
    place: Place, broken: str
) -> None:
    """The broken manifest shows the producer's message; the other its tasks.

    The problem's fix names the producer whose manifest it is.
    """
    # Arrange
    place.manifest(broken).write_text("{", encoding="utf-8")
    place.scan(broken)
    other = next(producer for producer in PRODUCERS if producer != broken)
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)

        # Act
        (item,) = owner.request("GET", "/projects").json()["items"]
        card = owner.request("GET", f"/projects/{KEY}").json()

    # Assert
    manifests = {manifest["producer"]: manifest for manifest in item["manifests"]}
    assert list(manifests) == list(PRODUCERS)
    assert manifests[broken]["problem"]
    assert (manifests[broken]["store"], manifests[broken]["status"]) == (None, None)
    assert (manifests[other]["store"], manifests[other]["problem"]) == (STORE, None)
    expected = {"kartograf": KARTOGRAF_TASKS, "imgw": [FLOWS]}[other]
    assert _tasks(card) == [(other, task) for task in expected]
    assert {pin["producer"] for pin in card["pins"]} <= {other}
    (problem,) = card["problems"]
    assert problem["code"] == "invalid_manifest"
    assert manifests[broken]["problem"] in problem["message"]
    assert broken in problem["instruction"]


def test_a_task_name_in_both_manifests_is_warned_about_until_one_is_renamed(
    place: Place,
) -> None:
    """`duplicate_task` names the task and both producers; a removal names one.

    Without the producer the removal is refused (`producer_required`) and
    nothing changes; with it, only that manifest loses the task.
    """
    # Arrange
    imgwtools.add_project_task(
        place.directory, name="nmt-pl", command="series select", options=FLOW_OPTIONS
    )
    place.scan("imgw")
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)

        # Act
        warned = owner.request("GET", f"/projects/{KEY}").json()
        before = place.manifests()
        refused = owner.request("DELETE", f"/projects/{KEY}/tasks/nmt-pl")
        unchanged = place.manifests()
        removed = owner.request(
            "DELETE", f"/projects/{KEY}/tasks/nmt-pl?producer=kartograf"
        )

    # Assert
    (problem,) = warned["problems"]
    assert (problem["code"], problem["task"], problem["project"]) == (
        "duplicate_task",
        "nmt-pl",
        KEY,
    )
    assert "kartograf, imgw" in problem["message"]
    assert _tasks(warned) == [
        ("kartograf", "nmt-pl"),
        ("kartograf", "nmt-cz"),
        ("imgw", FLOWS),
        ("imgw", "nmt-pl"),
    ]
    assert_problem(refused, 400, "validation_error", "producer_required")
    assert refused.json()["details"]["option"] == "producer"
    assert unchanged == before
    assert removed.status_code == 200, removed.text
    assert _tasks(removed.json()) == [
        ("kartograf", "nmt-cz"),
        ("imgw", FLOWS),
        ("imgw", "nmt-pl"),
    ]
    assert removed.json()["problems"] == []
    assert place.manifests()["imgw"] == before["imgw"]


def test_a_manifest_removed_leaves_the_project_and_its_key_to_the_other(
    place: Place,
) -> None:
    """The project goes with its last manifest, not with the one it was found by."""
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)

        # Act
        place.manifest("kartograf").unlink()
        place.scan("kartograf")
        left = owner.request("GET", "/projects").json()["items"]
        place.manifest("imgw").unlink()
        place.scan("imgw")
        gone = owner.request("GET", "/projects").json()["items"]

    # Assert
    assert [
        (item["project"], [m["producer"] for m in item["manifests"]], item["tasks"])
        for item in left
    ] == [(KEY, ["imgw"], 1)]
    assert gone == []


def test_a_kartograf_project_created_beside_an_imgw_manifest_joins_its_project(
    place: Place,
) -> None:
    """`POST /projects` beside an IMGWTools manifest keeps its project's key."""
    directory = place.directory.parent / "wisla"
    imgwtools.init_project(directory, store_dir=place.imgw)
    place.scan("imgw")
    body = {"producer": "kartograf", "path": str(directory), "store": STORE}
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)
        before = owner.request("GET", "/projects").json()["items"]

        # Act
        created = owner.request("POST", "/projects", json=body)

    # Assert
    assert [
        [m["producer"] for m in item["manifests"]]
        for item in before
        if item["project"] == "wisla"
    ] == [["imgw"]]
    assert created.status_code == 201, created.text
    assert created.headers["location"] == "/api/v1/projects/wisla"
    assert [(m["producer"], m["store"]) for m in created.json()["manifests"]] == [
        ("kartograf", STORE),
        ("imgw", STORE),
    ]
    assert sorted(path.name for path in directory.iterdir()) == [
        "imgw-project.json",
        "kartograf-project.json",
    ]


def _refused_request(
    action: str, producer: str | None
) -> tuple[str, str, dict[str, Any] | None, list[str]]:
    """Return a request of an action on the project and the same command."""
    named = [] if producer is None else ["--producer", producer]
    if action == "add":
        body = {**TERRAIN, **({} if producer is None else {"producer": producer})}
        argv = ["project-add", KEY, TERRAIN["name"], TERRAIN["command"]]
        argv += ["--options", json.dumps(TERRAIN["options"]), *named]
        return "POST", f"/projects/{KEY}/tasks", body, argv
    if action == "remove":
        query = "" if producer is None else f"?producer={producer}"
        path = f"/projects/{KEY}/tasks/nmt-pl{query}"
        return "DELETE", path, None, ["project-remove", KEY, "nmt-pl", *named]
    assert action == "verify"
    body = {"kind": "verify", **({} if producer is None else {"producer": producer})}
    return "POST", f"/projects/{KEY}/jobs", body, ["project-verify", KEY, *named]


@pytest.mark.parametrize("action", ["add", "remove", "verify"])
@pytest.mark.parametrize(
    ("producer", "status", "code", "reason"),
    [
        (None, 400, "validation_error", "producer_required"),
        ("external", 400, "validation_error", "other_producer"),
        ("imgw", 422, "unsupported", "no_project_actions"),
    ],
)
def test_an_action_on_a_project_of_two_manifests_names_one_of_them(
    place: Place,
    capsys: pytest.CaptureFixture[str],
    action: str,
    producer: str | None,
    status: int,
    code: str,
    reason: str,
) -> None:
    """The route and the command refuse alike, before anything is written.

    No producer, or one whose manifest the project lacks, is refused with
    `details.option` `producer`; IMGWTools has no project actions yet.
    """
    method, path, body, argv = _refused_request(action, producer)
    before = place.manifests()
    with _api(place.paths, max_jobs=0) as (api, jobs):
        owner = api.session(LOCAL_OWNER)

        # Act
        refused = owner.request(method, path, json=body)
        printed = _cli(capsys, place.paths, *argv)
        recorded = jobs.list().items

    # Assert
    assert_problem(refused, status, code, reason)
    assert_same_error(printed, refused.json())
    if reason != "no_project_actions":
        assert refused.json()["details"]["option"] == "producer"
    assert place.manifests() == before
    assert recorded == ()


def test_a_kartograf_change_of_the_mixed_project_writes_only_its_manifest(
    place: Place,
) -> None:
    """Named, Kartograf adds and removes its task; IMGWTools' manifest is untouched."""
    before = place.manifests()
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)

        # Act
        added = owner.request(
            "POST", f"/projects/{KEY}/tasks", json={**TERRAIN, "producer": "kartograf"}
        )
        removed = owner.request(
            "DELETE", f"/projects/{KEY}/tasks/{TERRAIN['name']}?producer=kartograf"
        )

    # Assert
    assert added.status_code == 201, added.text
    assert _tasks(added.json()) == [
        ("kartograf", "nmt-pl"),
        ("kartograf", "nmt-cz"),
        ("kartograf", TERRAIN["name"]),
        ("imgw", FLOWS),
    ]
    assert removed.status_code == 200, removed.text
    assert _tasks(removed.json()) == [
        ("kartograf", "nmt-pl"),
        ("kartograf", "nmt-cz"),
        ("imgw", FLOWS),
    ]
    assert place.manifests() == before


def test_a_kartograf_job_of_the_mixed_project_runs_the_tasks_of_its_manifest(
    place: Place,
) -> None:
    """A verification named for Kartograf checks its two pins in a worker, offline."""
    with _api(place.paths) as (api, jobs):
        owner = api.session(LOCAL_OWNER)

        # Act
        started = owner.request(
            "POST",
            f"/projects/{KEY}/jobs",
            json={"kind": "verify", "producer": "kartograf"},
        )
        jobs.wait(started.json()["id"], timeout=JOB_TIMEOUT_S)
        ended = owner.request("GET", f"/jobs/{started.json()['id']}").json()

    # Assert
    assert started.status_code == 202, started.text
    assert started.json()["params"] == {
        "project": KEY,
        "tasks": None,
        "producer": "kartograf",
    }
    assert ended["state"] == "succeeded", ended
    assert [item["status"] for item in ended["result"]["files"]] == ["ok", "ok"]
    assert not place.attempts.exists()
