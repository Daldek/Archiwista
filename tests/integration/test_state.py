"""The state database: separate from the index, migrated, backed up (A-ADR-029).

Accounts, groups, project access, passwords and the action log cannot be
rebuilt from files, so an index rebuild must leave them alone, an older
database must migrate with its data (the permission log of version 2 becomes
the action log), a newer one must be refused untouched, the action log must
refuse changes, and ``archiwista state export`` → ``state import`` into an
empty database must give back the same state (``archiwista-state/2``; a
``/1`` document still imports).
"""

import hashlib
import json
import os
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER, SCHEDULER, access_key
from archiwista.auth.authorize import Authorizer
from archiwista.cli import main
from archiwista.config import AppSettings
from archiwista.errors import StateError
from archiwista.index import IndexQueries, IndexWriter, ManifestStamp, initialize
from archiwista.sources import ProjectInfo
from archiwista.state import (
    MIGRATIONS,
    STATE_SCHEMA_VERSION,
    StateStore,
    dump_state,
    export_state,
    import_state,
)
from archiwista.state import initialize as initialize_state
from tests.fixtures.index_data import PRODUCER, ROOT, STORE
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import (
    ADMIN,
    VISIBILITY_VALUES,
    WHO,
    WRITER,
    Who,
    add_people,
    log_entries,
    principal,
    share,
)

DIRECTORIES = {
    visibility: f"/projekty/{visibility}" for visibility in VISIBILITY_VALUES
}
DEFAULTS = AppSettings()
OWNER_AND_OTHER: tuple[Who, ...] = ("owner", "other")
# A private project of the owner: she sees it, another person does not.
EXPECTED_AFTER_REBUILD: tuple[tuple[Who, list[str]], ...] = (
    ("owner", ["Tajny"]),
    ("other", []),
)
# A stand-in PHC string: the state database keeps a hash without reading it.
HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29sdHNvbHQ$aGFzaGhhc2hoYXNo"
AT = "2026-10-20T08:00:00Z"


def _shared_state(path: Path) -> StateStore:
    """Four people, a group, one project per visibility, a password and the log."""
    state = StateStore(path)
    add_people(state)
    for visibility, directory in DIRECTORIES.items():
        share(state, access_key(directory), visibility)
    state.update_user("igor", roles=WRITER, actor=LOCAL_OWNER)
    state.set_password(ADMIN, HASH, expires_at=None, actor=LOCAL_OWNER)
    state.record(
        None,
        "user.password_reset",
        ADMIN,
        outcome="denied",
        client="10.0.0.7",
        details={"reason": "test"},
    )
    return state


def _matrix(state: StateStore) -> dict[str, frozenset[str]]:
    """Who sees which project, as decided from this state."""
    authorizer = Authorizer(state, lambda: DEFAULTS)
    return {
        who: frozenset(
            visibility
            for visibility, directory in DIRECTORIES.items()
            if authorizer.visible_projects(principal(state, who)).sees(
                access_key(directory)
            )
        )
        for who in WHO
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup(**parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Return an ``archiwista-state/2`` document; omitted parts are empty."""
    names = ("users", "groups", "projects", "passwords", "preferences", "actions")
    unknown = set(parts) - set(names)
    assert not unknown, unknown
    return {
        "schema": "archiwista-state/2",
        "exported_at": AT,
        **{name: parts.get(name, []) for name in names},
    }


def _user(user_id: str, *, revoked: str | None = None) -> dict[str, Any]:
    return {
        "id": user_id,
        "name": user_id.capitalize(),
        "roles": [],
        "disabled": False,
        "created_at": AT,
        "updated_at": AT,
        "sessions_revoked_at": revoked,
    }


def _password(user_id: str, *, temporary: bool, expires: str | None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "hash": HASH,
        "set_at": AT,
        "set_by": "local",
        "temporary": temporary,
        "expires_at": expires,
    }


def _action(entry_id: int, at: str) -> dict[str, Any]:
    """Return a refused anonymous entry, as a failed sign-in writes one."""
    return {
        "id": entry_id,
        "at": at,
        "actor": "-",
        "actor_kind": "anonymous",
        "session": None,
        "client": "10.0.0.7",
        "action": "user.password_reset",
        "target": "jan",
        "outcome": "denied",
        "before": None,
        "after": None,
        "details": {"reason": "test"},
    }


def test_index_rebuild_leaves_state_untouched(tmp_path: Path) -> None:
    """Rebuilding the index changes no byte of the state; access still applies."""
    # Arrange
    paths = local_paths(tmp_path)
    state = _shared_state(paths.state_file)
    project = ProjectInfo(PRODUCER, ROOT, Path(DIRECTORIES["private"]), "Tajny")
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {PRODUCER: ROOT}})
        writer.write_project(project, store=STORE, stamp=ManifestStamp(1, 1))
    before = (_digest(paths.state_file), state.snapshot())
    with sqlite3.connect(paths.index_file) as connection:
        connection.execute("PRAGMA user_version = 1")
    connection.close()

    # Act
    rebuilt = initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {PRODUCER: ROOT}})
        writer.write_project(project, store=STORE, stamp=ManifestStamp(1, 1))

    # Assert
    assert rebuilt == "rebuilt"
    assert (_digest(paths.state_file), state.snapshot()) == before
    authorizer = Authorizer(state, lambda: DEFAULTS)
    with IndexQueries(paths.index_file) as queries:
        for who, names in EXPECTED_AFTER_REBUILD:
            visible = authorizer.visible_projects(principal(state, who))
            listed = [ref.name for ref in queries.projects(visible=visible)]
            assert listed == names


def test_project_through_symlink_keeps_its_access(tmp_path: Path) -> None:
    """The access key is the real directory: another path to it shares the entry."""
    # Arrange
    real = tmp_path / "dane" / "projekty"
    (real / "raba").mkdir(parents=True)
    alias = tmp_path / "projekty"
    os.symlink(real, alias, target_is_directory=True)
    state = StateStore(tmp_path / "state.sqlite")
    add_people(state)
    share(state, access_key(real / "raba"), "private")
    authorizer = Authorizer(state, lambda: DEFAULTS)

    # Act
    index = tmp_path / "index.sqlite"
    with IndexWriter(index) as writer, IndexQueries(index) as queries:
        writer.sync_stores({STORE: {PRODUCER: ROOT}})
        info = ProjectInfo(PRODUCER, ROOT, alias / "raba", "Raba")
        writer.write_project(info, store=STORE, stamp=ManifestStamp(1, 1))
        seen = {
            who: [
                ref.name
                for ref in queries.projects(
                    visible=authorizer.visible_projects(principal(state, who))
                )
            ]
            for who in OWNER_AND_OTHER
        }

    # Assert
    assert seen == {"owner": ["Raba"], "other": []}


def test_state_migrates_from_older_user_version(tmp_path: Path) -> None:
    """Pending migrations run in order and keep data; a failing one changes nothing."""
    # Arrange
    path = tmp_path / "state.sqlite"
    _shared_state(path)

    def add_email(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE users ADD COLUMN email TEXT")

    def broken(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        raise sqlite3.OperationalError("migration failed")

    # Act
    with pytest.raises(sqlite3.OperationalError):
        initialize_state(path, migrations=(*MIGRATIONS, broken))
    untouched = _columns(path)
    migrated = initialize_state(path, migrations=(*MIGRATIONS, add_email))

    # Assert
    assert "phone" not in untouched
    assert migrated == "migrated"
    with sqlite3.connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        users = [
            row[0] for row in connection.execute("SELECT id FROM users ORDER BY id")
        ]
    connection.close()
    assert version == STATE_SCHEMA_VERSION + 1
    assert "email" in _columns(path)
    assert users == ["ada", "igor", "lena", "olga"]


def test_newer_state_database_is_refused(tmp_path: Path) -> None:
    """A database from a newer Archiwista is neither read nor changed."""
    # Arrange
    path = tmp_path / "state.sqlite"
    _shared_state(path)
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {STATE_SCHEMA_VERSION + 1}")
    connection.close()
    before = _digest(path)

    # Act / Assert
    with pytest.raises(StateError):
        StateStore(path)
    assert _digest(path) == before


def test_version_2_log_becomes_ok_entries_of_the_action_log(tmp_path: Path) -> None:
    """Migrating a version 2 database keeps every permission entry, now ``ok``."""
    # Arrange
    path = tmp_path / "state.sqlite"
    initialize_state(path, migrations=MIGRATIONS[:2])
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO users (id, name, disabled, created_at, updated_at)"
            " VALUES ('ada', 'Ada', 0, ?, ?)",
            (AT, AT),
        )
        connection.executemany(
            "INSERT INTO permission_log"
            " (id, at, actor, actor_kind, session, action, target, before, after)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (4, AT, "local", None, None, "user.add", "ada", None, '{"id": "ada"}'),
                (9, AT, "ada", "agent", "s-2", "group.remove", "hydro", "{}", None),
            ],
        )
    connection.close()

    # Act
    state = StateStore(path)

    # Assert
    assert [
        (
            entry.id,
            entry.actor,
            entry.actor_kind,
            entry.session,
            entry.client,
            entry.action,
            entry.target,
            entry.outcome,
            entry.before,
            entry.after,
            entry.details,
        )
        for entry in log_entries(state)
    ] == [
        (
            4,
            "local",
            None,
            None,
            None,
            "user.add",
            "ada",
            "ok",
            None,
            {"id": "ada"},
            None,
        ),
        (9, "ada", "agent", "s-2", None, "group.remove", "hydro", "ok", {}, None, None),
    ]
    ada = state.user("ada")
    assert ada is not None
    assert (ada.password, ada.sessions_revoked_at) == ("none", None)
    with sqlite3.connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master")
        }
    connection.close()
    assert version == STATE_SCHEMA_VERSION == 3
    assert "permission_log" not in tables


def test_action_log_refuses_to_change_an_entry(tmp_path: Path) -> None:
    """The trigger stops an UPDATE of the log, even one written by hand."""
    # Arrange
    path = tmp_path / "state.sqlite"
    state = StateStore(path)
    entry = state.record(
        None, "user.password_reset", "ada", outcome="failed", client="10.0.0.7"
    )
    connection = sqlite3.connect(path, isolation_level=None)

    # Act
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE action_log SET outcome = 'ok' WHERE id = ?", (1,))
    connection.close()

    # Assert
    assert (entry.actor, entry.actor_kind, entry.client) == (
        "-",
        "anonymous",
        "10.0.0.7",
    )
    assert state.actions().entries == (entry,)


def test_pruning_deletes_only_entries_older_than_the_limit(tmp_path: Path) -> None:
    """Entries before the limit go and the pruning is logged; later ones stay."""
    # Arrange
    state = StateStore(tmp_path / "state.sqlite")
    times = ["2026-01-31T23:59:59Z", "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"]
    import_state(
        state,
        json.dumps(
            _backup(actions=[_action(i, at) for i, at in enumerate(times, start=1)])
        ),
    )
    limit = datetime(2026, 2, 1, tzinfo=UTC)

    # Act
    deleted = state.prune_actions(limit, actor=SCHEDULER)
    again = state.prune_actions(limit, actor=SCHEDULER)

    # Assert: the second pruning deleted nothing and logged nothing.
    assert (deleted, again) == (1, 0)
    entries = log_entries(state)
    assert [entry.id for entry in entries] == [2, 3, 4]
    pruned = entries[-1]
    assert (pruned.actor, pruned.actor_kind, pruned.session, pruned.client) == (
        "local",
        "scheduler",
        None,
        None,
    )
    assert (pruned.action, pruned.target, pruned.outcome) == ("log.prune", "log", "ok")
    assert pruned.details == {"before": "2026-02-01T00:00:00+00:00", "count": 1}


def test_export_import_gives_the_same_matrix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``state export`` then ``state import`` into an empty database restores all."""
    # Arrange
    source = local_paths(tmp_path / "a")
    target = local_paths(tmp_path / "b")
    original = _shared_state(source.state_file)
    backup = tmp_path / "kopia" / "stan.json"

    # Act
    exported = main(["state", "export", "--output", str(backup)], paths=source)
    imported = main(["state", "import", str(backup)], paths=target)
    capsys.readouterr()
    again = main(["state", "export"], paths=target)
    copy = json.loads(capsys.readouterr().out)

    # Assert
    assert (exported, imported, again) == (0, 0, 0)
    restored = StateStore(target.state_file)
    assert restored.snapshot() == original.snapshot()
    assert _matrix(restored) == _matrix(original)
    document = json.loads(backup.read_text(encoding="utf-8"))
    assert document["schema"] == "archiwista-state/2"
    assert [password["hash"] for password in document["passwords"]] == [HASH]
    assert {key: value for key, value in copy.items() if key != "exported_at"} == {
        key: value for key, value in document.items() if key != "exported_at"
    }


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")
def test_export_file_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    """The backup holds password hashes: mode 0600, also over a wider old file."""
    # Arrange
    paths = local_paths(tmp_path)
    _shared_state(paths.state_file)
    backup = tmp_path / "stan.json"
    backup.write_text("{}", encoding="utf-8")
    backup.chmod(0o644)

    # Act
    status = main(["state", "export", "--output", str(backup)], paths=paths)

    # Assert
    assert status == 0
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert json.loads(backup.read_text(encoding="utf-8"))["passwords"]


def test_backup_round_trips_passwords_preferences_and_actions(tmp_path: Path) -> None:
    """Restoring a document and exporting it again gives the same document."""
    # Arrange
    state = StateStore(tmp_path / "state.sqlite")
    document = _backup(
        users=[
            _user("ada", revoked="2026-10-20T09:00:00.123456Z"),
            _user("jan"),
            _user("ola"),
        ],
        passwords=[
            _password("ada", temporary=False, expires=None),
            _password("jan", temporary=True, expires="2100-01-01T00:00:00Z"),
            _password("ola", temporary=True, expires="2020-01-01T00:00:00Z"),
        ],
        preferences=[
            {"principal": "jan", "document": {"basemap": "osm"}, "updated_at": AT},
            {"principal": "local", "document": {"basemap": None}, "updated_at": AT},
        ],
        actions=[
            _action(3, AT),
            {
                **_action(8, AT),
                "actor": "ada",
                "actor_kind": "user",
                "session": "s-1",
                "client": "10.0.0.8",
                "action": "user.add",
                "target": "jan",
                "outcome": "ok",
                "after": {"id": "jan"},
                "details": None,
            },
        ],
    )

    # Act
    restored = import_state(state, json.dumps(document))
    again = json.loads(dump_state(export_state(state)))
    state.remove_user("jan", actor=LOCAL_OWNER)

    # Assert
    assert {key: value for key, value in again.items() if key != "exported_at"} == {
        key: value for key, value in document.items() if key != "exported_at"
    }
    assert [(user.id, user.password) for user in restored.users] == [
        ("ada", "set"),
        ("jan", "temporary"),
        ("ola", "expired"),
    ]
    after = state.snapshot()
    assert [preference.principal for preference in after.preferences] == ["local"]
    assert [password.user_id for password in after.passwords] == ["ada", "ola"]


def test_backup_of_version_1_imports_its_log_as_ok_entries(tmp_path: Path) -> None:
    """An ``archiwista-state/1`` document restores; its log joins the action log."""
    # Arrange
    state = StateStore(tmp_path / "state.sqlite")
    user = _user("ada")
    del user["sessions_revoked_at"]
    document = {
        "schema": "archiwista-state/1",
        "exported_at": AT,
        "users": [user],
        "groups": [],
        "projects": [],
        "permission_log": [
            {
                "id": 1,
                "at": AT,
                "actor": "local",
                "action": "user.add",
                "target": "ada",
                "before": None,
                "after": {"id": "ada"},
            },
            {
                "id": 2,
                "at": AT,
                "actor": "ada",
                "actor_kind": "user",
                "session": "s-1",
                "action": "user.update",
                "target": "ada",
                "before": {"name": "A"},
                "after": {"name": "Ada"},
            },
        ],
    }

    # Act
    restored = import_state(state, json.dumps(document))

    # Assert
    assert [
        (entry.id, entry.actor, entry.actor_kind, entry.session, entry.client)
        for entry in restored.actions
    ] == [(1, "local", None, None, None), (2, "ada", "user", "s-1", None)]
    assert {entry.outcome for entry in restored.actions} == {"ok"}
    assert (restored.passwords, restored.preferences) == ((), ())
    assert [(user.id, user.password) for user in restored.users] == [("ada", "none")]


def test_import_into_non_empty_state_is_rejected(tmp_path: Path) -> None:
    """A backup never merges into a working state: it needs an empty database."""
    # Arrange
    paths = local_paths(tmp_path)
    _shared_state(paths.state_file)
    backup = tmp_path / "stan.json"
    assert main(["state", "export", "--output", str(backup)], paths=paths) == 0
    state = StateStore(paths.state_file)
    state.remove_user("igor", actor=LOCAL_OWNER)
    before = state.snapshot()

    # Act
    status = main(["state", "import", str(backup)], paths=paths)

    # Assert
    assert status == 4  # conflict
    assert state.snapshot() == before


@pytest.mark.parametrize(
    "text",
    [
        "nie json",
        json.dumps({"schema": "archiwista-state/3", "users": []}),
        json.dumps({"schema": "archiwista-state/2", "users": []}),
        json.dumps({"schema": "archiwista-state/1", "users": [{"id": "x"}]}),
        json.dumps(
            {
                **_backup(users=[_user("ada")]),
                "passwords": [_password("ada", temporary=False, expires=None)] * 2,
            }
        ),
    ],
)
def test_import_rejects_other_documents(tmp_path: Path, text: str) -> None:
    """Only a complete, consistent ``archiwista-state/2`` or ``/1`` is restored."""
    # Arrange
    state = StateStore(tmp_path / "state.sqlite")

    # Act / Assert
    with pytest.raises(StateError):
        import_state(state, text)
    assert state.is_empty()


def _columns(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        names = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    connection.close()
    return names
