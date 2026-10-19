"""Renderer of vector files: layers, thumbnails, tiles, features (plan v0.2, step 5b).

GeoPackage, Shapefile, GeoJSON, FlatGeobuf and native MapInfo tables open
only through the format table (``archiwista.formats.vector_source``,
decision 3): a GeoPackage as ``GPKG:`` once its SQLite header is checked,
GeoJSON as ``GeoJSON:``, the others once their signature is checked; a set
of files with a member that is a symbolic link is refused. pyogrio reads:

- ``probe``: every layer (at most ``MAX_LAYERS``) with its geometry type,
  feature count, fields, CRS (the file's, else ``PreviewSource.crs``),
  extent in that CRS and in WGS84, and ``SAMPLE_ROWS`` rows of attributes;
  the file's CRS and extent when its layers share one CRS. ``no_crs``: no
  layer with geometry has a CRS (a Shapefile without ``.prj``);
  ``transform_unavailable``: no such layer's CRS has a pinned operation to
  WGS84. Either leaves a thumbnail in the file's CRS. A layer named after
  its file (a Shapefile, a MapInfo table, GeoJSON or FlatGeobuf without a
  name of its own) has no name: a probe never names a file (decision 3).
- ``thumbnail`` and ``tile``: at most ``DRAWN_FEATURES_MAX`` features of each
  of the ``DRAWN_LAYERS`` largest line and polygon layers (point layers
  only in a file without those), or of the chosen ``layer``, simplified to
  half a pixel and drawn (``archiwista.previews.rasterize``) in the file's
  CRS, in a frame or on a map tile (EPSG:3857), moved there by the pinned
  operation (``archiwista.previews.tiles.transformer``).
- ``features``: the features of one layer in a WGS84 view (decision 4). The
  view's densified rectangle moves into the layer's CRS by the pinned
  operation; at most ``limit + 1`` features are read (more: ``truncated``),
  their geometries simplified to half a pixel of the request's zoom in the
  layer's CRS and moved to WGS84 by the pinned operation, at most
  ``FEATURES_MAX_VERTICES`` vertices together (more: ``truncated``);
  attributes as they are, texts over ``TEXT_MAX_CHARS`` shortened.
- ``build``: the consistent copy of a working SQLite file in state (b) or
  (c), which the ``preview`` job keeps as ``source.gpkg``.

A GeoPackage of a store opens immutable (``IMMUTABLE=YES``, SPEC 4.6 pkt 4).
A working one (``PreviewSource.mutable``) follows the three states of
decision 8 through ``consistent_sqlite_read``: in state (a) it is read in
place, immutable, and must not change meanwhile; in states (b) and (c) only
a consistent copy is read: the ``source.gpkg`` the ``preview`` job keeps in
the preview cache (``PreviewProbe.needs_copy``), else a copy made for the
request in the process's work directory. Nothing is written next to it.
"""

import contextlib
import json
import math
import shutil
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyogrio
import pyogrio.raw
import shapely
from pyogrio.errors import DataLayerError

from archiwista.errors import (
    FormatRefusedError,
    InconsistentReadError,
    PreviewUnavailableError,
    ProducerError,
)
from archiwista.formats import vector_source
from archiwista.owndata import (
    FILESET_SUFFIXES,
    consistent_sqlite_read,
    fileset_members,
    is_sqlite,
)
from archiwista.owndata.content import SqliteRead
from archiwista.previews import tiles, worker
from archiwista.previews.rasterize import REACH_PX, Geometries, Grid, draw_png
from archiwista.previews.types import (
    SOURCE_GPKG_NAME,
    BBox,
    Extent,
    JsonObject,
    PreviewKind,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
    StyleName,
)

# The one style of vectors: features drawn in their layers' colours.
VECTOR_STYLE: StyleName = "features"
# Layers of a file a probe lists; GDAL opens the file once per layer.
MAX_LAYERS = 1000
# Rows of attributes of each layer in its probe.
SAMPLE_ROWS = 20
# Largest line and polygon layers drawn on a thumbnail or a tile, and
# features read of each (decision 5).
DRAWN_LAYERS = 3
DRAWN_FEATURES_MAX = 50_000
# Features of one ``features`` answer at most, and their vertices together
# (decision 4: more is "Przybliż albo otwórz w QGIS").
FEATURES_LIMIT_MAX = 5000
FEATURES_MAX_VERTICES = 500_000
# Characters of a text attribute kept; a longer one ends with an ellipsis.
TEXT_MAX_CHARS = 500
# Decimal places of WGS84 coordinates in ``features`` (about 1 cm).
COORDINATE_DIGITS = 7
# Positions along each edge of a view, a frame or a tile before it moves to
# another CRS: its edges are curves there (decision 4).
EDGE_POSITIONS = 64

_IMMUTABLE: Mapping[str, str] = {"IMMUTABLE": "YES"}
# Drivers naming a file's layer after the file when it has no name inside.
_NAMED_AFTER_FILE = frozenset(
    {"ESRI Shapefile", "MapInfo File", "GeoJSON", "FlatGeobuf"}
)
# Families of geometry types (the type's first word without ``Multi``), in
# the order they are drawn: areas below lines, points on top.
_DRAW_ORDER = {"polygon": 0, "other": 1, "line": 2, "point": 3}
_POLYGON_TYPES = frozenset(
    {"Polygon", "Surface", "CurvePolygon", "PolyhedralSurface", "TIN", "Triangle"}
)
_LINE_TYPES = frozenset(
    {"LineString", "Curve", "CompoundCurve", "CircularString", "LinearRing"}
)


@dataclass(frozen=True, slots=True)
class _Opened:
    """A vector file as OGR opens it: its name with the driver, open options.

    ``copied``: read from a consistent copy of a working SQLite file in
    state (b) or (c) (decision 8).
    """

    name: str
    options: Mapping[str, str]
    copied: bool = False


class VectorRenderer:
    """Renderer of vector files (``kinds``: ``vector``), run in render processes.

    Parameters
    ----------
    work_dir : Path or None, optional
        Directory of the copies of working SQLite files; the render
        process's own (``archiwista.previews.worker.work_dir``) when
        omitted.
    """

    def __init__(self, *, work_dir: Path | None = None) -> None:
        self._work_dir = work_dir

    @property
    def kinds(self) -> frozenset[PreviewKind]:
        """Vector files."""
        return frozenset({"vector"})

    def probe(self, source: PreviewSource) -> PreviewProbe:
        """Recognise a vector file: its layers, CRS and extents.

        Raises
        ------
        FormatRefusedError
            Content of another format under the file's name.
        PreviewUnavailableError
            ``changed_since_scan``: a working file changed while it was read.
        """
        # The file's own state decides needs_copy, never a kept copy.
        with self._opened(source, cached=False) as opened:
            layers = [
                _layer_json(opened, index, info, source)
                for index, info in _infos(opened)
            ]
        return _probe_of(source, layers, needs_copy=opened.copied)

    def thumbnail(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        size: int,
        frame: Extent | None,
        layer: str | None = None,
    ) -> bytes:
        """Return an RGBA PNG of the drawn layers, its longer side ``size``.

        Without ``frame`` in the CRS of the largest drawn layer around the
        drawn layers' extent (a file without a CRS too); with it, the
        frame's rectangle in its CRS.

        Raises
        ------
        PreviewUnavailableError
            ``no_crs`` in a frame for a file whose drawn layers have no CRS;
            ``transform_unavailable`` without a pinned operation to the
            frame's CRS.
        ValueError
            Another style than ``features``, no such ``layer``, a size
            below 1.
        """
        _require_style(style)
        if size < 1:
            raise ValueError(f"a thumbnail has at least one pixel, not {size}")
        drawn = _drawn_layers(probe, layer)
        if frame is not None:
            height, width = tiles.frame_shape(frame.bbox, size)
            return self._framed(
                source, drawn, Grid(frame.bbox, width, height), frame.crs
            )
        crs = drawn[0][1].get("crs") if drawn else None
        same = [(index, info) for index, info in drawn if info.get("crs") == crs]
        boxes = [_bbox(info["bbox"]) for _, info in same if info.get("bbox")]
        if not boxes:
            return draw_png(Grid((0.0, 0.0, 1.0, 1.0), size, size), [])
        bounds = _padded(_union(boxes), size)
        height, width = tiles.frame_shape(bounds, size)
        grid = Grid(bounds, width, height)
        tolerance = min(grid.pixel_width, grid.pixel_height) / 2.0
        with self._opened(source) as opened:
            layers = [
                _simplified(_geometries(opened, index, None), tolerance)
                for index, _ in same
            ]
        return draw_png(grid, layers)

    def tile(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        z: int,
        x: int,
        y: int,
        params: JsonObject,
    ) -> bytes:
        """Return the RGBA PNG map tile ``z/x/y`` (EPSG:3857) of the drawn layers.

        ``params`` may choose one ``layer``; transparent where no feature is.

        Raises
        ------
        PreviewUnavailableError
            ``no_crs`` for a file whose drawn layers have no CRS,
            ``transform_unavailable`` without a pinned operation.
        ValueError
            Another style than ``features``, no such ``layer``.
        """
        _require_style(style)
        layer = params.get("layer")
        drawn = _drawn_layers(probe, None if layer is None else str(layer))
        side = tiles.TILE_SIZE
        grid = Grid(tiles.tile_bounds(z, x, y), side, side)
        return self._framed(source, drawn, grid, tiles.WEB_MERCATOR)

    def features(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        layer: str | None,
        bbox_wgs84: BBox,
        zoom: int,
        limit: int,
    ) -> JsonObject:
        """Return a layer's features in a WGS84 view as a GeoJSON collection.

        Parameters
        ----------
        source, probe : PreviewSource, PreviewProbe
            The file and its probe.
        layer : str or None
            The layer's name; ``None``: the first layer with geometry.
        bbox_wgs84 : BBox
            The view: west, south, east, north in degrees.
        zoom : int
            The map's zoom: geometries are simplified to half its pixel.
        limit : int
            Features at most (1 to ``FEATURES_LIMIT_MAX``).

        Returns
        -------
        JsonObject
            ``FeatureCollection`` in WGS84 with ``layer``, ``number_matched``
            (``None`` past ``limit``), ``number_returned``, ``truncated``
            (past ``limit`` or ``FEATURES_MAX_VERTICES``) and ``simplified``
            (some geometry lost vertices).

        Raises
        ------
        PreviewUnavailableError
            ``no_crs``: the layer has no CRS; ``transform_unavailable``: no
            pinned operation between it and WGS84.
        ValueError
            A view, zoom or limit out of range, no such layer.
        """
        if not 1 <= limit <= FEATURES_LIMIT_MAX:
            raise ValueError(f"limit is 1 to {FEATURES_LIMIT_MAX}, not {limit}")
        if not 0 <= zoom <= tiles.MAX_ZOOM:
            raise ValueError(f"zoom is 0 to {tiles.MAX_ZOOM}, not {zoom}")
        view = _view(bbox_wgs84)
        index = _feature_layer(probe, layer)
        info = probe.layers[index]
        crs = info.get("crs")
        if crs is None:
            raise PreviewUnavailableError("no_crs", "the layer has no CRS")
        read_bbox = _moved_bounds(view, tiles.WGS84, crs)
        if read_bbox is None:
            return _collection(info, [], matched=0, truncated=False, simplified=False)
        tolerance = _half_pixel(view, read_bbox, zoom)
        with self._opened(source) as opened:
            meta, fids, wkb, fields = pyogrio.raw.read(
                opened.name,
                layer=index,
                bbox=read_bbox,
                max_features=limit + 1,
                return_fids=True,
                force_2d=True,
                datetime_as_string=True,
                **opened.options,
            )
        matched = len(fids)
        kept = min(matched, limit)
        geometries = _from_wkb(wkb, kept)
        simplified = _simplified(geometries, tolerance)
        moved = _rounded(_moved(simplified, crs, tiles.WGS84))
        within = np.cumsum(shapely.get_num_coordinates(moved)) <= FEATURES_MAX_VERTICES
        returned = kept if within.all() else int(np.argmin(within))
        lost = shapely.get_num_coordinates(simplified) < shapely.get_num_coordinates(
            geometries
        )
        rows = _rows(meta, [values[:returned] for values in fields], returned)
        texts = shapely.to_geojson(moved[:returned])
        items = [
            {
                "type": "Feature",
                "id": int(fid),
                "geometry": None if text is None else json.loads(text),
                "properties": row,
            }
            for fid, text, row in zip(fids[:returned], texts, rows, strict=True)
        ]
        return _collection(
            info,
            items,
            matched=matched if matched <= limit else None,
            truncated=matched > limit or returned < kept,
            simplified=bool(lost[:returned].any()),
        )

    def build(self, source: PreviewSource, probe: PreviewProbe, out_path: Path) -> None:
        """Write the consistent copy of a working SQLite file to ``out_path``.

        What the ``preview`` job keeps as ``source.gpkg`` for a file whose
        probe ``needs_copy``: committed rows only, one file without a
        journal (``consistent_sqlite_read``).

        Raises
        ------
        PreviewUnavailableError
            ``changed_since_scan``: the file changed while it was copied.
        ValueError
            Not a working GeoPackage.
        """
        path = source.paths[0]
        if not (source.mutable and source.format.driver == "GPKG"):
            raise ValueError("only a working GeoPackage has a consistent copy")
        _require_sqlite(path)
        with self._consistent(path) as view:
            if view.state == "in_place":
                shutil.copyfile(view.path, out_path)
            else:  # the copy is this process's own: moved, not copied again
                shutil.move(view.path, out_path)

    def _framed(
        self,
        source: PreviewSource,
        drawn: Sequence[tuple[int, JsonObject]],
        grid: Grid,
        crs: str,
    ) -> bytes:
        """Draw the layers on a grid of ``crs`` (a frame, a map tile)."""
        placed = [(index, info) for index, info in drawn if info.get("crs") is not None]
        if drawn and not placed:
            raise PreviewUnavailableError("no_crs", "the drawn layers have no CRS")
        reach = (grid.pixel_width * REACH_PX, grid.pixel_height * REACH_PX)
        min_x, min_y, max_x, max_y = grid.bounds
        wider = (min_x - reach[0], min_y - reach[1], max_x + reach[0], max_y + reach[1])
        layers: list[Geometries] = []
        with self._opened(source) as opened:
            for index, info in placed:
                layer_crs = str(info["crs"])
                read_bbox = _moved_bounds(wider, crs, layer_crs)
                if read_bbox is None:
                    continue
                across = grid.width + 2 * REACH_PX
                down = grid.height + 2 * REACH_PX
                tolerance = (
                    min(
                        (read_bbox[2] - read_bbox[0]) / across,
                        (read_bbox[3] - read_bbox[1]) / down,
                    )
                    / 2.0
                )
                found = _simplified(_geometries(opened, index, read_bbox), tolerance)
                layers.append(_moved(found, layer_crs, crs))
        return draw_png(grid, layers)

    @contextlib.contextmanager
    def _opened(
        self, source: PreviewSource, *, cached: bool = True
    ) -> Iterator[_Opened]:
        """Open the source's main file the one way its format and state allow.

        ``cached``: a working SQLite file is read from its ``source.gpkg``
        when the preview cache has it, without opening the file itself.
        """
        path = source.paths[0]
        fmt = source.format
        path.stat()  # a missing file is missing_file, not unreadable
        if fmt.driver != "GPKG":
            _refuse_linked_members(path)
            yield _Opened(vector_source(path, fmt), {})
            return
        if source.mutable and cached:
            with worker.cached_file(source, SOURCE_GPKG_NAME) as copy:
                if copy is not None:
                    yield _Opened(vector_source(copy, fmt), _IMMUTABLE, copied=True)
                    return
        _require_sqlite(path)
        if not source.mutable:
            yield _Opened(vector_source(path, fmt), _IMMUTABLE)
            return
        with self._consistent(path) as view:
            options = view.gdal_options
            copied = view.state != "in_place"
            yield _Opened(vector_source(view.path, fmt), options, copied)

    @contextlib.contextmanager
    def _consistent(self, path: Path) -> Iterator[SqliteRead]:
        """Run ``consistent_sqlite_read``; a change is ``changed_since_scan``."""
        work_dir = self._work_dir if self._work_dir is not None else worker.work_dir()
        try:
            with consistent_sqlite_read(path, work_dir=work_dir) as view:
                yield view
        except InconsistentReadError as error:
            raise PreviewUnavailableError("changed_since_scan", str(error)) from error


def _infos(opened: _Opened) -> Iterator[tuple[int, dict[str, Any]]]:
    """Every layer's ``read_info``, by index: ``list_layers`` takes no open options."""
    for index in range(MAX_LAYERS):
        try:
            info = pyogrio.read_info(
                opened.name,
                layer=index,
                force_feature_count=True,
                force_total_bounds=True,
                **opened.options,
            )
        except DataLayerError:  # no layer of that index
            return
        yield index, info


def _layer_json(
    opened: _Opened, index: int, info: Mapping[str, Any], source: PreviewSource
) -> JsonObject:
    """One layer of a probe: name, geometry, count, fields, CRS, extents, sample."""
    geometry_type = info["geometry_type"]
    spatial = geometry_type is not None
    crs = (info["crs"] or source.crs) if spatial else None
    bbox = _finite_bbox(info["total_bounds"]) if spatial else None
    count = int(info["features"])
    name = str(info["layer_name"])
    if source.format.driver in _NAMED_AFTER_FILE and name == source.paths[0].stem:
        name_or_none: str | None = None
    else:
        name_or_none = name
    meta, _, _, fields = pyogrio.raw.read(
        opened.name,
        layer=index,
        read_geometry=False,
        max_features=SAMPLE_ROWS,
        datetime_as_string=True,
        **opened.options,
    )
    return {
        "name": name_or_none,
        "geometry_type": geometry_type,
        "feature_count": count if count >= 0 else None,
        "fields": [
            {"name": str(field), "type": _field_type(str(kind), str(subtype))}
            for field, kind, subtype in zip(
                info["fields"], info["ogr_types"], info["ogr_subtypes"], strict=True
            )
        ],
        "crs": crs,
        "bbox": None if bbox is None else list(bbox),
        "bbox_wgs84": None if bbox is None or crs is None else _wgs84_list(bbox, crs),
        "sample": _rows(meta, fields, len(fields[0]) if len(fields) else 0),
    }


def _probe_of(
    source: PreviewSource, layers: Sequence[JsonObject], *, needs_copy: bool
) -> PreviewProbe:
    """Return the file's probe from its layers: common CRS, extents, reason."""
    spatial = [layer for layer in layers if layer["geometry_type"] is not None]
    systems = {str(layer["crs"]) for layer in spatial if layer["crs"] is not None}
    reason: PreviewReason | None = None
    if not systems:
        reason = "no_crs"
    elif not any(_reaches_wgs84(crs) for crs in systems):
        reason = "transform_unavailable"
    crs = next(iter(systems)) if len(systems) == 1 else None
    native = [
        _bbox(layer["bbox"])
        for layer in spatial
        if crs is not None and layer["crs"] == crs and layer["bbox"] is not None
    ]
    wgs84 = [_bbox(layer["bbox_wgs84"]) for layer in spatial if layer["bbox_wgs84"]]
    return PreviewProbe(
        kind=source.kind,
        driver=source.format.driver,
        crs=crs,
        bbox_native=_union(native) if native else None,
        bbox_wgs84=_union(wgs84) if wgs84 else None,
        layers=tuple(layers),
        needs_copy=needs_copy,
        reason=reason,
        styles=(VECTOR_STYLE,),
        default_style=VECTOR_STYLE,
    )


def _drawn_layers(
    probe: PreviewProbe, layer: str | None
) -> list[tuple[int, JsonObject]]:
    """Layers a thumbnail or a tile draws, in drawing order, with their indexes.

    The chosen layer; else the ``DRAWN_LAYERS`` largest line and polygon
    layers (point layers in a file without those).
    """
    if layer is not None:
        index = _named_layer(probe, layer)
        chosen = probe.layers[index]
        return [(index, chosen)] if chosen.get("geometry_type") else []
    spatial = [
        (index, info)
        for index, info in enumerate(probe.layers)
        if info.get("geometry_type") is not None
    ]
    shapes = [item for item in spatial if _family(item[1]) != "point"]
    largest = sorted(
        shapes or spatial, key=lambda item: -(item[1].get("feature_count") or 0)
    )
    return sorted(
        largest[:DRAWN_LAYERS],
        key=lambda item: (_DRAW_ORDER[_family(item[1])], item[0]),
    )


def _feature_layer(probe: PreviewProbe, layer: str | None) -> int:
    """Index of the named layer, else of the first layer with geometry."""
    if layer is not None:
        return _named_layer(probe, layer)
    for index, info in enumerate(probe.layers):
        if info.get("geometry_type") is not None:
            return index
    raise PreviewUnavailableError("no_crs", "the file has no layer with geometry")


def _named_layer(probe: PreviewProbe, layer: str) -> int:
    for index, info in enumerate(probe.layers):
        if info.get("name") == layer:
            return index
    raise ValueError(f"no layer {layer!r}")


def _family(info: Mapping[str, Any]) -> str:
    """``polygon``, ``line``, ``point`` or ``other`` of a layer's geometry type."""
    base = str(info.get("geometry_type") or "").split(" ")[0].removeprefix("Multi")
    if base == "Point":
        return "point"
    if base in _POLYGON_TYPES:
        return "polygon"
    if base in _LINE_TYPES:
        return "line"
    return "other"


def _geometries(opened: _Opened, index: int, bbox: BBox | None) -> Geometries:
    """Read a layer's geometries (``DRAWN_FEATURES_MAX``), in a rectangle if given."""
    _, _, wkb, _ = pyogrio.raw.read(
        opened.name,
        layer=index,
        columns=[],
        force_2d=True,
        bbox=bbox,
        max_features=DRAWN_FEATURES_MAX,
        **opened.options,
    )
    return _from_wkb(wkb, None)


def _from_wkb(wkb: Any, count: int | None) -> Geometries:
    """Shapely geometries of WKB; ``None`` for a missing or unreadable one (curves)."""
    if wkb is None:
        return np.full(count or 0, None, dtype=object)
    found = wkb if count is None else wkb[:count]
    return np.asarray(shapely.from_wkb(found, on_invalid="ignore"), dtype=object)


def _simplified(geometries: Geometries, tolerance: float) -> Geometries:
    """Geometries simplified to ``tolerance``; one that would vanish keeps its shape."""
    if not tolerance > 0 or not geometries.size:
        return geometries
    simplified = np.asarray(
        shapely.simplify(geometries, tolerance, preserve_topology=False), dtype=object
    )
    vanished = shapely.is_empty(simplified) & ~shapely.is_empty(geometries)
    vanished &= ~shapely.is_missing(geometries)
    if vanished.any():
        simplified[vanished] = shapely.simplify(
            geometries[vanished], tolerance, preserve_topology=True
        )
    return simplified


def _moved(geometries: Geometries, src_crs: str, dst_crs: str) -> Geometries:
    """Geometries moved by the pinned operation; ``None`` where it gives no position."""
    if src_crs.upper() == dst_crs.upper() or not geometries.size:
        return geometries
    operation = tiles.transformer(src_crs, dst_crs)
    try:
        moved = np.asarray(
            shapely.transform(geometries, operation.transform, interleaved=False),
            dtype=object,
        )
    except ProducerError as error:
        raise PreviewUnavailableError("transform_unavailable", str(error)) from error
    present = ~shapely.is_missing(moved) & ~shapely.is_empty(moved)
    lost = present & ~np.isfinite(shapely.bounds(moved)).all(axis=1)
    moved[lost] = None
    return moved


def _rounded(geometries: Geometries) -> Geometries:
    """WGS84 geometries with coordinates to ``COORDINATE_DIGITS`` places."""
    if not geometries.size:
        return geometries
    return np.asarray(
        shapely.transform(geometries, lambda xy: np.round(xy, COORDINATE_DIGITS)),
        dtype=object,
    )


def _moved_bounds(bbox: BBox, src_crs: str, dst_crs: str) -> BBox | None:
    """Bounds of a rectangle's densified edges moved to another CRS.

    ``None`` when the operation gives no finite position for any of them.
    """
    if src_crs.upper() == dst_crs.upper():
        return bbox
    xs, ys = _ring(bbox)
    try:
        moved_xs, moved_ys = tiles.transformer(src_crs, dst_crs).transform(xs, ys)
    except ProducerError as error:
        raise PreviewUnavailableError("transform_unavailable", str(error)) from error
    finite = np.isfinite(moved_xs) & np.isfinite(moved_ys)
    if not finite.any():
        return None
    xs, ys = np.asarray(moved_xs)[finite], np.asarray(moved_ys)[finite]
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def _ring(bbox: BBox) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Positions along a rectangle's edges, ``EDGE_POSITIONS`` per edge."""
    min_x, min_y, max_x, max_y = bbox
    steps = np.linspace(0.0, 1.0, EDGE_POSITIONS, endpoint=False)
    along_x = min_x + (max_x - min_x) * steps
    along_y = min_y + (max_y - min_y) * steps
    west, east = np.full_like(steps, min_x), np.full_like(steps, max_x)
    south, north = np.full_like(steps, min_y), np.full_like(steps, max_y)
    # South edge eastwards, east edge northwards, north westwards, west southwards.
    xs = np.concatenate(
        [along_x, east, along_x[::-1] + (max_x - min_x) / EDGE_POSITIONS, west]
    )
    ys = np.concatenate(
        [south, along_y, north, along_y[::-1] + (max_y - min_y) / EDGE_POSITIONS]
    )
    return xs, ys


def _half_pixel(view: BBox, read_bbox: BBox, zoom: int) -> float:
    """Half a map pixel of ``zoom`` at the view, in units of the layer's CRS."""
    west, south, east, north = tiles.mercator_bounds(view)
    resolution = tiles.tile_resolution(zoom)
    across = (east - west) / resolution
    down = (north - south) / resolution
    min_x, min_y, max_x, max_y = read_bbox
    if not (across > 0 and down > 0):
        return 0.0
    return min((max_x - min_x) / across, (max_y - min_y) / down) / 2.0


def _view(bbox: BBox) -> BBox:
    """Return a WGS84 view within the world, west to east and south to north."""
    west, south, east, north = (float(value) for value in bbox)
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        raise ValueError("a view has finite coordinates")
    west, east = max(-180.0, west), min(180.0, east)
    south, north = max(-90.0, south), min(90.0, north)
    if not (west < east and south < north):
        raise ValueError("a view is west, south, east, north in WGS84 degrees")
    return west, south, east, north


def _collection(
    info: Mapping[str, Any],
    items: list[JsonObject],
    *,
    matched: int | None,
    truncated: bool,
    simplified: bool,
) -> JsonObject:
    return {
        "type": "FeatureCollection",
        "layer": info.get("name"),
        "features": items,
        "number_matched": matched,
        "number_returned": len(items),
        "truncated": truncated,
        "simplified": simplified,
    }


def _rows(
    meta: Mapping[str, Any], fields: Sequence[Any], count: int
) -> list[JsonObject]:
    """Attributes of ``count`` features as JSON objects (field name to value)."""
    names = [str(name) for name in meta["fields"]]
    columns = [
        _json_values(values, str(dtype))
        for values, dtype in zip(fields, meta["dtypes"], strict=True)
    ]
    if not columns:
        return [{} for _ in range(count)]
    return [dict(zip(names, row, strict=True)) for row in zip(*columns, strict=True)]


def _json_values(values: Any, dtype: str) -> list[Any]:
    """Return a field's values as JSON: ``None`` for null, binary or not finite."""
    try:
        kind = np.dtype(dtype).kind
    except TypeError:
        kind = "O"
    return [_json_value(value, kind) for value in np.asarray(values).tolist()]


def _json_value(value: Any, kind: str) -> Any:
    """One value as JSON; integers and booleans come back from NaN-able floats."""
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if kind in "iu" and isinstance(value, int | float):
        return int(value)
    if kind == "b" and isinstance(value, int | float):
        return bool(value)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _shortened(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return None
    if isinstance(value, list | tuple | np.ndarray):
        return [_json_value(item, "O") for item in np.asarray(value).tolist()]
    return _shortened(str(value))


def _shortened(text: str) -> str:
    if len(text) <= TEXT_MAX_CHARS:
        return text
    return text[: TEXT_MAX_CHARS - 1] + "…"


def _field_type(kind: str, subtype: str) -> str:
    """``OFTString`` / ``OFSTNone`` -> ``String``; a subtype wins (``Boolean``)."""
    subtype = subtype.removeprefix("OFST")
    return subtype if subtype != "None" else kind.removeprefix("OFT")


def _wgs84_list(bbox: BBox, crs: str) -> list[float] | None:
    """WGS84 bounds of a layer's extent; ``None`` without a pinned operation."""
    min_x, min_y, max_x, max_y = bbox
    try:
        if min_x < max_x and min_y < max_y:
            return list(tiles.wgs84_bounds(bbox, crs))
        # A point, or a line along an axis: its two corners move.
        corners = (np.array([min_x, max_x]), np.array([min_y, max_y]))
        xs, ys = tiles.transformer(crs, tiles.WGS84).transform(*corners)
    except (PreviewUnavailableError, ProducerError):
        return None
    if not (np.isfinite(xs).all() and np.isfinite(ys).all()):
        return None
    return [float(np.min(xs)), float(np.min(ys)), float(np.max(xs)), float(np.max(ys))]


def _reaches_wgs84(crs: str) -> bool:
    """Whether a CRS has a pinned operation to WGS84 (or is WGS84)."""
    try:
        tiles.transformer(crs, tiles.WGS84)
    except PreviewUnavailableError:
        return False
    return True


def _padded(bounds: BBox, size: int) -> BBox:
    """Room around an extent for markers and outlines; a point gets a square."""
    min_x, min_y, max_x, max_y = bounds
    span = max(max_x - min_x, max_y - min_y) or 1.0
    # Each side at least a tenth of the longer one: no ribbon of one pixel.
    half_width = max(max_x - min_x, span / 10.0) / 2.0
    half_height = max(max_y - min_y, span / 10.0) / 2.0
    pad = span * REACH_PX / size
    centre_x, centre_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    return (
        centre_x - half_width - pad,
        centre_y - half_height - pad,
        centre_x + half_width + pad,
        centre_y + half_height + pad,
    )


def _union(boxes: Sequence[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _bbox(value: Sequence[Any]) -> BBox:
    return float(value[0]), float(value[1]), float(value[2]), float(value[3])


def _finite_bbox(value: Sequence[Any] | None) -> BBox | None:
    """Return a finite ``(min_x, min_y, max_x, max_y)``; ``None``: an empty layer."""
    if value is None:
        return None
    numbers = tuple(float(number) for number in value)
    if len(numbers) != 4 or not all(math.isfinite(number) for number in numbers):
        return None
    return _bbox(numbers)


def _require_style(style: str) -> None:
    if style != VECTOR_STYLE:
        raise ValueError(f"vectors are drawn in style {VECTOR_STYLE!r}, not {style!r}")


def _require_sqlite(path: Path) -> None:
    """Refuse a GeoPackage name on another content before SQLite opens it."""
    if not is_sqlite(path):
        raise FormatRefusedError("not a GeoPackage file (no SQLite header)")


def _refuse_linked_members(path: Path) -> None:
    """Refuse a set of files with a member that is a symbolic link.

    GDAL opens a Shapefile's ``.dbf`` or a MapInfo table's ``.dat`` by name:
    a link would make it read another file of the computer.
    """
    if path.suffix.lower() not in FILESET_SUFFIXES:
        return
    if any(member.is_symlink() for member in fileset_members(path)[1:]):
        raise FormatRefusedError("a member of the file set is a symbolic link")
