"""The jobs of a project: download, repin, check, verify (plan of 2026-10-25, A8).

Kartograf's fixture store and project (``kartograf.testing``): two tasks, each
pinning one version. A verification and a download of pins the store holds
work offline, so they run in real worker processes whose sockets refuse every
connection (``NO_NETWORK_ENV``). A check and a download that would fetch need
the network: they run in this process with Kartograf's function stood in for.
One job of a project runs at a time, offline mode refuses the jobs that need
the network, a project whose manifest names no configured store is refused
before Kartograf writes, and a lock of the manifest that stays fails the job
as ``project_locked`` with its path, never removed.
"""

import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kartograf
import pytest
from kartograf.testing import FixtureStore, build_fixture_store, build_project

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.error_document import describe
from archiwista.errors import (
    CheckFailedError,
    ConflictError,
    JobConflictError,
    OfflineModeError,
    ProjectLockedError,
)
from archiwista.index import IndexQueries, IndexWriter, initialize
from archiwista.index.projects import record_project
from archiwista.jobs import JobRecord, JobSupervisor, worker
from archiwista.jobs.protocol import JobKind, JobSpec, JsonObject
from archiwista.sources.registry import load_registry
from tests.fixtures.job_worker import NO_NETWORK_ENV
from tests.fixtures.jobs import TEST_WORKER, worker_path

STORE = "zespol"
PL_TASK = "nmt-pl"
CZ_TASK = "nmt-cz"
LOCK = ".kartograf-project.lock"
JOB_TIMEOUT_S = 90.0


@dataclass(frozen=True)
class Place:
    """A configured store and project directory, the index and the project's key."""

    paths: AppPaths
    built: FixtureStore
    projects: Path
    directory: Path
    settings: AppSettings
    key: str
    attempts: Path

    def supervisor(self, **options: Any) -> JobSupervisor:
        """Return a supervisor whose workers refuse the network."""
        registry = load_registry(cache_dir=self.paths.cache_dir)
        settings = SettingsService(ConfigStore(self.paths.config_file), registry)
        return JobSupervisor(
            self.paths, settings, worker_command=TEST_WORKER, **options
        )

    def spec(
        self, kind: JobKind, params: JsonObject, settings: AppSettings | None = None
    ) -> JobSpec:
        """Return the job a worker receives, for a run in this process."""
        return JobSpec(
            job_id="0123456789abcdef",
            kind=kind,
            store=None,
            params=params,
            actor="local",
            actor_kind="local_owner",
            session=None,
            index_path=self.paths.index_file,
            cache_dir=self.paths.cache_dir,
            previews_dir=self.paths.previews_dir,
            work_dir=self.paths.work_dir,
            settings=settings or self.settings,
        )

    def add(self, name: str) -> str:
        """Build another fixture project beside the first; return its key."""
        directory = build_project(self.projects / name, self.built)
        with IndexWriter(self.paths.index_file) as writer:
            return record_project(
                load_registry(cache_dir=self.paths.cache_dir).adapter("kartograf"),
                writer,
                directory,
                stores=self.settings.stores,
            )

    def corrupt(self, task: int) -> None:
        """Change the bytes of the version a task pinned."""
        pin = kartograf.open_project(self.directory).tasks[task].files[0]
        version = self.built.root / pin.version
        version.chmod(0o644)
        version.write_bytes(b"0" * 10)


def _place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, offline: bool = False
) -> Place:
    worker_path(monkeypatch)
    attempts = tmp_path / "network.log"
    monkeypatch.setenv(NO_NETWORK_ENV, str(attempts))
    nas = tmp_path / "nas"
    built = build_fixture_store(nas / "kartograf")
    projects = nas / "projekty"
    directory = build_project(projects / "raba", built)
    config = StoreConfig(id=STORE, name="Zespół", kartograf=built.root, kind="local")
    settings = AppSettings(stores=(config,), project_dirs=(projects,), offline=offline)
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    adapter = load_registry(cache_dir=paths.cache_dir).adapter("kartograf")
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        key = record_project(adapter, writer, directory, stores=settings.stores)
    return Place(paths, built, projects, directory, settings, key, attempts)


@pytest.fixture
def place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Place:
    """Give the fixture project in a configured store, recorded in the index."""
    return _place(tmp_path, monkeypatch)


@pytest.fixture
def held(place: Place) -> Iterator[JobSupervisor]:
    """Yield a supervisor that runs no network job: they stay queued."""
    with place.supervisor(max_network_jobs=0) as jobs:
        yield jobs


def _run(place: Place, kind: str, **params: Any) -> JobRecord:
    """Run one job of the place's project in a worker and return it ended."""
    with place.supervisor() as jobs:
        job = jobs.submit(
            kind, params={"project": place.key, **params}, actor=LOCAL_OWNER
        )
        return jobs.wait(job.id, timeout=JOB_TIMEOUT_S)


def _report(directory: Path, root: Path, *results: kartograf.TaskResult) -> Any:
    """Return a report of ``download_project`` with these results of tasks."""
    return kartograf.ProjectReport(
        project=kartograf.Project(directory=directory, root=root, tasks=()),
        tasks=results,
        notices=(),
        ok=all(result.outcome != "failed" for result in results),
    )


def test_a_verification_reports_each_pin_in_its_result_without_network(
    place: Place,
) -> None:
    """A whole project is ``ok``; a corrupt pin is a state, not a failed job."""
    whole = _run(place, "project_verify")
    place.corrupt(0)
    damaged = _run(place, "project_verify", tasks=[PL_TASK])

    assert (whole.state, whole.store, whole.error) == ("succeeded", None, None)
    assert whole.params == {"project": place.key, "tasks": None}
    assert whole.result is not None
    assert (whole.result["project"], whole.result["ok"]) == (place.key, True)
    assert whole.result["root"] == str(place.built.root)
    assert [(item["task"], item["status"]) for item in whole.result["files"]] == [
        (PL_TASK, "ok"),
        (CZ_TASK, "ok"),
    ]
    assert whole.result["counts"]["ok"] == 2
    assert whole.result["not_downloaded"] == []
    assert damaged.state == "succeeded"
    assert damaged.result is not None
    assert damaged.result["ok"] is False
    assert [item["status"] for item in damaged.result["files"]] == ["corrupt"]
    assert not place.attempts.exists()


def test_a_download_of_pins_the_store_holds_keeps_them_without_network(
    place: Place,
) -> None:
    """Every task is ``unchanged``; the index still holds the project and its pins."""
    manifest = (place.directory / "kartograf-project.json").read_bytes()

    record = _run(place, "project_download")

    assert (record.state, record.error) == ("succeeded", None)
    assert record.result is not None
    assert record.result["counts"] == {
        "pinned": 0,
        "unchanged": 2,
        "restored": 0,
        "updated": 0,
        "failed": 0,
    }
    assert (record.result["store"], record.result["upgrade"]) == (STORE, False)
    assert (record.result["failed"], record.result["rescanned"]) == (0, 0)
    assert [task["name"] for task in record.result["tasks"]] == [PL_TASK, CZ_TASK]
    assert (place.directory / "kartograf-project.json").read_bytes() == manifest
    with IndexQueries(place.paths.index_file) as queries:
        indexed = queries.project(place.key, visible=ALL_PROJECTS)
    assert indexed is not None
    assert ([m.store for m in indexed.project.manifests], len(indexed.pins)) == (
        [STORE],
        2,
    )
    assert not place.attempts.exists()


def test_a_failed_task_ends_the_download_partial_and_all_failed_fail_it(
    place: Place,
) -> None:
    """A corrupt pin fails its task; with both pins corrupt the job fails.

    The failure has the code of the first failed task, Kartograf's text and
    the task's name; nothing reaches the network.
    """
    place.corrupt(0)
    partial = _run(place, "project_download")
    place.corrupt(1)
    failed = _run(place, "project_download")

    assert partial.state == "partial"
    assert partial.result is not None
    assert partial.result["counts"]["failed"] == 1
    assert partial.result["counts"]["unchanged"] == 1
    first = partial.result["tasks"][0]
    assert (first["name"], first["code"], first["reason"]) == (
        PL_TASK,
        "data_error",
        "corrupt_pin",
    )
    assert failed.state == "failed"
    assert failed.error is not None
    assert failed.error.code == "data_error"
    assert failed.error.details == {"reason": "run_failed", "task": PL_TASK}
    assert "--force" in failed.error.detail
    assert not place.attempts.exists()


def test_one_job_of_a_project_at_a_time_and_another_project_is_free(
    place: Place, held: JobSupervisor
) -> None:
    """A second job of the project is ``409 conflict`` naming the first, of any kind."""
    other = place.add("wisla")
    first = held.submit(
        "project_download", params={"project": place.key}, actor=LOCAL_OWNER
    )

    with pytest.raises(JobConflictError) as raised:
        held.submit("project_verify", params={"project": place.key}, actor=LOCAL_OWNER)
    beside = held.submit(
        "project_download", params={"project": other}, actor=LOCAL_OWNER
    )

    assert first.state == "queued"
    assert raised.value.details["job"] == {
        "id": first.id,
        "kind": "project_download",
        "state": "queued",
    }
    assert beside.state == "queued"


def test_offline_mode_refuses_the_jobs_that_need_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A download, a repin and a check are refused unrecorded; a verification runs."""
    place = _place(tmp_path, monkeypatch, offline=True)
    params = {"project": place.key, "tasks": [PL_TASK]}

    with place.supervisor() as jobs:
        for kind in ("project_download", "project_repin", "project_check"):
            with pytest.raises(OfflineModeError):
                jobs.submit(kind, params=params, actor=LOCAL_OWNER)
        listed = jobs.list().items
        verified = jobs.submit("project_verify", params=params, actor=LOCAL_OWNER)
        ended = jobs.wait(verified.id, timeout=JOB_TIMEOUT_S)

    assert listed == ()
    assert ended.state == "succeeded"


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("project_repin", {}),
        ("project_repin", {"tasks": [PL_TASK, CZ_TASK]}),
        ("project_download", {"tasks": []}),
        ("project_download", {"tasks": [""]}),
        ("project_check", {"tasks": PL_TASK}),
        ("project_verify", {"store": STORE}),
    ],
)
def test_a_project_job_takes_its_project_and_valid_tasks(
    place: Place, held: JobSupervisor, kind: str, params: dict[str, Any]
) -> None:
    """A repin names one task; tasks are names; no other parameter is taken."""
    with pytest.raises(ValueError):
        held.submit(kind, params={"project": place.key, **params}, actor=LOCAL_OWNER)


def test_a_task_named_twice_is_kept_once_and_the_job_has_no_store(
    place: Place, held: JobSupervisor
) -> None:
    """The job is of the project: no store, its tasks in the order given."""
    job = held.submit(
        "project_repin",
        params={"project": place.key, "tasks": [PL_TASK, PL_TASK]},
        actor=LOCAL_OWNER,
    )

    assert (job.store, job.params) == (None, {"project": place.key, "tasks": [PL_TASK]})
    with pytest.raises(ValueError):
        held.submit(
            "project_repin",
            store=STORE,
            params={"project": place.key},
            actor=LOCAL_OWNER,
        )


def test_a_project_of_a_store_not_configured_is_refused_before_kartograf_writes(
    place: Place,
) -> None:
    """The manifest is read again first; its store must be one of the settings."""
    elsewhere = place.settings.model_copy(update={"stores": ()})
    manifest = (place.directory / "kartograf-project.json").read_bytes()

    with pytest.raises(ConflictError) as raised:
        worker.run_project_download(
            place.spec(
                "project_download", {"project": place.key, "tasks": None}, elsewhere
            ),
            worker.Emitter(io.StringIO()),
        )

    problem = describe(raised.value)
    assert (problem.code, problem.details["reason"]) == ("conflict", "unknown_store")
    assert str(place.built.root) in problem.detail
    assert (place.directory / "kartograf-project.json").read_bytes() == manifest


def test_a_lock_left_by_an_interrupted_change_fails_the_download_and_stays(
    place: Place, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task that failed while the lock stays fails the job as ``project_locked``."""
    lock = place.directory / LOCK
    lock.mkdir()
    text = "project locked by another process"

    def download(project_dir: Path, **kwargs: Any) -> Any:
        failed = kartograf.TaskResult(
            PL_TASK, "failed", (), (), (text,), "validation_error", "project_locked"
        )
        return _report(project_dir, place.built.root, failed)

    monkeypatch.setattr(actions_module, "download_project", download)

    with pytest.raises(ProjectLockedError) as raised:
        worker.run_project_repin(
            place.spec("project_repin", {"project": place.key, "tasks": [PL_TASK]}),
            worker.Emitter(io.StringIO()),
        )

    problem = describe(raised.value)
    assert (problem.code, problem.details["reason"]) == ("conflict", "project_locked")
    assert problem.details["lock"] == str(lock)
    assert problem.hint is not None and str(lock) in problem.hint
    assert lock.is_dir()


def test_a_check_with_some_pins_unasked_ends_partial_and_with_none_asked_fails(
    place: Place, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every state is in the result; a check that asked the source nothing fails."""
    statuses: list[Any] = ["current", "check_failed"]

    def check(project_dir: Path, **kwargs: Any) -> Any:
        assert isinstance(kwargs["cache"], kartograf.MetadataCache)
        files = tuple(
            kartograf.FileCheck(
                task, "unit", f"nmt/{task}.asc", status, "2021", None, None
            )
            for task, status in zip((PL_TASK, CZ_TASK), statuses, strict=True)
        )
        return kartograf.ProjectCheck(
            kartograf.Project(project_dir, place.built.root, ()),
            files,
            (),
            (),
            "check_failed" not in statuses,
        )

    monkeypatch.setattr(actions_module, "check_project", check)
    spec = place.spec("project_check", {"project": place.key, "tasks": None})

    partial = worker.run_project_check(spec, worker.Emitter(io.StringIO()))
    statuses[0] = "check_failed"
    with pytest.raises(CheckFailedError) as raised:
        worker.run_project_check(spec, worker.Emitter(io.StringIO()))

    assert isinstance(partial, worker.PartialResult)
    assert partial.summary["counts"]["current"] == 1
    assert partial.summary["counts"]["check_failed"] == 1
    assert [item["status"] for item in partial.summary["files"]] == [
        "current",
        "check_failed",
    ]
    problem = describe(raised.value)
    assert (problem.code, problem.details["reason"]) == (
        "source_unavailable",
        "check_failed",
    )
