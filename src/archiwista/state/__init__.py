"""Local state database: accounts, groups, roles, project access, permission log.

Unlike the index, this state cannot be rebuilt from files (A-ADR-029, SPEC
4.3): it changes by migrations and is backed up with ``archiwista state
export`` (``archiwista-state/1``).
"""

from archiwista.state.export import (
    STATE_DOCUMENT_SCHEMA,
    StateDocument,
    dump_state,
    export_state,
    import_state,
    parse_state,
)
from archiwista.state.schema import (
    MIGRATIONS,
    STATE_SCHEMA_VERSION,
    Migration,
    StateSchemaState,
    initialize,
)
from archiwista.state.store import (
    ID_PATTERN,
    NAME_MAX_LENGTH,
    RESERVED_USER_IDS,
    ROLES,
    VISIBILITIES,
    ChangeAction,
    GroupRecord,
    PermissionChange,
    ProjectAccessRecord,
    Role,
    StateSnapshot,
    StateStore,
    UserRecord,
    Visibility,
)

__all__ = [
    "ID_PATTERN",
    "MIGRATIONS",
    "NAME_MAX_LENGTH",
    "RESERVED_USER_IDS",
    "ROLES",
    "STATE_DOCUMENT_SCHEMA",
    "STATE_SCHEMA_VERSION",
    "VISIBILITIES",
    "ChangeAction",
    "GroupRecord",
    "Migration",
    "PermissionChange",
    "ProjectAccessRecord",
    "Role",
    "StateDocument",
    "StateSchemaState",
    "StateSnapshot",
    "StateStore",
    "UserRecord",
    "Visibility",
    "dump_state",
    "export_state",
    "import_state",
    "initialize",
    "parse_state",
]
