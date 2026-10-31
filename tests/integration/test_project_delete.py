"""Deleting a project: Archiwista forgets it, its data stays (A-ADR-049 decision 16).

``DELETE /projects/{project}`` and ``archiwista project-delete PROJEKT --yes``
remove under the project's lock only what Archiwista wrote in the directory
(``archiwista-project.json``, the area files of ``obszary/``, ``eksport/``),
keep the own data (``dane/`` with ``.wersje/``) and any other file, remove
the directory when it is then empty, forget the project's access entry and
its rows of the index, log ``project.delete`` and leave the store as it was.
The owner and an administrator may, the listed person may not, another
person does not see the project; a job of the project, a file of a newer
format and a missing ``--yes`` are refused. The world is a marked Kartograf
store ``zespol`` (empty), a project directory and a supervisor that starts
no job, so a project's job waits. Offline.
"""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

import kartograf
import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter, initialize
from archiwista.jobs import JobSupervisor
from archiwista.projects import change_project_file
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import Api, assert_problem, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import (
    WHO,
    Who,
    add_people,
    last_entry,
    log_entries,
    principal,
    share,
)

STORE = "zespol"
AREA = "5f2b9c0e7d41a3b6.geojson"
VERSION = "nmt/pl_1992_1m_evrf2007/versions/N-34/2023-05-02_1_00000000/N-34.asc"
# What the owner, the listed person, another person and an administrator meet.
ANSWERS: dict[Who, tuple[int, str | None, str | None]] = {
    "owner": (204, None, None),
    "listed": (403, "forbidden", "permission_denied"),
    "other": (404, "not_found", None),
    "admin": (204, None, None),
}
INDEX_TABLES = ("projects", "project_stores", "pin_groups", "pins")


@dataclass(frozen=True)
class World:
    """A served installation with the project ``raba`` and its files."""

    api: Api
    jobs: JobSupervisor
    paths: AppPaths
    store: Path
    directory: Path
    key: str


@contextmanager
def world(tmp_path: Path) -> Iterator[World]:
    """Serve a project that pins one version, with an area, an export and own data."""
    store = tmp_path / "nas" / "kartograf"
    kartograf.init_store(store)
    projects = tmp_path / "nas" / "projekty"
    projects.mkdir()
    paths = local_paths(tmp_path)
    config = StoreConfig(id=STORE, name="Zespół", kartograf=store, kind="local")
    ConfigStore(paths.config_file).save(
        AppSettings(stores=(config,), project_dirs=(projects,))
    )
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    state = StateStore(paths.state_file)
    with (
        JobSupervisor(paths, settings, max_jobs=0, record=state.record) as jobs,
        running_api(paths, registry, jobs=jobs) as api,
    ):
        add_people(api.state)
        directory = projects / "raba"
        owner = api.session(LOCAL_OWNER)
        created = owner.request("POST", "/projects", json={"path": str(directory)})
        assert created.status_code == 201, created.text
        key = str(created.json()["project"])
        _fill(directory, store)
        changed = owner.request(
            "PUT", f"/projects/{key}/stores/kartograf", json={"store": STORE}
        )
        assert changed.status_code == 200, changed.text
        share(api.state, access_key(directory), "users")
        yield World(api, jobs, paths, store, directory, key)


def _fill(directory: Path, store: Path) -> None:
    """Give the project a pinned version, an area file, an export and own data."""

    def pin(data: dict[str, object]) -> None:
        data["groups"] = [
            {
                "name": "NMT",
                "origin": {
                    "kind": "local",
                    "selections": [{"from": "file"}],
                },
                "pins": [
                    {
                        "producer": "kartograf",
                        "version": VERSION,
                        "sha256": "0" * 64,
                        "size_bytes": 12,
                        "unit": None,
                        "label": None,
                        "pinned_at": "2026-10-31T12:00:00Z",
                        "pinned_by": "local",
                    }
                ],
            }
        ]

    change_project_file(directory, pin)
    (directory / "obszary").mkdir()
    (directory / "obszary" / AREA).write_text("{}", encoding="utf-8")
    (directory / "eksport" / "hydrograf" / "NMT").mkdir(parents=True)
    (directory / "eksport" / "hydrograf" / "README.txt").write_text("x")
    (directory / "eksport" / "hydrograf.zip").write_bytes(b"PK")
    (directory / "dane" / ".wersje" / "pomiary.csv").mkdir(parents=True)
    (directory / "dane" / "pomiary.csv").write_text("a;b\n", encoding="utf-8")
    (directory / "kartograf-project.json").write_text("{}", encoding="utf-8")


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    """Return every file below ``root`` with its size and modification time."""
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _index_rows(paths: AppPaths) -> dict[str, int]:
    """Return the number of rows of each project table of the index."""
    with closing(sqlite3.connect(paths.index_file)) as connection:
        return {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in INDEX_TABLES
        }


def test_deleting_removes_what_archiwista_wrote_and_keeps_the_data(
    tmp_path: Path,
) -> None:
    """The file, obszary/ and eksport/ go; dane/, .wersje/ and other files stay."""
    with world(tmp_path) as made:
        store_before = _tree(made.store)
        # The area a plan group's calls name (A-ADR-035 erratum 2).
        (made.directory / "obszary" / "0123456789abcdef.gpkg").write_bytes(b"GPKG")
        assert all(_index_rows(made.paths).values())
        since = last_entry(made.api.state)
        owner = made.api.session(principal(made.api.state, "owner"))

        # Act
        deleted = owner.request("DELETE", f"/projects/{made.key}")

        # Assert
        assert deleted.status_code == 204, deleted.text
        assert deleted.content == b""
        assert sorted(os.listdir(made.directory)) == ["dane", "kartograf-project.json"]
        assert (made.directory / "dane" / "pomiary.csv").read_text() == "a;b\n"
        assert (made.directory / "dane" / ".wersje" / "pomiary.csv").is_dir()
        assert _tree(made.store) == store_before
        assert _index_rows(made.paths) == dict.fromkeys(INDEX_TABLES, 0)
        assert made.api.state.project_access(access_key(made.directory)) is None
        assert owner.request("GET", f"/projects/{made.key}").status_code == 404
        entries = [
            entry
            for entry in log_entries(made.api.state, after=since)
            if entry.action == "project.delete"
        ]
        assert [(e.actor, e.target, e.outcome) for e in entries] == [
            ("olga", access_key(made.directory), "ok")
        ]
        assert entries[0].details == {
            "name": "raba",
            "path": str(made.directory),
            "kept": ["dane", "kartograf-project.json"],
        }


def test_an_emptied_directory_is_removed_and_the_activity_stays(
    tmp_path: Path,
) -> None:
    """With nothing of its own left, the directory goes; its log entries stay."""
    with world(tmp_path) as made:
        (made.directory / "kartograf-project.json").unlink()
        (made.directory / "dane" / "pomiary.csv").unlink()
        (made.directory / "dane" / ".wersje" / "pomiary.csv").rmdir()
        (made.directory / "dane" / ".wersje").rmdir()
        (made.directory / "dane").rmdir()
        target = access_key(made.directory)
        owner = made.api.session(LOCAL_OWNER)

        # Act
        deleted = owner.request("DELETE", f"/projects/{made.key}")

        # Assert
        assert deleted.status_code == 204, deleted.text
        assert not made.directory.exists()
        actions = [
            entry.action
            for entry in log_entries(made.api.state)
            if entry.target == target
        ]
        assert actions[0] == "project.create"
        assert actions[-1] == "project.delete"
        entries = log_entries(made.api.state)
        delete = [e for e in entries if e.action == "project.delete"]
        assert delete[0].details is not None
        assert delete[0].details["kept"] == []


def test_a_file_a_person_put_into_obszary_stays(tmp_path: Path) -> None:
    """Only the area files Archiwista names go; obszary/ stays with another file."""
    with world(tmp_path) as made:
        (made.directory / "obszary" / "szkic.qgz").write_bytes(b"q")

        # Act
        deleted = made.api.session(LOCAL_OWNER).request(
            "DELETE", f"/projects/{made.key}"
        )

        # Assert
        assert deleted.status_code == 204, deleted.text
        assert os.listdir(made.directory / "obszary") == ["szkic.qgz"]


@pytest.mark.parametrize("who", WHO)
def test_who_may_delete_a_project(tmp_path: Path, who: Who) -> None:
    """The owner and an administrator may, the listed person not; others see none."""
    with world(tmp_path) as made:
        person = made.api.session(principal(made.api.state, who))

        # Act
        deleted = person.request("DELETE", f"/projects/{made.key}")

        # Assert
        status, code, reason = ANSWERS[who]
        if code is None:
            assert deleted.status_code == status, deleted.text
            assert not (made.directory / "archiwista-project.json").exists()
        else:
            assert_problem(deleted, status, code, reason)
            assert (made.directory / "archiwista-project.json").is_file()
            assert (made.directory / "eksport" / "hydrograf.zip").is_file()
            assert _index_rows(made.paths)["projects"] == 1


def test_a_job_of_the_project_refuses_the_deletion(tmp_path: Path) -> None:
    """A waiting job of the project is `409 conflict` naming it; nothing goes."""
    with world(tmp_path) as made:
        job = made.jobs.submit(
            "project_verify",
            params={"project": made.key, "groups": None},
            actor=LOCAL_OWNER,
        )

        # Act
        deleted = made.api.session(LOCAL_OWNER).request(
            "DELETE", f"/projects/{made.key}"
        )

        # Assert
        assert_problem(deleted, 409, "conflict")
        assert deleted.json()["details"]["job"] == {
            "id": job.id,
            "kind": "project_verify",
            "state": "queued",
        }
        assert (made.directory / "archiwista-project.json").is_file()
        assert _index_rows(made.paths)["projects"] == 1


def test_a_file_of_a_newer_format_is_not_removed(tmp_path: Path) -> None:
    """Archiwista removes no project file it cannot read (`409`)."""
    with world(tmp_path) as made:
        path = made.directory / "archiwista-project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema"] = "archiwista-project/2"
        path.write_text(json.dumps(data), encoding="utf-8")

        # Act
        deleted = made.api.session(LOCAL_OWNER).request(
            "DELETE", f"/projects/{made.key}"
        )

        # Assert
        assert_problem(deleted, 409, "conflict", "unsupported_project_schema")
        assert path.is_file()
        assert (made.directory / "obszary" / AREA).is_file()
        assert (made.directory / "eksport" / "hydrograf.zip").is_file()


def test_the_command_needs_yes_and_then_does_what_the_route_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without `--yes` nothing goes (`validation_error`); with it, as the API does."""
    with world(tmp_path) as made:
        registry = load_registry(cache_dir=made.paths.cache_dir)
        since = last_entry(made.api.state)

        # Act
        refused = main(
            ["project-delete", made.key], registry=registry, paths=made.paths
        )
        refusal = capsys.readouterr()
        status = main(
            ["project-delete", made.key, "--yes"], registry=registry, paths=made.paths
        )
        printed = capsys.readouterr()

        # Assert
        assert refused != 0
        document = json.loads(refusal.err.strip().splitlines()[-1])
        assert document["code"] == "validation_error"
        assert document["details"] == {
            "reason": "confirmation_required",
            "option": "--yes",
        }
        assert "--yes" in refusal.err.splitlines()[0]
        assert status == 0, printed.err
        assert "dane, kartograf-project.json" in printed.out
        assert sorted(os.listdir(made.directory)) == ["dane", "kartograf-project.json"]
        assert _index_rows(made.paths) == dict.fromkeys(INDEX_TABLES, 0)
        assert made.api.state.project_access(access_key(made.directory)) is None
        entries = [
            entry
            for entry in log_entries(made.api.state, after=since)
            if entry.action == "project.delete"
        ]
        assert [(e.actor, e.details) for e in entries] == [
            (
                "local",
                {
                    "name": "raba",
                    "path": str(made.directory),
                    "kept": ["dane", "kartograf-project.json"],
                },
            )
        ]


def test_the_openapi_document_has_the_route(tmp_path: Path) -> None:
    """`DELETE /projects/{project}` answers `204` and its refusals."""
    with world(tmp_path) as made:
        document = made.api.session(LOCAL_OWNER).request("GET", "/openapi.json").json()

    operation = document["paths"]["/api/v1/projects/{project}"]["delete"]
    assert {"204", "403", "404", "409", "500"} <= set(operation["responses"])
    assert "content" not in operation["responses"]["204"]
