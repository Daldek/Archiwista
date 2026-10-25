"""The read API over HTTP (plan step 9a, SPEC 9).

A generated Kartograf store is scanned through the real adapter into a fresh
index and served by the application; every route is called with a session
like a browser or an agent would, errors are RFC 9457 problems with stable
codes, and the OpenAPI document describes it all with examples.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

import archiwista.api.models as models
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.config import ConfigStore
from archiwista.error_document import describe
from archiwista.errors import (
    ArchiwistaError,
    IndexQueryError,
    PathOutsideRootError,
    ProducerError,
    SourceUnavailableError,
)
from archiwista.index import IndexQueries, IndexWriter, ManifestStamp, MapQuery
from archiwista.security import CSRF_HEADER
from archiwista.sources import ProjectInfo, SourceAdapter, SourceState
from archiwista.sources.registry import source_error
from tests.fixtures.api_session import assert_problem, running_api
from tests.fixtures.api_store import ALIAS, STORE, ServedStore, served_store
from tests.fixtures.local_server import NoSources, local_paths, serving

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

KRAKOW = "19.9,50.0,20.0,50.05"
ROUTES = {
    ("get", "/api/v1/health"),
    ("get", "/api/v1/sources"),
    ("get", "/api/v1/stores"),
    ("get", "/api/v1/stores/{store}"),
    ("get", "/api/v1/products"),
    ("get", "/api/v1/slots"),
    ("get", "/api/v1/stores/{store}/slots/{slot}"),
    ("get", "/api/v1/stores/{store}/versions/{version}"),
    ("get", "/api/v1/stores/{store}/versions/{version}/sidecar"),
    ("get", "/api/v1/requests/{parent_request}"),
    ("get", "/api/v1/map/footprints"),
    ("get", "/api/v1/map/sheets"),
    ("get", "/api/v1/projects"),
    ("get", "/api/v1/projects/{project}"),
    ("get", "/api/v1/projects/{project}/status"),
    ("get", "/api/v1/settings"),
    ("put", "/api/v1/settings"),
}


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServedStore]:
    """Serve one scanned store for the read-only tests of this module."""
    with served_store(tmp_path_factory.mktemp("api")) as found:
        yield found


def _get(served: ServedStore, path: str) -> Any:
    response = served.owner.request("GET", path)
    assert response.status_code == 200, response.text
    return response.json()


def _all_rows(
    served: ServedStore, query: str, limit: int
) -> list[tuple[str, str | None]]:
    rows: list[tuple[str, str | None]] = []
    cursor = ""
    while True:
        page = _get(served, f"/slots?{query}&limit={limit}{cursor}")
        rows += [
            (row["slot"], (row["version"] or {}).get("path")) for row in page["items"]
        ]
        if page["next_cursor"] is None:
            return rows
        cursor = f"&cursor={page['next_cursor']}"


def test_api_every_read_route_answers_from_the_index(served: ServedStore) -> None:
    """Health, sources, stores, products, catalog, cards, map and projects."""
    # Arrange
    root = served.store.root

    # Act
    health = _get(served, "/health")
    stores = _get(served, "/stores")
    store = _get(served, f"/stores/{STORE}")
    products = _get(served, f"/products?store={STORE}")
    page = _get(served, "/slots?product=nmt&limit=1")
    row = page["items"][0]
    card = _get(served, f"/stores/{STORE}/slots/{row['slot']}")
    path = card["current"]
    version = _get(served, f"/stores/{STORE}/versions/{path}")
    sidecar = _get(served, f"/stores/{STORE}/versions/{path}/sidecar")
    footprints = _get(served, "/map/footprints?bbox=14,49,24.2,55&limit=1")
    sheets = _get(served, f"/map/sheets?bbox={KRAKOW}&system=1992&scale=1:10000")
    projects = _get(served, "/projects")
    project = _get(served, f"/projects/{projects['items'][0]['project']}")
    sources = _get(served, "/sources")

    # Assert
    assert health["stores"][0]["state"]["status"] == "available"
    assert health["stores"][0]["state"]["last_scan"] is None  # scanned in-process
    assert health["index"]["schema_version"] >= 3
    assert stores["items"][0]["state"]["slots"] == health["stores"][0]["state"]["slots"]
    assert store["usage"]["versions"] > 0 and store["projects"]
    assert {item["product"] for item in products["items"]} >= {"nmt"}
    assert page["groups"]["footprint"] + page["groups"]["none"] > 0
    assert (card["store"], card["slot"]) == (STORE, row["slot"])
    assert any(item["is_current"] for item in card["versions"])
    assert card["paths"]["local"] == str(root / row["slot"])
    assert card["paths"]["aliases"][0].startswith(ALIAS)
    assert version["version"]["path"] == path and version["sidecar"] == sidecar
    assert version["paths"]["local"] == str(root / path)
    assert footprints["aggregated"] and footprints["total"] > 1
    assert sheets["status"] == "available" and sheets["items"][0]["geometry"]
    assert project["tasks"] and project["project"] == projects["items"][0]["project"]
    producers = {item["producer"]: item["status"] for item in sources["items"]}
    assert list(producers) == ["imgw", "kartograf"]
    assert producers["kartograf"] == "available"
    assert not page["stale"] and page["stale_stores"] == []


def test_api_map_outlines_match_index_and_keep_response_contract(
    served: ServedStore,
) -> None:
    """Large map answers reuse the indexed polygons without changing JSON fields."""
    query = MapQuery(bbox=(14.0, 49.0, 24.2, 55.0))
    with IndexQueries(served.api.paths.index_file) as queries:
        page = queries.footprints(query, visible=ALL_PROJECTS)
    response = served.owner.request("GET", "/map/footprints?bbox=14,49,24.2,55")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    actual = models.MapView.model_validate_json(response.content)
    assert actual.total == len(page.items) and not actual.aggregated
    assert [item.model_dump() for item in actual.items] == [
        models.Footprint.of(item).model_dump() for item in page.items
    ]
    assert actual.groups == models.LocationGroups.of(page.groups)


def test_api_slots_filters_limit_and_cursor(served: ServedStore) -> None:
    """Pages of any size give the same rows; limits, cursors, params are checked."""
    # Arrange
    every = _all_rows(served, "versions=all", 200)

    # Act
    paged = _all_rows(served, "versions=all", 7)
    nmt = _all_rows(served, "versions=all&product=nmt", 200)
    years = _get(served, "/slots?versions=all&years=2019-2021&limit=200")
    first = _get(served, "/slots?limit=3")
    too_many = served.owner.request("GET", "/slots?limit=201")
    foreign = served.owner.request(
        "GET", f"/slots?product=nmt&cursor={first['next_cursor']}"
    )
    misspelt = served.owner.request("GET", "/slots?prodcut=nmt")
    unknown = served.owner.request("GET", "/slots?store=brak")
    reversed_years = served.owner.request("GET", "/slots?years=2022-2020")

    # Assert
    assert paged == every and len(every) > 7
    assert nmt and set(nmt) < set(every)
    assert all(2019 <= row["version"]["data_year"] <= 2021 for row in years["items"])
    assert_problem(too_many, 400, "validation_error")
    assert too_many.json()["errors"][0]["pointer"] == "/query/limit"
    assert_problem(foreign, 400, "validation_error")
    assert_problem(misspelt, 400, "validation_error")
    assert_problem(unknown, 400, "validation_error")
    assert_problem(reversed_years, 400, "validation_error")


def test_api_problems_for_routes_methods_and_unknown_files(served: ServedStore) -> None:
    """Unknown routes and files are 404, other methods 405 with Allow."""
    # Act
    route = served.owner.request("GET", "/nie-ma")
    method = served.owner.request("DELETE", "/slots")
    slot = served.owner.request("GET", f"/stores/{STORE}/slots/nmt/brak.asc")
    group = served.owner.request("GET", "/requests/brak")
    # Permission groups own /groups: their paths are never a request key.
    members = served.owner.request("GET", "/groups/hydro/members")
    sheets = served.owner.request(
        "GET", "/map/sheets?bbox=14,49,24.2,55&system=1992&scale=1:5000"
    )
    scale = served.owner.request(
        "GET", f"/map/sheets?bbox={KRAKOW}&system=1992&scale=1:7"
    )

    # Assert
    assert_problem(route, 404, "not_found")
    assert_problem(method, 405, "method_not_allowed")
    assert method.headers["allow"] == "GET"
    assert_problem(members, 405, "method_not_allowed")
    assert members.headers["allow"] == "PUT"
    assert_problem(slot, 404, "not_found")
    assert_problem(group, 404, "not_found")
    assert_problem(sheets, 400, "validation_error")
    assert_problem(scale, 500, "data_error", "kartograf_error")
    assert scale.json()["details"]["kartograf"]["exception"] == "ValidationError"


@pytest.mark.parametrize(
    ("error", "status", "code", "reason"),
    [
        (PathOutsideRootError("poza"), 403, "forbidden", "path_outside_root"),
        (IndexQueryError("kursor"), 400, "validation_error", None),
        (
            ProducerError("kartograf", "ValidationError", "zła skala"),
            500,
            "data_error",
            "kartograf_error",
        ),
        (
            ProducerError("external-producer", "Boom", "x"),
            500,
            "data_error",
            "producer_error",
        ),
        (
            SourceUnavailableError("magazyn odłączony"),
            503,
            "store_unavailable",
            "store_unreadable",
        ),
    ],
)
def test_api_service_errors_map_to_registry_codes(
    error: ArchiwistaError, status: int, code: str, reason: str | None
) -> None:
    """Each service error has one registry code and status, whatever the text."""
    # Act
    problem = describe(error)

    # Assert
    assert (problem.status, problem.code, problem.detail) == (status, code, str(error))
    assert problem.details.get("reason") == reason


class _Incompatible(NoSources):
    """Every producer installed in an unsupported version."""

    def state(self, producer: str) -> SourceState:
        return SourceState(producer, "incompatible", package_version="0.7.0")

    def adapter(self, producer: str) -> SourceAdapter:
        raise source_error(self.state(producer))


@pytest.mark.parametrize(
    ("registry", "reason", "state"),
    [
        (NoSources(), "source_unavailable", "not_installed"),
        (_Incompatible(), "source_incompatible", "incompatible"),
    ],
)
def test_source_states_map_to_503(
    tmp_path: Path, registry: NoSources, reason: str, state: str
) -> None:
    """Requests needing a producer say which plugin is missing and how to fix it."""
    # Arrange
    paths = local_paths(tmp_path)
    with running_api(paths, registry) as api:
        with IndexWriter(paths.index_file) as writer:
            writer.sync_stores({STORE: {"kartograf": str(tmp_path / "data")}})
            info = ProjectInfo("kartograf", str(tmp_path), tmp_path / "raba", "raba")
            writer.write_project(info, store=STORE, stamp=ManifestStamp(1, 1))
        owner = api.session(LOCAL_OWNER)

        # Act
        answers = [
            owner.request(
                "GET", f"/map/sheets?bbox={KRAKOW}&system=1992&scale=1:10000"
            ),
            owner.request("GET", f"/slots?bbox={KRAKOW}"),
            owner.request("GET", "/projects/raba/status"),
        ]
        listed = owner.request("GET", "/slots")

    # Assert
    for answer in answers:
        assert_problem(answer, 503, "missing_dependency", reason)
        source = answer.json()["details"]["source"]
        assert (source["id"], source["state"]) == ("kartograf", state)
        assert source["requirement"].startswith("kartograf")
        assert "pip install" in answer.json()["detail"]
    assert listed.status_code == 200  # the index alone needs no producer


def test_api_disconnected_store_answers_stale(tmp_path: Path) -> None:
    """Lists stay 200 from the index; the live project check falls back or 503."""
    with served_store(tmp_path) as served:
        # Arrange
        paths = served.api.paths
        project = _get(served, "/projects")["items"][0]["project"]
        with IndexWriter(paths.index_file) as writer:
            writer.set_store_status(STORE, "unavailable", detail="udział odłączony")
            info = ProjectInfo("kartograf", "x", tmp_path / "nowy", "nowy")
            writer.write_project(info, store=STORE, stamp=ManifestStamp(1, 1))

        # Act
        page = _get(served, "/slots?limit=5")
        footprints = _get(served, "/map/footprints?bbox=14,49,24.2,55")
        stores = _get(served, "/stores")
        status = _get(served, f"/projects/{project}/status")
        unchecked = served.owner.request("GET", "/projects/nowy/status")

    # Assert
    assert page["items"] and page["stale"] and footprints["stale"]
    assert page["stale_stores"][0]["store"] == STORE
    assert page["stale_stores"][0]["detail"] == "udział odłączony"
    assert stores["items"][0]["state"]["stale"]
    assert status["stale"] and status["stale_reason"] == "store_unavailable"
    assert_problem(unchecked, 503, "store_unavailable", "store_unreadable")


def test_api_settings_change_checked_saved_and_in_csp(tmp_path: Path) -> None:
    """PUT /settings validates, saves, and the next responses get the new CSP."""
    with served_store(tmp_path) as served:
        # Arrange
        current = _get(served, "/settings")
        config = ConfigStore(served.api.paths.config_file)
        before = config.path.read_text("utf-8")
        missing = {
            **current,
            "stores": [{**current["stores"][0], "kartograf": str(tmp_path / "brak")}],
        }

        # Act
        refused = served.owner.request("PUT", "/settings", json=missing)
        unchanged = config.path.read_text("utf-8")
        online = served.owner.request("GET", "/settings").headers
        saved = served.owner.request(
            "PUT", "/settings", json={**current, "offline": True}
        )
        offline = served.owner.request("GET", "/settings").headers
        no_csrf = served.owner.request("PUT", "/settings", json=current, csrf=False)

    # Assert
    assert_problem(refused, 400, "validation_error")
    assert refused.json()["details"]["problems"][0]["field"] == "stores[0].kartograf"
    assert unchanged == before
    assert saved.status_code == 200 and saved.json()["offline"] is True
    assert "https://tiles.openfreemap.org" in online["content-security-policy"]
    assert "tiles.openfreemap.org" not in offline["content-security-policy"]
    assert_problem(no_csrf, 403, "forbidden", "csrf_rejected")


def test_api_openapi_documents_routes_examples_and_problems(
    served: ServedStore,
) -> None:
    """Agents find every route, its parameters, examples and problem answers."""
    # Act
    document = _get(served, "/openapi.json")
    docs = served.api.client.get("/api/docs")
    anonymous = served.api.client.get("/api/v1/openapi.json")

    # Assert
    operations = {
        (method, path): operation
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
    }
    assert set(operations) >= ROUTES
    schemas = document["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    ids = [operation["operationId"] for operation in operations.values()]
    assert len(ids) == len(set(ids))
    for key in ROUTES:
        responses = operations[key]["responses"]
        assert "application/problem+json" in responses["401"]["content"]
        assert "application/problem+json" in responses["403"]["content"]
        for status, response in responses.items():
            if int(status) >= 400:
                assert list(response["content"]) == ["application/problem+json"]
        ok = responses["200"]["content"]["application/json"]
        reference = ok.get("schema", {}).get("$ref")
        if reference is not None:
            assert schemas[reference.rsplit("/", 1)[1]]["examples"]
    names = {
        item["name"] for item in operations[("get", "/api/v1/slots")]["parameters"]
    }
    assert names == {
        "q", "store", "product", "country", "years", "unit", "location",
        "versions", "status", "project", "area_id", "bbox", "bbox_crs", "limit",
        "cursor",
    }  # fmt: skip
    assert docs.status_code == 200
    assert re.findall(r'src="([^"]+)"', docs.text) == [
        "/api/docs/swagger-ui-bundle.js",
        "/api/docs/archiwista-docs.js",
    ]
    assert_problem(anonymous, 401, "unauthorized", "session_required")


def test_api_agent_with_cookie_jar_sees_state(tmp_path: Path) -> None:
    """A client without Origin exchanges the printed token and reads /health."""
    with serving(local_paths(tmp_path)) as (server, printed):
        token = re.search(r"#token=(\S+)", printed)
        assert token is not None
        base = f"http://127.0.0.1:{server.port}/api/v1"
        with httpx.Client() as agent, httpx.Client() as stranger:
            # Act
            exchanged = agent.post(f"{base}/session", json={"token": token[1]})
            agent.headers[CSRF_HEADER] = exchanged.json()["csrf_token"]
            health = agent.get(f"{base}/health")
            refused = stranger.get(f"{base}/health")

    # Assert
    assert exchanged.status_code == 200
    assert health.status_code == 200 and health.json()["archiwista"]
    assert_problem(refused, 401, "unauthorized", "session_required")


def test_api_examples_validate_against_their_models() -> None:
    """Every documented example is a valid instance of its model."""
    for model in vars(models).values():
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            continue
        extra = model.model_config.get("json_schema_extra")
        examples = extra.get("examples") if isinstance(extra, dict) else None
        for example in examples if isinstance(examples, list) else []:
            model.model_validate(example)
