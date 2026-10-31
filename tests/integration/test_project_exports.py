"""A project's exports over HTTP and by commands (A-ADR-049 decision 13, plan P6).

``POST /projects/{project}/exports`` writes ``zestawy/<name>/pliki.txt`` and
``ATRYBUCJE.txt`` from the pins of the generated store's projects, scanned
into the index; ``GET …/exports`` lists them and says which are older than
the project file. ``archiwista project-export`` and ``project-exports``
print the routes' models. Writing needs ``project.write``; reading, seeing
the project. Offline.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import access_key
from archiwista.cli import main
from archiwista.config import AppPaths
from archiwista.projects import Pin, change_project_file, pin_json
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import ServedStore, served_store
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.make_store import StoreManifest
from tests.fixtures.permissions import Who, add_people, last_entry, log_entries, share
from tests.fixtures.permissions import principal as person_of

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

PROJECT = "projekt-01"
ATTRIBUTION = "Archiwista synthetic test store"
UNKNOWN_STORE_VERSION = "nmt/pl_1992_1m_evrf2007/versions/obcy/nmt.asc"


def _pin_elsewhere(store: StoreManifest) -> None:
    """Pin a version of the store ``inny-magazyn`` names (one not configured)."""
    directory = store.base / store.project("inny-magazyn").path

    def change(data: dict[str, Any]) -> None:
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

    change_project_file(directory, change)


@contextmanager
def _served(tmp_path: Path) -> Iterator[ServedStore]:
    with served_store(tmp_path, before_scan=_pin_elsewhere) as served:
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
    return served.store.base / served.store.project(name).path


def _lines(served: ServedStore, *groups: str) -> list[str]:
    """Return ``pliki.txt`` of ``projekt-01``'s groups as lines, each version once."""
    lines: list[str] = []
    for group in served.store.project(PROJECT).groups:
        if groups and group.name not in groups:
            continue
        for pin in group.pins:
            line = f"../../../../data/{pin.version}"
            if line not in lines:
                lines.append(line)
    return lines


def test_an_export_lists_the_pinned_files_and_attributions(tmp_path: Path) -> None:
    """Every group's pins in order, relative on one share; one attribution."""
    with _served(tmp_path) as served:
        since = last_entry(served.api.state)

        # Act
        written = served.owner.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "hydrograf"}
        )
        listed = served.owner.request("GET", f"/projects/{PROJECT}/exports")
        entries = log_entries(served.api.state, after=since)

    # Assert
    assert written.status_code == 201, written.text
    target = _directory(served, PROJECT) / "zestawy" / "hydrograf"
    lines = _lines(served)
    assert len(lines) == 3
    body = written.json()
    assert (body["name"], body["path"]["local"], body["files"]) == (
        "hydrograf",
        str(target),
        ["pliki.txt", "ATRYBUCJE.txt"],
    )
    assert (body["pins"], body["skipped"]) == (3, {"no_store": 0, "missing": 0})
    assert (target / "pliki.txt").read_text(encoding="utf-8") == "".join(
        f"{line}\n" for line in lines
    )
    for line in lines:
        assert (target / line).is_file()
    assert (target / "ATRYBUCJE.txt").read_bytes() == f"{ATTRIBUTION}\n".encode()
    assert listed.json() == {
        "items": [
            {
                "name": "hydrograf",
                "path": body["path"],
                "files": ["pliki.txt", "ATRYBUCJE.txt"],
                "written_at": body["written_at"],
                "changed_since": False,
            }
        ]
    }
    [entry] = [item for item in entries if item.action == "project.export"]
    assert (entry.actor, entry.target, entry.outcome, entry.details) == (
        "local",
        access_key(_directory(served, PROJECT)),
        "ok",
        {"name": "hydrograf", "pins": 3},
    )


def test_an_export_of_some_groups_is_written_again_in_place(tmp_path: Path) -> None:
    """Regenerating replaces the files; names match case-folded; unknown is `404`."""
    with _served(tmp_path) as served:
        served.owner.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "zestaw"}
        )

        # Act
        again = served.owner.request(
            "POST",
            f"/projects/{PROJECT}/exports",
            json={"name": "zestaw", "groups": ["POKRYCIE", "archiwum"]},
        )
        unknown = served.owner.request(
            "POST",
            f"/projects/{PROJECT}/exports",
            json={"name": "inny", "groups": ["brak"]},
        )
        invalid = served.owner.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": ".ukryty"}
        )

    # Assert
    assert again.status_code == 201, again.text
    target = _directory(served, PROJECT) / "zestawy"
    # The file's order of groups, whatever the request's.
    assert (target / "zestaw" / "pliki.txt").read_text(encoding="utf-8") == "".join(
        f"{line}\n" for line in _lines(served, "archiwum", "pokrycie")
    )
    assert again.json()["pins"] == 2
    assert_problem(unknown, 404, "not_found")
    assert_problem(invalid, 400, "validation_error")
    assert sorted(item.name for item in target.iterdir()) == ["zestaw"]


def test_an_export_counts_the_pins_it_leaves_out(tmp_path: Path) -> None:
    """A store not configured, a version not indexed, a file gone from the disk."""
    with _served(tmp_path) as served:
        gone = _lines(served, "archiwum")[0]
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
    target = _directory(served, PROJECT) / "zestawy" / "x"
    assert gone not in (target / "pliki.txt").read_text(encoding="utf-8")
    for name in ("inny-magazyn", "brak-wersji"):
        files = _directory(served, name) / "zestawy" / "x"
        assert (files / "pliki.txt").read_bytes() == b""
        assert (files / "ATRYBUCJE.txt").read_bytes() == b""


def test_an_export_is_older_than_a_pin_written_after_it(tmp_path: Path) -> None:
    """A pin added to the project file marks the export to be written again."""
    with _served(tmp_path) as served:
        served.owner.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "hydrograf"}
        )
        pinned = served.store.project(PROJECT).groups[0].pins[0]

        def pin(data: dict[str, Any]) -> None:
            group = next(item for item in data["groups"] if item["name"] == "archiwum")
            group["pins"].append(
                pin_json(
                    Pin(
                        producer="kartograf",
                        version=pinned.version,
                        sha256=pinned.sha256,
                        content_sha256=None,
                        size_bytes=pinned.size_bytes,
                        unit=pinned.unit,
                        label=pinned.label,
                        pinned_at=datetime(2026, 10, 31, tzinfo=UTC),
                        pinned_by="local",
                    )
                )
            )

        # Act
        before = served.owner.request("GET", f"/projects/{PROJECT}/exports").json()
        change_project_file(_directory(served, PROJECT), pin)
        after = served.owner.request("GET", f"/projects/{PROJECT}/exports").json()

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
    """Shared with listed people: they read the exports and may not write one."""
    with _served(tmp_path) as served:
        share(served.api.state, access_key(_directory(served, PROJECT)), "users")
        person = served.api.session(person_of(served.api.state, who))

        # Act
        exported = person.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "z"}
        )
        listed = person.request("GET", f"/projects/{PROJECT}/exports")

    # Assert
    codes = {403: "forbidden", 404: "not_found"}
    assert exported.status_code == written, exported.text
    assert listed.status_code == read, listed.text
    if written in codes:
        assert_problem(exported, written, codes[written])
        assert not (_directory(served, PROJECT) / "zestawy").exists()
    if read in codes:
        assert_problem(listed, read, codes[read])


def test_the_commands_print_what_the_routes_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` is the route's model; a refusal is the route's problem."""
    with _served(tmp_path) as served:
        paths = served.api.paths
        by_api = served.owner.request(
            "POST",
            f"/projects/{PROJECT}/exports",
            json={"name": "api", "groups": ["teren"]},
        ).json()

        # Act
        by_cli = _cli(
            capsys, paths, "project-export", PROJECT, "cli", "--group", "teren"
        )
        listed_cli = _cli(capsys, paths, "project-exports", PROJECT)
        listed_api = served.owner.request("GET", f"/projects/{PROJECT}/exports").json()
        unknown = _cli(capsys, paths, "project-export", PROJECT, "x", "--group", "b")
        refused = served.owner.request(
            "POST", f"/projects/{PROJECT}/exports", json={"name": "x", "groups": ["b"]}
        )
        invalid = _cli(capsys, paths, "project-export", PROJECT, ".x")

    # Assert
    target = _directory(served, PROJECT) / "zestawy"
    assert {**by_cli, "name": "api", "path": None, "written_at": None} == {
        **by_api,
        "path": None,
        "written_at": None,
    }
    assert by_cli["path"]["local"] == str(target / "cli")
    assert (target / "cli" / "pliki.txt").read_bytes() == (
        target / "api" / "pliki.txt"
    ).read_bytes()
    assert listed_cli == listed_api
    assert [item["name"] for item in listed_cli["items"]] == ["api", "cli"]
    assert_same_error(unknown, refused.json())
    assert invalid["code"] == "validation_error"


def test_openapi_documents_the_exports(tmp_path: Path) -> None:
    """Both routes, their models with examples, and the problems they answer."""
    with _served(tmp_path) as served:
        document = served.owner.request("GET", "/openapi.json").json()

    route = document["paths"]["/api/v1/projects/{project}/exports"]
    schemas = document["components"]["schemas"]
    written, listed = route["post"], route["get"]
    assert (written["operationId"], listed["operationId"]) == (
        "export_project",
        "list_project_exports",
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
    for name in ("ExportRequest", "ProjectExport", "ProjectExports"):
        assert schemas[name]["examples"]
    assert schemas["ExportRequest"]["additionalProperties"] is False
