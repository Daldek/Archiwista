"""``archiwista serve`` in team mode: a real server over TLS (ADR-046, SPEC 10.2)."""

import socket
import ssl
import threading
from pathlib import Path

import httpx
import pytest

from archiwista.cli import main
from archiwista.config import AppSettings, ConfigStore, TeamSettings
from archiwista.security import HSTS
from tests.fixtures.cli_errors import refusal
from tests.fixtures.local_server import NoSources, local_paths
from tests.fixtures.team_server import free_port, team_serving, team_site


def test_serve_team_answers_its_origin_over_tls_only(tmp_path: Path) -> None:
    """The origin answers over TLS with HSTS; plain HTTP to the port gets nothing."""
    paths = local_paths(tmp_path)
    site = team_site(tmp_path / "tls")
    trust = ssl.create_default_context(cafile=site.tls.ca_file)
    with team_serving(paths, site) as (server, output):
        with httpx.Client(base_url=site.origin, verify=trust) as client:
            page = client.get("/")
            api = client.get("/api/v1/health")
        with (
            httpx.Client(base_url=f"http://localhost:{site.port}") as plain,
            pytest.raises(httpx.TransportError),
        ):
            plain.get("/")
        launch_files = sorted(paths.data_dir.glob("open-*.html"))

    assert page.status_code == 200
    assert page.headers["strict-transport-security"] == HSTS
    assert api.status_code == 401
    assert api.headers["strict-transport-security"] == HSTS
    assert site.origin in output
    assert "token" not in output
    assert server.url == site.origin
    assert server.launch is None
    assert launch_files == []


def test_serve_team_without_tls_or_proxy_exits_before_listening(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Team mode without TLS files and trusted proxies is refused: exit 2, no port."""
    paths = local_paths(tmp_path)
    team = TeamSettings(enabled=True, origin="https://archiwista.firma.local")
    ConfigStore(paths.config_file).save(AppSettings(team=team))
    port = free_port()
    statuses: list[int] = []
    argv = ["serve", "--host", "0.0.0.0", "--port", str(port), "--no-browser"]
    thread = threading.Thread(
        target=lambda: statuses.append(main(argv, registry=NoSources(), paths=paths)),
        daemon=True,
    )

    thread.start()
    thread.join(timeout=10)

    assert not thread.is_alive()
    captured = capsys.readouterr()
    document = refusal(captured.out, captured.err, statuses[0])
    assert (document["code"], document["details"]["reason"]) == (
        "validation_error",
        "tls_required",
    )
    assert document["hint"]
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    assert not paths.data_dir.exists()
