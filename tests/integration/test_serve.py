"""``archiwista serve`` and ``archiwista token`` with a real server in a thread."""

import io
import json
import os
import re
import socket
import stat
import threading
import time
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from archiwista import server as server_module
from archiwista.api import health
from archiwista.cli import main
from archiwista.security import CSRF_HEADER, LOOPBACK_HOST, SESSION_COOKIE, TOKEN_TTL
from archiwista.server import AppServer, LaunchFile, open_in_browser
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import assert_problem
from tests.fixtures.cli_errors import refusal
from tests.fixtures.local_server import NoSources, local_paths, server_nodelay, serving
from tests.fixtures.preview_api import (
    center_tile_url,
    entry_of,
    scanned_store,
    version_url,
)
from tests.fixtures.server_logs import printed, records

FRAGMENT_URL = re.compile(r"http://127\.0\.0\.1:(\d+)/#token=([A-Za-z0-9_-]+)")
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


def free_port() -> int:
    """Return a loopback port that nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "localhost"])
def test_serve_refuses_non_loopback_host(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], host: str
) -> None:
    """Any address but 127.0.0.1 ends with an error, before anything listens."""
    paths = local_paths(tmp_path)
    port = free_port()
    statuses: list[int] = []
    argv = ["serve", "--host", host, "--port", str(port), "--no-browser"]
    thread = threading.Thread(
        target=lambda: statuses.append(main(argv, registry=NoSources(), paths=paths)),
        daemon=True,
    )

    thread.start()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert statuses == [2]
    err = capsys.readouterr().err
    assert host in err
    assert "127.0.0.1" in err
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    assert not paths.data_dir.exists()


def test_serve_prints_fragment_url_on_a_terminal(tmp_path: Path) -> None:
    """On a terminal the address carries a one-time token the server exchanges."""
    with serving(local_paths(tmp_path), terminal=True) as (server, output):
        match = FRAGMENT_URL.search(output)
        assert match is not None
        port, token = int(match[1]), match[2]
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            exchanged = client.post("/api/v1/session", json={"token": token})
            csrf = {CSRF_HEADER: exchanged.json()["csrf_token"]}
            state = client.get("/api/v1/session", headers=csrf)
            replayed = client.post("/api/v1/session", json={"token": token})
            rebound = client.get("/api/v1/session", headers={"host": "evil.example"})

    assert port == server.port
    assert exchanged.status_code == 200
    assert state.json()["actor"] == "local"
    assert_problem(replayed, 401, "unauthorized", "session_required")
    assert_problem(rebound, 403, "forbidden", "invalid_host")


def test_serve_prints_only_its_lifecycle_when_not_on_a_terminal(
    tmp_path: Path,
) -> None:
    """Under a service manager the one-time address stays out of the journal.

    Standard output, which the journal keeps, gets nothing; standard error gets
    the lifecycle records ``start`` (the origin alone, never the
    token) and ``stop``, as the lifecycle log does (Nogat DEV-12.7).
    """
    paths = local_paths(tmp_path)
    err = io.StringIO()
    with serving(paths, err=err) as (server, output):
        token = server.url.partition("#token=")[2]
    lines = printed(err.getvalue())

    assert output == ""
    assert token and token not in err.getvalue()
    assert [(line["kind"], line["event"]) for line in lines] == [
        ("lifecycle", "start"),
        ("lifecycle", "stop"),
    ]
    assert lines == records(paths.logs_dir, "lifecycle")
    assert lines[0]["settings"] == {"origin": f"http://127.0.0.1:{server.port}"}


def test_serve_logs_each_request_once_without_its_secrets(tmp_path: Path) -> None:
    """One access record per request; no token, search text or User-Agent in a log.

    The token is exchanged in a request's body; a query keeps the names of
    ``token`` and ``q`` without their values; the client is named by the class
    of its User-Agent only.
    """
    paths = local_paths(tmp_path)
    err = io.StringIO()
    with (
        serving(paths, err=err) as (server, _),
        httpx.Client(
            base_url=f"http://127.0.0.1:{server.port}",
            headers={"User-Agent": FIREFOX},
        ) as browser,
    ):
        token = server.url.partition("#token=")[2]
        exchanged = browser.post("/api/v1/session", json={"token": token})
        csrf = {CSRF_HEADER: exchanged.json()["csrf_token"]}
        query = {"token": token, "q": "Kraków", "limit": "5"}
        queried = browser.get("/api/v1/health", params=query, headers=csrf)
        missing = browser.get("/api/v1/nothing", headers=csrf)
    access = records(paths.logs_dir, "access")
    written = [path.read_text("utf-8") for path in paths.logs_dir.iterdir()]
    logged = "".join([*written, err.getvalue()])

    assert (exchanged.status_code, queried.status_code, missing.status_code) == (
        200,
        200,
        404,
    )
    assert [(r["method"], r["path"], r["status"], r["agent"]) for r in access] == [
        ("POST", "/api/v1/session", 200, "browser"),
        ("GET", "/api/v1/health?token=&q=&limit=5", 200, "browser"),
        ("GET", "/api/v1/nothing", 404, "browser"),
    ]
    assert access[1]["bytes"] == len(queried.content)
    assert len({record["request_id"] for record in access}) == 3
    assert "x-request-id" not in queried.headers
    assert token not in logged
    assert "Krak" not in logged and "Firefox" not in logged


# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
@pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
def test_serve_leaves_tiles_and_interface_files_below_400_out_of_the_access_log(
    tmp_path: Path,
) -> None:
    """A map tile and an interface file, also revalidated: not logged; a 404 is."""
    store, paths = scanned_store(tmp_path)
    raster = entry_of(store, "tif_sheet", "regular").path
    registry = load_registry(cache_dir=paths.cache_dir)
    with serving(paths, registry=registry) as (server, _), _owner(server) as owner:
        info = owner.get(version_url(raster)).json()
        tile = owner.get(center_tile_url(info))
        same_tile = owner.get(
            center_tile_url(info), headers={"If-None-Match": tile.headers["etag"]}
        )
        beyond = owner.get(center_tile_url(info, info["maxzoom"] + 1))
        style = owner.get("/static/styles.css")
        same_style = owner.get(
            "/static/styles.css", headers={"If-None-Match": style.headers["etag"]}
        )
        missing = owner.get("/static/nothing.css")
    access = records(paths.logs_dir, "access")

    assert [tile.status_code, same_tile.status_code, beyond.status_code] == [
        200,
        304,
        404,
    ]
    assert [style.status_code, same_style.status_code, missing.status_code] == [
        200,
        304,
        404,
    ]
    assert [(record["path"], record["status"]) for record in access] == [
        ("/api/v1/session", 200),
        (version_url(raster), 200),
        (urlsplit(str(beyond.url)).path, 404),
        ("/static/nothing.css", 404),
    ]


def test_serve_logs_an_unhandled_exception_as_an_app_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A defect in a route: an app record of its request; its type on stderr.

    The record carries the request's id and the error with its message, an IP
    address in it written ``[ip]``; standard error gets the error reduced to
    its type, and Uvicorn's own report of it adds nothing.
    """

    def broken(*args: object) -> None:
        raise RuntimeError("the index of 203.0.113.7 is gone")

    monkeypatch.setattr(health, "read_health", broken)
    paths = local_paths(tmp_path)
    err = io.StringIO()
    with serving(paths, err=err) as (server, _), _owner(server) as owner:
        failed = owner.get("/api/v1/health")
    (access,) = [
        record
        for record in records(paths.logs_dir, "access")
        if record["path"] == "/api/v1/health"
    ]
    (application,) = records(paths.logs_dir, "app")
    lines = printed(err.getvalue())

    assert_problem(failed, 500, "internal_error")
    assert access["status"] == 500
    assert application["request_id"] == access["request_id"]
    assert (application["level"], application["event"]) == (
        "error",
        "unhandled_exception",
    )
    assert application["error"]["type"] == "RuntimeError"
    assert application["error"]["message"] == "the index of [ip] is gone"
    assert [(line["kind"], line["event"]) for line in lines] == [
        ("lifecycle", "start"),
        ("app", "unhandled_exception"),
        ("lifecycle", "stop"),
    ]
    assert (lines[1]["request_id"], lines[1]["message"], lines[1]["error"]) == (
        None,
        None,
        {"type": "RuntimeError"},
    )


def test_serve_reports_busy_port(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A taken port ends with a Polish message and a non-zero status."""
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        status = main(
            ["serve", "--port", str(port), "--no-browser"],
            registry=NoSources(),
            paths=local_paths(tmp_path),
        )

    captured = capsys.readouterr()
    document = refusal(captured.out, captured.err, status)
    assert (status, document["code"]) == (4, "conflict")
    assert document["details"]["reason"] == "port_unavailable"
    assert f"Nie można nasłuchiwać na 127.0.0.1:{port}" in captured.err


def test_serve_connections_send_without_nagle_delay(tmp_path: Path) -> None:
    """The server's end of a connection sends at once (``TCP_NODELAY``).

    Without it every response written in parts on a kept-alive connection
    waited for the client's delayed acknowledgement: about 40 ms added to each
    request of the browser. asyncio sets it only on an accepted socket that
    reports ``IPPROTO_TCP``: never on macOS, and nowhere for the server's
    listening socket, so this fails wherever the server relies on asyncio.
    """
    with (
        serving(local_paths(tmp_path)) as (server, _),
        socket.create_connection((LOOPBACK_HOST, server.port), timeout=10) as client,
    ):
        client.sendall(b"GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        answered = client.recv(64)
        nodelay = server_nodelay(client)

    assert answered.startswith(b"HTTP/1.1 ")
    assert nodelay != 0


def test_token_command_issues_one_time_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista token`` gives an agent a one-time session of the server."""
    paths = local_paths(tmp_path)
    with serving(paths) as (server, _):
        printed = main(["token", "--port", str(server.port)], paths=paths)
        url = capsys.readouterr().out.strip()
        listed = main(["token", "--port", str(server.port), "--json"], paths=paths)
        as_json = json.loads(capsys.readouterr().out)
        match = FRAGMENT_URL.fullmatch(url)
        assert match is not None
        with httpx.Client(base_url=f"http://127.0.0.1:{server.port}") as client:
            first = client.post("/api/v1/session", json={"token": match[2]})
            second = client.post("/api/v1/session", json={"token": match[2]})
            other = client.post("/api/v1/session", json={"token": as_json["token"]})

    assert (printed, listed) == (0, 0)
    assert int(match[1]) == server.port
    assert as_json["url"] == f"http://127.0.0.1:{server.port}/#token={as_json['token']}"
    assert first.status_code == 200
    assert second.status_code == 401
    assert other.status_code == 200


def test_serve_browser_opens_private_file_removed_once_token_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The browser gets a 0600 file, never the token; using the token deletes it."""
    opened: list[str] = []
    browsed = threading.Event()

    def browser(uri: str) -> bool:
        opened.append(uri)
        browsed.set()
        return True

    monkeypatch.setattr(webbrowser, "open", browser)
    paths = local_paths(tmp_path)
    with serving(paths, on_ready=open_in_browser) as (server, _):
        assert browsed.wait(10)
        launch = _launch(server).path
        assert launch is not None
        mode = stat.S_IMODE(launch.stat().st_mode)
        page = launch.read_text("utf-8")
        match = FRAGMENT_URL.fullmatch(server.url)
        assert match is not None
        with httpx.Client(base_url=f"http://127.0.0.1:{server.port}") as client:
            exchanged = client.post("/api/v1/session", json={"token": match[2]})
        kept_after_use = launch.exists()

    assert opened == [launch.as_uri()]
    assert match[2] not in opened[0]
    assert launch.parent == paths.data_dir
    if os.name == "posix":
        assert mode == 0o600
    assert f'content="0;url={server.url}"' in page
    assert exchanged.status_code == 200
    assert not kept_after_use
    assert _launch(server).path is None


def test_serve_launch_file_removed_on_stop(tmp_path: Path) -> None:
    """A token nobody used leaves no launch file once the server stops."""
    with serving(local_paths(tmp_path), on_ready=_write_launch) as (server, _):
        launch = _launch(server).path
        assert launch is not None
        existed = launch.exists()

    assert existed
    assert not launch.exists()


def test_serve_launch_file_removed_when_token_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launch file goes when the startup token expires, server still running."""
    expiring = {**TOKEN_TTL, "startup": timedelta(seconds=0.2)}
    monkeypatch.setattr(server_module, "TOKEN_TTL", expiring)
    with serving(local_paths(tmp_path), on_ready=_write_launch) as (server, _):
        launch = _launch(server).path
        assert launch is not None
        deadline = time.monotonic() + 10
        while launch.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        removed_while_serving = not launch.exists()

    assert removed_while_serving


def test_token_revoke_all_ends_agent_sessions_of_running_server(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista token --revoke-all`` ends agents' sessions, not the owner's."""
    paths = local_paths(tmp_path)
    with serving(paths) as (server, _):
        owner_token = FRAGMENT_URL.fullmatch(server.url)
        assert owner_token is not None
        main(["token", "--port", str(server.port)], paths=paths)
        agent_url = FRAGMENT_URL.fullmatch(capsys.readouterr().out.strip())
        main(["token", "--port", str(server.port)], paths=paths)
        unused_url = FRAGMENT_URL.fullmatch(capsys.readouterr().out.strip())
        assert agent_url is not None and unused_url is not None
        with httpx.Client(base_url=f"http://127.0.0.1:{server.port}") as client:
            owner = _session(client, owner_token[2])
            agent = _session(client, agent_url[2])
            before = client.get("/api/v1/session", headers=agent)

            status = main(["token", "--revoke-all"], paths=paths)
            printed = capsys.readouterr().out

            ended = client.get("/api/v1/session", headers=agent)
            kept = client.get("/api/v1/session", headers=owner)
            late = client.post("/api/v1/session", json={"token": unused_url[2]})

    assert status == 0
    assert "unieważnione niewykorzystane tokeny agentów: 1." in printed
    assert before.status_code == 200 and before.json()["kind"] == "agent"
    assert ended.status_code == 401
    assert ended.json()["code"] == "unauthorized"
    assert ended.json()["details"]["reason"] == "session_required"
    assert kept.status_code == 200 and kept.json()["kind"] == "local_owner"
    assert late.status_code == 401


def _write_launch(server: AppServer) -> None:
    """Write the launch file as ``open_in_browser`` does, opening no browser."""
    _launch(server).write(server.url)


def _launch(server: AppServer) -> LaunchFile:
    """Return the launch file of a server of local mode."""
    assert server.launch is not None
    return server.launch


def _session(client: httpx.Client, token: str) -> dict[str, str]:
    """Exchange ``token``; return the headers carrying that session."""
    exchanged = client.post("/api/v1/session", json={"token": token})
    assert exchanged.status_code == 200, exchanged.text
    cookie = exchanged.cookies[SESSION_COOKIE]
    client.cookies.clear()
    return {
        "cookie": f"{SESSION_COOKIE}={cookie}",
        CSRF_HEADER: exchanged.json()["csrf_token"],
    }


@contextmanager
def _owner(server: AppServer) -> Iterator[httpx.Client]:
    """Yield a client of the owner's session, from the server's one-time address."""
    token = server.url.partition("#token=")[2]
    with httpx.Client(base_url=f"http://127.0.0.1:{server.port}") as client:
        exchanged = client.post("/api/v1/session", json={"token": token})
        assert exchanged.status_code == 200, exchanged.text
        client.headers[CSRF_HEADER] = exchanged.json()["csrf_token"]
        yield client
