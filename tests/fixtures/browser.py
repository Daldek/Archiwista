"""A real ``archiwista serve`` and a Chromium tab that records what went wrong.

``Served`` is a server over a test directory with the real plugin registry,
job supervisor and scan scheduler; ``Tab`` a Playwright page recording CSP
violations (``securitypolicyviolation``), page errors, console errors,
requests and workers, so interface tests can assert the page stayed within
its policy and made no request outside the server.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from playwright.sync_api import ConsoleMessage, Page, Request, ViewportSize, Worker

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, AppSettings, ConfigStore
from archiwista.security import CSRF_HEADER, fragment_url, issue_one_time_token
from archiwista.server import LocalServer

VIEWPORT: ViewportSize = {"width": 1440, "height": 900}
# Installed before any page script; the page's CSP does not apply to it.
CSP_WATCH = """
window.__cspViolations = [];
document.addEventListener("securitypolicyviolation", (event) => {
  window.__cspViolations.push({
    directive: event.violatedDirective,
    blocked: event.blockedURI,
    sample: event.sample,
  });
});
"""
# Chromium logs every 4xx/5xx answer like this; expected API problems are
# asserted by the tests themselves.
FAILED_RESOURCE = "Failed to load resource"


@dataclass(frozen=True)
class Served:
    """A running server over a test directory."""

    server: LocalServer
    paths: AppPaths

    @property
    def base(self) -> str:
        """Return the server's address, e.g. ``http://127.0.0.1:41234``."""
        return f"http://127.0.0.1:{self.server.port}"

    def token_url(self) -> str:
        """Return a new one-time session address, as ``archiwista token`` does."""
        issued = issue_one_time_token(
            self.paths.index_file, "startup", minted_by=LOCAL_OWNER
        )
        return fragment_url(self.server.port, issued.token)

    def settings(self) -> AppSettings:
        """Return the settings saved in the configuration file."""
        return ConfigStore(self.paths.config_file).load()


@dataclass
class Tab:
    """A Chromium page and what happened on it."""

    page: Page
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    workers: list[str] = field(default_factory=list)

    def watch(self) -> None:
        """Start recording; call once, before the first navigation."""
        self.page.add_init_script(CSP_WATCH)
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.page.on("console", self._console)
        self.page.on("request", self._request)
        self.page.on("worker", self._worker)

    def csp_violations(self) -> list[dict[str, str]]:
        """Return the CSP violations of the current document."""
        violations: list[dict[str, str]] = self.page.evaluate("window.__cspViolations")
        return violations

    def foreign_requests(self, base: str) -> list[str]:
        """Return requests to any origin but ``base`` (data: and blob: aside)."""
        origin = urlsplit(base).netloc
        return [
            url
            for url in self.requests
            if urlsplit(url).scheme in ("http", "https", "ws", "wss")
            and urlsplit(url).netloc != origin
        ]

    def assert_clean(self) -> None:
        """Check no CSP violation, page error or console error happened."""
        assert self.csp_violations() == []
        assert self.page_errors == []
        assert self.console_errors == []

    def _console(self, message: ConsoleMessage) -> None:
        if message.type == "error" and not message.text.startswith(FAILED_RESOURCE):
            self.console_errors.append(message.text)

    def _request(self, request: Request) -> None:
        self.requests.append(request.url)

    def _worker(self, worker: Worker) -> None:
        self.workers.append(worker.url)


def session_headers(page: Page) -> dict[str, str]:
    """Return the CSRF header of the page's session (its ``sessionStorage``)."""
    token = page.evaluate("() => sessionStorage.getItem('archiwista_csrf')")
    assert isinstance(token, str), "the page has no session"
    return {CSRF_HEADER: token}
