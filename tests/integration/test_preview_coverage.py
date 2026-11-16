"""Every file of the test store has a preview or says why not (SPEC 13 v0.2, 1).

The generated store holds every product family of plan v0.1 and the file
families of plan v0.2 (decision 5), also a version whose 0.7.x sidecar has
no ``sha256``; the application serves it with real render processes and the
real job worker (``tests.fixtures.preview_api``).
"""

from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import ConfigStore
from archiwista.index import IndexQueries
from archiwista.messages import message
from archiwista.previews.cache import INFO_NAME, cache_key, path_key
from archiwista.previews.types import PREVIEW_REASONS
from archiwista.refs import ObjectResolver, VersionRef
from tests.fixtures.api_store import STORE
from tests.fixtures.preview_api import (
    center_tile_url,
    decoded_png,
    preview_api,
    version_url,
)

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

KINDS = {"raster", "image", "vector", "points", "archive", "document", "auxiliary"}


def test_every_store_file_type_has_preview_or_reason(tmp_path: Path) -> None:
    """Each version is shown, built on request, or has a known reason in Polish.

    Every version of the catalog has a ``PreviewInfo``: ``ready`` with a
    thumbnail that decodes or an archive's members, ``unavailable`` with a
    known reason, or ``needs_build`` within the auto-build limits, which
    ``POST …/preview`` turns ``ready`` with map tiles. A version without a
    ``sha256`` is previewed under the key of its path, size and modification
    time.
    """
    with preview_api(tmp_path) as served:
        # Arrange
        versions = {version["path"]: version for version in served.versions()}

        # Act
        infos = {path: served.get(version_url(path)).json() for path in versions}
        thumbnails = {
            path: served.get(info["thumbnail_url"])
            for path, info in infos.items()
            if info["thumbnail_url"]
        }
        members = {
            path: served.get(info["members_url"])
            for path, info in infos.items()
            if info["members_url"]
        }
        posted = {
            path: served.post(version_url(path), {"force": False})
            for path, info in infos.items()
            if info["state"] == "needs_build"
        }
        records = {
            path: served.wait(response.json()["id"])
            for path, response in posted.items()
        }
        built = {path: served.get(version_url(path)).json() for path in posted}
        tiles = {
            path: served.get(center_tile_url(info)) for path, info in built.items()
        }
        unkeyed = {}
        with IndexQueries(served.api.paths.index_file) as queries:
            settings = ConfigStore(served.api.paths.config_file).load()
            resolver = ObjectResolver(queries, lambda: settings)
            for path, version in versions.items():
                if version["sha256"] is None:
                    status = (served.store.root / path).stat()
                    content = path_key(STORE, path, status.st_size, status.st_mtime_ns)
                    source = resolver.locate(
                        VersionRef(STORE, path), principal=LOCAL_OWNER
                    )
                    assert source.content_key == content
                    unkeyed[path] = served.pool.cache.has(cache_key(source), INFO_NAME)

    # Assert
    assert {info["kind"] for info in infos.values()} == KINDS
    for path, info in infos.items():
        assert info["ref"] == versions[path]["ref"]
        assert info["state"] in ("ready", "needs_build", "unavailable"), info
        assert info["auto_build"] is True, info
        reason = info["reason"]
        if reason is not None:
            code = reason["code"]
            assert code in PREVIEW_REASONS, info
            assert reason["message"] == message(f"preview.reason_{code}")
            assert reason["fix"] == message(f"preview.fix_{code}")
        if info["state"] == "unavailable":
            assert reason is not None, info
        else:
            assert path in thumbnails or path in members, info
    for path, response in thumbnails.items():
        assert response.status_code == 200, (path, response.text)
        assert decoded_png(response.content).size > 0
    for path, response in members.items():
        assert response.status_code == 200, (path, response.text)
        assert response.json()["total"] > 0
    assert posted and any(versions[path]["sha256"] is None for path in posted)
    for path, response in posted.items():
        assert response.status_code == 202, (path, response.text)
        record = records[path]
        assert record.state == "succeeded" and record.result is not None, record
        assert record.result["failed"] == [], record.result
        assert built[path]["state"] == "ready", built[path]
        assert tiles[path].status_code == 200, (path, tiles[path].text)
        assert decoded_png(tiles[path].content).shape[1:] == (256, 256)
    assert unkeyed and all(unkeyed.values()), unkeyed
    assert all(infos[path]["state"] != "unavailable" for path in unkeyed)
