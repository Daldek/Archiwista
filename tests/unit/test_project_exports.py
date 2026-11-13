"""A project's exports on the disk: folders, copies, names, README, replacing.

``archiwista.projects.exports`` writes ``eksport/<name>/`` (A-ADR-049
decision 13 and its erratum 1): each version's file copied into its category
folder under its name with its companions (never a ``*.meta.json``), a ZIP
of one raster unpacked under its member's name, two files of one name in a
folder told apart by their labels, ``README.txt`` with every file and the
providers' lines once each, which ``ATTRIBUTION.txt`` at the root holds too
(A-ADR-055), the export and its ZIP replaced whole.
"""

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from archiwista.attribution import Attribution
from archiwista.errors import PathOutsideRootError, ProjectFileWriteError
from archiwista.projects.exports import (
    ATTRIBUTION,
    README,
    ExportItem,
    export_zip,
    folder_name,
    is_export_name,
    list_exports,
    write_export,
)
from tests.fixtures.provider_lines import (
    CHMI_PROCESSED,
    CHMI_SOURCE,
    IMGW_PROCESSED,
    IMGW_SOURCE,
    IMGW_TERMS_PUBLIC_DATA,
)

# A version of a producer whose providers' terms Archiwista does not know: the
# attribution of its sidecar is its one line.
GUGIK = Attribution(("Główny Urząd Geodezji i Kartografii",))
# A station series of Obserwator, processed; a file of IMGW-PIB as published.
SERIES = Attribution((IMGW_SOURCE, IMGW_PROCESSED), (IMGW_TERMS_PUBLIC_DATA,))
ARCHIVE = Attribution((IMGW_SOURCE,), (IMGW_TERMS_PUBLIC_DATA,))
CHMI = Attribution((CHMI_SOURCE, CHMI_PROCESSED))
NO_LINES = Attribution()


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


def _zip_version(
    tmp_path: Path, directory: str, name: str, members: list[tuple[str, bytes]]
) -> Path:
    path = tmp_path / "magazyn" / directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for member, body in members:
            archive.writestr(member, body)
    return path


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _item(
    file: Path,
    folder: str = "NMT",
    *,
    label: str | None = None,
    sets: tuple[str, ...] = ("2024",),
    lines: Attribution = NO_LINES,
    sha256: str = "ab" * 32,
    crs: str | None = "EPSG:2180",
    vertical_crs: str | None = None,
) -> ExportItem:
    return ExportItem(
        file=file,
        folder=folder,
        label=label,
        sha256=sha256,
        sets=sets,
        product="nmt",
        year=2024,
        crs=crs,
        vertical_crs=vertical_crs,
        lines=lines,
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
    """Known facts only; the sets; the providers' lines once each, in order."""
    directory = _project(tmp_path)
    sheet = _version(tmp_path, "v1", "a.asc", b"abc")
    tile = _version(tmp_path, "v2", "b.tif", b"xy")
    czech = _version(tmp_path, "v3", "cz.csv", b"t,h\n")
    archive = _version(tmp_path, "v4", "stany.csv", b"t,h\n")
    series = _version(tmp_path, "v5", "seria.csv", b"t,h\n")

    # Act
    result = write_export(
        directory,
        "raba",
        [
            _item(sheet, label="2024-06-13", sets=("2024", "2014"), lines=GUGIK),
            _item(tile, "ORTO", lines=GUGIK),
            _item(czech, "OBSERWATOR", lines=CHMI),
            _item(archive, "OBSERWATOR", lines=ARCHIVE),
            _item(series, "OBSERWATOR", lines=SERIES),
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
    assert readme.endswith(
        "\nŹródła danych i warunki korzystania\n"
        f"- {IMGW_SOURCE}\n"
        f"- {IMGW_PROCESSED}\n"
        f"- {CHMI_SOURCE}\n"
        f"- {CHMI_PROCESSED}\n"
        "- Główny Urząd Geodezji i Kartografii\n"
        f"- {IMGW_TERMS_PUBLIC_DATA}\n"
    )


def test_exports_write_export_writes_the_providers_lines_into_attribution_txt(
    tmp_path: Path,
) -> None:
    """At the root, listed and zipped: the attribution, then the terms, each once."""
    directory = _project(tmp_path)
    series = _version(tmp_path, "v1", "seria.csv", b"t,h\n")
    archive = _version(tmp_path, "v2", "stany.csv", b"t,h\n")

    # Act
    result = write_export(
        directory,
        "raba",
        [
            _item(archive, "OBSERWATOR", lines=ARCHIVE),
            _item(series, "OBSERWATOR", lines=SERIES),
        ],
        project="Raba",
        with_zip=True,
    )

    # Assert
    assert result.files == (
        "OBSERWATOR/seria.csv",
        "OBSERWATOR/stany.csv",
        ATTRIBUTION,
        README,
    )
    written = (result.path / ATTRIBUTION).read_text(encoding="utf-8")
    assert written.split("\n") == [
        IMGW_SOURCE,
        IMGW_PROCESSED,
        IMGW_TERMS_PUBLIC_DATA,
        "",
    ]
    packed = zipfile.ZipFile(directory / "eksport" / "raba.zip")
    assert packed.namelist() == list(result.files)
    assert packed.read(ATTRIBUTION).decode() == written


def test_exports_write_export_unpacks_a_zip_of_one_xyz_and_describes_it(
    tmp_path: Path,
) -> None:
    """The member under its own name, bytes unchanged; both checksums, CRS to set."""
    directory = _project(tmp_path)
    grid = b"500000.5 600000.5 12.25\n500001.5 600000.5 12.5\n"
    packed = _zip_version(
        tmp_path, "2020", "73044_N-33-66-C-d-3-3.zip", [("N-33-66-C-d-3-3.xyz", grid)]
    )
    _version(tmp_path, "2020", "73044_N-33-66-C-d-3-3.zip.aux.xml", b"<aux/>")
    archive_sha = _sha256(packed.read_bytes())

    # Act
    result = write_export(
        directory,
        "wolin",
        [
            _item(
                packed,
                sets=("2020",),
                sha256=archive_sha,
                vertical_crs="PL-EVRF2007-NH",
            )
        ],
        project="Wolin",
        with_zip=False,
    )

    # Assert
    assert result.files == ("NMT/N-33-66-C-d-3-3.xyz", README)
    assert (result.path / "NMT" / "N-33-66-C-d-3-3.xyz").read_bytes() == grid
    readme = (result.path / README).read_text(encoding="utf-8")
    assert (
        "NMT/N-33-66-C-d-3-3.xyz\n"
        "  produkt: nmt\n"
        "  rok: 2024\n"
        "  układ współrzędnych: EPSG:2180\n"
        "  układ wysokości: PL-EVRF2007-NH\n"
        f"  rozmiar: {len(grid)} B\n"
        f"  suma SHA-256: {_sha256(grid)}\n"
        "  zestaw: 2020\n"
        "  rozpakowany z 73044_N-33-66-C-d-3-3.zip,"
        f" suma SHA-256 pliku ZIP: {archive_sha}\n"
        "  plik XYZ nie zawiera układu współrzędnych: w QGIS ustaw EPSG:2180"
        " (układ wysokości PL-EVRF2007-NH); punkty brakujące w siatce to nodata\n"
    ) in readme


def test_exports_write_export_tells_apart_unpacked_rasters_and_zips_them(
    tmp_path: Path,
) -> None:
    """One inner name in two years: labels on both; `with_zip` holds the rasters."""
    directory = _project(tmp_path)
    old = _zip_version(tmp_path, "2020", "a.zip", [("dane/arkusz.xyz", b"2020")])
    new = _zip_version(tmp_path, "2021", "b.zip", [("arkusz.xyz", b"2021")])

    # Act
    result = write_export(
        directory,
        "raba",
        [_item(old, label="2020"), _item(new, label="2021")],
        project="Raba",
        with_zip=True,
    )

    # Assert
    files = ["NMT/arkusz_2020.xyz", "NMT/arkusz_2021.xyz", README]
    assert list(result.files) == files
    packed = zipfile.ZipFile(directory / "eksport" / "raba.zip")
    assert packed.namelist() == files
    assert packed.read("NMT/arkusz_2020.xyz") == b"2020"
    assert packed.read("NMT/arkusz_2021.xyz") == b"2021"


def test_exports_write_export_copies_other_zips_as_they_are(
    tmp_path: Path,
) -> None:
    """Two files or no raster: the ZIP itself, README says it was kept."""
    directory = _project(tmp_path)
    two = _zip_version(
        tmp_path, "v1", "dwa.zip", [("a.xyz", b"a"), ("a.xyz.aux.xml", b"<aux/>")]
    )
    text = _zip_version(tmp_path, "v2", "opis.zip", [("opis.txt", b"tekst")])
    sheet = _zip_version(tmp_path, "v3", "asc.zip", [("arkusz.asc", b"ncols 1\n")])

    # Act
    result = write_export(
        directory,
        "raba",
        [_item(two), _item(text), _item(sheet)],
        project="Raba",
        with_zip=False,
    )

    # Assert
    assert result.files == ("NMT/arkusz.asc", "NMT/dwa.zip", "NMT/opis.zip", README)
    assert (result.path / "NMT" / "dwa.zip").read_bytes() == two.read_bytes()
    assert (result.path / "NMT" / "opis.zip").read_bytes() == text.read_bytes()
    assert (result.path / "NMT" / "arkusz.asc").read_bytes() == b"ncols 1\n"
    readme = (result.path / README).read_text(encoding="utf-8")
    kept = (
        "  ZIP skopiowany bez zmian: nie zawiera dokładnie jednego pliku rastrowego\n"
    )
    assert readme.count(kept) == 2
    assert "\nNMT/dwa.zip\n" in readme
    assert "rozpakowany z asc.zip" in readme
    assert "plik XYZ" not in readme


def test_exports_write_export_tells_to_set_the_crs_of_an_xyz_of_unknown_crs(
    tmp_path: Path,
) -> None:
    """An XYZ the store gives no CRS: README says to set one in QGIS."""
    directory = _project(tmp_path)
    grid = _version(tmp_path, "v1", "siatka.xyz", b"1 2 3\n")

    # Act
    result = write_export(
        directory, "raba", [_item(grid, crs=None)], project="Raba", with_zip=False
    )

    # Assert
    readme = (result.path / README).read_text(encoding="utf-8")
    assert (
        "  plik XYZ nie zawiera układu współrzędnych, a magazyn go nie podaje:"
        " ustaw go w QGIS; punkty brakujące w siatce to nodata\n"
    ) in readme
    assert "rozpakowany" not in readme
    assert "ZIP skopiowany" not in readme


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
        ("..", "obserwator", "OBSERWATOR"),
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
    old = write_export(
        directory, "stary", [_item(sheet, lines=SERIES)], project="R", with_zip=True
    )
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
    assert found[0].files == (README,)
    assert found[1].files == old.files == ("NMT/a.asc", ATTRIBUTION, README)
    assert found[1].written_at.timestamp() == pytest.approx(stamp - 10)
    assert export_zip(directory, "stary") == directory / "eksport" / "stary.zip"
    assert export_zip(directory, "nowy") is None


def test_exports_list_exports_of_a_project_without_exports_is_empty(
    tmp_path: Path,
) -> None:
    """No `eksport/`: no exports."""
    assert list_exports(_project(tmp_path), 0.0) == ()
