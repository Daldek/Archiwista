"""The application under a test client, with sessions acting as given principals."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi.testclient import TestClient

from archiwista.app import create_app
from archiwista.auth import Principal
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.index.schema import initialize
from archiwista.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    issue_one_time_token,
)
from archiwista.state import StateStore
from tests.fixtures.local_server import NoSources

PORT = 8090
BASE_URL = f"http://127.0.0.1:{PORT}"


@dataclass(frozen=True)
class Caller:
    """A session of one principal: its cookie and CSRF token."""

    client: TestClient
    session_id: str
    csrf: str

    def request(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        csrf: bool = True,
    ) -> httpx.Response:
        """Send ``method path`` under ``/api/v1`` with the session (and CSRF)."""
        headers = {
            "cookie": f"{SESSION_COOKIE}={self.session_id}; {CSRF_COOKIE}={self.csrf}"
        }
        if csrf:
            headers[CSRF_HEADER] = self.csrf
        response: httpx.Response = self.client.request(
            method, f"/api/v1{path}", json=json, headers=headers
        )
        return response


@dataclass(frozen=True)
class Api:
    """A running application over local data in a test directory."""

    client: TestClient
    paths: AppPaths
    state: StateStore

    def session(
        self, principal: Principal, *, token: Literal["startup", "agent"] = "startup"
    ) -> Caller:
        """Open a session from a one-time token ``principal`` minted.

        A ``startup`` token acts as the principal itself, an ``agent`` token
        as an agent acting for it.
        """
        issued = issue_one_time_token(self.paths.index_file, token, minted_by=principal)
        response = self.client.post("/api/v1/session", json={"token": issued.token})
        assert response.status_code == 200, response.text
        session_id = response.cookies[SESSION_COOKIE]
        csrf = str(response.json()["csrf_token"])
        self.client.cookies.clear()
        return Caller(self.client, session_id, csrf)


@contextmanager
def running_api(paths: AppPaths) -> Iterator[Api]:
    """Serve the application over ``paths`` (index and state database)."""
    initialize(paths.index_file)
    state = StateStore(paths.state_file)
    settings = SettingsService(ConfigStore(paths.config_file), NoSources())
    app = create_app(
        port=PORT, settings=settings, index_path=paths.index_file, state=state
    )
    with TestClient(app, base_url=BASE_URL) as client:
        yield Api(client, paths, state)


def assert_problem(response: httpx.Response, status: int, code: str) -> None:
    """Check an RFC 9457 problem with a Polish detail."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert (body["status"], body["code"]) == (status, code)
    assert body["detail"]
