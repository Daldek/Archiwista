"""Store summary: usage without link inflation, cleanup report, problems."""

from dataclasses import replace
from pathlib import Path

from archiwista.auth import ALL_PROJECTS
from archiwista.config import StoreConfig
from archiwista.index import IndexQueries, IndexWriter, ManifestStamp, ProductUsage
from archiwista.services import store_summary
from archiwista.sources import ProjectInfo, ProjectPin, SourceSegment
from tests.fixtures.index_data import (
    NMT,
    ORTO,
    PRODUCER,
    ROOT,
    STORE,
    link,
    problem,
    sha,
    slot_path,
    version,
    version_path,
    write_pass,
)

SHEET_A = slot_path(NMT, "M-34-1-A")
SHEET_B = slot_path(NMT, "M-34-1-B")
PHOTO = slot_path(ORTO, "N-33-1", ".tif")
CONFIG = StoreConfig(id=STORE, name="Zespół", kartograf=Path(ROOT), kind="share")


def test_store_summary_counts_linked_content_once(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Links and relabelled hard links add nothing to a product's usage."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2024-05-01_1", 1, size_bytes=700)
    # The same content under another label (a relabelled hard link).
    relabel = version(SHEET_A, "2024-05-01_2", 2, sha256=sha(1), size_bytes=700)
    other = version(SHEET_B, "2023-04-01_1", 3, size_bytes=300)
    photo = version(PHOTO, "2022_1", 4, product="orto", size_bytes=50)
    write_pass(
        writer,
        [
            current,
            relabel,
            link(SHEET_A, current),
            link(SHEET_A, current, kind="full_sheet"),
            other,
            link(SHEET_B, other),
            photo,
            link(PHOTO, photo),
        ],
    )

    # Act
    summary = store_summary(queries, CONFIG, visible=ALL_PROJECTS)

    # Assert
    assert summary.usage.products == (
        ProductUsage("nmt", 3, 1000),
        ProductUsage("orto", 1, 50),
    )
    assert summary.usage.unique_bytes == 1050
    assert (summary.store, summary.name, summary.kind) == (STORE, "Zespół", "share")


def test_store_summary_reports_unused_versions_with_reclaimable_size(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Not current, not a full sheet, not pinned; shared content frees nothing."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2024-05-01_1", 1, size_bytes=700)
    full = version(SHEET_A, "2019-03-01_1", 2, size_bytes=600)
    pinned = version(SHEET_A, "2016-06-01_1", 3, size_bytes=500)
    unused = version(SHEET_A, "2012-02-01_1", 4, size_bytes=400)
    shared = version(SHEET_A, "2012-02-01_2", 5, sha256=sha(1), size_bytes=700)
    photo_old = version(PHOTO, "2020_1", 6, product="orto", size_bytes=90)
    photo = version(PHOTO, "2022_1", 7, product="orto", size_bytes=50)
    write_pass(
        writer,
        [
            current,
            full,
            pinned,
            unused,
            shared,
            link(SHEET_A, current),
            link(SHEET_A, full, kind="full_sheet"),
            photo_old,
            photo,
            link(PHOTO, photo),
        ],
    )
    pin = ProjectPin(ROOT, Path(version_path(SHEET_A, "2016-06-01_1", sha(3))))
    writer.write_project(
        ProjectInfo(PRODUCER, ROOT, Path("/projekty/Raba"), "Raba", pins=(pin,)),
        store=STORE,
        stamp=ManifestStamp(1, 1),
    )

    # Act
    report = store_summary(queries, CONFIG, visible=ALL_PROJECTS).unused

    # Assert
    assert report.versions == 3
    assert report.products == (
        ProductUsage("nmt", 2, 1100),
        ProductUsage("orto", 1, 90),
    )
    assert report.unique_bytes == 1190
    # The relabelled copy of the current content frees no space.
    assert report.reclaimable_bytes == 490


def test_store_summary_problems_carry_fix_instructions(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Producer findings, checks, orphan link sidecars and missing pins show."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2024-05-01_1", 1)
    gone = version(SHEET_B, "2023-04-01_1", 2)
    incoming = f"{NMT}/versions/.incoming/host_1_abc"
    write_pass(
        writer,
        [
            current,
            link(SHEET_A, current),
            # The link's sidecar names a version that is not in the store.
            link(SHEET_B, gone),
            problem(incoming, "stale_incoming", segment=NMT, slot=None),
        ],
    )
    writer.record_issue(
        STORE, PRODUCER, path=SHEET_A, code="link_mismatch", segment=NMT, slot=SHEET_A
    )
    absent = version_path(SHEET_A, "2010-01-01_1", sha(9))
    writer.write_project(
        ProjectInfo(
            PRODUCER,
            ROOT,
            Path("/projekty/Raba"),
            "Raba",
            pins=(ProjectPin(ROOT, Path(absent), sha(9), "teren"),),
        ),
        store=STORE,
        stamp=ManifestStamp(1, 1),
    )

    # Act
    problems = store_summary(queries, CONFIG, visible=ALL_PROJECTS).problems

    # Assert
    found = {(p.code, p.path) for p in problems}
    assert found == {
        ("stale_incoming", incoming),
        ("link_mismatch", SHEET_A),
        ("orphan_sidecar", SHEET_B),
        ("missing_pin", absent),
    }
    by_code = {p.code: p for p in problems}
    assert by_code["link_mismatch"].origin == "check"
    assert gone.relative_path.as_posix() in by_code["orphan_sidecar"].message
    assert by_code["missing_pin"].project == "raba"
    assert "project download teren" in by_code["missing_pin"].instruction
    assert all(p.path and p.path in p.message and p.instruction for p in problems)


def test_store_summary_names_the_producer_each_problem_belongs_to(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """With a directory of each producer, an instruction names the producer at fault."""
    # Arrange
    writer, queries = index
    stray = f"{NMT}/stray"
    write_pass(writer, [problem(stray, "unknown_segment", segment=NMT, slot=None)])
    folder = "archives/stray"
    writer.write_segments(
        STORE, "imgw", [SourceSegment(folder, None, None, None, folder, False)]
    )
    writer.begin_pass(STORE, "imgw", segment=None, slots=None, full=False)
    other = replace(
        problem(f"{folder}/x", "unknown_segment", segment=folder, slot=None),
        producer="imgw",
    )
    writer.write_entries([other])
    writer.finish_pass()
    absent = version_path(SHEET_A, "2010-01-01_1", sha(9))
    writer.write_project(
        ProjectInfo(
            "imgw",
            ROOT,
            Path("/projekty/Wisla"),
            "Wisła",
            pins=(ProjectPin(ROOT, Path(absent), sha(9), "pomiary"),),
        ),
        store=STORE,
        stamp=ManifestStamp(1, 1),
    )
    config = StoreConfig(
        id=STORE,
        name="Zespół",
        kartograf=Path(ROOT),
        imgw=Path("/mnt/nas/imgw"),
        kind="share",
    )

    # Act
    problems = store_summary(queries, config, visible=ALL_PROJECTS).problems

    # Assert
    by_path = {p.path: p for p in problems}
    assert "kartograf" in by_path[stray].message
    assert "imgw" in by_path[other.relative_path.as_posix()].message
    assert "kartograf" not in by_path[other.relative_path.as_posix()].message
    assert "imgw project download pomiary" in by_path[absent].instruction
