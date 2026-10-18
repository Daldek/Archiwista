"""An AI agent over real HTTP, as the agent guide describes it (step 12).

The agent takes a one-time token from ``archiwista token --json``, opens a
session with a cookie jar and no ``Origin``, pages the catalog with cursors,
starts a scan with the CSRF header and follows it over SSE, and meets the
documented problems.
"""

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from archiwista.cli import main
from archiwista.config import ConfigStore
from archiwista.jobs.reindex import reindex_main
from archiwista.security import CSRF_HEADER
from archiwista.sources.registry import load_registry
from tests.fixtures.api_store import STORE, store_settings
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.make_store import make_store

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
            unchecked = agent.post(f"/stores/{STORE}/scan")
            scan = agent.post(
                f"/stores/{STORE}/scan",
                headers={CSRF_HEADER: session.json()["csrf_token"]},
            )
            events = _events(agent, scan.json()["id"])
            job = agent.get(f"/jobs/{scan.json()['id']}").json()
            no_plugin = agent.get("/slots", params={"bbox": KRAKOW})

    # Assert
    assert issued["url"] == f"http://127.0.0.1:{server.port}/#token={issued['token']}"
    assert session.status_code == 200 and session.json()["actor"] == "local"
    assert reused.status_code == 401 and reused.json()["code"] == "session_required"
    assert len(pages) > 1
    assert _rows([page["items"] for page in pages]) == _rows([whole.json()["items"]])
    assert foreign.status_code == 422 and foreign.json()["code"] == "validation_error"
    assert unchecked.status_code == 403
    assert unchecked.json()["code"] == "csrf_rejected"
    assert scan.status_code == 202, scan.text
    assert scan.headers["location"] == f"/api/v1/jobs/{scan.json()['id']}"
    assert scan.json()["actor"] == "local"
    assert events[-1][0] == "state" and events[-1][1]["state"] == job["state"]
    assert job["state"] == "succeeded" and job["error"] is None
    assert no_plugin.status_code == 503
    assert no_plugin.headers["content-type"] == "application/problem+json"
    assert no_plugin.json()["code"] == "source_unavailable"
    assert no_plugin.json()["source"]["id"] == "kartograf"
