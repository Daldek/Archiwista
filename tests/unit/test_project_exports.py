"""A project's exports on the disk: folders, copies, names, README, replacing.

``archiwista.projects.exports`` writes ``eksport/<name>/`` (A-ADR-049
decision 13 and its erratum 1): each version's file copied into its category
folder under its name with its companions (never a ``*.meta.json``), two
files of one name in a folder told apart by their labels, ``README.txt``
with every file and each attribution once, the export and its ZIP replaced
whole.
"""

import os
import zipfile
from pathlib import Path

import pytest

from archiwista.errors import PathOutsideRootError, ProjectFileWriteError
from archiwista.projects.exports import (
    README,
    ExportItem,
    export_zip,
    folder_name,
    is_export_name,
    list_exports,
    write_export,
)


def _project(tmp_path: Path) -> Path:
    directory = tmp_path / "projekty" / "raba"
    directory.mkdir(parents=True)
    return directory


def _version(
    tmp_path: Path, directory: str, name: str, body: bytes = b"ncols 1\n"
) -> Path:
    path = tmp_path / "magazyn" / directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _item(
    file: Path,
    folder: str = "NMT",
    *,
    label: str | None = None,
    sets: tuple[str, ...] = ("2024",),
    attribution: str | None = None,
    sha256: str = "ab" * 32,
) -> ExportItem:
    return ExportItem(
        file=file,
        folder=folder,
        label=label,
        sha256=sha256,
        sets=sets,
        product="nmt",
        year=2024,
        crs="EPSG:2180",
        vertical_crs=None,
        attribution=attribution,
    )


def test_exports_write_export_copies_each_file_with_its_companions(
    tmp_path: Path,
) -> None:
    """Copies, not links; the companions beside it come along, a sidecar never."""
    directory = _project(tmp_path)
    sheet = _version(tmp_path, "v1", "M-33-44-A-d-2-2.asc")
    _version(tmp_path, "v1", "M-33-44-A-d-2-2.prj", b"PROJCS")
    _version(tmp_path, "v1", "M-33-44-A-d-2-2.asc.aux.xml", b"<aux/>")
    _version(tmp_path, "v1", "M-33-44-A-d-2-2.asc.meta.json", b"{}")
    _version(tmp_path, "v1", "M-33-44-A-d-2.asc", b"other sheet")
    roads = _version(tmp_path, "v2", "0261.gpkg", b"SQLite format 3")

    # Act
    result = write_export(
        directory,
        "raba-2024",
        [_item(sheet), _item(roads, "BDOT")],
        project="Raba",
        with_zip=False,
    )

    # Assert
    target = directory / "eksport" / "raba-2024"
    assert result.path == target
    assert result.files == (
        "BDOT/0261.gpkg",
        "NMT/M-33-44-A-d-2-2.asc",
        "NMT/M-33-44-A-d-2-2.asc.aux.xml",
        "NMT/M-33-44-A-d-2-2.prj",
        README,
    )
    assert (result.versions, result.zip) == (2, False)
    assert (target / "NMT" / "M-33-44-A-d-2-2.asc").read_bytes() == b"ncols 1\n"
    assert (target / "BDOT" / "0261.gpkg").read_bytes() == b"SQLite format 3"
    copied = os.stat(target / "BDOT" / "0261.gpkg")
    assert copied.st_ino != os.stat(roads).st_ino
    assert copied.st_nlink == 1


def test_exports_write_export_tells_apart_files_of_one_name_by_their_labels(
    tmp_path: Path,
) -> None:
    """The same sheet of two years: both get their label, companions follow."""
    directory = _project(tmp_path)
    old = _version(tmp_path, "2014", "M-33-44-A-d-2-2.asc", b"2014")
    _version(tmp_path, "2014", "M-33-44-A-d-2-2.prj", b"PROJCS 2014")
    new = _version(tmp_path, "2024", "M-33-44-A-d-2-2.asc", b"2024")
    other = _version(tmp_path, "2024", "M-33-44-A-d-2-1.asc")

    # Act
    result = write_export(
        directory,
        "raba",
        [
            _item(new, label="2024-06-13", sets=("2024",)),
            _item(old, label="2014/05", sets=("2014",)),
            _item(other, label="2024-06-13"),
        ],
        project="Raba",
        with_zip=False,
    )

    # Assert
    assert result.files == (
        "NMT/M-33-44-A-d-2-1.asc",
        "NMT/M-33-44-A-d-2-2_2014_05.asc",
        "NMT/M-33-44-A-d-2-2_2014_05.prj",
        "NMT/M-33-44-A-d-2-2_2024-06-13.asc",
        README,
    )
    folder = result.path / "NMT"
    assert (folder / "M-33-44-A-d-2-2_2024-06-13.asc").read_bytes() == b"2024"
    assert (folder / "M-33-44-A-d-2-2_2014_05.asc").read_bytes() == b"2014"


def test_exports_write_export_adds_the_hash_when_the_labels_are_equal(
    tmp_path: Path,
) -> None:
    """Equal names and labels (compared case-folded): the SHA-256 prefix too."""
    directory = _project(tmp_path)
    first = _version(tmp_path, "a", "Arkusz.tif", b"a")
    second = _version(tmp_path, "b", "arkusz.TIF", b"b")

    # Act
    result = write_export(
        directory,
        "raba",
        [
            _item(first, "ORTO", label="2024", sha256="11" * 32),
            _item(second, "ORTO", label="2024", sha256="22" * 32),
        ],
        project="Raba",
        with_zip=False,
    )

    # Assert
    assert result.files == (
        "ORTO/Arkusz_2024_11111111.tif",
        "ORTO/arkusz_2024_22222222.TIF",
        README,
    )


def test_exports_write_export_describes_every_file_and_source_in_readme(
    tmp_path: Path,
) -> None:
    """Known facts only; the sets; each attribution once under „Źródła danych”."""
    directory = _project(tmp_path)
    sheet = _version(tmp_path, "v1", "a.asc", b"abc")
    tile = _version(tmp_path, "v2", "b.tif", b"xy")

    # Act
    result = write_export(
        directory,
        "raba",
        [
            _item(sheet, label="2024-06-13", sets=("2024", "2014"), attribution="A"),
            _item(tile, "ORTO", attribution=" A "),
        ],
        project="Raba",
        with_zip=False,
    )

    # Assert
    readme = (result.path / README).read_text(encoding="utf-8")
    assert readme.startswith("Eksport „raba” projektu „Raba”")
    assert (
        "NMT/a.asc\n"
        "  produkt: nmt\n"
        "  rok: 2024\n"
        "  wersja: 2024-06-13\n"
        "  układ współrzędnych: EPSG:2180\n"
        "  rozmiar: 3 B\n"
        "  suma SHA-256: ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad\n"
        "  zestaw: 2024, 2014\n"
    ) in readme
    assert readme.endswith("\nŹródła danych\n- A\n")


def test_exports_write_export_without_versions_writes_a_readme(
    tmp_path: Path,
) -> None:
    """A project without present pins gets an export of its README alone."""
    directory = _project(tmp_path)

    # Act
    result = write_export(directory, "pusty", [], project="Raba", with_zip=False)

    # Assert
    assert result.files == (README,)
    assert sorted(path.name for path in result.path.iterdir()) == [README]
    assert "Magazyn nie podaje atrybucji" in (result.path / README).read_text(
        encoding="utf-8"
    )


def test_exports_write_export_replaces_the_export_and_its_zip(
    tmp_path: Path,
) -> None:
    """Written again: the old files go; without `with_zip` the old ZIP goes too."""
    directory = _project(tmp_path)
    first = _version(tmp_path, "v1", "a.asc")
    second = _version(tmp_path, "v2", "b.asc")
    write_export(directory, "raba", [_item(first)], project="Raba", with_zip=True)
    archive = directory / "eksport" / "raba.zip"
    before = zipfile.ZipFile(archive).namelist()

    # Act
    again = write_export(
        directory, "raba", [_item(second)], project="Raba", with_zip=True
    )
    after = zipfile.ZipFile(archive).namelist()
    write_export(directory, "raba", [_item(first)], project="Raba", with_zip=False)

    # Assert
    assert before == ["NMT/a.asc", README]
    assert after == list(again.files) == ["NMT/b.asc", README]
    assert not archive.exists()
    assert sorted(path.name for path in (directory / "eksport").iterdir()) == ["raba"]
    assert sorted(
        path.name for path in (directory / "eksport" / "raba" / "NMT").iterdir()
    ) == ["a.asc"]


def test_exports_write_export_failed_copy_leaves_the_old_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy fails: the old export and its ZIP stay, nothing temporary is left."""
    directory = _project(tmp_path)
    sheet = _version(tmp_path, "v1", "a.asc")
    _version(tmp_path, "v2", "b.asc")
    _version(tmp_path, "v2", "b.prj")
    old = write_export(directory, "raba", [_item(sheet)], project="Raba", with_zip=True)
    readme = (old.path / README).read_bytes()

    def refuse(source: object, destination: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("archiwista.projects.exports.shutil.copyfile", refuse)

    # Act
    with pytest.raises(ProjectFileWriteError):
        write_export(
            directory,
            "raba",
            [_item(tmp_path / "magazyn" / "v2" / "b.asc")],
            project="Raba",
            with_zip=False,
        )

    # Assert
    assert (old.path / README).read_bytes() == readme
    assert sorted(path.name for path in (directory / "eksport").iterdir()) == [
        "raba",
        "raba.zip",
    ]


def test_exports_write_export_refuses_exports_linked_out_of_the_project(
    tmp_path: Path,
) -> None:
    """`eksport/` as a link out of the project is refused before anything is written."""
    directory = _project(tmp_path)
    outside = tmp_path / "gdzie-indziej"
    outside.mkdir()
    (directory / "eksport").symlink_to(outside, target_is_directory=True)

    # Act
    with pytest.raises(PathOutsideRootError):
        write_export(directory, "raba", [], project="Raba", with_zip=False)

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


@pytest.mark.parametrize(
    ("text", "fallback", "folder"),
    [
        ("NMT", "kartograf", "NMT"),
        ("true-orto", "kartograf", "TRUE-ORTO"),
        ("../etc", "kartograf", "ETC"),
        ("a/b c", "kartograf", "A_B_C"),
        (None, "kartograf", "KARTOGRAF"),
        ("..", "imgw", "IMGW"),
    ],
)
def test_exports_folder_name_is_one_plain_upper_case_name(
    text: str | None, fallback: str, folder: str
) -> None:
    """Never a path: other characters become `_`, an empty name the fallback."""
    assert folder_name(text, fallback) == folder


def test_exports_list_exports_says_which_are_older_than_the_project(
    tmp_path: Path,
) -> None:
    """Exports by name with files and ZIP; one older than the project is flagged."""
    directory = _project(tmp_path)
    sheet = _version(tmp_path, "v1", "a.asc")
    old = write_export(directory, "stary", [_item(sheet)], project="R", with_zip=True)
    new = write_export(directory, "nowy", [], project="R", with_zip=False)
    (directory / "eksport" / "inny").mkdir()  # not an export: no README
    stamp = old.written_at.timestamp()
    os.utime(old.path / README, (stamp - 10, stamp - 10))
    project_mtime = stamp - 5

    # Act
    found = list_exports(directory, project_mtime)

    # Assert
    assert [(item.name, item.zip, item.changed_since) for item in found] == [
        ("nowy", False, False),
        ("stary", True, True),
    ]
    assert found[0].written_at == new.written_at
    assert found[1].files == ("NMT/a.asc", README)
    assert found[1].written_at.timestamp() == pytest.approx(stamp - 10)
    assert export_zip(directory, "stary") == directory / "eksport" / "stary.zip"
    assert export_zip(directory, "nowy") is None


def test_exports_list_exports_of_a_project_without_exports_is_empty(
    tmp_path: Path,
) -> None:
    """No `eksport/`: no exports."""
    assert list_exports(_project(tmp_path), 0.0) == ()
