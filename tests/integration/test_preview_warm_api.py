"""The warm-up of previews over HTTP and by the command (plan of 2026-10-25, A9).

``POST /previews/warm`` and ``archiwista preview-warm`` start the
``preview_warm`` job (SPEC 5.7, ADR-041) over a generated store, scanned into
a fresh index and served with real render processes; the jobs run in real
worker processes (slowed down by ``tests.fixtures.warm_worker`` where a test
needs time). Who may warm a project's own data and who sees that job, the
refusals of both interfaces, a person's preview while a warm-up runs, and a
store that cannot be read or written.
"""

import json
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.index import IndexQueries, WarmQuery
from archiwista.jobs import JobSupervisor, supervisor
from archiwista.sources.registry import load_registry
from archiwista.state import Visibility
from tests.fixtures.api_session import Caller, assert_problem
from tests.fixtures.api_store import STORE
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.jobs import worker_path
from tests.fixtures.own_data_api import FIRST, OwnDataApi, own_data_api
from tests.fixtures.permissions import SEES, WHO, principal, share
from tests.fixtures.preview_api import (
    JOB_TIMEOUT_S,
    PreviewApi,
    preview_api,
    scanned_store,
    serve_previews,
    version_url,
)
from tests.fixtures.read_only_mount import set_read_only, tree
from tests.fixtures.warm_worker import DELAY_ENV, WARM_WORKER

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

WARM = "/previews/warm"
WAIT_S = 60.0
# A person's preview while a warm-up runs: the target of a first thumbnail
# (plan v0.2, decision 12) on a local disk.
INTERACTIVE_S = 2.0
# The pane's thumbnail, the one the warm-up prepares.
PANE = "?size=512"
# The project is shared with the listed person (by name).
VISIBILITY: Visibility = "users"
UNKNOWN_AREA = "0123456789abcdef"
_NO_ROOT = pytest.mark.skipif(
    os.geteuid() == 0, reason="root reads and writes whatever the modes say"
)


def _await(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.05)


def _warm(caller: Caller, body: dict[str, Any] | None) -> httpx.Response:
    """Ask for a warm-up as ``caller``."""
    return caller.request("POST", WARM, json=body)


def _listed(caller: Caller) -> set[str]:
    """Return the ids of the warm-ups ``caller`` sees in ``GET /jobs``."""
    page = caller.request("GET", "/jobs?kind=preview_warm").json()
    return {item["id"] for item in page["items"]}


def _pane_thumbnail(info: dict[str, Any]) -> str | None:
    """Return the address of the pane's thumbnail of a first look, if it has one.

    A file that waits for its build past the auto-build limits shows its
    thumbnail only after the build, so the warm-up prepares none.
    """
    waits = info["state"] == "needs_build" and not info["auto_build"]
    if not info["thumbnail_url"] or waits:
        return None
    return f"{info['thumbnail_url']}{PANE}"


def _current_versions(paths: AppPaths) -> list[str]:
    """Return the paths of the current versions a whole warm-up selects, in order."""
    with IndexQueries(paths.index_file) as queries:
        selection = queries.warm_selection(WarmQuery(), visible=ALL_PROJECTS)
    return [path for store, path in selection.versions if store == STORE]


def _thumbnails(served: PreviewApi, versions: list[str]) -> list[str]:
    """Return the pane's thumbnails of the versions whose first look has one."""
    addresses = []
    for path in versions:
        info = served.get(version_url(path)).json()
        address = _pane_thumbnail(info)
        if address is not None:
            addresses.append(address)
    return addresses


def _cli(
    capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str
) -> tuple[int, Any]:
    """Run ``archiwista preview-warm … --json``: its status and model or error."""
    capsys.readouterr()
    registry = load_registry(cache_dir=paths.cache_dir)
    status = main(["preview-warm", *argv, "--json"], registry=registry, paths=paths)
    captured = capsys.readouterr()
    if status in (0, 10, 11, 130):
        return status, json.loads(captured.out)
    return status, refusal(captured.out, captured.err, status)


def test_who_sees_a_project_warms_its_own_data_and_sees_that_warm_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project's warm-up is for those who see the project, a store's for all.

    The owner, the person the project is shared with and an administrator
    start it (`202`, the same waiting job, which they all see); another
    person gets `404` as for an unknown project, and sees neither that job
    nor its id. Everyone may warm a store and sees that warm-up. An agent
    acts with the person who minted its token.
    """
    # Arrange: no job runs, so equal requests join the waiting one.
    monkeypatch.setattr(supervisor, "default_max_jobs", lambda: 0)
    with own_data_api(tmp_path, first=("geojson_wgs84",), second=()) as served:
        share(served.api.state, served.first.access_key, VISIBILITY)
        tokens: tuple[Literal["startup", "agent"], ...] = ("startup", "agent")
        callers = {
            (who, token): served.api.session(
                principal(served.api.state, who), token=token
            )
            for who in WHO
            for token in tokens
        }

        # Act
        asked = {
            key: _warm(caller, {"project": FIRST}) for key, caller in callers.items()
        }
        store = _warm(callers[("other", "startup")], {"store": STORE})
        project_jobs = {
            answer.json()["id"]
            for answer in asked.values()
            if answer.status_code == 202
        }
        (project_job,) = project_jobs
        listed = {key: _listed(caller) for key, caller in callers.items()}
        detail = {
            key: caller.request("GET", f"/jobs/{project_job}").status_code
            for key, caller in callers.items()
        }

    # Assert
    sees = SEES[VISIBILITY]
    for (who, token), answer in asked.items():
        if who in sees:
            assert answer.status_code == 202, (who, token, answer.text)
            assert answer.json()["params"]["project"] == FIRST
        else:
            assert_problem(answer, 404, "not_found")
    assert store.status_code == 202, store.text
    assert store.json()["params"]["store"] == STORE
    store_job = store.json()["id"]
    assert listed == {
        (who, token): {store_job, project_job} if who in sees else {store_job}
        for who in WHO
        for token in tokens
    }
    assert detail == {
        (who, token): 200 if who in sees else 404 for who in WHO for token in tokens
    }


def test_a_store_warm_up_leaves_own_data_cold_and_a_project_warm_up_prepares_it(
    tmp_path: Path,
) -> None:
    """Own files are warmed only for a project's warm-up, never for a store's.

    After a warm-up of the store, the first look at a project's own file is
    rendered by the server; after one of the project, the first look at its
    other own file comes from the cache.
    """
    with own_data_api(
        tmp_path, first=("tif_2180", "geojson_wgs84"), second=()
    ) as served:
        # Arrange
        project, owner = served.first, served.owner
        pool = served.previews.pool
        raster = project.folder.file("tif_2180").path
        vector = project.folder.file("geojson_wgs84").path

        def first_look(path: str) -> tuple[int, int]:
            """Look at an own file's pane thumbnail: its answer and the renders."""
            info = served.get(owner, project.url(path, "preview")).json()
            address = _pane_thumbnail(info)
            assert address is not None, info
            before = pool.stats().rendered
            answer = served.get(owner, address)
            return answer.status_code, pool.stats().rendered - before

        # Act
        by_store = _ended(served, _warm(owner, {"store": STORE}))
        cold = first_look(raster)
        by_project = _ended(served, _warm(owner, {"project": FIRST}))
        warm = first_look(vector)

    # Assert
    for job in (by_store, by_project):
        assert job["state"] == "succeeded", job
    assert by_store["result"]["files"] == 0
    assert by_store["result"]["versions"] > 0
    assert cold[0] == 200 and cold[1] >= 1
    assert by_project["result"]["files"] == 2
    assert warm == (200, 0)


def _ended(served: OwnDataApi, started: httpx.Response) -> dict[str, Any]:
    """Wait for the job an answer started; return it as the owner sees it."""
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]
    served.wait(job_id)
    detail: dict[str, Any] = served.owner.request("GET", f"/jobs/{job_id}").json()
    return detail


@pytest.mark.parametrize(
    ("body", "argv", "status", "code", "reason"),
    [
        ({"store": "nieznany"}, ["--store", "nieznany"], 404, "not_found", None),
        ({"project": "nieznany"}, ["--project", "nieznany"], 404, "not_found", None),
        (
            {"area_id": UNKNOWN_AREA},
            ["--area-id", UNKNOWN_AREA],
            404,
            "not_found",
            None,
        ),
        (
            {"product": ""},
            ["--product", ""],
            400,
            "validation_error",
            "invalid_request",
        ),
    ],
)
def test_a_refusal_is_the_same_by_the_api_and_the_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
    argv: list[str],
    status: int,
    code: str,
    reason: str | None,
) -> None:
    """The command's error document says what the route's problem says; no job."""
    # Arrange
    monkeypatch.setattr(supervisor, "default_max_jobs", lambda: 0)
    store, paths = scanned_store(tmp_path)

    # Act
    _, printed = _cli(capsys, paths, *argv)
    with serve_previews(store, paths) as served:
        refused = _warm(served.owner, body)
        unknown = _warm(served.owner, {"sheet": "N-34-130-D"})
        recorded = served.jobs.list(kind="preview_warm").items

    # Assert
    assert_problem(refused, status, code, reason)
    assert_same_error(printed, refused.json())
    assert_problem(unknown, 400, "validation_error", "invalid_request")
    assert recorded == ()


def test_the_command_prints_the_warm_up_as_the_route_shows_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` is `GET /jobs/{job}` of the warm-up as it ended; exit 0.

    The route answers `202` with `Location`, the job of no store with every
    filter in `params`; a second warm-up finds the work of the first ready.
    """
    # Arrange
    store, paths = scanned_store(tmp_path)

    # Act
    status, printed = _cli(capsys, paths, "--store", STORE, "--product", "nmt")
    with serve_previews(store, paths) as served:
        shown = served.owner.request("GET", f"/jobs/{printed['id']}").json()
        started = _warm(served.owner, {"store": STORE, "product": "nmt"})
        again = served.wait(started.json()["id"])

    # Assert
    assert status == 0
    assert printed == shown
    assert (shown["kind"], shown["store"], shown["state"]) == (
        "preview_warm",
        None,
        "succeeded",
    )
    assert shown["params"] == {
        "store": STORE,
        "product": "nmt",
        "segment": None,
        "project": None,
        "area_id": None,
        "since": None,
    }
    assert shown["result"]["warmed"] == shown["result"]["versions"] > 0
    assert started.status_code == 202, started.text
    assert started.headers["location"] == f"/api/v1/jobs/{started.json()['id']}"
    assert again.result is not None
    assert again.result["cached"] == shown["result"]["versions"]
    assert again.result["warmed"] == 0


def test_a_person_s_preview_is_served_at_once_while_a_slow_warm_up_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server's render pool serves a person while a warm-up works.

    The warm-up runs under a second supervisor of the same installation,
    each of its files delayed; the thumbnail of a version it has not
    reached is rendered by the server within the target of a first one.
    """
    # Arrange
    worker_path(monkeypatch)
    monkeypatch.setenv(DELAY_ENV, "2")
    with preview_api(tmp_path) as served:
        paths = served.api.paths
        versions = _current_versions(paths)
        thumbnails = _thumbnails(served, versions)
        assert served.get(thumbnails[0]).status_code == 200
        last = thumbnails[-1]
        settings = SettingsService(
            ConfigStore(paths.config_file), load_registry(cache_dir=paths.cache_dir)
        )
        with JobSupervisor(paths, settings, worker_command=WARM_WORKER) as warming:
            job = warming.submit("preview_warm", actor=LOCAL_OWNER)
            _await(lambda: _progress(warming, job.id) >= 1)

            # Act
            rendered = served.pool.stats().rendered
            started = time.perf_counter()
            answer = served.get(last)
            seconds = time.perf_counter() - started
            renders = served.pool.stats().rendered - rendered
            during = warming.get(job.id)
            warming.cancel(job.id)
            ended = warming.wait(job.id, timeout=JOB_TIMEOUT_S)

    # Assert
    assert answer.status_code == 200
    assert renders >= 1
    assert seconds <= INTERACTIVE_S, seconds
    assert during is not None and during.state == "running"
    assert ended.state == "cancelled"


def _progress(jobs: JobSupervisor, job_id: str) -> int:
    """Return how many files a warm-up has gone through."""
    record = jobs.get(job_id)
    progress: dict[str, Any] = (record.progress if record else None) or {}
    return int(progress.get("current", 0))


@_NO_ROOT
def test_a_warmed_thumbnail_is_served_after_the_store_files_become_unreadable(
    tmp_path: Path,
) -> None:
    """The first thumbnail of every warmed version comes from the cache alone.

    After the warm-up every file of the store is made unreadable (mode
    000); the pane's thumbnails are still `200` and nothing is rendered.
    """
    with preview_api(tmp_path) as served:
        # Arrange
        root = served.store.root
        warmed = served.wait(_warm(served.owner, {"store": STORE}).json()["id"])
        thumbnails = _thumbnails(served, _current_versions(served.api.paths))
        files = [
            Path(top) / name
            for top, _, names in os.walk(root)
            for name in names
            if not (Path(top) / name).is_symlink()
        ]
        modes = {path: stat.S_IMODE(path.stat().st_mode) for path in files}
        for path in files:
            path.chmod(0o000)
        try:
            # Act
            rendered = served.pool.stats().rendered
            answers = [served.get(address).status_code for address in thumbnails]
            renders = served.pool.stats().rendered - rendered
            with pytest.raises(PermissionError):
                files[0].read_bytes()
        finally:
            for path, mode in modes.items():
                path.chmod(mode)

    # Assert
    assert warmed.state == "succeeded"
    assert thumbnails
    assert answers == [200] * len(thumbnails)
    assert renders == 0


@_NO_ROOT
def test_a_read_only_store_is_warmed_and_left_as_it_was(tmp_path: Path) -> None:
    """A store without the write permission is warmed whole; nothing in it changes."""
    # Arrange
    store, paths = scanned_store(tmp_path)
    before = tree(store.base)
    set_read_only(store.base, read_only=True)
    try:
        with serve_previews(store, paths) as served:
            # Act
            warmed = served.wait(_warm(served.owner, None).json()["id"])
            thumbnails = _thumbnails(served, _current_versions(paths))
            rendered = served.pool.stats().rendered
            answers = [served.get(address).status_code for address in thumbnails]
            renders = served.pool.stats().rendered - rendered
    finally:
        set_read_only(store.base, read_only=False)

    # Assert
    assert warmed.state == "succeeded"
    assert warmed.result is not None
    assert (warmed.result["failed"], warmed.result["skipped"]) == (0, 0)
    assert answers == [200] * len(thumbnails)
    assert renders == 0
    assert tree(store.base) == before


def test_openapi_documents_the_warm_up(tmp_path: Path) -> None:
    """`202` with the job; the closed request model; refusals are problems."""
    store, paths = scanned_store(tmp_path)
    with serve_previews(store, paths) as served:
        document = served.owner.request("GET", "/openapi.json").json()

    operation = document["paths"]["/api/v1/previews/warm"]["post"]
    responses = operation["responses"]
    assert operation["operationId"] == "warm_previews"
    assert responses["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/JobDetail"
    }
    problems = {status for status in responses if int(status) >= 400}
    assert {"400", "404"} <= problems
    for status in problems:
        assert list(responses[status]["content"]) == ["application/problem+json"]
    model = document["components"]["schemas"]["WarmRequest"]
    assert model["additionalProperties"] is False
    assert model["examples"]
