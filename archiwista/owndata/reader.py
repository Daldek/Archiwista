"""Reader of own-data files: a sandboxed process, one JSON line per file (decision 8).

``python -P -m archiwista.owndata.reader --config-file F --data-dir D``
imports GDAL, prints ``{"ready": true}`` and then answers every request line
``{"path": "<absolute path>"}`` of its standard input with one line: the
file's ``OwnFileInfo`` as JSON. It opens a file only through the format
table (``archiwista.formats``: explicit driver, prefix or checked
signature; a MapInfo table only as a native one) in the sandbox of
``archiwista.sandbox``, so a file never makes it read another file or an
address, and it writes nothing next to the file: a GeoPackage is read
through ``consistent_sqlite_read``, with its copies in the process's work
directory (``process_work_dir``). It reads what the scan keeps: the GDAL
driver, the layers with their geometry type, feature count, fields, CRS and
extent, the parameters of a raster; never pixels or features.

``OwnReader`` runs that process from a scan: it gives each file
``OWN_READ_TIMEOUT_S`` (30 s) and ``OWN_READER_MEMORY_BYTES`` of address
space, kills the process on a file it does not finish (``timeout``) and
starts a new one for the next file. Importing this module loads no GDAL: the
reading code imports pyogrio and rasterio in the process only.
"""

import argparse
import contextlib
import json
import logging
import math
import os
import queue
import re
import subprocess
import sys
import threading
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal, Self

from archiwista.config import AppPaths
from archiwista.errors import FormatRefusedError, OwnReaderError
from archiwista.formats import FileFormat, FormatKind, file_format, vector_source
from archiwista.owndata.content import SqliteRead, read_sqlite
from archiwista.owndata.formats import fileset_members, is_sqlite
from archiwista.sandbox import (
    child_limits,
    kill_untrusted,
    process_work_dir,
    untrusted_env,
)

if TYPE_CHECKING:
    from rasterio.crs import CRS

type BBox = tuple[float, float, float, float]
type ReadError = Literal["unsupported_format", "unreadable", "timeout", "memory_limit"]

OWN_READER_COMMAND: tuple[str, ...] = (
    sys.executable,
    "-P",
    "-m",
    "archiwista.owndata.reader",
)
OWN_READ_TIMEOUT_S = 30.0
OWN_READER_START_TIMEOUT_S = 60.0
OWN_READER_MEMORY_BYTES = 2 * 1024**3
# Layers listed of one file; GDAL opens the file once per layer.
MAX_LAYERS = 1000

_READY = {"ready": True}
_STOP_TIMEOUT_S = 10.0
_DETAIL_CHARS = 300

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FieldInfo:
    """A field of a vector layer.

    Parameters
    ----------
    name : str
        Field name.
    type : str
        OGR type without its prefix (``String``, ``Integer``, ``Real``,
        ``Date``...), or its subtype when it has one (``Boolean``, ``JSON``).
    """

    name: str
    type: str


@dataclass(frozen=True, slots=True)
class LayerInfo:
    """A vector layer as GDAL reads it.

    Parameters
    ----------
    name : str
        Layer name.
    geometry_type : str or None
        OGR geometry type (``Point``, ``LineString``, ``Polygon``,
        ``Unknown``...); ``None`` for a table without geometry.
    feature_count : int or None
        Number of features; ``None`` when GDAL cannot count them.
    fields : tuple[FieldInfo, ...]
        The attribute fields.
    crs : str or None
        ``EPSG:<code>`` when GDAL identifies it, else WKT; ``None``: none.
    bbox : BBox or None
        ``(min_x, min_y, max_x, max_y)`` in ``crs``, x east; ``None`` for an
        empty layer or one without geometry.
    """

    name: str
    geometry_type: str | None
    feature_count: int | None
    fields: tuple[FieldInfo, ...]
    crs: str | None
    bbox: BBox | None


@dataclass(frozen=True, slots=True)
class RasterInfo:
    """Parameters of a raster or image.

    Parameters
    ----------
    width, height : int
        Size in pixels.
    bands : int
        Number of bands.
    dtype : str
        Data type of the first band (``uint8``, ``float32``...).
    nodata : float or None
        The no-data value of the first band (may be NaN); ``None``: none.
    pixel_size : tuple[float, float] or None
        Pixel width and height in CRS units; ``None`` without georeference.
    georeferenced : bool
        Whether the file itself places its pixels (GeoTIFF tags, an ASC
        header); a world file or ``.aux.xml`` next to it is never read.
    """

    width: int
    height: int
    bands: int
    dtype: str
    nodata: float | None
    pixel_size: tuple[float, float] | None
    georeferenced: bool


@dataclass(frozen=True, slots=True)
class OwnFileInfo:
    """What the reader learned about an own-data file.

    Parameters
    ----------
    kind : FormatKind
        Kind of its format by extension (``archiwista.formats``).
    driver : str or None
        The GDAL driver that read it; ``None`` for a file GDAL does not read
        (no driver in the format table): unrecognised for the scan.
    members : tuple[str, ...]
        Names of its files next to it, the file first: every member of a
        Shapefile or native MapInfo table, else the file alone.
    layers : tuple[LayerInfo, ...]
        Vector layers (at most ``MAX_LAYERS``).
    raster : RasterInfo or None
        Raster parameters.
    native_crs : str or None
        The CRS of the file: of the raster, or the one CRS of every layer
        with geometry (``None`` when they differ or have none).
    native_bbox : BBox or None
        Extent in ``native_crs`` (the union of the layers' extents), x east;
        ``None`` without georeference or when the layers' CRSs differ.
    feature_count : int or None
        Features of all layers; ``None`` for a raster or an unknown count.
    error : {"unsupported_format", "unreadable", "timeout", "memory_limit"} or None
        Why the file was not read: refused by the format table (a view,
        VRT content under a data name), refused or failed by GDAL, killed
        after the time limit, or out of memory.
    detail : str or None
        English message of the library behind ``error``, without the
        file's directory.
    """

    kind: FormatKind
    driver: str | None
    members: tuple[str, ...]
    layers: tuple[LayerInfo, ...] = ()
    raster: RasterInfo | None = None
    native_crs: str | None = None
    native_bbox: BBox | None = None
    feature_count: int | None = None
    error: ReadError | None = None
    detail: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Return the information as a JSON object (the reader's answer)."""
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        """Rebuild the information from ``to_json``.

        Raises
        ------
        KeyError, TypeError, ValueError
            ``data`` is not such an object.
        """
        raster = data["raster"]
        return cls(
            kind=data["kind"],
            driver=data["driver"],
            members=tuple(str(name) for name in data["members"]),
            layers=tuple(
                LayerInfo(
                    name=layer["name"],
                    geometry_type=layer["geometry_type"],
                    feature_count=layer["feature_count"],
                    fields=tuple(FieldInfo(**field) for field in layer["fields"]),
                    crs=layer["crs"],
                    bbox=_bbox(layer["bbox"]),
                )
                for layer in data["layers"]
            ),
            raster=None
            if raster is None
            else RasterInfo(
                width=raster["width"],
                height=raster["height"],
                bands=raster["bands"],
                dtype=raster["dtype"],
                nodata=raster["nodata"],
                pixel_size=None
                if raster["pixel_size"] is None
                else (raster["pixel_size"][0], raster["pixel_size"][1]),
                georeferenced=raster["georeferenced"],
            ),
            native_crs=data["native_crs"],
            native_bbox=_bbox(data["native_bbox"]),
            feature_count=data["feature_count"],
            error=data["error"],
            detail=data["detail"],
        )


class OwnReader:
    """The reader process of own-data files, one file at a time.

    The process starts with the first ``read`` and serves the next ones; a
    file it does not finish within ``timeout_s`` gets ``timeout``, a process
    that ends gets ``unreadable``, and the next file goes to a new process.
    Not for concurrent use; ``close`` (or the end of a ``with`` block) ends
    the process.

    Parameters
    ----------
    paths : AppPaths
        Local application data; the process keeps its copies in its work
        directory under ``AppPaths.work_dir``.
    timeout_s : float, optional
        Seconds for one file.
    memory_bytes : int or None, optional
        Address space of the process (``RLIMIT_AS``); ``None``: unlimited.
    command : Sequence[str], optional
        The process, ``OWN_READER_COMMAND``; it gets ``--config-file`` and
        ``--data-dir``.
    start_timeout_s : float, optional
        Seconds for the process to import GDAL and say it is ready.
    """

    def __init__(
        self,
        paths: AppPaths,
        *,
        timeout_s: float = OWN_READ_TIMEOUT_S,
        memory_bytes: int | None = OWN_READER_MEMORY_BYTES,
        command: Sequence[str] = OWN_READER_COMMAND,
        start_timeout_s: float = OWN_READER_START_TIMEOUT_S,
    ) -> None:
        self._argv = [
            *command,
            "--config-file",
            str(paths.config_file),
            "--data-dir",
            str(paths.data_dir),
        ]
        self._timeout_s = timeout_s
        self._memory_bytes = memory_bytes
        self._start_timeout_s = start_timeout_s
        self._process: subprocess.Popen[bytes] | None = None
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        self._pump: threading.Thread | None = None

    def read(self, path: Path) -> OwnFileInfo:
        """Read one file in the reader process.

        Parameters
        ----------
        path : Path
            Absolute path of the file (its real path: members of a set are
            looked up next to it).

        Returns
        -------
        OwnFileInfo
            What the process read, or ``timeout`` / ``unreadable`` when it
            did not answer.

        Raises
        ------
        OwnReaderError
            The process could not start, took no request or answered
            something else than a file's information.
        """
        request = json.dumps({"path": str(path)}).encode("ascii") + b"\n"
        if not self._send(request):  # the process ended after its last answer
            self._stop()
            if not self._send(request):
                self._stop()
                raise OwnReaderError("the own-data reader takes no requests")
        try:
            line = self._lines.get(timeout=self._timeout_s)
        except queue.Empty:
            logger.warning(
                "own-data reader killed after %ss: %s", self._timeout_s, path
            )
            self._stop()
            return _failed(path, "timeout")
        if line is None:
            code = self._stop()
            logger.warning("own-data reader ended (%s) on %s", code, path)
            return _failed(path, "unreadable", f"reader process ended ({code})")
        try:
            info = OwnFileInfo.from_json(json.loads(line))
        except (KeyError, TypeError, ValueError) as error:
            self._stop()
            raise OwnReaderError("the own-data reader answered out of turn") from error
        if info.error == "memory_limit":
            self._stop()  # the process leaves after it; the next file gets a new one
        return info

    def close(self) -> None:
        """End the reader process (it finishes at the end of its input)."""
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            with contextlib.suppress(OSError):
                process.stdin.close()
        try:
            process.wait(timeout=_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            kill_untrusted(process)
        self._stop()

    def __enter__(self) -> Self:
        """Return the reader."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """End the reader process."""
        self.close()

    def _send(self, request: bytes) -> bool:
        """Write a request to the ready process; ``False`` if it is gone."""
        stdin = self._ready_process().stdin
        assert stdin is not None
        try:
            stdin.write(request)
            stdin.flush()
        except OSError:
            return False
        return True

    def _ready_process(self) -> subprocess.Popen[bytes]:
        """Return the running process, or start one and wait until it is ready."""
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._stop()
        try:
            process = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=untrusted_env(),
                **child_limits(self._memory_bytes),
            )
        except OSError as error:
            raise OwnReaderError("the own-data reader could not be run") from error
        self._process = process
        self._lines = queue.Queue()
        self._pump = threading.Thread(
            target=_pump, args=(process.stdout, self._lines), daemon=True
        )
        self._pump.start()
        try:
            line = self._lines.get(timeout=self._start_timeout_s)
        except queue.Empty:
            line = None
        if line is None or _parsed(line) != _READY:
            code = self._stop()
            raise OwnReaderError(f"the own-data reader did not start ({code})")
        return process

    def _stop(self) -> int | None:
        """Kill the process if it runs, reap it and close its pipes."""
        process, pump = self._process, self._pump
        self._process = self._pump = None
        if process is None:
            return None
        kill_untrusted(process)
        code = process.wait()
        if pump is not None:
            pump.join()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
        return code


def read_own_file(path: Path, *, work_dir: Path) -> OwnFileInfo:
    """Read one own-data file in this process (the reader process's work).

    Parameters
    ----------
    path : Path
        Absolute path of the file.
    work_dir : Path
        This process's work directory, for the copies of a GeoPackage.

    Returns
    -------
    OwnFileInfo
        What GDAL read; ``error`` set when the file was refused or failed.
    """
    fmt = file_format(path)
    members: tuple[str, ...] = (path.name,)
    if fmt.driver is None:
        return OwnFileInfo(fmt.kind, None, members)
    try:
        if fmt.kind != "vector":
            return _read_raster(path, fmt)
        found = fileset_members(path)
        members = tuple(member.name for member in found)
        if any(member.is_symlink() for member in found[1:]):
            raise FormatRefusedError("a member of the file set is a symbolic link")
        return _read_vector(path, fmt, members, work_dir)
    except FormatRefusedError as error:
        detail = _describe(error, path, work_dir)
        return _refused(fmt, members, "unsupported_format", detail)
    except MemoryError:
        return _refused(fmt, members, "memory_limit")
    except Exception as error:  # GDAL, SQLite or the disk refusing the file
        return _refused(fmt, members, "unreadable", _describe(error, path, work_dir))


def main(argv: Sequence[str] | None = None) -> int:
    """Answer the requests of the standard input (see the module).

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        ``--config-file F --data-dir D``; ``sys.argv`` when omitted.

    Returns
    -------
    int
        ``0`` at the end of the input or after an answer ``memory_limit``;
        ``2`` for a request that is not ``{"path": "..."}``.
    """
    parser = argparse.ArgumentParser(prog="python -m archiwista.owndata.reader")
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    paths = AppPaths(
        config_file=arguments.config_file, data_dir=arguments.data_dir.absolute()
    )
    work_dir = process_work_dir(paths)
    import pyogrio  # noqa: F401 - GDAL loaded before the first file's clock
    import rasterio  # noqa: F401

    _answer(_READY)
    for line in sys.stdin:
        try:
            path = Path(json.loads(line)["path"])
        except (KeyError, TypeError, ValueError):
            return 2
        info = read_own_file(path, work_dir=work_dir)
        _answer(info.to_json())
        if info.error == "memory_limit":
            return 0
    return 0


def _read_vector(
    path: Path, fmt: FileFormat, members: tuple[str, ...], work_dir: Path
) -> OwnFileInfo:
    if fmt.driver == "GPKG":
        if not is_sqlite(path):
            raise ValueError("not a SQLite database")

        def layers_of(view: SqliteRead) -> tuple[LayerInfo, ...]:
            return _layers(vector_source(view.path, fmt), view.gdal_options)

        layers = read_sqlite(path, layers_of, work_dir=work_dir)
    else:
        layers = _layers(vector_source(path, fmt), {})
    with_geometry = [layer for layer in layers if layer.geometry_type is not None]
    crs_names = {layer.crs for layer in with_geometry}
    native_crs = next(iter(crs_names)) if len(crs_names) == 1 else None
    boxes = [layer.bbox for layer in with_geometry if layer.bbox is not None]
    native_bbox = _union(boxes) if len(crs_names) == 1 and boxes else None
    counts = [layer.feature_count for layer in layers]
    return OwnFileInfo(
        kind=fmt.kind,
        driver=fmt.driver,
        members=members,
        layers=layers,
        native_crs=native_crs,
        native_bbox=native_bbox,
        feature_count=None
        if any(count is None for count in counts)
        else sum(count for count in counts if count is not None),
    )


def _layers(source: str, options: dict[str, str]) -> tuple[LayerInfo, ...]:
    """Every layer of a vector source, one ``read_info`` (one opening) each.

    ``list_layers`` takes no open options, so a GeoPackage would lose
    ``IMMUTABLE``; the layers are asked for by index until GDAL has none.
    """
    import pyogrio
    from pyogrio.errors import DataLayerError

    layers: list[LayerInfo] = []
    for index in range(MAX_LAYERS):
        try:
            info = pyogrio.read_info(
                source,
                layer=index,
                force_feature_count=True,
                force_total_bounds=True,
                **options,
            )
        except DataLayerError:  # no layer of that index
            break
        count = int(info["features"])
        layers.append(
            LayerInfo(
                name=str(info["layer_name"]),
                geometry_type=info["geometry_type"],
                feature_count=count if count >= 0 else None,
                fields=tuple(
                    FieldInfo(str(name), _field_type(str(kind), str(subtype)))
                    for name, kind, subtype in zip(
                        info["fields"],
                        info["ogr_types"],
                        info["ogr_subtypes"],
                        strict=True,
                    )
                ),
                crs=info["crs"],
                bbox=_bbox(info["total_bounds"]),
            )
        )
    return tuple(layers)


def _read_raster(path: Path, fmt: FileFormat) -> OwnFileInfo:
    from rasterio.errors import NotGeoreferencedWarning

    from archiwista.formats import open_raster

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with open_raster(path, fmt) as dataset:
            transform = dataset.transform
            georeferenced = not transform.is_identity
            width, height = int(dataset.width), int(dataset.height)
            corners = [transform * corner for corner in _corners(width, height)]
            crs = dataset.crs
            nodata = dataset.nodata
            raster = RasterInfo(
                width=width,
                height=height,
                bands=int(dataset.count),
                dtype=str(dataset.dtypes[0]),
                nodata=None if nodata is None else float(nodata),
                pixel_size=(float(dataset.res[0]), float(dataset.res[1]))
                if georeferenced
                else None,
                georeferenced=georeferenced,
            )
            native_crs = _crs_name(crs) if crs else None
    native_bbox = (
        _bbox(
            (
                min(x for x, _ in corners),
                min(y for _, y in corners),
                max(x for x, _ in corners),
                max(y for _, y in corners),
            )
        )
        if georeferenced
        else None
    )
    return OwnFileInfo(
        kind=fmt.kind,
        driver=fmt.driver,
        members=(path.name,),
        raster=raster,
        native_crs=native_crs,
        native_bbox=native_bbox,
    )


def _corners(width: int, height: int) -> tuple[tuple[int, int], ...]:
    return ((0, 0), (width, 0), (0, height), (width, height))


def _crs_name(crs: "CRS") -> str:
    """``EPSG:<code>`` for a CRS that is exactly an EPSG one, else its WKT."""
    code = crs.to_epsg(confidence_threshold=100)
    return f"EPSG:{code}" if code is not None else str(crs.to_wkt())


def _field_type(kind: str, subtype: str) -> str:
    """``OFTString`` / ``OFSTNone`` -> ``String``; a subtype wins (``Boolean``)."""
    subtype = subtype.removeprefix("OFST")
    return subtype if subtype != "None" else kind.removeprefix("OFT")


def _bbox(value: Iterable[Any] | None) -> BBox | None:
    """Return a finite ``(min_x, min_y, max_x, max_y)``, or ``None``."""
    if value is None:
        return None
    numbers = tuple(float(number) for number in value)
    if len(numbers) != 4 or not all(math.isfinite(number) for number in numbers):
        return None
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def _union(boxes: Sequence[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _failed(path: Path, error: ReadError, detail: str | None = None) -> OwnFileInfo:
    """Answer for a file the process did not finish, without touching the file."""
    return _refused(file_format(path), (path.name,), error, detail)


def _refused(
    fmt: FileFormat,
    members: tuple[str, ...],
    error: ReadError,
    detail: str | None = None,
) -> OwnFileInfo:
    return OwnFileInfo(fmt.kind, fmt.driver, members, error=error, detail=detail)


def _describe(error: BaseException, path: Path, work_dir: Path) -> str:
    """Return a library message without the file's directory or the work one."""
    text = str(error).strip() or type(error).__name__
    for directory in (str(work_dir), str(path.parent)):
        text = re.sub(
            re.escape(directory) + r"[\\/]+(?:sqlite-[0-9a-f]+[\\/]+)?", "", text
        )
    return text[:_DETAIL_CHARS]


def _parsed(line: bytes) -> Any:
    try:
        return json.loads(line)
    except ValueError:
        return None


def _pump(stream: IO[bytes], lines: "queue.Queue[bytes | None]") -> None:
    """Move the process's answer lines to ``lines``; ``None`` at its end."""
    try:
        for line in stream:
            lines.put(line)
    except (OSError, ValueError):  # the stream closed under the loop
        pass
    finally:
        lines.put(None)


def _answer(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    if os.name == "posix":
        os.umask(0o077)  # copies in the work directory stay the user's alone
    sys.exit(main())
