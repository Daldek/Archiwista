"""``archiwista serve`` in team mode: a real server over TLS (ADR-046, SPEC 10.2)."""

import socket
import ssl
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from archiwista.auth import LOCAL_OWNER, passwords
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, TeamSettings
from archiwista.security import HSTS
from archiwista.state import StateStore
from tests.fixtures.cli_errors import refusal
from tests.fixtures.local_server import NoSources, local_paths
from tests.fixtures.team_server import (
    ADMIN_ACCOUNT,
    ADMIN_PASSWORD,
    TeamSite,
    cheap_hasher,
    free_port,
    team_serving,
    team_site,
)

# TLS 1.2 ciphers without AEAD (CBC with HMAC), with and without forward secrecy.
CBC_CIPHERS = (
    "ECDHE-ECDSA-AES128-SHA256:ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES128-SHA256:"
    "ECDHE-RSA-AES256-SHA384:ECDHE-ECDSA-AES128-SHA:AES128-SHA256:AES128-SHA"
)


def refused_start(
    paths: AppPaths, capsys: pytest.CaptureFixture[str], host: str, port: int
) -> dict[str, Any]:
    """Run ``archiwista serve`` that must end by itself; return its error document.

    Nothing may listen on ``port`` afterwards.
    """
    statuses: list[int] = []
    argv = ["serve", "--host", host, "--port", str(port), "--no-browser"]
    thread = threading.Thread(
        target=lambda: statuses.append(main(argv, registry=NoSources(), paths=paths)),
        daemon=True,
    )

    thread.start()
    thread.join(timeout=10)

    assert not thread.is_alive()
    captured = capsys.readouterr()
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    return refusal(captured.out, captured.err, statuses[0])


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


def handshake(site: TeamSite, client: ssl.SSLContext) -> tuple[str, str] | None:
    """Return the TLS version and cipher the site agrees on, ``None`` if refused."""
    client.load_verify_locations(cafile=site.tls.ca_file)
    with socket.create_connection(("127.0.0.1", site.port), timeout=10) as raw:
        try:
            with client.wrap_socket(raw, server_hostname="localhost") as tls:
                version = tls.version()
                cipher = tls.cipher()
        except ssl.SSLError:
            return None
    assert version is not None and cipher is not None
    return version, cipher[0]


def test_serve_team_speaks_tls_12_or_newer_with_aead_ciphers_only(
    tmp_path: Path,
) -> None:
    """TLS 1.1, and TLS 1.2 without an AEAD cipher, are refused; 1.2 and 1.3 pass.

    The versions and ciphers were the libraries' defaults: Python's let TLS 1.2
    use CBC ciphers, and older Uvicorn widened them to every TLS 1.0 cipher
    (review of v0.4, D11).
    """
    paths = local_paths(tmp_path)
    site = team_site(tmp_path / "tls")
    old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with pytest.deprecated_call():
        old.minimum_version = ssl.TLSVersion.TLSv1
        old.maximum_version = ssl.TLSVersion.TLSv1_1
    old.set_ciphers("ALL:@SECLEVEL=0")
    cbc = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cbc.maximum_version = ssl.TLSVersion.TLSv1_2
    cbc.set_ciphers(CBC_CIPHERS)
    tls12 = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls12.maximum_version = ssl.TLSVersion.TLSv1_2

    with team_serving(paths, site):
        agreed = {
            "TLS 1.1": handshake(site, old),
            "TLS 1.2 CBC": handshake(site, cbc),
            "TLS 1.2": handshake(site, tls12),
            "TLS 1.3": handshake(site, ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)),
        }

    assert agreed["TLS 1.1"] is None
    assert agreed["TLS 1.2 CBC"] is None
    assert agreed["TLS 1.2"] is not None and agreed["TLS 1.3"] is not None
    version, cipher = agreed["TLS 1.2"]
    assert version == "TLSv1.2" and cipher.startswith("ECDHE-")
    assert "-GCM-" in cipher or "CHACHA20" in cipher
    assert agreed["TLS 1.3"][0] == "TLSv1.3"


def test_serve_team_without_tls_or_proxy_exits_before_listening(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Team mode without TLS files and trusted proxies is refused: exit 2, no port."""
    paths = local_paths(tmp_path)
    team = TeamSettings(enabled=True, origin="https://archiwista.firma.local")
    ConfigStore(paths.config_file).save(AppSettings(team=team))

    document = refused_start(paths, capsys, "0.0.0.0", free_port())

    assert (document["code"], document["details"]["reason"]) == (
        "validation_error",
        "tls_required",
    )
    assert document["hint"]
    assert not paths.data_dir.exists()


@pytest.mark.parametrize(
    "administrator", ["none", "without a password", "expired", "disabled"]
)
def test_serve_team_needs_an_administrator_who_can_sign_in(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    administrator: str,
) -> None:
    """No administrator, or one who cannot sign in: exit 2 before the port opens."""
    monkeypatch.setattr(passwords, "HASHER", cheap_hasher())
    paths = local_paths(tmp_path)
    site = team_site(tmp_path / "tls")
    ConfigStore(paths.config_file).save(site.settings())
    state = StateStore(paths.state_file)
    if administrator != "none":
        state.add_user(ADMIN_ACCOUNT, roles=["admin"], actor=LOCAL_OWNER)
    if administrator in ("expired", "disabled"):
        passwords.set_password(
            state,
            ADMIN_ACCOUNT,
            ADMIN_PASSWORD,
            temporary=administrator == "expired",
            actor=LOCAL_OWNER,
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    if administrator == "disabled":
        state.update_user(ADMIN_ACCOUNT, disabled=True, actor=LOCAL_OWNER)

    document = refused_start(paths, capsys, "127.0.0.1", site.port)

    assert (document["code"], document["details"]["reason"]) == (
        "validation_error",
        "team_no_admin",
    )
    assert "archiwista users add ID --role admin" in document["hint"]
    assert "archiwista users password ID" in document["hint"]


def test_serve_team_starts_through_the_proxy_without_a_password(
    tmp_path: Path,
) -> None:
    """With proxy_user_header an enabled administrator needs no password to start."""
    paths = local_paths(tmp_path)
    site = team_site(tmp_path / "tls")
    StateStore(paths.state_file).add_user(
        ADMIN_ACCOUNT, roles=["admin"], actor=LOCAL_OWNER
    )
    trust = ssl.create_default_context(cafile=site.tls.ca_file)
    proxy = {"trusted_proxies": ["127.0.0.1"], "proxy_user_header": "X-Remote-User"}

    with (
        team_serving(paths, site, admin=False, **proxy) as (server, _),
        httpx.Client(base_url=site.origin, verify=trust) as client,
    ):
        page = client.get("/")

    assert page.status_code == 200
    assert server.url == site.origin
