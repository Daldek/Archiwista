"""A local tile server standing in for an online basemap.

It runs on its own port, so its origin differs from Archiwista's. A raster
basemap gets one grey PNG for every ``/{z}/{x}/{y}.png``; a vector basemap
its TileJSON at ``/planet`` and the same OpenMapTiles vector tile
(``vector_tile``) for every ``/planet/{z}/{x}/{y}.pbf`` — all with
``Access-Control-Allow-Origin``, as public tile servers send it. Each request
is recorded with its ``Referer`` and ``Origin`` headers, so an interface test
can check that the browser fetched basemap tiles within the page's CSP and
without a ``Referer``.
"""

import json
import re
import struct
import threading
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TILE_PX = 256
TILEJSON_PATH = "/planet"
# The TileJSON's attribution, which the configured one must replace.
TILEJSON_ATTRIBUTION = '<a href="https://example.com/">Obca atrybucja</a>'
_TILE_PATH = re.compile(r"(/planet)?/\d+/\d+/\d+\.(png|pbf)")
_EXTENT = 4096
_POINT, _LINE, _POLYGON = 1, 2, 3
_MOVE_TO, _LINE_TO, _CLOSE_PATH = 1, 2, 7
# Places of every vector tile with their names as OpenFreeMap gives them: in
# Polish (`name:pl`), in Latin script and local. The last one has only a
# local name, in a script the packaged glyphs lack (Georgian).
PLACES = (
    {"name": "Gdańsk", "name:pl": "Gdańsk", "name:latin": "Gdańsk"},
    {"name": "Львів", "name:pl": "Lwów", "name:latin": "Lviv"},
    {"name": "თბილისი"},
)
type Properties = dict[str, str | int]
type Feature = tuple[int, list[int], Properties]


def grey_png(size: int = TILE_PX, level: int = 200) -> bytes:
    """Return a square, single-colour 8-bit greyscale PNG.

    Parameters
    ----------
    size : int
        Side in pixels.
    level : int
        Grey level, 0 (black) to 255 (white).

    Returns
    -------
    bytes
        A complete PNG file.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes([level]) * size for _ in range(size))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def vector_tile() -> bytes:
    """Return a Mapbox Vector Tile with one feature per layer Archiwista draws.

    A lake, a built-up area, a river, a country boundary, a primary road, a
    sea's name and the ``PLACES`` as cities, in the OpenMapTiles schema of
    OpenFreeMap. Every tile is the same.

    Returns
    -------
    bytes
        The tile, protobuf-encoded (version 2, extent 4096).
    """
    city: Properties = {"class": "city", "rank": 3}
    layers: dict[str, list[Feature]] = {
        "water": [
            (
                _POLYGON,
                _ring([(0, 0), (1500, 0), (1500, 1500), (0, 1500)]),
                {"class": "lake"},
            )
        ],
        "landuse": [
            (
                _POLYGON,
                _ring([(2600, 2600), (4000, 2600), (4000, 4000), (2600, 4000)]),
                {"class": "residential"},
            )
        ],
        "waterway": [
            (
                _LINE,
                _path([(0, 2048), (4096, 1800)]),
                {"class": "river", "name": "Wisła", "name:pl": "Wisła"},
            )
        ],
        "boundary": [
            (
                _LINE,
                _path([(2048, 0), (2048, 4096)]),
                {"admin_level": 2, "maritime": 0, "disputed": 0},
            )
        ],
        "transportation": [
            (_LINE, _path([(0, 3000), (4096, 3200)]), {"class": "primary"})
        ],
        "water_name": [
            (
                _POINT,
                _path([(700, 700)]),
                {"class": "sea", "name": "Østersøen", "name:pl": "Morze Bałtyckie"},
            )
        ],
        "place": [
            (_POINT, _path([point]), {**city, **names})
            for point, names in zip(
                [(1024, 1024), (3072, 1024), (2048, 3584)], PLACES, strict=True
            )
        ],
    }
    return b"".join(
        _message(3, _layer(name, features)) for name, features in layers.items()
    )


def _layer(name: str, features: list[Feature]) -> bytes:
    keys: list[str] = []
    values: list[str | int] = []
    encoded = b""
    for kind, geometry, properties in features:
        tags: list[int] = []
        for key, value in properties.items():
            if key not in keys:
                keys.append(key)
            if value not in values:
                values.append(value)
            tags += [keys.index(key), values.index(value)]
        encoded += _message(
            2,
            _message(2, _packed(tags))
            + _number(3, kind)
            + _message(4, _packed(geometry)),
        )
    return (
        _number(15, 2)
        + _message(1, name.encode())
        + encoded
        + b"".join(_message(3, key.encode()) for key in keys)
        + b"".join(_message(4, _value(value)) for value in values)
        + _number(5, _EXTENT)
    )


def _value(value: str | int) -> bytes:
    if isinstance(value, str):
        return _message(1, value.encode())
    return _number(5, value)


def _path(points: list[tuple[int, int]]) -> list[int]:
    """Return the commands of a point or a line: move to the first, lines on."""
    commands = [_command(_MOVE_TO, 1)]
    x = y = 0
    for index, (next_x, next_y) in enumerate(points):
        if index == 1:
            commands.append(_command(_LINE_TO, len(points) - 1))
        commands += [_zigzag(next_x - x), _zigzag(next_y - y)]
        x, y = next_x, next_y
    return commands


def _ring(points: list[tuple[int, int]]) -> list[int]:
    """Return the commands of a polygon's outer ring (clockwise with y down)."""
    return [*_path(points), _command(_CLOSE_PATH, 1)]


def _command(command: int, count: int) -> int:
    return command | count << 3


def _zigzag(value: int) -> int:
    return value << 1 ^ value >> 31


def _packed(values: list[int]) -> bytes:
    return b"".join(_varint(value) for value in values)


def _message(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _number(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append(value & 0x7F | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


@dataclass(frozen=True)
class TileRequest:
    """One request the tile server received."""

    path: str
    referer: str | None
    origin: str | None


@dataclass
class TileServer:
    """A running tile server and the requests it answered."""

    port: int
    requests: list[TileRequest] = field(default_factory=list)

    @property
    def origin(self) -> str:
        """Return the server's origin, e.g. ``http://127.0.0.1:41234``."""
        return f"http://127.0.0.1:{self.port}"

    @property
    def template(self) -> str:
        """Return the XYZ template of a raster basemap setting."""
        return f"{self.origin}/{{z}}/{{x}}/{{y}}.png"

    @property
    def tilejson(self) -> str:
        """Return the TileJSON address of a vector basemap setting."""
        return f"{self.origin}{TILEJSON_PATH}"

    def tiles(self) -> list[TileRequest]:
        """Return the tile requests answered so far, raster or vector."""
        return [
            request
            for request in list(self.requests)
            if _TILE_PATH.fullmatch(request.path)
        ]


@contextmanager
def tile_server() -> Iterator[TileServer]:
    """Serve grey and vector tiles on a free port of 127.0.0.1 until the block ends."""
    png = grey_png()
    pbf = vector_tile()
    served = TileServer(port=0)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Answer a tile or the TileJSON, or 404 for any other path."""
            with lock:
                served.requests.append(
                    TileRequest(
                        path=self.path,
                        referer=self.headers.get("Referer"),
                        origin=self.headers.get("Origin"),
                    )
                )
            if self.path == TILEJSON_PATH:
                body, kind = _tilejson(served.origin), "application/json"
            elif _TILE_PATH.fullmatch(self.path):
                vector = self.path.endswith(".pbf")
                body = pbf if vector else png
                kind = "application/x-protobuf" if vector else "image/png"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Keep the test output quiet."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    served.port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield served
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _tilejson(origin: str) -> bytes:
    """Return a TileJSON like OpenFreeMap's, its tiles on this server."""
    layers = [
        "boundary",
        "landuse",
        "place",
        "transportation",
        "water",
        "water_name",
        "waterway",
    ]
    return json.dumps(
        {
            "tilejson": "3.0.0",
            "tiles": [f"{origin}{TILEJSON_PATH}/{{z}}/{{x}}/{{y}}.pbf"],
            "minzoom": 0,
            "maxzoom": 14,
            "attribution": TILEJSON_ATTRIBUTION,
            "vector_layers": [{"id": layer, "fields": {}} for layer in layers],
        }
    ).encode()
