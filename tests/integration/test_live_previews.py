r"""Previews on Kartograf's live 0.8.0 stores: each file shown or why not.

Criterion 1 of SPEC 13 v0.2 on the stores written by Kartograf's live
release test (``<udział>/kartograf/release-0.8.0/data`` and the others named
in ``docs/reports/v0.1-measurements.md``): every version of the catalog has
a ``PreviewInfo`` — ``ready`` with a thumbnail that decodes or an archive's
members, ``unavailable`` with a known reason described in Polish, or
``needs_build`` within the auto-build limits, which ``POST …/preview`` turns
``ready`` with map tiles. The table *extension → result* of each store is
printed for the report. Run deliberately, on the store itself (several
stores separated by ``os.pathsep``)::

    ARCHIWISTA_LIVE_STORE=<udział>/kartograf/release-0.8.0/data \\
        .venv/bin/python -m pytest -m live tests/integration/test_live_previews.py \\
        --no-cov -s

The store is only read: the index, the preview cache and the local COGs
live in the test directory, and the store's tree (names, sizes,
modification times) is the same afterwards.
"""

import os
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.messages import MESSAGES
from archiwista.previews.types import PREVIEW_REASONS
from archiwista.sources.registry import load_registry
from tests.fixtures.api_store import STORE
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import StoreManifest
from tests.fixtures.preview_api import (
    PreviewApi,
    center_tile_url,
    decoded_png,
    serve_previews,
    version_url,
)

# A JPEG sheet's header has no geotransform (its outline comes from the world
# file); rasterio says so while the footprint is read.
pytestmark = [
    pytest.mark.live,
    pytest.mark.filterwarnings("ignore:Dataset has no geotransform"),
]


def _stores() -> list[Path]:
    variable = os.environ.get("ARCHIWISTA_LIVE_STORE", "")
    stores = [Path(item) for item in variable.split(os.pathsep) if item]
    if not stores:
        pytest.skip("ARCHIWISTA_LIVE_STORE names the live store's data/ directory")
    return stores


def _tree(directory: Path) -> dict[str, tuple[int, int]]:
    found = {}
    for top, dirnames, filenames in os.walk(directory):
        for name in [*dirnames, *filenames]:
            info = os.lstat(os.path.join(top, name))
            relative = os.path.relpath(os.path.join(top, name), directory)
            found[relative] = (info.st_size, info.st_mtime_ns)
    return found


def _scanned(root: Path, directory: Path) -> AppPaths:
    """Index a live store fully under ``directory``; return its local paths."""
    paths = local_paths(directory)
    config = StoreConfig(id=STORE, name="Żywy", kartograf=root, kind="share")
    settings = AppSettings(offline=True, stores=(config,))
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        scan_store(registry.adapter("kartograf"), writer, settings, STORE, mode="full")
    return paths


def _outcome(info: dict[str, Any]) -> str:
    """Return a version's preview as the report's table names it."""
    reason = info["reason"]
    return info["state"] if reason is None else f"{info['state']} ({reason['code']})"


def _table(root: Path, results: dict[str, list[str]]) -> str:
    """Return the Markdown table *extension → result* of one store."""
    lines = [
        f"{root}:",
        "",
        "| Rozszerzenie | Wersje | Wynik |",
        "|---|---|---|",
    ]
    for extension, outcomes in sorted(results.items()):
        counted = ", ".join(
            f"{outcome} × {count}" for outcome, count in Counter(outcomes).most_common()
        )
        lines.append(f"| `{extension}` | {len(outcomes)} | {counted} |")
    return "\n".join(lines)


def _previews(served: PreviewApi) -> dict[str, list[str]]:
    """Check every version's preview (building the missing); return the table's rows."""
    versions = {version["path"]: version for version in served.versions()}
    infos = {path: served.get(version_url(path)).json() for path in versions}
    results: dict[str, list[str]] = defaultdict(list)
    for path, info in infos.items():
        assert info["ref"] == versions[path]["ref"], info
        assert info["state"] in ("ready", "needs_build", "unavailable"), info
        reason = info["reason"]
        if reason is not None:
            code = reason["code"]
            assert code in PREVIEW_REASONS, info
            assert reason["message"] == MESSAGES[f"preview_reason_{code}"]
            assert reason["fix"] == MESSAGES[f"preview_fix_{code}"]
        if info["state"] == "unavailable":
            assert reason is not None, info
        else:
            assert info["thumbnail_url"] or info["members_url"], info
        if info["thumbnail_url"]:
            thumbnail = served.get(info["thumbnail_url"])
            assert thumbnail.status_code == 200, (path, thumbnail.text)
            assert decoded_png(thumbnail.content).size > 0, path
        if info["members_url"]:
            members = served.get(info["members_url"])
            assert members.status_code == 200, (path, members.text)
            assert members.json()["total"] > 0, path
        outcome = _outcome(info)
        if info["state"] == "needs_build" and info["auto_build"]:
            posted = served.post(version_url(path), {"force": False})
            assert posted.status_code == 202, (path, posted.text)
            record = served.wait(posted.json()["id"])
            assert record.state == "succeeded" and record.result is not None, record
            assert record.result["failed"] == [], (path, record.result)
            built = served.get(version_url(path)).json()
            assert built["state"] == "ready", built
            tile = served.get(center_tile_url(built))
            assert tile.status_code == 200, (path, tile.text)
            assert decoded_png(tile.content).shape[1:] == (256, 256), path
            outcome = f"{outcome} → ready"
        extension = PurePosixPath(path).suffix.lower().lstrip(".") or path
        results[extension].append(outcome)
    return results


def test_live_store_file_types_have_preview_or_reason(tmp_path: Path) -> None:
    """Each live version is shown, built on request, or has a known reason."""
    for number, root in enumerate(_stores()):
        # Arrange
        before = _tree(root)
        paths = _scanned(root, tmp_path / f"store-{number}")
        # The served store is the configured one; the manifest only names it.
        manifest = StoreManifest(root.parent, 0, 0, (), ())

        # Act
        with serve_previews(manifest, paths) as served:
            results = _previews(served)
        print(_table(root, results))

        # Assert
        assert results, root
        assert _tree(root) == before, root
