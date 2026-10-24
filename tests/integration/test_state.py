"""The state database: separate from the index, migrated, backed up (A-ADR-029).

Accounts, groups and project access cannot be rebuilt from files, so an
index rebuild must leave them alone, an older database must migrate with
its data, a newer one must be refused untouched, and ``archiwista state
export`` → ``state import`` into an empty database must give back the same
permissions.
"""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER, access_key
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
    import_state,
)
from archiwista.state import initialize as initialize_state
from tests.fixtures.index_data import PRODUCER, ROOT, STORE
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import (
    VISIBILITY_VALUES,
    WHO,
    WRITER,
    Who,
    add_people,
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


def _shared_state(path: Path) -> StateStore:
    """Four people, a group, one project per visibility and their log."""
    state = StateStore(path)
    add_people(state)
    for visibility, directory in DIRECTORIES.items():
        share(state, access_key(directory), visibility)
    state.update_user("igor", roles=WRITER, actor=LOCAL_OWNER)
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
    assert document["schema"] == "archiwista-state/1"
    assert {key: value for key, value in copy.items() if key != "exported_at"} == {
        key: value for key, value in document.items() if key != "exported_at"
    }


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
        json.dumps({"schema": "archiwista-state/2", "users": []}),
        json.dumps({"schema": "archiwista-state/1", "users": [{"id": "x"}]}),
    ],
)
def test_import_rejects_other_documents(tmp_path: Path, text: str) -> None:
    """Only a complete ``archiwista-state/1`` document is restored."""
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
