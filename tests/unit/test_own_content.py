"""Content identity of own-data files (plan v0.2, step 7a; decision 8).

The logical hash of a SQLite file follows its committed rows and schema and
nothing else: not the page layout, a checkpoint, an open transaction (also
one a crashed writer left half in the file), the R*Tree's shadow tables or
what OGR and QGIS rewrite on an open for update without edits. Virtual and
shadow tables are told from ``sqlite_master`` as ``PRAGMA table_list`` tells
them. A file set hashes its members in any order.
"""

import contextlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import shapely

from archiwista.errors import InconsistentReadError
from archiwista.owndata.content import (
    consistent_sqlite_read,
    content_identity,
    file_sha256,
    table_kinds,
)
from archiwista.owndata.formats import fileset_members
from tests.fixtures.own_data import GpkgEditor, make_own_folder

_BASIN = shapely.box(566_200, 241_200, 566_300, 241_300)
# A writer in rollback mode dying inside its transaction: a cache of one page
# spills the changed pages into the file, the journal keeps the old ones.
CRASHING_WRITER = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("PRAGMA cache_size=1")
db.execute("BEGIN IMMEDIATE")
db.execute("UPDATE notes SET body = upper(body)")
os._exit(0)
"""


@pytest.fixture
def gpkg(tmp_path: Path) -> Path:
    """GeoPackage of two layers written by GDAL, with its spatial indexes."""
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_layers",))
    return folder.path("gpkg_layers")


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """Return the work directory for the copies of states (b) and (c)."""
    directory = tmp_path / "work"
    directory.mkdir()
    return directory


def _logical(path: Path, work: Path) -> str:
    return content_identity([path], method="sqlite", work_dir=work).sha256


def _execute(path: Path, script: str) -> None:
    """Run SQL on the file; GDAL's triggers name SQL functions of geometries.

    No change here touches a geometry, so those functions are never called.
    """
    with contextlib.closing(sqlite3.connect(path)) as db:
        for name in ("ST_IsEmpty", "ST_MinX", "ST_MinY", "ST_MaxX", "ST_MaxY"):
            db.create_function(name, 1, _no_geometry)
        db.executescript(script)


def _no_geometry(_blob: object) -> None:
    raise AssertionError("a geometry function was called")


def test_sqlite_hash_ignores_vacuum_and_checkpoint(gpkg: Path, work: Path) -> None:
    """Committed frames hash the same in the WAL and after the checkpoint.

    A ``VACUUM`` to another page size rewrites every page of the file; the
    logical hash stays.
    """
    # Arrange
    with GpkgEditor(gpkg) as editor:
        editor.begin()
        editor.insert("zlewnie", _BASIN, nazwa="Zlewnia C")
        editor.commit()
        in_wal = _logical(gpkg, work)
    checkpointed = _logical(gpkg, work)
    layout = file_sha256(gpkg)

    # Act
    _execute(gpkg, "PRAGMA journal_mode=DELETE; PRAGMA page_size=8192; VACUUM;")

    # Assert
    assert file_sha256(gpkg) != layout
    assert in_wal == checkpointed == _logical(gpkg, work)


def test_sqlite_hash_includes_committed_wal_frames(gpkg: Path, work: Path) -> None:
    """A row committed only in ``-wal`` changes the hash, also after a crash."""
    # Arrange
    before = _logical(gpkg, work)
    editor = GpkgEditor(gpkg)
    editor.begin()
    editor.insert("zlewnie", _BASIN, nazwa="Zlewnia C")
    editor.commit()

    # Act
    while_open = _logical(gpkg, work)
    editor.crash_without_shm()
    after_crash = _logical(gpkg, work)

    # Assert
    assert while_open != before
    assert after_crash == while_open
    assert editor.wal.exists() and not editor.shm.exists()


def test_sqlite_hash_excludes_uncommitted_transaction(gpkg: Path, work: Path) -> None:
    """Rows of a transaction still open in the editor are not in the hash."""
    # Arrange
    before = _logical(gpkg, work)

    with GpkgEditor(gpkg) as editor:
        editor.begin()
        editor.insert("zlewnie", _BASIN, nazwa="Zlewnia C")

        # Act
        during = _logical(gpkg, work)

    # Assert
    assert during == before


def _contents(directory: Path) -> dict[str, str]:
    return {path.name: file_sha256(path) for path in sorted(directory.iterdir())}


def test_sqlite_hash_rolls_back_a_hot_journal_in_a_copy(
    tmp_path: Path, work: Path
) -> None:
    """A crash in the middle of a rollback-mode transaction counts as undone.

    The file already holds changed pages; read in place it would hash them.
    The copy rolls the journal back, and the folder keeps both files as left.
    """
    # Arrange
    path = tmp_path / "dane" / "notatki.sqlite"
    path.parent.mkdir()
    with contextlib.closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        db.executemany(
            "INSERT INTO notes (body) VALUES (?)",
            [(f"notatka {number} " * 20,) for number in range(2000)],
        )
        db.commit()
    before = _logical(path, work)
    original = file_sha256(path)
    subprocess.run([sys.executable, "-c", CRASHING_WRITER, str(path)], check=True)
    left = _contents(path.parent)

    # Act
    after = _logical(path, work)

    # Assert
    assert sorted(left) == ["notatki.sqlite", "notatki.sqlite-journal"]
    assert left["notatki.sqlite"] != original
    assert after == before
    assert _contents(path.parent) == left


@pytest.mark.parametrize(
    "change",
    [
        'UPDATE "przewody" SET "material" = \'PVC\' WHERE fid = 2;',
        'UPDATE "przewody" SET "material" = CAST("material" AS BLOB) WHERE fid = 3;',
        'DELETE FROM "zlewnie" WHERE fid = 1;',
        'ALTER TABLE "zlewnie" ADD COLUMN "uwagi" TEXT;',
        'CREATE INDEX "przewody_material" ON "przewody" ("material");',
        "UPDATE gpkg_contents SET description = 'kanały' WHERE table_name = 'zlewnie';",
        "PRAGMA user_version = 10201;",
    ],
    ids=[
        "value",
        "type_of_value",
        "row_deleted",
        "column_added",
        "index_created",
        "gpkg_contents_description",
        "user_version",
    ],
)
def test_sqlite_hash_changes_with_row_or_schema(
    gpkg: Path, work: Path, change: str
) -> None:
    """Rows, value types, schema and other ``gpkg_contents`` columns count."""
    # Arrange
    before = _logical(gpkg, work)

    # Act
    _execute(gpkg, change)

    # Assert
    assert _logical(gpkg, work) != before


def test_sqlite_hash_ignores_rtree_shadow_tables(gpkg: Path, work: Path) -> None:
    """An emptied or wrong spatial index (R*Tree shadow tables) keeps the hash."""
    # Arrange
    before = _logical(gpkg, work)
    layout = file_sha256(gpkg)

    # Act
    _execute(
        gpkg,
        'DELETE FROM "rtree_przewody_geom";'
        'INSERT INTO "rtree_zlewnie_geom" VALUES (99, 0, 1, 0, 1);',
    )

    # Assert
    assert file_sha256(gpkg) != layout
    assert _logical(gpkg, work) == before


def test_sqlite_hash_ignores_ogr_contents_cache(gpkg: Path, work: Path) -> None:
    """An open for update without edits rewrites counts and times, not the hash."""
    # Arrange
    before = _logical(gpkg, work)
    layout = file_sha256(gpkg)

    # Act
    with GpkgEditor(gpkg) as editor:
        editor.reopen_for_update_unchanged()

    # Assert
    assert file_sha256(gpkg) != layout
    assert _logical(gpkg, work) == before


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < (3, 37, 0), reason="PRAGMA table_list: SQLite 3.37"
)
def test_shadow_tables_from_sqlite_master_match_table_list(tmp_path: Path) -> None:
    """``sqlite_master`` tells virtual and shadow tables as ``table_list`` does.

    Quoted names, ``IF NOT EXISTS`` and a module in any letter case count;
    a table named like a shadow table of no virtual table is data.
    """
    # Arrange
    statements = [
        "CREATE TABLE plain (id INTEGER PRIMARY KEY, body TEXT)",
        "CREATE TABLE rt_extra (id INTEGER PRIMARY KEY)",
        "CREATE TABLE lost_node (id INTEGER PRIMARY KEY)",
        "CREATE VIRTUAL TABLE rt USING rtree(id, min_x, max_x, min_y, max_y)",
        "CREATE VIRTUAL TABLE rt32 USING RTREE_I32(id, min_x, max_x)",
        'CREATE VIRTUAL TABLE IF NOT EXISTS "spatial index" using rtree(id, a, b)',
        "CREATE VIRTUAL TABLE [f 3] USING fts3(body)",
        "CREATE VIRTUAL TABLE f4 USING fts4(body)",
        "CREATE VIRTUAL TABLE f5 USING fts5(body)",
    ]
    with contextlib.closing(sqlite3.connect(tmp_path / "virtual.sqlite")) as db:
        for statement in statements:
            db.execute(statement)
        db.commit()
        listed = db.execute(
            "SELECT name, type FROM pragma_table_list WHERE schema = 'main'"
            " AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        # Act
        kinds = table_kinds(db)

    # Assert
    assert kinds == dict(listed)


def test_fileset_independent_of_listing_order(tmp_path: Path) -> None:
    """Members hash the same in any order and letter case; a member counts."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("shp_full",))
    members = fileset_members(folder.path("shp_full"))
    renamed = tmp_path / "kopia"
    renamed.mkdir()
    for member in members:
        shutil.copyfile(member, renamed / member.name.upper())

    # Act
    listed = content_identity(members, method="fileset")
    reversed_order = content_identity(members[::-1], method="fileset")
    upper_case = content_identity(sorted(renamed.iterdir()), method="fileset")
    with (renamed / "DZIALKI.DBF").open("ab") as dbf:
        dbf.write(b"\x1a")
    changed = content_identity(sorted(renamed.iterdir()), method="fileset")

    # Assert
    assert len(members) == 5
    assert listed == reversed_order == upper_case
    assert changed != listed


def test_fileset_members_found_in_any_letter_case(tmp_path: Path) -> None:
    """Members of any letter case follow the main file; other files stay out."""
    # Arrange
    for name in ("Dzialki.SHP", "Dzialki.shx", "DZIALKI.DBF", "dzialki.Prj"):
        (tmp_path / name).write_bytes(b"x")
    for name in ("Dzialki.csv", "Dzialki.shp.xml", "inne.dbf"):
        (tmp_path / name).write_bytes(b"x")

    # Act
    members = fileset_members(tmp_path / "Dzialki.SHP")

    # Assert
    assert [member.name for member in members] == [
        "Dzialki.SHP",
        "Dzialki.shx",
        "DZIALKI.DBF",
        "dzialki.Prj",
    ]


def test_sqlite_read_in_place_detects_a_change(gpkg: Path, work: Path) -> None:
    """A file written during an in-place read fails the read, never misleads."""
    # Arrange
    reads: list[str] = []

    # Act
    with (
        pytest.raises(InconsistentReadError),
        consistent_sqlite_read(gpkg, work_dir=work) as view,
    ):
        reads.append(view.state)
        _execute(gpkg, 'DELETE FROM "zlewnie" WHERE fid = 1;')

    # Assert
    assert reads == ["in_place"]
