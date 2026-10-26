"""Formats of data files and opening them with one explicit driver (decision 3).

``FORMATS`` maps a file extension to its format: the kind of preview the
file can have and, for a file GDAL reads, the one driver allowed to open
it. Render processes, COG builds and the own-data reader open files with
GDAL only through ``open_raster`` and ``vector_source``, and only in the
sandbox (``archiwista.sandbox``):

- a raster opens with ``driver=``: content of another format under the
  file's name (VRT XML in ``a.tif``) is refused by GDAL, also after a
  ``WarpedVRT`` registered the VRT driver again in the process;
- a vector opens with its driver's prefix (``GPKG:``, ``GeoJSON:``) or,
  where GDAL has none (Shapefile, FlatGeobuf, MapInfo TAB), after its
  signature is checked: a Shapefile starts with the file code 9994, a
  FlatGeobuf with its magic (``fgb``, version 3, ``fgb``), and a MapInfo
  ``.tab`` must describe a native table (a view, a seamless table or a
  raster or linked table names other files). A file swapped between the
  check and the opening still meets ``GDAL_SKIP`` of the sandbox.

Sibling files stay out of reach (``EMPTY_DIR``), so a raster's
georeference comes from the file itself. Only the standard library is
imported here; rasterio is imported when a raster is opened, so the server
can use the table without loading GDAL.
"""

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any, Literal

from archiwista.errors import FormatRefusedError

if TYPE_CHECKING:
    from rasterio.io import DatasetReader

type FormatKind = Literal[
    "raster", "image", "vector", "points", "archive", "document", "auxiliary", "unknown"
]


@dataclass(frozen=True, slots=True)
class FileFormat:
    """A format of the table.

    Parameters
    ----------
    name : str
        Name shown to people, e.g. ``"GeoTIFF"``.
    kind : FormatKind
        What a preview can show: ``raster`` (values), ``image`` (colours),
        ``vector``, ``points``, ``archive`` (members), ``document``,
        ``auxiliary`` (a file serving another one) or ``unknown``.
    extensions : tuple[str, ...]
        Lower-case extensions with the dot.
    driver : str or None, optional
        The only GDAL driver allowed to open the file; ``None`` when GDAL
        never opens it.
    media_type : str or None, optional
        Its registered media type, the ``Content-Type`` of a download of it
        (``archiwista.services.files``); ``None`` when it has none.
    """

    name: str
    kind: FormatKind
    extensions: tuple[str, ...]
    driver: str | None = None
    media_type: str | None = None


FORMATS: tuple[FileFormat, ...] = (
    FileFormat(
        "GeoTIFF",
        "raster",
        (".tif", ".tiff"),
        "GTiff",
        "image/tiff; application=geotiff",
    ),
    FileFormat("ASCII Grid", "raster", (".asc",), "AAIGrid"),
    FileFormat("XYZ", "raster", (".xyz",), "XYZ"),
    FileFormat("JPEG", "image", (".jpg", ".jpeg"), "JPEG", "image/jpeg"),
    FileFormat("PNG", "image", (".png",), "PNG", "image/png"),
    FileFormat(
        "GeoPackage", "vector", (".gpkg",), "GPKG", "application/geopackage+sqlite3"
    ),
    FileFormat("Shapefile", "vector", (".shp",), "ESRI Shapefile"),
    FileFormat("GeoJSON", "vector", (".geojson",), "GeoJSON", "application/geo+json"),
    FileFormat("FlatGeobuf", "vector", (".fgb",), "FlatGeobuf"),
    FileFormat("MapInfo TAB", "vector", (".tab",), "MapInfo File"),
    FileFormat("LAZ", "points", (".laz",), media_type="application/vnd.laszip"),
    FileFormat("LAS", "points", (".las",), media_type="application/vnd.las"),
    FileFormat("ZIP", "archive", (".zip",), media_type="application/zip"),
    FileFormat("PDF", "document", (".pdf",), media_type="application/pdf"),
    FileFormat("TXT", "document", (".txt",), media_type="text/plain"),
    FileFormat("world file", "auxiliary", (".jgw", ".pgw", ".tfw", ".wld")),
)
UNKNOWN_FORMAT = FileFormat("unknown", "unknown", ())

_BY_EXTENSION = {
    extension: found for found in FORMATS for extension in found.extensions
}
_RASTER_KINDS = frozenset({"raster", "image"})
# Shapefile: file code 9994, big-endian. FlatGeobuf: magic, version 3.
_SHAPEFILE_SIGNATURE = (9994).to_bytes(4, "big")
_FLATGEOBUF_SIGNATURE = b"fgb\x03fgb"
# A native MapInfo table is a small text file; more is not a table header.
_TAB_HEADER_LIMIT_BYTES = 1024**2


def file_format(path: PurePath | str) -> FileFormat:
    """Return the format of a file by its extension (any letter case).

    Returns
    -------
    FileFormat
        The format, or ``UNKNOWN_FORMAT`` for an extension not in the table.
    """
    return _BY_EXTENSION.get(PurePath(path).suffix.lower(), UNKNOWN_FORMAT)


def open_raster(path: Path, fmt: FileFormat, **options: Any) -> "DatasetReader":
    """Open a raster or image file with its format's driver only.

    Parameters
    ----------
    path : Path
        Absolute path of the file (passed to GDAL as it is).
    fmt : FileFormat
        Its format (``file_format``), of kind ``raster`` or ``image``.
    **options : Any
        GDAL open options, e.g. ``OVERVIEW_LEVEL=0``.

    Returns
    -------
    rasterio.io.DatasetReader
        The open dataset; the caller closes it.

    Raises
    ------
    FormatRefusedError
        The format is not a raster one, or the path is not a plain one.
    rasterio.errors.RasterioIOError
        The file is not of that format (GDAL refuses it).
    """
    if fmt.kind not in _RASTER_KINDS or fmt.driver is None:
        raise FormatRefusedError(f"{fmt.name} is not read as a raster")
    _require_plain(path)
    import rasterio  # GDAL only in the processes that read files

    return rasterio.open(path, driver=fmt.driver, **options)


def vector_source(path: Path, fmt: FileFormat) -> str:
    """Return the name under which OGR opens a vector file with its driver only.

    Parameters
    ----------
    path : Path
        Absolute path of the file.
    fmt : FileFormat
        Its format (``file_format``), of kind ``vector``.

    Returns
    -------
    str
        ``GPKG:"<path>"`` (quoted: GDAL splits the name at ``:``),
        ``GeoJSON:<path>``, or the path of a Shapefile, FlatGeobuf or
        native MapInfo table whose signature was checked.

    Raises
    ------
    FormatRefusedError
        Not a vector format, a path that is not a plain one (or, for a
        GeoPackage, has a ``"``), a wrong signature or a MapInfo table other
        than a native one.
    OSError
        The file cannot be read.
    """
    if fmt.kind != "vector" or fmt.driver is None:
        raise FormatRefusedError(f"{fmt.name} is not read as a vector")
    _require_plain(path)
    if fmt.driver == "GPKG":
        if '"' in str(path):
            raise FormatRefusedError("a GeoPackage name with a double quote")
        return f'GPKG:"{path}"'
    if fmt.driver == "GeoJSON":
        return f"GeoJSON:{path}"
    if fmt.driver == "ESRI Shapefile":
        _require_signature(path, _SHAPEFILE_SIGNATURE, fmt)
    elif fmt.driver == "FlatGeobuf":
        _require_signature(path, _FLATGEOBUF_SIGNATURE, fmt)
    elif fmt.driver == "MapInfo File":
        _require_native_table(path)
    else:  # pragma: no cover - every vector driver of FORMATS is handled
        raise FormatRefusedError(f"{fmt.name} has no safe opening")
    return str(path)


def _require_plain(path: Path) -> None:
    """Refuse a relative path or a GDAL virtual file system name."""
    if not path.is_absolute() or path.as_posix().startswith("/vsi"):
        raise FormatRefusedError("not a plain absolute path")


def _require_signature(path: Path, signature: bytes, fmt: FileFormat) -> None:
    with path.open("rb") as stream:
        head = stream.read(len(signature))
    if head != signature:
        raise FormatRefusedError(f"not a {fmt.name} file (signature)")


def _require_native_table(path: Path) -> None:
    """Refuse a ``.tab`` that is not a native MapInfo table."""
    with path.open("rb") as stream:
        head = stream.read(_TAB_HEADER_LIMIT_BYTES + 1)
    if len(head) > _TAB_HEADER_LIMIT_BYTES:
        raise FormatRefusedError("MapInfo table header over 1 MiB")
    # Keywords are ASCII; Latin-1 maps every byte of any charset.
    lines = [line.strip().lower() for line in head.decode("latin-1").splitlines()]
    lines = [line for line in lines if line]
    if not lines or lines[0] != "!table":
        raise FormatRefusedError("not a MapInfo table")
    if any(_names_other_files(line) for line in lines):
        raise FormatRefusedError("MapInfo view or seamless table")
    try:
        start = lines.index("definition table")
    except ValueError:
        raise FormatRefusedError("MapInfo table without a definition") from None
    kind = next(
        (line.split()[1:2] for line in lines[start + 1 :] if line.startswith("type ")),
        [],
    )
    if [word.strip('"') for word in kind] != ["native"]:
        raise FormatRefusedError("MapInfo table other than a native one")


def _names_other_files(line: str) -> bool:
    """Whether a ``.tab`` line makes it a view or a seamless table."""
    if line.startswith(("open table", "create view")):
        return True
    return "\\isseamless" in line and "true" in line
