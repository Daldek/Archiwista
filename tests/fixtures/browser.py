"""A real ``archiwista serve`` and a Chromium tab that records what went wrong.

``Served`` is a server over a test directory with the real plugin registry,
job supervisor and scan scheduler; ``Tab`` a Playwright page recording CSP
violations (``securitypolicyviolation``), page errors, console errors,
requests and workers, so interface tests can assert the page stayed within
its policy and made no request outside the server.

For frame rates (plan v0.2, decision 1) ``gpu_browser`` gives a Chromium
drawing WebGL on the GPU when it can: Chrome of a graphical session over CDP
(``ARCHIWISTA_BROWSER_CDP``), else Playwright's Chromium with the GPU flags;
``webgl_renderer`` names what draws, ``require_hardware_gl`` skips a
measurement drawn in software — or fails it with ``ARCHIWISTA_REQUIRE_GPU=1``
— and ``pan_frames`` drags a map while counting its frames.
"""

import math
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import (
    Browser,
    ConsoleMessage,
    Page,
    Playwright,
    Request,
    ViewportSize,
    Worker,
)

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, AppSettings, ConfigStore
from archiwista.security import CSRF_HEADER, fragment_url, issue_one_time_token
from archiwista.server import LocalServer

VIEWPORT: ViewportSize = {"width": 1440, "height": 900}
CDP_VARIABLE = "ARCHIWISTA_BROWSER_CDP"
REQUIRE_GPU_VARIABLE = "ARCHIWISTA_REQUIRE_GPU"
# nouveau is on Chromium's GPU blocklist; ANGLE on EGL takes Mesa's driver of
# the card instead of SwiftShader (plan v0.2, decision 1, way a).
GPU_ARGS = ("--ignore-gpu-blocklist", "--use-gl=angle", "--use-angle=gl-egl")
# WebGL drawn by the processor: frame rates say nothing of a computer's GPU.
SOFTWARE_GL = ("SwiftShader", "llvmpipe", "softpipe")
_RENDERER = """
() => {
  const gl = document.createElement("canvas").getContext("webgl2");
  if (!gl) return "no WebGL 2";
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  return gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
}
"""
# Collects the times of animation frames for ``duration`` ms; the page reads
# ``window.__frames`` when they are over.
_COUNT_FRAMES = """
(duration) => {
  window.__frames = new Promise((resolve) => {
    const times = [];
    const step = (now) => {
      times.push(now);
      if (now - times[0] < duration) requestAnimationFrame(step);
      else resolve(times);
    };
    requestAnimationFrame(step);
  });
}
"""
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


def gpu_browser(playwright: Playwright) -> Browser:
    """Return a Chromium drawing WebGL on the GPU if it can (decision 1).

    ``ARCHIWISTA_BROWSER_CDP`` (``http://127.0.0.1:<port>``) names a Chrome
    started with ``--remote-debugging-port`` in a graphical session (way b);
    closing the returned browser only disconnects from it. Otherwise
    Playwright's Chromium starts with ``GPU_ARGS`` (way a: an account in
    group ``render``); without access to the GPU it draws in software, which
    ``webgl_renderer`` shows.
    """
    address = os.environ.get(CDP_VARIABLE)
    if address:
        return playwright.chromium.connect_over_cdp(address)
    return playwright.chromium.launch(args=list(GPU_ARGS))


def webgl_renderer(page: Page) -> str:
    """Return what draws the page's WebGL (``WEBGL_debug_renderer_info``)."""
    renderer: str = page.evaluate(_RENDERER)
    return renderer


def require_hardware_gl(renderer: str, summary: str) -> None:
    """Skip a frame rate drawn in software; fail it with ``ARCHIWISTA_REQUIRE_GPU=1``.

    A software renderer (``SOFTWARE_GL``) measures the processor, not the
    GPU of the computer, so it neither meets nor misses a frame-rate target;
    the gate mode makes the missing GPU an error instead of a skip.
    """
    if not any(name in renderer for name in SOFTWARE_GL):
        return
    message = f"no GPU for the browser, WebGL in software: {summary}"
    if os.environ.get(REQUIRE_GPU_VARIABLE) == "1":
        pytest.fail(message)
    pytest.skip(message)


def pan_frames(page: Page, seconds: float) -> list[float]:
    """Drag the map in a slow circle for ``seconds``; return its frames' times (ms).

    The map follows the pointer at every frame (``requestAnimationFrame``
    in the page counts them).
    """
    page.wait_for_timeout(2000)
    box = page.locator(".maplibregl-canvas").bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.evaluate(_COUNT_FRAMES, seconds * 1000)
    started = time.monotonic()
    while (moving := time.monotonic() - started) < seconds + 0.2:
        page.mouse.move(x + 150 * math.sin(moving * 2), y + 90 * math.cos(moving * 2))
        time.sleep(1 / 120)
    times: list[float] = page.evaluate("() => window.__frames")
    page.mouse.up()
    return times
