"""„Zadania”: everyone's jobs in Chromium and Firefox (plan v0.4 T9, A12 of plan A).

The stand-in producer (``tests/fixtures/action_source``) serves the store
``pomiary``; the server's workers run as ``ACTION_WORKER``, and while the store
holds the stand-in's ``HOLD`` a download waits after its first new file. The
directory ``tajny`` is Olga's private project. Igor (``store_writer``) opens
„Zadania”: his held download shows its progress and stops by „Anuluj”, Olga's
held download and her scan of her project's data folder show her name, the
second without any detail; his planned download of a station her download
claimed lists those positions as hers. A download stopped by a restart of the
server is „przerwane” and „Ponów” runs it again. „Ponów” of a job only an
administrator retries (a store's scan, outlines and link check, the scan of
every project's data folder) is disabled for Igor with its reason. With
``ARCHIWISTA_SCREENSHOTS=<directory>`` the queue is kept as ``08-zadania.png``
(``docs/reports/v0.4-screenshots/``).
"""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from kartograf import init_project
from playwright.sync_api import Locator, Page, expect

from archiwista.auth import LOCAL_OWNER, SCHEDULER, Principal, access_key
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter, initialize
from archiwista.index.projects import record_project
from archiwista.jobs import JobSupervisor
from archiwista.security import CSRF_HEADER, fragment_url, issue_one_time_token
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore, Visibility
from tests.fixtures.actions import ACTION_WORKER, standin_in_settings, station_calls
from tests.fixtures.availability import register_standin
from tests.fixtures.browser import Served, Tab
from tests.fixtures.jobs import worker_path
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.permissions import (
    OTHER,
    OWNER,
    WRITER,
    add_people,
    principal,
    share,
)

STORE = "pomiary"
WAIT_S = 60.0
FINISHED = ("succeeded", "partial", "failed", "interrupted", "cancelled")
# Stations: Olga's and Igor's planned downloads share the first; the second is
# only Igor's plan; the third his download without a plan.
SHARED, OWN, UNPLANNED = "150160180", "150160200", "150160210"
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
ADMIN_ONLY = (
    "Skan magazynu, obrysy jednostek, potwierdzenie dowiązania i skan danych"
    " wszystkich projektów zleca i ponawia administrator (rola admin)."
)
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const answer = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: answer.status, body: await answer.json() };
}"""


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in; the server's workers give it the store's directory."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", ACTION_WORKER)
    return module


def team_paths(
    tmp_path: Path, visibility: Visibility = "private"
) -> tuple[AppPaths, Path, str]:
    """Save the store ``pomiary`` and the people; index Olga's project ``tajny``.

    The project has ``visibility``, private by default. Returns the
    installation, the store's directory and the project's key.
    """
    paths = local_paths(tmp_path)
    root = tmp_path / STORE
    root.mkdir()
    projects = tmp_path / "projekty"
    directory = projects / "tajny"
    init_project(directory, root=root)
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    settings = AppSettings(
        offline=False, basemaps=(), stores=(store,), project_dirs=(projects,)
    )
    ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    adapter = load_registry(cache_dir=paths.cache_dir).adapter("kartograf")
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: store.roots()})
        key = record_project(adapter, writer, directory, stores=settings.stores)
    state = StateStore(paths.state_file)
    add_people(state)
    for person in (OWNER, OTHER):
        state.update_user(person, roles=WRITER, actor=LOCAL_OWNER)
    share(state, access_key(directory), visibility)
    return paths, root, key


def session_url(served: Served, person: Principal) -> str:
    """Return a one-time session address of ``person``."""
    issued = issue_one_time_token(served.paths.index_file, "startup", minted_by=person)
    return fragment_url(served.base, issued.token)


def open_jobs(page: Page, served: Served, url: str) -> None:
    """Open „Zadania” with the session of ``url`` once the store is scanned."""
    page.goto(f"{served.base}/?view=jobs#{urlsplit(url).fragment}")
    expect(page.get_by_role("heading", name="Zadania w tle")).to_be_visible()
    deadline = time.monotonic() + WAIT_S
    while True:
        stores = call(page, "GET", "/health")["stores"]
        if all(
            s["state"]["last_scan"] and not s["state"]["running_job"] for s in stores
        ):
            return
        assert time.monotonic() < deadline, "the store was not scanned in time"
        page.wait_for_timeout(200)


def call(page: Page, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Return the JSON answer of an API request made with the page's session."""
    data = None if body is None else json.dumps(body)
    answer: dict[str, Any] = page.evaluate(API, [method, path, data])
    assert answer["status"] in (200, 202), answer
    return answer["body"]


def body(kind: str, *stations: str, plan_job: str | None = None) -> dict[str, Any]:
    """Return the body of a ``check`` or ``download`` of the stations' files."""
    request: dict[str, Any] = {
        "kind": kind,
        "producer": "standin",
        "store": STORE,
        "calls": station_calls(*stations),
    }
    if plan_job is not None:
        request["plan_job"] = plan_job
    return request


class Person:
    """Another person's session over HTTP, as another computer would use it."""

    def __init__(self, client: httpx.Client, csrf: str) -> None:
        self.client = client
        self.csrf = csrf

    def request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        """Return the JSON answer of a request that succeeded."""
        answer = self.client.request(
            method, f"/api/v1{path}", json=json, headers={CSRF_HEADER: self.csrf}
        )
        assert answer.status_code in (200, 202), answer.text
        return answer.json()

    def ended(self, job: str) -> dict[str, Any]:
        """Wait for a job to end; return it."""
        deadline = time.monotonic() + WAIT_S
        while True:
            detail: dict[str, Any] = self.request("GET", f"/jobs/{job}")
            if detail["state"] in FINISHED:
                return detail
            assert time.monotonic() < deadline, f"job {job} did not end"
            time.sleep(0.1)


@contextmanager
def person_session(served: Served, person: Principal) -> Iterator[Person]:
    """Yield ``person``'s session, started with a one-time token."""
    issued = issue_one_time_token(served.paths.index_file, "startup", minted_by=person)
    with httpx.Client(base_url=served.base) as client:
        started = client.post("/api/v1/session", json={"token": issued.token})
        assert started.status_code == 200, started.text
        yield Person(client, started.json()["csrf_token"])


def ended(page: Page, job: str) -> dict[str, Any]:
    """Wait for a job to end; return it as the page's session gets it."""
    deadline = time.monotonic() + WAIT_S
    while True:
        detail: dict[str, Any] = call(page, "GET", f"/jobs/{job}")
        if detail["state"] in FINISHED:
            return detail
        assert time.monotonic() < deadline, f"job {job} did not end"
        page.wait_for_timeout(200)


def held(page: Page, job: str) -> None:
    """Wait until a download reported its first new file: it waits on ``HOLD``."""
    deadline = time.monotonic() + WAIT_S
    while True:
        progress = call(page, "GET", f"/jobs/{job}")["progress"]
        if progress and progress.get("status") == "completed":
            return
        assert time.monotonic() < deadline, f"job {job} fetched nothing"
        page.wait_for_timeout(200)


def row(page: Page, job: str) -> Locator:
    """Return the row of a job in „Zadania”."""
    return page.get_by_role("list", name="Lista zadań").locator(
        f'> li[data-job="{job}"]'
    )


def shot(page: Page, name: str) -> None:
    """Keep a screenshot for the report when ``ARCHIWISTA_SCREENSHOTS`` is set."""
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(directory) / f"{name}.png"))


def test_everyone_sees_the_queue_with_names_progress_and_no_hidden_details(
    engine_tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Igor's and Olga's jobs, her hidden one bare; cancel, taken, „Moje”."""
    # Arrange
    paths, root, key = team_paths(tmp_path)
    hold = root / standin.HOLD
    page = engine_tab.page
    registry = load_registry(cache_dir=paths.cache_dir)
    with serving(paths, registry=registry) as (server, _):
        served = Served(server, paths)
        state = StateStore(paths.state_file)
        open_jobs(page, served, session_url(served, principal(state, "other")))
        hold.touch()
        with person_session(served, principal(state, "owner")) as olga:
            planned = olga.request("POST", "/jobs", body("check", SHARED))
            olga.ended(planned["id"])
            hers = olga.request(
                "POST", "/jobs", body("download", SHARED, plan_job=planned["id"])
            )
            folder = olga.ended(olga.request("POST", f"/projects/{key}/scan")["id"])

        # Act: Igor's download without a plan, held after its first file.
        mine = call(page, "POST", "/jobs", body("download", UNPLANNED))
        held(page, mine["id"])
        held(page, hers["id"])

        # Assert: his and hers with names and progress; her project's scan bare.
        own = row(page, mine["id"])
        expect(own.locator(".state-badge").first).to_have_text("trwa")
        expect(own.locator(".jobs-who")).to_have_text("Ty")
        expect(own).to_contain_text("1 z 4")
        expect(row(page, hers["id"]).locator(".jobs-who")).to_have_text("olga")
        expect(row(page, hers["id"])).to_contain_text("1 z 2")
        hidden = row(page, folder["id"])
        expect(hidden).to_contain_text("Skan danych własnych · bez dostępu")
        expect(hidden.locator(".jobs-who")).to_have_text("olga")
        expect(hidden).not_to_contain_text(key)
        expect(hidden.get_by_role("group", name="Działania zadania")).to_have_count(0)
        navigation = page.get_by_role("navigation", name="Widoki")
        expect(navigation.get_by_role("link", name="Zadania")).to_contain_text(
            "trwa: 2"
        )
        shot(page, "08-zadania")

        # Act: his cancel; then his plan of the shared station and his own.
        own.get_by_role("button", name="Anuluj").click()
        expect(own.locator(".state-badge").first).to_have_text("anulowane")
        checked = call(page, "POST", "/jobs", body("check", SHARED, OWN))
        ended(page, checked["id"])
        second = call(
            page, "POST", "/jobs", body("download", SHARED, OWN, plan_job=checked["id"])
        )
        held(page, second["id"])
        hold.unlink()
        ended(page, second["id"])
        ended(page, hers["id"])

        # Assert: the shared station's positions are Olga's, named in his row.
        taken = row(page, second["id"])
        expect(taken.locator(".state-badge").first).to_have_text("zakończone częściowo")
        expect(taken).to_contain_text(f"2 pozycje pobiera olga (zadanie {hers['id']})")
        taken.get_by_role("button", name="Szczegóły").click()
        expect(taken.locator(".jobs-details")).to_contain_text("pobiera już olga")
        taken.get_by_role("button", name="Dziennik").click()
        expect(taken.locator(".jobs-log")).to_be_visible()

        # Act: only his jobs.
        page.get_by_role("group", name="Które zadania").get_by_role(
            "button", name="Moje"
        ).click()

        # Assert
        listed = page.get_by_role("list", name="Lista zadań").locator("> li")
        expect(listed).to_have_count(3)
        expect(row(page, hers["id"])).to_have_count(0)
        assert "filter=mine" in page.url
    engine_tab.assert_clean()


def test_a_download_stopped_by_a_restart_is_interrupted_and_runs_again(
    engine_tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """„przerwane” after the server stopped; „Ponów” fetches the rest."""
    # Arrange: the owner's download waits after its first file; the server stops.
    paths, root, _ = team_paths(tmp_path)
    hold = root / standin.HOLD
    page = engine_tab.page
    registry = load_registry(cache_dir=paths.cache_dir)
    with serving(paths, registry=registry) as (server, _):
        served = Served(server, paths)
        open_jobs(page, served, served.token_url())
        hold.touch()
        stopped = call(page, "POST", "/jobs", body("download", UNPLANNED))
        held(page, stopped["id"])
        expect(row(page, stopped["id"])).to_contain_text("1 z 4")
        page.goto("about:blank")
    hold.unlink()

    with serving(paths, registry=registry) as (server, _):
        served = Served(server, paths)
        open_jobs(page, served, served.token_url())
        interrupted = row(page, stopped["id"])
        expect(interrupted.locator(".state-badge").first).to_have_text("przerwane")

        # Act
        interrupted.get_by_role("button", name="Ponów").click()

        # Assert: a new job of the same call, which fetches the rest.
        expect(interrupted).to_contain_text("Ponowiono jako zadanie")
        retried = call(page, "GET", "/jobs?kind=download")["items"][0]
        assert retried["id"] != stopped["id"]
        assert retried["params"] == stopped["params"]
        again = ended(page, retried["id"])
        assert again["state"] == "succeeded", again
        assert [f["status"] for f in again["result"]["files"]] == [
            "unchanged",
            "new",
            "new",
            "new",
        ]
        expect(row(page, retried["id"]).locator(".state-badge").first).to_have_text(
            "zakończone"
        )
        expect(interrupted.locator(".state-badge").first).to_have_text("przerwane")
    engine_tab.assert_clean()


def test_retry_of_a_job_only_an_administrator_retries_is_disabled_with_its_reason(
    engine_tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Igor's „Ponów” of the store's jobs and of every folder's scan says why not.

    The store's scan, unit outlines and link check and the scan of every
    project's data folder are an administrator's (``store.scan``): Igor
    (``store_writer``) sees their „Ponów” disabled with the reason, the one of
    his scan of a public project's folder enabled; the computer's owner, an
    administrator, retries the store's scan.
    """
    # Arrange: each job cancelled while it waits, before the server starts.
    paths, _, key = team_paths(tmp_path, "public")
    igor = principal(StateStore(paths.state_file), "other")
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    submitted: dict[str, tuple[str, str | None, dict[str, Any], Principal]] = {
        "scan": ("scan", STORE, {"mode": "full"}, LOCAL_OWNER),
        "footprints": ("footprints", STORE, {}, LOCAL_OWNER),
        "link_check": ("link_check", STORE, {"slot": SHARED}, LOCAL_OWNER),
        "every_folder": ("own_scan", None, {}, SCHEDULER),
        "his_folder": ("own_scan", None, {"project": key}, igor),
    }
    jobs: dict[str, str] = {}
    with JobSupervisor(paths, settings, max_jobs=0) as supervisor:
        for name, (kind, store, params, actor) in submitted.items():
            job = supervisor.submit(kind, store=store, params=params, actor=actor)
            assert supervisor.cancel(job.id).state == "cancelled"
            jobs[name] = job.id
    page = engine_tab.page
    with serving(paths, registry=registry) as (server, _):
        served = Served(server, paths)

        # Act
        open_jobs(page, served, session_url(served, igor))

        # Assert: the four of an administrator disabled with the reason.
        for name in ("scan", "footprints", "link_check", "every_folder"):
            refused = row(page, jobs[name]).get_by_role("button", name="Ponów")
            expect(refused).to_be_disabled()
            expect(refused).to_have_accessible_description(ADMIN_ONLY)
        folder = row(page, jobs["his_folder"]).get_by_role("button", name="Ponów")
        expect(folder).to_be_enabled()

        # Act: the computer's owner retries the store's scan.
        page.goto("about:blank")
        open_jobs(page, served, served.token_url())
        for name in ("scan", "footprints", "link_check", "every_folder"):
            expect(
                row(page, jobs[name]).get_by_role("button", name="Ponów")
            ).to_be_enabled()
        row(page, jobs["scan"]).get_by_role("button", name="Ponów").click()

        # Assert: a new scan of the store, the owner's.
        expect(row(page, jobs["scan"])).to_contain_text("Ponowiono jako zadanie")
        retried = call(page, "GET", "/jobs?kind=scan")["items"][0]
        assert retried["id"] != jobs["scan"]
        assert (retried["actor"], retried["params"]["mode"]) == ("local", "full")
    engine_tab.assert_clean()
