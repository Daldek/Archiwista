"""A share that disconnects and comes back, under the scan scheduler (6b).

SPEC 13 v0.1, criterion 4: the index keeps its entries while the share is
gone, the store is only probed meanwhile, and the first scan after it comes
back is incremental and finds the new version.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.jobs import JobRecord, ScanScheduler
from archiwista.sources.registry import load_registry
from tests.fixtures.jobs import STORE, jobs_env
from tests.fixtures.store_edits import add_version

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")


def _one(jobs: tuple[JobRecord, ...]) -> JobRecord:
    assert len(jobs) == 1, jobs
    return jobs[0]


def test_disconnect_preserves_index_then_incremental_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disconnected: index kept, probe only; reconnected: incremental scan."""
    with jobs_env(tmp_path, monkeypatch, kind="share") as env:
        registry = load_registry(cache_dir=env.paths.cache_dir)
        scheduler = ScanScheduler(
            env.jobs, env.settings, registry, index_path=env.paths.index_file
        )
        root = env.store.root
        away = root.with_name("data-away")
        link = next(
            entry for entry in env.store.by_kind("link") if entry.case == "regular"
        )
        try:
            # Arrange
            first = env.wait(_one(scheduler.tick()).id)
            rows = env.rows()
            later = datetime.now(UTC) + timedelta(minutes=16)

            # Act
            root.rename(away)
            root.mkdir()  # the empty mount point of a share that is gone
            lost = env.wait(_one(scheduler.tick(later)).id)
            gone = env.state()
            kept = env.rows()
            probed = scheduler.tick(later + timedelta(minutes=1))
            root.rmdir()
            away.rename(root)
            version = add_version(root, link.path, label="2026-10-01_99999")
            back = env.wait(_one(scheduler.tick(later + timedelta(minutes=2))).id)
            state = env.state()
            slot = env.queries.slot(STORE, link.path, visible=ALL_PROJECTS)
            after = env.rows()
        finally:
            scheduler.stop()

    # Assert
    assert (first.params["mode"], first.state) == ("full", "succeeded")
    assert (lost.params["mode"], lost.state) == ("incremental", "failed")
    assert lost.error is not None and lost.error.code == "store_unavailable"
    assert str(root) in lost.error.detail
    assert (gone.status, gone.stale, gone.missing_versions) == ("unavailable", True, 0)
    assert kept == rows
    assert probed == ()
    assert (back.params["mode"], back.state) == ("incremental", "succeeded")
    assert back.result is not None
    assert (back.result["versions_written"], back.result["missing"]) == (1, 0)
    assert (state.status, state.stale) == ("available", False)
    assert slot is not None and slot.current == version
    unchanged = [row for row in rows if row[0] != link.path]
    assert unchanged == [row for row in after if row[0] != link.path]
