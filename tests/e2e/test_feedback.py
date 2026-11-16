"""„Zgłoś uwagę” and „Zgłoszenia” in Chromium on a real server (Hydrograf's feedback).

The owner of a local installation (an administrator) opens the window from
the top bar: the counter follows the text, a blank description is refused
in the window, the preview shows the diagnostics that are sent — the view
and its parameters and the calls of the API, never the session's token —,
and „Wyślij” thanks and closes the window two seconds later. „Zgłoszenia” is
Nogat's kit view ``<nogat-admin-feedback>`` with Archiwista's session: the
report is unread, its context (the contact, the account, the diagnostics) is
folded under „Kontekst”, „Oznacz jako przeczytane” and back change it, and
„Usuń” deletes it after a confirmation.
"""

import json
from collections.abc import Callable

from playwright.sync_api import Page, expect

from archiwista.state import StateStore
from tests.fixtures.browser import Served, Tab

Serve = Callable[..., Served]
MESSAGE = "Mapa nie pokazuje arkuszy po przybliżeniu.\nDruga linia opisu."
THANKS = "Dziękujemy! Zgłoszenie zostało zapisane."
# A report another session sent through the API: markup in its text, and
# diagnostics of any shape (the server keeps any JSON object as sent).
HOSTILE = {
    "message": '<img src="x" onerror="window.__pwned = 1"><b>pogrubione</b>',
    "contact": "<script>window.__pwned = 2</script>",
    "diagnostics": {"events": "nie lista", "view": "<i>x</i>", "env": 5},
}
# Send a report as the page's session (its CSRF header), as feedback.js does.
SEND = """async (report) => {
  const headers = {
    "Content-Type": "application/json",
    "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf"),
  };
  const body = JSON.stringify(report);
  return (await fetch("/api/v1/feedback", { method: "POST", headers, body })).status;
}"""


def open_shell(page: Page, url: str) -> None:
    """Open an address and wait for the shell of a started session."""
    page.goto(url)
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()


def test_a_report_is_sent_with_its_diagnostics_and_read_by_the_administrator(
    serve: Serve, tab: Tab
) -> None:
    """The window, its preview and thanks; the list marks, unmarks and deletes."""
    served = serve()
    page = tab.page
    token = served.token_url().partition("#token=")[2]
    open_shell(page, f"{served.base}/?view=setup#token={token}")
    window = page.get_by_role("dialog", name="Zgłoś uwagę")

    page.get_by_role("button", name="Zgłoś uwagę").click()
    description = window.get_by_label("Opis problemu lub sugestii")
    expect(description).to_be_focused()
    expect(window.get_by_text("0/5000")).to_be_visible()
    window.get_by_role("button", name="Wyślij").click()
    expect(window.get_by_text("Opis nie może być pusty.")).to_be_visible()
    description.fill(MESSAGE)
    expect(window.get_by_text(f"{len(MESSAGE)}/5000")).to_be_visible()
    window.get_by_label("Imię lub e-mail").fill("ola@example.com")
    window.get_by_text("Pokaż co zostanie wysłane").click()
    preview = json.loads(window.locator("pre").inner_text())
    window.get_by_role("button", name="Wyślij").click()
    expect(window.get_by_text(THANKS)).to_be_visible()
    expect(window).to_be_hidden()

    assert preview["view"] == {"view": "setup", "params": {}}
    assert preview["env"]["url"] == f"{served.base}/?view=setup"
    assert preview["env"]["mode"] == "local"
    calls = {
        (event["data"]["method"], event["data"]["endpoint"], event["data"]["status"])
        for event in preview["events"]
        if event["type"] == "api_call"
    }
    assert ("POST", "/api/v1/session", 200) in calls
    assert token not in json.dumps(preview)

    page.get_by_role("link", name="Zgłoszenia").click()
    expect(page.get_by_role("heading", name="Zgłoszenia")).to_be_visible()
    report = page.locator("li.nogat-admin-report")
    expect(report).to_have_count(1)
    expect(report.get_by_text("nowe", exact=True)).to_be_visible()
    expect(page.get_by_text("Nieprzeczytane: 1 z 1")).to_be_visible()
    expect(report.locator(".nogat-admin-message")).to_have_text(MESSAGE)
    report.get_by_text("Kontekst").click()
    context = report.locator(".nogat-admin-context")
    expect(context.get_by_text("ola@example.com")).to_be_visible()
    expect(context.locator(".nogat-admin-json")).to_contain_text('"api_call"')
    report.get_by_role("button", name="Oznacz jako przeczytane").click()
    expect(report.get_by_text("nowe", exact=True)).to_have_count(0)
    expect(page.get_by_text("Nieprzeczytane: 0 z 1")).to_be_visible()
    report.get_by_role("button", name="Oznacz jako nieprzeczytane").click()
    expect(report.get_by_text("nowe", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_text("Nieprzeczytane: 1 z 1")).to_be_visible()
    report.get_by_role("button", name="Usuń").click()
    confirmation = page.get_by_role("dialog", name="Usunąć zgłoszenie #1?")
    confirmation.get_by_role("button", name="Usuń").click()
    expect(page.get_by_text("Brak zgłoszeń.")).to_be_visible()

    reports = StateStore(served.paths.state_file).feedback(limit=1)
    assert (reports.total, reports.unread) == (0, 0)
    tab.assert_clean()


def test_a_report_is_shown_as_text_whatever_it_holds(serve: Serve, tab: Tab) -> None:
    """Markup stays text, and diagnostics of any shape show as JSON."""
    served = serve()
    page = tab.page
    open_shell(page, served.token_url())
    status = page.evaluate(SEND, HOSTILE)

    page.get_by_role("link", name="Zgłoszenia").click()
    report = page.locator("li.nogat-admin-report")
    report.get_by_text("Kontekst").click()
    context = report.locator(".nogat-admin-context")

    assert status == 201
    expect(report.locator(".nogat-admin-message")).to_have_text(str(HOSTILE["message"]))
    expect(context.get_by_text(str(HOSTILE["contact"]))).to_be_visible()
    expect(context.locator(".nogat-admin-json")).to_contain_text('"<i>x</i>"')
    expect(report.locator("img, b, script, i")).to_have_count(0)
    assert page.evaluate("() => window.__pwned") is None
    tab.assert_clean()
