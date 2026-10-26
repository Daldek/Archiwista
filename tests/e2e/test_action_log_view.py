"""„Dziennik”: the action log of administrators in Chromium and Firefox (plan v0.4 T8).

The state database holds a dated log, restored so that its entries keep their
times: fifty scans Olga started ten days ago, then her change of a project's
sharing, Ada's change of the settings, Igor's refusal, the scheduler's pruning
and an agent's file download in the last days, and the accounts made today.
Ada (an administrator) pages through it, filters it by the group of actions,
the outcome, the person and the days, which the address keeps, opens a row
with the state before and after, and exports the entries the filters select
as CSV and JSON Lines. Igor (no administrator) has no „Dziennik” and gets the
server's refusal. With ``ARCHIWISTA_SCREENSHOTS=<directory>`` the log is kept
as ``07-dziennik.png`` (``docs/reports/v0.4-screenshots/``).
"""

import csv
import io
import json
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, expect

from archiwista.auth import LOCAL_OWNER, Principal
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.services.log import FIELDS
from archiwista.sources.registry import load_registry
from archiwista.state import (
    ActionEntry,
    ActionName,
    ActorKind,
    Outcome,
    StateSnapshot,
    StateStore,
)
from tests.fixtures.browser import Served, Tab
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.permissions import (
    ADMIN,
    LISTED,
    OTHER,
    OWNER,
    add_people,
    principal,
)

STORE = "pomiary"
# The time zone of the test browsers (tests/e2e/conftest.py): the filters' days.
WARSAW = ZoneInfo("Europe/Warsaw")
# Olga's scans ten days ago, so that the log has a second page.
SCANS = 50
WAIT_S = 60.0
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
HEALTH = """async () => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch("/api/v1/health", { headers });
  return answer.json();
}"""


def entry(
    number: int,
    at: datetime,
    action: ActionName,
    target: str,
    *,
    actor: str = OWNER,
    kind: ActorKind = "user",
    session: str | None = "5e1f0a9b3c",
    client: str | None = "10.0.0.15",
    outcome: Outcome = "ok",
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
    details: dict[str, object] | None = None,
) -> ActionEntry:
    """Return an entry of the restored log, Olga's in her browser by default."""
    return ActionEntry(
        id=number,
        at=at,
        actor=actor,
        actor_kind=kind,
        session=session,
        client=client,
        action=action,
        target=target,
        outcome=outcome,
        before=before,
        after=after,
        details=details,
    )


def dated_log(today: date) -> tuple[ActionEntry, ...]:
    """Return the log of the days before ``today``, its ids rising with its times."""

    def day(before: int, hour: int) -> datetime:
        return datetime.combine(today - timedelta(days=before), clock(hour), WARSAW)

    scans = tuple(
        entry(
            number,
            day(10, 8) + timedelta(minutes=number),
            "job.start",
            f"{number:016x}",
            details={"kind": "scan", "store": STORE},
        )
        for number in range(1, SCANS + 1)
    )
    pruned = (day(1, 3) - timedelta(days=365)).astimezone(UTC)
    return (
        *scans,
        entry(
            51,
            day(5, 12),
            "project.access",
            "7c2e9f4a1b3d5e60",
            before={"owner": OWNER, "visibility": "private", "groups": []},
            after={"owner": OWNER, "visibility": "group", "groups": ["hydro"]},
        ),
        entry(
            52,
            day(3, 12),
            "settings.update",
            "settings",
            actor=ADMIN,
            session="a41c9e7d20",
            client="10.0.0.2",
            before={"network_jobs_per_person": 2},
            after={"network_jobs_per_person": 3},
        ),
        entry(
            53,
            day(2, 12),
            "permission.denied",
            "settings",
            actor=OTHER,
            session="c3d81f6a95",
            client="10.0.0.22",
            outcome="denied",
            details={"action": "settings.update", "route": "PUT /settings"},
        ),
        entry(
            54,
            day(1, 3),
            "log.prune",
            "log",
            actor=LOCAL_OWNER.id,
            kind="scheduler",
            session=None,
            client=None,
            details={"before": pruned.isoformat(timespec="seconds"), "count": 3},
        ),
        entry(
            55,
            day(1, 12),
            "file.download",
            f"version:{STORE}:150160180/2026-10-01_1/150160180.csv",
            actor=LISTED,
            kind="agent",
            session="0d9b27e4f1",
            client="10.0.0.17",
            details={"size_bytes": 182044},
        ),
    )


def log_paths(tmp_path: Path) -> tuple[AppPaths, date]:
    """Save the empty store ``pomiary``, restore the dated log, add the people.

    Returns the installation and today in Warsaw.
    """
    paths = local_paths(tmp_path)
    root = tmp_path / STORE
    root.mkdir()
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    settings = AppSettings(offline=False, basemaps=(), stores=(store,))
    ConfigStore(paths.config_file).save(settings)
    today = datetime.now(WARSAW).date()
    state = StateStore(paths.state_file)
    state.restore(
        StateSnapshot(
            users=(),
            groups=(),
            projects=(),
            passwords=(),
            preferences=(),
            actions=dated_log(today),
        )
    )
    add_people(state)
    return paths, today


def open_log(page: Page, served: Served, person: Principal) -> None:
    """Load „Dziennik” with a new session of ``person`` once the store is scanned.

    The page loads anew: a token given to an open page starts its session in
    the views already shown. It returns when the shell no longer reports the
    scan of the store.
    """
    issued = issue_one_time_token(served.paths.index_file, "startup", minted_by=person)
    fragment = urlsplit(fragment_url(served.base, issued.token)).fragment
    page.goto("about:blank")
    page.goto(f"{served.base}/?view=log#{fragment}")
    expect(page.get_by_role("heading", name="Dziennik działań")).to_be_visible()
    deadline = time.monotonic() + WAIT_S
    while True:
        stores = page.evaluate(HEALTH)["stores"]
        if all(
            s["state"]["last_scan"] and not s["state"]["running_job"] for s in stores
        ):
            break
        assert time.monotonic() < deadline, "the store was not scanned in time"
        page.wait_for_timeout(200)
    expect(page.get_by_role("region", name="Stan indeksu")).to_have_count(0)


def rows(page: Page) -> Locator:
    """Return the rows of the entries shown."""
    table = page.get_by_role("table", name="Wpisy dziennika")
    return table.locator("tbody > tr.log-row")


def query(page: Page) -> dict[str, list[str]]:
    """Return the parameters of the page's address."""
    return parse_qs(urlsplit(page.url).query)


def export(page: Page, button: str, tmp_path: Path, suffix: str) -> bytes:
    """Click an export button; return the file the browser saved."""
    with page.expect_download() as started:
        page.get_by_role("button", name=button, exact=True).click()
    download = started.value
    name = download.suggested_filename
    assert re.fullmatch(rf"archiwista-log-\d{{8}}T\d{{6}}Z\.{suffix}", name)
    expect(page.get_by_role("status").filter(has_text="Zapisano plik")).to_have_text(
        f"Zapisano plik {name}."
    )
    saved = tmp_path / name
    download.save_as(saved)
    return saved.read_bytes()


def shot(page: Page, name: str) -> None:
    """Keep a screenshot for the report when ``ARCHIWISTA_SCREENSHOTS`` is set."""
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(directory) / f"{name}.png"))


def test_an_administrator_pages_filters_opens_and_exports_the_log(
    engine_tab: Tab, tmp_path: Path
) -> None:
    """Ada's pages, filters in the address, a row's states, both exports; not Igor's."""
    # Arrange
    paths, today = log_paths(tmp_path)
    page = engine_tab.page
    registry = load_registry(cache_dir=paths.cache_dir)
    with serving(paths, registry=registry) as (server, _):
        served = Served(server, paths)
        state = StateStore(paths.state_file)
        open_log(page, served, principal(state, "admin"))
        entries = rows(page)
        foot = page.locator(".log-foot .hint")
        navigation = page.get_by_role("navigation", name="Widoki")

        # Assert: the newest 50 of 60, who and how for people, „Dziennik” for her.
        expect(entries).to_have_count(50)
        expect(entries.first).to_have_attribute("data-entry", "60")
        expect(foot).to_have_text("wpisy 1–50 z 60 · starsze niż 365 dni są usuwane")
        expect(navigation.get_by_role("link", name="Dziennik")).to_be_visible()
        expect(page.locator('tr[data-entry="55"]')).to_contain_text("lena (agent)")
        pruning = page.locator('tr[data-entry="54"]')
        expect(pruning).to_contain_text("harmonogram")
        expect(pruning).to_contain_text("usunięcie starych wpisów")
        expect(page.locator('tr[data-entry="56"]')).to_contain_text("terminal")

        # Act: open the change of the settings.
        page.get_by_role("button", name="Szczegóły wpisu 52").click()

        # Assert: the state before and after.
        opened = page.locator("#log-entry-52")
        expect(opened.get_by_role("region", name="Przed", exact=True)).to_contain_text(
            '"network_jobs_per_person": 2'
        )
        expect(opened.get_by_role("region", name="Po", exact=True)).to_contain_text(
            '"network_jobs_per_person": 3'
        )
        expect(opened).to_contain_text("a41c9e7d20")
        shot(page, "07-dziennik")

        # Act: the older page, then back.
        page.get_by_role("button", name="Dalej", exact=True).click()
        expect(entries).to_have_count(10)
        expect(entries.first).to_have_attribute("data-entry", "10")
        expect(foot).to_have_text("wpisy 51–60 z 60 · starsze niż 365 dni są usuwane")
        page.get_by_role("button", name="Wstecz", exact=True).click()
        expect(entries).to_have_count(50)
        expect(foot).to_contain_text("wpisy 1–50 z 60")

        # Act and assert: each filter changes the rows and the address.
        filters = page.get_by_role("group", name="Filtry dziennika")
        clear = filters.get_by_role("button", name="Wyczyść filtry")
        filters.get_by_label("Działanie").select_option(label="Odmowy")
        expect(entries).to_have_count(1)
        expect(entries.first).to_have_attribute("data-entry", "53")
        expect(entries.first).to_contain_text("odmowa dostępu settings.update")
        assert query(page)["action"] == ["permission."]
        clear.click()
        expect(entries).to_have_count(50)
        assert "action" not in query(page)

        filters.get_by_label("Wynik").select_option(label="udane")
        expect(foot).to_contain_text("wpisy 1–50 z 59")
        assert query(page)["outcome"] == ["ok"]
        filters.get_by_label("Wynik").select_option(label="odmowa")
        expect(entries).to_have_count(1)
        expect(entries.first).to_have_attribute("data-entry", "53")
        clear.click()

        who = filters.get_by_label("Kto")
        who.fill(LISTED)
        who.press("Enter")
        expect(entries).to_have_count(1)
        expect(entries.first).to_have_attribute("data-entry", "55")
        assert query(page)["actor"] == [LISTED]
        clear.click()
        expect(who).to_have_value("")

        since = (today - timedelta(days=3)).isoformat()
        until = (today - timedelta(days=2)).isoformat()
        filters.get_by_label("Od dnia").fill(since)
        expect(entries).to_have_count(9)
        filters.get_by_label("Do dnia").fill(until)
        expect(entries).to_have_count(2)
        expect(entries.first).to_have_attribute("data-entry", "53")
        assert query(page)["from"] == [since]
        assert query(page)["to"] == [until]

        # Act: export these two entries in both formats.
        data = export(page, "Eksportuj CSV", tmp_path, "csv")
        lines = export(page, "Eksportuj JSON Lines", tmp_path, "jsonl").splitlines()

        # Assert: the same two entries, newest first.
        assert data.startswith(b"\xef\xbb\xbf") and data.endswith(b"\r\n")
        table = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
        assert table[0] == list(FIELDS)
        assert [row[0] for row in table[1:]] == ["53", "52"]
        documents = [json.loads(line) for line in lines]
        assert [document["id"] for document in documents] == [53, 52]
        assert documents[1]["before"] == {"network_jobs_per_person": 2}
        assert documents[1]["after"] == {"network_jobs_per_person": 3}

        # Assert: each export is an entry of the log.
        clear.click()
        expect(entries.first).to_have_attribute("data-entry", "62")
        expect(entries.first).to_contain_text("eksport dziennika")

        # Act: Igor, who is no administrator.
        open_log(page, served, principal(state, "other"))

        # Assert: the server's refusal; no „Dziennik”, no filters, no export.
        refusal = page.get_by_role("main").get_by_role("alert")
        expect(refusal).to_contain_text(
            "Odczyt dziennika działań wymaga roli administratora."
        )
        expect(refusal).to_contain_text("HTTP 403")
        expect(navigation.get_by_role("link", name="Zadania")).to_be_visible()
        expect(navigation.get_by_role("link", name="Dziennik")).to_have_count(0)
        expect(page.get_by_role("group", name="Filtry dziennika")).to_have_count(0)
        expect(page.get_by_role("button", name="Eksportuj CSV")).to_have_count(0)
    engine_tab.assert_clean()
