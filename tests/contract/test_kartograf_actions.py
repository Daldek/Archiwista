"""Kartograf's commands through the adapter's action capability (plan 2026-10-25, A1).

The catalog, the reading of a line, the check of a call and the line of a call
run against the installed Kartograf, as every test does, under the canary of
the producers' default roots (``tests/conftest.py``). Kartograf's
``kartograf-commands/1`` gives the commands and their example lines. The
availability at the source (A2) is Kartograf's ``check_availability`` with
Archiwista's own metadata cache; its network part is stood in for, its
refusals before the network are Kartograf's own. A call given an area of
Archiwista (``AreaCommandAdapter``, A-ADR-049 erratum 5) is checked by
Kartograf's own ``validate_command``.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import kartograf
import pytest
import shapely
from shapely.geometry import shape

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.adapter.kartograf import load
from archiwista.areas import area_from_geometry, write_area_geojson
from archiwista.errors import ProducerError, UnsupportedError
from archiwista.sources import (
    ActionAdapter,
    AreaCommandAdapter,
    AvailabilityArea,
    AvailabilityCampaign,
    AvailabilityCombination,
    AvailabilityFailure,
    AvailabilityNotice,
    AvailabilityReport,
    AvailabilitySheet,
    CommandCall,
    CommandInfo,
    CommandOption,
    GeoAdapter,
    GeoJSONGeometry,
    OptionType,
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

    The area goes as its GeoJSON (``geometry``) with its country, never as a
    box (ADR-035 erratum 2). The report and its notices come back in
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
    area_file = tmp_path / "areas" / "0123456789abcdef.geojson"

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
    area_file = tmp_path / "0123456789abcdef.geojson"

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

    An area of two small squares at the corners of a diagonal: its GeoJSON
    holds the parts as they are in WGS84 (RFC 7946), and Kartograf's own
    offline sheet selection of that file picks the sheets of the parts only,
    never those of the envelope between them, the box Archiwista sent before
    ADR-035 erratum 2.
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
    written = write_area_geojson(tmp_path / "areas", area)

    adapter.availability("nmt", area_file=written, countries=area.countries)

    (call,) = received
    area_file = call["geometry"]
    assert isinstance(area_file, Path)
    collection = json.loads(area_file.read_text(encoding="utf-8"))
    (feature,) = collection["features"]
    assert (call["country"], collection["type"], "crs" in collection) == (
        "pl",
        "FeatureCollection",
        False,
    )
    union = shapely.union_all([shape(part) for part in parts])
    assert shapely.equals(shape(feature["geometry"]), union)

    def box(bounds: tuple[float, float, float, float]) -> kartograf.BBox:
        return kartograf.BBox(bounds[0], bounds[1], bounds[2], bounds[3], "EPSG:4326")

    by_file = kartograf.find_sheets_for_geometry(
        area_file, "1:10000", sheet_system="1992"
    )
    by_parts = {
        sheet
        for part in parts
        for sheet in kartograf.find_sheets_for_bbox(
            box(shape(part).bounds),
            "1:10000",
            sheet_system="1992",
        )
    }
    by_box = kartograf.find_sheets_for_bbox(
        box(union.bounds),
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
    area_file = write_area_geojson(tmp_path / "areas", record)

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


# A WGS84 area in Poland alone (Kraków), as the index keeps it.
KRAKOW = _box(19.9, 50.0, 20.0, 50.05)


@pytest.mark.parametrize(
    ("line", "replaced", "added"),
    [
        (
            "imagery download --product orto --sheet N-34-130-D-d-2-4"
            " --sheet-system 1992",
            ("sheet",),
            {"country": "pl"},
        ),
        ("landcover download --product bdot10k --teryt 1465", ("teryt",), {}),
        (
            "elevation download --product nmt --country pl"
            " --bbox 500000,250000,501000,251000 --bbox-crs EPSG:2180"
            " --sheet-system 1992 --resolution 1m --vertical-crs EVRF2007 --year 2023",
            ("bbox", "bbox_crs"),
            {},
        ),
    ],
    ids=["sheet", "teryt", "bbox"],
)
def test_an_area_takes_the_place_of_the_area_a_call_names(
    adapter: ActionAdapter,
    tmp_path: Path,
    line: str,
    replaced: tuple[str, ...],
    added: dict[str, object],
) -> None:
    """The area's GeoJSON is ``geometry``; Kartograf validates the call offline.

    The options that chose an area go, the other options stay, a country the
    command needs and the call lacks is the area's, and the call's line reads
    back into it.
    """
    assert isinstance(adapter, AreaCommandAdapter)
    geo = cast(GeoAdapter, adapter)
    record = area_from_geometry(KRAKOW, adapter=geo, source="drawn")
    area_file = write_area_geojson(tmp_path / "areas", record)
    call = adapter.parse(line)
    kept = {name: value for name, value in call.options.items() if name not in replaced}

    with no_network() as attempts:
        found = adapter.with_area(
            call,
            area_file=area_file,
            geometry=record.geometry,
            countries=record.countries,
        )
        read_back = adapter.parse(adapter.format(found.call))
        adapter.validate(
            found.call.command, found.call.options, root=tmp_path / "store"
        )

    assert record.countries == ("PL",)
    assert (found.way, found.replaced) == ("geometry", replaced)
    assert found.call == CommandCall(
        "kartograf", call.command, {**kept, "geometry": str(area_file), **added}
    )
    assert read_back == found.call
    assert attempts == []


def _boxed_command() -> CommandInfo:
    """Return a command that chooses its area by a sheet or a box, no geometry file."""

    def option(name: str, kind: OptionType, group: str | None = None) -> CommandOption:
        return CommandOption(name, kind, False, name, group=group)

    return CommandInfo(
        producer="kartograf",
        command="boxes download",
        group="boxes",
        summary="",
        description="",
        options=(
            option("product", "string"),
            option("country", "string"),
            option("sheet", "string", "area"),
            option("bbox", "array", "area"),
            option("bbox_crs", "string"),
        ),
        read_only=False,
        writes="add",
        network=True,
        check=True,
        store=True,
        examples=(),
    )


@pytest.mark.parametrize(
    ("countries", "crs"),
    [(("PL",), "EPSG:2180"), (("CZ",), "EPSG:5514"), ((), "EPSG:4326")],
)
def test_a_command_without_a_geometry_file_gets_the_box_of_the_area(
    tmp_path: Path, countries: tuple[str, ...], crs: str
) -> None:
    """The box encloses the polygon in the CRS of its first country, whole metres.

    An area in neither country gives its WGS84 envelope. The call says so
    (``way`` ``bbox``): the producer may select data outside the area.
    """
    call = CommandCall("kartograf", "boxes download", {"product": "p", "sheet": "A"})

    found = actions_module.area_call(
        _boxed_command(),
        call,
        area_file=tmp_path / "0123456789abcdef.geojson",
        geometry=KRAKOW,
        countries=countries,
    )

    options = dict(found.call.options)
    box = cast(list[float], options.pop("bbox"))
    assert (found.way, found.replaced) == ("bbox", ("sheet",))
    assert options == {
        "product": "p",
        "bbox_crs": crs,
        "country": actions_module.area_country(countries),
    }
    ring = shapely.get_coordinates(shapely.segmentize(shape(KRAKOW), 0.005))
    if crs == "EPSG:4326":
        xs, ys = ring[:, 0], ring[:, 1]
        slack = 1e-6
    else:
        xs, ys = kartograf.pinned_transform("EPSG:4326", crs).transform(
            ring[:, 0], ring[:, 1]
        )
        slack = 1.0
        assert all(value == round(value) for value in box)
    assert box[0] <= xs.min() <= box[0] + slack
    assert box[1] <= ys.min() <= box[1] + slack
    assert box[2] - slack <= xs.max() <= box[2]
    assert box[3] - slack <= ys.max() <= box[3]


def test_a_command_that_takes_no_area_is_refused(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """``store overview`` chooses no area; an unknown command is Kartograf's refusal."""
    assert isinstance(adapter, AreaCommandAdapter)
    area_file = tmp_path / "0123456789abcdef.geojson"

    def given(call: CommandCall) -> None:
        adapter.with_area(call, area_file=area_file, geometry=KRAKOW, countries=("PL",))

    with pytest.raises(UnsupportedError) as without:
        given(adapter.parse("store overview"))
    with pytest.raises(ProducerError) as unknown:
        given(CommandCall("kartograf", "boxes download", {}))

    assert without.value.details["reason"] == "no_area_option"
    assert unknown.value.code == "validation_error"
