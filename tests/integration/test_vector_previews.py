"""Vector previews in real render processes (plan v0.2, step 5b; decision 8).

A GeoPackage an editor has open (state (b)) is read only from a consistent
copy. Once the ``preview`` build kept that copy as ``source.gpkg`` in the
preview cache, the render processes read it and never open the file again.
"""

import hashlib
import os
from pathlib import Path

import pytest
import shapely

from archiwista.previews.cache import INFO_NAME, PreviewCache, cache_key
from archiwista.previews.pool import RenderPool
from archiwista.previews.protocol import RenderRequest, encode_request
from archiwista.previews.renderers.vector import VectorRenderer
from archiwista.previews.types import (
    SOURCE_GPKG_NAME,
    FileStat,
    PreviewProbe,
    PreviewSource,
    SourceStat,
    build_product,
)
from archiwista.previews.worker import answer_line
from tests.fixtures.own_data import GpkgEditor, make_own_folder

_BASIN = shapely.box(566_200, 241_200, 566_300, 241_300)
# Kraków, around the own-data fixture's layers.
_VIEW = [19.9, 50.0, 20.0, 50.1]


def _stat(path: Path) -> FileStat:
    found = path.stat()
    return FileStat(found.st_size, found.st_mtime_ns)


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() == 0, reason="root reads any file"
)
def test_open_gpkg_read_from_kept_copy(tmp_path: Path) -> None:
    """The kept ``source.gpkg`` serves the map: the file itself stays closed.

    The build (as the ``preview`` job runs it) copies the committed rows of a
    GeoPackage open in an editor; with the file unreadable afterwards, its
    features still come, from the copy alone.
    """
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_layers",))
    path = folder.path("gpkg_layers")
    editor = GpkgEditor(path)
    editor.begin()
    editor.insert("zlewnie", _BASIN, nazwa="Zlewnia C")
    editor.commit()
    editor.begin()
    editor.insert("zlewnie", _BASIN, nazwa="Zlewnia D")
    wal = path.with_name(path.name + "-wal")
    source = PreviewSource(
        f"file:p:{path.name}",
        hashlib.sha256(path.read_bytes()).hexdigest(),
        (path,),
        mutable=True,
        stat=SourceStat(_stat(path), _stat(wal)),
    )
    work = tmp_path / "work"
    work.mkdir()
    built = tmp_path / "built.gpkg"
    request = RenderRequest("1", "build", source, {"out": str(built), "force": False})
    params = {"layer": "zlewnie", "bbox": _VIEW, "zoom": 14, "limit": 100}

    # Act
    try:
        answer = answer_line(encode_request(request), (VectorRenderer(work_dir=work),))
        info = answer.files[INFO_NAME]
        with (
            PreviewCache(tmp_path / "previews", limit_bytes=100 * 1024**2) as cache,
            RenderPool(workers=1, cache=cache, work_dir=work) as pool,
        ):
            cache.put(cache_key(source), INFO_NAME, info)
            cache.put(cache_key(source), SOURCE_GPKG_NAME, built)
            path.chmod(0)
            try:
                found = pool.request("features", source, params).json()
            finally:
                path.chmod(0o600)
    finally:
        editor.close()

    # Assert
    assert build_product(PreviewProbe.from_bytes(info)) == SOURCE_GPKG_NAME
    assert sorted(item["properties"]["nazwa"] for item in found["features"]) == [
        "Zlewnia A",
        "Zlewnia B",
        "Zlewnia C",
    ]
