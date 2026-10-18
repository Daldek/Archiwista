"""Acceptance of v0.1 in Chromium on real servers (plan v0.1, step 13).

The main journey of SPEC 13 v0.1 runs on a real ``archiwista serve`` over a
generated store and asks nothing outside the server: the first-run wizard
in offline mode, the search, the map with an area, a product and its local
state, the catalog, a project and the store. The failure scenarios follow
the acceptance criteria: a store without write permission and one on a
read-only mount served by the real command line (criterion 3), a share that
disconnects and comes back without a rebuild (criterion 4) and a second
producer plugin beside Kartograf's (criteria 7 and 8). The API answers the
browser's session like the views and refuses requests without a session,
without the CSRF token or from another site.
"""

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from playwright.sync_api import APIResponse, Browser, FloatRect, Locator, Page, expect

from archiwista.api.errors import PROBLEM_MEDIA_TYPE
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig, StoreKind
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.jobs import FINISHED_STATES, scheduler
from archiwista.messages import MESSAGES
from archiwista.security import CSRF_COOKIE, CSRF_HEADER
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import Served, Tab
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import (
    NMT,
    ExpectedEntry,
    ExpectedPin,
    StoreManifest,
    make_store,
)
from tests.fixtures.store_edits import add_version

Serve = Callable[..., Served]
Snapshot = dict[str, tuple[int, int, int]]
Row = tuple[str, str | None]

STORE = "zespol"
STORE_NAME = "Zespół"
SECOND_SOURCE = Path(__file__).parents[1] / "fixtures" / "second_source"
FIXTURE_MODULES = ("external_source_plugin", "external_producer")
INDEX_TIMEOUT_S = 90.0
JOB_TIMEOUT_MS = 90_000
# Answers that read the store first (an area's local state, a project's live
# state) may take long on a busy machine.
READ_TIMEOUT_MS = 30_000
START_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 30.0
# The map is still when its address has not changed for this long.
STILL_S = 0.6
WORLD = "-180,-85,180,85"
LOADED = re.compile("w widoku|Brak obrysów")
NEW_LABEL = "2026-10-01_99999"
SERVE_URL = re.compile(r"http://127\.0\.0\.1:\d+/#token=\S+")
# Rows of the catalog's scrolled area with their file card links, by row index.
RENDERED_ROWS = """
() => [...document.querySelectorAll(".cat-rows [role=row][data-index]")].map((row) => [
  Number(row.dataset.index),
  row.querySelector("a.cat-name").getAttribute("href"),
])
"""


# --- settings and store -------------------------------------------------------


def zespol(root: Path, *, kind: StoreKind = "local") -> StoreConfig:
    """Return a store directory as the ``zespol`` store."""
    return StoreConfig(id=STORE, name=STORE_NAME, kartograf=root, kind=kind)


def offline_settings(store: StoreManifest, *, kind: StoreKind = "local") -> AppSettings:
    """Return offline settings: the generated store as ``zespol`` and its projects."""
    return AppSettings(
        offline=True,
        stores=(zespol(store.root, kind=kind),),
        project_dirs=(store.projects_dir,),
    )


def generate(tmp_path: Path) -> StoreManifest:
    """Write the synthetic store of the acceptance tests."""
    return make_store(tmp_path / "store", slots=24, seed=7)


def archive_pin(store: StoreManifest) -> ExpectedPin:
    """Return the pin of an older version: task ``archiwum`` of ``projekt-01``."""
    tasks = store.project("projekt-01").tasks
    return next(task for task in tasks if task.name == "archiwum").pins[0]


def link_of(store: StoreManifest, slot: str) -> ExpectedEntry:
    """Return the standard-path entry of a slot."""
    return next(entry for entry in store.by_kind("link") if entry.path == slot)


def versions_of(store: StoreManifest, slot: str) -> list[ExpectedEntry]:
    """Return the versions of a slot: same segment, hierarchy and file name."""
    link = link_of(store, slot)
    name = PurePosixPath(slot).name
    return [
        entry
        for entry in store.by_kind("version")
        if (entry.segment, entry.hierarchy) == (link.segment, link.hierarchy)
        and PurePosixPath(entry.path).name == name
    ]


def current_of(store: StoreManifest, slot: str) -> ExpectedEntry:
    """Return the version a slot's standard path holds."""
    target = link_of(store, slot).version_path
    return next(entry for entry in versions_of(store, slot) if entry.path == target)


def nmt_sheet(store: StoreManifest) -> ExpectedEntry:
    """Return the first regular NMT sheet of the store (its standard path)."""
    return next(
        entry
        for entry in store.by_kind("link")
        if entry.segment == NMT
        and entry.family == "asc_sheet"
        and entry.case == "regular"
    )


def tree(directory: Path) -> Snapshot:
    """Return every name below ``directory`` with its size, mtime and inode."""
    found = {}
    for top, dirnames, filenames in os.walk(directory):
        for name in [*dirnames, *filenames]:
            info = os.lstat(os.path.join(top, name))
            found[os.path.relpath(os.path.join(top, name), directory)] = (
                info.st_size,
                info.st_mtime_ns,
                info.st_ino,
            )
    return found


def read_only(directory: Path, *, locked: bool) -> None:
    """Take away (or give back) the write permission of a whole tree."""
    for top, _, filenames in os.walk(directory):
        os.chmod(top, 0o555 if locked else 0o755)
        for name in filenames:
            os.chmod(os.path.join(top, name), 0o444 if locked else 0o644)


# --- session and API ----------------------------------------------------------


def start_session(page: Page, url: str) -> None:
    """Open a one-time address and wait for the shell of the started session."""
    page.goto(url)
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()


def api(page: Page, base: str, path: str, params: dict[str, Any] | None = None) -> Any:
    """Read ``/api/v1`` with the page's session; the answer must be ``200``."""
    response = page.request.get(f"{base}/api/v1{path}", params=params)
    assert response.status == 200, response.text()
    return response.json()


def api_items(page: Page, base: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """Return every row of a ``/slots`` query, page after page."""
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {**params, "limit": "200", **({"cursor": cursor} if cursor else {})}
        answer = api(page, base, "/slots", query)
        items += answer["items"]
        cursor = answer["next_cursor"]
        if cursor is None:
            return items


def wait_indexed(page: Page, base: str) -> None:
    """Wait until every store had a complete pass and no job runs (``/health``)."""
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while True:
        stores = api(page, base, "/health")["stores"]
        if stores and all(
            item["state"]["indexed_at"] and item["state"]["running_job"] is None
            for item in stores
        ):
            return
        assert time.monotonic() < deadline, stores
        page.wait_for_timeout(250)


def scans(page: Page, base: str) -> list[dict[str, Any]]:
    """Return the scans of ``zespol``, newest first."""
    jobs: list[dict[str, Any]] = api(
        page, base, "/jobs", {"store": STORE, "kind": "scan"}
    )["items"]
    return jobs


def wait_job(page: Page, base: str, job: str) -> dict[str, Any]:
    """Wait until a job has ended; return it as ``GET /jobs/{job}`` gives it."""
    deadline = time.monotonic() + JOB_TIMEOUT_MS / 1000
    while True:
        detail: dict[str, Any] = api(page, base, f"/jobs/{job}")
        if detail["state"] in FINISHED_STATES:
            return detail
        assert time.monotonic() < deadline, detail
        page.wait_for_timeout(250)


def assert_problem(response: APIResponse, status: int, code: str, detail: str) -> None:
    """Check an RFC 9457 problem: status, stable code and the Polish detail."""
    assert response.status == status, response.text()
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert {"type", "title", "status", "detail", "code"} <= set(body)
    assert (body["status"], body["code"], body["detail"]) == (status, code, detail)
    assert body["title"]


def address(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


# --- views --------------------------------------------------------------------


def views(page: Page) -> Locator:
    """Return the navigation between the views."""
    return page.get_by_role("navigation", name="Widoki")


def grid(page: Page) -> Locator:
    """Return the catalog's list."""
    return page.get_by_role("grid", name="Lista plików katalogu")


def counter(page: Page) -> Locator:
    """Return the map's counter of outlines in the view."""
    return page.locator(".map-count")


def wait_still(page: Page) -> None:
    """Wait until the map stopped moving and the outlines of its view arrived.

    The address changes only when a move ends, so the wait starts after the
    longest framing animation (600 ms).
    """
    page.wait_for_timeout(700)
    deadline = time.monotonic() + 30
    url = page.url
    since = time.monotonic()
    while time.monotonic() - since < STILL_S:
        assert time.monotonic() < deadline, "the map did not stop"
        page.wait_for_timeout(100)
        if page.url != url:
            url = page.url
            since = time.monotonic()
    expect(page.locator(".map-counts .loading")).to_have_count(0)
    expect(counter(page)).to_have_text(LOADED)


def map_box(page: Page) -> FloatRect:
    """Return the map's box on the page."""
    box = page.locator(".map-gl").bounding_box()
    assert box is not None
    return box


def choose_area_sheet(page: Page, sheet: str) -> None:
    """Type a sheet code into the area tools, wait for the area and the map."""
    page.get_by_label("Godło arkusza").fill(sheet)
    page.get_by_role("button", name="Wybierz", exact=True).click()
    expect(page.locator(".area-card .big")).to_have_text(sheet)
    wait_still(page)


def open_card(page: Page, base: str, slot: str) -> Locator:
    """Open the file card of a slot over the Store view."""
    page.goto(f"{base}/?view=store&file={STORE}/{slot}")
    card = page.get_by_role("dialog", name=PurePosixPath(slot).name)
    expect(card).to_be_visible()
    return card


def axis(card: Locator) -> Locator:
    """Return the versions on a file card's axis."""
    return card.locator(".fc-axis").get_by_role("listitem")


def value(scope: Locator | Page, name: str) -> Locator:
    """Return the value of a label in a definition list (``<dt>`` → ``<dd>``)."""
    return scope.locator(f"dt:text-is('{name}') + dd")


def card_of(item: dict[str, Any]) -> Row:
    """Return the file card a catalog row opens: its slot, no chosen version."""
    return f"{item['store']}/{item['slot']}", None


def shown_rows(page: Page, total: int) -> list[Row]:
    """Scroll the list of ``total`` rows; return each row's file card by its index."""
    expect(grid(page)).to_have_attribute("aria-rowcount", str(total + 1))
    expect(grid(page)).to_have_attribute("aria-busy", "false")
    scroller = page.locator(".cat-scroll")
    rows: dict[int, Row] = {}
    scroller.evaluate("(element) => { element.scrollTop = 0; }")
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while len(rows) < total:
        assert time.monotonic() < deadline, f"{len(rows)} of {total} rows shown"
        for index, link in page.evaluate(RENDERED_ROWS):
            card = dict(parse_qsl(urlsplit(link).query))
            rows[index] = (card["file"], card.get("file_version"))
        scroller.evaluate(
            "(element) => { element.scrollTop += element.clientHeight / 2; }"
        )
        page.wait_for_timeout(30)
    return [rows[index] for index in sorted(rows)]


def browse_every_view(page: Page, base: str, store: StoreManifest) -> None:
    """Visit Map, Catalog, File card, Projects and Store; each must show data.

    The map's local state re-reads the area's slots from the store, the
    file card's link check reads the standard path in a background job, the
    project's live state asks the producer and the store's usage, problems
    and last scan come from the index.
    """
    sheet = nmt_sheet(store)
    assert sheet.unit is not None
    page.goto(f"{base}/?view=map&product=nmt")
    expect(counter(page)).to_have_text(LOADED, timeout=30_000)
    choose_area_sheet(page, sheet.unit)
    local = page.get_by_role("region", name="Stan lokalny")
    expect(local.get_by_text("lokalnie 100% obszaru")).to_be_visible(
        timeout=READ_TIMEOUT_MS
    )

    rows = api_items(page, base, {})
    page.goto(f"{base}/?view=catalog")
    expect(grid(page)).to_have_attribute("aria-rowcount", str(len(rows) + 1))

    slot = archive_pin(store).path
    label = current_of(store, slot).label
    card = open_card(page, base, slot)
    expect(axis(card)).to_have_count(len(versions_of(store, slot)))
    expect(axis(card).filter(has_text="bieżąca")).to_contain_text(str(label))
    card.get_by_role("button", name="Potwierdź bieżącą wersję").click()
    expect(card.locator(".job-summary")).to_have_text(
        f"Potwierdzono: ścieżka standardowa trzyma wersję {label}.",
        timeout=JOB_TIMEOUT_MS,
    )
    page.keyboard.press("Escape")

    project = store.project("projekt-01")
    page.goto(f"{base}/?view=projects&project={project.name}")
    panel = page.get_by_role("complementary", name="Projekt")
    expect(panel.get_by_role("heading", name=project.name)).to_be_visible()
    expect(value(panel, "Stan teraz")).to_contain_text(
        "sprawdzono", timeout=READ_TIMEOUT_MS
    )
    for task in project.tasks:
        pins = panel.locator(".pc-task").filter(
            has=page.locator(".pc-task-head b").get_by_text(task.name, exact=True)
        )
        expect(pins.locator(".pc-pin")).to_have_count(len(task.pins))

    detail = api(page, base, f"/stores/{STORE}")
    page.goto(f"{base}/?view=store")
    usage = page.get_by_role("region", name="Zajętość według produktów")
    expect(usage.locator("tbody").get_by_role("row")).to_have_count(
        len(detail["usage"]["products"])
    )
    expect(
        page.get_by_role(
            "heading", name=f"Problemy magazynu ({len(detail['problems'])})"
        )
    ).to_be_visible()
    expect(value(page, "Ostatni skan")).to_contain_text("zakończone")


# --- the real command line on a read-only mount -------------------------------


def require_read_only_mounts(tmp_path: Path) -> None:
    """Skip unless an unprivileged mount namespace makes a directory read-only."""
    if shutil.which("unshare") is None:
        pytest.skip("unshare (util-linux) is not installed")
    probe = tmp_path / "probe"
    probe.mkdir()
    where = shlex.quote(str(probe))
    script = (
        f"mount --bind {where} {where} && mount -o remount,bind,ro {where}"
        f" && ! touch {where}/written 2>/dev/null"
    )
    done = subprocess.run(
        ["unshare", "--user", "--map-root-user", "--mount", "sh", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    shutil.rmtree(probe)
    if done.returncode != 0:
        reason = done.stderr.strip() or f"exit status {done.returncode}"
        pytest.skip(f"no read-only bind mount in a user namespace: {reason}")


def mount_options(pid: int, mount_point: Path) -> list[str]:
    """Return the options of the mount at ``mount_point`` as process ``pid`` sees it."""
    found = [
        fields[5].split(",")
        for fields in (
            line.split(" ")
            for line in Path(f"/proc/{pid}/mountinfo").read_text().splitlines()
        )
        if fields[4] == str(mount_point)
    ]
    assert found, f"no mount at {mount_point} in process {pid}"
    return found[-1]


@contextmanager
def serving_read_only(
    directory: Path, env: dict[str, str], logs: Path
) -> Iterator[tuple["subprocess.Popen[bytes]", str]]:
    """Run ``archiwista serve`` where ``directory`` is mounted read-only.

    A user and mount namespace binds ``directory`` onto itself read-only and
    then executes the console script installed next to the interpreter; the
    network namespace is shared, so the browser reaches the server. Yields
    the process and the one-time address it printed; afterwards the server
    gets ``SIGINT`` (Ctrl+C) and must stop by itself.
    """
    console = Path(sys.executable).with_name("archiwista")
    where = shlex.quote(str(directory))
    script = (
        f"mount --bind {where} {where} && mount -o remount,bind,ro {where}"
        f" && exec {shlex.quote(str(console))} serve --no-browser --port 0"
    )
    out, err = logs / "serve.out", logs / "serve.err"
    with out.open("wb") as stdout, err.open("wb") as stderr:
        process = subprocess.Popen(
            ["unshare", "--user", "--map-root-user", "--mount", "sh", "-c", script],
            stdout=stdout,
            stderr=stderr,
            env=env,
        )
        try:
            deadline = time.monotonic() + START_TIMEOUT_S
            while (found := SERVE_URL.search(out.read_text(encoding="utf-8"))) is None:
                assert process.poll() is None, err.read_text(encoding="utf-8")
                assert time.monotonic() < deadline, err.read_text(encoding="utf-8")
                time.sleep(0.1)
            yield process, found[0]
            process.send_signal(signal.SIGINT)
            process.wait(timeout=STOP_TIMEOUT_S)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


# --- tests --------------------------------------------------------------------


def test_acceptance_first_run_to_every_view(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """From the first-run wizard to every view offline, asking nothing outside.

    The wizard saves the store, its projects and offline mode; the
    scheduler's full scan indexes the store; ``Ctrl+K`` finds a file by the
    start of its SHA-256; the map takes a typed sheet and a product, shows
    the area's local state and files and opens a card; the catalog lists
    the area's files from the address; the project shows its pins and live
    state; the store its usage, problems, source and last scan.
    """
    store = generate(tmp_path)
    sheet = nmt_sheet(store)
    assert sheet.unit is not None
    project = store.project("projekt-01")
    served = serve()
    base = served.base
    page = tab.page
    start_session(page, served.token_url())
    expect(page.get_by_role("heading", name="Pierwsze uruchomienie")).to_be_visible()

    page.get_by_label("Nazwa", exact=True).fill(STORE_NAME)
    page.get_by_label("Katalog Kartografa").fill(str(store.root))
    page.get_by_role("button", name="Dalej").click()
    page.get_by_role("button", name="Dodaj katalog").click()
    page.get_by_label("Katalog projektów 1").fill(str(store.projects_dir))
    page.get_by_role("button", name="Dalej").click()
    offline = page.get_by_label("Tryb offline")
    expect(offline).not_to_be_checked()
    offline.check()
    page.get_by_role("button", name="Dalej").click()
    expect(value(page, "Tryb pracy:")).to_have_text("offline")
    page.get_by_role("button", name="Zapisz i zindeksuj").click()
    expect(page.get_by_text("Zapisano ustawienia.")).to_be_visible()
    expect(page.get_by_text(f"Magazyn „{STORE_NAME}” zindeksowany")).to_be_visible(
        timeout=JOB_TIMEOUT_MS
    )
    saved = served.settings()
    indexed = scans(page, base)
    page.get_by_role("button", name="Przejdź do przeglądania").click()
    expect(counter(page)).to_have_text(LOADED, timeout=30_000)

    rows = api_items(page, base, {})
    target = next(
        item
        for item in rows
        if item["version"]
        and item["version"]["sha256"]
        and sum(
            other["version"] is not None
            and (other["version"]["sha256"] or "").startswith(
                item["version"]["sha256"][:12]
            )
            for other in rows
        )
        == 1
    )
    page.keyboard.press("Control+k")
    expect(page.get_by_role("searchbox", name="Szukaj w katalogu")).to_be_focused()
    page.keyboard.type(target["version"]["sha256"][:12])
    expect(grid(page)).to_have_attribute("aria-rowcount", "2")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    found = page.get_by_role("dialog", name=target["name"])
    expect(found).to_be_visible()
    found_at = address(page)
    page.keyboard.press("Escape")
    expect(found).to_have_count(0)

    views(page).get_by_role("link", name="Mapa").click()
    expect(counter(page)).to_have_text(LOADED, timeout=30_000)
    choose_area_sheet(page, sheet.unit)
    page.get_by_role("group", name="Produkty w indeksie").get_by_role(
        "button", name=re.compile(r"\bnmt\b")
    ).click()
    expect(page).to_have_url(re.compile("product=nmt"))
    wait_still(page)
    local = page.get_by_role("region", name="Stan lokalny")
    expect(local.get_by_text("lokalnie 100% obszaru")).to_be_visible(
        timeout=READ_TIMEOUT_MS
    )
    area = address(page)["area_id"]
    groups = api(page, base, "/slots", {"product": "nmt", "area_id": area})["groups"]
    expect(local.locator(".area-files")).to_have_text(
        re.compile(
            rf"Pliki w obszarze: {groups['footprint']} plik\S* z obrysem w obszarze"
            rf" · {groups['country']} plik\S* dla całego kraju"
        )
    )
    expect(page.get_by_text("Tryb offline: bez podkładu")).to_be_visible()
    box = map_box(page)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.get_by_text("Kliknij, aby otworzyć kartę pliku")).to_be_visible()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    from_map = page.get_by_role("dialog", name=PurePosixPath(sheet.path).name)
    expect(from_map).to_be_visible()
    expect(axis(from_map).filter(has_text="bieżąca")).to_have_count(1)
    from_map_at = address(page)
    page.keyboard.press("Escape")

    local.get_by_role("link", name="Pokaż pliki obszaru w Katalogu").click()
    expect(grid(page)).to_be_visible()
    filters = {name: text for name, text in address(page).items() if name != "view"}
    in_area = api_items(page, base, filters)
    expect(grid(page)).to_have_attribute("aria-rowcount", str(len(in_area) + 1))
    expect(page.get_by_label("Produkt", exact=True)).to_have_value("nmt")

    views(page).get_by_role("link", name="Projekty").click()
    page.get_by_role("link", name=project.name, exact=True).click()
    panel = page.get_by_role("complementary", name="Projekt")
    expect(panel.get_by_role("heading", name=project.name)).to_be_visible()
    expect(value(panel, "Stan teraz")).to_contain_text(
        "sprawdzono", timeout=READ_TIMEOUT_MS
    )
    for task in project.tasks:
        pins = panel.locator(".pc-task").filter(
            has=page.locator(".pc-task-head b").get_by_text(task.name, exact=True)
        )
        expect(pins.locator(".pc-pin")).to_have_count(len(task.pins))
        for pin in task.pins:
            expect(pins.get_by_role("link", name=pin.label)).to_be_visible()

    detail = api(page, base, f"/stores/{STORE}")
    sources = {item["producer"]: item for item in api(page, base, "/sources")["items"]}
    views(page).get_by_role("link", name="Magazyn").click()
    usage = page.get_by_role("region", name="Zajętość według produktów")
    expect(usage.locator("tbody").get_by_role("row")).to_have_count(
        len(detail["usage"]["products"])
    )
    expect(
        page.get_by_role(
            "heading", name=f"Problemy magazynu ({len(detail['problems'])})"
        )
    ).to_be_visible()
    expect(value(page, "Źródło danych")).to_contain_text(
        f"kartograf {sources['kartograf']['package_version']}"
    )
    expect(value(page, "Źródło danych")).to_contain_text("dostępne")
    expect(value(page, "Ostatni skan")).to_contain_text("zakończone")
    expect(value(page, "Ostatni skan")).to_contain_text("Wykonawca: właściciel lokalny")

    assert saved.offline is True
    assert [config.kartograf for config in saved.stores] == [store.root]
    assert saved.project_dirs == (store.projects_dir,)
    assert [(job["params"]["mode"], job["state"]) for job in indexed] == [
        ("full", "succeeded")
    ]
    assert found_at["file"] == f"{STORE}/{target['slot']}"
    assert found_at["q"] == target["version"]["sha256"][:12]
    assert from_map_at["file"] == f"{STORE}/{sheet.path}"
    assert from_map_at["file_version"] == sheet.version_path
    assert filters["product"] == "nmt" and filters["area_id"] == area
    assert tab.foreign_requests(base) == []
    tab.assert_clean()


def test_acceptance_read_only_store_every_view(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A store and projects without write permission: every view, nothing written.

    The scheduler's full scan and a scan started with „Odśwież” succeed; the
    map, catalog, file card, project and store show data; the tree keeps
    its names, sizes, modification times and inodes.
    """
    store = generate(tmp_path)
    read_only(store.output_dir, locked=True)
    try:
        before = tree(store.output_dir)
        served = serve(offline_settings(store))
        base = served.base
        page = tab.page
        start_session(page, served.token_url())
        wait_indexed(page, base)
        page.goto(f"{base}/?view=store")
        page.get_by_role("button", name="Odśwież").click()
        expect(page.locator(".job")).to_contain_text(
            "Skan: zakończone", timeout=JOB_TIMEOUT_MS
        )
        done = scans(page, base)
        browse_every_view(page, base, store)
        after = tree(store.output_dir)
    finally:
        read_only(store.output_dir, locked=False)

    assert [(job["params"]["mode"], job["state"]) for job in done] == [
        ("incremental", "succeeded"),
        ("full", "succeeded"),
    ]
    assert after == before
    tab.assert_clean()


def test_acceptance_api_requests_with_browser_session(
    serve: Serve, tab: Tab, chromium: Browser, tmp_path: Path
) -> None:
    """The browser's session reads the API as the views show it; rules refuse others.

    ``page.request`` shares the context's cookies. Reads answer ``200`` and
    agree with the views; a scan needs the CSRF token of the session, a
    request without a session gets ``401`` and one from another site or for
    a foreign ``Host`` is refused. Every refusal is an RFC 9457 problem with
    a Polish ``detail``.
    """
    store = generate(tmp_path)
    served = serve(offline_settings(store))
    base = served.base
    page = tab.page
    start_session(page, served.token_url())
    wait_indexed(page, base)
    request = page.request
    scan_url = f"{base}/api/v1/stores/{STORE}/scan"
    slot = archive_pin(store).path

    health = request.get(f"{base}/api/v1/health")
    pages = [request.get(f"{base}/api/v1/slots", params={"limit": "10"})]
    while (cursor := pages[-1].json()["next_cursor"]) is not None:
        pages.append(
            request.get(
                f"{base}/api/v1/slots", params={"limit": "10", "cursor": cursor}
            )
        )
    card = request.get(f"{base}/api/v1/stores/{STORE}/slots/{slot}")
    footprints = request.get(
        f"{base}/api/v1/map/footprints", params={"bbox": WORLD, "limit": "5000"}
    )
    projects = request.get(f"{base}/api/v1/projects")
    reads = [health, *pages, card, footprints, projects]
    assert [response.status for response in reads] == [200] * len(reads)
    rows = [item for answer in pages for item in answer.json()["items"]]
    state = health.json()["stores"][0]["state"]
    versions = card.json()["versions"]
    current = next(item for item in versions if item["is_current"])

    page.goto(f"{base}/?view=catalog")
    expect(grid(page)).to_have_attribute("aria-rowcount", str(len(rows) + 1))
    opened = open_card(page, base, slot)
    expect(axis(opened)).to_have_count(len(versions))
    expect(axis(opened).filter(has_text="bieżąca")).to_contain_text(current["label"])
    page.goto(f"{base}/?view=map")
    expect(counter(page)).to_have_text(LOADED, timeout=30_000)
    expect(page.get_by_role("link", name=re.compile("bez obrysu"))).to_have_text(
        re.compile(rf"^{footprints.json()['groups']['none']} plik\S* bez obrysu")
    )
    page.goto(f"{base}/?view=projects")
    expect(page.locator(".projects-table tbody tr")).to_have_count(
        len(projects.json()["items"])
    )
    page.goto(f"{base}/?view=store")
    expect(value(page, "Zawartość indeksu")).to_contain_text(
        re.compile(rf"^{state['slots']} plik\S* · {state['versions']} wersj\S*")
    )

    cookies = {cookie["name"]: cookie["value"] for cookie in page.context.cookies()}
    csrf = request.get(f"{base}/api/v1/session").json()["csrf_token"]
    refused = request.post(scan_url, data={"mode": "incremental"})
    started = request.post(
        scan_url, data={"mode": "incremental"}, headers={CSRF_HEADER: csrf}
    )
    finished = wait_job(page, base, started.json()["id"])
    anonymous = chromium.new_context()
    try:
        without_session = anonymous.request.get(f"{base}/api/v1/health")
        assert_problem(
            without_session, 401, "session_required", MESSAGES["api_session_required"]
        )
    finally:
        anonymous.close()
    cross_site = request.get(
        f"{base}/api/v1/health", headers={"Sec-Fetch-Site": "cross-site"}
    )
    other_origin = request.post(
        scan_url,
        data={"mode": "incremental"},
        headers={CSRF_HEADER: csrf, "Origin": "http://archiwista.example"},
    )
    foreign_host = request.get(
        f"{base}/api/v1/health",
        headers={"Host": f"archiwista.example:{served.server.port}"},
    )

    assert len(pages) > 1
    assert len({(item["store"], item["slot"]) for item in rows}) == len(rows)
    assert card.json()["current"] == current["path"]
    assert len(versions) == len(versions_of(store, slot))
    assert csrf == cookies[CSRF_COOKIE]
    assert_problem(refused, 403, "csrf_rejected", MESSAGES["api_csrf_missing"])
    assert started.status == 202, started.text()
    assert started.headers["location"] == f"/api/v1/jobs/{started.json()['id']}"
    assert (finished["state"], finished["actor"]) == ("succeeded", "local")
    assert finished["params"]["mode"] == "incremental"
    assert_problem(cross_site, 403, "csrf_rejected", MESSAGES["api_cross_site"])
    assert_problem(other_origin, 403, "csrf_rejected", MESSAGES["api_cross_site"])
    assert_problem(
        foreign_host,
        400,
        "invalid_host",
        MESSAGES["api_invalid_host"].format(port=served.server.port),
    )
    tab.assert_clean()


def test_acceptance_share_disconnects_and_returns(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A share that is gone: banner and the index's answers; back: no rebuild.

    The share's directory is replaced by an empty mount point. A scan fails
    with ``store_unavailable``, the banner names the index's time, the
    catalog keeps its rows and the file card says where its state comes
    from. With the share back and one new download, the next scan is
    incremental: the new version is current and nothing else changed.
    """
    store = generate(tmp_path)
    link = next(entry for entry in store.by_kind("link") if entry.case == "regular")
    served = serve(offline_settings(store, kind="share"))
    base = served.base
    page = tab.page
    start_session(page, served.token_url())
    wait_indexed(page, base)
    everything = api_items(page, base, {"versions": "all"})
    current = api_items(page, base, {})
    page.goto(f"{base}/?view=store")
    indexed = value(page, "Ostatnie pełne przejście").inner_text()
    banner = page.get_by_role("region", name="Stan indeksu")
    away = store.root.with_name("data-away")

    store.root.rename(away)
    store.root.mkdir()  # the empty mount point of a share that is gone
    page.get_by_role("button", name="Odśwież").click()
    expect(page.locator(".job")).to_contain_text("Skan: błąd", timeout=JOB_TIMEOUT_MS)
    expect(banner).to_contain_text(
        f"Magazyn „{STORE_NAME}” jest niedostępny."
        f" Wyniki pochodzą z indeksu z {indexed}"
    )
    lost = scans(page, base)[0]
    page.goto(f"{base}/?view=catalog")
    expect(grid(page)).to_have_attribute("aria-rowcount", str(len(current) + 1))
    kept = api_items(page, base, {"versions": "all"})
    card = open_card(page, base, link.path)
    expect(card.get_by_role("note")).to_contain_text(
        f"Magazyn „{STORE_NAME}” jest niedostępny — stan z indeksu z {indexed}"
    )
    page.keyboard.press("Escape")
    version = add_version(away, link.path, label=NEW_LABEL)
    store.root.rmdir()
    away.rename(store.root)  # the share is back, with a new download on it
    page.goto(f"{base}/?view=store")
    page.get_by_role("button", name="Odśwież").click()
    expect(page.locator(".job")).to_contain_text(
        "Skan: zakończone", timeout=JOB_TIMEOUT_MS
    )
    expect(banner).to_have_count(0)
    later = scans(page, base)
    back = later[: [job["id"] for job in later].index(lost["id"])]
    renewed = open_card(page, base, link.path)
    expect(axis(renewed).filter(has_text=NEW_LABEL)).to_contain_text("bieżąca")
    expect(axis(renewed).filter(has_text="bieżąca")).to_have_count(1)
    after = api_items(page, base, {"versions": "all"})
    renewed_row = next(
        item for item in api_items(page, base, {}) if item["slot"] == link.path
    )

    assert (lost["params"]["mode"], lost["state"]) == ("incremental", "failed")
    assert lost["error"]["code"] == "store_unavailable"
    assert kept == everything
    assert back and all(
        (job["params"]["mode"], job["state"]) == ("incremental", "succeeded")
        for job in back
    )
    assert sum(job["result"]["versions_written"] for job in back) == 1
    assert sum(job["result"]["missing"] for job in back) == 0
    assert renewed_row["version"]["path"] == version
    assert [item for item in after if item["slot"] != link.path] == [
        item for item in everything if item["slot"] != link.path
    ]
    tab.assert_clean()


def test_acceptance_serve_on_read_only_mount(
    tab: Tab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real ``archiwista serve`` on a read-only mount: every view, nothing written.

    The store's whole directory (data and projects) is bind-mounted
    read-only in the server's own mount namespace; the settings and the
    local index live in the XDG directories of the test.
    """
    require_read_only_mounts(tmp_path)
    store = generate(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("PYTHONUNBUFFERED", "1")
    ConfigStore(AppPaths.default().config_file).save(offline_settings(store))
    before = tree(store.output_dir)
    page = tab.page

    with serving_read_only(store.output_dir, dict(os.environ), tmp_path) as (
        process,
        url,
    ):
        base = url.partition("/#")[0]
        start_session(page, url)
        wait_indexed(page, base)
        indexed = scans(page, base)
        browse_every_view(page, base, store)
        options = mount_options(process.pid, store.output_dir)
        tab.assert_clean()
        page.goto("about:blank")

    assert "ro" in options
    assert [(job["params"]["mode"], job["state"]) for job in indexed] == [
        ("full", "succeeded")
    ]
    assert process.returncode == 0, (tmp_path / "serve.err").read_text("utf-8")
    assert tree(store.output_dir) == before


# The in-process scan reads the synthetic JPEG sheets, whose headers carry no
# geotransform (their outline comes from the world file); rasterio says so.
@pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
def test_acceptance_second_plugin_beside_kartograf(
    serve: Serve, tab: Tab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second producer's store beside Kartograf's: Store, Catalog and file card.

    The test plugin is registered by its entry point; as in
    ``test_second_adapter_entries_in_catalog`` (v0.1 settings name only
    Kartograf's directory) ``roots()`` gives it the store's directory, both
    stores are indexed in the test process and the scheduler plans no scan.
    """
    for name in FIXTURE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(SECOND_SOURCE))
    kartograf_roots = StoreConfig.roots

    def roots(config: StoreConfig) -> dict[str, Path]:
        if config.id == "pomiary":
            return {"external": config.kartograf}
        return kartograf_roots(config)

    monkeypatch.setattr(StoreConfig, "roots", roots)
    monkeypatch.setattr(scheduler, "plan_scans", lambda *args, **kwargs: ())
    store = generate(tmp_path)
    folder = tmp_path / "pomiary"
    folder.mkdir()
    for name in ("opady.csv", "stany.csv"):
        (folder / name).write_text("data;wartość\n", encoding="utf-8")
    pomiary = StoreConfig(id="pomiary", name="Pomiary", kartograf=folder, kind="local")
    settings = AppSettings(offline=True, stores=(zespol(store.root), pomiary))
    paths = local_paths(tmp_path)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({config.id: config.roots() for config in settings.stores})
        for config in settings.stores:
            for producer in config.roots():
                scan_store(
                    registry.adapter(producer), writer, settings, config.id, mode="full"
                )
    served = serve(settings)
    base = served.base
    page = tab.page
    start_session(page, served.token_url())
    wait_indexed(page, base)
    sources = {item["producer"]: item for item in api(page, base, "/sources")["items"]}
    states = {
        item["store"]: item["state"] for item in api(page, base, "/health")["stores"]
    }
    rows = api_items(page, base, {})

    page.goto(f"{base}/?view=store")
    for config, producer, other in (
        (settings.stores[0], "kartograf", "external"),
        (pomiary, "external", "kartograf"),
    ):
        page.get_by_role("group", name="Magazyny").get_by_role(
            "button", name=config.name, exact=True
        ).click()
        state = states[config.id]
        source = value(page, "Źródło danych")
        expect(page.get_by_role("heading", level=1)).to_contain_text(config.name)
        expect(page.locator(".store-head")).to_contain_text("dostępny")
        expect(value(page, "Zawartość indeksu")).to_contain_text(
            re.compile(rf"^{state['slots']} plik\S* · {state['versions']} wersj\S*")
        )
        expect(source).to_contain_text(
            f"{producer} {sources[producer]['package_version']}"
        )
        expect(source).to_contain_text("dostępne")
        expect(source).not_to_contain_text(other)
    page.goto(f"{base}/?view=catalog")
    shown = shown_rows(page, len(rows))
    page.goto(f"{base}/?view=catalog&q=opady")
    csv = grid(page).get_by_role("row").filter(has_text="opady.csv")
    expect(csv.locator(".c-store")).to_have_text("Pomiary")
    expect(csv.locator(".c-prod")).to_contain_text("external")
    csv.locator("a.cat-name").click()
    card = page.get_by_role("dialog", name="opady.csv")
    expect(card).to_be_visible()
    expect(axis(card)).to_have_count(1)

    assert {producer: item["status"] for producer, item in sources.items()} == {
        "external": "available",
        "kartograf": "available",
    }
    assert shown == [card_of(item) for item in rows]
    assert {item["store"] for item in rows} == {STORE, "pomiary"}
    assert address(page) == {
        "view": "catalog",
        "q": "opady",
        "file": "pomiary/opady.csv",
    }
    tab.assert_clean()
