"""Principals: who acts in a session, a service call or a background job.

Every service and query takes a ``Principal`` (A-ADR-029), so that
permission checks can be added without rewriting the layers. Local mode
knows one person, the owner of the computer: the principal ``local`` with
the roles ``admin`` and ``store_writer`` and no groups. A session opened with
the startup address belongs to the owner (``local_owner``); one opened with a
token from ``archiwista token`` or ``POST /api/v1/session/tokens`` is an
``agent`` acting for the principal that minted the token.
"""

from dataclasses import dataclass
from typing import Literal

type PrincipalKind = Literal["local_owner", "user", "agent"]

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
    kind : {"local_owner", "user", "agent"}
        The owner of a local installation, a signed-in person (team mode),
        or an agent acting with a token that a principal minted for it.
    roles : frozenset[str]
        Granted roles; local mode grants ``admin`` and ``store_writer``.
    groups : frozenset[str]
        Groups of people the principal belongs to; none in local mode.
    """

    id: str
    kind: PrincipalKind
    roles: frozenset[str]
    groups: frozenset[str]


LOCAL_OWNER = Principal(
    id=LOCAL_PRINCIPAL_ID, kind="local_owner", roles=LOCAL_ROLES, groups=frozenset()
)
