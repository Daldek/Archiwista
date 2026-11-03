"""The language of a request's texts is its ``Accept-Language`` (AGI-6.4, AGI-9.2)."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

from archiwista.api import API_PREFIX, OPENAPI_PATH
from archiwista.api.language import LanguageMiddleware
from archiwista.messages import current_language, message

PROBLEM = "application/problem+json"


def _sync_route(request: Request) -> Response:
    """Answer the language of the request, from a route that is a function."""
    return JSONResponse({"language": current_language()})


async def _async_route(request: Request) -> Response:
    return JSONResponse({"language": current_language()})


def _problem(request: Request) -> Response:
    text = message("job.state_queued")
    return Response(f'{{"detail": "{text}"}}', media_type=PROBLEM)


def _own_language(request: Request) -> Response:
    """Name a language of its own, as a problem made outside the middleware does."""
    headers = {"Content-Language": "en", "Vary": "accept-language"}
    return JSONResponse({}, headers=headers)


def _image(request: Request) -> Response:
    return Response(b"\x89PNG", media_type="image/png")


def _stream(request: Request) -> Response:
    async def events() -> AsyncIterator[str]:
        yield f"event: state\ndata: {current_language()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@pytest.fixture
def client() -> TestClient:
    """Build an application of routes that tell the language they were called in."""
    app = Starlette(
        routes=[
            Route(f"{API_PREFIX}/sync", _sync_route),
            Route(f"{API_PREFIX}/async", _async_route),
            Route(f"{API_PREFIX}/problem", _problem),
            Route(f"{API_PREFIX}/own", _own_language),
            Route(f"{API_PREFIX}/image", _image),
            Route(f"{API_PREFIX}/events", _stream),
            Route(OPENAPI_PATH, _sync_route),
            Route("/interface.json", _sync_route),
        ]
    )
    app.add_middleware(LanguageMiddleware)
    return TestClient(app)


@pytest.mark.parametrize("route", ["sync", "async"])
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "en"),
        ("en-US,en;q=0.9", "en"),
        ("pl", "pl"),
        ("pl-PL,pl;q=0.9,en;q=0.8", "pl"),
        ("de", "en"),
    ],
)
def test_a_route_runs_in_the_language_of_the_request(
    client: TestClient, route: str, header: str | None, expected: str
) -> None:
    """The texts of a response model follow the request, in a thread or not."""
    headers = {} if header is None else {"Accept-Language": header}

    response = client.get(f"{API_PREFIX}/{route}", headers=headers)

    assert response.json() == {"language": expected}
    assert response.headers["content-language"] == expected
    assert response.headers["vary"] == "Accept-Language"


def test_a_request_does_not_keep_the_language_of_the_one_before(
    client: TestClient,
) -> None:
    """Polish for one request does not make the next one Polish."""
    polish = client.get(f"{API_PREFIX}/sync", headers={"Accept-Language": "pl"})
    english = client.get(f"{API_PREFIX}/sync")

    assert (polish.json(), english.json()) == (
        {"language": "pl"},
        {"language": "en"},
    )


def test_a_problem_and_an_event_stream_name_their_language(client: TestClient) -> None:
    """The answers that hold texts for a person say which language they are in."""
    headers = {"Accept-Language": "pl"}

    problem = client.get(f"{API_PREFIX}/problem", headers=headers)
    events = client.get(f"{API_PREFIX}/events", headers=headers)

    assert problem.json() == {"detail": "w kolejce"}
    assert events.text == "event: state\ndata: pl\n\n"
    for response in (problem, events):
        assert response.headers["content-language"] == "pl"
        assert response.headers["vary"] == "Accept-Language"


def test_an_answer_that_names_its_own_language_keeps_it(client: TestClient) -> None:
    """A problem knows its language better than the header does."""
    response = client.get(f"{API_PREFIX}/own", headers={"Accept-Language": "pl"})

    assert response.headers["content-language"] == "en"
    assert response.headers.get_list("vary") == ["accept-language"]


@pytest.mark.parametrize(
    "path", [f"{API_PREFIX}/image", OPENAPI_PATH, "/interface.json"]
)
def test_an_answer_without_texts_for_the_request_says_no_language(
    client: TestClient, path: str
) -> None:
    """Images, the OpenAPI document and the interface's files do not depend on it."""
    response = client.get(path, headers={"Accept-Language": "pl"})

    assert "content-language" not in response.headers
    assert "vary" not in response.headers


def test_a_scope_that_is_not_http_passes_unchanged() -> None:
    """A lifespan or a websocket is not a request: the application sees it as it is."""
    seen: list[tuple[str, str]] = []

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append((scope["type"], current_language()))

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        raise AssertionError(message)

    scope: Scope = {"type": "lifespan", "headers": [(b"accept-language", b"pl")]}
    asyncio.run(LanguageMiddleware(application)(scope, receive, send))

    assert seen == [("lifespan", "en")]
