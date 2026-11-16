"""ZIP archives: members listed from the central directory, never unpacked.

``zipfile`` is replaced by a trap in every test: the renderer reads the end
records and the central directory itself (SPEC 10.1, decision 5). An
archive of exactly one raster (GUGiK's NMT as an XYZ grid in a ZIP) is
previewed as that raster, read by GDAL through ``/vsizip/``.
"""

import warnings
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from archiwista.errors import FormatRefusedError, PreviewUnavailableError
from archiwista.formats import file_format, open_raster
from archiwista.messages import message
from archiwista.previews.renderers import archive
from archiwista.previews.renderers.archive import ArchiveRenderer
from archiwista.previews.types import PreviewSource, build_product, format_name
from tests.fixtures.hostile_files import ZIP_DECLARED_ENTRIES, hostile_files
from tests.fixtures.store_files import xyz_grid, zip_members

_KEY = "a" * 64
# An NMT sheet's corner in EPSG:2180, 16 cells of 5 m a side.
_BOUNDS = (214_620.0, 690_440.0, 214_700.0, 690_520.0)
_SIDE = 16


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
    assert message("preview.reason_archive_members_only")


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


def _nmt_source(path: Path) -> PreviewSource:
    """Return a ``pl.gugik.nmt_xyz_5m`` version as the index gives it (sidecar CRS)."""
    return PreviewSource(
        f"version:zespol:{path.name}",
        _KEY,
        (path,),
        crs="EPSG:2180",
        product="nmt",
        dataset_key="pl.gugik.nmt_xyz_5m",
    )


def _decoded(png: bytes) -> np.ndarray[Any, Any]:
    with warnings.catch_warnings(), MemoryFile(png) as memory:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with memory.open(driver="PNG") as image:
            return np.asarray(image.read())


def _rows_from_the_south(grid: bytes) -> bytes:
    """Return the same grid as GUGiK writes it: rows by rising Y."""
    lines = grid.decode("ascii").splitlines()
    rows = [lines[start : start + _SIDE] for start in range(0, len(lines), _SIDE)]
    return ("\n".join(line for row in reversed(rows) for line in row) + "\n").encode()


def test_zip_of_one_xyz_is_previewed_as_its_grid(tmp_path: Path) -> None:
    """One XYZ in a ZIP: its size, the index's CRS, NMT styles and a COG."""
    # Arrange
    path = _write_zip(
        tmp_path / "N-33-66-C-d-3-3.zip",
        [("73843_1035511_NMT-N3366Cd33.xyz", xyz_grid(_BOUNDS, 7, size=_SIDE))],
    )
    source = _nmt_source(path)
    renderer = ArchiveRenderer()

    # Act
    probe = renderer.probe(source)
    renderer.build(source, probe, tmp_path / "cog.tif")
    thumbnail = _decoded(renderer.thumbnail(source, probe, "hillshade", 256, None))

    # Assert
    assert (probe.kind, probe.driver, probe.reason) == ("raster", "XYZ", None)
    assert (probe.width, probe.height, probe.crs) == (_SIDE, _SIDE, "EPSG:2180")
    assert probe.bbox_native == pytest.approx(_BOUNDS)
    assert probe.default_style == "hillshade" and probe.unit == "m"
    assert build_product(probe) == "cog.tif"
    assert format_name(source.format, probe) == "XYZ (ZIP)"
    with rasterio.open(tmp_path / "cog.tif", driver="GTiff") as cog:
        assert cog.crs.to_epsg() == 2180
        assert (cog.width, cog.height) == (_SIDE, _SIDE)
        assert tuple(cog.bounds) == pytest.approx(_BOUNDS)
    assert thumbnail.shape == (4, _SIDE, _SIDE)
    assert thumbnail[3].all()


def test_xyz_rows_from_the_south_thumbnail_north_up(tmp_path: Path) -> None:
    """GUGiK's rows by rising Y give the same thumbnail as rows from the north."""
    # Arrange
    grid = xyz_grid(_BOUNDS, 7, size=_SIDE)
    renderer = ArchiveRenderer()
    sources = [
        _nmt_source(_write_zip(tmp_path / f"{name}.zip", [(f"{name}.xyz", data)]))
        for name, data in (("north", grid), ("south", _rows_from_the_south(grid)))
    ]

    # Act
    north, south = (
        _decoded(renderer.thumbnail(item, probe, "hypsometry", 256, None))
        for item in sources
        for probe in [renderer.probe(item)]
    )

    # Assert
    assert not np.array_equal(north, north[:, ::-1, :])
    assert np.array_equal(north, south)


def test_zip_of_unsorted_xyz_has_no_preview(tmp_path: Path) -> None:
    """Points that are no grid (Y changing direction): ``unsupported_format``."""
    # Arrange
    points = b"0 10 1\n10 0 2\n5 5 3\n0 0 4\n10 10 5\n"
    path = _write_zip(tmp_path / "punkty.zip", [("punkty.xyz", points)])

    # Act
    with pytest.raises(PreviewUnavailableError) as refused:
        ArchiveRenderer().probe(_nmt_source(path))

    # Assert
    assert refused.value.reason == "unsupported_format"


@pytest.mark.parametrize(
    "entries",
    [
        [("arkusz.xyz", b"0 0 1\n"), ("opis.txt", b"NMT")],
        [("a.xyz", b"0 0 1\n"), ("b.xyz", b"0 0 1\n")],
        [("opis.txt", b"NMT")],
    ],
    ids=["raster_and_text", "two_rasters", "no_raster"],
)
def test_zip_of_no_single_raster_lists_members(
    tmp_path: Path, entries: list[tuple[str, bytes]]
) -> None:
    """More files than one raster, or none: the list of members, no image."""
    # Arrange
    path = _write_zip(tmp_path / "arkusze.zip", entries)
    renderer = ArchiveRenderer()
    source = _nmt_source(path)

    # Act
    probe = renderer.probe(source)

    # Assert
    assert (probe.kind, probe.reason) == ("archive", "archive_members_only")
    assert format_name(source.format, probe) == "ZIP"
    with pytest.raises(PreviewUnavailableError):
        renderer.thumbnail(source, probe, "hillshade", 256, None)


def test_zip_raster_member_outside_is_never_opened(tmp_path: Path) -> None:
    """A single raster named ``../x.xyz`` is only listed; GDAL never opens it."""
    # Arrange
    path = _write_zip(tmp_path / "zly.zip", [("../x.xyz", b"0 0 1\n")])

    # Act
    probe = ArchiveRenderer().probe(_nmt_source(path))

    # Assert
    assert (probe.kind, probe.reason) == ("archive", "archive_members_only")
    with pytest.raises(FormatRefusedError):
        open_raster(path, file_format("x.xyz"), member="../x.xyz")
