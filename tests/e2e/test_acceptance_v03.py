"""Acceptance of v0.3 "Actions" on the whole path, in Chromium (plan A14).

SPEC 13 v0.3 without the network: UC-01 with the stand-in producer
(``tests/fixtures/action_source``, its store ``pomiary``, the kept area
"Kraków"). Each test walks one path a person takes and asserts the criteria
on it:

- criterion 3: the coverage labels of the area's years are the ones computed
  here by hand from the report the index keeps (SPEC 6.4: the share rounded
  down, the campaigns of the records a download takes, the ranking of the
  variants of a year);
- criterion 4: nothing is downloaded before the plan window's confirmation;
  the window's own work is a ``check`` job, which writes nothing;
- criterion 5: a server stopped during the download leaves the job
  ``interrupted``, and its retry (``POST /jobs/{job}/retry``; „Ponów” of
  „Zadania” is ``test_jobs_view.py``) fetches only what the stopped run had not;
- criterion 7: without ``store_writer`` (and without ``store_write_for_all``)
  a download is disabled with the reason, and the API answers ``403
  permission_denied`` with no job.

UC-06 (a project's jobs through its producer) left with the producers'
project manifests (A-ADR-049); the plan's P4 and P5 bring the project's jobs
and their acceptance back.

Criteria 1, 2 and 6 need the network and real stores:
``tests/integration/test_live_actions.py`` (marker ``live``, run by the
author). Criterion 8 is ``tests/perf/test_warm_perf.py`` and the report
``docs/reports/v0.3-measurements.md``.
"""

import json
import math
import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlencode, urlsplit

import pytest
from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexQueries, IndexWriter
from archiwista.jobs import JobSupervisor
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.sources import AvailabilityCombination
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.actions import ACTION_WORKER, standin_in_settings
from tests.fixtures.availability import AREA, register_standin
from tests.fixtures.browser import Served, Tab
from tests.fixtures.jobs import worker_path
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.permissions import add_people, principal

Serve = Callable[..., Served]

STORE = "pomiary"
PRODUCT = "standin/dem"
WAIT_S = 60.0
FINISHED = ("succeeded", "partial", "failed", "interrupted", "cancelled")
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


def call(
    page: Page, method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the status and JSON answer of a request made with the page's session."""
    data = None if body is None else json.dumps(body)
    answer: dict[str, Any] = page.evaluate(API, [method, path, data])
    return answer


def ended(page: Page, job: str) -> dict[str, Any]:
    """Wait for a job to end; return it as ``GET /jobs/{job}`` answers."""
    deadline = time.monotonic() + WAIT_S
    while True:
        detail: dict[str, Any] = call(page, "GET", f"/jobs/{job}")["body"]
        if detail["state"] in FINISHED:
            return detail
        assert time.monotonic() < deadline, f"job {job} did not end"
        page.wait_for_timeout(200)


def jobs_of(page: Page, kind: str) -> list[dict[str, Any]]:
    """Return the jobs of a kind the page's session sees."""
    page_of_jobs = call(page, "GET", f"/jobs?kind={kind}")["body"]
    items: list[dict[str, Any]] = page_of_jobs["items"]
    return items


def standin_paths(tmp_path: Path) -> tuple[AppPaths, Path]:
    """Save the settings of the store ``pomiary`` online; keep the area."""
    paths = local_paths(tmp_path)
    root = tmp_path / STORE
    root.mkdir()
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    ConfigStore(paths.config_file).save(
        AppSettings(offline=False, basemaps=(), stores=(store,))
    )
    with IndexWriter(paths.index_file) as writer:
        writer.write_area(AREA)
    return paths, root


def open_area(page: Page, served: Served, url: str) -> Locator:
    """Open the map on the area with the session of ``url``; return „U źródła”."""
    query = urlencode({"view": "map", "area_id": AREA.id})
    page.goto(f"{served.base}/?{query}#{urlsplit(url).fragment}")
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    step = page.get_by_role("region", name="U źródła")
    step.get_by_label("Produkt u źródła").select_option(PRODUCT)
    return step


def check_at_source(step: Locator) -> Locator:
    """Ask the source and return the rows of its report."""
    step.get_by_role("button", name="Sprawdź u źródła").click()
    rows = step.get_by_role("list", name="Lata u źródła").locator("> li")
    expect(rows).to_have_count(2)
    return rows


def label_by_hand(combination: AvailabilityCombination, land_m2: float) -> str:
    """Return the label SPEC 6.4 gives a combination, computed from its records.

    The share is exact (fractions), rounded down. Only the cases of the
    stand-in's report: complete from one campaign or from 2-4 campaigns none of
    which covers the land alone, partial with one partial sheet.
    """
    campaigns = {record.campaign for record in combination.sheet_records}
    if combination.complete:
        alone = any(item.complete for item in combination.campaign_coverage)
        assert 1 <= len(campaigns) <= 4
        if len(campaigns) == 1 or alone:
            return "pełne"
        return f"pełne · {len(campaigns)} kampanie"
    share_pct = math.floor(Fraction(combination.full_m2) * 100 / Fraction(land_m2))
    assert len(combination.sheets_partial) == 1 and 1 <= share_pct < 100
    return f"częściowe · {share_pct}% · 1 ark. niepełny"


def ranked_by_hand(
    combinations: list[AvailabilityCombination], land_m2: float
) -> list[AvailabilityCombination]:
    """Return a year's variants best first: full, larger share, fewer campaigns."""
    return sorted(
        combinations,
        key=lambda item: (
            not item.complete,
            -Fraction(item.full_m2) / Fraction(land_m2),
            len({record.campaign for record in item.sheet_records}),
            combinations.index(item),
        ),
    )


def test_uc01_a_year_of_the_area_reaches_the_store_through_the_plan_and_a_restart(
    tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Area → labels (3) → plan window (4) → download stopped by a restart (5)."""
    # Arrange
    paths, root = standin_paths(tmp_path)
    hold = root / standin.HOLD
    page = tab.page
    with serving(paths, registry=load_registry(cache_dir=paths.cache_dir)) as (
        server,
        _,
    ):
        served = Served(server, paths)
        step = open_area(page, served, served.token_url())

        # Act: the source's report of the area, kept by the index.
        rows = check_at_source(step)
        with IndexQueries(paths.index_file) as queries:
            kept = queries.availability(AREA.id, "dem", producer="standin")
        assert kept is not None
        land_m2 = sum(area.land_m2 for area in kept.report.areas)
        years: dict[int, list[AvailabilityCombination]] = {}
        for combination in kept.report.combinations:
            assert combination.year is not None
            years.setdefault(combination.year, []).append(combination)

        # Assert (criterion 3): each year's label and best variant by hand.
        assert sorted(years, reverse=True) == [2023, 2022]
        for place, year in enumerate(sorted(years, reverse=True)):
            row = rows.nth(place)
            best, *others = ranked_by_hand(years[year], land_m2)
            expect(row.locator(".src-year")).to_have_text(str(year))
            expect(row.locator(".src-row-head .src-label")).to_have_text(
                label_by_hand(best, land_m2)
            )
            expect(row.locator(".src-variant .src-dims").first).to_have_text(
                f"{best.horizontal} · {best.resolution} · {best.vertical_crs}"
            )
            if others:
                row.get_by_role("button", name=f"+{len(others)} wariant").click()
                listed = row.get_by_role("list", name=f"Pozostałe warianty roku {year}")
                expect(listed.locator(".src-label")).to_have_text(
                    [label_by_hand(item, land_m2) for item in others]
                )

        # Act (criterion 4): the plan window of 2023's best variant.
        rows.nth(0).get_by_role("button", name="Pobierz…").first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("Do pobrania: 2")

        # Assert: planned by a check job; nothing downloaded, the store empty.
        assert [job["state"] for job in jobs_of(page, "check")] == ["succeeded"]
        assert jobs_of(page, "download") == []
        assert sorted(path.name for path in root.iterdir()) == []

        # Act: confirm; the run waits after its first file, then the server stops.
        hold.touch()
        dialog.get_by_role("button", name="Pobierz 2 pozycje").click()
        expect(dialog.locator(".job-progress")).to_contain_text("1 z 2")
        (download,) = jobs_of(page, "download")
        page.goto("about:blank")
    hold.unlink()

    with serving(paths, registry=load_registry(cache_dir=paths.cache_dir)) as (
        server,
        _,
    ):
        served = Served(server, paths)
        open_area(page, served, served.token_url())

        # Assert (criterion 5): the stopped run is interrupted, one file fetched.
        stopped = call(page, "GET", f"/jobs/{download['id']}")["body"]
        assert stopped["state"] == "interrupted", stopped
        folder = root / "hydro" / "150160190"
        assert sorted(path.name for path in folder.iterdir()) == ["2024.csv"]
        fetched = (folder / "2024.csv").stat().st_mtime_ns

        # Act: its retry, the same call and plan.
        retried = call(page, "POST", f"/jobs/{download['id']}/retry")
        assert retried["status"] == 202, retried
        again = ended(page, retried["body"]["id"])

        # Assert: the finished file was not fetched again; the index has both.
        assert again["state"] == "succeeded", again
        assert again["params"]["plan_job"] == download["params"]["plan_job"]
        assert [
            (item["path"], item["status"]) for item in again["result"]["files"]
        ] == [
            ("hydro/150160190/2024.csv", "unchanged"),
            ("hydro/150160190/2025.csv", "new"),
        ]
        assert (folder / "2024.csv").stat().st_mtime_ns == fetched
        health = call(page, "GET", "/health")["body"]
        (state,) = [item["state"] for item in health["stores"]]
        assert state["versions"] == 2
    assert tab.page_errors == []


def test_uc01_without_the_permission_to_write_the_stores_nothing_is_written(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Criterion 7: the plan is shown, the download refused: no job, no file."""
    # Arrange
    root = tmp_path / STORE
    root.mkdir()
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    served = serve(AppSettings(offline=False, basemaps=(), stores=(store,)))
    with IndexWriter(served.paths.index_file) as writer:
        writer.write_area(AREA)
    state = StateStore(served.paths.state_file)
    add_people(state)
    issued = issue_one_time_token(
        served.paths.index_file, "startup", minted_by=principal(state, "other")
    )
    page = tab.page
    step = open_area(page, served, fragment_url(served.base, issued.token))

    # Act
    check_at_source(step).nth(0).get_by_role("button", name="Pobierz…").first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Do pobrania: 2")
    (plan,) = jobs_of(page, "check")
    refused = call(
        page,
        "POST",
        "/jobs",
        {
            "kind": "download",
            "producer": "standin",
            "store": STORE,
            "calls": plan["params"]["calls"],
            "plan_job": plan["id"],
        },
    )

    # Assert
    expect(dialog.get_by_role("button", name="Pobierz 2 pozycje")).to_be_disabled()
    expect(dialog).to_contain_text("ta sesja nie ma uprawnienia „zapis do magazynu”")
    assert refused["status"] == 403, refused
    assert (refused["body"]["code"], refused["body"]["details"]["reason"]) == (
        "forbidden",
        "permission_denied",
    )
    assert jobs_of(page, "download") == []
    assert list(root.iterdir()) == []
    tab.assert_clean()
