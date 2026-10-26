"""Team mode in tests: a test certificate authority, a team server, clients over https.

``team_site`` issues a server certificate of a test authority (``trustme``) and
reserves a free port before the settings exist, so that the team's origin is
``https://localhost:<port>``. ``team_serving`` runs ``serve_main`` in team mode
with TLS in the server there; ``team_client`` drives an application in a test
client from a given peer address, over https by default. ``save_team`` writes
the settings of a team that no server serves, for ``running_api``, and
``cheap_hasher`` is the Argon2id a test puts into ``passwords.HASHER``.
"""

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import argon2
import trustme
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archiwista.auth import LOCAL_OWNER, passwords
from archiwista.config import AppPaths, AppSettings, ConfigStore, TeamSettings
from archiwista.server import AppServer
from archiwista.state import StateStore
from tests.fixtures.local_server import serving

# The names the server certificate holds: a team server in the tests is opened at
# https://localhost:<port> and also reached at its loopback address.
SERVER_NAMES = ("localhost", "127.0.0.1")
# The port of a test client's peer address (any; the server reads the address).
PEER_PORT = 50_000
# The administrator of a team server of the tests: team mode starts only with an
# administrator who can sign in (ADR-046 decision 2).
ADMIN_ACCOUNT = "anna"
ADMIN_PASSWORD = "kajak-po-Rabie-o-swicie"
# A team that no server of the tests serves: the transport rules never open its
# TLS files (``serve_main`` would), so they are named only.
TEAM_ORIGIN = "https://archiwista.firma.local"
NAMED_TLS = {
    "tls_cert": "/etc/archiwista/tls/fullchain.pem",
    "tls_key": "/etc/archiwista/tls/privkey.pem",
}
# A person's computer on the team's network: the peer of ``running_api``'s client.
PERSON_PEER = "10.0.0.5"


def cheap_hasher() -> argon2.PasswordHasher:
    """Return Argon2id at the lowest cost argon2-cffi allows.

    Tests check what Archiwista does with hashes, not what they cost, so they
    replace ``archiwista.auth.passwords.HASHER`` with it; the defaults of the
    code stay as they are (plan v0.4, rule 4).
    """
    return argon2.PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def save_team(paths: AppPaths, **team: object) -> AppSettings:
    """Write settings of team mode at ``TEAM_ORIGIN`` with TLS in the server.

    ``team`` adds or replaces values of the table ``[team]``. ``running_api``
    over these paths then serves team mode to a client at ``PERSON_PEER``.
    """
    table = {"enabled": True, "origin": TEAM_ORIGIN, **NAMED_TLS, **team}
    settings = AppSettings(team=TeamSettings.model_validate(table))
    ConfigStore(paths.config_file).save(settings)
    return settings


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


def add_admin(paths: AppPaths, account: str = ADMIN_ACCOUNT) -> None:
    """Create an administrator whose password is ``ADMIN_PASSWORD``."""
    state = StateStore(paths.state_file)
    state.add_user(account, roles=["admin"], actor=LOCAL_OWNER)
    passwords.set_password(
        state, account, ADMIN_PASSWORD, temporary=False, actor=LOCAL_OWNER
    )


@contextmanager
def team_serving(
    paths: AppPaths, site: TeamSite, *, admin: bool = True, **team: object
) -> Iterator[tuple[AppServer, str]]:
    """Run ``serve_main`` in team mode with TLS in the server on the site's port.

    ``team`` adds or replaces values of the table ``[team]``; with ``admin``
    the state database first gets the administrator ``ADMIN_ACCOUNT`` with a
    password, without which team mode does not start. Yields the server and
    what it printed; the server stops when the block ends and must then exit
    with status 0.
    """
    ConfigStore(paths.config_file).save(site.settings(**team))
    if admin:
        add_admin(paths)
    with serving(paths, port=site.port) as served:
        yield served


def team_client(app: FastAPI, *, peer: str, base_url: str | None = None) -> TestClient:
    """Return a test client of ``app`` whose requests come from ``peer``.

    The requests go to the application's origin (``https`` in team mode)
    unless ``base_url`` names another address (for example ``http://``).
    """
    origin: str = app.state.transport.origin
    return TestClient(app, base_url=base_url or origin, client=(peer, PEER_PORT))
