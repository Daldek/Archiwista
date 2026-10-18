"""Areas of interest: drawn, a map view, a sheet, or read from a file.

An area (SPEC 6.3, 9.2) is kept in the index (``IndexWriter.write_area``)
as a GeoJSON polygon in WGS84 with its countries (``GeoAdapter.countries``)
and its area in km², measured in the planar CRS of the first of its
countries in the order of ``PLANAR_CRS`` (PL → EPSG:2180, CZ → EPSG:5514;
decision 5), never in degrees. An invalid polygon is repaired
(``make_valid``), never simplified. The id comes from the geometry, so the
same area always gets the same id.

A file — GeoJSON, GeoPackage, or a Shapefile in a ZIP archive — is limited
before and while it is read (decision 9, SPEC 10.1): a body of at most
``AREA_BODY_LIMIT_BYTES`` (50 MB); an archive declaring at most
``UNPACKED_LIMIT_BYTES`` (200 MB) unpacked, with no member leaving its
directory, refused before unpacking; reading in ``archiwista.area_reader``,
a separate process killed after ``AREA_READ_TIMEOUT_S`` (30 s), started
with a minimal environment that keeps GDAL and PROJ offline; at most
``MAX_VERTICES`` (100 000) vertices. The file's CRS is converted to WGS84
with the producer's pinned operation (``GeoAdapter.transformer``, KA-6)
after densifying the edges. A path from the client is never opened: the
upload is written under a random name. The copy of the file stays in
``<user_data_dir>/areas/<id>/`` and is deleted at start-up once older than
``AREA_COPY_MAX_AGE`` (7 days); the area itself stays in the index.
"""

import contextlib
import hashlib
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import shapely
from shapely.geometry import mapping, shape

from archiwista.area_reader import MAX_VERTICES, UPLOAD_NAME
from archiwista.errors import (
    AreaTooComplexError,
    AreaTooLargeError,
    AreaUnreadableError,
    IndexQueryError,
)
from archiwista.index import AreaRecord
from archiwista.index.coverage import (
    PLANAR_CRS,
    SEGMENT_DEGREES,
    SEGMENT_METRES,
    WGS84,
    measure_coverage,
)
from archiwista.index.geometry import require_wgs84_area
from archiwista.messages import MESSAGES
from archiwista.paths import private_directory
from archiwista.sources import GeoAdapter, GeoJSONGeometry

type AreaSource = Literal["drawn", "view", "sheet", "file"]

AREA_SOURCES: tuple[AreaSource, ...] = ("drawn", "view", "sheet", "file")
AREA_BODY_LIMIT_BYTES = 50 * 1024**2
AREA_READ_TIMEOUT_S = 30.0
AREA_COPY_MAX_AGE = timedelta(days=7)
# Edges of an area together, in degrees: measuring densifies them every
# SEGMENT_DEGREES, so this bounds the work (a real area is far below it).
AREA_MAX_LENGTH_DEG = 5000.0
AREA_READER_COMMAND: tuple[str, ...] = (
    sys.executable,
    "-P",
    "-m",
    "archiwista.area_reader",
)
# Inherited by the reader: what Python and its libraries need to start on
# Linux and Windows, ARCHIWISTA_* (the application's own) and COVERAGE_*
# (measuring the reader in tests). Nothing about proxies, credentials, GDAL
# or the network: libcurl honours NO_PROXY even with GDAL_HTTP_PROXY set.
_READER_INHERITED = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LANGUAGE",
        "LD_LIBRARY_PATH",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROJ_DATA",
        "PROJ_LIB",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUTF8",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
        "XDG_DATA_HOME",
    }
)
_READER_INHERITED_PREFIXES = ("ARCHIWISTA_", "COVERAGE_", "LC_")
# GDAL and PROJ kept offline even if they try to fetch something: every
# request goes to a closed local port, gives up within a second, untried again.
_READER_FORCED = {
    "PROJ_NETWORK": "OFF",
    "GDAL_HTTP_PROXY": "127.0.0.1:9",
    "GDAL_HTTPS_PROXY": "127.0.0.1:9",
    "GDAL_HTTP_TIMEOUT": "1",
    "GDAL_HTTP_CONNECTTIMEOUT": "1",
    "GDAL_HTTP_MAX_RETRY": "0",
    "GDAL_HTTP_NETRC": "NO",
}
# Uploads being read; what a crash leaves is pruned like the copies.
INCOMING_DIR = ".incoming"
AREA_ID_CHARS = 16

_WGS84_NAMES = frozenset({WGS84, "OGC:CRS84"})
_MIB = 1024**2

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AreaFiles:
    """Where copies of area files are kept and how a file is read.

    Parameters
    ----------
    directory : Path
        ``<user_data_dir>/areas`` (``AppPaths.areas_dir``).
    command : tuple[str, ...], optional
        The reader process; it gets the upload's directory and, when asked
        for, ``--layer=<name>``.
    timeout_s : float, optional
        Wall-clock seconds after which the reader is killed.
    """

    directory: Path
    command: tuple[str, ...] = AREA_READER_COMMAND
    timeout_s: float = AREA_READ_TIMEOUT_S


def check_body_size(size: int) -> None:
    """Refuse a body (or its declared length) over ``AREA_BODY_LIMIT_BYTES``.

    Raises
    ------
    AreaTooLargeError
        ``size`` is over the limit.
    """
    if size > AREA_BODY_LIMIT_BYTES:
        raise AreaTooLargeError(
            MESSAGES["area_body_too_large"].format(
                limit_mb=AREA_BODY_LIMIT_BYTES // _MIB
            )
        )


@dataclass(frozen=True, slots=True)
class FileGeometry:
    """The polygons the reader process found in a file, in the file's CRS.

    ``directory`` holds the file's copy until ``keep_copy`` or
    ``discard_copy``; ``vertices`` counts the positions as read.
    """

    geometry: GeoJSONGeometry
    crs: str
    geographic: bool
    vertices: int
    directory: Path


def area_crs(countries: Iterable[str]) -> str | None:
    """Return the planar CRS an area is measured in, ``None`` without one.

    The CRS of the first of the area's countries in the order of
    ``PLANAR_CRS`` (PL, then CZ).
    """
    codes = {country.upper() for country in countries}
    return next((crs for country, crs in PLANAR_CRS.items() if country in codes), None)


def count_vertices(geometry: GeoJSONGeometry) -> int:
    """Count the positions of a GeoJSON polygon, each ring's closing one too."""
    coordinates: list[Any] = cast(list[Any], geometry.get("coordinates") or [])
    polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
    return sum(len(ring) for polygon in polygons for ring in polygon)


def area_id(geometry: GeoJSONGeometry) -> str:
    """Return the id of an area: a digest of its WGS84 geometry."""
    text = json.dumps(geometry, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:AREA_ID_CHARS]


def area_from_geometry(
    geometry: GeoJSONGeometry,
    *,
    adapter: GeoAdapter,
    source: AreaSource,
    name: str | None = None,
    vertices: int | None = None,
    now: datetime | None = None,
) -> AreaRecord:
    """Return the area of a WGS84 polygon: its id, geometry, km² and countries.

    Parameters
    ----------
    geometry : GeoJSONGeometry
        ``Polygon`` or ``MultiPolygon`` in WGS84 (longitude, latitude).
    adapter : GeoAdapter
        The producer's countries and pinned operations.
    source : AreaSource
        How the area was chosen: ``drawn``, ``view``, ``sheet`` or ``file``.
    name : str or None, optional
        Name shown with the area, e.g. a sheet code or a file's name.
    vertices : int or None, optional
        Positions counted before the geometry was converted (a file);
        counted in ``geometry`` when omitted.
    now : datetime or None, optional
        Creation time; the current time when omitted.

    Raises
    ------
    IndexQueryError
        Not a polygon in WGS84, or no area left after repair.
    AreaTooComplexError
        More than ``MAX_VERTICES`` positions, or edges longer together
        than ``AREA_MAX_LENGTH_DEG``.
    ProducerError
        The producer has no pinned operation to the planar CRS.
    """
    require_wgs84_area(geometry)
    count = count_vertices(geometry) if vertices is None else vertices
    if count > MAX_VERTICES:
        raise AreaTooComplexError(
            MESSAGES["area_too_many_vertices"].format(
                vertices=count, limit=MAX_VERTICES
            )
        )
    try:
        polygon = shapely.force_2d(shape(geometry))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise IndexQueryError(MESSAGES["index_invalid_area"]) from error
    length = float(shapely.length(polygon))
    if length > AREA_MAX_LENGTH_DEG:
        raise AreaTooComplexError(
            MESSAGES["area_too_long"].format(
                length=f"{length:.0f}", limit=f"{AREA_MAX_LENGTH_DEG:.0f}"
            )
        )
    if not shapely.is_valid(polygon):
        polygon = _polygons(shapely.make_valid(polygon))
    if polygon.is_empty or polygon.area <= 0:
        raise IndexQueryError(MESSAGES["area_empty"])
    stored = _plain(polygon)
    bounds = require_wgs84_area(stored)
    countries = tuple(adapter.countries(bounds))
    crs = area_crs(countries)
    area_km2 = None
    if crs is not None:
        measure = measure_coverage(stored, (), crs=crs, transformer=adapter.transformer)
        area_km2 = measure.area_km2
    return AreaRecord(
        id=area_id(stored),
        source=source,
        geometry=stored,
        # The index keeps whole seconds; the answer must match what it keeps.
        created_at=(now or datetime.now(UTC)).replace(microsecond=0),
        area_km2=area_km2,
        countries=countries,
        name=name,
    )


def read_area_file(
    files: AreaFiles, content: bytes, *, layer: str | None = None
) -> FileGeometry:
    """Read the polygons of an uploaded file in the reader process.

    The upload is written under a random name in a fresh directory, which
    then holds the file's copy (see ``FileGeometry``); it is removed when
    the file is refused.

    Parameters
    ----------
    files : AreaFiles
        Where the copy goes and how the file is read.
    content : bytes
        The uploaded file (its size is checked by the caller).
    layer : str or None, optional
        Layer of a GeoPackage or Shapefile name in an archive.

    Raises
    ------
    AreaTooLargeError
        An archive declares more than ``UNPACKED_LIMIT_BYTES`` unpacked.
    AreaUnreadableError
        Unknown format, unsafe or broken archive, layer, CRS, no polygon,
        or the reader killed after ``AreaFiles.timeout_s``.
    AreaTooComplexError
        More than ``MAX_VERTICES`` positions.
    """
    if not content:
        raise AreaUnreadableError(MESSAGES["area_format_unknown"])
    # Copies of the user's files: the areas directory is the user's alone.
    private_directory(files.directory)
    directory = files.directory / INCOMING_DIR / secrets.token_hex(8)
    directory.mkdir(parents=True)
    try:
        (directory / UPLOAD_NAME).write_bytes(content)
        answer = _run_reader(files, directory, layer)
        return FileGeometry(
            geometry=answer["geometry"],
            crs=str(answer["crs"]),
            geographic=bool(answer["geographic"]),
            vertices=int(answer["vertices"]),
            directory=directory,
        )
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def area_from_file(
    found: FileGeometry,
    *,
    adapter: GeoAdapter,
    name: str | None = None,
    now: datetime | None = None,
) -> AreaRecord:
    """Return the area of a file's polygons, converted to WGS84.

    Edges are densified in the file's CRS (``SEGMENT_METRES``, or
    ``SEGMENT_DEGREES`` in a geographic CRS; at most about ``MAX_VERTICES``
    more positions) before the pinned operation moves them.

    Raises
    ------
    ProducerError
        The producer has no pinned operation from the file's CRS.
    IndexQueryError
        The converted area is not in WGS84 bounds.
    AreaTooComplexError
        Edges too long to measure (see ``area_from_geometry``).
    """
    geometry = found.geometry
    if found.crs.upper() not in _WGS84_NAMES:
        polygon = shape(geometry)
        step = SEGMENT_DEGREES if found.geographic else SEGMENT_METRES
        step = max(step, float(shapely.length(polygon)) / MAX_VERTICES)
        operation = adapter.transformer(found.crs, WGS84)
        moved = shapely.transform(
            shapely.segmentize(polygon, step), operation.transform, interleaved=False
        )
        geometry = _plain(moved)
    return area_from_geometry(
        geometry,
        adapter=adapter,
        source="file",
        name=name,
        vertices=found.vertices,
        now=now,
    )


def keep_copy(files: AreaFiles, found: FileGeometry, area: str) -> Path:
    """Keep a read file's copy as ``<directory>/<area>/``, replacing an older one.

    Returns
    -------
    Path
        The copy's directory.
    """
    target = files.directory / area
    if target.is_dir():
        shutil.rmtree(target)
    try:
        os.replace(found.directory, target)
    except OSError:
        if not target.is_dir():
            raise
        # The same area was uploaded at the same time: one copy is enough.
        discard_copy(found)
    return target


def discard_copy(found: FileGeometry) -> None:
    """Remove a read file's copy that is not kept."""
    shutil.rmtree(found.directory, ignore_errors=True)


def prune_area_copies(
    directory: Path,
    *,
    now: datetime | None = None,
    max_age: timedelta = AREA_COPY_MAX_AGE,
) -> int:
    """Delete copies of area files (and unfinished uploads) older than ``max_age``.

    Called at start-up; the areas stay in the index. Nothing outside
    ``directory`` is touched: a link is removed, never followed.

    Returns
    -------
    int
        Copies removed.
    """
    cutoff = (now or datetime.now(UTC)).timestamp() - max_age.total_seconds()
    removed = 0
    for parent in (directory, directory / INCOMING_DIR):
        for entry in _entries(parent):
            if parent == directory and entry.name == INCOMING_DIR:
                continue
            try:
                if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path)
                else:
                    os.unlink(entry.path)
            except OSError as error:
                logger.warning("cannot remove the area copy %s: %s", entry.path, error)
                continue
            removed += 1
    return removed


def _entries(directory: Path) -> Sequence[os.DirEntry[str]]:
    try:
        with os.scandir(directory) as entries:
            return list(entries)
    except FileNotFoundError:
        return ()
    except OSError as error:
        logger.warning("cannot list the area copies in %s: %s", directory, error)
        return ()


def _run_reader(files: AreaFiles, directory: Path, layer: str | None) -> dict[str, Any]:
    """Run the reader on a directory and return its answer, or raise its refusal."""
    command = [*files.command, str(directory.absolute())]
    if layer is not None:
        command.append(f"--layer={layer}")
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=directory,
        env=_reader_environment(),
        **_own_group(),
    )
    try:
        output, _ = process.communicate(timeout=files.timeout_s)
    except subprocess.TimeoutExpired:
        _kill(process)
        process.communicate()
        seconds = f"{files.timeout_s:g}"
        raise AreaUnreadableError(
            MESSAGES["area_read_timeout"].format(seconds=seconds)
        ) from None
    except BaseException:
        _kill(process)
        process.wait()
        raise
    crashed = AreaUnreadableError(
        MESSAGES["area_reader_crashed"].format(code=process.returncode)
    )
    lines = output.decode("utf-8", "replace").strip().splitlines()
    if process.returncode != 0 or not lines:
        raise crashed
    try:
        answer = json.loads(lines[-1])
    except ValueError as error:
        raise crashed from error
    if not isinstance(answer, dict):
        raise crashed
    code = answer.get("error")
    if code is None:
        return answer
    detail = str(answer.get("detail") or MESSAGES["area_format_unknown"])
    if code == "area_too_large":
        raise AreaTooLargeError(detail)
    if code == "area_too_complex":
        raise AreaTooComplexError(detail)
    layers = tuple(str(item) for item in answer.get("layers") or ())
    raise AreaUnreadableError(detail, layers=layers)


def _reader_environment() -> dict[str, str]:
    """Return the reader's environment: allowed inherited variables, forced ones."""
    kept = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _READER_INHERITED
        or name.upper().startswith(_READER_INHERITED_PREFIXES)
    }
    return {**kept, **_READER_FORCED}


def _own_group() -> dict[str, Any]:
    """Start the reader in its own process group, killed as a whole."""
    if sys.platform == "win32":  # pragma: no cover - Windows
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":  # pragma: no cover - Windows
        process.kill()
        return
    with contextlib.suppress(ProcessLookupError):  # ended in the meantime
        os.killpg(process.pid, signal.SIGKILL)


def _polygons(geometry: Any) -> Any:
    """Return the polygons of a repaired geometry (``make_valid`` may add lines)."""
    parts = shapely.get_parts(shapely.get_parts(geometry))
    polygons = [part for part in parts if part.geom_type == "Polygon" and part.area > 0]
    return shapely.union_all(polygons) if polygons else shapely.Polygon()


def _plain(geometry: Any) -> GeoJSONGeometry:
    """GeoJSON of a shapely geometry with lists, as the index stores it."""
    plain: GeoJSONGeometry = json.loads(json.dumps(mapping(geometry)))
    return plain
