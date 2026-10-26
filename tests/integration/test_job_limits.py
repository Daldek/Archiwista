"""Network jobs of one person (plan v0.4 T9, ADR-047 decision 4).

A person runs at most ``network_jobs_per_person`` network jobs at once (an
agent counts as its account, the scheduler as no one); further ones wait in
the queue, none is refused, and a free network place goes to the oldest
waiting job of the person with the fewest running ones. Real workers run
downloads of the stand-in producer (``tests/fixtures/actions.py``) without a
plan, one station each: each waits after its first new file while the store
holds ``HOLD``, so the jobs keep running until the test lets them go.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.auth import SCHEDULER, Principal
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.sources.registry import load_registry
from tests.fixtures.actions import (
    ACTION_WORKER,
    STORE,
    action_paths,
    station_calls,
    store_root,
)
from tests.fixtures.availability import register_standin
from tests.fixtures.jobs import worker_path

JOB_TIMEOUT_S = 90.0
STATIONS = ("150160180", "150160190", "150160200", "150160210", "150160220")
WRITER = frozenset({"store_writer"})
MAREK = Principal("marek", "user", WRITER, frozenset(), "s-marek")
MAREK_AGENT = Principal("marek", "agent", WRITER, frozenset(), "s-agent")
ANNA = Principal("anna", "user", WRITER, frozenset(), "s-anna")


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers; return its producer library."""
    worker_path(monkeypatch)
    return register_standin(monkeypatch)


@pytest.fixture
def paths(tmp_path: Path, standin: ModuleType) -> AppPaths:
    """Return a fresh installation with the stand-in's store."""
    return action_paths(tmp_path)


@contextmanager
def _supervisor(
    paths: AppPaths, *, max_network_jobs: int
) -> Iterator[tuple[JobSupervisor, SettingsService]]:
    """Yield a started supervisor of real workers and its settings.

    Eight workers may run, so only the network limits hold jobs back.
    """
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    jobs = JobSupervisor(
        paths,
        settings,
        worker_command=ACTION_WORKER,
        max_jobs=8,
        max_network_jobs=max_network_jobs,
    )
    with jobs:
        yield jobs, settings


def _download(jobs: JobSupervisor, person: Principal, station: str) -> JobRecord:
    """Submit a download of one station's files without a plan."""
    params = {"producer": "standin", "calls": station_calls(station), "plan_job": None}
    return jobs.submit("download", store=STORE, params=params, actor=person)


def _state(jobs: JobSupervisor, job: JobRecord) -> str:
    """Return the state a job has now."""
    record = jobs.get(job.id)
    assert record is not None
    return record.state


def _ended(jobs: JobSupervisor, *started: JobRecord) -> list[str]:
    """Wait for the jobs to end; return their states in their order."""
    return [jobs.wait(job.id, timeout=JOB_TIMEOUT_S).state for job in started]


def test_a_free_place_goes_to_the_person_running_fewer_network_jobs(
    tmp_path: Path, paths: AppPaths, standin: ModuleType
) -> None:
    """Marek's third job waits while Anna's, asked after it, takes a freed place.

    Marek's first two fill both network places of the server; his third and
    Anna's one wait. When his first ends, Anna (no running job) goes before
    him (one running); his third starts when the next place frees.
    """
    hold = store_root(tmp_path) / standin.HOLD
    hold.touch()
    with _supervisor(paths, max_network_jobs=2) as (jobs, _):
        first, second, third = (_download(jobs, MAREK, s) for s in STATIONS[:3])
        anna = _download(jobs, ANNA, STATIONS[3])
        asked = [job.state for job in (first, second, third, anna)]
        jobs.cancel(first.id)
        jobs.wait(first.id, timeout=JOB_TIMEOUT_S)
        freed = [_state(jobs, job) for job in (second, third, anna)]
        jobs.cancel(second.id)
        jobs.wait(second.id, timeout=JOB_TIMEOUT_S)
        last = _state(jobs, third)
        hold.unlink()
        ended = _ended(jobs, third, anna)

    assert asked == ["running", "running", "queued", "queued"]
    assert freed == ["running", "queued", "running"]
    assert last == "running"
    assert ended == ["succeeded", "succeeded"]


def test_one_network_job_per_person_counts_agents_and_spares_the_scheduler(
    tmp_path: Path, paths: AppPaths, standin: ModuleType
) -> None:
    """With the setting 1 each person runs one network job; raising it starts more.

    The server's limit (here 5) has room all along: Marek's agent waits
    behind his own job, Anna's starts, the scheduler runs two. Raising the
    setting to 2 starts the agent's job at once.
    """
    hold = store_root(tmp_path) / standin.HOLD
    hold.touch()
    config = ConfigStore(paths.config_file)
    config.save(config.load().model_copy(update={"network_jobs_per_person": 1}))
    with _supervisor(paths, max_network_jobs=5) as (jobs, settings):
        marek = _download(jobs, MAREK, STATIONS[0])
        agent = _download(jobs, MAREK_AGENT, STATIONS[1])
        anna = _download(jobs, ANNA, STATIONS[2])
        scheduled = [_download(jobs, SCHEDULER, s) for s in STATIONS[3:]]
        asked = [job.state for job in (marek, agent, anna, *scheduled)]
        raised = settings.get().model_copy(update={"network_jobs_per_person": 2})
        settings.update(raised)
        after = _state(jobs, agent)
        hold.unlink()
        ended = _ended(jobs, marek, agent, anna, *scheduled)

    assert asked == ["running", "queued", "running", "running", "running"]
    assert after == "running"
    assert ended == ["succeeded"] * 5
