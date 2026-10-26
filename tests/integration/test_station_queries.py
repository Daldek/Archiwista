"""Station queries of the local index (plan I4, commit 2).

The stations are written the way a scan writes a provider's catalog
(``IndexWriter.replace_stations``), from synthetic lists, so every rule is
shown on the codes it is about: the box takes located stations only and the
stations without a location are counted beside it after the attribute
filters, a river with its tributaries is a prefix of the hydrographic code
(by whole parts for ČHMÚ codes), and two providers never share a station.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from archiwista.errors import IndexQueryError
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    RiverScope,
    StationCounts,
    StationPage,
    StationQuery,
)
from archiwista.sources import Station

STORE = "dane"
OTHER = "drugi"
PL = "IMGW-PIB"
CZ = "CHMI"


@pytest.fixture
def index(tmp_path: Path) -> Iterator[tuple[IndexWriter, IndexQueries]]:
    """Return a writer and queries of an index that knows two stores."""
    path = tmp_path / "index.sqlite"
    with IndexWriter(path) as writer, IndexQueries(path) as queries:
        writer.sync_stores(
            {
                STORE: {"imgw": tmp_path / "dane" / "imgw"},
                OTHER: {"imgw": tmp_path / "drugi" / "imgw"},
            }
        )
        yield writer, queries


def _write(
    writer: IndexWriter, provider: str, stations: list[Station], store: str = STORE
) -> None:
    slot = "stations/versions" + ("/chmi_stations" if provider == CZ else "")
    writer.replace_stations(
        store,
        "imgw",
        provider,
        slot=slot,
        version=f"{slot}/2026-10-26_00000000/stations.geojson",
        stations=stations,
    )


def _codes(page: StationPage) -> set[str]:
    return {row.code for row in page.items}


def _all(queries: IndexQueries, query: StationQuery) -> list[tuple[str, str, str]]:
    """Return ``(store, provider, code)`` of every row, page after page."""
    rows: list[tuple[str, str, str]] = []
    cursor = None
    while True:
        page = queries.stations(
            StationQuery(
                store=query.store,
                provider=query.provider,
                code=query.code,
                kind=query.kind,
                active=query.active,
                river_code=query.river_code,
                river_scope=query.river_scope,
                bbox=query.bbox,
                location=query.location,
                limit=query.limit,
                cursor=cursor,
            )
        )
        rows.extend((row.store, row.provider, row.code) for row in page.items)
        cursor = page.next_cursor
        if cursor is None:
            return rows


def test_a_box_returns_only_the_located_stations_inside_it(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Edges included; the stations without a location are counted beside it."""
    # Arrange
    writer, queries = index
    _write(
        writer,
        PL,
        [
            Station(PL, "149190310", kind="hydro", point=(20.0, 50.0)),
            Station(PL, "149190320", kind="hydro", point=(21.0, 50.5)),
            Station(PL, "150200010", kind="hydro", point=(21.0001, 50.5)),
            Station(PL, "149190330", kind="hydro", location_reason="none"),
            Station(PL, "249190340", kind="meteo", location_reason="zero"),
        ],
    )
    _write(
        writer,
        CZ,
        [
            Station(CZ, "0-203-1-1", kind="hydro", point=(20.5, 50.25)),
            Station(CZ, "0-203-1-2", kind="hydro", location_reason="outside_country"),
        ],
    )
    box = (20.0, 50.0, 21.0, 50.5)

    # Act
    boxed = queries.stations(StationQuery(bbox=box))
    hydro = queries.stations(StationQuery(bbox=box, kind="hydro", provider=PL))
    unlocated = queries.stations(StationQuery(bbox=box, location="none"))
    everything = queries.stations(StationQuery())

    # Assert
    assert _codes(boxed) == {"149190310", "149190320", "0-203-1-1"}
    assert all(row.location == "point" and row.point for row in boxed.items)
    assert boxed.counts == StationCounts(located=3, unlocated=3)
    assert _codes(hydro) == {"149190310", "149190320"}
    assert hydro.counts == StationCounts(located=2, unlocated=1)
    assert _codes(unlocated) == {"149190330", "249190340", "0-203-1-2"}
    assert {(row.location, row.point) for row in unlocated.items} == {("none", None)}
    assert {row.location_reason for row in unlocated.items} == {
        "none",
        "zero",
        "outside_country",
    }
    assert everything.counts == StationCounts(located=4, unlocated=3)
    assert len(everything.items) == 7


def test_a_river_with_its_tributaries_is_a_prefix_of_the_imgw_code(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """P19: Raba 2138 takes Mszanka 21382 and Stradomka 21388, never 2139."""
    # Arrange
    writer, queries = index
    codes = {
        "1": "2138",
        "2": "21382",
        "3": "21388",
        "4": "213821",
        "5": "2139",
        "6": "213",
        "7": "21",
        "8": None,
    }
    _write(
        writer,
        PL,
        [
            Station(
                PL,
                f"14919031{key}",
                hydrographic_code=code,
                point=(20.0, 50.0) if key != "2" else None,
                location_reason=None if key != "2" else "none",
            )
            for key, code in codes.items()
        ],
    )

    def river(code: str, scope: RiverScope) -> set[str | None]:
        page = queries.stations(StationQuery(river_code=code, river_scope=scope))
        return {row.hydrographic_code for row in page.items}

    # Act
    tributaries = river("2138", "tributaries")
    exact = river("2138", "exact")
    shorter = river("213", "tributaries")

    # Assert
    assert tributaries == {"2138", "21382", "21388", "213821"}
    assert exact == {"2138"}
    assert shorter == {"2138", "21382", "21388", "213821", "2139", "213"}
    assert river("2139", "tributaries") == {"2139"}
    assert river("21382", "tributaries") == {"21382", "213821"}


def test_a_czech_river_takes_its_tributaries_by_whole_parts_of_the_code(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """ČHMÚ HLGP4 codes: 1-05 takes 1-05-03-0110, not 1-050-01-0001."""
    # Arrange
    writer, queries = index
    codes = [
        "1-05",
        "1-05-03-0110",
        "1-05-02-0720",
        "1-050-01-0001",
        "1-06-01-0010",
        "2-01-02-0030",
    ]
    _write(
        writer,
        CZ,
        [
            Station(CZ, f"0-203-1-{number}", hydrographic_code=code, point=(15.0, 50.0))
            for number, code in enumerate(codes)
        ],
    )

    def river(code: str) -> set[str | None]:
        page = queries.stations(
            StationQuery(river_code=code, river_scope="tributaries")
        )
        return {row.hydrographic_code for row in page.items}

    # Act
    found = river("1-05")

    # Assert
    assert found == {"1-05", "1-05-03-0110", "1-05-02-0720"}
    assert river("1") == {code for code in codes if code.startswith("1-")}
    assert river("1-0") == set()
    assert river("1-05-03-0110") == {"1-05-03-0110"}
    assert river(" 2-01 ") == {"2-01-02-0030"}


def test_two_providers_and_two_stores_never_share_a_station(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A code is the provider's: one code in two catalogs is two stations."""
    # Arrange
    writer, queries = index
    same = "149190310"
    _write(writer, PL, [Station(PL, same, name="Stróża", point=(20.0, 50.0))])
    _write(writer, CZ, [Station(CZ, same, name="Lhota", location_reason="none")])
    _write(writer, PL, [Station(PL, same, name="Stróża", point=(20.0, 50.0))], OTHER)

    # Act
    everywhere = _all(queries, StationQuery(code=same))
    polish = queries.stations(StationQuery(code=same, provider=PL, store=STORE))
    card = queries.station(STORE, CZ, same)

    # Assert
    assert sorted(everywhere) == [
        (STORE, CZ, same),
        (STORE, PL, same),
        (OTHER, PL, same),
    ]
    assert [(row.name, row.point) for row in polish.items] == [("Stróża", (20.0, 50.0))]
    assert card is not None
    assert (card.name, card.location, card.location_reason) == ("Lhota", "none", "none")
    assert card.catalog_version == (
        "stations/versions/chmi_stations/2026-10-26_00000000/stations.geojson"
    )
    assert queries.station(STORE, PL, "149190311") is None
    assert queries.station("unknown", PL, same) is None


def test_pages_follow_the_names_and_a_cursor_belongs_to_its_query(
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Every station once, by name; a cursor of other filters is refused."""
    # Arrange
    writer, queries = index
    _write(
        writer,
        PL,
        [
            Station(
                PL,
                f"1491903{number:02d}",
                name=None if number % 5 == 0 else f"Stacja {number % 7}",
                kind="hydro" if number % 2 else "meteo",
                active=number % 3 != 0,
                point=(20.0 + number / 100, 50.0) if number % 4 else None,
                location_reason=None if number % 4 else "none",
            )
            for number in range(23)
        ],
    )

    # Act
    paged = _all(queries, StationQuery(limit=4))
    first = queries.stations(StationQuery(limit=4, kind="hydro"))
    historical = queries.stations(StationQuery(active=False, limit=200))

    # Assert
    assert len(paged) == len(set(paged)) == 23
    assert paged == [
        (STORE, PL, row.code) for row in queries.stations(StationQuery(limit=200)).items
    ]
    assert first.next_cursor is not None
    with pytest.raises(IndexQueryError):
        queries.stations(StationQuery(limit=4, cursor=first.next_cursor))
    with pytest.raises(IndexQueryError):
        queries.stations(StationQuery(limit=4, cursor="not-a-cursor"))
    assert {row.active for row in historical.items} == {False}
    assert len(historical.items) == len([n for n in range(23) if n % 3 == 0])


@pytest.mark.parametrize(
    "query",
    [
        StationQuery(river_code="  ", river_scope="tributaries"),
        StationQuery(bbox=(21.0, 50.0, 20.0, 51.0)),
        StationQuery(limit=0),
    ],
    ids=["empty river code", "reversed box", "limit"],
)
def test_a_query_out_of_its_rules_is_refused(
    index: tuple[IndexWriter, IndexQueries], query: StationQuery
) -> None:
    """An empty river code, a box that is no rectangle, a page of no rows."""
    _, queries = index

    with pytest.raises(IndexQueryError):
        queries.stations(query)
