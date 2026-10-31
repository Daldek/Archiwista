"""The store badge of an availability row over a store Kartograf wrote (SPEC 6.4).

A report names the campaigns of a combination by their survey work numbers
(``nr_zglosz``: Kartograf's ``AvailabilityCombination.campaigns``), and a
version's sidecar keeps that number (``survey_work_id``) beside the campaign's
own id, the number its file name starts with. The store of
``kartograf.testing`` holds the sheet ``PL_SHEET`` from three campaigns:
83233 of 2022 (survey work ``P.83233``), 84020 and 84500 of 2025 (``P.84020``
and ``P.84500``). The expected badges follow from those versions.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from kartograf.testing import PL_SHEET, build_fixture_store

from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexQueries, IndexWriter, initialize, scan_store
from archiwista.services.availability import summary
from archiwista.sources import (
    AvailabilityArea,
    AvailabilityCombination,
    AvailabilityReport,
    AvailabilitySheet,
)
from archiwista.sources.registry import load_registry

STORE = "zespol"
DATASET = "pl.gugik.nmt_1m"
LAND_M2 = 5_000_000.0


@pytest.fixture(scope="module")
def queries(tmp_path_factory: pytest.TempPathFactory) -> Iterator[IndexQueries]:
    """Return the index of the producer's fixture store after a full scan."""
    base = tmp_path_factory.mktemp("badge")
    built = build_fixture_store(base / "kartograf")
    config = StoreConfig(id=STORE, name="Zespół", kartograf=built.root, kind="local")
    path = base / "index.sqlite"
    initialize(path)
    with IndexWriter(path) as writer:
        writer.sync_stores({STORE: config.roots()})
        adapter = load_registry(cache_dir=base / "cache").adapter("kartograf")
        scan_store(adapter, writer, AppSettings(stores=(config,)), STORE, mode="full")
    with IndexQueries(path) as found:
        yield found


def _report(year: int, work: str) -> AvailabilityReport:
    """Return a report of one full sheet ``PL_SHEET`` of ``year`` and ``work``."""
    combination = AvailabilityCombination(
        country="PL",
        product="nmt",
        source=DATASET,
        year=year,
        horizontal="PL-1992",
        resolution="1m",
        vertical_crs="EVRF2007",
        format="ASC",
        campaigns=(work,),
        complete=True,
        sheets_full=(PL_SHEET,),
        sheets_partial=(),
        sheets_missing=(),
        uncovered_m2=0.0,
        full_m2=LAND_M2,
        sheet_records=(AvailabilitySheet(PL_SHEET, work, full_sheet=True),),
    )
    return AvailabilityReport(
        producer="kartograf",
        schema="kartograf-availability/1",
        checked_at=datetime(2026, 10, 31, 8, 0, tzinfo=UTC),
        request={"product": "nmt"},
        areas=(
            AvailabilityArea("PL", "EPSG:2180", (0.0, 0.0, 1.0, 1.0), LAND_M2, LAND_M2),
        ),
        combinations=(combination,),
    )


@pytest.mark.parametrize(
    ("year", "work", "state"),
    [
        (2022, "P.83233", "all"),
        (2025, "P.84500", "all"),
        (2022, "P.84020", "none"),
        (2022, "83233", "none"),
    ],
    ids=["2022-held", "2025-held", "survey-work-of-another-year", "campaign-id"],
)
def test_summary_badge_matches_the_survey_work_of_a_kartograf_sidecar(
    queries: IndexQueries, year: int, work: str, state: str
) -> None:
    """A report's survey work finds the versions of that work, not a campaign id.

    ``83233`` is the campaign id of the 2022 version: a report names survey
    works only, so an id that equals it names no version of the store.
    """
    (row,) = summary(queries, _report(year, work), store=STORE)

    assert row.local is not None
    assert (row.local.units, row.local.of, row.local.state) == (
        1 if state == "all" else 0,
        1,
        state,
    )
