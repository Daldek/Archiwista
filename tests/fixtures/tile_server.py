"""A local XYZ tile server standing in for an online basemap.

It runs on its own port, so its origin differs from Archiwista's, and
answers every ``/{z}/{x}/{y}.png`` with one grey PNG (with
``Access-Control-Allow-Origin``, as public tile servers send it). Each
request is recorded with its ``Referer`` and ``Origin`` headers, so an
interface test can check that the browser fetched basemap tiles within the
page's CSP and without a ``Referer``.
"""

import re
import struct
import threading
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TILE_PX = 256
_TILE_PATH = re.compile(r"/\d+/\d+/\d+\.png")


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
        """Return the XYZ template of a basemap setting."""
        return f"{self.origin}/{{z}}/{{x}}/{{y}}.png"

    def tiles(self) -> list[TileRequest]:
        """Return the tile requests answered so far."""
        return [
            request
            for request in list(self.requests)
            if _TILE_PATH.fullmatch(request.path)
        ]


@contextmanager
def tile_server() -> Iterator[TileServer]:
    """Serve grey tiles on a free port of 127.0.0.1 until the block ends."""
    tile = grey_png()
    served = TileServer(port=0)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Answer a tile, or 404 for any other path."""
            with lock:
                served.requests.append(
                    TileRequest(
                        path=self.path,
                        referer=self.headers.get("Referer"),
                        origin=self.headers.get("Origin"),
                    )
                )
            if not _TILE_PATH.fullmatch(self.path):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(tile)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(tile)

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
