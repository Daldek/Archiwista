"""Team mode in tests: a test certificate authority and TLS files of the server."""

from dataclasses import dataclass
from pathlib import Path

import trustme

# The names the server certificate holds: a team server in the tests is opened at
# https://localhost:<port> and also reached at its loopback address.
SERVER_NAMES = ("localhost", "127.0.0.1")


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
