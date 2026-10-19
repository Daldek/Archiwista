"""The metadata comparison over HTTP (plan v0.2, step 10; decision 10, level 1).

A generated store is scanned into a fresh index and served; two versions of
one NMT sheet get a campaign each and different sizes in their sidecars, so
``GET /compare`` must mark the dates, the campaign, ``sha256`` and the size
as different, list the raw sidecar's fields as flattened JSON paths, compare
versions of two slots and recognize the same content. Own-data sides
(``file:``, ``snapshot:``) and their visibility come with step 9.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from archiwista.messages import MESSAGES
from archiwista.services.compare import VERSION_FIELDS
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE, ServedStore, served_store
from tests.fixtures.make_store import ExpectedEntry, StoreManifest

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

CAMPAIGNS = ("41022", "82710")


def _sheet_history(store: StoreManifest) -> tuple[ExpectedEntry, ExpectedEntry]:
    """Return the first two versions of the first NMT sheet with a history."""
    versions = [
        entry for entry in store.by_family("asc_sheet") if entry.kind == "version"
    ]
    for first in versions:
        for second in versions:
            if (
                second.hierarchy == first.hierarchy
                and second.segment == first.segment
                and second.sha256 != first.sha256
            ):
                return first, second
    raise AssertionError("the store has no NMT sheet with two versions")


def _other_slot(store: StoreManifest, entry: ExpectedEntry) -> ExpectedEntry:
    """Return a version of another slot of the same family."""
    return next(
        other
        for other in store.by_family("asc_sheet")
        if other.kind == "version" and other.hierarchy != entry.hierarchy
    )


def _same_content(store: StoreManifest) -> tuple[ExpectedEntry, ExpectedEntry]:
    """Return two versions at different paths holding the same bytes."""
    versions = [entry for entry in store.by_kind("version") if entry.sha256]
    for first in versions:
        for second in versions:
            if first.sha256 == second.sha256 and first.path != second.path:
                return first, second
    raise AssertionError("the store has no two versions of the same content")


def _give_campaigns(store: StoreManifest) -> None:
    """Give both versions of the history a campaign; make B one byte longer."""
    for index, entry in enumerate(_sheet_history(store)):
        sidecar = store.root / f"{entry.path}.meta.json"
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        meta.setdefault("extra", {})["campaign"] = {"id": CAMPAIGNS[index]}
        meta["size_bytes"] += index
        written = sidecar.with_name(sidecar.name + ".new")
        written.write_text(json.dumps(meta), encoding="utf-8")
        written.replace(sidecar)


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServedStore]:
    """Serve the store with the campaigns written before the scan."""
    with served_store(
        tmp_path_factory.mktemp("compare"), before_scan=_give_campaigns
    ) as found:
        yield found


def _ref(entry: ExpectedEntry) -> str:
    return f"version:{STORE}:{entry.path}"


def _compare(served: ServedStore, a: str, b: str) -> Any:
    response = served.owner.request("GET", "/compare?" + urlencode({"a": a, "b": b}))
    assert response.status_code == 200, response.text
    return response.json()


def _rows(comparison: Any, group: str) -> dict[str, Any]:
    return {row["field"]: row for row in comparison["rows"] if row["group"] == group}


def test_versions_of_one_slot_mark_differences(served: ServedStore) -> None:
    """Dates, campaign, ``sha256`` and size differ; the rest is as on the card."""
    # Arrange
    first, second = _sheet_history(served.store)
    cards = [
        served.owner.request("GET", f"/stores/{STORE}/versions/{entry.path}").json()
        for entry in (first, second)
    ]

    # Act
    comparison = _compare(served, _ref(first), _ref(second))

    # Assert
    assert [comparison["a"]["ref"], comparison["b"]["ref"]] == [
        _ref(first),
        _ref(second),
    ]
    assert comparison["a"]["kind"] == "version"
    assert comparison["a"]["title"] == MESSAGES["compare_title_version"].format(
        name=Path(first.path).name, label=first.label
    )
    assert comparison["a"]["outline"] == cards[0]["footprint"]
    assert comparison["b"]["preview"] == (
        f"/api/v1/stores/{STORE}/versions/{second.path}/preview"
    )
    assert comparison["same_content"] is False
    assert comparison["schema_diff"] is None
    metadata = _rows(comparison, "metadata")
    assert list(metadata) == list(VERSION_FIELDS)
    assert metadata["campaign"]["label"] == MESSAGES["compare_field_campaign"]
    assert (metadata["campaign"]["a"], metadata["campaign"]["b"]) == CAMPAIGNS
    assert metadata["size_bytes"]["b"] == metadata["size_bytes"]["a"] + 1
    differing = ("data_date", "data_year", "label", "campaign", "sha256", "size_bytes")
    for field in differing:
        assert metadata[field]["differs"], field
    for field in ("horizontal_crs", "vertical_crs", "resolution", "license"):
        assert not metadata[field]["differs"], field
    assert metadata["sha256"]["a"] == cards[0]["version"]["sha256"]
    assert metadata["data_date"]["b"] == cards[1]["version"]["data_date"]
    assert metadata["nodata"]["a"] == cards[0]["nodata"]


def test_raw_sidecar_fields_are_flattened_paths(served: ServedStore) -> None:
    """Every leaf of both raw sidecars is a row named by its JSON path."""
    # Arrange
    first, second = _sheet_history(served.store)
    sidecars = [
        served.owner.request(
            "GET", f"/stores/{STORE}/versions/{entry.path}/sidecar"
        ).json()
        for entry in (first, second)
    ]

    # Act
    comparison = _compare(served, _ref(first), _ref(second))

    # Assert
    raw = _rows(comparison, "sidecar")
    assert raw["extra.campaign.id"]["a"] == CAMPAIGNS[0]
    assert raw["extra.campaign.id"]["label"] == "extra.campaign.id"
    assert raw["extra.campaign.id"]["differs"]
    assert raw["license.id"]["a"] == sidecars[0]["license"]["id"]
    assert raw["schema"]["a"] == raw["schema"]["b"] == sidecars[0]["schema"]
    assert not raw["schema"]["differs"]
    assert raw["sha256"]["b"] == sidecars[1]["sha256"]
    assert all("." in field or "[" in field or field in sidecars[0] for field in raw)


def test_versions_of_two_slots(served: ServedStore) -> None:
    """A version of another slot compares alike, with its own title."""
    # Arrange
    first, _ = _sheet_history(served.store)
    other = _other_slot(served.store, first)

    # Act
    comparison = _compare(served, _ref(first), _ref(other))

    # Assert
    assert comparison["b"]["title"].startswith(Path(other.path).name)
    assert comparison["a"]["title"] != comparison["b"]["title"]
    assert _rows(comparison, "metadata")["sha256"]["differs"]
    assert comparison["same_content"] is False


def test_same_content_is_recognized(served: ServedStore) -> None:
    """Two versions of the same bytes, and one version with itself, match."""
    # Arrange
    first, second = _same_content(served.store)

    # Act
    pair = _compare(served, _ref(first), _ref(second))
    itself = _compare(served, _ref(first), _ref(first))

    # Assert
    assert pair["same_content"] is True
    assert not _rows(pair, "metadata")["sha256"]["differs"]
    assert itself["same_content"] is True
    assert not any(row["differs"] for row in itself["rows"])


@pytest.mark.parametrize(
    ("a", "b", "status", "code"),
    [
        ("plik.tif", None, 422, "invalid_ref"),
        (None, "version:ZŁY:plik.tif", 422, "invalid_ref"),
        (None, "file:raba:dzialki.gpkg", 422, "invalid_ref"),
        (None, f"version:{STORE}:nie/ma.tif", 404, "not_found"),
    ],
)
def test_bad_refs_refused(
    served: ServedStore, a: str | None, b: str | None, status: int, code: str
) -> None:
    """A malformed reference, a kind not compared yet or an unknown version."""
    # Arrange
    known = _ref(_sheet_history(served.store)[0])
    query = urlencode({"a": a or known, "b": b or known})

    # Act
    response = served.owner.request("GET", f"/compare?{query}")

    # Assert
    assert_problem(response, status, code)


def test_query_and_session_rules(served: ServedStore) -> None:
    """Both sides are required, nothing else is allowed, CSRF as everywhere."""
    # Arrange
    known = _ref(_sheet_history(served.store)[0])

    # Act
    missing = served.owner.request("GET", "/compare?" + urlencode({"a": known}))
    extra = served.owner.request(
        "GET", "/compare?" + urlencode({"a": known, "b": known, "c": known})
    )
    no_csrf = served.owner.request(
        "GET", "/compare?" + urlencode({"a": known, "b": known}), csrf=False
    )
    document = served.owner.request("GET", "/openapi.json").json()

    # Assert
    assert_problem(missing, 422, "validation_error")
    assert_problem(extra, 422, "validation_error")
    assert_problem(no_csrf, 403, "csrf_rejected")
    responses = document["paths"]["/api/v1/compare"]["get"]["responses"]
    assert {"200", "404", "422"} <= set(responses)
    assert document["components"]["schemas"]["Comparison"]["examples"]
