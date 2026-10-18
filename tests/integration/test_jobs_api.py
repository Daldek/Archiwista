"""Background jobs over HTTP and their events as SSE (plan step 9b).

The application serves a generated Kartograf store with a real job
supervisor whose workers carry test hooks (``tests.fixtures.job_worker``):
jobs are started, listed and followed over HTTP as the interface and agents
do, offline. The test client buffers a response, so it reads a stream whole
once the job has ended; one test follows a stream on a real server.
"""

import json
import queue
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from archiwista.api import API_PREFIX
from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER
from archiwista.jobs import JobSupervisor
from archiwista.messages import MESSAGES
from archiwista.security import SESSION_COOKIE, issue_one_time_token
from archiwista.server import LocalServer, bind_loopback
from archiwista.state import StateStore
from tests.fixtures.api_session import assert_problem
from tests.fixtures.jobs import (
    DELAY_ENV,
    NO_NETWORK_ENV,
    SLOW_ENTRY_S,
    STORE,
    TEST_WORKER,
    jobs_env,
)
from tests.fixtures.jobs_api import JobsApi, jobs_api
from tests.fixtures.local_server import NoSources
from tests.fixtures.permissions import OTHER, add_people, principal

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

WAIT_S = 30.0

type Message = tuple[int, str, dict[str, Any]]


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[JobsApi]:
    """Serve a fresh store with a started supervisor of test workers."""
    with jobs_api(tmp_path, monkeypatch) as created:
        yield created


def _stream(served: JobsApi, job: str, last_event_id: str | None = None) -> Any:
    """Read a job's event stream (to its end) with the owner's session."""
    headers = {"cookie": f"{SESSION_COOKIE}={served.owner.session_id}"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = last_event_id
    return served.api.client.get(f"{API_PREFIX}/jobs/{job}/events", headers=headers)


def _messages(response: httpx.Response) -> list[Message]:
    """Parse an event stream into ``(id, event, data)`` messages."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    messages: list[Message] = []
    for block in response.text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line[:1] != ":"
        )
        if fields:
            data = json.loads(fields["data"])
            messages.append((int(fields["id"]), fields["event"], data))
    return messages


def test_scan_events_progress_notice_state(served: JobsApi, tmp_path: Path) -> None:
    """A scan started over HTTP streams numbered progress, notice and state events."""
    # Arrange: a project directory removed after it was configured gives the
    # scan a notice.
    gone = tmp_path / "projects-gone"
    gone.mkdir()
    settings = served.env.settings
    current = settings.get()
    dirs = (*current.project_dirs, gone)
    settings.update(current.model_copy(update={"project_dirs": dirs}))
    gone.rmdir()

    # Act
    started = served.owner.request(
        "POST", f"/stores/{STORE}/scan", json={"mode": "full"}
    )
    job = started.json()["id"]
    messages = _messages(_stream(served, job))
    detail = served.owner.request("GET", f"/jobs/{job}").json()

    # Assert
    assert started.status_code == 202, started.text
    assert started.headers["location"] == f"/api/v1/jobs/{job}"
    assert started.json()["params"] == {"mode": "full", "segment": None}
    assert [seq for seq, _, _ in messages] == list(range(1, len(messages) + 1))
    states = [data for _, event, data in messages if event == "state"]
    assert states == [
        {"state": "queued"},
        {"state": "running"},
        {"state": "succeeded", "result": detail["result"]},
    ]
    assert messages[-1][1] == "state"
    progress = [data for _, event, data in messages if event == "progress"]
    segments = len(detail["result"]["segments"])
    assert [item["current"] for item in progress] == list(range(segments + 1))
    assert progress[-1] == detail["progress"]
    notices = [data for _, event, data in messages if event == "notice"]
    assert [(n["level"], n["code"]) for n in notices] == [
        ("warning", "project_dir_unreadable")
    ]
    assert str(gone) in notices[0]["message"]
    assert detail["state"] == "succeeded" and detail["error"] is None


def test_second_scan_of_store_returns_409_with_job_id(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a scan writes the store's index, a scan or footprints job gets 409."""
    # Arrange
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    first = served.owner.request("POST", f"/stores/{STORE}/scan").json()

    # Act
    scan = served.owner.request("POST", f"/stores/{STORE}/scan", json={"mode": "full"})
    footprints = served.owner.request("POST", f"/stores/{STORE}/footprints")
    recorded = served.owner.request("GET", "/jobs").json()["items"]
    served.env.jobs.cancel(first["id"])
    served.env.wait(first["id"])

    # Assert
    assert first["params"] == {"mode": "incremental", "segment": None}
    for refused in (scan, footprints):
        assert_problem(refused, 409, "conflict")
        body = refused.json()
        assert body["job"] == {"id": first["id"], "kind": "scan", "state": "running"}
        assert first["id"] in body["detail"]
    assert [job["id"] for job in recorded] == [first["id"]]


def test_footprints_refused_offline(
    served: JobsApi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In offline mode unit outlines answer 409 offline_mode and record nothing."""
    # Arrange
    monkeypatch.setenv(NO_NETWORK_ENV, str(tmp_path / "connections.txt"))
    settings = served.env.settings
    online = settings.get()
    settings.update(online.model_copy(update={"offline": True}))

    # Act
    refused = served.owner.request("POST", f"/stores/{STORE}/footprints")
    listed = served.owner.request("GET", "/jobs?kind=footprints")
    settings.update(online)
    accepted = served.owner.request("POST", f"/stores/{STORE}/footprints")
    served.env.wait(accepted.json()["id"])

    # Assert
    assert_problem(refused, 409, "offline_mode")
    assert refused.json()["detail"] == MESSAGES["job_offline_mode"]
    assert listed.json() == {"items": [], "next_cursor": None}
    assert accepted.status_code == 202
    assert (accepted.json()["kind"], accepted.json()["params"]) == ("footprints", {})


def test_job_detail_has_actor(served: JobsApi) -> None:
    """A job keeps who started it: an account, also behind its agent's token."""
    # Arrange
    served.env.scan("full")
    add_people(served.api.state)
    person = principal(served.api.state, "other")
    link = served.env.store.by_kind("link")[0].path
    callers = {
        "person": served.api.session(person),
        "agent": served.api.session(person, token="agent"),
        "owner": served.owner,
    }

    # Act
    started = {
        who: caller.request(
            "POST", f"/stores/{STORE}/link-check", json={"slot": link}
        ).json()
        for who, caller in callers.items()
    }
    for job in started.values():
        served.env.wait(job["id"])
    details = {
        who: served.owner.request("GET", f"/jobs/{job['id']}").json()
        for who, job in started.items()
    }
    listed = served.owner.request("GET", "/jobs?kind=link_check").json()["items"]

    # Assert
    assert {who: detail["actor"] for who, detail in details.items()} == {
        "person": OTHER,
        "agent": OTHER,
        "owner": "local",
    }
    for detail in details.values():
        assert (detail["state"], detail["store"]) == ("succeeded", STORE)
        assert detail["params"] == {"slot": link}
        assert detail["result"]["status"] == "confirmed"
    assert {job["id"]: job["actor"] for job in listed} == {
        detail["id"]: detail["actor"] for detail in details.values()
    }


def test_sse_resume_from_last_event_id(served: JobsApi) -> None:
    """A stream resumes after Last-Event-ID from the kept events; at the end, 204."""
    # Arrange
    job = served.env.scan("full").id

    # Act
    whole = _messages(_stream(served, job))
    resumed = _messages(_stream(served, job, last_event_id="3"))
    ended = _stream(served, job, last_event_id=str(whole[-1][0]))
    invalid = _stream(served, job, last_event_id="trzy")
    unknown = _stream(served, "0123456789abcdef")

    # Assert
    assert len(whole) > 4 and whole[-1][2]["state"] == "succeeded"
    assert resumed == whole[3:]
    assert ended.status_code == 204 and ended.content == b""
    assert_problem(invalid, 422, "validation_error")
    assert_problem(unknown, 404, "not_found")


def test_sse_follows_job_of_another_supervisor(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job another supervisor runs (as ``archiwista reindex``) streams to its end."""
    # Arrange: the server's supervisor hears nothing of it; the index has all.
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    env = served.env
    with JobSupervisor(env.paths, env.settings, worker_command=TEST_WORKER) as other:
        job = other.submit("scan", store=STORE, actor="local")

        # Act
        messages = _messages(_stream(served, job.id))
        record = other.wait(job.id, timeout=WAIT_S)

    # Assert
    assert [seq for seq, _, _ in messages] == list(range(1, len(messages) + 1))
    assert [event for _, event, _ in messages].count("progress") > 1
    assert messages[-1][2] == {"state": "succeeded", "result": record.result}


def test_post_without_csrf_rejected(served: JobsApi) -> None:
    """Starting any job needs the session's CSRF token; nothing is recorded."""
    # Arrange
    link = served.env.store.by_kind("link")[0].path
    routes = [
        (f"/stores/{STORE}/scan", {"mode": "full"}),
        (f"/stores/{STORE}/footprints", None),
        (f"/stores/{STORE}/link-check", {"slot": link}),
    ]

    # Act
    refused = [
        served.owner.request("POST", path, json=body, csrf=False)
        for path, body in routes
    ]
    listed = served.owner.request("GET", "/jobs").json()

    # Assert
    for response in refused:
        assert_problem(response, 403, "csrf_rejected")
    assert listed["items"] == []


def test_link_check_of_unknown_slot_refused(served: JobsApi) -> None:
    """Only a slot the index knows is checked; any other path records no job."""
    # Act
    unknown = served.owner.request(
        "POST", f"/stores/{STORE}/link-check", json={"slot": "../../etc/passwd"}
    )
    store = served.owner.request(
        "POST", "/stores/nieznany/link-check", json={"slot": "nmt/x.asc"}
    )
    listed = served.owner.request("GET", "/jobs").json()

    # Assert
    assert_problem(unknown, 404, "not_found")
    assert "../../etc/passwd" in unknown.json()["detail"]
    assert_problem(store, 404, "not_found")
    assert listed["items"] == []


def test_job_list_filters_and_pages(served: JobsApi) -> None:
    """GET /jobs filters and pages newest first; another query's cursor is refused."""
    # Arrange
    scan = served.env.scan("full")
    links = [entry.path for entry in served.env.store.by_kind("link")[:2]]
    checks = [served.env.run("link_check", slot=link) for link in links]

    # Act
    first = served.owner.request("GET", "/jobs?kind=link_check&limit=1").json()
    cursor = first["next_cursor"]
    second = served.owner.request(
        "GET", f"/jobs?kind=link_check&limit=1&cursor={cursor}"
    ).json()
    scans = served.owner.request("GET", f"/jobs?store={STORE}&state=succeeded")
    foreign = served.owner.request("GET", f"/jobs?kind=scan&limit=1&cursor={cursor}")
    misspelt = served.owner.request("GET", "/jobs?kinds=scan")
    unknown_state = served.owner.request("GET", "/jobs?state=done")

    # Assert
    assert [job["id"] for job in first["items"] + second["items"]] == [
        checks[1].id,
        checks[0].id,
    ]
    assert second["next_cursor"] is None
    assert [job["id"] for job in scans.json()["items"]] == [
        checks[1].id,
        checks[0].id,
        scan.id,
    ]
    for refused in (foreign, misspelt, unknown_state):
        assert_problem(refused, 422, "validation_error")


def test_event_stream_ends_when_server_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stopping the server ends an open event stream at once; the job goes on."""
    # Arrange: a scan of about 16 s followed over a real connection.
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S * 4))
    lines: queue.Queue[str | None] = queue.Queue()
    with jobs_env(tmp_path, monkeypatch) as env:
        sock = bind_loopback(0)
        port = sock.getsockname()[1]
        app = create_app(
            port=port,
            settings=env.settings,
            index_path=env.paths.index_file,
            state=StateStore(env.paths.state_file),
            registry=NoSources(),
            areas_dir=env.paths.areas_dir,
            jobs=env.jobs,
        )
        server = LocalServer(
            sock, app, url="", access_log=False, on_stop=app.state.job_streams.close
        )
        serving = threading.Thread(target=server.run, daemon=True)
        serving.start()
        job = env.jobs.submit("scan", store=STORE, actor="local")
        token = issue_one_time_token(
            env.paths.index_file, "startup", minted_by=LOCAL_OWNER
        )
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}{API_PREFIX}", timeout=None
        )
        assert client.post("/session", json={"token": token.token}).status_code == 200

        def follow() -> None:
            with client.stream("GET", f"/jobs/{job.id}/events") as response:
                lines.put(str(response.status_code))
                for line in response.iter_lines():
                    lines.put(line)
            lines.put(None)

        follower = threading.Thread(target=follow, daemon=True)
        follower.start()
        opened = [lines.get(timeout=WAIT_S) for _ in range(4)]

        # Act
        server.stop()
        serving.join(timeout=WAIT_S / 3)
        follower.join(timeout=WAIT_S / 3)
        record = env.jobs.get(job.id)
        env.jobs.cancel(job.id)
        env.wait(job.id)
        client.close()

    # Assert
    assert opened == ["200", "id: 1", "event: state", 'data: {"state":"queued"}']
    assert not serving.is_alive() and not follower.is_alive()
    assert record is not None and record.state == "running"
