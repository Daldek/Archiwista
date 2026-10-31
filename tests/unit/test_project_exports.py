"""A project's exports on the disk: lines, attributions, names, replacing.

``archiwista.projects.exports`` writes ``zestawy/<name>/pliki.txt`` and
``ATRYBUCJE.txt`` (A-ADR-049 decision 13): a version's file relative to the
export on one share, else absolute; each file and each attribution once;
each file replaced whole.
"""

import os
from pathlib import Path

import pytest

from archiwista.errors import PathOutsideRootError, ProjectFileWriteError
from archiwista.projects.exports import (
    ATTRIBUTIONS,
    FILES_LIST,
    ExportRow,
    export_path,
    is_export_name,
    list_exports,
    write_export,
)

# A directory below the root that no test machine has: only "/" is common.
ELSEWHERE = Path("/archiwista-test-elsewhere/magazyn/nmt.asc")


def _project(tmp_path: Path) -> Path:
    directory = tmp_path / "nas" / "projekty" / "raba"
    directory.mkdir(parents=True)
    return directory


def _version(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "nas" / "magazyn" / "nmt" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ncols 1\n")
    return path


def test_exports_export_path_is_relative_on_one_share(tmp_path: Path) -> None:
    """A file and the export below one directory: a `/` path from the export."""
    version = _version(tmp_path, "a.asc")
    export = _project(tmp_path) / "zestawy" / "hydrograf"

    # Act
    line = export_path(version, export)

    # Assert
    assert line == "../../../../magazyn/nmt/a.asc"
    assert (export / line).resolve() == version.resolve()


def test_exports_export_path_is_absolute_with_only_the_root_in_common(
    tmp_path: Path,
) -> None:
    """Nothing in common below the root: the path as the server reads it."""
    export = _project(tmp_path) / "zestawy" / "hydrograf"

    # Act
    line = export_path(ELSEWHERE, export)

    # Assert
    assert line == str(ELSEWHERE)


def test_exports_write_export_lists_each_file_and_attribution_once(
    tmp_path: Path,
) -> None:
    """Rows in pin order: duplicates dropped, attributions in order of first use."""
    directory = _project(tmp_path)
    first = _version(tmp_path, "a.asc")
    second = _version(tmp_path, "b.asc")
    rows = [
        ExportRow(first, "© GUGiK"),
        ExportRow(ELSEWHERE, "ISRIC SoilGrids"),
        ExportRow(first, "© GUGiK"),  # pinned by a second group
        ExportRow(second, " © GUGiK "),
        ExportRow(second, None),
    ]

    # Act
    result = write_export(directory, "hydrograf", rows)

    # Assert
    target = directory / "zestawy" / "hydrograf"
    assert result.path == target
    assert result.versions == 3
    assert (target / FILES_LIST).read_bytes() == (
        f"../../../../magazyn/nmt/a.asc\n{ELSEWHERE}\n../../../../magazyn/nmt/b.asc\n"
    ).encode()
    assert (target / ATTRIBUTIONS).read_text(encoding="utf-8") == (
        "© GUGiK\nISRIC SoilGrids\n"
    )


def test_exports_write_export_without_versions_writes_empty_files(
    tmp_path: Path,
) -> None:
    """A project without pins gets an export too, with two empty files."""
    directory = _project(tmp_path)

    # Act
    result = write_export(directory, "pusty", [])

    # Assert
    assert result.versions == 0
    assert (result.path / FILES_LIST).read_bytes() == b""
    assert (result.path / ATTRIBUTIONS).read_bytes() == b""


def test_exports_write_export_failed_replace_leaves_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writing again fails at `os.replace`: the old export stays, no temporary file."""
    directory = _project(tmp_path)
    write_export(directory, "hydrograf", [ExportRow(ELSEWHERE, "A")])
    target = directory / "zestawy" / "hydrograf"
    before = (target / FILES_LIST).read_bytes()

    def refuse(source: object, destination: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("archiwista.projects.files.os.replace", refuse)

    # Act
    with pytest.raises(ProjectFileWriteError):
        write_export(directory, "hydrograf", [ExportRow(_version(tmp_path, "c"), None)])

    # Assert
    assert (target / FILES_LIST).read_bytes() == before
    assert sorted(path.name for path in target.iterdir()) == [ATTRIBUTIONS, FILES_LIST]


def test_exports_write_export_refuses_exports_linked_out_of_the_project(
    tmp_path: Path,
) -> None:
    """`zestawy/` as a link out of the project is refused before anything is written."""
    directory = _project(tmp_path)
    outside = tmp_path / "gdzie-indziej"
    outside.mkdir()
    (directory / "zestawy").symlink_to(outside, target_is_directory=True)

    # Act
    with pytest.raises(PathOutsideRootError):
        write_export(directory, "hydrograf", [])

    # Assert
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("hydrograf", True),
        ("nmt_2024-v1.0", True),
        ("zlewnia-łąki", True),
        ("x" * 64, True),
        ("x" * 65, False),
        ("", False),
        (".ukryty", False),
        ("..", False),
        ("a/b", False),
        ("a b", False),
        ("ok\n", False),
    ],
)
def test_exports_is_export_name_keeps_the_rule(name: str, valid: bool) -> None:
    """Letters, digits, `.`, `_` and `-`, 1 to 64, not starting with `.`."""
    assert is_export_name(name) is valid


def test_exports_list_exports_says_which_are_older_than_the_project(
    tmp_path: Path,
) -> None:
    """Exports by name; one written before the project file changed is flagged."""
    directory = _project(tmp_path)
    old = write_export(directory, "stary", [ExportRow(ELSEWHERE, None)])
    new = write_export(directory, "nowy", [])
    (directory / "zestawy" / "inny").mkdir()  # not an export: no files of one
    stamp = old.written_at.timestamp()
    os.utime(old.path / FILES_LIST, (stamp - 20, stamp - 20))
    os.utime(old.path / ATTRIBUTIONS, (stamp - 10, stamp - 10))
    project_mtime = stamp - 5

    # Act
    found = list_exports(directory, project_mtime)

    # Assert
    assert [(item.name, item.changed_since) for item in found] == [
        ("nowy", False),
        ("stary", True),
    ]
    assert found[0].written_at == new.written_at
    assert found[1].files == (FILES_LIST, ATTRIBUTIONS)
    assert found[1].written_at.timestamp() == pytest.approx(stamp - 10)


def test_exports_list_exports_of_a_project_without_exports_is_empty(
    tmp_path: Path,
) -> None:
    """No `zestawy/`: no exports."""
    assert list_exports(_project(tmp_path), 0.0) == ()
