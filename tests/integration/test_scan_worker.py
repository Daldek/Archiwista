"""The index answers queries while a worker process scans (plan step 6b)."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.index import SlotQuery
from tests.fixtures.jobs import DELAY_ENV, SLOW_ENTRY_S, STORE, JobsEnv, jobs_env

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

# A query slower than this while the worker writes means it waited for it.
MAX_QUERY_S = 1.0


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[JobsEnv]:
    """Yield a fresh store with a started supervisor of test workers."""
    with jobs_env(tmp_path, monkeypatch) as created:
        yield created


def test_queries_answer_during_scan(
    env: JobsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog and status queries answer at once while a full scan writes."""
    # Arrange
    env.scan("full")
    query = SlotQuery(store=STORE, versions="all", limit=200)
    rows = len(env.queries.slots(query, visible=ALL_PROJECTS).items)
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    job = env.jobs.submit("scan", store=STORE, params={"mode": "full"}, actor="local")
    env.follow(job.id, lambda event: event.type == "progress")

    # Act
    seconds = []
    answers = []
    running = []
    while (record := env.jobs.get(job.id)) is not None and record.state == "running":
        started = time.perf_counter()
        page = env.queries.slots(query, visible=ALL_PROJECTS)
        status = env.state()
        seconds.append(time.perf_counter() - started)
        answers.append(len(page.items))
        running.append(status.running_job)
        time.sleep(0.05)
    finished = env.wait(job.id)

    # Assert
    assert finished.state == "succeeded"
    assert len(seconds) >= 10
    assert max(seconds) < MAX_QUERY_S
    assert set(answers) == {rows}
    progress = [job_ref.progress for job_ref in running if job_ref is not None]
    assert progress and {job_ref.id for job_ref in running if job_ref} == {job.id}
    assert all(item is not None and item[0] <= item[1] for item in progress)
