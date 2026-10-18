"""Read an uploaded area file in a worker process (SPEC 10.1, plan step 9c).

``python -m archiwista.area_reader <directory> [--layer NAME]`` reads
``<directory>/upload``: a GeoJSON file, a GeoPackage, or a ZIP archive with
one Shapefile (``.shp``, ``.shx``, ``.dbf``, ``.prj``). The server runs it in
a separate process and kills it after the time limit, so GDAL reading
untrusted input can neither crash nor block the server.

The upload becomes the area's local copy in the same directory
(``area.geojson``, ``area.gpkg``, or the Shapefile's parts as
``area.shp``…); no name from the client is ever used as a path. An archive
is checked before anything is unpacked: at most ``MAX_MEMBERS`` members,
together at most ``UNPACKED_LIMIT_BYTES`` as their headers declare, none
leaving the directory, no link and nothing encrypted; only the chosen
Shapefile's parts are unpacked.

The answer is one JSON line on stdout. Either the union of the file's
polygons in the file's CRS — ``geometry``, ``crs``, ``geographic``,
``format``, ``layer``, ``features``, ``vertices`` (coordinate positions of
the polygons as read, at most ``MAX_VERTICES``) — or a refusal: ``error``
(``area_unreadable``, ``area_too_large`` or ``area_too_complex``), a Polish
``detail`` and, for a file with several layers, ``layers``.

GDAL (``pyogrio``) and PROJ (``pyproj``) are imported only when a file is
read, so the server and the command line, which share the limits of this
module, never load them for it.
"""

import argparse
import json
import os
import re
import shutil
import stat
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import shapely
from shapely.geometry import mapping

from archiwista.messages import MESSAGES

UPLOAD_NAME = "upload"
COPY_STEM = "area"
MAX_VERTICES = 100_000
UNPACKED_LIMIT_BYTES = 200 * 1024**2
MAX_MEMBERS = 1000
# Bytes read to tell the format: magic numbers, or the ``{`` of JSON after
# a byte order mark and whitespace.
_HEAD_BYTES = 1024

_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")
_SQLITE_MAGIC = b"SQLite format 3\x00"
_UTF8_BOM = b"\xef\xbb\xbf"
_REQUIRED_PARTS = (".shp", ".shx", ".dbf", ".prj")
_PARTS = (*_REQUIRED_PARTS, ".cpg")
_POLYGON_TYPE_IDS = (3, 6)  # shapely: Polygon, MultiPolygon
_DRIVE = re.compile(r"^[A-Za-z]:")
_DETAIL_CHARS = 300
_MIB = 1024**2


class AreaFileError(Exception):
    """A refusal of the file: problem code, Polish detail, layers to choose."""

    def __init__(self, code: str, detail: str, *, layers: Sequence[str] = ()) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.layers = tuple(layers)

    def answer(self) -> dict[str, Any]:
        """Return the refusal as the worker prints it."""
        answer: dict[str, Any] = {"error": self.code, "detail": self.detail}
        if self.layers:
            answer["layers"] = list(self.layers)
        return answer


@dataclass
class _Shapefile:
    """One Shapefile in an archive: its name and its parts by extension."""

    stem: str
    parts: dict[str, zipfile.ZipInfo] = field(default_factory=dict)


def read_area(directory: Path, *, layer: str | None = None) -> dict[str, Any]:
    """Read ``directory/upload`` and keep it as the area's copy.

    Parameters
    ----------
    directory : Path
        A fresh directory holding only ``upload``.
    layer : str or None, optional
        Layer of a GeoPackage or Shapefile name in an archive, needed when
        the file has several.

    Returns
    -------
    dict[str, Any]
        The union of the polygons in the file's CRS (see the module).

    Raises
    ------
    AreaFileError
        The file is refused: unknown format, unsafe or too large archive,
        layer, CRS, no polygon, too many vertices.
    """
    # GDAL and PROJ only when a file is read (see the module).
    import pyogrio.raw
    import pyproj

    upload = directory / UPLOAD_NAME
    with upload.open("rb") as stream:
        head = stream.read(_HEAD_BYTES)
    shown: str | None = None
    read_layer: str | None = None
    if head[:4] in _ZIP_MAGIC:
        path, shown = _unpack_shapefile(upload, directory, layer)
        kind = "shapefile"
    elif head.startswith(_SQLITE_MAGIC):
        path = upload.rename(directory / f"{COPY_STEM}.gpkg")
        read_layer = shown = _gpkg_layer(path, layer)
        kind = "gpkg"
    elif head.removeprefix(_UTF8_BOM).lstrip()[:1] == b"{":
        path = upload.rename(directory / f"{COPY_STEM}.geojson")
        kind = "geojson"
    else:
        raise _unreadable("area_format_unknown")
    crs = pyogrio.read_info(path, layer=read_layer).get("crs")
    if not crs:
        raise _unreadable("area_crs_missing")
    _, _, wkb, _ = pyogrio.raw.read(
        path, layer=read_layer, read_geometry=True, columns=[], force_2d=True
    )
    geometry, features, vertices = _union(shapely.from_wkb(wkb))
    return {
        "geometry": mapping(geometry),
        "crs": str(crs),
        "geographic": bool(pyproj.CRS.from_user_input(crs).is_geographic),
        "format": kind,
        "layer": shown,
        "features": features,
        "vertices": vertices,
    }


def _union(geometries: Any) -> tuple[Any, int, int]:
    """Return the union of the file's polygons, their count and positions.

    Features without a geometry are skipped; any other geometry type
    refuses the file, as does a count of positions above ``MAX_VERTICES``.
    Invalid polygons are repaired (``make_valid``), never simplified.
    """
    present = np.array(
        [item for item in geometries if item is not None and not item.is_empty],
        dtype=object,
    )
    if present.size == 0:
        raise _unreadable("area_no_polygon")
    other = present[~np.isin(shapely.get_type_id(present), _POLYGON_TYPE_IDS)]
    if other.size:
        types = ", ".join(sorted({item.geom_type for item in other}))
        raise _unreadable("area_not_polygonal", types=types)
    vertices = int(shapely.get_num_coordinates(present).sum())
    if vertices > MAX_VERTICES:
        raise AreaFileError(
            "area_too_complex",
            MESSAGES["area_too_many_vertices"].format(
                vertices=vertices, limit=MAX_VERTICES
            ),
        )
    parts = shapely.get_parts(shapely.get_parts(shapely.make_valid(present)))
    polygons = parts[
        (shapely.get_type_id(parts) == _POLYGON_TYPE_IDS[0]) & ~shapely.is_empty(parts)
    ]
    union = shapely.union_all(polygons)
    if union.is_empty or shapely.get_type_id(union) not in _POLYGON_TYPE_IDS:
        raise _unreadable("area_no_polygon")
    return union, int(present.size), vertices


def _gpkg_layer(path: Path, layer: str | None) -> str:
    """Choose the layer to read: the one asked for, or the only one with geometry."""
    import pyogrio

    listed = pyogrio.list_layers(path)
    names = [str(name) for name, geometry in listed if geometry is not None]
    if layer is not None:
        if layer not in names:
            raise _unreadable(
                "area_layer_unknown",
                layers=names,
                layer=layer,
                names=", ".join(names) or "—",
            )
        return layer
    if not names:
        raise _unreadable("area_layers_none")
    if len(names) > 1:
        raise _unreadable("area_layers_many", layers=names, names=", ".join(names))
    return names[0]


def _unpack_shapefile(
    upload: Path, directory: Path, layer: str | None
) -> tuple[Path, str]:
    """Check the whole archive, then unpack one Shapefile's parts as ``area.*``.

    Returns the copy's ``.shp`` and the Shapefile's name in the archive.
    """
    try:
        with zipfile.ZipFile(upload) as archive:
            members = archive.infolist()
            _check_members(members)
            chosen = _shapefile(members, layer)
            for suffix, member in chosen.parts.items():
                target = directory / f"{COPY_STEM}{suffix}"
                with archive.open(member) as source, target.open("xb") as copy:
                    shutil.copyfileobj(source, copy, _MIB)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError) as error:
        raise _unreadable("area_archive_broken", detail=_describe(error)) from error
    except RuntimeError as error:  # e.g. a member needing a password
        raise _unreadable("area_archive_broken", detail=_describe(error)) from error
    upload.unlink()
    return directory / f"{COPY_STEM}.shp", chosen.stem


def _check_members(members: Sequence[zipfile.ZipInfo]) -> None:
    """Refuse an archive before unpacking: count, declared size, names, kinds."""
    if len(members) > MAX_MEMBERS:
        raise _unreadable("area_archive_members", count=len(members), limit=MAX_MEMBERS)
    declared = sum(member.file_size for member in members)
    if declared > UNPACKED_LIMIT_BYTES:
        raise AreaFileError(
            "area_too_large",
            MESSAGES["area_archive_too_large"].format(
                size_mb=_megabytes(declared), limit_mb=UNPACKED_LIMIT_BYTES // _MIB
            ),
        )
    seen: set[str] = set()
    for member in members:
        name = member.filename
        if not _inside(name):
            raise _unreadable("area_archive_unsafe", member=name)
        if stat.S_ISLNK(member.external_attr >> 16):
            raise _unreadable("area_archive_link", member=name)
        if member.flag_bits & 0x1:
            raise _unreadable("area_archive_encrypted", member=name)
        key = name.replace("\\", "/").rstrip("/").casefold()
        if key in seen:
            raise _unreadable("area_archive_duplicate", member=name)
        seen.add(key)


def _inside(name: str) -> bool:
    """Whether an archive member stays inside the directory it is unpacked to."""
    path = name.replace("\\", "/")
    if not path or "\x00" in path or path.startswith("/") or _DRIVE.match(path):
        return False
    return ".." not in path.split("/")


def _shapefile(members: Sequence[zipfile.ZipInfo], layer: str | None) -> _Shapefile:
    """Choose the Shapefile to read: the one asked for, or the only one."""
    found: dict[tuple[str, str], _Shapefile] = {}
    for member in members:
        if member.is_dir():
            continue
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if "__MACOSX" in path.parts or path.name.startswith("._"):
            continue  # resource forks a Mac adds to an archive
        suffix = path.suffix.casefold()
        if suffix not in _PARTS:
            continue
        key = (str(path.parent).casefold(), path.stem.casefold())
        found.setdefault(key, _Shapefile(path.stem)).parts[suffix] = member
    shapefiles = [item for item in found.values() if ".shp" in item.parts]
    names = sorted(item.stem for item in shapefiles)
    if layer is not None:
        shapefiles = [item for item in shapefiles if item.stem == layer]
        if not shapefiles:
            raise _unreadable(
                "area_layer_unknown",
                layers=names,
                layer=layer,
                names=", ".join(names) or "—",
            )
    if not shapefiles:
        raise _unreadable("area_shapefile_missing")
    if len(shapefiles) > 1:
        raise _unreadable("area_layers_many", layers=names, names=", ".join(names))
    chosen = shapefiles[0]
    missing = [suffix for suffix in _REQUIRED_PARTS if suffix not in chosen.parts]
    if missing:
        raise _unreadable(
            "area_shapefile_parts", layer=chosen.stem, parts=", ".join(missing)
        )
    return chosen


def _unreadable(
    message: str, *, layers: Sequence[str] = (), **values: object
) -> AreaFileError:
    return AreaFileError(
        "area_unreadable", MESSAGES[message].format(**values), layers=layers
    )


def _megabytes(size: int) -> str:
    return f"{size / _MIB:.1f}"


def _describe(error: BaseException, *, directory: Path | None = None) -> str:
    text = str(error).strip() or type(error).__name__
    if directory is not None:
        # GDAL names the file by its path: keep only the copy's own name.
        text = text.replace(f"{directory}{os.sep}", "")
    return text[:_DETAIL_CHARS]


def main(argv: Sequence[str] | None = None) -> int:
    """Read the upload of a directory and print the answer (see the module).

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        ``<directory> [--layer NAME]``; ``sys.argv`` when omitted.

    Returns
    -------
    int
        ``0`` whenever an answer was printed, also a refusal.
    """
    parser = argparse.ArgumentParser(prog="python -m archiwista.area_reader")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--layer")
    arguments = parser.parse_args(argv)
    try:
        answer = read_area(arguments.directory, layer=arguments.layer)
    except AreaFileError as error:
        answer = error.answer()
    except Exception as error:  # GDAL or the archive refusing untrusted input
        text = _describe(error, directory=arguments.directory)
        detail = MESSAGES["area_read_failed"].format(detail=text)
        answer = {"error": "area_unreadable", "detail": detail}
    sys.stdout.write(json.dumps(answer) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
