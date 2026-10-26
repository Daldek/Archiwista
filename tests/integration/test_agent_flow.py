"""An AI agent over real HTTP, as the agent guide describes it (step 12).

The agent takes a one-time token from ``archiwista token --json``, opens a
session with a cookie jar and no ``Origin``, pages the catalog with cursors,
starts a scan with the CSRF header and follows it over SSE, and meets the
documented problems. It also snapshots a project's own file: the plan, the
``snapshot`` job over SSE and the file's card (plan v0.2, step 9).
"""

import io
import json
import ssl
from pathlib import Path
from typing import Any

import httpx
import pytest

from archiwista.auth import LOCAL_OWNER, passwords
from archiwista.cli import main
from archiwista.config import ConfigStore
from archiwista.jobs.reindex import reindex_main
from archiwista.security import CSRF_HEADER
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import STORE, store_settings
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.make_store import make_store
from tests.fixtures.own_data import make_own_folder
from tests.fixtures.own_data_api import DATA_DIR, FIRST, scan_own
from tests.fixtures.preview_api import scanned_store
from tests.fixtures.team_server import (
    ADMIN_ACCOUNT,
    ADMIN_PASSWORD,
    cheap_hasher,
    team_serving,
    team_site,
)

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
KRAKOW = "19.9,50.0,20.0,50.05"


def _rows(pages: list[Any]) -> list[tuple[str, str | None]]:
    return [
        (row["slot"], (row["version"] or {}).get("path"))
        for page in pages
        for row in page
    ]


def _events(agent: httpx.Client, job: str) -> list[tuple[str, dict[str, Any]]]:
    """Read a job's SSE stream to its end: ``(event, data)`` frames."""
    events: list[tuple[str, dict[str, Any]]] = []
    kind = ""
    with agent.stream("GET", f"/jobs/{job}/events") as stream:
        assert stream.status_code == 200
        for line in stream.iter_lines():
            if line.startswith("event:"):
                kind = line.partition(":")[2].strip()
            elif line.startswith("data:"):
                events.append((kind, json.loads(line.partition(":")[2])))
    return events


def test_agent_session_paging_and_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Token, session, cursor pages, CSRF scan with SSE, documented problems."""
    # Arrange: a scanned store served without producer plugins.
    store = make_store(tmp_path / "store", slots=24, seed=7)
    paths = local_paths(tmp_path)
    ConfigStore(paths.config_file).save(store_settings(store))
    registry = load_registry(cache_dir=paths.cache_dir)
    assert reindex_main(paths, registry, io.StringIO(), io.StringIO()) == 0
    with serving(paths) as (server, _):
        capsys.readouterr()
        assert main(["token", "--port", str(server.port), "--json"], paths=paths) == 0
        issued = json.loads(capsys.readouterr().out)
        base = f"http://127.0.0.1:{server.port}/api/v1"
        with httpx.Client(base_url=base, timeout=None) as agent:
            # Act
            session = agent.post("/session", json={"token": issued["token"]})
            reused = agent.post("/session", json={"token": issued["token"]})
            unchecked_read = agent.get("/health")
            agent.headers[CSRF_HEADER] = session.json()["csrf_token"]
            pages: list[Any] = []
            cursor: dict[str, str] = {}
            while True:
                query = {"versions": "all", "limit": "7", **cursor}
                pages.append(agent.get("/slots", params=query).json())
                if pages[-1]["next_cursor"] is None:
                    break
                cursor = {"cursor": pages[-1]["next_cursor"]}
            whole = agent.get("/slots", params={"versions": "all", "limit": "200"})
            foreign = agent.get(
                "/slots", params={"product": "nmt", "cursor": pages[0]["next_cursor"]}
            )
            unchecked = agent.post(
                f"/stores/{STORE}/scan", headers={CSRF_HEADER: "wrong"}
            )
            scan = agent.post(f"/stores/{STORE}/scan")
            events = _events(agent, scan.json()["id"])
            job = agent.get(f"/jobs/{scan.json()['id']}").json()
            no_plugin = agent.get("/slots", params={"bbox": KRAKOW})

    # Assert
    assert issued["url"] == f"http://127.0.0.1:{server.port}/#token={issued['token']}"
    assert session.status_code == 200 and session.json()["actor"] == "local"
    assert_problem(reused, 401, "unauthorized", "session_required")
    assert len(pages) > 1
    assert _rows([page["items"] for page in pages]) == _rows([whole.json()["items"]])
    assert_problem(foreign, 400, "validation_error")
    assert_problem(unchecked, 403, "forbidden", "csrf_rejected")
    # The session cookie alone reads nothing either.
    assert_problem(unchecked_read, 403, "forbidden", "csrf_rejected")
    assert scan.status_code == 202, scan.text
    assert scan.headers["location"] == f"/api/v1/jobs/{scan.json()['id']}"
    assert scan.json()["actor"] == "local"
    assert events[-1][0] == "state" and events[-1][1]["state"] == job["state"]
    assert job["state"] == "succeeded" and job["error"] is None
    assert_problem(no_plugin, 503, "missing_dependency", "source_unavailable")
    assert no_plugin.json()["details"]["source"]["id"] == "kartograf"


def test_agent_snapshot_flow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Token, session, snapshot plan, snapshot job followed over SSE, the card."""
    # Arrange: a project with a scanned data folder, served with jobs and previews.
    store, paths = scanned_store(tmp_path)
    project_dir = store.base / store.project(FIRST).path
    folder = make_own_folder(project_dir / DATA_DIR, families=("tif_2180",))
    scan_own(paths)
    registry = load_registry(cache_dir=paths.cache_dir)
    with serving(paths, registry=registry) as (server, _):
        capsys.readouterr()
        assert main(["token", "--port", str(server.port), "--json"], paths=paths) == 0
        issued = json.loads(capsys.readouterr().out)
        base = f"http://127.0.0.1:{server.port}/api/v1"
        with httpx.Client(base_url=base, timeout=None) as agent:
            # Act
            session = agent.post("/session", json={"token": issued["token"]})
            agent.headers[CSRF_HEADER] = session.json()["csrf_token"]
            files = agent.get(f"/projects/{FIRST}/files").json()["items"]
            address = f"/projects/{FIRST}/files/{files[0]['file_id']}"
            plan = agent.get(f"{address}/snapshot-plan")
            started = agent.post(f"{address}/snapshots", json={"note": "Od agenta"})
            events = _events(agent, started.json()["id"])
            job = agent.get(f"/jobs/{started.json()['id']}").json()
            card = agent.get(address).json()

    # Assert
    assert session.status_code == 200, session.text
    assert [item["path"] for item in files] == [folder.file("tif_2180").path]
    assert plan.status_code == 200 and plan.json()["blocked"] is None
    assert started.status_code == 202, started.text
    assert started.headers["location"] == f"/api/v1/jobs/{job['id']}"
    assert started.json()["kind"] == "snapshot"
    assert [data["phase"] for kind, data in events if kind == "progress"][-1] == (
        "published"
    )
    assert events[-1][0] == "state" and events[-1][1]["state"] == "succeeded"
    assert (job["state"], job["result"]["status"]) == ("succeeded", "created")
    assert [(item["label"], item["note"]) for item in card["snapshots"]] == [
        (job["result"]["label"], "Od agenta")
    ]
    assert card["last_snapshot"]["label"] == job["result"]["label"]


def test_agent_of_a_team_account_acts_with_its_roles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Team mode: a token names its account, its address is the team's origin."""
    # Arrange: a team server over TLS; kasia may write the stores, nothing more.
    monkeypatch.setattr(passwords, "HASHER", cheap_hasher())
    paths = local_paths(tmp_path)
    site = team_site(tmp_path / "tls")
    trust = ssl.create_default_context(cafile=site.tls.ca_file)
    with team_serving(paths, site):
        StateStore(paths.state_file).add_user(
            "kasia", roles=["store_writer"], actor=LOCAL_OWNER
        )
        capsys.readouterr()
        without_account = main(["token", "--json"], paths=paths)
        refused = capsys.readouterr().err
        assert main(["token", "--user", "kasia", "--json"], paths=paths) == 0
        issued = json.loads(capsys.readouterr().out)
        base = f"{site.origin}/api/v1"
        with httpx.Client(base_url=base, verify=trust, timeout=None) as agent:
            # Act
            session = agent.post("/session", json={"token": issued["token"]})
            agent.headers[CSRF_HEADER] = session.json()["csrf_token"]
            own = agent.get("/session")
            users = agent.get("/users")
            further = agent.post("/session/tokens")
        with httpx.Client(base_url=base, verify=trust, timeout=None) as anna:
            signed_in = anna.post(
                "/session/login",
                json={"account": ADMIN_ACCOUNT, "password": ADMIN_PASSWORD},
            )
            anna.headers[CSRF_HEADER] = signed_in.json()["csrf_token"]
            minted = anna.post("/session/tokens")

    # Assert
    assert without_account == 2
    assert json.loads(refused.splitlines()[-1])["details"]["reason"] == "user_required"
    assert issued["url"] == f"{site.origin}/#token={issued['token']}"
    assert session.status_code == 200, session.text
    assert (own.json()["actor"], own.json()["kind"], own.json()["method"]) == (
        "kasia",
        "agent",
        "token",
    )
    assert (own.json()["roles"], own.json()["store_write"]) == (["store_writer"], True)
    assert_problem(users, 403, "forbidden", "permission_denied")
    assert_problem(further, 403, "forbidden", "permission_denied")
    assert minted.status_code == 201, minted.text
    assert minted.json()["url"] == f"{site.origin}/#token={minted.json()['token']}"


def test_token_for_an_account_needs_an_enabled_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unknown account exits 3 (not_found), a disabled one or --revoke-all 2."""
    # Arrange
    paths = local_paths(tmp_path)
    state = StateStore(paths.state_file)
    state.add_user("ola", actor=LOCAL_OWNER)
    state.update_user("ola", disabled=True, actor=LOCAL_OWNER)

    # Act
    statuses = [
        main(argv, paths=paths)
        for argv in (
            ["token", "--user", "nikt"],
            ["token", "--user", "ola"],
            ["token", "--user", "ola", "--revoke-all"],
        )
    ]
    reasons = [
        json.loads(line)["details"].get("reason")
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{")
    ]

    # Assert
    assert statuses == [3, 2, 2]
    assert reasons == [None, "user_disabled", "user_with_revoke_all"]
