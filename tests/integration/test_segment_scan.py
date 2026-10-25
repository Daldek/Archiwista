"""A scan of one segment goes to the producers that own it (ADR 0032, decision 9).

Every test runs real worker processes (``tests.fixtures.job_worker``) on a generated
Kartograf store and, where a test says so, on a store of IMGWTools beside it or
instead of it, offline. The index knows the owner of a segment from the scan that
described it; a producer that reads only its whole directory (IMGWTools) cannot scan
one segment, and refuses the job as ``unsupported``.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from archiwista.jobs import JobRecord
from archiwista.messages import message
from tests.fixtures.jobs import STORE, JobsEnv, jobs_env
from tests.fixtures.make_store import NMT

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

DATASET = "pl.imgw.hydro_daily"
UNKNOWN = "newproduct/pl_experimental"

type Stores = Callable[[str], Path]


def _scanned(record: JobRecord) -> list[tuple[str, str | None]]:
    """Return ``(producer, segment)`` of each segment a succeeded scan read."""
    assert record.state == "succeeded" and record.result is not None, record.error
    return [(item["producer"], item["segment"]) for item in record.result["segments"]]


def _refused(record: JobRecord, env: JobsEnv, *, producer: str, segment: str) -> None:
    """Require a job that failed as ``unsupported`` before it scanned anything."""
    assert (record.state, record.result) == ("failed", None)
    assert record.error is not None
    assert (record.error.code, record.error.reason) == ("unsupported", None)
    assert record.error.detail == message(
        "job.segment_scan_unsupported", producer=producer, segment=segment
    )
    assert [e for e in env.jobs.events(record.id) if e.type == "progress"] == []


def test_a_kartograf_store_scans_a_segment_the_index_knows_or_does_not_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name nobody owns goes to the producers that scan by segment, as before."""
    # Arrange
    with jobs_env(tmp_path, monkeypatch) as env:
        # Act
        first = env.run("scan", mode="full", segment=NMT)
        owners = env.queries.segment_producers(STORE, NMT)
        again = env.run("scan", mode="incremental", segment=NMT)

        # Assert
        assert _scanned(first) == [("kartograf", NMT)]
        assert owners == ("kartograf",)
        assert _scanned(again) == [("kartograf", NMT)]
        for record in (first, again):
            assert record.result is not None
            assert (record.result["segment"], record.result["projects"]) == (NMT, None)


def test_a_store_of_only_imgw_files_refuses_a_segment_scan_and_scans_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, imgw_store: Stores
) -> None:
    """A dataset is a label for IMGWTools: the job fails, the index stays as it was."""
    # Arrange
    pytest.importorskip("imgwtools")
    with jobs_env(
        tmp_path, monkeypatch, imgw=imgw_store("complete"), kartograf=False
    ) as env:
        whole = env.scan("full")
        indexed = env.state()

        # Act
        refused = env.run("scan", segment=DATASET)
        unknown = env.run("scan", segment=UNKNOWN)
        after = env.state()

        # Assert
        assert env.queries.segment_producers(STORE, DATASET) == ("imgw",)
        assert {producer for producer, _ in _scanned(whole)} == {"imgw"}
        _refused(refused, env, producer="imgw", segment=DATASET)
        _refused(unknown, env, producer="imgw", segment=UNKNOWN)
        assert indexed.slots > 0 and indexed.versions > 0
        assert indexed.indexed_at is not None
        assert (after.slots, after.versions, after.indexed_at) == (
            indexed.slots,
            indexed.versions,
            indexed.indexed_at,
        )


def test_a_mixed_store_scans_a_segment_only_through_its_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, imgw_store: Stores
) -> None:
    """The owner of a Kartograf segment scans it; the IMGW directory is not read."""
    # Arrange
    pytest.importorskip("imgwtools")
    with jobs_env(tmp_path, monkeypatch, imgw=imgw_store("complete")) as env:
        whole = env.scan("full")

        # Act
        kartograf = env.run("scan", segment=NMT)
        imgw = env.run("scan", segment=DATASET)

        # Assert
        assert {producer for producer, _ in _scanned(whole)} == {"kartograf", "imgw"}
        assert _scanned(kartograf) == [("kartograf", NMT)]
        _refused(imgw, env, producer="imgw", segment=DATASET)
