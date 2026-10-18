"""The catalog in Chromium on a real server (plan v0.1, step 10c).

Filters are the parameters of ``GET /slots`` in the address and pages follow
its cursor; the unit filter matches a code exactly while the search also
finds codes with the same start; files without an outline are a group of
the catalog that the map's data never holds; ``Ctrl+K`` opens the search
from any view; a second producer's files list like Kartograf's.
"""

import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.jobs import scheduler
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import Served, Tab
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import StoreManifest, make_store

Serve = Callable[..., Served]
Row = tuple[str, str | None]

SECOND_SOURCE = Path(__file__).parents[1] / "fixtures" / "second_source"
FIXTURE_MODULES = ("external_source_plugin", "external_producer")
INDEX_TIMEOUT_S = 60.0
# Rows of the scrolled area with their file card links, by row index.
RENDERED_ROWS = """
() => [...document.querySelectorAll(".cat-rows [role=row][data-index]")].map((row) => [
  Number(row.dataset.index),
  row.querySelector("a.cat-name").getAttribute("href"),
])
"""


def start_store(
    serve: Serve, tmp_path: Path, *, slots: int
) -> tuple[Served, StoreManifest]:
    """Serve a generated store as ``zespol``; the server's scheduler indexes it."""
    store = make_store(tmp_path / "store", slots=slots, seed=7)
    config = StoreConfig(id="zespol", name="Zespół", kartograf=store.root, kind="local")
    settings = AppSettings(
        offline=True, stores=(config,), project_dirs=(store.projects_dir,)
    )
    served = serve(settings)
    return served, store


def open_catalog(
    page: Page, served: Served, query: dict[str, str] | None = None
) -> None:
    """Start a session, wait until every store is indexed, open the catalog."""
    page.goto(served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    wait_indexed(page, served.base)
    page.goto(f"{served.base}/?{urlencode({'view': 'catalog', **(query or {})})}")
    expect(page.get_by_role("grid", name="Lista plików katalogu")).to_be_visible()


def wait_indexed(page: Page, base: str) -> None:
    """Wait for the stores' first scans (the scheduler starts them with the server)."""
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while True:
        stores = api(page, base, "/health")["stores"]
        if stores and all(
            item["state"]["indexed_at"] and item["state"]["running_job"] is None
            for item in stores
        ):
            return
        assert time.monotonic() < deadline, stores
        page.wait_for_timeout(200)


def api(page: Page, base: str, path: str, params: dict[str, Any] | None = None) -> Any:
    """Read ``/api/v1`` with the page's session."""
    response = page.request.get(f"{base}/api/v1{path}", params=params)
    assert response.ok, response.text()
    return response.json()


def api_items(page: Page, base: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """Every row of a ``/slots`` query, page after page."""
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {**params, "limit": "200", **({"cursor": cursor} if cursor else {})}
        page_ = api(page, base, "/slots", query)
        items += page_["items"]
        cursor = page_["next_cursor"]
        if cursor is None:
            return items


def card_of(item: dict[str, Any], *, version: bool) -> Row:
    """Return the file card a row opens: its slot, its version outside ``current``."""
    path = item["version"]["path"] if version and item["version"] else None
    return f"{item['store']}/{item['slot']}", path


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


def grid(page: Page) -> Locator:
    """Return the catalog's list."""
    return page.get_by_role("grid", name="Lista plików katalogu")


def address(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def test_filters_paging_and_url_state(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """Filters are /slots parameters in the address; pages follow the cursor.

    A link of the address restores the filters and the list; Back undoes a
    filter; a value the API refuses is marked on its field.
    """
    served, _ = start_store(serve, tmp_path, slots=60)
    page = tab.page
    open_catalog(page, served, {"limit": "10"})
    everything = [
        card_of(item, version=False) for item in api_items(page, served.base, {})
    ]
    scrolled = shown_rows(page, len(everything))
    cursors = [
        url for url in tab.requests if "/api/v1/slots?" in url and "cursor=" in url
    ]

    page.get_by_label("Produkt", exact=True).select_option("nmt")
    page.get_by_label("Wersje", exact=True).select_option("all")
    page.get_by_label("Rok danych od").fill("2019")
    page.get_by_label("Rok danych od").press("Enter")
    expect(page).to_have_url(re.compile(r"years=2019-"))
    filters = {"product": "nmt", "versions": "all", "years": "2019-"}
    expected = [
        card_of(item, version=True) for item in api_items(page, served.base, filters)
    ]
    shown = shown_rows(page, len(expected))
    link = page.url
    other = page.context.new_page()
    other.goto(link)
    expect(other.get_by_label("Produkt", exact=True)).to_have_value("nmt")
    expect(other.get_by_label("Wersje", exact=True)).to_have_value("all")
    expect(other.get_by_label("Rok danych od")).to_have_value("2019")
    expect(grid(other)).to_have_attribute("aria-rowcount", str(len(expected) + 1))
    first_link = other.locator("a.cat-name").first.get_attribute("href") or ""
    first = dict(parse_qsl(urlsplit(first_link).query))
    page.go_back()
    expect(page.get_by_label("Rok danych od")).to_have_value("")
    any_year = api_items(page, served.base, {"product": "nmt", "versions": "all"})
    expect(grid(page)).to_have_attribute("aria-rowcount", str(len(any_year) + 1))
    page.goto(f"{served.base}/?view=catalog&years=20x3")
    expect(page.get_by_label("Rok danych od")).to_have_attribute("aria-invalid", "true")
    refused = page.get_by_role("alert").filter(has_text="years to rok albo zakres lat")
    expect(refused).not_to_have_count(0)

    assert scrolled == everything
    assert len(cursors) >= len(everything) // 10 >= 6
    assert dict(parse_qsl(urlsplit(link).query)) == {
        "view": "catalog",
        "limit": "10",
        **filters,
    }
    assert shown == expected
    assert len(expected) > 10
    assert (first["file"], first.get("file_version")) == expected[0]
    assert len(any_year) > len(expected)
    assert address(page) == {"view": "catalog", "years": "20x3"}
    tab.assert_clean()


def test_unit_filter_exact_code(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """``unit`` is the index's exact code (decision 9); search finds prefixes too."""
    served, _ = start_store(serve, tmp_path, slots=40)
    page = tab.page
    open_catalog(page, served)
    rows = api_items(page, served.base, {})
    versions = api_items(page, served.base, {"versions": "all"})
    units = sorted(
        {item["unit"] for item in rows if item["unit"] and item["unit"].count("-") == 6}
    )
    prefix, unit = next(
        (code.rsplit("-", 1)[0], code)
        for code in units
        if sum(other.startswith(code.rsplit("-", 1)[0]) for other in units) > 1
    )
    field = page.get_by_label("Jednostka (dokładny kod)")

    field.fill(prefix)
    field.press("Enter")
    expect(
        page.get_by_text(f"Żaden plik nie ma jednostki dokładnie „{prefix}”.")
    ).to_be_visible()
    empty = grid(page).get_attribute("aria-rowcount")
    page.get_by_role("searchbox", name="Szukaj w katalogu").fill(prefix)
    page.get_by_role("searchbox", name="Szukaj w katalogu").press("Enter")
    expect(page).to_have_url(re.compile(f"q={re.escape(prefix)}"))
    expect(grid(page)).to_have_attribute("aria-busy", "false")
    still_empty = grid(page).get_attribute("aria-rowcount")
    field.fill("")
    field.press("Enter")
    found = api_items(page, served.base, {"q": prefix})
    searched = shown_rows(page, len(found))
    page.get_by_role("searchbox", name="Szukaj w katalogu").fill(unit)
    page.get_by_role("searchbox", name="Szukaj w katalogu").press("Enter")
    page.get_by_role("button", name=f"Tylko jednostka „{unit}” (dokładny kod)").click()
    expect(page).to_have_url(re.compile(f"unit={re.escape(unit)}"))
    exact = shown_rows(page, sum(item["unit"] == unit for item in rows))
    page.get_by_label("Wersje", exact=True).select_option("all")
    expect(page).to_have_url(re.compile("versions=all"))
    exact_versions = shown_rows(page, sum(item["unit"] == unit for item in versions))

    assert (empty, still_empty) == ("1", "1")
    assert searched == [card_of(item, version=False) for item in found]
    assert len(searched) > 1
    assert {item["unit"] for item in found} >= {
        code for code in units if code.startswith(prefix)
    }
    assert "q" not in address(page)
    assert exact == [
        card_of(item, version=False) for item in rows if item["unit"] == unit
    ]
    assert exact_versions == [
        card_of(item, version=True) for item in versions if item["unit"] == unit
    ]
    tab.assert_clean()


def test_no_outline_in_catalog_not_on_map(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Files without an outline: the catalog's „Bez obrysu” group, never the map's."""
    served, _ = start_store(serve, tmp_path, slots=40)
    page = tab.page
    open_catalog(page, served)
    groups = api(page, served.base, "/slots", {"limit": "1"})["groups"]
    unlocated = api_items(page, served.base, {"location": "none"})
    world = api(
        page,
        served.base,
        "/map/footprints",
        {"bbox": "-180,-90,180,90", "limit": "5000"},
    )
    chips = page.get_by_role("group", name="Położenie")
    expect(chips.get_by_role("button", name=re.compile("^Wszystkie"))).to_contain_text(
        str(groups["footprint"] + groups["country"] + groups["none"])
    )

    chips.get_by_role("button", name=re.compile("^Bez obrysu")).click()
    expect(page).to_have_url(re.compile("location=none"))
    expect(
        chips.get_by_role("button", name=re.compile("^Bez obrysu"))
    ).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("note")).to_contain_text("nie ma ich na mapie")
    shown = shown_rows(page, len(unlocated))
    locations = page.locator(".cat-rows [role=row] .c-loc").all_inner_texts()
    map_actions = page.get_by_role(
        "button", name=re.compile("^Pokaż na mapie: ")
    ).count()
    page.goto(f"{served.base}/?view=catalog&location=with")
    located = page.locator(".cat-rows [role=row]").first
    expect(
        located.get_by_role("button", name=re.compile("^Pokaż na mapie: "))
    ).to_be_visible()
    name = located.locator("a.cat-name").inner_text()
    located.get_by_role("button", name=f"Pokaż na mapie: {name}").click()
    expect(page).to_have_url(re.compile("view=map"))

    assert groups["none"] == len(unlocated) > 0
    assert shown == [card_of(item, version=False) for item in unlocated]
    assert locations and all(text.startswith("bez obrysu") for text in locations)
    assert map_actions == 0
    assert world["groups"] == groups
    assert not {item["slot"] for item in world["items"]} & {
        item["slot"] for item in unlocated
    }
    assert address(page)["store"] == "zespol"
    assert "location" not in address(page)
    tab.assert_clean()


def test_ctrl_k_search(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """``Ctrl+K`` in any view opens the search; an ID finds its file; Enter opens it."""
    served, _ = start_store(serve, tmp_path, slots=30)
    page = tab.page
    open_catalog(page, served)
    rows = api_items(page, served.base, {})
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
    prefix = target["version"]["sha256"][:12]
    page.goto(f"{served.base}/?view=setup")
    expect(page.get_by_role("heading", name="Ustawienia")).to_be_visible()
    search = page.get_by_role("searchbox", name="Szukaj w katalogu")

    page.keyboard.press("Control+k")
    expect(search).to_be_focused()
    opened = address(page)
    page.keyboard.type(prefix)
    expect(grid(page)).to_have_attribute("aria-rowcount", "2")
    expect(page).to_have_url(re.compile(f"q={prefix}"))
    page.keyboard.press("ArrowDown")
    row = grid(page).get_by_role("row").filter(has_text=target["name"])
    expect(row).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile("file="))
    expect(page.get_by_role("dialog")).to_be_visible()
    card = address(page)
    page.keyboard.press("Escape")
    expect(page).not_to_have_url(re.compile("file="))
    expect(row).to_be_focused()
    page.keyboard.press("/")
    expect(search).to_be_focused()
    page.keyboard.press("Escape")
    expect(search).to_have_value("")
    expect(grid(page)).to_have_attribute("aria-rowcount", str(len(rows) + 1))
    grid(page).get_by_role("row").nth(1).focus()
    focused = "document.activeElement.getAttribute('aria-rowindex')"
    page.keyboard.press("End")
    at_end = page.evaluate(focused)
    page.keyboard.press("Home")
    at_start = page.evaluate(focused)
    page.keyboard.press("PageDown")
    one_page_down = int(page.evaluate(focused))

    assert opened == {"view": "catalog"}
    assert card["file"] == f"zespol/{target['slot']}"
    assert card["q"] == prefix
    assert (at_end, at_start) == (str(len(rows) + 1), "2")
    assert one_page_down > 10
    tab.assert_clean()


def test_second_adapter_entries_in_catalog(
    serve: Serve, tab: Tab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second producer's files reach the catalog through the index and the API.

    v0.1 settings name only Kartograf's directory, so — as in
    tests/integration/test_second_adapter.py — ``roots()`` gives the test
    producer the store's directory, the store is indexed in the test process
    and the scheduler plans no scan: a worker process would read the
    settings without that override.
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
    folder = tmp_path / "pomiary"
    folder.mkdir()
    for name in ("opady.csv", "stany.csv"):
        (folder / name).write_text("data;wartość\n", encoding="utf-8")
    config = StoreConfig(id="pomiary", name="Pomiary", kartograf=folder, kind="local")
    settings = AppSettings(offline=True, stores=(config,))
    paths = local_paths(tmp_path)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({"pomiary": {"external": str(folder)}})
        scan_store(
            registry.adapter("external"), writer, settings, "pomiary", mode="full"
        )
    served = serve(settings)
    page = tab.page

    open_catalog(page, served)
    shown = shown_rows(page, 2)
    rows = page.locator(".cat-rows [role=row]")
    chips = page.get_by_role("group", name="Położenie")
    expect(chips.get_by_role("button", name=re.compile("^Bez obrysu"))).to_contain_text(
        "2"
    )
    products = rows.locator(".c-prod").all_inner_texts()
    locations = rows.locator(".c-loc").all_inner_texts()
    rows.filter(has_text="opady.csv").click()

    assert shown == [("pomiary/opady.csv", None), ("pomiary/stany.csv", None)]
    assert all("external" in text for text in products)
    assert locations == ["bez obrysu\nbrak źródła obrysu"] * 2
    assert address(page)["file"] == "pomiary/opady.csv"
    tab.assert_clean()
