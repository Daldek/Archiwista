"""Obserwator's HTTP layer stood in for with the archives of its own fixtures.

Obserwator's own tests answer ``httpx`` from recordings by patching
``httpx.HTTPTransport.handle_request``; this does the same for any file of
``obserwator.testing.fixture_files()`` under ``archives/`` and any archive a
test adds (``archives``, by server path): a ``HEAD`` or ``GET`` of
``<base>/<server path>`` answers the file with an ``ETag`` of its bytes (or
one a test sets, ``etags``), a ``GET`` of a directory of them its listing
(links to its files, as IMGW-PIB's server lists a directory), a ``GET`` of
IMGW-PIB's public API (the station catalog's source) the answer recorded in
``recordings.json``, anything else is ``404``. No request leaves the
process. Every request is recorded (``requests``), and a test may stop a
``GET`` of a file after a number of them (``interrupt_after``) to stand for
a person who stopped the job.
"""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from unittest import mock

import httpx
from obserwator.testing import fixture_files

# The base of IMGW-PIB's archives (Obserwator's ``IMGW_PUBLIC_DATA_URL``).
BASE = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/"
LAST_MODIFIED = "Sat, 17 Oct 2026 12:00:00 GMT"
# The recorded answers of IMGW-PIB's public API among Obserwator's fixtures.
_API_CASES = ("hydro_current", "meteo_current")


@dataclass
class StandinSource:
    """What the stood-in source answers, and what it was asked."""

    etags: dict[str, str] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)
    interrupt_after: int | None = None
    archives: dict[str, bytes] = field(default_factory=dict)

    def gets(self) -> list[str]:
        """Return the server paths fetched with ``GET``, in their order."""
        return [path for method, path in self.requests if method == "GET"]

    def files(self) -> list[str]:
        """Return the files fetched with ``GET`` (no listing), in their order."""
        return [path for path in self.gets() if not path.endswith("/")]


def _api_answers() -> dict[str, object]:
    """Return the recorded answers of the public API, by URL."""
    document = json.loads(fixture_files().joinpath("recordings.json").read_text())
    return {
        str(item["url"]): item["json"]
        for item in document["interactions"]
        if item["case"] in _API_CASES
    }


def _listing(source: StandinSource, path: str) -> str | None:
    """Return a directory listing of the archives under ``path``; ``None``: none."""
    directory = fixture_files().joinpath("archives", path.rstrip("/"))
    names = (
        {item.name for item in directory.iterdir() if item.is_file()}
        if directory.is_dir()
        else set()
    )
    names |= {
        name.removeprefix(path)
        for name in source.archives
        if name.startswith(path) and "/" not in name.removeprefix(path)
    }
    if not names and not directory.is_dir():
        return None
    return "".join(f'<a href="{name}">{name}</a>' for name in sorted(names))


def _answer(source: StandinSource, request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    path = url.removeprefix(BASE) if url.startswith(BASE) else None
    source.requests.append((request.method, path or url))
    api = _api_answers()
    if path is None:
        if request.method == "GET" and url in api:
            return httpx.Response(200, json=api[url], request=request)
        return httpx.Response(404, request=request)
    if path.endswith("/"):
        listing = _listing(source, path)
        if listing is None:
            return httpx.Response(404, request=request)
        return httpx.Response(200, text=listing, request=request)
    resource = fixture_files().joinpath("archives", path)
    data = source.archives.get(path)
    if data is None and not resource.is_file():
        return httpx.Response(404, request=request)
    stop = source.interrupt_after
    if request.method == "GET" and stop is not None and len(source.files()) > stop:
        raise KeyboardInterrupt
    if data is None:
        data = resource.read_bytes()
    etag = source.etags.get(path, f'"{hashlib.sha256(data).hexdigest()[:16]}"')
    headers = {
        "ETag": etag,
        "Last-Modified": LAST_MODIFIED,
        "Content-Length": str(len(data)),
    }
    content = b"" if request.method == "HEAD" else data
    return httpx.Response(200, headers=headers, content=content, request=request)


@contextmanager
def standin_source() -> Iterator[StandinSource]:
    """Answer Obserwator's synchronous ``httpx`` requests from its fixtures."""
    source = StandinSource()

    def handle(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        return _answer(source, request)

    with mock.patch.object(httpx.HTTPTransport, "handle_request", handle):
        yield source
