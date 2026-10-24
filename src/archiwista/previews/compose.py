"""Layers composed from their versions: thumbnails and map tiles (plan v0.2, step 5a3).

A layer (a variant's year, campaign or edition — decision 7) is drawn from
the previews of its versions, so the same bytes are rendered once whatever
layers share them (A-ADR-008 errata 2):

- ``layer_thumbnail`` (Wachlarz): each version's thumbnail in the layer's
  planar frame (PL: EPSG:2180, CZ: EPSG:5514), warped with the pinned
  operation (decision 4), laid over each other;
- ``layer_tile`` (a year on the map): each version's EPSG:3857 tile ``z/x/y``
  laid over each other — only versions whose WGS84 bounds meet the tile.

Versions are given oldest first and drawn in that order (alpha over), the
newest on top. A version's own thumbnail or tile comes from the preview
cache under its content; one not there yet is rendered by the renderer of
its kind (rasters, vectors) and the answer carries it back
(``worker.object_file``), so the pool keeps it under the version's content
for every other layer and view. Callers give the layer's ready versions
(their local COG built); one evicted meanwhile is drawn from its file, so
a composite never lacks a version its key names. A version that cannot be
drawn at all (no map place, too large without its COG, a working file
changed since its scan) stays out; its outline remains on the map.

Each composite is a cache object of its own (renderer ``composite``) whose
content key names the operation, the rendered-object identities of the
versions drawn (bytes and indexed metadata), the frame or the tile, the style
and the size (``cache.composite_key``): a new ready version changes the key
only of the tiles it meets. The parameters::

    layer_thumbnail: {"versions": [{"source": PreviewSource JSON,
                                    "bounds": [w, s, e, n] or null}, …],
                      "frame": {"bbox": [...], "crs": "EPSG:2180"},
                      "style": "hillshade", "size": 256}
    layer_tile:      {"versions": [{"source": …, "bounds": [w, s, e, n]}, …],
                      "z": 14, "x": 9101, "y": 5550, "style": "hillshade"}

``bounds`` (WGS84, from the index) are required for tiles: they choose the
versions of a tile without opening any file.

Only the standard library at import: the server reads the targets (the
pool's cache keys); the handlers import their libraries in the render
process.
"""

import json
import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from archiwista.errors import PreviewUnavailableError
from archiwista.previews.cache import (
    INFO_NAME,
    RENDERER_VERSIONS,
    CacheKey,
    cache_key,
    composite_key,
    thumbnail_name,
    tile_name,
)
from archiwista.previews.types import (
    BBox,
    Extent,
    JsonObject,
    PreviewProbe,
    PreviewSource,
    Renderer,
)

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from archiwista.previews.protocol import RenderRequest

LAYER_THUMBNAIL = "layer_thumbnail"
LAYER_TILE = "layer_tile"
# Reasons of a probe after which a version has no place in a composite.
_UNPLACED = frozenset({"no_georeference", "no_crs", "transform_unavailable"})


def layer_thumbnail_target(
    source: PreviewSource | None, params: JsonObject
) -> tuple[CacheKey, str]:
    """Return the cache object and name of a layer's thumbnail (the pool's key).

    Raises
    ------
    ValueError
        Parameters that are not a layer thumbnail's.
    """
    versions = _versions(params)
    frame = _canonical(_frame_json(params))
    style, size = str(params["style"]), int(params["size"])
    contents = [cache_key(found).content_key for found, _ in versions]
    key = composite_key(LAYER_THUMBNAIL, contents, frame, style, size)
    return _composite(key), thumbnail_name(style, size)


def layer_tile_target(
    source: PreviewSource | None, params: JsonObject
) -> tuple[CacheKey, str]:
    """Return the cache object and name of a layer's map tile (the pool's key).

    Only the versions meeting the tile enter its key.

    Raises
    ------
    ValueError
        Parameters that are not a layer tile's (``bounds`` missing).
    """
    z, x, y = int(params["z"]), int(params["x"]), int(params["y"])
    style = str(params["style"])
    contents = [
        cache_key(found).content_key for found, _ in _tile_versions(params, z, x, y)
    ]
    key = composite_key(LAYER_TILE, contents, f"{z}/{x}/{y}", style, None)
    return _composite(key), tile_name(style, z, x, y)


def layer_thumbnail(
    renderers: Sequence[Renderer], request: "RenderRequest"
) -> dict[str, bytes]:
    """Draw a layer's thumbnail in its planar frame (a render process)."""
    from archiwista.previews import tiles

    params = request.params
    frame_json = _frame_json(params)
    frame = Extent(_bbox(frame_json["bbox"]), str(frame_json["crs"]))
    style, size = str(params["style"]), int(params["size"])
    rows, columns = tiles.frame_shape(frame.bbox, size)
    files: dict[str, bytes] = {}

    def draw(
        renderer: Renderer, source: PreviewSource, probe: PreviewProbe, use: str
    ) -> bytes:
        return renderer.thumbnail(source, probe, use, size, frame)

    def name(use: str) -> str:
        return thumbnail_name(use, size, _canonical(frame_json))

    images = [
        image
        for source, _ in _versions(params)
        if (image := _version_image(renderers, source, style, name, draw, files))
        is not None
    ]
    files[_IMAGE] = tiles.encode_png(_over(images, rows, columns))
    return files


def layer_tile(
    renderers: Sequence[Renderer], request: "RenderRequest"
) -> dict[str, bytes]:
    """Draw a layer's map tile from its versions' tiles (a render process)."""
    from archiwista.previews import tiles

    params = request.params
    z, x, y = int(params["z"]), int(params["x"]), int(params["y"])
    style = str(params["style"])
    files: dict[str, bytes] = {}

    def draw(
        renderer: Renderer, source: PreviewSource, probe: PreviewProbe, use: str
    ) -> bytes:
        return renderer.tile(source, probe, use, z, x, y, {})

    def name(use: str) -> str:
        return tile_name(use, z, x, y)

    images = [
        image
        for source, _ in _tile_versions(params, z, x, y)
        if (image := _version_image(renderers, source, style, name, draw, files))
        is not None
    ]
    side = tiles.TILE_SIZE
    files[_IMAGE] = tiles.encode_png(_over(images, side, side))
    return files


def tile_wgs84_bounds(z: int, x: int, y: int) -> BBox:
    """Return west, south, east, north (degrees) of the EPSG:3857 tile ``z/x/y``."""
    count = 1 << z

    def latitude(row: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / count))))

    return (
        x / count * 360.0 - 180.0,
        latitude(y + 1),
        (x + 1) / count * 360.0 - 180.0,
        latitude(y),
    )


# The answer's composite image (``worker.IMAGE_NAME``).
_IMAGE = "image.png"


def _version_image(
    renderers: Sequence[Renderer],
    source: PreviewSource,
    style: str,
    name: Callable[[str], str],
    draw: Callable[[Renderer, PreviewSource, PreviewProbe, str], bytes],
    files: dict[str, bytes],
) -> bytes | None:
    """Return a version's own image: from the cache, else rendered and kept.

    ``None`` for a version that cannot be drawn now.
    """
    from archiwista.previews import worker

    try:
        worker.require_unchanged(source)
    except (PreviewUnavailableError, FileNotFoundError):
        return None
    key = cache_key(source)
    probe = _probe(renderers, source, key, files)
    if probe is None or probe.reason is not None and probe.reason in _UNPLACED:
        return None
    use = style if style in probe.styles or not probe.styles else probe.default_style
    if use is None:
        return None
    cached = worker.cached_bytes(key, name(use))
    if cached is not None:
        return cached
    # A COG evicted since the caller saw the version ready: the renderer draws
    # from the file itself, so the composite under this key is complete.
    try:
        image = draw(worker.renderer_for(renderers, source), source, probe, use)
    except (PreviewUnavailableError, FileNotFoundError):
        return None
    files[worker.object_file(key, name(use))] = image
    return image


def _probe(
    renderers: Sequence[Renderer],
    source: PreviewSource,
    key: CacheKey,
    files: dict[str, bytes],
) -> PreviewProbe | None:
    """Return a version's probe from the cache, else made (and kept)."""
    from archiwista.previews import worker

    info = worker.cached_bytes(key, INFO_NAME)
    if info is not None:
        try:
            return PreviewProbe.from_bytes(info)
        except ValueError:  # a damaged object: probed again
            pass
    try:
        probe = worker.renderer_for(renderers, source).probe(source)
    except (PreviewUnavailableError, FileNotFoundError):
        return None
    files[worker.object_file(key, INFO_NAME)] = probe.to_bytes()
    return probe


def _over(images: Sequence[bytes], rows: int, columns: int) -> "npt.NDArray[np.uint8]":
    """Lay PNGs over each other (alpha over), the first at the bottom."""
    import numpy as np

    colour = np.zeros((3, rows, columns), dtype=np.float32)
    alpha = np.zeros((rows, columns), dtype=np.float32)
    for image in images:
        rgba = _decoded(image)
        if rgba.shape[1:] != (rows, columns):
            continue
        top = rgba[3].astype(np.float32) / 255.0
        below = alpha * (1.0 - top)
        total = top + below
        drawn = total > 0
        mixed = rgba[:3].astype(np.float32) * top + colour * below
        colour = np.where(drawn, mixed / np.where(drawn, total, 1.0), 0.0)
        alpha = total
    out = np.empty((4, rows, columns), dtype=np.uint8)
    out[:3] = np.clip(colour.round(), 0, 255)
    out[3] = np.clip((alpha * 255.0).round(), 0, 255)
    return out


def _decoded(image: bytes) -> "npt.NDArray[np.uint8]":
    """Return a PNG as RGBA (4, rows, columns)."""
    import warnings

    import numpy as np
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile

    with warnings.catch_warnings(), MemoryFile(image) as memory:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)  # a PNG has none
        with memory.open(driver="PNG") as found:
            data = found.read()
    if data.dtype != np.uint8:
        data = np.clip(data, 0, 255).astype(np.uint8)
    bands = data.shape[0]
    opaque = np.full(data.shape[1:], 255, dtype=np.uint8)
    if bands >= 4:
        return np.asarray(data[:4])
    if bands == 3:
        return np.concatenate([data, opaque[np.newaxis]])
    gray = data[0]
    alpha = data[1] if bands == 2 else opaque
    return np.stack([gray, gray, gray, alpha])


def _versions(params: JsonObject) -> list[tuple[PreviewSource, BBox | None]]:
    """Return the versions of a layer request with their WGS84 bounds."""
    found = params["versions"]
    if not isinstance(found, list):
        raise ValueError("versions is a list")
    versions = []
    for item in found:
        bounds = item.get("bounds")
        versions.append(
            (
                PreviewSource.from_json(item["source"]),
                None if bounds is None else _bbox(bounds),
            )
        )
    return versions


def _tile_versions(
    params: JsonObject, z: int, x: int, y: int
) -> list[tuple[PreviewSource, BBox]]:
    """Return the versions whose WGS84 bounds meet tile ``z/x/y``, in order."""
    west, south, east, north = tile_wgs84_bounds(z, x, y)
    chosen: list[tuple[PreviewSource, BBox]] = []
    for source, bounds in _versions(params):
        if bounds is None:
            raise ValueError("a layer tile's versions have bounds")
        if (
            bounds[0] < east
            and bounds[2] > west
            and bounds[1] < north
            and bounds[3] > south
        ):
            chosen.append((source, bounds))
    return chosen


def _frame_json(params: JsonObject) -> JsonObject:
    frame = params["frame"]
    if not isinstance(frame, dict):
        raise ValueError("a frame is {bbox, crs}")
    _bbox(frame["bbox"])
    return {"bbox": frame["bbox"], "crs": str(frame["crs"])}


def _composite(key: str) -> CacheKey:
    return CacheKey(key, "composite", RENDERER_VERSIONS["composite"])


def _bbox(value: Any) -> BBox:
    numbers = tuple(float(number) for number in value)
    if len(numbers) != 4 or not all(math.isfinite(number) for number in numbers):
        raise ValueError("a bounding box is four finite numbers")
    return numbers[0], numbers[1], numbers[2], numbers[3]


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
