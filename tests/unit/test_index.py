"""Local index: writing passes and reading the catalog (plan v0.1, step 5)."""

import sqlite3
from dataclasses import dataclass, field, replace
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
    SlotRow,
    initialize,
)
from archiwista.sources import (
    EntryMeta,
    Footprint,
    ProjectInfo,
    ProjectPin,
    ProjectTask,
    SourceEntry,
    SourceObservation,
    SourceSegment,
)
from tests.fixtures.index_data import (
    BDOT,
    CZ_NMT,
    NMT,
    ORTO,
    PRG,
    PRODUCER,
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
    version_path,
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


def _observation(
    slot_entry: SourceEntry,
    name: str,
    repeats: SourceEntry,
    *,
    seen_at: datetime = NOW,
) -> SourceEntry:
    """Return the record of a register file of the slot, repeating a version."""
    return replace(
        slot_entry,
        kind="observation",
        relative_path=Path(f"{NMT}/observations/{name}.json"),
        version_path=repeats.version_path,
        meta=None,
        observation=SourceObservation(
            seen_at=seen_at,
            url=f"https://example.org/{name}.zip",
            etag='"6ad58aac"',
            last_modified="Mon, 19 Oct 2026 03:12:44 GMT",
            size_bytes=1234,
            sha256=sha(9),
        ),
    )


def test_index_observation_is_history_and_never_a_slot_version_or_link(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A producer's observation changes no slot, version, link or issue."""
    # Arrange
    writer, queries = index
    sheet = version(SHEET_A, "2023-06-11_93763", 1)
    history = _observation(sheet, "2024-01-01_aabbccdd", sheet)
    elsewhere = replace(
        history,
        relative_path=Path(f"{NMT}/observations/2024-01-02_11223344.json"),
        slot_path=Path(f"{NMT}/other"),
    )
    unrecorded = replace(
        history,
        relative_path=Path(f"{NMT}/observations/2024-01-03_55667788.json"),
        observation=None,
    )

    # Act
    summary = write_pass(
        writer, [history, sheet, link(SHEET_A, sheet), elsewhere, unrecorded]
    )
    page = queries.slots(SlotQuery(), visible=ALL_PROJECTS)

    # Assert
    assert [(row.slot, row.status) for row in page.items] == [(SHEET_A, "ok")]
    assert [row.version.path for row in page.items if row.version] == [
        sheet.relative_path.as_posix()
    ]
    assert page.items[0].versions_count == 1
    assert (summary.missing, summary.unlinked, summary.issues_resolved) == (0, 0, 0)
    assert queries.issues(STORE) == ()
    (record,) = queries.observations(STORE, SHEET_A)
    assert (record.path, record.version, record.seen_at) == (
        f"{NMT}/observations/2024-01-01_aabbccdd.json",
        sheet.relative_path.as_posix(),
        NOW,
    )
    assert (record.url, record.etag, record.size_bytes, record.sha256) == (
        "https://example.org/2024-01-01_aabbccdd.zip",
        '"6ad58aac"',
        1234,
        sha(9),
    )
    assert queries.observations(STORE, f"{NMT}/other") == ()


def test_index_observation_is_forgotten_when_a_pass_does_not_see_it(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A register file that is gone leaves the history; the slot stays."""
    # Arrange
    writer, queries = index
    sheet = version(SHEET_A, "2023-06-11_93763", 1)
    history = _observation(sheet, "2024-01-01_aabbccdd", sheet)
    write_pass(writer, [sheet, link(SHEET_A, sheet), history])
    seen_again = write_pass(writer, [skipped(sheet), link(SHEET_A, sheet), history])

    # Act
    write_pass(writer, [skipped(sheet), link(SHEET_A, sheet)])

    # Assert
    assert (seen_again.missing, seen_again.issues_resolved) == (0, 0)
    assert queries.observations(STORE, SHEET_A) == ()
    assert _slots(queries) == [SHEET_A]


def test_index_observations_come_newest_first_and_go_with_their_slot(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """The history of a slot is listed newest first and ends with the slot."""
    # Arrange
    writer, queries = index
    sheet = version(SHEET_A, "2023-06-11_93763", 1)
    older = _observation(sheet, "2024-01-01_aabbccdd", sheet)
    newer = _observation(
        sheet, "2024-02-01_11223344", sheet, seen_at=NOW.replace(year=2027)
    )
    write_pass(writer, [sheet, link(SHEET_A, sheet), older, newer], full=True)
    assert [r.seen_at.year for r in queries.observations(STORE, SHEET_A)] == [
        2027,
        2026,
    ]

    # Act
    write_pass(writer, [], full=True)
    write_pass(writer, [], full=True)

    # Assert
    assert _slots(queries) == []
    assert queries.observations(STORE, SHEET_A) == ()


def _keyed(entry: SourceEntry, key: str) -> SourceEntry:
    """Return an entry of a producer that names its slots itself and has no links."""
    return replace(entry, slot_key=key)


@dataclass
class _Producer:
    """A producer's current versions of its slots, and what it was asked."""

    answers: dict[str, SourceEntry | None]
    asked: list[str] = field(default_factory=list)

    def __call__(self, key: str) -> Path | None:
        self.asked.append(key)
        found = self.answers[key]
        return None if found is None else found.relative_path


def _rows(queries: IndexQueries) -> dict[str, SlotRow]:
    page = queries.slots(SlotQuery(limit=200), visible=ALL_PROJECTS)
    return {row.slot: row for row in page.items}


def _current(queries: IndexQueries) -> dict[str, tuple[str, str | None]]:
    """Return each slot's status and the path of its current version."""
    return {
        slot: (row.status, row.version.path if row.version else None)
        for slot, row in _rows(queries).items()
    }


def _keyed_slots() -> tuple[SourceEntry, SourceEntry, SourceEntry]:
    """Return two versions of a slot and the only version of another."""
    return (
        _keyed(version(SHEET_A, "2023-06-11_93763", 1), "a"),
        _keyed(version(SHEET_A, "2024-05-21_92288", 2), "a"),
        _keyed(version(SHEET_B, "2022-01-01_1", 3), "b"),
    )


def test_index_a_slot_with_a_key_takes_the_producers_current_version(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """No link names it: the producer is asked once, at the end of the pass."""
    # Arrange
    writer, queries = index
    old, new, lone = _keyed_slots()
    producer = _Producer({"a": new, "b": lone})

    # Act
    summary = write_pass(writer, [old, new, lone], current=producer)

    # Assert
    assert sorted(producer.asked) == ["a", "b"]
    assert (summary.current, summary.unlinked) == (2, 0)
    assert _current(queries) == {
        SHEET_A: ("ok", new.relative_path.as_posix()),
        SHEET_B: ("ok", lone.relative_path.as_posix()),
    }
    assert _rows(queries)[SHEET_A].versions_count == 2


def test_index_a_pass_that_changed_nothing_asks_for_no_slot_and_keeps_the_answers(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """An unchanged incremental pass reads nothing; no link seen is no link gone."""
    # Arrange
    writer, queries = index
    old, new, lone = _keyed_slots()
    producer = _Producer({"a": new, "b": lone})
    write_pass(writer, [old, new, lone], current=producer)
    before = _current(queries)
    producer.asked.clear()
    known = [skipped(old), skipped(new), skipped(lone)]

    # Act
    asked = write_pass(writer, known, current=producer)
    without = write_pass(writer, known)

    # Assert
    assert producer.asked == []
    assert (asked.current, asked.unlinked, asked.missing) == (0, 0, 0)
    assert (without.current, without.unlinked) == (0, 0)
    assert _current(queries) == before


def test_index_a_new_version_asks_for_its_slot_only_and_moves_its_current_version(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """What a pass wrote is what it asks about: a slot it did not touch is left."""
    # Arrange
    writer, queries = index
    old, new, lone = _keyed_slots()
    producer = _Producer({"a": new, "b": lone})
    write_pass(writer, [old, new, lone], current=producer)
    producer.asked.clear()
    newest = _keyed(version(SHEET_A, "2025-01-01_3", 4), "a")
    producer.answers["a"] = newest

    # Act
    summary = write_pass(
        writer, [skipped(old), skipped(new), newest, skipped(lone)], current=producer
    )

    # Assert
    assert producer.asked == ["a"]
    assert summary.current == 1
    assert _current(queries)[SHEET_A] == ("ok", newest.relative_path.as_posix())
    assert _current(queries)[SHEET_B] == ("ok", lone.relative_path.as_posix())


def test_index_a_current_version_that_is_gone_gives_way_to_the_producers_next_choice(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A version that goes missing makes its slot asked, and the slot moves on."""
    # Arrange
    writer, queries = index
    old, new, lone = _keyed_slots()
    producer = _Producer({"a": new, "b": lone})
    write_pass(writer, [old, new, lone], current=producer)
    producer.asked.clear()
    producer.answers["a"] = old

    # Act
    summary = write_pass(writer, [skipped(old), skipped(lone)], current=producer)
    versions = queries.slots(SlotQuery(versions="all", limit=200), visible=ALL_PROJECTS)

    # Assert
    assert producer.asked == ["a"]
    assert (summary.missing, summary.current) == (1, 1)
    assert _current(queries)[SHEET_A] == ("ok", old.relative_path.as_posix())
    assert {
        row.version.path: row.version.state for row in versions.items if row.version
    } == {
        old.relative_path.as_posix(): "present",
        new.relative_path.as_posix(): "missing",
        lone.relative_path.as_posix(): "present",
    }


def test_index_a_slot_the_producer_names_no_version_of_has_none_and_no_older_one(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A broken version in a slot: its problem shows, no older version stands in."""
    # Arrange
    writer, queries = index
    old, new, lone = _keyed_slots()
    producer = _Producer({"a": new, "b": lone})
    write_pass(writer, [old, new, lone], current=producer)
    broken_dir = version_path(SHEET_A, "2025-02-02_9", sha(9)).rpartition("/")[0]
    broken = _keyed(problem(broken_dir, "invalid_json", segment=NMT, slot=SHEET_A), "a")
    producer.answers["a"] = None

    # Act
    summary = write_pass(
        writer, [skipped(old), skipped(new), broken, skipped(lone)], current=producer
    )

    # Assert
    assert summary.current == 1
    assert _current(queries)[SHEET_A] == ("unreadable", None)
    assert _rows(queries)[SHEET_A].versions_count == 2
    assert [(i.code, i.path, i.slot) for i in queries.issues(STORE)] == [
        ("invalid_json", broken_dir, SHEET_A)
    ]


def test_index_an_answer_the_pass_did_not_see_waits_for_the_pass_that_does(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A version published since the listing is no current version the index lacks."""
    # Arrange
    writer, queries = index
    old, new, lone = _keyed_slots()
    producer = _Producer({"a": new, "b": lone})
    write_pass(writer, [old, new, lone], current=producer)
    fresh = _keyed(version(SHEET_A, "2025-01-01_3", 4), "a")
    published_since = _keyed(version(SHEET_A, "2025-03-03_8", 8), "a")
    producer.answers["a"] = published_since

    # Act
    early = write_pass(
        writer, [skipped(old), skipped(new), fresh, skipped(lone)], current=producer
    )
    kept = _current(queries)[SHEET_A]
    later = write_pass(
        writer,
        [skipped(old), skipped(new), skipped(fresh), published_since, skipped(lone)],
        current=producer,
    )

    # Assert
    assert early.current == 0
    assert kept == ("ok", new.relative_path.as_posix())
    assert later.current == 1
    assert _current(queries)[SHEET_A] == (
        "ok",
        published_since.relative_path.as_posix(),
    )


def test_index_slots_a_killed_pass_left_without_a_current_version_are_asked_again(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """The batches are written before ``finish_pass``: nothing else would heal them."""
    # Arrange
    writer, queries = index
    old, new, lone = _keyed_slots()
    producer = _Producer({"a": new, "b": lone})
    writer.write_segments(STORE, PRODUCER, list(SEGMENTS.values()))
    writer.begin_pass(STORE, PRODUCER)
    writer.write_entries([old, new, lone])
    writer.abandon_pass()
    assert _current(queries)[SHEET_A] == ("missing", None)
    known = [skipped(old), skipped(new), skipped(lone)]

    # Act
    healed = write_pass(writer, known, current=producer)
    asked = sorted(producer.asked)
    producer.asked.clear()
    again = write_pass(writer, known, current=producer)

    # Assert
    assert (asked, healed.current) == (["a", "b"], 2)
    assert _current(queries) == {
        SHEET_A: ("ok", new.relative_path.as_posix()),
        SHEET_B: ("ok", lone.relative_path.as_posix()),
    }
    assert (producer.asked, again.current) == ([], 0)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("missing_sidecar", "no_sidecar"),
        ("invalid_sidecar", "unreadable"),
        ("invalid_json", "unreadable"),
        ("invalid_meta", "unreadable"),
        ("unknown_schema", "unreadable"),
        ("unreadable", "unreadable"),
        ("size_mismatch", "missing"),
    ],
)
def test_index_a_problem_of_a_version_directory_gives_its_slot_the_status_of_its_code(
    index: tuple[IndexWriter, IndexQueries], code: str, status: str
) -> None:
    """The problem belongs to the slot, not to a path equal to the slot's."""
    # Arrange
    writer, queries = index
    directory = version_path(SHEET_A, "2025-02-02_9", sha(9)).rpartition("/")[0]
    found = _keyed(problem(directory, code, segment=NMT, slot=SHEET_A), "a")

    # Act
    write_pass(writer, [found])

    # Assert
    assert _current(queries) == {SHEET_A: (status, None)}


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


def test_index_project_is_its_directory_with_a_manifest_of_each_producer(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Both manifests of a directory are one project with one key, Kartograf's first.

    Each manifest keeps its store, state, stamp, tasks and pins: writing one
    again replaces only its own, and removing one keeps the project and its key
    until the last one goes.
    """
    # Arrange
    writer, queries = index
    current = version(SHEET_A, "2025-04-26_82710", 1)
    write_pass(writer, [link(SHEET_A, current), current])
    directory = Path("/projekty/Raba")
    imgw = ProjectInfo(
        "imgw",
        "/dane/imgw",
        directory,
        "Raba",
        tasks=(
            ProjectTask("przeplywy", "series select"),
            ProjectTask("opady", "series select"),
        ),
        status="not_downloaded",
    )
    kartograf = ProjectInfo(
        "kartograf",
        ROOT,
        directory,
        "Raba",
        tasks=(ProjectTask("teren", "elevation download"),),
        pins=(ProjectPin(ROOT, current.relative_path, sha(1), "teren"),),
        status="ok",
    )

    # Act
    keys = [
        writer.write_project(imgw, store=None, stamp=ManifestStamp(1, 10)),
        writer.write_project(kartograf, store=STORE, stamp=ManifestStamp(2, 20)),
        writer.write_project(
            replace(imgw, tasks=imgw.tasks[:1]), store=None, stamp=ManifestStamp(3, 30)
        ),
    ]
    both = queries.project("raba", visible=ALL_PROJECTS)
    stamps = {name: writer.project_stamps(name) for name in ("kartograf", "imgw")}
    removed_first = writer.remove_projects("kartograf", keep=set())
    left = queries.projects(visible=ALL_PROJECTS)
    removed_last = writer.remove_projects("imgw", keep=set())

    # Assert
    assert keys == ["raba", "raba", "raba"]
    assert both is not None
    assert [(m.producer, m.store, m.status) for m in both.project.manifests] == [
        ("kartograf", STORE, "ok"),
        ("imgw", None, "not_downloaded"),
    ]
    assert [(t.producer, t.task_id) for t in both.tasks] == [
        ("kartograf", "teren"),
        ("imgw", "przeplywy"),
    ]
    assert [(p.producer, p.task, p.state) for p in both.pins] == [
        ("kartograf", "teren", "ok")
    ]
    assert (both.project.tasks, both.project.pins) == (2, 1)
    assert stamps == {
        "kartograf": {str(directory): ManifestStamp(2, 20)},
        "imgw": {str(directory): ManifestStamp(None, None)},
    }
    assert removed_first == 1
    assert [(p.key, p.producers, p.tasks, p.pins) for p in left] == [
        ("raba", ("imgw",), 1, 0)
    ]
    assert removed_last == 1
    assert queries.projects(visible=ALL_PROJECTS) == ()


# The projects of an index of schema 12 (v0.4): one row per producer and directory.
_SCHEMA_12_PROJECTS = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    producer TEXT NOT NULL,
    path TEXT NOT NULL,
    access_key TEXT NOT NULL,
    name TEXT NOT NULL,
    store_id INTEGER,
    store_dir TEXT NOT NULL,
    status TEXT,
    problem TEXT,
    manifest_mtime_ns INTEGER,
    manifest_size INTEGER,
    scanned_at TEXT NOT NULL,
    UNIQUE (producer, path)
);
INSERT INTO projects (key, producer, path, access_key, name, store_dir, scanned_at)
VALUES
    ('raba', 'kartograf', '/projekty/Raba', '/projekty/Raba', 'Raba', '/dane',
        '2026-10-25T12:00:00+00:00'),
    ('raba-2', 'imgw', '/projekty/Raba', '/projekty/Raba', 'Raba', '/dane/imgw',
        '2026-10-25T12:00:00+00:00');
PRAGMA user_version = 12;
"""


def test_index_of_schema_12_is_rebuilt_into_one_project_per_directory(
    tmp_path: Path,
) -> None:
    """An index of a project per producer and directory is rebuilt, not migrated.

    Its two projects of one directory are gone; the manifests written again
    make one project.
    """
    # Arrange
    path = tmp_path / "index.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(_SCHEMA_12_PROJECTS)
    connection.close()

    # Act
    state = initialize(path)
    with IndexQueries(path) as queries:
        emptied = queries.projects(visible=ALL_PROJECTS)
    with IndexWriter(path) as writer:
        writer.sync_stores({STORE: {"kartograf": ROOT, "imgw": "/dane/imgw"}})
        keys = [
            writer.write_project(
                ProjectInfo(producer, root, Path("/projekty/Raba"), "Raba"),
                store=STORE,
                stamp=STAMP,
            )
            for producer, root in (("kartograf", ROOT), ("imgw", "/dane/imgw"))
        ]
    with IndexQueries(path) as queries:
        listed = queries.projects(visible=ALL_PROJECTS)

    # Assert
    assert state == "rebuilt"
    assert emptied == ()
    assert keys == ["raba", "raba"]
    assert [(p.key, p.producers) for p in listed] == [("raba", ("kartograf", "imgw"))]


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
