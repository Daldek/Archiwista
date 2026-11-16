"""The rows of an availability report: labels, variants and ranking (SPEC 6.4).

Every expected value is worked out by hand from the sheet records and the
areas of the report the test builds (SPEC 13 v0.3 criterion 3), so a test
never asks the code under test what to expect.
"""

from datetime import UTC, datetime

import pytest

from archiwista.services.availability import (
    NO_DATA,
    AvailabilityRow,
    AvailabilityVariant,
    VariantFilter,
    rows,
)
from archiwista.sources import (
    AvailabilityArea,
    AvailabilityCampaign,
    AvailabilityCombination,
    AvailabilityReport,
    AvailabilitySheet,
)

# The land of the "Kraków" area: 120 km².
LAND_M2 = 120_000_000.0


def _records(campaign: str | None, *sheets: str) -> tuple[AvailabilitySheet, ...]:
    """Return full records of one campaign's sheets."""
    return tuple(
        AvailabilitySheet(sheet, campaign, full_sheet=True) for sheet in sheets
    )


def _alone(campaign: str, full_m2: float, *, complete: bool) -> AvailabilityCampaign:
    """Return one campaign of a combination on its own."""
    return AvailabilityCampaign(campaign, complete=complete, full_m2=full_m2)


def _combination(
    year: int | None,
    horizontal: str,
    *,
    complete: bool,
    full_m2: float,
    records: tuple[AvailabilitySheet, ...],
    resolution: str | None = "1m",
    file_format: str = "ASC",
    campaigns: tuple[str, ...] | None = None,
    coverage: tuple[AvailabilityCampaign, ...] = (),
    sheets_partial: tuple[str, ...] = (),
    sheets_missing: tuple[str, ...] = (),
    size_bytes: int | None = None,
    country: str = "PL",
    vertical_crs: str = "EVRF2007",
) -> AvailabilityCombination:
    """Return a combination; its campaigns are those of its records by default."""
    named = sorted({record.campaign for record in records if record.campaign})
    return AvailabilityCombination(
        country=country,
        product="nmt",
        source="pl.gugik.nmt",
        year=year,
        horizontal=horizontal,
        resolution=resolution,
        vertical_crs=vertical_crs,
        format=file_format,
        campaigns=tuple(named) if campaigns is None else campaigns,
        complete=complete,
        sheets_full=tuple(record.sheet for record in records),
        sheets_partial=sheets_partial,
        sheets_missing=sheets_missing,
        uncovered_m2=0.0,
        full_m2=full_m2,
        size_bytes=size_bytes,
        sheet_records=records,
        campaign_coverage=coverage,
    )


def _report(
    *combinations: AvailabilityCombination,
    lands: tuple[tuple[str, float], ...] = (("PL", LAND_M2),),
) -> AvailabilityReport:
    """Return a report of the combinations over areas of the given land."""
    return AvailabilityReport(
        producer="kartograf",
        schema="kartograf-availability/1",
        checked_at=datetime(2026, 10, 25, 8, 0, tzinfo=UTC),
        request={"product": "nmt"},
        areas=tuple(
            AvailabilityArea(country, "EPSG:2180", (0.0, 0.0, 1.0, 1.0), land, land)
            for country, land in lands
        ),
        combinations=combinations,
    )


# Kraków, NMT 1 m, three years.
#
# 2023, PL-1992: campaigns A (S1, S2) and B (S3, S4); each alone covers half of
# the land, together all of it: "pełne · 2 kampanie".
PL1992_2023 = _combination(
    2023,
    "PL-1992",
    complete=True,
    full_m2=LAND_M2,
    records=_records("A", "S1", "S2") + _records("B", "S3", "S4"),
    coverage=(
        _alone("A", 60_000_000.0, complete=False),
        _alone("B", 60_000_000.0, complete=False),
    ),
)
# 2023, PL-2000: campaign C (T1 to T3) covers the land alone: "pełne". Its
# frames lie on another grid, so the land in them is the same up to the
# floating-point error of the measure; the two shares are equal, and the
# fewer campaigns put PL-2000 first.
PL2000_2023 = _combination(
    2023,
    "PL-2000",
    complete=True,
    full_m2=119_999_999.9999,
    records=_records("C", "T1", "T2", "T3"),
    coverage=(_alone("C", 119_999_999.9999, complete=True),),
)
# 2022, PL-1992: campaign D, S1 to S3 full and S4 partial; 69.6 km² of 120 km²
# lies in full sheets: 69.6 / 120 = 0.58, "częściowe · 58%" with one partial
# sheet (the floating-point quotient is 57.999…%).
PL1992_2022 = _combination(
    2022,
    "PL-1992",
    complete=False,
    full_m2=69_600_000.0,
    records=_records("D", "S1", "S2", "S3")
    + (AvailabilitySheet("S4", "D", full_sheet=False),),
    sheets_partial=("S4",),
    coverage=(_alone("D", 69_600_000.0, complete=False),),
)
# 2021, PL-1992 1 m, in ASCII-NMT (listed first) and ASC: the combination names
# campaigns E, F and G, but the newest record of each sheet is E's (S1, S2) or
# F's (S3, S4), so a download takes 2 campaigns: "pełne · 2 kampanie". One set,
# one variant; its size is that of ASC, the default format.
ASCII_2021 = _combination(
    2021,
    "PL-1992",
    complete=True,
    full_m2=LAND_M2,
    records=_records("E", "S1", "S2") + _records("F", "S3", "S4"),
    campaigns=("E", "F", "G"),
    coverage=(
        _alone("E", 60_000_000.0, complete=False),
        _alone("F", 60_000_000.0, complete=False),
        _alone("G", 10_000_000.0, complete=False),
    ),
    file_format="ASCII-NMT",
    size_bytes=150_000_000,
)
ASC_2021 = _combination(
    2021,
    "PL-1992",
    complete=True,
    full_m2=LAND_M2,
    records=_records("E", "S1", "S2") + _records("F", "S3", "S4"),
    campaigns=("G", "F", "E"),
    coverage=ASCII_2021.campaign_coverage,
    size_bytes=400_000_000,
)
# 2021, PL-2000: 119.64 km² of 120 km² in full sheets = 99.7%, rounded down
# 99, and a partial combination never shows 100.
PL2000_2021 = _combination(
    2021,
    "PL-2000",
    complete=False,
    full_m2=119_640_000.0,
    records=_records("J", "T1", "T2", "T3"),
)
# 2021, PL-1992 0.5 m: 0.6 km² of 120 km² = 0.5%: "częściowe · <1%".
HALF_METRE_2021 = _combination(
    2021,
    "PL-1992",
    resolution="0.5m",
    complete=False,
    full_m2=600_000.0,
    records=_records("K", "S1"),
)
KRAKOW = _report(
    PL1992_2023,
    PL2000_2023,
    PL1992_2022,
    ASCII_2021,
    ASC_2021,
    PL2000_2021,
    HALF_METRE_2021,
)


def _variant(variant: AvailabilityVariant) -> tuple[object, ...]:
    """Return what a person reads of a variant, label included."""
    combination = variant.combination
    label = variant.label
    return (
        combination.horizontal,
        combination.resolution,
        variant.formats,
        variant.default_format,
        variant.size_bytes,
        label.kind,
        label.campaigns,
        label.percent,
        label.below_one,
        label.partial_sheets,
    )


def _row(row: AvailabilityRow) -> tuple[object, ...]:
    """Return a row: its year, its variants best first and their count."""
    return (row.country, row.year, [_variant(item) for item in row.variants])


def test_rows_of_three_years_of_krakow_match_the_hand_computed_labels() -> None:
    """The rows of 2023, 2022 and 2021 are the labels worked out from the records."""
    found = rows(KRAKOW)

    assert [_row(row) for row in found] == [
        (
            "PL",
            2023,
            [
                ("PL-2000", "1m", ("ASC",), "ASC", None, "full", 1, 100, False, 0),
                (
                    "PL-1992",
                    "1m",
                    ("ASC",),
                    "ASC",
                    None,
                    "full_campaigns",
                    2,
                    100,
                    False,
                    0,
                ),
            ],
        ),
        (
            "PL",
            2022,
            [("PL-1992", "1m", ("ASC",), "ASC", None, "partial", 1, 58, False, 1)],
        ),
        (
            "PL",
            2021,
            [
                (
                    "PL-1992",
                    "1m",
                    ("ASCII-NMT", "ASC"),
                    "ASC",
                    400_000_000,
                    "full_campaigns",
                    2,
                    100,
                    False,
                    0,
                ),
                ("PL-2000", "1m", ("ASC",), "ASC", None, "partial", 1, 99, False, 0),
                ("PL-1992", "0.5m", ("ASC",), "ASC", None, "partial", 1, 0, True, 0),
            ],
        ),
    ]
    assert [row.other_variants for row in found] == [1, 0, 2]
    assert [row.label.kind for row in found] == ["full", "partial", "full_campaigns"]


def test_rows_with_a_fixed_dimension_show_a_year_without_it_as_no_data() -> None:
    """A fixed sheet system or resolution leaves the ranking only what has it."""
    by_system = rows(KRAKOW, fixed=VariantFilter(horizontal="PL-2000"))
    by_resolution = rows(KRAKOW, fixed=VariantFilter(resolution="0.5m"))

    assert [(row.year, row.label.kind, row.other_variants) for row in by_system] == [
        (2023, "full", 0),
        (2022, "no_data", 0),
        (2021, "partial", 0),
    ]
    assert by_system[1].variants == ()
    assert by_system[1].label == NO_DATA
    assert [(row.year, row.label.kind) for row in by_resolution] == [
        (2023, "no_data"),
        (2022, "no_data"),
        (2021, "partial"),
    ]
    assert by_resolution[2].label.below_one


# Pairs of variants of one year, the better one first: the criterion named
# decides, though each later criterion prefers the other one (SPEC 6.4).
# Complete with 99% of the land measured in full sheets, against partial with
# all of it but a sliver.
_COMPLETE_5M = _combination(
    2020,
    "PL-1992",
    resolution="5m",
    complete=True,
    full_m2=118_800_000.0,
    records=_records("A", "S1") + _records("B", "S2") + _records("C", "S3"),
)
_PARTIAL_100_HALF_METRE = _combination(
    2020,
    "PL-2000",
    resolution="0.5m",
    complete=False,
    full_m2=LAND_M2,
    records=_records("D", "T1"),
)
_PARTIAL_70_5M = _combination(
    2020,
    "PL-1992",
    resolution="5m",
    complete=False,
    full_m2=84_000_000.0,
    records=_records("A", "S1") + _records("B", "S2") + _records("C", "S3"),
)
_PARTIAL_60_HALF_METRE = _combination(
    2020,
    "PL-2000",
    resolution="0.5m",
    complete=False,
    full_m2=72_000_000.0,
    records=_records("D", "T1"),
)
_ONE_CAMPAIGN_5M = _combination(
    2020,
    "PL-1992",
    resolution="5m",
    complete=True,
    full_m2=LAND_M2,
    records=_records("A", "S1", "S2"),
)
_TWO_CAMPAIGNS_HALF_METRE = _combination(
    2020,
    "PL-2000",
    resolution="0.5m",
    complete=True,
    full_m2=LAND_M2,
    records=_records("B", "T1") + _records("C", "T2"),
)
_ONE_CAMPAIGN_HALF_METRE = _combination(
    2020,
    "PL-2000",
    resolution="0.5m",
    complete=True,
    full_m2=LAND_M2,
    records=_records("B", "T1", "T2"),
)


@pytest.mark.parametrize(
    ("better", "worse"),
    [
        pytest.param(_COMPLETE_5M, _PARTIAL_100_HALF_METRE, id="complete"),
        pytest.param(_PARTIAL_70_5M, _PARTIAL_60_HALF_METRE, id="full-share"),
        pytest.param(_ONE_CAMPAIGN_5M, _TWO_CAMPAIGNS_HALF_METRE, id="campaigns"),
        pytest.param(_ONE_CAMPAIGN_HALF_METRE, _ONE_CAMPAIGN_5M, id="resolution"),
    ],
)
@pytest.mark.parametrize("worse_first", [True, False])
def test_rows_rank_a_year_by_completeness_share_campaigns_then_resolution(
    better: AvailabilityCombination,
    worse: AvailabilityCombination,
    worse_first: bool,
) -> None:
    """The first criterion that differs decides, whatever the report's order."""
    listed = (worse, better) if worse_first else (better, worse)

    (row,) = rows(_report(*listed))

    assert [item.combination for item in row.variants] == [better, worse]
    assert row.other_variants == 1


def test_rows_rank_equal_variants_in_the_report_order() -> None:
    """Variants equal by every measure, resolution none, keep the report's order."""
    first = _combination(
        2020,
        "PL-1992",
        resolution=None,
        file_format="LAZ",
        complete=True,
        full_m2=LAND_M2,
        records=_records("A", "S1"),
        vertical_crs="EVRF2007",
    )
    second = _combination(
        2020,
        "PL-1992",
        resolution=None,
        file_format="LAZ",
        complete=True,
        full_m2=LAND_M2,
        records=_records("A", "S1"),
        vertical_crs="KRON86",
    )

    (row,) = rows(_report(first, second))
    (reversed_row,) = rows(_report(second, first))

    assert [item.combination for item in row.variants] == [first, second]
    assert [item.combination for item in reversed_row.variants] == [second, first]


@pytest.mark.parametrize(
    ("full_m2", "percent", "below_one"),
    [
        # 69.6 / 120 = 58% exactly; the floating-point quotient is 57.999…%.
        pytest.param(69_600_000.0, 58, False, id="58-percent"),
        # 119.64 / 120 = 99.7%, rounded down.
        pytest.param(119_640_000.0, 99, False, id="99.7-percent"),
        # All the land in full sheets, a sliver outside them: never 100.
        pytest.param(LAND_M2, 99, False, id="never-100"),
        # 0.6 / 120 = 0.5%: "<1%".
        pytest.param(600_000.0, 0, True, id="below-one"),
        # Nothing in full sheets: 0%, not "<1%".
        pytest.param(0.0, 0, False, id="zero"),
    ],
)
def test_rows_partial_percent_rounds_down_below_100(
    full_m2: float, percent: int, below_one: bool
) -> None:
    """A partial label's percent is the full share rounded down, at most 99."""
    partial = _combination(
        2020,
        "PL-1992",
        complete=False,
        full_m2=full_m2,
        records=_records("A", "S1"),
        sheets_partial=("S2",),
    )

    (row,) = rows(_report(partial))

    assert (row.label.kind, row.label.percent, row.label.below_one) == (
        "partial",
        percent,
        below_one,
    )
    assert row.label.partial_sheets == 1


def test_rows_partial_percent_is_unknown_without_land() -> None:
    """An area without land gives no share rather than a division by zero."""
    partial = _combination(
        2020, "PL-1992", complete=False, full_m2=0.0, records=_records("A", "S1")
    )

    (row,) = rows(_report(partial, lands=(("PL", 0.0),)))

    assert (row.label.share, row.label.percent, row.label.below_one) == (
        None,
        None,
        False,
    )


@pytest.mark.parametrize(
    ("records", "coverage", "kind", "campaigns"),
    [
        # Records of A and B, and neither covers the land alone.
        pytest.param(
            _records("A", "S1") + _records("B", "S2"),
            (
                _alone("A", 60_000_000.0, complete=False),
                _alone("B", 60_000_000.0, complete=False),
            ),
            "full_campaigns",
            2,
            id="two-together",
        ),
        # Records of A and B, but A covers the land alone.
        pytest.param(
            _records("A", "S1") + _records("B", "S2"),
            (
                _alone("A", LAND_M2, complete=True),
                _alone("B", 60_000_000.0, complete=False),
            ),
            "full",
            2,
            id="one-alone",
        ),
        # Records of A and records without a campaign: one campaign.
        pytest.param(
            _records("A", "S1") + _records(None, "S2"),
            (_alone("A", 60_000_000.0, complete=False),),
            "full",
            1,
            id="unnamed-records",
        ),
    ],
)
def test_rows_complete_label_counts_the_campaigns_of_the_records(
    records: tuple[AvailabilitySheet, ...],
    coverage: tuple[AvailabilityCampaign, ...],
    kind: str,
    campaigns: int,
) -> None:
    """A complete label is full from one campaign alone, N from the records."""
    complete = _combination(
        2020,
        "PL-1992",
        complete=True,
        full_m2=LAND_M2,
        records=records,
        campaigns=("A", "B", "Z"),
        coverage=coverage,
    )

    (row,) = rows(_report(complete))

    assert (row.label.kind, row.label.campaigns) == (kind, campaigns)


def test_rows_group_the_formats_of_one_set_and_keep_other_campaigns_apart() -> None:
    """Formats of one set are one variant; another campaign is another variant."""
    archives = [
        _combination(
            2019,
            "PL-1992",
            resolution="5m",
            complete=True,
            full_m2=LAND_M2,
            records=_records("A", "S1"),
            file_format=name,
            size_bytes=size,
        )
        for name, size in (("ASCII-NMT", 10_000), ("XYZ", 20_000))
    ]
    other_campaign = _combination(
        2019,
        "PL-1992",
        resolution="5m",
        complete=True,
        full_m2=LAND_M2,
        records=_records("B", "S1"),
        file_format="ASCII-NMT",
    )

    (row,) = rows(_report(*archives, other_campaign))

    assert [(item.formats, item.default_format) for item in row.variants] == [
        (("ASCII-NMT", "XYZ"), None),
        (("ASCII-NMT",), None),
    ]
    # No default format: the plan asks for a choice, and no size is given.
    assert row.variants[0].size_bytes is None
    assert row.other_variants == 1


def test_rows_of_a_border_area_measure_each_country_on_its_own_land() -> None:
    """A CZ part without years is its own row, measured on the CZ land."""
    poland = _combination(
        2023, "PL-1992", complete=True, full_m2=LAND_M2, records=_records("A", "S1")
    )
    # 30 km² of 40 km² of CZ land in sheets with a file: 75%, 2 sheets without one.
    czechia = _combination(
        None,
        "S-JTSK",
        country="CZ",
        resolution="2m",
        vertical_crs="Bpv",
        file_format="TIFF",
        complete=False,
        full_m2=30_000_000.0,
        records=(),
        sheets_missing=("CZ-1", "CZ-2"),
        size_bytes=5_000_000,
    )

    found = rows(
        _report(poland, czechia, lands=(("PL", LAND_M2), ("CZ", 40_000_000.0)))
    )

    assert [(row.country, row.year, row.label.kind) for row in found] == [
        ("PL", 2023, "full"),
        ("CZ", None, "partial"),
    ]
    label = found[1].label
    assert (label.percent, label.missing_sheets, label.campaigns) == (75, 2, 0)
    assert (found[1].variants[0].default_format, found[1].variants[0].size_bytes) == (
        "TIFF",
        5_000_000,
    )
