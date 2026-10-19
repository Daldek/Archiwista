"""Opening files only as their format (plan v0.2, decision 3).

A MapInfo ``.tab`` is opened only as a native table: a view, a seamless
table, a raster or linked table names other files. Names GDAL would read
as something else than a plain file are refused before GDAL sees them.
"""

from pathlib import Path

import pytest

from archiwista.errors import FormatRefusedError
from archiwista.formats import file_format, vector_source

_NATIVE = """!table
!version 300
!charset WindowsLatin2

Definition Table
  Type NATIVE Charset "WindowsLatin2"
  Fields 1
    name Char (254) ;
"""
_VIEW = """!table
!version 100
!charset Neutral

Open Table "lakes" Hide
Open Table "rivers" Hide

Create View lakes_rivers As
Select * From lakes, rivers
"""
_SEAMLESS = """!table
!version 300
!charset Neutral

Definition Table
  Type NATIVE Charset "Neutral"
  Fields 2
    Table Char (100) ;
    Description Char (25) ;
begin_metadata
"\\IsSeamless" = "TRUE"
end_metadata
"""
_RASTER = """!table
!version 300
!charset WindowsLatin2

Definition Table
  File "ortho.tif"
  Type "RASTER"
  (500000,300000) (0,0) Label "Pt 1",
  (500100,300000) (100,0) Label "Pt 2",
  (500100,299900) (100,100) Label "Pt 3"
"""
_LINKED = _NATIVE.replace("Type NATIVE", "Type LINKED")


def test_formats_mapinfo_native_table_opened_by_path(tmp_path: Path) -> None:
    """A native table is opened by its path (GDAL has no MapInfo prefix)."""
    # Arrange
    path = tmp_path / "Jeziora.TAB"
    path.write_text(_NATIVE, encoding="latin-1")

    # Act
    source = vector_source(path, file_format(path))

    # Assert
    assert source == str(path)


@pytest.mark.parametrize(
    "header",
    [_VIEW, _SEAMLESS, _RASTER, _LINKED, "<OGRVRTDataSource/>"],
    ids=["view", "seamless", "raster", "linked", "not_a_table"],
)
def test_formats_mapinfo_table_naming_other_files_refused(
    tmp_path: Path, header: str
) -> None:
    """Views, seamless, raster and linked tables are refused before GDAL."""
    # Arrange
    path = tmp_path / "plan.tab"
    path.write_text(header, encoding="latin-1")

    # Act / Assert
    with pytest.raises(FormatRefusedError):
        vector_source(path, file_format(path))


@pytest.mark.parametrize(
    "name",
    ["relative/plan.gpkg", "/vsicurl/http://example.com/plan.gpkg", '/data/a"b.gpkg'],
    ids=["relative", "virtual_file_system", "double_quote"],
)
def test_formats_vector_source_refuses_names_gdal_reads_otherwise(name: str) -> None:
    """Relative, ``/vsi`` and quote-breaking names never reach GDAL."""
    # Act / Assert
    with pytest.raises(FormatRefusedError):
        vector_source(Path(name), file_format(name))
