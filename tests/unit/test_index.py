"""Local index: writing passes and reading the catalog (plan v0.1, step 5)."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.errors import IndexQueryError
from archiwista.index import (
    SCHEMA_VERSION,
    AreaFilter,
    AreaRecord,
    IndexQueries,
    IndexWriter,
    ManifestStamp,
    SlotQuery,
    initialize,
)
from archiwista.sources import (
    EntryMeta,
    Footprint,
    ProjectInfo,
    ProjectPin,
    ProjectTask,
    SourceEntry,
    SourceSegment,
)
from tests.fixtures.index_data import (
    BDOT,
    CZ_NMT,
    NMT,
    ORTO,
    PRG,
    ROOT,
    SEGMENTS,
    STORE,
    box,
    link,
    polygon,
    problem,
    sha,
    skipped,
    slot_path,
    version,
    write_pass,
)

SHEET_A = slot_path(NMT, "M-34-100-C-c-4-1")
SHEET_B = slot_path(NMT, "M-34-100-C-c-4-2")
STAMP = ManifestStamp(mtime_ns=1, size=10)
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _slots(queries: IndexQueries, **filters: object) -> list[str]:
    page = queries.slots(SlotQuery(limit=200, **filters), visible=ALL_PROJECTS)  # type: ignore[arg-type]
    return [row.slot for row in page.items]


def test_index_rows_without_location_form_their_own_group(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Files without outline are counted apart and never dropped by an area."""
    # Arrange
    writer, queries = index
    sheet = version(SHEET_A, "2023-06-11_93763", 1)
    country = version(f"{PRG}/country/pl.zip", "2025-03-03", 2)
    unlocated = version(f"{BDOT}/teryt/1465.gpkg", "2020", 3, unit="1465")
    plain = slot_path(NMT, "M-34-100-C-d-1-4")
    entries = [
        sheet,
        link(SHEET_A, sheet),
        country,
        link(f"{PRG}/country/pl.zip", country),
        unlocated,
        link(f"{BDOT}/teryt/1465.gpkg", unlocated),
        problem(plain, "missing_sidecar", segment=NMT, slot=plain),
    ]
    write_pass(
        writer,
        entries,
        footprints={
            sheet.relative_path.as_posix(): box(19.5625, 49.0208, 19.59375, 49.0417),
            country.relative_path.as_posix(): Footprint("country", source="country"),
        },
    )
    far = AreaFilter(polygon((15.0, 50.0), (15.1, 50.0), (15.1, 50.1)), ("PL",))

    # Act
    everything = queries.slots(SlotQuery(), visible=ALL_PROJECTS)
    without = queries.slots(SlotQuery(location="none"), visible=ALL_PROJECTS)
    in_far_area = queries.slots(SlotQuery(area=far), visible=ALL_PROJECTS)
    abroad = queries.slots(
        SlotQuery(area=replace(far, countries=("CZ",))), visible=ALL_PROJECTS
    )

    # Assert
    assert (everything.groups.footprint, everything.groups.country) == (1, 1)
    assert everything.groups.none == 2
    assert {row.slot: row.location.reason for row in without.items} == {
        f"{BDOT}/teryt/1465.gpkg": "no_source",
        plain: "no_current",
    }
    assert without.groups == everything.groups
    assert in_far_area.groups.footprint == 0
    assert in_far_area.groups.country == 1
    assert in_far_area.groups.none == 2
    assert abroad.groups.country == 0
    assert {row.slot for row in abroad.items} == {
        f"{BDOT}/teryt/1465.gpkg",
        plain,
    }


def test_index_data_year_never_from_download_date(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """The year filter uses the data year; a version without one never matches."""
    # Arrange
    writer, queries = index
    flown = version(SHEET_A, "2019-08-09_86133", 1)
    undated = version(
        f"{BDOT}/teryt/1465.gpkg", "2025-11-15", 2, data_year=None, data_date=None
    )
    write_pass(
        writer,
        [
            flown,
            link(SHEET_A, flown),
            undated,
            link(f"{BDOT}/teryt/1465.gpkg", undated),
        ],
    )

    # Act
    of_2019 = queries.slots(SlotQuery(years=(2019, 2019)), visible=ALL_PROJECTS)
    of_2025 = _slots(queries, years=(2025, None))
    open_start = _slots(queries, years=(None, 2030))

    # Assert
    assert [row.slot for row in of_2019.items] == [SHEET_A]
    row_version = of_2019.items[0].version
    assert row_version is not None
    assert row_version.data_year == 2019
    assert row_version.downloaded_at is not None
    assert row_version.downloaded_at.year == 2025
    assert of_2025 == []
    assert open_start == [SHEET_A]


def test_index_two_links_to_one_version_count_its_size_once(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Usage sums each present version once, however many links hold it."""
    # Arrange
    writer, queries = index
    full = version(SHEET_A, "2023-06-11_93763", 1, size_bytes=12_000)
    older = version(SHEET_A, "2019-08-09_86133", 2, size_bytes=5_000)
    orto = version(slot_path(ORTO, "M-34-1", ".tif"), "2021-08-23_13756", 3)
    write_pass(
        writer,
        [
            link(SHEET_A, full),
            link(SHEET_A, full, kind="full_sheet"),
            full,
            older,
            orto,
            link(slot_path(ORTO, "M-34-1", ".tif"), orto),
        ],
    )

    # Act
    usage = queries.usage(STORE)
    card = queries.slot(STORE, SHEET_A, visible=ALL_PROJECTS)

    # Assert
    assert usage is not None
    assert usage.versions == 3
    assert usage.unique_bytes == 12_000 + 5_000 + 1_000
    assert {item.product: item.unique_bytes for item in usage.products} == {
        "nmt": 17_000,
        "orto": 1_000,
    }
    assert card is not None
    assert card.current == card.full_sheet == full.relative_path.as_posix()
    assert queries.usage("nieznany") is None


def test_index_same_content_in_two_versions_counts_once(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A relabelled version (same SHA-256, hard link) adds no usage."""
    # Arrange
    writer, queries = index
    first = version(SHEET_A, "2020", 1, sha256=sha(7), size_bytes=4_000)
    relabelled = version(SHEET_A, "2020_2021-07-07", 2, sha256=sha(7), size_bytes=4_000)
    write_pass(writer, [link(SHEET_A, relabelled), first, relabelled])

    # Act
    usage = queries.usage(STORE)

    # Assert
    assert usage is not None
    assert (usage.versions, usage.unique_bytes) == (2, 4_000)


def test_index_pin_to_older_version(index: tuple[IndexWriter, IndexQueries]) -> None:
    """A pinned older version is listed as pinned and kept out of clean-up rows."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2025-04-26_82710", 1)
    pinned = version(SHEET_A, "2019-08-09_86133", 2)
    loose = version(SHEET_A, "2012-08-02_72135", 3)
    write_pass(writer, [link(SHEET_A, current), current, pinned, loose])
    project = ProjectInfo(
        producer="kartograf",
        store=ROOT,
        path=Path("/projekty/Raba"),
        name="Raba",
        tasks=(ProjectTask("teren", "elevation download"),),
        pins=(
            ProjectPin(
                store=ROOT,
                version_path=pinned.relative_path,
                sha256=sha(2),
                task_id="teren",
            ),
        ),
    )

    # Act
    key = writer.write_project(project, store=STORE, stamp=STAMP)
    pinned_rows = queries.slots(
        SlotQuery(versions="pinned"), visible=ALL_PROJECTS
    ).items
    cleanup = _slots(queries, versions="noncurrent_unpinned")
    card = queries.slot(STORE, SHEET_A, visible=ALL_PROJECTS)

    # Assert
    assert key == "raba"
    assert [row.version.path for row in pinned_rows if row.version] == [
        pinned.relative_path.as_posix()
    ]
    pin = pinned_rows[0].version.pinned_by[0] if pinned_rows[0].version else None
    assert pin is not None
    assert (pin.project, pin.project_key, pin.task, pin.state) == (
        "Raba",
        "raba",
        "teren",
        "ok",
    )
    assert cleanup == [SHEET_A]
    assert queries.slots(
        SlotQuery(versions="noncurrent_unpinned"), visible=ALL_PROJECTS
    ).items[0].version.path == (loose.relative_path.as_posix())  # type: ignore[union-attr]
    assert card is not None
    assert {item.path: bool(item.pinned_by) for item in card.versions} == {
        current.relative_path.as_posix(): False,
        pinned.relative_path.as_posix(): True,
        loose.relative_path.as_posix(): False,
    }


def test_index_pin_states_follow_the_version(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A pin reports other content and a version gone from the disk."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2025-04-26_82710", 1)
    older = version(SHEET_A, "2019-08-09_86133", 2)
    write_pass(writer, [link(SHEET_A, current), current, older])
    pins = (
        ProjectPin(ROOT, current.relative_path, sha(99), "teren"),
        ProjectPin(ROOT, older.relative_path, sha(2), "archiwum"),
    )
    info = ProjectInfo("kartograf", ROOT, Path("/projekty/Raba"), "Raba", pins=pins)
    writer.write_project(info, store=STORE, stamp=STAMP)

    # Act
    write_pass(writer, [link(SHEET_A, current), skipped(current)])
    card = queries.slot(STORE, SHEET_A, visible=ALL_PROJECTS)

    # Assert
    assert card is not None
    states = {
        item.label: [pin.state for pin in item.pinned_by] for item in card.versions
    }
    assert states == {
        "2025-04-26_82710": ["sha256_mismatch"],
        "2019-08-09_86133": ["missing"],
    }


@pytest.mark.parametrize("versions", ["current", "all"])
def test_index_cursor_pages_cover_the_result_once(
    index: tuple[IndexWriter, IndexQueries], versions: str
) -> None:
    """Pages follow one another without gaps or repeats; the last has no cursor."""
    # Arrange
    writer, queries = index
    entries = []
    for number in range(7):
        slot = slot_path(NMT, f"M-34-100-C-c-{number}-1")
        newer = version(slot, "2023-06-11_93763", 10 * number + 1)
        older = version(slot, "2019-08-09_86133", 10 * number + 2)
        entries += [link(slot, newer), newer, older]
    write_pass(writer, entries)
    whole = queries.slots(SlotQuery(versions=versions, limit=200), visible=ALL_PROJECTS)  # type: ignore[arg-type]

    # Act
    seen = []
    cursor = None
    pages = 0
    while True:
        page = queries.slots(
            SlotQuery(versions=versions, limit=3, cursor=cursor),  # type: ignore[arg-type]
            visible=ALL_PROJECTS,
        )
        seen += [
            (row.slot, row.version.path if row.version else None) for row in page.items
        ]
        pages += 1
        cursor = page.next_cursor
        if cursor is None:
            break

    # Assert
    expected = [
        (row.slot, row.version.path if row.version else None) for row in whole.items
    ]
    assert seen == expected
    assert len(seen) == (7 if versions == "current" else 14)
    assert pages == (3 if versions == "current" else 5)


@pytest.mark.usefixtures("polish")
def test_index_cursor_of_another_query_is_rejected(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A cursor continues only its own query; a damaged one is refused."""
    # Arrange
    writer, queries = index
    entries = []
    for number in range(3):
        slot = slot_path(NMT, f"M-34-100-C-c-{number}-1")
        item = version(slot, "2023-06-11_93763", number + 1)
        entries += [link(slot, item), item]
    write_pass(writer, entries)
    cursor = queries.slots(SlotQuery(limit=1), visible=ALL_PROJECTS).next_cursor

    # Act / Assert
    with pytest.raises(IndexQueryError, match="Kursor"):
        queries.slots(
            SlotQuery(limit=1, product="nmt", cursor=cursor), visible=ALL_PROJECTS
        )
    with pytest.raises(IndexQueryError, match="Kursor"):
        queries.slots(SlotQuery(limit=1, cursor="nie-kursor"), visible=ALL_PROJECTS)
    with pytest.raises(IndexQueryError, match="Limit"):
        queries.slots(SlotQuery(limit=201), visible=ALL_PROJECTS)
    with pytest.raises(IndexQueryError, match="odwrócony"):
        queries.slots(SlotQuery(years=(2020, 2019)), visible=ALL_PROJECTS)


def test_index_filters_by_exact_unit(index: tuple[IndexWriter, IndexQueries]) -> None:
    """``unit`` matches one exact code, not codes starting with it."""
    # Arrange
    writer, queries = index
    county = version(f"{BDOT}/teryt/1465.gpkg", "2020", 1, unit="1465")
    commune = version(f"{BDOT}/teryt/146501.gpkg", "2021", 2, unit="146501")
    older = version(f"{BDOT}/teryt/1465.gpkg", "2019", 3, unit="1465")
    write_pass(
        writer,
        [
            county,
            older,
            link(f"{BDOT}/teryt/1465.gpkg", county),
            commune,
            link(f"{BDOT}/teryt/146501.gpkg", commune),
        ],
    )

    # Act
    exact = _slots(queries, unit="1465")
    with_product = _slots(queries, unit="1465", product="bdot10k")
    other_product = _slots(queries, unit="1465", product="nmt")
    every_version = queries.slots(
        SlotQuery(unit="1465", versions="all"), visible=ALL_PROJECTS
    )

    # Assert
    assert exact == with_product == [f"{BDOT}/teryt/1465.gpkg"]
    assert other_product == []
    assert [row.version.label for row in every_version.items if row.version] == [
        "2019",
        "2020",
    ]


def test_index_unseen_version_missing_then_removed_after_second_full_pass(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A version is marked missing first and removed only by a later full pass."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2025-04-26_82710", 1)
    gone = version(SHEET_A, "2019-08-09_86133", 2)
    write_pass(writer, [link(SHEET_A, current), current, gone], full=True)

    # Act
    marked = write_pass(writer, [link(SHEET_A, current), skipped(current)])
    card_marked = queries.slot(STORE, SHEET_A, visible=ALL_PROJECTS)
    missing_rows = queries.slots(
        SlotQuery(versions="all", status="missing"), visible=ALL_PROJECTS
    ).items
    removed = write_pass(writer, [link(SHEET_A, current), current], full=True)
    card_removed = queries.slot(STORE, SHEET_A, visible=ALL_PROJECTS)

    # Assert
    assert (marked.missing, marked.removed) == (1, 0)
    assert card_marked is not None
    missing = [item for item in card_marked.versions if item.state == "missing"]
    assert [item.label for item in missing] == ["2019-08-09_86133"]
    assert missing[0].missing_since is not None
    assert [row.version.label for row in missing_rows if row.version] == [
        "2019-08-09_86133"
    ]
    assert (removed.missing, removed.removed) == (0, 1)
    assert card_removed is not None
    assert [item.label for item in card_removed.versions] == ["2025-04-26_82710"]


def test_index_missing_version_seen_again_is_present(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A missing version that comes back (a reconnected share) is present again."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2025-04-26_82710", 1)
    write_pass(writer, [link(SHEET_A, current), current])
    write_pass(writer, [])
    marked = queries.slots(SlotQuery(status="missing"), visible=ALL_PROJECTS)

    # Act
    back = write_pass(writer, [link(SHEET_A, current), skipped(current)])
    page = queries.slots(SlotQuery(), visible=ALL_PROJECTS)

    # Assert
    assert [row.slot for row in marked.items] == [SHEET_A]
    assert back.reappeared == 1
    assert [(row.slot, row.status) for row in page.items] == [(SHEET_A, "ok")]


def test_index_unchanged_incremental_pass_writes_nothing(
    index: tuple[IndexWriter, IndexQueries], tmp_path: Path
) -> None:
    """Known versions and unchanged links cost no write at all."""
    # Arrange
    writer, _ = index
    newer = version(SHEET_A, "2025-04-26_82710", 1)
    older = version(SHEET_A, "2019-08-09_86133", 2)
    write_pass(
        writer,
        [link(SHEET_A, newer), link(SHEET_A, older, kind="full_sheet"), newer, older],
        footprints={newer.relative_path.as_posix(): box(19.5, 49.0, 19.6, 49.1)},
        full=True,
    )
    before = _changes(tmp_path / "index.sqlite")
    writer.begin_pass(STORE, "kartograf")
    known = writer.known_versions(NMT)

    # Act
    result = writer.write_entries(
        [
            link(SHEET_A, newer),
            link(SHEET_A, older, kind="full_sheet"),
            skipped(newer),
            skipped(older),
        ]
    )
    summary = writer.finish_pass()

    # Assert
    assert known == {
        newer.relative_path.parent.as_posix(): (newer.relative_path.name,),
        older.relative_path.parent.as_posix(): (older.relative_path.name,),
    }
    assert (result.versions_written, result.links_changed) == (0, 0)
    assert result.needs_footprint == ()
    assert summary.missing == summary.unlinked == 0
    assert _changes(tmp_path / "index.sqlite")["versions"] == before["versions"]


def test_index_known_versions_name_only_settled_directories(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A version directory with a problem, a missing or an unread version is listed.

    Only directories whose every file was a valid version at the last read
    are named, so a scan lists the others again and keeps their problems.
    """
    # Arrange
    writer, _ = index
    current = version(SHEET_A, "2025-04-26_82710", 1)
    gone = version(SHEET_A, "2019-08-09_86133", 2)
    flawed = version(SHEET_B, "2023-06-11_93763", 3)
    unread = skipped(version(SHEET_B, "2021-05-05_11111", 4))
    beside = f"{flawed.relative_path.parent.as_posix()}/M-34-100-C-c-4-2.xyz"
    write_pass(
        writer, [link(SHEET_A, current), current, gone, link(SHEET_B, flawed), flawed]
    )
    write_pass(
        writer,
        [
            link(SHEET_A, current),
            skipped(current),
            link(SHEET_B, flawed),
            skipped(flawed),
            problem(beside, "missing_sidecar", segment=NMT, slot=SHEET_B),
            unread,
        ],
    )

    # Act
    writer.begin_pass(STORE, "kartograf")
    known = writer.known_versions(NMT)
    everything = writer.known_versions()
    writer.abandon_pass()

    # Assert
    assert (
        known
        == everything
        == {current.relative_path.parent.as_posix(): (current.relative_path.name,)}
    )


def test_index_slots_beside_share_exactly_the_directory(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Neighbours of a slot lie in its directory: not deeper, not in a longer name."""
    # Arrange
    writer, _ = index
    wanted = f"{NMT}/bbox/601000_242000.asc"
    beside = f"{NMT}/bbox/601000_243000.asc"
    deeper = f"{NMT}/bbox/old/601000_244000.asc"
    longer = f"{NMT}/bbox2/601000_245000.asc"
    write_pass(
        writer,
        [
            entry
            for seed, slot in enumerate((wanted, beside, deeper, longer), start=1)
            for found in [version(slot, "2024-01-01_10000", seed)]
            for entry in (found, link(slot, found))
        ],
    )

    # Act
    near = writer.slots_beside(STORE, [wanted])
    alone = writer.slots_beside(STORE, [f"{NMT}/bbox/nowy.asc"])

    # Assert
    assert near == {wanted, beside}
    assert alone == {f"{NMT}/bbox/nowy.asc", wanted, beside}


def test_index_asks_footprints_of_new_and_pending_versions(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """New and never-located versions need a footprint; a full pass retries none."""
    # Arrange
    writer, queries = index
    located = version(SHEET_A, "2025-04-26_82710", 1)
    pending = version(SHEET_A, "2023-06-11_93763", 2)
    without = version(SHEET_A, "2019-08-09_86133", 3)
    writer.write_segments(STORE, "kartograf", [SEGMENTS[NMT]])
    writer.begin_pass(STORE, "kartograf", full=True)
    first = writer.write_entries([link(SHEET_A, located), located, pending, without])
    writer.write_footprints(
        STORE,
        [
            (located, box(19.5, 49.0, 19.6, 49.1)),
            (without, Footprint("none", reason="no_source")),
        ],
    )
    writer.finish_pass()
    card = queries.slot(STORE, SHEET_A, visible=ALL_PROJECTS)
    rescans = []

    # Act
    for full, entries in (
        (False, [skipped(located), skipped(pending), skipped(without)]),
        (True, [located, pending, without]),
    ):
        writer.begin_pass(STORE, "kartograf", full=full)
        result = writer.write_entries([link(SHEET_A, located), *entries])
        writer.finish_pass()
        rescans.append({entry.relative_path for entry in result.needs_footprint})

    # Assert
    assert len(first.needs_footprint) == 3
    assert card is not None
    assert {item.label: item.location.reason for item in card.versions} == {
        "2025-04-26_82710": None,
        "2023-06-11_93763": "pending",
        "2019-08-09_86133": "no_source",
    }
    assert rescans == [
        {pending.relative_path},
        {pending.relative_path, without.relative_path},
    ]


def test_index_link_moved_to_new_version_changes_current(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """The current version is the one the link's sidecar names."""
    # Arrange
    writer, queries = index
    old = version(SHEET_A, "2019-08-09_86133", 1)
    new = version(SHEET_A, "2025-04-26_82710", 2)
    write_pass(writer, [link(SHEET_A, old), old])

    # Act
    write_pass(writer, [link(SHEET_A, new), skipped(old), new])
    row = queries.slots(SlotQuery(), visible=ALL_PROJECTS).items[0]
    found = _slots(queries, q="2025-04-26_82710")

    # Assert
    assert row.version is not None
    assert row.version.label == "2025-04-26_82710"
    assert row.versions_count == 2
    assert found == [SHEET_A]


def test_index_slot_states_from_problems(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Problems set slot states; a fixed problem disappears with the next pass."""
    # Arrange
    writer, queries = index
    plain = slot_path(NMT, "M-34-100-C-d-1-4")
    broken = slot_path(NMT, "M-34-100-C-d-1-3")
    dev_segment = "orto/pl_1992_true"
    dev = slot_path(dev_segment, "M-34-100-C-c-4-4", ".tif")
    dev_version = version(dev, "2010-04-23_65018", 5)
    unknown = SourceSegment(dev_segment, None, None, None, dev_segment, False)
    write_pass(
        writer,
        [
            problem(plain, "missing_sidecar", segment=NMT, slot=plain),
            problem(broken, "invalid_sidecar", segment=NMT, slot=broken),
            problem(dev_segment, "unknown_segment", segment=dev_segment, slot=None),
            dev_version,
            link(dev, dev_version),
        ],
        segments=[*SEGMENTS.values(), unknown],
    )

    # Act
    states = {
        row.slot: row.status
        for row in queries.slots(SlotQuery(), visible=ALL_PROJECTS).items
    }
    fixed = version(plain, "2024-05-21_92288", 6)
    write_pass(writer, [fixed, link(plain, fixed)], segment=NMT)
    after = {
        row.slot: row.status
        for row in queries.slots(SlotQuery(), visible=ALL_PROJECTS).items
    }

    # Assert
    assert states == {
        plain: "no_sidecar",
        broken: "unreadable",
        dev: "unrecognized",
    }
    assert after[plain] == "ok"
    assert broken not in after
    assert [issue.code for issue in queries.issues(STORE)] == ["unknown_segment"]


def test_index_plain_file_without_version_is_its_own_version(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A file from before ``versions/`` is the current and only copy of its slot."""
    # Arrange
    writer, queries = index
    legacy = slot_path(NMT, "M-34-100-C-c-4-3")
    plain_link = link(legacy, None, label=None, data_year=2019, size_bytes=900)

    # Act
    write_pass(writer, [plain_link])
    row = queries.slots(SlotQuery(), visible=ALL_PROJECTS).items[0]
    usage = queries.usage(STORE)

    # Assert
    assert row.version is not None
    assert (row.version.path, row.version.data_year) == (legacy, 2019)
    assert row.version.is_current
    assert usage is not None
    assert usage.unique_bytes == 900


def test_index_abandoned_pass_marks_nothing_missing(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """An interrupted pass (store gone mid-scan) leaves every version present."""
    # Arrange
    writer, queries = index
    a = version(SHEET_A, "2025-04-26_82710", 1)
    b = version(SHEET_B, "2025-04-26_82711", 2)
    write_pass(writer, [link(SHEET_A, a), a, link(SHEET_B, b), b])

    # Act
    writer.begin_pass(STORE, "kartograf")
    writer.write_entries([link(SHEET_A, a), skipped(a)])
    writer.abandon_pass()
    writer.set_store_status(STORE, "unavailable", detail="udział odłączony")
    status = queries.status().stores[0]

    # Assert
    assert queries.slots(SlotQuery(status="missing"), visible=ALL_PROJECTS).items == ()
    assert (status.status, status.stale, status.detail) == (
        "unavailable",
        True,
        "udział odłączony",
    )
    assert status.versions == 2


def test_index_slot_scoped_pass_marks_only_its_slots(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A view refresh acts only on the slots it covers."""
    # Arrange
    writer, queries = index
    a_new = version(SHEET_A, "2025-04-26_82710", 1)
    a_old = version(SHEET_A, "2019-08-09_86133", 2)
    b_old = version(SHEET_B, "2019-08-09_86134", 3)
    write_pass(
        writer, [link(SHEET_A, a_new), a_new, a_old, link(SHEET_B, b_old), b_old]
    )

    # Act
    summary = write_pass(
        writer, [link(SHEET_A, a_new), skipped(a_new)], segment=NMT, slots=[SHEET_A]
    )
    missing = queries.slots(
        SlotQuery(versions="all", status="missing"), visible=ALL_PROJECTS
    ).items

    # Assert
    assert summary.missing == 1
    assert [row.version.label for row in missing if row.version] == ["2019-08-09_86133"]
    assert queries.slot(STORE, SHEET_B, visible=ALL_PROJECTS) is not None


def test_index_removed_store_takes_its_rows(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A store removed from the settings leaves nothing in the index."""
    # Arrange
    writer, queries = index
    a = version(SHEET_A, "2025-04-26_82710", 1)
    write_pass(
        writer,
        [link(SHEET_A, a), a],
        footprints={a.relative_path.as_posix(): box(19.5, 49.0, 19.6, 49.1)},
    )

    # Act
    writer.sync_stores({"inny": {"kartograf": "/dane/inny"}})
    status = queries.status()

    # Assert
    assert [state.store for state in status.stores] == ["inny"]
    assert queries.slots(SlotQuery(), visible=ALL_PROJECTS).items == ()
    assert queries.slot(STORE, SHEET_A, visible=ALL_PROJECTS) is None


def test_index_schema_change_rebuilds_an_empty_index(tmp_path: Path) -> None:
    """An index of another schema version is rebuilt empty, not migrated."""
    # Arrange
    path = tmp_path / "index.sqlite"
    with IndexWriter(path) as writer:
        writer.sync_stores({STORE: {"kartograf": ROOT}})
        a = version(SHEET_A, "2025-04-26_82710", 1)
        write_pass(writer, [link(SHEET_A, a), a])
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()

    # Act
    state = initialize(path)
    again = initialize(path)

    # Assert
    assert (state, again) == ("rebuilt", "current")
    with IndexQueries(path) as queries:
        assert queries.status().stores == ()
        assert queries.slots(SlotQuery(), visible=ALL_PROJECTS).items == ()


def test_index_producer_without_links_or_segments(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Each file of a flat producer is its own slot's current version."""
    # Arrange
    writer, queries = index
    writer.sync_stores({STORE: {"kartograf": ROOT}, "pomiary": {"external": "/dane"}})
    files = [
        SourceEntry(
            producer="external",
            store="/dane",
            relative_path=Path(name),
            kind="version",
            version_path=Path(name),
            meta=found,
        )
        for name, found in (
            ("opady.csv", _external_meta("opady.csv")),
            ("stany.csv", None),
        )
    ]
    writer.begin_pass("pomiary", "external", full=True)
    result = writer.write_entries(files)
    writer.write_footprints(
        "pomiary",
        [
            (entry, Footprint("none", reason="no_source"))
            for entry in result.needs_footprint
        ],
    )
    writer.finish_pass()

    # Act
    page = queries.slots(SlotQuery(store="pomiary"), visible=ALL_PROJECTS)
    known = writer.begin_pass("pomiary", "external")
    paths = writer.known_versions()
    writer.abandon_pass()

    # Assert
    assert [(row.slot, row.status, row.segment.segment) for row in page.items] == [
        ("opady.csv", "ok", None),
        ("stany.csv", "ok", None),
    ]
    assert [row.version.path for row in page.items if row.version] == [
        "opady.csv",
        "stany.csv",
    ]
    assert page.items[0].version is not None
    assert page.items[0].version.label == "2024"
    assert page.groups.none == 2
    assert known.segment is None
    # Each file is its own slot: no version directory to trust.
    assert paths == {}
    assert queries.slots(SlotQuery(store=STORE), visible=ALL_PROJECTS).items == ()


def test_index_filters_by_store_country_and_location(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Store, country and ``location=with`` narrow the rows; groups do not."""
    # Arrange
    writer, queries = index
    writer.sync_stores({STORE: {"kartograf": ROOT}, "drugi": {"kartograf": "/d"}})
    pl = version(SHEET_A, "2025-04-26_82710", 1)
    cz_slot = f"{CZ_NMT}/bbox/1_2_3_4.tif"
    cz = version(cz_slot, "2025-12-19", 2, country="CZ")
    other = version(SHEET_B, "2024-05-21_92288", 3)
    write_pass(
        writer,
        [link(SHEET_A, pl), pl, link(cz_slot, cz), cz],
        footprints={pl.relative_path.as_posix(): box(19.5, 49.0, 19.6, 49.1)},
    )
    write_pass(writer, [link(SHEET_B, other), other], store="drugi")

    # Act
    second = _slots(queries, store="drugi")
    czech = _slots(queries, country="CZ")
    located = queries.slots(
        SlotQuery(location="with", store=STORE), visible=ALL_PROJECTS
    )
    unknown_store = _slots(queries, store="brak")

    # Assert
    assert second == [SHEET_B]
    assert czech == [cz_slot]
    assert [row.slot for row in located.items] == [SHEET_A]
    assert (located.groups.footprint, located.groups.none) == (1, 1)
    assert unknown_store == []


def test_index_check_issue_survives_scans_until_cleared(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A problem found by a check job stays through scans until it is cleared."""
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2025-04-26_82710", 1)
    write_pass(writer, [link(SHEET_A, current), current])
    writer.record_issue(
        STORE,
        "kartograf",
        path=SHEET_A,
        code="link_mismatch",
        segment=NMT,
        slot=SHEET_A,
    )

    # Act
    write_pass(writer, [link(SHEET_A, current), skipped(current)], full=True)
    kept = queries.issues(STORE)
    cleared = writer.clear_issue(STORE, path=SHEET_A, code="link_mismatch")
    again = writer.clear_issue(STORE, path=SHEET_A, code="link_mismatch")

    # Assert
    assert [(issue.code, issue.slot, issue.origin) for issue in kept] == [
        ("link_mismatch", SHEET_A, "check")
    ]
    assert (cleared, again) == (True, False)
    assert queries.issues(STORE) == ()


def test_index_segment_recognised_later_reaches_its_slots(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A segment the producer learns to describe gives its slots a product."""
    # Arrange
    writer, queries = index
    segment = "orto/pl_1992_true"
    slot = slot_path(segment, "M-34-100-C-c-4-4", ".tif")
    item = version(slot, "2010-04-23_65018", 1, product=None, country=None)
    unknown = SourceSegment(segment, None, None, None, segment, False)
    write_pass(writer, [link(slot, item), item], segments=[unknown])
    before = queries.slots(SlotQuery(), visible=ALL_PROJECTS).items[0]

    # Act
    writer.write_segments(
        STORE,
        "kartograf",
        [
            SourceSegment(
                segment, "true_orto", "PL", None, "Prawdziwa ortofotomapa", True
            )
        ],
    )
    after = queries.slots(SlotQuery(product="true_orto"), visible=ALL_PROJECTS).items
    found = _slots(queries, q="prawdziwa")

    # Assert
    assert (before.status, before.product) == ("unrecognized", None)
    assert [(row.slot, row.status, row.country) for row in after] == [
        (slot, "ok", "PL")
    ]
    assert found == [slot]


def test_index_projects_keep_unique_keys_and_stamps(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Projects of one name get distinct keys; stamps and removal follow paths.

    A project without a store or a status has an empty stamp: it is read
    again on the next pass.
    """
    # Arrange
    writer, _ = index
    first = ProjectInfo(
        "kartograf", ROOT, Path("/projekty/a/Raba"), "Raba", status="ok"
    )
    second = ProjectInfo("kartograf", ROOT, Path("/projekty/b/Raba"), "Raba")
    broken = ProjectInfo(
        "kartograf", "/inny", Path("/projekty/Łąka"), "Łąka", problem="invalid"
    )

    # Act
    keys = [
        writer.write_project(first, store=STORE, stamp=ManifestStamp(1, 10)),
        writer.write_project(second, store=STORE, stamp=ManifestStamp(2, 20)),
        writer.write_project(broken, store=None, stamp=ManifestStamp(3, 30)),
        writer.write_project(first, store=STORE, stamp=ManifestStamp(4, 40)),
    ]
    stamps = writer.project_stamps("kartograf")
    removed = writer.remove_projects("kartograf", keep={"/projekty/a/Raba"})

    # Assert
    assert keys == ["raba", "raba-2", "laka", "raba"]
    assert stamps["/projekty/a/Raba"] == ManifestStamp(4, 40)
    assert stamps["/projekty/b/Raba"] == ManifestStamp(None, None)
    assert stamps["/projekty/Łąka"] == ManifestStamp(None, None)
    assert len(stamps) == 3
    assert removed == 2
    assert list(writer.project_stamps("kartograf")) == ["/projekty/a/Raba"]


def test_index_writer_refuses_misuse(index: tuple[IndexWriter, IndexQueries]) -> None:
    """Passes are explicit: one at a time, for a known store and one producer."""
    # Arrange
    writer, _ = index
    foreign = replace(version(SHEET_A, "2025-04-26_82710", 1), producer="external")

    # Act / Assert
    with pytest.raises(RuntimeError):
        writer.write_entries([])
    with pytest.raises(ValueError, match="sync_stores"):
        writer.begin_pass("brak", "kartograf")
    writer.begin_pass(STORE, "kartograf")
    with pytest.raises(RuntimeError):
        writer.begin_pass(STORE, "kartograf")
    with pytest.raises(ValueError, match="external"):
        writer.write_entries([foreign])
    writer.abandon_pass()
    with pytest.raises(ValueError):
        writer.write_area(
            AreaRecord("x", "drawn", {"type": "Point", "coordinates": [1, 2]}, NOW)
        )


def _external_meta(name: str) -> EntryMeta:
    return EntryMeta(
        producer="external",
        store="/dane",
        relative_path=Path(name),
        label="2024",
        data_year=2024,
    )


def _changes(path: Path) -> dict[str, object]:
    """Return row values a write would change, read without the index API."""
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT id, path, digest, state, location, indexed_at FROM versions"
            " ORDER BY id"
        ).fetchall()
        return {"versions": rows}
    finally:
        connection.close()
