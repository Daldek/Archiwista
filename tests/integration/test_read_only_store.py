"""A store without write permission is scanned and browsed unchanged (SPEC 13.3).

The whole generated tree (store and projects) is made read-only before the
scans; every read route is then called through the API, and the tree must
be identical afterwards: names, sizes, modification times and inodes.
"""

import os
from pathlib import Path

import pytest

from tests.fixtures.api_store import STORE, served_store
from tests.fixtures.make_store import StoreManifest

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")


def _tree(directory: Path) -> dict[str, tuple[int, int, int]]:
    found = {}
    for top, dirnames, filenames in os.walk(directory):
        for name in [*dirnames, *filenames]:
            info = os.lstat(os.path.join(top, name))
            found[os.path.relpath(os.path.join(top, name), directory)] = (
                info.st_size,
                info.st_mtime_ns,
                info.st_ino,
            )
    return found


def _read_only(directory: Path, *, read_only: bool) -> None:
    for top, _, filenames in os.walk(directory):
        os.chmod(top, 0o555 if read_only else 0o755)
        for name in filenames:
            os.chmod(os.path.join(top, name), 0o444 if read_only else 0o644)


def test_read_only_store_scan_and_browse(tmp_path: Path) -> None:
    """Full and incremental scans and every read route leave the tree as it was."""
    # Arrange
    snapshots: list[dict[str, tuple[int, int, int]]] = []

    def lock(store: StoreManifest) -> None:
        _read_only(store.output_dir, read_only=True)
        snapshots.append(_tree(store.output_dir))

    try:
        with served_store(tmp_path, before_scan=lock) as served:
            owner = served.owner
            row = owner.request("GET", "/slots?limit=1").json()["items"][0]
            card = owner.request("GET", f"/stores/{STORE}/slots/{row['slot']}").json()
            project = owner.request("GET", "/projects").json()["items"][0]["project"]
            paths = [
                "/health",
                "/sources",
                "/stores",
                f"/stores/{STORE}",
                "/products",
                "/slots?versions=all&limit=200",
                f"/stores/{STORE}/versions/{card['current']}",
                f"/stores/{STORE}/versions/{card['current']}/sidecar",
                "/map/footprints?bbox=14,49,24.2,55",
                "/map/sheets?bbox=19.9,50.0,20.0,50.05&system=1992&scale=1:10000",
                "/projects",
                f"/projects/{project}",
                f"/projects/{project}/status",
                "/settings",
            ]

            # Act
            statuses = {path: owner.request("GET", path).status_code for path in paths}
            after = _tree(served.store.output_dir)
    finally:
        _read_only(tmp_path / "store", read_only=False)

    # Assert
    assert statuses == dict.fromkeys(paths, 200)
    assert after == snapshots[0]
