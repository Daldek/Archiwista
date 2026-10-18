"""``archiwista serve`` and ``archiwista token`` with a real server in a thread."""

import asyncio
import json
import re
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from archiwista.cli import main
from archiwista.server import bind_loopback
from tests.fixtures.local_server import NoSources, local_paths, serving

FRAGMENT_URL = re.compile(r"http://127\.0\.0\.1:(\d+)/#token=([A-Za-z0-9_-]+)")


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


def test_serve_prints_fragment_url(tmp_path: Path) -> None:
    """The printed address carries a one-time token the real server exchanges."""
    with serving(local_paths(tmp_path)) as (server, output):
        match = FRAGMENT_URL.search(output)
        assert match is not None
        port, token = int(match[1]), match[2]
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            exchanged = client.post("/api/v1/session", json={"token": token})
            state = client.get("/api/v1/session")
            replayed = client.post("/api/v1/session", json={"token": token})
            rebound = client.get("/api/v1/session", headers={"host": "evil.example"})

    assert port == server.port
    assert exchanged.status_code == 200
    assert state.json()["actor"] == "local"
    assert replayed.status_code == 401
    assert rebound.status_code == 400


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

    assert status == 1
    assert f"Nie można nasłuchiwać na 127.0.0.1:{port}" in capsys.readouterr().err


def test_serve_connections_send_without_nagle_delay() -> None:
    """Connections of the server's socket send at once (``TCP_NODELAY``).

    asyncio disables Nagle's algorithm only on connections accepted by an
    ``IPPROTO_TCP`` socket. Without it every response written in parts on a
    kept-alive connection waited for the client's delayed acknowledgement:
    about 40 ms added to each request of the browser.
    """

    async def accepted_nodelay() -> int:
        listening = bind_loopback(0)
        loop = asyncio.get_running_loop()
        accepted: asyncio.Future[int] = loop.create_future()

        class Probe(asyncio.Protocol):
            def connection_made(self, transport: asyncio.BaseTransport) -> None:
                raw = transport.get_extra_info("socket")
                accepted.set_result(
                    raw.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
                )
                transport.close()

        async with await loop.create_server(Probe, sock=listening):
            _, writer = await asyncio.open_connection(*listening.getsockname())
            try:
                return await asyncio.wait_for(accepted, timeout=10)
            finally:
                writer.close()
                await writer.wait_closed()

    # Its own thread: the session's Playwright may run an event loop here.
    with ThreadPoolExecutor(1) as pool:
        nodelay = pool.submit(asyncio.run, accepted_nodelay()).result()

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
