"""The store badge of an availability row from the index (SPEC 6.4).

The badge counts the units of a variant's shown combination, its full and
partial sheets, of which the store holds a present version of the same
dataset (so format), year and campaign: a report names a campaign by its
survey work, which a version keeps as ``survey_work_id``. The expected
counts are worked out from the versions each test writes.
"""

from datetime import UTC, datetime

from archiwista.index import IndexQueries, IndexWriter
from archiwista.services.availability import summary
from archiwista.sources import (
    AvailabilityArea,
    AvailabilityCombination,
    AvailabilityReport,
    AvailabilitySheet,
    SourceEntry,
)
from tests.fixtures.index_data import NMT, STORE, slot_path, version, write_pass

DATASET = "pl.gugik.nmt_1m"
LAND_M2 = 120_000_000.0


def _report(*combinations: AvailabilityCombination) -> AvailabilityReport:
    """Return a report of the combinations over 120 km² of land in PL."""
    return AvailabilityReport(
        producer="kartograf",
        schema="kartograf-availability/1",
        checked_at=datetime(2026, 10, 25, 8, 0, tzinfo=UTC),
        request={"product": "nmt"},
        areas=(
            AvailabilityArea("PL", "EPSG:2180", (0.0, 0.0, 1.0, 1.0), LAND_M2, LAND_M2),
        ),
        combinations=combinations,
    )


def _combination(
    year: int, campaign: str, *, file_format: str = "ASC", source: str = DATASET
) -> AvailabilityCombination:
    """Return 2022's partial combination: S1 to S3 full, S4 partial."""
    return AvailabilityCombination(
        country="PL",
        product="nmt",
        source=source,
        year=year,
        horizontal="PL-1992",
        resolution="1m",
        vertical_crs="EVRF2007",
        format=file_format,
        campaigns=(campaign,),
        complete=False,
        sheets_full=("S1", "S2", "S3"),
        sheets_partial=("S4",),
        sheets_missing=(),
        uncovered_m2=0.0,
        full_m2=69_600_000.0,
        sheet_records=tuple(
            AvailabilitySheet(sheet, campaign, full_sheet=sheet != "S4")
            for sheet in ("S1", "S2", "S3", "S4")
        ),
    )


def _version(
    unit: str,
    seed: int,
    *,
    year: int = 2022,
    work: str = "D",
    dataset: str = DATASET,
) -> SourceEntry:
    """Return a version of a sheet of the NMT segment with its year and survey work.

    Its campaign id is the producer's own number, which no report names.
    """
    return version(
        slot_path(NMT, unit),
        f"{year}-05-01_{seed}",
        seed,
        dataset=dataset,
        campaign=str(seed),
        survey_work_id=work,
        data_year=year,
    )


def test_summary_counts_the_units_with_a_version_of_the_set(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Only S1 holds a version of 2022, survey work D, in the dataset of ASC.

    S2 holds one of 2021, S3 one of another survey work, S4 one of the dataset
    of another format, and S2's 2022 version went missing: 1 of 4 units.
    """
    writer, queries = index
    gone = _version("S2", 5)
    write_pass(
        writer,
        [
            _version("S1", 1),
            _version("S2", 2, year=2021),
            _version("S3", 3, work="X"),
            _version("S4", 4, dataset="pl.gugik.nmt_ascii_nmt_1m"),
            gone,
        ],
        full=True,
    )
    write_pass(
        writer,
        [
            _version("S1", 1),
            _version("S2", 2, year=2021),
            _version("S3", 3, work="X"),
            _version("S4", 4, dataset="pl.gugik.nmt_ascii_nmt_1m"),
        ],
        full=True,
    )

    (row,) = summary(queries, _report(_combination(2022, "D")), store=STORE)

    assert row.local is not None
    assert (row.local.store, row.local.units, row.local.of, row.local.state) == (
        STORE,
        1,
        4,
        "some",
    )


def test_summary_badge_is_all_or_none_and_absent_without_a_store(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Every unit held is "all"; another year's set has "none"; no store, no badge."""
    writer, queries = index
    write_pass(
        writer,
        [_version(unit, seed) for seed, unit in enumerate(("S1", "S2", "S3", "S4"))],
        full=True,
    )
    report = _report(_combination(2022, "D"), _combination(2021, "E"))

    held, other = summary(queries, report, store=STORE)
    unasked = summary(queries, report)

    assert held.local is not None and other.local is not None
    assert (held.local.units, held.local.of, held.local.state) == (4, 4, "all")
    assert (other.local.units, other.local.of, other.local.state) == (0, 4, "none")
    assert [row.local for row in unasked] == [None, None]
