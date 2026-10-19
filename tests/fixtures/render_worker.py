"""Render process of the preview tests: the real worker with a test renderer.

A test's ``RenderPool`` (or ``preview`` job) starts ``python -m
tests.fixtures.render_worker`` (``TEST_RENDER_WORKER``). ``TestRenderer``
handles every kind of file; a data file holds a JSON object telling it what
to do in every operation:

``sleep_s``
    Seconds to sleep first (time limits, overlap of builds): a number for
    every operation, or an object of seconds by operation (``{"build": 3}``).
``allocate_bytes``
    Bytes to allocate (the address-space limit).
``signal``
    Name of a signal the process sends itself (a crash).
``fail``
    Raise ``RuntimeError`` naming the file by its path, its real path and
    their directories (the detail must reach the pool without them).
``log``
    File to which each operation appends ``<pid> <op> <start> <end>``.
``needs_cog``, ``pixels``, ``build_bytes``
    The probe's ``needs_cog`` and ``pixels``; bytes a build writes.
``hostile``
    ``members``: after a ``WarpedVRT`` in this process, read planted files
    through the format table and report what came back
    (``tests.fixtures.hostile_files``).
``network``
    ``members``: let GDAL open URLs below this address.

Only ``members`` imports GDAL, as a real renderer would.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from archiwista.previews import worker
from archiwista.previews.types import (
    PREVIEW_KINDS,
    Extent,
    JsonObject,
    PreviewKind,
    PreviewProbe,
    PreviewSource,
)

TEST_RENDER_WORKER: tuple[str, ...] = (
    sys.executable,
    "-m",
    "tests.fixtures.render_worker",
)


class TestRenderer:
    """A renderer of every kind, doing what the file's instructions say."""

    __test__ = False  # not a test class
    kinds: frozenset[PreviewKind] = frozenset(PREVIEW_KINDS)

    def probe(self, source: PreviewSource) -> PreviewProbe:
        """Return a probe of the instructed ``needs_cog`` and ``pixels``."""
        steps = _act(source, "probe")
        return PreviewProbe(
            kind=source.kind,
            driver="test",
            needs_cog=bool(steps.get("needs_cog", False)),
            pixels=steps.get("pixels"),
        )

    def thumbnail(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        size: int,
        frame: Extent | None,
    ) -> bytes:
        """Return bytes naming the content, style and size."""
        _act(source, "thumbnail")
        return f"thumbnail {source.content_key} {style} {size} {frame}".encode()

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
        """Return bytes naming the content and the tile."""
        _act(source, "tile")
        return f"tile {source.content_key} {style} {z}/{x}/{y} {params}".encode()

    def members(self, source: PreviewSource) -> JsonObject:
        """Run the instructed probe of the process's environment."""
        steps = _act(source, "members")
        if "hostile" in steps:
            return _read_hostile(steps["hostile"])
        if "network" in steps:
            return _reach(str(steps["network"]))
        return {"members": []}

    def build(self, source: PreviewSource, probe: PreviewProbe, out_path: Path) -> None:
        """Write ``build_bytes`` bytes to ``out_path``."""
        steps = _act(source, "build")
        out_path.write_bytes(b"\0" * int(steps.get("build_bytes", 1024)))


def _act(source: PreviewSource, op: str) -> dict[str, Any]:
    """Follow the file's instructions for one operation; return them."""
    started = time.time()
    steps: dict[str, Any] = json.loads(source.paths[0].read_text(encoding="utf-8"))
    sleep = steps.get("sleep_s", 0)
    time.sleep(float(sleep.get(op, 0) if isinstance(sleep, dict) else sleep))
    if "allocate_bytes" in steps:
        held = bytearray(int(steps["allocate_bytes"]))
        del held
    if "signal" in steps:
        os.kill(os.getpid(), signal.Signals[steps["signal"]])
    if steps.get("fail"):
        path = source.paths[0]
        real = path.resolve()
        raise RuntimeError(
            f"cannot read {path} in {path.parent} (really {real} in {real.parent})"
        )
    if "log" in steps:
        with Path(steps["log"]).open("a", encoding="utf-8") as log:
            log.write(f"{os.getpid()} {op} {started} {time.time()}\n")
    return steps


def _read_hostile(planted: dict[str, Any]) -> JsonObject:
    """Read planted files through the format table after a ``WarpedVRT``."""
    import numpy as np
    import pyogrio.raw
    import rasterio
    from rasterio.vrt import WarpedVRT

    from archiwista.formats import file_format, open_raster, vector_source

    def attempt(read: Any) -> Any:
        try:
            return read()
        except Exception as error:  # the answer names the refusal
            return {"refused": type(error).__name__}

    genuine = Path(planted["ovr_base"])
    with (
        rasterio.open(genuine, driver="GTiff") as src,
        WarpedVRT(src, crs="EPSG:3857") as warped,
    ):
        warped.read(1)  # GDAL registers the VRT driver again

    def raster(path: Path) -> Any:
        with open_raster(path, file_format(path)) as src:
            overview = src.read(1, out_shape=(1, 4, 4))
            return {
                "max": int(np.max(src.read(1))),
                "overview_max": int(np.max(overview)),
                "overviews": src.overviews(1),
            }

    def vector(path: Path) -> Any:
        found = pyogrio.raw.read(vector_source(path, file_format(path)))
        return [str(value) for column in found[3] for value in column]

    answer: JsonObject = {}
    for name in [*planted["vrt_rasters"], planted["ovr_base"]]:
        answer[Path(name).name] = attempt(lambda name=name: raster(Path(name)))
    for name in planted["ogr_vrt_vectors"]:
        answer[Path(name).name] = attempt(lambda name=name: vector(Path(name)))
    return answer


def _reach(address: str) -> JsonObject:
    """Let GDAL, OGR and PROJ try the network; report how each ended."""
    import pyogrio
    import rasterio

    answer: JsonObject = {}
    try:
        with rasterio.open(f"/vsicurl/{address}/raster.tif") as src:
            answer["raster"] = src.driver
    except Exception as error:
        answer["raster"] = type(error).__name__
    try:
        answer["vector"] = str(pyogrio.read_info(f"{address}/vector.geojson"))
    except Exception as error:
        answer["vector"] = type(error).__name__
    return answer


def main() -> int:
    """Run the real render process with the test renderer."""
    return worker.main(renderers=(TestRenderer(),))


if __name__ == "__main__":
    sys.exit(main())
