"""Team mode in tests: a test certificate authority, a team server, clients over https.

``team_site`` issues a server certificate of a test authority (``trustme``) and
reserves a free port before the settings exist, so that the team's origin is
``https://localhost:<port>``. ``team_serving`` runs ``serve_main`` in team mode
with TLS in the server there; ``team_client`` drives an application in a test
client from a given peer address, over https by default.
"""

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import trustme
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archiwista.config import AppPaths, AppSettings, ConfigStore, TeamSettings
from archiwista.server import AppServer
from tests.fixtures.local_server import serving

# The names the server certificate holds: a team server in the tests is opened at
# https://localhost:<port> and also reached at its loopback address.
SERVER_NAMES = ("localhost", "127.0.0.1")
# The port of a test client's peer address (any; the server reads the address).
PEER_PORT = 50_000


@dataclass(frozen=True)
class TeamTls:
    """TLS files of a team server, issued by a test certificate authority.

    Parameters
    ----------
    ca : trustme.CA
        The authority; ``ca.configure_trust`` makes a client context trust it.
    ca_file : Path
        The authority's certificate (PEM), for clients.
    cert : Path
        The server's certificate chain (PEM), for ``tls_cert``.
    key : Path
        The server's private key (PEM, mode ``0600``), for ``tls_key``.
    """

    ca: trustme.CA
    ca_file: Path
    cert: Path
    key: Path


def team_tls(directory: Path) -> TeamTls:
    """Issue a server certificate for ``SERVER_NAMES`` into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    ca = trustme.CA()
    issued = ca.issue_cert(*SERVER_NAMES)
    ca_file = directory / "ca.pem"
    cert = directory / "fullchain.pem"
    key = directory / "privkey.pem"
    ca.cert_pem.write_to_path(str(ca_file))
    for number, blob in enumerate(issued.cert_chain_pems):
        blob.write_to_path(str(cert), append=number > 0)
    issued.private_key_pem.write_to_path(str(key))
    key.chmod(0o600)
    return TeamTls(ca=ca, ca_file=ca_file, cert=cert, key=key)


def free_port() -> int:
    """Return a loopback port that nothing listens on now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


@dataclass(frozen=True)
class TeamSite:
    """Where a team server of a test listens: its TLS files and port.

    Parameters
    ----------
    tls : TeamTls
        The server's certificate, key and the authority that issued them.
    port : int
        The port, reserved before the settings name it in ``origin``.
    """

    tls: TeamTls
    port: int

    @property
    def origin(self) -> str:
        """The address people open: ``https://localhost:<port>``."""
        return f"https://localhost:{self.port}"

    def settings(self, **team: object) -> AppSettings:
        """Return settings of team mode with TLS in the server at the origin.

        ``team`` adds or replaces values of the table ``[team]``.
        """
        table: dict[str, object] = {
            "enabled": True,
            "origin": self.origin,
            "tls_cert": self.tls.cert,
            "tls_key": self.tls.key,
            **team,
        }
        return AppSettings(port=self.port, team=TeamSettings.model_validate(table))


def team_site(directory: Path) -> TeamSite:
    """Issue the TLS files into ``directory`` and reserve a free port."""
    return TeamSite(tls=team_tls(directory), port=free_port())


@contextmanager
def team_serving(paths: AppPaths, site: TeamSite) -> Iterator[tuple[AppServer, str]]:
    """Run ``serve_main`` in team mode with TLS in the server on the site's port.

    Yields the server and what it printed; the server stops when the block
    ends and must then exit with status 0.
    """
    ConfigStore(paths.config_file).save(site.settings())
    with serving(paths, port=site.port) as served:
        yield served


def team_client(app: FastAPI, *, peer: str, base_url: str | None = None) -> TestClient:
    """Return a test client of ``app`` whose requests come from ``peer``.

    The requests go to the application's origin (``https`` in team mode)
    unless ``base_url`` names another address (for example ``http://``).
    """
    origin: str = app.state.transport.origin
    return TestClient(app, base_url=base_url or origin, client=(peer, PEER_PORT))
