"""The station routes over the producer's fixture store (plan I6, SPEC 9.2, 6.7).

``GET /stations``, ``/stations/{code}``, ``/stations/{code}/coverage`` and
``GET /map/stations`` answer from the index of a scanned copy of
``complete_pl_cz`` (``imgwtools.testing``): the stations of both providers, the
location groups counted apart (SPEC 4.3 point 3), the coverage of each
variable with its licence and attribution, the boundary of an area by the
location uncertainty, and ``503`` while the source is not available
(SPEC 5.8). The OpenAPI document lists the four routes with their
parameters, examples and problems.
"""

import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from archiwista.api import models_stations
from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import AreaRecord, IndexWriter, initialize, scan_store
from archiwista.sources.registry import PluginRegistry, load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.local_server import NoSources, local_paths
from tests.fixtures.missing_package import hide_packages

STORE = "dane"
COPY = "kopia"
DAILY = "pl.imgw.hydro_daily"
RABA = "149190310"  # Raba Górna: 20.1 E, 49.7 N, uncertain to 5566 m

type Stores = Callable[[str], Path]
# An area 1.4 km east of Raba Górna, closer to it than its uncertainty.
AREA = AreaRecord(
    id="zlewnia",
    source="drawn",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [[20.12, 49.6], [20.4, 49.6], [20.4, 49.8], [20.12, 49.8], [20.12, 49.6]]
        ],
    },
    created_at=datetime(2026, 10, 26, tzinfo=UTC),
    area_km2=630.0,
    countries=("PL",),
    name="zlewnia.gpkg",
)
EAST_OF_RABA = "20.12,49.6,20.4,49.8"
ROUTES = (
    "/api/v1/stations",
    "/api/v1/stations/{code}",
    "/api/v1/stations/{code}/coverage",
    "/api/v1/map/stations",
)


@dataclass(frozen=True)
class Served:
    """The API over the index of the fixture store, with the owner's session."""

    owner: Caller
    paths: AppPaths

    def get(self, path: str, *, lang: str | None = None) -> httpx.Response:
        """Return the answer of ``GET path`` under ``/api/v1``."""
        return self.owner.request("GET", path, accept_language=lang)

    def json(self, path: str) -> Any:
        """Return the body of a ``200`` answer of ``GET path``."""
        response = self.get(path)
        assert response.status_code == 200, response.text
        return response.json()


def _scanned(paths: AppPaths, roots: dict[str, Path], registry: PluginRegistry) -> None:
    """Configure a store over each root and scan it fully into the index."""
    configs = tuple(
        StoreConfig(id=store, name=store.title(), imgw=root, kind="local")
        for store, root in roots.items()
    )
    settings = AppSettings(stores=configs)
    ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({config.id: config.roots() for config in configs})
        writer.write_area(AREA)
        for config in configs:
            adapter = registry.adapter("imgw")
            scan_store(adapter, writer, settings, config.id, mode="full")


@pytest.fixture(scope="module")
def served(
    imgw_store: Stores, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Served]:
    """Serve the index of a copy of ``complete_pl_cz`` after a full scan."""
    base = tmp_path_factory.mktemp("stations-api")
    root = base / "store"
    shutil.copytree(imgw_store("complete_pl_cz"), root)
    paths = local_paths(base)
    registry = load_registry(cache_dir=paths.cache_dir)
    _scanned(paths, {STORE: root}, registry)
    with running_api(paths, registry) as api:
        yield Served(api.session(LOCAL_OWNER), paths)


def _codes(body: dict[str, Any]) -> list[str]:
    return [item["code"] for item in body["items"]]


def test_stations_lists_both_providers_page_by_page_with_the_location_groups(
    served: Served,
) -> None:
    """Every station once, page after page; the unlocated keep their reason."""
    # Act
    pages = [served.json("/stations?limit=5")]
    while pages[-1]["next_cursor"] is not None:
        pages.append(
            served.json(f"/stations?limit=5&cursor={pages[-1]['next_cursor']}")
        )
    unlocated = served.json("/stations?location=none")
    whole = served.json("/stations?limit=50")

    # Assert
    codes = [code for page in pages for code in _codes(page)]
    assert codes == _codes(whole)
    assert len(codes) == len(set(codes)) == 13
    assert {item["provider"] for item in whole["items"]} == {"IMGW-PIB", "CHMI"}
    assert whole["counts"] == {"located": 8, "boundary": 0, "unlocated": 5, "hidden": 0}
    assert {item["location"]["reason"] for item in unlocated["items"]} == {
        "none",
        "zero",
        "outside_country",
    }
    assert {item["location"]["lon"] for item in unlocated["items"]} == {None}
    assert whole["stale"] is False and whole["area"] is None


def test_a_station_card_labels_each_series_with_its_file_licence_and_formula(
    served: Served,
) -> None:
    """The card names the series version, the file with its digest, the terms."""
    # Act
    card = served.json(f"/stations/{RABA}")["station"]
    czech = served.json("/stations/0-203-1-900001")["station"]
    polish = served.get(f"/stations/{RABA}?dataset={DAILY}", lang="pl").json()

    # Assert
    assert (card["name"], card["provider"], card["store"]) == (
        "Raba Górna",
        "IMGW-PIB",
        STORE,
    )
    assert card["location"] == {
        "kind": "point",
        "lon": 20.1,
        "lat": 49.7,
        "reason": None,
        "source": "api_hydro",
        "uncertainty_m": 5566.0,
        "on_boundary": False,
    }
    (series,) = card["series"]
    assert (series["dataset"], series["year_type"], series["years"]) == (
        DAILY,
        "hydrological",
        {"from": 1951, "to": 2024},
    )
    assert (
        series["file"]
        == f"{series['series_version'].rsplit('/', 1)[0]}/stations/{RABA}.parquet"
    )
    assert len(series["sha256"]) == 64
    assert series["license"] == "IMGW-PIB"
    assert series["attribution"].startswith("Źródłem pochodzenia danych jest Instytut")
    assert list(series["coverage"]) == ["H", "Q", "T"]
    assert series["coverage"]["Q"]["state"] == "gaps"
    assert series["coverage"]["Q"]["unknown_years"] == [{"from": 1951, "to": 2023}]
    assert czech["provider"] == "CHMI"
    assert {item["license"] for item in czech["series"]} == {"CC-BY-4.0"}
    label = polish["station"]["series"][0]["coverage"]["H"]["label"]
    assert label == "luki 91% · najdł. 2024.03.01–2024.10.31 · nieznane: 1951–2023"


def test_the_timeline_gives_every_year_of_the_range_with_its_cell(
    served: Served,
) -> None:
    """A year that is not wholly known is ``unknown``, never a gap."""
    # Act
    timeline = served.json(f"/stations/{RABA}/coverage?variable=Q&years=2022-2024")

    # Assert
    (series,) = timeline["series"]
    assert series["years"] == {"from": 2022, "to": 2024}
    (variable,) = series["variables"]
    assert variable["key"] == "Q"
    assert [
        (year["year"], year["units"], year["known"], year["with_value"], year["cell"])
        for year in variable["years"]
    ] == [
        (2022, 365, 0, 0, "unknown"),
        (2023, 365, 0, 0, "unknown"),
        (2024, 366, 366, 1, "fraction"),
    ]


def test_an_area_takes_a_station_on_its_boundary_by_its_uncertainty(
    served: Served,
) -> None:
    """Raba Górna lies 1.4 km outside, uncertain to 5.6 km: on the boundary.

    A kept area and the same rectangle as ``bbox`` agree; ``boundary=false``
    leaves the station out and still counts it; the stations without a
    location are counted beside the area and never placed in it.
    """
    # Act
    kept = served.json(f"/stations?area_id={AREA.id}")
    drawn = served.json(f"/stations?bbox={EAST_OF_RABA}")
    inside = served.json(f"/stations?area_id={AREA.id}&boundary=false")
    unlocated = served.json(f"/stations?area_id={AREA.id}&location=none")

    # Assert
    assert _codes(kept) == [RABA]
    assert kept["items"][0]["location"]["on_boundary"] is True
    assert kept["area"] == {
        "id": AREA.id,
        "name": "zlewnia.gpkg",
        "area_km2": 630.0,
        "countries": ["PL"],
    }
    assert kept["counts"] == {"located": 1, "boundary": 1, "unlocated": 5, "hidden": 0}
    assert (drawn["items"], drawn["counts"]) == (kept["items"], kept["counts"])
    assert drawn["area"] is None
    assert (inside["items"], inside["counts"]["boundary"]) == ([], 1)
    assert inside["counts"]["located"] == 0
    assert len(unlocated["items"]) == unlocated["counts"]["unlocated"] == 5


def test_coverage_filters_hide_stations_and_count_them(served: Served) -> None:
    """``Q:gaps`` keeps Raba Górna; its neighbour without a value of Q is hidden."""
    # Act
    gaps = served.json(f"/stations?dataset={DAILY}&coverage=Q:gaps")
    no_data = served.json(f"/stations?dataset={DAILY}&coverage=Q:no_data")
    either = served.json(
        f"/stations?dataset={DAILY}&coverage=Q:gaps&coverage=Q:no_data"
    )
    years = served.json(f"/stations?dataset={DAILY}&min_complete_years=H:1")
    having = served.json(f"/stations?dataset={DAILY}&variable=Q")

    # Assert
    assert _codes(gaps) == [RABA]
    assert gaps["counts"] == {"located": 1, "boundary": 0, "unlocated": 0, "hidden": 1}
    assert _codes(no_data) == ["149190311"]
    assert no_data["items"][0]["location"]["kind"] == "none"
    assert no_data["counts"] == {
        "located": 0,
        "boundary": 0,
        "unlocated": 1,
        "hidden": 1,
    }
    assert sorted(_codes(either)) == ["149190310", "149190311"]
    assert either["counts"]["hidden"] == 0
    assert (years["items"], years["counts"]["hidden"]) == ([], 2)
    assert _codes(having) == [RABA]
    assert having["counts"]["hidden"] == 0


@pytest.mark.parametrize(
    ("path", "status", "code", "pointer"),
    [
        ("/stations?coverage=Q:gaps", 400, "validation_error", None),
        ("/stations?min_complete_years=Q:30", 400, "validation_error", None),
        (f"/stations?dataset={DAILY}&years=2025-1951", 400, "validation_error", None),
        ("/stations?coverage=Q:bad", 400, "validation_error", "/query/coverage"),
        ("/stations?min_complete_years=Q:x", 400, "validation_error", None),
        ("/stations?years=19-20", 400, "validation_error", "/query/years"),
        ("/stations?product=hydro", 400, "validation_error", "/query/product"),
        (
            f"/stations?area_id={AREA.id}&bbox={EAST_OF_RABA}",
            400,
            "validation_error",
            None,
        ),
        ("/stations?area_id=brak", 400, "validation_error", None),
        ("/stations?store=brak", 400, "validation_error", None),
        ("/map/stations", 400, "validation_error", "/query/bbox"),
        ("/stations/000000000", 404, "not_found", None),
        ("/stations/000000000/coverage", 404, "not_found", None),
    ],
)
def test_station_routes_refuse_what_they_cannot_answer(
    served: Served, path: str, status: int, code: str, pointer: str | None
) -> None:
    """A filter that cannot apply is a problem, never an empty or a wrong answer."""
    # Act
    response = served.get(path)

    # Assert
    assert_problem(response, status, code)
    if pointer is not None:
        pointers = [item["pointer"] for item in response.json()["errors"]]
        assert pointer in pointers


def test_the_map_draws_located_stations_or_their_grid(served: Served) -> None:
    """Above ``limit`` a grid; with ``dataset`` each point has its labels."""
    # Act
    points = served.json("/map/stations?bbox=14,48,24,55")
    grid = served.json("/map/stations?bbox=14,48,24,55&limit=3&grid_columns=4")
    labelled = served.json(f"/map/stations?bbox=14,48,24,55&dataset={DAILY}")

    # Assert
    assert (points["total"], points["aggregated"], len(points["items"])) == (
        8,
        False,
        8,
    )
    assert {item["coverage"] == {} for item in points["items"]} == {True}
    assert (grid["total"], grid["aggregated"], grid["items"]) == (8, True, [])
    assert sum(cell["count"] for cell in grid["cells"]) == 8
    assert (
        grid["counts"]
        == points["counts"]
        == {
            "located": 8,
            "boundary": 0,
            "unlocated": 5,
            "hidden": 0,
        }
    )
    (raba,) = labelled["items"]
    assert raba["code"] == RABA
    assert {key: value["state"] for key, value in raba["coverage"].items()} == {
        "H": "gaps",
        "Q": "gaps",
        "T": "gaps",
    }


def test_a_code_of_two_stations_names_them_until_store_and_provider_choose(
    imgw_store: Stores, tmp_path: Path
) -> None:
    """Two stores over copies of one store: the code alone is ambiguous."""
    # Arrange
    roots = {store: tmp_path / store for store in (STORE, COPY)}
    for root in roots.values():
        shutil.copytree(imgw_store("complete_pl_cz"), root)
    paths = local_paths(tmp_path)
    registry = load_registry(cache_dir=paths.cache_dir)
    _scanned(paths, roots, registry)

    # Act
    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        ambiguous = owner.request("GET", f"/stations/{RABA}")
        timeline = owner.request("GET", f"/stations/{RABA}/coverage")
        chosen = owner.request(
            "GET", f"/stations/{RABA}?store={COPY}&provider=IMGW-PIB"
        )

    # Assert
    assert_problem(ambiguous, 400, "validation_error", "ambiguous_station")
    body = ambiguous.json()
    assert body["details"]["stations"] == [
        {"store": STORE, "provider": "IMGW-PIB"},
        {"store": COPY, "provider": "IMGW-PIB"},
    ]
    assert body["hint"]
    assert timeline.json() == {**body, "instance": f"/api/v1/stations/{RABA}/coverage"}
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["station"]["store"] == COPY


@pytest.mark.parametrize("missing", ["registry", "package"])
def test_station_routes_answer_503_while_the_source_is_not_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """Without IMGWTools the stations the index may hold are not shown (SPEC 5.8)."""
    # Arrange
    paths = local_paths(tmp_path)
    registry: PluginRegistry = NoSources()
    if missing == "package":
        hide_packages(monkeypatch, "imgwtools")
        registry = load_registry(cache_dir=paths.cache_dir)

    # Act
    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        answers = [
            owner.request("GET", path)
            for path in (
                "/stations",
                f"/stations/{RABA}",
                f"/stations/{RABA}/coverage",
                "/map/stations?bbox=14,48,24,55",
            )
        ]
        polish = owner.request("GET", "/stations", accept_language="pl")

    # Assert
    for response in answers:
        assert_problem(response, 503, "missing_dependency", "source_unavailable")
        source = response.json()["details"]["source"]
        assert (source["id"], source["state"]) == ("imgw", "not_installed")
        assert source["requirement"] == "archiwista[imgw]"
        assert 'pip install "archiwista[imgw]"' in response.json()["hint"]
    assert polish.headers["content-language"] == "pl"
    assert 'pip install "archiwista[imgw]"' in polish.json()["detail"]


def test_openapi_documents_the_station_routes(served: Served) -> None:
    """Agents find the four routes, their parameters, examples and problems."""
    # Act
    document = served.json("/openapi.json")

    # Assert
    schemas = document["components"]["schemas"]
    for path in ROUTES:
        operation = document["paths"][path]["get"]
        responses = operation["responses"]
        assert {"400", "401", "503"} <= set(responses), path
        for status, response in responses.items():
            if int(status) >= 400:
                assert list(response["content"]) == ["application/problem+json"]
        reference = responses["200"]["content"]["application/json"]["schema"]["$ref"]
        assert schemas[reference.rsplit("/", 1)[1]]["examples"]
    names = {
        item["name"]
        for item in document["paths"]["/api/v1/stations"]["get"]["parameters"]
    }
    assert names == {
        "store", "provider", "dataset", "years", "year_type", "kind", "active",
        "river_code", "river_scope", "variable", "coverage", "min_complete_years",
        "meteo_kind", "q", "sort",
        "area_id", "bbox", "bbox_crs", "boundary", "location", "limit", "cursor",
    }  # fmt: skip
    card = document["paths"]["/api/v1/stations/{code}"]["get"]
    assert {item["name"] for item in card["parameters"]} == {
        "code", "store", "provider", "dataset", "years", "year_type",
    }  # fmt: skip
    assert "404" in card["responses"]
    assert document["paths"]["/api/v1/map/stations"]["get"]["tags"] == [
        "stations",
        "map",
    ]


def test_station_examples_validate_against_their_models() -> None:
    """Every documented example of the station models is a valid instance."""
    checked = 0
    for model in vars(models_stations).values():
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            continue
        extra = model.model_config.get("json_schema_extra")
        examples = extra.get("examples") if isinstance(extra, dict) else None
        for example in examples if isinstance(examples, list) else []:
            model.model_validate(example)
            checked += 1
    assert checked >= 15
