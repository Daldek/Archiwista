"""Index queries: search by identifiers, the map, areas and cards (step 5)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.errors import IndexQueryError
from archiwista.index import (
    AreaFilter,
    AreaRecord,
    IndexQueries,
    IndexWriter,
    MapQuery,
    SlotQuery,
    VersionsMode,
)
from archiwista.sources import Footprint, SourceSegment
from tests.fixtures.index_data import (
    BDOT,
    CZ_NMT,
    NMT,
    ORTO,
    SEGMENTS,
    STORE,
    box,
    link,
    polygon,
    slot_path,
    version,
    write_pass,
)

SHA_A = "fdd30535e8085f861a106824ba4401a7e96187a6c54abc33511803acd87b4623"
KU = "cadastre/cz_cadastral-map_shp"
CITY = "boundaries/city"
SEARCH_SEGMENTS = [
    *SEGMENTS.values(),
    SourceSegment(KU, "map", "CZ", "cz.cuzk.cadastral_map", "Mapa katastralna", True),
    SourceSegment(CITY, "city", "PL", None, "Granice Łodzi", True),
]
Index = tuple[IndexWriter, IndexQueries]


def _write_search_store(writer: IndexWriter) -> None:
    sheet = slot_path(NMT, "M-34-100-C-c-4-1")
    sibling = slot_path(NMT, "M-34-100-C-c-4-2")
    other = slot_path(NMT, "N-34-130-D-d-2-4")
    flight = version(
        sheet, "2023-06-11_93763", 1, sha256=SHA_A, survey_work_id="GK.6640.93763.2023"
    )
    older = version(sibling, "2019-08-09_86133", 2)
    entries = [
        flight,
        link(sheet, flight),
        older,
        link(sibling, older),
        version(other, "2023-07-01_11111", 3),
    ]
    entries.append(link(other, entries[-1]))
    for path, label, unit, seed in (
        (f"{BDOT}/teryt/1465.gpkg", "2020", "1465", 4),
        (f"{BDOT}/teryt/146501.gpkg", "2021", "146501", 5),
        (f"{KU}/ku/773921.zip", "2026-05-23", "773921", 6),
        (slot_path(ORTO, "N-34-115-D-c-3-4", ".tif"), "2021-08-23_13756", None, 7),
        (f"{CITY}/teryt/1061.zip", "2024", "1061", 8),
    ):
        item = version(path, label, seed, unit=unit)
        entries += [item, link(path, item)]
    write_pass(writer, entries, segments=SEARCH_SEGMENTS)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("M-34-100-C-c-4-1", ["M-34-100-C-c-4-1.asc"]),
        ("M-34-100-C-c", ["M-34-100-C-c-4-1.asc", "M-34-100-C-c-4-2.asc"]),
        ("1465", ["1465.gpkg", "146501.gpkg"]),
        ("773921", ["773921.zip"]),
        ("2023-06-11_93763", ["M-34-100-C-c-4-1.asc"]),
        ("GK.6640.93763.2023", ["M-34-100-C-c-4-1.asc"]),
        ("fdd30535", ["M-34-100-C-c-4-1.asc"]),
        (SHA_A.upper(), ["M-34-100-C-c-4-1.asc"]),
        ("fdd3053", []),
        ("ortofotomapa", ["N-34-115-D-c-3-4.tif"]),
        ("lodzi", ["1061.zip"]),
        ("nmt 2023", ["M-34-100-C-c-4-1.asc", "N-34-130-D-d-2-4.asc"]),
        ("  ", None),
    ],
    ids=[
        "sheet",
        "sheet_prefix",
        "teryt",
        "ku",
        "label",
        "survey_work",
        "sha256_prefix",
        "sha256_full_uppercase",
        "seven_hex_digits",
        "product_name",
        "polish_letters_folded",
        "every_word",
        "blank",
    ],
)
def test_queries_search_finds_identifiers(
    index: Index, text: str, expected: list[str] | None
) -> None:
    """A word finds sheets, units, labels, survey work and SHA-256 prefixes."""
    # Arrange
    writer, queries = index
    _write_search_store(writer)
    everything = [
        row.name
        for row in queries.slots(SlotQuery(limit=200), visible=ALL_PROJECTS).items
    ]

    # Act
    found = [
        row.name
        for row in queries.slots(
            SlotQuery(q=text, limit=200), visible=ALL_PROJECTS
        ).items
    ]

    # Assert
    assert found == (everything if expected is None else expected)


def test_queries_search_finds_old_versions_by_their_sha256(index: Index) -> None:
    """In the all-versions mode a SHA-256 prefix picks the version itself."""
    # Arrange
    writer, queries = index
    sheet = slot_path(NMT, "M-34-100-C-c-4-1")
    current = version(sheet, "2025-04-26_82710", 1)
    old = version(sheet, "2019-08-09_86133", 2, sha256=SHA_A)
    write_pass(writer, [link(sheet, current), current, old])

    # Act
    slots = queries.slots(SlotQuery(q=SHA_A[:12]), visible=ALL_PROJECTS)
    versions = queries.slots(
        SlotQuery(q=SHA_A[:12], versions="all"), visible=ALL_PROJECTS
    )

    # Assert
    assert [row.version.label for row in slots.items if row.version] == [
        "2025-04-26_82710"
    ]
    assert [row.version.label for row in versions.items if row.version] == [
        "2019-08-09_86133"
    ]


def _write_grid(writer: IndexWriter, count: int) -> None:
    """Sheets 0.04° wide in rows of 100, 0.05° apart, from 14°E 49°N."""
    entries = []
    footprints = {}
    for number in range(count):
        column, row = number % 100, number // 100
        slot = slot_path(NMT, f"T-{number:05d}")
        item = version(slot, "2023-06-11_93763", number + 1)
        entries += [link(slot, item), item]
        min_lon, min_lat = 14.0 + column * 0.05, 49.0 + row * 0.05
        footprints[item.relative_path.as_posix()] = box(
            min_lon, min_lat, min_lon + 0.04, min_lat + 0.04
        )
    write_pass(writer, entries, footprints=footprints)


def test_queries_map_lists_5000_footprints_then_aggregates(index: Index) -> None:
    """Up to 5000 footprints come as outlines, more as a grid of counts."""
    # Arrange
    writer, queries = index
    _write_grid(writer, 5001)
    five_thousand = (13.9, 48.9, 19.1, 51.49)
    everything = (13.9, 48.9, 19.1, 51.6)

    # Act
    listed = queries.footprints(MapQuery(bbox=five_thousand), visible=ALL_PROJECTS)
    gridded = queries.footprints(
        MapQuery(bbox=everything, grid_columns=10), visible=ALL_PROJECTS
    )

    # Assert
    assert (listed.total, listed.aggregated, len(listed.items)) == (5000, False, 5000)
    assert listed.cells == ()
    assert listed.items[0].geometry["type"] == "Polygon"
    assert (gridded.total, gridded.aggregated, gridded.items) == (5001, True, ())
    assert sum(cell.count for cell in gridded.cells) == 5001
    assert all(
        everything[0] <= cell.min_lon < cell.max_lon <= everything[2] + 1e-9
        and everything[1] <= cell.min_lat < cell.max_lat <= everything[3] + 1e-9
        for cell in gridded.cells
    )
    assert gridded.groups.footprint == 5001


def test_queries_map_draws_the_versions_of_the_mode(index: Index) -> None:
    """The map shows current versions by default and every version on demand."""
    # Arrange
    writer, queries = index
    sheet = slot_path(NMT, "M-34-100-C-c-4-1")
    current = version(sheet, "2025-04-26_82710", 1)
    full = version(sheet, "2019-08-09_86133", 2)
    outline = box(19.5625, 49.0208, 19.59375, 49.0417)
    write_pass(
        writer,
        [link(sheet, current), link(sheet, full, kind="full_sheet"), current, full],
        footprints={
            current.relative_path.as_posix(): outline,
            full.relative_path.as_posix(): outline,
        },
    )
    view = (19.0, 48.5, 20.0, 49.5)

    # Act
    modes: tuple[VersionsMode, ...] = ("current", "all", "full_sheet")
    labels = {
        mode: sorted(
            item.label or ""
            for item in queries.footprints(
                MapQuery(bbox=view, versions=mode), visible=ALL_PROJECTS
            ).items
        )
        for mode in modes
    }

    # Assert
    assert labels == {
        "current": ["2025-04-26_82710"],
        "all": ["2019-08-09_86133", "2025-04-26_82710"],
        "full_sheet": ["2019-08-09_86133"],
    }


def test_queries_area_of_one_sheet_leaves_out_its_neighbours(index: Index) -> None:
    """Sheets sharing only an edge or a corner with the area are not in it."""
    # Arrange
    writer, queries = index
    entries = []
    footprints = {}
    for column in range(3):
        for row in range(3):
            slot = slot_path(NMT, f"S-{column}-{row}")
            item = version(slot, "2023-06-11_93763", 10 * column + row + 1)
            entries += [link(slot, item), item]
            footprints[item.relative_path.as_posix()] = box(*_cell(column, row))
    triangle = version(slot_path(NMT, "T-0"), "2023-06-11_93763", 99)
    entries += [link(slot_path(NMT, "T-0"), triangle), triangle]
    # A triangle whose box reaches into the middle sheet but whose outline does not.
    footprints[triangle.relative_path.as_posix()] = Footprint(
        "footprint",
        wgs84=polygon((19.0, 49.0), (19.035, 49.0), (19.0, 49.025)),
        source="header",
    )
    write_pass(writer, entries, footprints=footprints)
    west, south, east, north = _cell(1, 1)
    sheet = polygon((west, south), (east, south), (east, north), (west, north))
    inner = polygon((19.035, 49.025), (19.06, 49.025), (19.04, 49.04))
    wider = polygon((19.025, 49.015), (19.07, 49.015), (19.07, 49.05), (19.025, 49.05))

    # Act
    found = {
        name: [
            row.name
            for row in queries.slots(
                SlotQuery(area=AreaFilter(area), limit=200), visible=ALL_PROJECTS
            ).items
        ]
        for name, area in (("sheet", sheet), ("inner", inner), ("wider", wider))
    }

    # Assert
    assert found["sheet"] == found["inner"] == ["S-1-1.asc"]
    assert sorted(found["wider"]) == sorted(
        f"S-{column}-{row}.asc" for column in range(3) for row in range(3)
    )


def _cell(column: int, row: int) -> tuple[float, float, float, float]:
    """Return the box of a sheet in a grid of sheets sharing their edges."""
    return (
        19.0 + column * 0.03125,
        49.0 + row * 0.02083,
        19.0 + (column + 1) * 0.03125,
        49.0 + (row + 1) * 0.02083,
    )


def test_queries_card_and_version_detail(index: Index) -> None:
    """The card lists versions; a version has its metadata, outline and sidecar."""
    # Arrange
    writer, queries = index
    sheet = slot_path(NMT, "M-34-100-C-c-4-1")
    current = version(
        sheet,
        "2025-04-26_82710",
        1,
        survey_work_id="GK-FOTO.6201.11.2025",
        resolution="1m",
        source_files=("nmt/x/versions/a.asc",),
    )
    write_pass(
        writer,
        [link(sheet, current), current],
        footprints={
            current.relative_path.as_posix(): box(
                19.5625,
                49.0208,
                19.59375,
                49.0417,
                native={
                    "type": "Polygon",
                    "coordinates": [[[1, 2], [3, 2], [3, 4], [1, 2]]],
                },
                native_crs="EPSG:2180",
            )
        },
    )
    path = current.relative_path.as_posix()

    # Act
    card = queries.slot(STORE, sheet, visible=ALL_PROJECTS)
    detail = queries.version(STORE, path, visible=ALL_PROJECTS)
    sidecar = queries.sidecar(STORE, path)

    # Assert
    assert card is not None and card.current == path
    assert detail is not None
    assert (detail.survey_work_id, detail.resolution, detail.native_crs) == (
        "GK-FOTO.6201.11.2025",
        "1m",
        "EPSG:2180",
    )
    assert detail.source_files == ("nmt/x/versions/a.asc",)
    assert detail.summary.location.source == "sheet"
    assert detail.footprint is not None
    assert detail.footprint["coordinates"] == [
        [
            [19.5625, 49.0208],
            [19.59375, 49.0208],
            [19.59375, 49.0417],
            [19.5625, 49.0417],
            [19.5625, 49.0208],
        ]
    ]
    assert sidecar == {"schema": "kartograf-meta/1", "path": path}
    assert queries.version(STORE, "nmt/brak.asc", visible=ALL_PROJECTS) is None
    assert queries.slot("inny", sheet, visible=ALL_PROJECTS) is None


def test_queries_group_lists_files_of_one_request(index: Index) -> None:
    """Files of one producer request (PL and CZ) are found together."""
    # Arrange
    writer, queries = index
    request = '{"bbox":[1,2,3,4]}'
    pl_slot = f"{NMT}/bbox/1_2_3_4.tif"
    cz_slot = f"{CZ_NMT}/bbox/5_6_7_8.tif"
    pl = version(pl_slot, "2025-12-19", 1, parent_request=request)
    cz = version(cz_slot, "2025-12-19", 2, parent_request=request, country="CZ")
    alone = version(f"{NMT}/bbox/9_9_9_9.tif", "2025-12-20", 3)
    write_pass(writer, [pl, link(pl_slot, pl), cz, link(cz_slot, cz), alone])

    # Act
    members = queries.group(request)

    # Assert
    assert [(member.slot, member.country, member.is_current) for member in members] == [
        (cz_slot, "CZ", True),
        (pl_slot, "PL", True),
    ]
    assert queries.group("{}") == ()


def test_queries_products_and_slots_for_a_view_refresh(index: Index) -> None:
    """Products list their segments; a view lists slots and unlocated entries."""
    # Arrange
    writer, queries = index
    sheet = slot_path(NMT, "M-34-100-C-c-4-1")
    kron = slot_path(ORTO, "M-34-100-C-c-4-1", ".tif")
    cz_slot = f"{CZ_NMT}/bbox/1_2_3_4.tif"
    unlocated = f"{BDOT}/teryt/1465.gpkg"
    entries = []
    for path, seed in ((sheet, 1), (kron, 2), (cz_slot, 3), (unlocated, 4)):
        item = version(path, "2023-06-11_93763", seed)
        entries += [item, link(path, item)]
    write_pass(
        writer,
        entries,
        footprints={
            entries[0].relative_path.as_posix(): box(19.5, 49.0, 19.6, 49.1),
            entries[2].relative_path.as_posix(): box(19.5, 49.0, 19.6, 49.1),
            entries[4].relative_path.as_posix(): box(15.0, 50.0, 15.1, 50.1),
        },
    )

    # Act
    products = {item.product: item for item in queries.products()}
    in_view = queries.slots_in_bbox(STORE, (19.0, 48.5, 20.0, 49.5))
    nmt_only = queries.slots_in_bbox(STORE, (19.0, 48.5, 20.0, 49.5), product="nmt")
    without = queries.entries_without_footprint(STORE)

    # Assert
    assert products["nmt"].countries == ("CZ", "PL")
    assert [segment.segment.segment for segment in products["nmt"].segments] == [
        CZ_NMT,
        NMT,
    ]
    assert (products["nmt"].slots, products["nmt"].versions) == (2, 2)
    assert [(item.slot, item.unit) for item in in_view] == [
        (sheet, "M-34-100-C-c-4-1"),
        (kron, "M-34-100-C-c-4-1"),
    ]
    assert [item.slot for item in nmt_only] == [sheet]
    assert [(entry.slot_path, entry.kind) for entry in without] == [
        (Path(unlocated), "version")
    ]
    assert without[0].store == "/mnt/nas/kartograf/data"


def test_queries_status_reports_jobs_and_areas_are_kept(
    index: Index, tmp_path: Path
) -> None:
    """The state shows the last scan and a running job; an area is read back."""
    # Arrange
    writer, queries = index
    connection = sqlite3.connect(tmp_path / "index.sqlite")
    connection.executemany(
        "INSERT INTO jobs (id, kind, actor, store, state, created_at, finished_at)"
        " VALUES (?, ?, 'local', ?, ?, ?, ?)",
        [
            (
                "j1",
                "scan",
                STORE,
                "succeeded",
                "2026-10-18T10:00:00+00:00",
                "2026-10-18T10:01:00+00:00",
            ),
            ("j2", "scan", STORE, "running", "2026-10-18T11:00:00+00:00", None),
        ],
    )
    connection.execute(
        "INSERT INTO job_events (job_id, seq, type, data, at)"
        " VALUES ('j2', 1, 'progress', ?, '2026-10-18T11:00:05+00:00')",
        ('{"current": 3, "total": 7}',),
    )
    connection.commit()
    connection.close()
    area = AreaRecord(
        id="raba",
        source="drawn",
        geometry=polygon((19.0, 49.5), (20.0, 49.5), (20.0, 50.0)),
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
        area_km2=1470.0,
        countries=("PL",),
    )

    # Act
    writer.write_area(area)
    state = queries.status().stores[0]
    kept = queries.area("raba")

    # Assert
    assert state.last_scan is not None and state.last_scan.id == "j1"
    assert state.running_job is not None
    assert (state.running_job.id, state.running_job.progress) == ("j2", (3, 7))
    assert kept == area
    assert queries.area("brak") is None


@pytest.mark.parametrize(
    "query",
    [
        MapQuery(bbox=(20.0, 49.0, 19.0, 50.0)),
        MapQuery(bbox=(19.0, 49.0, 20.0, 50.0), limit=0),
        MapQuery(bbox=(19.0, 49.0, 20.0, 50.0), grid_columns=0),
    ],
    ids=["reversed_view", "no_limit", "no_grid"],
)
def test_queries_map_rejects_invalid_views(index: Index, query: MapQuery) -> None:
    """A reversed view, a zero limit or grid are refused with a Polish message."""
    # Arrange
    _, queries = index

    # Act / Assert
    with pytest.raises(IndexQueryError):
        queries.footprints(query, visible=ALL_PROJECTS)


def test_queries_area_must_be_a_polygon(index: Index) -> None:
    """An area that is not a polygon in WGS84 is refused."""
    # Arrange
    _, queries = index
    line: dict[str, object] = {
        "type": "LineString",
        "coordinates": [[19.0, 49.0], [20.0, 50.0]],
    }

    # Act / Assert
    with pytest.raises(IndexQueryError, match="wielokątem"):
        queries.slots(SlotQuery(area=AreaFilter(line)), visible=ALL_PROJECTS)
