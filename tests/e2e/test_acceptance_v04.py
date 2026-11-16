"""Acceptance of v0.4 "Zespół" in Chromium (plan v0.4 T12; SPEC 13 "v0.4" 1, 3).

Three people use one team server over TLS (``team_serve``), each in a browser
context of their own: Anna (``admin``, ``store_writer``), Marek
(``store_writer``) and Kasia (no role, a member of ``hydro``). The stand-in
producer (``tests/fixtures/action_source``) serves the store ``pomiary``: while
the store holds the stand-in's ``HOLD`` a run waits after its first new file,
and every transfer is a line of ``FETCHES``.

- Kasia plans a pasted line: the plan shows, its download is disabled with the
  reason, and the route answers ``403`` and starts no job.
- Marek's planned download of two stations and his download of a fourth run,
  held, so his third network job waits, and so does Anna's planned download of
  one of his stations and another. His cancel frees a place: Anna's download
  takes it before his third job, leaves the positions his first download
  claimed to it and fetches her other station's. Kasia's „Zadania” names them
  both; Anna's downloads list says what Marek fetches; every file is fetched
  once.
- Kasia creates a project and shares it with ``hydro``: Marek does not see it,
  Anna as an administrator does.
- Anna's „Dziennik” shows the three sign-ins, the job starts and Kasia's
  refusal.
- Marek signs out; Anna and Kasia stay signed in.

The run on three computers with the store on an SMB share is the author's,
from ``docs/reports/v0.4-lan-runbook.md``.
"""

import json
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import kartograf
import pytest
from playwright.sync_api import Locator, Page, expect

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, StoreConfig
from archiwista.jobs import JobSupervisor
from archiwista.state import StateStore
from tests.fixtures.actions import ACTION_WORKER, standin_in_settings, station_calls
from tests.fixtures.availability import register_standin
from tests.fixtures.browser import Tab
from tests.fixtures.jobs import worker_path
from tests.fixtures.team_pages import signed_in
from tests.fixtures.team_server import (
    ADMIN_ACCOUNT,
    ADMIN_PASSWORD,
    TeamServed,
    add_person,
)

TeamServe = Callable[..., TeamServed]
TeamTab = Callable[..., Tab]
STORE = "pomiary"
PASSWORD = "wiosla-na-Dunajcu-7"
WAIT_S = 60.0
FINISHED = ("succeeded", "partial", "failed", "interrupted", "cancelled")
# Marek plans the first two stations, Anna the second and the third: the
# second is planned by both. Marek's other downloads have a station each, and
# Kasia plans a station of her own.
MAREK_PLAN = ("150160180", "150160190")
ANNA_PLAN = ("150160190", "150160200")
MAREK_OTHER, MAREK_THIRD, KASIA_STATION = "150160210", "150160220", "150160230"
NO_STORE_WRITE = (
    "Pobieranie zapisuje magazyn, a ta sesja nie ma uprawnienia „zapis do"
    " magazynu” (rola store_writer). Plan można obejrzeć."
)
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: response.status, body: await response.json() };
}"""


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Install the real stand-in worker in the server and its child processes."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    roots = StoreConfig.roots

    def both(self: StoreConfig) -> dict[str, Path]:
        """Expose the same fixture root to the stand-in and project adapter."""
        store = roots(self)
        return {**store, "kartograf": store["standin"]}

    monkeypatch.setattr(StoreConfig, "roots", both)
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", ACTION_WORKER)
    return module


def call(
    page: Page, method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Request the API as the person signed in in this browser."""
    result: dict[str, Any] = page.evaluate(
        API, [method, path, None if body is None else json.dumps(body)]
    )
    return result


def job_request(kind: str, *stations: str, plan: str | None = None) -> dict[str, Any]:
    """Return the body of a ``check`` or ``download`` of the stations' files."""
    request: dict[str, Any] = {
        "kind": kind,
        "producer": "standin",
        "store": STORE,
        "calls": station_calls(*stations),
    }
    if plan is not None:
        request["plan_job"] = plan
    return request


def start(page: Page, body: dict[str, Any]) -> str:
    """Start a job as the page's person; return its id."""
    answer = call(page, "POST", "/jobs", body)
    assert answer["status"] == 202, answer
    job: str = answer["body"]["id"]
    return job


def job(page: Page, job_id: str) -> dict[str, Any]:
    """Return a job as the page's person reads it."""
    answer = call(page, "GET", f"/jobs/{job_id}")
    assert answer["status"] == 200, answer
    detail: dict[str, Any] = answer["body"]
    return detail


def until(page: Page, job_id: str, done: Callable[[dict[str, Any]], bool]) -> None:
    """Wait for a job to reach ``done``, bounded apart from the browser's waits."""
    deadline = time.monotonic() + WAIT_S
    while not done(job(page, job_id)):
        assert time.monotonic() < deadline, f"job {job_id}: {job(page, job_id)}"
        page.wait_for_timeout(100)


def finished(page: Page, job_id: str) -> dict[str, Any]:
    """Wait for a job to end; return it."""
    until(page, job_id, lambda detail: detail["state"] in FINISHED)
    return job(page, job_id)


def held(page: Page, job_id: str) -> None:
    """Wait for a download to report its first new file: it waits on ``HOLD``."""
    until(
        page,
        job_id,
        lambda detail: (detail["progress"] or {}).get("status") == "completed",
    )


def scanned(page: Page) -> None:
    """Wait for the scheduler's first scan of the store to end."""
    deadline = time.monotonic() + WAIT_S
    while True:
        stores = call(page, "GET", "/health")["body"]["stores"]
        if all(
            s["state"]["last_scan"] and not s["state"]["running_job"] for s in stores
        ):
            return
        assert time.monotonic() < deadline, "the store was not scanned in time"
        page.wait_for_timeout(100)


def row(page: Page, job_id: str) -> Locator:
    """Return the row of a job in „Zadania”."""
    jobs = page.get_by_role("list", name="Lista zadań")
    return jobs.locator(f'> li[data-job="{job_id}"]')


def logged(page: Page, action: str) -> list[dict[str, Any]]:
    """Return the entries of an action in the log, newest first."""
    answer = call(page, "GET", f"/log?action={action}&limit=200")
    assert answer["status"] == 200, answer
    entries: list[dict[str, Any]] = answer["body"]["items"]
    return entries


@pytest.mark.parametrize("team_tab", ["chromium"], indirect=True)
def test_three_people_share_one_queue_and_keep_their_own_permissions(
    team_serve: TeamServe, team_tab: TeamTab, tmp_path: Path, standin: ModuleType
) -> None:
    """Criteria 1 and 3 of v0.4 with three people, as the plan's T12 says."""
    # Arrange: the store, a free project directory and three people signed in.
    root = tmp_path / STORE
    kartograf.init_store(root)
    projects = tmp_path / "projekty"
    projects.mkdir()
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    settings = AppSettings(
        offline=False,
        basemaps=(),
        network_jobs_per_person=2,
        stores=(store,),
        project_dirs=(projects,),
    )
    served = team_serve(settings)
    add_person(
        served.paths, "marek", PASSWORD, name="Marek Lis", roles=["store_writer"]
    )
    add_person(served.paths, "kasia", PASSWORD, name="Kasia Wrona")
    state = StateStore(served.paths.state_file)
    state.update_user(ADMIN_ACCOUNT, roles=("admin", "store_writer"), actor=LOCAL_OWNER)
    state.add_group("hydro", name="Hydrologia", members=("kasia",), actor=LOCAL_OWNER)
    tabs = [team_tab() for _ in range(3)]
    anna, marek, kasia = (tab.page for tab in tabs)
    signed_in(anna, served.origin, ADMIN_ACCOUNT, ADMIN_PASSWORD)
    signed_in(marek, served.origin, "marek", PASSWORD)
    signed_in(kasia, served.origin, "kasia", PASSWORD)
    scanned(anna)

    # Act: Kasia plans a pasted line, then asks the API for its download.
    kasia.goto(f"{served.origin}/?view=map")
    step = kasia.get_by_role("region", name="U źródła")
    line = f"standin series fetch --station {KASIA_STATION} --kind hydro"
    step.get_by_label("Wklej polecenie producenta").fill(line)
    step.get_by_role("button", name="Zaplanuj…").click()
    plan = kasia.get_by_role("dialog", name="Pobrać? standin · series fetch")
    expect(plan).to_contain_text("Do pobrania: 2")
    refused = call(kasia, "POST", "/jobs", job_request("download", KASIA_STATION))

    # Assert: the plan with its download disabled and why; 403 and no job.
    expect(plan.get_by_role("button", name="Pobierz 2 pozycje")).to_be_disabled()
    expect(plan.get_by_role("note")).to_have_text(NO_STORE_WRITE)
    assert refused["status"] == 403, refused
    assert refused["body"]["code"] == "forbidden"
    downloads = call(kasia, "GET", "/jobs?kind=download")["body"]["items"]
    assert downloads == []
    plan.get_by_role("button", name="Anuluj").click()
    expect(plan).to_be_hidden()

    # Act: both plans; Marek's two downloads held, his third and Anna's queued.
    marek_plan = start(marek, job_request("check", *MAREK_PLAN))
    anna_plan = start(anna, job_request("check", *ANNA_PLAN))
    assert finished(marek, marek_plan)["state"] == "succeeded"
    assert finished(anna, anna_plan)["state"] == "succeeded"
    hold = root / standin.HOLD
    hold.touch()
    try:
        first = start(marek, job_request("download", *MAREK_PLAN, plan=marek_plan))
        held(marek, first)
        other = start(marek, job_request("download", MAREK_OTHER))
        held(marek, other)
        third = start(marek, job_request("download", MAREK_THIRD))
        second = start(anna, job_request("download", *ANNA_PLAN, plan=anna_plan))
        waiting = [job(anna, job_id)["state"] for job_id in (third, second)]
        marek.goto(f"{served.origin}/?view=jobs")
        row(marek, other).get_by_role("button", name="Anuluj").click()
        expect(row(marek, other).locator(".state-badge").first).to_have_text(
            "anulowane"
        )
        held(anna, second)
        kasia.goto(f"{served.origin}/?view=jobs")
        anna.reload()

        # Assert: Anna's took the freed place before Marek's third; Kasia sees
        # who runs what; Anna's downloads list names what Marek fetches.
        assert waiting == ["queued", "queued"]
        assert job(kasia, third)["state"] == "queued"
        for job_id, who, badge in (
            (first, "marek", "trwa"),
            (second, ADMIN_ACCOUNT, "trwa"),
            (third, "marek", "w kolejce"),
        ):
            expect(row(kasia, job_id).locator(".jobs-who")).to_have_text(who)
            expect(row(kasia, job_id).locator(".state-badge").first).to_have_text(badge)
        top = anna.get_by_role("banner")
        top.get_by_role("button", name="Pobieranie 0/1", exact=False).click()
        listed = anna.get_by_role("dialog", name="Pobrania w tle").get_by_role(
            "list", name="Pobrania w tle"
        )
        expect(listed.locator("> li")).to_have_count(1)
        expect(listed.locator("> li").first).to_contain_text(
            f"Pozycje do pobrania (2) pobiera już marek w zadaniu {first}"
        )
    finally:
        hold.unlink(missing_ok=True)

    # Assert: each file fetched once; the shared station's by Marek's download.
    ended = {job_id: finished(anna, job_id) for job_id in (first, second, third)}
    assert ended[first]["state"] == "succeeded", ended[first]
    assert ended[second]["state"] == "partial", ended[second]
    assert ended[third]["state"] == "succeeded", ended[third]
    taken = ended[second]["result"]["taken"]
    assert sorted(item["path"] for item in taken) == [
        f"hydro/{ANNA_PLAN[0]}/2024.csv",
        f"hydro/{ANNA_PLAN[0]}/2025.csv",
    ]
    assert {(item["job"], item["actor"]) for item in taken} == {(first, "marek")}
    transfers = Counter((root / standin.FETCHES).read_text(encoding="utf-8").split())
    assert set(transfers.values()) == {1}, transfers
    for station in (*MAREK_PLAN, ANNA_PLAN[1]):
        for year in ("2024", "2025"):
            assert transfers[f"hydro/{station}/{year}.csv"] == 1
    expect(listed.locator("> li").first).to_contain_text(
        f"2 pozycje pobiera marek (zadanie {first})"
    )

    # Act: Kasia creates a project and shares it with hydro.
    kasia.goto(f"{served.origin}/?view=projects")
    expect(kasia.get_by_role("heading", name="Projekty")).to_be_visible()
    kasia.get_by_role("button", name="Nowy projekt…").click()
    form = kasia.get_by_role("form", name="Nowy projekt")
    form.get_by_label("Katalog projektu").fill(str(projects / "raba"))
    form.get_by_role("button", name="Załóż projekt").click()
    card = kasia.get_by_role("complementary", name="Projekt")
    card.get_by_role("button", name="Udostępnij…").click()
    sharing = kasia.get_by_role("dialog", name="Udostępnianie · projekt raba")
    sharing.get_by_label("wybrane grupy").check()
    sharing.get_by_label("+ grupa").select_option(label="Hydrologia (hydro)")
    sharing.get_by_role("button", name="Zapisz").click()
    expect(sharing).to_be_hidden()
    marek.goto(f"{served.origin}/?view=projects")

    # Assert: hers, shared with hydro; Marek does not see it, Anna does.
    expect(
        marek.get_by_text("Nie znaleziono projektów w katalogach projektów z ustawień.")
    ).to_be_visible()
    assert call(marek, "GET", "/projects/raba")["status"] == 404
    assert call(anna, "GET", "/projects/raba")["status"] == 200
    access = call(anna, "GET", "/projects/raba/access")["body"]
    assert (access["owner"], access["visibility"]) == ("kasia", "group")
    assert access["groups"] == ["hydro"]

    # Act: Anna reads „Dziennik” by the groups of actions.
    anna.goto(f"{served.origin}/?view=log")
    expect(anna.get_by_role("heading", name="Dziennik działań")).to_be_visible()
    filters = anna.get_by_role("group", name="Filtry dziennika")
    signs = {entry["actor"]: entry["id"] for entry in logged(anna, "session.login")}
    starts = {entry["target"]: entry for entry in logged(anna, "job.start")}
    (denied,) = (
        entry
        for entry in logged(anna, "permission.denied")
        if entry["actor"] == "kasia"
    )

    # Assert: the three sign-ins, the job starts and Kasia's refusal.
    assert {"kasia", "marek", ADMIN_ACCOUNT} <= set(signs)
    filters.get_by_label("Działanie").select_option(label="Logowanie i sesje")
    for account in ("kasia", "marek", ADMIN_ACCOUNT):
        entry = anna.locator(f'tr[data-entry="{signs[account]}"]')
        expect(entry).to_contain_text("logowanie")
        expect(entry).to_contain_text(account)
    filters.get_by_label("Działanie").select_option(label="Zadania")
    for job_id, account in (
        (marek_plan, "marek"),
        (first, "marek"),
        (other, "marek"),
        (third, "marek"),
        (anna_plan, ADMIN_ACCOUNT),
        (second, ADMIN_ACCOUNT),
    ):
        assert starts[job_id]["actor"] == account
        entry = anna.locator(f'tr[data-entry="{starts[job_id]["id"]}"]')
        expect(entry).to_contain_text("uruchomienie zadania")
    assert denied["target"] == STORE
    assert denied["details"]["action"] == "store.write"
    filters.get_by_label("Działanie").select_option(label="Odmowy")
    entry = anna.locator(f'tr[data-entry="{denied["id"]}"]')
    expect(entry).to_contain_text("odmowa dostępu store.write")
    expect(entry).to_contain_text("kasia")

    # Act: Marek signs out.
    marek.get_by_role("button", name="Konto: Marek Lis").click()
    marek.get_by_role("button", name="Wyloguj").click()

    # Assert: his browser is back at the sign-in; the others' sessions stay.
    expect(marek.get_by_role("heading", name="Logowanie")).to_be_visible()
    assert call(anna, "GET", "/session")["status"] == 200
    assert call(kasia, "GET", "/session")["status"] == 200
    assert [entry["actor"] for entry in logged(anna, "session.logout")] == ["marek"]
    for tab in tabs:
        tab.assert_clean()
