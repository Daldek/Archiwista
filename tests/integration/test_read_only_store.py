"""A store without write permission is scanned and browsed unchanged (SPEC 13.3).

The whole generated tree (store and projects) is made read-only before the
scans; every read route is then called through the API, and the tree must
be identical afterwards: names, sizes, modification times and inodes.
"""

from pathlib import Path

import pytest

from tests.fixtures.api_store import STORE, served_store
from tests.fixtures.make_store import StoreManifest
from tests.fixtures.read_only_mount import Snapshot, set_read_only, tree

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")


def test_read_only_store_scan_and_browse(tmp_path: Path) -> None:
    """Full and incremental scans and every read route leave the tree as it was."""
    # Arrange
    snapshots: list[Snapshot] = []

    def lock(store: StoreManifest) -> None:
        set_read_only(store.base, read_only=True)
        snapshots.append(tree(store.base))

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
                "/settings",
            ]

            # Act
            statuses = {path: owner.request("GET", path).status_code for path in paths}
            after = tree(served.store.base)
    finally:
        set_read_only(tmp_path / "store", read_only=False)

    # Assert
    assert statuses == dict.fromkeys(paths, 200)
    assert after == snapshots[0]
