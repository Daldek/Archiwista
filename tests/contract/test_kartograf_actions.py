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
from typing import cast

import kartograf
import pyogrio.raw
import pytest
import shapely

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.adapter.kartograf import load
from archiwista.areas import area_from_geometry, write_area_package
from archiwista.errors import ProducerError
from archiwista.index.coverage import PlanarMover
from archiwista.sources import (
    ActionAdapter,
    AvailabilityArea,
    AvailabilityCampaign,
    AvailabilityCombination,
    AvailabilityFailure,
    AvailabilityNotice,
    AvailabilityReport,
    AvailabilitySheet,
    GeoAdapter,
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


def test_availability_asks_kartograf_with_archiwistas_cache_and_the_area_file(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is ``metadata.db`` of the adapter's cache, never ``cache=True``.

    The area goes as its GeoPackage (``geometry``) with its country, never as
    a box (ADR-035 erratum 2). The report and its notices come back in
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
    area_file = tmp_path / "areas" / "0123456789abcdef.gpkg"

    with no_network() as attempts:
        report = adapter.availability(
            "nmt",
            area_file=area_file,
            countries=("PL",),
            force=True,
            on_notice=said.append,
        )

    (call,) = received
    cache = call.pop("cache")
    assert isinstance(cache, kartograf.MetadataCache)
    assert cache.db_path == tmp_path / "cache" / "kartograf" / "metadata.db"
    assert call == {
        "product": "nmt",
        "country": "pl",
        "geometry": area_file,
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
    ("countries", "country"),
    [(("CZ", "PL"), "auto"), (("CZ",), "cz"), (("PL",), "pl"), ((), "auto")],
)
def test_an_area_of_two_countries_is_auto(
    adapter: ActionAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    countries: tuple[str, ...],
    country: str,
) -> None:
    """One country is named; both, or neither for Kartograf to refuse, are ``auto``."""
    received: list[dict[str, object]] = []

    def recording(**kwargs: object) -> kartograf.AvailabilityReport:
        received.append(kwargs)
        return _kartograf_report()

    monkeypatch.setattr(actions_module, "check_availability", recording)
    area_file = tmp_path / "0123456789abcdef.gpkg"

    adapter.availability("laz", area_file=area_file, countries=countries)

    (call,) = received
    assert (call["country"], call["geometry"], call["force"]) == (
        country,
        area_file,
        False,
    )


def test_an_area_reaches_kartograf_as_its_polygon_not_its_box(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartograf reads the area itself, so its runs select by the polygon.

    An area of two small squares at the corners of a diagonal: its GeoPackage
    holds each part as it is in EPSG:2180, and Kartograf's own offline sheet
    selection of that file picks the sheets of the parts only, never those of
    the envelope between them, the box Archiwista sent before ADR-035
    erratum 2.
    """
    received: list[dict[str, object]] = []

    def recording(**kwargs: object) -> kartograf.AvailabilityReport:
        received.append(kwargs)
        return _kartograf_report()

    monkeypatch.setattr(actions_module, "check_availability", recording)
    geo = cast(GeoAdapter, adapter)
    parts = [_box(19.90, 50.00, 19.91, 50.01), _box(20.00, 50.07, 20.01, 50.08)]
    area = area_from_geometry(
        {
            "type": "MultiPolygon",
            "coordinates": [part["coordinates"] for part in parts],
        },
        adapter=geo,
        source="drawn",
    )
    written = write_area_package(tmp_path / "areas", area, transformer=geo.transformer)

    adapter.availability("nmt", area_file=written, countries=area.countries)

    (call,) = received
    area_file = call["geometry"]
    assert isinstance(area_file, Path)
    meta, _, read, _ = pyogrio.raw.read(area_file)
    mover = PlanarMover("EPSG:2180", geo.transformer)
    planar = [mover.move(part, "EPSG:4326") for part in parts]
    assert (call["country"], meta["crs"]) == ("pl", "EPSG:2180")
    assert [
        shapely.equals_exact(
            shapely.normalize(shapely.from_wkb(found)),
            shapely.normalize(part),
            tolerance=1e-6,
        )
        for found, part in zip(read, planar, strict=True)
    ] == [True, True]
    by_file = kartograf.find_sheets_for_geometry(
        area_file, "1:10000", sheet_system="1992"
    )
    by_parts = {
        sheet
        for part in planar
        for sheet in kartograf.find_sheets_for_bbox(
            kartograf.BBox(
                part.bounds[0],
                part.bounds[1],
                part.bounds[2],
                part.bounds[3],
                "EPSG:2180",
            ),
            "1:10000",
            sheet_system="1992",
        )
    }
    min_x, min_y, max_x, max_y = shapely.union_all(planar).bounds
    by_box = kartograf.find_sheets_for_bbox(
        kartograf.BBox(min_x, min_y, max_x, max_y, "EPSG:2180"),
        "1:10000",
        sheet_system="1992",
    )
    assert set(by_file) == by_parts
    assert len(by_file) < len(by_box)


@pytest.mark.parametrize(
    ("product", "area", "countries", "option"),
    [
        ("bdot10k", _box(19.9, 50.0, 20.0, 50.05), ("PL",), "product"),
        ("nmt", _box(10.0, 50.0, 10.1, 50.05), (), "geometry"),
    ],
)
def test_kartograf_refuses_a_product_or_an_area_before_the_network(
    adapter: ActionAdapter,
    tmp_path: Path,
    product: str,
    area: GeoJSONGeometry,
    countries: tuple[str, ...],
    option: str,
) -> None:
    """An unknown product and an area in neither country are Kartograf's refusals."""
    geo = cast(GeoAdapter, adapter)
    record = area_from_geometry(area, adapter=geo, source="drawn")
    area_file = write_area_package(
        tmp_path / "areas", record, transformer=geo.transformer
    )

    with no_network() as attempts, pytest.raises(ProducerError) as refused:
        adapter.availability(product, area_file=area_file, countries=countries)

    error = refused.value
    assert (error.code, error.details["option"]) == ("validation_error", option)
    assert error.details["reason"] == "kartograf_error"
    assert attempts == []


def test_availability_products_are_the_elevation_products(
    adapter: ActionAdapter,
) -> None:
    """Kartograf reports the availability of NMT, NMPT and LAZ (SPEC 6.3)."""
    assert adapter.availability_products() == ("nmt", "nmpt", "laz")
