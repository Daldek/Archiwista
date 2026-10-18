"""The API with a job supervisor of test workers over a generated store."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import BASE_URL, PORT, Api, Caller
from tests.fixtures.jobs import JobsEnv, jobs_env


@dataclass(frozen=True)
class JobsApi:
    """The application over a store with a started supervisor, and the owner."""

    env: JobsEnv
    api: Api
    owner: Caller


@contextmanager
def jobs_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **supervisor: Any
) -> Iterator[JobsApi]:
    """Serve the application with the supervisor of ``jobs_env`` (same settings)."""
    with jobs_env(tmp_path, monkeypatch, **supervisor) as env:
        state = StateStore(env.paths.state_file)
        app = create_app(
            port=PORT,
            settings=env.settings,
            index_path=env.paths.index_file,
            state=state,
            registry=load_registry(cache_dir=env.paths.cache_dir),
            jobs=env.jobs,
        )
        with TestClient(app, base_url=BASE_URL) as client:
            api = Api(client, env.paths, state)
            yield JobsApi(env, api, api.session(LOCAL_OWNER))
