"""ZIP archives: members listed from the central directory, never unpacked.

``zipfile`` is replaced by a trap in every test: the renderer reads the end
records and the central directory itself (SPEC 10.1, decision 5).
"""

import zipfile
from pathlib import Path

import pytest

from archiwista.errors import PreviewUnavailableError
from archiwista.messages import MESSAGES
from archiwista.previews.renderers import archive
from archiwista.previews.renderers.archive import ArchiveRenderer
from archiwista.previews.types import PreviewSource
from tests.fixtures.hostile_files import ZIP_DECLARED_ENTRIES, hostile_files
from tests.fixtures.store_files import zip_members

_KEY = "a" * 64


@pytest.fixture(autouse=True)
def _no_zipfile(monkeypatch: pytest.MonkeyPatch) -> None:
    def trap(*args: object, **kwargs: object) -> None:
        raise AssertionError("zipfile.ZipFile used")

    monkeypatch.setattr(zipfile, "ZipFile", trap)


def _source(path: Path) -> PreviewSource:
    return PreviewSource(f"file:p:{path.name}", _KEY, (path,))


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    return zip_members(entries)


def _write_zip(path: Path, entries: list[tuple[str, bytes]]) -> Path:
    # ``zip_members`` needs the real ZipFile: restored only while writing.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(zipfile, "ZipFile", _REAL_ZIPFILE)
        path.write_bytes(_zip(entries))
    return path


_REAL_ZIPFILE = zipfile.ZipFile


def test_archive_members_lists_names_sizes_and_formats(tmp_path: Path) -> None:
    """Each member: name, size, compressed size, format by its extension."""
    # Arrange
    path = _write_zip(
        tmp_path / "lod2.zip",
        [
            ("budynki/1465011.gml", b"<CityModel/>" * 100),
            ("budynki/opis.pdf", b"%PDF-1.4\n"),
            ("budynki/", b""),
        ],
    )
    renderer = ArchiveRenderer()

    # Act
    probe = renderer.probe(_source(path))
    listed = renderer.members(_source(path))

    # Assert
    assert (probe.driver, probe.members, probe.reason) == (
        "ZIP",
        3,
        "archive_members_only",
    )
    assert (listed["total"], listed["truncated"]) == (3, False)
    first, second, third = listed["members"]
    assert first["name"] == "budynki/1465011.gml"
    assert first["size_bytes"] == 1200
    assert 0 < first["compressed_bytes"] < 1200
    assert (first["format"], first["kind"]) == ("unknown", "unknown")
    assert (second["format"], second["kind"]) == ("PDF", "document")
    assert third["directory"] is True
    assert MESSAGES["preview_reason_archive_members_only"]


def test_archive_members_truncated_past_10000(tmp_path: Path) -> None:
    """10 001 members: the first 10 000 listed, the total counted."""
    # Arrange
    entries = [(f"arkusze/{index:05d}.asc", b"") for index in range(10_001)]
    path = _write_zip(tmp_path / "duzo.zip", entries)

    # Act
    listed = ArchiveRenderer().members(_source(path))

    # Assert
    assert listed["total"] == 10_001
    assert listed["truncated"] is True
    assert len(listed["members"]) == archive.MAX_LISTED == 10_000
    assert listed["members"][-1]["name"] == "arkusze/09999.asc"


def test_archive_member_outside_is_only_listed(tmp_path: Path) -> None:
    """A member ``../x`` is a name in the list; nothing is written anywhere."""
    # Arrange
    folder = tmp_path / "folder"
    folder.mkdir()
    path = _write_zip(folder / "zly.zip", [("../x", b"tajne"), ("/etc/y", b"z")])
    before = sorted(tmp_path.rglob("*"))

    # Act
    listed = ArchiveRenderer().members(_source(path))

    # Assert
    assert [member["name"] for member in listed["members"]] == ["../x", "/etc/y"]
    assert sorted(tmp_path.rglob("*")) == before


def test_archive_declaring_200000_entries_is_too_large(tmp_path: Path) -> None:
    """ZIP64 end record declaring 200 000 entries: ``too_large`` from the records."""
    # Arrange
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(zipfile, "ZipFile", _REAL_ZIPFILE)
        files = hostile_files(tmp_path / "podstawione")
    renderer = ArchiveRenderer()

    # Act
    probe = renderer.probe(_source(files.zip_many_entries))
    with pytest.raises(PreviewUnavailableError) as members:
        renderer.members(_source(files.zip_many_entries))

    # Assert
    assert (probe.members, probe.reason) == (ZIP_DECLARED_ENTRIES, "too_large")
    assert members.value.reason == "too_large"


def test_archive_with_prepended_bytes_lists_members(tmp_path: Path) -> None:
    """A self-extracting archive (bytes before it) still lists its members."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(zipfile, "ZipFile", _REAL_ZIPFILE)
        data = _zip([("a.txt", b"a"), ("b.tif", b"b")])
    path = tmp_path / "sfx.zip"
    path.write_bytes(b"MZ" + bytes(4094) + data)

    listed = ArchiveRenderer().members(_source(path))

    assert [member["name"] for member in listed["members"]] == ["a.txt", "b.tif"]


@pytest.mark.parametrize("content", [b"", b"PK\x03\x04 not an archive", bytes(100)])
def test_archive_not_zip_is_value_error(tmp_path: Path, content: bytes) -> None:
    """No end record: a library error, which the worker turns into ``unreadable``."""
    path = tmp_path / "zepsute.zip"
    path.write_bytes(content)

    with pytest.raises(ValueError):
        ArchiveRenderer().probe(_source(path))


def test_archive_has_no_thumbnail_or_tile(tmp_path: Path) -> None:
    """An archive's preview is its list: the image operations give the reason."""
    path = _write_zip(tmp_path / "a.zip", [("a.txt", b"a")])
    renderer = ArchiveRenderer()
    probe = renderer.probe(_source(path))

    with pytest.raises(PreviewUnavailableError) as thumbnail:
        renderer.thumbnail(_source(path), probe, "rgb", 256, None)
    with pytest.raises(PreviewUnavailableError) as tile:
        renderer.tile(_source(path), probe, "rgb", 3, 1, 1, {})

    assert thumbnail.value.reason == tile.value.reason == "archive_members_only"
