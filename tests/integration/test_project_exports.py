"""A project's exports over HTTP and by commands (A-ADR-049 decision 13, erratum 1).

``POST /projects/{project}/exports`` copies the pinned versions of the
generated store's projects, scanned into the index, into flat category
folders of ``eksport/<name>/`` with ``README.txt``, and with ``zip`` into
``eksport/<name>.zip``; ``GET …/exports`` lists them and says which are older
than the project file, ``GET …/exports/{name}/zip`` sends the ZIP.
``archiwista project-export`` and ``project-exports`` print the routes'
models. Writing needs ``project.write``; reading, seeing the project.
Offline.
"""

import json
import os
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import access_key
from archiwista.cli import main
from archiwista.config import AppPaths
from archiwista.projects import PROJECT_FILE, Pin, change_project_file, pin_json
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import ServedStore, served_store
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.make_store import ExpectedEntry, StoreManifest
from tests.fixtures.permissions import Who, add_people, last_entry, log_entries, share
from tests.fixtures.permissions import principal as person_of

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

PROJECT = "projekt-01"
YEARS = "porownanie"
SHEET = "M-34-79-D-c-2-3"
ATTRIBUTION = "Archiwista synthetic test store"
UNKNOWN_STORE_VERSION = "nmt/pl_1992_1m_evrf2007/versions/obcy/nmt.asc"
README = "README.txt"


def _versions(store: StoreManifest, unit: str) -> list[ExpectedEntry]:
    """Return the regular versions of a slot, oldest first."""
    return [
        entry
        for entry in store.by_kind("version")
        if entry.case == "regular" and entry.unit == unit
    ]


def _years(store: StoreManifest) -> dict[str, ExpectedEntry]:
    """Return the versions the project ``porownanie`` pins, by role."""
    old, new = _versions(store, SHEET)[:2]
    [orto] = _versions(store, "N-34-82-A-b-4-3")[-1:]
    gpkg = next(
        entry
        for entry in store.by_kind("version")
        if entry.path.endswith("/0411.gpkg") and entry.label == "2025"
    )
    return {"old": old, "new": new, "orto": orto, "gpkg": gpkg}


def _pin(entry: ExpectedEntry) -> dict[str, Any]:
    assert entry.sha256 is not None and entry.size_bytes is not None
    return pin_json(
        Pin(
            producer="kartograf",
            version=entry.path,
            sha256=entry.sha256,
            content_sha256=None,
            size_bytes=entry.size_bytes,
            unit=entry.unit,
            label=entry.label,
            pinned_at=datetime(2026, 10, 31, tzinfo=UTC),
            pinned_by="local",
        )
    )


def _prepare(store: StoreManifest) -> None:
    """Pin a store not configured; add the two-year project and a `.prj`."""
    directory = store.base / store.project("inny-magazyn").path

    def elsewhere(data: dict[str, Any]) -> None:
        pin = Pin(
            producer="kartograf",
            version=UNKNOWN_STORE_VERSION,
            sha256="a" * 64,
            content_sha256=None,
            size_bytes=10,
            unit=None,
            label=None,
            pinned_at=datetime(2026, 10, 1, tzinfo=UTC),
            pinned_by="local",
        )
        data["groups"][0]["pins"].append(pin_json(pin))

    change_project_file(directory, elsewhere)
    pinned = _years(store)
    (store.root / pinned["new"].path).with_suffix(".prj").write_bytes(b"PROJCS")
    data = json.loads(
        (store.base / store.project(PROJECT).path / PROJECT_FILE).read_text("utf-8")
    )
    local = {"kind": "local", "selections": [{"from": "file"}]}
    data |= {
        "name": "Porównanie",
        "groups": [
            {
                "name": "2024",
                "origin": local,
                "pins": [_pin(pinned[key]) for key in ("new", "orto", "gpkg")],
            },
            {
                "name": "2014",
                "origin": local,
                "pins": [_pin(pinned[key]) for key in ("old", "gpkg")],
            },
        ],
    }
    target = store.projects_dir / YEARS
    target.mkdir()
    (target / PROJECT_FILE).write_text(json.dumps(data), encoding="utf-8")


@contextmanager
def _served(tmp_path: Path) -> Iterator[ServedStore]:
    with served_store(tmp_path, before_scan=_prepare) as served:
        add_people(served.api.state)
        yield served


def _cli(capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str) -> Any:
    """Run ``archiwista … --json``; a refusal gives its error document."""
    capsys.readouterr()
    registry = load_registry(cache_dir=paths.cache_dir)
    status = main([*argv, "--json"], registry=registry, paths=paths)
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def _directory(served: ServedStore, name: str) -> Path:
    if name == YEARS:
        return served.store.projects_dir / YEARS
    return served.store.base / served.store.project(name).path


def _tree(path: Path) -> list[str]:
    """Return every file below ``path``, relative, sorted."""
    return sorted(
        file.relative_to(path).as_posix() for file in path.rglob("*") if file.is_file()
    )


def test_an_export_copies_two_sets_into_flat_folders(tmp_path: Path) -> None:
    """Copies by category, one sheet of two years told apart, README and ZIP."""
    with _served(tmp_path) as served:
        since = last_entry(served.api.state)
        pinned = _years(served.store)

        # Act
        written = served.owner.request(
            "POST", f"/projects/{YEARS}/exports", json={"name": "raba", "zip": True}
        )
        listed = served.owner.request("GET", f"/projects/{YEARS}/exports")
        archive = served.owner.request("GET", f"/projects/{YEARS}/exports/raba/zip")
        entries = log_entries(served.api.state, after=since)

    # Assert
    assert written.status_code == 201, written.text
    target = _directory(served, YEARS) / "eksport" / "raba"
    old, new = (f"NMT/{SHEET}_{pinned[key].label}" for key in ("old", "new"))
    files = [
        "BDOT/0411.gpkg",
        f"{old}.asc",
        f"{new}.asc",
        f"{new}.prj",
        "ORTO/N-34-82-A-b-4-3.tif",
        README,
    ]
    body = written.json()
    assert (body["name"], body["path"]["local"], body["files"]) == (
        "raba",
        str(target),
        files,
    )
    assert (body["pins"], body["skipped"], body["zip"]) == (
        4,
        {"no_store": 0, "missing": 0},
        True,
    )
    assert _tree(target) == sorted(files)
    copies = {f"{old}.asc": "old", f"{new}.asc": "new", "BDOT/0411.gpkg": "gpkg"}
    copies["ORTO/N-34-82-A-b-4-3.tif"] = "orto"
    for name, key in copies.items():
        source = served.store.root / pinned[key].path
        assert (target / name).read_bytes() == source.read_bytes()
        assert os.stat(target / name).st_ino != os.stat(source).st_ino
    assert (target / f"{new}.prj").read_bytes() == b"PROJCS"
    readme = (target / README).read_text(encoding="utf-8")
    assert "BDOT/0411.gpkg\n  produkt: bdot10k" in readme
    assert "  zestaw: 2024, 2014\n" in readme
    assert f"  suma SHA-256: {pinned['old'].sha256}\n" in readme
    assert readme.endswith(f"\nŹródła danych\n- {ATTRIBUTION}\n")
    zip_path = target.parent / "raba.zip"
    assert zipfile.ZipFile(zip_path).namelist() == files
    assert archive.status_code == 200, archive.text
    assert archive.headers["content-type"] == "application/zip"
    assert archive.headers["content-disposition"].startswith("attachment")
    assert archive.content == zip_path.read_bytes()
    assert (
        zipfile.ZipFile(BytesIO(archive.content)).read(README)
        == (target / README).read_bytes()
    )
    assert listed.json() == {
        "items": [
            {
                "name": "raba",
                "path": body["path"],
                "files": files,
                "zip": True,
                "written_at": body["written_at"],
                "changed_since": False,
            }
        ]
    }
    [entry] = [item for item in entries if item.action == "project.export"]
    assert (entry.actor, entry.target, entry.outcome, entry.details) == (
        "local",
        access_key(_directory(served, YEARS)),
        "ok",
        {"name": "raba", "pins": 4},
    )


def test_the_zip_goes_to_a_link_of_the_interface_without_the_csrf_header(
    tmp_path: Path,
) -> None:
    """„Pobierz ZIP” is a plain link: the cookie and ``Sec-Fetch-Site`` only."""
    with _served(tmp_path) as served:
        served.owner.request(
            "POST", f"/projects/{YEARS}/exports", json={"name": "raba", "zip": True}
        )
        url = f"/api/v1/projects/{YEARS}/exports/raba/zip"
        cookie = f"{served.owner.cookie}={served.owner.session_id}"

        # Act
        sites = {
            site: served.owner.client.get(
                url, headers={"cookie": cookie, "sec-fetch-site": site}
            )
            for site in ("same-origin", "none", "same-site", "cross-site")
        }
        bare = served.owner.client.get(url, headers={"cookie": cookie})
        listed = served.owner.client.get(
            f"/api/v1/projects/{YEARS}/exports",
            headers={"cookie": cookie, "sec-fetch-site": "same-origin"},
        )

    # Assert
    zip_path = _directory(served, YEARS) / "eksport" / "raba.zip"
    for site in ("same-origin", "none"):
        assert sites[site].status_code == 200, sites[site].text
        assert sites[site].content == zip_path.read_bytes()
    for answer in (sites["same-site"], sites["cross-site"], bare, listed):
        assert_problem(answer, 403, "forbidden", "csrf_rejected")


def test_an_export_of_one_set_replaces_the_export_and_its_zip(tmp_path: Path) -> None:
    """Written again: the old files and ZIP go; names match case-folded."""
    with _served(tmp_path) as served:
        served.owner.request(
            "POST", f"/projects/{YEARS}/exports", json={"name": "raba", "zip": True}
        )

        # Act
        again = served.owner.request(
            "POST",
            f"/projects/{YEARS}/exports",
            json={"name": "raba", "groups": ["2014"]},
        )
        archive = served.owner.request("GET", f"/projects/{YEARS}/exports/raba/zip")
        unknown = served.owner.request(
            "POST",
            f"/projects/{YEARS}/exports",
            json={"name": "inny", "groups": ["brak"]},
        )
        invalid = served.owner.request(
            "POST", f"/projects/{YEARS}/exports", json={"name": ".ukryty"}
        )

    # Assert
    assert again.status_code == 201, again.text
    base = _directory(served, YEARS) / "eksport"
    files = ["BDOT/0411.gpkg", f"NMT/{SHEET}.asc", README]
    assert (again.json()["files"], again.json()["pins"]) == (files, 2)
    assert again.json()["zip"] is False
    assert _tree(base) == sorted(f"raba/{file}" for file in files)
    assert_problem(archive, 404, "not_found")
    assert_problem(unknown, 404, "not_found")
    assert_problem(invalid, 400, "validation_error")


def test_an_export_counts_the_pins_it_leaves_out(tmp_path: Path) -> None:
    """A store not configured, a version not indexed, a file gone from the disk."""
    with _served(tmp_path) as served:
        archived = served.store.project(PROJECT).groups[1].pins[0].version
        (served.store.root / archived).unlink()

        # Act
        elsewhere = served.owner.request(
            "POST", "/projects/inny-magazyn/exports", json={"name": "x"}
        )
        missing = served.owner.request(
            "POST", "/projects/brak-wersji/exports", json={"name": "x"}
        )
        deleted = served.owner.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "x"}
        )

    # Assert
    assert (elsewhere.json()["pins"], elsewhere.json()["skipped"]) == (
        0,
        {"no_store": 1, "missing": 0},
    )
    assert (missing.json()["pins"], missing.json()["skipped"]) == (
        0,
        {"no_store": 0, "missing": 1},
    )
    assert (deleted.json()["pins"], deleted.json()["skipped"]) == (
        2,
        {"no_store": 0, "missing": 1},
    )
    # The remaining sheet is alone in its folder: no label is added.
    assert deleted.json()["files"] == ["BDOT/0411.gpkg", f"NMT/{SHEET}.asc", README]
    for name in ("inny-magazyn", "brak-wersji"):
        assert _tree(_directory(served, name) / "eksport" / "x") == [README]


def test_an_export_is_older_than_a_pin_written_after_it(tmp_path: Path) -> None:
    """A pin added to the project file marks the export to be written again."""
    with _served(tmp_path) as served:
        served.owner.request("POST", f"/projects/{YEARS}/exports", json={"name": "a"})
        pinned = _years(served.store)

        def pin(data: dict[str, Any]) -> None:
            data["groups"][1]["pins"].append(_pin(pinned["orto"]))

        # Act
        before = served.owner.request("GET", f"/projects/{YEARS}/exports").json()
        change_project_file(_directory(served, YEARS), pin)
        after = served.owner.request("GET", f"/projects/{YEARS}/exports").json()

    # Assert
    assert [item["changed_since"] for item in before["items"]] == [False]
    assert [item["changed_since"] for item in after["items"]] == [True]


@pytest.mark.parametrize(
    ("who", "written", "read"),
    [
        ("owner", 201, 200),
        ("admin", 201, 200),
        ("listed", 403, 200),
        ("other", 404, 404),
    ],
)
def test_an_export_is_written_by_whoever_changes_the_project(
    tmp_path: Path, who: Who, written: int, read: int
) -> None:
    """Shared with listed people: they read the exports and ZIP, may not write one."""
    with _served(tmp_path) as served:
        share(served.api.state, access_key(_directory(served, PROJECT)), "users")
        served.owner.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "z", "zip": True}
        )
        person = served.api.session(person_of(served.api.state, who))

        # Act
        exported = person.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "y"}
        )
        listed = person.request("GET", f"/projects/{PROJECT}/exports")
        archive = person.request("GET", f"/projects/{PROJECT}/exports/z/zip")

    # Assert
    codes = {403: "forbidden", 404: "not_found"}
    assert exported.status_code == written, exported.text
    assert listed.status_code == read, listed.text
    assert archive.status_code == read, archive.text
    if written in codes:
        assert_problem(exported, written, codes[written])
        assert not (_directory(served, PROJECT) / "eksport" / "y").exists()
    if read in codes:
        assert_problem(listed, read, codes[read])
        assert_problem(archive, read, codes[read])


def test_the_commands_print_what_the_routes_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` is the route's model; a refusal is the route's problem."""
    with _served(tmp_path) as served:
        paths = served.api.paths
        by_api = served.owner.request(
            "POST",
            f"/projects/{YEARS}/exports",
            json={"name": "api", "groups": ["2024"], "zip": True},
        ).json()

        # Act
        by_cli = _cli(
            capsys, paths, "project-export", YEARS, "cli", "--group", "2024", "--zip"
        )
        listed_cli = _cli(capsys, paths, "project-exports", YEARS)
        listed_api = served.owner.request("GET", f"/projects/{YEARS}/exports").json()
        unknown = _cli(capsys, paths, "project-export", YEARS, "x", "--group", "b")
        refused = served.owner.request(
            "POST", f"/projects/{YEARS}/exports", json={"name": "x", "groups": ["b"]}
        )
        invalid = _cli(capsys, paths, "project-export", YEARS, ".x")

    # Assert
    target = _directory(served, YEARS) / "eksport"
    assert {**by_cli, "name": "api", "path": None, "written_at": None} == {
        **by_api,
        "path": None,
        "written_at": None,
    }
    assert by_cli["path"]["local"] == str(target / "cli")
    assert zipfile.ZipFile(target / "cli.zip").namelist() == by_api["files"]
    assert listed_cli == listed_api
    assert [item["name"] for item in listed_cli["items"]] == ["api", "cli"]
    assert_same_error(unknown, refused.json())
    assert invalid["code"] == "validation_error"


def test_openapi_documents_the_exports(tmp_path: Path) -> None:
    """The routes, their models with examples, and the problems they answer."""
    with _served(tmp_path) as served:
        document = served.owner.request("GET", "/openapi.json").json()

    route = document["paths"]["/api/v1/projects/{project}/exports"]
    archive = document["paths"]["/api/v1/projects/{project}/exports/{name}/zip"]["get"]
    schemas = document["components"]["schemas"]
    written, listed = route["post"], route["get"]
    assert (written["operationId"], listed["operationId"], archive["operationId"]) == (
        "export_project",
        "list_project_exports",
        "get_project_export_zip",
    )
    assert written["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProjectExport"
    }
    assert {status for status in written["responses"] if int(status) >= 400} >= {
        "400",
        "403",
        "404",
        "409",
        "500",
    }
    assert listed["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProjectExports"
    }
    assert "application/zip" in archive["responses"]["200"]["content"]
    assert {"403", "404"} <= set(archive["responses"])
    for name in ("ExportRequest", "ProjectExport", "ProjectExports"):
        assert schemas[name]["examples"]
    assert schemas["ExportRequest"]["additionalProperties"] is False
