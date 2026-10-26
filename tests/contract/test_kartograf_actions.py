"""Kartograf's commands through the adapter's action capability (plan 2026-10-25, A1).

The catalog, the reading of a line, the check of a call and the line of a call
run against the installed Kartograf, as every test does, under the canary of
the producers' default roots (``tests/conftest.py``). Kartograf's
``kartograf-commands/1`` gives the commands and their example lines. The
availability at the source (A2) is Kartograf's ``check_availability`` with
Archiwista's own metadata cache; its network part is stood in for, its
refusals before the network are Kartograf's own.
"""

from datetime import UTC, datetime
from pathlib import Path

import kartograf
import pytest

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.adapter.kartograf import load
from archiwista.errors import ProducerError
from archiwista.sources import (
    ActionAdapter,
    AvailabilityArea,
    AvailabilityCampaign,
    AvailabilityCombination,
    AvailabilityFailure,
    AvailabilityNotice,
    AvailabilityReport,
    AvailabilitySheet,
    GeoJSONGeometry,
    SourceContext,
)
from tests.fixtures.network import no_network

# A complete call of a store command (the example of ``elevation download``).
NMT = {
    "product": "nmt",
    "sheet": "N-34-130-D-d-2-4",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
}
CHECKED_AT = "2026-10-20T08:15:02+00:00"


def _box(west: float, south: float, east: float, north: float) -> GeoJSONGeometry:
    """Return a WGS84 rectangle as an area keeps it."""
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Polygon", "coordinates": [ring]}


def _kartograf_report() -> kartograf.AvailabilityReport:
    """Return a report of Kartograf's own classes: one combination of 2023."""
    combination = kartograf.AvailabilityCombination(
        country="PL",
        product="nmt",
        source="nmt_pl",
        year=2023,
        acquisition_dates=("2023-04-01", "2023-05-02"),
        published=("2023-06-01", "2023-07-01"),
        campaigns=("DFT.1.2023", "DFT.2.2023"),
        horizontal="PL-1992",
        resolution="1m",
        vertical_crs="EVRF2007",
        format="ASC",
        densities=(),
        complete=True,
        sheets_full=("N-34-139-A-b-1-1", "N-34-139-A-b-1-2"),
        sheets_partial=(),
        sheets_missing=(),
        uncovered=False,
        uncovered_m2=0.0,
        size_bytes=None,
        download_hint=("elevation download --product nmt",),
        full_m2=118_000_000.0,
        sheet_records=(
            kartograf.AvailabilityRecord(
                sheet="N-34-139-A-b-1-1",
                campaign="DFT.1.2023",
                acquisition_date="2023-04-01",
                published="2023-06-01",
                full_sheet=True,
                url="https://example.invalid/1.asc",
            ),
        ),
        campaign_coverage=(
            kartograf.AvailabilityCampaign("DFT.1.2023", False, 59_000_000.0),
        ),
    )
    return kartograf.AvailabilityReport(
        request={"product": "nmt", "country": "pl"},
        checked_at=CHECKED_AT,
        areas=(
            kartograf.AvailabilityArea(
                "PL", "EPSG:2180", (1.0, 2.0, 3.0, 4.0), 120e6, 118e6
            ),
        ),
        combinations=(combination,),
        failed=(kartograf.UnitFailure("CZ", "CZ", "CUZK did not answer", "country"),),
        notices=(kartograf.Notice("info", "index_unsupported", "2 records skipped"),),
        ok=False,
    )


@pytest.fixture
def adapter(tmp_path: Path) -> ActionAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, ActionAdapter)
    return created


def test_catalog_holds_every_command_of_kartograf_in_its_order(
    adapter: ActionAdapter,
) -> None:
    """The ids are those of ``kartograf commands list``, in its order."""
    listed = [row.name for row in kartograf.list_commands().commands]

    commands = adapter.commands()

    assert [info.command for info in commands] == listed
    assert {info.producer for info in commands} == {"kartograf"}


def test_options_of_a_call_leave_the_store_and_the_flags_of_a_run_out(
    adapter: ActionAdapter,
) -> None:
    """A download takes its store by name; its run flags are no options of a call."""
    commands = {info.command: info for info in adapter.commands()}

    download = commands["elevation download"]
    parse = commands["sheet parse"]

    names = {option.name for option in download.options}
    assert {"product", "sheet", "year", "geometry"} <= names
    assert not names & {"root", "output_dir", "check", "update", "plan", "workers"}
    assert (download.store, download.check, download.writes) == (True, True, "add")
    assert (parse.store, parse.check, parse.read_only) == (False, False, True)
    geometry = next(option for option in download.options if option.name == "geometry")
    assert (geometry.path_role, geometry.group) == ("input", "area")


def test_every_example_line_reads_back_into_its_call_without_the_network(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """``parse`` reads the line ``format`` writes into the same call; nothing connects.

    Kartograf writes the canonical line of a call. The examples are complete
    calls, so each also passes ``validate`` (with a store root for a store
    command).
    """
    root = tmp_path / "store"

    with no_network() as attempts:
        catalog = adapter.commands()
        calls = [adapter.parse(line) for info in catalog for line in info.examples]
        read_back = [adapter.parse(adapter.format(call)) for call in calls]
        stores = {info.command: info.store for info in catalog}
        for call in calls:
            adapter.validate(
                call.command, call.options, root=root if stores[call.command] else None
            )

    assert read_back == calls
    assert {call.command for call in calls} == set(stores)
    assert attempts == []


def test_an_invalid_year_is_refused_with_its_option_and_kartograf_text(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """Kartograf's text is kept, its option becomes ``details.option``."""
    options = {**NMT, "year": 1800}
    with pytest.raises(kartograf.ValidationError) as own:
        kartograf.validate_command("elevation download", options, root=tmp_path)

    with pytest.raises(ProducerError) as refused:
        adapter.validate("elevation download", options, root=tmp_path)

    error = refused.value
    assert (error.code, error.http_status) == ("validation_error", 400)
    assert error.message == own.value.localized("en")
    assert error.details["option"] == "year"
    assert error.details["reason"] == "kartograf_error"
    assert error.details["kartograf"]["reason"] == "invalid_input"


def test_validate_names_the_store_root_of_a_store_command_only(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartograf gets ``root=`` for a download, none for a command without a store.

    A download without its root never reaches Kartograf, whose default root
    would stand in (Decision 1 of the plan).
    """
    received: list[tuple[str, dict[str, object]]] = []

    def recording(command: str, options: object, **kwargs: object) -> None:
        received.append((command, kwargs))
        kartograf.validate_command(command, options, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(actions_module, "validate_command", recording)
    root = tmp_path / "store"

    adapter.validate("elevation download", NMT, root=root)
    adapter.validate("sheet parse", {"sheet": "N-34-130-D-d-2-4"}, root=root)
    with pytest.raises(ValueError, match="works on a store"):
        adapter.validate("elevation download", NMT, root=None)

    assert received == [("elevation download", {"root": root}), ("sheet parse", {})]


def test_availability_asks_kartograf_with_archiwistas_cache_and_the_area_box(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is ``metadata.db`` of the adapter's cache, never ``cache=True``.

    The box is the envelope of the area's polygon in EPSG:2180 with its edges
    densified: a box across 19°E reaches its lowest northing on the central
    meridian, between the corners (Kartograf's own ``bbox_to_2180`` lost that
    strip from the corners alone). The report and its notices come back in
    Archiwista's types.
    """
    received: list[dict[str, object]] = []

    def recording(**kwargs: object) -> kartograf.AvailabilityReport:
        received.append(kwargs)
        on_notice = kwargs["on_notice"]
        assert callable(on_notice)
        on_notice(kartograf.Notice("info", "index_unsupported", "2 records skipped"))
        return _kartograf_report()

    monkeypatch.setattr(actions_module, "check_availability", recording)
    said: list[AvailabilityNotice] = []
    to_2180 = kartograf.pinned_transform("EPSG:4326", "EPSG:2180")
    west, south = to_2180.transform(18.5, 50.0)
    middle, low = to_2180.transform(19.0, 50.0)
    east, _ = to_2180.transform(19.5, 50.0)
    _, north = to_2180.transform(19.5, 50.2)

    with no_network() as attempts:
        report = adapter.availability(
            "nmt",
            area=_box(18.5, 50.0, 19.5, 50.2),
            countries=("PL",),
            force=True,
            on_notice=said.append,
        )

    (call,) = received
    cache = call.pop("cache")
    bbox = call.pop("bbox")
    assert isinstance(cache, kartograf.MetadataCache)
    assert cache.db_path == tmp_path / "cache" / "kartograf" / "metadata.db"
    assert isinstance(bbox, kartograf.BBox)
    assert bbox.crs == "EPSG:2180"
    assert tuple(bbox[:4]) == pytest.approx((west, low, east, north), abs=0.01)
    assert south - low > 100
    assert middle == pytest.approx(500_000.0)
    assert call == {
        "product": "nmt",
        "country": "pl",
        "force": True,
        "on_notice": call["on_notice"],
    }
    assert said == [
        AvailabilityNotice("info", "index_unsupported", "2 records skipped")
    ]
    assert report == AvailabilityReport(
        producer="kartograf",
        schema="kartograf-availability/1",
        checked_at=datetime(2026, 10, 20, 8, 15, 2, tzinfo=UTC),
        request={"product": "nmt", "country": "pl"},
        areas=(
            AvailabilityArea("PL", "EPSG:2180", (1.0, 2.0, 3.0, 4.0), 120e6, 118e6),
        ),
        combinations=(
            AvailabilityCombination(
                country="PL",
                product="nmt",
                source="nmt_pl",
                year=2023,
                horizontal="PL-1992",
                resolution="1m",
                vertical_crs="EVRF2007",
                format="ASC",
                campaigns=("DFT.1.2023", "DFT.2.2023"),
                complete=True,
                sheets_full=("N-34-139-A-b-1-1", "N-34-139-A-b-1-2"),
                sheets_partial=(),
                sheets_missing=(),
                uncovered_m2=0.0,
                full_m2=118_000_000.0,
                size_bytes=None,
                published=("2023-06-01", "2023-07-01"),
                sheet_records=(
                    AvailabilitySheet(
                        "N-34-139-A-b-1-1",
                        "DFT.1.2023",
                        True,
                        "2023-04-01",
                        "2023-06-01",
                    ),
                ),
                campaign_coverage=(
                    AvailabilityCampaign("DFT.1.2023", False, 59_000_000.0),
                ),
                commands=("elevation download --product nmt",),
            ),
        ),
        failed=(AvailabilityFailure("CZ", "CUZK did not answer", "country"),),
        notices=(AvailabilityNotice("info", "index_unsupported", "2 records skipped"),),
        ok=False,
    )
    assert AvailabilityReport.from_json(report.to_json()) == report
    assert attempts == []


@pytest.mark.parametrize(
    ("countries", "country", "crs"),
    [
        (("CZ", "PL"), "auto", "EPSG:2180"),
        (("CZ",), "cz", "EPSG:5514"),
    ],
)
def test_an_area_of_two_countries_is_auto_in_the_crs_of_its_first(
    adapter: ActionAdapter,
    monkeypatch: pytest.MonkeyPatch,
    countries: tuple[str, ...],
    country: str,
    crs: str,
) -> None:
    """PL comes first, as Kartograf reports its parts; CZ alone is in S-JTSK."""
    received: list[dict[str, object]] = []

    def recording(**kwargs: object) -> kartograf.AvailabilityReport:
        received.append(kwargs)
        return _kartograf_report()

    monkeypatch.setattr(actions_module, "check_availability", recording)

    adapter.availability("laz", area=_box(18.0, 49.6, 18.6, 49.9), countries=countries)

    (call,) = received
    bbox = call["bbox"]
    assert isinstance(bbox, kartograf.BBox)
    assert (call["country"], bbox.crs, call["force"]) == (country, crs, False)


@pytest.mark.parametrize(
    ("product", "area", "countries", "option"),
    [
        ("bdot10k", _box(19.9, 50.0, 20.0, 50.05), ("PL",), "product"),
        ("nmt", _box(10.0, 50.0, 10.1, 50.05), (), "bbox"),
    ],
)
def test_kartograf_refuses_a_product_or_an_area_before_the_network(
    adapter: ActionAdapter,
    product: str,
    area: GeoJSONGeometry,
    countries: tuple[str, ...],
    option: str,
) -> None:
    """An unknown product and an area in neither country are Kartograf's refusals."""
    with no_network() as attempts, pytest.raises(ProducerError) as refused:
        adapter.availability(product, area=area, countries=countries)

    error = refused.value
    assert (error.code, error.details["option"]) == ("validation_error", option)
    assert error.details["reason"] == "kartograf_error"
    assert attempts == []


def test_availability_products_are_the_elevation_products(
    adapter: ActionAdapter,
) -> None:
    """Kartograf reports the availability of NMT, NMPT and LAZ (SPEC 6.3)."""
    assert adapter.availability_products() == ("nmt", "nmpt", "laz")
