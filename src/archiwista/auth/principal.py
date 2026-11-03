"""Principals: who acts in a session, a service call or a background job.

Every service and query takes a ``Principal`` (A-ADR-029), so that
permission checks can be added without rewriting the layers. Local mode
knows one person, the owner of the computer: the principal ``local`` with
the roles ``admin`` and ``store_writer`` and no groups. A session opened with
the startup address belongs to the owner (``local_owner``); one opened with a
token from ``archiwista token`` or ``POST /api/v1/session/tokens`` is an
``agent`` acting for the principal that minted the token. Scheduled scans
run as the ``scheduler``, for the owner. A session keeps only who acts and
how (id and kind): roles and groups are read again for every request.
"""

from dataclasses import dataclass
from typing import Literal

type PrincipalKind = Literal["local_owner", "user", "agent", "scheduler"]

LOCAL_PRINCIPAL_ID = "local"
LOCAL_ROLES = frozenset({"admin", "store_writer"})


@dataclass(frozen=True, slots=True)
class Principal:
    """Who acts.

    Parameters
    ----------
    id : str
        Stable identity, recorded as the ``actor`` of jobs; ``local`` in
        local mode.
    kind : {"local_owner", "user", "agent", "scheduler"}
        The owner of a local installation, a signed-in person (team mode),
        an agent acting with a token that a principal minted for it, or the
        scan scheduler acting for the owner.
    roles : frozenset[str]
        Granted roles; local mode grants ``admin`` and ``store_writer``.
    groups : frozenset[str]
        Groups of people the principal belongs to; none in local mode.
    session : str or None, optional
        Label of the session the principal acts in, recorded with its jobs
        and permission changes; ``None`` at the terminal and for the
        scheduler.
    client : str or None, optional
        Address of the client of the request (the peer, or behind trusted
        proxies the client they name, ADR-046); ``None`` at the terminal and
        for the scheduler.
    """

    id: str
    kind: PrincipalKind
    roles: frozenset[str]
    groups: frozenset[str]
    session: str | None = None
    client: str | None = None


LOCAL_OWNER = Principal(
    id=LOCAL_PRINCIPAL_ID, kind="local_owner", roles=LOCAL_ROLES, groups=frozenset()
)
SCHEDULER = Principal(
    id=LOCAL_PRINCIPAL_ID, kind="scheduler", roles=LOCAL_ROLES, groups=frozenset()
)
