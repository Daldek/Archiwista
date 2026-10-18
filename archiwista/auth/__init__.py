"""Who acts and which projects they see.

``Principal`` and ``ProjectVisibility`` are plain values that every layer
passes along; the decisions themselves (``Authorizer``: ``can``,
``require``, ``visible_projects``) live in ``archiwista.auth.authorize``,
which reads the state database.
"""

from archiwista.auth.principal import (
    LOCAL_OWNER,
    LOCAL_PRINCIPAL_ID,
    LOCAL_ROLES,
    Principal,
    PrincipalKind,
)
from archiwista.auth.visibility import ALL_PROJECTS, ProjectVisibility, access_key

__all__ = [
    "ALL_PROJECTS",
    "LOCAL_OWNER",
    "LOCAL_PRINCIPAL_ID",
    "LOCAL_ROLES",
    "Principal",
    "PrincipalKind",
    "ProjectVisibility",
    "access_key",
]
