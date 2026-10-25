"""A store with the directory of a source that is not available (SPEC 5.8).

The directory of an unavailable source is skipped by the scans and stays in the
settings; the store's other directories are scanned and probed as before, and a
store whose every source is unavailable starts no scan. Every test runs real
worker processes on a generated Kartograf store; the IMGWTools package looks
not installed, so the source ``imgw`` is ``not_installed`` everywhere.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from archiwista.index import IndexWriter
from archiwista.jobs import JobRecord, ScanScheduler
from archiwista.sources.registry import load_registry
from tests.fixtures.jobs import STORE, jobs_env
from tests.fixtures.missing_package import hide_packages

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")


def _scans(jobs: tuple[JobRecord, ...]) -> list[JobRecord]:
    """Return the store scans a tick submitted (besides ``own_scan``)."""
    return [job for job in jobs if job.kind == "scan"]


def test_scan_and_probe_go_on_without_the_directory_of_an_unavailable_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Kartograf directory is scanned and probed; the IMGW entry stays."""
    # Arrange
    hide_packages(monkeypatch, "imgwtools")
    imgw = tmp_path / "imgw"
    imgw.mkdir()
    with jobs_env(tmp_path, monkeypatch, imgw=imgw) as env:
        registry = load_registry(cache_dir=env.paths.cache_dir)
        scheduler = ScanScheduler(
            env.jobs, env.settings, registry, index_path=env.paths.index_file
        )
        try:
            # Act
            (planned,) = _scans(scheduler.tick())
            first = env.wait(planned.id)
            notices = [
                event.data
                for event in env.jobs.events(first.id)
                if event.type == "notice"
            ]
            with IndexWriter(env.paths.index_file) as writer:
                writer.set_store_status(STORE, "unavailable", detail="udział odłączony")
            later = datetime.now(UTC) + timedelta(minutes=16)
            (probed,) = _scans(scheduler.tick(later))
            second = env.wait(probed.id)
            kept = env.settings.get().stores[0].roots()
            indexed = env.state()
        finally:
            scheduler.stop()

    # Assert
    assert first.state == "succeeded"
    assert first.result is not None and first.result["entries"] > 0
    assert [(item["level"], item["code"]) for item in notices] == [
        ("warning", "source_skipped")
    ]
    assert "imgw" in str(notices[0]["message"])
    assert second.state == "succeeded"
    assert kept == {"kartograf": env.store.root, "imgw": imgw}
    assert (indexed.status, indexed.slots > 0) == ("available", True)


def test_store_of_only_unavailable_sources_starts_no_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing can scan the store: the scheduler leaves it alone."""
    # Arrange
    hide_packages(monkeypatch, "imgwtools")
    imgw = tmp_path / "imgw"
    imgw.mkdir()
    with jobs_env(tmp_path, monkeypatch, imgw=imgw, kartograf=False) as env:
        registry = load_registry(cache_dir=env.paths.cache_dir)
        scheduler = ScanScheduler(
            env.jobs, env.settings, registry, index_path=env.paths.index_file
        )
        try:
            # Act
            submitted = scheduler.tick()
            scanned = env.jobs.scan_history(STORE).finished_at
        finally:
            scheduler.stop()

    # Assert
    assert _scans(submitted) == []
    assert scanned is None
