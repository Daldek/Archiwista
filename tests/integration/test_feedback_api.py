"""The feedback reports over HTTP: "Zgłoś uwagę" and the administrators' list.

``POST /feedback`` keeps a report of any session with Hydrograf's limits and
the account that sent it (none for the owner of a local installation);
``GET``, ``PATCH`` and ``DELETE /admin/feedback[/{id}]`` are an
administrator's. Each session comes from a one-time token minted by the
identity under test, as the server would see it.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.state import ActionQuery
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import OTHER, add_people, principal

DIAGNOSTICS: dict[str, Any] = {
    "events": [
        {
            "t": "2026-11-03T09:14:02.120Z",
            "type": "api_call",
            "data": {"method": "GET", "endpoint": "/api/v1/health", "status": 200},
        }
    ],
    "view": {"view": "catalog", "params": {"q": "N-34-130-D"}},
    "env": {"language": "pl-PL", "viewport": {"width": 1440, "height": 900}},
}
REPORT = {
    "message": "Katalog nie pokazuje arkuszy po wyszukaniu godła.",
    "contact": "igor@example.com",
    "page_url": "http://127.0.0.1:8090/?view=catalog",
    "diagnostics": DIAGNOSTICS,
}
# The most a report holds: Hydrograf's limits, the diagnostics as compact JSON.
LARGEST = {
    "message": "m" * 5000,
    "contact": "c" * 200,
    "page_url": "u" * 500,
    "diagnostics": {"note": "x" * (100_000 - len('{"note":""}'))},
}


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """Serve a state with the four people of the permission tests."""
    with running_api(local_paths(tmp_path)) as served:
        add_people(served.state)
        yield served


def _send(caller: Caller, body: dict[str, Any], *, agent: str = "Firefox/144.0") -> int:
    """Send a report as ``caller`` with a browser's ``User-Agent``; return its id."""
    response = caller.client.post(
        "/api/v1/feedback",
        json=body,
        headers={
            "cookie": f"{caller.cookie}={caller.session_id}",
            "X-Archiwista-CSRF": caller.csrf,
            "user-agent": agent,
        },
    )
    assert response.status_code == 201, response.text
    answer = response.json()
    assert answer["status"] == "ok"
    return int(answer["id"])


def test_feedback_api_keeps_a_report_of_every_kind_of_session(api: Api) -> None:
    """The owner, a person and the person's agent; newest first, all unread."""
    # Arrange
    owner = api.session(LOCAL_OWNER)
    igor = api.session(principal(api.state, "other"))
    agent = api.session(principal(api.state, "other"), token="agent")
    admin = api.session(principal(api.state, "admin"))

    # Act
    first = _send(owner, {"message": "  Mapa się nie wczytuje.  "})
    second = _send(igor, REPORT, agent="x" * 600)
    third = _send(agent, {**REPORT, "contact": "   "})
    listed = admin.request("GET", "/admin/feedback")

    # Assert
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert (page["total"], page["unread_count"]) == (3, 3)
    assert [item["id"] for item in page["items"]] == [third, second, first]
    newest, middle, oldest = page["items"]
    assert (oldest["user_id"], oldest["message"]) == (None, "Mapa się nie wczytuje.")
    assert (oldest["contact"], oldest["page_url"], oldest["diagnostics"]) == (
        None,
        None,
        None,
    )
    assert oldest["user_agent"] == "Firefox/144.0"
    assert {key: middle[key] for key in REPORT} == REPORT
    assert (middle["user_id"], middle["user_agent"]) == (OTHER, "x" * 500)
    assert (newest["user_id"], newest["contact"]) == (OTHER, None)
    assert not any(item["is_read"] for item in page["items"])


def test_feedback_api_keeps_a_report_at_every_limit(api: Api) -> None:
    """5,000 characters, a contact of 200, an address of 500, 100,000 of JSON."""
    # Arrange
    igor = api.session(principal(api.state, "other"))

    # Act
    kept = _send(igor, LARGEST)

    # Assert
    (item,) = api.state.feedback(limit=10).items
    assert item.id == kept
    assert (item.message, item.contact, item.page_url, item.diagnostics) == (
        LARGEST["message"],
        LARGEST["contact"],
        LARGEST["page_url"],
        LARGEST["diagnostics"],
    )


@pytest.mark.parametrize(
    "body, pointer",
    [
        ({}, "/body/message"),
        ({"message": ""}, "/body/message"),
        ({"message": " \n\t "}, "/body/message"),
        ({"message": "m" * 5001}, "/body/message"),
        ({"message": "ok", "contact": "c" * 201}, "/body/contact"),
        ({"message": "ok", "page_url": "u" * 501}, "/body/page_url"),
        (
            {"message": "ok", "diagnostics": {"note": "x" * 100_000}},
            "/body/diagnostics",
        ),
        ({"message": "ok", "diagnostics": ["a", "list"]}, "/body/diagnostics"),
        ({"message": "ok", "rating": 5}, "/body/rating"),
    ],
    ids=[
        "no message",
        "empty",
        "blank",
        "message over 5000",
        "contact over 200",
        "address over 500",
        "diagnostics over 100000",
        "diagnostics not an object",
        "unknown field",
    ],
)
def test_feedback_api_refuses_a_report_over_a_limit(
    api: Api, body: dict[str, Any], pointer: str
) -> None:
    """``400 validation_error`` naming the field; nothing is kept."""
    # Arrange
    igor = api.session(principal(api.state, "other"))

    # Act
    response = igor.request("POST", "/feedback", json=body, accept_language="pl")

    # Assert
    assert_problem(response, 400, "validation_error", "invalid_request")
    assert [error["pointer"] for error in response.json()["errors"]] == [pointer]
    assert api.state.feedback(limit=10).total == 0


def test_feedback_api_says_a_blank_report_is_empty_in_the_readers_language(
    api: Api,
) -> None:
    """The refusal of a blank description is the catalog's text, Polish for pl."""
    # Arrange
    igor = api.session(principal(api.state, "other"))

    # Act
    polish = igor.request(
        "POST", "/feedback", json={"message": "  "}, accept_language="pl"
    )
    english = igor.request("POST", "/feedback", json={"message": "  "})

    # Assert
    assert polish.json()["errors"][0]["message"].endswith("opis nie może być pusty")
    assert english.json()["errors"][0]["message"].endswith(
        "the description must not be empty"
    )


def test_feedback_api_refuses_a_caller_without_a_session_or_the_admin_role(
    api: Api,
) -> None:
    """No session: ``401``; without ``admin``: ``403``, logged; nothing changes."""
    # Arrange
    igor = api.session(principal(api.state, "other"))
    kept = _send(igor, REPORT)
    agent = api.session(principal(api.state, "other"), token="agent")
    routes = [
        ("GET", "/admin/feedback", None),
        ("PATCH", f"/admin/feedback/{kept}", {"is_read": True}),
        ("DELETE", f"/admin/feedback/{kept}", None),
    ]

    # Act
    anonymous = [
        api.client.request(method, f"/api/v1{path}", json=body)
        for method, path, body in [("POST", "/feedback", REPORT), *routes]
    ]
    refused = [
        caller.request(method, path, json=body)
        for caller in (igor, agent)
        for method, path, body in routes
    ]

    # Assert
    for response in anonymous:
        assert_problem(response, 401, "unauthorized", "session_required")
    for response in refused:
        assert_problem(response, 403, "forbidden", "permission_denied")
    denials = api.state.actions(ActionQuery(action="permission.denied")).entries
    assert {entry.details["action"] for entry in denials if entry.details} == {
        "feedback.manage"
    }
    (item,) = api.state.feedback(limit=10).items
    assert (item.id, item.is_read) == (kept, False)


def test_feedback_api_administrator_pages_marks_and_deletes(api: Api) -> None:
    """Pages by offset, read and unread counted, a deleted report ``404``."""
    # Arrange
    igor = api.session(principal(api.state, "other"))
    ids = [_send(igor, {"message": f"Uwaga {number}"}) for number in range(3)]
    admin = api.session(principal(api.state, "admin"))

    # Act
    first = admin.request("GET", "/admin/feedback?limit=2").json()
    rest = admin.request("GET", "/admin/feedback?limit=2&offset=2").json()
    read = admin.request("PATCH", f"/admin/feedback/{ids[1]}", json={"is_read": True})
    after_read = admin.request("GET", "/admin/feedback").json()
    unread = admin.request(
        "PATCH", f"/admin/feedback/{ids[1]}", json={"is_read": False}
    )
    deleted = admin.request("DELETE", f"/admin/feedback/{ids[0]}")
    after_delete = admin.request("GET", "/admin/feedback").json()
    gone = [
        admin.request("PATCH", f"/admin/feedback/{ids[0]}", json={"is_read": True}),
        admin.request("DELETE", f"/admin/feedback/{ids[0]}"),
        admin.request("DELETE", "/admin/feedback/999"),
    ]

    # Assert
    assert [item["id"] for item in first["items"]] == [ids[2], ids[1]]
    assert (first["total"], first["unread_count"]) == (3, 3)
    assert [item["id"] for item in rest["items"]] == [ids[0]]
    assert read.status_code == 200, read.text
    assert (read.json()["id"], read.json()["is_read"]) == (ids[1], True)
    assert after_read["unread_count"] == 2
    assert [item["is_read"] for item in after_read["items"]] == [False, True, False]
    assert unread.json()["is_read"] is False
    assert deleted.status_code == 204
    assert [item["id"] for item in after_delete["items"]] == [ids[2], ids[1]]
    assert (after_delete["total"], after_delete["unread_count"]) == (2, 2)
    for response in gone:
        assert_problem(response, 404, "not_found", "feedback_not_found")


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("PATCH", "/admin/feedback/1", {"is_read": "yes"}),
        ("PATCH", "/admin/feedback/1", {"is_read": 1}),
        ("PATCH", "/admin/feedback/1", {}),
        ("PATCH", "/admin/feedback/1", {"is_read": True, "note": "x"}),
        ("PATCH", "/admin/feedback/one", {"is_read": True}),
        ("GET", "/admin/feedback?limit=0", None),
        ("GET", "/admin/feedback?limit=201", None),
        ("GET", "/admin/feedback?offset=-1", None),
        ("GET", "/admin/feedback?page=2", None),
    ],
)
def test_feedback_api_refuses_invalid_requests_of_an_administrator(
    api: Api, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """``400 validation_error``: a read flag that is no boolean, a bad page."""
    # Arrange
    igor = api.session(principal(api.state, "other"))
    _send(igor, REPORT)
    admin = api.session(LOCAL_OWNER)

    # Act
    response = admin.request(method, path, json=body)

    # Assert
    assert_problem(response, 400, "validation_error", "invalid_request")
    assert api.state.feedback(limit=10).unread == 1
