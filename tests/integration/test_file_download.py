"""File download over HTTP (plan v0.4 T10, C11; A-ADR-047 decision 5).

A version of a generated Kartograf store and the own data of a project are
downloaded as a browser's link and an agent fetch them: the whole file and
parts of it, as an attachment with its name and type, only what the index
knows and the session sees, inside its root, at most two streams of one
person at once, and one entry of the action log for a download from its
first byte.
"""

import hashlib
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.types import ASGIApp

from archiwista.index import own_file_id
from tests.fixtures.api_session import PORT, Caller, assert_problem
from tests.fixtures.api_store import STORE, served_store
from tests.fixtures.own_data import write_snapshot_fixture
from tests.fixtures.own_data_api import own_data_api
from tests.fixtures.permissions import last_entry, log_entries, share
from tests.fixtures.preview_api import entry_of

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

WAIT_S = 30.0
GEOTIFF = "image/tiff; application=geotiff"
# A file larger than what the sockets of one connection buffer.
LARGE_BYTES = 64 * 1024**2


def fetch(
    caller: Caller,
    url: str,
    *,
    method: str = "GET",
    csrf: bool = True,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Send a request of ``caller``'s session to ``/api/v1{url}``."""
    sent = {"cookie": f"archiwista_session={caller.session_id}", **(headers or {})}
    if csrf:
        sent["x-archiwista-csrf"] = caller.csrf
    response: httpx.Response = caller.client.request(
        method, f"/api/v1{url}", headers=sent
    )
    return response


def test_a_version_streams_whole_and_in_parts_and_is_logged_once(
    tmp_path: Path,
) -> None:
    """The body and SHA-256 of the file, a range, HEAD, unknown and outside."""
    with served_store(tmp_path) as served:
        # Arrange
        entry = entry_of(served.store, "tif_sheet", "regular")
        on_disk = served.store.root / entry.path
        data = on_disk.read_bytes()
        url = f"/stores/{STORE}/versions/{entry.path}/file"
        card = fetch(served.owner, f"/stores/{STORE}/versions/{entry.path}").json()
        before = last_entry(served.api.state)

        # Act
        whole = fetch(served.owner, url)
        part = fetch(served.owner, url, headers={"range": "bytes=10-19"})
        head = fetch(served.owner, url, method="HEAD")
        unknown = fetch(served.owner, f"/stores/{STORE}/versions/nmt/brak.tif/file")
        logged = log_entries(served.api.state, after=before)
        outside = tmp_path / "poza.tif"
        outside.write_bytes(b"not in the store")
        on_disk.parent.chmod(0o755)
        on_disk.unlink()
        on_disk.symlink_to(outside)
        refused = fetch(served.owner, url)

    # Assert
    assert whole.status_code == 200
    assert whole.content == data
    assert hashlib.sha256(whole.content).hexdigest() == card["version"]["sha256"]
    name = entry.path.rsplit("/", 1)[1]
    assert whole.headers["content-disposition"] == f'attachment; filename="{name}"'
    assert whole.headers["content-type"] == GEOTIFF
    assert whole.headers["x-content-type-options"] == "nosniff"
    assert whole.headers["cache-control"] == "private, no-store"
    assert whole.headers["accept-ranges"] == "bytes"
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 10-19/{len(data)}"
    assert part.content == data[10:20]
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(data))
    assert [(item.action, item.target, item.details) for item in logged] == [
        ("file.download", card["ref"], {"size_bytes": len(data)})
    ]
    assert_problem(unknown, 404, "not_found")
    assert_problem(refused, 403, "forbidden", "path_outside_root")


def test_own_files_their_sets_and_snapshots_for_those_who_see_the_project(
    tmp_path: Path,
) -> None:
    """Names and types, a member of a set, a snapshot, hidden and changed files."""
    with own_data_api(tmp_path, first=("shp_full", "tif_2180"), workers=1) as served:
        # Arrange
        project = served.first
        root = project.root
        shapefile = project.folder.file("shp_full").path
        raster = project.folder.file("tif_2180").path
        (root / "raport łąki.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (root / "notatki.qwerty").write_bytes(b"nothing known")
        snapshot = write_snapshot_fixture(
            root, raster, created_at=datetime(2026, 10, 20, 12, tzinfo=UTC)
        )
        served.scan()
        share(served.api.state, project.access_key, "private")
        olga, igor = served.caller("owner"), served.caller("other")
        dbf = shapefile.removesuffix(".shp") + ".dbf"
        snapshot_url = project.snapshot_url(raster, snapshot.label, "file")
        copied = snapshot.directory / snapshot.document["files"][0]["name"]

        # Act
        pdf = fetch(olga, project.url("raport łąki.pdf", "file"))
        unknown = fetch(olga, project.url("notatki.qwerty", "file"))
        card = fetch(olga, project.url(shapefile)).json()
        member = fetch(olga, project.url(shapefile, f"file?member={dbf}"))
        stranger = fetch(olga, project.url(shapefile, "file?member=obce.dbf"))
        copy = fetch(olga, snapshot_url)
        hidden = fetch(igor, project.url(raster, "file"))
        hidden_copy = fetch(igor, snapshot_url)
        with (root / raster).open("ab") as changing:
            changing.write(b"\0")
        changed = fetch(olga, project.url(raster, "file"))

    # Assert
    assert pdf.status_code == 200 and pdf.content == b"%PDF-1.4\n%%EOF\n"
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"] == (
        "attachment; filename*=utf-8''raport%20%C5%82%C4%85ki.pdf"
    )
    assert unknown.headers["content-type"] == "application/octet-stream"
    assert card["members"][0] == shapefile and dbf in card["members"]
    assert member.status_code == 200
    assert member.content == (root / dbf).read_bytes()
    assert member.headers["content-disposition"] == f'attachment; filename="{dbf}"'
    assert_problem(stranger, 404, "not_found")
    assert copy.status_code == 200
    assert copy.content == copied.read_bytes()
    assert copy.headers["content-type"] == GEOTIFF
    assert_problem(hidden, 404, "not_found")
    assert_problem(hidden_copy, 404, "not_found")
    assert_problem(changed, 409, "conflict", "own_file_changed")


def test_only_a_link_of_the_same_origin_goes_without_the_csrf_header(
    tmp_path: Path,
) -> None:
    """``Sec-Fetch-Site`` ``same-origin`` and ``none`` pass; others keep the rule."""
    with served_store(tmp_path) as served:
        # Arrange
        entry = entry_of(served.store, "tif_sheet", "regular")
        url = f"/stores/{STORE}/versions/{entry.path}/file"

        # Act
        sites = {
            site: fetch(served.owner, url, csrf=False, headers={"sec-fetch-site": site})
            for site in ("same-origin", "none", "same-site", "cross-site")
        }
        bare = fetch(served.owner, url, csrf=False)
        head = fetch(
            served.owner,
            url,
            method="HEAD",
            csrf=False,
            headers={"sec-fetch-site": "same-origin"},
        )
        wrong = fetch(
            served.owner,
            url,
            csrf=False,
            headers={"sec-fetch-site": "same-origin", "x-archiwista-csrf": "obcy"},
        )
        other_route = fetch(
            served.owner, "/health", csrf=False, headers={"sec-fetch-site": "none"}
        )

    # Assert
    assert sites["same-origin"].status_code == 200
    assert sites["none"].status_code == 200
    assert head.status_code == 200
    assert_problem(sites["same-site"], 403, "forbidden", "csrf_rejected")
    assert_problem(sites["cross-site"], 403, "forbidden", "csrf_rejected")
    assert_problem(bare, 403, "forbidden", "csrf_rejected")
    assert_problem(wrong, 403, "forbidden", "csrf_rejected")
    assert_problem(other_route, 403, "forbidden", "csrf_rejected")


@contextmanager
def listening(app: ASGIApp) -> Iterator[str]:
    """Serve ``app`` on a socket: the test client buffers each answer whole."""
    sock = socket.create_server(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        deadline = time.monotonic() + WAIT_S
        while not server.started:
            assert time.monotonic() < deadline, "the server did not start"
            time.sleep(0.01)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join()
        sock.close()


def test_a_person_streams_two_downloads_at_once_until_one_ends(
    tmp_path: Path,
) -> None:
    """A third stream is ``429`` with ``Retry-After``; a client leaving frees one."""
    with own_data_api(tmp_path, first=("tif_2180",), workers=1) as served:
        # Arrange
        with (served.first.root / "duzy.bin").open("wb") as large:
            large.truncate(LARGE_BYTES)
        served.scan()
        olga = served.caller("owner")
        url = (
            f"/api/v1/projects/{served.first.key}/files/{own_file_id('duzy.bin')}/file"
        )
        headers = {
            "host": f"127.0.0.1:{PORT}",
            "cookie": f"archiwista_session={olga.session_id}",
            "x-archiwista-csrf": olga.csrf,
        }
        with (
            listening(served.api.client.app) as base,
            httpx.Client(base_url=base, headers=headers, timeout=WAIT_S) as client,
        ):
            # Act
            with (
                client.stream("GET", url) as first,
                client.stream("GET", url) as second,
            ):
                third = client.get(url)
            deadline = time.monotonic() + WAIT_S
            while (
                again := client.get(url, headers={"range": "bytes=1-1"})
            ).status_code == 429:
                assert time.monotonic() < deadline, "the streams were not ended"
                time.sleep(0.05)

    # Assert
    assert (first.status_code, second.status_code) == (200, 200)
    assert_problem(third, 429, "rate_limited", "too_many_downloads")
    assert third.headers["retry-after"] == "10"
    assert again.status_code == 206 and again.content == b"\0"
