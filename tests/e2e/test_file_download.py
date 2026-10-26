"""„Pobierz plik” in Chromium and Firefox (plan v0.4 T10 commit 2; ADR-047 decision 5).

A generated Kartograf store is served offline; the data folder of its project
``projekt-01`` holds a Shapefile. The file card of a version and the card of
the own file offer „Pobierz plik”, a link of the page that the server lets in
without the CSRF header (``Sec-Fetch-Site: same-origin``): the browser saves
the bytes of the version, of the working file and of one file of its set
(„Pliki zestawu”) under their names. While the store is unavailable the
version's „Pobierz plik” is disabled with its reason.
"""

import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, StoreConfig
from archiwista.index import own_file_id
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import make_store
from tests.fixtures.own_data import make_own_folder

Serve = Callable[..., Served]

STORE = "zespol"
PROJECT = "projekt-01"
WAIT_S = 60.0
ENDED = ("succeeded", "partial", "failed", "interrupted", "cancelled")
OFFLINE = "Magazyn jest niedostępny, więc pliku nie można teraz pobrać."
API = """async ([method, path]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch(`/api/v1${path}`, { method, headers });
  return { status: answer.status, body: await answer.json() };
}"""


def call(page: Page, method: str, path: str) -> Any:
    """Return the JSON answer of an API request made with the page's session."""
    answer: dict[str, Any] = page.evaluate(API, [method, path])
    assert answer["status"] in (200, 202), answer
    return answer["body"]


def wait_until(page: Page, done: Callable[[], bool], what: str) -> None:
    """Wait until ``done`` is true."""
    deadline = time.monotonic() + WAIT_S
    while not done():
        assert time.monotonic() < deadline, f"not in time: {what}"
        page.wait_for_timeout(200)


def ended(page: Page, job: dict[str, Any]) -> str:
    """Wait for a job to end; return its state."""
    deadline = time.monotonic() + WAIT_S
    while (state := call(page, "GET", f"/jobs/{job['id']}")["state"]) not in ENDED:
        assert time.monotonic() < deadline, f"job {job['id']} did not end"
        page.wait_for_timeout(200)
    return str(state)


def saved(page: Page, link: Locator) -> tuple[str, bytes]:
    """Click a download link; return the name and bytes the browser saved."""
    with page.expect_download() as started:
        link.click()
    download = started.value
    return download.suggested_filename, Path(download.path()).read_bytes()


def test_file_download_saves_versions_own_files_and_set_files(
    serve: Serve, engine_tab: Tab, tmp_path: Path
) -> None:
    """The bytes of a version, a working file and a file of its set; none offline."""
    # Arrange
    store = make_store(tmp_path / "store", slots=24, seed=7)
    folder = make_own_folder(
        store.base / store.project(PROJECT).path / "dane", families=("shp_full",)
    )
    config = StoreConfig(id=STORE, name="Zespół", kartograf=store.root, kind="local")
    served = serve(
        AppSettings(offline=True, stores=(config,), project_dirs=(store.projects_dir,))
    )
    link = next(entry for entry in store.by_kind("link") if entry.problem is None)
    assert link.version_path is not None
    version = PurePosixPath(link.version_path).name
    version_bytes = (store.root / link.version_path).read_bytes()
    shapefile = folder.file("shp_full")
    dbf = PurePosixPath(next(m for m in shapefile.members if m.endswith(".dbf")))
    file_card = f"{served.base}/?" + urlencode(
        {"view": "store", "file": f"{STORE}/{link.path}"}
    )
    own_card = f"{served.base}/?" + urlencode(
        {
            "view": "projects",
            "project": PROJECT,
            "own": f"{PROJECT}/{own_file_id(shapefile.path)}",
        }
    )
    page = engine_tab.page
    page.goto(served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    wait_until(
        page,
        lambda: all(
            item["state"]["last_scan"] and not item["state"]["running_job"]
            for item in call(page, "GET", "/health")["stores"]
        ),
        "the store's index",
    )
    assert ended(page, call(page, "POST", f"/projects/{PROJECT}/scan")) == "succeeded"

    # Act
    page.goto(file_card)
    card = page.get_by_role("dialog", name=PurePosixPath(link.path).name)
    of_version = saved(page, card.get_by_role("link", name="Pobierz plik"))
    page.goto(own_card)
    own = page.get_by_role("dialog", name=shapefile.path)
    of_working_file = saved(page, own.get_by_role("link", name="Pobierz plik"))
    of_member = saved(page, own.get_by_role("link", name=dbf.name))
    store.root.rename(store.root.with_name("data-odlaczony"))
    assert ended(page, call(page, "POST", f"/stores/{STORE}/scan")) == "failed"
    page.goto(file_card)
    offline = card.get_by_role("button", name="Pobierz plik")

    # Assert
    assert of_version == (version, version_bytes)
    assert of_working_file == (
        PurePosixPath(shapefile.path).name,
        (folder.root / shapefile.path).read_bytes(),
    )
    assert of_member == (dbf.name, (folder.root / dbf).read_bytes())
    expect(offline).to_be_disabled()
    expect(offline).to_have_accessible_description(OFFLINE)
    expect(card.get_by_role("link", name="Pobierz plik")).to_have_count(0)
    engine_tab.assert_clean()
