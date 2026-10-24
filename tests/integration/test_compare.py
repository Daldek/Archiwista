"""The metadata comparison (plan v0.2, steps 9 and 10; decision 10, level 1).

A generated store is scanned into a fresh index and served; two versions of
one NMT sheet get a campaign each and different sizes in their sidecars, so
``GET /compare`` must mark the dates, the campaign, ``sha256`` and the size
as different, list the raw sidecar's fields as flattened JSON paths, compare
versions of two slots and recognize the same content. Own data: a project's
GeoPackage and GeoTIFF are snapshotted, then the GeoPackage is edited (an
object more, a field added, one removed, one retyped, a new layer) and
scanned again, so its snapshot and working file differ in object counts per
layer, extent, content and schema, while the untouched GeoTIFF's snapshot
holds the working file's content; a project the caller does not see is not
found.
"""

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import pyogrio
import pytest
import shapely

from archiwista.auth import ALL_PROJECTS, ProjectVisibility
from archiwista.config import AppPaths, AppSettings
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries, IndexWriter, ManifestStamp, own_file_id
from archiwista.messages import MESSAGES
from archiwista.owndata.document import SnapshotAuthor
from archiwista.owndata.reader import OwnReader
from archiwista.owndata.scan import check_own_folder, folder_rules, scan_own_data
from archiwista.owndata.snapshots import make_snapshot
from archiwista.sandbox import process_work_dir
from archiwista.services.compare import OWN_FIELDS, VERSION_FIELDS, compare
from archiwista.sources import ProjectInfo
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE, ServedStore, served_store
from tests.fixtures.make_store import ExpectedEntry, StoreManifest
from tests.fixtures.own_data import make_own_folder

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
    ("a", "b", "status", "code", "reason"),
    [
        ("plik.tif", None, 400, "validation_error", "invalid_ref"),
        (None, "version:ZŁY:plik.tif", 400, "validation_error", "invalid_ref"),
        (None, "file:raba:dzialki.gpkg", 404, "not_found", None),
        (None, f"version:{STORE}:nie/ma.tif", 404, "not_found", None),
    ],
)
def test_bad_refs_refused(
    served: ServedStore,
    a: str | None,
    b: str | None,
    status: int,
    code: str,
    reason: str | None,
) -> None:
    """A malformed reference, an unknown version or an unknown project."""
    # Arrange
    known = _ref(_sheet_history(served.store)[0])
    query = urlencode({"a": a or known, "b": b or known})

    # Act
    response = served.owner.request("GET", f"/compare?{query}")

    # Assert
    assert_problem(response, status, code, reason)


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
    assert_problem(missing, 400, "validation_error")
    assert_problem(extra, 400, "validation_error")
    assert_problem(no_csrf, 403, "forbidden", "csrf_rejected")
    responses = document["paths"]["/api/v1/compare"]["get"]["responses"]
    assert {"200", "404", "400"} <= set(responses)
    assert document["components"]["schemas"]["Comparison"]["examples"]


GPKG = "kanalizacja.gpkg"
TIF = "nmt.tif"
NOTE = "przed przebudową"


@dataclass(frozen=True)
class OwnData:
    """A project's data folder after its snapshots and the GeoPackage's edit."""

    queries: IndexQueries
    project: str
    labels: dict[str, str]
    """Label of the snapshot of each file, by path."""

    def file(self, path: str) -> str:
        """Return the ``ref`` of a working file."""
        return f"file:{self.project}:{path}"

    def snapshot(self, path: str) -> str:
        """Return the ``ref`` of a file's snapshot."""
        return f"snapshot:{self.project}:{self.labels[path]}:{path}"


def _edit_gpkg(path: Path) -> None:
    """Change the GeoPackage like a person in QGIS (through GDAL).

    ``przewody`` gets the field ``rok``, loses ``material`` and one object
    more reaching past the old extent; ``zlewnie.nazwa`` becomes a number;
    the new layer ``studnie`` has two points.
    """
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE przewody ADD COLUMN rok INTEGER")
        connection.execute("ALTER TABLE przewody DROP COLUMN material")
        connection.execute("ALTER TABLE zlewnie DROP COLUMN nazwa")
        connection.execute("ALTER TABLE zlewnie ADD COLUMN nazwa INTEGER")
    connection.close()
    pipe = shapely.LineString([(569_000.0, 245_000.0), (571_000.0, 247_500.0)])
    wells = [shapely.Point(567_000.0, 242_000.0), shapely.Point(568_000.0, 243_000.0)]
    for layer, geometries, fields in (
        ("przewody", [pipe], {"srednica_mm": [100], "rok": [2026]}),
        ("studnie", wells, {"numer": [1, 2]}),
    ):
        pyogrio.raw.write(
            path,
            np.array([shapely.to_wkb(item) for item in geometries], dtype=object),
            [np.array(values, dtype=np.int32) for values in fields.values()],
            list(fields),
            layer=layer,
            driver="GPKG",
            geometry_type=geometries[0].geom_type,
            crs="EPSG:2180",
            append=layer == "przewody",
        )


@pytest.fixture(scope="module")
def own(tmp_path_factory: pytest.TempPathFactory) -> Iterator[OwnData]:
    """Index a project, snapshot its files, edit the GeoPackage, scan again."""
    root = tmp_path_factory.mktemp("compare_own")
    paths = AppPaths(
        config_file=root / "config" / "config.toml", data_dir=root / "data"
    )
    registry = load_registry(cache_dir=paths.cache_dir)
    transformer = registry.adapter("kartograf").transformer  # type: ignore[attr-defined]
    settings = AppSettings()
    place = root / "projekty" / "raba"
    place.mkdir(parents=True)
    folder = make_own_folder(place / "dane", families=("gpkg_layers", "tif_2180"))
    with (
        IndexWriter(paths.index_file) as writer,
        IndexQueries(paths.index_file) as queries,
        OwnReader(paths) as reader,
    ):
        key = writer.write_project(
            ProjectInfo("kartograf", str(root / "magazyn"), place, "Raba"),
            store=None,
            stamp=ManifestStamp(None, None),
        )

        def scan() -> None:
            known = queries.projects(visible=ALL_PROJECTS)
            scan_own_data(
                writer,
                known,
                known_projects=known,
                settings=settings,
                paths=paths,
                transformer=transformer,
                reader=reader,
            )

        scan()
        known = queries.projects(visible=ALL_PROJECTS)
        stores, folders = folder_rules(settings, known)
        access = known[0].access_key
        checked = check_own_folder(
            settings,
            access,
            stores=stores,
            app_data=paths.data_dir,
            others=[path for name, path in folders.items() if name != access],
        )
        labels = {}
        for path in (GPKG, TIF):
            detail = queries.own_file(key, own_file_id(path), visible=ALL_PROJECTS)
            assert detail is not None, path
            made = make_snapshot(
                checked,
                detail,
                author=SnapshotAuthor(
                    id="local", kind="local_owner", name=None, session=None
                ),
                note=NOTE,
                work_dir=process_work_dir(paths),
                reader=reader,
                transformer=transformer,
            )
            labels[path] = made.label
        _edit_gpkg(folder.root / GPKG)
        scan()
        yield OwnData(queries, key, labels)


def _own_rows(comparison: Any, group: str) -> dict[str, Any]:
    rows = json.loads(comparison.model_dump_json())["rows"]
    return {row["field"]: row for row in rows if row["group"] == group}


def test_snapshot_against_edited_working_file(own: OwnData) -> None:
    """Objects per layer, extent, content and schema differ; the CRS does not."""
    # Arrange
    card = own.queries.own_file(own.project, own_file_id(GPKG), visible=ALL_PROJECTS)
    assert card is not None
    label = own.labels[GPKG]
    base = f"/api/v1/projects/{own.project}/files/{own_file_id(GPKG)}"

    # Act
    forward = compare(
        own.queries, own.snapshot(GPKG), own.file(GPKG), visible=ALL_PROJECTS
    )
    backward = compare(
        own.queries, own.file(GPKG), own.snapshot(GPKG), visible=ALL_PROJECTS
    )

    # Assert
    assert (forward.a.kind, forward.b.kind) == ("snapshot", "file")
    assert forward.a.title == f"{GPKG} — {label}"
    assert forward.b.title == f"{GPKG} — {MESSAGES['compare_title_working']}"
    assert forward.a.preview == f"{base}/snapshots/{label}/preview"
    assert forward.b.preview == f"{base}/preview"
    assert forward.a.outline is not None
    assert forward.b.outline == card.wgs84
    assert forward.same_content is False
    assert [row.group for row in forward.rows] == ["own"] * len(OWN_FIELDS) + [
        "layers"
    ] * 3
    layers = _own_rows(forward, "layers")
    assert {name: (row["a"], row["b"]) for name, row in layers.items()} == {
        "przewody": (3, 4),
        "zlewnie": (2, 2),
        "studnie": (None, 2),
    }
    assert [row["differs"] for row in layers.values()] == [True, False, True]
    assert layers["przewody"]["label"] == MESSAGES["compare_layer_features"].format(
        layer="przewody"
    )
    fields = _own_rows(forward, "own")
    assert list(fields) == list(OWN_FIELDS)
    assert (fields["feature_count"]["a"], fields["feature_count"]["b"]) == (5, 8)
    assert fields["crs"]["a"] == fields["crs"]["b"] == "EPSG:2180"
    assert not fields["crs"]["differs"]
    assert fields["extent"]["differs"]
    assert fields["extent"]["b"].endswith("571000.0, 247500.0")
    assert fields["content_method"]["a"] == fields["content_method"]["b"] == "sqlite"
    assert fields["content_sha256"]["differs"]
    assert fields["content_sha256"]["b"] == card.content_sha256
    assert (fields["note"]["a"], fields["note"]["b"]) == (NOTE, None)
    assert (fields["author"]["a"], fields["author"]["b"]) == ("local", None)
    assert fields["created_at"]["a"] is not None and fields["created_at"]["b"] is None
    assert fields["changed_at"]["a"] is None and fields["changed_at"]["b"] is not None
    assert forward.schema_diff is not None
    diff = forward.schema_diff.model_dump()
    assert (diff["layers_only_a"], diff["layers_only_b"]) == ([], ["studnie"])
    przewody, zlewnie = diff["layers"]
    assert przewody == {
        "name": "przewody",
        "feature_count_a": 3,
        "feature_count_b": 4,
        "fields_added": [{"name": "rok", "type": przewody["fields_added"][0]["type"]}],
        "fields_removed": [{"name": "material", "type": "String"}],
        "fields_changed": [],
    }
    assert przewody["fields_added"][0]["type"].startswith("Integer")
    assert zlewnie["name"] == "zlewnie"
    assert (zlewnie["fields_added"], zlewnie["fields_removed"]) == ([], [])
    assert [(f["name"], f["type_a"]) for f in zlewnie["fields_changed"]] == [
        ("nazwa", "String")
    ]
    assert zlewnie["fields_changed"][0]["type_b"].startswith("Integer")
    assert backward.schema_diff is not None
    assert backward.schema_diff.layers_only_a == ["studnie"]
    assert [f.name for f in backward.schema_diff.layers[0].fields_added] == ["material"]
    assert [f.name for f in backward.schema_diff.layers[0].fields_removed] == ["rok"]


def test_snapshot_of_unchanged_file_has_same_content(own: OwnData) -> None:
    """An untouched raster's snapshot holds its content; it has no schema."""
    # Act
    pair = compare(own.queries, own.snapshot(TIF), own.file(TIF), visible=ALL_PROJECTS)
    itself = compare(
        own.queries, own.snapshot(TIF), own.snapshot(TIF), visible=ALL_PROJECTS
    )

    # Assert
    assert pair.same_content is True
    assert pair.schema_diff is None
    fields = _own_rows(pair, "own")
    for name in ("crs", "extent", "content_method", "content_sha256", "size_bytes"):
        assert not fields[name]["differs"], name
    assert fields["content_method"]["a"] == "bytes"
    assert _own_rows(pair, "layers") == {}
    assert itself.same_content is True
    assert not any(row.differs for row in itself.rows)


def test_own_data_not_found(own: OwnData) -> None:
    """An invisible project, an unknown file or label: ``404`` (NotFoundError)."""
    # Arrange
    unknown_label = f"snapshot:{own.project}:2000-01-01_00000000:{GPKG}"
    cases = [
        (
            own.file(GPKG),
            ProjectVisibility(),
            MESSAGES["project_not_found"].format(project=own.project),
        ),
        (
            own.snapshot(GPKG),
            ProjectVisibility(),
            MESSAGES["project_not_found"].format(project=own.project),
        ),
        (
            own.file("brak.gpkg"),
            ALL_PROJECTS,
            MESSAGES["compare_file_not_found"].format(
                project=own.project, path="brak.gpkg"
            ),
        ),
        (
            unknown_label,
            ALL_PROJECTS,
            MESSAGES["compare_snapshot_not_found"].format(
                project=own.project, path=GPKG, label="2000-01-01_00000000"
            ),
        ),
    ]

    for ref, visible, message in cases:
        # Act
        with pytest.raises(NotFoundError) as caught:
            compare(own.queries, ref, own.file(TIF), visible=visible)

        # Assert
        assert str(caught.value) == message, ref
